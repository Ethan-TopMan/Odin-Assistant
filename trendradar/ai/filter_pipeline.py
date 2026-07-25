# coding=utf-8
"""
AI 筛选流水线

从 context.py 提取的完整 AI 筛选业务流程：
标签管理 → 待分类新闻收集 → 批量 AI 分类 → 结果保存 → 报告数据转换
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

from trendradar.ai.filter import AIFilter, AIFilterResult
from trendradar.utils.time import (
    DEFAULT_TIMEZONE,
    convert_time_for_display,
    format_iso_time_friendly,
    is_within_days,
)


class AIFilterPipeline:
    """AI 筛选流水线，编排标签提取、批量分类、结果存储的完整流程"""

    def __init__(
        self,
        config: Dict[str, Any],
        storage_manager: Any,
        get_time_func: Callable,
    ):
        self.config = config
        self.storage = storage_manager
        self.get_time = get_time_func

        self._ai_config = config.get("AI", {})
        self._filter_config = config.get("AI_FILTER", {})
        self._debug = config.get("DEBUG", False)

        rss_config = config.get("RSS", {})
        self._rss_enabled = rss_config.get("ENABLED", False)
        self._rss_feeds = rss_config.get("FEEDS", [])

        freshness_config = rss_config.get("FRESHNESS_FILTER", {})
        self._freshness_enabled = freshness_config.get("ENABLED", True)
        self._default_max_age_days = freshness_config.get("MAX_AGE_DAYS", 3)
        self._timezone = config.get("TIMEZONE", DEFAULT_TIMEZONE)

        self._priority_sort_enabled = config.get("FILTER", {}).get("PRIORITY_SORT_ENABLED", False)
        self._rank_threshold = config.get("RANK_THRESHOLD", 50)
        self._max_news = config.get("MAX_NEWS_PER_KEYWORD", 0)

        self._feed_max_age_map = self._build_feed_max_age_map()

        # 白名单源：这些源的 RSS 条目不受 AI 分数过滤，一律推送
        self._whitelist_feeds: List[str] = rss_config.get("WHITELIST_FEEDS", []) or []

        # 直接推送分类：按分类名批量绕过 AI 评分，直接进入聚合
        direct_push_cfg = rss_config.get("DIRECT_PUSH", {}) or {}
        self._direct_push_enabled = direct_push_cfg.get("ENABLED", False)
        raw_categories = direct_push_cfg.get("CATEGORIES", []) or []
        # category_name → max_age_days
        self._direct_push_categories: Dict[str, int] = {}
        for cat in raw_categories:
            name = cat.get("name", "")
            days = cat.get("max_age_days", self._default_max_age_days)
            if name:
                self._direct_push_categories[name] = int(days) if days is not None else self._default_max_age_days

    def _build_feed_max_age_map(self) -> Dict[str, int]:
        result = {}
        for feed_cfg in self._rss_feeds:
            feed_id = feed_cfg.get("id", "")
            max_age = feed_cfg.get("max_age_days")
            if max_age is not None:
                try:
                    result[feed_id] = int(max_age)
                except (ValueError, TypeError):
                    pass
        return result

    def run(self, interests_file: Optional[str] = None) -> Optional[AIFilterResult]:
        """
        执行 AI 智能筛选完整流程

        1. 读取兴趣描述文件，计算 hash
        2. 对比数据库 prompt_hash，决定是否重新提取标签
        3. 收集待分类新闻（去重）
        4. 按 batch_size 分组调用 AI 分类
        5. 保存结果
        6. 查询 active 结果，按标签分组返回
        """
        filter_config = self._filter_config

        ai_filter = AIFilter(self._ai_config, filter_config, self.get_time, self._debug)

        configured_interests = interests_file or filter_config.get("INTERESTS_FILE")
        effective_interests_file = configured_interests or "ai_interests.txt"

        if self._debug:
            print(f"[AI筛选][DEBUG] === 配置信息 ===")
            print(f"[AI筛选][DEBUG] 存储后端: {self.storage.backend_name}")
            print(f"[AI筛选][DEBUG] batch_size={filter_config.get('BATCH_SIZE', 200)}, "
                  f"batch_interval={filter_config.get('BATCH_INTERVAL', 5)}")
            print(f"[AI筛选][DEBUG] interests_file={effective_interests_file}")
            print(f"[AI筛选][DEBUG] prompt_file={filter_config.get('PROMPT_FILE', 'prompt.txt')}")
            print(f"[AI筛选][DEBUG] extract_prompt_file={filter_config.get('EXTRACT_PROMPT_FILE', 'extract_prompt.txt')}")

        # 1. 读取兴趣描述
        interests_content = ai_filter.load_interests_content(configured_interests)
        if not interests_content:
            return AIFilterResult(success=False, error="兴趣描述文件为空或不存在")

        current_hash = ai_filter.compute_interests_hash(interests_content, effective_interests_file)

        if self._debug:
            print(f"[AI筛选][DEBUG] 兴趣描述 hash: {current_hash}")
            print(f"[AI筛选][DEBUG] 兴趣描述内容 ({len(interests_content)} 字符):\n{interests_content}")

        # 2. 开启批量模式
        self.storage.begin_batch()

        # 3. 检查提示词是否变更
        stored_hash = self.storage.get_latest_prompt_hash(interests_file=effective_interests_file)

        if self._debug:
            print(f"[AI筛选][DEBUG] 数据库存储 hash: {stored_hash}")
            print(f"[AI筛选][DEBUG] hash 对比: stored={stored_hash} vs current={current_hash} → {'匹配' if stored_hash == current_hash else '不匹配'}")

        if stored_hash != current_hash:
            self._handle_tag_update(
                ai_filter, interests_content, current_hash, stored_hash,
                effective_interests_file, filter_config,
            )

        # 获取当前 active 标签
        active_tags = self.storage.get_active_ai_filter_tags(interests_file=effective_interests_file)
        if self._debug:
            print(f"[AI筛选][DEBUG] 从数据库获取 active 标签: {len(active_tags)} 个")
            for t in active_tags:
                print(f"[AI筛选][DEBUG]   id={t['id']} tag={t['tag']} priority={t.get('priority', 9999)} version={t.get('version')} hash={t.get('prompt_hash', '')[:8]}...")

        if not active_tags:
            self.storage.end_batch()
            return AIFilterResult(success=False, error="没有可用的标签")

        # 确保存在「其他资讯」标签（用于归类不匹配任何兴趣领域的新闻）
        if not any(t.get("tag", "") == "其他资讯" for t in active_tags):
            max_id = max((t.get("id", 0) for t in active_tags), default=0)
            max_priority = max((t.get("priority", 0) for t in active_tags), default=0)
            active_tags.append({
                "id": max_id + 1,
                "tag": "其他资讯",
                "description": "与用户关注领域不直接相关的一般资讯、娱乐、体育、生活等",
                "priority": max_priority + 1,
            })
            if self._debug:
                print(f"[AI筛选][DEBUG] 自动添加「其他资讯」标签 (id={max_id + 1})")

        print(f"[AI筛选] 使用 {len(active_tags)} 个标签")

        # 4. 收集待分类新闻
        pending_news, pending_rss, all_news, analyzed_hotlist, all_rss, analyzed_rss, freshness_filtered_rss = self._collect_pending_news(effective_interests_file)

        self._print_pending_stats(
            all_news, analyzed_hotlist, pending_news,
            all_rss, analyzed_rss, pending_rss, freshness_filtered_rss,
        )

        total_pending = len(pending_news) + len(pending_rss)
        if total_pending == 0:
            print("[AI筛选] 没有新增新闻需要分类")

        # 5. 批量分类
        total_results, succeeded_news_ids, succeeded_rss_ids = self._classify_batches(
            ai_filter, pending_news, pending_rss, active_tags, interests_content, filter_config,
        )

        # 6. 保存结果
        self._save_results(
            total_results, succeeded_news_ids, succeeded_rss_ids,
            effective_interests_file, current_hash,
        )

        # 7. 结束批量模式
        self.storage.end_batch()

        # 8. 查询并组装返回结果
        all_results = self.storage.get_active_ai_filter_results(interests_file=effective_interests_file)

        if self._debug:
            print(f"[AI筛选][DEBUG] === 最终汇总 ===")
            print(f"[AI筛选][DEBUG] 数据库 active 分类结果: {len(all_results)} 条")
            tag_counts: dict = {}
            for r in all_results:
                tag_name = r.get("tag", "?")
                src_type = r.get("source_type", "?")
                key = f"{tag_name}({src_type})"
                tag_counts[key] = tag_counts.get(key, 0) + 1
            for key, count in sorted(tag_counts.items()):
                print(f"[AI筛选][DEBUG]   {key}: {count} 条")

        return self._build_filter_result(all_results, active_tags, total_pending)

    def _handle_tag_update(
        self,
        ai_filter: AIFilter,
        interests_content: str,
        current_hash: str,
        stored_hash: Optional[str],
        effective_interests_file: str,
        filter_config: Dict,
    ) -> None:
        new_version = self.storage.get_latest_ai_filter_tag_version() + 1
        threshold = filter_config.get("RECLASSIFY_THRESHOLD", 0.6)

        if stored_hash is None:
            print(f"[AI筛选] 首次运行 ({effective_interests_file})，提取标签...")
            tags_data = ai_filter.extract_tags(interests_content)
            if not tags_data:
                self.storage.end_batch()
                raise _TagExtractionError()
            tags_data = _with_ordered_priorities(tags_data, start_priority=1)
            saved_count = self.storage.save_ai_filter_tags(tags_data, new_version, current_hash, interests_file=effective_interests_file)
            print(f"[AI筛选] 已保存 {saved_count} 个标签 (版本 {new_version})")
            return

        old_tags = self.storage.get_active_ai_filter_tags(interests_file=effective_interests_file)
        update_result = ai_filter.update_tags(old_tags, interests_content)

        if update_result is None:
            print(f"[AI筛选] AI 标签更新失败，回退到重新提取")
            tags_data = ai_filter.extract_tags(interests_content)
            if not tags_data:
                self.storage.end_batch()
                raise _TagExtractionError()
            tags_data = _with_ordered_priorities(tags_data, start_priority=1)
            deprecated_count = self.storage.deprecate_all_ai_filter_tags(interests_file=effective_interests_file)
            self.storage.clear_analyzed_news(interests_file=effective_interests_file)
            saved_count = self.storage.save_ai_filter_tags(tags_data, new_version, current_hash, interests_file=effective_interests_file)
            print(f"[AI筛选] 废弃 {deprecated_count} 个旧标签, 保存 {saved_count} 个新标签 (版本 {new_version})")
            return

        change_ratio = update_result["change_ratio"]
        keep_tags = update_result["keep"]
        add_tags = update_result["add"]
        remove_tags = update_result["remove"]

        if self._debug:
            print(f"[AI筛选][DEBUG] AI 标签更新: keep={len(keep_tags)}, add={len(add_tags)}, remove={len(remove_tags)}, change_ratio={change_ratio:.2f}, threshold={threshold:.2f}")

        if change_ratio >= threshold:
            print(f"[AI筛选] 兴趣文件变更: {effective_interests_file} (AI change_ratio={change_ratio:.2f} >= threshold={threshold:.2f} → 全量重分类)")
            tags_data = ai_filter.extract_tags(interests_content)
            if not tags_data:
                self.storage.end_batch()
                raise _TagExtractionError()
            tags_data = _with_ordered_priorities(tags_data, start_priority=1)
            deprecated_count = self.storage.deprecate_all_ai_filter_tags(interests_file=effective_interests_file)
            self.storage.clear_analyzed_news(interests_file=effective_interests_file)
            saved_count = self.storage.save_ai_filter_tags(tags_data, new_version, current_hash, interests_file=effective_interests_file)
            print(f"[AI筛选] 废弃 {deprecated_count} 个旧标签, 保存 {saved_count} 个新标签 (版本 {new_version})")
        else:
            self._apply_incremental_update(
                old_tags, keep_tags, add_tags, remove_tags,
                change_ratio, threshold, new_version, current_hash,
                effective_interests_file,
            )

    def _apply_incremental_update(
        self,
        old_tags, keep_tags, add_tags, remove_tags,
        change_ratio, threshold, new_version, current_hash,
        effective_interests_file,
    ) -> None:
        print(f"[AI筛选] 兴趣文件变更: {effective_interests_file} (AI change_ratio={change_ratio:.2f} < threshold={threshold:.2f} → 增量更新)")
        print(f"[AI筛选]   保留 {len(keep_tags)} 个标签, 新增 {len(add_tags)} 个, 废弃 {len(remove_tags)} 个")

        if remove_tags:
            remove_set = set(remove_tags)
            removed_ids = [t["id"] for t in old_tags if t["tag"] in remove_set]
            if removed_ids:
                self.storage.deprecate_specific_ai_filter_tags(removed_ids)
                if self._debug:
                    print(f"[AI筛选][DEBUG] 废弃标签 IDs: {removed_ids}")

        keep_with_priority = []
        if keep_tags:
            self.storage.update_ai_filter_tag_descriptions(keep_tags, interests_file=effective_interests_file)
            keep_with_priority = _with_ordered_priorities(keep_tags, start_priority=1)
            self.storage.update_ai_filter_tag_priorities(keep_with_priority, interests_file=effective_interests_file)

        if add_tags:
            add_start = keep_with_priority[-1]["priority"] + 1 if keep_with_priority else 1
            add_with_priority = _with_ordered_priorities(add_tags, start_priority=add_start)
            saved_count = self.storage.save_ai_filter_tags(add_with_priority, new_version, current_hash, interests_file=effective_interests_file)
            if self._debug:
                print(f"[AI筛选][DEBUG] 新增保存 {saved_count} 个标签")

        self.storage.update_ai_filter_tags_hash(effective_interests_file, current_hash)

        if add_tags:
            cleared = self.storage.clear_unmatched_analyzed_news(interests_file=effective_interests_file)
            if cleared > 0:
                print(f"[AI筛选]   清除 {cleared} 条不匹配记录，将在新标签下重新分析")

    def _collect_pending_news(self, effective_interests_file: str):
        all_news = self.storage.get_all_news_ids()
        analyzed_hotlist = self.storage.get_analyzed_news_ids("hotlist", interests_file=effective_interests_file)
        pending_news = [n for n in all_news if n["id"] not in analyzed_hotlist]

        pending_rss = []
        freshness_filtered_rss = 0
        all_rss = []
        analyzed_rss = set()

        if self._rss_enabled:
            all_rss = self.storage.get_all_rss_ids()

            fresh_rss = []
            for n in all_rss:
                published_at = n.get("published_at", "")
                feed_id = n.get("source_id", "")
                max_days = self._feed_max_age_map.get(feed_id, self._default_max_age_days)
                if self._freshness_enabled and max_days > 0 and published_at:
                    if not is_within_days(published_at, max_days, self._timezone):
                        freshness_filtered_rss += 1
                        continue
                fresh_rss.append(n)

            analyzed_rss = self.storage.get_analyzed_news_ids("rss", interests_file=effective_interests_file)
            pending_rss = [n for n in fresh_rss if n["id"] not in analyzed_rss]

            # RSS 每源每日上限：同一源超过 5 条时只保留最新的 5 条
            rss_per_feed_limit = self._filter_config.get("RSS_PER_FEED_LIMIT", 5)
            if rss_per_feed_limit > 0 and pending_rss:
                feed_groups: Dict[str, list] = {}
                for n in pending_rss:
                    fid = n.get("source_id", "")
                    feed_groups.setdefault(fid, []).append(n)
                limited_rss = []
                limited_count = 0
                for fid, items in feed_groups.items():
                    if len(items) > rss_per_feed_limit:
                        # items 按 id 升序排列，取最后 rss_per_feed_limit 条（最新）
                        kept = items[-rss_per_feed_limit:]
                        limited_rss.extend(kept)
                        limited_count += len(items) - rss_per_feed_limit
                    else:
                        limited_rss.extend(items)
                if limited_count > 0:
                    print(f"[AI筛选] RSS 每源上限 {rss_per_feed_limit} 条: 截断 {limited_count} 条")
                pending_rss = limited_rss

        return pending_news, pending_rss, all_news, analyzed_hotlist, all_rss, analyzed_rss, freshness_filtered_rss

    def _print_pending_stats(self, all_news, analyzed_hotlist, pending_news, all_rss, analyzed_rss, pending_rss, freshness_filtered_rss):
        hotlist_total = len(all_news)
        hotlist_skipped = len(analyzed_hotlist)
        hotlist_pending = len(pending_news)
        print(f"[AI筛选] 热榜: 总计 {hotlist_total} 条, 已分析跳过 {hotlist_skipped} 条, 本次发送AI分析 {hotlist_pending} 条")
        if self._rss_enabled:
            rss_total = len(all_rss)
            rss_skipped = len(analyzed_rss)
            rss_pending = len(pending_rss)
            freshness_info = f", 新鲜度过滤 {freshness_filtered_rss} 条" if freshness_filtered_rss > 0 else ""
            print(f"[AI筛选] RSS: 总计 {rss_total} 条{freshness_info}, 已分析跳过 {rss_skipped} 条, 本次发送AI分析 {rss_pending} 条")

    def _classify_batches(self, ai_filter, pending_news, pending_rss, active_tags, interests_content, filter_config):
        batch_size = filter_config.get("BATCH_SIZE", 200)
        batch_interval = filter_config.get("BATCH_INTERVAL", 5)
        total_results = []
        batch_count = 0

        succeeded_news_ids = []
        for i in range(0, len(pending_news), batch_size):
            if batch_count > 0 and batch_interval > 0:
                import time
                print(f"[AI筛选] 批次间隔等待 {batch_interval} 秒...")
                time.sleep(batch_interval)
            batch = pending_news[i:i + batch_size]
            titles_for_ai = [
                {"id": n["id"], "title": n["title"], "source": n.get("source_name", "")}
                for n in batch
            ]
            batch_results = ai_filter.classify_batch(titles_for_ai, active_tags, interests_content)
            batch_count += 1
            if batch_results is None:
                print(f"[AI筛选] 热榜批次 {i // batch_size + 1}: {len(batch)} 条 → 分类失败，将在下次运行重试")
                continue
            for r in batch_results:
                r["source_type"] = "hotlist"
            total_results.extend(batch_results)
            succeeded_news_ids.extend(n["id"] for n in batch)
            print(f"[AI筛选] 热榜批次 {i // batch_size + 1}: {len(batch)} 条 → {len(batch_results)} 条匹配")

        succeeded_rss_ids = []
        for i in range(0, len(pending_rss), batch_size):
            if batch_count > 0 and batch_interval > 0:
                import time
                print(f"[AI筛选] 批次间隔等待 {batch_interval} 秒...")
                time.sleep(batch_interval)
            batch = pending_rss[i:i + batch_size]
            titles_for_ai = [
                {"id": n["id"], "title": n["title"], "source": n.get("source_name", "")}
                for n in batch
            ]
            batch_results = ai_filter.classify_batch(titles_for_ai, active_tags, interests_content)
            batch_count += 1
            if batch_results is None:
                print(f"[AI筛选] RSS 批次 {i // batch_size + 1}: {len(batch)} 条 → 分类失败，将在下次运行重试")
                continue
            for r in batch_results:
                r["source_type"] = "rss"
            total_results.extend(batch_results)
            succeeded_rss_ids.extend(n["id"] for n in batch)
            print(f"[AI筛选] RSS 批次 {i // batch_size + 1}: {len(batch)} 条 → {len(batch_results)} 条匹配")

        return total_results, succeeded_news_ids, succeeded_rss_ids

    def _save_results(self, total_results, succeeded_news_ids, succeeded_rss_ids, effective_interests_file, current_hash):
        if total_results:
            saved = self.storage.save_ai_filter_results(total_results)
            print(f"[AI筛选] 保存 {saved} 条分类结果")
            if self._debug and saved != len(total_results):
                print(f"[AI筛选][DEBUG] !! 保存数量不一致: 期望 {len(total_results)}, 实际 {saved}（可能有重复记录被跳过）")

        matched_hotlist_ids = {r["news_item_id"] for r in total_results if r.get("source_type") == "hotlist"}
        matched_rss_ids = {r["news_item_id"] for r in total_results if r.get("source_type") == "rss"}

        if succeeded_news_ids:
            self.storage.save_analyzed_news(
                succeeded_news_ids, "hotlist", effective_interests_file,
                current_hash, matched_hotlist_ids
            )

        if succeeded_rss_ids:
            self.storage.save_analyzed_news(
                succeeded_rss_ids, "rss", effective_interests_file,
                current_hash, matched_rss_ids
            )

        if succeeded_news_ids or succeeded_rss_ids:
            total_analyzed = len(succeeded_news_ids) + len(succeeded_rss_ids)
            total_matched = len(matched_hotlist_ids) + len(matched_rss_ids)
            print(f"[AI筛选] 已记录 {total_analyzed} 条新闻分析状态 (匹配 {total_matched}, 不匹配 {total_analyzed - total_matched})")

    def _build_filter_result(
        self,
        raw_results: List[Dict],
        tags: List[Dict],
        total_processed: int,
    ) -> AIFilterResult:
        tag_priority_map = {}
        for idx, t in enumerate(tags, start=1):
            tag_name = str(t.get("tag", "")).strip() if isinstance(t, dict) else ""
            if not tag_name:
                continue
            try:
                tag_priority_map[tag_name] = int(t.get("priority", idx))
            except (TypeError, ValueError):
                tag_priority_map[tag_name] = idx

        tag_groups: Dict[str, Dict] = {}
        seen_titles: Dict[str, set] = {}

        for r in raw_results:
            tag_name = r["tag"]
            if tag_name not in tag_groups:
                raw_priority = r.get("tag_priority", tag_priority_map.get(tag_name, 9999))
                try:
                    tag_position = int(raw_priority)
                except (TypeError, ValueError):
                    tag_position = 9999
                tag_groups[tag_name] = {
                    "tag": tag_name,
                    "description": r.get("tag_description", ""),
                    "position": tag_position,
                    "count": 0,
                    "items": [],
                }
                seen_titles[tag_name] = set()

            title = r["title"]
            if title in seen_titles[tag_name]:
                continue
            seen_titles[tag_name].add(title)

            tag_groups[tag_name]["items"].append({
                "title": title,
                "source_id": r.get("source_id", ""),
                "source_name": r.get("source_name", ""),
                "url": r.get("url", ""),
                "mobile_url": r.get("mobile_url", ""),
                "rank": r.get("rank", 0),
                "ranks": r.get("ranks", []),
                "first_time": r.get("first_time", ""),
                "last_time": r.get("last_time", ""),
                "count": r.get("count", 1),
                "relevance_score": r.get("relevance_score", 0),
                "source_type": r.get("source_type", "hotlist"),
            })
            tag_groups[tag_name]["count"] += 1

        if self._priority_sort_enabled:
            sorted_tags = sorted(
                tag_groups.values(),
                key=lambda x: (x.get("position", 9999), -x["count"], x["tag"]),
            )
        else:
            sorted_tags = sorted(
                tag_groups.values(),
                key=lambda x: (-x["count"], x.get("position", 9999), x["tag"]),
            )

        total_matched = sum(t["count"] for t in sorted_tags)

        return AIFilterResult(
            tags=sorted_tags,
            total_matched=total_matched,
            total_processed=total_processed,
            success=True,
        )

    def convert_to_report_data(
        self,
        ai_filter_result: AIFilterResult,
        mode: str = "daily",
        new_titles: Optional[Dict] = None,
        rss_new_urls: Optional[set] = None,
        feed_category_map: Optional[Dict[str, str]] = None,
    ) -> tuple:
        """
        将 AI 筛选结果转换为与关键词匹配相同的数据结构

        Returns:
            (hotlist_stats, rss_stats, rss_new_stats)
        """
        hotlist_stats = []
        rss_stats = []
        rss_new_stats = []
        min_score = self._filter_config.get("MIN_SCORE", 0)

        latest_time = None
        if mode == "current":
            for tag_data in ai_filter_result.tags:
                for item in tag_data.get("items", []):
                    if item.get("source_type", "hotlist") == "hotlist":
                        last_time = item.get("last_time", "")
                        if last_time and (latest_time is None or last_time > latest_time):
                            latest_time = last_time
            if latest_time:
                print(f"[AI筛选] current 模式：最新时间 {latest_time}，过滤已下榜新闻")

        filtered_count = 0
        for tag_data in ai_filter_result.tags:
            tag_name = tag_data.get("tag", "")
            items = tag_data.get("items", [])
            if not items:
                continue

            hotlist_titles = []
            rss_titles = []

            for item in items:
                source_type = item.get("source_type", "hotlist")

                if mode == "current" and latest_time and source_type == "hotlist":
                    if item.get("last_time", "") != latest_time:
                        filtered_count += 1
                        continue

                if min_score > 0 and source_type == "hotlist":
                    score = item.get("relevance_score", 0)
                    if score < min_score:
                        continue
                # RSS 条目不受 min_score 限制，全量展示

                first_time = item.get("first_time", "")
                last_time = item.get("last_time", "")
                if source_type == "rss":
                    if self._freshness_enabled and first_time:
                        feed_id = item.get("source_id", "")
                        max_days = self._feed_max_age_map.get(feed_id, self._default_max_age_days)
                        if max_days > 0 and not is_within_days(first_time, max_days, self._timezone):
                            continue
                    time_display = format_iso_time_friendly(first_time, self._timezone, include_date=True) if first_time else ""
                else:
                    if first_time and last_time and first_time != last_time:
                        first_display = convert_time_for_display(first_time)
                        last_display = convert_time_for_display(last_time)
                        time_display = f"[{first_display} ~ {last_display}]"
                    elif first_time:
                        time_display = convert_time_for_display(first_time)
                    else:
                        time_display = ""

                if source_type == "rss":
                    is_new = False
                    if rss_new_urls:
                        item_url = item.get("url", "")
                        is_new = item_url in rss_new_urls if item_url else False
                else:
                    is_new = False
                    if new_titles:
                        item_source_id = item.get("source_id", "")
                        item_title = item.get("title", "")
                        if item_source_id in new_titles:
                            is_new = item_title in new_titles[item_source_id]

                if mode == "incremental" and not is_new:
                    continue

                title_entry = {
                    "title": item.get("title", ""),
                    "source_name": item.get("source_name", ""),
                    "url": item.get("url", ""),
                    "mobile_url": item.get("mobile_url", ""),
                    "ranks": item.get("ranks", []),
                    "rank_threshold": self._rank_threshold,
                    "count": item.get("count", 1),
                    "is_new": is_new,
                    "time_display": time_display,
                    "matched_keyword": tag_name,
                }

                if source_type == "rss":
                    rss_titles.append(title_entry)
                else:
                    hotlist_titles.append(title_entry)

            if hotlist_titles:
                if self._max_news > 0:
                    hotlist_titles = hotlist_titles[:self._max_news]
                hotlist_stats.append({
                    "word": tag_name,
                    "count": len(hotlist_titles),
                    "position": tag_data.get("position", 9999),
                    "titles": hotlist_titles,
                })

            if rss_titles:
                if self._max_news > 0:
                    rss_titles = rss_titles[:self._max_news]
                rss_stats.append({
                    "word": tag_name,
                    "count": len(rss_titles),
                    "position": tag_data.get("position", 9999),
                    "titles": rss_titles,
                })
                new_rss_titles = [t for t in rss_titles if t.get("is_new")]
                if new_rss_titles:
                    rss_new_stats.append({
                        "word": tag_name,
                        "count": len(new_rss_titles),
                        "position": tag_data.get("position", 9999),
                        "titles": new_rss_titles,
                    })

        if mode == "current" and filtered_count > 0:
            total_kept = sum(s["count"] for s in hotlist_stats)
            print(f"[AI筛选] current 模式：过滤 {filtered_count} 条已下榜新闻，保留 {total_kept} 条当前在榜")

        if min_score > 0:
            hotlist_kept = sum(s["count"] for s in hotlist_stats)
            rss_kept = sum(s["count"] for s in rss_stats)
            total_kept = hotlist_kept + rss_kept
            parts = [f"热榜 {hotlist_kept} 条"]
            if rss_kept > 0:
                parts.append(f"RSS {rss_kept} 条")
            print(f"[AI筛选] 分数过滤：min_score={min_score}，保留 {total_kept} 条 score≥{min_score} ({', '.join(parts)})")

        # ── 白名单源：无条件追加（不受 AI 分数/过滤影响） ──
        if self._whitelist_feeds:
            whitelist_stats, whitelist_new = self._get_whitelist_rss_items(mode, rss_new_urls)
            if whitelist_stats:
                print(f"[AI筛选] 白名单源追加 {sum(s['count'] for s in whitelist_stats)} 条 (不受 min_score 过滤)")
                # 合并到 rss_stats，同名 word 合并
                whitelist_word_map = {s["word"]: s for s in whitelist_stats}
                for existing in list(rss_stats):
                    w = existing["word"]
                    if w in whitelist_word_map:
                        wl = whitelist_word_map.pop(w)
                        existing["titles"].extend(wl["titles"])
                        existing["count"] = len(existing["titles"])
                rss_stats.extend(whitelist_word_map.values())

            if whitelist_new:
                whitelist_new_map = {s["word"]: s for s in whitelist_new}
                for existing in list(rss_new_stats):
                    w = existing["word"]
                    if w in whitelist_new_map:
                        wl = whitelist_new_map.pop(w)
                        existing["titles"].extend(wl["titles"])
                        existing["count"] = len(existing["titles"])
                rss_new_stats.extend(whitelist_new_map.values())

        # ── 直接推送分类：按分类名批量绕过 AI 评分，直接进入聚合 ──
        if self._direct_push_enabled and self._direct_push_categories and feed_category_map:
            dp_stats, dp_new = self._get_direct_push_rss_items(mode, rss_new_urls, feed_category_map)
            if dp_stats:
                total_dp = sum(s['count'] for s in dp_stats)
                print(f"[AI筛选] 直接推送分类追加 {len(dp_stats)} 个组, 共 {total_dp} 条 (绕过 AI 评分)")
                # 合并到 rss_stats，同名 word 合并
                dp_word_map = {s["word"]: s for s in dp_stats}
                for existing in list(rss_stats):
                    w = existing["word"]
                    if w in dp_word_map:
                        dp = dp_word_map.pop(w)
                        existing["titles"].extend(dp["titles"])
                        existing["count"] = len(existing["titles"])
                rss_stats.extend(dp_word_map.values())
            if dp_new:
                dp_new_map = {s["word"]: s for s in dp_new}
                for existing in list(rss_new_stats):
                    w = existing["word"]
                    if w in dp_new_map:
                        dp = dp_new_map.pop(w)
                        existing["titles"].extend(dp["titles"])
                        existing["count"] = len(existing["titles"])
                rss_new_stats.extend(dp_new_map.values())

        sort_key_priority = lambda x: (x.get("position", 9999), -x["count"], x["word"])
        sort_key_count = lambda x: (-x["count"], x.get("position", 9999), x["word"])
        sort_key = sort_key_priority if self._priority_sort_enabled else sort_key_count
        hotlist_stats.sort(key=sort_key)
        rss_stats.sort(key=sort_key)
        rss_new_stats.sort(key=sort_key)

        return hotlist_stats, rss_stats, rss_new_stats

    def _get_whitelist_rss_items(self, mode: str = "daily", rss_new_urls: Optional[set] = None) -> Tuple[List[Dict], List[Dict]]:
        """
        获取白名单源的最新 RSS 条目（不受 AI 分数过滤，24h 内的一律返回）

        Returns:
            (whitelist_stats, whitelist_new_stats) — 与 rss_stats/rss_new_stats 格式一致
        """
        if not self._whitelist_feeds:
            return [], []

        try:
            rss_data = self.storage.get_rss_data()
        except Exception as e:
            print(f"[AI筛选] 白名单: 获取 RSS 数据失败: {e}")
            return [], []

        if not rss_data or not rss_data.items:
            return [], []

        whitelist_set = set(self._whitelist_feeds)
        stats: List[Dict] = []
        new_stats: List[Dict] = []

        for feed_id, items in rss_data.items.items():
            if feed_id not in whitelist_set:
                continue

            feed_name = rss_data.id_to_name.get(feed_id, feed_id)
            # 用 feed 名作为分组 word，带 🔥 标识
            group_word = f"🔥 {feed_name}"

            titles = []
            new_titles = []

            for item in items:
                # 新鲜度过滤
                if self._freshness_enabled and item.published_at:
                    max_days = self._feed_max_age_map.get(feed_id, self._default_max_age_days)
                    if max_days > 0 and not is_within_days(item.published_at, max_days, self._timezone):
                        continue

                published_at = item.published_at or ""
                time_display = format_iso_time_friendly(published_at, self._timezone, include_date=True) if published_at else ""

                is_new = False
                if rss_new_urls and item.url:
                    is_new = item.url in rss_new_urls

                if mode == "incremental" and not is_new:
                    continue

                title_entry = {
                    "title": item.title,
                    "source_name": feed_name,
                    "url": item.url or "",
                    "mobile_url": "",
                    "ranks": [],
                    "rank_threshold": self._rank_threshold,
                    "count": 1,
                    "is_new": is_new,
                    "time_display": time_display,
                    "matched_keyword": group_word,
                }
                titles.append(title_entry)
                if is_new:
                    new_titles.append(title_entry)

            if titles:
                stats.append({
                    "word": group_word,
                    "count": len(titles),
                    "position": 9998,  # 白名单排在 AI 分类结果之后
                    "titles": titles,
                })
            if new_titles:
                new_stats.append({
                    "word": group_word,
                    "count": len(new_titles),
                    "position": 9998,
                    "titles": new_titles,
                })

        if stats:
            total = sum(s["count"] for s in stats)
            print(f"[AI筛选] 白名单源 {len(stats)} 个组, 共 {total} 条 (新鲜度 ≤{self._default_max_age_days}天)")

        return stats, new_stats

    def _get_direct_push_rss_items(
        self,
        mode: str = "daily",
        rss_new_urls: Optional[set] = None,
        feed_category_map: Optional[Dict[str, str]] = None,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        获取直接推送分类（如个人博客、新闻类博客）的 RSS 条目。
        这些条目绕过 AI 评分过滤，按分类各自的新鲜度阈值进行过滤，
        直接进入后续的 AI 聚合摘要流程。

        Returns:
            (dp_stats, dp_new_stats) — 与 rss_stats/rss_new_stats 格式一致
        """
        if not self._direct_push_enabled or not self._direct_push_categories or not feed_category_map:
            return [], []

        try:
            rss_data = self.storage.get_rss_data()
        except Exception as e:
            print(f"[AI筛选] 直接推送: 获取 RSS 数据失败: {e}")
            return [], []

        if not rss_data or not rss_data.items:
            return [], []

        # 构建 feed_id → 板块名的反向映射（使用原始分类名）
        # 注意：feed_category_map 里存的是原始分类名（如 HPC, AI, News, 个人博客, 新闻类博客）
        feed_to_raw_cat = feed_category_map

        # 收集所有需要直接推送的 feed_id
        direct_push_cat_set = set(self._direct_push_categories.keys())
        dp_feed_ids = {
            feed_id for feed_id, raw_cat in feed_to_raw_cat.items()
            if raw_cat in direct_push_cat_set
        }

        if not dp_feed_ids:
            return [], []

        # 分类名 → 展示名 映射
        from trendradar.core.analyzer import RSS_CATEGORY_DISPLAY_NAMES

        # 按分类分组统计
        cat_buckets: Dict[str, list] = {}  # display_cat → [title_entry, ...]
        cat_new_buckets: Dict[str, list] = {}
        cat_used_days: Dict[str, int] = {}

        for feed_id, items in rss_data.items.items():
            if feed_id not in dp_feed_ids:
                continue

            raw_cat = feed_to_raw_cat.get(feed_id, "")
            if raw_cat not in direct_push_cat_set:
                continue

            display_cat = RSS_CATEGORY_DISPLAY_NAMES.get(raw_cat, raw_cat)
            max_days = self._direct_push_categories.get(raw_cat, self._default_max_age_days)
            cat_used_days[raw_cat] = max_days
            feed_name = rss_data.id_to_name.get(feed_id, feed_id)
            group_word = f"📌 {display_cat}"

            cat_buckets.setdefault(group_word, [])
            cat_new_buckets.setdefault(group_word, [])

            for item in items:
                # 按分类自己的新鲜度阈值过滤
                if self._freshness_enabled and item.published_at:
                    if max_days > 0 and not is_within_days(item.published_at, max_days, self._timezone):
                        continue

                published_at = item.published_at or ""
                time_display = format_iso_time_friendly(published_at, self._timezone, include_date=True) if published_at else ""

                is_new = False
                if rss_new_urls and item.url:
                    is_new = item.url in rss_new_urls

                if mode == "incremental" and not is_new:
                    continue

                title_entry = {
                    "title": item.title,
                    "source_name": feed_name,
                    "url": item.url or "",
                    "mobile_url": "",
                    "ranks": [],
                    "rank_threshold": self._rank_threshold,
                    "count": 1,
                    "is_new": is_new,
                    "time_display": time_display,
                    "matched_keyword": group_word,
                }
                cat_buckets[group_word].append(title_entry)
                if is_new:
                    cat_new_buckets[group_word].append(title_entry)

        stats: List[Dict] = []
        new_stats: List[Dict] = []
        for group_word, titles in cat_buckets.items():
            if titles:
                stats.append({
                    "word": group_word,
                    "count": len(titles),
                    "position": 9996,  # 排在白名单之前
                    "titles": titles,
                })
        for group_word, titles in cat_new_buckets.items():
            if titles:
                new_stats.append({
                    "word": group_word,
                    "count": len(titles),
                    "position": 9996,
                    "titles": titles,
                })

        if stats:
            days_info = ", ".join(f"{k}={v}天" for k, v in sorted(cat_used_days.items()))
            total = sum(s["count"] for s in stats)
            print(f"[AI筛选] 直接推送分类 {len(stats)} 个组, 共 {total} 条 ({days_info})")

        return stats, new_stats


class _TagExtractionError(Exception):
    pass


def _with_ordered_priorities(tags: List[Dict], start_priority: int = 1) -> List[Dict]:
    normalized: List[Dict] = []
    priority = start_priority
    for tag_data in tags:
        if not isinstance(tag_data, dict):
            continue
        tag_name = str(tag_data.get("tag", "")).strip()
        if not tag_name:
            continue
        item = dict(tag_data)
        item["tag"] = tag_name
        item["priority"] = priority
        normalized.append(item)
        priority += 1
    return normalized

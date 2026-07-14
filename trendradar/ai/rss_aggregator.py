# coding=utf-8
"""
RSS & 热榜 AI 聚合摘要模块

- RSSAggregator: 对白名单 RSS 条目按 OPML 分类进行 AI 去重、聚合、摘要
- HotlistAggregator: 对热榜新闻按标签分组进行 AI 去重、聚合、摘要
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from trendradar.ai.client import AIClient
from trendradar.core.analyzer import RSS_CATEGORY_DISPLAY_NAMES


@dataclass
class AggregatedCategory:
    """单个分类的聚合结果"""
    category: str                              # 展示名（如 "🤖 AI 与科技前沿"）
    summary: str = ""                          # AI 生成的分类摘要
    items: List[Dict] = field(default_factory=list)  # 去重后的条目列表
    total_before_dedup: int = 0                # 去重前条数
    total_after_dedup: int = 0                 # 去重后条数


@dataclass
class RSSAggregateResult:
    """RSS 聚合摘要结果"""
    categories: List[AggregatedCategory] = field(default_factory=list)
    total_before: int = 0
    total_after: int = 0
    success: bool = False
    error: str = ""


# 聚合提示词模板（不依赖外部文件，内嵌以降低复杂度）
AGGREGATE_SYSTEM_PROMPT = """你是一个 RSS 资讯聚合助手。你的任务是对同一分类下的 RSS 文章标题进行智能处理：

1. 去重合并：识别内容相似或报道同一事件的多篇文章，合并为一条（保留最完整的标题）
2. 分类总结：用 1-2 句话概括这个分类今天的主要内容方向
3. 去重后的文章按相关性从高到低排列

返回严格的 JSON 格式（不要添加任何额外内容）：
{"summary": "分类概括文本", "items": [{"title": "去重后的标题", "source": "来源名称"}, ...]}

注意：
- items 数组中的标题是去重合并后的结果，相似的文章只保留一条
- 每条 item 的 title 为最终展示标题（可选择合并后最完整的那条）
- source 为来源名称
- 如果某分类没有内容，返回空 items
"""


class RSSAggregator:
    """RSS 聚合摘要器"""

    def __init__(self, ai_config: Dict[str, Any], debug: bool = False):
        self.client = AIClient(ai_config)
        self.debug = debug
        self.batch_interval = 1  # 分类间等待秒数，避免限流

    def aggregate(
        self,
        rss_items: List[Dict],
        feed_category_map: Dict[str, str],
    ) -> RSSAggregateResult:
        """
        对 RSS 条目按分类进行 AI 去重聚合摘要

        Args:
            rss_items: RSS 条目列表（含 feed_id, title, source_name, url, published_at 等）
            feed_category_map: feed_id → OPML 分类名 的映射

        Returns:
            RSSAggregateResult: 聚合结果
        """
        if not rss_items:
            return RSSAggregateResult(success=True, error="无 RSS 条目")

        # 1. 按 feed_id 映射到 OPML 分类（raw category）
        feed_to_raw_cat: Dict[str, str] = feed_category_map

        # 2. 按展示分类分组
        category_buckets: Dict[str, List[Dict]] = {}
        for item in rss_items:
            feed_id = item.get("feed_id", "")
            raw_cat = feed_to_raw_cat.get(feed_id, "未分类")
            display_cat = RSS_CATEGORY_DISPLAY_NAMES.get(raw_cat, raw_cat)
            category_buckets.setdefault(display_cat, []).append(item)

        total_before = len(rss_items)
        category_results: List[AggregatedCategory] = []

        print(f"[RSS聚合] 共 {total_before} 条，按 {len(category_buckets)} 个分类处理")

        for idx, (cat_name, items) in enumerate(category_buckets.items()):
            if idx > 0 and self.batch_interval > 0:
                time.sleep(self.batch_interval)

            print(f"[RSS聚合] 处理分类 [{cat_name}] ({len(items)} 条)...")
            result = self._process_category(cat_name, items)
            category_results.append(result)
            print(f"[RSS聚合]   → {result.total_before_dedup} 条 → 去重后 {result.total_after_dedup} 条")

        total_after = sum(c.total_after_dedup for c in category_results)
        print(f"[RSS聚合] 完成: {total_before} → {total_after} 条")

        return RSSAggregateResult(
            categories=category_results,
            total_before=total_before,
            total_after=total_after,
            success=True,
        )

    def _process_category(self, cat_name: str, items: List[Dict]) -> AggregatedCategory:
        """处理单个分类：调用 AI 去重+摘要"""
        if not items:
            return AggregatedCategory(category=cat_name)

        # 构建标题列表文本
        title_lines = []
        for i, item in enumerate(items, 1):
            title = item.get("title", "")
            source = item.get("source_name", item.get("feed_name", ""))
            title_lines.append(f"{i}. [{source}] {title}")

        titles_text = "\n".join(title_lines)

        user_prompt = f"## 分类\n{cat_name}\n\n## 文章列表（共 {len(items)} 条）\n\n{titles_text}\n\n请去重合并并生成摘要。"

        messages = [
            {"role": "system", "content": AGGREGATE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        if self.debug:
            print(f"\n[RSS聚合][DEBUG] === 分类 [{cat_name}] Prompt ===")
            print(f"System: {AGGREGATE_SYSTEM_PROMPT[:100]}...")
            print(f"User ({len(titles_text)} chars): {titles_text[:200]}...")
            print(f"[RSS聚合][DEBUG] === Prompt 结束 ===\n")

        try:
            response = self.client.chat(messages)
            parsed = self._parse_response(response)

            summary = parsed.get("summary", "")
            ai_items = parsed.get("items", [])

            # 将 AI 返回的去重结果转为标准 title_entry 格式
            deduped_items = []
            ai_title_set = set()
            for ai_item in ai_items:
                title = ai_item.get("title", "").strip()
                source = ai_item.get("source", "").strip()
                if not title:
                    continue
                # 去重
                title_lower = title.lower()
                if title_lower in ai_title_set:
                    continue
                ai_title_set.add(title_lower)

                # 找到原始条目中匹配的，保留完整信息
                original = self._find_matching_item(title, source, items)

                if original:
                    entry = dict(original)
                    entry["matched_keyword"] = cat_name
                else:
                    entry = {
                        "title": title,
                        "source_name": source or cat_name,
                        "url": "",
                        "mobile_url": "",
                        "ranks": [],
                        "rank_threshold": 50,
                        "count": 1,
                        "is_new": False,
                        "time_display": "",
                        "matched_keyword": cat_name,
                    }

                # 用 AI 返回的标题（可能更完整）
                entry["title"] = title
                deduped_items.append(entry)

            return AggregatedCategory(
                category=cat_name,
                summary=summary,
                items=deduped_items,
                total_before_dedup=len(items),
                total_after_dedup=len(deduped_items),
            )

        except Exception as e:
            print(f"[RSS聚合] 分类 [{cat_name}] AI 处理失败: {type(e).__name__}: {e}")
            # 失败时返回原始条目（不过滤）
            return AggregatedCategory(
                category=cat_name,
                summary="",
                items=list(items),
                total_before_dedup=len(items),
                total_after_dedup=len(items),
            )

    def _find_matching_item(self, title: str, source: str, items: List[Dict]) -> Optional[Dict]:
        """在原始条目中查找匹配的项（基于标题相似度）"""
        title_lower = title.lower().strip()

        # 精确匹配
        for item in items:
            if item.get("title", "").lower().strip() == title_lower:
                return item

        # 包含匹配
        for item in items:
            orig_title = item.get("title", "").lower().strip()
            if len(title_lower) > 10 and (title_lower in orig_title or orig_title in title_lower):
                return item

        # 来源+关键词匹配
        if source:
            source_lower = source.lower().strip()
            for item in items:
                item_source = (item.get("source_name", "") or item.get("feed_name", "") or "").lower().strip()
                if source_lower == item_source or source_lower in item_source or item_source in source_lower:
                    return item

        return None

    def _parse_response(self, response: str) -> Dict:
        """解析 AI 响应 JSON"""
        if not response or not response.strip():
            return {"summary": "", "items": []}

        text = response.strip()

        # 提取 ```json ... ``` 代码块
        if "```json" in text:
            parts = text.split("```json", 1)
            if len(parts) > 1:
                code_block = parts[1]
                end_idx = code_block.find("```")
                text = code_block[:end_idx] if end_idx != -1 else code_block
        elif "```" in text:
            parts = text.split("```", 2)
            if len(parts) >= 2:
                text = parts[1]

        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 尝试修复常见问题
            try:
                # 有的模型会在 JSON 外包裹额外文本
                brace_start = text.find("{")
                brace_end = text.rfind("}")
                if brace_start != -1 and brace_end != -1:
                    text = text[brace_start : brace_end + 1]
                    data = json.loads(text)
                else:
                    return {"summary": "", "items": []}
            except (json.JSONDecodeError, ValueError):
                return {"summary": "", "items": []}

        if not isinstance(data, dict):
            return {"summary": "", "items": []}

        summary = data.get("summary", "")
        items = data.get("items", [])

        if not isinstance(items, list):
            items = []

        # 校验 items 格式
        validated = []
        for item in items:
            if isinstance(item, dict) and item.get("title"):
                validated.append({
                    "title": str(item["title"]).strip(),
                    "source": str(item.get("source", "")).strip(),
                })
            elif isinstance(item, str):
                validated.append({"title": item.strip(), "source": ""})

        return {"summary": summary.strip(), "items": validated}


# ═══════════════════════════════════════════════════════════════
#  热榜聚合摘要
# ═══════════════════════════════════════════════════════════════

HOTLIST_AGGREGATE_SYSTEM_PROMPT = """你是一个新闻聚合助手。你的任务是对同一话题标签下的多条新闻进行智能处理：

1. 去重合并：识别报道同一事件/话题的新闻，合并为一条（保留最完整、信息量最大的标题）
2. 生成摘要：用 1-2 句话概括该标签下今天的主要动态
3. 去重后的结果按热度从高到低排列

返回严格的 JSON 格式（不要添加任何额外内容）：
{"summary": "该标签下的内容概括", "items": [{"title": "去重后的标题", "source": "来源平台"}, ...]}

注意：
- 同一事件出现在多个平台时只保留一条（选标题最完整的那个）
- 明显不同的新闻各自保留
- source 为来源平台名称
- 如果该标签下只有一条内容或无需去重，summary 简短概括即可
"""


@dataclass
class HotlistAggregateResult:
    """热榜聚合摘要结果"""
    stats: List[Dict] = field(default_factory=list)   # 聚合后的 stats（含 summary）
    total_before: int = 0
    total_after: int = 0
    success: bool = False
    error: str = ""


class HotlistAggregator:
    """热榜新闻聚合摘要器"""

    def __init__(self, ai_config: Dict[str, Any], debug: bool = False):
        self.client = AIClient(ai_config)
        self.debug = debug
        self.batch_interval = 1  # 标签间等待秒数

    def aggregate(self, stats: List[Dict]) -> HotlistAggregateResult:
        """
        对热榜新闻按标签分组进行 AI 去重聚合摘要

        Args:
            stats: 热榜统计数据，格式 [{"word": "英伟达", "count": N, "titles": [...]}, ...]

        Returns:
            HotlistAggregateResult: 聚合结果
        """
        if not stats:
            return HotlistAggregateResult(success=True)

        total_before = sum(len(s.get("titles", [])) for s in stats)
        aggregated_stats = []

        print(f"[热榜聚合] 共 {len(stats)} 个标签, {total_before} 条新闻")

        for idx, stat in enumerate(stats):
            word = stat.get("word", "")
            titles = stat.get("titles", [])
            if not titles:
                aggregated_stats.append(stat)
                continue

            if idx > 0 and self.batch_interval > 0:
                time.sleep(self.batch_interval)

            print(f"[热榜聚合] 处理标签 [{word}] ({len(titles)} 条)...")
            result = self._process_tag(word, titles, stat)
            aggregated_stats.append(result)
            new_count = len(result.get("titles", []))
            if new_count != len(titles):
                print(f"[热榜聚合]   → {len(titles)} 条 → 去重后 {new_count} 条")

        total_after = sum(len(s.get("titles", [])) for s in aggregated_stats)
        if total_after < total_before:
            print(f"[热榜聚合] 完成: {total_before} → {total_after} 条")
        else:
            print(f"[热榜聚合] 完成: {len(stats)} 个标签处理完毕")

        return HotlistAggregateResult(
            stats=aggregated_stats,
            total_before=total_before,
            total_after=total_after,
            success=True,
        )

    def _process_tag(self, tag: str, titles: List[Dict], original_stat: Dict) -> Dict:
        """处理单个标签：调用 AI 去重+摘要"""
        if len(titles) <= 1:
            # 只有一条，无需去重
            return original_stat

        # 构建标题列表
        title_lines = []
        for i, t in enumerate(titles, 1):
            title = t.get("title", "")
            source = t.get("source_name", t.get("source", ""))
            time_info = t.get("time_display", "")
            rank_info = ""
            ranks = t.get("ranks", [])
            if ranks:
                rank_info = f" (排名:{min(ranks)})"
            title_lines.append(f"{i}. [{source}] {title}{rank_info} | {time_info}" if time_info else f"{i}. [{source}] {title}{rank_info}")

        titles_text = "\n".join(title_lines)

        user_prompt = f"## 标签\n{tag}\n\n## 新闻列表（共 {len(titles)} 条）\n\n{titles_text}\n\n请去重合并并生成摘要。"

        messages = [
            {"role": "system", "content": HOTLIST_AGGREGATE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        if self.debug:
            print(f"\n[热榜聚合][DEBUG] === 标签 [{tag}] Prompt ===")
            print(f"User ({len(titles_text)} chars)")
            print(f"[热榜聚合][DEBUG] === Prompt 结束 ===\n")

        try:
            response = self.client.chat(messages)
            parsed = self._parse_response(response)

            summary = parsed.get("summary", "")
            ai_items = parsed.get("items", [])

            # 将 AI 返回的去重结果与原始条目匹配
            deduped = []
            seen = set()
            for ai_item in ai_items:
                ai_title = ai_item.get("title", "").strip()
                ai_source = ai_item.get("source", "").strip()
                if not ai_title or ai_title.lower() in seen:
                    continue
                seen.add(ai_title.lower())

                # 在原始 titles 中找匹配项
                matched = self._find_match(ai_title, ai_source, titles)
                if matched:
                    entry = dict(matched)
                else:
                    entry = {
                        "title": ai_title,
                        "source_name": ai_source or tag,
                        "url": "",
                        "mobile_url": "",
                        "ranks": [],
                        "rank_threshold": 50,
                        "count": 1,
                        "is_new": False,
                        "time_display": "",
                    }
                entry["title"] = ai_title
                entry["matched_keyword"] = tag
                deduped.append(entry)

            # 如果 AI 返回为空，保留原文
            if not deduped:
                deduped = list(titles)

            result = dict(original_stat)
            result["titles"] = deduped
            result["count"] = len(deduped)
            if summary:
                result["summary"] = summary
            return result

        except Exception as e:
            print(f"[热榜聚合] 标签 [{tag}] AI 处理失败: {type(e).__name__}: {e}")
            return dict(original_stat)

    def _find_match(self, ai_title: str, ai_source: str, titles: List[Dict]) -> Optional[Dict]:
        """在原始标题列表中查找匹配项"""
        ai_title_lower = ai_title.lower().strip()

        for t in titles:
            orig_title = (t.get("title", "") or "").lower().strip()
            if orig_title == ai_title_lower:
                return t

        for t in titles:
            orig_title = (t.get("title", "") or "").lower().strip()
            if len(ai_title_lower) > 10 and (ai_title_lower in orig_title or orig_title in ai_title_lower):
                return t

        if ai_source:
            ai_source_lower = ai_source.lower().strip()
            for t in titles:
                src = (t.get("source_name", "") or "").lower().strip()
                if ai_source_lower and src and (ai_source_lower in src or src in ai_source_lower):
                    return t

        return None

# coding=utf-8
"""
RSS 板块映射管理命令

显示和导出 RSS 订阅源 → 板块的映射关系。
用户可以编辑导出的 rss_categories.yaml 来自定义分类。
"""

from pathlib import Path
from typing import Dict, List, Optional
from trendradar.core.loader import load_config
from trendradar.core.analyzer import RSS_CATEGORY_DISPLAY_NAMES
import yaml


def show_rss_categories(config_path: str = "config/config.yaml") -> None:
    """
    显示当前 RSS 订阅源的板块映射表，并导出可编辑的配置文件。

    映射规则：
    1. 优先读取 config/rss_categories.yaml（可手动编辑）
    2. 如果没有该文件，则使用 OPML 文件中的文件夹分类
    3. 通过 RSS_CATEGORY_DISPLAY_NAMES 将 OPML 分类名转为展示名
    """
    config = load_config(config_path)
    feeds: List[Dict] = config.get("RSS", {}).get("FEEDS", [])

    if not feeds:
        print("❌ 没有加载到任何 RSS 订阅源")
        return

    # 读取已有自定义映射（如果有）
    custom_path = Path("config/rss_categories.yaml")
    custom_map: Dict[str, str] = {}
    if custom_path.exists():
        with open(custom_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and isinstance(data, dict) and "feed_categories" in data:
            custom_map = data["feed_categories"]
        print(f"📂 已加载自定义映射: {custom_path}")

    # 按板块分组统计
    category_counts: Dict[str, int] = {}
    category_feeds: Dict[str, list] = {}
    uncategorized: list = []

    for feed in feeds:
        feed_id = feed["id"]
        feed_name = feed["name"]

        # 优先使用自定义映射
        raw_cat = custom_map.get(feed_id)
        if not raw_cat:
            raw_cat = feed.get("category") or "未分类"

        display_cat = RSS_CATEGORY_DISPLAY_NAMES.get(raw_cat, raw_cat)
        category_counts[display_cat] = category_counts.get(display_cat, 0) + 1
        category_feeds.setdefault(display_cat, []).append((feed_id, feed_name, raw_cat))

    # ========== 输出板块概览 ==========
    print(f"\n{'='*65}")
    print(f"  RSS 订阅源板块映射表（共 {len(feeds)} 个源）")
    print(f"{'='*65}\n")

    # 排序板块
    order = [
        "🤖  AI 与科技前沿",
        "🖥️  科技与前沿",
        "📈  财经与市场",
        "🏢  商业与产业",
        "🏛️  政策与大事",
        "📰  综合新闻",
    ]
    sorted_cats = sorted(category_counts.keys(),
                         key=lambda c: order.index(c) if c in order else 999)

    for cat in sorted_cats:
        feeds_in_cat = category_feeds.get(cat, [])
        print(f"  {cat}  ({len(feeds_in_cat)} 个源)")
        for fid, fname, raw_cat in feeds_in_cat:
            custom_hint = " [自定义]" if fid in custom_map else ""
            print(f"    ├─ {fname}")
        print()

    if uncategorized:
        print(f"  📋  未分类 ({len(uncategorized)} 个源)")
        for fid, fname, _ in uncategorized:
            print(f"    ├─ {fname}")
        print()

    # ========== 导出 / 更新映射文件 ==========
    _export_category_yaml(feeds, custom_map)


def _export_category_yaml(feeds: List[Dict], existing_map: Dict[str, str]) -> None:
    """导出/更新 rss_categories.yaml"""
    export_path = Path("config/rss_categories.yaml")

    # 构建映射：已有自定义映射优先，否则用 OPML 分类
    feed_categories: Dict[str, str] = {}
    for feed in feeds:
        feed_id = feed["id"]
        if feed_id in existing_map:
            feed_categories[feed_id] = existing_map[feed_id]
        else:
            feed_categories[feed_id] = feed.get("category", "未分类")

    data = {
        "# 说明": "RSS 订阅源 → 板块映射表",
        "# 编辑方式": "修改下方 feed_categories 中 feed_id 对应的值即可",
        "# 可用板块展示名（可直接使用 emoji 前缀的展示名或 OPML 分类名）": [
            "🤖  AI 与科技前沿",
            "🖥️  科技与前沿",
            "📈  财经与市场",
            "🏢  商业与产业",
            "🏛️  政策与大事",
            "📰  综合新闻",
        ],
        "feed_categories": feed_categories,
    }

    with open(export_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False, width=120)

    print(f"💾 映射表已导出 → {export_path.resolve()}")
    print(f"   编辑此文件后重新运行即可生效")

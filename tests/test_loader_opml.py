import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

pkg = types.ModuleType("trendradar")
pkg.__path__ = [str(ROOT / "trendradar")]
sys.modules.setdefault("trendradar", pkg)

core_pkg = types.ModuleType("trendradar.core")
core_pkg.__path__ = [str(ROOT / "trendradar" / "core")]
sys.modules.setdefault("trendradar.core", core_pkg)

spec = importlib.util.spec_from_file_location("trendradar.core.config", ROOT / "trendradar" / "core" / "config.py")
config_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = config_module
spec.loader.exec_module(config_module)

spec = importlib.util.spec_from_file_location("trendradar.core.loader", ROOT / "trendradar" / "core" / "loader.py")
loader_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = loader_module
spec.loader.exec_module(loader_module)

_load_rss_config = loader_module._load_rss_config


def test_load_rss_config_reads_feeds_from_opml(tmp_path):
    opml_path = tmp_path / "feeds.opml"
    opml_path.write_text(
        """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<opml version=\"1.0\">
  <body>
    <outline text=\"Tech\" title=\"Tech\">
      <outline type=\"rss\" text=\"Example Tech\" title=\"Example Tech\" xmlUrl=\"https://example.com/tech.xml\" htmlUrl=\"https://example.com/tech\"/>
    </outline>
    <outline text=\"News\" title=\"News\">
      <outline type=\"rss\" text=\"Example News\" title=\"Example News\" xmlUrl=\"https://example.com/news.xml\" htmlUrl=\"https://example.com/news\"/>
    </outline>
  </body>
</opml>
""",
        encoding="utf-8",
    )

    config_data = {
        "rss": {
            "enabled": True,
            "opml_file": str(opml_path.name),
            "feeds": [],
        },
        "advanced": {"rss": {}, "crawler": {}},
    }

    result = _load_rss_config(config_data, config_dir=tmp_path)

    assert result["ENABLED"] is True
    assert result["FEEDS"] == [
        {
            "id": "example-tech",
            "name": "Example Tech",
            "url": "https://example.com/tech.xml",
            "enabled": True,
        },
        {
            "id": "example-news",
            "name": "Example News",
            "url": "https://example.com/news.xml",
            "enabled": True,
        },
    ]


def test_load_rss_config_limits_feeds_in_debug_mode(tmp_path):
    opml_path = tmp_path / "feeds.opml"
    opml_path.write_text(
        """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<opml version=\"1.0\">
  <body>
""" + "\n".join(
            f'<outline type="rss" text="Feed {i}" title="Feed {i}" xmlUrl="https://example.com/{i}.xml"/>'
            for i in range(12)
        ) + "\n  </body>\n</opml>",
        encoding="utf-8",
    )

    config_data = {
        "rss": {
            "enabled": True,
            "opml_file": str(opml_path.name),
            "feeds": [],
        },
        "advanced": {"rss": {}, "crawler": {}},
    }

    result = _load_rss_config(config_data, config_dir=tmp_path, debug_mode=True, rss_feed_limit=10)

    assert len(result["FEEDS"]) == 10
    assert result["FEEDS"][0]["url"] == "https://example.com/0.xml"
    assert result["FEEDS"][-1]["url"] == "https://example.com/9.xml"

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from modules.nightly_engine import NightlyEngine


class NightlyEngineCacheTests(unittest.TestCase):
    def setUp(self):
        self.engine = NightlyEngine(timeout=1, news_limit=4)

    def test_corrupt_cache_is_removed_and_treated_as_miss(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "broken.json"
            cache_path.write_text("{not-json", encoding="utf-8")

            result = self.engine._read_cache(cache_path)

            self.assertIsNone(result)
            self.assertFalse(cache_path.exists())

    def test_atomic_cache_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "news.json"
            items = [
                {
                    "title": "測試新聞",
                    "link": "https://example.test/news",
                    "published": "today",
                }
            ]

            self.engine._write_cache(cache_path, items)
            result = self.engine._read_cache(cache_path)

            self.assertEqual(result, items)
            self.assertFalse(
                cache_path.with_suffix(cache_path.suffix + ".tmp").exists()
            )

    def test_repeated_query_uses_memory_cache(self):
        raw_xml = """
        <rss><channel>
          <item>
            <title>台積電獲利成長 - Google News</title>
            <link>https://example.test/tsmc</link>
            <pubDate>today</pubDate>
          </item>
        </channel></rss>
        """
        response = Mock()
        response.text = raw_xml
        response.raise_for_status.return_value = None
        self.engine.session.get = Mock(return_value=response)

        with tempfile.TemporaryDirectory() as temp_dir:
            self.engine.cache_dir = Path(temp_dir)
            first = self.engine._fetch_google_news("台積電", limit=1)
            second = self.engine._fetch_google_news("台積電", limit=1)

        self.assertEqual(first, second)
        self.assertEqual(first[0]["title"], "台積電獲利成長")
        self.engine.session.get.assert_called_once()

    def test_malformed_cache_shape_is_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "bad-shape.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "fetched_at": "2026-08-07T00:00:00",
                        "items": {},
                    }
                ),
                encoding="utf-8",
            )

            result = self.engine._read_cache(cache_path)

            self.assertIsNone(result)
            self.assertFalse(cache_path.exists())

    def test_legacy_naive_timestamp_cache_remains_readable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "legacy.json"
            items = [{"title": "legacy", "link": "", "published": ""}]
            cache_path.write_text(
                json.dumps(
                    {
                        "fetched_at": datetime.now().isoformat(
                            timespec="seconds"
                        ),
                        "items": items,
                    }
                ),
                encoding="utf-8",
            )

            result = self.engine._read_cache(cache_path)

            self.assertEqual(result, items)
            self.assertTrue(cache_path.exists())

    def test_cache_write_failure_keeps_fetched_news(self):
        raw_xml = """
        <rss><channel>
          <item>
            <title>測試快取失敗 - Google News</title>
            <link>https://example.test/news</link>
            <pubDate>today</pubDate>
          </item>
        </channel></rss>
        """
        response = Mock()
        response.text = raw_xml
        response.raise_for_status.return_value = None
        self.engine.session.get = Mock(return_value=response)
        self.engine._write_cache = Mock(side_effect=OSError("read-only"))

        result = self.engine._fetch_google_news(
            "cache-write-failure",
            limit=1,
        )
        repeated = self.engine._fetch_google_news(
            "cache-write-failure",
            limit=1,
        )

        self.assertEqual(result, repeated)
        self.assertEqual(result[0]["title"], "測試快取失敗")
        self.engine.session.get.assert_called_once()


if __name__ == "__main__":
    unittest.main()

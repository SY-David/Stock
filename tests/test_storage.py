import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests

from modules.storage import TWSEClient


class TWSEClientCacheTests(unittest.TestCase):
    def setUp(self):
        self.client = TWSEClient(timeout=1)
        self.client.session.get = Mock()

    @staticmethod
    def _response(payload):
        response = Mock()
        response.text = json.dumps(payload, ensure_ascii=False)
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        return response

    def test_fresh_cache_is_used_without_network_request(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            payload = {"stat": "OK", "data": [["cached"]]}
            cache_path.write_text(json.dumps(payload), encoding="utf-8")

            result = self.client._fetch_json(
                "https://example.test/data",
                cache_path=cache_path,
                max_cache_age_seconds=60,
            )

        self.assertEqual(result, payload)
        self.client.session.get.assert_not_called()

    def test_stale_cache_is_refreshed_and_replaced_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            stale_payload = {"value": "stale"}
            fresh_payload = {"value": "fresh"}
            cache_path.write_text(json.dumps(stale_payload), encoding="utf-8")
            stale_time = time.time() - 120
            os.utime(cache_path, (stale_time, stale_time))
            self.client.session.get = Mock(
                return_value=self._response(fresh_payload)
            )

            result = self.client._fetch_json(
                "https://example.test/data",
                cache_path=cache_path,
                max_cache_age_seconds=60,
            )

            persisted = json.loads(cache_path.read_text(encoding="utf-8"))
            temp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")

        self.assertEqual(result, fresh_payload)
        self.assertEqual(persisted, fresh_payload)
        self.assertFalse(temp_path.exists())
        self.client.session.get.assert_called_once()

    def test_stale_valid_cache_is_used_when_refresh_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            stale_payload = {"value": "last-known-good"}
            cache_path.write_text(json.dumps(stale_payload), encoding="utf-8")
            stale_time = time.time() - 120
            os.utime(cache_path, (stale_time, stale_time))
            self.client.session.get = Mock(
                side_effect=requests.ConnectionError("offline")
            )

            result = self.client._fetch_json(
                "https://example.test/data",
                cache_path=cache_path,
                max_cache_age_seconds=60,
            )

        self.assertEqual(result, stale_payload)
        self.client.session.get.assert_called_once()

    def test_corrupt_cache_is_discarded_before_refetch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            fresh_payload = {"value": "fresh"}
            cache_path.write_text("{not-json", encoding="utf-8")
            self.client.session.get = Mock(
                return_value=self._response(fresh_payload)
            )

            result = self.client._fetch_json(
                "https://example.test/data",
                cache_path=cache_path,
            )
            persisted = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertEqual(result, fresh_payload)
        self.assertEqual(persisted, fresh_payload)


if __name__ == "__main__":
    unittest.main()

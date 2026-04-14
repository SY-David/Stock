import json
import tempfile
import unittest
from pathlib import Path

from modules.candidate_pool import generate_daily_candidate_pool
from modules.paper_trading import _build_exit_reason


class DynamicCandidatePoolTests(unittest.TestCase):
    def test_auto_candidate_pool_prefers_common_stocks_and_respects_exclusions(self):
        snapshot_rows = {
            "0050": {
                "Code": "0050",
                "TradeVolume": "120000000",
                "TradeValue": "9000000000",
                "OpeningPrice": "80.00",
                "HighestPrice": "81.00",
                "LowestPrice": "79.80",
                "ClosingPrice": "80.80",
                "Change": "1.20",
                "Transaction": "80000",
            },
            "2330": {
                "Code": "2330",
                "TradeVolume": "42000000",
                "TradeValue": "38000000000",
                "OpeningPrice": "980.00",
                "HighestPrice": "995.00",
                "LowestPrice": "975.00",
                "ClosingPrice": "992.00",
                "Change": "14.00",
                "Transaction": "42000",
            },
            "1101": {
                "Code": "1101",
                "TradeVolume": "5500000",
                "TradeValue": "250000000",
                "OpeningPrice": "40.00",
                "HighestPrice": "41.20",
                "LowestPrice": "39.90",
                "ClosingPrice": "41.00",
                "Change": "1.00",
                "Transaction": "2200",
            },
            "2881": {
                "Code": "2881",
                "TradeVolume": "4200000",
                "TradeValue": "360000000",
                "OpeningPrice": "70.20",
                "HighestPrice": "71.20",
                "LowestPrice": "70.10",
                "ClosingPrice": "71.00",
                "Change": "0.50",
                "Transaction": "2100",
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir)
            payload = {
                "candidate_symbols": ["2881"],
                "recommendations": [
                    {"symbol": "2881", "tomorrow_light": "綠燈", "tomorrow_score": 72, "score": 69}
                ],
            }
            (history_path / "site_snapshot_2026-04-11.json").write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            result = generate_daily_candidate_pool(
                snapshot_rows=snapshot_rows,
                exclude_symbols=["2330"],
                limit=2,
                history_dir=history_path,
            )

        self.assertEqual(len(result), 2)
        self.assertNotIn("0050", result)
        self.assertNotIn("2330", result)
        self.assertIn("2881", result)
        self.assertIn("1101", result)

    def test_position_exits_when_symbol_no_longer_stays_in_candidates(self):
        exit_reason = _build_exit_reason(
            symbol="2382",
            position={"days_held": 2},
            evaluation={},
            candidate_symbols=set(),
            recommended_symbols=set(),
        )

        self.assertEqual(exit_reason, "未持續留在當日候選/推薦名單")


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from modules.analysis_service import NEUTRAL_NIGHTLY_MARKET, analyze_market


class AnalysisServicePriceOnlyTests(unittest.TestCase):
    @patch("modules.analysis_service.NightlyEngine")
    @patch("modules.analysis_service.ScoringEngine")
    @patch("modules.analysis_service.DataStorage")
    def test_price_only_symbols_are_fetched_but_not_ranked(
        self,
        storage_cls,
        scoring_cls,
        nightly_cls,
    ):
        storage = storage_cls.return_value
        storage.get_stock_data.side_effect = lambda symbol: {
            "symbol": symbol,
            "info": {"name": symbol, "sector": "Test", "market": "test"},
            "prices": [
                {
                    "date": "2026-08-06",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1000,
                }
            ],
            "valuation_history": [],
            "institutional_history": [],
            "revenue_history": [],
            "margin_history": [],
            "warnings": [],
        }

        scoring = scoring_cls.return_value
        scoring.evaluate.side_effect = lambda data: {
            "symbol": data["symbol"],
            "symbol_name": data["symbol"],
            "score": 60,
            "rating": "Watch",
            "trend": "區間整理",
            "ml_probability": 0.6,
            "reasons": [],
            "risks": [],
        }
        nightly_cls.return_value.analyze.return_value = (
            dict(NEUTRAL_NIGHTLY_MARKET),
            {},
        )

        bundle = analyze_market(
            ["0050"],
            ["2330"],
            price_only_symbols=["2382", "2330"],
        )

        self.assertEqual(set(bundle.raw_data), {"0050", "2330", "2382"})
        self.assertEqual(set(bundle.evaluations), {"0050", "2330"})
        self.assertEqual(bundle.watchlist_symbols, ["0050"])
        self.assertEqual(bundle.candidate_symbols, ["2330"])
        fetched_symbols = [call.args[0] for call in storage.get_stock_data.call_args_list]
        self.assertEqual(fetched_symbols, ["0050", "2330", "2382"])
        self.assertEqual(scoring.evaluate.call_count, 2)


if __name__ == "__main__":
    unittest.main()

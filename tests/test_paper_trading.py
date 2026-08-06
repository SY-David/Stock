import unittest

from modules.paper_trading import _execute_pending_orders, _get_price_row
from modules.scoring_engine import ScoringEngine


class PaperTradingDateTests(unittest.TestCase):
    @staticmethod
    def _snapshot(price_date: str, open_price: float = 100.0) -> dict:
        return {
            "raw_data": {
                "2330": {
                    "prices": [
                        {
                            "date": price_date,
                            "open": open_price,
                            "high": open_price,
                            "low": open_price,
                            "close": open_price,
                            "volume": 1000,
                        }
                    ]
                }
            }
        }

    @staticmethod
    def _buy_order() -> dict:
        return {
            "side": "BUY",
            "symbol": "2330",
            "symbol_name": "台積電",
            "signal_date": "2026-01-02",
            "execute_on_or_after": "2026-01-02",
            "budget": 1000.0,
            "reason": "測試訊號",
        }

    def test_same_or_stale_price_does_not_fill_after_signal(self):
        pending, trades, cash, realized = _execute_pending_orders(
            snapshot=self._snapshot("2026-01-02"),
            current_date="2026-01-03",
            pending_orders=[self._buy_order()],
            positions={},
            trades=[],
            cash=50000.0,
            realized_pnl=0.0,
        )

        self.assertEqual(len(pending), 1)
        self.assertEqual(trades, [])
        self.assertEqual(cash, 50000.0)
        self.assertEqual(realized, 0.0)

    def test_later_price_fills_and_records_actual_trading_date(self):
        positions = {}
        pending, trades, cash, realized = _execute_pending_orders(
            snapshot=self._snapshot("2026-01-05"),
            current_date="2026-01-05",
            pending_orders=[self._buy_order()],
            positions=positions,
            trades=[],
            cash=50000.0,
            realized_pnl=0.0,
        )

        self.assertEqual(pending, [])
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["date"], "2026-01-05")
        self.assertEqual(positions["2330"]["entered_on"], "2026-01-05")
        self.assertEqual(positions["2330"]["last_mark_date"], "2026-01-05")
        self.assertEqual(cash, 49000.0)
        self.assertEqual(realized, 0.0)

    def test_price_lookup_can_require_a_strictly_later_date(self):
        snapshot = self._snapshot("2026-01-02")
        self.assertIsNotNone(_get_price_row(snapshot, "2330", "2026-01-03"))
        self.assertIsNone(
            _get_price_row(
                snapshot,
                "2330",
                "2026-01-03",
                after_date="2026-01-02",
            )
        )


class ScoringSemanticsTests(unittest.TestCase):
    def test_zero_institutional_flow_is_neutral(self):
        prices = []
        for index in range(65):
            prices.append(
                {
                    "date": f"2026-03-{(index % 28) + 1:02d}-{index:03d}",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1000,
                }
            )

        result = ScoringEngine().evaluate(
            {
                "symbol": "2330",
                "info": {"name": "台積電", "sector": "Test", "market": "test"},
                "prices": prices,
                "valuation_history": [],
                "institutional_history": [],
                "revenue_history": [],
                "margin_history": [],
                "warnings": [],
            }
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["institutional_trend"], "中性")


if __name__ == "__main__":
    unittest.main()

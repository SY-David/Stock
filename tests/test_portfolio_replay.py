import math
import unittest
from datetime import date

from app_config import PAPER_ORDER_MAX_CALENDAR_DAYS
from modules.paper_trading import simulate_paper_portfolio


class PortfolioReplayIntegrationTests(unittest.TestCase):
    def test_repository_history_replays_with_consistent_accounting(self):
        result = simulate_paper_portfolio()

        self.assertGreater(result.snapshots_used, 0)
        self.assertGreater(len(result.daily_records), 0)

        record_dates = [row["date"] for row in result.daily_records]
        self.assertEqual(record_dates, sorted(record_dates))
        self.assertEqual(len(record_dates), len(set(record_dates)))

        for row in result.daily_records:
            for field in (
                "cash",
                "market_value",
                "total_assets",
                "realized_pnl",
                "unrealized_pnl",
            ):
                self.assertTrue(math.isfinite(float(row[field])), (field, row))
            self.assertGreaterEqual(float(row["cash"]), -0.01)
            self.assertGreaterEqual(float(row["market_value"]), 0.0)
            self.assertGreaterEqual(float(row["total_assets"]), 0.0)

        trade_dates = [trade["date"] for trade in result.trades]
        self.assertEqual(trade_dates, sorted(trade_dates))

        for trade in result.trades:
            signal_date = date.fromisoformat(str(trade["signal_date"])[:10])
            execution_date = date.fromisoformat(str(trade["date"])[:10])
            lag_days = (execution_date - signal_date).days

            self.assertGreater(lag_days, 0, trade)
            self.assertLessEqual(lag_days, PAPER_ORDER_MAX_CALENDAR_DAYS, trade)
            self.assertGreater(float(trade["price"]), 0.0)
            self.assertGreater(float(trade["quantity"]), 0.0)
            self.assertGreater(float(trade["amount"]), 0.0)

            if trade["side"] == "BUY":
                self.assertIsNone(trade["pnl"])
                self.assertIsNone(trade["return_pct"])
            else:
                self.assertEqual(trade["side"], "SELL")
                self.assertTrue(math.isfinite(float(trade["pnl"])))
                self.assertTrue(math.isfinite(float(trade["return_pct"])))

        for position in result.positions:
            self.assertGreater(float(position["quantity"]), 0.0)
            self.assertGreater(float(position["avg_cost"]), 0.0)
            self.assertGreaterEqual(float(position["market_value"]), 0.0)
            self.assertTrue(math.isfinite(float(position["unrealized_pnl"])))

        latest_date = date.fromisoformat(record_dates[-1])
        for order in result.pending_orders:
            signal_date = date.fromisoformat(str(order["signal_date"])[:10])
            self.assertLessEqual(
                (latest_date - signal_date).days,
                PAPER_ORDER_MAX_CALENDAR_DAYS,
                order,
            )


if __name__ == "__main__":
    unittest.main()

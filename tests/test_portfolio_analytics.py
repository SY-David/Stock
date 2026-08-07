import unittest
from types import SimpleNamespace

from modules.portfolio_analytics import analyze_portfolio


class PortfolioAnalyticsTests(unittest.TestCase):
    def test_drawdown_exposure_and_trade_quality(self):
        result = SimpleNamespace(
            daily_records=[
                {
                    "date": "2026-01-02",
                    "total_assets": 100.0,
                    "position_count": 0,
                },
                {
                    "date": "2026-01-05",
                    "total_assets": 120.0,
                    "position_count": 1,
                },
                {
                    "date": "2026-01-06",
                    "total_assets": 90.0,
                    "position_count": 1,
                },
            ],
            trades=[
                {
                    "side": "SELL",
                    "pnl": 30.0,
                    "return_pct": 10.0,
                },
                {
                    "side": "SELL",
                    "pnl": -10.0,
                    "return_pct": -5.0,
                },
                {
                    "side": "BUY",
                    "pnl": None,
                    "return_pct": None,
                },
            ],
        )

        analytics = analyze_portfolio(result)

        self.assertEqual(analytics.max_drawdown_pct, 25.0)
        self.assertEqual(analytics.max_drawdown_start, "2026-01-05")
        self.assertEqual(analytics.max_drawdown_end, "2026-01-06")
        self.assertEqual(analytics.exposure_pct, 66.67)
        self.assertEqual(analytics.gross_profit, 30.0)
        self.assertEqual(analytics.gross_loss, -10.0)
        self.assertEqual(analytics.profit_factor, 3.0)
        self.assertEqual(analytics.average_win, 30.0)
        self.assertEqual(analytics.average_loss, -10.0)
        self.assertEqual(analytics.best_trade_return_pct, 10.0)
        self.assertEqual(analytics.worst_trade_return_pct, -5.0)

    def test_monthly_returns_use_first_and_last_assets(self):
        result = SimpleNamespace(
            daily_records=[
                {
                    "date": "2026-01-02",
                    "total_assets": 100.0,
                    "position_count": 0,
                },
                {
                    "date": "2026-01-30",
                    "total_assets": 110.0,
                    "position_count": 1,
                },
                {
                    "date": "2026-02-02",
                    "total_assets": 120.0,
                    "position_count": 1,
                },
                {
                    "date": "2026-02-27",
                    "total_assets": 108.0,
                    "position_count": 0,
                },
            ],
            trades=[],
        )

        analytics = analyze_portfolio(result)

        self.assertEqual(
            analytics.monthly_returns,
            [
                {
                    "month": "2026-01",
                    "start_assets": 100.0,
                    "end_assets": 110.0,
                    "return_pct": 10.0,
                },
                {
                    "month": "2026-02",
                    "start_assets": 120.0,
                    "end_assets": 108.0,
                    "return_pct": -10.0,
                },
            ],
        )

    def test_empty_portfolio_is_safe(self):
        analytics = analyze_portfolio(
            SimpleNamespace(daily_records=[], trades=[])
        )

        self.assertEqual(analytics.max_drawdown_pct, 0.0)
        self.assertEqual(analytics.annualized_volatility_pct, 0.0)
        self.assertIsNone(analytics.sharpe_ratio)
        self.assertEqual(analytics.exposure_pct, 0.0)
        self.assertEqual(analytics.drawdown_series, [])
        self.assertEqual(analytics.monthly_returns, [])


if __name__ == "__main__":
    unittest.main()

import unittest

import pandas as pd

from modules.scoring_engine import ScoringEngine


def build_stock_data(
    symbol: str,
    name: str,
    closes: list[float],
    volumes: list[int],
    foreign_net_buy_3d: int,
    trust_net_buy_3d: int,
    pe_ratio: float | None,
    dividend_yield: float | None,
    revenue_yoy_positive: bool,
):
    prices = []
    date_range = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    for index, (trade_date, close) in enumerate(zip(date_range, closes), start=1):
        prices.append(
            {
                "date": trade_date.strftime("%Y-%m-%d"),
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": volumes[index - 1],
            }
        )

    valuation_history = [
        {
            "date": prices[-1]["date"],
            "pe_ratio": pe_ratio,
            "pb_ratio": 2.0,
            "dividend_yield": dividend_yield,
        }
    ]

    institutional_history = [
        {
            "date": prices[-1]["date"],
            "investor_name": "Foreign_Investor",
            "buy": max(foreign_net_buy_3d, 0),
            "sell": abs(min(foreign_net_buy_3d, 0)),
        },
        {
            "date": prices[-1]["date"],
            "investor_name": "Investment_Trust",
            "buy": max(trust_net_buy_3d, 0),
            "sell": abs(min(trust_net_buy_3d, 0)),
        },
    ]

    revenue_history = [
        {"date": "2025-12-01", "revenue": 100, "revenue_year": 2025, "revenue_month": 12},
        {"date": "2026-01-01", "revenue": 120 if revenue_yoy_positive else 90, "revenue_year": 2026, "revenue_month": 1},
        {"date": "2025-01-01", "revenue": 100, "revenue_year": 2025, "revenue_month": 1},
    ]

    margin_history = [
        {
            "date": prices[-1]["date"],
            "margin_balance": 1000,
            "margin_limit": 10000,
            "short_balance": 0,
            "short_limit": 10000,
        }
    ]

    return {
        "symbol": symbol,
        "info": {"name": name, "sector": "Test", "market": "test"},
        "prices": prices,
        "valuation_history": valuation_history,
        "institutional_history": institutional_history,
        "revenue_history": revenue_history,
        "margin_history": margin_history,
        "warnings": [],
        "source": "test",
    }


class ScoringEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = ScoringEngine()

    def test_uptrend_stock_gets_watch_rating(self):
        closes = [100 + i * 1.2 for i in range(65)]
        volumes = [1000] * 64 + [2600]
        data = build_stock_data(
            symbol="2330",
            name="TSMC",
            closes=closes,
            volumes=volumes,
            foreign_net_buy_3d=12000,
            trust_net_buy_3d=4000,
            pe_ratio=18,
            dividend_yield=4.2,
            revenue_yoy_positive=True,
        )

        result = self.engine.evaluate(data)

        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["score"], 60)
        self.assertIn(result["rating"], {"Strong Watch", "Watch"})

    def test_downtrend_stock_is_avoid_or_reduce(self):
        closes = [180 - i * 1.4 for i in range(65)]
        volumes = [1500] * 64 + [3200]
        data = build_stock_data(
            symbol="2303",
            name="UMC",
            closes=closes,
            volumes=volumes,
            foreign_net_buy_3d=-18000,
            trust_net_buy_3d=-6000,
            pe_ratio=42,
            dividend_yield=0.8,
            revenue_yoy_positive=False,
        )

        result = self.engine.evaluate(data)

        self.assertIsNotNone(result)
        self.assertLess(result["score"], 50)
        self.assertIn(result["rating"], {"Reduce", "Avoid"})


if __name__ == "__main__":
    unittest.main()

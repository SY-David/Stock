from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean, stdev
from typing import Any


@dataclass(frozen=True)
class PortfolioAnalytics:
    max_drawdown_pct: float
    max_drawdown_start: str | None
    max_drawdown_end: str | None
    annualized_volatility_pct: float
    sharpe_ratio: float | None
    exposure_pct: float
    gross_profit: float
    gross_loss: float
    profit_factor: float | None
    average_win: float
    average_loss: float
    best_trade_return_pct: float | None
    worst_trade_return_pct: float | None
    drawdown_series: list[dict]
    monthly_returns: list[dict]


def analyze_portfolio(result: Any) -> PortfolioAnalytics:
    daily_records = list(getattr(result, "daily_records", []) or [])
    trades = list(getattr(result, "trades", []) or [])

    drawdown_series, max_drawdown_pct, drawdown_start, drawdown_end = (
        _drawdown_statistics(daily_records)
    )
    daily_returns = _daily_returns(daily_records)
    volatility_pct = (
        stdev(daily_returns) * sqrt(252) * 100 if len(daily_returns) >= 2 else 0.0
    )
    sharpe_ratio = _annualized_sharpe(daily_returns)

    exposure_pct = (
        sum(1 for row in daily_records if int(row.get("position_count", 0)) > 0)
        / len(daily_records)
        * 100
        if daily_records
        else 0.0
    )

    closed_trades = [
        trade
        for trade in trades
        if trade.get("side") == "SELL" and trade.get("pnl") is not None
    ]
    profits = [float(trade["pnl"]) for trade in closed_trades if float(trade["pnl"]) > 0]
    losses = [float(trade["pnl"]) for trade in closed_trades if float(trade["pnl"]) < 0]
    returns = [
        float(trade["return_pct"])
        for trade in closed_trades
        if trade.get("return_pct") is not None
    ]

    gross_profit = sum(profits)
    gross_loss = sum(losses)
    profit_factor = gross_profit / abs(gross_loss) if gross_loss < 0 else None

    return PortfolioAnalytics(
        max_drawdown_pct=round(max_drawdown_pct, 2),
        max_drawdown_start=drawdown_start,
        max_drawdown_end=drawdown_end,
        annualized_volatility_pct=round(volatility_pct, 2),
        sharpe_ratio=round(sharpe_ratio, 2) if sharpe_ratio is not None else None,
        exposure_pct=round(exposure_pct, 2),
        gross_profit=round(gross_profit, 2),
        gross_loss=round(gross_loss, 2),
        profit_factor=round(profit_factor, 2) if profit_factor is not None else None,
        average_win=round(mean(profits), 2) if profits else 0.0,
        average_loss=round(mean(losses), 2) if losses else 0.0,
        best_trade_return_pct=round(max(returns), 2) if returns else None,
        worst_trade_return_pct=round(min(returns), 2) if returns else None,
        drawdown_series=drawdown_series,
        monthly_returns=_monthly_returns(daily_records),
    )


def _daily_returns(daily_records: list[dict]) -> list[float]:
    returns: list[float] = []
    previous_assets: float | None = None

    for row in daily_records:
        assets = float(row.get("total_assets", 0.0))
        if previous_assets is not None and previous_assets > 0:
            returns.append((assets / previous_assets) - 1.0)
        previous_assets = assets

    return returns


def _annualized_sharpe(daily_returns: list[float]) -> float | None:
    if len(daily_returns) < 2:
        return None
    volatility = stdev(daily_returns)
    if volatility == 0:
        return None
    return mean(daily_returns) / volatility * sqrt(252)


def _drawdown_statistics(
    daily_records: list[dict],
) -> tuple[list[dict], float, str | None, str | None]:
    peak_assets = 0.0
    peak_date: str | None = None
    max_drawdown_pct = 0.0
    max_start: str | None = None
    max_end: str | None = None
    series: list[dict] = []

    for row in daily_records:
        date = str(row.get("date", ""))
        assets = float(row.get("total_assets", 0.0))
        if assets >= peak_assets:
            peak_assets = assets
            peak_date = date

        drawdown_pct = ((assets / peak_assets) - 1.0) * 100 if peak_assets > 0 else 0.0
        series.append({"date": date, "drawdown_pct": round(drawdown_pct, 4)})

        magnitude = abs(min(drawdown_pct, 0.0))
        if magnitude > max_drawdown_pct:
            max_drawdown_pct = magnitude
            max_start = peak_date
            max_end = date

    return series, max_drawdown_pct, max_start, max_end


def _monthly_returns(daily_records: list[dict]) -> list[dict]:
    monthly: dict[str, dict[str, float]] = {}

    for row in daily_records:
        date = str(row.get("date", ""))
        if len(date) < 7:
            continue
        month = date[:7]
        assets = float(row.get("total_assets", 0.0))
        if month not in monthly:
            monthly[month] = {"start_assets": assets, "end_assets": assets}
        else:
            monthly[month]["end_assets"] = assets

    rows: list[dict] = []
    for month, values in sorted(monthly.items()):
        start_assets = values["start_assets"]
        end_assets = values["end_assets"]
        return_pct = (
            ((end_assets / start_assets) - 1.0) * 100 if start_assets > 0 else 0.0
        )
        rows.append(
            {
                "month": month,
                "start_assets": round(start_assets, 2),
                "end_assets": round(end_assets, 2),
                "return_pct": round(return_pct, 2),
            }
        )

    return rows

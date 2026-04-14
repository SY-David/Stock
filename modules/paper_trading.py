from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app_config import (
    HISTORY_DIR,
    PAPER_ALLOW_FRACTIONAL,
    PAPER_CONTINUATION_MIN_SCORE,
    PAPER_DAILY_BUDGET,
    PAPER_INITIAL_CASH,
    PAPER_MAX_HOLD_DAYS,
    PAPER_MAX_NEW_BUYS_PER_DAY,
    SNAPSHOT_PATH,
)
from modules.analysis_service import hydrate_decision_fields


@dataclass
class PaperTradingResult:
    initial_cash: float
    cash: float
    market_value: float
    total_assets: float
    realized_pnl: float
    unrealized_pnl: float
    total_return_pct: float
    closed_trade_count: int
    win_rate_pct: float
    avg_closed_trade_return_pct: float
    snapshots_used: int
    positions: list[dict]
    pending_orders: list[dict]
    trades: list[dict]
    daily_records: list[dict]


def simulate_paper_portfolio() -> PaperTradingResult:
    snapshots = _load_full_snapshots()
    if not snapshots:
        return PaperTradingResult(
            initial_cash=PAPER_INITIAL_CASH,
            cash=PAPER_INITIAL_CASH,
            market_value=0.0,
            total_assets=PAPER_INITIAL_CASH,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            total_return_pct=0.0,
            closed_trade_count=0,
            win_rate_pct=0.0,
            avg_closed_trade_return_pct=0.0,
            snapshots_used=0,
            positions=[],
            pending_orders=[],
            trades=[],
            daily_records=[],
        )

    cash = PAPER_INITIAL_CASH
    realized_pnl = 0.0
    positions: dict[str, dict] = {}
    pending_orders: list[dict] = []
    trades: list[dict] = []
    daily_records: list[dict] = []
    market_value = 0.0
    unrealized_pnl = 0.0

    for snapshot in snapshots:
        current_date = snapshot["generated_at"][:10]
        evaluations = snapshot.get("evaluations", {})
        recommendations = snapshot.get("recommendations", [])
        candidate_symbols = set(snapshot.get("candidate_symbols", []))
        recommended_symbols = {item["symbol"] for item in recommendations}

        pending_orders, trades, cash, realized_pnl = _execute_pending_orders(
            snapshot=snapshot,
            current_date=current_date,
            pending_orders=pending_orders,
            positions=positions,
            trades=trades,
            cash=cash,
            realized_pnl=realized_pnl,
        )

        market_value = 0.0
        unrealized_pnl = 0.0
        for symbol, position in positions.items():
            price_row = _get_price_row(snapshot, symbol, current_date)
            if price_row:
                position["last_open"] = price_row["open"]
                position["last_close"] = price_row["close"]
                position["last_mark_date"] = current_date
                position["days_held"] = position.get("days_held", 0) + 1

            market_price = position.get("last_close", position["avg_cost"])
            position["market_value"] = round(position["quantity"] * market_price, 2)
            position["unrealized_pnl"] = round(
                position["quantity"] * (market_price - position["avg_cost"]),
                2,
            )
            market_value += position["market_value"]
            unrealized_pnl += position["unrealized_pnl"]

        pending_symbols = {order["symbol"] for order in pending_orders}
        for symbol, position in list(positions.items()):
            evaluation = evaluations.get(symbol, {})
            exit_reason = _build_exit_reason(
                symbol=symbol,
                position=position,
                evaluation=evaluation,
                candidate_symbols=candidate_symbols,
                recommended_symbols=recommended_symbols,
            )

            if exit_reason and symbol not in pending_symbols:
                pending_orders.append(
                    {
                        "side": "SELL",
                        "symbol": symbol,
                        "symbol_name": position["symbol_name"],
                        "signal_date": current_date,
                        "execute_on_or_after": current_date,
                        "reason": exit_reason,
                    }
                )
                pending_symbols.add(symbol)

        buy_candidates = [
            item
            for item in recommendations
            if item["symbol"] not in positions and item["symbol"] not in pending_symbols
        ][:PAPER_MAX_NEW_BUYS_PER_DAY]

        total_buy_budget = min(PAPER_DAILY_BUDGET, cash)
        if buy_candidates and total_buy_budget > 0:
            per_order_budget = total_buy_budget / len(buy_candidates)
            for item in buy_candidates:
                pending_orders.append(
                    {
                        "side": "BUY",
                        "symbol": item["symbol"],
                        "symbol_name": item["symbol_name"],
                        "signal_date": current_date,
                        "execute_on_or_after": current_date,
                        "budget": round(per_order_budget, 2),
                        "reason": item.get("recommendation_reason", item.get("action", "明日推薦")),
                    }
                )

        total_assets = round(cash + market_value, 2)
        daily_records.append(
            {
                "date": current_date,
                "cash": round(cash, 2),
                "market_value": round(market_value, 2),
                "total_assets": total_assets,
                "realized_pnl": round(realized_pnl, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "position_count": len(positions),
                "pending_orders": len(pending_orders),
                "recommendation_count": len(recommendations),
            }
        )

    positions_rows = sorted(
        (
            {
                "symbol": symbol,
                "symbol_name": position["symbol_name"],
                "quantity": position["quantity"],
                "avg_cost": round(position["avg_cost"], 2),
                "days_held": position.get("days_held", 0),
                "last_close": round(position.get("last_close", position["avg_cost"]), 2),
                "market_value": round(position.get("market_value", 0.0), 2),
                "unrealized_pnl": round(position.get("unrealized_pnl", 0.0), 2),
            }
            for symbol, position in positions.items()
        ),
        key=lambda item: item["market_value"],
        reverse=True,
    )
    pending_rows = sorted(
        pending_orders,
        key=lambda item: (item["execute_on_or_after"], item["side"], item["symbol"]),
    )
    total_assets = round(cash + market_value, 2)
    total_return_pct = ((total_assets / PAPER_INITIAL_CASH) - 1) * 100 if PAPER_INITIAL_CASH else 0.0
    closed_trades = [trade for trade in trades if trade["side"] == "SELL" and trade.get("return_pct") is not None]
    winning_trades = [trade for trade in closed_trades if (trade.get("pnl") or 0) > 0]
    win_rate_pct = (len(winning_trades) / len(closed_trades) * 100) if closed_trades else 0.0
    avg_closed_trade_return_pct = (
        sum(trade["return_pct"] for trade in closed_trades) / len(closed_trades)
        if closed_trades
        else 0.0
    )

    return PaperTradingResult(
        initial_cash=PAPER_INITIAL_CASH,
        cash=round(cash, 2),
        market_value=round(market_value, 2),
        total_assets=total_assets,
        realized_pnl=round(realized_pnl, 2),
        unrealized_pnl=round(unrealized_pnl, 2),
        total_return_pct=round(total_return_pct, 2),
        closed_trade_count=len(closed_trades),
        win_rate_pct=round(win_rate_pct, 2),
        avg_closed_trade_return_pct=round(avg_closed_trade_return_pct, 2),
        snapshots_used=len(snapshots),
        positions=positions_rows,
        pending_orders=pending_rows,
        trades=trades,
        daily_records=daily_records,
    )


def _build_exit_reason(
    symbol: str,
    position: dict,
    evaluation: dict,
    candidate_symbols: set[str],
    recommended_symbols: set[str],
) -> str | None:
    if position.get("days_held", 0) >= PAPER_MAX_HOLD_DAYS:
        return f"持有滿 {PAPER_MAX_HOLD_DAYS} 個交易日"
    if evaluation.get("tomorrow_light") == "紅燈":
        return "明日燈號轉紅燈"

    continues_to_qualify = symbol in recommended_symbols or (
        symbol in candidate_symbols
        and evaluation
        and evaluation.get("tomorrow_light") != "紅燈"
        and float(evaluation.get("tomorrow_score", evaluation.get("score", 0))) >= PAPER_CONTINUATION_MIN_SCORE
    )
    if not continues_to_qualify:
        return "未持續留在當日候選/推薦名單"
    return None


def _load_full_snapshots() -> list[dict]:
    payloads_by_date: dict[str, dict] = {}

    if HISTORY_DIR.exists():
        for path in sorted(HISTORY_DIR.glob("site_snapshot_*.json")):
            payload = _read_snapshot_file(path)
            if payload:
                payloads_by_date[payload["generated_at"][:10]] = payload

    if SNAPSHOT_PATH.exists():
        payload = _read_snapshot_file(SNAPSHOT_PATH)
        if payload:
            payloads_by_date[payload["generated_at"][:10]] = payload

    return sorted(payloads_by_date.values(), key=lambda item: item["generated_at"])


def _read_snapshot_file(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    evaluations = payload.get("evaluations", {})
    for item in evaluations.values():
        hydrate_decision_fields(item)

    recommendations = payload.get("recommendations", [])
    hydrated_recommendations: list[dict] = []
    for row in recommendations:
        cloned = dict(row)
        hydrate_decision_fields(cloned)
        hydrated_recommendations.append(cloned)
    payload["recommendations"] = hydrated_recommendations
    return payload


def _execute_pending_orders(
    snapshot: dict,
    current_date: str,
    pending_orders: list[dict],
    positions: dict[str, dict],
    trades: list[dict],
    cash: float,
    realized_pnl: float,
) -> tuple[list[dict], list[dict], float, float]:
    still_pending: list[dict] = []

    for order in pending_orders:
        if order["execute_on_or_after"] > current_date:
            still_pending.append(order)
            continue

        price_row = _get_price_row(snapshot, order["symbol"], current_date)
        if not price_row:
            still_pending.append(order)
            continue

        open_price = float(price_row["open"])
        if order["side"] == "BUY":
            if order["symbol"] in positions:
                continue

            quantity = _calc_quantity(order.get("budget", 0.0), open_price)
            if quantity <= 0:
                continue

            amount = round(quantity * open_price, 2)
            if amount > cash:
                quantity = _calc_quantity(cash, open_price)
                amount = round(quantity * open_price, 2)
            if quantity <= 0 or amount > cash:
                continue

            cash = round(cash - amount, 2)
            positions[order["symbol"]] = {
                "symbol_name": order["symbol_name"],
                "quantity": quantity,
                "avg_cost": open_price,
                "days_held": 0,
                "entered_on": current_date,
                "signal_date": order["signal_date"],
                "last_close": float(price_row["close"]),
                "last_open": open_price,
                "market_value": amount,
                "unrealized_pnl": 0.0,
            }
            trades.append(
                {
                    "date": current_date,
                    "side": "BUY",
                    "symbol": order["symbol"],
                    "symbol_name": order["symbol_name"],
                    "price": round(open_price, 2),
                    "quantity": quantity,
                    "amount": amount,
                    "pnl": None,
                    "reason": order["reason"],
                    "signal_date": order["signal_date"],
                }
            )
            continue

        if order["side"] == "SELL":
            position = positions.get(order["symbol"])
            if not position:
                continue

            quantity = position["quantity"]
            amount = round(quantity * open_price, 2)
            cost_amount = round(quantity * position["avg_cost"], 2)
            pnl = round(quantity * (open_price - position["avg_cost"]), 2)
            return_pct = ((open_price / position["avg_cost"]) - 1) * 100 if position["avg_cost"] else 0.0
            cash = round(cash + amount, 2)
            realized_pnl = round(realized_pnl + pnl, 2)
            trades.append(
                {
                    "date": current_date,
                    "side": "SELL",
                    "symbol": order["symbol"],
                    "symbol_name": order["symbol_name"],
                    "price": round(open_price, 2),
                    "quantity": quantity,
                    "amount": amount,
                    "cost_amount": cost_amount,
                    "pnl": pnl,
                    "return_pct": round(return_pct, 2),
                    "reason": order["reason"],
                    "signal_date": order["signal_date"],
                }
            )
            del positions[order["symbol"]]
            continue

    return still_pending, trades, cash, realized_pnl


def _get_price_row(snapshot: dict, symbol: str, current_date: str) -> dict | None:
    rows = snapshot.get("raw_data", {}).get(symbol, {}).get("prices", [])
    for row in reversed(rows):
        if row.get("date") == current_date:
            return row
        if row.get("date", "") < current_date:
            break
    return None


def _calc_quantity(budget: float, price: float) -> float:
    if price <= 0 or budget <= 0:
        return 0.0
    if PAPER_ALLOW_FRACTIONAL:
        return round(budget / price, 3)
    return float(int(budget // price))

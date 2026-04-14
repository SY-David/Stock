from __future__ import annotations

import json
import math
from pathlib import Path

from app_config import AUTO_DAILY_CANDIDATE_COUNT, HISTORY_DIR


def generate_daily_candidate_pool(
    snapshot_rows: dict[str, dict],
    exclude_symbols: list[str] | set[str] | None = None,
    limit: int = AUTO_DAILY_CANDIDATE_COUNT,
    history_dir: Path = HISTORY_DIR,
) -> list[str]:
    excluded = {symbol for symbol in (exclude_symbols or [])}
    continuity_scores = _load_continuity_scores(history_dir)

    ranked = _rank_candidates(
        snapshot_rows=snapshot_rows,
        excluded=excluded,
        continuity_scores=continuity_scores,
        min_trade_volume=1_000_000,
        min_trade_value=250_000_000,
        min_transactions=800,
        min_price=10.0,
    )
    if len(ranked) < limit:
        ranked = _rank_candidates(
            snapshot_rows=snapshot_rows,
            excluded=excluded,
            continuity_scores=continuity_scores,
            min_trade_volume=300_000,
            min_trade_value=80_000_000,
            min_transactions=300,
            min_price=8.0,
        )

    return [item["symbol"] for item in ranked[:limit]]


def _rank_candidates(
    snapshot_rows: dict[str, dict],
    excluded: set[str],
    continuity_scores: dict[str, float],
    min_trade_volume: int,
    min_trade_value: int,
    min_transactions: int,
    min_price: float,
) -> list[dict]:
    ranked: list[dict] = []

    for symbol, row in snapshot_rows.items():
        if not _is_common_stock(symbol) or symbol in excluded:
            continue

        close_price = _safe_float(row.get("ClosingPrice"))
        open_price = _safe_float(row.get("OpeningPrice"))
        high_price = _safe_float(row.get("HighestPrice"))
        low_price = _safe_float(row.get("LowestPrice"))
        change_value = _safe_float(row.get("Change")) or 0.0
        trade_volume = _safe_int(row.get("TradeVolume"))
        trade_value = _safe_int(row.get("TradeValue"))
        transaction_count = _safe_int(row.get("Transaction"))

        if close_price is None or close_price < min_price:
            continue
        if trade_volume < min_trade_volume or trade_value < min_trade_value or transaction_count < min_transactions:
            continue

        if open_price is None:
            open_price = close_price
        if high_price is None:
            high_price = close_price
        if low_price is None:
            low_price = close_price

        previous_close = close_price - change_value
        if previous_close <= 0:
            previous_close = close_price

        day_return = (close_price / previous_close) - 1 if previous_close else 0.0
        intraday_range = ((high_price - low_price) / previous_close) if previous_close else 0.0
        close_strength = ((close_price - low_price) / (high_price - low_price)) if high_price and high_price > low_price else 0.5

        score = 0.0
        score += min(24.0, max(-8.0, day_return * 260))
        score += min(18.0, max(0.0, math.log10(max(trade_value, 1)) * 5 - 33))
        score += min(10.0, max(0.0, math.log10(max(transaction_count, 1)) * 4 - 8))

        if close_price >= open_price:
            score += 6.0
        if close_strength >= 0.75:
            score += 5.0
        if intraday_range >= 0.04 and close_price >= open_price:
            score += 4.0
        if trade_value >= 1_500_000_000:
            score += 4.0

        # Let persistent names stay in the pool only if they have shown up repeatedly.
        score += continuity_scores.get(symbol, 0.0)

        # Allow a limited amount of rebound candidates on sharp down days.
        if day_return <= -0.035 and close_price > open_price:
            score += 8.0

        ranked.append({"symbol": symbol, "selection_score": score})

    ranked.sort(key=lambda item: (item["selection_score"], item["symbol"]), reverse=True)
    return ranked


def _load_continuity_scores(history_dir: Path, max_files: int = 5) -> dict[str, float]:
    if not history_dir.exists():
        return {}

    scores: dict[str, float] = {}
    for index, path in enumerate(sorted(history_dir.glob("site_snapshot_*.json"), reverse=True)[:max_files]):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        weight = max(1.0, float(max_files - index))

        for symbol in payload.get("candidate_symbols", []):
            if _is_common_stock(symbol):
                scores[symbol] = scores.get(symbol, 0.0) + 0.6 * weight

        for item in payload.get("recommendations", []):
            symbol = str(item.get("symbol", ""))
            if not _is_common_stock(symbol):
                continue

            bonus = 1.6 * weight
            if item.get("tomorrow_light") == "綠燈":
                bonus += 0.6 * weight
            if float(item.get("tomorrow_score", item.get("score", 0))) >= 68:
                bonus += 0.6 * weight
            scores[symbol] = scores.get(symbol, 0.0) + bonus

    return scores


def _is_common_stock(symbol: str) -> bool:
    return symbol.isdigit() and len(symbol) == 4 and not symbol.startswith("00")


def _safe_float(value: object) -> float | None:
    if value in ("", None, "--", "---"):
        return None
    return float(str(value).replace(",", ""))


def _safe_int(value: object) -> int:
    if value in ("", None, "--", "---"):
        return 0
    return int(str(value).replace(",", ""))

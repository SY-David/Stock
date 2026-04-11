from __future__ import annotations

from dataclasses import dataclass

from config import REPORT_TOP_N
from modules.ai_reporter import AIReporter
from modules.scoring_engine import ScoringEngine
from modules.storage import DataStorage


@dataclass
class AnalysisBundle:
    raw_data: dict[str, dict]
    evaluations: dict[str, dict]
    watchlist_symbols: list[str]
    candidate_symbols: list[str]

    @property
    def watchlist_results(self) -> list[dict]:
        return self._ordered_subset(self.watchlist_symbols)

    @property
    def candidate_results(self) -> list[dict]:
        return self._ordered_subset(self.candidate_symbols)

    @property
    def all_results(self) -> list[dict]:
        return sorted(self.evaluations.values(), key=lambda item: item["score"], reverse=True)

    def _ordered_subset(self, symbols: list[str]) -> list[dict]:
        subset = [self.evaluations[symbol] for symbol in symbols if symbol in self.evaluations]
        return sorted(subset, key=lambda item: item["score"], reverse=True)


def analyze_market(
    watchlist_symbols: list[str],
    candidate_symbols: list[str],
) -> AnalysisBundle:
    storage = DataStorage()
    engine = ScoringEngine()

    normalized_watchlist = _normalize_unique_symbols(watchlist_symbols)
    normalized_candidates = [symbol for symbol in _normalize_unique_symbols(candidate_symbols) if symbol not in normalized_watchlist]
    symbols_to_fetch = normalized_watchlist + normalized_candidates

    raw_data: dict[str, dict] = {}
    evaluations: dict[str, dict] = {}

    for symbol in symbols_to_fetch:
        stock_data = storage.get_stock_data(symbol)
        if not stock_data:
            continue

        raw_data[symbol] = stock_data
        result = engine.evaluate(stock_data)
        if result:
            evaluations[symbol] = result

    return AnalysisBundle(
        raw_data=raw_data,
        evaluations=evaluations,
        watchlist_symbols=normalized_watchlist,
        candidate_symbols=normalized_candidates,
    )


def get_recommendations(bundle: AnalysisBundle) -> list[dict]:
    reporter = AIReporter()
    return reporter.select_recommendations(bundle.candidate_results)


def get_rebound_watchlist(bundle: AnalysisBundle, top_n: int = REPORT_TOP_N) -> list[dict]:
    ranked_items = []
    for item in bundle.all_results:
        rebound_item = _build_rebound_item(item)
        if rebound_item is not None:
            ranked_items.append(rebound_item)
    return sorted(ranked_items, key=lambda row: row["theme_score"], reverse=True)[:top_n]


def get_overheated_watchlist(bundle: AnalysisBundle, top_n: int = REPORT_TOP_N) -> list[dict]:
    ranked_items = []
    for item in bundle.all_results:
        overheated_item = _build_overheated_item(item)
        if overheated_item is not None:
            ranked_items.append(overheated_item)
    return sorted(ranked_items, key=lambda row: row["theme_score"], reverse=True)[:top_n]


def _normalize_unique_symbols(symbols: list[str]) -> list[str]:
    unique_symbols: list[str] = []
    seen = set()
    for symbol in symbols:
        if symbol in seen:
            continue
        seen.add(symbol)
        unique_symbols.append(symbol)
    return unique_symbols


def _build_rebound_item(item: dict) -> dict | None:
    return_20d = item.get("return_20d")
    return_5d = item.get("return_5d")
    ma5 = item.get("ma5")
    ma20 = item.get("ma20")
    close = item.get("close")
    ml_probability = item.get("ml_probability", 0.0)

    oversold_signal = False
    theme_score = 0
    reasons: list[str] = []

    if return_20d is not None and return_20d <= -0.08:
        oversold_signal = True
        theme_score += min(35, int(abs(return_20d) * 160))
        reasons.append(f"近 20 日已下跌 {abs(return_20d) * 100:.1f}%")
    if return_5d is not None and return_5d <= -0.05:
        oversold_signal = True
        theme_score += min(15, int(abs(return_5d) * 120))
        reasons.append(f"近 5 日仍偏弱，跌幅 {abs(return_5d) * 100:.1f}%")
    if ma20 and close and close < ma20:
        oversold_signal = True
        theme_score += 12
        reasons.append("收盤仍在 MA20 下方")
    if item.get("trend") == "弱勢下彎":
        oversold_signal = True
        theme_score += 8
        reasons.append("目前仍是弱勢下彎")

    if not oversold_signal:
        return None

    if ml_probability >= 0.60:
        theme_score += 20
        reasons.append("ML 勝率已回到偏多")
    elif ml_probability >= 0.50:
        theme_score += 12
        reasons.append("ML 勝率回到中性偏多")
    elif ml_probability < 0.40:
        theme_score -= 10

    if return_5d is not None and return_5d >= -0.03:
        theme_score += 10
        reasons.append("近 5 日跌勢開始放緩")

    if ma5 and close and close >= ma5:
        theme_score += 10
        reasons.append("短線重新站回 MA5")

    if item.get("score", 0) < 30:
        theme_score -= 12

    if theme_score < 25:
        return None

    return {
        **item,
        "theme": "oversold_rebound",
        "theme_score": theme_score,
        "theme_reason": "；".join(reasons[:3]) if reasons else "跌深後等待止穩訊號",
    }


def _build_overheated_item(item: dict) -> dict | None:
    return_20d = item.get("return_20d")
    return_5d = item.get("return_5d")
    ma5 = item.get("ma5")
    ma20 = item.get("ma20")
    close = item.get("close")
    volume_ratio = item.get("volume_ratio")
    ml_probability = item.get("ml_probability", 0.0)

    theme_score = 0
    overheat_signal = False
    reasons: list[str] = []

    if return_5d is not None and return_5d >= 0.08:
        overheat_signal = True
        theme_score += min(25, int(return_5d * 150))
        reasons.append(f"近 5 日漲幅 {return_5d * 100:.1f}%")
    if return_20d is not None and return_20d >= 0.15:
        overheat_signal = True
        theme_score += min(30, int(return_20d * 120))
        reasons.append(f"近 20 日漲幅 {return_20d * 100:.1f}%")

    if ma20 and close:
        distance_to_ma20 = (close / ma20) - 1
        if distance_to_ma20 >= 0.08:
            overheat_signal = True
            theme_score += min(20, int(distance_to_ma20 * 100))
            reasons.append(f"收盤高於 MA20 {distance_to_ma20 * 100:.1f}%")

    if not overheat_signal:
        return None

    if volume_ratio is not None and volume_ratio < 0.95:
        theme_score += 10
        reasons.append("漲多後量能沒有跟上")

    if ml_probability <= 0.40:
        theme_score += 20
        reasons.append("ML 已轉偏空")
    elif ml_probability <= 0.50:
        theme_score += 10
        reasons.append("ML 已降到中性")

    if ma5 and close and close < ma5:
        theme_score += 12
        reasons.append("短線跌回 MA5 下方")

    if theme_score < 25:
        return None

    return {
        **item,
        "theme": "overheated_pullback",
        "theme_score": theme_score,
        "theme_reason": "；".join(reasons[:3]) if reasons else "短線漲多，留意拉回",
    }

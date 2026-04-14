from __future__ import annotations

from dataclasses import dataclass

from app_config import AUTO_DAILY_CANDIDATE_COUNT, ENABLE_NIGHTLY_CONTEXT, REPORT_TOP_N
from modules.ai_reporter import AIReporter
from modules.nightly_engine import NightlyEngine
from modules.scoring_engine import ScoringEngine
from modules.storage import DataStorage


NEUTRAL_NIGHTLY_MARKET = {
    "market_bias": "中性",
    "macro_score": 0,
    "summary": "夜間消息偏中性",
    "tags": [],
    "headlines": [],
    "warnings": [],
}


@dataclass
class AnalysisBundle:
    raw_data: dict[str, dict]
    evaluations: dict[str, dict]
    watchlist_symbols: list[str]
    candidate_symbols: list[str]
    nightly_market: dict
    nightly_signals: dict[str, dict]

    @property
    def watchlist_results(self) -> list[dict]:
        return self._ordered_subset(self.watchlist_symbols)

    @property
    def candidate_results(self) -> list[dict]:
        return self._ordered_subset(self.candidate_symbols)

    @property
    def all_results(self) -> list[dict]:
        return sorted(self.evaluations.values(), key=_ranking_key, reverse=True)

    def _ordered_subset(self, symbols: list[str]) -> list[dict]:
        subset = [self.evaluations[symbol] for symbol in symbols if symbol in self.evaluations]
        return sorted(subset, key=_ranking_key, reverse=True)


def analyze_market(
    watchlist_symbols: list[str],
    candidate_symbols: list[str] | None = None,
) -> AnalysisBundle:
    storage = DataStorage()
    engine = ScoringEngine()

    normalized_watchlist = _normalize_unique_symbols(watchlist_symbols)
    requested_candidates = _normalize_unique_symbols(candidate_symbols or [])
    if requested_candidates:
        normalized_candidates = [
            symbol
            for symbol in requested_candidates
            if symbol not in normalized_watchlist
        ]
    else:
        normalized_candidates = storage.build_daily_candidate_pool(
            exclude_symbols=normalized_watchlist,
            limit=AUTO_DAILY_CANDIDATE_COUNT,
        )
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

    nightly_market = dict(NEUTRAL_NIGHTLY_MARKET)
    nightly_signals: dict[str, dict] = {}

    if evaluations and ENABLE_NIGHTLY_CONTEXT:
        nightly_engine = NightlyEngine()
        nightly_market, nightly_signals = nightly_engine.analyze(raw_data, evaluations)

    for symbol, evaluation in evaluations.items():
        evaluation.update(_default_night_fields(evaluation))
        if symbol in nightly_signals:
            evaluation.update(nightly_signals[symbol])
        hydrate_decision_fields(evaluation)
        nightly_signals[symbol] = _extract_nightly_signal(evaluation)

    return AnalysisBundle(
        raw_data=raw_data,
        evaluations=evaluations,
        watchlist_symbols=normalized_watchlist,
        candidate_symbols=normalized_candidates,
        nightly_market=nightly_market,
        nightly_signals=nightly_signals,
    )


def hydrate_decision_fields(evaluation: dict) -> dict:
    evaluation.update(_default_night_fields(evaluation))

    base_score = int(round(evaluation.get("score", 0)))
    night_score = int(round(evaluation.get("night_score", 0)))
    tomorrow_score = int(round(evaluation.get("tomorrow_score", base_score)))
    tomorrow_score = max(0, min(100, tomorrow_score))

    evaluation["tomorrow_score"] = tomorrow_score
    evaluation["tomorrow_delta"] = tomorrow_score - base_score

    rating = evaluation.get("rating", "Neutral")
    trend = evaluation.get("trend", "區間整理")
    ml_probability = float(evaluation.get("ml_probability", 0.0))
    positive_reason = _first_text(evaluation.get("reasons"))
    risk_reason = _first_text(evaluation.get("risks"))
    headline_summary = evaluation.get("headline_summary", "夜間消息偏中性")

    if (
        tomorrow_score >= 68
        and rating in {"Strong Watch", "Watch"}
        and trend != "弱勢下彎"
        and ml_probability >= 0.55
        and night_score >= -2
    ):
        tomorrow_light = "綠燈"
        tomorrow_action = "可試單，優先留意"
        reason_parts = [
            positive_reason or "整體分數仍在強勢區間",
            headline_summary if night_score > 0 else "夜間沒有明顯利空",
        ]
    elif night_score <= -6 or tomorrow_score < 50 or trend == "弱勢下彎":
        tomorrow_light = "紅燈"
        tomorrow_action = "先觀望或留意減碼"
        reason_parts = [
            risk_reason or "短線結構偏弱",
            headline_summary if night_score < 0 else "先等更明確的止穩訊號",
        ]
    else:
        tomorrow_light = "黃燈"
        tomorrow_action = "可觀察，等開盤或拉回確認"
        if night_score > 0:
            second_part = headline_summary
        elif night_score < 0:
            second_part = "但夜間消息有雜訊，追價要保守"
        else:
            second_part = "夜間沒有額外加分"
        reason_parts = [
            positive_reason or risk_reason or "整體分數維持中段",
            second_part,
        ]

    tomorrow_reason = "；".join(part for part in reason_parts if part)

    evaluation["tomorrow_light"] = tomorrow_light
    evaluation["tomorrow_action"] = tomorrow_action
    evaluation["tomorrow_reason"] = tomorrow_reason
    evaluation["recommendation_reason"] = tomorrow_reason
    return evaluation


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


def get_nightly_positive_watchlist(bundle: AnalysisBundle, top_n: int = REPORT_TOP_N) -> list[dict]:
    rows = [item for item in bundle.all_results if item.get("night_score", 0) >= 4]
    return sorted(rows, key=lambda item: (item.get("night_score", 0), item.get("tomorrow_score", item["score"])), reverse=True)[:top_n]


def get_nightly_risk_watchlist(bundle: AnalysisBundle, top_n: int = REPORT_TOP_N) -> list[dict]:
    rows = [item for item in bundle.all_results if item.get("night_score", 0) <= -4]
    return sorted(rows, key=lambda item: (item.get("night_score", 0), item.get("tomorrow_score", item["score"])))[:top_n]


def _ranking_key(item: dict) -> tuple[int, int, int]:
    return (
        int(item.get("tomorrow_score", item.get("score", 0))),
        int(item.get("score", 0)),
        int(item.get("night_score", 0)),
    )


def _normalize_unique_symbols(symbols: list[str]) -> list[str]:
    unique_symbols: list[str] = []
    seen = set()
    for symbol in symbols:
        if symbol in seen:
            continue
        seen.add(symbol)
        unique_symbols.append(symbol)
    return unique_symbols


def _default_night_fields(evaluation: dict) -> dict:
    base_score = int(round(evaluation.get("score", 0)))
    return {
        "night_score": evaluation.get("night_score", 0),
        "night_bias": evaluation.get("night_bias", "中性"),
        "tomorrow_score": evaluation.get("tomorrow_score", base_score),
        "night_action": evaluation.get("night_action", "夜間消息偏中性"),
        "event_tags": evaluation.get("event_tags", []),
        "headline_summary": evaluation.get("headline_summary", "夜間消息偏中性"),
        "headlines": evaluation.get("headlines", []),
    }


def _extract_nightly_signal(evaluation: dict) -> dict:
    return {
        "night_score": evaluation.get("night_score", 0),
        "night_bias": evaluation.get("night_bias", "中性"),
        "tomorrow_score": evaluation.get("tomorrow_score", evaluation.get("score", 0)),
        "night_action": evaluation.get("night_action", "夜間消息偏中性"),
        "event_tags": evaluation.get("event_tags", []),
        "headline_summary": evaluation.get("headline_summary", "夜間消息偏中性"),
        "headlines": evaluation.get("headlines", []),
        "warnings": evaluation.get("warnings", []),
        "tomorrow_light": evaluation.get("tomorrow_light", "黃燈"),
        "tomorrow_action": evaluation.get("tomorrow_action", "可觀察，等開盤或拉回確認"),
        "tomorrow_reason": evaluation.get("tomorrow_reason", "夜間消息偏中性"),
    }


def _first_text(items: list[str] | None) -> str | None:
    if not items:
        return None
    return next((item for item in items if item), None)


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
        reasons.append(f"近 20 日跌幅 {abs(return_20d) * 100:.1f}%")
    if return_5d is not None and return_5d <= -0.05:
        oversold_signal = True
        theme_score += min(15, int(abs(return_5d) * 120))
        reasons.append(f"近 5 日仍在下修 {abs(return_5d) * 100:.1f}%")
    if ma20 and close and close < ma20:
        oversold_signal = True
        theme_score += 12
        reasons.append("收盤仍在 MA20 下方")
    if item.get("trend") == "弱勢下彎":
        oversold_signal = True
        theme_score += 8
        reasons.append("結構仍偏弱，但可能接近超跌區")

    if not oversold_signal:
        return None

    if ml_probability >= 0.60:
        theme_score += 20
        reasons.append("ML 勝率回到 60% 以上")
    elif ml_probability >= 0.50:
        theme_score += 12
        reasons.append("ML 勝率回升到中性偏多")
    elif ml_probability < 0.40:
        theme_score -= 10

    if return_5d is not None and return_5d >= -0.03:
        theme_score += 10
        reasons.append("近 5 日跌勢開始放緩")

    if ma5 and close and close >= ma5:
        theme_score += 10
        reasons.append("收盤重新站回 MA5")

    if item.get("score", 0) < 30:
        theme_score -= 12

    if theme_score < 25:
        return None

    return {
        **item,
        "theme": "oversold_rebound",
        "theme_score": theme_score,
        "theme_reason": "；".join(reasons[:3]) if reasons else "跌深後正在觀察是否止穩",
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
        reasons.append("量能沒有跟上，留意動能轉弱")

    if ml_probability <= 0.40:
        theme_score += 20
        reasons.append("ML 勝率已轉弱")
    elif ml_probability <= 0.50:
        theme_score += 10
        reasons.append("ML 勝率只剩中性附近")

    if ma5 and close and close < ma5:
        theme_score += 12
        reasons.append("收盤跌回 MA5 下方")

    if theme_score < 25:
        return None

    return {
        **item,
        "theme": "overheated_pullback",
        "theme_score": theme_score,
        "theme_reason": "；".join(reasons[:3]) if reasons else "短線過熱，留意拉回壓力",
    }

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from app_config import (
    DAILY_CANDIDATE_POOL,
    GENERATE_LLM_PROMPT,
    HISTORY_DIR,
    HISTORY_LIMIT,
    SNAPSHOT_PATH,
    SNAPSHOT_PRICE_DAYS,
    UPDATE_STATUS_PATH,
    WATCHLIST,
)
from modules.ai_reporter import AIReporter
from modules.analysis_service import (
    AnalysisBundle,
    NEUTRAL_NIGHTLY_MARKET,
    analyze_market,
    get_nightly_positive_watchlist,
    get_nightly_risk_watchlist,
    get_overheated_watchlist,
    get_rebound_watchlist,
    get_recommendations,
    hydrate_decision_fields,
)


HISTORY_SCHEMA_VERSION = 2


@dataclass
class SnapshotPayload:
    generated_at: str
    watchlist_symbols: list[str]
    candidate_symbols: list[str]
    raw_data: dict[str, dict]
    evaluations: dict[str, dict]
    recommendations: list[dict]
    rebound_watchlist: list[dict]
    overheated_watchlist: list[dict]
    nightly_positive_watchlist: list[dict]
    nightly_risk_watchlist: list[dict]
    nightly_market: dict
    report_text: str
    prompt_text: str | None

    @property
    def bundle(self) -> AnalysisBundle:
        evaluations = {symbol: dict(item) for symbol, item in self.evaluations.items()}
        for item in evaluations.values():
            hydrate_decision_fields(item)

        nightly_signals = {
            symbol: {
                "night_score": item.get("night_score", 0),
                "night_bias": item.get("night_bias", "中性"),
                "tomorrow_score": item.get("tomorrow_score", item.get("score", 0)),
                "night_action": item.get("night_action", "夜間消息偏中性"),
                "event_tags": item.get("event_tags", []),
                "headline_summary": item.get("headline_summary", "夜間消息偏中性"),
                "headlines": item.get("headlines", []),
                "tomorrow_light": item.get("tomorrow_light", "黃燈"),
                "tomorrow_action": item.get("tomorrow_action", "可觀察，等開盤或拉回確認"),
                "tomorrow_reason": item.get("tomorrow_reason", "夜間消息偏中性"),
            }
            for symbol, item in evaluations.items()
        }

        return AnalysisBundle(
            raw_data=self.raw_data,
            evaluations=evaluations,
            watchlist_symbols=self.watchlist_symbols,
            candidate_symbols=self.candidate_symbols,
            nightly_market=self.nightly_market,
            nightly_signals=nightly_signals,
        )


def build_snapshot(
    watchlist_symbols: list[str] | None = None,
    candidate_symbols: list[str] | None = None,
    generate_prompt: bool = GENERATE_LLM_PROMPT,
) -> SnapshotPayload:
    watchlist = watchlist_symbols or WATCHLIST
    candidate_pool = candidate_symbols or DAILY_CANDIDATE_POOL

    bundle = analyze_market(watchlist, candidate_pool)
    recommendations = get_recommendations(bundle)
    rebound_watchlist = get_rebound_watchlist(bundle)
    overheated_watchlist = get_overheated_watchlist(bundle)
    nightly_positive_watchlist = get_nightly_positive_watchlist(bundle)
    nightly_risk_watchlist = get_nightly_risk_watchlist(bundle)

    reporter = AIReporter()
    today_str = datetime.now().strftime("%Y-%m-%d")
    report_text = reporter.generate_report(
        date_str=today_str,
        watchlist_results=bundle.watchlist_results,
        daily_recommendations=recommendations,
        candidate_results=bundle.candidate_results,
        rebound_watchlist=rebound_watchlist,
        overheated_watchlist=overheated_watchlist,
        nightly_market=bundle.nightly_market,
        nightly_positive_watchlist=nightly_positive_watchlist,
        nightly_risk_watchlist=nightly_risk_watchlist,
    )
    prompt_text = None
    if generate_prompt:
        prompt_text = reporter.generate_prompt(
            date_str=today_str,
            watchlist_results=bundle.watchlist_results,
            daily_recommendations=recommendations,
            candidate_results=bundle.candidate_results,
            rebound_watchlist=rebound_watchlist,
            overheated_watchlist=overheated_watchlist,
            nightly_market=bundle.nightly_market,
            nightly_positive_watchlist=nightly_positive_watchlist,
            nightly_risk_watchlist=nightly_risk_watchlist,
        )

    return SnapshotPayload(
        generated_at=datetime.now().isoformat(timespec="seconds"),
        watchlist_symbols=bundle.watchlist_symbols,
        candidate_symbols=bundle.candidate_symbols,
        raw_data=_compact_raw_data(bundle.raw_data, SNAPSHOT_PRICE_DAYS),
        evaluations=bundle.evaluations,
        recommendations=recommendations,
        rebound_watchlist=rebound_watchlist,
        overheated_watchlist=overheated_watchlist,
        nightly_positive_watchlist=nightly_positive_watchlist,
        nightly_risk_watchlist=nightly_risk_watchlist,
        nightly_market=bundle.nightly_market,
        report_text=report_text,
        prompt_text=prompt_text,
    )


def save_snapshot(snapshot: SnapshotPayload, path: Path = SNAPSHOT_PATH) -> Path:
    serialized = asdict(snapshot)
    _write_json_atomic(path, serialized, indent=2)
    _migrate_legacy_history_snapshots()
    _save_history_snapshot(serialized)
    return path


def load_snapshot(path: Path = SNAPSHOT_PATH) -> SnapshotPayload | None:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None

    evaluations = payload.get("evaluations") or {}
    for item in evaluations.values():
        hydrate_decision_fields(item)

    return SnapshotPayload(
        generated_at=str(payload.get("generated_at", "")),
        watchlist_symbols=list(payload.get("watchlist_symbols") or []),
        candidate_symbols=list(payload.get("candidate_symbols") or []),
        raw_data=dict(payload.get("raw_data") or {}),
        evaluations=evaluations,
        recommendations=_hydrate_rows(payload.get("recommendations") or []),
        rebound_watchlist=_hydrate_rows(payload.get("rebound_watchlist") or []),
        overheated_watchlist=_hydrate_rows(payload.get("overheated_watchlist") or []),
        nightly_positive_watchlist=_hydrate_rows(
            payload.get("nightly_positive_watchlist") or []
        ),
        nightly_risk_watchlist=_hydrate_rows(payload.get("nightly_risk_watchlist") or []),
        nightly_market=dict(
            payload.get("nightly_market") or dict(NEUTRAL_NIGHTLY_MARKET)
        ),
        report_text=str(payload.get("report_text") or ""),
        prompt_text=payload.get("prompt_text"),
    )


def load_snapshot_history(limit: int = HISTORY_LIMIT) -> list[dict]:
    if not HISTORY_DIR.exists():
        return []

    history_rows: list[dict] = []
    paths = sorted(HISTORY_DIR.glob("site_snapshot_*.json"), reverse=True)[:limit]
    for path in paths:
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue

        evaluations = payload.get("evaluations") or {}
        recommendations = payload.get("recommendations") or []
        history_rows.append(
            {
                "date": str(payload.get("generated_at", ""))[:10],
                "generated_at": str(payload.get("generated_at", "")),
                "recommendation_count": len(recommendations),
                "green_count": sum(
                    1 for item in evaluations.values() if item.get("tomorrow_light") == "綠燈"
                ),
                "yellow_count": sum(
                    1 for item in evaluations.values() if item.get("tomorrow_light") == "黃燈"
                ),
                "red_count": sum(
                    1 for item in evaluations.values() if item.get("tomorrow_light") == "紅燈"
                ),
                "nightly_bias": (payload.get("nightly_market") or {}).get(
                    "market_bias", "中性"
                ),
                "top_recommendations": "、".join(
                    f"{item.get('symbol', '')} {item.get('symbol_name', '')}".strip()
                    for item in recommendations[:3]
                )
                or "無",
            }
        )

    return history_rows


def load_update_status(path: Path = UPDATE_STATUS_PATH) -> dict | None:
    payload = _read_json(path)
    return payload if isinstance(payload, dict) else None


def save_update_status(status_payload: dict, path: Path = UPDATE_STATUS_PATH) -> Path:
    _write_json_atomic(path, status_payload, indent=2)
    return path


def _compact_raw_data(raw_data: dict[str, dict], price_limit: int) -> dict[str, dict]:
    compacted: dict[str, dict] = {}
    for symbol, stock_data in raw_data.items():
        cloned = dict(stock_data)
        prices = list(stock_data.get("prices") or [])
        if price_limit > 0:
            prices = prices[-price_limit:]
        cloned["prices"] = prices
        compacted[symbol] = cloned
    return compacted


def _build_history_payload(serialized_snapshot: dict) -> dict:
    generated_at = str(serialized_snapshot.get("generated_at", ""))
    current_date = generated_at[:10]

    compact_evaluations: dict[str, dict] = {}
    for symbol, item in (serialized_snapshot.get("evaluations") or {}).items():
        compact_evaluations[symbol] = {
            "symbol": item.get("symbol", symbol),
            "symbol_name": item.get("symbol_name", symbol),
            "score": item.get("score", 0),
            "tomorrow_score": item.get("tomorrow_score", item.get("score", 0)),
            "tomorrow_light": item.get("tomorrow_light", "黃燈"),
        }

    compact_recommendations: list[dict] = []
    for item in serialized_snapshot.get("recommendations") or []:
        compact_recommendations.append(
            {
                "symbol": item.get("symbol", ""),
                "symbol_name": item.get("symbol_name", item.get("symbol", "")),
                "score": item.get("score", 0),
                "tomorrow_score": item.get("tomorrow_score", item.get("score", 0)),
                "tomorrow_light": item.get("tomorrow_light", "黃燈"),
                "action": item.get("action", "明日推薦"),
                "recommendation_reason": item.get(
                    "recommendation_reason", item.get("tomorrow_reason", "明日推薦")
                ),
            }
        )

    compact_prices: dict[str, dict] = {}
    for symbol, stock_data in (serialized_snapshot.get("raw_data") or {}).items():
        latest = _latest_price_on_or_before(stock_data.get("prices") or [], current_date)
        if latest is not None:
            compact_prices[symbol] = {"prices": [latest]}

    nightly_market = serialized_snapshot.get("nightly_market") or {}
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "generated_at": generated_at,
        "candidate_symbols": list(serialized_snapshot.get("candidate_symbols") or []),
        "evaluations": compact_evaluations,
        "recommendations": compact_recommendations,
        "nightly_market": {
            "market_bias": nightly_market.get("market_bias", "中性"),
        },
        "raw_data": compact_prices,
    }


def _latest_price_on_or_before(rows: list[dict], target_date: str) -> dict | None:
    for row in reversed(rows):
        row_date = str(row.get("date", ""))
        if not target_date or row_date <= target_date:
            return dict(row)
    return None


def _hydrate_rows(rows: list[dict]) -> list[dict]:
    hydrated: list[dict] = []
    for row in rows:
        cloned = dict(row)
        hydrate_decision_fields(cloned)
        hydrated.append(cloned)
    return hydrated


def _save_history_snapshot(serialized_snapshot: dict) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = str(serialized_snapshot.get("generated_at", ""))
    date_part = generated_at[:10] or datetime.now().strftime("%Y-%m-%d")
    history_path = HISTORY_DIR / f"site_snapshot_{date_part}.json"
    _write_json_atomic(history_path, _build_history_payload(serialized_snapshot), indent=2)


def _migrate_legacy_history_snapshots() -> None:
    if not HISTORY_DIR.exists():
        return

    for path in HISTORY_DIR.glob("site_snapshot_*.json"):
        try:
            with path.open("r", encoding="utf-8") as handle:
                prefix = handle.read(256)
        except OSError:
            continue

        if f'"schema_version": {HISTORY_SCHEMA_VERSION}' in prefix:
            continue

        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        _write_json_atomic(path, _build_history_payload(payload), indent=2)


def _read_json(path: Path) -> object | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _write_json_atomic(path: Path, payload: object, indent: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=indent),
        encoding="utf-8",
    )
    temp_path.replace(path)

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
        raw_data=bundle.raw_data,
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serialized, ensure_ascii=False, indent=2), encoding="utf-8")
    _save_history_snapshot(serialized)
    return path


def load_snapshot(path: Path = SNAPSHOT_PATH) -> SnapshotPayload | None:
    if not path.exists():
        return None

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("nightly_positive_watchlist", [])
    payload.setdefault("nightly_risk_watchlist", [])
    payload.setdefault("nightly_market", dict(NEUTRAL_NIGHTLY_MARKET))
    payload.setdefault("prompt_text", None)

    evaluations = payload.setdefault("evaluations", {})
    for item in evaluations.values():
        hydrate_decision_fields(item)

    payload["recommendations"] = _hydrate_rows(payload.get("recommendations", []))
    payload["rebound_watchlist"] = _hydrate_rows(payload.get("rebound_watchlist", []))
    payload["overheated_watchlist"] = _hydrate_rows(payload.get("overheated_watchlist", []))
    payload["nightly_positive_watchlist"] = _hydrate_rows(payload.get("nightly_positive_watchlist", []))
    payload["nightly_risk_watchlist"] = _hydrate_rows(payload.get("nightly_risk_watchlist", []))
    return SnapshotPayload(**payload)


def load_snapshot_history(limit: int = HISTORY_LIMIT) -> list[dict]:
    if not HISTORY_DIR.exists():
        return []

    history_rows: list[dict] = []
    for path in sorted(HISTORY_DIR.glob("site_snapshot_*.json"), reverse=True)[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        evaluations = payload.get("evaluations", {})
        for item in evaluations.values():
            hydrate_decision_fields(item)

        recommendations = _hydrate_rows(payload.get("recommendations", []))
        history_rows.append(
            {
                "date": payload.get("generated_at", "")[:10],
                "generated_at": payload.get("generated_at", ""),
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
                "nightly_bias": payload.get("nightly_market", {}).get("market_bias", "中性"),
                "top_recommendations": "、".join(
                    f"{item['symbol']} {item['symbol_name']}" for item in recommendations[:3]
                )
                or "無",
            }
        )

    return history_rows


def load_update_status(path: Path = UPDATE_STATUS_PATH) -> dict | None:
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_update_status(status_payload: dict, path: Path = UPDATE_STATUS_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _hydrate_rows(rows: list[dict]) -> list[dict]:
    hydrated: list[dict] = []
    for row in rows:
        cloned = dict(row)
        hydrate_decision_fields(cloned)
        hydrated.append(cloned)
    return hydrated


def _save_history_snapshot(serialized_snapshot: dict) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = serialized_snapshot.get("generated_at", "")
    date_part = generated_at[:10] or datetime.now().strftime("%Y-%m-%d")
    history_path = HISTORY_DIR / f"site_snapshot_{date_part}.json"
    history_path.write_text(json.dumps(serialized_snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

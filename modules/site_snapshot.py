from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from config import DAILY_CANDIDATE_POOL, GENERATE_LLM_PROMPT, SNAPSHOT_PATH, WATCHLIST
from modules.ai_reporter import AIReporter
from modules.analysis_service import (
    AnalysisBundle,
    analyze_market,
    get_overheated_watchlist,
    get_rebound_watchlist,
    get_recommendations,
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
    report_text: str
    prompt_text: str | None

    @property
    def bundle(self) -> AnalysisBundle:
        return AnalysisBundle(
            raw_data=self.raw_data,
            evaluations=self.evaluations,
            watchlist_symbols=self.watchlist_symbols,
            candidate_symbols=self.candidate_symbols,
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

    reporter = AIReporter()
    today_str = datetime.now().strftime("%Y-%m-%d")
    report_text = reporter.generate_report(
        date_str=today_str,
        watchlist_results=bundle.watchlist_results,
        daily_recommendations=recommendations,
        candidate_results=bundle.candidate_results,
        rebound_watchlist=rebound_watchlist,
        overheated_watchlist=overheated_watchlist,
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
        report_text=report_text,
        prompt_text=prompt_text,
    )


def save_snapshot(snapshot: SnapshotPayload, path: Path = SNAPSHOT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(snapshot), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_snapshot(path: Path = SNAPSHOT_PATH) -> SnapshotPayload | None:
    if not path.exists():
        return None

    payload = json.loads(path.read_text(encoding="utf-8"))
    return SnapshotPayload(**payload)

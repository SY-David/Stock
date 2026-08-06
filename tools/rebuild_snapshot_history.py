from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_REPO_PATH = "data/site_snapshot.json"
HISTORY_DIR = ROOT / "data" / "history"
SCHEMA_VERSION = 2


def git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout


def latest_price(rows: list[dict], target_date: str) -> dict | None:
    for row in reversed(rows):
        row_date = str(row.get("date", ""))
        if not target_date or row_date <= target_date:
            return dict(row)
    return None


def compact_snapshot(payload: dict) -> dict | None:
    generated_at = str(payload.get("generated_at", ""))
    if not generated_at:
        return None
    current_date = generated_at[:10]

    evaluations: dict[str, dict] = {}
    for symbol, item in (payload.get("evaluations") or {}).items():
        evaluations[symbol] = {
            "symbol": item.get("symbol", symbol),
            "symbol_name": item.get("symbol_name", symbol),
            "score": item.get("score", 0),
            "tomorrow_score": item.get("tomorrow_score", item.get("score", 0)),
            "tomorrow_light": item.get("tomorrow_light", "黃燈"),
        }

    recommendations: list[dict] = []
    for item in payload.get("recommendations") or []:
        symbol = str(item.get("symbol", ""))
        if not symbol:
            continue
        recommendations.append(
            {
                "symbol": symbol,
                "symbol_name": item.get("symbol_name", symbol),
                "score": item.get("score", 0),
                "tomorrow_score": item.get("tomorrow_score", item.get("score", 0)),
                "tomorrow_light": item.get("tomorrow_light", "黃燈"),
                "action": item.get("action", "明日推薦"),
                "recommendation_reason": item.get(
                    "recommendation_reason",
                    item.get("tomorrow_reason", "明日推薦"),
                ),
            }
        )

    raw_data: dict[str, dict] = {}
    for symbol, stock_data in (payload.get("raw_data") or {}).items():
        row = latest_price(stock_data.get("prices") or [], current_date)
        if row is not None:
            raw_data[symbol] = {"prices": [row]}

    nightly_market = payload.get("nightly_market") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "candidate_symbols": list(payload.get("candidate_symbols") or []),
        "evaluations": evaluations,
        "recommendations": recommendations,
        "nightly_market": {
            "market_bias": nightly_market.get("market_bias", "中性"),
        },
        "raw_data": raw_data,
    }


def snapshots_from_git_history() -> dict[str, dict]:
    commits = git_output(
        "rev-list",
        "--reverse",
        "HEAD",
        "--",
        SNAPSHOT_REPO_PATH,
    ).splitlines()

    snapshots_by_date: dict[str, dict] = {}
    for commit in commits:
        try:
            raw = git_output("show", f"{commit}:{SNAPSHOT_REPO_PATH}")
            payload = json.loads(raw)
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue

        compact = compact_snapshot(payload)
        if compact is None:
            continue
        snapshots_by_date[compact["generated_at"][:10]] = compact

    current_path = ROOT / SNAPSHOT_REPO_PATH
    if current_path.exists():
        try:
            compact = compact_snapshot(json.loads(current_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            compact = None
        if compact is not None:
            snapshots_by_date[compact["generated_at"][:10]] = compact

    return snapshots_by_date


def main() -> None:
    snapshots = snapshots_from_git_history()
    if not snapshots:
        raise RuntimeError("No valid historical snapshots were found in Git history")

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    for date_str, payload in sorted(snapshots.items()):
        path = HISTORY_DIR / f"site_snapshot_{date_str}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    first_date = min(snapshots)
    last_date = max(snapshots)
    print(
        f"Rebuilt {len(snapshots)} compact snapshots from {first_date} through {last_date}"
    )


if __name__ == "__main__":
    main()

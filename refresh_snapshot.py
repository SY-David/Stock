from __future__ import annotations

import argparse
from datetime import datetime

from app_config import SNAPSHOT_PATH, normalize_symbol
from modules.site_snapshot import (
    build_snapshot,
    load_snapshot,
    save_snapshot,
    save_update_status,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="更新網站快照資料")
    parser.add_argument(
        "--watchlist",
        nargs="*",
        help="臨時覆蓋固定追蹤清單，例如: python refresh_snapshot.py --watchlist 0050 2344",
    )
    parser.add_argument(
        "--candidate-pool",
        nargs="*",
        help="臨時覆蓋每日候選池，例如: python refresh_snapshot.py --candidate-pool 2330 2317 2454",
    )
    parser.add_argument("--no-prompt", action="store_true", help="只更新快照，不產生 LLM prompt")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    watchlist = (
        [normalize_symbol(item) for item in args.watchlist]
        if args.watchlist
        else None
    )
    candidate_pool = (
        [normalize_symbol(item) for item in args.candidate_pool]
        if args.candidate_pool
        else None
    )

    previous_snapshot = load_snapshot()
    attempted_at = datetime.now().isoformat(timespec="seconds")

    print("開始更新網站快照...")
    try:
        snapshot = build_snapshot(
            watchlist_symbols=watchlist,
            candidate_symbols=candidate_pool,
            generate_prompt=not args.no_prompt,
        )
        if not snapshot.evaluations:
            raise RuntimeError("本次更新沒有取得任何可用評分結果")

        saved_path = save_snapshot(snapshot)
        save_update_status(
            {
                "status": "success",
                "last_attempt_at": attempted_at,
                "snapshot_generated_at": snapshot.generated_at,
                "snapshot_path": str(saved_path),
                "message": "快照更新成功",
                "error": None,
            }
        )
        print(f"快照已更新: {saved_path}")
        print(f"更新時間: {snapshot.generated_at}")
        print(f"固定追蹤檔數: {len(snapshot.watchlist_symbols)}")
        print(f"候選池檔數: {len(snapshot.candidate_symbols)}")
        print(f"明日推薦檔數: {len(snapshot.recommendations)}")
        return

    except Exception as exc:
        if previous_snapshot is not None and SNAPSHOT_PATH.exists():
            save_update_status(
                {
                    "status": "fallback",
                    "last_attempt_at": attempted_at,
                    "snapshot_generated_at": previous_snapshot.generated_at,
                    "snapshot_path": str(SNAPSHOT_PATH),
                    "message": f"更新失敗，沿用 {previous_snapshot.generated_at} 的快照",
                    "error": str(exc),
                }
            )
            print(f"更新失敗，已沿用上一版快照: {previous_snapshot.generated_at}")
            print(f"錯誤原因: {exc}")
            raise SystemExit(1) from exc

        save_update_status(
            {
                "status": "error",
                "last_attempt_at": attempted_at,
                "snapshot_generated_at": None,
                "snapshot_path": str(SNAPSHOT_PATH),
                "message": "更新失敗，且沒有可沿用的舊快照",
                "error": str(exc),
            }
        )
        raise


if __name__ == "__main__":
    main()

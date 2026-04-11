from __future__ import annotations

import argparse

from config import SNAPSHOT_PATH, normalize_symbol
from modules.site_snapshot import build_snapshot, save_snapshot


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
    parser.add_argument("--no-prompt", action="store_true", help="更新快照時不產生 LLM prompt")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    watchlist = [normalize_symbol(item) for item in args.watchlist] if args.watchlist else None
    candidate_pool = [normalize_symbol(item) for item in args.candidate_pool] if args.candidate_pool else None

    print("開始更新網站快照...")
    snapshot = build_snapshot(
        watchlist_symbols=watchlist,
        candidate_symbols=candidate_pool,
        generate_prompt=not args.no_prompt,
    )
    saved_path = save_snapshot(snapshot)
    print(f"快照已更新: {saved_path}")
    print(f"更新時間: {snapshot.generated_at}")
    print(f"固定追蹤檔數: {len(snapshot.watchlist_symbols)}")
    print(f"候選池檔數: {len(snapshot.candidate_symbols)}")
    print(f"今日推薦檔數: {len(snapshot.recommendations)}")


if __name__ == "__main__":
    main()

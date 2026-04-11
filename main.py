from __future__ import annotations

import argparse
from datetime import datetime

from config import DAILY_CANDIDATE_POOL, GENERATE_LLM_PROMPT, WATCHLIST, normalize_symbol
from modules.analysis_service import (
    analyze_market,
    get_overheated_watchlist,
    get_rebound_watchlist,
    get_recommendations,
)
from modules.ai_reporter import AIReporter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="台股自選股研究助理")
    parser.add_argument("--no-prompt", action="store_true", help="只輸出本地日報，不產生 LLM prompt")
    parser.add_argument(
        "--watchlist",
        nargs="*",
        help="臨時覆蓋固定追蹤清單，例如: python main.py --watchlist 0050 2344",
    )
    parser.add_argument(
        "--candidate-pool",
        nargs="*",
        help="臨時覆蓋每日候選池，例如: python main.py --candidate-pool 2330 2317 2454",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    watchlist = [normalize_symbol(item) for item in (args.watchlist or WATCHLIST)]
    candidate_pool = [normalize_symbol(item) for item in (args.candidate_pool or DAILY_CANDIDATE_POOL)]

    print("啟動台股自選股研究助理...")
    print("資料來源: TWSE 官方資料 + 本地快取")
    print(f"固定追蹤: {', '.join(watchlist)}")
    print(f"每日候選池: {', '.join(candidate_pool)}")

    reporter = AIReporter()

    total_symbols = len({*watchlist, *candidate_pool})
    print(f"\n正在抓取線上資料並評分 (共 {total_symbols} 檔)...")
    bundle = analyze_market(watchlist, candidate_pool)

    for symbol in watchlist:
        if symbol not in bundle.raw_data:
            print(f"  [警告] 固定追蹤 {symbol} 讀不到線上資料，略過。")
            continue
        stock_name = bundle.raw_data[symbol]["info"]["name"]
        print(f"  -> 固定追蹤 {symbol} {stock_name}")
        if symbol not in bundle.evaluations and bundle.raw_data[symbol].get("warnings"):
            print(f"     資料警示: {'；'.join(bundle.raw_data[symbol]['warnings'])}")

    for symbol in candidate_pool:
        if symbol not in bundle.raw_data:
            print(f"  [警告] 候選池 {symbol} 讀不到線上資料，略過。")
            continue
        stock_name = bundle.raw_data[symbol]["info"]["name"]
        print(f"  -> 候選池 {symbol} {stock_name}")
        if symbol not in bundle.evaluations and bundle.raw_data[symbol].get("warnings"):
            print(f"     資料警示: {'；'.join(bundle.raw_data[symbol]['warnings'])}")

    if not bundle.evaluations:
        print("\n沒有足夠的線上資料可產生日報。")
        return

    daily_recommendations = get_recommendations(bundle)
    rebound_watchlist = get_rebound_watchlist(bundle)
    overheated_watchlist = get_overheated_watchlist(bundle)

    print("\n今日推薦:")
    if daily_recommendations:
        for item in daily_recommendations:
            print(
                f"  - {item['symbol']} {item['symbol_name']} | {item['score']} 分 | "
                f"{item['signal_strength']} | {item['action']}"
            )
    else:
        print("  - 今天沒有達到門檻的新推薦。")

    print("\n固定追蹤摘要:")
    if bundle.watchlist_results:
        for item in bundle.watchlist_results:
            print(f"  - {item['symbol']} {item['symbol_name']} | {item['score']} 分 | {item['rating']}")
    else:
        print("  - 固定追蹤清單沒有足夠資料。")

    print("\n超跌反彈觀察:")
    if rebound_watchlist:
        for item in rebound_watchlist:
            print(f"  - {item['symbol']} {item['symbol_name']} | {item['theme_score']} | {item['theme_reason']}")
    else:
        print("  - 目前沒有明顯跌深後轉穩的標的。")

    print("\n超漲轉弱觀察:")
    if overheated_watchlist:
        for item in overheated_watchlist:
            print(f"  - {item['symbol']} {item['symbol_name']} | {item['theme_score']} | {item['theme_reason']}")
    else:
        print("  - 目前沒有明顯短線過熱的標的。")

    today_str = datetime.now().strftime("%Y-%m-%d")
    print("\n正在產生日報...")

    report_md = reporter.generate_report(
        date_str=today_str,
        watchlist_results=bundle.watchlist_results,
        daily_recommendations=daily_recommendations,
        candidate_results=bundle.candidate_results,
        rebound_watchlist=rebound_watchlist,
        overheated_watchlist=overheated_watchlist,
    )
    report_path = reporter.save_report(report_md, f"daily_report_{today_str}.md")
    print(f"[Success] 日報已輸出: {report_path}")

    should_generate_prompt = not args.no_prompt and GENERATE_LLM_PROMPT
    if should_generate_prompt:
        prompt_text = reporter.generate_prompt(
            date_str=today_str,
            watchlist_results=bundle.watchlist_results,
            daily_recommendations=daily_recommendations,
            candidate_results=bundle.candidate_results,
            rebound_watchlist=rebound_watchlist,
            overheated_watchlist=overheated_watchlist,
        )
        prompt_path = reporter.save_report(prompt_text, f"chatgpt_input_{today_str}.txt")
        print(f"[Success] LLM prompt 已輸出: {prompt_path}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
from datetime import datetime

from app_config import (
    AUTO_DAILY_CANDIDATE_COUNT,
    DAILY_CANDIDATE_POOL,
    GENERATE_LLM_PROMPT,
    WATCHLIST,
    normalize_symbol,
)
from modules.analysis_service import (
    analyze_market,
    get_nightly_positive_watchlist,
    get_nightly_risk_watchlist,
    get_overheated_watchlist,
    get_rebound_watchlist,
    get_recommendations,
)
from modules.ai_reporter import AIReporter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="台股個人分析 CLI")
    parser.add_argument("--no-prompt", action="store_true", help="不輸出給 LLM 的 prompt")
    parser.add_argument(
        "--watchlist",
        nargs="*",
        help="指定固定追蹤清單，例如：python main.py --watchlist 0050 2344",
    )
    parser.add_argument(
        "--candidate-pool",
        nargs="*",
        help="指定候選池；若不填，會自動生成每日 10 檔候選池",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    watchlist = [normalize_symbol(item) for item in (args.watchlist or WATCHLIST)]
    requested_candidate_pool = [normalize_symbol(item) for item in (args.candidate_pool or DAILY_CANDIDATE_POOL)]

    print("開始分析台股資料...")
    print("資料來源：TWSE 官方資料 + 本地快取 + 夜間事件層")
    print(f"固定追蹤：{', '.join(watchlist)}")
    if requested_candidate_pool:
        print(f"指定候選池：{', '.join(requested_candidate_pool)}")
    else:
        print(f"指定候選池：未指定，改用自動生成 {AUTO_DAILY_CANDIDATE_COUNT} 檔")

    reporter = AIReporter()

    total_symbols = len({*watchlist, *requested_candidate_pool})
    print(f"\n開始抓資料並評分（初始股票數 {total_symbols}）...")
    bundle = analyze_market(watchlist, requested_candidate_pool)
    candidate_pool = bundle.candidate_symbols
    print(f"實際候選池：{', '.join(candidate_pool)}")

    for symbol in watchlist:
        if symbol not in bundle.raw_data:
            print(f"  [略過] 固定追蹤 {symbol} 沒有拿到資料")
            continue
        stock_name = bundle.raw_data[symbol]["info"]["name"]
        print(f"  -> 固定追蹤 {symbol} {stock_name}")

    for symbol in candidate_pool:
        if symbol not in bundle.raw_data:
            print(f"  [略過] 候選池 {symbol} 沒有拿到資料")
            continue
        stock_name = bundle.raw_data[symbol]["info"]["name"]
        print(f"  -> 候選池 {symbol} {stock_name}")

    if not bundle.evaluations:
        print("\n這次沒有足夠資料，無法輸出分析。")
        return

    daily_recommendations = get_recommendations(bundle)
    rebound_watchlist = get_rebound_watchlist(bundle)
    overheated_watchlist = get_overheated_watchlist(bundle)
    nightly_positive_watchlist = get_nightly_positive_watchlist(bundle)
    nightly_risk_watchlist = get_nightly_risk_watchlist(bundle)

    print("\n夜間市場摘要：")
    print(
        f"  - 偏向：{bundle.nightly_market.get('market_bias', '中性')} | "
        f"分數 {bundle.nightly_market.get('macro_score', 0)} | "
        f"{bundle.nightly_market.get('summary', '目前沒有額外夜間訊號')}"
    )

    print("\n明日推薦：")
    if daily_recommendations:
        for item in daily_recommendations:
            print(
                f"  - {item['symbol']} {item['symbol_name']} | "
                f"{item.get('tomorrow_light', '黃燈')} | "
                f"明日分數 {item.get('tomorrow_score', item['score'])} | "
                f"{item.get('tomorrow_action', item['action'])} | "
                f"{item.get('recommendation_reason', '無')}"
            )
    else:
        print("  - 今天沒有達到門檻的新推薦")

    print("\n固定追蹤總覽：")
    if bundle.watchlist_results:
        for item in bundle.watchlist_results:
            print(
                f"  - {item['symbol']} {item['symbol_name']} | "
                f"{item.get('tomorrow_light', '黃燈')} | "
                f"明日分數 {item.get('tomorrow_score', item['score'])}"
            )
    else:
        print("  - 固定追蹤沒有可用結果")

    print("\n超跌反彈觀察：")
    if rebound_watchlist:
        for item in rebound_watchlist:
            print(f"  - {item['symbol']} {item['symbol_name']} | {item['theme_score']} | {item['theme_reason']}")
    else:
        print("  - 今天沒有明顯超跌反彈名單")

    print("\n超漲轉弱觀察：")
    if overheated_watchlist:
        for item in overheated_watchlist:
            print(f"  - {item['symbol']} {item['symbol_name']} | {item['theme_score']} | {item['theme_reason']}")
    else:
        print("  - 今天沒有明顯過熱轉弱名單")

    print("\n夜間偏多：")
    if nightly_positive_watchlist:
        for item in nightly_positive_watchlist:
            print(
                f"  - {item['symbol']} {item['symbol_name']} | 夜間分數 {item.get('night_score', 0)} | "
                f"{item.get('headline_summary', '目前沒有額外夜間訊號')}"
            )
    else:
        print("  - 今天沒有明顯夜間偏多名單")

    print("\n夜間偏空：")
    if nightly_risk_watchlist:
        for item in nightly_risk_watchlist:
            print(
                f"  - {item['symbol']} {item['symbol_name']} | 夜間分數 {item.get('night_score', 0)} | "
                f"{item.get('headline_summary', '目前沒有額外夜間訊號')}"
            )
    else:
        print("  - 今天沒有明顯夜間偏空名單")

    today_str = datetime.now().strftime("%Y-%m-%d")
    print("\n開始輸出報告...")

    report_md = reporter.generate_report(
        date_str=today_str,
        watchlist_results=bundle.watchlist_results,
        daily_recommendations=daily_recommendations,
        candidate_results=bundle.candidate_results,
        rebound_watchlist=rebound_watchlist,
        overheated_watchlist=overheated_watchlist,
        nightly_market=bundle.nightly_market,
        nightly_positive_watchlist=nightly_positive_watchlist,
        nightly_risk_watchlist=nightly_risk_watchlist,
    )
    report_path = reporter.save_report(report_md, f"daily_report_{today_str}.md")
    print(f"[Success] 日報已輸出到 {report_path}")

    should_generate_prompt = not args.no_prompt and GENERATE_LLM_PROMPT
    if should_generate_prompt:
        prompt_text = reporter.generate_prompt(
            date_str=today_str,
            watchlist_results=bundle.watchlist_results,
            daily_recommendations=daily_recommendations,
            candidate_results=bundle.candidate_results,
            rebound_watchlist=rebound_watchlist,
            overheated_watchlist=overheated_watchlist,
            nightly_market=bundle.nightly_market,
            nightly_positive_watchlist=nightly_positive_watchlist,
            nightly_risk_watchlist=nightly_risk_watchlist,
        )
        prompt_path = reporter.save_report(prompt_text, f"chatgpt_input_{today_str}.txt")
        print(f"[Success] LLM prompt 已輸出到 {prompt_path}")


if __name__ == "__main__":
    main()

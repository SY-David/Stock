from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from app_config import DAILY_CANDIDATE_POOL, HISTORY_DIR, SNAPSHOT_PATH, UPDATE_STATUS_PATH, WATCHLIST, normalize_symbol
from modules.analysis_service import (
    analyze_market,
    get_nightly_positive_watchlist,
    get_nightly_risk_watchlist,
    get_overheated_watchlist,
    get_rebound_watchlist,
    get_recommendations,
)
from modules.ai_reporter import AIReporter
from modules.site_snapshot import load_snapshot, load_snapshot_history, load_update_status


st.set_page_config(page_title="台股自選股研究助理", layout="wide")


def parse_symbol_text(raw_text: str) -> list[str]:
    return [normalize_symbol(item) for item in raw_text.replace("\n", ",").split(",") if item.strip()]


def format_accuracy(value: float | None) -> str:
    if value is None:
        return "無資料"
    return f"{value * 100:.1f}%"


@st.cache_data(ttl=600, show_spinner=False)
def load_analysis_bundle(watchlist_key: str, candidate_key: str):
    watchlist = parse_symbol_text(watchlist_key)
    candidate_pool = parse_symbol_text(candidate_key)
    return analyze_market(watchlist, candidate_pool)


@st.cache_data(ttl=60, show_spinner=False)
def load_saved_snapshot(snapshot_mtime: float):
    del snapshot_mtime
    return load_snapshot()


@st.cache_data(ttl=60, show_spinner=False)
def load_saved_status(status_mtime: float):
    del status_mtime
    return load_update_status()


@st.cache_data(ttl=60, show_spinner=False)
def load_history_rows(history_marker: str):
    del history_marker
    return load_snapshot_history()


def history_marker() -> str:
    if not HISTORY_DIR.exists():
        return "none"
    rows = []
    for path in sorted(HISTORY_DIR.glob("site_snapshot_*.json"))[-20:]:
        rows.append(f"{path.name}:{int(path.stat().st_mtime)}")
    return "|".join(rows)


def render_status_banner(update_status: dict | None, data_source_label: str | None) -> None:
    if data_source_label:
        st.caption(f"資料來源: {data_source_label}")

    if not update_status:
        return

    status = update_status.get("status")
    message = update_status.get("message")
    error = update_status.get("error")

    if status == "fallback":
        st.warning(f"{message}。網站目前顯示上一版可用快照。")
        if error:
            st.caption(f"最近一次更新失敗原因: {error}")
    elif status == "error":
        st.error(message or "最近一次更新失敗。")
        if error:
            st.caption(f"錯誤原因: {error}")
    elif status == "success" and update_status.get("snapshot_generated_at"):
        st.caption(f"最近一次自動更新成功: {update_status['snapshot_generated_at']}")


def render_metrics(watchlist_results: list[dict], candidate_results: list[dict], recommendations: list[dict]) -> None:
    avg_candidate_score = (
        sum(item.get("tomorrow_score", item["score"]) for item in candidate_results) / len(candidate_results)
        if candidate_results
        else 0
    )
    avg_ml = (sum(item["ml_probability"] for item in candidate_results) / len(candidate_results)) if candidate_results else 0
    green_count = sum(1 for item in candidate_results if item.get("tomorrow_light") == "綠燈")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("固定追蹤", len(watchlist_results))
    col2.metric("候選池", len(candidate_results))
    col3.metric("明日推薦", len(recommendations))
    col4.metric("候選池平均明日分數", f"{avg_candidate_score:.1f}" if candidate_results else "0.0")
    st.caption(f"候選池平均 ML 勝率: {avg_ml * 100:.1f}% | 綠燈標的: {green_count} 檔")


def render_nightly_market_overview(nightly_market: dict) -> None:
    st.subheader("今晚到明早總覽")
    col1, col2, col3 = st.columns(3)
    col1.metric("夜間市場偏向", nightly_market.get("market_bias", "中性"))
    col2.metric("夜間市場分數", nightly_market.get("macro_score", 0))
    tags = "、".join(nightly_market.get("tags", [])[:4]) if nightly_market.get("tags") else "無"
    col3.metric("關鍵標籤", tags)

    st.caption(nightly_market.get("summary", "夜間消息偏中性"))
    for headline in nightly_market.get("headlines", [])[:3]:
        st.write(f"- {headline['title']}")
    for warning in nightly_market.get("warnings", [])[:3]:
        st.caption(f"夜間資料警示: {warning}")


def render_recommendations(recommendations: list[dict]) -> None:
    st.subheader("明日推薦")
    if not recommendations:
        st.info("今天沒有達到門檻的新推薦。")
        return

    rec_df = pd.DataFrame(
        [
            {
                "股票": f"{item['symbol']} {item['symbol_name']}",
                "明日燈號": item.get("tomorrow_light", "黃燈"),
                "明日分數": item.get("tomorrow_score", item["score"]),
                "原始分數": item["score"],
                "夜間分數": item.get("night_score", 0),
                "明日動作": item.get("tomorrow_action", item["action"]),
                "推薦理由": item.get("recommendation_reason", "夜間消息偏中性"),
            }
            for item in recommendations
        ]
    )
    st.dataframe(rec_df, use_container_width=True, hide_index=True)


def render_rank_table(title: str, rows: list[dict]) -> None:
    st.subheader(title)
    if not rows:
        st.info("目前沒有可顯示資料。")
        return

    df = pd.DataFrame(
        [
            {
                "股票": f"{item['symbol']} {item['symbol_name']}",
                "明日燈號": item.get("tomorrow_light", "黃燈"),
                "明日分數": item.get("tomorrow_score", item["score"]),
                "原始分數": item["score"],
                "趨勢": item["trend"],
                "明日動作": item.get("tomorrow_action", item["action"]),
            }
            for item in rows
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_theme_table(title: str, rows: list[dict], score_label: str) -> None:
    st.subheader(title)
    if not rows:
        st.info("目前沒有符合條件的標的。")
        return

    df = pd.DataFrame(
        [
            {
                "股票": f"{item['symbol']} {item['symbol_name']}",
                score_label: item["theme_score"],
                "明日燈號": item.get("tomorrow_light", "黃燈"),
                "ML 勝率": f"{item['ml_probability'] * 100:.1f}%",
                "觀察理由": item["theme_reason"],
            }
            for item in rows
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_night_signal_table(title: str, rows: list[dict]) -> None:
    st.subheader(title)
    if not rows:
        st.info("目前沒有符合條件的夜間事件。")
        return

    df = pd.DataFrame(
        [
            {
                "股票": f"{item['symbol']} {item['symbol_name']}",
                "夜間分數": item.get("night_score", 0),
                "明日分數": item.get("tomorrow_score", item["score"]),
                "明日燈號": item.get("tomorrow_light", "黃燈"),
                "夜間偏向": item.get("night_bias", "中性"),
                "夜間動作": item.get("night_action", "夜間消息偏中性"),
                "摘要": item.get("headline_summary", "無資料"),
            }
            for item in rows
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_history_table(rows: list[dict]) -> None:
    st.subheader("歷史紀錄")
    if not rows:
        st.info("目前還沒有歷史快照。")
        return

    df = pd.DataFrame(
        [
            {
                "日期": row["date"],
                "更新時間": row["generated_at"],
                "推薦檔數": row["recommendation_count"],
                "綠燈": row["green_count"],
                "黃燈": row["yellow_count"],
                "紅燈": row["red_count"],
                "夜間偏向": row["nightly_bias"],
                "當日推薦": row["top_recommendations"],
            }
            for row in rows
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_glossary() -> None:
    with st.expander("欄位說明", expanded=False):
        st.markdown(
            "\n".join(
                [
                    "- `原始分數`: 純技術面、量能、法人、估值等規則與 ML 綜合後的分數。",
                    "- `夜間分數`: 用夜間新聞、重大訊息、法說與財經關鍵字做的加減分。",
                    "- `明日分數`: 原始分數加上夜間分數後，給隔天開盤前判斷用。",
                    "- `明日燈號`: 綠燈代表可優先留意，黃燈代表可觀察，紅燈代表先觀望。",
                    "- `推薦理由`: 把原始理由與夜間事件濃縮成一句明天該怎麼看的結論。",
                    "- `ML 勝率`: 模型估計未來幾個交易日偏多的機率，屬於輔助訊號。",
                    "- `驗證準確率`: 模型用歷史驗證資料回頭檢查時的表現，不保證未來一定準。",
                ]
            )
        )


def render_stock_detail(symbol: str, stock_data: dict, result: dict) -> None:
    header = f"{symbol} {result['symbol_name']} | {result.get('tomorrow_light', '黃燈')} | 明日分數 {result.get('tomorrow_score', result['score'])}"
    with st.expander(header, expanded=False):
        left, right = st.columns([3, 2])

        with left:
            price_df = pd.DataFrame(stock_data["prices"]).copy()
            price_df["date"] = pd.to_datetime(price_df["date"])
            chart_df = price_df.set_index("date")[["close"]]
            st.line_chart(chart_df, use_container_width=True)

        with right:
            st.markdown(
                "\n".join(
                    [
                        f"- 原始評級: `{result['rating']}`",
                        f"- 原始分數: `{result['score']}`",
                        f"- 明日燈號: `{result.get('tomorrow_light', '黃燈')}`",
                        f"- 明日分數: `{result.get('tomorrow_score', result['score'])}`",
                        f"- 夜間分數: `{result.get('night_score', 0)}`",
                        f"- 明日動作: `{result.get('tomorrow_action', result['action'])}`",
                        f"- ML: `{result['signal_strength']}`",
                        f"- 驗證準確率: `{format_accuracy(result['ml_validation_accuracy'])}`",
                        f"- 可用樣本: `{result['ml_usable_samples']}`",
                        f"- 訓練樣本: `{result['ml_train_samples']}`",
                        f"- 驗證樣本: `{result['ml_validation_samples']}`",
                    ]
                )
            )

        stat1, stat2, stat3 = st.columns(3)
        stat1.metric("收盤價", f"{result['close']:.2f}")
        stat2.metric("近 5 日報酬", "無資料" if result["return_5d"] is None else f"{result['return_5d'] * 100:.1f}%")
        stat3.metric("近 20 日報酬", "無資料" if result["return_20d"] is None else f"{result['return_20d'] * 100:.1f}%")

        st.markdown("**明日理由**")
        st.write(f"- {result.get('tomorrow_reason', '夜間消息偏中性')}")

        st.markdown("**加分理由**")
        for item in result.get("reasons", []) or ["沒有明顯訊號"]:
            st.write(f"- {item}")

        st.markdown("**風險提醒**")
        for item in result.get("risks", []) or ["沒有明顯訊號"]:
            st.write(f"- {item}")

        st.markdown("**夜間評估**")
        st.write(f"- {result.get('night_action', '夜間消息偏中性')}")
        st.write(f"- {result.get('headline_summary', '沒有明顯事件')}")
        if result.get("event_tags"):
            st.write(f"- 標籤: {'、'.join(result['event_tags'])}")
        for headline in result.get("headlines", [])[:2]:
            st.write(f"- 標題: {headline['title']}")

        if result.get("warnings"):
            st.markdown("**資料警示**")
            for item in result["warnings"]:
                st.write(f"- {item}")


def main() -> None:
    st.title("台股自選股研究助理")
    st.caption("以日線與夜間事件為主，適合盤後到隔天開盤前做決策。")

    reporter = AIReporter()
    default_watchlist_text = ", ".join(WATCHLIST)
    default_candidate_text = ", ".join(DAILY_CANDIDATE_POOL)

    with st.sidebar:
        st.header("設定")
        watchlist_text = st.text_area("固定追蹤", value=default_watchlist_text, height=90)
        candidate_text = st.text_area("每日候選池", value=default_candidate_text, height=180)
        run_button = st.button("重新分析", type="primary", use_container_width=True)
        st.caption("若網站正在讀快照，重新分析只會更新目前這個頁面，不會覆蓋正式快照。")

    if "bundle" not in st.session_state:
        snapshot = None
        if SNAPSHOT_PATH.exists():
            snapshot = load_saved_snapshot(SNAPSHOT_PATH.stat().st_mtime)

        update_status = None
        if UPDATE_STATUS_PATH.exists():
            update_status = load_saved_status(UPDATE_STATUS_PATH.stat().st_mtime)

        if snapshot is not None:
            st.session_state["bundle"] = snapshot.bundle
            st.session_state["watchlist"] = snapshot.watchlist_symbols
            st.session_state["candidate_pool"] = snapshot.candidate_symbols
            st.session_state["recommendations"] = snapshot.recommendations
            st.session_state["rebound_watchlist"] = snapshot.rebound_watchlist
            st.session_state["overheated_watchlist"] = snapshot.overheated_watchlist
            st.session_state["nightly_positive_watchlist"] = snapshot.nightly_positive_watchlist
            st.session_state["nightly_risk_watchlist"] = snapshot.nightly_risk_watchlist
            st.session_state["nightly_market"] = snapshot.nightly_market
            st.session_state["report_text"] = snapshot.report_text
            st.session_state["prompt_text"] = snapshot.prompt_text
            st.session_state["data_source_label"] = f"快照 {snapshot.generated_at}"
            st.session_state["update_status"] = update_status
        else:
            with st.spinner("正在抓取線上資料並建立分析..."):
                bundle = load_analysis_bundle(default_watchlist_text, default_candidate_text)
                recommendations = get_recommendations(bundle)
                rebound_watchlist = get_rebound_watchlist(bundle)
                overheated_watchlist = get_overheated_watchlist(bundle)
                nightly_positive_watchlist = get_nightly_positive_watchlist(bundle)
                nightly_risk_watchlist = get_nightly_risk_watchlist(bundle)
                today_str = datetime.now().strftime("%Y-%m-%d")
                st.session_state["bundle"] = bundle
                st.session_state["watchlist"] = parse_symbol_text(default_watchlist_text)
                st.session_state["candidate_pool"] = parse_symbol_text(default_candidate_text)
                st.session_state["recommendations"] = recommendations
                st.session_state["rebound_watchlist"] = rebound_watchlist
                st.session_state["overheated_watchlist"] = overheated_watchlist
                st.session_state["nightly_positive_watchlist"] = nightly_positive_watchlist
                st.session_state["nightly_risk_watchlist"] = nightly_risk_watchlist
                st.session_state["nightly_market"] = bundle.nightly_market
                st.session_state["report_text"] = reporter.generate_report(
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
                st.session_state["prompt_text"] = reporter.generate_prompt(
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
                st.session_state["data_source_label"] = "即時分析"
                st.session_state["update_status"] = None

    if run_button:
        watchlist = parse_symbol_text(watchlist_text)
        candidate_pool = parse_symbol_text(candidate_text)
        if not watchlist:
            st.error("請至少輸入一檔固定追蹤股票。")
            return
        if not candidate_pool:
            st.error("請至少輸入一檔候選池股票。")
            return

        with st.spinner("正在重新抓取資料、評分與夜間分析..."):
            bundle = load_analysis_bundle(",".join(watchlist), ",".join(candidate_pool))
            recommendations = get_recommendations(bundle)
            rebound_watchlist = get_rebound_watchlist(bundle)
            overheated_watchlist = get_overheated_watchlist(bundle)
            nightly_positive_watchlist = get_nightly_positive_watchlist(bundle)
            nightly_risk_watchlist = get_nightly_risk_watchlist(bundle)
            today_str = datetime.now().strftime("%Y-%m-%d")
            st.session_state["bundle"] = bundle
            st.session_state["watchlist"] = watchlist
            st.session_state["candidate_pool"] = candidate_pool
            st.session_state["recommendations"] = recommendations
            st.session_state["rebound_watchlist"] = rebound_watchlist
            st.session_state["overheated_watchlist"] = overheated_watchlist
            st.session_state["nightly_positive_watchlist"] = nightly_positive_watchlist
            st.session_state["nightly_risk_watchlist"] = nightly_risk_watchlist
            st.session_state["nightly_market"] = bundle.nightly_market
            st.session_state["report_text"] = reporter.generate_report(
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
            st.session_state["prompt_text"] = reporter.generate_prompt(
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
            st.session_state["data_source_label"] = f"即時分析 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            st.session_state["update_status"] = {
                "status": "live",
                "message": "目前頁面顯示即時分析結果，未覆蓋正式快照。",
            }

    bundle = st.session_state.get("bundle")
    if bundle is None:
        st.error("目前沒有可用資料。")
        return

    if not bundle.evaluations:
        st.error("本次沒有拿到足夠資料，無法建立分析。")
        return

    watchlist = st.session_state.get("watchlist", WATCHLIST)
    candidate_pool = st.session_state.get("candidate_pool", DAILY_CANDIDATE_POOL)
    recommendations = st.session_state.get("recommendations", [])
    rebound_watchlist = st.session_state.get("rebound_watchlist", [])
    overheated_watchlist = st.session_state.get("overheated_watchlist", [])
    nightly_positive_watchlist = st.session_state.get("nightly_positive_watchlist", [])
    nightly_risk_watchlist = st.session_state.get("nightly_risk_watchlist", [])
    nightly_market = st.session_state.get("nightly_market", {})
    report_text = st.session_state.get("report_text")
    prompt_text = st.session_state.get("prompt_text")
    data_source_label = st.session_state.get("data_source_label")
    update_status = st.session_state.get("update_status")

    history_rows = load_history_rows(history_marker())

    render_status_banner(update_status, data_source_label)
    render_metrics(bundle.watchlist_results, bundle.candidate_results, recommendations)
    render_nightly_market_overview(nightly_market)
    render_glossary()
    render_recommendations(recommendations)

    top_candidates = bundle.candidate_results[:5]
    weak_candidates = [item for item in bundle.candidate_results if item.get("tomorrow_light") == "紅燈"][:5]

    col1, col2 = st.columns(2)
    with col1:
        render_rank_table("候選池前段班", top_candidates)
    with col2:
        render_rank_table("明日先觀望", weak_candidates)

    col3, col4 = st.columns(2)
    with col3:
        render_theme_table("超跌反彈觀察", rebound_watchlist, "觀察分數")
    with col4:
        render_theme_table("超漲轉弱觀察", overheated_watchlist, "風險分數")

    col5, col6 = st.columns(2)
    with col5:
        render_night_signal_table("夜間消息偏多", nightly_positive_watchlist)
    with col6:
        render_night_signal_table("夜間消息偏空", nightly_risk_watchlist)

    today_str = datetime.now().strftime("%Y-%m-%d")
    if report_text is None:
        report_text = reporter.generate_report(
            date_str=today_str,
            watchlist_results=bundle.watchlist_results,
            daily_recommendations=recommendations,
            candidate_results=bundle.candidate_results,
            rebound_watchlist=rebound_watchlist,
            overheated_watchlist=overheated_watchlist,
            nightly_market=nightly_market,
            nightly_positive_watchlist=nightly_positive_watchlist,
            nightly_risk_watchlist=nightly_risk_watchlist,
        )
    if prompt_text is None:
        prompt_text = reporter.generate_prompt(
            date_str=today_str,
            watchlist_results=bundle.watchlist_results,
            daily_recommendations=recommendations,
            candidate_results=bundle.candidate_results,
            rebound_watchlist=rebound_watchlist,
            overheated_watchlist=overheated_watchlist,
            nightly_market=nightly_market,
            nightly_positive_watchlist=nightly_positive_watchlist,
            nightly_risk_watchlist=nightly_risk_watchlist,
        )

    tab1, tab2, tab3, tab4 = st.tabs(["固定追蹤", "候選池", "歷史紀錄", "匯出"])

    with tab1:
        st.subheader("固定追蹤清單")
        for symbol in watchlist:
            if symbol not in bundle.raw_data or symbol not in bundle.evaluations:
                st.warning(f"{symbol} 目前沒有足夠資料。")
                continue
            render_stock_detail(symbol, bundle.raw_data[symbol], bundle.evaluations[symbol])

    with tab2:
        st.subheader("候選池")
        for symbol in candidate_pool:
            if symbol not in bundle.raw_data or symbol not in bundle.evaluations:
                st.warning(f"{symbol} 目前沒有足夠資料。")
                continue
            render_stock_detail(symbol, bundle.raw_data[symbol], bundle.evaluations[symbol])

    with tab3:
        render_history_table(history_rows)

    with tab4:
        st.subheader("匯出內容")
        st.download_button("下載日報", data=report_text, file_name=f"daily_report_{today_str}.md", mime="text/markdown")
        st.markdown("**Markdown 日報**")
        st.code(report_text, language="markdown")
        if prompt_text:
            st.download_button("下載 Prompt", data=prompt_text, file_name=f"chatgpt_input_{today_str}.txt", mime="text/plain")
            st.markdown("**LLM Prompt**")
            st.code(prompt_text, language="markdown")
        else:
            st.info("目前沒有產生 LLM Prompt。")


if __name__ == "__main__":
    main()

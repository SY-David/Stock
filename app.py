from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from config import DAILY_CANDIDATE_POOL, SNAPSHOT_PATH, WATCHLIST, normalize_symbol
from modules.analysis_service import (
    analyze_market,
    get_overheated_watchlist,
    get_rebound_watchlist,
    get_recommendations,
)
from modules.ai_reporter import AIReporter
from modules.site_snapshot import load_snapshot


st.set_page_config(page_title="台股研究助理", layout="wide")


def parse_symbol_text(raw_text: str) -> list[str]:
    return [normalize_symbol(item) for item in raw_text.replace("\n", ",").split(",") if item.strip()]


def format_accuracy(value: float | None) -> str:
    if value is None:
        return "資料不足"
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


def render_metrics(watchlist_results: list[dict], candidate_results: list[dict], recommendations: list[dict]) -> None:
    avg_candidate_score = (sum(item["score"] for item in candidate_results) / len(candidate_results)) if candidate_results else 0
    avg_ml = (sum(item["ml_probability"] for item in candidate_results) / len(candidate_results)) if candidate_results else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("固定追蹤", len(watchlist_results))
    col2.metric("候選池", len(candidate_results))
    col3.metric("今日推薦", len(recommendations))
    col4.metric("候選池平均分", f"{avg_candidate_score:.1f}" if candidate_results else "0.0")
    st.caption(f"候選池平均 ML 勝率：{avg_ml * 100:.1f}%" if candidate_results else "候選池平均 ML 勝率：0.0%")


def render_recommendations(recommendations: list[dict]) -> None:
    st.subheader("今日推薦")
    if not recommendations:
        st.info("今天沒有達到門檻的新推薦。")
        return

    rec_df = pd.DataFrame(
        [
            {
                "股票": f"{item['symbol']} {item['symbol_name']}",
                "總分": item["score"],
                "規則分": item["rule_score"],
                "ML 勝率": f"{item['ml_probability'] * 100:.1f}%",
                "評級": item["rating"],
                "建議": item["action"],
            }
            for item in recommendations
        ]
    )
    st.dataframe(rec_df, use_container_width=True, hide_index=True)


def render_rank_table(title: str, rows: list[dict]) -> None:
    st.subheader(title)
    if not rows:
        st.info("沒有可顯示的資料。")
        return

    df = pd.DataFrame(
        [
            {
                "股票": f"{item['symbol']} {item['symbol_name']}",
                "總分": item["score"],
                "規則分": item["rule_score"],
                "ML 勝率": f"{item['ml_probability'] * 100:.1f}%",
                "趨勢": item["trend"],
                "評級": item["rating"],
            }
            for item in rows
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_theme_table(title: str, rows: list[dict], score_label: str) -> None:
    st.subheader(title)
    if not rows:
        st.info("目前沒有符合條件的股票。")
        return

    df = pd.DataFrame(
        [
            {
                "股票": f"{item['symbol']} {item['symbol_name']}",
                score_label: item["theme_score"],
                "目前評級": item["rating"],
                "ML 勝率": f"{item['ml_probability'] * 100:.1f}%",
                "觀察理由": item["theme_reason"],
            }
            for item in rows
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_glossary() -> None:
    with st.expander("這些分數是什麼？中學生版說明", expanded=False):
        st.markdown(
            "\n".join(
                [
                    "- `總分`：像總成績，越高代表目前整體狀態越好。",
                    "- `規則分`：照固定規則打分，主要看均線、漲跌和量能。",
                    "- `ML 勝率`：電腦估計未來幾天上漲的機率，像天氣預報。",
                    "- `驗證準確率`：模型以前猜題時準不準，不是保證這次一定對。",
                    "- `評級`：把分數翻成白話，例如值得觀察、先保守、先避開。",
                    "- `趨勢`：看最近是走強、整理，還是開始變弱。",
                    "- `建議`：最直接的行動句，像列入觀察、不要追價。",
                    "- `超跌反彈觀察`：不是叫你直接抄底，而是提醒這些股票跌深後可能開始止穩。",
                    "- `超漲轉弱觀察`：不是一定要空，而是提醒這些股票漲多後可能開始拉回。",
                ]
            )
        )


def render_stock_detail(symbol: str, stock_data: dict, result: dict) -> None:
    with st.expander(f"{symbol} {result['symbol_name']}｜{result['rating']}｜{result['score']} 分", expanded=False):
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
                        f"- 評級：`{result['rating']}`",
                        f"- 總分：`{result['score']}`",
                        f"- 規則分：`{result['rule_score']}`",
                        f"- ML：`{result['signal_strength']}`",
                        f"- ML 模型：`{result['ml_model_name']}`",
                        f"- 驗證準確率：`{format_accuracy(result['ml_validation_accuracy'])}`",
                        f"- 可用樣本：`{result['ml_usable_samples']}`",
                        f"- 訓練樣本：`{result['ml_train_samples']}`",
                        f"- 驗證樣本：`{result['ml_validation_samples']}`",
                    ]
                )
            )

        stat1, stat2, stat3 = st.columns(3)
        stat1.metric("收盤價", f"{result['close']:.2f}")
        stat2.metric("5 日報酬", "資料不足" if result["return_5d"] is None else f"{result['return_5d'] * 100:.1f}%")
        stat3.metric("20 日報酬", "資料不足" if result["return_20d"] is None else f"{result['return_20d'] * 100:.1f}%")

        st.markdown("**理由**")
        for item in result["reasons"] or ["資料不足"]:
            st.write(f"- {item}")

        st.markdown("**風險**")
        for item in result["risks"] or ["資料不足"]:
            st.write(f"- {item}")

        if result["warnings"]:
            st.markdown("**資料警示**")
            for item in result["warnings"]:
                st.write(f"- {item}")


def main() -> None:
    st.title("台股自選股研究助理")
    st.caption("官方 TWSE 資料 + 本地快取 + CPU 友善 ML 推薦。")

    reporter = AIReporter()
    default_watchlist_text = ", ".join(WATCHLIST)
    default_candidate_text = ", ".join(DAILY_CANDIDATE_POOL)

    with st.sidebar:
        st.header("設定")
        watchlist_text = st.text_area("固定追蹤", value=default_watchlist_text, height=90)
        candidate_text = st.text_area("每日候選池", value=default_candidate_text, height=180)
        run_button = st.button("即時分析", type="primary", use_container_width=True)
        st.caption("網站預設讀取排程更新的快照；按下即時分析才會重新抓取線上資料。")

    if "bundle" not in st.session_state:
        snapshot = None
        if SNAPSHOT_PATH.exists():
            snapshot = load_saved_snapshot(SNAPSHOT_PATH.stat().st_mtime)

        if snapshot is not None:
            st.session_state["bundle"] = snapshot.bundle
            st.session_state["watchlist"] = snapshot.watchlist_symbols
            st.session_state["candidate_pool"] = snapshot.candidate_symbols
            st.session_state["recommendations"] = snapshot.recommendations
            st.session_state["rebound_watchlist"] = snapshot.rebound_watchlist
            st.session_state["overheated_watchlist"] = snapshot.overheated_watchlist
            st.session_state["report_text"] = snapshot.report_text
            st.session_state["prompt_text"] = snapshot.prompt_text
            st.session_state["data_source_label"] = f"網站快照｜更新於 {snapshot.generated_at}"
        else:
            with st.spinner("正在載入預設追蹤清單與每日候選池..."):
                bundle = load_analysis_bundle(default_watchlist_text, default_candidate_text)
                recommendations = get_recommendations(bundle)
                rebound_watchlist = get_rebound_watchlist(bundle)
                overheated_watchlist = get_overheated_watchlist(bundle)
                today_str = datetime.now().strftime("%Y-%m-%d")
                st.session_state["bundle"] = bundle
                st.session_state["watchlist"] = parse_symbol_text(default_watchlist_text)
                st.session_state["candidate_pool"] = parse_symbol_text(default_candidate_text)
                st.session_state["recommendations"] = recommendations
                st.session_state["rebound_watchlist"] = rebound_watchlist
                st.session_state["overheated_watchlist"] = overheated_watchlist
                st.session_state["report_text"] = reporter.generate_report(
                    date_str=today_str,
                    watchlist_results=bundle.watchlist_results,
                    daily_recommendations=recommendations,
                    candidate_results=bundle.candidate_results,
                    rebound_watchlist=rebound_watchlist,
                    overheated_watchlist=overheated_watchlist,
                )
                st.session_state["prompt_text"] = reporter.generate_prompt(
                    date_str=today_str,
                    watchlist_results=bundle.watchlist_results,
                    daily_recommendations=recommendations,
                    candidate_results=bundle.candidate_results,
                    rebound_watchlist=rebound_watchlist,
                    overheated_watchlist=overheated_watchlist,
                )
                st.session_state["data_source_label"] = "即時分析"

    if run_button:
        watchlist = parse_symbol_text(watchlist_text)
        candidate_pool = parse_symbol_text(candidate_text)
        if not watchlist:
            st.error("請至少輸入一檔固定追蹤股票。")
            return
        if not candidate_pool:
            st.error("請至少輸入一檔每日候選股票。")
            return

        with st.spinner("正在抓取線上資料並建立評分 / ML 訊號..."):
            bundle = load_analysis_bundle(",".join(watchlist), ",".join(candidate_pool))
            recommendations = get_recommendations(bundle)
            rebound_watchlist = get_rebound_watchlist(bundle)
            overheated_watchlist = get_overheated_watchlist(bundle)
            today_str = datetime.now().strftime("%Y-%m-%d")
            st.session_state["bundle"] = bundle
            st.session_state["watchlist"] = watchlist
            st.session_state["candidate_pool"] = candidate_pool
            st.session_state["recommendations"] = recommendations
            st.session_state["rebound_watchlist"] = rebound_watchlist
            st.session_state["overheated_watchlist"] = overheated_watchlist
            st.session_state["report_text"] = reporter.generate_report(
                date_str=today_str,
                watchlist_results=bundle.watchlist_results,
                daily_recommendations=recommendations,
                candidate_results=bundle.candidate_results,
                rebound_watchlist=rebound_watchlist,
                overheated_watchlist=overheated_watchlist,
            )
            st.session_state["prompt_text"] = reporter.generate_prompt(
                date_str=today_str,
                watchlist_results=bundle.watchlist_results,
                daily_recommendations=recommendations,
                candidate_results=bundle.candidate_results,
                rebound_watchlist=rebound_watchlist,
                overheated_watchlist=overheated_watchlist,
            )
            st.session_state["data_source_label"] = f"即時分析｜{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    bundle = st.session_state.get("bundle")
    watchlist = st.session_state.get("watchlist", WATCHLIST)
    candidate_pool = st.session_state.get("candidate_pool", DAILY_CANDIDATE_POOL)
    recommendations = st.session_state.get("recommendations", [])
    rebound_watchlist = st.session_state.get("rebound_watchlist", [])
    overheated_watchlist = st.session_state.get("overheated_watchlist", [])
    report_text = st.session_state.get("report_text")
    prompt_text = st.session_state.get("prompt_text")
    data_source_label = st.session_state.get("data_source_label")
    if bundle is None:
        st.error("目前沒有可用資料。")
        return

    if not bundle.evaluations:
        warning_lines = []
        for symbol, stock_data in bundle.raw_data.items():
            for warning in stock_data.get("warnings", []):
                warning_lines.append(f"{symbol}: {warning}")

        if warning_lines:
            st.error("目前沒有可用資料，主因如下：")
            for line in warning_lines[:8]:
                st.write(f"- {line}")
        else:
            st.error("目前沒有可用資料。")
        st.info("目前版本改抓官方 TWSE 資料。若暫時沒資料，通常是來源暫時無回應或該股票不在已支援的官方接口內。")
        return

    watchlist_results = bundle.watchlist_results
    candidate_results = bundle.candidate_results
    if data_source_label:
        st.caption(f"資料模式：{data_source_label}")

    render_metrics(watchlist_results, candidate_results, recommendations)
    render_glossary()
    render_recommendations(recommendations)

    top_candidates = candidate_results[:5]
    weak_candidates = [item for item in candidate_results if item["score"] < 50][:5]

    col1, col2 = st.columns(2)
    with col1:
        render_rank_table("候選池前段班", top_candidates)
    with col2:
        render_rank_table("候選池偏弱股", weak_candidates)

    col3, col4 = st.columns(2)
    with col3:
        render_theme_table("超跌反彈觀察", rebound_watchlist, "反彈觀察分")
    with col4:
        render_theme_table("超漲轉弱觀察", overheated_watchlist, "轉弱風險分")

    today_str = datetime.now().strftime("%Y-%m-%d")
    if report_text is None:
        report_text = reporter.generate_report(
            date_str=today_str,
            watchlist_results=watchlist_results,
            daily_recommendations=recommendations,
            candidate_results=candidate_results,
            rebound_watchlist=rebound_watchlist,
            overheated_watchlist=overheated_watchlist,
        )
    if prompt_text is None:
        prompt_text = reporter.generate_prompt(
            date_str=today_str,
            watchlist_results=watchlist_results,
            daily_recommendations=recommendations,
            candidate_results=candidate_results,
            rebound_watchlist=rebound_watchlist,
            overheated_watchlist=overheated_watchlist,
        )

    tab1, tab2, tab3 = st.tabs(["固定追蹤", "每日候選池", "匯出"])

    with tab1:
        st.subheader("固定追蹤清單")
        for symbol in watchlist:
            if symbol not in bundle.raw_data or symbol not in bundle.evaluations:
                st.warning(f"{symbol} 目前沒有足夠資料。")
                continue
            render_stock_detail(symbol, bundle.raw_data[symbol], bundle.evaluations[symbol])

    with tab2:
        st.subheader("每日候選池")
        for symbol in candidate_pool:
            if symbol not in bundle.raw_data or symbol not in bundle.evaluations:
                st.warning(f"{symbol} 目前沒有足夠資料。")
                continue
            render_stock_detail(symbol, bundle.raw_data[symbol], bundle.evaluations[symbol])

    with tab3:
        st.subheader("匯出內容")
        st.download_button("下載日報", data=report_text, file_name=f"daily_report_{today_str}.md", mime="text/markdown")
        st.markdown("**Markdown 日報**")
        st.code(report_text, language="markdown")
        if prompt_text:
            st.download_button("下載 Prompt", data=prompt_text, file_name=f"chatgpt_input_{today_str}.txt", mime="text/plain")
            st.markdown("**LLM Prompt**")
            st.code(prompt_text, language="markdown")
        else:
            st.info("這份快照沒有產生 LLM Prompt。")


if __name__ == "__main__":
    main()

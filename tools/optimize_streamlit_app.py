from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
PAPER_PATH = ROOT / "modules" / "paper_trading.py"


def optimize_app() -> None:
    text = APP_PATH.read_text(encoding="utf-8")

    if 'run_button = st.button("重新分析"' in text:
        text = text.replace(
            '        run_button = st.button("重新分析", type="primary", use_container_width=True)\n'
            '        st.caption("若網站正在讀快照，重新分析只會更新目前這個頁面，不會覆蓋正式快照。")\n',
            '        reload_button = st.button("重新載入每日快照", type="primary", use_container_width=True)\n'
            '        st.caption("網站只讀取 GitHub Actions 產生的每日快照，避免在免費主機上重跑大量抓取與模型訓練。")\n',
            1,
        )

        fallback_start = text.find(
            '        else:\n            with st.spinner("正在抓取線上資料並建立分析..."):\n'
        )
        refresh_start = text.find('    if run_button:\n', fallback_start)
        if fallback_start < 0 or refresh_start < 0:
            raise RuntimeError("Could not locate the initial live-analysis fallback")
        text = (
            text[:fallback_start]
            + '        else:\n            st.session_state["snapshot_load_error"] = True\n\n'
            + text[refresh_start:]
        )

        refresh_start = text.find('    if run_button:\n')
        bundle_start = text.find(
            '    bundle = st.session_state.get("bundle")\n', refresh_start
        )
        if refresh_start < 0 or bundle_start < 0:
            raise RuntimeError("Could not locate the live refresh block")
        reload_block = '''    if reload_button:
        st.cache_data.clear()
        st.cache_resource.clear()
        for key in (
            "bundle",
            "watchlist",
            "candidate_pool",
            "recommendations",
            "rebound_watchlist",
            "overheated_watchlist",
            "nightly_positive_watchlist",
            "nightly_risk_watchlist",
            "nightly_market",
            "report_text",
            "prompt_text",
            "data_source_label",
            "update_status",
            "live_refresh_error",
            "snapshot_load_error",
        ):
            st.session_state.pop(key, None)
        st.rerun()

'''
        text = text[:refresh_start] + reload_block + text[bundle_start:]

        text = text.replace(
            '        st.error("目前沒有可用資料。")\n',
            '        st.error("目前沒有可用快照；請到 GitHub Actions 執行 Refresh Site Snapshot。")\n',
            1,
        )

    if 'key="main_section"' not in text:
        replacements = {
            "@st.cache_data(ttl=600, show_spinner=False)\ndef load_analysis_bundle":
                "@st.cache_data(ttl=600, max_entries=2, show_spinner=False)\ndef load_analysis_bundle",
            "@st.cache_data(ttl=60, show_spinner=False)\ndef load_saved_snapshot":
                "@st.cache_resource(max_entries=2, show_spinner=False)\ndef load_saved_snapshot",
            "@st.cache_data(ttl=60, show_spinner=False)\ndef load_saved_status":
                "@st.cache_data(ttl=60, max_entries=2, show_spinner=False)\ndef load_saved_status",
            "@st.cache_data(ttl=60, show_spinner=False)\ndef load_history_rows":
                "@st.cache_data(ttl=300, max_entries=2, show_spinner=False)\ndef load_history_rows",
            "@st.cache_data(ttl=60, show_spinner=False)\ndef load_paper_trading_result":
                "@st.cache_data(ttl=300, max_entries=2, show_spinner=False)\ndef load_paper_trading_result",
            "    history_rows = load_history_rows(history_marker())\n"
            "    snapshot_mtime = SNAPSHOT_PATH.stat().st_mtime if SNAPSHOT_PATH.exists() else None\n"
            "    paper_trading_result = load_paper_trading_result(history_marker(), snapshot_mtime)\n\n": "",
        }
        for old, new in replacements.items():
            if old not in text:
                raise RuntimeError(f"Expected app.py fragment not found: {old[:80]!r}")
            text = text.replace(old, new, 1)

        start_marker = (
            '    tab1, tab2, tab3, tab4, tab5 = st.tabs('
            '["固定追蹤", "候選池", "模擬帳戶", "歷史紀錄", "匯出"])\n'
        )
        end_marker = '\n\nif __name__ == "__main__":\n'
        start = text.find(start_marker)
        end = text.find(end_marker, start)
        if start < 0 or end < 0:
            raise RuntimeError("Could not locate the original tab section in app.py")

        lazy_section = '''    section = st.radio(
        "檢視內容",
        ["固定追蹤", "候選池", "模擬帳戶", "歷史紀錄", "匯出"],
        horizontal=True,
        key="main_section",
    )

    if section == "固定追蹤":
        available = [
            symbol
            for symbol in watchlist
            if symbol in bundle.raw_data and symbol in bundle.evaluations
        ]
        if not available:
            st.info("固定追蹤清單目前沒有足夠資料。")
        else:
            symbol = st.selectbox("選擇固定追蹤股票", available)
            render_stock_detail(symbol, bundle.raw_data[symbol], bundle.evaluations[symbol])

    elif section == "候選池":
        available = [
            symbol
            for symbol in candidate_pool
            if symbol in bundle.raw_data and symbol in bundle.evaluations
        ]
        if not available:
            st.info("候選池目前沒有足夠資料。")
        else:
            symbol = st.selectbox("選擇候選股票", available)
            render_stock_detail(symbol, bundle.raw_data[symbol], bundle.evaluations[symbol])

    elif section == "模擬帳戶":
        with st.spinner("正在讀取精簡歷史資料並計算模擬帳戶..."):
            snapshot_mtime = SNAPSHOT_PATH.stat().st_mtime if SNAPSHOT_PATH.exists() else None
            paper_trading_result = load_paper_trading_result(
                history_marker(), snapshot_mtime
            )
        render_paper_trading(paper_trading_result)

    elif section == "歷史紀錄":
        with st.spinner("正在讀取歷史紀錄..."):
            history_rows = load_history_rows(history_marker())
        render_history_table(history_rows)

    else:
        st.subheader("匯出內容")
        st.download_button(
            "下載日報",
            data=report_text,
            file_name=f"daily_report_{today_str}.md",
            mime="text/markdown",
        )
        st.markdown("**Markdown 日報**")
        st.code(report_text, language="markdown")
        if prompt_text:
            st.download_button(
                "下載 Prompt",
                data=prompt_text,
                file_name=f"chatgpt_input_{today_str}.txt",
                mime="text/plain",
            )
            st.markdown("**LLM Prompt**")
            st.code(prompt_text, language="markdown")
        else:
            st.info("目前沒有產生 LLM Prompt。")
'''
        text = text[:start] + lazy_section + text[end:]

    compile(text, str(APP_PATH), "exec")
    APP_PATH.write_text(text, encoding="utf-8")
    print("Optimized app.py for snapshot-only, lazy rendering and bounded caches")


def fix_paper_trading_price_lookup() -> None:
    text = PAPER_PATH.read_text(encoding="utf-8")
    old = (
        '        if row_date == current_date:\n'
        '            return row\n'
        '        if row_date < current_date:\n'
        '            break\n'
    )
    new = '        if row_date <= current_date:\n            return row\n'
    if old in text:
        text = text.replace(old, new, 1)
        compile(text, str(PAPER_PATH), "exec")
        PAPER_PATH.write_text(text, encoding="utf-8")
        print("Fixed paper-trading price lookup for holidays and non-trading days")
    elif new in text:
        print("paper_trading.py price lookup is already fixed")
    else:
        raise RuntimeError("Could not locate paper-trading price lookup")


def main() -> None:
    optimize_app()
    fix_paper_trading_price_lookup()


if __name__ == "__main__":
    main()

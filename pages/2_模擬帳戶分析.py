from __future__ import annotations

import pandas as pd
import streamlit as st

from modules.paper_trading import simulate_paper_portfolio
from modules.portfolio_analytics import analyze_portfolio


st.set_page_config(page_title="模擬帳戶分析", page_icon="📊", layout="wide")

st.title("模擬帳戶分析")
st.caption("沿用主程式的完整歷史模擬結果，補上回撤、波動、交易品質與匯出功能。")

result = simulate_paper_portfolio()
analytics = analyze_portfolio(result)

if not result.daily_records:
    st.warning("目前沒有可分析的模擬帳戶歷史。")
    st.stop()

metric_row_1 = st.columns(4)
metric_row_1[0].metric("總資產", f"{result.total_assets:,.0f}")
metric_row_1[1].metric("總報酬率", f"{result.total_return_pct:.2f}%")
metric_row_1[2].metric("最大回撤", f"-{analytics.max_drawdown_pct:.2f}%")
metric_row_1[3].metric("市場曝險時間", f"{analytics.exposure_pct:.1f}%")

metric_row_2 = st.columns(4)
metric_row_2[0].metric("年化波動率", f"{analytics.annualized_volatility_pct:.2f}%")
metric_row_2[1].metric(
    "Sharpe Ratio",
    f"{analytics.sharpe_ratio:.2f}" if analytics.sharpe_ratio is not None else "—",
)
metric_row_2[2].metric(
    "Profit Factor",
    f"{analytics.profit_factor:.2f}"
    if analytics.profit_factor is not None
    else ("∞" if analytics.gross_profit > 0 else "—"),
)
metric_row_2[3].metric("已平倉交易", f"{result.closed_trade_count}")

with st.expander("指標說明"):
    st.markdown(
        """
- **最大回撤**：資產從歷史高點跌到後續低點的最大幅度。
- **年化波動率**：以每日資產報酬率估計並乘上 $\sqrt{252}$。
- **Sharpe Ratio**：未扣無風險利率；歷史天數太少或波動為零時顯示 `—`。
- **Profit Factor**：所有獲利交易總額除以所有虧損交易絕對值。
- **市場曝險時間**：每日紀錄中至少持有一個部位的比例。
        """
    )
    if analytics.max_drawdown_start and analytics.max_drawdown_end:
        st.write(
            f"最大回撤區間：{analytics.max_drawdown_start} → {analytics.max_drawdown_end}"
        )

st.subheader("資產曲線")
equity_df = pd.DataFrame(result.daily_records)
equity_df["date"] = pd.to_datetime(equity_df["date"])
st.line_chart(
    equity_df.set_index("date")[["total_assets"]],
    width="stretch",
)

st.subheader("回撤曲線")
drawdown_df = pd.DataFrame(analytics.drawdown_series)
drawdown_df["date"] = pd.to_datetime(drawdown_df["date"])
st.line_chart(
    drawdown_df.set_index("date")[["drawdown_pct"]],
    width="stretch",
)

st.subheader("月度報酬")
monthly_df = pd.DataFrame(analytics.monthly_returns)
if monthly_df.empty:
    st.info("目前尚不足以計算月度報酬。")
else:
    monthly_display = monthly_df.rename(
        columns={
            "month": "月份",
            "start_assets": "月初資產",
            "end_assets": "月末資產",
            "return_pct": "月報酬率 (%)",
        }
    )
    st.dataframe(monthly_display, hide_index=True, width="stretch")

st.subheader("已平倉交易品質")
trade_quality = pd.DataFrame(
    [
        {"指標": "總獲利", "數值": analytics.gross_profit},
        {"指標": "總虧損", "數值": analytics.gross_loss},
        {"指標": "平均獲利", "數值": analytics.average_win},
        {"指標": "平均虧損", "數值": analytics.average_loss},
        {
            "指標": "最佳單筆報酬率 (%)",
            "數值": analytics.best_trade_return_pct,
        },
        {
            "指標": "最差單筆報酬率 (%)",
            "數值": analytics.worst_trade_return_pct,
        },
    ]
)
st.dataframe(trade_quality, hide_index=True, width="stretch")

st.subheader("資料匯出")
trades_df = pd.DataFrame(result.trades)
download_columns = st.columns(2)
download_columns[0].download_button(
    "下載交易紀錄 CSV",
    data=trades_df.to_csv(index=False).encode("utf-8-sig"),
    file_name="paper_trades.csv",
    mime="text/csv",
    disabled=trades_df.empty,
)
download_columns[1].download_button(
    "下載每日資產 CSV",
    data=equity_df.to_csv(index=False).encode("utf-8-sig"),
    file_name="paper_equity_curve.csv",
    mime="text/csv",
)

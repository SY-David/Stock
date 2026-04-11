from __future__ import annotations

from pathlib import Path

from config import OUTPUT_DIR, RECOMMENDATION_MIN_SCORE, RECOMMENDATION_TOP_N, REPORT_TOP_N


class AIReporter:
    def generate_report(
        self,
        date_str: str,
        watchlist_results: list[dict],
        daily_recommendations: list[dict],
        candidate_results: list[dict],
        rebound_watchlist: list[dict] | None = None,
        overheated_watchlist: list[dict] | None = None,
    ) -> str:
        market_summary = self._summarize_market(candidate_results)
        rebound_watchlist = rebound_watchlist or []
        overheated_watchlist = overheated_watchlist or []

        lines = [
            f"# 台股自選股日報 ({date_str})",
            "",
            "## 市場總評",
            f"- 候選池狀態：{market_summary['market_bias']}",
            f"- 固定追蹤檔數：{len(watchlist_results)}",
            f"- 每日候選池檔數：{len(candidate_results)}",
            f"- 候選池平均分數：{market_summary['average_score']:.1f} / 100",
            f"- 候選池強勢標的數：{market_summary['strong_count']} 檔",
            f"- 候選池偏弱標的數：{market_summary['weak_count']} 檔",
            "",
            "## 今日推薦",
        ]

        if daily_recommendations:
            for item in daily_recommendations:
                lines.extend(self._format_stock_block(item, compact=False))
        else:
            lines.extend(["- 今天沒有達到門檻的新推薦。", ""])

        lines.append("## 候選池前段班")
        candidate_top = candidate_results[:REPORT_TOP_N]
        if candidate_top:
            for item in candidate_top:
                lines.append(
                    f"- {item['symbol']} {item['symbol_name']}｜{item['score']} 分｜"
                    f"{item['rating']}｜{item['signal_strength']}"
                )
        else:
            lines.append("- 今日沒有足夠資料可供排序。")

        weak_names = [item for item in candidate_results if item["score"] < 50][:REPORT_TOP_N]
        lines.extend(["", "## 今日應保守處理"])
        if weak_names:
            for item in weak_names:
                lines.append(
                    f"- {item['symbol']} {item['symbol_name']}｜{item['score']} 分｜{item['action']}｜"
                    f"{self._join_or_fallback(item['risks'])}"
                )
        else:
            lines.append("- 目前候選池沒有明顯低於 50 分的標的。")

        lines.extend(["", "## 超跌反彈觀察"])
        if rebound_watchlist:
            for item in rebound_watchlist:
                lines.append(self._format_theme_line(item, "反彈觀察分"))
        else:
            lines.append("- 目前沒有明顯跌深後轉穩的標的。")

        lines.extend(["", "## 超漲轉弱觀察"])
        if overheated_watchlist:
            for item in overheated_watchlist:
                lines.append(self._format_theme_line(item, "轉弱風險分"))
        else:
            lines.append("- 目前沒有明顯短線過熱的標的。")

        lines.extend(["", "## 固定追蹤清單"])
        if watchlist_results:
            for item in watchlist_results:
                lines.extend(self._format_stock_block(item, compact=True))
        else:
            lines.append("- 目前固定追蹤清單沒有足夠資料。")

        lines.extend(["", "## 今日推薦詳細說明"])
        if daily_recommendations:
            for item in daily_recommendations:
                lines.extend(self._format_stock_detail(item))
        else:
            lines.append("- 今天沒有達到門檻的新推薦。")

        lines.extend(
            [
                "",
                "## 資料來源與限制",
                "- 資料來源：TWSE 官方公開資料，即時抓取並快取。",
                "- 報告用途：自選股研究整理，不是交易保證。",
                "- 目前版本以價格量能為主，未額外載入法人、估值、月營收資料。",
            ]
        )

        return "\n".join(lines).strip() + "\n"

    def generate_prompt(
        self,
        date_str: str,
        watchlist_results: list[dict],
        daily_recommendations: list[dict],
        candidate_results: list[dict],
        rebound_watchlist: list[dict] | None = None,
        overheated_watchlist: list[dict] | None = None,
    ) -> str:
        rebound_watchlist = rebound_watchlist or []
        overheated_watchlist = overheated_watchlist or []
        recommendation_blocks = [self._format_prompt_block(item) for item in daily_recommendations]
        watchlist_blocks = [self._format_prompt_block(item) for item in watchlist_results]
        candidate_top_blocks = [self._format_prompt_block(item) for item in candidate_results[:REPORT_TOP_N]]
        rebound_blocks = [self._format_theme_prompt_block(item, "oversold_rebound") for item in rebound_watchlist]
        overheated_blocks = [self._format_theme_prompt_block(item, "overheated_pullback") for item in overheated_watchlist]

        recommendation_body = "\n\n".join(recommendation_blocks) if recommendation_blocks else "- 今日無達標推薦"
        watchlist_body = "\n\n".join(watchlist_blocks) if watchlist_blocks else "- 固定追蹤資料不足"
        candidate_top_body = "\n\n".join(candidate_top_blocks) if candidate_top_blocks else "- 候選池資料不足"
        rebound_body = "\n\n".join(rebound_blocks) if rebound_blocks else "- 無明顯超跌反彈觀察標的"
        overheated_body = "\n\n".join(overheated_blocks) if overheated_blocks else "- 無明顯超漲轉弱觀察標的"

        return (
            f"你是台股研究助理。日期是 {date_str}。\n"
            "請根據以下結構化資料，輸出保守、可解釋、以風險為先的每日研究摘要。\n"
            "不要捏造資料，不要保證報酬，遇到資料不足要明確指出。\n\n"
            "請輸出：\n"
            "1. 市場總評\n"
            "2. 今日推薦名單（最多 3 檔，若不足就明說）\n"
            "3. 固定追蹤清單評價\n"
            "4. 今日應保守處理名單\n"
            "5. 超跌反彈觀察名單\n"
            "6. 超漲轉弱觀察名單\n"
            "7. 今晚或明日需要注意的重點\n\n"
            f"【今日推薦】\n{recommendation_body}\n\n"
            f"【固定追蹤】\n{watchlist_body}\n\n"
            f"【候選池前段班】\n{candidate_top_body}\n\n"
            f"【超跌反彈觀察】\n{rebound_body}\n\n"
            f"【超漲轉弱觀察】\n{overheated_body}\n"
        )

    def save_report(self, report_text: str, filename: str) -> str:
        output_dir = Path(OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / filename
        path.write_text(report_text, encoding="utf-8")
        return str(path)

    @staticmethod
    def select_recommendations(ordered_results: list[dict]) -> list[dict]:
        recommended = [
            item
            for item in ordered_results
            if item["score"] >= RECOMMENDATION_MIN_SCORE
            and item["rating"] in {"Strong Watch", "Watch"}
            and item["trend"] != "弱勢下彎"
            and item.get("ml_probability", 0) >= 0.55
            and (item.get("ml_validation_accuracy") is None or item.get("ml_validation_accuracy", 0) >= 0.45)
        ]
        return recommended[:RECOMMENDATION_TOP_N]

    def _format_stock_block(self, item: dict, compact: bool) -> list[str]:
        lines = [
            f"### {item['symbol']} {item['symbol_name']}",
            f"- 評級：{item['rating']} ({item['score']} 分)",
            f"- 規則分數：{item['rule_score']} 分",
            f"- 建議：{item['action']}",
            f"- 趨勢：{item['trend']}",
            f"- 量化訊號：{item['signal_strength']}",
            f"- ML 模型：{self._format_ml_summary(item)}",
            f"- 理由：{self._join_or_fallback(item['reasons'])}",
            f"- 風險：{self._join_or_fallback(item['risks'])}",
            f"- 關鍵數據：{self._format_snapshot(item)}",
        ]
        if item["warnings"]:
            lines.append(f"- 資料警示：{'；'.join(item['warnings'])}")
        lines.append("")

        if compact:
            return lines
        return lines

    def _format_stock_detail(self, item: dict) -> list[str]:
        lines = [
            f"### {item['symbol']} {item['symbol_name']}",
            f"- 產業：{item['sector']}",
            f"- 評級：{item['rating']} ({item['score']} 分)",
            f"- 規則分數：{item['rule_score']} 分",
            f"- 建議：{item['action']}",
            f"- 趨勢：{item['trend']}",
            f"- ML：{self._format_ml_summary(item)}",
            f"- 籌碼：{self._format_institutional(item)}",
            f"- 估值：{self._format_valuation(item)}",
            f"- 月營收：{self._format_revenue(item)}",
            f"- 技術面：{self._format_technical(item)}",
            f"- 理由：{self._join_or_fallback(item['reasons'])}",
            f"- 風險：{self._join_or_fallback(item['risks'])}",
        ]
        if item["warnings"]:
            lines.append(f"- 資料警示：{'；'.join(item['warnings'])}")
        lines.append("")
        return lines

    def _format_prompt_block(self, item: dict) -> str:
        return "\n".join(
            [
                f"- {item['symbol']} {item['symbol_name']}",
                f"  - score: {item['score']}",
                f"  - rule_score: {item['rule_score']}",
                f"  - rating: {item['rating']}",
                f"  - action: {item['action']}",
                f"  - trend: {item['trend']}",
                f"  - signal_strength: {item['signal_strength']}",
                f"  - ml_summary: {self._format_ml_summary(item)}",
                f"  - reasons: {self._join_or_fallback(item['reasons'])}",
                f"  - risks: {self._join_or_fallback(item['risks'])}",
                f"  - valuation: {self._format_valuation(item)}",
                f"  - revenue: {self._format_revenue(item)}",
                f"  - technical: {self._format_technical(item)}",
            ]
        )

    @staticmethod
    def _format_theme_line(item: dict, score_label: str) -> str:
        return (
            f"- {item['symbol']} {item['symbol_name']}｜{score_label} {item['theme_score']}｜"
            f"{item['theme_reason']}"
        )

    @staticmethod
    def _format_theme_prompt_block(item: dict, theme_name: str) -> str:
        return "\n".join(
            [
                f"- {item['symbol']} {item['symbol_name']}",
                f"  - theme: {theme_name}",
                f"  - theme_score: {item['theme_score']}",
                f"  - theme_reason: {item['theme_reason']}",
                f"  - score: {item['score']}",
                f"  - rating: {item['rating']}",
                f"  - ml_probability: {item['ml_probability']:.2f}",
            ]
        )

    @staticmethod
    def _join_or_fallback(items: list[str]) -> str:
        return "；".join(items) if items else "資料不足"

    @staticmethod
    def _signed(value: int) -> str:
        if value > 0:
            return f"+{value:,}"
        return f"{value:,}"

    @staticmethod
    def _format_snapshot(item: dict) -> str:
        parts = [
            f"收盤 {item['close']:.2f}",
            f"5 日報酬 {AIReporter._format_pct(item.get('return_5d'))}",
            f"20 日報酬 {AIReporter._format_pct(item.get('return_20d'))}",
            f"量比 {item['volume_ratio']:.2f}" if item.get("volume_ratio") is not None else "量比資料不足",
        ]
        return "｜".join(parts)

    @staticmethod
    def _format_valuation(item: dict) -> str:
        if not item.get("has_valuation_data"):
            return "官方價格量能版未載入估值資料"
        pe = f"PE {item['pe_ratio']:.1f}" if item.get("pe_ratio") is not None else "PE 無資料"
        pb = f"PBR {item['pb_ratio']:.1f}" if item.get("pb_ratio") is not None else "PBR 無資料"
        dividend = (
            f"殖利率 {item['dividend_yield']:.2f}%"
            if item.get("dividend_yield") is not None
            else "殖利率無資料"
        )
        return f"{pe}｜{pb}｜{dividend}"

    @staticmethod
    def _format_revenue(item: dict) -> str:
        if not item.get("has_revenue_data"):
            return "官方價格量能版未載入月營收資料"
        latest = item.get("latest_revenue_month") or "無資料"
        yoy = AIReporter._format_pct(item.get("revenue_yoy"))
        mom = AIReporter._format_pct(item.get("revenue_mom"))
        return f"{latest}｜YoY {yoy}｜MoM {mom}"

    @staticmethod
    def _format_technical(item: dict) -> str:
        parts = [f"收盤 {item['close']:.2f}"]
        if item.get("ma5") is not None:
            parts.append(f"MA5 {item['ma5']:.2f}")
        if item.get("ma20") is not None:
            parts.append(f"MA20 {item['ma20']:.2f}")
        if item.get("ma60") is not None:
            parts.append(f"MA60 {item['ma60']:.2f}")
        if item.get("margin_usage") is not None:
            parts.append(f"融資使用率 {item['margin_usage'] * 100:.1f}%")
        return "｜".join(parts)

    @staticmethod
    def _format_pct(value: float | None) -> str:
        if value is None:
            return "資料不足"
        return f"{value * 100:.1f}%"

    @staticmethod
    def _format_ml_summary(item: dict) -> str:
        accuracy = item.get("ml_validation_accuracy")
        accuracy_text = "驗證資料不足" if accuracy is None else f"驗證準確率 {accuracy * 100:.1f}%"
        usable_samples = item.get("ml_usable_samples", 0)
        train_samples = item.get("ml_train_samples", 0)
        validation_samples = item.get("ml_validation_samples", 0)
        return (
            f"{item['ml_model_name']}｜{item['signal_strength']}｜{accuracy_text}｜"
            f"可用 {usable_samples}｜訓練 {train_samples}｜驗證 {validation_samples}"
        )

    @staticmethod
    def _format_institutional(item: dict) -> str:
        if not item.get("has_institutional_data"):
            return "官方價格量能版未載入法人籌碼資料"
        return f"外資 3 日 {AIReporter._signed(item['foreign_net_buy_3d'])} 張，投信 3 日 {AIReporter._signed(item['trust_net_buy_3d'])} 張"

    @staticmethod
    def _summarize_market(ordered_results: list[dict]) -> dict:
        if not ordered_results:
            return {
                "market_bias": "資料不足",
                "average_score": 0.0,
                "strong_count": 0,
                "weak_count": 0,
            }

        scores = [item["score"] for item in ordered_results]
        average_score = sum(scores) / len(scores)
        strong_count = sum(1 for item in ordered_results if item["score"] >= 60)
        weak_count = sum(1 for item in ordered_results if item["score"] < 50)

        if average_score >= 65:
            market_bias = "偏多"
        elif average_score <= 45:
            market_bias = "偏空"
        else:
            market_bias = "中性"

        return {
            "market_bias": market_bias,
            "average_score": average_score,
            "strong_count": strong_count,
            "weak_count": weak_count,
        }

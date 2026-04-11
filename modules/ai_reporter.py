from __future__ import annotations

from pathlib import Path

from app_config import OUTPUT_DIR, RECOMMENDATION_MIN_SCORE, RECOMMENDATION_TOP_N, REPORT_TOP_N


class AIReporter:
    def generate_report(
        self,
        date_str: str,
        watchlist_results: list[dict],
        daily_recommendations: list[dict],
        candidate_results: list[dict],
        rebound_watchlist: list[dict] | None = None,
        overheated_watchlist: list[dict] | None = None,
        nightly_market: dict | None = None,
        nightly_positive_watchlist: list[dict] | None = None,
        nightly_risk_watchlist: list[dict] | None = None,
    ) -> str:
        market_summary = self._summarize_market(candidate_results)
        rebound_watchlist = rebound_watchlist or []
        overheated_watchlist = overheated_watchlist or []
        nightly_market = nightly_market or {}
        nightly_positive_watchlist = nightly_positive_watchlist or []
        nightly_risk_watchlist = nightly_risk_watchlist or []

        lines = [
            f"# 台股自選股研究日報 ({date_str})",
            "",
            "## 市場摘要",
            f"- 候選池整體偏向: {market_summary['market_bias']}",
            f"- 固定追蹤檔數: {len(watchlist_results)}",
            f"- 候選池檔數: {len(candidate_results)}",
            f"- 候選池平均分數: {market_summary['average_score']:.1f} / 100",
            f"- 候選池綠燈數: {market_summary['green_count']} 檔",
            f"- 候選池紅燈數: {market_summary['red_count']} 檔",
            "",
            "## 今晚到明早總覽",
            f"- 夜間市場偏向: {nightly_market.get('market_bias', '中性')}",
            f"- 夜間市場分數: {nightly_market.get('macro_score', 0)}",
            f"- 夜間摘要: {nightly_market.get('summary', '夜間消息偏中性')}",
            "",
            "## 明日推薦",
        ]

        if daily_recommendations:
            for item in daily_recommendations:
                lines.extend(self._format_recommendation_block(item))
        else:
            lines.extend(["- 今天沒有達到門檻的新推薦。", ""])

        lines.extend(["## 候選池前段班"])
        if candidate_results:
            for item in candidate_results[:REPORT_TOP_N]:
                lines.append(
                    f"- {item['symbol']} {item['symbol_name']} | 明日 {item.get('tomorrow_light', '黃燈')} | "
                    f"明日分數 {item.get('tomorrow_score', item['score'])} | "
                    f"{item.get('tomorrow_action', item['action'])}"
                )
        else:
            lines.append("- 候選池目前沒有可用資料。")

        lines.extend(["", "## 偏弱或先觀望"])
        weak_names = [item for item in candidate_results if item.get("tomorrow_light") == "紅燈"][:REPORT_TOP_N]
        if weak_names:
            for item in weak_names:
                lines.append(
                    f"- {item['symbol']} {item['symbol_name']} | 明日分數 {item.get('tomorrow_score', item['score'])} | "
                    f"{item.get('tomorrow_reason', self._join_or_fallback(item.get('risks', [])))}"
                )
        else:
            lines.append("- 目前沒有明顯紅燈標的。")

        lines.extend(["", "## 超跌反彈觀察"])
        if rebound_watchlist:
            for item in rebound_watchlist:
                lines.append(self._format_theme_line(item, "反彈觀察分數"))
        else:
            lines.append("- 目前沒有明顯跌深後轉穩的標的。")

        lines.extend(["", "## 超漲轉弱觀察"])
        if overheated_watchlist:
            for item in overheated_watchlist:
                lines.append(self._format_theme_line(item, "轉弱風險分數"))
        else:
            lines.append("- 目前沒有明顯短線過熱的標的。")

        lines.extend(["", "## 夜間消息偏多"])
        if nightly_positive_watchlist:
            for item in nightly_positive_watchlist:
                lines.append(self._format_night_line(item))
        else:
            lines.append("- 今晚沒有明顯偏多事件加分。")

        lines.extend(["", "## 夜間消息偏空"])
        if nightly_risk_watchlist:
            for item in nightly_risk_watchlist:
                lines.append(self._format_night_line(item))
        else:
            lines.append("- 今晚沒有明顯偏空事件風險。")

        lines.extend(["", "## 固定追蹤清單"])
        if watchlist_results:
            for item in watchlist_results:
                lines.extend(self._format_stock_block(item, compact=True))
        else:
            lines.append("- 固定追蹤清單沒有足夠資料。")

        lines.extend(["", "## 明日決策細節"])
        if daily_recommendations:
            for item in daily_recommendations:
                lines.extend(self._format_stock_detail(item))
        else:
            lines.append("- 今天沒有新推薦。")

        lines.extend(
            [
                "",
                "## 使用說明",
                "- 明日燈號是把原始分數和夜間事件一起看後的結果，適合盤後到隔天開盤前參考。",
                "- 夜間事件層以公開新聞標題、重大訊息、法說與財經關鍵字做規則判讀，屬於輔助訊號。",
                "- 若更新失敗，網站會沿用上一版快照，不會直接清空。",
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
        nightly_market: dict | None = None,
        nightly_positive_watchlist: list[dict] | None = None,
        nightly_risk_watchlist: list[dict] | None = None,
    ) -> str:
        rebound_watchlist = rebound_watchlist or []
        overheated_watchlist = overheated_watchlist or []
        nightly_market = nightly_market or {}
        nightly_positive_watchlist = nightly_positive_watchlist or []
        nightly_risk_watchlist = nightly_risk_watchlist or []

        recommendation_body = "\n\n".join(self._format_prompt_block(item) for item in daily_recommendations) or "- 沒有新推薦"
        watchlist_body = "\n\n".join(self._format_prompt_block(item) for item in watchlist_results) or "- 固定追蹤沒有可用資料"
        candidate_top_body = "\n\n".join(
            self._format_prompt_block(item) for item in candidate_results[:REPORT_TOP_N]
        ) or "- 候選池沒有可用資料"
        rebound_body = "\n\n".join(
            self._format_theme_prompt_block(item, "oversold_rebound") for item in rebound_watchlist
        ) or "- 沒有超跌反彈觀察標的"
        overheated_body = "\n\n".join(
            self._format_theme_prompt_block(item, "overheated_pullback") for item in overheated_watchlist
        ) or "- 沒有超漲轉弱觀察標的"
        nightly_positive_body = "\n\n".join(
            self._format_night_prompt_block(item) for item in nightly_positive_watchlist
        ) or "- 沒有夜間偏多個股"
        nightly_risk_body = "\n\n".join(
            self._format_night_prompt_block(item) for item in nightly_risk_watchlist
        ) or "- 沒有夜間偏空個股"

        return (
            f"請根據以下台股資料，生成 {date_str} 的明日盤前整理。\n"
            "重點請放在：明日推薦、明日燈號、夜間消息如何修正原本分數、以及風險提醒。\n\n"
            "【夜間市場總覽】\n"
            f"- market_bias: {nightly_market.get('market_bias', '中性')}\n"
            f"- macro_score: {nightly_market.get('macro_score', 0)}\n"
            f"- summary: {nightly_market.get('summary', '夜間消息偏中性')}\n\n"
            f"【明日推薦】\n{recommendation_body}\n\n"
            f"【固定追蹤】\n{watchlist_body}\n\n"
            f"【候選池前段班】\n{candidate_top_body}\n\n"
            f"【超跌反彈】\n{rebound_body}\n\n"
            f"【超漲轉弱】\n{overheated_body}\n\n"
            f"【夜間消息偏多】\n{nightly_positive_body}\n\n"
            f"【夜間消息偏空】\n{nightly_risk_body}\n"
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
            if item.get("tomorrow_score", item["score"]) >= RECOMMENDATION_MIN_SCORE
            and item.get("tomorrow_light") != "紅燈"
            and item["rating"] in {"Strong Watch", "Watch"}
            and item["trend"] != "弱勢下彎"
            and item.get("ml_probability", 0) >= 0.52
            and (item.get("ml_validation_accuracy") is None or item.get("ml_validation_accuracy", 0) >= 0.45)
            and item.get("night_score", 0) > -8
        ]
        recommended.sort(
            key=lambda item: (
                1 if item.get("tomorrow_light") == "綠燈" else 0,
                item.get("tomorrow_score", item["score"]),
                item["score"],
                item.get("night_score", 0),
            ),
            reverse=True,
        )
        return recommended[:RECOMMENDATION_TOP_N]

    def _format_recommendation_block(self, item: dict) -> list[str]:
        lines = [
            f"### {item['symbol']} {item['symbol_name']}",
            f"- 明日燈號: {item.get('tomorrow_light', '黃燈')}",
            f"- 明日分數: {item.get('tomorrow_score', item['score'])} (原始分數 {item['score']})",
            f"- 明日動作: {item.get('tomorrow_action', item['action'])}",
            f"- 推薦理由: {item.get('recommendation_reason', self._join_or_fallback(item.get('reasons', [])))}",
            f"- 夜間修正: {self._format_night_summary(item)}",
            "",
        ]
        return lines

    def _format_stock_block(self, item: dict, compact: bool) -> list[str]:
        lines = [
            f"### {item['symbol']} {item['symbol_name']}",
            f"- 評級: {item['rating']} ({item['score']} 分)",
            f"- 規則分數: {item['rule_score']} 分",
            f"- 明日燈號: {item.get('tomorrow_light', '黃燈')}",
            f"- 明日動作: {item.get('tomorrow_action', item['action'])}",
            f"- 明日理由: {item.get('tomorrow_reason', '夜間消息偏中性')}",
            f"- 趨勢: {item['trend']}",
            f"- ML: {self._format_ml_summary(item)}",
            f"- 夜間評估: {self._format_night_summary(item)}",
            f"- 加分理由: {self._join_or_fallback(item.get('reasons', []))}",
            f"- 風險提醒: {self._join_or_fallback(item.get('risks', []))}",
            "",
        ]
        if compact:
            return lines
        return lines

    def _format_stock_detail(self, item: dict) -> list[str]:
        lines = [
            f"### {item['symbol']} {item['symbol_name']}",
            f"- 產業: {item['sector']}",
            f"- 原始評級: {item['rating']} ({item['score']} 分)",
            f"- 明日燈號: {item.get('tomorrow_light', '黃燈')}",
            f"- 明日分數: {item.get('tomorrow_score', item['score'])}",
            f"- 明日動作: {item.get('tomorrow_action', item['action'])}",
            f"- 明日理由: {item.get('tomorrow_reason', '夜間消息偏中性')}",
            f"- ML: {self._format_ml_summary(item)}",
            f"- 夜間評估: {self._format_night_summary(item)}",
            f"- 技術面: {self._format_technical(item)}",
            f"- 估值: {self._format_valuation(item)}",
            f"- 月營收: {self._format_revenue(item)}",
            f"- 法人: {self._format_institutional(item)}",
            f"- 加分理由: {self._join_or_fallback(item.get('reasons', []))}",
            f"- 風險提醒: {self._join_or_fallback(item.get('risks', []))}",
            "",
        ]
        return lines

    def _format_prompt_block(self, item: dict) -> str:
        return "\n".join(
            [
                f"- {item['symbol']} {item['symbol_name']}",
                f"  - score: {item['score']}",
                f"  - tomorrow_score: {item.get('tomorrow_score', item['score'])}",
                f"  - tomorrow_light: {item.get('tomorrow_light', '黃燈')}",
                f"  - tomorrow_action: {item.get('tomorrow_action', item['action'])}",
                f"  - recommendation_reason: {item.get('recommendation_reason', '夜間消息偏中性')}",
                f"  - night_summary: {self._format_night_summary(item)}",
                f"  - ml_summary: {self._format_ml_summary(item)}",
                f"  - reasons: {self._join_or_fallback(item.get('reasons', []))}",
                f"  - risks: {self._join_or_fallback(item.get('risks', []))}",
            ]
        )

    @staticmethod
    def _format_theme_line(item: dict, score_label: str) -> str:
        return f"- {item['symbol']} {item['symbol_name']} | {score_label} {item['theme_score']} | {item['theme_reason']}"

    @staticmethod
    def _format_theme_prompt_block(item: dict, theme_name: str) -> str:
        return "\n".join(
            [
                f"- {item['symbol']} {item['symbol_name']}",
                f"  - theme: {theme_name}",
                f"  - theme_score: {item['theme_score']}",
                f"  - theme_reason: {item['theme_reason']}",
                f"  - tomorrow_light: {item.get('tomorrow_light', '黃燈')}",
            ]
        )

    @staticmethod
    def _format_night_line(item: dict) -> str:
        return (
            f"- {item['symbol']} {item['symbol_name']} | 夜間分數 {item.get('night_score', 0)} | "
            f"{item.get('night_action', '夜間消息偏中性')} | "
            f"{item.get('headline_summary', '沒有明顯事件')}"
        )

    @staticmethod
    def _format_night_prompt_block(item: dict) -> str:
        tags = "、".join(item.get("event_tags", [])) if item.get("event_tags") else "無"
        return "\n".join(
            [
                f"- {item['symbol']} {item['symbol_name']}",
                f"  - night_score: {item.get('night_score', 0)}",
                f"  - night_bias: {item.get('night_bias', '中性')}",
                f"  - tomorrow_score: {item.get('tomorrow_score', item['score'])}",
                f"  - tomorrow_light: {item.get('tomorrow_light', '黃燈')}",
                f"  - night_action: {item.get('night_action', '夜間消息偏中性')}",
                f"  - event_tags: {tags}",
                f"  - headline_summary: {item.get('headline_summary', '沒有明顯事件')}",
            ]
        )

    @staticmethod
    def _join_or_fallback(items: list[str]) -> str:
        return "；".join(items) if items else "沒有明顯訊號"

    @staticmethod
    def _signed(value: int) -> str:
        if value > 0:
            return f"+{value:,}"
        return f"{value:,}"

    @staticmethod
    def _format_night_summary(item: dict) -> str:
        tags = "、".join(item.get("event_tags", [])[:3]) if item.get("event_tags") else "沒有明顯事件"
        return (
            f"{item.get('night_bias', '中性')} | 夜間分數 {item.get('night_score', 0)} | "
            f"{item.get('night_action', '夜間消息偏中性')} | {tags}"
        )

    @staticmethod
    def _format_valuation(item: dict) -> str:
        if not item.get("has_valuation_data"):
            return "目前沒有估值資料"
        pe = f"PE {item['pe_ratio']:.1f}" if item.get("pe_ratio") is not None else "PE 無資料"
        pb = f"PBR {item['pb_ratio']:.1f}" if item.get("pb_ratio") is not None else "PBR 無資料"
        dividend = (
            f"殖利率 {item['dividend_yield']:.2f}%"
            if item.get("dividend_yield") is not None
            else "殖利率無資料"
        )
        return f"{pe} | {pb} | {dividend}"

    @staticmethod
    def _format_revenue(item: dict) -> str:
        if not item.get("has_revenue_data"):
            return "目前沒有月營收資料"
        latest = item.get("latest_revenue_month") or "無資料"
        yoy = AIReporter._format_pct(item.get("revenue_yoy"))
        mom = AIReporter._format_pct(item.get("revenue_mom"))
        return f"{latest} | YoY {yoy} | MoM {mom}"

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
        return " | ".join(parts)

    @staticmethod
    def _format_pct(value: float | None) -> str:
        if value is None:
            return "無資料"
        return f"{value * 100:.1f}%"

    @staticmethod
    def _format_ml_summary(item: dict) -> str:
        accuracy = item.get("ml_validation_accuracy")
        accuracy_text = "驗證無資料" if accuracy is None else f"驗證準確率 {accuracy * 100:.1f}%"
        usable_samples = item.get("ml_usable_samples", 0)
        train_samples = item.get("ml_train_samples", 0)
        validation_samples = item.get("ml_validation_samples", 0)
        return (
            f"{item['ml_model_name']} | {item['signal_strength']} | {accuracy_text} | "
            f"樣本 {usable_samples} / 訓練 {train_samples} / 驗證 {validation_samples}"
        )

    @staticmethod
    def _format_institutional(item: dict) -> str:
        if not item.get("has_institutional_data"):
            return "目前沒有法人資料"
        return (
            f"外資近 3 日 {AIReporter._signed(item['foreign_net_buy_3d'])} 張 | "
            f"投信近 3 日 {AIReporter._signed(item['trust_net_buy_3d'])} 張"
        )

    @staticmethod
    def _summarize_market(ordered_results: list[dict]) -> dict:
        if not ordered_results:
            return {
                "market_bias": "無資料",
                "average_score": 0.0,
                "green_count": 0,
                "red_count": 0,
            }

        scores = [item.get("tomorrow_score", item["score"]) for item in ordered_results]
        average_score = sum(scores) / len(scores)
        green_count = sum(1 for item in ordered_results if item.get("tomorrow_light") == "綠燈")
        red_count = sum(1 for item in ordered_results if item.get("tomorrow_light") == "紅燈")

        if average_score >= 65:
            market_bias = "偏多"
        elif average_score <= 45:
            market_bias = "偏空"
        else:
            market_bias = "中性"

        return {
            "market_bias": market_bias,
            "average_score": average_score,
            "green_count": green_count,
            "red_count": red_count,
        }

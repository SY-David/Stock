from __future__ import annotations

import math

import pandas as pd

from config import ALERT_RULES
from modules.ml_model import SimpleQuantML


class ScoringEngine:
    def __init__(self):
        self.ml_engine = SimpleQuantML()

    def evaluate(self, stock_data: dict) -> dict | None:
        prices = stock_data.get("prices", [])
        if not prices:
            return None

        price_df = pd.DataFrame(prices).sort_values("date").reset_index(drop=True)
        price_df["ma5"] = price_df["close"].rolling(window=5, min_periods=3).mean()
        price_df["ma20"] = price_df["close"].rolling(window=20, min_periods=10).mean()
        price_df["ma60"] = price_df["close"].rolling(window=60, min_periods=30).mean()
        price_df["avg_volume_20"] = price_df["volume"].rolling(window=20, min_periods=5).mean()

        latest = price_df.iloc[-1]
        prev = price_df.iloc[-2] if len(price_df) > 1 else latest

        ma5 = self._safe_number(latest.get("ma5"))
        ma20 = self._safe_number(latest.get("ma20"))
        ma60 = self._safe_number(latest.get("ma60"))
        avg_volume_20 = self._safe_number(latest.get("avg_volume_20"))

        close = float(latest["close"])
        prev_close = float(prev["close"])
        volume = int(latest["volume"])
        volume_ratio = (volume / avg_volume_20) if avg_volume_20 else None

        return_5d = self._calc_return(price_df, 5)
        return_20d = self._calc_return(price_df, 20)

        valuation = self._latest_row(stock_data.get("valuation_history", []))
        revenue_summary = self._summarize_revenue(stock_data.get("revenue_history", []))
        institutional_summary = self._summarize_institutional(stock_data.get("institutional_history", []))
        margin_summary = self._summarize_margin(stock_data.get("margin_history", []))

        rule_score = 50
        reasons: list[str] = []
        risks: list[str] = []

        trend_label = self._build_trend_label(close, ma20, ma60)

        if ma20 and close > ma20:
            rule_score += 10
            reasons.append(f"收盤 {close:.2f} 站上 MA20 {ma20:.2f}")
        elif ma20:
            rule_score -= 10
            risks.append(f"收盤 {close:.2f} 跌破 MA20 {ma20:.2f}")

        if ma20 and ma60 and ma20 > ma60:
            rule_score += 10
            reasons.append(f"MA20 {ma20:.2f} 高於 MA60 {ma60:.2f}，中期趨勢仍偏多")
        elif ma20 and ma60 and ma20 < ma60:
            rule_score -= 8
            risks.append(f"MA20 {ma20:.2f} 仍低於 MA60 {ma60:.2f}，中期趨勢未翻正")

        if return_20d is not None:
            if return_20d >= 0.08:
                rule_score += 8
                reasons.append(f"近 20 日漲幅 {return_20d * 100:.1f}%")
            elif return_20d <= -0.08:
                rule_score -= 8
                risks.append(f"近 20 日跌幅 {abs(return_20d) * 100:.1f}%")

        if volume_ratio is not None:
            if volume_ratio >= ALERT_RULES["strong_volume_multiplier"] and close >= prev_close:
                rule_score += 8
                reasons.append(f"今日量能為 20 日均量的 {volume_ratio:.2f} 倍，且收盤未轉弱")
            elif volume_ratio >= ALERT_RULES["volume_surge_multiplier"] and close < prev_close:
                rule_score -= 6
                risks.append(f"今日量能放大至 {volume_ratio:.2f} 倍，但價格轉弱")

        foreign_3d = institutional_summary["foreign_net_buy_3d"]
        trust_3d = institutional_summary["trust_net_buy_3d"]
        total_inst_3d = foreign_3d + trust_3d + institutional_summary["dealer_net_buy_3d"]

        if foreign_3d > 0:
            rule_score += 6
            reasons.append(f"外資近 3 日買超 {self._format_signed_int(foreign_3d)} 張")
        elif foreign_3d < 0:
            rule_score -= 5
            risks.append(f"外資近 3 日賣超 {self._format_signed_int(foreign_3d)} 張")

        if trust_3d > 0:
            rule_score += 4
            reasons.append(f"投信近 3 日買超 {self._format_signed_int(trust_3d)} 張")
        elif trust_3d < 0:
            rule_score -= 3
            risks.append(f"投信近 3 日賣超 {self._format_signed_int(trust_3d)} 張")

        pe_ratio = self._safe_number(valuation.get("pe_ratio")) if valuation else None
        pb_ratio = self._safe_number(valuation.get("pb_ratio")) if valuation else None
        dividend_yield = self._safe_number(valuation.get("dividend_yield")) if valuation else None

        if pe_ratio is not None:
            if 0 < pe_ratio <= 20:
                rule_score += 4
                reasons.append(f"本益比 {pe_ratio:.1f} 位於相對溫和區間")
            elif pe_ratio >= 35:
                rule_score -= 4
                risks.append(f"本益比 {pe_ratio:.1f} 偏高，評價壓力較大")

        if dividend_yield is not None:
            if dividend_yield >= 4:
                rule_score += 4
                reasons.append(f"殖利率 {dividend_yield:.2f}% 提供部分防守")
            elif dividend_yield <= 1 and pe_ratio and pe_ratio >= 25:
                rule_score -= 2
                risks.append(f"殖利率 {dividend_yield:.2f}% 偏低，評價支撐較弱")

        revenue_yoy = revenue_summary.get("revenue_yoy")
        revenue_mom = revenue_summary.get("revenue_mom")
        if revenue_yoy is not None:
            if revenue_yoy >= 0.15:
                rule_score += 8
                reasons.append(f"最新月營收年增 {revenue_yoy * 100:.1f}%")
            elif revenue_yoy >= 0.05:
                rule_score += 4
                reasons.append(f"最新月營收年增 {revenue_yoy * 100:.1f}%")
            elif revenue_yoy <= 0:
                rule_score -= 6
                risks.append(f"最新月營收年增 {revenue_yoy * 100:.1f}%")

        if revenue_mom is not None:
            if revenue_mom >= 0.10:
                reasons.append(f"最新月營收月增 {revenue_mom * 100:.1f}%")
            elif revenue_mom <= -0.15:
                risks.append(f"最新月營收月減 {abs(revenue_mom) * 100:.1f}%，追價需保守")

        margin_usage = margin_summary.get("margin_usage")
        if margin_usage is not None:
            if margin_usage >= ALERT_RULES["margin_usage_danger"]:
                rule_score -= 8
                risks.append(f"融資使用率 {margin_usage * 100:.1f}% 偏高")
            elif margin_usage >= ALERT_RULES["margin_usage_warning"]:
                rule_score -= 4
                risks.append(f"融資使用率 {margin_usage * 100:.1f}% 需要留意追價風險")

        if len(price_df) < 60:
            risks.append("價格歷史不足 60 個交易日，長期均線參考性較低")

        if not risks:
            if return_5d is not None and return_5d >= 0.08:
                risks.append(f"近 5 日已上漲 {return_5d * 100:.1f}%，留意短線震盪")
            elif volume_ratio is not None and volume_ratio < 1:
                risks.append(f"量比僅 {volume_ratio:.2f}，上攻量能仍待放大")
            else:
                risks.append("目前未見明顯破壞訊號，但仍需留意大盤波動")

        rule_score = max(0, min(100, int(round(rule_score))))
        ml_result = self.ml_engine.predict(stock_data=stock_data, base_score=rule_score)
        ml_probability_score = int(round(ml_result.probability * 100))
        score = int(round(rule_score * 0.72 + ml_probability_score * 0.28))
        score = max(0, min(100, score))
        rating, action = self._to_rating(score)

        return {
            "symbol": stock_data["symbol"],
            "symbol_name": stock_data["info"]["name"],
            "sector": stock_data["info"].get("sector", "未知"),
            "market": stock_data["info"].get("market", "unknown"),
            "has_institutional_data": bool(stock_data.get("institutional_history")),
            "has_valuation_data": bool(stock_data.get("valuation_history")),
            "has_revenue_data": bool(stock_data.get("revenue_history")),
            "rating": rating,
            "action": action,
            "score": score,
            "rule_score": rule_score,
            "trend": trend_label,
            "signal_strength": ml_result.label,
            "ml_source": ml_result.source,
            "ml_model_name": ml_result.model_name,
            "ml_probability": ml_result.probability,
            "ml_validation_accuracy": ml_result.validation_accuracy,
            "ml_usable_samples": ml_result.usable_samples,
            "ml_train_samples": ml_result.train_samples,
            "ml_validation_samples": ml_result.validation_samples,
            "ml_features_used": ml_result.features_used,
            "ml_note": ml_result.note,
            "reasons": self._unique_items(reasons, limit=4),
            "risks": self._unique_items(risks, limit=4),
            "warnings": stock_data.get("warnings", []),
            "latest_price_date": latest["date"],
            "close": close,
            "ma5": ma5,
            "ma20": ma20,
            "ma60": ma60,
            "return_5d": return_5d,
            "return_20d": return_20d,
            "volume": volume,
            "volume_ratio": volume_ratio,
            "institutional_trend": "偏多" if total_inst_3d > 0 else "偏空",
            "foreign_net_buy_3d": foreign_3d,
            "trust_net_buy_3d": trust_3d,
            "dealer_net_buy_3d": institutional_summary["dealer_net_buy_3d"],
            "pe_ratio": pe_ratio,
            "pb_ratio": pb_ratio,
            "dividend_yield": dividend_yield,
            "revenue_yoy": revenue_yoy,
            "revenue_mom": revenue_mom,
            "latest_revenue_month": revenue_summary.get("latest_label"),
            "margin_usage": margin_usage,
        }

    @staticmethod
    def _calc_return(price_df: pd.DataFrame, days: int) -> float | None:
        if len(price_df) <= days:
            return None
        base_close = float(price_df.iloc[-days - 1]["close"])
        latest_close = float(price_df.iloc[-1]["close"])
        if base_close == 0:
            return None
        return (latest_close / base_close) - 1

    @staticmethod
    def _build_trend_label(close: float, ma20: float | None, ma60: float | None) -> str:
        if ma20 and ma60 and close > ma20 and ma20 > ma60:
            return "多頭延續"
        if ma20 and ma60 and close > ma20 and ma20 <= ma60:
            return "短線轉強"
        if ma20 and ma60 and close < ma20 and ma20 < ma60:
            return "弱勢下彎"
        return "區間整理"

    @staticmethod
    def _latest_row(rows: list[dict]) -> dict | None:
        if not rows:
            return None
        return sorted(rows, key=lambda item: item["date"])[-1]

    @staticmethod
    def _summarize_institutional(rows: list[dict]) -> dict:
        if not rows:
            return {
                "foreign_net_buy_3d": 0,
                "trust_net_buy_3d": 0,
                "dealer_net_buy_3d": 0,
            }

        recent_dates = sorted({row["date"] for row in rows})[-3:]
        totals = {
            "Foreign_Investor": 0,
            "Investment_Trust": 0,
            "Dealer_self": 0,
            "Dealer_Hedging": 0,
            "Foreign_Dealer_Self": 0,
        }

        for row in rows:
            if row["date"] not in recent_dates:
                continue
            totals[row["investor_name"]] = totals.get(row["investor_name"], 0) + row["buy"] - row["sell"]

        return {
            "foreign_net_buy_3d": totals.get("Foreign_Investor", 0),
            "trust_net_buy_3d": totals.get("Investment_Trust", 0),
            "dealer_net_buy_3d": (
                totals.get("Dealer_self", 0)
                + totals.get("Dealer_Hedging", 0)
                + totals.get("Foreign_Dealer_Self", 0)
            ),
        }

    @staticmethod
    def _summarize_revenue(rows: list[dict]) -> dict:
        if not rows:
            return {"revenue_yoy": None, "revenue_mom": None, "latest_label": None}

        sorted_rows = sorted(rows, key=lambda item: item["date"])
        latest = sorted_rows[-1]
        lookup = {(row["revenue_year"], row["revenue_month"]): row["revenue"] for row in sorted_rows}

        latest_year = latest["revenue_year"]
        latest_month = latest["revenue_month"]
        latest_revenue = latest["revenue"]

        prev_year_same_month = lookup.get((latest_year - 1, latest_month))
        prev_month_key = (latest_year, latest_month - 1)
        if latest_month == 1:
            prev_month_key = (latest_year - 1, 12)
        prev_month_revenue = lookup.get(prev_month_key)

        revenue_yoy = None
        if prev_year_same_month:
            revenue_yoy = (latest_revenue / prev_year_same_month) - 1

        revenue_mom = None
        if prev_month_revenue:
            revenue_mom = (latest_revenue / prev_month_revenue) - 1

        return {
            "revenue_yoy": revenue_yoy,
            "revenue_mom": revenue_mom,
            "latest_label": f"{latest_year}-{latest_month:02d}",
        }

    @staticmethod
    def _summarize_margin(rows: list[dict]) -> dict:
        if not rows:
            return {"margin_usage": None}

        latest = sorted(rows, key=lambda item: item["date"])[-1]
        limit_value = latest.get("margin_limit") or 0
        margin_usage = None
        if limit_value > 0:
            margin_usage = latest["margin_balance"] / limit_value

        return {"margin_usage": margin_usage}

    @staticmethod
    def _safe_number(value: object) -> float | None:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return float(value)

    @staticmethod
    def _format_signed_int(value: int) -> str:
        sign = "+" if value > 0 else ""
        return f"{sign}{value:,}"

    @staticmethod
    def _unique_items(items: list[str], limit: int) -> list[str]:
        seen = set()
        unique = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            unique.append(item)
            if len(unique) >= limit:
                break
        return unique

    @staticmethod
    def _to_rating(score: int) -> tuple[str, str]:
        if score >= 72:
            return "Strong Watch", "可持有或拉回續看"
        if score >= 60:
            return "Watch", "列入優先觀察"
        if score >= 50:
            return "Neutral", "中性觀察，不追價"
        if score >= 40:
            return "Reduce", "偏保守，只能等轉強"
        return "Avoid", "避免追價，先觀望"

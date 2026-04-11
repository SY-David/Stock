from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from config import ML_PREDICTION_HORIZON_DAYS

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    HAS_SKLEARN = True
except ImportError:  # pragma: no cover - environment fallback
    HAS_SKLEARN = False


@dataclass
class MLPredictionResult:
    probability: float
    label: str
    source: str
    model_name: str
    validation_accuracy: float | None
    usable_samples: int
    train_samples: int
    validation_samples: int
    features_used: int
    note: str


class SimpleQuantML:
    def predict(self, stock_data: dict, base_score: int) -> MLPredictionResult:
        if not HAS_SKLEARN:
            return self._fallback(base_score, "scikit-learn 未安裝，改用規則式估計")

        feature_frame = self._build_feature_frame(stock_data)
        if feature_frame is None or feature_frame.empty:
            return self._fallback(base_score, "特徵資料不足，改用規則式估計")

        features = [column for column in feature_frame.columns if column not in {"date", "close", "target"}]
        train_frame = feature_frame.dropna(subset=features + ["target"]).reset_index(drop=True)
        if len(train_frame) < 80:
            return self._fallback(base_score, f"可訓練樣本不足 ({len(train_frame)})")

        if train_frame["target"].nunique() < 2:
            return self._fallback(base_score, "歷史標記只有單一方向，無法訓練分類模型")

        train_size = max(int(len(train_frame) * 0.8), len(train_frame) - 60)
        train_size = min(train_size, len(train_frame) - 20)
        if train_size <= 0:
            return self._fallback(base_score, "訓練/驗證切分失敗")

        train_df = train_frame.iloc[:train_size]
        valid_df = train_frame.iloc[train_size:]
        if valid_df.empty or train_df["target"].nunique() < 2:
            return self._fallback(base_score, "驗證樣本不足，改用規則式估計")

        model = Pipeline(
            steps=[
                ("scaler", StandardScaler()),
                (
                    "logreg",
                    LogisticRegression(
                        max_iter=1000,
                        solver="lbfgs",
                        class_weight="balanced",
                        random_state=42,
                    ),
                ),
            ]
        )

        X_train = train_df[features]
        y_train = train_df["target"].astype(int)
        X_valid = valid_df[features]
        y_valid = valid_df["target"].astype(int)

        model.fit(X_train, y_train)
        valid_pred = model.predict(X_valid)
        validation_accuracy = accuracy_score(y_valid, valid_pred)

        latest_features = feature_frame.iloc[[-1]][features]
        probability = float(model.predict_proba(latest_features)[0][1])
        label = self._label_probability(probability)

        return MLPredictionResult(
            probability=probability,
            label=label,
            source="trained_model",
            model_name="Logistic Regression",
            validation_accuracy=validation_accuracy,
            usable_samples=len(train_frame),
            train_samples=len(train_df),
            validation_samples=len(valid_df),
            features_used=len(features),
            note="使用歷史日線與籌碼/估值特徵訓練",
        )

    def _build_feature_frame(self, stock_data: dict) -> pd.DataFrame | None:
        price_df = self._build_price_frame(stock_data.get("prices", []))
        if price_df is None or price_df.empty:
            return None

        valuation_df = self._build_valuation_frame(stock_data.get("valuation_history", []))
        institutional_df = self._build_institutional_frame(stock_data.get("institutional_history", []))
        margin_df = self._build_margin_frame(stock_data.get("margin_history", []))
        revenue_df = self._build_revenue_frame(stock_data.get("revenue_history", []))

        feature_df = price_df.copy()

        for extra_df in [valuation_df, institutional_df, margin_df, revenue_df]:
            if extra_df is None or extra_df.empty:
                continue
            feature_df = pd.merge_asof(
                feature_df.sort_values("date"),
                extra_df.sort_values("date"),
                on="date",
                direction="backward",
            )

        zero_fill_columns = [
            "foreign_net",
            "trust_net",
            "dealer_net",
            "foreign_net_3d",
            "trust_net_3d",
            "dealer_net_3d",
            "margin_usage",
        ]
        forward_fill_columns = ["pe_ratio", "pb_ratio", "dividend_yield", "revenue_yoy", "revenue_mom"]

        for column in zero_fill_columns:
            if column in feature_df.columns:
                feature_df[column] = feature_df[column].fillna(0)
        for column in forward_fill_columns:
            if column in feature_df.columns:
                feature_df[column] = feature_df[column].ffill()

        feature_df["target"] = (
            feature_df["close"].shift(-ML_PREDICTION_HORIZON_DAYS) > feature_df["close"]
        ).astype("float")
        feature_df.loc[feature_df.index[-ML_PREDICTION_HORIZON_DAYS :], "target"] = pd.NA

        feature_columns = [column for column in feature_df.columns if column not in {"date", "close", "target"}]
        if not feature_columns:
            return None

        feature_df[feature_columns] = feature_df[feature_columns].replace([pd.NA, float("inf"), float("-inf")], pd.NA)
        feature_df[feature_columns] = feature_df[feature_columns].apply(pd.to_numeric, errors="coerce")
        feature_df[feature_columns] = feature_df[feature_columns].ffill().fillna(0)
        return feature_df

    @staticmethod
    def _build_price_frame(prices: list[dict]) -> pd.DataFrame | None:
        if not prices:
            return None

        df = pd.DataFrame(prices).copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        df["return_1d"] = df["close"].pct_change()
        df["return_5d"] = df["close"].pct_change(5)
        df["return_20d"] = df["close"].pct_change(20)
        df["ma5"] = df["close"].rolling(5).mean()
        df["ma20"] = df["close"].rolling(20).mean()
        df["ma60"] = df["close"].rolling(60).mean()
        df["dist_ma5"] = (df["close"] - df["ma5"]) / df["ma5"]
        df["dist_ma20"] = (df["close"] - df["ma20"]) / df["ma20"]
        df["dist_ma60"] = (df["close"] - df["ma60"]) / df["ma60"]
        df["vol_ratio_5"] = df["volume"] / df["volume"].rolling(5).mean()
        df["vol_ratio_20"] = df["volume"] / df["volume"].rolling(20).mean()
        df["range_ratio"] = (df["high"] - df["low"]) / df["close"].replace(0, pd.NA)
        df["close_to_open"] = (df["close"] - df["open"]) / df["open"].replace(0, pd.NA)

        return df[
            [
                "date",
                "close",
                "return_1d",
                "return_5d",
                "return_20d",
                "dist_ma5",
                "dist_ma20",
                "dist_ma60",
                "vol_ratio_5",
                "vol_ratio_20",
                "range_ratio",
                "close_to_open",
            ]
        ]

    @staticmethod
    def _build_valuation_frame(rows: list[dict]) -> pd.DataFrame | None:
        if not rows:
            return None
        df = pd.DataFrame(rows).copy()
        df["date"] = pd.to_datetime(df["date"])
        return df[["date", "pe_ratio", "pb_ratio", "dividend_yield"]]

    @staticmethod
    def _build_institutional_frame(rows: list[dict]) -> pd.DataFrame | None:
        if not rows:
            return None

        df = pd.DataFrame(rows).copy()
        df["date"] = pd.to_datetime(df["date"])
        df["net"] = df["buy"] - df["sell"]

        pivot = (
            df.pivot_table(index="date", columns="investor_name", values="net", aggfunc="sum")
            .fillna(0)
            .sort_index()
            .reset_index()
        )

        for column in ["Foreign_Investor", "Investment_Trust", "Dealer_self", "Dealer_Hedging", "Foreign_Dealer_Self"]:
            if column not in pivot.columns:
                pivot[column] = 0

        pivot["foreign_net"] = pivot["Foreign_Investor"]
        pivot["trust_net"] = pivot["Investment_Trust"]
        pivot["dealer_net"] = pivot["Dealer_self"] + pivot["Dealer_Hedging"] + pivot["Foreign_Dealer_Self"]
        pivot["foreign_net_3d"] = pivot["foreign_net"].rolling(3).sum()
        pivot["trust_net_3d"] = pivot["trust_net"].rolling(3).sum()
        pivot["dealer_net_3d"] = pivot["dealer_net"].rolling(3).sum()

        return pivot[
            [
                "date",
                "foreign_net",
                "trust_net",
                "dealer_net",
                "foreign_net_3d",
                "trust_net_3d",
                "dealer_net_3d",
            ]
        ]

    @staticmethod
    def _build_margin_frame(rows: list[dict]) -> pd.DataFrame | None:
        if not rows:
            return None
        df = pd.DataFrame(rows).copy()
        df["date"] = pd.to_datetime(df["date"])
        df["margin_usage"] = df.apply(
            lambda row: (row["margin_balance"] / row["margin_limit"]) if row["margin_limit"] else 0,
            axis=1,
        )
        return df[["date", "margin_usage"]]

    @staticmethod
    def _build_revenue_frame(rows: list[dict]) -> pd.DataFrame | None:
        if not rows:
            return None

        df = pd.DataFrame(rows).copy()
        df = df.sort_values(["revenue_year", "revenue_month"]).reset_index(drop=True)
        lookup = {(row["revenue_year"], row["revenue_month"]): row["revenue"] for _, row in df.iterrows()}

        yoy_values = []
        mom_values = []
        for _, row in df.iterrows():
            prev_year_value = lookup.get((row["revenue_year"] - 1, row["revenue_month"]))
            if row["revenue_month"] == 1:
                prev_month_key = (row["revenue_year"] - 1, 12)
            else:
                prev_month_key = (row["revenue_year"], row["revenue_month"] - 1)
            prev_month_value = lookup.get(prev_month_key)

            yoy = ((row["revenue"] / prev_year_value) - 1) if prev_year_value else None
            mom = ((row["revenue"] / prev_month_value) - 1) if prev_month_value else None
            yoy_values.append(yoy)
            mom_values.append(mom)

        df["revenue_yoy"] = yoy_values
        df["revenue_mom"] = mom_values
        df["date"] = pd.to_datetime(df["date"])
        return df[["date", "revenue_yoy", "revenue_mom"]]

    @staticmethod
    def _label_probability(probability: float) -> str:
        percent = int(round(probability * 100))
        if percent >= 65:
            return f"{percent}% (偏多)"
        if percent <= 40:
            return f"{percent}% (偏空)"
        return f"{percent}% (中性)"

    def _fallback(self, base_score: int, note: str) -> MLPredictionResult:
        probability = max(0.10, min(0.90, 0.50 + (base_score - 50) / 120))
        return MLPredictionResult(
            probability=probability,
            label=self._label_probability(probability),
            source="fallback",
            model_name="Rule Fallback",
            validation_accuracy=None,
            usable_samples=0,
            train_samples=0,
            validation_samples=0,
            features_used=0,
            note=note,
        )

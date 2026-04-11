from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import requests

from config import CACHE_DIR, LOOKBACK_DAYS, ML_LOOKBACK_DAYS, REQUEST_TIMEOUT, normalize_symbol


class TWSEClient:
    DAILY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    STOCK_DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            }
        )
        Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)

    def fetch_daily_all(self) -> list[dict]:
        cache_path = Path(CACHE_DIR) / f"twse_daily_all_{date.today().isoformat()}.json"
        return self._fetch_json(self.DAILY_ALL_URL, cache_path=cache_path)

    def fetch_stock_month(self, stock_id: str, year_month: str) -> dict:
        cache_path = Path(CACHE_DIR) / f"twse_stock_day_{stock_id}_{year_month}.json"
        params = {"response": "json", "date": f"{year_month}01", "stockNo": stock_id}
        return self._fetch_json(self.STOCK_DAY_URL, params=params, cache_path=cache_path)

    def _fetch_json(self, url: str, params: dict | None = None, cache_path: Path | None = None):
        if cache_path and cache_path.exists():
            return self._read_cache(cache_path)

        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()

        if cache_path:
            cache_path.write_text(response.text, encoding="utf-8")

        return payload

    @staticmethod
    def _read_cache(cache_path: Path):
        import json

        return json.loads(cache_path.read_text(encoding="utf-8"))


class DataStorage:
    TRADING_DAYS_PER_MONTH = 20

    def __init__(self):
        self.client = TWSEClient(timeout=REQUEST_TIMEOUT)
        self._daily_snapshot_cache: dict[str, dict] | None = None

    def get_stock_data(self, symbol: str) -> dict | None:
        stock_id = normalize_symbol(symbol)
        return self._fetch_live_stock_data(stock_id)

    def _fetch_live_stock_data(self, stock_id: str) -> dict:
        warnings: list[str] = []
        snapshot = self._get_daily_snapshot()
        name = snapshot.get(stock_id, {}).get("Name", stock_id)
        sector = "ETF" if stock_id.startswith("00") else "上市個股"

        history_days = max(LOOKBACK_DAYS, ML_LOOKBACK_DAYS, 120)
        months_to_fetch = max(6, math.ceil(history_days / self.TRADING_DAYS_PER_MONTH) + 2)
        prices: list[dict] = []

        for year_month in self._iter_recent_year_months(months_to_fetch):
            try:
                payload = self.client.fetch_stock_month(stock_id, year_month)
            except Exception as exc:
                warnings.append(f"{year_month} 月資料抓取失敗：{exc}")
                continue

            monthly_rows = self._parse_stock_month_payload(payload)
            prices.extend(monthly_rows)

        prices = self._deduplicate_prices(prices)
        if not prices:
            warnings.append("官方日線資料沒有回傳內容；若是上櫃股票，目前版本尚未支援 TPEX 歷史接口。")

        return {
            "symbol": stock_id,
            "info": {
                "name": name,
                "sector": sector,
                "market": "twse_open_data",
            },
            "prices": prices,
            "valuation_history": [],
            "institutional_history": [],
            "revenue_history": [],
            "margin_history": [],
            "warnings": warnings,
            "source": "twse_official",
        }

    def _get_daily_snapshot(self) -> dict[str, dict]:
        if self._daily_snapshot_cache is not None:
            return self._daily_snapshot_cache

        try:
            rows = self.client.fetch_daily_all()
            self._daily_snapshot_cache = {row["Code"]: row for row in rows if row.get("Code")}
        except Exception:
            self._daily_snapshot_cache = {}
        return self._daily_snapshot_cache

    @staticmethod
    def _iter_recent_year_months(months_to_fetch: int) -> list[str]:
        today = date.today()
        year = today.year
        month = today.month
        months: list[str] = []
        for offset in range(months_to_fetch):
            month_index = (year * 12 + month - 1) - offset
            current_year = month_index // 12
            current_month = month_index % 12 + 1
            months.append(f"{current_year}{current_month:02d}")
        return list(reversed(months))

    @staticmethod
    def _parse_stock_month_payload(payload: dict) -> list[dict]:
        if payload.get("stat") != "OK":
            return []

        parsed_rows: list[dict] = []
        for row in payload.get("data", []):
            if len(row) < 8:
                continue
            trade_date = DataStorage._roc_date_to_iso(row[0])
            if trade_date is None:
                continue

            close_value = DataStorage._safe_float(row[6])
            if close_value is None:
                continue
            open_value = DataStorage._safe_float(row[3])
            high_value = DataStorage._safe_float(row[4])
            low_value = DataStorage._safe_float(row[5])

            parsed_rows.append(
                {
                    "date": trade_date,
                    "open": open_value if open_value is not None else close_value,
                    "high": high_value if high_value is not None else close_value,
                    "low": low_value if low_value is not None else close_value,
                    "close": close_value,
                    "volume": DataStorage._safe_int(row[1]),
                    "turnover": DataStorage._safe_int(row[8] if len(row) > 8 else 0),
                }
            )

        return parsed_rows

    @staticmethod
    def _deduplicate_prices(rows: list[dict]) -> list[dict]:
        deduplicated: dict[str, dict] = {}
        for row in rows:
            deduplicated[row["date"]] = row
        return [deduplicated[key] for key in sorted(deduplicated)]

    @staticmethod
    def _roc_date_to_iso(value: str) -> str | None:
        try:
            year_str, month_str, day_str = value.split("/")
            year = int(year_str) + 1911
            month = int(month_str)
            day = int(day_str)
            return date(year, month, day).isoformat()
        except Exception:
            return None

    @staticmethod
    def _safe_float(value: object) -> float | None:
        if value in ("", None, "--", "---"):
            return None
        return float(str(value).replace(",", ""))

    @staticmethod
    def _safe_int(value: object) -> int:
        if value in ("", None, "--", "---"):
            return 0
        return int(str(value).replace(",", ""))

from __future__ import annotations

import json
import math
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import requests
import urllib3

from app_config import (
    ALLOW_INSECURE_TWSE_SSL_FALLBACK,
    AUTO_DAILY_CANDIDATE_COUNT,
    CACHE_DIR,
    LOOKBACK_DAYS,
    ML_LOOKBACK_DAYS,
    REQUEST_TIMEOUT,
    normalize_symbol,
)
from modules.candidate_pool import generate_daily_candidate_pool


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class TWSEClient:
    DAILY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    STOCK_DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
    INTRADAY_CACHE_TTL_SECONDS = 15 * 60

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.allow_insecure_ssl_fallback = ALLOW_INSECURE_TWSE_SSL_FALLBACK
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
        return self._fetch_json(
            self.DAILY_ALL_URL,
            cache_path=cache_path,
            max_cache_age_seconds=self.INTRADAY_CACHE_TTL_SECONDS,
        )

    def fetch_stock_month(self, stock_id: str, year_month: str) -> dict:
        today = date.today()
        is_current_month = year_month == today.strftime("%Y%m")
        cache_suffix = (
            f"{year_month}_{today.isoformat()}" if is_current_month else year_month
        )
        cache_path = Path(CACHE_DIR) / f"twse_stock_day_{stock_id}_{cache_suffix}.json"
        params = {"response": "json", "date": f"{year_month}01", "stockNo": stock_id}
        return self._fetch_json(
            self.STOCK_DAY_URL,
            params=params,
            cache_path=cache_path,
            max_cache_age_seconds=(
                self.INTRADAY_CACHE_TTL_SECONDS if is_current_month else None
            ),
        )

    def _fetch_json(
        self,
        url: str,
        params: dict | None = None,
        cache_path: Path | None = None,
        max_cache_age_seconds: int | None = None,
    ):
        cached_payload = None
        if cache_path and cache_path.exists():
            try:
                cached_payload = self._read_cache(cache_path)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                cache_path.unlink(missing_ok=True)
            else:
                if self._is_cache_fresh(cache_path, max_cache_age_seconds):
                    return cached_payload

        try:
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.exceptions.SSLError:
                if not self._should_retry_without_verify(url):
                    raise
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    verify=False,
                )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            if cached_payload is not None:
                return cached_payload
            raise

        if cache_path:
            temp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
            temp_path.write_text(response.text, encoding="utf-8")
            temp_path.replace(cache_path)

        return payload

    @staticmethod
    def _read_cache(cache_path: Path):
        return json.loads(cache_path.read_text(encoding="utf-8"))

    @staticmethod
    def _is_cache_fresh(
        cache_path: Path,
        max_cache_age_seconds: int | None,
    ) -> bool:
        if max_cache_age_seconds is None:
            return True
        try:
            cache_age_seconds = max(0.0, time.time() - cache_path.stat().st_mtime)
        except OSError:
            return False
        return cache_age_seconds <= max_cache_age_seconds

    def _should_retry_without_verify(self, url: str) -> bool:
        if not self.allow_insecure_ssl_fallback:
            return False
        hostname = (urlparse(url).hostname or "").lower()
        return hostname.endswith("twse.com.tw")


class DataStorage:
    TRADING_DAYS_PER_MONTH = 20

    def __init__(self):
        self.client = TWSEClient(timeout=REQUEST_TIMEOUT)
        self._daily_snapshot_cache: dict[str, dict] | None = None

    def get_stock_data(self, symbol: str) -> dict | None:
        stock_id = normalize_symbol(symbol)
        return self._fetch_live_stock_data(stock_id)

    def build_daily_candidate_pool(
        self,
        exclude_symbols: list[str] | None = None,
        limit: int = AUTO_DAILY_CANDIDATE_COUNT,
    ) -> list[str]:
        snapshot = self._get_daily_snapshot()
        return generate_daily_candidate_pool(
            snapshot,
            exclude_symbols=exclude_symbols or [],
            limit=limit,
        )

    def _fetch_live_stock_data(self, stock_id: str) -> dict:
        warnings: list[str] = []
        snapshot = self._get_daily_snapshot()
        name = snapshot.get(stock_id, {}).get("Name", stock_id)
        sector = "ETF" if stock_id.startswith("00") else "上市個股"

        history_days = max(LOOKBACK_DAYS, ML_LOOKBACK_DAYS, 120)
        months_to_fetch = max(
            6,
            math.ceil(history_days / self.TRADING_DAYS_PER_MONTH) + 2,
        )
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
            warnings.append(
                "官方日線資料沒有回傳內容；若是上櫃股票，目前版本尚未支援 TPEX 歷史接口。"
            )

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
            self._daily_snapshot_cache = {
                row["Code"]: row for row in rows if row.get("Code")
            }
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
                    "turnover": DataStorage._safe_int(
                        row[8] if len(row) > 8 else 0
                    ),
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
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value: object) -> int:
        if value in ("", None, "--", "---"):
            return 0
        try:
            return int(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return 0

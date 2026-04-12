from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency during bootstrap
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
CACHE_DIR = DATA_DIR / "cache"
HISTORY_DIR = DATA_DIR / "history"
SNAPSHOT_PATH = DATA_DIR / "site_snapshot.json"
UPDATE_STATUS_PATH = DATA_DIR / "update_status.json"

if load_dotenv:
    load_dotenv(BASE_DIR / ".env")


def _parse_bool(raw_value: str | None, default: bool = False) -> bool:
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper()
    if cleaned.endswith(".TW"):
        return cleaned[:-3]
    return cleaned


def _parse_symbol_list(raw_value: str | None, default_symbols: list[str]) -> list[str]:
    if not raw_value:
        return default_symbols

    parsed = [normalize_symbol(item) for item in raw_value.split(",") if item.strip()]
    return parsed or default_symbols


WATCHLIST = _parse_symbol_list(os.getenv("WATCHLIST"), ["0050", "2344"])
DAILY_CANDIDATE_POOL = _parse_symbol_list(
    os.getenv("DAILY_CANDIDATE_POOL"),
    ["2330", "2317", "2454", "2382", "2308", "3231", "2603", "2881"],
)
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", "480"))
ML_LOOKBACK_DAYS = int(os.getenv("ML_LOOKBACK_DAYS", "960"))
ML_PREDICTION_HORIZON_DAYS = int(os.getenv("ML_PREDICTION_HORIZON_DAYS", "5"))
REPORT_TOP_N = int(os.getenv("REPORT_TOP_N", "5"))
RECOMMENDATION_TOP_N = int(os.getenv("RECOMMENDATION_TOP_N", "3"))
RECOMMENDATION_MIN_SCORE = int(os.getenv("RECOMMENDATION_MIN_SCORE", "65"))
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "30"))
PAPER_INITIAL_CASH = float(os.getenv("PAPER_INITIAL_CASH", "50000"))
PAPER_DAILY_BUDGET = float(os.getenv("PAPER_DAILY_BUDGET", "5000"))
PAPER_MAX_NEW_BUYS_PER_DAY = int(os.getenv("PAPER_MAX_NEW_BUYS_PER_DAY", "2"))
PAPER_MAX_HOLD_DAYS = int(os.getenv("PAPER_MAX_HOLD_DAYS", "5"))
PAPER_ALLOW_FRACTIONAL = _parse_bool(os.getenv("PAPER_ALLOW_FRACTIONAL"), default=True)
GENERATE_LLM_PROMPT = _parse_bool(os.getenv("GENERATE_LLM_PROMPT"), default=True)
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
ALLOW_INSECURE_TWSE_SSL_FALLBACK = _parse_bool(os.getenv("ALLOW_INSECURE_TWSE_SSL_FALLBACK"), default=True)
ENABLE_NIGHTLY_CONTEXT = _parse_bool(os.getenv("ENABLE_NIGHTLY_CONTEXT"), default=True)
NIGHTLY_REQUEST_TIMEOUT = int(os.getenv("NIGHTLY_REQUEST_TIMEOUT", "12"))
NIGHTLY_NEWS_LIMIT = int(os.getenv("NIGHTLY_NEWS_LIMIT", "4"))


ALERT_RULES = {
    "volume_surge_multiplier": 1.8,
    "strong_volume_multiplier": 2.2,
    "margin_usage_warning": 0.25,
    "margin_usage_danger": 0.40,
}

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
CONFIG_PATH = ROOT / "app_config.py"
PAPER_PATH = ROOT / "modules" / "paper_trading.py"
SCORING_PATH = ROOT / "modules" / "scoring_engine.py"
STORAGE_PATH = ROOT / "modules" / "storage.py"
README_PATH = ROOT / "README.md"


def replace_one(text: str, old: str, new: str, label: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise RuntimeError(f"Could not locate source fragment for {label}")


def patch_app() -> None:
    text = APP_PATH.read_text(encoding="utf-8")

    old_numeric = '                    "損益": float(row["pnl"]) if row["pnl"] is not None else None,\n'
    old_mixed = '                    "損益": row["pnl"] if row["pnl"] is not None else "",\n'
    new = (
        '                    "損益": (\n'
        '                        f"{float(row[\'pnl\']):,.0f}"\n'
        '                        if row["pnl"] is not None\n'
        '                        else "—"\n'
        '                    ),\n'
    )
    if old_numeric in text:
        text = text.replace(old_numeric, new, 1)
    elif old_mixed in text:
        text = text.replace(old_mixed, new, 1)
    elif new not in text:
        raise RuntimeError("Could not locate trade P/L display in app.py")

    text = replace_one(
        text,
        '                    "報酬率": f"{row[\'return_pct\']:.2f}%" if row.get("return_pct") is not None else "",\n',
        '                    "報酬率": f"{row[\'return_pct\']:.2f}%" if row.get("return_pct") is not None else "—",\n',
        "trade return display",
    )

    compile(text, str(APP_PATH), "exec")
    APP_PATH.write_text(text, encoding="utf-8")
    print("Fixed Streamlit trade-table missing-value display")


def patch_config() -> None:
    text = CONFIG_PATH.read_text(encoding="utf-8")
    text = replace_one(
        text,
        'PAPER_MAX_NEW_BUYS_PER_DAY = int(os.getenv("PAPER_MAX_NEW_BUYS_PER_DAY", "2"))\n',
        'PAPER_MAX_NEW_BUYS_PER_DAY = int(os.getenv("PAPER_MAX_NEW_BUYS_PER_DAY", "2"))\nPAPER_ORDER_MAX_CALENDAR_DAYS = int(os.getenv("PAPER_ORDER_MAX_CALENDAR_DAYS", "7"))\n',
        "paper-order expiry setting",
    )
    compile(text, str(CONFIG_PATH), "exec")
    CONFIG_PATH.write_text(text, encoding="utf-8")
    print("Added paper-order expiry setting")


def patch_paper_trading() -> None:
    text = PAPER_PATH.read_text(encoding="utf-8")

    if "from datetime import date\n" not in text:
        text = text.replace(
            "from dataclasses import dataclass\n",
            "from dataclasses import dataclass\nfrom datetime import date\n",
            1,
        )

    text = replace_one(
        text,
        '    PAPER_MAX_NEW_BUYS_PER_DAY,\n',
        '    PAPER_MAX_NEW_BUYS_PER_DAY,\n    PAPER_ORDER_MAX_CALENDAR_DAYS,\n',
        "paper-order expiry import",
    )

    text = replace_one(
        text,
        '''            price_row = _get_price_row(snapshot, symbol, current_date)
            if price_row:
                position["last_open"] = float(price_row["open"])
                position["last_close"] = float(price_row["close"])
                position["last_mark_date"] = current_date
                position["days_held"] = position.get("days_held", 0) + 1
''',
        '''            price_row = _get_price_row(snapshot, symbol, current_date)
            if price_row:
                price_date = str(price_row.get("date", current_date))
                position["last_open"] = float(price_row["open"])
                position["last_close"] = float(price_row["close"])
                if position.get("last_mark_date") != price_date:
                    position["last_mark_date"] = price_date
                    position["days_held"] = position.get("days_held", 0) + 1
''',
        "position trading-day accounting",
    )

    text = replace_one(
        text,
        '''    for order in pending_orders:
        if order["execute_on_or_after"] > current_date:
            still_pending.append(order)
            continue

        price_row = _get_price_row(snapshot, order["symbol"], current_date)
''',
        '''    for order in pending_orders:
        if order["execute_on_or_after"] > current_date:
            still_pending.append(order)
            continue

        try:
            order_age_days = (
                date.fromisoformat(current_date)
                - date.fromisoformat(str(order["signal_date"])[:10])
            ).days
        except (KeyError, TypeError, ValueError):
            order_age_days = 0
        if order_age_days > PAPER_ORDER_MAX_CALENDAR_DAYS:
            continue

        price_row = _get_price_row(
            snapshot,
            order["symbol"],
            current_date,
            after_date=order["signal_date"],
        )
''',
        "order expiry and next-trading-day lookup",
    )

    text = replace_one(
        text,
        '        open_price = float(price_row["open"])\n        if order["side"] == "BUY":\n',
        '        execution_date = str(price_row.get("date", current_date))\n        open_price = float(price_row["open"])\n        if order["side"] == "BUY":\n',
        "actual execution date",
    )

    text = replace_one(
        text,
        '                "entered_on": current_date,\n',
        '                "entered_on": execution_date,\n                "last_mark_date": execution_date,\n',
        "position entry date",
    )

    text = replace_one(
        text,
        '''            trades.append(
                {
                    "date": current_date,
                    "side": "BUY",
''',
        '''            trades.append(
                {
                    "date": execution_date,
                    "side": "BUY",
''',
        "buy execution date",
    )

    text = replace_one(
        text,
        '''            trades.append(
                {
                    "date": current_date,
                    "side": "SELL",
''',
        '''            trades.append(
                {
                    "date": execution_date,
                    "side": "SELL",
''',
        "sell execution date",
    )

    text = replace_one(
        text,
        '''def _get_price_row(snapshot: dict, symbol: str, current_date: str) -> dict | None:
    rows = snapshot.get("raw_data", {}).get(symbol, {}).get("prices", [])
    for row in reversed(rows):
        row_date = str(row.get("date", ""))
        if row_date <= current_date:
            return row
    return None
''',
        '''def _get_price_row(
    snapshot: dict,
    symbol: str,
    current_date: str,
    after_date: str | None = None,
) -> dict | None:
    rows = snapshot.get("raw_data", {}).get(symbol, {}).get("prices", [])
    for row in reversed(rows):
        row_date = str(row.get("date", ""))
        if not row_date or row_date > current_date:
            continue
        if after_date is not None and row_date <= after_date:
            continue
        return row
    return None
''',
        "price-row date bounds",
    )

    compile(text, str(PAPER_PATH), "exec")
    PAPER_PATH.write_text(text, encoding="utf-8")
    print("Fixed paper-trading stale fills, order expiry and trading-day counts")


def patch_scoring() -> None:
    text = SCORING_PATH.read_text(encoding="utf-8")
    text = replace_one(
        text,
        '            "institutional_trend": "偏多" if total_inst_3d > 0 else "偏空",\n',
        '''            "institutional_trend": (
                "偏多" if total_inst_3d > 0 else "偏空" if total_inst_3d < 0 else "中性"
            ),
''',
        "neutral institutional flow",
    )
    compile(text, str(SCORING_PATH), "exec")
    SCORING_PATH.write_text(text, encoding="utf-8")
    print("Fixed neutral institutional-flow label")


def patch_storage() -> None:
    text = STORAGE_PATH.read_text(encoding="utf-8")

    if "import json\n" not in text:
        text = text.replace("import math\n", "import json\nimport math\n", 1)

    text = replace_one(
        text,
        '''    def fetch_stock_month(self, stock_id: str, year_month: str) -> dict:
        cache_path = Path(CACHE_DIR) / f"twse_stock_day_{stock_id}_{year_month}.json"
        params = {"response": "json", "date": f"{year_month}01", "stockNo": stock_id}
        return self._fetch_json(self.STOCK_DAY_URL, params=params, cache_path=cache_path)
''',
        '''    def fetch_stock_month(self, stock_id: str, year_month: str) -> dict:
        today = date.today()
        cache_suffix = (
            f"{year_month}_{today.isoformat()}"
            if year_month == today.strftime("%Y%m")
            else year_month
        )
        cache_path = Path(CACHE_DIR) / f"twse_stock_day_{stock_id}_{cache_suffix}.json"
        params = {"response": "json", "date": f"{year_month}01", "stockNo": stock_id}
        return self._fetch_json(self.STOCK_DAY_URL, params=params, cache_path=cache_path)
''',
        "current-month cache freshness",
    )

    text = replace_one(
        text,
        '''        if cache_path and cache_path.exists():
            return self._read_cache(cache_path)
''',
        '''        if cache_path and cache_path.exists():
            try:
                return self._read_cache(cache_path)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                cache_path.unlink(missing_ok=True)
''',
        "corrupt cache recovery",
    )

    text = replace_one(
        text,
        '''        if cache_path:
            cache_path.write_text(response.text, encoding="utf-8")
''',
        '''        if cache_path:
            temp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
            temp_path.write_text(response.text, encoding="utf-8")
            temp_path.replace(cache_path)
''',
        "atomic cache writes",
    )

    text = replace_one(
        text,
        '''    @staticmethod
    def _read_cache(cache_path: Path):
        import json

        return json.loads(cache_path.read_text(encoding="utf-8"))
''',
        '''    @staticmethod
    def _read_cache(cache_path: Path):
        return json.loads(cache_path.read_text(encoding="utf-8"))
''',
        "cache JSON import",
    )

    text = replace_one(
        text,
        '''    @staticmethod
    def _safe_float(value: object) -> float | None:
        if value in ("", None, "--", "---"):
            return None
        return float(str(value).replace(",", ""))

    @staticmethod
    def _safe_int(value: object) -> int:
        if value in ("", None, "--", "---"):
            return 0
        return int(str(value).replace(",", ""))
''',
        '''    @staticmethod
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
''',
        "robust numeric parsing",
    )

    compile(text, str(STORAGE_PATH), "exec")
    STORAGE_PATH.write_text(text, encoding="utf-8")
    print("Fixed TWSE cache freshness, corruption recovery and numeric parsing")


def patch_readme() -> None:
    text = README_PATH.read_text(encoding="utf-8")
    text = text.replace("HISTORY_LIMIT=30", "HISTORY_LIMIT=0\nPAPER_HISTORY_LIMIT=0")
    if "PAPER_ORDER_MAX_CALENDAR_DAYS=" not in text:
        text = text.replace(
            "PAPER_MAX_NEW_BUYS_PER_DAY=2\n",
            "PAPER_MAX_NEW_BUYS_PER_DAY=2\nPAPER_ORDER_MAX_CALENDAR_DAYS=7\n",
        )
    text = text.replace(
        "網站若找到 `data/site_snapshot.json`，會優先讀取快照；沒有快照時才會即時抓資料。",
        "網站只讀取 `data/site_snapshot.json`；沒有快照時會提示先執行 GitHub Actions，不會在免費主機上即時重跑完整分析。",
    )
    text = text.replace(
        "[deploy/cron.example](/c:/Users/USER/Desktop/tw_stock_assistant/deploy/cron.example)",
        "[deploy/cron.example](deploy/cron.example)",
    )
    text = text.replace(
        "[refresh_snapshot.yml](/c:/Users/USER/Desktop/tw_stock_assistant/.github/workflows/refresh_snapshot.yml)",
        "[refresh_snapshot.yml](.github/workflows/refresh_snapshot.yml)",
    )
    README_PATH.write_text(text, encoding="utf-8")
    print("Updated README to match current deployment and history behavior")


def main() -> None:
    patch_app()
    patch_config()
    patch_paper_trading()
    patch_scoring()
    patch_storage()
    patch_readme()


if __name__ == "__main__":
    main()

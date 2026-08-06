from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = ROOT / "modules" / "analysis_service.py"
SNAPSHOT_PATH = ROOT / "modules" / "site_snapshot.py"


def replace_one(text: str, old: str, new: str, label: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise RuntimeError(f"Could not locate source fragment for {label}")


def patch_analysis_service() -> None:
    text = ANALYSIS_PATH.read_text(encoding="utf-8")

    text = replace_one(
        text,
        '''def analyze_market(
    watchlist_symbols: list[str],
    candidate_symbols: list[str] | None = None,
) -> AnalysisBundle:
''',
        '''def analyze_market(
    watchlist_symbols: list[str],
    candidate_symbols: list[str] | None = None,
    price_only_symbols: list[str] | None = None,
) -> AnalysisBundle:
''',
        "price-only analysis parameter",
    )

    text = replace_one(
        text,
        '''    symbols_to_fetch = normalized_watchlist + normalized_candidates

    raw_data: dict[str, dict] = {}
''',
        '''    normalized_price_only = [
        symbol
        for symbol in _normalize_unique_symbols(price_only_symbols or [])
        if symbol not in normalized_watchlist and symbol not in normalized_candidates
    ]
    symbols_to_fetch = (
        normalized_watchlist + normalized_candidates + normalized_price_only
    )

    raw_data: dict[str, dict] = {}
''',
        "price-only symbol set",
    )

    text = replace_one(
        text,
        '''        raw_data[symbol] = stock_data
        result = engine.evaluate(stock_data)
        if result:
            evaluations[symbol] = result
''',
        '''        raw_data[symbol] = stock_data
        if symbol in normalized_price_only:
            continue

        result = engine.evaluate(stock_data)
        if result:
            evaluations[symbol] = result
''',
        "price-only evaluation skip",
    )

    compile(text, str(ANALYSIS_PATH), "exec")
    ANALYSIS_PATH.write_text(text, encoding="utf-8")
    print("Analysis service now fetches price-only symbols without ranking them")


def patch_site_snapshot() -> None:
    text = SNAPSHOT_PATH.read_text(encoding="utf-8")

    if "from modules.paper_trading import simulate_paper_portfolio\n" not in text:
        text = text.replace(
            "from modules.ai_reporter import AIReporter\n",
            "from modules.ai_reporter import AIReporter\nfrom modules.paper_trading import simulate_paper_portfolio\n",
            1,
        )

    text = replace_one(
        text,
        '''    bundle = analyze_market(watchlist, candidate_pool)
    recommendations = get_recommendations(bundle)
''',
        '''    paper_result = simulate_paper_portfolio()
    paper_symbols = sorted(
        {
            item.get("symbol", "")
            for item in [*paper_result.positions, *paper_result.pending_orders]
            if item.get("symbol")
        }
    )
    bundle = analyze_market(
        watchlist,
        candidate_pool,
        price_only_symbols=paper_symbols,
    )
    recommendations = get_recommendations(bundle)
''',
        "paper-position price tracking",
    )

    compile(text, str(SNAPSHOT_PATH), "exec")
    SNAPSHOT_PATH.write_text(text, encoding="utf-8")
    print("Snapshot refresh now retains prices for paper positions and pending orders")


def main() -> None:
    patch_analysis_service()
    patch_site_snapshot()


if __name__ == "__main__":
    main()

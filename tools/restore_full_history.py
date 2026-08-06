from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAPER_PATH = ROOT / "modules" / "paper_trading.py"
SNAPSHOT_PATH = ROOT / "modules" / "site_snapshot.py"


def patch_paper_trading() -> None:
    text = PAPER_PATH.read_text(encoding="utf-8")
    text = text.replace("    HISTORY_LIMIT,\n", "    PAPER_HISTORY_LIMIT,\n", 1)

    old = '        paths = sorted(HISTORY_DIR.glob("site_snapshot_*.json"))[-HISTORY_LIMIT:]\n'
    new = (
        '        paths = sorted(HISTORY_DIR.glob("site_snapshot_*.json"))\n'
        '        if PAPER_HISTORY_LIMIT > 0:\n'
        '            paths = paths[-PAPER_HISTORY_LIMIT:]\n'
    )
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise RuntimeError("Could not locate paper-trading history limit")

    compile(text, str(PAPER_PATH), "exec")
    PAPER_PATH.write_text(text, encoding="utf-8")
    print("Paper trading now uses complete history by default")


def patch_snapshot_history() -> None:
    text = SNAPSHOT_PATH.read_text(encoding="utf-8")
    old = (
        '    paths = sorted(HISTORY_DIR.glob("site_snapshot_*.json"), reverse=True)[:limit]\n'
    )
    new = (
        '    paths = sorted(HISTORY_DIR.glob("site_snapshot_*.json"), reverse=True)\n'
        '    if limit > 0:\n'
        '        paths = paths[:limit]\n'
    )
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise RuntimeError("Could not locate displayed history limit")

    compile(text, str(SNAPSHOT_PATH), "exec")
    SNAPSHOT_PATH.write_text(text, encoding="utf-8")
    print("History table now shows complete history by default")


def main() -> None:
    patch_paper_trading()
    patch_snapshot_history()


if __name__ == "__main__":
    main()

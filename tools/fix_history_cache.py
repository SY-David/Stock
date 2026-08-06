from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"


def main() -> None:
    text = APP_PATH.read_text(encoding="utf-8")

    if "import hashlib\n" not in text:
        text = text.replace(
            "from datetime import datetime\n",
            "from datetime import datetime\nimport hashlib\n",
            1,
        )

    old = '''def history_marker() -> str:
    if not HISTORY_DIR.exists():
        return "none"
    rows = []
    for path in sorted(HISTORY_DIR.glob("site_snapshot_*.json"))[-20:]:
        rows.append(f"{path.name}:{int(path.stat().st_mtime)}")
    return "|".join(rows)
'''
    new = '''def history_marker() -> str:
    if not HISTORY_DIR.exists():
        return "none"

    paths = sorted(HISTORY_DIR.glob("site_snapshot_*.json"))
    digest = hashlib.sha256()
    for path in paths:
        stat = path.stat()
        digest.update(
            f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}\\n".encode("utf-8")
        )
    return f"{len(paths)}:{digest.hexdigest()}"
'''

    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise RuntimeError("Could not locate history_marker in app.py")

    compile(text, str(APP_PATH), "exec")
    APP_PATH.write_text(text, encoding="utf-8")
    print("History cache marker now includes the complete snapshot set")


if __name__ == "__main__":
    main()

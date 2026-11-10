from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RETRY_DELAYS = (10, 30)
TRANSIENT_ERRORS = (
    "fatal error in commit_refs_rules",
    "internal server error",
    "the requested url returned error: 500",
    "the requested url returned error: 502",
    "the requested url returned error: 503",
    "the requested url returned error: 504",
    "remote end hung up unexpectedly",
    "connection reset",
    "connection timed out",
    "could not resolve host",
)


def push_snapshot() -> int:
    max_attempts = len(RETRY_DELAYS) + 1
    for attempt in range(1, max_attempts + 1):
        print(f"Pushing snapshot: attempt {attempt}/{max_attempts}", flush=True)
        try:
            result = subprocess.run(
                ["git", "push", "origin", "HEAD:main"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            print("Git push timed out after 120 seconds.", file=sys.stderr, flush=True)
            return_code = 1
            retryable = True
        else:
            if result.stdout:
                print(result.stdout, end="", flush=True)
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr, flush=True)
            return_code = result.returncode
            if return_code == 0:
                return 0
            output = (result.stdout + result.stderr).lower()
            retryable = any(error in output for error in TRANSIENT_ERRORS)

        if not retryable or attempt == max_attempts:
            return return_code
        delay = RETRY_DELAYS[attempt - 1]
        print(f"Transient push failure; retrying in {delay} seconds.", flush=True)
        time.sleep(delay)

    return 1


if __name__ == "__main__":
    raise SystemExit(push_snapshot())

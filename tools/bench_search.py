"""Measure the optional Rust core against the pure-Python fallbacks.

There were no numbers anywhere for the native extension, only claims that it
accelerates hot paths.  This script runs the same local work twice — once with
the extension, once with `native.core` forced to None — and prints the ratio.
It never writes to the library, and it works whether or not the extension is
installed (with the extension absent, both columns are Python).

Usage: python3 tools/bench_search.py [repeats]
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gbible import db, native, search          # noqa: E402


def bench(fn, repeats: int) -> float:
    """Best of `repeats`, in milliseconds — scheduling noise is excluded."""
    best = float("inf")
    for _ in range(max(1, repeats)):
        started = time.perf_counter()
        fn()
        best = min(best, (time.perf_counter() - started) * 1000)
    return best


def main() -> int:
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    core = native.core
    print("native core:", native.status().get("engine", "unknown"))
    print("repeats:", repeats, "(best time shown)")

    # One unit's worth of text, tokenized repeatedly.  This is the hot path
    # the Rust tokenizer was added for.
    conn = db.connect()
    row = conn.execute(
        "SELECT text FROM unit WHERE length(text)>600 LIMIT 1").fetchone()
    sample = (row["text"] if row else "faith hope love and grace ") * 4

    cases = {
        "tokenize+key": lambda: [db.token_key(w) for w, _a, _b in db.words(sample)],
        "search 'faith'": lambda: search.search(
            "faith", search.SearchOpts(limit=20, smart=False)),
        "search 'faith AND hope'": lambda: search.search(
            "faith AND hope", search.SearchOpts(limit=20, smart=False)),
        "search phrase": lambda: search.search(
            '"faith in God"', search.SearchOpts(limit=20, smart=False)),
    }

    print(f"{'case':24} {'native ms':>10} {'python ms':>10} {'ratio':>7}")
    for name, fn in cases.items():
        native.core = core
        fast = bench(fn, repeats)
        native.core = None
        slow = bench(fn, repeats)
        ratio = slow / fast if fast else 0.0
        print(f"{name:24} {fast:10.2f} {slow:10.2f} {ratio:7.2f}x")
    native.core = core
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

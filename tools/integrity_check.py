"""Offline integrity check for gbible.db.

    python3 tools/integrity_check.py

Runs SQLite's PRAGMA integrity_check and foreign_key_check against the local
database without blocking application startup.  A full check on a large library
can take a while, which is why it is not run on every launch.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gbible import db


def main() -> int:
    p = db.db_path()
    print(f"Database: {p}", flush=True)
    if not p.exists():
        print("No database yet.", flush=True)
        return 0
    conn = db.connect()
    t0 = time.time()
    print("Running integrity_check (this may take a while on a large library)...", flush=True)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        res = row[0] if row else "no result"
    except Exception as e:
        print(f"ERROR: {e}", flush=True)
        return 1
    print(f"integrity_check: {res} ({time.time() - t0:.1f}s)", flush=True)
    t0 = time.time()
    try:
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    except Exception as e:
        print(f"foreign_key_check error: {e}", flush=True)
        return 1
    print(f"foreign_key_check: {len(fk)} violation(s) ({time.time() - t0:.1f}s)", flush=True)
    for r in fk[:20]:
        print("  ", dict(r), flush=True)
    return 0 if (res == "ok" and not fk) else 1


if __name__ == "__main__":
    raise SystemExit(main())
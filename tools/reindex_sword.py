"""Re-index a SWORD module from the package already on disk.

    python3 tools/reindex_sword.py <module-id> [<module-id> ...] [--dry-run]
    python3 tools/reindex_sword.py --all          # every SWORD module

Every SWORD module installed through the Store lost its first forty
units.  The installer read them to check the package had produced
readable text, and handed the same generator on to the indexer; a
generator cannot be rewound, so those forty were never installed.

Barnes had no Genesis 1:1.  Hitchcock's Bible Names was short of its
first forty names, so it had no entry for Aaron -- and the fact guide,
which names the people in a passage out of the fact books, could name
nobody.

This re-runs the parse over the bytes already downloaded, so the repair
needs no network and no Store: every module's own folder holds the
package it was installed from.

It is a re-index, not a reinstall: the module keeps its id, its name,
its licence, its place in the library and its collection membership.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gbible import db, formats, indexer, library      # noqa: E402


def package_of(module_id: str) -> Path | None:
    """The SWORD package the module was installed from, if it is still there."""
    row = db.connect().execute(
        "SELECT path FROM module WHERE id=?", (module_id,)).fetchone()
    if not row or not row["path"]:
        return None
    p = Path(row["path"]) / "module.zip"
    return p if p.is_file() else None


def reindex(module_id: str, *, dry_run: bool = False) -> dict:
    conn = db.connect()
    old = conn.execute("SELECT name, type, entries FROM module WHERE id=?",
                       (module_id,)).fetchone()
    if old is None:
        return {"ok": False, "error": f"{module_id!r} is not installed"}
    pkg = package_of(module_id)
    if pkg is None:
        return {"ok": False, "error":
                f"the package for {module_id!r} is not on disk; reinstall it "
                f"from the Store instead"}

    data = pkg.read_bytes()
    _conf, units, _meta = formats.load_sword_zip(data)
    got = list(units)
    if not got:
        return {"ok": False, "error": f"{module_id!r} yielded no units"}

    if dry_run:
        return {"ok": True, "dry_run": True, "before": old["entries"],
                "after": len(got)}

    t0 = time.time()
    library.mark_removed(conn, module_id)
    conn.commit()
    stats = indexer.run_import(module_id, iter(got),
                               folder=module_id,
                               path=str(pkg.parent))
    new = conn.execute("SELECT entries FROM module WHERE id=?",
                       (module_id,)).fetchone()
    return {"ok": True, "before": old["entries"], "after": new["entries"],
            "gained": new["entries"] - old["entries"],
            "secs": round(time.time() - t0, 1), "stats": stats}


def all_sword_modules() -> list[str]:
    conn = db.connect()
    return [r["id"] for r in conn.execute(
        "SELECT id FROM module WHERE installed_at>0 AND source='crosswire' "
        "ORDER BY id").fetchall()]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("modules", nargs="*", help="module ids to re-index")
    ap.add_argument("--all", action="store_true",
                    help="every SWORD module in the library")
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would happen, and change nothing")
    a = ap.parse_args(argv)

    ids = a.modules or (all_sword_modules() if a.all else [])
    if not ids:
        print("name the modules to re-index, or pass --all")
        return 1

    gained = 0
    failed = 0
    for mid in ids:
        r = reindex(mid, dry_run=a.dry_run)
        if not r.get("ok"):
            print(f"  FAIL {mid}: {r.get('error')}")
            failed += 1
            continue
        if r.get("dry_run"):
            print(f"  {mid:32} {r['before']:>8,} -> {r['after']:>8,} "
                  f"(+{r['after'] - r['before']:,})")
            continue
        g = r.get("gained", 0)
        gained += max(0, g)
        print(f"  {mid:32} {r['before']:>8,} -> {r['after']:>8,} "
              f"(+{g:,}) in {r['secs']}s")
    if not a.dry_run:
        print(f"\n{len(ids) - failed} modules re-indexed, {failed} failed, "
              f"{gained:,} units recovered")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

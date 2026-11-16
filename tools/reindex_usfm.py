"""Re-index a USFM module from the source package already on disk.

    python3 tools/reindex_usfm.py <module-id> [<module-id> ...] [--dry-run]
    python3 tools/reindex_usfm.py --all          # every USFM module in the library

USFM Bibles from eBible.org install from a `source.zip` stored in the
module's own folder before conversion.  This re-runs the parse over those
bytes already downloaded, so a fix to the USFM importer applies to an
installed module without going back to the network:

    python3 tools/reindex_usfm.py ebible-engwebp

It keeps the module's id, name, licence and library placement, and only
rebuilds its units, markers and search index.
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
    """The USFM package the module was installed from, if it is still there."""
    row = db.connect().execute(
        "SELECT path FROM module WHERE id=?", (module_id,)).fetchone()
    if not row or not row["path"]:
        return None
    p = Path(row["path"]) / "source.zip"
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
    got = list(formats.load_usfm_zip(data))
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


def all_usfm_modules() -> list[str]:
    conn = db.connect()
    return [r["id"] for r in conn.execute(
        "SELECT id FROM module WHERE installed_at>0 AND source='ebible' "
        "ORDER BY id").fetchall()]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("modules", nargs="*", help="module ids to re-index")
    ap.add_argument("--all", action="store_true",
                    help="every USFM module in the library")
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would happen, and change nothing")
    a = ap.parse_args(argv)

    ids = a.modules or (all_usfm_modules() if a.all else [])
    if not ids:
        print("name the modules to re-index, or pass --all")
        return 1

    failed = 0
    for mid in ids:
        r = reindex(mid, dry_run=a.dry_run)
        if not r.get("ok"):
            print(f"  FAIL {mid}: {r.get('error')}")
            failed += 1
            continue
        if r.get("dry_run"):
            print(f"  {mid:32} {r['before']:>8,} -> {r['after']:>8,}")
            continue
        print(f"  {mid:32} {r['before']:>8,} -> {r['after']:>8,} "
              f"(+{r.get('gained', 0):,}) in {r['secs']}s")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Repair the full-text index where it disagrees with the unit table.

`unit.text` is the source of truth.  `unit_fts` is derived from it, and it had
drifted: 14,024 rows across 39 modules held text that was not the text of the
unit they were filed against.  Barnes' notes are the clearest case -- a FTS row
keyed `Rev.2.6` held 6,761 characters where the unit holds 47.

Why that matters is not staleness in the abstract.  FTS5 decides which units
match, so a row holding the wrong text matches the wrong queries.  A search for
`faith hope` came back with the article on the Jovinianists and with Barnes on
Revelation 2:6 -- units whose real text contains neither word.  The reader is
shown a hit that does not exist.

Nothing catches this on its own, because both tables look healthy and every
query succeeds.  So:

    python3 tools/rebuild_fts.py            # report what disagrees
    python3 tools/rebuild_fts.py --repair   # rewrite those modules' FTS rows

The check is `length()` rather than a content comparison, which is what makes it
cheap enough to run over 1.2 million rows; a full text comparison is the repair's
job, not the detector's.  Repair rewrites a module's FTS rows from `unit.text`,
in batches, and is safe to interrupt and re-run.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gbible import db  # noqa: E402

BATCH = 2000


def disagreements(only_modules: list[str] | None = None) -> list[dict]:
    """Modules whose FTS rows do not match their unit text, by length."""
    conn = db.connect()
    sql = (
        "SELECT f.module_id AS m, COUNT(*) AS n, "
        "  SUM(CASE WHEN length(u.text) <> length(f.text) THEN 1 ELSE 0 END) AS mism, "
        "  SUM(CASE WHEN u.rowid IS NULL THEN 1 ELSE 0 END) AS orphan "
        "FROM unit_fts f LEFT JOIN unit u "
        "  ON u.module_id = f.module_id AND u.key = f.unit_key "
    )
    params: list = []
    if only_modules:
        ph = ",".join("?" * len(only_modules))
        sql += f" WHERE f.module_id IN ({ph})"
        params += only_modules
    sql += " GROUP BY f.module_id"
    out = []
    for r in conn.execute(sql, params):
        mism = r["mism"] or 0
        orphan = r["orphan"] or 0
        if mism or orphan:
            out.append({"module_id": r["m"], "rows": r["n"],
                        "mismatched": mism, "orphan": orphan})
    out.sort(key=lambda x: -x["mismatched"])
    return out


def _delete_module(conn, mid: str) -> int:
    """Remove a module's FTS rows.

    FTS5 wants a rowid or a MATCH to delete.  module_id is UNINDEXED, so a plain
    `WHERE module_id=?` may not qualify; deleting by rowid always does, and the
    rowids are obtained by the same scan that found them.
    """
    try:
        cur = conn.execute("DELETE FROM unit_fts WHERE module_id=?", (mid,))
        if cur.rowcount and cur.rowcount > 0:
            return cur.rowcount
    except Exception:
        pass
    ids = [r["rowid"] for r in conn.execute(
        "SELECT rowid FROM unit_fts WHERE module_id=?", (mid,))]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        conn.execute("DELETE FROM unit_fts WHERE rowid IN (%s)"
                     % ",".join("?" * len(chunk)), chunk)
    return len(ids)


def repair(module_ids: list[str], *, verbose: bool = True) -> dict:
    conn = db.connect()
    t0 = time.time()
    written = 0
    for mid in module_ids:
        rows = conn.execute(
            # COALESCE needs the alias: an unaliased expression has no usable
            # column name, so r["title"] raises rather than returning "".
            "SELECT module_id, key, COALESCE(title,'') AS title, text FROM unit "
            "WHERE module_id=? ORDER BY key", (mid,)).fetchall()
        _delete_module(conn, mid)
        buf = []
        for r in rows:
            buf.append((r["module_id"], r["key"], r["title"], r["text"] or ""))
            if len(buf) >= BATCH:
                conn.executemany(
                    "INSERT INTO unit_fts(module_id,unit_key,title,text) "
                    "VALUES(?,?,?,?)", buf)
                written += len(buf)
                buf = []
        if buf:
            conn.executemany(
                "INSERT INTO unit_fts(module_id,unit_key,title,text) VALUES(?,?,?,?)",
                buf)
            written += len(buf)
        conn.commit()
        if verbose:
            print(f"  {mid:<32} rewrote {len(rows):>7} rows")
    return {"ok": True, "modules": len(module_ids), "rows": written,
            "seconds": round(time.time() - t0, 1)}


def main(argv: list[str]) -> int:
    do_repair = "--repair" in argv
    names = [a for a in argv if not a.startswith("-")]
    bad = disagreements(names or None)
    if not bad:
        print("  the full-text index agrees with the unit table")
        return 0
    total = sum(b["mismatched"] + b["orphan"] for b in bad)
    print(f"  {len(bad)} module(s) disagree with the unit table, "
          f"{total:,} rows")
    for b in bad[:15]:
        print(f"    {b['module_id']:<34} {b['mismatched']:>7} mismatched"
              + (f", {b['orphan']} orphaned" if b["orphan"] else ""))
    if len(bad) > 15:
        print(f"    ... and {len(bad) - 15} more")
    if not do_repair:
        print("\n  Re-run with --repair to rewrite those modules from unit.text.")
        return 1
    print()
    r = repair([b["module_id"] for b in bad])
    print(f"  rewrote {r['rows']:,} rows across {r['modules']} modules "
          f"in {r['seconds']}s")
    left = disagreements()
    if left:
        print(f"  {len(left)} module(s) still disagree -- run again")
        return 1
    print("  the full-text index now agrees with the unit table")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
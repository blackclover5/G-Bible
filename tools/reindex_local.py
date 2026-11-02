"""Re-index a module from the source files already on disk.

    python3 tools/reindex_local.py <module-id> [--dry-run]

Most importers write their download into the module's own folder before
converting it, so the source is usually still there.  That makes a fix to an
importer repairable without going back to the network: point this at a module
whose text was built wrongly and it re-runs the parse over the bytes already
downloaded.

This exists because of a real defect it was written for.  The OSHB Hebrew
importer joined one segment per word with nothing between them, and
`markup.segs_flatten` adds no separator of its own, so all 23,213 verses went
into the database as single unsearchable blobs -- a search for one Hebrew word
across the whole Hebrew Bible returned nothing, and 295,403 morphology markers
sat on text no query could reach.  Fixing the importer is half the job; the
other half is getting the fixed text back in, which is what this does.

It refuses to guess.  If the module folder has no source files, it says so
rather than reporting a successful re-index of nothing.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gbible import db, indexer, library                    # noqa: E402
from gbible.importers import runner                          # noqa: E402


def sources_for(module_id: str) -> list[Path]:
    d = db.modules_dir() / module_id
    if not d.is_dir():
        return []
    skip = (".orig", ".conf", ".zip")
    return sorted(p for p in d.iterdir()
                  if p.is_file() and p.suffix.lower() in (".xml", ".usfm",
                                                           ".txt", ".osis"))


def rebuild(module_id: str, *, dry_run: bool = False) -> dict:
    files = sources_for(module_id)
    if not files:
        return {"ok": False, "error":
                f"no source files in the module folder for {module_id!r}; "
                f"reinstall it from the Store instead"}

    conn = db.connect()
    old = conn.execute("SELECT name, type, lang, entries FROM module WHERE id=?",
                       (module_id,)).fetchone()
    if old is None:
        return {"ok": False, "error": f"{module_id!r} is not installed"}

    if dry_run:
        return {"ok": True, "dry_run": True, "files": len(files),
                "first": files[0].name,
                "before": {"units": old["entries"], "name": old["name"]}}

    units: list = []
    t0 = time.time()
    for i, f in enumerate(files, 1):
        raw = f.read_bytes()
        if f.suffix.lower() == ".xml":
            try:
                units.extend(runner._os_verse_units(_root(raw)))
            except Exception as e:               # noqa: BLE001
                print(f"  {f.name}: {type(e).__name__}: {e}")
        else:
            units.extend(runner._sbl_units(raw.decode("utf-8", "replace"),
                                           f.name))
        if i % 10 == 0:
            print(f"  parsed {i}/{len(files)} files, {len(units):,} units")

    if not units:
        return {"ok": False, "error": "the source files yielded no units; "
                                      "the importer change did not apply"}

    library.mark_removed(conn, module_id)
    conn.commit()
    # Name only what this re-index actually decides.  `library.register` is a
    # partial upsert, so everything else on the row survives by itself -- no list
    # of fields to keep in step with the schema, and no way for a future column
    # to be forgotten here.
    #
    # This used to name six fields and hardcode a seventh, when `register` was
    # an `INSERT OR REPLACE` over whatever it was handed.  Everything it did not
    # name was reset, which is how `openscriptures-morphhb` ended up a CC BY 4.0
    # module with no `rights` at all: no `subject`, no `source_url`, no
    # `format`, no `raw_meta`, and nobody to credit.  `license_audit.py` could
    # not catch it, because the *licence* was still present.
    stats = indexer.run_import(module_id, iter(units),
                               folder=module_id,
                               path=str(db.modules_dir() / module_id))
    new = conn.execute("SELECT entries, verses FROM module WHERE id=?",
                       (module_id,)).fetchone()
    sample = conn.execute("SELECT key, text, word_count FROM unit "
                          "WHERE module_id=? AND key=?",
                          (module_id, "Gen.1.1")).fetchone()
    return {"ok": True, "files": len(files), "units_before": old["entries"],
            "units_after": new["entries"], "secs": round(time.time() - t0, 1),
            "sample": {"key": sample["key"], "words": sample["word_count"],
                       "text": (sample["text"] or "")[:90]} if sample else None,
            "stats": stats}


def _root(raw: bytes):
    import xml.etree.ElementTree as ET
    return ET.fromstring(raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("module_id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    db.init()
    r = rebuild(args.module_id, dry_run=args.dry_run)
    if not r.get("ok"):
        print(r.get("error"))
        return 1
    if r.get("dry_run"):
        print(f"{r['files']} source file(s), first {r['first']}; "
              f"{r['before']['units']:,} units now")
        return 0
    print(f"{r['units_before']:,} -> {r['units_after']:,} units "
          f"from {r['files']} files in {r['secs']}s")
    if r.get("sample"):
        s = r["sample"]
        print(f"  {s['key']}: {s['words']} words — {s['text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
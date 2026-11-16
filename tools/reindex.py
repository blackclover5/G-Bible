"""Re-index any installed module from the source files it was installed from.

    python3 tools/reindex.py <module-id> [<module-id> ...] [--dry-run]
    python3 tools/reindex.py --all [--dry-run]

Every importer writes its source into the module's own folder (the Store
keeps the downloaded zip, uploads keep the original file as ``<name>.orig``),
so most modules can be rebuilt without going back to the network.  This is
the tool for picking up a parser fix in modules that were installed before
it — including uploads, which the SWORD-only and USFM-only scripts cannot
reach.

Units, markers and search rows are rebuilt; the module row, its library
placement, your notes and highlights are kept.  Like the other reindex
tools it is a re-index, not a reinstall: it keeps the module id.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gbible import db, formats, indexer, library          # noqa: E402
from gbible.importers import runner                        # noqa: E402


def _candidates(folder: Path) -> list[Path]:
    """Likely source files for the module, most specific first."""
    if not folder.is_dir():
        return []
    out: list[Path] = []
    for name in ("module.zip", "source.zip"):
        p = folder / name
        if p.is_file():
            out.append(p)
    out += sorted(folder.glob("*.orig"))          # uploads: the .orig copy
    for p in sorted(folder.iterdir()):
        if not p.is_file():
            continue
        n = p.name.lower()
        if n in ("module.zip", "source.zip") or n.endswith(".orig"):
            continue
        if p.suffix.lower() in (".conf", ".txt", ".json", ".jpg", ".jpeg",
                                ".png", ".svg", ".gif", ".css", ".js"):
            continue
        out.append(p)
    return out


def reindex(module_id: str, *, dry_run: bool = False) -> dict:
    conn = db.connect()
    old = conn.execute(
        "SELECT name, type, path, entries, source FROM module WHERE id=?",
        (module_id,)).fetchone()
    if old is None:
        return {"ok": False, "error": f"{module_id!r} is not installed"}
    # Modules built by purpose-built importers (openscriptures, macula,
    # stepbible, midvash, wikisource, gutenberg, ccel, wikimedia, ...) have no
    # bytes-to-units path through the local dispatch.  They are permanently
    # ineligible: not a failure, just not this tool.
    if old["source"] not in ("local", "ebible", "crosswire", "open-bibles"):
        return {"skip": True, "source": old["source"]}
    folder = Path(old["path"] or (db.modules_dir() / module_id))

    it = {"category": old["type"], "path": ""}
    tried: list[str] = []
    for cand in _candidates(folder):
        name = cand.name[:-5] if cand.name.lower().endswith(".orig") else cand.name
        data = cand.read_bytes()
        it["path"] = str(cand)
        try:
            source_path = Path(name)
            got = list(_units_for(data, source_path, it))
            if not got:
                raise runner.InstallErrorFailed("yielded no units")
        except Exception as e:
            tried.append(f"{cand.name}: {type(e).__name__}")
            continue
        if dry_run:
            return {"ok": True, "dry_run": True, "src": cand.name,
                    "before": old["entries"], "after": len(got)}
        library.mark_removed(conn, module_id)
        conn.commit()
        stats = indexer.run_import(module_id, iter(got),
                                   folder=module_id, path=str(folder))
        new = conn.execute("SELECT entries FROM module WHERE id=?",
                           (module_id,)).fetchone()
        return {"ok": True, "src": cand.name, "before": old["entries"],
                "after": new["entries"], "gained": new["entries"] - old["entries"],
                "stats": stats}

    detail = "; ".join(tried) if tried else "no source files found"
    return {"ok": False, "error": f"no readable source for {module_id!r} ({detail})"}


def _units_for(data: bytes, source_path: Path, it: dict):
    """Route bytes through exactly the dispatch an upload uses."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="gbible-reindex-") as td:
        workdir = Path(td)
        # _import_local_bytes reads the file it is given; give it a real name.
        staged = workdir / source_path.name
        staged.write_bytes(data)
        units, _extra = runner._import_local_bytes(
            data, path=staged, it=it, workdir=workdir)
        # Materialise inside the with-block (legacy e-Sword stages here).
        return list(units)


def all_module_ids() -> list[str]:
    conn = db.connect()
    return [r["id"] for r in conn.execute(
        "SELECT id FROM module WHERE installed_at>0 ORDER BY id").fetchall()]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("modules", nargs="*", help="module ids to re-index")
    ap.add_argument("--all", action="store_true", help="every installed module")
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would happen, and change nothing")
    a = ap.parse_args(argv)

    ids = a.modules or (all_module_ids() if a.all else [])
    if not ids:
        print("name the modules to re-index, or pass --all")
        return 1

    failed = 0
    for mid in ids:
        r = reindex(mid, dry_run=a.dry_run)
        if r.get("skip"):
            print(f"  SKIP {mid:32} purpose-built importer (source={r['source']})")
            continue
        if not r.get("ok"):
            print(f"  FAIL {mid}: {r.get('error')}")
            failed += 1
            continue
        if r.get("dry_run"):
            print(f"  {mid:32} {r['src']:28} "
                  f"{r['before']:>8,} -> {r['after']:>8,}")
            continue
        print(f"  {mid:32} {r['src']:28} "
              f"{r['before']:>8,} -> {r['after']:>8,} (+{r.get('gained', 0):,})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

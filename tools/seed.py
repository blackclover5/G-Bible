"""Seed a library with one representative module per resource type.

The self-test is only meaningful against real content, and installing twenty
modules by hand is slow and easy to get wrong.  This installs a deliberately
small set that between them exercise every reader and every placement slot:

    Bible              eBible WEB USFM        verse reader, Strong's
    Bible (2nd)        open-bibles KJV         the Bible the checks name
    Commentary         Barnes                 verse reader, links to the Bible
    Commentary (2nd)   TSK                    verse reader, another voice
    FactBook           Nave's Topical Bible  topic reader
    FactBook (2nd)     Hitchcock's Names      names reader
    Concordance        Strong's               article reader, Strong's keys
    Dictionary         Easton                 article reader, headwords
    Dictionary (2nd)   Webster 1806           a full text to rank against
    Lexicon            Abbott-Smith           headword lookup
    OriginalLanguage   SBLGNT                 own versification
    Devotional         Daily Light            date reader
    Book               Jewish Thoughts        book reader
    Map                Exodus map             image reader
    Atlas              Jerusalem              place coordinates
    Bible (2nd repo)   Textus Receptus        proves two repos coexist

    python3 tools/seed.py            # skip anything already installed
    python3 tools/seed.py --force    # reinstall everything
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# (repo, item, what it proves)
SEED: tuple[tuple[str, str, str], ...] = (
    ("ebible", "eng-web", "Bible, verse reader, Strong's"),
    ("ebible", "eng-asv", "second translation, parallel comparison"),
    ("open-bibles", "eng-kjv", "the Bible the checks name"),
    ("crosswire", "barnes", "Commentary, links to the Bible"),
    ("crosswire", "tsk", "Commentary, a second voice on the text"),
    ("crosswire", "nave", "FactBook, topic reader"),
    ("crosswire", "hitchcock", "FactBook, names reader"),
    ("wikisource", "strongs-concordance", "Concordance, Strong's lookup"),
    ("wikisource", "eastons-bible-dictionary", "Dictionary, headword lookup"),
    ("crosswire", "webster1806", "Dictionary, a full text to rank against"),
    ("crosswire", "abbottsmithstrongs", "Lexicon, headword lookup"),
    ("crosswire", "daily", "Devotional, date reader"),
    ("gutenberg", "57218", "Book, section reader"),
    ("wikimedia", "ortelius-exodus-1624", "Map, image reader"),
    ("openbible-geo", "jerusalem", "Atlas, place coordinates"),
    ("openscriptures", "sblgnt", "Original language, own versification"),
    ("midvash", "gr-tr", "Bible from a second repository"),
    ("open-bibles", "eng-bsb", "USFX Bible with Strong's on every word"),
)

# The Wikisource ids are page prefixes, not module ids; resolve them here so a
# typo in the table above fails loudly instead of silently installing nothing.
_ALIASES = {
    "easton": "eastons-bible-dictionary",
    "exodus-map": "ortelius-exodus-1624",
}


def _resolve(repo: str, item: str) -> str | None:
    from gbible import store
    want = _ALIASES.get(item, item)
    ids = {str(i.get("id")) for i in store.repo_items(repo)}
    if want in ids:
        return want
    hits = [i for i in ids if want in i or i in want]
    return hits[0] if len(hits) == 1 else None


def main(argv: list[str]) -> int:
    force = "--force" in argv
    from gbible import db, library, placement, store
    db.init()
    store.sync_all()

    have = {m.id for m in library.list_all()}
    ok = skipped = failed = 0
    for repo, item, why in SEED:
        rid = _resolve(repo, item)
        if rid is None:
            print(f"  ??  {repo}/{item}: no such item in the catalogue", flush=True)
            failed += 1
            continue
        mid = f"{repo}-{rid}"
        if mid in have and not force:
            print(f"  --  {repo}/{item:<22} already installed", flush=True)
            skipped += 1
            continue
        t0 = time.time()
        try:
            res = store.install(repo, rid, force=force)
        except Exception as e:                       # noqa: BLE001
            print(f"  XX  {repo}/{item:<22} {type(e).__name__}: {e}", flush=True)
            failed += 1
            continue
        m = library.get(res["module_id"])
        d = placement.describe(m)
        note = f" [reclassified from {d['reclassified_from']}]" if d["reclassified"] else ""
        print(f"  ok  {repo}/{item:<22} {d['slot']:<11} "
              f"{d['reader']:<7} {m.verses or m.entries:>6} units "
              f"{time.time() - t0:5.1f}s{note}", flush=True)
        ok += 1

    mods = library.list_all()
    print(f"\n{len(mods)} modules installed "
          f"({ok} installed, {skipped} skipped, {failed} failed)")
    by_slot: dict[str, int] = {}
    for m in mods:
        by_slot[m.slot] = by_slot.get(m.slot, 0) + 1
    for slot, n in sorted(by_slot.items()):
        label = placement.SLOT_BY_ID[slot].label
        print(f"    {slot:<12} {label:<24} {n}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

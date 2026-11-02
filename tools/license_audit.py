"""Audit what is installed against the licence and date gates.

The gates are checked at install time, which is the only place they used to be
checked.  That leaves a gap: if a catalogue entry is tightened, re-dated, or
dropped, the copy already unpacked into `data/` stays installed and keeps
appearing in search and in study results.  That happened here -- `ebible-eng-web`
is the World English Bible dated 2020 and offered as Public Domain, which the
gate refuses because US copyright runs from publication; it had been installed
before the date gate existed, and taking it out of the catalogue did not take it
out of the library.

Run it:

    python3 tools/license_audit.py           # report only
    python3 tools/license_audit.py --remove  # also remove what fails

Removal is opt-in.  This tool deletes files, so it does nothing destructive
unless asked; that is the difference between a check and a cleaner, and a
report is what you want when you are only asking what is wrong.
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gbible import db, library, taxonomy  # noqa: E402


def audit() -> list[dict]:
    """Every installed module that fails a gate, with the reason."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT id, name, license, year, source FROM module "
        "WHERE installed_at > 0 ORDER BY id").fetchall()
    bad = []
    for r in rows:
        ok, why = taxonomy.redistributable(dict(r))
        if not ok:
            bad.append({"id": r["id"], "name": r["name"],
                        "license": r["license"], "year": r["year"],
                        "reason": why})
    return bad


# ---------------------------------------------------------------- bundled data

BUNDLED = ROOT / "gbible" / "data" / "outlines.json.gz"

#: The only fields a section entry is allowed to carry.
#:
#: This is the whole schema of the committed file: a heading, a scripture
#: reference, and optional sub-headings.  There is no field a paragraph of
#: commentary could be put in, so an entry with a `body` or `text` key is
#: prose that should not be in the repository, and saying so is cheaper than
#: reading it.
ENTRY_FIELDS = frozenset({"title", "ref", "sub"})

#: Ceilings, set from what the file actually contains.
#:
#: The committed headings are 103,328 characters across 2,624 of them, the
#: longest 179.  The same commentary as prose is roughly 2.5 MB.  So a ceiling
#: four times the real thing catches a swap to prose with room to spare for
#: legitimate growth, and no amount of fiddling with individual heading lengths
#: gets under it: headings are short by nature, prose is not, and the total is
#: the measurement that tells them apart.
MAX_HEADING_CHARS = 400_000
MAX_TITLE_CHARS = 400

#: Text that would mean the file contains something other than the authors'
#: own headings: the source library's own matter, or anyone else's.
#:
#: Run over the *content* only, never over the metadata.  The attribution is
#: *supposed* to name the library the headings came from and to say it holds
#: copyright over some of its contents -- that is the honest description of
#: where the file came from, and a scan that flagged its own provenance note
#: would be a scan that had to be disabled.
THIRD_PARTY = re.compile(
    r"christian\s+classics|\bccel\b|plantinga|calvin\s+university"
    r"|all\s+rights\s+reserved|transcribed\s+by|proofread\s+by|typed\s+by"
    r"|https?://|www\.", re.I)

REQUIRED_FIELDS = ("source", "title", "attribution", "note",
                   "license", "year", "rights")


def audit_bundled() -> list[dict]:
    """Does the data committed to the repository pass the same gates?

    The installed modules are all audited above, which left the one piece of
    third-party-derived material that ships *inside* the repository
    unchecked -- 52 KB of Jamieson-Fausset-Brown section headings.  It was
    read, confirmed to be nothing but the authors' own headings, and then
    nobody made sure it stayed that way.  Nothing stops a later rebuild from
    quietly including the commentary prose, or the source library's front
    matter, and the file would still look the same in a diff.

    So it is checked here, against the actual claim being made: public domain,
    no prose, nothing but the authors' own work.
    """
    bad: list[dict] = []

    def fail(reason: str) -> None:
        bad.append({"id": "gbible/data/outlines.json.gz", "name": "JFB outlines",
                    "license": "", "year": "", "reason": reason})

    if not BUNDLED.exists():
        fail("the committed outline file is missing")
        return bad
    try:
        doc = json.loads(gzip.decompress(BUNDLED.read_bytes()).decode("utf-8"))
    except Exception as exc:
        fail(f"it does not decompress to readable JSON: "
             f"{type(exc).__name__}: {exc}")
        return bad

    missing = [f for f in REQUIRED_FIELDS if not str(doc.get(f, "")).strip()]
    if missing:
        fail("it records no provenance for these: " + ", ".join(missing))
        return bad

    # The same date gate the catalogue entries pass, on the same fields.
    ok, why = taxonomy.pd_dated_ok({"id": "outlines", "license": doc["license"],
                                    "year": doc["year"]})
    if not ok:
        fail(f"it claims {doc['license']!r} but {why}")

    books = doc.get("books")
    if not isinstance(books, dict) or not books:
        fail("it carries no books")
        return bad

    entries = 0
    chars = 0
    for book, chapters in books.items():
        if not isinstance(chapters, dict):
            fail(f"{book} is not a set of chapters")
            continue
        for chapter, points in chapters.items():
            if not isinstance(points, list):
                fail(f"{book} {chapter} is not a list of headings")
                continue
            for p in points:
                entries += 1
                if not isinstance(p, dict):
                    fail(f"{book} {chapter} has an entry that is not a heading")
                    continue
                extra = set(p) - ENTRY_FIELDS
                if extra:
                    fail(f"{book} {chapter} has fields a heading should not "
                         f"have: {', '.join(sorted(extra))} -- this file is "
                         f"headings only")
                    continue
                title = str(p.get("title", ""))
                chars += len(title)
                if len(title) > MAX_TITLE_CHARS:
                    fail(f"{book} {chapter} has a {len(title)}-character "
                         f"heading: {title[:60]!r}... that is a paragraph, "
                         f"not a heading")
                for sub in p.get("sub", []) or []:
                    chars += len(str(sub))
                    if len(str(sub)) > MAX_TITLE_CHARS:
                        fail(f"{book} {chapter} has a {len(str(sub))}-character "
                             f"sub-heading")

    if chars > MAX_HEADING_CHARS:
        fail(f"the headings total {chars:,} characters, over the "
             f"{MAX_HEADING_CHARS:,} a headings-only file should be -- this "
             f"looks like prose has been included")

    # Content only: the metadata above is *meant* to name the source.
    hits = THIRD_PARTY.findall(json.dumps(books, ensure_ascii=False))
    if hits:
        fail(f"the headings contain {len(hits)} reference(s) to something "
             f"other than the authors' own words -- e.g. "
             f"{sorted({h if isinstance(h, str) else h[0] for h in hits})[:3]}")

    return bad


def main(argv: list[str]) -> int:
    remove = "--remove" in argv
    conn = db.connect()
    total = conn.execute(
        "SELECT COUNT(*) c FROM module WHERE installed_at > 0").fetchone()["c"]
    print(f"  {total} modules installed")

    bundled = audit_bundled()
    if bundled:
        print("  the committed data fails a gate:")
        for b in bundled:
            print(f"    {b['id']}")
            print(f"      {b['reason']}")
    else:
        print("  the committed JFB outlines pass: public domain, the authors' "
              "own headings, no prose, no third-party contribution")

    bad = audit()
    if not bad:
        print("  all installed modules pass the licence and date gates")
        return 1 if bundled else 0
    print(f"  {len(bad)} installed module(s) fail a gate:")
    for b in bad:
        print(f"    {b['id']}  ({b['license']}, {b['year'] or 'no year'})")
        print(f"      {b['reason']}")
    if not remove:
        print("\n  Re-run with --remove to remove these.")
        return 1
    print()
    for b in bad:
        r = library.remove_module(b["id"], delete_files=True)
        state = "removed" if r.get("ok") else f"FAILED: {r.get('error') or r}"
        print(f"    {b['id']}: {state}")
    left = audit()
    print()
    if bundled:
        print(f"  {len(left)} installed still failing; the committed data is "
              f"reported only -- it is a repository file, and --remove "
              f"deletes installed modules, not source.")
    else:
        print(f"  {len(left)} still failing" if left else "  every gate passes")
    return 1 if left else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
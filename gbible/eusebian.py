"""The Eusebian canon tables, and the Ammonian sections they index.

Every Greek and Latin manuscript of the Gospels carries a number in the margin
against each section, in the form `table.section`, and those numbers are the
whole apparatus: they say which of the ten canon tables the section belongs to,
and within that table they line the four Gospels up against each other.  It is a
cross-reference system two thousand years old, and it is the ancestor of the
verse numbers we use instead of it.

The library has it installed -- twice, identically, as two modules -- as a table
of one entry per verse giving that verse's number.  Nothing read it.  This
module turns it back into the thing it was designed to be.

Reading the numbers correctly is the whole job, and it is easy to get wrong in
a way that looks fine.  The first number is **not** a book index and **not** a
verse count.  Canon I is not Matthew; canon I is "the material common to all
four Gospels", canon II is "common to Matthew, Mark and Luke", canon III is
"Matthew, Luke and John", and so on.  Matthew happens to *be* the first column
of the earliest tables, which is where the confusion starts, and an
implementation that reads `4.1` as "the fourth book, first verse" produces a
harmony that is completely wrong and completely plausible.

The ten tables, from Eusebius's own letter to Carpianus:

    I     all four Gospels
    II    Matthew, Mark, Luke
    III   Matthew, Luke, John
    IV    Matthew, Mark, John
    V     Matthew, Luke
    VI    Matthew, Mark
    VII   Matthew, John
    VIII  Mark, Luke
    IX    Luke, John
    X     what is unique to one Gospel

There is no "Mark and John" table and no "Mark, Luke and John" table, and that
is not an oversight in this list: no text is common to Mark and John without
also being common to at least one of Matthew or Luke, so the column would be
empty in every row.

On coverage: the installed module is real data but it is not complete, and this
says so rather than letting the gaps pass as an accident of the text.  The
section counts in the scholarly literature are 355 for Matthew, 235 for Mark,
343 for Luke and 232 for John, and the installed numbers fall short of those --
and a handful of entries carry a table number above ten, which cannot be right
under any reading.  `health()` reports all of it, so the tables can say "this
module covers 94% of the sections it claims" rather than implying a completeness
it does not have.
"""
from __future__ import annotations

import re
from collections import defaultdict

from . import db, library

#: The ten canon tables, and the Gospels each compares.  Order is the order
#: Eusebius gives them and the order every manuscript writes them in.
CANONS: list[dict] = [
    {"n": 1, "roman": "I", "label": "In Quo Quattuor", "en": "All four Gospels",
     "books": ("Matt", "Mark", "Luke", "John")},
    {"n": 2, "roman": "II", "label": "In Quo Tres", "en": "Matthew, Mark, Luke",
     "books": ("Matt", "Mark", "Luke")},
    {"n": 3, "roman": "III", "label": "In Quo Tres", "en": "Matthew, Luke, John",
     "books": ("Matt", "Luke", "John")},
    {"n": 4, "roman": "IV", "label": "In Quo Tres", "en": "Matthew, Mark, John",
     "books": ("Matt", "Mark", "John")},
    {"n": 5, "roman": "V", "label": "In Quo Duo", "en": "Matthew and Luke",
     "books": ("Matt", "Luke")},
    {"n": 6, "roman": "VI", "label": "In Quo Duo", "en": "Matthew and Mark",
     "books": ("Matt", "Mark")},
    {"n": 7, "roman": "VII", "label": "In Quo Duo", "en": "Matthew and John",
     "books": ("Matt", "John")},
    {"n": 8, "roman": "VIII", "label": "In Quo Duo", "en": "Mark and Luke",
     "books": ("Mark", "Luke")},
    {"n": 9, "roman": "IX", "label": "In Quo Duo", "en": "Luke and John",
     "books": ("Luke", "John")},
    {"n": 10, "roman": "X", "label": "In Quo Matthaei Proprie",
     "en": "Unique to one Gospel", "books": ("Matt", "Mark", "Luke", "John")},
]

BOOK_NAME = {"Matt": "Matthew", "Mark": "Mark", "Luke": "Luke", "John": "John"}

#: Section counts as reported in the standard treatments of the apparatus.
#: Compared against rather than trusted: the difference between the two is the
#: honest measure of how much of the table this library actually has.
EXPECTED = {"Matt": 355, "Mark": 235, "Luke": 343, "John": 232}

_NUM = re.compile(r"^(\d+)\.(\d+)$")
_KEY = re.compile(r"^([A-Za-z]+)\.(\d+)\.(\d+)$")

#: Parsed once against the module ids, then reused.  Parsing 3,783 rows per
#: request would be absurd; the library changing bumps the generation.
_CACHE: dict = {}


def _modules() -> list:
    """Every installed copy of the Eusebian table, de-duplicated.

    There are two, byte for byte identical, which is a Crosswire packaging
    artefact rather than two editions -- so they are compared and only one is
    used.  Silently using the first would mean the duplicate is invisible, and
    silently using both would double every section.
    """
    mods = [m for m in library.list_all()
            if "eusebian" in (m.id or "").lower()
            or "eusebian" in (m.name or "").lower()]
    if not mods:
        return []
    sigs: dict[str, str] = {}
    conn = db.connect()
    for m in mods:
        sigs[m.id] = _signature(conn, m.id)
    seen: dict[str, str] = {}
    unique = []
    for m in mods:
        sig = sigs[m.id]
        if sig in seen:
            _CACHE.setdefault("dupes", {})[m.id] = seen[sig]
            continue
        seen[sig] = m.id
        unique.append(m)
    return unique


def _signature(conn, module_id: str) -> str:
    """A cheap fingerprint of a module's units, for spotting exact copies."""
    rows = conn.execute(
        "SELECT COUNT(*) c, MIN(key) a, MAX(key) b, SUM(ord) s FROM unit "
        "WHERE module_id=?", (module_id,)).fetchone()
    return f"{rows['c']}:{rows['a']}:{rows['b']}:{rows['s']}"


def data() -> dict:
    """The parsed apparatus: sections, verse lookups, and what is wrong.

    Keys are `(table, section)`, values are `{book: [verse keys]}`.  Built on
    first use and cached against the library generation, so a re-index is
    picked up without anything having to remember to clear a cache.
    """
    from . import db as _db
    key = ("eusebian", _db.GENERATION)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    conn = db.connect()
    mods = _modules()
    sections: dict[tuple[int, int], dict] = defaultdict(dict)
    by_verse: dict[str, tuple[int, int]] = {}
    bad: list[dict] = []
    # Distinct *sections* per book, not verses.  These are different quantities
    # and confusing them reads as 300% coverage: Matthew has about 1,070 verses
    # but only about 350 sections, because a section spans a paragraph and most
    # of them are several verses long.
    counts: dict[str, set] = defaultdict(set)
    seen_keys: set[str] = set()
    for m in mods:
        for r in conn.execute(
                "SELECT key, text FROM unit WHERE module_id=? ORDER BY ord",
                (m.id,)):
            vk = (r["key"] or "").strip()
            km = _KEY.match(vk)
            if km is None:
                bad.append({"verse": vk, "value": (r["text"] or "").strip(),
                            "why": "the verse reference is not Book.Chapter.Verse"})
                continue
            num = (r["text"] or "").strip()
            nm = _NUM.match(num)
            if nm is None:
                bad.append({"verse": vk, "value": num,
                            "why": "the number is not in table.section form"})
                continue
            t, s = int(nm.group(1)), int(nm.group(2))
            if not 1 <= t <= 10:
                # A table number above ten is not a variant reading of Eusebius;
                # there are ten tables.  These are dropped and reported, because
                # treating "144" as canon 144 would file five verses under a
                # table that has never existed.
                bad.append({"verse": vk, "value": num,
                            "why": f"table {t} does not exist; there are ten"})
                continue
            book = km.group(1)
            if vk in seen_keys:
                continue
            seen_keys.add(vk)
            sections[(t, s)].setdefault(book, []).append(vk)
            by_verse[vk] = (t, s)
            counts[book].add(s)
    out = {
        "modules": [m.id for m in mods],
        "sections": {k: dict(v) for k, v in sections.items()},
        "by_verse": by_verse,
        "bad": bad,
        "counts": {b: len(v) for b, v in counts.items()},
        "available": bool(mods),
    }
    _CACHE[key] = out
    return out


def _ref_for(vk: str) -> str:
    m = _KEY.match(vk)
    return f"{BOOK_NAME.get(m.group(1), m.group(1))} {m.group(2)}:{m.group(3)}" \
        if m else vk


def notation(verse: str) -> str:
    """The Eusebian number for one verse, or '' if this table has none.

    `verse` is a unit key ("John.1.1").  This is the function the reader wants
    nine times out of ten: they are looking at a verse and they want to know its
    number so they can find its parallels.
    """
    d = data()
    ts = d["by_verse"].get((verse or "").strip())
    return f"{ts[0]}.{ts[1]}" if ts else ""


def lookup(notation_: str) -> dict:
    """Every verse sharing one Eusebian number.

    That is the operation the apparatus exists for: given `4.1`, find what the
    other Gospels say in the same place.  The four columns are returned
    separately, because the *shape* of the answer -- which Gospels are blank --
    is what tells the reader whether this is a four-way parallel or something
    unique to John.
    """
    d = data()
    m = _NUM.match((notation_ or "").strip())
    if not m:
        return {"ok": False, "error": "that is not a number in the form "
                                       "table.section, e.g. 4.1"}
    t, s = int(m.group(1)), int(m.group(2))
    row = d["sections"].get((t, s), {})
    canon = next((c for c in CANONS if c["n"] == t), None)
    columns = []
    for b in ("Matt", "Mark", "Luke", "John"):
        vs = row.get(b) or []
        columns.append({
            "book": b, "name": BOOK_NAME[b],
            "present": bool(vs),
            "verses": [_ref_for(v) for v in sorted(vs, key=_vkey)],
            "first": _ref_for(vs[0]) if vs else "",
            "last": _ref_for(sorted(vs, key=_vkey)[-1]) if vs else "",
            "count": len(vs),
        })
    return {
        "ok": True, "table": t, "section": s,
        "notation": f"{t}.{s}",
        "canon": canon,
        "columns": columns,
        "in_table": [c["book"] for c in columns if c["present"]],
        "missing_from_table": [c["book"] for c in canon["books"]]
                              if canon and not
                              [c for c in columns if c["present"]] else [],
    }


def _vkey(vk: str) -> tuple:
    m = _KEY.match(vk)
    return (m.group(1), int(m.group(2)), int(m.group(3))) if m else (vk, 0, 0)


def harmony(*, canon: int | None = None, limit: int = 400,
            start: int = 1) -> dict:
    """The tables, laid out as the tables: canon by canon, row by row.

    `canon` picks one table (1-10); without it every table is returned, which is
    how the apparatus actually appears at the front of a Gospel book and is the
    only view in which the pattern of which Gospels agree is visible at all.
    Rows are the sections, columns the four Gospels -- the shape of the printed
    page, because the printed page is what this is for.
    """
    d = data()
    if not d["available"]:
        return {"ok": False, "error": "the Eusebian table is not installed"}
    canons = [c for c in CANONS if canon is None or c["n"] == canon]
    if canon is not None and not canons:
        return {"ok": False, "error": f"there is no canon table {canon}"}
    tables = []
    for c in canons:
        rows = []
        keys = sorted(s for (t, s) in d["sections"] if t == c["n"])
        for s in keys:
            if s < start:
                continue
            row = d["sections"][(c["n"], s)]
            rows.append({
                "section": s,
                "notation": f"{c['n']}.{s}",
                "cells": [
                    {"book": b, "verses": [_ref_for(v) for v in
                                           sorted(row.get(b) or [], key=_vkey)]}
                    for b in ("Matt", "Mark", "Luke", "John")
                ],
            })
            if len(rows) >= limit:
                break
        tables.append({**c, "rows": rows, "count": len(rows)})
    return {
        "ok": True, "canons": tables,
        "canon_list": [{k: c[k] for k in ("n", "roman", "label", "en", "books")}
                       for c in CANONS],
        "sections_total": len(d["sections"]),
        "health": health(),
    }


def health() -> dict:
    """What this library actually has, and where it falls short.

    Worth having as a first-class answer rather than a caveat in a docstring,
    because a harmony that silently omits ninety of Matthew's sections looks
    exactly like a harmony of the whole thing.
    """
    d = data()
    counts = d["counts"]
    books = []
    for b in ("Matt", "Mark", "Luke", "John"):
        got = counts.get(b, 0)
        want = EXPECTED[b]
        books.append({
            "book": b, "name": BOOK_NAME[b],
            "have": got, "expected": want,
            "missing": max(0, want - got),
            "pct": round(100.0 * got / want, 1) if want else 0.0,
        })
    dupes = _CACHE.get("dupes", {})
    total_expected = sum(EXPECTED.values())
    total_have = sum(counts.get(b, 0) for b in EXPECTED)
    tables_here = sorted({t for (t, _s) in d["sections"]})
    # A canon table is a *comparison*: its whole purpose is that one number puts
    # two or more Gospels side by side.  So the test of whether this module is
    # the Eusebian apparatus at all is whether any of its numbers occur in more
    # than one Gospel -- and if none do, it is not the apparatus.
    shared = sum(1 for row in d["sections"].values() if len(row) > 1)
    usable = shared > 0
    out = {
        "ok": d["available"],
        "available": d["available"],
        "usable": usable,
        "modules": d["modules"],
        "duplicate_modules": dupes,
        "sections": len(d["sections"]),
        "tables_present": tables_here,
        "tables_expected": [c["n"] for c in CANONS],
        "shared_sections": shared,
        "books": books,
        "complete_pct": round(100.0 * total_have / total_expected, 1)
                        if total_expected else 0.0,
        "malformed": d["bad"],
        "malformed_count": len(d["bad"]),
        "notes": _notes(d, books, dupes, tables_here, shared),
    }
    return out


def _notes(d, books, dupes, tables_here, shared) -> list[str]:
    out: list[str] = []
    if not d["available"]:
        return ["The Eusebian canon table is not installed, so there are no "
                "Ammonian section numbers here. Install 'Eusebian Numbers By "
                "Verse' from the Modules tab."]
    if not shared:
        out.append(
            "This module does not contain the Eusebian canon table. Every "
            "number in it belongs to exactly one Gospel -- Matthew's are all "
            "numbered in table 1, Mark's in table 2, Luke's in 3, John's in 4 "
            "-- so no number is shared and no verse here can be matched to a "
            "parallel in another Gospel. Tables V to X, the ones that actually "
            "compare Gospels, are absent entirely. "
            "It is a per-Gospel section numbering, not the canon table, and the "
            "harmonies below show one column where they should show two or "
            "four. The numbers themselves are real Ammonian section numbers and "
            "worth keeping as a way of citing a pericope; they just cannot do "
            "the one job the tables exist for.")
    for b in books:
        if b["missing"]:
            out.append(
                f"{b['name']} has {b['have']} of the {b['expected']} sections "
                f"usually counted, so {b['missing']} are missing here. The "
                f"numbers that are present are sound; the gaps are in the "
                f"module, not in the table.")
    if dupes:
        out.append(
            f"{len(dupes) + 1} copies of this table are installed and they are "
            f"identical, so one is being read and the rest ignored: "
            f"{', '.join(sorted(dupes))}. Removing them changes nothing.")
    if d["bad"]:
        out.append(
            f"{len(d['bad'])} entries carry a number no reading of Eusebius "
            f"allows and are left out: "
            + ", ".join(f"{x['verse']} = {x['value']!r}" for x in d["bad"][:4])
            + ("..." if len(d["bad"]) > 4 else "") + ".")
    return out

"""Search ranges, panel links, equivalent references, visual filters.

Pack 3 plumbing. The search engine itself is untouched: ranges are named book
lists applied as a post-filter (reported, never silent), equivalent references
expand through the installed `xref` table, and visual filters are saved
query+style pairs evaluated per chapter so the reader can highlight them.
"""

from __future__ import annotations

import time
import uuid

from . import canon, db, library

# Book lists by English name; resolved to OSIS through canon.lookup_book so a
# typo fails loudly at import-test time rather than silently matching nothing.
_OT = ["Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy",
        "Joshua", "Judges", "Ruth", "1 Samuel", "2 Samuel", "1 Kings",
        "2 Kings", "1 Chronicles", "2 Chronicles", "Ezra", "Nehemiah",
        "Esther", "Job", "Psalms", "Proverbs", "Ecclesiastes",
        "Song of Solomon", "Isaiah", "Jeremiah", "Lamentations", "Ezekiel",
        "Daniel", "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah",
        "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi"]
_NT = ["Matthew", "Mark", "Luke", "John", "Acts", "Romans", "1 Corinthians",
       "2 Corinthians", "Galatians", "Ephesians", "Philippians", "Colossians",
       "1 Thessalonians", "2 Thessalonians", "1 Timothy", "2 Timothy",
       "Titus", "Philemon", "Hebrews", "James", "1 Peter", "2 Peter",
       "1 John", "2 John", "3 John", "Jude", "Revelation"]


def _osis(names: list[str]) -> list[str]:
    out = []
    for n in names:
        b = canon.lookup_book(n)
        if b is None:
            raise ValueError(f"unknown book in range table: {n!r}")
        out.append(b.osis)
    return out


def _build_ranges() -> dict[str, list[str]]:
    ot = _osis(_OT)
    nt = _osis(_NT)
    by = {b: i for i, b in enumerate(ot)}
    pent = ot[0:5]
    hist = ot[5:17]
    poet = ot[17:22]
    major = ot[22:27]
    minor = ot[27:39]
    gospels = nt[0:4]
    pauline = nt[5:18]
    general = nt[18:26]
    return {
        "Old Testament": ot,
        "New Testament": nt,
        "Pentateuch": pent,
        "History": hist,
        "Poetry & Wisdom": poet,
        "Major Prophets": major,
        "Minor Prophets": minor,
        "Gospels": gospels,
        "Acts": nt[4:5],
        "Pauline Epistles": pauline,
        "General Epistles": general,
        "Prophecy (Revelation)": nt[26:27],
    }


RANGES: dict[str, list[str]] = _build_ranges()


def ranges() -> list[dict]:
    return [{"name": k, "books": v, "count": len(v)} for k, v in RANGES.items()]


def range_books(name: str) -> list[str]:
    return list(RANGES.get(name, []))


def search_in_range(q: str, range_name: str, opts_dict: dict | None = None) -> dict:
    """Run a search, keep only hits in the named range's books.

    The engine has no book filter, so this over-fetches (3x limit) and filters
    on the unit table. `truncated` says when the window may have cut hits.
    """
    from . import search as _search
    books = set(range_books(range_name))
    if not books:
        return {"ok": False, "error": f"Unknown range {range_name!r}"}
    opts_dict = dict(opts_dict or {})
    limit = int(opts_dict.pop("limit", 200) or 200)
    fetch = min(limit * 3, 1200)
    opts = _search.SearchOpts(
        modules=opts_dict.get("modules") or [],
        scope=opts_dict.get("scope") or "",
        match_case=bool(opts_dict.get("match_case")),
        match_all_forms=bool(opts_dict.get("match_all_forms")),
        reference_matching=opts_dict.get("reference_matching", "default"),
        limit=fetch, offset=0,
        sort=opts_dict.get("sort", "relevance"),
        snippets=True, context=0, fast=True, smart=False,
    )
    res = _search.search(q, opts)
    hits = res.get("hits") or res.get("results") or []
    conn = db.connect()
    kept = []
    for h in hits:
        mid = h.get("module_id") if isinstance(h, dict) else getattr(h, "module_id", "")
        key = h.get("key") if isinstance(h, dict) else getattr(h, "key", "")
        r = conn.execute("SELECT book FROM unit WHERE module_id=? AND key=?",
                         (mid, key)).fetchone() if (mid and key) else None
        if r is None:
            # Non-verse units (lexica, books): keep only when range is whole.
            continue
        if r["book"] in books:
            kept.append(h)
        if len(kept) >= limit:
            break
    return {"ok": True, "query": q, "range": range_name, "hits": kept[:limit],
            "shown": min(len(kept), limit),
            "truncated": len(hits) >= fetch,
            "total_in_window": len(kept)}


def equivalent_refs(module_id: str, ref: str) -> dict:
    """A verse plus everything installed cross-reference tables link it to."""
    m = library.get(module_id)
    if m is None:
        return {"ok": False, "error": "Not installed"}
    rr = canon.parse_ref(ref, m.v11n)
    if rr is None:
        return {"ok": False, "error": f"Cannot parse {ref!r}"}
    key = rr.start.osis_id()
    conn = db.connect()
    rows = conn.execute(
        "SELECT DISTINCT to_key FROM xref WHERE module_id=? AND from_key=? "
        "UNION SELECT DISTINCT from_key FROM xref WHERE module_id=? AND to_key=?",
        (module_id, key, module_id, key)).fetchall()
    linked = sorted({r[0] for r in rows if r[0] != key})
    return {"ok": True, "ref": ref, "key": key, "equivalent": [ref] + linked}


# -- Search-panel link set: which link group a click-to-search follows. --

def get_panel_link() -> str:
    try:
        return db.get_setting("search_panel_link", "") or ""
    except Exception:  # noqa: BLE001
        return ""


def set_panel_link(letter: str) -> dict:
    from .workspace import LINK_SETS
    if letter and letter not in LINK_SETS:
        return {"ok": False, "error": "Unknown link set"}
    db.set_setting("search_panel_link", letter or "")
    return {"ok": True, "link_set": letter or ""}


# -- Visual filters: saved query+style pairs, evaluated per chapter. --

def visual_filters() -> list[dict]:
    try:
        v = db.get_setting("visual_filters", [])
    except Exception:  # noqa: BLE001
        return []
    return v if isinstance(v, list) else []


def save_visual_filter(name: str, query: str, style: str = "yellow",
                       morph: str = "", enabled: bool = True,
                       fid: str = "") -> dict:
    if not (query or "").strip() and not (morph or "").strip():
        return {"ok": False, "error": "A filter needs a query or morphology"}
    try:
        all_f = db.get_setting("visual_filters", [])
    except Exception:  # noqa: BLE001
        all_f = []
    if not isinstance(all_f, list):
        all_f = []
    fid = fid or ("vf" + uuid.uuid4().hex[:11])
    rec = {"id": fid, "name": (name or "").strip() or (query or morph)[:40],
           "query": query or "", "morph": morph or "", "style": style or "yellow",
           "enabled": bool(enabled), "updated_at": time.time()}
    all_f = [f for f in all_f if f.get("id") != fid] + [rec]
    db.set_setting("visual_filters", all_f)
    return {"ok": True, "filter": rec}


def delete_visual_filter(fid: str) -> dict:
    try:
        all_f = db.get_setting("visual_filters", [])
    except Exception:  # noqa: BLE001
        all_f = []
    db.set_setting("visual_filters",
                   [f for f in (all_f or []) if f.get("id") != fid])
    return {"ok": True, "removed": fid}


def apply_visual_filters(module_id: str, book: str, chapter: int) -> dict:
    """Which enabled filters match which verses of one chapter."""
    from . import search as _search
    m = library.get(module_id)
    if m is None:
        return {"ok": False, "error": "Not installed"}
    conn = db.connect()
    verses = [r["key"] for r in conn.execute(
        "SELECT key FROM unit WHERE module_id=? AND book=? AND chapter=? "
        "ORDER BY verse", (module_id, book, chapter)).fetchall()]
    if not verses:
        return {"ok": True, "matches": {}, "verses": []}
    matches: dict[str, list[str]] = {}
    surfaces: dict[str, list[str]] = {}
    for f in visual_filters():
        if not f.get("enabled"):
            continue
        if f.get("morph"):
            hit_here = _morph_hits(module_id, verses, f["morph"])
            if hit_here:
                matches[f["id"]] = hit_here
                # Morph markers carry codes, not surface words, so text-level
                # highlighting is left to query-based filters for now.
                surfaces[f["id"]] = []
            continue
        q = f.get("query") or ""
        if not q:
            continue
        try:
            opts = _search.SearchOpts(modules=[module_id], limit=400,
                                      snippets=False, smart=False, fast=True)
            res = _search.search(q, opts)
        except Exception:  # noqa: BLE001
            continue
        hits = res.get("hits") or res.get("results") or []
        keys = {h.get("key") for h in hits
                if isinstance(h, dict) and h.get("module_id") == module_id}
        hit_here = sorted(set(verses) & keys)
        if hit_here:
            matches[f["id"]] = hit_here
            surfaces[f["id"]] = _query_terms(q)
    return {"ok": True, "matches": matches, "verses": verses,
            "surfaces": surfaces}


def _morph_hits(module_id: str, verses: list[str], spec: str) -> list[str]:
    """Verses of this chapter carrying the morphology: `pos=N,tense=ximpf`
    field filters, or a bare code prefix like `HNcms` or `robinson:CONJ`."""
    from . import morphq
    spec = (spec or "").strip()
    if not spec:
        return []
    conn = db.connect()
    codes: list[str] = []
    if "=" in spec or spec.startswith("not:"):
        filt: dict[str, str] = {}
        for part in spec.split(","):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            if k.strip() in morphq._FILTERS:
                filt[k.strip()] = v.strip()
        try:
            res = morphq.query(limit=0, **filt)
        except Exception:  # noqa: BLE001
            return []
        # limit=0 means "no paging" in morphq (page = all codes).
        entries = res.get("results") or []
        codes = [e["code"] for e in entries if e.get("code")]
    else:
        prefix = spec.lower()
        rows = conn.execute("SELECT DISTINCT value FROM marker WHERE kind='morph'"
                            ).fetchall()
        codes = [r["value"] for r in rows
                 if r["value"] and r["value"].lower().startswith(prefix)]
    if not codes:
        return []
    verseset = set(verses)
    ph = ",".join("?" * len(codes))
    rows = conn.execute(
        f"SELECT DISTINCT unit_key FROM marker WHERE module_id=? AND kind='morph'"
        f" AND value IN ({ph})", [module_id, *codes]).fetchall()
    return sorted({r["unit_key"] for r in rows} & verseset)


def _morph_surfaces(module_id, verses, spec):
    spec = (spec or "").strip()
    if not spec:
        return []
    conn = db.connect()
    codes = []
    filt = {}
    if "=" in spec or spec.startswith("not:"):
        for part in spec.split(","):
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            if k.strip() in ("pos", "gender", "number", "state", "conjugation",
                             "tense", "person", "participle", "scheme",
                             "pos_particle"):
                filt[k.strip()] = v.strip()
        if filt:
            try:
                from . import morphq as _mq
                res = _mq.query(limit=1, **filt)
                codes = [e["code"] for e in (res.get("results") or [])
                         if e.get("code")]
            except Exception:
                codes = []
        if not codes and not filt:
            prefix = spec.lower()
            rows = conn.execute(
                "SELECT DISTINCT value FROM marker WHERE kind='morph'").fetchall()
            codes = [r["value"] for r in rows
                     if r["value"] and r["value"].lower().startswith(prefix)]
    else:
        prefix = spec.lower()
        rows = conn.execute(
            "SELECT DISTINCT value FROM marker WHERE kind='morph'").fetchall()
        codes = [r["value"] for r in rows
                 if r["value"] and r["value"].lower().startswith(prefix)]
    if not codes:
        return []
    verseset = set(verses or [])
    ph = ",".join("?" * len(codes))
    sql = ("SELECT DISTINCT surface FROM marker WHERE module_id=? "
           "AND kind='morph' AND value IN (%s)" % ph)
    params = [module_id] + list(codes)
    if verseset:
        vp = ",".join("?" * len(verseset))
        sql += " AND unit_key IN (%s)" % vp
        params += sorted(verseset)
    rows = conn.execute(sql, params).fetchall()
    return [r["surface"] for r in rows if r["surface"]]


def _query_terms(q):
    import re as _re
    words = _re.findall(r"[A-Za-z]+", q or "")
    return sorted({w for w in words if len(w) > 2})


def apply_for_key(module_id: str, unit_key: str) -> dict:
    """apply_visual_filters without the caller parsing the key.

    Unit keys are module-specific (`John.3.16` vs `John 3:16`), so the book
    and chapter are read off the unit row instead of the string.
    """
    conn = db.connect()
    r = conn.execute("SELECT book, chapter FROM unit WHERE module_id=? AND key=?",
                     (module_id, unit_key)).fetchone()
    if r is None or not r["book"]:
        return {"ok": True, "matches": {}, "verses": [],
                "filters": visual_filters(),
                "note": "No verse address for this unit."}
    out = apply_visual_filters(module_id, r["book"], r["chapter"] or 0)
    out["filters"] = visual_filters()
    return out


def filtered_reading(module_id: str, refs: list[str]) -> dict:
    """Read exactly the given references in order (passage/xref filtered view).

    Unresolvable refs are reported, never silently dropped.

    Each reference is resolved by *book, chapter and verse*, not by looking up
    the OSIS id in `unit.key`.  Those are two different things: `unit.key` is
    whatever the importer wrote, and it is not always an OSIS id.  A module
    built from plain USFX or from a Bible whose files were already shaped for
    display keys its verses "John 3:16", so a `key=?` lookup misses every one
    of them and the reading comes back empty for a Bible that plainly contains
    the text.  The book/chapter/verse columns are set the same way for every
    module, and `row["key"]` is then whatever *this* module calls that verse.
    """
    m = library.get(module_id)
    if m is None:
        return {"ok": False, "error": "Not installed"}
    conn = db.connect()
    keys, missing = [], []
    for ref in refs or []:
        rr = canon.parse_ref(ref, m.v11n)
        if rr is None:
            missing.append(ref)
            continue
        row = None
        for v in rr.refs():
            row = conn.execute(
                "SELECT key FROM unit WHERE module_id=? AND book=? AND chapter=? "
                "AND verse=? LIMIT 1",
                (module_id, v.book, v.chapter, v.verse)).fetchone()
            if row is not None:
                break
        if row is not None:
            keys.append(row["key"])
        else:
            missing.append(ref)
    content = library.read(module_id, {"keys": keys,
                                       "list_name": f"{len(keys)} passages"})
    from .server.app import _item_dict as _ser
    out = {k: v for k, v in content.__dict__.items() if k != "items"}
    out["items"] = [_ser(i) for i in content.items]
    out["missing"] = missing
    return {"ok": True, **out}

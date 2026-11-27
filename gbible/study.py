"""Linked resources: one verse, or one word, or everything you have installed.

A word knows its lemma, the lemma knows its lexicon entry, the entry knows every
occurrence, and a verse knows every commentary, cross-reference, topic and
place.  Every tool is a different view onto those same edges.

This module builds those edges from what is already installed.  The raw
material is here -- TSK, Barnes, Clarke, Nave, Torrey, Hitchcock, ISBE, the
Strong's lexicons, 334 geocoded places, OSHB and SBLGNT morphology -- so the
joining layer is the only thing that has to be written.

Nothing here is tied to a specific product and nothing needs a key: it is all
local.
"""

from __future__ import annotations

import json
import re
import time

from . import canon, db, library, store, taxonomy, topicindex

# --------------------------------------------------------------------------
# small helpers

# Greek is 0370-03FF, but polytonic text -- the whole of Strong's and the OSHB
# lemma -- lives in Greek *Extended*, 1F00-1FFF.  A range that stops at 03FF
# matches nothing at all, which is what left a Strong's Greek lemma sitting in
# front of the reader as a transliteration.
_SCRIPT = r"Ͱ-Ͽἀ-῿֐-ۿ"
_SCRIPT_RX = re.compile("[" + _SCRIPT + "]+")

_REF_IN_TEXT = re.compile(
    r"\b(1|2|3)?\s?([A-Za-z][A-Za-z]{1,14})\s+(\d{1,3}):(\d{1,3})\b")


def _ids_of_type(types: tuple[str, ...]) -> list[str]:
    return [m.id for m in library.list_all() if m.type in types]


def _chunk(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _summary_text(text: str, limit: int = 320) -> str:
    """A scannable summary of an entry.

    Outline indexes (Nave, Torrey) open with long whitespace and a chain of
    ``→ Heading  refs`` lines, so the first 320 characters are usually a single
    half-finished reference.  Show the headings instead: that is the answer a
    reader wants from a topic index, with "Open in a pane" for the full list.
    Ordinary prose keeps the old truncation.
    """
    raw = text or ""
    heads = [ln.strip()[1:].strip() for ln in raw.splitlines()
             if ln.strip().startswith("→")]
    if not heads and ("•  See" in raw or "• See" in raw):
        # Some SWORD outlines number their points instead of using arrows.
        heads = [re.sub(r"^\d+\.\s*", "", ln.strip())
                 for ln in raw.splitlines() if re.match(r"^\s*\d+\.\s", ln)]
    if not heads:
        return _chunk(raw, limit)
    out = []
    for h in heads[:4]:
        m = re.search(r"\b(?:\d\s?)?[A-Z][a-z]{1,9}\.?\s+\d{1,3}", h)
        label = (h[:m.start()].strip() if m and m.start() > 0 else h)
        out.append(_chunk(label, 64))
    summary = " · ".join(x for x in out if x)
    if len(heads) > 4:
        summary += " …"
    return summary


# --------------------------------------------------------------------------
# commentary notes at a verse

def commentaries_at(conn, book: str, chapter: int, verse: int,
                    limit: int = 60) -> list[dict]:
    """Every commentary note anchored at this verse, chapter or book.

    Commentaries are anchored at three granularities -- a single verse, a whole
    chapter, a whole book -- and a good note at the chapter level is exactly
    what a reader wants at verse 16.  Barnes is per-verse; some others are not.
    """
    ids = _ids_of_type(("Commentary",))
    if not ids or not book or not chapter:
        return []
    ph = ",".join("?" * len(ids))
    sql = (f"SELECT module_id, key, ref_label, title, text, book, chapter, verse "
           f"FROM unit WHERE module_id IN ({ph}) AND book=? AND ("
           f"  (chapter=? AND verse=?) OR (chapter=? AND verse=0) OR verse=0)")
    rows = conn.execute(sql, [*ids, book, chapter, verse, chapter]).fetchall()
    mods = {m.id: m for m in library.list_all() if m.id in ids}
    out = []
    for r in rows:
        m = mods.get(r["module_id"])
        if not m or not (r["text"] or "").strip():
            continue
        gran = "verse" if r["verse"] else ("chapter" if r["chapter"] else "book")
        out.append({
            "module_id": m.id, "module": m.name, "abbrev": m.abbrev or "",
            "key": r["key"], "label": r["ref_label"] or r["key"],
            "title": r["title"] or "", "granularity": gran,
            "text": _chunk(r["text"], 2400),
        })
    # Verse-level notes before chapter- or book-level ones, because a note
    # anchored exactly here is the one that answers the question being asked.
    # Ties then go to the reader's own priority order and only then to the
    # module name -- previously the name was the whole tie-break, so two
    # commentaries covering the same verse were listed alphabetically and the
    # order the reader had set in Library ▸ Prioritise was ignored here even
    # though the passage guide, one screen away, honoured it.
    from . import workspace as _ws
    rank: dict = {}
    try:
        ref = f"{book} {chapter or 0}:{verse or 1}"
        rank = {mid: i for i, mid in enumerate(
            _ws.resolve_priority(req_type="commentary", ref=ref))}
    except Exception:                       # ordering must never lose a note
        rank = {}
    out.sort(key=lambda n: (
        n["granularity"] != "verse",
        rank.get(n["module_id"], 10 ** 6),
        n["module"]))
    return out[:limit]


# --------------------------------------------------------------------------
# cross-references, from TSK and from the xref table

_TSK_CITES: dict | None = None
_BOOK_TOKENS: dict | None = None


def _book_tokens() -> dict:
    """OSIS book name -> the spellings TSK actually writes for it.

    TSK writes "Joh 3:19", "1Ki 2:10", "Ro 8:17" -- never "John 3:19".  So a
    LIKE on the OSIS name misses everything, and every reference has to be run
    through canon.parse_ref, which tries every book for every token.  There are
    only about sixty distinct book tokens in the whole corpus, so resolve each
    *token* once and reuse the answer: that turns roughly a hundred thousand
    parse calls into sixty.
    """
    global _BOOK_TOKENS
    if _BOOK_TOKENS is not None:
        return _BOOK_TOKENS
    conn = db.connect()
    tokens: set[str] = set()
    ids = [m.id for m in library.list_all()
           if m.id.endswith("-tsk") or "Treasury" in (m.name or "")]
    for mid in ids:
        for (text,) in conn.execute("SELECT text FROM unit WHERE module_id=?", (mid,)):
            for m in _REF_IN_TEXT.finditer(text or ""):
                tokens.add(m.group(2))
    out: dict[str, list[str]] = {}
    for tok in tokens:
        rr = canon.parse_ref(f"{tok} 1:1")
        f = next(iter(rr.refs()), None) if rr else None
        if f is not None and f.book:
            out.setdefault(f.book, []).append(tok)
    _BOOK_TOKENS = out
    return out


def crossref_module_ids() -> list[str]:
    """Installed resources that belong in the cross-reference pane.

    Found by *placement*, not by name.  Both callers used to match
    `id.endswith("-tsk") or "Treasury" in name`, which finds one module by its
    proper name and nothing else -- a second Treasury from another repository, or
    a different cross-reference index, was silently outside the feature.
    Placement already answers the question properly: the Treasury ships as a
    SWORD commentary but is filed as a cross-reference index, and
    `placement.type_for` is what says so.

    The name test survives only for a module whose own catalogue type is
    unrecognised, and it is deliberately narrower than it was.  As a general
    fallback `"Treasury" in name` also matched *C. H. Spurgeon's Treasury of
    David*, which is a commentary on 2 Samuel and has nothing to do with
    cross-references -- so a plain name test would pull a 24-entry commentary
    into an index of 6,414 entries and call it a cross-reference.  The trailing
    id is the part that is actually specific.
    """
    from . import placement
    from . import taxonomy
    out: list[str] = []
    for m in library.list_all():
        if not m.installed_at:
            continue
        if placement.type_for(m.id, m.type) == "CrossReference":
            out.append(m.id)
            continue
        if m.type not in taxonomy.TYPE_BY_ID and m.id.endswith("-tsk"):
            out.append(m.id)
    return out


def _tsk_cites() -> dict:
    """osis id -> cross-reference entries that cite it, built once.

    One combined pattern over every known book token, so the corpus is walked
    once.  A pattern per book meant one pass per book -- sixty passes over four
    thousand units, and fifteen seconds before a reader saw a panel.
    """
    global _TSK_CITES
    if _TSK_CITES is not None:
        return _TSK_CITES
    tok2osis = {tok: book for book, toks in _book_tokens().items() for tok in toks}
    if not tok2osis:
        _TSK_CITES = {}
        return _TSK_CITES
    rx = re.compile(r"\b(" + "|".join(
        re.escape(t) for t in sorted(tok2osis, key=len, reverse=True))
        + r")\s+(\d{1,3}):(\d{1,3})\b")
    index: dict[str, list[dict]] = {}
    conn = db.connect()
    for mid in crossref_module_ids():
        for r in conn.execute("SELECT key, ref_label, text FROM unit "
                              "WHERE module_id=?", (mid,)):
            entry = {"module_id": mid, "key": r["key"],
                     "label": r["ref_label"] or r["key"],
                     "text": _chunk(r["text"], 260)}
            seen: set[str] = set()
            for m in rx.finditer(r["text"] or ""):
                osis = (f"{tok2osis[m.group(1)]}."
                        f"{int(m.group(2))}.{int(m.group(3))}")
                if osis in seen:
                    continue
                seen.add(osis)
                index.setdefault(osis, []).append(entry)
    _TSK_CITES = index
    return index


def crossrefs_at(conn, book: str, chapter: int, verse: int) -> dict:
    """Cross-references two ways, because TSK is a topical index.

    TSK only has an entry at verses that carry a topic -- John 3 has eight, and
    3:16 is not one of them.  So "outgoing" is whatever the TSK entry at this
    verse cites, and "incoming" is any TSK entry whose body mentions this verse.
    The second is the more useful of the two and the reason a topical index is
    worth parsing at all.
    """
    out: dict = {"outgoing": [], "incoming": [], "tsk_entry": None}
    if not book:
        return out
    osis = f"{book}.{chapter}.{verse}"

    tsk_ids = crossref_module_ids()
    for mid in tsk_ids:
        row = conn.execute(
            "SELECT key, ref_label, text FROM unit WHERE module_id=? AND key=?",
            (mid, osis)).fetchone()
        if not row:
            continue
        out["tsk_entry"] = {"module_id": mid, "key": row["key"],
                            "label": row["ref_label"] or row["key"],
                            "text": _chunk(row["text"], 3000)}
        seen, refs = set(), []
        for key, entries in _tsk_cites().items():
            if key == osis or not any(e["key"] == row["key"] for e in entries):
                continue
            b, c, v = key.split(".")
            label = f"{b} {int(c)}:{int(v)}"
            if label in seen:
                continue
            seen.add(label)
            refs.append({"label": label, "osis": key})
        out["outgoing"] = sorted(refs, key=lambda x: x["label"])[:80]

    out["incoming"] = [x for x in _tsk_cites().get(osis, [])
                       if x["key"] != osis][:40]
    return out


def crossref_panel(ref: str, *, module_ids: list[str] | None = None) -> dict:
    """The cross-references for one reference, both directions, as a panel.

    This is what the verse guide shows, lifted out of it so the cross-reference
    pane has something to open.  Two things make it worth having on its own.

    **A cross-reference index is topical, so most verses have no entry.** The
    Treasury of Scripture Knowledge is an index of subjects; John 3:16, the most
    quoted verse in the New Testament, has no TSK entry at all because it states
    no topic.  A panel that only showed "this verse's entry" would be empty more
    often than not, and would look broken rather than honest.  So it shows both
    directions, and the one that carries most verses is the useful one: *which
    entries elsewhere in the index cite this verse*.

    **It says when there is nothing.** A library with no cross-reference module
    gets a sentence saying so and naming where to get one, not an empty pane --
    an empty pane reads as a broken feature and a sentence reads as a fact about
    the library.

    Module ids given by the caller win, so a reader can pin a specific index;
    otherwise every installed resource filed in the cross-reference slot is used.
    """
    rr = canon.parse_ref(ref) if ref else None
    if rr is None:
        return {"ok": False, "error": f"cannot read {ref!r} as a reference"}
    conn = db.connect()
    want = [m for m in (module_ids or crossref_module_ids())
            if library.get(m) is not None]
    if not want:
        return {"ok": True, "ref": rr.label(), "modules": [], "outgoing": [],
                "incoming": [], "entries": [],
                "notice": ("No cross-reference index is installed, so there is "
                           "nothing to show here. The Store's CrossWire "
                           "repository has the Treasury of Scripture Knowledge, "
                           "which is filed as a cross-reference rather than a "
                           "commentary because that is what its content is.")}
    mods = []
    for mid in want:
        m = library.get(mid)
        mods.append({"id": mid, "name": m.name,
                     "abbrev": m.abbrev or "", "entries": m.entries})
    x = crossrefs_at(conn, rr.start.book, rr.start.chapter, rr.start.verse)
    return {"ok": True, "ref": rr.label(), "modules": mods,
            "entry": x["tsk_entry"],
            "outgoing": x["outgoing"], "incoming": x["incoming"],
            "entries": [] if not want else want,
            "notice": ""}


# --------------------------------------------------------------------------
# topic entries from the FactBook-shaped modules

def my_topics_at(conn, book: str, chapter: int, verse: int,
                 limit: int = 24) -> list[dict]:
    """The reader's own tags on this verse, in the same shape as topic articles.

    Reader tags live in `tag_item` with canonical book/chapter/verse columns,
    so they follow the passage across translations just as published articles
    do.  They are kept separate from FactBook material: a tag is the reader's
    own view, not a reference work.
    """
    if not book:
        return []
    rows = conn.execute(
        "SELECT t.id, t.name, t.color FROM tag_item i "
        "JOIN tag t ON t.id=i.tag_id "
        "WHERE i.book=? AND i.chapter=? AND i.verse=? "
        "ORDER BY t.name COLLATE NOCASE LIMIT ?",
        (book, chapter, verse, limit)).fetchall()
    return [{"module_id": "my-tags", "module": "My topics", "key": r["id"],
             "title": r["name"], "text": r["name"],
             "kind": "mytopic", "color": r["color"] or "", "length": len(r["name"])}
            for r in rows]


def my_topics_for_term(conn, term: str, limit: int = 24) -> list[dict]:
    """Verses the reader tagged with a topic matching `term`."""
    q = (term or "").strip()
    if len(q) < 2:
        return []
    rows = conn.execute(
        "SELECT t.name, i.book, i.chapter, i.verse FROM tag_item i "
        "JOIN tag t ON t.id=i.tag_id "
        "WHERE lower(t.name) LIKE ? AND i.book IS NOT NULL "
        "ORDER BY i.book, i.chapter, i.verse LIMIT ?",
        (f"%{q.lower()}%", limit)).fetchall()
    return [{"module_id": "my-tags", "module": "My topics",
             "key": f"{r['book']}.{r['chapter']}.{r['verse']}",
             "title": f"{r['name']} — {r['book']} {r['chapter']}:{r['verse']}",
             "text": f"{r['book']} {r['chapter']}:{r['verse']}",
             "kind": "mytopic", "length": 0}
            for r in rows]


def topics_at(conn, book: str, chapter: int, verse: int,
              limit: int = 24) -> list[dict]:
    """Topic articles that mention this verse.

    Served from the topic marker index, which is an index lookup on the verse.
    Nave, Torrey, Thompson, ISBE and the Condensed Biblical Cyclopedia all address
    scripture from inside a paragraph of prose -- "Ex 6:16-20; Jos 21:4, 10" --
    with the references as plain characters in a text field, so there is no column
    to ask.  That is what `topicindex` extracts at index time.

    The text scan below is kept as a fallback, and it is only reached when the
    index has not been built for this module yet.  It scans the Fact-book bodies
    with LIKE, which is why the old version had to bound the corpus: it worked
    only because those modules happen to total about ten thousand units, and it
    would have quietly stopped finding things the moment that stopped being true.
    """
    ids = _ids_of_type(("FactBook",))
    if not ids or not book:
        return []
    key = canon.Ref(book, chapter, verse).osis_id()
    indexed = topicindex.topics_reaching(ids, key)
    if indexed:
        mods = {m.id: m for m in library.list_all() if m.id in ids}
        out = []
        for x in indexed:
            m = mods.get(x["module_id"])
            if not m:
                continue
            row = conn.execute(
                "SELECT text FROM unit WHERE module_id=? AND key=?",
                (m.id, x["key"])).fetchone()
            out.append({"module_id": m.id, "module": m.name, "key": x["key"],
                        "title": x["title"],
                        "text": _chunk((row["text"] if row else ""), 1400),
                        "from_index": True})
            if len(out) >= limit:
                break
        return my_topics_at(conn, book, chapter, verse, limit) + out
    ph = ",".join("?" * len(ids))
    # Search every spelling the corpus actually uses for this book, not just the
    # OSIS name -- Nave writes "Joh 3:16" where the unit key says "John.3.16".
    spellings = {book, *_book_tokens().get(book, [])}
    pats = [f"%{t} {chapter}:{verse}%" for t in spellings]
    pats.append(f"%{book}.{chapter}.{verse}%")
    sql = (f"SELECT module_id, key, title, ref_label, text FROM unit "
           f"WHERE module_id IN ({ph}) AND text LIKE ? "
           f"ORDER BY length(text) LIMIT ?")
    seen_pats: list[str] = []
    for p in pats:
        if p not in seen_pats:
            seen_pats.append(p)
    ors = " OR ".join(["text LIKE ?"] * len(seen_pats))
    sql = (f"SELECT module_id, key, title, ref_label, text FROM unit "
           f"WHERE module_id IN ({ph}) AND ({ors}) "
           f"ORDER BY length(text) LIMIT ?")
    rows = conn.execute(sql, [*ids, *seen_pats, limit * 3]).fetchall()
    mods = {m.id: m for m in library.list_all() if m.id in ids}
    out, seen = [], set()
    for r in rows:
        k = (r["module_id"], r["key"])
        if k in seen:
            continue
        seen.add(k)
        m = mods.get(r["module_id"])
        if not m:
            continue
        out.append({"module_id": m.id, "module": m.name,
                    "key": r["key"], "title": r["title"] or r["key"],
                    "text": _chunk(r["text"], 1400),
                    "from_index": False})
        if len(out) >= limit:
            break
    return my_topics_at(conn, book, chapter, verse, limit) + out


# --------------------------------------------------------------------------
# places

_PLACE_CACHE: dict | None = None


def _places() -> list[dict]:
    global _PLACE_CACHE
    if _PLACE_CACHE is None:
        try:
            _PLACE_CACHE = store.load_catalog("openbible-geo").get("places", [])
        except Exception:
            _PLACE_CACHE = []
    return _PLACE_CACHE


_PLACE_REF_CACHE: dict = {}


def _place_refs():
    """Parse gazetteer passages once, not on every verse lookup."""
    from . import refmatch
    places = _places()
    key = id(places)
    got = _PLACE_REF_CACHE.get(key)
    if got is None:
        got = [refmatch.parse_cited("; ".join(p.get("passages") or []))
               for p in places]
        _PLACE_REF_CACHE.clear()
        _PLACE_REF_CACHE[key] = got
    return places, got


def places_at(book: str, chapter: int, verse: int) -> list[dict]:
    """Geocoded places whose passage list includes this verse.

    References are parsed with canon, so the catalogue's inconsistent book
    abbreviations do not matter.  A chapter-level request (verse 0) matches
    every verse in that chapter.
    """
    from . import refmatch
    if verse:
        target = refmatch.milestones(f"{book} {chapter}:{verse}")
    else:
        target = refmatch.milestones(f"{book} {chapter}")
    if not target:
        return []
    out = []
    places, parsed_refs = _place_refs()
    for p, cited in zip(places, parsed_refs):
        if not refmatch.intersects(cited, [target]):
            continue
        if True:
            out.append({"name": p.get("name", ""), "lat": p.get("lat"),
                        "lon": p.get("lon"), "type": p.get("type", ""),
                        "comment": _chunk(p.get("comment", ""), 300),
                        "slug": p.get("slug", "")})
    return out[:20]


# --------------------------------------------------------------------------
# words: Strong's, lexicon entries, occurrences

def _lexicon_keys(num: str) -> list[str]:
    """The key spellings a Strong's lexicon might use for this number.

    CrossWire lexicons are inconsistent: Strong's Greek uses bare zero-padded
    numbers ("00401"), BDB uses "H0430", Dodson "G0001".  Try the plausible
    spellings rather than assuming one.
    """
    if not num:
        return []
    letter = num[0]
    digits = num[1:].lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    unpadded = digits.lstrip("0") or "0"
    cands = {num, f"{letter}{digits}", f"{letter}{unpadded}"}
    if letter == "G":
        # Greek lexicons are keyed "G0025" or bare "00025"
        cands |= {digits, digits.zfill(5)}
    else:
        # Hebrew is four digits, and BDB also files the suffixed senses
        # separately ("H1254a"), so include the base with no suffix.  Zero
        # padding to five here searched for "04300" and found a different word.
        cands |= {digits.zfill(4), digits.lstrip("0") or "0"}
    return sorted(cands)


def lexicon_entries_for(conn, num: str, limit: int = 8) -> list[dict]:
    """Every installed lexicon article for this Strong's number."""
    keys = _lexicon_keys(num)
    if not keys:
        return []
    ids = _ids_of_type(("Lexicon", "Dictionary", "Concordance"))
    if not ids:
        return []
    mods = {m.id: m for m in library.list_all() if m.id in ids}
    ph_m = ",".join("?" * len(ids))
    ph_k = ",".join("?" * len(keys))
    rows = conn.execute(
        f"SELECT module_id, key, title, text FROM unit WHERE module_id IN ({ph_m}) "
        f"AND key IN ({ph_k}) LIMIT ?", [*ids, *keys, limit * 4]).fetchall()
    out = []
    for r in rows:
        m = mods.get(r["module_id"])
        if not m or not (r["text"] or "").strip():
            continue
        out.append({"module_id": m.id, "module": m.name,
                    "key": r["key"], "title": r["title"] or num,
                    "text": _chunk(r["text"], 2000)})
    return out[:limit]


def strongs_in_unit(conn, module_id: str, unit_key: str) -> list[dict]:
    """The Strong's numbers a single unit carries, with their surface forms."""
    rows = conn.execute(
        "SELECT value, surface FROM marker WHERE module_id=? AND unit_key=? "
        "AND kind='strongs' ORDER BY pos", (module_id, unit_key)).fetchall()
    out, seen = [], set()
    for r in rows:
        v = canon.normalise_strongs(r["value"] or "")
        if not v:
            continue
        entry = next((x for x in out if x["number"] == v), None)
        if entry is None:
            out.append({"number": v, "surfaces": []})
            entry = out[-1]
        if r["surface"] and r["surface"] not in entry["surfaces"]:
            entry["surfaces"].append(r["surface"])
    return out


def occurrences_of(conn, num: str, module_ids: list[str] | None = None,
                   limit: int = 300) -> list[dict]:
    """Where a Strong's number occurs, with the reference of each hit.

    One query, joined: asking for the unit again per marker is three hundred
    round trips for one panel and was the whole cost of a word study.
    """
    if not num:
        return []
    sql = ("SELECT m.module_id, m.unit_key, m.surface, "
           "       u.book, u.chapter, u.verse, u.ref_label "
           "FROM marker m LEFT JOIN unit u "
           "  ON u.module_id=m.module_id AND u.key=m.unit_key "
           "WHERE m.kind='strongs' AND m.value=?")
    a: list = [num]
    if module_ids:
        sql += f" AND m.module_id IN ({','.join('?' * len(module_ids))})"
        a += module_ids
    sql += " LIMIT ?"
    a.append(limit)
    out = []
    for r in conn.execute(sql, a):
        ref = None
        if r["book"]:
            ref = {"book": r["book"], "chapter": r["chapter"],
                   "verse": r["verse"], "label": r["ref_label"] or ""}
        out.append({"module_id": r["module_id"], "key": r["unit_key"],
                    "surface": r["surface"] or "", "ref": ref})
    return out


# --------------------------------------------------------------------------
# morphology

def morph_at(conn, book: str, chapter: int, verse: int) -> list[dict]:
    """Every tagged word in this verse, with lemma, Strong's and morph code.

    This is the raw material for reverse interlinears and morph search: OSHB
    and SBLGNT tag every word, so the panel can show the form the manuscript
    actually has rather than an English gloss.
    """
    out = []
    for mid in ("openscriptures-morphhb", "openscriptures-sblgnt"):
        if not _has(mid):
            continue
        rows = conn.execute(
            "SELECT key FROM unit WHERE module_id=? AND book=? AND chapter=? "
            "AND verse=? LIMIT 1", (mid, book, chapter, verse)).fetchall()
        for r in rows:
            for s in strongs_in_unit(conn, mid, r["key"]):
                out.append({"module_id": mid, "unit_key": r["key"],
                            "number": s["number"], "surfaces": s["surfaces"]})
    return out


_MORPH_PRESENT: dict | None = None


def _has(module_id: str) -> bool:
    global _MORPH_PRESENT
    if _MORPH_PRESENT is None:
        _MORPH_PRESENT = {m.id for m in library.list_all()}
    return module_id in _MORPH_PRESENT


_SPAN_CACHE: dict[tuple[str, str], list] = {}


def _spans(conn, module_id: str, key: str) -> list:
    """The unit's span table: [[start, len, kind, strongs, morph, attrs], ...]."""
    ck = (module_id, key)
    if ck not in _SPAN_CACHE:
        row = conn.execute("SELECT markup, text FROM unit WHERE module_id=? "
                           "AND key=?", (module_id, key)).fetchone()
        spans, text = [], ""
        if row is not None:
            text = row["text"] or ""
            try:
                spans = (json.loads(row["markup"] or "{}") or {}).get("s") or []
            except (json.JSONDecodeError, TypeError, AttributeError):
                spans = []
        _SPAN_CACHE[ck] = (spans, text)
    return _SPAN_CACHE[ck]


def _surface_for(conn, module_id: str, key: str, code: str,
                 surface: str = "") -> str:
    """The actual word behind a morphology hit.

    The marker table stores the morphology code in `surface`, so a hit would
    read "HNcmsa" rather than the Hebrew.  The unit's span table has the offsets
    into the text, so slice it to get the word the reader actually wants.
    """
    if surface and surface != code:
        return surface
    spans, text = _spans(conn, module_id, key)
    for sp in spans:
        if len(sp) >= 5 and sp[4] == code:
            start, ln = int(sp[0]), int(sp[1])
            word = text[start:start + ln]
            if word.strip():
                return word
    return surface


def morph_search(conn, code: str, *, scheme: str = "", limit: int = 400,
                 module_id: str = "", ref: str = "") -> dict:
    """Find every tagged word with this morphology code.

    Three tagging schemes are installed and they are not interchangeable, so
    they are reported separately rather than merged:

      * OSHB   -- "HNp", "HTd/Ncmsa"  (Robinson codes, H-prefixed)
      * Robinson -- "robinson:CONJ"
      * strongMorph -- "strongMorph:TH8799"

    A prefix search is the useful one: "HNcms" finds every noun, "HTd/" every
    article.  This is morphology search, and it needs no subscription because
    the tagging is already in the text.

    Pass ``module_id`` to constrain the search to one morphologically-tagged
    resource (used for the side-by-side "compare versions" view).  Pass
    ``ref`` (e.g. "John 3") to constrain the search to a passage.
    """
    code = (code or "").strip()
    if not code:
        return {"ok": False, "error": "no morphology code"}
    ref = (ref or "").strip()
    from . import morphq
    # Resolve the request once through the same decoder the search engine uses.
    # A prefix search on the raw code found spellings, not grammatical forms:
    # `HNcms` missed the same noun written under another scheme, and a fragment
    # inside an unrelated tag matched a word with none of the requested features.
    codes = morphq.resolve_query(code)["codes"]
    if not codes:
        return {"ok": True, "query": code, "total": 0, "scanned": 0,
                "schemes": [], "hits": [],
                "note": "No tagged word carries those morphological features."}
    extra_where, extra_args = "", []
    if module_id:
        extra_where += " AND m.module_id=?"
        extra_args.append(module_id)
    if ref:
        scoped = [module_id] if module_id else morphq.morph_module_ids(conn)
        try:
            morphq.passage_table(conn, ref, scoped)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        extra_where += morphq._passage_clause("m")
    # Exact count over every matching tag, not over the page the panel shows.
    # Chunked IN below the common SQLite variable floor: a broad feature match
    # can resolve to hundreds of tag values.
    found: list = []
    total = 0
    for i in range(0, len(codes), 400):
        chunk = codes[i:i + 400]
        ph = ",".join("?" * len(chunk))
        where = "m.kind='morph' AND m.value IN (" + ph + ")" + extra_where
        args = [*chunk, *extra_args]
        total += conn.execute(
            "SELECT count(*) FROM marker m WHERE " + where, args).fetchone()[0]
        found.extend(conn.execute(
            "SELECT m.value, m.module_id, m.unit_key, m.surface FROM marker m "
            "WHERE " + where, args).fetchall())
    found.sort(key=lambda r: (r["module_id"], r["unit_key"], r["value"]))
    rows = found[:limit]
    groups: dict[str, dict] = {}
    hits: list[dict] = []
    for r in rows:
        v = r["value"]
        scheme_name = ("Robinson" if v.startswith("robinson:")
                       else "strongMorph" if v.startswith("strongMorph:")
                       else "OSHB")
        g = groups.setdefault(scheme_name, {"scheme": scheme_name, "count": 0,
                                            "codes": set()})
        g["count"] += 1
        g["codes"].add(v)
        hit_ref = None
        u = conn.execute("SELECT book, chapter, verse, ref_label FROM unit "
                         "WHERE module_id=? AND key=?",
                         (r["module_id"], r["unit_key"])).fetchone()
        if u and u["book"]:
            hit_ref = {"book": u["book"], "chapter": u["chapter"],
                       "verse": u["verse"], "label": u["ref_label"] or ""}
        hits.append({"code": v, "module_id": r["module_id"],
                     "key": r["unit_key"],
                     "surface": _surface_for(conn, r["module_id"],
                                             r["unit_key"], v, r["surface"] or ""),
                     "ref": hit_ref})
    return {
        "ok": True, "query": code,
        "total": total,
        "scanned": len(rows),
        "schemes": [{"scheme": k, "count": v["count"],
                     "codes": sorted(v["codes"])[:40]}
                    for k, v in sorted(groups.items())],
        "hits": hits,
    }


_GLOSS_CACHE: dict[str, str] = {}


def _clean_gloss(text: str) -> str:
    """Turn a lexicon article's opening into one readable line.

    Every installed lexicon writes its head differently, and a generic strip
    mangles all of them:

      BDB          "H430  \u05d0\u05e9\u05dc\u05d4\u05d9\u05dd   n. m. pl .  .  .  rulers , judges"
      Dodson       "\u03b8\u03b5\u03cc\u03c2, \u03bf\u1d58, \u03bf\u03b1\nn.f. & n.m.\nGod, a god"
      Strong's     "\n \u03b8\u03b5\u03cc\u03c2\n\n qeovs   theos   {theh'-os} \n\n\n of uncertain..."
      Abbott-Smith "\n \n **  \u03b4\u03b9\u03b1-\u03ba\u03c9\u03bb\u03b5\u03cd\u03c9  \n \n  [in LXX: ...]  to hinder"
    """
    t = (text or "")
    t = re.sub(r"\*\*", " ", t)                       # Abbott-Smith bold
    t = re.sub(r"\[[^\]]*\]", " ", t)                 # bracketed apparatus
    t = re.sub(r"\{[^}]*\}", " ", t)                  # {transliteration}
    t = re.sub(r"^\s*[GH]?\d{2,5}[a-z]?\b", " ", t)   # H430 / 430 / H1254a
    # a lemma line: the headword with its ", -o\u1d58, \u03bf\u03b1" suffixes
    # \W is Unicode-aware in Python 3, so it matches Greek and Hebrew as *word*
    # characters and eats the lemma before the explicit class can.  Match the
    # leading space and the lemma separately.
    t = re.sub(r"^\s*[" + _SCRIPT + r"]+[,\s\-[" + _SCRIPT + r"]*", " ", t)
    # an ASCII transliteration line: "qeovs   theos"
    # A transliteration line is at most two tokens ("qeovs   theos").  Allowing
    # any number ate whole clauses, and "perhaps from agan" vanished with it.
    t = re.sub(r"^\s*[A-Za-z][A-Za-z'\-]{1,14}(?:\s+[A-Za-z][A-Za-z'\-]{1,14}){0,1}\s*"
               r"\.{0,3}\s*", " ", t, count=1)
    t = re.sub(r"\bn\.\s*[fm]\s*\.?", " ", t)          # "n.f. & n.m."
    t = t.replace("&", " ")
    t = re.sub(r"\s+", " ", t).strip(" .,-\u2013\u2014;")
    if not t:
        return ""
    return re.split(r"(?<=[.;])\s", t)[0][:120].strip()


_ETY = re.compile(r"^(of (?:uncertain|Latin|Greek|Hebrew|Arabic|Persian|Chaldee)"
                   r"|from (?:the same|\d|[a-zA-Z\u0370-\u03ff\u0590-\u05ff])"
                   r"|perhaps from|compare|formed from|of the form"
                   r"|a primitive root|transliteration|\S*or compare)", re.I)


def _usable_gloss(g: str) -> bool:
    """Does this read like a definition rather than a transliteration?

    A lexicon head that survives the clean can still be "a-gapa-o agapao
    perhaps from agan" -- the Greek lemma followed by its romanisation.  A
    definition has ordinary words in it.  When nothing passes, the interlinear
    shows the Strong's number alone and the reader clicks through, which is
    better than a confident wrong gloss.
    """
    if len(g) < 6:
        return False
    if re.search(r"[\u2e80-\u9fff\uf900-\ufaff]", g):
        return False        # a mixed-script lexicon, not a definition
    words = re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", g)
    if not words:
        return False
    if len(words) < 2 and max(len(w) for w in words) < 6:
        return False
    # a transliteration blob: several short lowercase tokens and no real words
    if len(words) >= 3 and sum(len(w) for w in words) < 18:
        return False
    return True


def _gloss_for(conn, num: str) -> str:
    """A one-line definition for a Strong's number.

    Two sources, in order of trust:

    1. The concordance.  It is keyed by the Strong's number exactly, and every
       entry is "word (transliteration): definition" -- so the definition is
       the part after the colon.  Nothing has to be guessed.
    2. A lexicon article, cleaned.  BDB and Strong's both carry short
       cross-reference stubs ("see 303") and letter-suffixed keys ("H1254a"),
       so these are only consulted when the concordance is silent.

    The `strongs` roll-up is never used: its `word` column is the most frequent
    *surface form* for the number, so G2316 reads "would" and H7225 "of".
    """
    if num in _GLOSS_CACHE:
        return _GLOSS_CACHE[num]
    # Normalise first, or "G25" and "G0025" are two cache entries with two
    # different answers for the same word.
    num = canon.normalise_strongs(num) or num
    if num in _GLOSS_CACHE:
        return _GLOSS_CACHE[num]
    gloss = ""

    row = conn.execute(
        "SELECT u.text FROM unit u JOIN module m ON m.id=u.module_id "
        f"WHERE u.key IN ({','.join('?' * len(_lexicon_keys(num)))}) "
        "AND m.type='Concordance' AND m.installed_at>0 LIMIT 1",
        _lexicon_keys(num)).fetchone()
    if row is not None:
        t = re.sub(r"\s+", " ", row["text"] or "").strip()
        m = re.match(r"^.{0,60}?\(([^)]*)\)\s*:\s*(.+)$", t)
        gloss = m.group(2) if m else (re.search(r":\s*(.+)$", t) or [None, t])[1]
        # A concordance entry opens with its etymology and puts the sense after
        # it: "of uncertain affinity; a deity, especially (with o) the supreme
        # Divinity".  Cutting at the first semicolon keeps the etymology and
        # throws the definition away, so drop the etymology clauses instead.
        clauses = [x.strip() for x in gloss.split(";") if x.strip()]
        while clauses and _ETY.match(clauses[0]):
            clauses.pop(0)
        gloss = "; ".join(clauses) if clauses else ""

    # The concordance is mostly right but not entirely: its G2889 article is
    # about Quartus, not kosmos.  A mis-keyed row would put a confident wrong
    # gloss in front of the reader, so cross-check the headword against the
    # lexicon article for the same number and fall back if they disagree.
    if gloss:
        head = re.search(r"[\u0370-\u03ff\u0590-\u05ff]+", row["text"] or "")
        if head:
            lex = conn.execute(
                "SELECT u.text FROM unit u JOIN module m ON m.id=u.module_id "
                f"WHERE u.key IN ({','.join('?' * len(_lexicon_keys(num)))}) "
                "AND m.type IN ('Lexicon','Dictionary') AND m.installed_at>0 "
                "LIMIT 1",
                _lexicon_keys(num)).fetchone()
            if lex is not None:
                lhead = re.search(r"[\u0370-\u03ff\u0590-\u05ff]+", lex["text"] or "")
                if lhead and lhead.group(0) != head.group(0):
                    gloss = ""

    if not gloss or len(gloss) < 3:
        rows = conn.execute(
            "SELECT u.module_id, u.text FROM unit u JOIN module m ON m.id=u.module_id "
            f"WHERE u.key IN ({','.join('?' * len(_lexicon_keys(num)))}) "
            "AND m.type IN ('Lexicon','Dictionary') AND m.installed_at>0", _lexicon_keys(num)).fetchall()
        hebrew = num.startswith("H")
        order = {"crosswire-dodson": 0, "crosswire-bdbglosses-strongs": 1,
                 "crosswire-strongsgreek": 2}

        def rank(r):
            raw = r["text"] or ""
            stub = 1 if (re.match(r"^\s*see\b", raw, re.I) or len(raw) < 40) else 0
            gk = ("dodson" in r["module_id"] or "strongsgreek" in r["module_id"]
                  or "abbottsmith" in r["module_id"])
            return (stub, 0 if (gk != hebrew) else 1,
                    order.get(r["module_id"], 5), len(raw))

        for r in sorted(rows, key=rank):
            g = _clean_gloss(r["text"])
            # strip the same etymology clauses the concordance path drops, or
            # the gloss comes out as "perhaps from agan (much)"
            g = "; ".join(c for c in (x.strip() for x in g.split(";"))
                          if c and not _ETY.match(c))
            if _usable_gloss(g):
                gloss = g
                break
    _GLOSS_CACHE[num] = gloss[:120]
    return _GLOSS_CACHE[num]


def _original_form(conn, num: str) -> str:
    """The original-language form for a Strong's number, if a lexicon has it.

    Concordance and lexicon entries open with the word itself -- Greek or
    Hebrew -- so the first run of Greek/Hebrew characters in the entry is the
    form.  Returns '' when nothing is installed or the entry is English only.
    """
    if not num:
        return ""
    num = canon.normalise_strongs(num) or num
    row = conn.execute(
        "SELECT u.text FROM unit u JOIN module m ON m.id=u.module_id "
        "WHERE u.key=? AND m.type='Concordance' AND m.installed_at>0 LIMIT 1",
        (num,)).fetchone()
    if row is not None:
        m = re.search(r"[\u0370-\u03ff\u0590-\u05ff\u1f00-\u1fff]+", row["text"] or "")
        if m:
            return m.group(0)
    keys = _lexicon_keys(num)
    rows = conn.execute(
        "SELECT u.text FROM unit u JOIN module m ON m.id=u.module_id "
        f"WHERE u.key IN ({','.join('?' * len(keys))}) "
        "AND m.type IN ('Lexicon','Dictionary') AND m.installed_at>0",
        keys).fetchall()
    for r in rows:
        m = re.search(r"[\u0370-\u03ff\u0590-\u05ff\u1f00-\u1fff]+", r["text"] or "")
        if m:
            return m.group(0)
    return ""


def definition(word: str = "", num: str = "") -> dict:
    """A small, fast definition lookup by printed word and/or Strong's number.

    The reader's old word paths only asked for a Strong's number, which no
    headword-keyed dictionary (Smith's, Easton, Webster, TIPNR) can answer.
    This is the one place both key types meet: lexicons and concordances by
    number, dictionaries and fact books by the word as printed.
    """
    conn = db.connect()
    word = (word or "").strip()
    num = canon.normalise_strongs(num or "") or (num or "").strip()
    out = {"ok": True, "word": word, "num": num,
           "strongs": None, "entries": [], "more": 0}
    if num:
        form = _original_form(conn, num)
        gloss = _gloss_for(conn, num).strip()
        out["strongs"] = {"number": num, "form": form, "gloss": gloss[:300]}
    if not word:
        return out
    mods = [m for m in library.list_all()
            if m.type in ("Dictionary", "Lexicon", "FactBook", "Concordance")]
    if not mods:
        return out
    ids = [m.id for m in mods]
    by_id = {m.id: m for m in mods}
    ph = ",".join("?" * len(ids))
    key = word.lower()
    rows = conn.execute(
        f"SELECT module_id,key,title,text FROM unit WHERE module_id IN ({ph}) "
        "AND (lower(key)=? OR lower(title)=?) LIMIT 300",
        [*ids, key, key]).fetchall()
    if not rows:
        rows = conn.execute(
            f"SELECT module_id,key,title,text FROM unit WHERE module_id IN ({ph}) "
            "AND (lower(key) LIKE ? OR lower(title) LIKE ?) LIMIT 300",
            [*ids, key + "%", key + "%"]).fetchall()
    seen = set()
    for r in rows:
        mid = r["module_id"]
        title = (r["title"] or r["key"] or "").strip()
        marker = (mid, title.lower())
        if marker in seen:
            continue
        seen.add(marker)
        text = re.sub(r"<[^>]+>", " ", r["text"] or "")
        # Keep line breaks: outline indexes are summarised by their headings,
        # and collapsing whitespace here would hide that structure.
        text = re.sub(r"[ \t]+", " ", text).strip()
        m = by_id.get(mid)
        out["entries"].append({
            "module_id": mid, "module": (m.name if m else mid) or mid,
            "type": (m.type if m else "") or "",
            "title": title, "key": r["key"] or "",
            "text": _summary_text(text, 300),
        })
    out["more"] = max(0, len(rows) - len(out["entries"]))
    return out


def reverse_interlinear(conn, module_id: str, book: str, chapter: int,
                      verse: int) -> dict:
    """A reverse interlinear: English word on top, original form beneath.

    Reuses the tagged span data of the source module (a tagged English Bible
    such as the KJV with Strong's) and looks up the original-language form for
    each Strong's number from installed concordances/lexicons, so nothing new
    has to be downloaded.  Words without a number carry no original form.
    """
    base = interlinear(conn, module_id, book, chapter, verse)
    if not base.get("ok"):
        return base
    out_words = []
    for w in base.get("words", []):
        orig = ""
        for n in (w.get("strongs") or []):
            o = _original_form(conn, n)
            if o:
                orig = o
                break
        out_words.append({
            "form": w.get("form", ""),
            "strongs": w.get("strongs", []),
            "morph": w.get("morph", []),
            "gloss": w.get("gloss", ""),
            "original": orig,
        })
    base["words"] = out_words
    base["mode"] = "reverse"
    return base


def interlinear(conn, module_id: str, book: str, chapter: int,
                verse: int) -> dict:
    """One verse, word by word: the form, its lemma, and a short gloss.

    The span table written at index time carries, for every word, where it is
    in the text, its Strong's numbers and its morphology.  That is everything a
    three-line interlinear needs:

        Hebrew   בְּ/רֵאשִׁ֖ית   בָּרָ֣א   אֱלֹהִ֑ים
        lemma    H7225          H1254    H0430
        gloss    beginning      created  God

    OSHB gives a real Hebrew interlinear.  The tagged KJV gives the same
    structure over English with Robinson codes, which is an analysis rather
    than a translation, and is labelled as such.
    """
    m = library.get(module_id)
    row = conn.execute("SELECT key, text, markup, ref_label FROM unit "
                       "WHERE module_id=? AND book=? AND chapter=? AND verse=? "
                       "LIMIT 1", (module_id, book, chapter, verse)).fetchone()
    if row is None:
        return {"ok": False, "error": "no such verse"}
    text = row["text"] or ""
    try:
        spans = (json.loads(row["markup"] or "{}") or {}).get("s") or []
    except (json.JSONDecodeError, TypeError):
        spans = []
    if not spans:
        return {"ok": False, "error": "this resource is not tagged word by word"}

    # one gloss lookup for the whole verse
    nums: list[str] = []
    for sp in spans:
        for n in (sp[3] or "").split():
            n = canon.normalise_strongs(n)
            if n and n not in nums:
                nums.append(n)
    gloss: dict[str, str] = {}
    for n in nums:
        gloss[n] = _gloss_for(conn, n)

    words = []
    for sp in spans:
        start, ln = int(sp[0]), int(sp[1])
        form = text[start:start + ln]
        if not form.strip():
            continue                       # whitespace span
        sn = [canon.normalise_strongs(x) for x in (sp[3] or "").split()]
        mn = [x for x in (sp[4] or "").split() if x]
        words.append({
            "form": form,
            "strongs": [x for x in sn if x],
            "morph": mn,
            "gloss": "; ".join(gloss.get(x, "") for x in sn if gloss.get(x)),
        })
    return {
        "ok": True,
        "module_id": module_id, "module": m.name if m else module_id,
        "lang": m.lang if m else "",
        "ref": row["ref_label"] or f"{book} {chapter}:{verse}",
        "text": text,
        "words": words,
        "tagged": len(words),
    }


# --------------------------------------------------------------------------
# topic guide
#: Translations to look in for Related Verses, best first.  Picking the first
#: Bible alphabetically does not work: the one that sorts first may not contain
#: the word at all, which is why an early version returned nothing for
#: "Jerusalem" while reporting success.
_VERSE_BIBLE_PREFERENCE = (
    "open-bibles-eng-kjv", "crosswire-kjv", "ebible-eng-web", "open-bibles-eng-web",
    "open-bibles-eng-bsb", "ebible-eng-asv", "crosswire-asv", "ebible-eng-kjv",
    "open-bibles-eng-kjv-strongs", "ebible-eng-kjvstrongs",
)


def _related_verses(q: str, *, limit: int = 12,
                    modules: dict | None = None) -> list[dict]:
    """Verses in which the word stands, from a translation or two.

    A plain scan of one Bible's ~31,000 verses takes about ten milliseconds and
    answers exactly what is wanted; the general search engine takes seven seconds
    to answer the same question because it is built for ranked multi-term
    matching across everything.  A guide that assembles in a tenth of a second
    and says "verses containing the word" is more useful than one that hangs and
    overstates what it found.
    """
    term = (q or "").strip()
    if len(term) < 3:
        return []
    have = {m.id: m for m in (modules.values() if modules is not None
                              else library.list_all()) if m.type == "Bible"}
    ordered = [have[i] for i in _VERSE_BIBLE_PREFERENCE if i in have]
    ordered += [m for m in have.values() if m not in ordered]
    conn = db.connect()
    out: list[dict] = []
    used = 0
    for m in ordered:
        if used >= 2:
            break
        rows = conn.execute(
            "SELECT key, ref_label, book, chapter, verse, text FROM unit "
            "WHERE module_id=? AND text LIKE ? "
            "AND book IS NOT NULL AND chapter>0 "
            "ORDER BY book, chapter, verse",
            (m.id, f"%{term}%")).fetchall()
        if not rows:
            continue
        used += 1
        for r in rows:
            if len(out) >= limit:
                break
            body = _chunk(r["text"], 300)
            # Show the word in place, so the reader can see it in the sentence.
            i = body.lower().find(term.lower())
            if i > 40:
                body = "…" + body[i - 40:]
            out.append({"module_id": m.id, "module": m.name, "key": r["key"],
                        "label": r["ref_label"] or f"{r['book']} {r['chapter']}",
                        "title": r["ref_label"] or r["key"], "text": body,
                        "length": len(r["text"] or "")})
    return out[:limit]


def _atlas_for(conn, ql: str, limit: int,
               modules: dict | None = None) -> list[dict]:
    """Atlas and map entries whose name mentions the term."""
    atlas = [m for m in (modules.values() if modules is not None
                         else library.list_all())
             if m.type in ("Atlas", "Map")]
    if not atlas:
        return []
    ph = ",".join("?" * len(atlas))
    like = f"%{ql}%"
    rows = conn.execute(
        f"SELECT module_id, key, title, text FROM unit WHERE module_id IN ({ph}) "
        f"AND (title LIKE ? OR key LIKE ?) LIMIT ?",
        [*[m.id for m in atlas], like, like, limit]).fetchall()
    mods = {m.id: m for m in atlas}
    return [{"module_id": r["module_id"], "module": mods[r["module_id"]].name,
             "key": r["key"], "title": r["title"] or r["key"],
             "text": _chunk(r["text"], 300), "length": len(r["text"] or "")}
            for r in rows]


def _strip_tags(html: str) -> str:
    import re as _re
    t = _re.sub(r"<[^>]+>", "", html or "")
    return _re.sub(r"\s+", " ", t).strip()


# --------------------------------------------------------------------------
# what the two guides share
# --------------------------------------------------------------------------
#
# The topic guide and the fact book answer two different questions of the same
# material -- *what is installed on this topic?* and *what kind of thing is
# this, and what does each reference work say about it?* -- and they were
# gathering some of the same things separately, which is how a reader ends up
# learning two shapes for one question.
#
# So the gathering is done once, here, and each guide arranges what it gets.

def _fact_rows(conn, mods, q: str) -> list[dict]:
    """Every fact-book entry that mentions the term.

    The query is shared because both guides ask the same question of the same
    books -- *what do the fact books say about this?* -- and answer it
    differently afterwards: the topic guide hands back the longest articles,
    and the fact book sorts them into kinds.
    """
    names = [m.id for m in mods]
    ph = ",".join("?" * len(names))
    # Fact-book heads are stored in each book's own case -- Hitchcock and Nave
    # are all caps, Torrey title case -- so match both the given and the
    # capitalised form.  "aaron" has to find AARON.
    like, like_cap = f"%{q}%", f"%{q.capitalize()}%"
    rows = conn.execute(
        f"SELECT module_id, key, title, text FROM unit WHERE module_id IN ({ph}) "
        f"AND (title LIKE ? OR title LIKE ? OR key LIKE ? OR key LIKE ?)",
        [*names, like, like_cap, like, like_cap]).fetchall()
    return [dict(r) for r in rows]


def _extra_sections(conn, mods, q: str, per_section: int, *,
                    places: bool = True) -> list[dict]:
    """The material that is not a fact-book entry.

    The verses that use the word, the short glosses from a dictionary, the
    concordance, the maps, the Strong's entry, and the places named for the
    term.  Both guides show these, because a reader who has asked about a
    term wants the same things whichever door they came through.

    `places` is off for the fact book, which already carries the gazetteer in
    its own *located* list: the same places, with their coordinates and the
    passages that name them.
    """
    out: list[dict] = []
    all_mods = dict(mods)

    # -- Related Verses: where the term is actually addressed.
    # This section lets you save the result as a passage list.
    verses = _related_verses(q, limit=14, modules=all_mods)
    if verses:
        out.append({"kind": "verses", "label": "Related Verses",
                    "note": "Verses containing the word", "items": verses})

    # -- Atlas: the map and atlas resources.  Eighty-six of them are installed.
    atlas = _atlas_for(conn, q, per_section, modules=all_mods)
    if atlas:
        out.append({"kind": "atlas", "label": "Atlas",
                    "note": "From your atlas and map resources",
                    "items": atlas})

    # -- dictionary and lexicon glosses, deliberately short
    lex = [i for i in all_mods.values() if i.type in ("Dictionary", "Lexicon")]
    if lex:
        ph = ",".join("?" * len(lex))
        rows = conn.execute(
            f"SELECT module_id, key, title, text FROM unit WHERE module_id IN ({ph}) "
            f"AND (title LIKE ? OR key LIKE ?) LIMIT ?",
            [*[m.id for m in lex], f"%{q}%", f"%{q}%", per_section * 8]).fetchall()
        ql = q.lower()

        def rank(r):
            t = (r["title"] or "").lower()
            k = (r["key"] or "").lower()
            if t == ql or k == ql:
                return 0
            if t.startswith(ql) or k.startswith(ql):
                return 1
            if ql in t.split(",")[0] or ql in k.split(",")[0]:
                return 2
            return 3
        # A Strong's article that is only a cross-reference ("see HEBREW for
        # 03722") is not a gloss of the word; rank the ones that actually
        # define it first.
        crossref = lambda r: 4 if (r["text"] or "").strip().lower().startswith("see ") else 0
        rows = sorted(rows, key=lambda r: (rank(r), crossref(r), len(r["text"] or "")))
        items = [_item(r, all_mods, 320) for r in rows[:per_section]]
        if items:
            out.append({"kind": "dictionary", "label": "Dictionary",
                        "note": "Short glosses; open the resource to read past "
                                "the summary",
                        "items": items})

    # -- concordance, by headword only: matching the body finds the word a
    # passage *denies* ("unbelief" under a search for "faith")
    con = [i for i in all_mods.values() if i.type == "Concordance"]
    if con:
        ph = ",".join("?" * len(con))
        rows = conn.execute(
            f"SELECT module_id, key, title, text FROM unit WHERE module_id IN ({ph}) "
            f"AND (title LIKE ? OR key LIKE ?) LIMIT ?",
            [*[m.id for m in con], f"%{q}%", f"%{q}%", per_section]).fetchall()
        items = [_item(r, all_mods, 320) for r in rows]
        if items:
            out.append({"kind": "concordance", "label": "Concordance",
                        "note": "By the headword", "items": items})

    # -- places named for the term
    if places:
        pz = [p for p in _places() if q.lower() in (p.get("name") or "").lower()]
        if pz:
            out.append({"kind": "place", "label": "Places",
                        "note": "Geocoded", "items": [
                            {"module_id": "", "module": "", "key": p.get("slug", ""),
                             "title": p.get("name", ""),
                             "text": _chunk(p.get("comment", ""), 320),
                             "lat": p.get("lat"), "lon": p.get("lon"),
                             "length": len(p.get("comment") or "")}
                            for p in pz[:per_section]]})

    # -- if it is a Strong's number, the lexicons and occurrences
    num = canon.normalise_strongs(q)
    if num and num != q.upper():
        wb = word_bundle(num)
        if wb.get("ok") and (wb["entries"] or wb["total"]):
            out.append({"kind": "word", "label": "Strong's " + num,
                        "note": f"{wb['total']} occurrences, "
                                f"{len(wb['entries'])} lexicon articles",
                        "number": num, "items": []})
    return out


def _item(r, mods: dict, limit: int) -> dict:
    """One unit as a section item, with its text trimmed to `limit`."""
    return {"module_id": r["module_id"], "module": mods[r["module_id"]].name,
            "key": r["key"], "title": r["title"] or r["key"],
            "text": _summary_text(r["text"], limit), "length": len(r["text"] or "")}


def _priority_rank(m) -> int:
    """Negative priority, so a plain sort puts the reader's preferred books first."""
    try:
        return -int(getattr(m, "priority", 0) or 0)
    except (TypeError, ValueError):
        return 0


def topic_guide(query: str, *, per_section: int = 6,
                modules: dict | None = None) -> dict:
    """Every installed resource on one topic, gathered under one heading.

    This is the shape a good fact book has: a topical article, a short
    dictionary gloss, and the other material that shares the heading, rather
    than a flat list of resources you have to go and open yourself.

    The sections are kept separate on purpose.  A dictionary belongs in a
    dictionary section -- brief, because Easton is a glossary, not an essay --
    while a topical article belongs in full.  Merging them would bury the
    article under three glosses for the same word.

    The gathering is shared with the fact book, which asks a different
    question of the same material; see `_extra_sections`.
    """
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "no topic"}
    conn = db.connect()
    out: dict = {"ok": True, "query": q, "sections": []}

    mods = dict(modules) if modules is not None else {
        m.id: m for m in library.list_all()}

    # -- the full article, and a way on to the Fact guide.
    # A short definition here links onward to the Fact guide article; the Fact
    # guide holds the one long article, so the two do not print the same thing
    # twice.
    fb = [i for i in mods.values()
          if i.type == "FactBook" and _is_a_fact_book(i.name)]
    fb.sort(key=lambda m: (_priority_rank(m), m.name or ""))
    if fb:
        rows = _fact_rows(conn, fb, q)
        prio = {m.id: _priority_rank(m) for m in fb}
        rows = sorted(rows, key=lambda r: (
            prio.get(r["module_id"], 0), -len(r["text"] or "")))[:per_section]
        out["sections"].append({
            "kind": "topic", "label": "Topic", "note": "The full article",
            "fact_query": q,
            "items": [_item(r, mods, 2200) for r in rows]})

    # -- the material that is not a fact-book entry
    mine = my_topics_for_term(conn, q, per_section)
    if mine:
        out["sections"].append({
            "kind": "mytopics", "label": "My topics",
            "note": "Verses you tagged with this topic", "items": mine})
    out["sections"].extend(_extra_sections(conn, mods, q, per_section))

    out["total_sections"] = len(out["sections"])
    return out


# --------------------------------------------------------------------------
# parallel comparison

def compare(ref: str, module_ids: list[str]) -> dict:
    """The same verse in several translations, side by side."""
    rr = canon.parse_ref(ref)
    if rr is None:
        return {"ok": False, "error": f"cannot read {ref!r} as a reference"}
    osis = next(iter(rr.refs()), None)
    if osis is None:
        return {"ok": False, "error": "no verse in that range"}
    conn = db.connect()
    out = []
    skipped = []
    for mid in module_ids:
        m = library.get_installed(mid)
        if m is None:
            skipped.append({"module_id": mid, "reason": "not installed"})
            continue
        if m.type not in library.VERSE_TEXT_TYPES:
            skipped.append({"module_id": mid, "reason": "not a verse text"})
            continue
        # Look the verse up by its columns, not by key: the key format is not
        # consistent between modules -- WEB stores "John.3.16" and the Berean
        # "John 3:16" -- so building the key drops translations silently.
        r = conn.execute(
            "SELECT text, ref_label FROM unit WHERE module_id=? AND book=? "
            "AND chapter=? AND verse=? LIMIT 1",
            (mid, osis.book, osis.chapter, osis.verse)).fetchone()
        if r is None or not (r["text"] or "").strip():
            skipped.append({"module_id": mid, "reason": "does not contain that verse"})
            continue
        out.append({"module_id": mid, "module": m.name, "abbrev": m.abbrev or "",
                    "version": m.version or "", "lang": m.lang,
                    "text": r["text"].strip(),
                    "label": r["ref_label"] or f"{osis.book} {osis.chapter}:{osis.verse}"})
    if not out:
        return {"ok": False, "error": "none of those resources have that verse",
                "skipped": skipped}
    requested = list(rr.refs())
    return {"ok": True, "ref": canon.format_ref(osis),
            "requested": ref, "skipped": skipped,
            "note": ("Only the first verse of the requested range was compared."
                     if len(requested) > 1 else ""),
            "columns": out}


# --------------------------------------------------------------------------
# the two bundles

def verse_bundle(module_id: str, unit_key: str, *, want_morph: bool = True) -> dict:
    """Everything installed that bears on one verse."""
    conn = db.connect()
    row = conn.execute("SELECT * FROM unit WHERE module_id=? AND key=?",
                       (module_id, unit_key)).fetchone()
    if row is None:
        return {"ok": False, "error": "no such unit"}
    book, chapter, verse = row["book"], int(row["chapter"] or 0), int(row["verse"] or 0)

    out: dict = {
        "ok": True,
        "ref": {"book": book, "chapter": chapter, "verse": verse,
                "label": row["ref_label"] or canon.Ref(book, chapter, verse).label()
                if book else (row["ref_label"] or row["key"])},
        "osis": f"{book}.{chapter}.{verse}" if book else "",
        "text": row["text"] or "",
        "commentaries": commentaries_at(conn, book, chapter, verse),
        "crossrefs": crossrefs_at(conn, book, chapter, verse),
        "topics": topics_at(conn, book, chapter, verse),
        "places": places_at(book, chapter, verse),
        "words": [],
    }
    # Occurrence counts come from the strongs roll-up in ONE query.  Asking
    # marker for a count per word is a full scan each time -- fifteen words per
    # verse made a verse take ten seconds, all of it in the index.
    counts: dict[str, int] = {}
    words = strongs_in_unit(conn, module_id, unit_key)
    if words:
        nums = [w["number"] for w in words]
        ph = ",".join("?" * len(nums))
        for r in conn.execute(
                f"SELECT strongs, count FROM strongs WHERE strongs IN ({ph})", nums):
            counts[r["strongs"]] = r["count"]
    for s in words:
        s["count"] = counts.get(s["number"], 0)
    out["words"] = words
    if want_morph:
        out["morph"] = morph_at(conn, book, chapter, verse)
    return out


def word_bundle(num: str, *, module_ids: list[str] | None = None,
                word: str = "") -> dict:
    """Everything installed that bears on one Strong's number.

    A surface word is accepted too: callers used to send "love" as a number
    and get "no Strong's number", even though the marker table can resolve it.
    """
    conn = db.connect()
    num = canon.normalise_strongs(num or "")
    if not num and word:
        row = conn.execute(
            "SELECT value FROM marker WHERE kind='strongs' AND lower(surface)=lower(?) "
            "ORDER BY pos LIMIT 1", (word.strip(),)).fetchone()
        if row:
            num = canon.normalise_strongs(row["value"] or "")
    if not num:
        return {"ok": False, "error": "no Strong's number"}
    row = conn.execute("SELECT word, lemma FROM strongs WHERE strongs=?",
                       (num,)).fetchone()
    occ = occurrences_of(conn, num, module_ids)
    # The strongs roll-up's `count` is a sum over every module that indexed the
    # number, so it reads far higher than the number of marked occurrences
    # (H0430: 23,991 against a real 15,029).  Count the markers.
    total = conn.execute("SELECT count(*) FROM marker WHERE kind='strongs' "
                         "AND value=?", (num,)).fetchone()[0]
    by_book = [(r["book"], r["n"]) for r in conn.execute(
        "SELECT u.book, count(*) AS n FROM marker m JOIN unit u "
        "ON u.module_id=m.module_id AND u.key=m.unit_key "
        "WHERE m.kind='strongs' AND m.value=? AND u.book<>'' "
        "GROUP BY u.book ORDER BY n DESC", (num,))]
    return {
        "ok": True, "number": num,
        "word": (row["word"] if row else "") or "",
        # Several renderers read these keys; without them the root label fell
        # back to the bare number and clause participants were always empty.
        "headword": (row["word"] if row else "") or num,
        "morph_codes": [],
        "lemma": (row["lemma"] if row else "") or "",
        "total": total,
        "entries": lexicon_entries_for(conn, num),
        "occurrences": occ[:300],
        "by_book": by_book,
    }


# --------------------------------------------------------------------------
# FactBook guide
# --------------------------------------------------------------------------

#: A lens is a different question asked of the same fact-book entries.  These
#: lenses re-filter the entries; they are the honest local equivalents, computed
#: from what is installed.
_LENSES = {
    "": {"label": "All entries", "note": "Every fact-book entry, sorted by kind."},
    "theological": {"label": "Theological lens",
                    "note": "Systematic theology: what the entry means for doctrine."},
    "counseling": {"label": "Counseling lens",
                   "note": "Pastoral care: what the entry means for people."},
}

#: Keywords that mark an entry as theologically weighted, matched against the
#: entry's own text.  A lens does not invent content -- it surfaces what the
#: installed books already say, under a different heading.
_THEOLOGY_HINTS = (
    "god", "christ", "holy spirit", "trinity", "salvation", "grace", "faith",
    "sin", "redemption", "covenant", "kingdom", "church", "resurrection",
    "atonement", "justification", "sanctification", "propitiation", "elect",
    "gospel", "heaven", "hell", "judgment", "mercy", "righteousness",
)

#: Keywords that mark an entry as pastoral-counseling weighted.
_COUNSELING_HINTS = (
    "grief", "fear", "anxiety", "anger", "forgive", "marriage", "parent",
    "temptation", "suffer", "death", "hope", "lonely", "depress", "peace",
    "comfort", "healing", "loss", "pain", "struggle", "worry", "trust",
)


def _lens_score(text: str, hints: tuple[str, ...]) -> int:
    """How many of a lens's keywords appear in the text, as a relevance score."""
    low = (text or "").lower()
    return sum(1 for h in hints if h in low)


#: The primary Topics sections come from FactBook modules only.  Headword
#: reference works (Smith's, Easton, Webster, TIPNR, the Strong's lexicons) are
#: deliberately a separate "Dictionary" section added by `_extra_sections`,
#: and are also available in the definition popup and the dictionary pane.
#: An older `_FACT_ROLES` table claimed People/Places searched Dictionaries but
#: was never read; it was removed rather than left contradicting the code.

_NAME_MEANING_HINTS = ("Hitchcock", "Names", "Proper Names")


#: Filmed as fact books because the taxonomy says so, but containing no biblical
#: fact at all.  Naming them in "searched these books" would be a lie about
#: what was searched, and they can only ever match on an English word.
_NOT_FACT_BOOKS = ("mapping lexicon", "klingon")


def _is_a_fact_book(name: str) -> bool:
    low = (name or "").lower()
    return not any(x in low for x in _NOT_FACT_BOOKS)


def _is_names_book(name: str) -> bool:
    low = (name or "").lower()
    return "hitchcock" in low or "names" in low


def fact_guide(query: str, *, per_section: int = 8, lens: str = "",
               modules: dict | None = None) -> dict:
    """Every fact-book entry about one term, sorted into what kind it is.

    The Topic guide gathers everything sharing a heading.  This one asks the
    question a fact book is built to answer: *what kind of thing is this, and
    what does each reference work say about it?*

    Three sections, and no more, because three is what can be established from
    the data without guessing:

    **Name** -- a names-and-meanings book.  Unambiguous: Hitchcock says only
    what a name meant, and it is the only book installed that does.

    **Place** -- established by the *geocoded* data rather than by reading the
    article.  A keyword heuristic on the prose put Aaron under "Places",
    because his name means "mountain of strength"; whether a name is in the
    gazetteer is a fact, and whether a paragraph uses the word "valley" is not.

    **Article** -- everything else, in full, because deciding that an entry is
    about a person rather than a topic from a paragraph is not something to
    assert to a reader.

    Each entry appears in exactly one section.  Sorting them twice, as an
    earlier version did, told the reader the same article twice.

    A **lens** (theological or counseling) re-ranks the Article section by
    relevance to that question, so the same entries appear in a different
    order and the most pertinent are read first.  It does not invent content.
    """
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "no term"}
    conn = db.connect()
    all_mods = dict(modules) if modules is not None else {
        m.id: m for m in library.list_all()}
    mods = [m for m in all_mods.values()
            if m.type == "FactBook" and _is_a_fact_book(m.name)]
    mods.sort(key=lambda m: (_priority_rank(m), m.name or ""))
    if not mods:
        return {"ok": False, "error":
                "No fact book is installed. The Store has Nave, Hitchcock, "
                "Torrey, Thompson and the Condensed Biblical Cyclopedia."}

    lens = (lens or "").strip()
    lens_label = ""
    lens_note = ""
    if lens in _LENSES:
        lens_label = _LENSES[lens]["label"]
        lens_note = _LENSES[lens]["note"]

    ql = q.lower()
    ph = ",".join("?" * len(mods))
    names = [m.id for m in mods]
    by_id = {m.id: m for m in mods}

    # Fact-book heads are stored in each book's own case -- Hitchcock and Nave
    # are all caps, Torrey title case -- so match both the given and the
    # capitalised form.  "aaron" has to find AARON.
    like, like_cap = f"%{q}%", f"%{q.capitalize()}%"
    rows = conn.execute(
        f"SELECT module_id, key, title, text FROM unit WHERE module_id IN ({ph}) "
        f"AND (title LIKE ? OR title LIKE ? OR key LIKE ? OR key LIKE ?)",
        [*names, like, like_cap, like, like_cap]).fetchall()

    def rank(r):
        t = (r["title"] or "").lower().strip()
        k = (r["key"] or "").lower().strip()
        if t == ql or k == ql:
            return 0
        if t.startswith(ql) or k.startswith(ql):
            return 1
        return 2 if (t.startswith(ql + " ") or t.startswith(ql + ",")) else 3

    prio = {m.id: _priority_rank(m) for m in mods}
    ordered = sorted(rows, key=lambda r: (
        rank(r), prio.get(r["module_id"], 0), -len(r["text"] or "")))

    def item(r):
        m = by_id[r["module_id"]]
        return {"module_id": m.id, "module": m.name, "key": r["key"],
                "title": r["title"] or r["key"],
                "text": _summary_text(r["text"], 2400), "length": len(r["text"] or "")}

    sections: list[dict] = []

    def add(kind, label, items, note="", geo=None):
        if not items and not geo:
            return
        entry = {"kind": kind, "label": label, "note": note, "items": items}
        if geo:
            entry["geo"] = geo
        sections.append(entry)

    geo = _geo_for(conn, ql)

    # Gather the non-fact-book sections once.  Dictionary is placed directly
    # after Name: a one-line name meaning is the quick answer, and the full
    # headword article from Smith's/Easton/Webster is the substance that follows.
    extra = _extra_sections(conn, all_mods, q, per_section, places=False)
    name_rows = [r for r in ordered if _is_names_book(by_id[r["module_id"]].name)]
    add("name", "Name",
        [item(r) for r in name_rows[:per_section]],
        note="What the name meant to those who heard it")
    for sec in extra:
        if sec["kind"] == "dictionary":
            add(sec["kind"], sec["label"], sec["items"], note=sec.get("note", ""))

    # A place is established by the gazetteer, not by reading the prose.  A
    # keyword heuristic on the article put Aaron under "Places", because his
    # name means "mountain of strength" and the word appeared there.  Whether
    # the gazetteer knows the name is a fact; whether a paragraph contains the
    # word "valley" is not.  Articles are attached to the Place section only when
    # their title is a place the gazetteer confirms.
    gazetteer = {g["name"].lower() for g in geo}
    claimed_names = {(x["module_id"], x["key"]) for x in name_rows}
    place_rows = [r for r in ordered
                  if (r["module_id"], r["key"]) not in claimed_names
                  and (r["title"] or "").strip().lower() in gazetteer]
    add("place", "Place",
        [item(r) for r in place_rows[:per_section]], geo=geo,
        note=("Where it is, with the passages that name it" if geo
              else "Not in the gazetteer, so treated as an article"))

    claimed = {(r["module_id"], r["key"]) for r in name_rows}
    claimed |= {(r["module_id"], r["key"]) for r in place_rows}
    rest = [r for r in ordered if (r["module_id"], r["key"]) not in claimed]

    # A lens re-ranks the Article section.  The entries are the same; the order
    # and the heading change, so the most pertinent for that question are read
    # first.  This is a re-ranking, not a filter -- nothing is hidden.
    if lens == "theological":
        rest.sort(key=lambda r: (-_lens_score(r["text"] or "", _THEOLOGY_HINTS),
                                  -len(r["text"] or "")))
    elif lens == "counseling":
        rest.sort(key=lambda r: (-_lens_score(r["text"] or "", _COUNSELING_HINTS),
                                  -len(r["text"] or "")))

    add("article", lens_label or "Article",
        [item(r) for r in rest[:per_section]],
        note=lens_note or "The full entry, with its scripture references")

    # -- the material that is not a fact-book entry.  The topic guide has
    # always shown these, and so does this: a reader who has asked about a
    # term wants the same things whichever door they came through, and a
    # reader who has to look in one place and not the other learns two shapes
    # for one question.
    #
    # The places are left out, because this guide already carries the
    # gazetteer in its own *located* list -- the same places, with their
    # coordinates and the passages that name them.
    mine = my_topics_for_term(conn, q, per_section)
    if mine:
        sections.append({
            "kind": "mytopics", "label": "My topics",
            "note": "Verses you tagged with this topic", "items": mine})
    for sec in extra:
        if sec["kind"] == "dictionary":
            continue                      # already shown right after Name
        add(sec["kind"], sec["label"], sec["items"], note=sec.get("note", ""))

    # Curated questions a reader can take to the material -- the non-AI
    # equivalent of curated topic questions.  They are templates chosen from what
    # the guide actually found, never generated from the text.
    questions = []
    if any(s.get("kind") == "name" for s in sections):
        questions += ["What does this name mean?",
                      "Who in Scripture bears this name?",
                      "What people or places are named after it?"]
    if any(s.get("kind") == "place" for s in sections):
        questions += ["Where is this place?",
                      "Which passages mention it?",
                      "What events happened there?"]
    if any(s.get("kind") == "article" for s in sections):
        questions += ["What do the fact books say about it?",
                      "Which scripture references are given?",
                      "How does it connect to other topics?"]
    if lens == "theological":
        questions.append("What does this mean for doctrine?")
    if lens == "counseling":
        questions.append("How does this help someone in need?")
    # keep order, drop duplicates
    seen_q, uniq = set(), []
    for qq in questions:
        if qq in seen_q:
            continue
        seen_q.add(qq)
        uniq.append(qq)

    return {"ok": True, "query": q, "sections": sections,
            "matched": len(ordered),
            "factbooks": sorted({m.name for m in mods}),
            "lens": lens, "questions": uniq}


def factbook_search(q: str = "", module_ids: list[str] = None,
                    limit: int = 30) -> dict:
    """Search the fact books by heading — what the Topics lens searches.

    Fact-book entries are headed by their term (Nave's groups everything
    about Aaron under one entry), so a heading search finds the entry a
    reader means, not every paragraph that happens to mention the word.  The
    rows are the same shape as the flat search results the frontend renders,
    and clicking one opens the Topics guide for that entry's own term.
    """
    q = (q or "").strip()
    if not q:
        return {"ok": False, "error": "no query given"}
    conn = db.connect()
    # The Topics search covers headword reference works as well as fact books:
    # looking up "AARON" should find Smith's and Easton, not only Nave.
    mods = [m for m in library.list_all()
            if (m.type == "FactBook" and _is_a_fact_book(m.name))
            or m.type in ("Dictionary", "Lexicon")]
    if module_ids:
        keep = set(module_ids)
        mods = [m for m in mods if m.id in keep]
    if not mods:
        return {"ok": False,
                "error": "No fact book is installed. The Store has Nave, "
                         "Hitchcock, Torrey, Thompson and the Condensed "
                         "Biblical Cyclopedia."}
    names = [m.id for m in mods]
    ph = ",".join("?" * len(names))
    # Headings are stored in each book's own case -- Hitchcock and Nave are
    # all caps, Torrey title case -- so match the given and the capitalised
    # form.  "aaron" has to find AARON.
    esc = lambda t: t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like, like_cap = "%" + esc(q) + "%", "%" + esc(q.capitalize()) + "%"
    where = (f"module_id IN ({ph}) AND (title LIKE ? ESCAPE '\\' "
             "OR title LIKE ? ESCAPE '\\' OR key LIKE ? ESCAPE '\\' "
             "OR key LIKE ? ESCAPE '\\')")
    args = [*names, like, like_cap, like, like_cap]
    total = conn.execute(
        f"SELECT count(*) c FROM unit WHERE {where}", args).fetchone()["c"]
    rows = conn.execute(
        f"SELECT module_id, key, title, text FROM unit WHERE {where} "
        "ORDER BY length(text) DESC LIMIT ?", args + [max(1, limit) * 4]).fetchall()

    def rank(r):
        return 3

    by_id = {m.id: m for m in mods}
    ordered = sorted(rows, key=lambda r: (rank(r), -len(r["text"] or "")))[:limit]
    results = []
    for r in ordered:
        m = by_id[r["module_id"]]
        results.append({
            "module_id": m.id,
            "module": m.name,
            "key": r["key"],
            "title": r["title"] or r["key"],
            "text": _chunk(r["text"] or "", 220),
            "length": len(r["text"] or ""),
        })
    return {"ok": True, "query": q, "results": results,
            "count": total, "returned": len(results),
            "more": total > len(results),
            "notice": "" if results else "No fact-book heading matches that term."}


def _geo_for(conn, ql: str) -> list[dict]:
    """Geocoded places matching a term, if any geography is installed."""
    rows = conn.execute(
        "SELECT u.module_id, u.key, u.ref_label, u.text FROM unit u "
        "JOIN module m ON m.id=u.module_id "
        "WHERE m.source='openbible-geo' AND m.installed_at>0 "
        "AND lower(u.key) LIKE ? LIMIT 6",
        (f"%{ql}%",)).fetchall()
    out = []
    for r in rows:
        text = r["text"] or ""
        # The stored text begins with the place name, so `Coordinates:` is not
        # at position 0 -- which is why every coordinate came out blank.
        coords, _, refs = text.partition("Referenced at:")
        coords = coords.split("Coordinates:", 1)[-1].strip()
        lat, _, lon = coords.partition(",")
        refs = refs.strip()
        out.append({"name": r["ref_label"] or r["key"], "key": r["key"],
                    "lat": lat.strip(), "lon": lon.strip(), "refs": refs,
                    "module_id": r["module_id"]})
    return out


# --------------------------------------------------------------------------
# Factbook tags: a definition on the word itself
# --------------------------------------------------------------------------
# Proper names across the installed resources carry a definition, so hovering a
# name in a commentary gives its meaning without leaving the page.  That is the
# single most recognisable thing about the Fact guide, and it needs no new
# material -- only an index of the fact-book heads we already have.

_TAG_CACHE: dict[str, dict] | None = None
#: Sources worth tagging from, in preference order.  Hitchcock is first because a
#: name's meaning is the thing you want on hover; Nave is included because its
#: one-line articles are good glosses too.
_TAG_SOURCES = ("Hitchcock", "Bible Names")


def tag_index(refresh: bool = False) -> dict[str, dict]:
    """word -> {gloss, source, module_id, key}, built once per process.

    Capitalisation is normalised, so "Moses" and "moses" find the same entry.
    Only sources named in `_TAG_SOURCES` are indexed: tagging from every fact
    book would put Nave's paragraph-length articles in a tooltip, which is not a
    tooltip.
    """
    global _TAG_CACHE
    if _TAG_CACHE is not None and not refresh:
        return _TAG_CACHE
    conn = db.connect()
    mods = [m for m in library.list_all()
            if m.type == "FactBook" and _is_a_fact_book(m.name)]
    wanted = [m for m in mods if any(h in m.name for h in _TAG_SOURCES)]
    index: dict[str, dict] = {}
    for m in wanted:
        for r in conn.execute(
                "SELECT key, title, text FROM unit WHERE module_id=? "
                "AND length(coalesce(text,''))>0", (m.id,)):
            w = _norm(r["title"] or r["key"] or "")
            if len(w) < 3 or w in index:
                continue
            gloss = " ".join((r["text"] or "").split())
            index[w] = {"gloss": gloss[:220], "source": m.name,
                        "module_id": m.id, "key": r["key"]}
    # TIPNR proper-name records (installed from STEPBible-Data) carry a name,
    # a short description and a long article per person/place/thing, so they
    # are a natural fact-book source for proper-noun tooltips too.
    for m in library.list_all():
        if "TIPNR" not in (m.name or "") and "Proper Names" not in (m.name or ""):
            continue
        if m.type not in ("Dictionary", "FactBook"):
            continue
        for r in conn.execute(
                "SELECT key, text FROM unit WHERE module_id=? "
                "AND length(coalesce(text,''))>0", (m.id,)):
            parsed = _parse_tipnr_record(r["text"] or "")
            if not parsed:
                continue
            w = _norm(parsed["name"])
            if len(w) < 3 or w in index:
                continue
            gloss = parsed["gloss"] or parsed["article"]
            if not gloss:
                continue
            index[w] = {"gloss": gloss[:220], "source": m.name,
                        "module_id": m.id, "key": r["key"]}
    _TAG_CACHE = index
    return index


def fact_tags(text: str, *, limit: int = 40) -> list[dict]:
    """The words in a piece of text that the fact books have something to say about.

    Proper nouns only.  Tagging every word that happens to match a head would put
    a tooltip on "the" and on every form of a common noun, which trains a reader
    to ignore the feature.
    """
    idx = tag_index()
    if not idx or not text:
        return []
    seen: dict[str, dict] = {}
    for tok in re.finditer(r"[A-Z][a-zA-Z'’-]{2,}", text or ""):
        w = _norm(tok.group(0))
        hit = idx.get(w)
        if hit and w not in seen:
            seen[w] = {"word": tok.group(0), **hit}
        if len(seen) >= limit:
            break
    return list(seen.values())


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _parse_tipnr_record(text: str) -> dict | None:
    """Pull a name and a short description out of one TIPNR record.

    TIPNR records begin with a header line whose first field is
    ``Name@Ref=Strong`` and carry ``@Briefest=``, ``@Brief=``, ``@Short=`` and
    ``@Article=`` lines with progressively longer descriptions.  Returns None
    when the record has no usable name.
    """
    if not text:
        return None
    lines = text.splitlines()
    if not lines:
        return None
    data_line = ""
    for ln in lines:
        if "@" in ln and "\t" in ln:
            data_line = ln.strip()
            break
    if not data_line:
        for ln in lines:
            if "@" in ln:
                data_line = ln.strip()
                break
    if not data_line:
        return None
    name_field = data_line.split("\t")[0]
    name = name_field.split("@")[0].strip()
    if not name or len(name) < 2 or name.startswith("$"):
        return None
    briefest = brief = short = article = ""
    for ln in lines:
        ln = ln.strip()
        if ln.startswith("@Briefest="):
            briefest = ln[len("@Briefest="):].strip()
        elif ln.startswith("@Brief="):
            brief = ln[len("@Brief="):].strip()
        elif ln.startswith("@Short="):
            short = ln[len("@Short="):].strip()
        elif ln.startswith("@Article="):
            article = ln[len("@Article="):].strip()
    gloss = briefest or brief or short
    return {"name": name, "gloss": gloss, "article": article}


# --------------------------------------------------------------------------
# Passage guide
# --------------------------------------------------------------------------

def _narrative_only(text: str) -> str:
    """Drop section headings, leaving the prose they label.

    A heading names a place as often as the prose does, and it says nothing
    about where the passage happens: the Berean Standard heads Matthew 2:12
    "The Flight to Egypt", and matching on the whole unit reported Egypt -- and
    with it the Brook of Egypt and Syene -- for a passage in which the Magi
    never leave Judea.  The Magi did not go to Egypt; a heading saying the
    family later did is not the same claim.

    The test is deliberately narrow, because over-eagerly deleting prose loses
    real places: a line has to be short, end without sentence punctuation, and
    be capitalised like a title.  Ordinary narrative fails the third test.
    """
    kept = []
    for line in (text or "").split("\n"):
        t = line.strip()
        if not t:
            continue
        if t[-1] not in ".!?;," and len(t) <= 80:
            words = [w for w in re.findall(r"[A-Za-z][A-Za-z'\u2019-]*", t)]
            if len(words) >= 2 and sum(w[0].isupper() for w in words) >= len(words) - 1:
                continue
        kept.append(t)
    return "\n".join(kept)


def _places_named(text: str, *, limit: int = 14) -> list[dict]:
    """Gazetteer places this text actually names.

    Matched on the alternative names too, and that matters more than it sounds:
    "Egypt" is an alternative name of Syene and of the Brook of Egypt, not a
    gazetteer entry in its own right, so matching on `name` alone found no
    places at all in the whole book of Exodus.

    Longest name wins, so "Brook of Egypt" is not also reported as a bare
    "Egypt" match from the same entry.
    """
    low = (text or "").lower()
    if not low:
        return []
    out = []
    for p in _places():
        cands = [(p.get("name") or "").strip()]
        alt = p.get("alt_names")
        if isinstance(alt, str):
            cands += [x.strip() for x in alt.replace("[", "").replace("]", "")
                      .replace("'", "").split(",")]
        elif isinstance(alt, (list, tuple)):
            cands += [str(x).strip() for x in alt]
        best = ""
        for c in cands:
            if len(c) > 3 and c.lower() in low and len(c) > len(best):
                best = c
        if best:
            out.append({"name": p.get("name") or best, "matched": best,
                        "lat": p.get("lat"), "lon": p.get("lon"),
                        "comment": _chunk(p.get("comment", ""), 200),
                        "passages": p.get("passages")})
    # Several entries share one alternative name -- "Egypt" belongs to both
    # Syene and the Brook of Egypt, and "River" to both the Nile and the
    # Euphrates -- so matching on alt_names alone reports the same word twice.
    # Dedupe on what was matched, keeping the longest match, which is the most
    # specific one and so the least likely to be a coincidence.
    out.sort(key=lambda x: -len(x["matched"]))
    seen, kept = set(), []
    for x in out:
        k = x["matched"].lower()
        if k in seen:
            continue
        seen.add(k)
        kept.append(x)
    return kept[:limit]

def passage_guide(ref: str, *, span: int = 3) -> dict:
    """Everything known about a passage, gathered in one place.

    Given a passage, hand back the text, the people named in it, the places, the
    commentary on it, its cross-references and the fact-book entries it touches.
    Every part is computed from material already installed -- nothing is fetched,
    and nothing is guessed about.

    People come from the genealogy graph, which was built by reading the text
    rather than from a dataset, so a name it does not know is simply absent.
    That is stated in the section note rather than papered over.
    """
    rr = canon.parse_ref(ref)
    if rr is None:
        return {"ok": False, "error": f"cannot read {ref!r} as a reference"}
    verses = list(rr.refs())[:12]
    if not verses:
        return {"ok": False, "error": "no verse in that reference"}
    conn = db.connect()
    label = (verses[0].label if len(verses) == 1
             else f"{verses[0].label}\u2013{verses[-1].label}")

    # -- the text, from one good translation and one that spells things out
    texts = []
    prefer = ("open-bibles-eng-kjv", "ebible-eng-web", "ebicle-eng-web",
              "open-bibles-eng-bsb", "ebible-eng-kjv", "crosswire-kjv",
              "ebible-eng-asv")
    have = [m for m in library.list_all()
            if m.type == "Bible" and m.installed_at and m.lang == "eng"]
    preferred = {mid: i for i, mid in enumerate(prefer)}
    have.sort(key=lambda m: (preferred.get(m.id, len(prefer)),
                             m.name or m.id))
    for m in have:
        parts = []
        for v in verses:
            row = conn.execute(
                "SELECT text FROM unit WHERE module_id=? AND book=? AND chapter=? "
                "AND verse=? LIMIT 1",
                (m.id, v.book, v.chapter, v.verse)).fetchone()
            if row and (row["text"] or "").strip():
                parts.append(_chunk(row["text"], 400))
        if parts:
            texts.append({"module_id": m.id, "module": m.name,
                          "text": " ".join(parts)})
        if len(texts) >= 2:
            break

    # -- the people the genealogy graph can attest for this passage
    people = _people_in(conn, verses)

    # -- places named in the passage, from the gazetteer
    body = " ".join(t["text"] for t in texts)
    places = _places_named(_narrative_only(body))

    # -- commentary on the passage
    comments = []
    for m in [x for x in library.list_all() if x.type == "Commentary"][:40]:
        for v in verses[:3]:
            row = conn.execute(
                "SELECT key, ref_label, title, text FROM unit WHERE module_id=? "
                "AND book=? AND chapter=? AND verse=? LIMIT 1",
                (m.id, v.book, v.chapter, v.verse)).fetchone()
            if row and (row["text"] or "").strip():
                comments.append({"module_id": m.id, "module": m.name,
                                 "key": row["key"],
                                 "title": row["title"] or row["ref_label"],
                                 "text": _chunk(row["text"], 900)})
                break
        if len(comments) >= 8:
            break

    # -- cross-references, from the resources that carry them
    xrefs = []
    for v in verses:
        k = canon.Ref(v.book, v.chapter, v.verse).osis_id()
        rows = conn.execute(
            "SELECT DISTINCT to_key FROM xref WHERE from_key=? LIMIT 20",
            (k,)).fetchall()
        for r in rows:
            t = r["to_key"]
            if t and t not in {x["key"] for x in xrefs}:
                xrefs.append({"key": t, "label": t.replace(".", " ", 1)})
        if len(xrefs) >= 20:
            break

    # -- names in the passage, with what the fact books say about them.
    # These and "people" are one section, not two: both come from the same name
    # index, and splitting them printed a bare list of names with no meanings
    # beside a list of names with meanings, which is a distinction without a
    # difference.
    named = _fact_terms(body)

    # -- sermons and Bible-study notes that name this passage
    markers = {"sermons": [], "studies": []}
    try:
        from . import docs as _docs
        markers = _docs.sermon_markers(ref) or markers
    except Exception:  # noqa: BLE001
        pass
    sermons = markers.get("sermons") or []
    studies = markers.get("studies") or []

    return {
        "ok": True, "ref": label, "verses": len(verses),
        "texts": texts, "people": people, "named": named, "places": places,
        "commentary": comments, "xrefs": xrefs[:20],
        "sermons": sermons, "studies": studies,
        "sections": {
            "text": bool(texts), "people": bool(named or people),
            "places": bool(places), "commentary": bool(comments),
            "xrefs": bool(xrefs),
            "sermons": bool(sermons or studies),
        },
    }


# ===========================================================================
# Bible Word Study — lemma, translation, senses, example uses
# ===========================================================================

def bible_word_study(num: str = "", word: str = "", *,
                     module_id: str = "", limit: int = 30) -> dict:
    """Everything known about one word, collated from the installed library.

    For original-language words it returns Lemma, Translation, Root, Senses,
    Example Uses, Clause Participants,
    and Textual Searches.  For English words it returns Topic, Hebrew Words,
    Greek Words, Senses, Phrases, and Textual Searches.

    The word can be supplied as a Strong's number (`num`) or a bare surface
    form (`word`).  When neither is given the call is a no-op.
    """
    conn = db.connect()
    num = canon.normalise_strongs(num or "")

    # Resolve the Strong's number from a bare word if needed.
    if not num and word:
        for r in conn.execute(
                "SELECT m.value FROM marker m JOIN module md ON md.id=m.module_id "
                "WHERE m.kind='strongs' AND m.surface=? AND m.module_id=? "
                "ORDER BY m.pos LIMIT 1",
                (word, module_id or "")):
            num = canon.normalise_strongs(r["value"] or "")
            break

    if not num:
        return {"ok": False, "error": "no word or Strong's number"}

    wb = word_bundle(num)
    if not wb.get("ok"):
        return {"ok": False, "error": wb.get("error", "no such word")}

    # ---- Lemma section: lexicon articles for this Strong's number.
    lex = lexicon_entries_for(conn, num, limit=limit)

    # ---- Translation: how this word is rendered in each tagged Bible.
    mods = [m for m in library.list_all()
            if m.is_bible and m.installed_at and m.lang == "eng"]
    translations = []
    for m in mods[:6]:
        occs = occurrences_of(conn, num, module_ids=[m.id], limit=20)
        if occs:
            surfaces = {}
            for o in occs:
                s = o["surface"] or ""
                surfaces[s] = surfaces.get(s, 0) + 1
            translations.append({
                "module_id": m.id, "module": m.name,
                "renderings": sorted(surfaces.items(), key=lambda x: -x[1])[:6],
                "count": len(occs),
            })

    # ---- Root: linked lemmas (same root family).
    root = {"lemma": wb.get("headword", num), "related": []}
    for r in wb.get("by_book", [])[:6]:
        root["related"].append({"book": r[0], "count": r[1]})

    # ---- Senses: glosses from installed lexicons.
    gloss = _gloss_for(conn, num)
    senses = [{"sense": gloss, "definition": gloss}] if gloss else []

    # ---- Example Uses: where the word occurs, verse by verse.
    occs = occurrences_of(conn, num, limit=limit * 3)
    examples = []
    for o in occs[:limit]:
        examples.append({
            "ref": (o["ref"] and o["ref"]["label"]) or o["key"],
            "surface": o["surface"] or "",
            "module_id": o["module_id"],
        })

    # ---- Clause Participants: subjects/objects for verbs (morph-based).
    participants = []
    if wb.get("morph_codes"):
        participants = wb["morph_codes"][:6]

    # ---- Textual Searches: where the word occurs in each top Bible.
    textual = []
    for m in mods[:5]:
        hits = occurrences_of(conn, num, module_ids=[m.id], limit=10)
        if hits:
            textual.append({
                "module_id": m.id, "module": m.name,
                "count": len(hits),
                "sample": [{"ref": (h["ref"] and h["ref"]["label"]) or h["key"],
                            "surface": h["surface"] or ""} for h in hits[:4]],
            })

    return {
        "ok": True, "num": num, "headword": wb.get("headword", num),
        "lemma": wb.get("lemma", ""), "gloss": gloss,
        "sections": {
            "lemma": [{"module_id": x["module_id"], "module": x["module"],
                       "text": _chunk(x["text"], 600)} for x in lex],
            "translation": translations,
            "root": root,
            "senses": senses,
            "example_uses": examples,
            "clause_participants": participants,
            "textual_searches": textual,
        },
    }


# ===========================================================================
# Exegetical Guide — textual variants, grammars, word-by-word
# ===========================================================================

def exegetical_guide(ref: str, *, span: int = 3) -> dict:
    """Detailed exegesis of a passage: variants, grammar, word-by-word analysis.

    It collects Textual Variants, Grammars, Grammatical Constructions,
    Visualizations, Word by Word, Important Words, Commentaries,
    and Ancient Literature.
    """
    rr = canon.parse_ref(ref)
    if rr is None:
        return {"ok": False, "error": f"cannot read {ref!r} as a reference"}
    verses = list(rr.refs())[:12]
    if not verses:
        return {"ok": False, "error": "no verse in that reference"}
    conn = db.connect()
    label = (verses[0].label if len(verses) == 1
             else f"{verses[0].label}\u2013{verses[-1].label}")

    # ---- Word by Word: every tagged word in the passage.
    word_by_word = []
    for v in verses:
        row = conn.execute(
            "SELECT key, text, markup, ref_label FROM unit WHERE module_id=? "
            "AND book=? AND chapter=? AND verse=? LIMIT 1",
            ("openscriptures-morphhb", v.book, v.chapter, v.verse)).fetchone()
        if not row:
            # Try any tagged original-language module.
            tagged = [m.id for m in library.list_all()
                      if m.installed_at and (m.type in ("OriginalLanguage", "Bible")
                                             and m.has_morph)]
            if tagged:
                ph = ",".join("?" * len(tagged))
                row = conn.execute(
                    f"SELECT key, text, markup, ref_label FROM unit WHERE "
                    f"module_id IN ({ph}) AND book=? AND chapter=? AND verse=? "
                    f"LIMIT 1", [*tagged, v.book, v.chapter, v.verse]).fetchone()
        if row:
            try:
                spans = (json.loads(row["markup"] or "{}") or {}).get("s") or []
            except (json.JSONDecodeError, TypeError):
                spans = []
            text = row["text"] or ""
            words = []
            for sp in spans:
                start, ln = int(sp[0]), int(sp[1])
                form = text[start:start + ln]
                if not form.strip():
                    continue
                sn = [canon.normalise_strongs(x) for x in (sp[3] or "").split()]
                mn = [x for x in (sp[4] or "").split() if x]
                words.append({
                    "form": form,
                    "strongs": [x for x in sn if x],
                    "morph": mn,
                    "gloss": "; ".join(_gloss_for(conn, x) for x in sn
                                       if _gloss_for(conn, x)),
                })
            word_by_word.append({
                "ref": row["ref_label"] or f"{v.book} {v.chapter}:{v.verse}",
                "words": words,
            })

    # ---- Commentaries on the passage.
    comments = []
    for m in [x for x in library.list_all() if x.type == "Commentary"][:40]:
        for v in verses[:3]:
            row = conn.execute(
                "SELECT key, ref_label, title, text FROM unit WHERE module_id=? "
                "AND book=? AND chapter=? AND verse=? LIMIT 1",
                (m.id, v.book, v.chapter, v.verse)).fetchone()
            if row and (row["text"] or "").strip():
                comments.append({"module_id": m.id, "module": m.name,
                                 "key": row["key"],
                                 "title": row["title"] or row["ref_label"],
                                 "text": _chunk(row["text"], 900)})
                break
        if len(comments) >= 8:
            break

    # ---- Grammars: sections mentioning this passage's grammatical features.
    grammars = []
    gm_mods = [m.id for m in library.list_all()
               if m.installed_at and m.type == "Grammar"]
    if gm_mods:
        ph = ",".join("?" * len(gm_mods))
        rows = conn.execute(
            f"SELECT module_id, key, title, text FROM unit WHERE module_id IN ({ph}) "
            f"LIMIT 12", gm_mods).fetchall()
        mods = {m.id: m for m in library.list_all() if m.id in gm_mods}
        for r in rows:
            m = mods.get(r["module_id"])
            if m:
                grammars.append({"module_id": m.id, "module": m.name,
                                 "key": r["key"], "title": r["title"],
                                 "text": _chunk(r["text"], 500)})

    # ---- Visualizations: syntax trees / diagrams for this passage.
    visualizations = []
    try:
        from . import syntax as _syn
        for v in verses[:3]:
            r = _syn.syntax_for(ref=f"{v.book} {v.chapter}:{v.verse}")
            if r.get("ok"):
                visualizations.append({"ref": r.get("ref"), "tree": r.get("tree")})
    except Exception:
        pass

    # ---- Important Words: high-frequency commentary words in the passage.
    # Derived from commentary text: words that appear across multiple commentaries.
    important = []
    try:
        comment_text = " ".join(c["text"] for c in comments)
        words = {}
        for w in re.findall(r"[A-Za-z']{4,}", comment_text.lower()):
            words[w] = words.get(w, 0) + 1
        important = sorted(words.items(), key=lambda x: -x[1])[:10]
    except Exception:
        pass

    return {
        "ok": True, "ref": label, "verses": len(verses),
        "sections": {
            "word_by_word": word_by_word,
            "commentaries": comments,
            "grammars": grammars,
            "visualizations": visualizations,
            "important_words": [{"word": w, "count": n} for w, n in important],
        },
    }


_GEN_REF_CACHE: dict = {}


def _people_in(conn, verses) -> list[dict]:
    """People whose recorded references fall inside this passage.

    The genealogy is built and held in memory by `gbible.genealogy`, not kept in
    a table -- an early version of this queried a `genealogy_person` table that
    does not exist.  Each person carries the list of verses that named them, so
    the test is simply "does any of their verses fall in the range".
    """
    try:
        from . import genealogy as _gen
    except Exception:
        return []
    try:
        g = _gen.build()
    except Exception:
        return []
    if not g.get("ok"):
        return []

    # Genealogy refs keep their module's key format ("Gen.4.18", "1Chr.22.17").
    # Parse them once per distinct string, then use the shared ref matcher so
    # whole-book and whole-chapter references are honoured.
    from . import refmatch
    targets = [refmatch.milestones(f"{v.book} {v.chapter}:{v.verse}")
               for v in verses]
    targets = [t for t in targets if t]

    def in_passage(ref):
        got = _GEN_REF_CACHE.get(ref)
        if got is None:
            got = refmatch.milestones(ref)
            _GEN_REF_CACHE[ref] = got
        return any(refmatch.intersects([got], [t]) for t in targets)

    out = []
    for name, p in (g.get("people") or {}).items():
        hits = [r for r in p.get("refs", []) if in_passage(r)]
        if hits:
            out.append({"name": name, "refs": hits[:6],
                        "father": p.get("father") or "",
                        "mentions": len(p.get("refs", []))})
    out.sort(key=lambda x: (-len(x["refs"]), x["name"]))
    return out[:20]


def _fact_terms(body: str, *, limit: int = 8) -> list[dict]:
    """The fact books' short glosses for names in the passage."""
    idx = tag_index()
    out, seen = [], set()
    for tok in re.finditer(r"[A-Z][a-zA-Z'’-]{2,}", body or ""):
        w = _norm(tok.group(0))
        hit = idx.get(w)
        if hit and w not in seen:
            seen.add(w)
            out.append({"word": tok.group(0), **hit})
        if len(out) >= limit:
            break
    return out


def bible_browser(conn) -> dict:
    """A searchable index of Bible entities: places (gazetteer) and the
    headwords of installed fact books.

    Returns places with their passages and coordinates, and fact-book entries
    with their source module.  Classification into person/place/thing is left to
    the reader: the fact book itself says which is which, and re-deriving it
    here would be a guess.
    """
    import json as _j
    # Places from the gazetteer.
    places = []
    try:
        from . import maps as _maps
        for p in _maps.places("", limit=100000):
            places.append({
                "kind": "place",
                "name": p.get("name") or "",
                "alt": p.get("alt_names") or [],
                "passages": p.get("passages") or [],
                "lat": p.get("lat"),
                "lon": p.get("lon"),
            })
    except Exception:  # noqa: BLE001
        places = []
    # Fact-book headwords.
    entries = []
    seen = set()
    rows = conn.execute(
        "SELECT DISTINCT u.key, m.id AS module_id, m.name AS module_name "
        "FROM unit u JOIN module m ON m.id=u.module_id "
        "WHERE m.type IN ('FactBook','Dictionary') AND m.installed_at>0 "
        "ORDER BY u.key").fetchall()
    # Simple person/thing classification by name patterns and module hints.
    PERSON_HINTS = ("son of", "daughter of", "father of", "mother of", "husband of",
                    "wife of", "brother of", "sister of", "king of", "queen of",
                    "prophet", "priest", "apostle", "disciple", "judge", "apostle",
                    "servant of", "man of", "woman of", "boy of", "girl of",
                    "son-in-law", "daughter-in-law", "mother-in-law", "father-in-law",
                    "brother-in-law", "sister-in-law")
    THING_HINTS = ("altar", "ark", "temple", "tabernacle", "altar", "well", "gate",
                   "wall", "city", "mountain", "valley", "river", "sea", "desert",
                   "wilderness", "garden", "throne", "sword", "shield", "tent",
                   "house", "city", "town", "village", "country", "land", "kingdom")
    for r in rows:
        key = (r["key"] or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        kl = key.lower()
        kind = "entry"
        # Heuristic: names that look like persons vs places vs things
        if any(h in kl for h in PERSON_HINTS) or kl.endswith(("-ite", "ite", "ian", "ean", "an", "ite")):
            kind = "person"
        elif any(h in kl for h in THING_HINTS) or kl.endswith(("gate", "wall", "well", "sea", "desert", "mount", "hill", "valley", "city", "town", "village", "land", "kingdom", "garden", "throne")):
            kind = "thing"
        entries.append({
            "kind": kind,
            "name": key,
            "module_id": r["module_id"],
            "module": r["module_name"] or r["module_id"],
        })
    return {"ok": True, "places": places, "entries": entries,
            "place_count": len(places), "entry_count": len(entries)}


def sense_search(conn, concept: str, *, limit: int = 80) -> dict:
    """Approximate a Bible Sense Lexicon search.

    The real thing needs sense-tagged data we do not have.  What we *do* have
    is a concordance and lexicon keyed by Strong's number, and a marker table
    saying which verses carry each number.  So a "sense" is answered as: the
    Strong's numbers whose gloss contains the concept word, and every verse that
    uses one of them.  It is an approximation, and the panel says so.
    """
    concept = (concept or "").strip().lower()
    if len(concept) < 2:
        return {"ok": False, "error": "type a concept (e.g. 'love', 'covenant')"}
    # Candidate Strong's numbers: those whose concordance/lexicon gloss
    # contains the concept, plus those whose roll-up surface word contains it.
    cands: list[str] = []
    seen = set()
    rows = conn.execute(
        "SELECT DISTINCT u.key FROM unit u JOIN module m ON m.id=u.module_id "
        "WHERE m.type IN ('Concordance','Lexicon','Dictionary') "
        "AND m.installed_at>0 AND lower(u.text) LIKE ?", ('%' + concept + '%',)).fetchall()
    for r in rows:
        k = (r["key"] or "").strip()
        if not k or k in seen:
            continue
        # Only Strong's-shaped keys count as candidates.
        if not (k.startswith("G") or k.startswith("H")) or not k[1:].isdigit():
            continue
        seen.add(k)
        cands.append(k)
    # Surface-word fallback.
    for r in conn.execute(
            "SELECT strongs FROM strongs WHERE lower(word) LIKE ?",
            ('%' + concept + '%',)).fetchall():
        k = r["strongs"]
        if k not in seen:
            seen.add(k)
            cands.append(k)
    cands = cands[:25]
    if not cands:
        return {"ok": True, "concept": concept, "numbers": [], "verses": [],
                "note": "No Strong's number's gloss contains that concept."}
    # Gather verses for each candidate number, via the marker table.
    verse_keys: list[str] = []
    vseen = set()
    for num in cands:
        for r in conn.execute(
                "SELECT DISTINCT unit_key FROM marker "
                "WHERE kind='strongs' AND value=? LIMIT 40", (num,)).fetchall():
            k = r["unit_key"]
            if k in vseen:
                continue
            vseen.add(k)
            verse_keys.append(k)
            if len(verse_keys) >= limit:
                break
        if len(verse_keys) >= limit:
            break
    # Resolve keys to text.
    verses = []
    for k in verse_keys[:limit]:
        # unit_key like "John.3.16" -> need module. Use any installed Bible module.
        row = conn.execute(
            "SELECT u.ref_label, u.text, u.module_id FROM unit u "
            "JOIN module m ON m.id=u.module_id "
            "WHERE u.key=? AND m.type='Bible' AND m.installed_at>0 LIMIT 1",
            (k,)).fetchone()
        if row is None:
            # Fall back to any module carrying that key.
            row = conn.execute(
                "SELECT u.ref_label, u.text, u.module_id FROM unit u "
                "WHERE u.key=? LIMIT 1", (k,)).fetchone()
        if row is None:
            continue
        verses.append({
            "ref": row["ref_label"] or k,
            "key": k,
            "text": (row["text"] or "").strip(),
            "module_id": row["module_id"],
        })
    return {"ok": True, "concept": concept, "numbers": cands,
            "verses": verses, "count": len(verses),
            "note": "Approximation: Strong's numbers whose gloss contains the concept, "
                    "and the verses that use them. Not a true sense-tagged search."}


# ===========================================================================
# Sermon Starter Guide — sermon ideas, outlines, illustrations for a passage
# ===========================================================================

def sermon_starter(q: str = "", *, limit: int = 10) -> dict:
    """Sermon starter ideas for a topic or passage.

    Collates commentaries, cross-references, illustrations and related verses
    into starter outlines. Returns suggested titles, key verses, main points
    and application ideas.
    """
    conn = db.connect()
    q = (q or "").strip()
    if not q:
        # Return trending/popular starter topics when no query given.
        return {
            "ok": True, "q": "", "starters": _default_starters(conn, limit),
            "note": "No topic given — here are common sermon starters.",
        }

    rr = canon.parse_ref(q)
    refs = list(rr.refs())[:5] if rr else []

    # Gather commentaries on the passage(s).
    comments = []
    for v in refs:
        for m in [x for x in library.list_all() if x.type == "Commentary"][:20]:
            row = conn.execute(
                "SELECT key, ref_label, title, text FROM unit WHERE module_id=? "
                "AND book=? AND chapter=? AND verse=? LIMIT 1",
                (m.id, v.book, v.chapter, v.verse)).fetchone()
            if row and (row["text"] or "").strip():
                comments.append({
                    "module_id": m.id, "module": m.name,
                    "key": row["key"],
                    "title": row["title"] or row["ref_label"],
                    "text": _chunk(row["text"], 900)})
                break
        if len(comments) >= 8:
            break

    # Gather cross-references.
    xrefs = []
    for v in refs:
        k = canon.Ref(v.book, v.chapter, v.verse).osis_id()
        rows = conn.execute(
            "SELECT DISTINCT to_key FROM xref WHERE from_key=? LIMIT 10", (k,))
        for r in rows:
            t = r["to_key"]
            if t and t not in {x["key"] for x in xrefs}:
                xrefs.append({"key": t, "label": t.replace(".", " ", 1)})
        if len(xrefs) >= 20:
            break

    # Related verses via keyword.
    related = _related_verses(q, limit=limit)

    # Build starter outlines.
    starters = []
    title = q
    if refs:
        title = f"Sermon on {refs[0].label}"
    starters.append({
        "title": title,
        "theme": q,
        "key_verses": [{"ref": (r["ref"] if r.get("ref") else ""),
                        "text": (r.get("text") or "")[:200]} for r in related[:5]],
        "main_points": [
            f"Introduction: {q} in context",
            f"Body: The meaning of {q}",
            f"Application: Living out {q}",
        ],
        "illustrations": [c["text"][:300] for c in comments[:3]],
        "commentaries": comments[:5],
        "cross_references": xrefs[:10],
    })

    return {
        "ok": True, "q": q, "ref": (refs[0].label if refs else ""),
        "starters": starters, "count": len(starters),
    }


def _default_starters(conn: object, limit: int) -> list[dict]:
    """Common sermon starter topics when no query is given."""
    default_topics = [
        ("Faith", "Hebrews 11:1"),
        ("Love", "1 Corinthians 13:4-7"),
        ("Hope", "Romans 15:13"),
        ("Grace", "Ephesians 2:8-9"),
        ("Prayer", "Philippians 4:6-7"),
        ("Forgiveness", "Matthew 6:14-15"),
        ("Salvation", "John 3:16"),
        ("Witness", "Acts 1:8"),
    ]
    out = []
    for topic, verse in default_topics[:limit]:
        rr = canon.parse_ref(verse)
        refs = list(rr.refs())[:1] if rr else []
        verse_text = ""
        if refs:
            v = refs[0]
            row = conn.execute(
                "SELECT text FROM unit WHERE book=? AND chapter=? AND verse=? "
                "LIMIT 1", (v.book, v.chapter, v.verse)).fetchone()
            if row:
                verse_text = (row["text"] or "")[:200]
        out.append({
            "title": f"Sermon on {topic}",
            "theme": topic,
            "key_verses": [{"ref": verse, "text": verse_text}],
            "main_points": [
                f"Introduction: Understanding {topic}",
                f"Body: {topic} in Scripture",
                f"Application: Living {topic} daily",
            ],
            "illustrations": [],
            "commentaries": [],
            "cross_references": [],
        })
    return out


# ===========================================================================
# Questions & Answers — community-curated Q&A about Bible passages/topics
# ===========================================================================

def qa(q: str = "", *, limit: int = 20) -> dict:
    """Questions & Answers about Bible passages and topics.

    Searches installed commentaries, dictionaries and fact books for Q&A-style
    content (question/answer pairs, explanations, definitions).
    """
    conn = db.connect()
    q = (q or "").strip()
    if not q:
        return {"ok": True, "q": "", "questions": [], "count": 0,
                "note": "No question given."}

    # Search fact books, dictionaries and commentaries for Q&A content.
    mods = [m for m in library.list_all()
            if m.type in ("FactBook", "Dictionary", "Commentary")
            and m.installed_at]
    if not mods:
        return {"ok": False, "error":
                "No reference resources installed for Q&A."}

    names = [m.id for m in mods]
    ph = ",".join("?" * len(names))
    like = f"%{q}%"
    rows = conn.execute(
        f"SELECT module_id, key, title, text FROM unit WHERE module_id IN ({ph}) "
        f"AND (title LIKE ? OR text LIKE ? OR key LIKE ?) LIMIT ?",
        [*names, like, like, like, limit * 2]).fetchall()

    out = []
    mods_map = {m.id: m for m in mods}
    for r in rows[:limit]:
        m = mods_map.get(r["module_id"])
        out.append({
            "module_id": r["module_id"],
            "module": m.name if m else r["module_id"],
            "key": r["key"],
            "title": r["title"] or r["key"],
            "question": r["title"] or r["key"],
            "answer": _chunk(r["text"], 800),
        })

    return {"ok": True, "q": q, "questions": out, "count": len(out)}


# ===========================================================================
# Bible Sense Lexicon — word sense disambiguation
# ===========================================================================

def sense_lexicon(q: str = "", *, module_id: str = "", limit: int = 10) -> dict:
    """Word sense disambiguation: which sense of a word is used where.

    Returns senses (glosses/definitions) for a word across installed lexicons,
    with example verses showing each sense in context.
    """
    conn = db.connect()
    q = (q or "").strip()
    if not q:
        return {"ok": False, "error": "no word given"}

    # Try Strong's number first, then bare word.
    num = canon.normalise_strongs(q)
    if not num:
        # Look up the word as a surface form to find its Strong's number.
        # With no module chosen, look across all tagged modules: the UI
        # advertises "love or G26", not "G26 only".
        extra = " AND m.module_id=?" if module_id else ""
        args = [q, module_id] if module_id else [q]
        row = conn.execute(
            "SELECT m.value FROM marker m JOIN module md ON md.id=m.module_id "
            "WHERE m.kind='strongs' AND m.surface=?" + extra + " "
            "ORDER BY m.pos LIMIT 1", args).fetchone()
        if row:
            num = canon.normalise_strongs(row["value"] or "")

    if not num:
        return {"ok": False, "error": f"no Strong's number found for '{q}'"}

    wb = word_bundle(num)
    if not wb.get("ok"):
        return {"ok": False, "error": wb.get("error", "no such word")}

    # Gather glosses from installed lexicons.
    lex = lexicon_entries_for(conn, num, limit=limit)

    # Example occurrences showing the word in context.
    occs = occurrences_of(conn, num, limit=limit * 2)
    examples = []
    for o in occs[:limit]:
        examples.append({
            "ref": (o["ref"] and o["ref"]["label"]) or o["key"],
            "surface": o["surface"] or "",
            "module_id": o["module_id"],
        })

    senses = []
    for lx in lex:
        senses.append({
            "sense": lx.get("module", "") + ": " + _chunk(lx.get("text", ""), 200),
            "definition": _chunk(lx.get("text", ""), 300),
            "module": lx.get("module", ""),
        })

    return {
        "ok": True, "num": num, "word": q, "headword": wb.get("headword", num),
        "lemma": wb.get("lemma", ""),
        "senses": senses, "examples": examples,
        "count": len(senses),
    }


# ===========================================================================
# Community Tags — user-sourced tags shareable across users
# ===========================================================================

def community_tags(action: str = "", tag: str = "", module_id: str = "",
                   ref: str = "") -> dict:
    """Community-sourced tags for verses, words, and topics.

    Actions: list, add, remove, by_tag, by_module, by_ref.
    Stored in the `community_tags` table (created on first use).
    """
    conn = db.connect()
    _ensure_community_tags_table(conn)

    if action == "list":
        rows = conn.execute(
            "SELECT tag, module_id, ref, count(*) AS n "
            "FROM community_tags GROUP BY tag, module_id, ref "
            "ORDER BY n DESC LIMIT 100").fetchall()
        return {"ok": True, "action": "list", "tags": [
            {"tag": r["tag"], "module_id": r["module_id"],
             "ref": r["ref"], "count": r["n"]} for r in rows]}

    if action == "add":
        if not tag or not module_id or not ref:
            return {"ok": False, "error": "need tag, module_id and ref"}
        conn.execute(
            "INSERT OR IGNORE INTO community_tags(tag, module_id, ref, added_at) "
            "VALUES(?,?,?,?)", (tag, module_id, ref, time.time()))
        conn.commit()
        return {"ok": True, "action": "add", "tag": tag,
                "module_id": module_id, "ref": ref}

    if action == "remove":
        if not tag or not module_id or not ref:
            return {"ok": False, "error": "need tag, module_id and ref"}
        conn.execute(
            "DELETE FROM community_tags WHERE tag=? AND module_id=? AND ref=?",
            (tag, module_id, ref))
        conn.commit()
        return {"ok": True, "action": "remove"}

    if action == "by_tag":
        rows = conn.execute(
            "SELECT module_id, ref, count(*) AS n FROM community_tags "
            "WHERE tag=? GROUP BY module_id, ref ORDER BY n DESC LIMIT 50",
            (tag,)).fetchall()
        return {"ok": True, "action": "by_tag", "tag": tag,
                "results": [{"module_id": r["module_id"], "ref": r["ref"],
                             "count": r["n"]} for r in rows]}

    if action == "by_module":
        rows = conn.execute(
            "SELECT tag, ref, count(*) AS n FROM community_tags "
            "WHERE module_id=? GROUP BY tag, ref ORDER BY n DESC LIMIT 50",
            (module_id,)).fetchall()
        return {"ok": True, "action": "by_module", "module_id": module_id,
                "results": [{"tag": r["tag"], "ref": r["ref"],
                             "count": r["n"]} for r in rows]}

    if action == "by_ref":
        rows = conn.execute(
            "SELECT tag, count(*) AS n FROM community_tags "
            "WHERE ref=? GROUP BY tag ORDER BY n DESC LIMIT 50", (ref,)).fetchall()
        return {"ok": True, "action": "by_ref", "ref": ref,
                "results": [{"tag": r["tag"], "count": r["n"]} for r in rows]}

    return {"ok": False, "error": f"unknown action '{action}'"}


def _ensure_community_tags_table(conn) -> None:
    """Create the community_tags table if it doesn't exist."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS community_tags ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  tag TEXT NOT NULL,"
        "  module_id TEXT NOT NULL,"
        "  ref TEXT NOT NULL,"
        "  added_at REAL NOT NULL,"
        "  UNIQUE(tag, module_id, ref))")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_ct_tag ON community_tags(tag)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_ct_module ON community_tags(module_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_ct_ref ON community_tags(ref)")
    conn.commit()


# ===========================================================================
# Personal Books — import user's own books as personal modules
# ===========================================================================

def personal_books(action: str = "", path: str = "", book_id: str = "") -> dict:
    """Import and manage personal books (PDF, EPUB, text, etc.).

    Actions: list, import, delete, read.
    """
    if action == "list":
        return {"ok": True, "action": "list", "books": _personal_books_list()}

    if action == "import":
        if not path:
            return {"ok": False, "error": "need a file path"}
        return _import_personal_book(path)

    if action == "delete":
        if not book_id:
            return {"ok": False, "error": "need a book id"}
        return _delete_personal_book(book_id)

    if action == "read":
        if not book_id:
            return {"ok": False, "error": "need a book id"}
        return _read_personal_book(book_id)

    return {"ok": False, "error": f"unknown action '{action}'"}


def _personal_books_list() -> list[dict]:
    """List imported personal books."""
    conn = db.connect()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS personal_books ("
        "  id TEXT PRIMARY KEY,"
        "  title TEXT NOT NULL,"
        "  path TEXT NOT NULL,"
        "  format TEXT NOT NULL,"
        "  imported_at REAL NOT NULL,"
        "  unit_count INTEGER DEFAULT 0)")
    rows = conn.execute(
        "SELECT * FROM personal_books ORDER BY imported_at DESC").fetchall()
    return [dict(r) for r in rows]


def _import_personal_book(path: str) -> dict:
    """Import a personal book file (PDF, EPUB, text)."""
    import os
    import hashlib

    if not os.path.exists(path):
        return {"ok": False, "error": f"file not found: {path}"}

    book_id = "pb_" + hashlib.sha1(path.encode()).hexdigest()[:12]
    title = os.path.basename(path)
    fmt = os.path.splitext(path)[1].lstrip(".").lower()

    conn = db.connect()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS personal_books ("
        "  id TEXT PRIMARY KEY,"
        "  title TEXT NOT NULL,"
        "  path TEXT NOT NULL,"
        "  format TEXT NOT NULL,"
        "  imported_at REAL NOT NULL,"
        "  unit_count INTEGER DEFAULT 0)")
    existing = conn.execute(
        "SELECT 1 FROM personal_books WHERE id=?", (book_id,)).fetchone()
    if existing:
        return {"ok": False, "error": "book already imported"}

    # Read the file content.
    try:
        if fmt == "epub":
            text = _read_epub(path)
        elif fmt == "pdf":
            text = _read_pdf(path)
        else:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
    except Exception as e:
        return {"ok": False, "error": f"could not read file: {e}"}

    if not text.strip():
        return {"ok": False, "error": "file contains no readable text"}

    # Split into units (paragraphs/chapters).
    units = [u.strip() for u in text.split("\n\n") if u.strip()]
    if not units:
        units = [text.strip()]

    now = time.time()
    conn.execute(
        "INSERT INTO personal_books(id, title, path, format, imported_at, unit_count) "
        "VALUES(?,?,?,?,?,?)",
        (book_id, title, path, fmt, now, len(units)))
    conn.commit()

    # Wire the imported book into the library and the search index so its
    # contents are searchable and readable like any other module.
    try:
        from . import indexer, library, markup
        lib_units = []
        for i, u in enumerate(units, 1):
            lib_units.append(indexer.UnitIn(
                key=f"{book_id}.{i}", label=f"\u00b6{i}",
                segs=markup.parse_plain(u), title=""))
        indexer.run_import(book_id, iter(lib_units),
                           name=title, type="Book", lang="eng",
                           source="Personal", format=fmt, author="")
    except Exception as e:  # noqa: BLE001
        try:
            db.log_history("personal-book", f"{book_id}: indexing failed: {e}")
        except Exception:
            pass

    return {"ok": True, "action": "import", "book_id": book_id,
            "title": title, "format": fmt, "unit_count": len(units)}


def _delete_personal_book(book_id: str) -> dict:
    conn = db.connect()
    try:
        from . import library
        library.mark_removed(conn, book_id)
        conn.commit()
        try:
            from . import posindex
            posindex.forget(book_id)
        except Exception:
            pass
    except Exception:
        pass
    conn.execute("DELETE FROM personal_books WHERE id=?", (book_id,))
    conn.commit()
    return {"ok": True, "action": "delete", "book_id": book_id}


def _read_personal_book(book_id: str) -> dict:
    conn = db.connect()
    row = conn.execute(
        "SELECT * FROM personal_books WHERE id=?", (book_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "book not found"}

    path = row["path"]
    fmt = row["format"]
    try:
        if fmt == "epub":
            text = _read_epub(path)
        elif fmt == "pdf":
            text = _read_pdf(path)
        else:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
    except Exception as e:
        return {"ok": False, "error": f"could not read file: {e}"}

    return {"ok": True, "book_id": book_id, "title": row["title"],
            "format": fmt, "text": text}


def _read_epub(path: str) -> str:
    """Extract text from an EPUB file."""
    try:
        import ebooklib
        from ebooklib import epub
        book = epub.read_epub(path)
        texts = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            content = item.get_content()
            # Strip HTML tags crudely.
            import re
            text = re.sub(r"<[^>]+>", " ", content.decode("utf-8", errors="replace"))
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                texts.append(text)
        return "\n\n".join(texts)
    except Exception:
        return ""


def _read_pdf(path: str) -> str:
    """Extract text from a PDF file."""
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(path)
        texts = []
        for page in reader.pages:
            texts.append(page.extract_text() or "")
        return "\n\n".join(texts)
    except Exception:
        return ""


# ===========================================================================
# Courses — video/audio course player and library
# ===========================================================================

def courses(action: str = "", course_id: str = "", lesson_id: str = "",
            title: str = "", description: str = "", author: str = "",
            lesson_title: str = "", content: str = "", video_url: str = "",
            audio_url: str = "", completed: str = "1") -> dict:
    """Course library and player.

    Actions: list, open, lesson, progress.
    """
    conn = db.connect()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS courses ("
        "  id TEXT PRIMARY KEY,"
        "  title TEXT NOT NULL,"
        "  description TEXT,"
        "  author TEXT,"
        "  created_at REAL NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS course_lessons ("
        "  id TEXT PRIMARY KEY,"
        "  course_id TEXT NOT NULL,"
        "  title TEXT NOT NULL,"
        "  content TEXT,"
        "  video_url TEXT,"
        "  audio_url TEXT,"
        "  position INTEGER DEFAULT 0,"
        "  FOREIGN KEY(course_id) REFERENCES courses(id))")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS course_progress ("
        "  course_id TEXT NOT NULL,"
        "  lesson_id TEXT NOT NULL,"
        "  completed INTEGER DEFAULT 0,"
        "  PRIMARY KEY(course_id, lesson_id))")
    conn.commit()

    if action == "list":
        rows = conn.execute(
            "SELECT c.*, COUNT(l.id) AS lesson_count "
            "FROM courses c LEFT JOIN course_lessons l ON l.course_id=c.id "
            "GROUP BY c.id ORDER BY c.created_at DESC").fetchall()
        return {"ok": True, "action": "list", "courses": [dict(r) for r in rows]}

    if action == "create":
        t = (title or "").strip()
        if not t:
            return {"ok": False, "error": "need a title"}
        import uuid as _u
        cid = "course_" + _u.uuid4().hex[:12]
        conn.execute(
            "INSERT INTO courses(id, title, description, author, created_at) "
            "VALUES(?,?,?,?,?)", (cid, t, description or "", author or "",
                                  time.time()))
        conn.commit()
        return {"ok": True, "action": "create", "course_id": cid,
                "title": t}

    if action == "delete":
        if not course_id:
            return {"ok": False, "error": "need a course id"}
        conn.execute("DELETE FROM course_lessons WHERE course_id=?", (course_id,))
        conn.execute("DELETE FROM course_progress WHERE course_id=?", (course_id,))
        conn.execute("DELETE FROM courses WHERE id=?", (course_id,))
        conn.commit()
        return {"ok": True, "action": "delete", "course_id": course_id}

    if action == "add-lesson":
        if not course_id:
            return {"ok": False, "error": "need a course id"}
        lt = (lesson_title or title or "").strip()
        if not lt:
            return {"ok": False, "error": "need a lesson title"}
        import uuid as _u
        lid = "lesson_" + _u.uuid4().hex[:12]
        pos = conn.execute(
            "SELECT COALESCE(MAX(position),0)+1 n FROM course_lessons WHERE course_id=?",
            (course_id,)).fetchone()["n"]
        conn.execute(
            "INSERT INTO course_lessons(id, course_id, title, content, video_url, audio_url, position) "
            "VALUES(?,?,?,?,?,?,?)",
            (lid, course_id, lt, content or "", video_url or "", audio_url or "", pos))
        conn.commit()
        return {"ok": True, "action": "add-lesson", "lesson_id": lid,
                "course_id": course_id}

    if action == "delete-lesson":
        if not lesson_id:
            return {"ok": False, "error": "need a lesson id"}
        conn.execute("DELETE FROM course_lessons WHERE id=?", (lesson_id,))
        conn.execute("DELETE FROM course_progress WHERE lesson_id=?", (lesson_id,))
        conn.commit()
        return {"ok": True, "action": "delete-lesson", "lesson_id": lesson_id}

    if action == "open":
        if not course_id:
            return {"ok": False, "error": "need a course id"}
        row = conn.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "course not found"}
        lessons = conn.execute(
            "SELECT * FROM course_lessons WHERE course_id=? ORDER BY position",
            (course_id,)).fetchall()
        progress = {}
        for p in conn.execute(
                "SELECT lesson_id, completed FROM course_progress WHERE course_id=?",
                (course_id,)).fetchall():
            progress[p["lesson_id"]] = bool(p["completed"])
        return {"ok": True, "action": "open", "course": dict(row),
                "lessons": [dict(l) for l in lessons],
                "progress": progress}

    if action == "lesson":
        if not lesson_id:
            return {"ok": False, "error": "need a lesson id"}
        row = conn.execute(
            "SELECT * FROM course_lessons WHERE id=?", (lesson_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "lesson not found"}
        return {"ok": True, "action": "lesson", "lesson": dict(row)}

    if action == "progress":
        if not course_id or not lesson_id:
            return {"ok": False, "error": "need course_id and lesson_id"}
        completed = str(completed).lower() not in ("0", "false", "")
        conn.execute(
            "INSERT OR REPLACE INTO course_progress(course_id, lesson_id, completed) "
            "VALUES(?,?,?)", (course_id, lesson_id, 1 if completed else 0))
        conn.commit()
        return {"ok": True, "action": "progress"}

    return {"ok": False, "error": f"unknown action '{action}'"}


# ===========================================================================
# Draw on Screen — drawing annotation overlay
# ===========================================================================

def draw_on_screen(action: str = "", drawing_id: str = "", title: str = "",
                   data: str = "") -> dict:
    """Drawing annotations over Bible text.

    Actions: list, save, delete, load.
    Drawings are JSON with paths, shapes, colors, etc.
    """
    conn = db.connect()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS drawings ("
        "  id TEXT PRIMARY KEY,"
        "  title TEXT NOT NULL,"
        "  data TEXT NOT NULL,"
        "  created_at REAL NOT NULL,"
        "  updated_at REAL NOT NULL)")
    conn.commit()

    if action == "list":
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM drawings "
            "ORDER BY updated_at DESC").fetchall()
        return {"ok": True, "action": "list", "drawings": [dict(r) for r in rows]}

    if action == "save":
        import json as _j
        if not drawing_id:
            import uuid
            drawing_id = "draw_" + uuid.uuid4().hex[:12]
        if not title:
            title = drawing_id
        now = time.time()
        conn.execute(
            "INSERT OR REPLACE INTO drawings(id, title, data, created_at, updated_at) "
            "VALUES(?,?,?,?,?)",
            (drawing_id, title, data, now, now))
        conn.commit()
        return {"ok": True, "action": "save", "drawing_id": drawing_id}

    if action == "delete":
        if not drawing_id:
            return {"ok": False, "error": "need a drawing id"}
        conn.execute("DELETE FROM drawings WHERE id=?", (drawing_id,))
        conn.commit()
        return {"ok": True, "action": "delete"}

    if action == "load":
        if not drawing_id:
            return {"ok": False, "error": "need a drawing id"}
        row = conn.execute("SELECT * FROM drawings WHERE id=?", (drawing_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "drawing not found"}
        return {"ok": True, "action": "load", "drawing": dict(row)}

    return {"ok": False, "error": f"unknown action '{action}'"}


# ===========================================================================
# Print/Export — full print and export
# ===========================================================================

def print_export(action: str = "", content_type: str = "", content_id: str = "",
                 format: str = "pdf") -> dict:
    """Print and export passages, guides, searches, notes, etc.

    Actions: list, formats, export, print.
    Formats: pdf, html, txt, md, docx.
    """
    if action == "list":
        return {"ok": True, "action": "list",
                "formats": ["pdf", "html", "txt", "md", "docx"],
                "content_types": ["passage", "search", "notes"]}

    if action == "formats":
        return {"ok": True, "action": "formats",
                "formats": ["pdf", "html", "txt", "md"]}

    if action == "export":
        if not content_type or not content_id:
            return {"ok": False, "error": "need content_type and content_id"}
        return _do_export(content_type, content_id, format)

    if action == "print":
        if not content_type or not content_id:
            return {"ok": False, "error": "need content_type and content_id"}
        return _do_print(content_type, content_id, format)

    return {"ok": False, "error": f"unknown action '{action}'"}


def _do_export(content_type: str, content_id: str, format: str) -> dict:
    """Export content in the given format."""
    # Gather content based on type.
    conn = db.connect()
    title = content_id
    body = ""

    if content_type == "passage":
        rr = canon.parse_ref(content_id)
        if rr:
            verses = list(rr.refs())[:12]
            parts = []
            for v in verses:
                row = conn.execute(
                    "SELECT text FROM unit WHERE book=? AND chapter=? AND verse=? "
                    "LIMIT 1", (v.book, v.chapter, v.verse)).fetchone()
                if row:
                    parts.append(f"{v.book} {v.chapter}:{v.verse} — "
                                 f"{(row['text'] or '').strip()}")
            body = "\n\n".join(parts)
            title = content_id
    elif content_type == "notes":
        row = conn.execute(
            "SELECT title, body FROM note WHERE id=?", (content_id,)).fetchone()
        if row:
            title = row["title"] or content_id
            body = row["body"] or ""
    elif content_type == "search":
        # Return the search query text.
        body = f"Search results for: {content_id}\n\n(Full search export requires the search panel.)"
    else:
        return {"ok": False, "error":
                f"export of {content_type!r} is not supported; "
                "choose passage, search or notes"}

    if format == "txt":
        content = f"{title}\n{'=' * len(title)}\n\n{body}"
        return {"ok": True, "action": "export", "format": "txt",
                "content": content, "filename": f"{title}.txt"}
    elif format == "md":
        content = f"# {title}\n\n{body}"
        return {"ok": True, "action": "export", "format": "md",
                "content": content, "filename": f"{title}.md"}
    elif format == "html":
        content = (f"<html><head><title>{title}</title></head><body>"
                   f"<h1>{title}</h1><div>{body}</div></body></html>")
        return {"ok": True, "action": "export", "format": "html",
                "content": content, "filename": f"{title}.html"}
    elif format == "pdf":
        # Prefer a real PDF when a library is available.
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas as _pcanvas
            import io as _io
            buf = _io.BytesIO()
            c = _pcanvas.Canvas(buf, pagesize=letter)
            w, h = letter
            y = h - 50
            c.setFont("Helvetica-Bold", 14)
            c.drawString(50, y, title[:80]); y -= 24
            c.setFont("Helvetica", 10)
            for line in (body or "").split("\n"):
                if y < 60:
                    c.showPage(); y = h - 50; c.setFont("Helvetica", 10)
                c.drawString(50, y, line[:110]); y -= 13
            c.save()
            import base64 as _b64
            return {"ok": True, "action": "export", "format": "pdf",
                    "content_base64": _b64.b64encode(buf.getvalue()).decode("ascii"),
                    "filename": f"{title}.pdf",
                    "note": "PDF generated with reportlab."}
        except Exception:
            pass
        # Fallback: HTML with a note.
        content = (f"<html><head><title>{title}</title></head><body>"
                   f"<h1>{title}</h1><div>{body}</div>"
                   f"<p><em>PDF export requires a PDF library installed on this system.</em></p>"
                   f"</body></html>")
        return {"ok": True, "action": "export", "format": "pdf",
                "content": content, "filename": f"{title}.html",
                "note": "PDF export returned as HTML (no PDF library available)."}
    elif format == "docx":
        content = f"{title}\n{'=' * len(title)}\n\n{body}"
        return {"ok": True, "action": "export", "format": "docx",
                "content": content, "filename": f"{title}.txt",
                "note": "DOCX export returned as plain text (no python-docx available)."}

    return {"ok": False, "error": f"unsupported format '{format}'"}


def _do_print(content_type: str, content_id: str, format: str) -> dict:
    """Print content — returns a print-ready HTML view."""
    # Reuse export but mark as print view.
    result = _do_export(content_type, content_id, format)
    if result.get("ok"):
        result["action"] = "print"
        result["print_view"] = True
    return result


# ===========================================================================
# Info Tool — info about a verse/person/place
# ===========================================================================

def info_tool(ref: str = "", module_id: str = "") -> dict:
    """Info tool: everything known about a passage/person/place.

    Returns the verse text, any notes, cross-references, places, people,
    topics, and related resources for a passage or word.
    """
    conn = db.connect()
    q = (ref or "").strip()
    if not q:
        return {"ok": False, "error": "no reference given"}

    rr = canon.parse_ref(q)
    if rr is None:
        return {"ok": False, "error": f"cannot read {q!r} as a reference"}
    refs = list(rr.refs())[:5]

    result = {"ok": True, "ref": ref, "ref_label": canon.format_ref(refs[0]) if refs else ref}

    verses = []
    for r_ in refs:
        row = conn.execute(
            "SELECT u.text, u.ref_label, u.module_id FROM unit u "
            "WHERE u.book=? AND u.chapter=? AND u.verse=? LIMIT 1",
            (r_.book, r_.chapter, r_.verse)).fetchone()
        if row:
            verses.append({
                "ref": row["ref_label"] or f"{r_.book} {r_.chapter}:{r_.verse}",
                "text": (row["text"] or "").strip(),
                "module_id": row["module_id"],
            })

    result["verses"] = verses

    strongs_markers = []
    morph_markers = []
    for v in verses:
        row = conn.execute(
            "SELECT m.value, m.surface, m.kind FROM marker m "
            "JOIN unit u ON u.module_id=m.module_id AND u.key=m.unit_key "
            "WHERE u.ref_label=? AND (m.kind='strongs' OR m.kind='morph') LIMIT 10",
            (v["ref"],)).fetchall()
        for r2 in row:
            if r2["kind"] == "strongs":
                strongs_markers.append(r2["value"])
            elif r2["kind"] == "morph":
                morph_markers.append(r2["value"])

    result["strongs"] = strongs_markers
    result["morphology"] = morph_markers

    # The reader's own notes on these verses.  This used to requery the
    # Strong's markers, printing the same numbers a second time under "Notes".
    notes = []
    for v in verses:
        rows = conn.execute(
            "SELECT title, body FROM note WHERE ref_label=? "
            "ORDER BY updated_at DESC LIMIT 5", (v["ref"],)).fetchall()
        for n in rows:
            label = (n["title"] or "").strip()
            body = (n["body"] or "").strip()
            if label or body:
                notes.append((label + ": " if label else "") + body[:300])
    result["notes"] = notes[:5]

    topics = []
    for v in verses:
        rows = conn.execute(
            "SELECT m.value FROM marker m "
            "JOIN unit u ON u.module_id=m.module_id AND u.key=m.unit_key "
            "WHERE u.ref_label=? AND m.kind='topic' LIMIT 10",
            (v["ref"],)).fetchall()
        topics.extend([r["value"] for r in rows if r["value"]])

    result["topics"] = topics[:10]

    xrefs = []
    for v in verses:
        rows = conn.execute(
            "SELECT x.to_key FROM xref x "
            "JOIN unit u ON u.module_id=x.module_id AND u.key=x.from_key "
            "WHERE u.ref_label=? LIMIT 10",
            (v["ref"],)).fetchall()
        xrefs.extend([r["to_key"] for r in rows if r["to_key"]])

    result["cross_references"] = xrefs[:10]

    return result


# ===========================================================================
# Bibliography — formatted citations for passages/modules.
# ===========================================================================

def bibliography(module_ids: list[str] = None, *, style: str = "sbl") -> dict:
    """Styled citations for installed modules, via the shared citation engine.

    This used to hand-build one "author. year. name." string and echo the
    requested `style` without ever using it.  `citation.bibliography` already
    implements the styles and reports which entries are missing fields.
    """
    from . import citation
    if style not in citation.STYLES:
        return {"ok": False, "error": f"unknown citation style {style!r}",
                "styles": sorted(citation.STYLES)}
    conn = db.connect()
    skipped = list(module_ids or [])
    if module_ids is None:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM module WHERE installed_at>0 ORDER BY name").fetchall()]
        skipped = []
    else:
        ids = [mid for mid in module_ids
               if conn.execute("SELECT 1 FROM module WHERE id=? AND installed_at>0",
                               (mid,)).fetchone()]
        skipped = [mid for mid in module_ids if mid not in ids]
    if not ids:
        return {"ok": False, "error": "no installed resources to cite",
                "skipped": skipped}
    r = citation.bibliography(ids, style=style)
    entries = []
    for c in r.get("entries", []):
        meta = c.get("meta") or {}
        entries.append({
            "module_id": c.get("module_id") or "",
            "name": meta.get("name") or "",
            "title": meta.get("name") or "",
            "type": meta.get("type") or "",
            "lang": meta.get("lang") or "",
            "author": meta.get("author") or "",
            "year": meta.get("year") or "",
            "description": ((meta.get("description") or "")[:497] + "…"
                            if len(meta.get("description") or "") > 500
                            else (meta.get("description") or "")),
            "citation": c.get("citation") or "",
            "complete": c.get("complete", False),
        })
    return {"ok": True, "style": style, "entries": entries,
            "count": len(entries), "text": r.get("text", ""),
            "flagged": r.get("flagged", []), "skipped": skipped,
            "note": r.get("note", "")}


# ===========================================================================
# Books Search — search inside books/modules.
# ===========================================================================

def books_search(q: str = "", module_ids: list[str] = None, limit: int = 20,
                 kind: str = "") -> dict:
    """Search inside books/modules for a term, optionally in one resource type."""
    conn = db.connect()
    q = (q or "").strip()
    if not q:
        return {"ok": False, "error": "no query given"}

    limit = max(1, min(int(limit or 20), 200))
    module_ids_list = list(module_ids) if module_ids else []
    # Escape LIKE wildcards: a bare "%" used to match the entire library.
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    where = "u.text LIKE ? ESCAPE '\\' AND m.installed_at>0"
    args: list = [like]
    if module_ids_list:
        ph = ",".join("?" * len(module_ids_list))
        where += f" AND u.module_id IN ({ph})"
        args.extend(module_ids_list)
    if (kind or "").strip():
        where += " AND m.type=?"
        args.append(kind.strip())
    total = conn.execute(
        "SELECT count(*) c FROM unit u JOIN module m ON m.id=u.module_id "
        f"WHERE {where}", args).fetchone()["c"]
    rows = conn.execute(
        "SELECT u.text, u.ref_label, u.module_id, m.name FROM unit u "
        f"JOIN module m ON m.id=u.module_id WHERE {where} "
        "ORDER BY m.name, u.ord LIMIT ?", args + [limit]).fetchall()

    results = []
    for r in rows:
        results.append({
            "ref": r["ref_label"] or "",
            "text": (r["text"] or "")[:300],
            "module_id": r["module_id"],
            "module": r["name"] or "",
        })

    return {"ok": True, "query": q, "results": results,
            "count": total, "returned": len(results),
            "more": total > len(results),
            "notice": "" if results else "No books matched that term."}


# ===========================================================================
# Search Synopsis — overview of search results across books.
# ===========================================================================

def search_synopsis(q: str = "", module_ids: list[str] = None) -> dict:
    """Search synopsis: overview of where results fall across books."""
    conn = db.connect()
    q = (q or "").strip()
    if not q:
        return {"ok": False, "error": "no query given"}

    module_ids_list = list(module_ids) if module_ids else []
    esc = lambda t: t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = "%" + esc(q) + "%"
    if module_ids_list:
        ph = ",".join("?" * len(module_ids_list))
        rows = conn.execute(
            f"SELECT u.module_id, m.name, COUNT(*) as c FROM unit u "
            f"JOIN module m ON m.id=u.module_id "
            f"WHERE u.text LIKE ? ESCAPE '\\' AND m.installed_at>0 "
            f"AND u.module_id IN ({ph}) "
            f"GROUP BY u.module_id ORDER BY c DESC",
            [like, *module_ids_list])
    else:
        rows = conn.execute(
            "SELECT u.module_id, m.name, COUNT(*) as c FROM unit u "
            f"JOIN module m ON m.id=u.module_id "
            f"WHERE u.text LIKE ? ESCAPE '\\' AND m.installed_at>0 "
            f"GROUP BY u.module_id ORDER BY c DESC",
            (like,)).fetchall()

    synopsis = []
    for r in rows:
        row = conn.execute(
            "SELECT u.text, u.key FROM unit u WHERE u.module_id=? "
            "AND u.text LIKE ? ESCAPE '\\' LIMIT 1",
            (r["module_id"], like)).fetchone()
        sample = (row["text"] or "")[:200] if row else ""
        synopsis.append({
            "module_id": r["module_id"],
            "module": r["name"] or r["module_id"],
            "count": r["c"],
            "sample": sample,
            # The matched unit key lets the UI make the sample a real link.
            "sample_ref": row["key"] if row else "",
        })

    return {"ok": True, "query": q, "synopsis": synopsis, "count": len(synopsis)}


# ===========================================================================
# Insights — AI-style insights about a passage.
# ===========================================================================

def insights(ref: str = "", module_id: str = "") -> dict:
    """Word frequency and a passage excerpt — deterministic, not AI analysis.

    Called "Insights" in the menu for historical reasons.  It reports the most
    frequent non-common words up to five verses and quotes the text it read, so
    every claim can be checked.  It does not infer themes or applications.
    """
    conn = db.connect()
    q = (ref or "").strip()
    if not q:
        return {"ok": False, "error": "no reference given"}

    rr = canon.parse_ref(q)
    if rr is None:
        return {"ok": False, "error": f"cannot read {q!r} as a reference"}
    refs = list(rr.refs())[:5]

    verses = []
    for r_ in refs:
        row = conn.execute(
            "SELECT u.text, u.ref_label FROM unit u "
            "WHERE u.book=? AND u.chapter=? AND u.verse=? LIMIT 1",
            (r_.book, r_.chapter, r_.verse)).fetchone()
        if row:
            verses.append({
                "ref": row["ref_label"] or f"{r_.book} {r_.chapter}:{r_.verse}",
                "text": (row["text"] or "").strip(),
            })

    stop_words = {"the", "and", "of", "to", "a", "in", "is", "it", "you", "that",
        "he", "was", "for", "on", "are", "as", "with", "his", "they",
        "at", "be", "this", "have", "from", "or", "one", "had", "by",
        "word", "but", "not", "what", "all", "were", "we", "when",
        "your", "can", "said", "there", "use", "an", "each", "which",
        "she", "do", "how", "their", "if", "will", "up", "other",
        "about", "out", "many", "then", "them", "these", "so", "some",
        "her", "would", "make", "him", "into", "time", "has",
        "look", "two", "more", "write", "go", "see", "number", "no",
        "way", "could", "people", "my", "than", "first", "water", "been",
        "call", "who", "oil", "its", "now", "find", "long", "down",
        "day", "did", "get", "come", "made", "may", "part"}

    word_counts = {}
    for v in verses:
        for word in v["text"].lower().split():
            word = word.strip(".,!?;:\"'()")
            if word and word not in stop_words and len(word) > 3:
                word_counts[word] = word_counts.get(word, 0) + 1

    insights_list = []
    if verses:
        insights_list.append({
            "type": "theme",
            "title": f"Common words in {refs[0].label if refs else q}",
            "content": ("The words appearing most often here are: "
                        + ', '.join(w for w, _ in
                                    sorted(word_counts.items(), key=lambda x: (-x[1], x[0]))[:5])
                        + ". Frequency is not the same as importance."),
            "verses": [v["ref"] for v in verses],
        })
        insights_list.append({
            "type": "summary",
            "title": "Passage excerpt",
            "content": verses[0]["text"][:200] + "..." if len(verses[0]["text"]) > 200 else verses[0]["text"],
        })

    return {"ok": True, "ref": q, "sections": insights_list, "count": len(insights_list)}


# ===========================================================================
# Sermon Import — import a sermon document.
# ===========================================================================

def sermon_import(text: str = "", title: str = "", series: str = "") -> dict:
    """Import a sermon document into the same store the Sermon Manager uses.

    This used to create a row in its own ``sermons`` table, so the sermon was
    invisible to the Manager, Editor, Documents search, calendar and backups.
    """
    from . import docs
    if not text:
        return {"ok": False, "error": "no text provided"}
    r = docs.sermon_import(text, title, series)
    if not r.get("ok"):
        return r
    return {"ok": True, "sermon_id": r.get("id"), "id": r.get("id"),
            "title": r.get("title") or title, "series": series}


# ===========================================================================
# Sermon Documents — view/manage sermon documents.
# ===========================================================================

def sermon_documents(sermon_id: str = "") -> dict:
    """List sermon documents from the canonical note store.

    The response keeps the legacy shape (``sermons[].text``, ``sermon_id``)
    because the Study Tools dialog renders it, but the rows are now the same
    ``note`` rows the Sermon Manager and Editor read and write.
    """
    from . import docs, notes

    def show(n):
        meta = docs._sermon_meta(n)
        return {"id": n.get("id") or "", "title": n.get("title") or "Untitled",
                "series": meta.get("series") or "",
                "text": n.get("body") or "",
                "created_at": n.get("created_at") or 0}

    if sermon_id:
        n = notes.get(sermon_id)
        if not n or n.get("kind") != "sermon":
            return {"ok": False, "error": "sermon not found"}
        return {"ok": True, "sermon": show(n)}
    rows = [show(n) for n in (notes.listing(kind="sermon", limit=5000) or [])]
    return {"ok": True, "sermons": rows, "count": len(rows)}


# ===========================================================================
# Visual Copy — copy verse as an image (text representation).
# ===========================================================================

def visual_copy(ref: str = "", module_id: str = "", style: str = "default") -> dict:
    """Supply the verse text for a shareable image.

    The old ASCII rendering is kept as `content` for callers that still want a
    text preview, but the browser now draws a real PNG from `text`.
    """
    conn = db.connect()
    ref = (ref or "").strip()
    if not ref:
        return {"ok": False, "error": "no reference given"}

    rr = canon.parse_ref(ref)
    if rr is None:
        return {"ok": False, "error": f"cannot read {ref!r} as a reference"}

    all_refs = list(rr.refs())
    if not all_refs:
        return {"ok": False, "error": "no valid reference"}
    r_ = all_refs[0]

    # unit.key is not unique across modules. Without a module filter the image
    # could be drawn from Greek/Hebrew or a commentary while showing an English
    # reference, and a bad id silently picked whichever module sorted first.
    m = library.get_installed(module_id) if module_id else None
    if module_id and m is None:
        return {"ok": False, "error": "that resource is not installed"}
    if m is None:
        mods = library.list_all()
        m = (next((x for x in mods
                   if x.type == "Bible" and x.lang == "eng" and x.is_bible), None)
             or next((x for x in mods if x.is_bible), None))
    if m is None:
        return {"ok": False, "error": "no installed Bible to read that verse from"}

    row = conn.execute(
        "SELECT u.text, u.ref_label FROM unit u "
        "WHERE u.module_id=? AND u.book=? AND u.chapter=? AND u.verse=? LIMIT 1",
        (m.id, r_.book, r_.chapter, r_.verse)).fetchone()

    if not row:
        return {"ok": False, "error": f"{m.name} has no text for that verse"}

    text = row["text"]
    ascii_art = f"""
╔════════════════════════════════════════╗
║  {ref:<38}║
║                                      ║
║  {text[:70]:<70}║
║                                      ║
╚═══════════════════════════════════════╝
"""

    return {"ok": True, "ref": canon.format_ref(r_),
            "requested": ref, "label": row["ref_label"] or ref,
            "note": ("Only the first verse was rendered."
                     if len(all_refs) > 1 else ""),
            "module_id": m.id, "module": m.name,
            "license": m.license or "", "attribution": m.rights or "",
            "text": text, "content": ascii_art, "format": "text"}


# ===========================================================================
# Confessional Documents — creeds, confessions, catechisms.
# ===========================================================================

def confessional_documents(doc_type: str = "", limit: int = 20) -> dict:
    """Creeds, confessions and catechisms from installed reference works.

    This used to keyword-search ``unit.text`` for "confession" and present
    lexicon headwords as confessional documents. It now requires a source that
    is actually a confessional work, and says so plainly when none is installed.
    """
    conn = db.connect()
    mods = [m for m in library.list_all()
            if m.type in ("Book", "FactBook", "StudyGuide")
            and re.search(r"creed|confess| catech| Westminster|Augsburg",
                          m.name or "", re.I)]
    if not mods:
        return {"ok": False,
                "error": ("No confessional document source is installed. "
                          "Install a creed, confession or catechism from the "
                          "Store to use this tool."),
                "documents": [], "count": 0}
    ids = [m.id for m in mods]
    ph = ",".join("?" * len(ids))
    where = f"u.module_id IN ({ph})"
    args: list = list(ids)
    if doc_type:
        where += " AND (u.title LIKE ? OR u.text LIKE ?)"
        esc = lambda t: t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        args += ["%" + esc(doc_type) + "%"] * 2
    rows = conn.execute(
        f"SELECT u.text, u.ref_label, m.name FROM unit u "
        f"JOIN module m ON m.id=u.module_id WHERE {where} LIMIT ?",
        args + [max(1, min(int(limit or 20), 200))]).fetchall()
    results = [{"title": r["ref_label"] or "Untitled",
                "text": (r["text"] or "")[:500], "module": r["name"] or ""}
               for r in rows]
    return {"ok": True, "documents": results, "count": len(results),
            "sources": [m.name for m in mods]}


# ===========================================================================
# Catholic Daily Readings / Topical Index
# ===========================================================================

def catholic_daily_readings(date: str = "", liturgical_season: str = "") -> dict:
    """Daily readings from an installed Lectionary module.

    The old implementation searched for the literal date string inside verse
    text, which cannot work: the ``unit`` table has no date column. It returned
    lexicon headwords and called them readings. With no Lectionary installed
    the only honest answer is to say so.
    """
    conn = db.connect()
    mods = [m for m in library.list_all() if m.type == "Lectionary"]
    if not mods:
        return {"ok": False,
                "error": ("No Lectionary module is installed. Daily readings "
                          "cannot be looked up from a date with the resources "
                          "currently in this library."),
                "readings": [], "count": 0, "date": date,
                "season": liturgical_season}
    ids = [m.id for m in mods]
    ph = ",".join("?" * len(ids))
    args: list = list(ids)
    where = f"u.module_id IN ({ph})"
    if date:
        where += " AND (u.key LIKE ? OR u.ref_label LIKE ?)"
        args += [f"%{date}%", f"%{date}%"]
    rows = conn.execute(
        f"SELECT u.text, u.ref_label, m.name FROM unit u "
        f"JOIN module m ON m.id=u.module_id WHERE {where} LIMIT 100",
        args).fetchall()
    results = [{"title": r["ref_label"] or "Daily Reading",
                "text": (r["text"] or "")[:500], "module": r["name"] or ""}
               for r in rows]
    return {"ok": True, "date": date, "season": liturgical_season,
            "readings": results, "count": len(results),
            "sources": [m.name for m in mods]}


# ===========================================================================
# Popular Quotes — most-quoted Bible verses.
# ===========================================================================

def popular_quotes(module_ids: list[str] = None, limit: int = 20) -> dict:
    """Verses most often pointed to by installed scripture cross-references.

    Topic-index links were previously mixed into the count, and the displayed
    text came from whichever module first had a matching ``unit.key`` -- often
    Greek or Hebrew under an English reference. The count now uses only
    ``kind='ref'`` links, and the text is read from an installed Bible at the
    reference the link points to, with that Bible named in the response.
    """
    conn = db.connect()
    limit = max(1, min(int(limit or 20), 200))
    bibles = [m for m in library.list_all()
              if m.is_bible and (not module_ids or m.id in module_ids)]
    if not bibles:
        return {"ok": False, "error": "no installed Bible to read quoted verses",
                "quotes": [], "count": 0}
    rows = conn.execute(
        "SELECT x.to_key, COUNT(DISTINCT x.from_key) as c FROM xref x "
        "JOIN module m ON m.id=x.module_id "
        "WHERE x.kind='ref' AND m.installed_at>0 "
        "GROUP BY x.to_key ORDER BY c DESC LIMIT ?", (limit,)).fetchall()
    # Prefer an English tagged Bible for the displayed text.
    bibles.sort(key=lambda m: ((2 if m.lang == "eng" else 0)
                               + (1 if m.has_strongs or m.has_morph else 0)),
                reverse=True)
    results = []
    for row in rows:
        target = canon.parse_ref(row["to_key"])
        if target is None:
            continue
        ref = target.start
        for m in bibles:
            text_row = conn.execute(
                "SELECT u.text, u.ref_label FROM unit u "
                "WHERE u.module_id=? AND u.book=? AND u.chapter=? AND u.verse=? "
                "LIMIT 1", (m.id, ref.book, ref.chapter, ref.verse)).fetchone()
            if text_row and (text_row["text"] or "").strip():
                results.append({
                    "ref": text_row["ref_label"] or canon.format_ref(ref),
                    "text": (text_row["text"] or "")[:200],
                    "count": row["c"],
                    "module": m.name,
                    "license": m.license or "",
                })
                break
    return {"ok": True, "quotes": results, "count": len(results),
            "metric": "distinct scripture cross-references (topic links excluded)"}


# ===========================================================================
# Louw–Nida sense domains (SBLGNT data rebuilt from the TSV).
# Words tagged with a Strong's number can carry Louw–Nida domain codes in
# the MACULA Greek module; these read them straight off the marker table.
# ===========================================================================

_MACULA = "macula-macula-greek-sblgnt"


def senses_domains(num: str, limit: int = 12) -> dict:
    """The Louw–Nida sense domains a Strong's number carries in SBLGNT.

    Each entry is one domain code and how often the words of this Strong's
    number bear it.  This is a word-level sense index built entirely from
    CC BY 4.0 data.
    """
    num = canon.normalise_strongs(num or "")
    if not num:
        return {"ok": False, "error": "no Strong's number"}
    conn = db.connect()
    rows = conn.execute(
        "SELECT s.value AS sense, COUNT(*) AS n "
        "FROM marker s "
        "JOIN marker t ON t.unit_key=s.unit_key AND t.pos=s.pos AND t.module_id=s.module_id "
        "WHERE s.module_id=? AND s.kind='sense' "
        "AND t.kind='strongs' AND t.value=? "
        "GROUP BY s.value ORDER BY n DESC LIMIT ?", (_MACULA, num, int(limit))).fetchall()
    return {"ok": True, "num": num,
            "domains": [{"sense": r["sense"], "count": r["n"]} for r in rows]}


def sense_occurrences(num: str, code: str = "", limit: int = 60) -> dict:
    """Every SBLGNT word of this Strong's number, optionally filtered to one
    Louw–Nida domain, with references readers can follow."""
    num = canon.normalise_strongs(num or "")
    code = (code or "").strip()
    if not num:
        return {"ok": False, "error": "no Strong's number"}
    conn = db.connect()
    sql = ("SELECT t.unit_key, s.value AS sense, t.surface, u.ref_label "
           "FROM marker s "
           "JOIN marker t ON t.unit_key=s.unit_key AND t.pos=s.pos AND t.module_id=s.module_id "
           "JOIN unit u ON u.module_id=s.module_id AND u.key=s.unit_key "
           "WHERE s.module_id=? AND s.kind='sense' "
           "AND t.kind='strongs' AND t.value=?")
    args = [_MACULA, num]
    if code:
        sql += " AND s.value=?"
        args.append(code)
    sql += " ORDER BY u.ord LIMIT ?"
    args.append(int(limit))
    rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        out.append({"ref": r["ref_label"], "surface": (r["surface"] or "").strip(),
                    "sense": r["sense"]})
    return {"ok": True, "num": num, "code": code, "occurrences": out}

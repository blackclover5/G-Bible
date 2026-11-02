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


def _place_mods() -> dict:
    """module ids by the kind of thing they are, computed once per call."""
    out: dict[str, list[str]] = {}
    for m in library.list_all():
        out.setdefault(m.type, []).append(m.id)
    return out


def _ids_of_type(types: tuple[str, ...]) -> list[str]:
    return [m.id for m in library.list_all() if m.type in types]


def _chunk(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


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
        return out
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
    return out


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


def places_at(book: str, chapter: int, verse: int) -> list[dict]:
    """Geocoded places whose passage list includes this verse.

    The catalogue writes book names inconsistently -- "1 Chr 6:74" with a space,
    "Josh 21:30" without -- so the match is on the numeric part of the reference
    rather than the whole string.
    """
    want = {f"{book} {chapter}:{verse}", f"{book}.{chapter}.{verse}",
            f"{book} {chapter}:{verse}".replace(" ", "")}
    nums = {f"{chapter}:{verse}"}
    out = []
    for p in _places():
        for ref in (p.get("passages") or []):
            ref = ref.strip()
            tail = ref.rsplit(" ", 1)[-1]
            if ref in want or tail in nums:
                out.append({"name": p.get("name", ""), "lat": p.get("lat"),
                            "lon": p.get("lon"), "type": p.get("type", ""),
                            "comment": _chunk(p.get("comment", ""), 300),
                            "slug": p.get("slug", "")})
                break
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
    cands = {num, f"{letter}{digits}"}
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


def morph_search(conn, code: str, *, scheme: str = "", limit: int = 400) -> dict:
    """Find every tagged word with this morphology code.

    Three tagging schemes are installed and they are not interchangeable, so
    they are reported separately rather than merged:

      * OSHB   -- "HNp", "HTd/Ncmsa"  (Robinson codes, H-prefixed)
      * Robinson -- "robinson:CONJ"
      * strongMorph -- "strongMorph:TH8799"

    A prefix search is the useful one: "HNcms" finds every noun, "HTd/" every
    article.  This is morphology search, and it needs no subscription because
    the tagging is already in the text.
    """
    code = (code or "").strip()
    if not code:
        return {"ok": False, "error": "no morphology code"}
    esc = code.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    # exact count first, so "total" is the real number and not the size of the
    # sample the panel happens to have fetched
    total = conn.execute(
        "SELECT count(*) FROM marker WHERE kind='morph' AND value LIKE ? ESCAPE '\\'",
        (esc + "%",)).fetchone()[0]
    rows = conn.execute(
        "SELECT value, module_id, unit_key, surface FROM marker "
        "WHERE kind='morph' AND value LIKE ? ESCAPE '\\' "
        "ORDER BY module_id, unit_key LIMIT ?", (esc + "%", limit)).fetchall()
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
        ref = None
        u = conn.execute("SELECT book, chapter, verse, ref_label FROM unit "
                         "WHERE module_id=? AND key=?",
                         (r["module_id"], r["unit_key"])).fetchone()
        if u and u["book"]:
            ref = {"book": u["book"], "chapter": u["chapter"],
                   "verse": u["verse"], "label": u["ref_label"] or ""}
        hits.append({"code": v, "module_id": r["module_id"],
                     "key": r["unit_key"],
                     "surface": _surface_for(conn, r["module_id"],
                                             r["unit_key"], v, r["surface"] or ""),
                     "ref": ref})
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
        "WHERE u.key=? AND m.type='Concordance' AND m.installed_at>0 LIMIT 1", (num,)).fetchone()
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


def _related_verses(q: str, *, limit: int = 12) -> list[dict]:
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
    have = {m.id: m for m in library.list_all() if m.type == "Bible"}
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


def _atlas_for(conn, ql: str, limit: int) -> list[dict]:
    """Atlas and map entries whose name mentions the term."""
    atlas = [m for m in library.list_all() if m.type in ("Atlas", "Map")]
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
    all_mods = {m.id: m for m in library.list_all()}

    # -- Related Verses: where the term is actually addressed.
    # This section lets you save the result as a passage list.
    verses = _related_verses(q, limit=14)
    if verses:
        out.append({"kind": "verses", "label": "Related Verses",
                    "note": "Verses containing the word", "items": verses})

    # -- Atlas: the map and atlas resources.  Eighty-six of them are installed.
    atlas = _atlas_for(conn, q, per_section)
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
            "text": _chunk(r["text"], limit), "length": len(r["text"] or "")}


def topic_guide(query: str, *, per_section: int = 6) -> dict:
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

    mods = {m.id: m for m in library.list_all()}

    # -- the full article, and a way on to the Fact guide.
    # A short definition here links onward to the Fact guide article; the Fact
    # guide holds the one long article, so the two do not print the same thing
    # twice.
    fb = [i for i in mods.values()
          if i.type == "FactBook" and _is_a_fact_book(i.name)]
    if fb:
        rows = _fact_rows(conn, fb, q)
        rows = sorted(rows, key=lambda r: -len(r["text"] or ""))[:per_section]
        out["sections"].append({
            "kind": "topic", "label": "Topic", "note": "The full article",
            "fact_query": q,
            "items": [_item(r, mods, 2200) for r in rows]})

    # -- the material that is not a fact-book entry
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
    for mid in module_ids:
        m = library.get(mid)
        if m is None or m.type not in library.VERSE_TEXT_TYPES:
            continue
        # Look the verse up by its columns, not by key: the key format is not
        # consistent between modules -- WEB stores "John.3.16" and the Berean
        # "John 3:16" -- so building the key drops translations silently.
        r = conn.execute(
            "SELECT text, ref_label FROM unit WHERE module_id=? AND book=? "
            "AND chapter=? AND verse=? LIMIT 1",
            (mid, osis.book, osis.chapter, osis.verse)).fetchone()
        if r is None or not (r["text"] or "").strip():
            continue
        out.append({"module_id": mid, "module": m.name, "abbrev": m.abbrev or "",
                    "version": m.version or "", "lang": m.lang,
                    "text": r["text"].strip(),
                    "label": r["ref_label"] or f"{osis.book} {osis.chapter}:{osis.verse}"})
    if not out:
        return {"ok": False, "error": "none of those resources have that verse"}
    return {"ok": True, "ref": f"{osis.book} {osis.chapter}:{osis.verse}",
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


def word_bundle(num: str, *, module_ids: list[str] | None = None) -> dict:
    """Everything installed that bears on one Strong's number."""
    conn = db.connect()
    num = canon.normalise_strongs(num or "")
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


#: The fact books, by what they are actually good for.  Classifying them here
#: rather than trusting the taxonomy is the point: all six are "FactBook", and
#: presenting a name-meaning list beside a full topical article, undifferentiated,
#: is what the Topic guide already does and what makes it less useful than it
#: could be.
_FACT_ROLES = (
    # (label, note, types, prefer)
    ("Names and meanings", "What a name meant", ("FactBook",), ("names",)),
    ("People", "Articles about a person", ("FactBook", "Dictionary"), ()),
    ("Places", "Articles about a place", ("FactBook", "Dictionary"), ()),
    ("Topic", "The full article", ("FactBook",), ()),
)

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


def fact_guide(query: str, *, per_section: int = 8, lens: str = "") -> dict:
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
    mods = [m for m in library.list_all()
            if m.type == "FactBook" and _is_a_fact_book(m.name)]
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

    ordered = sorted(rows, key=lambda r: (rank(r), -len(r["text"] or "")))

    def item(r):
        m = by_id[r["module_id"]]
        return {"module_id": m.id, "module": m.name, "key": r["key"],
                "title": r["title"] or r["key"],
                "text": _chunk(r["text"], 2400), "length": len(r["text"] or "")}

    sections: list[dict] = []

    def add(kind, label, items, note="", geo=None):
        if not items and not geo:
            return
        entry = {"kind": kind, "label": label, "note": note, "items": items}
        if geo:
            entry["geo"] = geo
        sections.append(entry)

    geo = _geo_for(conn, ql)

    name_rows = [r for r in ordered if _is_names_book(by_id[r["module_id"]].name)]
    add("name", "Name",
        [item(r) for r in name_rows[:per_section]],
        note="What the name meant to those who heard it")

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
    all_mods = {m.id: m for m in library.list_all()}
    for sec in _extra_sections(conn, all_mods, q, per_section, places=False):
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

    def key(v):
        # osis_id is a method, not a property.  Reading it as an attribute gave
        # a bound method, and the range test below then compared a method with a
        # string: "'<=' not supported between instances of 'method' and 'str'".
        return canon.Ref(v.book, v.chapter, v.verse).osis_id()

    # Genealogy refs are written "Gen 4:18" -- human style, not OSIS -- so the
    # range has to be built in that same shape or nothing ever matches.
    def human(v):
        return f"{v.book} {v.chapter}" if not v.verse else \
            f"{v.book} {v.chapter}:{v.verse}"
    lo, hi = human(verses[0]), human(verses[-1])
    out = []
    for name, p in (g.get("people") or {}).items():
        hits = [r for r in p.get("refs", []) if lo <= r <= hi]
        if hits:
            out.append({"name": name, "refs": hits[:6],
                        "father": p.get("father") or "",
                        "mentions": len(p.get("refs", []))})
    out.sort(key=lambda x: (-len(x["refs"]), x["name"]))
    return out[:20]


def _osis_key(v) -> str:
    return f"{v.book}.{v.chapter}.{v.verse}"


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
    for r in rows:
        key = (r["key"] or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        entries.append({
            "kind": "entry",
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

"""An index over topic markers, instead of matching topic text at query time.

A Fact-book article does not say where it applies in a machine-readable column.
Nave's entry for Aaron is a paragraph of prose with a list of references at the
end -- "Ex 6:16-20; Jos 21:4, 10; 1Ch 6:2, 3; 23:13" -- and the verse numbers are
just characters in a text field.  Torrey is the same shape.

So the only way to answer "what does this verse have a topic article about?"
without an index is to scan those bodies looking for the verse:

    SELECT ... FROM unit WHERE module_id IN (...) AND text LIKE '%Joh 3:16%'

which is what this did, on every single verse guide.  Its own comment admitted
the shape of the problem -- "this is a text match" -- and bounded the corpus
because a LIKE over every reference spelling is slow.  The bound was the only
thing stopping it from being obviously wrong: it works *because* the Fact-book
corpus is about ten thousand units, and it would quietly stop working the moment
that was not true.

The index is the same shape as the cross-reference table, because it is the same
kind of fact: an article identifier, a destination identifier, and a direction.
Rows go into `xref` with `kind='topic'`, which means:

* the existing primary key and the existing index on `(to_key, module_id)` do the
  work, so "which topics reach this verse" is an index lookup rather than a scan;
* topic lookups and cross-reference lookups are the same query shape, which is
  what lets the verse guide use one code path for both;
* nothing new is stored twice.

**Ranges are expanded to verses, and bounded.**  "Ex 6:16-20" is five verses and
is stored as five rows.  A reference like "Ps 119" is 176, and a hypothetical
whole-book range would be thirty thousand, so expansion stops at
`MAX_VERSES_PER_REF`.  A reference that long is not pointing anywhere a reader
would follow, and expanding it would cost more rows than the rest of the index
put together.  What gets truncated is recorded, so the number is never silently
low.
"""

from __future__ import annotations

import json
import re

from . import canon, db, taxonomy

#: A book token, then chapter:verse.  The same shape as the reference pattern
#: elsewhere in the app; kept separate so this module has no import cycle with
#: study.py, which is where the query-time version lived.
_REF = re.compile(r"\b(1|2|3)?\s?([A-Za-z][A-Za-z]{1,14})\s+(\d{1,3}):(\d{1,3})"
                  r"(?:\s*[-–—]\s*(\d{1,3}):?(\d{1,3}))?")

#: Bare chapter references -- "Ps 119", "Ro 8" -- appear in these articles too.
_CHAPTER = re.compile(r"\b(1|2|3)?\s?([A-Za-z][A-Za-z]{1,14})\s+(\d{1,3})\b(?!\s*:)")

#: Longest single reference that will be expanded.  "Ps 119" is 176 verses and is
#: worth having; a whole-book range would be thirty thousand and points nowhere a
#: reader would follow.
MAX_VERSES_PER_REF = 400

#: Longest *unit* that will be expanded, counting every reference in it together.
#: This is a different limit from the one above and was missing: capping only the
#: single-reference length was not enough, because the accumulator is per unit, so
#: an article with four hundred references in it exhausted the budget partway
#: through and every later reference was dropped.  Nave's article on Christ has
#: over a thousand; it was keeping its first four hundred and losing the rest,
#: and the truncation counter said so without anybody reading it.
MAX_MARKERS_PER_UNIT = 6000

#: Chapters expanded for a bare "Book N" reference.
MAX_CHAPTER_VERSES = 200

_topic_cache: dict | None = None


#: Resource types whose entries are topics indexed to verses.  A Fact book is one
#: article per topic, addressed to scripture -- Nave, Torrey, Hitchcock, the
#: Cyclopedia, Thompson.  A topical Bible is indexed at the other end of the same
#: relationship and is handled by the cross-reference table instead.
TOPIC_TYPES = ("FactBook",)


def _topic_modules() -> list[str]:
    """Modules whose entries are topics indexed to verses.

    Selected on resource type, not on `index_types`.  `index_types` looked more
    general and was much worse: 170 modules declare a topic or place index,
    including all hundred and forty-four gazetteer places, and their "references"
    are coordinates.  Indexing those would have stored tens of thousands of rows
    about places, to answer questions nobody asks of an atlas.

    A topic also has to be *addressed to verses*.  A Book that happens to mention
    "Ro 8" in a footnote is not a topic entry for Romans 8, and indexing it as one
    puts Westminster's Article VIII in the topics panel for Romans.
    """
    from .library import list_all
    # The taxonomy files the Klingon dictionaries under FactBook because they
    # have topic-shaped entries, but a Klingon-to-English lexicon contains no
    # biblical fact and no scripture reference.  Left in, its entries are keyed
    # FAITH, HOPE and LORD, and they take the top of every topic query while
    # never once citing a verse.  Excluded for the same reason as everywhere
    # else they appear -- see study._NOT_FACT_BOOKS.
    from .study import _NOT_FACT_BOOKS
    out = []
    for m in list_all():
        if m.type not in TOPIC_TYPES:
            continue
        low = (m.name or "").lower()
        if any(x in low for x in _NOT_FACT_BOOKS):
            continue
        out.append(m.id)
    return out


def _expand(text: str) -> tuple[list[str], int]:
    """OSIS keys for the references in `text`, and how many were truncated."""
    keys: list[str] = []
    truncated = 0
    seen = set()
    # Counts verses emitted for the reference currently being expanded, so one
    # enormous range cannot eat the unit's whole budget.
    run = [0]

    def add(osis_key: str) -> None:
        if run[0] >= MAX_VERSES_PER_REF:
            nonlocal truncated
            truncated += 1
            return
        if len(keys) >= MAX_MARKERS_PER_UNIT:
            truncated += 1
            return
        if osis_key not in seen:
            seen.add(osis_key)
            keys.append(osis_key)
            run[0] += 1

    for m in _REF.finditer(text or ""):
        run[0] = 0
        num, tok, ch, vs, _c2, v2 = m.groups()
        book = num + tok if num else tok
        rr = canon.parse_ref(f"{book} {ch}:{vs}")
        if rr is None:
            continue
        try:
            end_v = int(v2) if v2 else int(vs)
        except (TypeError, ValueError):
            end_v = int(vs)
        # "Ex 6:16-20" and "Ex 6:16-18" both mean sixteen to twenty; a reversed
        # range is a typo in the source, not a request to read backwards.
        if end_v < int(vs):
            end_v = int(vs)
        span = min(end_v, int(vs) + MAX_VERSES_PER_REF) - int(vs) + 1
        for r in rr.refs():
            if span <= 1:
                add(r.osis_id())
                break
            first = r.chapter * 1000 + r.verse
            for k in range(span):
                add(canon.Ref(r.book, r.chapter, r.verse + k).osis_id())
            break

    # Bare chapter references -- "Ps 119", "Ro 8" -- which these articles use
    # too.  The verse count comes from the installed Bible's own versification
    # rather than from a table here, because "how many verses are in Psalm 119"
    # is a property of the Bible the reader has, and guessing it would put
    # markers on verses that do not exist.
    for m in _CHAPTER.finditer(text or ""):
        run[0] = 0
        num, tok, ch = m.groups()
        book = num + tok if num else tok
        rr = canon.parse_ref(f"{book} {ch}")
        if rr is None:
            continue
        first = next(iter(rr.refs()), None)
        if first is None or not first.book:
            continue
        n = _chapter_verse_count(first.book, first.chapter)
        if not n:
            continue
        for v in range(1, min(n, MAX_CHAPTER_VERSES) + 1):
            add(canon.Ref(first.book, first.chapter, v).osis_id())
    return keys, truncated


_V11N: dict[tuple[str, int], int] = {}


def _chapter_verse_count(osis_book: str, chapter: int) -> int:
    """Verses in a chapter, taken from an installed Bible's versification."""
    k = (osis_book, chapter)
    if k in _V11N:
        return _V11N[k]
    n = 0
    try:
        rows = db.connect().execute(
            "SELECT v.verse FROM unit v JOIN module m ON m.id = v.module_id "
            "WHERE m.installed_at>0 AND m.type='Bible' AND v.book=? "
            "AND v.chapter=? ORDER BY v.verse DESC LIMIT 1",
            (osis_book, chapter)).fetchone()
        if rows is not None:
            n = int(rows["verse"] or 0)
    except Exception:
        n = 0
    _V11N[k] = n
    return n


def build(modules: list[str] | None = None, *, verbose: bool = False) -> dict:
    """Populate topic markers for every topic-indexed module.

    Safe to re-run: rows are replaced per module, so a module re-indexed or
    re-installed does not accumulate stale references pointing at text that has
    changed.
    """
    conn = db.connect()
    mods = modules if modules is not None else _topic_modules()
    total_rows = 0
    total_trunc = 0
    per_module = {}
    for mid in mods:
        rows = conn.execute(
            "SELECT key, text FROM unit WHERE module_id=?", (mid,)).fetchall()
        if not rows:
            continue
        buf = []
        trunc = 0
        for r in rows:
            keys, t = _expand(r["text"] or "")
            trunc += t
            for k in keys:
                buf.append((mid, r["key"], k, "topic"))
        conn.execute("DELETE FROM xref WHERE module_id=? AND kind='topic'", (mid,))
        if buf:
            conn.executemany(
                "INSERT OR REPLACE INTO xref(module_id,from_key,to_key,kind) "
                "VALUES(?,?,?,?)", buf)
        conn.commit()
        per_module[mid] = len(buf)
        total_rows += len(buf)
        total_trunc += trunc
        if verbose:
            print(f"  {mid:<30} {len(rows):>6} entries -> {len(buf):>7} markers")
    # Which modules were scanned, so coverage can tell "not indexed yet" from
    # "scanned and found nothing to index".  Hitchcock's Bible Names is the
    # second: it gives the meaning of a name and cites no verses, so a build that
    # stores no rows for it has done its job, and saying "unindexed" sends
    # somebody hunting a fault that is not there.
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('topic_scanned',?)",
                 (json.dumps(sorted(per_module)),))
    conn.commit()
    return {"ok": True, "modules": len(per_module), "rows": total_rows,
            "truncated": total_trunc, "per_module": per_module,
            "note": f"{total_trunc} reference(s) exceeded the "
                    f"{MAX_VERSES_PER_REF}-verse limit for one reference, or "
                    f"the {MAX_MARKERS_PER_UNIT}-marker limit for one entry"}


def topics_reaching(module_ids: list[str], key: str) -> list[dict]:
    """Topic articles that cite this verse.  An index lookup, not a scan.

    The module list matters: only Fact-book style modules carry topic entries, so
    asking a commentary for its own topic markers would return nothing, and
    asking every module would return the commentaries' own cross-references under
    a misleading heading.
    """
    if not module_ids or not key:
        return []
    conn = db.connect()
    ph = ",".join("?" * len(module_ids))
    return [{"module_id": r["module_id"], "key": r["from_key"],
             "title": r["title"] or r["from_key"]}
            for r in conn.execute(
                f"SELECT DISTINCT x.module_id, x.from_key, u.title "
                f"FROM xref x LEFT JOIN unit u "
                f"  ON u.module_id = x.module_id AND u.key = x.from_key "
                f"WHERE x.kind='topic' AND x.to_key=? "
                f"AND x.module_id IN ({ph}) ORDER BY x.module_id, x.from_key",
                [key, *module_ids])]


def coverage() -> dict:
    """How much of the topic corpus is actually indexed."""
    conn = db.connect()
    mods = _topic_modules()
    indexed = [r["module_id"] for r in conn.execute(
        "SELECT DISTINCT module_id FROM xref WHERE kind='topic'")]
    units = 0
    for mid in mods:
        units += conn.execute("SELECT COUNT(*) c FROM unit WHERE module_id=?",
                              (mid,)).fetchone()["c"]
    have = {r["module_id"]: r["c"] for r in conn.execute(
        "SELECT module_id, COUNT(*) c FROM xref WHERE kind='topic' "
        "GROUP BY module_id")}
    # A Fact book with no markers is not a failure: Hitchcock's Bible Names gives
    # the meaning of a name and cites nothing, so it has nothing to index.
    # Reporting it as "unindexed" would be wrong and would send somebody looking
    # for a bug that is not there.
    row = conn.execute(
        "SELECT value FROM meta WHERE key='topic_scanned'").fetchone()
    scanned: set[str] = set()
    if row:
        try:
            scanned = set(json.loads(row["value"] or "[]"))
        except (json.JSONDecodeError, TypeError):
            scanned = set()
    no_refs = sorted(m for m in scanned if have.get(m, 0) == 0)
    unindexed = [m for m in mods if m not in scanned]
    return {"topic_modules": len(mods), "scanned": len(scanned),
            "modules_with_markers": len(have), "units": units,
            "markers": sum(have.values()),
            "unindexed": unindexed, "indexed_but_no_references": no_refs,
            "note": ("every module with references to index is indexed" if not
                     unindexed else
                     f"{len(unindexed)} module(s) not indexed yet")}

def find_articles(term: str, module_ids: list[str] | None = None,
                  *, limit: int = 40) -> list[dict]:
    """Fact-book articles whose entry is about `term`.

    This is what `topic:faith` means: the article on faith, not every unit in the
    library containing the word.  The lookup is against the article key, which is
    the topic itself -- Nave's entries are keyed "FORGIVENESS", Torrey's
    "FORGIVENESS, OF GOD" -- and the title is checked as well so that a query
    matches the article a reader would look for by name.

    Keys are compared folded and with punctuation ignored, because these
    catalogues style the same topic several ways ("FAITH-UNBELIEF",
    "AFFLICTIONS, THE", "ISRAEL, GOD'S") and a reader typing "faith" expects to
    find the article either way.
    """
    if not term:
        return []
    from .library import list_all
    mods = module_ids if module_ids is not None else _topic_modules()
    wanted = _norm_topic(term)
    if not wanted:
        return []
    ph = ",".join("?" * len(mods))
    rows = db.connect().execute(
        f"SELECT module_id, key, title FROM unit WHERE module_id IN ({ph})",
        list(mods)).fetchall()
    exact, starts, contains = [], [], []
    for r in rows:
        k = _norm_topic(r["key"] or "")
        t = _norm_topic(r["title"] or "")
        cand = k or t
        if not cand:
            continue
        item = {"module_id": r["module_id"], "key": r["key"],
                "title": r["title"] or r["key"]}
        if cand == wanted:
            exact.append(item)
        elif cand.startswith(wanted) or wanted.startswith(cand):
            starts.append(item)
        elif wanted in cand:
            contains.append(item)
    out = exact + starts + contains
    return out[:limit]


def _norm_topic(s: str) -> str:
    """Folded, punctuation-free, lower case."""
    import unicodedata as _u
    t = _u.normalize("NFKD", str(s or ""))
    t = "".join(c for c in t if not _u.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "", t)

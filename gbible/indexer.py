"""Indexing: turn parsed units into a searchable, cross-linkable library.

The `marker` table is the important part.  It stores every token with its word
ordinal and character offset, which is what lets the search engine evaluate
`WITHIN n WORDS` / `WITHIN n CHARS` exactly, and evaluate `EQUALS` / `IN` /
`INTERSECTS` as set algebra over marker spans rather than as string matching.
That is the model made concrete: the index stores enough to answer queries
without re-reading the source text.
"""

from __future__ import annotations

import bisect
import json
import re
import time
from dataclasses import dataclass, field
from typing import Iterable, Iterator

from . import canon, db, library, markup, taxonomy, topicindex
from .markup import Seg


@dataclass
class UnitIn:
    key: str
    label: str
    segs: list[Seg] = field(default_factory=list)
    title: str = ""
    markup: str = ""
    book: str = ""
    chapter: int = 0
    verse: int = 0
    extra: dict = field(default_factory=dict)


def _last_per_key(rows: list[tuple]) -> list[tuple]:
    """The last row for each (module_id, unit_key).

    The importer may yield the same key more than once -- a passage with
    several sections under one verse, say -- and the unit table keeps only
    the last of them, because it is written with INSERT OR REPLACE.  The
    full-text index has to keep the last too, or it says something different
    from the unit table about what is in the library.

    It did not.  The index carried 536 rows for Barnes' notes where the unit
    table had 304, and 6,374 for the cross-references where the unit table
    had 4,868 -- seventy-seven percent more than there was, every row a
    duplicate of one already there.  The main search de-duplicated them
    again in the query, so the reader never saw a repeat; but the index was
    carrying them, and the fallback path -- one query per module, used when
    the engine cannot express a search -- did not.
    """
    out: dict[tuple, tuple] = {}
    for r in rows:
        out[(r[0], r[1])] = r
    return list(out.values())


class Indexer:
    def __init__(self, module_id: str, *, batch: int = 20000):
        self.mid = module_id
        self.batch = batch
        self.conn = db.connect()
        self._buf_units: list[tuple] = []
        self._buf_markers: list[tuple] = []
        self._buf_xrefs: list[tuple] = []
        self._buf_fts: list[tuple] = []
        self.stats = dict(units=0, words=0, chars=0, strongs=0, lemmas=0,
                          morphs=0, notes=0, xrefs=0, headings=0, redwords=0,
                          chapters=set(), books=set())

    # ------------------------------------------------------------------ main
    def add(self, u: UnitIn) -> None:
        # One flatten pass produces both the searchable text and the span table
        # the display layer uses, so the words are stored once.
        # Notes are excluded from the searchable text (so a footnote's
        # wording does not outrank the passage that contains it) but their
        # bodies are preserved in the span table so they render as footnotes.
        note_segs = [seg for seg in (u.segs or [])
                     if getattr(seg, "kind", None) == "note"]
        text, spans = markup.segs_flatten(u.segs, notes=False)
        blob = markup.spans_to_json(text, spans, notes=note_segs)
        full, _ = markup.segs_flatten(u.segs, notes=True)
        extra = dict(u.extra or {})
        markers, strongs, lemmas, morphs, notes, xrefs, reds, heads = \
            self._scan(u.segs, text, u.key)
        self.stats["units"] += 1
        self.stats["words"] += len(text.split())
        self.stats["chars"] += len(full)
        self.stats["strongs"] += strongs
        self.stats["lemmas"] += lemmas
        self.stats["morphs"] += morphs
        self.stats["notes"] += notes
        self.stats["xrefs"] += len(xrefs)
        self.stats["redwords"] += reds
        self.stats["headings"] += heads
        if u.book:
            self.stats["books"].add(u.book)
        if u.chapter:
            self.stats["chapters"].add((u.book, u.chapter))
        self._buf_units.append((
            self.mid, u.key, self.stats["units"], u.book or None, u.chapter or None,
            u.verse or None, u.label, u.title or "", text, blob,
            0, len(full), len(text.split()),
            json.dumps({**extra, "has_strongs": bool(strongs),
                        "lemmas": lemmas, "morphs": morphs,
                        "notes": notes, "has_red": bool(reds)}),
        ))
        for m in markers:
            self._buf_markers.append(m)
        for x in xrefs:
            self._buf_xrefs.append((self.mid, u.key, x, "ref"))
        self._buf_fts.append((self.mid, u.key, u.title or "", text))
        self._maybe_flush()

    def add_many(self, units: Iterable[UnitIn]) -> None:
        for u in units:
            self.add(u)

    # ----------------------------------------------------------------- flush
    def _maybe_flush(self) -> None:
        if len(self._buf_units) >= self.batch:
            self.flush()

    def flush(self) -> None:
        c = self.conn
        if self._buf_units:
            c.executemany(
                "INSERT OR REPLACE INTO unit(module_id,key,ord,book,chapter,verse,"
                "ref_label,title,text,markup,char_start,char_len,word_count,extra) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", self._buf_units)
            self._buf_units.clear()
        if self._buf_markers:
            c.executemany(
                "INSERT OR REPLACE INTO marker(module_id,kind,value,unit_key,pos,"
                "surface) VALUES(?,?,?,?,?,?)", self._buf_markers)
            self._buf_markers.clear()
        if self._buf_fts:
            c.executemany("INSERT INTO unit_fts(module_id,unit_key,title,text) "
                          "VALUES(?,?,?,?)", _last_per_key(self._buf_fts))
            self._buf_fts.clear()
        if self._buf_xrefs:
            c.executemany(
                "INSERT OR REPLACE INTO xref(module_id,from_key,to_key,kind) "
                "VALUES(?,?,?,?)", self._buf_xrefs)
            self._buf_xrefs.clear()
        c.commit()

    # ----------------------------------------------------------------- scan
    def _scan(self, segs: list[Seg], text: str, unit_key: str):
        """Emit marker rows for every word, and collect statistics.

        Marker position is a *character* offset into the unit's search text and a
        *word* ordinal.  Both are stored because the search engine offers both
        metrics, exactly as this index distinguishes WORDS from CHARS.
        """
        markers: list[tuple] = []
        n_strongs = n_lemma = n_morph = n_notes = n_xref = n_red = n_head = 0
        xrefs: list[str] = []

        # One pass over the text gives a word ordinal per character offset, so a
        # segment offset maps to a word position in O(log n) instead of
        # re-tokenising the whole text for every tagged word.
        starts = [cs for _w, cs, _ce in db.words(text)]
        char_i = 0
        for s in segs:
            seg_start = char_i
            if s.is_text():
                chunk = s.text
                if not chunk:
                    continue
                if s.kind == "red" or s.attrs.get("wj"):
                    n_red += len(chunk.split())
                if s.kind in ("title", "heading"):
                    n_head += 1
                char_i += len(chunk)
            elif s.kind in ("break", "para"):
                char_i += 1          # segs_flatten emits a single newline
            elif s.kind == "note":
                n_notes += 1
            elif s.kind == "xref":
                n_xref += 1
                for tgt in _split_xref(s.value):
                    if tgt and tgt != unit_key:
                        xrefs.append(tgt)
            elif s.kind == "heading":
                n_head += 1
            if s.kind == "strongs":
                # Positions are one-based word ordinals.  Capture the segment's
                # start before advancing char_i above; using its end shifted all
                # tagged words to the following token in sequence searches.
                widx = bisect.bisect_right(starts, seg_start)
                attrs = s.attrs or {}
                if s.value or s.lemma:
                    search_field = str(attrs.get("search_field") or attrs.get("field") or
                                       ("red-letter" if attrs.get("wj") else "main-text")).strip().lower()
                    if search_field:
                        markers.append((self.mid, "field", search_field, unit_key,
                                        widx, s.text or search_field))
                for n in (s.value or "").split():
                    ns = canon.normalise_strongs(n)
                    if not ns:
                        continue
                    markers.append((self.mid, "strongs", ns, unit_key, widx,
                                    s.text or ns))
                    n_strongs += 1
                if s.lemma:
                    for morph in s.lemma.split():
                        morph = morph.strip()
                        if not morph:
                            continue
                        markers.append((self.mid, "morph", morph, unit_key,
                                        widx, s.text or morph))
                        n_morph += 1
                lexical = (s.attrs or {}).get("lemma", "")
                for lemma in re.split(r"[|;,]", str(lexical)):
                    lemma = lemma.strip()
                    if not lemma:
                        continue
                    markers.append((self.mid, "lemma", lemma, unit_key,
                                    widx, s.text or lemma))
                    n_lemma += 1
        return markers, n_strongs, n_lemma, n_morph, n_notes, xrefs, n_red, n_head

    # A dead branch used to sit here.  `_topic_markers` returned `[]`, so the loop
    # over its result never ran, so nothing noticed that it appended an
    # **eleven**-field tuple to a list `flush()` inserts into `marker` with
    # **six** columns.  It was not merely unused: it was a trap, and the topics it
    # was reaching for are not lost -- `gbible.topicindex` writes them as `xref`
    # rows of kind `topic`, which is the same fact in the same shape, so a Fact
    # book's scripture references are indexed, searchable by `topic:` and read by
    # `study.topics_at`.  Writing them a second time as marker rows would have
    # duplicated every topic in the library, so the branch is gone rather than
    # filled in.  `study.topics_at` keeps its text-scan fallback for a Fact book
    # whose references were never extracted.

    # ------------------------------------------------------------- finalise
    def finalise(self) -> dict:
        self.flush()
        c = self.conn
        s = self.stats
        # ---- Strong's roll-up -------------------------------------------
        # ONE grouped pass.  The marker primary key is
        # (module_id, kind, value, unit_key, pos), so a per-value COUNT() on
        # (module_id, value) cannot use the index and degenerates into a full
        # table scan per Strong's number -- which for a Bible is ~5e9 row visits.
        rows = c.execute(
            "SELECT value, MAX(surface) surface, COUNT(*) n FROM marker "
            "WHERE module_id=? AND kind='strongs' GROUP BY value", (self.mid,)
        ).fetchall()
        existing: dict[str, list] = {}
        for r in c.execute("SELECT strongs, word, lemma, modules FROM strongs"):
            try:
                mods = json.loads(r["modules"] or "[]")
            except (json.JSONDecodeError, TypeError):
                mods = [x.strip().strip('"')
                        for x in (r["modules"] or "").split(",") if x.strip()]
            existing[r["strongs"]] = [r["word"] or "", r["lemma"] or "",
                                      mods if isinstance(mods, list) else [], 0]
        for r in rows:
            v = r["value"]
            rec = existing.setdefault(v, ["", "", [], 0])
            if not rec[0]:
                rec[0] = r["surface"] or ""
            if self.mid not in rec[2]:
                rec[2] = rec[2] + [self.mid]
        for r in rows:
            existing[r["value"]][3] = r["n"]
        c.executemany(
            "INSERT INTO strongs(strongs,word,lemma,count,modules) VALUES(?,?,?,?,?) "
            "ON CONFLICT(strongs) DO UPDATE SET "
            "word=COALESCE(NULLIF(excluded.word,''),strongs.word), "
            "count=strongs.count+excluded.count, modules=excluded.modules",
            [(v, rec[0], rec[1], rec[3], json.dumps(rec[2]))
             for v, rec in existing.items()])

        # ---- versification ---------------------------------------------
        if s["chapters"]:
            per_book: dict[str, dict[int, int]] = {
                b: {} for b in s["books"]}
            rows = c.execute(
                "SELECT book, chapter, MAX(verse) v FROM unit WHERE module_id=? "
                "AND book IS NOT NULL GROUP BY book, chapter", (self.mid,)).fetchall()
            for r in rows:
                per_book.setdefault(r["book"], {})[r["chapter"]] = r["v"]
            per_book = {b: ch for b, ch in per_book.items() if ch}
            for book, chmap in per_book.items():
                arr = [chmap.get(i, 0) for i in range(1, max(chmap) + 1)]
                c.execute("INSERT OR REPLACE INTO versification(module_id,book,chapters) "
                          "VALUES(?,?,?)", (self.mid, book, json.dumps(arr)))
        c.commit()
        return {
            "units": s["units"],
            "words": s["words"],
            "chars": s["chars"],
            "strongs": s["strongs"],
            "morphs": s["morphs"],
            "notes": s["notes"],
            "xrefs": s["xrefs"],
            "redwords": s["redwords"],
            "headings": s["headings"],
            "books": len(s["books"]),
            "chapters": len(s["chapters"]),
        }

    # ------------------------------------------------------ versification
    def module_verse_counts(self, book: str) -> list[int]:
        r = self.conn.execute(
            "SELECT chapters FROM versification WHERE module_id=? AND book=?",
            (self.mid, book)).fetchone()
        if r and r["chapters"]:
            try:
                return json.loads(r["chapters"])
            except json.JSONDecodeError:
                return []
        return []


def _span_for(char_i: int, length: int) -> tuple[int, int]:
    """Marker span as a permille fraction of the unit, so `IN` / `INTERSECTS`
    can be evaluated without knowing the unit's length up front."""
    return char_i * 1000, (char_i + max(1, length)) * 1000


def _split_xref(v: str) -> list[str]:
    out = []
    for part in re.split(r"[,;\s]+", v or ""):
        part = part.strip()
        if not part:
            continue
        r = canon.parse_osis_ref(part)
        if r:
            out.append(r.start.osis_id())
        elif " " in part:
            rr = canon.parse_ref(part)
            if rr:
                out.append(rr.start.osis_id())
    return out


# --------------------------------------------------------------------------
# High-level: run a whole import with progress reporting
# --------------------------------------------------------------------------

def run_import(module_id: str, units: Iterator[UnitIn], *,
               progress=None, **module_fields) -> dict:
    conn = db.connect()
    lib = library.get(module_id)
    if lib is not None:
        library.mark_removed(conn, module_id)
        conn.commit()
        # Re-installing is a removal too, and it has to say so.  `posindex`
        # keeps a per-module "indexed" record and deliberately does not verify
        # it -- proving it would mean a scan of the whole thirty-six-million-row
        # postings table -- so it trusts `forget()`.  Only `remove_module` used
        # to call that, and re-installing went through `mark_removed` directly,
        # which leaves the record intact.
        #
        # The consequence is quiet and looks like a search bug rather than a
        # bookkeeping one: a module re-imported from a fixed importer keeps the
        # postings built from its *old* text.  Re-installing Gesenius' grammar
        # after the transclusion fix left 173 units holding 2.7 million
        # characters, the full-text index matched "preposition" on 80 of them,
        # and the positional index had no posting for the word anywhere in the
        # grammar -- so searching the module returned nothing at all.
        try:
            from . import posindex
            posindex.forget(module_id)
        except Exception:                               # noqa: BLE001
            # Best-effort, like the removal path's.  A stale index is
            # recoverable by rebuilding; refusing to install a book over it is
            # not a trade worth making.
            db.log_history("index",
                           f"{module_id}: positional index not invalidated")
    mid = library.register(conn, id=module_id, installed_at=time.time(),
                           **module_fields)
    idx = Indexer(mid)
    n = 0
    t0 = time.time()
    try:
        for u in units:
            idx.add(u)
            n += 1
            if progress and n % 500 == 0:
                progress(n, n - 1 + 1)
    except Exception as e:  # partial import is still useful, but say so
        st = idx.finalise()
        conn.execute("UPDATE module SET error=? WHERE id=?", (f"{type(e).__name__}: {e}", mid))
        conn.commit()
        raise
    st = idx.finalise()
    # ---- apply derived capabilities -------------------------------------
    conn.execute(
        "UPDATE module SET chapters=?, verses=?, entries=?, has_strongs=?, "
        "has_morph=?, has_notes=?, has_xref=?, has_redletter=?, heading_count=?, "
        "v11n_source=?, error=NULL WHERE id=?",
        (st["chapters"], st["units"] if st["books"] else 0, st["units"],
         int(st["strongs"] > 0), int(st["morphs"] > 0), int(st["notes"] > 0),
         int(st["xrefs"] > 0), int(st["redwords"] > 0), st["headings"],
         "module" if st["books"] else "builtin", mid))
    conn.commit()
    m = library.get(mid)
    if m is not None:
        m.v11n = m.v11n or "KJV"
        fixes = {"v11n": m.v11n}
        # A text imported as a Devotional but with no M.D keys in it is a book.
        # Saying so is better than showing an empty calendar forever.
        n_dates = conn.execute(
            "SELECT COUNT(*) c FROM unit WHERE module_id=? AND key LIKE '%.%' "
            "AND key NOT LIKE '%.%:%' AND key NOT LIKE '%.%.%'",
            (mid,)).fetchone()["c"]
        if m.type == "Devotional" and n_dates == 0 and st["units"] > 0:
            fixes["type"] = "Book"
        conn.execute(
            "UPDATE module SET v11n=?, type=COALESCE(?, type) WHERE id=?",
            (fixes["v11n"], fixes.get("type"), mid))
        conn.commit()
        # A Fact book addresses scripture from inside prose, so the references
        # are extracted into the topic marker index here rather than left to be
        # found by scanning the bodies when somebody opens a verse guide.  Built
        # for this module alone: a full rebuild would touch every Fact book on
        # every install, and this one is the only thing that changed.
        if (m.type or "") in topicindex.TOPIC_TYPES:
            try:
                tr = topicindex.build([mid])
                st["topic_markers"] = tr["rows"]
            except Exception:
                # Not worth failing an install over: the verse guide falls back to
                # scanning the text when the index is absent.
                st["topic_markers"] = 0
    st["module_id"] = mid
    st["seconds"] = round(time.time() - t0, 2)
    st["units_per_sec"] = round(n / max(0.01, time.time() - t0), 1)
    db.log_history("install", f"Indexed {m.name if m else mid}", st)
    return st

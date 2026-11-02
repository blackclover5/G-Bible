"""The library: installed modules, and the read API every pane goes through.

Two ideas drive this module:

1.  A resource is addressed by its **milestone type** (`bibleVerse`, `headword`,
    `date`, `topic`, ...).  Two panes may be synchronised only when their
    milestone types intersect.  Everything else follows from that rule.

2.  A pane stores a **cursor into the resource's index space**, never a pixel
    offset.  That is why the same cursor can drive a Bible pane, a commentary
    pane and a lexicon pane at once.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import canon, db, markup, taxonomy
from .markup import RenderOpts, Seg


# --------------------------------------------------------------------------

# Types whose units are the text of scripture itself, as opposed to commentary
# on it.  One list, because three call sites had each grown their own and they
# did not agree.
#
# "Bible" on its own was the test for years and it is the wrong test.  It is
# wrong exactly where it matters most: the SBL Greek New Testament is typed
# OriginalLanguage and the Aleppo Codex Manuscript, so asking for a comparison
# between Textus Receptus and SBLGNT -- the single comparison a reader of the
# Greek text most wants -- found nothing and said "need two or more installed
# translations with text for that verse".  Both verses are right there.
VERSE_TEXT_TYPES = ("Bible", "OriginalLanguage", "Manuscript")


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "x"


@dataclass
class Module:
    id: str
    name: str
    abbrev: str = ""
    type: str = "Other"
    subject: list[str] = field(default_factory=list)
    lang: str = ""
    lang_name: str = ""
    version: str = ""
    source: str = ""
    source_name: str = ""
    source_url: str = ""
    download_url: str = ""
    format: str = ""
    license: str = ""
    rights: str = ""
    description: str = ""
    about: str = ""
    author: str = ""
    year: str = ""
    size_bytes: int = 0
    installed_at: float = 0.0
    folder: str = ""
    path: str = ""
    v11n: str = "KJV"
    v11n_source: str = "builtin"
    chapters: int = 0
    verses: int = 0
    entries: int = 0
    has_strongs: bool = False
    has_morph: bool = False
    has_lemma: bool = False
    has_notes: bool = False
    has_xref: bool = False
    has_redletter: bool = False
    index_types: list[str] = field(default_factory=list)
    priority: int = 0
    favorite: bool = False
    enabled: bool = True
    error: str = ""
    raw_meta: dict = field(default_factory=dict)

    @property
    def type_effective(self) -> str:
        """The type after placement overrides (TSK is filed as Commentary but
        is a cross-reference set).  Reading and linking both follow this, so a
        module can never be routed one way and read another."""
        from . import placement
        return placement.type_for(self.id, self.type)

    @property
    def reader(self) -> str:
        from . import placement
        return placement.slot_for_type(self.type_effective).reader

    @property
    def slot(self) -> str:
        from . import placement
        return placement.slot_for_type(self.type_effective).id

    @property
    def is_bible(self) -> bool:
        return self.type in ("Bible", "StudyBible", "ParallelBible",
                             "OriginalLanguage", "Manuscript")

    def link_types(self) -> set[str]:
        return set(self.index_types or taxonomy.index_types_for(self.type))

    @classmethod
    def from_row(cls, r) -> "Module":
        d = dict(r)
        for k in ("subject", "index_types", "raw_meta"):
            try:
                d[k] = json.loads(d.get(k) or "[]")
            except (json.JSONDecodeError, TypeError):
                d[k] = {} if k == "raw_meta" else []
        for k in ("has_strongs", "has_morph", "has_lemma", "has_notes",
                  "has_xref", "has_redletter", "favorite", "enabled", "verified"):
            if k in d:
                d[k] = bool(d.get(k))
        d.pop("heading_count", None)
        d.pop("notes_count", None)
        d.pop("xrefs_count", None)
        d.pop("heads_count", None)
        d.pop("redwords", None)
        d.pop("error", None) if d.get("error") is None else None
        # Re-derive the language name on the way out, not just on install.  It is
        # stored, so a row written before a code had a friendly name keeps the
        # bare code forever -- which is how four maps ended up listed under a
        # language called "und" instead of "Undetermined".
        if d.get("lang"):
            d["lang_name"] = taxonomy.language_name(d["lang"])
        # Same reasoning for a title mangled upstream: the name is stored, so
        # repairing it only on install would leave every already-installed copy
        # wrong.  Fix it on the way out, where every consumer reads it.
        for k in ("name", "description", "about", "title", "author",
                  "source_name", "abbrev"):
            if d.get(k):
                d[k] = taxonomy.fix_text(d[k])
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in allowed})


def get(module_id: str) -> Module | None:
    conn = db.connect()
    r = conn.execute("SELECT * FROM module WHERE id=?", (module_id,)).fetchone()
    return Module.from_row(r) if r else None


def module_dir(module_id: str) -> Path | None:
    """Where a module's files actually are, as opposed to where they were.

    `module.path` is an absolute path written at install time, and nothing else
    records that location -- so moving the project folder breaks every installed
    module at once.  The files moved *with* the database and the text is all in
    the index, so the library keeps reading perfectly well, and the only visible
    symptom is that re-indexing a module fails and "add audio" cannot find its
    files.  `module.folder` still names the directory, and it is relative, so
    resolution prefers the library this process is actually using and falls back
    to the recorded path.

    This is why the library is portable: nothing needs rewriting for the folder
    to work, and `repair_paths()` only tidies the stored value afterwards.
    """
    m = get(module_id) if not isinstance(module_id, Module) else module_id
    if m is None:
        return None
    if m.folder:
        p = db.app_dir() / "modules" / m.folder
        if p.exists():
            return p
    if m.path:
        p = Path(m.path)
        if p.exists():
            return p
    return None


def repair_paths() -> dict:
    """Rewrite recorded module paths that no longer exist.

    Run when the library directory itself has moved, which is the one event that
    invalidates a whole column at once.  Idempotent and cheap: a single
    comparison per start, and nothing at all once the marker matches.

    Not the same thing as resolving on the fly -- `module_dir` already works
    either way.  This exists so the stored value stops being a lie: it is what
    an export or a support answer would quote, and a path naming a folder that
    is not there is worse than a blank one.
    """
    lib = db.app_dir()
    conn = db.connect()
    row = conn.execute(
        "SELECT value FROM meta WHERE key='library_path'").fetchone()
    if row and row["value"] == str(lib):
        return {"ok": True, "changed": 0, "skipped": True}
    fixed, checked = [], 0
    for m in list_all(installed_only=False):
        if not m.installed_at or not m.folder:
            continue
        checked += 1
        want = lib / "modules" / m.folder
        if not want.exists() or str(want) == (m.path or ""):
            continue
        conn.execute("UPDATE module SET path=? WHERE id=?", (str(want), m.id))
        fixed.append(m.id)
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('library_path',?)",
                 (str(lib),))
    if fixed:
        db.log_history("repair", f"{len(fixed)} module paths repointed at {lib}")
    conn.commit()
    return {"ok": True, "changed": len(fixed), "checked": checked,
            "library_path": str(lib)}


def list_all(*, type_: str | None = None, lang: str | None = None,
             source: str | None = None, search: str | None = None,
             installed_only: bool = True, subject: str | None = None,
             order: str = "priority DESC, name ASC") -> list[Module]:
    conn = db.connect()
    q = "SELECT * FROM module WHERE 1=1"
    a: list[Any] = []
    if installed_only:
        q += " AND installed_at > 0"
    if type_:
        q += " AND type=?"
        a.append(type_)
    if lang:
        q += " AND lang=?"
        a.append(lang)
    if source:
        q += " AND source=?"
        a.append(source)
    if subject:
        q += " AND subject LIKE ?"
        a.append(f'%"{subject}"%')
    if search:
        q += " AND (name LIKE ? OR abbrev LIKE ? OR description LIKE ? OR author LIKE ?)"
        a += [f"%{search}%"] * 4
    q += f" ORDER BY {order}"
    return [Module.from_row(r) for r in conn.execute(q, a)]


def languages_present() -> list[tuple[str, int]]:
    conn = db.connect()
    return [(r["lang"] or "und", r["n"]) for r in conn.execute(
        "SELECT lang, COUNT(*) n FROM module WHERE installed_at>0 "
        "GROUP BY lang ORDER BY n DESC")]


# --------------------------------------------------------------------------
# Link-set compatibility -- the rule the whole workspace rests on
# --------------------------------------------------------------------------

def can_link(a: str, b: str) -> bool:
    ma, mb = get(a), get(b)
    if not ma or not mb:
        return False
    inter = ma.link_types() & mb.link_types()
    return bool(inter)


def link_map() -> dict[str, list[str]]:
    mods = list_all()
    out: dict[str, list[str]] = {}
    for m in mods:
        out[m.id] = [o.id for o in mods
                     if o.id != m.id and (m.link_types() & o.link_types())]
    return out


def link_index_types(a: str, b: str) -> list[str]:
    ma, mb = get(a), get(b)
    if not ma or not mb:
        return []
    return sorted(ma.link_types() & mb.link_types())


# --------------------------------------------------------------------------
# Reading content
# --------------------------------------------------------------------------

@dataclass
class Item:
    key: str
    label: str
    title: str = ""
    html: str = ""
    text: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class Content:
    module_id: str
    module_name: str
    kind: str                       # verse | article | book | date | image | topic
    items: list[Item] = field(default_factory=list)
    cursor: dict = field(default_factory=dict)
    ref_label: str = ""
    section_title: str = ""
    context: dict = field(default_factory=dict)
    notices: list[str] = field(default_factory=list)


_PANE_DEFAULTS = dict(
    show_strongs=False, show_notes=True, show_headings=True, show_red=True,
    show_xrefs=True, verse_per_line=False, show_add=True, font_scale=100,
)


def _opts(opts: dict | None) -> RenderOpts:
    o = dict(_PANE_DEFAULTS)
    o.update({k: v for k, v in (opts or {}).items() if k in _PANE_DEFAULTS})
    return RenderOpts(
        show_strongs=bool(o["show_strongs"]), show_notes=bool(o["show_notes"]),
        show_headings=bool(o["show_headings"]), show_red=bool(o["show_red"]),
        show_xrefs=bool(o["show_xrefs"]), verse_per_line=bool(o["verse_per_line"]),
        show_add=bool(o["show_add"]),
        font_scale=int(o["font_scale"] or 100),
    )


def _render(item, o: RenderOpts) -> str:
    """Prefer the stored markup (re-parse) only when we have to.  Rendering from
    the segment stream keeps every format consistent."""
    segs = _segs_of(item)
    return markup.segs_html(segs, o)


#: Cleaned article text, keyed by `(module id, unit key)`, with the raw text's
#: length kept alongside.  `_segs_of` runs on every article the app renders, and
#: unwrapping the Catholic Encyclopedia's 9,935 templated articles costs 3.6ms
#: each -- which doubled the runtime of the search check that compares the
#: positional index against the text path, from 439s to 974s.
#:
#: Keyed by identity rather than by the text, because an `lru_cache` over the
#: article itself has to hash and compare several kilobytes on every call, and
#: that measured 1.9ms an article even on a hit -- most of the cost it was meant
#: to avoid.  The reader knows which unit it is rendering; that is an O(1) key.
#: The stored length is what makes it safe: a re-indexed, edited or replaced
#: unit has a different length and misses, rather than being served text cleaned
#: for something else.
_WIKI_CACHE: dict[tuple, tuple] = {}
_WIKI_CACHE_MAX = 20000


def _segs_of(item) -> list[Seg]:
    """Rebuild the display segments for a unit.

    `markup` holds the span table written at index time, so Strong's, footnotes,
    supplied words and words of Christ survive without storing the source markup
    twice.  Anything without a span table falls back to plain text.

    Wikisource-derived articles are unwrapped first.  Their text still carries
    the MediaWiki templates the page was written in -- the Catholic
    Encyclopedia's 9,935 articles each open `{{CE13| contributor = ...` -- and
    the span table was built over *that*, with every brace counted as a word.
    So when the text changes, the table no longer lines up and is discarded:
    these are encyclopaedia and grammar articles with no tagging in them to
    lose, and a span table pointing into text that has moved is worse than none.
    """
    if item.extra.get("_segs"):
        return item.extra["_segs"]
    text = item.text
    if "{{" in text or "[[" in text:
        ck = (item.extra.get("_mid", ""), item.key)
        got = _WIKI_CACHE.get(ck)
        if got is not None and got[0] == len(text):
            clean = got[1]
        else:
            clean = markup.strip_wikitext_uncached(text)
            if len(_WIKI_CACHE) >= _WIKI_CACHE_MAX:
                # Cleared rather than evicted: this holds a whole working set,
                # and picking a victim one at a time costs more than starting
                # again, which is a few milliseconds.
                _WIKI_CACHE.clear()
            _WIKI_CACHE[ck] = (len(text), clean)
        if clean != text:
            return markup.segs_from_span(clean, None)
    return markup.segs_from_span(text, item.extra.get("markup"))


def read(module_id: str, cursor: dict | None = None, opts: dict | None = None,
         span: str = "chapter", context: int = 1) -> Content:
    """Read content at a cursor.  This is the only function a pane calls."""
    m = get(module_id)
    if m is None:
        raise KeyError(module_id)
    cursor = dict(cursor or {})
    o = _opts(opts)
    conn = db.connect()

    # An explicit list of unit keys: this is what a passage list is.  Reading the
    # keys in the order given is the whole point, so they are not sorted and not
    # grouped -- a list is a path through the Bible, not a concordance.
    keys = cursor.get("keys") or []
    if keys and m.reader == "verse":
        return _read_keys(m, cursor, o, keys)
    if m.reader == "audio":
        from . import audio
        return audio.read(module_id, cursor)
    if m.reader == "verse":
        return _read_bible(m, cursor, o, span, context)
    if m.reader == "article":
        return _read_article(m, cursor, o, context)
    if m.reader == "date":
        return _read_date(m, cursor, o)
    if m.reader == "book":
        return _read_book(m, cursor, o)
    if m.reader == "topic":
        return _read_topic(m, cursor, o, context)
    if m.reader == "image":
        return _read_image(m, cursor, o)
    return Content(m.id, m.name, "book", cursor=cursor)


def _read_keys(m: Module, cursor: dict, o: RenderOpts,
               keys: list) -> Content:
    """Read a saved list of references, in the order the user put them in."""
    conn = db.connect()
    items: list[Item] = []
    missing: list[str] = []
    for k in keys:
        row = conn.execute("SELECT * FROM unit WHERE module_id=? AND key=?",
                           (m.id, k)).fetchone()
        if row is None:
            missing.append(k)
            continue
        items.append(_mk_item(row, o))
    c = Content(m.id, m.name, "verse", cursor=cursor)
    c.items = items
    c.ref_label = cursor.get("list_name") or f"{len(items)} passages"
    c.section_title = cursor.get("list_name") or ""
    if missing:
        # said out loud rather than dropped: a list that quietly loses entries
        # is worse than one that tells you which are missing
        c.extra_missing = missing
    return c


def _mk_item(row, o: RenderOpts, *, with_html=True) -> Item:
    it = Item(key=row["key"], label=row["ref_label"], title=row["title"] or "",
              text=row["text"] or "", extra={})
    try:
        it.extra = json.loads(row["extra"] or "{}")
    except (json.JSONDecodeError, TypeError):
        it.extra = {}
    # The span table lives in its own column, not in extra.
    try:
        it.extra["markup"] = row["markup"] or ""
    except (IndexError, KeyError):
        pass
    # The module id, so `_segs_of` can key its cleaned-text cache on
    # (module, unit) rather than on the article text.  Not all callers pass a
    # `unit` row, so it is read defensively; an empty id still gives a usable
    # key when the unit key is unique within the process.
    try:
        it.extra["_mid"] = row["module_id"] or ""
    except (IndexError, KeyError):
        it.extra["_mid"] = ""
    # The canonical place of a verse, when the unit is one.  The unit key
    # belongs to its module -- the same verse is "John.3.16" in one Bible and
    # "John 3:16" in another -- so anything that has to recognise the same
    # verse across translations needs this instead of the key.
    try:
        _b, _c, _v = row["book"], row["chapter"], row["verse"]
    except (IndexError, KeyError):
        _b = _c = _v = None
    if _b and _c and _v:
        it.extra["osis"] = f"{_b}.{_c}.{_v}"
    if with_html:
        it.html = _render(it, o)
    return it


def _read_bible(m: Module, cursor: dict, o: RenderOpts, span: str, context: int) -> Content:
    conn = db.connect()
    rr = _cursor_to_range(m, cursor, span)
    rows = conn.execute(
        "SELECT * FROM unit WHERE module_id=? AND book=? AND chapter=? "
        "ORDER BY verse", (m.id, rr.start.book, rr.start.chapter)).fetchall()
    c = Content(m.id, m.name, "verse", cursor={"ref": canon.format_ref(rr.start),
                                              "span": span}, ref_label=canon.format_ref(rr.start))
    if not rows:
        # A verse-keyed module with nothing anchored to this chapter.  Some
        # real modules are verse-*numbered* but carry no book name at all --
        # Darby's Translation Notes key every note "9:38" -- so no reference can
        # ever match.  Showing an empty pane reads as "this module is broken";
        # offering its notes as a list does not.
        if not conn.execute("SELECT 1 FROM unit WHERE module_id=? AND "
                            "book IS NOT NULL AND book<>'' LIMIT 1",
                            (m.id,)).fetchone():
            listed = conn.execute(
                "SELECT * FROM unit WHERE module_id=? ORDER BY ord LIMIT 200",
                (m.id,)).fetchall()
            if listed:
                c.kind = "book"
                c.section_title = "Notes (no book references in this module)"
                c.notices.append(
                    "This module's notes carry chapter:verse but no book name, "
                    "so they cannot be opened by reference. They are listed "
                    "here and are fully searchable.")
                c.items = [_mk_item(r, o) for r in listed]
        return c
    bk = canon.BOOK_BY_OSIS.get(rows[0]["book"])
    c.section_title = (bk.name if bk else rows[0]["book"]) + " " + str(rows[0]["chapter"])
    c.items = [_mk_item(r, o) for r in rows]
    c.context = _bible_context(m, rr.start, context)
    return c


def _read_article(m: Module, cursor: dict, o: RenderOpts, context: int) -> Content:
    conn = db.connect()
    key = cursor.get("key") or cursor.get("headword") or ""
    r = None
    if not key:
        r = conn.execute("SELECT * FROM unit WHERE module_id=? ORDER BY ord LIMIT 1",
                         (m.id,)).fetchone()
    else:
        for sql, arg in (
            ("SELECT * FROM unit WHERE module_id=? AND key=?", key),
            ("SELECT * FROM unit WHERE module_id=? AND key=? COLLATE NOCASE", key),
            ("SELECT * FROM unit WHERE module_id=? AND key LIKE ? LIMIT 1",
             key.rstrip("*") + "%"),
        ):
            r = conn.execute(sql, (m.id, arg)).fetchone()
            if r is not None:
                break
    c = Content(m.id, m.name, "article", cursor={"key": key})
    if r is None and key:
        r = _article_by_word(m, key)
    if r is None:
        c.notices.append("No entry found for " + (key or "(nothing)"))
        c.context = _article_suggestions(m, key)
        return c
    c.items = [_mk_item(r, o)]
    c.ref_label = r["ref_label"]
    c.section_title = r["title"] or ""
    c.cursor = {"key": r["key"]}
    c.context = _neighbours(m, r["ord"], context)
    return c


def _article_by_word(m: Module, word: str):
    """Find an article by the plain word, not by its catalogue key.

    Concordances are keyed by Strong's number, so typing the word a reader
    actually sees -- "Aaron" -- finds nothing unless the word is resolved first.
    Two routes, in order of directness:

    1.  A unit whose own headword or title is the word (lexicons, dictionaries,
        encyclopaedias are all keyed this way).
    2.  The Strong's number(s) the word carries in an installed tagged Bible,
        which is what a concordance is actually keyed by.
    """
    conn = db.connect()
    w = word.strip()
    if not w:
        return None
    like = w.rstrip("*") + "%"
    r = conn.execute(
        "SELECT * FROM unit WHERE module_id=? AND (title=? COLLATE NOCASE "
        "OR title LIKE ?) ORDER BY ord LIMIT 1", (m.id, w, like)).fetchone()
    if r is not None:
        return r
    # A concordance: resolve the word to Strong's numbers via the marker table.
    # The English word the reader typed is on the *marker* of a tagged Bible,
    # next to the Strong's number it carries.  (The `strongs` summary table is
    # no use here: its `word` column holds the gloss of the underlying Hebrew
    # or Greek lemma, so looking up "love" there returns saul and to-hate.)
    rows = conn.execute(
        "SELECT value, COUNT(*) n FROM marker "
        "WHERE kind='strongs' AND surface = ? COLLATE NOCASE "
        "GROUP BY value ORDER BY n DESC LIMIT 12", (w,)).fetchall()
    for row in rows:
        if not row["value"]:
            continue
        r = _concordance_row(m, str(row["value"]))
        if r is not None:
            return r
    # A bare number is still a lookup: concordance keys are G/H + digits.
    if re.fullmatch(r"\d{1,5}", w):
        for pre in ("G", "H"):
            r = _concordance_row(m, pre + w)
            if r is not None:
                return r
    return None


def _concordance_row(m: Module, n: str):
    """Find a concordance entry for a Strong's number in any of its spellings.

    The number has to be matched with its letter.  An earlier version stripped
    both letters off the key before comparing, which was meant to cope with
    G2316 being stored as G02316 -- and did, but it also made every number
    ambiguous between the two scripts.  The marker table yields padded numbers
    (H0175) while the concordance stores them bare (H175), so looking up the
    word "Aaron" fell through to that comparison and returned G175, ἄκαρπος,
    "fruitless" -- a different word in a different language, silently, for any
    number that exists in both scripts.
    """
    conn = db.connect()
    raw = (n or "").strip()
    for cand in (raw, raw.upper(), raw.lower()):
        if not cand:
            continue
        r = conn.execute("SELECT * FROM unit WHERE module_id=? AND key=? LIMIT 1",
                         (m.id, cand)).fetchone()
        if r is not None:
            return r
    r = conn.execute("SELECT * FROM unit WHERE module_id=? AND key LIKE ? LIMIT 1",
                     (m.id, raw + "%")).fetchone()
    if r is not None:
        return r
    mm = re.fullmatch(r"([A-Za-z]?)(\d+)", raw)
    if not mm:
        return None
    pre = mm.group(1).upper()
    num = int(mm.group(2))
    if pre:
        # Same letter, same number, whatever the zero padding is on either side.
        for r in conn.execute(
                "SELECT * FROM unit WHERE module_id=? AND UPPER(key)=? LIMIT 1",
                (m.id, pre + str(num))):
            return r
        return None
    # No letter given at all: either script, but still by number.
    for r in conn.execute(
            "SELECT * FROM unit WHERE module_id=? AND UPPER(substr(key,1,1)) IN "
            "('G','H') AND CAST(REPLACE(REPLACE(UPPER(key),'G',''),'H','') "
            "AS INTEGER)=? LIMIT 1", (m.id, num)):
        return r
    return None


def _article_suggestions(m: Module, key: str) -> list:
    """Nearest headwords, so a failed lookup offers somewhere to go."""
    if not key:
        return []
    conn = db.connect()
    like = key.rstrip("*")[:3] + "%"
    rows = conn.execute(
        "SELECT * FROM unit WHERE module_id=? AND key LIKE ? ORDER BY key LIMIT 8",
        (m.id, like)).fetchall()
    out = []
    for r in rows:
        it = _mk_item(r, RenderOpts(), with_html=False)
        it.text = (it.text or "")[:220]
        out.append(it)
    return out


_DATE_KEY = re.compile(r"^(\d{1,2})\.(\d{1,2})$")


def _date_keys(key: str) -> list[str]:
    """Both spellings of a day key.

    Devotional modules index days zero-padded -- "01.15" -- but a person types
    "1.15", and `_today_key` produces the unpadded form.  Trying both is the
    difference between opening on today's reading and opening on page one.
    """
    out = [key]
    m = _DATE_KEY.match((key or "").strip())
    if m:
        mm, dd = m.group(1), m.group(2)
        padded = f"{int(mm):02d}.{int(dd):02d}"
        if padded not in out:
            out.append(padded)
        bare = f"{int(mm)}.{int(dd)}"
        if bare not in out:
            out.append(bare)
    return out


def _read_date(m: Module, cursor: dict, o: RenderOpts) -> Content:
    conn = db.connect()
    key = cursor.get("date") or cursor.get("ref") or cursor.get("key") or _today_key()
    r = None
    for cand in _date_keys(key):
        r = conn.execute("SELECT * FROM unit WHERE module_id=? AND key=?",
                         (m.id, cand)).fetchone()
        if r is not None:
            break
    c = Content(m.id, m.name, "date", cursor={"date": key}, ref_label=key)
    if r is None:
        c.notices.append("Nothing for " + key)
        # A "devotional" with no date-keyed units at all is not a calendar: the
        # importer filed a treatise as one.  John Owen's "Communion with God"
        # arrived that way, and opening it showed a permanently empty pane,
        # which reads as broken rather than mislabelled.  Read it as the book it
        # is and say why.
        dated = conn.execute(
            "SELECT 1 FROM unit WHERE module_id=? AND key GLOB '[0-9]*.[0-9]*' "
            "LIMIT 1", (m.id,)).fetchone()
        if dated is None:
            first = conn.execute(
                "SELECT * FROM unit WHERE module_id=? ORDER BY ord LIMIT 1",
                (m.id,)).fetchone()
            if first is not None:
                c.kind = "book"
                c.cursor = {}
                c.ref_label = first["ref_label"] or first["key"]
                c.section_title = first["title"] or ""
                c.items = [_mk_item(first, o)]
                c.notices.append(
                    "This is filed as a devotional but has no dated readings -- "
                    "it is a book, so it is shown as one. " + key + " has no entry.")
                return c
        return c
    c.items = [_mk_item(r, o)]
    c.ref_label = r["ref_label"]
    c.section_title = r["title"] or ""
    c.cursor = {"date": r["key"]}
    return c


def _today_key() -> str:
    t = time.localtime()
    return f"{t.tm_mon}.{t.tm_mday}"


def _read_book(m: Module, cursor: dict, o: RenderOpts) -> Content:
    conn = db.connect()
    key = cursor.get("key") or cursor.get("section") or cursor.get("ref") or ""
    r = None
    if key:
        for cand in _date_keys(key) if _DATE_KEY.match(key.strip()) else [key]:
            r = conn.execute("SELECT * FROM unit WHERE module_id=? AND key=?",
                             (m.id, cand)).fetchone()
            if r is not None:
                break
        if r is None:
            r = conn.execute(
                "SELECT * FROM unit WHERE module_id=? AND (ref_label=? OR title=?)",
                (m.id, key, key)).fetchone()
    if r is None:
        # A book or devotional pane that has never been opened should show its
        # first section rather than an empty pane telling the user to go and
        # find something.  Books are the one reader a person opens "cold".
        r = conn.execute("SELECT * FROM unit WHERE module_id=? ORDER BY ord LIMIT 1",
                         (m.id,)).fetchone()
    c = Content(m.id, m.name, "book", cursor={"key": key or (r["key"] if r else "")})
    if r is None:
        c.notices.append("This module has no readable sections.")
        return c
    c.items = [_mk_item(r, o)]
    c.ref_label = r["ref_label"]
    c.section_title = r["title"] or ""
    c.cursor = {"key": r["key"]}
    c.context = _neighbours(m, r["ord"], 1)
    return c


def _read_topic(m: Module, cursor: dict, o: RenderOpts, context: int) -> Content:
    """FactBooks are indexed by topic; the unit table holds the articles."""
    conn = db.connect()
    key = cursor.get("key") or cursor.get("topic") or ""
    rows = []
    if key:
        rows = conn.execute(
            "SELECT * FROM unit WHERE module_id=? AND (key=? OR key LIKE ?) ORDER BY ord",
            (m.id, key, key + "%")).fetchall()
    if not rows:
        rows = conn.execute("SELECT * FROM unit WHERE module_id=? ORDER BY ord LIMIT 1",
                            (m.id,)).fetchall()
    c = Content(m.id, m.name, "topic", cursor={"key": key})
    c.items = [_mk_item(r, o) for r in rows[:200]]
    c.ref_label = key or (rows[0]["key"] if rows else "")
    c.cursor = {"key": c.ref_label}
    return c


def _read_image(m: Module, cursor: dict, o: RenderOpts) -> Content:
    conn = db.connect()
    key = cursor.get("key") or ""
    r = conn.execute("SELECT * FROM unit WHERE module_id=? AND key=?",
                     (m.id, key)).fetchone()
    if r is None:
        r = conn.execute("SELECT * FROM unit WHERE module_id=? ORDER BY ord LIMIT 1",
                         (m.id,)).fetchone()
    c = Content(m.id, m.name, "image", cursor={"key": key})
    if r is None:
        c.notices.append("No images installed.")
        return c
    it = _mk_item(r, o)
    try:
        it.extra = json.loads(r["extra"] or "{}")
    except (json.JSONDecodeError, TypeError):
        pass
    c.items = [it]
    c.ref_label = r["ref_label"]
    c.section_title = r["title"] or ""
    c.cursor = {"key": r["key"]}
    return c


# --------------------------------------------------------------------------

def _cursor_to_range(m: Module, cursor: dict, span: str) -> canon.RefRange:
    scheme = m.v11n or "KJV"
    ref = canon.Ref("Gen", 1, 1)
    if cursor.get("ref"):
        r = canon.parse_ref(cursor["ref"], scheme)
        if r:
            ref = r.start
    elif cursor.get("book"):
        ref = canon.Ref(cursor["book"], int(cursor.get("chapter") or 1),
                        int(cursor.get("verse") or 1))
    if span == "verse":
        return canon.RefRange(ref, ref)
    if span == "book":
        n = canon.chapter_count(scheme, ref.book)
        last = canon.verse_count(scheme, ref.book, n) or 1
        return canon.RefRange(canon.Ref(ref.book, 1, 1), canon.Ref(ref.book, n, last))
    if span == "range" and cursor.get("to"):
        r2 = canon.parse_ref(cursor["to"], scheme)
        if r2:
            return canon.RefRange(ref, r2.start)
    return canon.RefRange(ref, ref)


def _bible_context(m: Module, ref: canon.Ref, n: int) -> dict:
    scheme = m.v11n or "KJV"
    out: dict = {}
    conn = db.connect()
    # Strong's present in this module, for the word-study pane
    if m.has_strongs and ref.verse:
        rows = conn.execute(
            "SELECT value, COUNT(*) n FROM marker WHERE module_id=? AND unit_key=? "
            "AND kind='strongs' GROUP BY value ORDER BY n DESC LIMIT 8",
            (m.id, ref.osis_id())).fetchall()
        out["strongs"] = [{"strongs": r["value"], "count": r["n"]} for r in rows]
    if m.has_xref:
        rows = conn.execute(
            "SELECT to_key FROM xref WHERE module_id=? AND from_key=? LIMIT 24",
            (m.id, ref.osis_id())).fetchall()
        out["xrefs"] = [r["to_key"] for r in rows]
    if n > 0:
        out["prev"] = canon.format_ref(canon.prev_ref(ref, scheme))
        out["next"] = canon.format_ref(canon.next_ref(ref, scheme))
    return out


def _neighbours(m: Module, ord_: int, n: int) -> dict:
    """The `n` entries either side of this one, for key-navigated resources.

    The window was `ord < ord_-n OR ord > ord_+n`, which is everything
    *except* the neighbourhood, and then took the first 2n of those in `ord`
    order.  So it returned the twelve oldest entries in the resource, not the
    ones around the one being read: asking for the neighbours of Strong's G2316
    answered G1, G2, G3 … Nothing called it, which is why it survived; the
    first thing that does is a previous/next control, and it would have walked
    the reader to the start of the book on every press.
    """
    if n <= 0:
        return {}
    conn = db.connect()
    rows = conn.execute(
        "SELECT key, title, ref_label, ord FROM unit WHERE module_id=? "
        "AND ord BETWEEN ? AND ? ORDER BY ord",
        (m.id, ord_ - n, ord_ + n)).fetchall()
    before = [dict(r) for r in rows if r["ord"] < ord_][::-1]
    after = [dict(r) for r in rows if r["ord"] > ord_]
    return {"before": before, "after": after}


_STRONGS_KEY = re.compile(r"^([GH])(\d+)$")


def article_index(m: Module, bucket: str = "", limit: int = 400) -> dict:
    """The table of contents of an article-keyed resource.

    A lexicon, dictionary, encyclopaedia or concordance is navigated by its key,
    and until now there was no way to see what keys exist.  The only navigation
    was the search box: type something you already know is in there.  For the
    resources that use this reader that is a poor substitute for a contents
    page -- Webster has 114,712 entries, the Catholic Encyclopedia 10,049,
    Strong's 14,199, and none of them can be scrolled.

    Bucketing is by leading letter, except for a Strong's concordance whose keys
    are numbers: an A-Z index over "G1..G5624" would be two letters and useless,
    so those are grouped by thousand, which is how the printed concordances are
    laid out and how a reader looks for G2316.
    """
    conn = db.connect()
    rows = conn.execute(
        "SELECT key, title FROM unit WHERE module_id=? AND key<>'' ORDER BY ord",
        (m.id,)).fetchall()
    if not rows:
        return {"ok": True, "buckets": [], "entries": [], "total": 0,
                "kind": "alpha"}
    sample = next((r["key"] for r in rows if _STRONGS_KEY.match(r["key"] or "")), "")
    kind = "numbers" if sample else "alpha"
    buckets: dict[str, int] = {}
    for r in rows:
        k = (r["key"] or "").strip()
        if not k:
            continue
        if kind == "numbers":
            g = _STRONGS_KEY.match(k)
            if not g:
                continue
            lo = (int(g.group(2)) - 1) // 1000 * 1000 + 1
            b = f"{g.group(1)}{lo}"
        else:
            ch = k[0].upper()
            if not ch.isalpha():
                b = "#"
            else:
                b = ch
        buckets[b] = buckets.get(b, 0) + 1
    keys = list(buckets)
    if kind == "numbers":
        keys.sort(key=lambda b: (b[1], int(b[1:])))
    else:
        # Letters first, and the catch-all last.  "#" is not a bucket a reader
        # would reach for, and it holds only the handful of in-article section
        # headings that are not keyed by a word at all -- sorting it first made
        # the Catholic Encyclopedia open on an empty page.
        keys.sort(key=lambda b: (b == "#", b))
    entries: list[dict] = []
    chosen = (bucket or "").strip()
    if not chosen and keys:
        chosen = keys[0]
    if chosen:
        if kind == "numbers":
            g = _STRONGS_KEY.match(chosen)
            lo = int(g.group(2)) if g else 1
            hi = lo + 1000
            pref = g.group(1) if g else ""
            for r in rows:
                k = (r["key"] or "").strip()
                mnum = _STRONGS_KEY.match(k)
                if not mnum or mnum.group(1) != pref:
                    continue
                if lo <= int(mnum.group(2)) < hi:
                    entries.append({"key": k, "title": r["title"] or k})
                    if len(entries) >= limit:
                        break
        else:
            like = "#%" if chosen == "#" else chosen + "%"
            entries = [{"key": r["key"], "title": r["title"] or r["key"]}
                       for r in rows
                       if ((r["key"] or "")[:1].upper() == "#"
                           if chosen == "#"
                           else (r["key"] or "")[:1].upper() == chosen)]
            entries = entries[:limit]
    return {"ok": True, "kind": kind, "total": len(rows),
            "buckets": [{"b": b, "n": buckets[b]} for b in keys],
            "bucket": chosen, "entries": entries,
            "truncated": len(entries) >= limit}


# --------------------------------------------------------------------------
# Navigation used by the panel menus
# --------------------------------------------------------------------------

def chapter_list(m: Module) -> list[dict]:
    if not m.is_bible:
        return []
    conn = db.connect()
    rows = conn.execute(
        "SELECT book, MAX(chapter) chapter FROM unit WHERE module_id=? "
        "GROUP BY book, chapter ORDER BY book, chapter", (m.id,)).fetchall()
    seen: dict[str, int] = {}
    for r in rows:
        seen[r["book"]] = max(seen.get(r["book"], 0), r["chapter"])
    return [{"osis": k, "name": (canon.BOOK_BY_OSIS.get(k).name if canon.BOOK_BY_OSIS.get(k) else k),
             "chapters": v} for k, v in seen.items()]


def outline(m: Module) -> list[dict]:
    """Section/headword list for article- and book-indexed resources."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT key, title, ref_label, ord FROM unit WHERE module_id=? "
        "ORDER BY ord", (m.id,)).fetchall()
    return [{"key": r["key"], "title": r["title"] or r["ref_label"],
             "label": r["ref_label"], "ord": r["ord"]} for r in rows]


def date_list(m: Module) -> list[dict]:
    conn = db.connect()
    rows = conn.execute(
        "SELECT key, title FROM unit WHERE module_id=? ORDER BY key", (m.id,)).fetchall()
    return [{"date": r["key"], "title": r["title"]} for r in rows]


# --------------------------------------------------------------------------
# Install / uninstall
# --------------------------------------------------------------------------

def register(conn, **kw) -> str:
    """Insert or **partially** update a module row.  Returns the module id.

    The library's words are about to change, so the vocabularies built from them
    are now stale.  See db.bump_generation().

    Partial is the whole point, and it was not always so.

    This used to be `INSERT OR REPLACE` over exactly the columns it was handed,
    which means every column the caller did *not* name was reset to its default.
    `run_import` calls it, so any caller of `run_import` that names a subset
    silently wiped the rest of the module's metadata.  Two did:

      * `tools/reindex_local.py`, which passed six fields and hardcoded a
        seventh.  Run against the Hebrew Bible, it left `openscriptures-morphhb`
        a CC BY 4.0 module with no `rights` -- so an export citing it could not
        discharge the attribution obligation.  `license_audit.py` cannot catch
        that: the *licence* was still there, only the text naming who to credit
        had gone.

      * the re-index endpoint, which passes name/abbrev/type/subject/lang/
        source/license/v11n and dropped `rights`, `author`, `year`, `version`,
        `description`, `source_url`, `format`, `raw_meta` and the rest.

    So the failure was never in either tool.  It was in a helper that made
    "tell me about this module" mean "forget everything you were not told".
    Naming a field now means *update this field* on a row that exists, and
    supply a default on a row that does not.

    Nothing needed the old behaviour.  The derived counters -- `entries`,
    `verses`, `chapters`, the `has_*` flags -- are written by explicit `UPDATE`s
    in `indexer.run_import` once indexing finishes, and `error` is cleared by
    `mark_removed`, so none of them depended on this resetting them.
    """
    mid = kw.get("id") or slugify(f"{kw.get('source','')}-{kw.get('abbrev') or kw.get('name','')}")
    if not mid:
        mid = slugify(kw.get("name", "module"))
    fields = dict(kw)
    fields["id"] = mid
    if "subject" in fields and not isinstance(fields["subject"], str):
        fields["subject"] = json.dumps(fields["subject"])
    if "index_types" in fields and not isinstance(fields["index_types"], str):
        fields["index_types"] = json.dumps(fields["index_types"])
    if "raw_meta" in fields and not isinstance(fields["raw_meta"], str):
        fields["raw_meta"] = json.dumps(fields["raw_meta"])
    # Always re-derive the name rather than only filling a blank: it is a
    # presentation value, and rows installed before a code got a friendly name
    # kept the bare code forever ("und" for a map with no language).
    if fields.get("lang"):
        fields["lang_name"] = taxonomy.language_name(fields["lang"])
    for k, v in list(fields.items()):
        if isinstance(v, bool):
            fields[k] = int(v)
    cols = ",".join(fields)
    ph = ",".join("?" * len(fields))
    values = list(fields.values())
    # Two statements, not `INSERT .. ON CONFLICT DO UPDATE`.
    #
    # The one-statement form still *builds* the candidate row before it notices
    # the conflict, so `NOT NULL` is enforced against the columns the caller
    # chose to name: asking for `{id, installed_at, name}` on a row that
    # already exists raised `NOT NULL constraint failed: module.type`.  That is
    # precisely the case this function exists to serve -- change two fields,
    # forget the rest -- so the form that cannot express it is the wrong one.
    conn.execute(f"INSERT OR IGNORE INTO module({cols}) VALUES({ph})", values)
    # `id` is the key, so it is not in the SET list: assigning it to itself is
    # legal and says nothing.
    sets = ",".join(f"{c}=?" for c in fields if c != "id")
    conn.execute(f"UPDATE module SET {sets} WHERE id=?",
                 [v for k, v in fields.items() if k != "id"] + [mid])
    if not fields.get("index_types"):
        conn.execute("UPDATE module SET index_types=? WHERE id=?",
                     (json.dumps(list(taxonomy.index_types_for(fields.get("type", "Other")))),
                      mid))
    db.bump_generation()
    return mid


def mark_removed(conn, module_id: str) -> None:
    """Soft-remove a module: the row stays so the Store can still say it was
    installed, but all content is dropped.  unit_fts has no module_id column
    (it is a contentless FTS5 table), so its rows are cleared by rowid first."""
    conn.execute("UPDATE module SET installed_at=0, error=NULL WHERE id=?", (module_id,))
    conn.execute("DELETE FROM unit_fts WHERE module_id=?", (module_id,))
    for tbl in ("unit", "marker", "versification", "xref"):
        conn.execute(f"DELETE FROM {tbl} WHERE module_id=?", (module_id,))
    # `strongs.modules` is a JSON list of module ids, so no DELETE can reach it
    # and nothing else was pruning it.  Removing the King James left its id in
    # 13,907 of 14,178 entries, which inflates every "has Strong's" count and
    # tells the concordance a removed Bible can still be searched.
    #
    # The rows are found with a LIKE prefilter rather than by parsing all 14,178
    # of them.  Parsing every row cost about a second per call, paid on every
    # install and every remove, to discover that a module nobody had Strong's for
    # appears in none of them -- which is the common case, and at twenty thousand
    # modules would have been six hours of JSON.
    #
    # A LIKE hit is only a candidate: module ids are distinctive slugs, so a false
    # positive is vanishingly unlikely, and one still gets parsed and filtered
    # below, so a false positive changes nothing but a little work.
    for row in conn.execute(
            "SELECT rowid, modules FROM strongs WHERE modules LIKE ?",
            (f'%{module_id}%',)).fetchall():
        try:
            ids = json.loads(row["modules"] or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(ids, list):
            continue
        kept = [i for i in ids if i != module_id]
        if len(kept) != len(ids):
            conn.execute("UPDATE strongs SET modules=? WHERE rowid=?",
                         (json.dumps(kept), row["rowid"]))


def remove_module(module_id: str, *, delete_files: bool = True) -> dict:
    conn = db.connect()
    m = get(module_id)
    if m is None:
        return {"ok": False, "error": "Not installed"}
    # Close the read transaction `get()` opened so the write below does not
    # have to upgrade a held read lock (which fails with "database is locked"
    # on a database this size).
    conn.commit()
    n_units = conn.execute("SELECT COUNT(*) c FROM unit WHERE module_id=?",
                           (module_id,)).fetchone()["c"]
    conn.commit()
    mark_removed(conn, module_id)
    conn.commit()
    db.bump_generation()
    # The positional index has to be told.  Its unit ids belong to the units just
    # deleted, and its coverage bookkeeping would otherwise still list this module
    # as indexed -- so reinstalling the same book would look already-indexed and
    # silently return nothing for it.  Best-effort: failing to tidy an index must
    # never block removing a book.
    try:
        from . import posindex
        posindex.forget(module_id)
    except Exception as exc:                          # noqa: BLE001
        db.log_history("remove",
                       f"{module_id}: positional index not updated: {exc}")
    # Removing a Bible deletes ~30,000 unit rows and their search-index entries
    # in one go, which is the other way the log grows without being folded back.
    db.maybe_checkpoint(conn)
    removed_files = 0
    # Resolved, not read: `m.path` names wherever this was installed, which is
    # not necessarily where the files are now. Deleting by the recorded path
    # after a move would report success while removing nothing.
    p = module_dir(module_id) if delete_files else None
    if delete_files:
        try:
            if p is None:
                # The files are not where either the recorded path or the
                # library says. Removing the module row is still what was asked
                # for; the orphaned files are named in the history rather than
                # silently abandoned.
                db.log_history(
                    "remove",
                    f"{module_id}: files not found, module row removed and "
                    f"the folder left where it is")
            elif p.is_dir():
                import shutil
                shutil.rmtree(p)
                removed_files = 1
            elif p.is_file():
                p.unlink()
                removed_files = 1
        except OSError as e:
            db.log_history("remove", f"{module_id}: could not delete files ({e})")
    if m.source:
        conn.execute("UPDATE store_item SET module_id=NULL WHERE module_id=?", (module_id,))
        conn.commit()
    db.log_history("remove", f"Removed {m.name}", {"module_id": module_id, "units": n_units})
    return {"ok": True, "module_id": module_id, "name": m.name, "units": n_units,
            "files_removed": removed_files}


# --------------------------------------------------------------------------
# Prioritise / favourites
# --------------------------------------------------------------------------

def set_priority(module_id: str, value: int) -> None:
    conn = db.connect()
    conn.execute("UPDATE module SET priority=? WHERE id=?", (int(value), module_id))
    conn.commit()


def set_favorite(module_id: str, value: bool) -> None:
    conn = db.connect()
    conn.execute("UPDATE module SET favorite=? WHERE id=?", (int(bool(value)), module_id))
    conn.commit()
    if not value:
        _tombstone(module_id, "favourite")


def _tombstone(module_id: str, kind: str) -> None:
    """Record a delete so sync does not bring it back.  See sync.tombstone."""
    try:
        from . import sync
        sync.tombstone(module_id, kind)
    except Exception:
        pass


# --------------------------------------------------------------------------
# Attribution
# --------------------------------------------------------------------------

def attributions() -> list[dict]:
    conn = db.connect()
    rows = conn.execute(
        "SELECT id,name,author,license,rights,source_name,source_url,version,type "
        "FROM module WHERE installed_at>0 ORDER BY license, author, name").fetchall()
    return [dict(r) for r in rows]

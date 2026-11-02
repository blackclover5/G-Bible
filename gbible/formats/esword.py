"""e-Sword module readers.

e-Sword 9 replaced every module type with a single-file SQLite database; e-Sword
8 and earlier used the same binary container family as SWORD zText with a
tab-separated `.mod` metadata file.  Both are handled here.

Table and column names are discovered rather than hard-coded.  Real `.bblx`
files disagree about which tables they use and what the payload column is called,
and e-Sword's own format is undocumented, so `PRAGMA table_info` probing is the
only robust approach -- the same thing And Bible does.
"""

from __future__ import annotations

import bz2
import json
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Iterator

from .. import canon, markup
from ..indexer import UnitIn
from ..markup import Seg
from . import sword
from .sword import Conf, SwordError, ZText, read_rawld


# --------------------------------------------------------------------------
# .mod  (e-Sword <= 8 metadata, tab-separated)
# --------------------------------------------------------------------------

_MOD_ALIASES = {
    "id": ("idtab", "id", "mod", "module", "idname"),
    "name": ("name", "title", "description", "modname"),
    "abbrev": ("abbrev", "abbreviation", "short", "abbr"),
    "version": ("version", "ver", "moduleversion"),
    "category": ("category", "cat", "type"),
    "description": ("description", "about", "comments", "desc"),
    "font": ("font",),
    "rtl": ("righttoleft", "rtl"),
    "ot": ("ot",),
    "nt": ("nt",),
    "apocrypha": ("apocrypha", "apo", "apoc"),
    "strong": ("strong", "strongs", "strongsnumber"),
    "lang": ("lang", "language"),
    "versiondate": ("versiondate", "date"),
    "copyright": ("copyright",),
    "encryption": ("encryption",),
    "passphrase": ("passphrase", "password"),
}

CATEGORY_MAP = {
    "bible": "Bible", "commentary": "Commentary", "dictionary": "Dictionary",
    "lexicon": "Lexicon", "devotional": "Devotional", "devotion": "Devotional",
    "images": "Illustration", "map": "Map", "maps": "Map", "illustration": "Illustration",
    "illustrations": "Illustration", "book": "Book", "audio": "Media",
    "topic": "FactBook", "lexdict": "Lexicon", "topical": "FactBook",
    "bible commentary": "Commentary", "devotionals": "Devotional",
    "greek": "Lexicon", "hebrew": "Lexicon", "encyclopedia": "Dictionary",
    "sermon": "Book", "theology": "Book", "journal": "Essay",
}


def read_mod(text: str) -> dict:
    """Parse a `.mod` file.  Tolerant by design: the format is not documented by
    e-Sword, so the first record's keys are taken as the schema and looked up
    case-insensitively with fallback lists."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return {}
    header = lines[0].split("\t")
    rec: dict = {}
    for i, col in enumerate(header):
        col = col.strip().lower()
        val = lines[1].split("\t")[i] if i < len(lines[1].split("\t")) else ""
        rec[col] = val.strip()

    out: dict = {}
    for field, names in _MOD_ALIASES.items():
        for n in names:
            if n in rec and rec[n]:
                out[field] = rec[n]
                break
    for raw_key, raw_val in rec.items():
        k = raw_key.strip().lower().replace(" ", "")
        if k in ("righttoleft", "rtl"):
            out["rtl"] = raw_val
        elif k in ("ot", "nt", "apocrypha", "strong"):
            out[k] = raw_val
    return out


def category_to_type(cat: str) -> str:
    c = (cat or "").strip().lower()
    return CATEGORY_MAP.get(c, "Other")


# --------------------------------------------------------------------------
# .bzu -- the bzip2 module bundle
# --------------------------------------------------------------------------

def open_bzu(path: Path) -> tuple[dict, Iterator[tuple[str, str]]] | None:
    """Open a `.bzu`.

    A .bzu is bzip2 of a `.mod` file followed by the payload.  The exact framing
    is not published by e-Sword, so this tries the documented shape and reports
    what it found rather than guessing silently.
    """
    raw = path.read_bytes()
    try:
        blob = bz2.decompress(raw)
    except OSError:
        return None
    m = re.search(rb"([A-Za-z0-9_]+\t[^\n]*\n)", blob)
    if not m:
        return None
    mod = read_mod(m.group(1).decode("latin-1", "replace"))
    rest = blob[m.end():]

    def payload() -> Iterator[tuple[str, str]]:
        if mod.get("category", "").lower() in ("dictionary", "lexicon", "devotional"):
            cur_key = ""
            buf: list[str] = []
            for line in rest.decode("utf-8", "replace").split("\n"):
                if not line.strip():
                    if cur_key:
                        yield cur_key, "\n".join(buf).strip()
                    cur_key, buf = "", []
                    continue
                if re.fullmatch(r"[A-Za-z][A-Za-z0-9' \-\.]*", line.strip()) and \
                   not line.startswith(("\t", " ")) and buf and \
                   not line.strip().endswith((".", ",", ";")):
                    pass
                buf.append(line)
            if cur_key:
                yield cur_key, "\n".join(buf).strip()
        else:
            yield "", rest.decode("utf-8", "replace")

    return mod, payload()


# --------------------------------------------------------------------------
# e-Sword 9+ : a single SQLite database
# --------------------------------------------------------------------------

_ES_EXT_TYPE = {
    ".bblx": "Bible", ".cmtx": "Commentary", ".dctx": "Dictionary",
    ".devx": "Devotional", ".mapx": "Map", ".harx": "Harmony",
    ".brpx": "Lectionary", ".notx": "FactBook", ".topx": "FactBook",
    ".refx": "FactBook", ".lstx": "Other", ".memx": "Other",
    ".prlx": "Devotional", ".ovlx": "Other", ".ill": "Illustration",
}


def esword_type(path: Path) -> str:
    return _ES_EXT_TYPE.get(path.suffix.lower(), "Other")


def _open_ro(path: Path) -> sqlite3.Connection:
    """Open read-only; some modules ship with the journal in place."""
    for uri in (f"file:{path}?mode=ro", f"file:{path}"):
        try:
            c = sqlite3.connect(uri, uri=True)
            c.row_factory = sqlite3.Row
            c.execute("SELECT count(*) FROM sqlite_master").fetchone()
            return c
        except sqlite3.Error:
            continue
    raise SwordError(f"cannot open {path.name} as SQLite")


def _pick_table(conn: sqlite3.Connection, wanted: tuple[str, ...]) -> str | None:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")]
    low = {n.lower(): n for n in names}
    for w in wanted:
        if w in low:
            return low[w]
    return names[0] if names else None


def _pick_col(cols: list[str], wanted: tuple[str, ...]) -> str | None:
    low = {c.lower(): c for c in cols}
    for w in wanted:
        if w in low:
            return low[w]
    for c in cols:
        cl = c.lower()
        if any(w in cl for w in wanted):
            return c
    return None


def esword_details(path: Path) -> dict:
    conn = _open_ro(path)
    tbl = _pick_table(conn, ("details", "detail", "info", "meta"))
    out: dict = {}
    if not tbl:
        conn.close()
        return out
    rows = conn.execute(f"SELECT * FROM {tbl} LIMIT 1").fetchall()
    if rows:
        out = {k: (r[k] if r[k] is not None else "") for k in rows[0].keys()}
    conn.close()
    return out


def _payload_to_segs(raw: str, details: dict) -> list[Seg]:
    if raw is None:
        return []
    s = str(raw)
    ver = str(details.get("version", "")).strip()
    if "\x00" in s or s.lstrip().startswith(r"{\rtf"):
        s = markup.parse_rtf(s)
    low = s.lstrip()[:200].lower()
    if "<" in low and re.search(r"</?(p|span|b|i|sup|div|font|table|tr|td)\b", low):
        return markup.parse_html(s)
    if ver == "4" or re.search(r"<[a-z]+[\s>]", low):
        return markup.parse_html(s)
    if re.search(r"\\[a-z]+\*?[\s|]", s) and "|" in s and "strong" in s.lower():
        return markup.parse_esword_inline(s)
    return markup.parse_plain(s)


def esword_units(path: Path, *, keep_notes: bool = True,
                 type_hint: str | None = None) -> tuple[dict, Iterator[UnitIn]]:
    """Return (details, unit iterator) for an e-Sword 9+ module."""
    conn = _open_ro(path)
    details = esword_details(path)
    mtype = type_hint or esword_type(path)
    itype = mtype

    if itype in ("Bible", "StudyBible", "OriginalLanguage", "Manuscript"):
        tbl = _pick_table(conn, ("bible", "scripture", "verses", "kjv"))
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")]
        cb = _pick_col(cols, ("book", "bookid", "b"))
        cc = _pick_col(cols, ("chapter", "c"))
        cv = _pick_col(cols, ("verse", "v"))
        ct = _pick_col(cols, ("scripture", "text", "verse_text", "content", "body"))
        if not (tbl and cb and cc and cv and ct):
            conn.close()
            raise SwordError(f"{path.name}: no scripture table")

        def bible() -> Iterator[UnitIn]:
            try:
                for r in conn.execute(
                        f"SELECT {cb} b,{cc} c,{cv} v,{ct} t FROM {tbl} "
                        f"ORDER BY {cb},{cc},{cv}"):
                    b = _es_book(int(r["b"]))
                    if b is None:
                        continue
                    segs = _payload_to_segs(r["t"], details)
                    yield UnitIn(key=f"{b.osis}.{r['c']}.{r['v']}",
                                 label=canon.format_ref(
                                     canon.Ref(b.osis, r["c"], r["v"])),
                                 segs=segs, markup="", book=b.osis,
                                 chapter=r["c"], verse=r["v"])
            finally:
                conn.close()
        return details, bible()

    if itype in ("Commentary", "Harmony", "FactBook"):
        tbl = _pick_table(conn, ("commentary", "commentaries", "cmt", "topical",
                                 "notes", "factbook"))
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")]
        ck = _pick_col(cols, ("chapter", "book", "key", "reference", "osisid"))
        cv = _pick_col(cols, ("verse", "v", "fromverse"))
        ct = _pick_col(cols, ("text", "commentary", "entry", "body", "content"))
        if not (tbl and ct):
            conn.close()
            raise SwordError(f"{path.name}: no commentary table")

        def cmt() -> Iterator[UnitIn]:
            order = f"{ck},{cv}" if cv else ck
            for i, r in enumerate(conn.execute(
                    f"SELECT * FROM {tbl} ORDER BY {order}"), 1):
                body = r[ct]
                segs = _payload_to_segs(body, details)
                if not segs:
                    continue
                if cv:
                    rr = canon.parse_osis_ref(str(r[ck] or ""))
                    if rr is None:
                        rr = canon.parse_ref(str(r[ck] or ""))
                    if rr is None:
                        continue
                    key = rr.start.osis_id()
                else:
                    key = str(r[ck] or f"e{i}")
                head = next((s.text for s in segs if s.kind in ("title", "heading")), "")
                yield UnitIn(key=key, label=canon.format_ref(
                    canon.parse_osis_id(key) or canon.Ref("Gen", 1, 1)),
                    segs=segs, markup="", title=head)
        return details, cmt()

    if itype == "Devotional":
        tbl = _pick_table(conn, ("devotional", "devotionals", "dev", "date"))
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")]
        ck = _pick_col(cols, ("day", "date", "month", "m", "key"))
        ct = _pick_col(cols, ("devotional", "text", "body", "content", "title"))
        if not (tbl and ct):
            conn.close()
            raise SwordError(f"{path.name}: no devotional table")

        def dev() -> Iterator[UnitIn]:
            for r in conn.execute(f"SELECT * FROM {tbl}"):
                key = _norm_date(r[ck]) if ck else ""
                if not key:
                    continue
                body = r[ct]
                title = ""
                segs = markup.parse_html(body) if body and "<" in str(body) \
                    else markup.parse_plain(markup.parse_rtf(str(body or "")))
                head = next((s.text for s in segs if s.kind == "title"), "")
                yield UnitIn(key=key, label=key, segs=segs, title=head or title)
        return details, dev()

    if itype in ("Dictionary", "Lexicon"):
        tbl = _pick_table(conn, ("dictionary", "lexicon", "entries", "entry",
                                 "dct"))
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")]
        ck = _pick_col(cols, ("name", "headword", "key", "term", "word"))
        ct = _pick_col(cols, ("definition", "text", "body", "content", "entry"))
        if not (tbl and ck and ct):
            conn.close()
            raise SwordError(f"{path.name}: no dictionary table")

        def dic() -> Iterator[UnitIn]:
            for r in conn.execute(f"SELECT * FROM {tbl}"):
                key = str(r[ck] or "").strip()
                if not key:
                    continue
                segs = _payload_to_segs(r[ct], details)
                if not segs:
                    continue
                yield UnitIn(key=key, label=key, segs=segs, title=key)
        return details, dic()

    # Unknown shape: expose the largest text column as articles.
    tbl = None
    best = 0
    for n in (r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({n})")]
        for c in cols:
            try:
                cnt = conn.execute(
                    f"SELECT COUNT({c}) FROM {n} WHERE {c} IS NOT NULL "
                    f"AND LENGTH({c})>0").fetchone()[0]
            except sqlite3.Error:
                continue
            if cnt > best:
                best, tbl = cnt, (n, cols)
    if not tbl:
        conn.close()
        raise SwordError(f"{path.name}: nothing indexable")
    n, cols = tbl
    ct = _pick_col(cols, ("text", "body", "content", "entry", "definition"))
    ck = _pick_col(cols, ("name", "key", "headword", "term", "title")) or ct

    def generic() -> Iterator[UnitIn]:
        for i, r in enumerate(conn.execute(f"SELECT * FROM {n}"), 1):
            body = r[ct] if ct else str(tuple(r))
            if not body:
                continue
            key = str(r[ck])[:120] if ck else f"e{i}"
            yield UnitIn(key=key, label=key, segs=_payload_to_segs(body, details),
                         title=key[:80])
    return details, generic()


def _norm_date(v) -> str:
    """e-Sword devotionals key on MM.DD in one form or another."""
    s = str(v or "").strip()
    m = re.match(r"(\d{1,2})[.\-/](\d{1,2})", s)
    if m:
        return f"{int(m.group(1))}.{int(m.group(2))}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{int(m.group(2))}.{int(m.group(3))}"
    m = re.fullmatch(r"(\d{3})", s)
    if m:
        mmdd = int(m.group(1))
        return f"{mmdd // 100}.{mmdd % 100}"
    return s


def _es_book(i: int):
    """e-Sword book ids are 1..66 in Protestant order; some modules use 1..80."""
    b = canon.book_by_esword_id(i)
    if b:
        return b
    for book in canon.BOOKS_KJA:
        if book.ordinal == i:
            return book
    return None


# --------------------------------------------------------------------------
# Legacy e-Sword <= 8 : .bbl + .bzs/.bzv/.bzz (same container as SWORD zText)
# --------------------------------------------------------------------------

def legacy_units(data_dir: Path, mod: dict, *, keep_notes: bool = True
                 ) -> Iterator[UnitIn]:
    cat = (mod.get("category") or "").lower()
    bzs = next(iter(sorted(data_dir.glob("*.bzs"))), None)
    bzv = next(iter(sorted(data_dir.glob("*.bzv"))), None)
    bzz = next(iter(sorted(data_dir.glob("*.bzz"))), None)
    if bzs and bzv and bzz:
        z = ZText(bzs, bzv, bzz, encoding="UTF-8", source_type="Plaintext",
                  compress="ZIP")
        for u in z.units():
            if keep_notes or True:
                yield u
        return
    for p in sorted(data_dir.iterdir()):
        if p.suffix.lower() in (".bbl", ".cmt", ".dct", ".dev", ".map"):
            yield from _legacy_plain(p, cat)
            return


def _legacy_plain(path: Path, cat: str) -> Iterator[UnitIn]:
    from .plain import units_from_articles
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for u in units_from_articles(raw, kind=category_to_type(cat),
                                 source=path.stem):
        yield u


# --------------------------------------------------------------------------
# Zip handling
# --------------------------------------------------------------------------

def find_esword_payload(zf: zipfile.ZipFile) -> tuple[str, bytes, str]:
    """Return (modname, mod bytes, payload name) from a .bzu-style zip."""
    mod_name = payload = ""
    for n in zf.namelist():
        low = n.lower()
        if low.endswith(".mod"):
            mod_name = n
        elif low.endswith((".bbl", ".cmt", ".dct", ".dev", ".bblx", ".cmtx",
                           ".dctx", ".devx", ".bmap", ".mapx")):
            payload = n
    if not payload:
        for n in zf.namelist():
            if n.lower().endswith((".bzz", ".bzs", ".bzv")):
                payload = n
                break
    return mod_name, (zf.read(mod_name) if mod_name else b""), payload

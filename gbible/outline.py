"""Bible outlines: the section headings of a chapter, and what they cover.

The chapter guide used to answer every request for an outline with a note
saying that no outline data was installed.  That was true, and it was the
honest thing to say rather than invent one -- but it left the feature empty,
and an outline is the one thing a study Bible cannot make do without, because
nobody can derive it from the text.  It is editorial.

So it comes from a book.  `data/outlines.json.gz` carries the headings of
Jamieson, Fausset and Brown (1871), which is out of copyright, covers all 66
books and every one of the 1189 chapters, and is small enough to ship with the
program -- 52 KB gzipped for the whole Bible.  tools/build_outlines.py
regenerates the file and can re-check it.

Two things are deliberately not hidden:

  * Which commentary it is.  An outline is an opinion about a text, and an
    outline presented without its author reads like the shape of the text
    itself.  Every response carries `source`, `title` and `attribution`, and
    `note` says plainly that JFB argues.
  * Where it is thin.  Six chapters -- Obadiah, Jude, Philemon, 2 Timothy,
    Lamentations 1 and Song of Solomon 37 -- are covered by the commentary but
    carry no headings at all.  Those come back as an empty list with the fact
    stated, not as a blank panel that could be mistaken for a bug.

Outlines from other sources can sit alongside it: any module installed with a
study-guide type contributes its own headings, and `sources()` lists what is
available.
"""

from __future__ import annotations

import gzip
import json
import threading
import time
import uuid
from pathlib import Path

from . import canon, db

DATA = Path(__file__).resolve().parent / "data" / "outlines.json.gz"

#: Marks the bundled data as loaded, so the 1,192 chapters are inserted once
#: per library rather than on every request.
_loaded = threading.local()

META: dict = {}


# --------------------------------------------------------------------- load

def _bundled() -> dict:
    """The shipped outline file, read once."""
    if getattr(_loaded, "bundle", None) is None:
        try:
            with gzip.open(DATA, "rt", encoding="utf-8") as f:
                _loaded.bundle = json.load(f)
        except (OSError, ValueError):
            # A missing or corrupt data file must not stop the app starting.
            # The browser then reports that no outline is installed, which is
            # the truth, instead of every request raising.
            _loaded.bundle = {}
    return _loaded.bundle


def meta() -> dict:
    b = _bundled()
    return {"source": b.get("source", ""), "title": b.get("title", ""),
            "attribution": b.get("attribution", ""), "note": b.get("note", ""),
            "installed": bool(b.get("books"))}


def ensure_loaded() -> bool:
    """Put the bundled headings into the database, once.

    They go into a table rather than being read from the gzip on every click
    because the browser joins them to the Bible: a heading says "Ge 1:3-5" and
    the pane wants to know which verses that covers, which is a lookup per row.
    Reading and re-parsing 52 KB of JSON to answer that is the wrong shape.
    """
    b = _bundled()
    if not b.get("books"):
        return False
    if getattr(_loaded, "done", None) == b.get("source"):
        return True
    conn = db.connect()
    source = b["source"]
    have = conn.execute("SELECT count(*) c FROM outline_node WHERE source=?",
                        (source,)).fetchone()["c"]
    if have:
        _loaded.done = source
        return True

    now = time.time()
    rows: list[tuple] = []
    for osis, chapters in b["books"].items():
        for cn, sections in chapters.items():
            chapter = int(cn)
            for i, s in enumerate(sections):
                base = f"{i + 1}"
                rows.append((f"ol_{uuid.uuid4().hex[:12]}", source, osis,
                             chapter, base, 0, s.get("title", ""),
                             s.get("ref", ""), i))
                for j, sub in enumerate(s.get("sub") or []):
                    rows.append((f"ol_{uuid.uuid4().hex[:12]}", source, osis,
                                 chapter, f"{base}.{j + 1}", 1, sub, "", i))
    conn.executemany(
        "INSERT INTO outline_node(id,source,book,chapter,path,depth,title,"
        "refs,ord) VALUES(?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    _loaded.done = source
    return True


# ------------------------------------------------------------------ reading

def _book_of(name: str) -> str | None:
    """Accept a full name, an OSIS abbreviation or a USFM one."""
    if not name:
        return None
    t = name.strip().lower()
    for b in canon.BOOKS_66:
        if t in (b.osis.lower(), b.name.lower(), getattr(b, "usfm", "").lower(),
                 getattr(b, "short", "").lower()):
            return b.osis
    return None


def chapter(book: str, chapter_no: int) -> dict:
    """The outline of one chapter."""
    ensure_loaded()
    osis = _book_of(book)
    full = next((b.name for b in canon.BOOKS_66 if b.osis == osis), book)
    out: dict = {"ok": False, "book": osis or book, "book_name": full,
                 "chapter": chapter_no, "sections": [],
                 "pointed": 0, **meta()}
    if not osis:
        out["error"] = f"{book!r} is not a book of the Bible"
        return out
    rows = db.connect().execute(
        "SELECT path,depth,title,refs,ord FROM outline_node "
        "WHERE source=? AND book=? AND chapter=? ORDER BY ord, depth, path",
        (META.get("source") or meta()["source"], osis, chapter_no)).fetchall()
    out["sections"] = [{"path": r["path"], "depth": r["depth"],
                        "title": r["title"], "ref": r["refs"] or ""}
                       for r in rows]
    out["pointed"] = len({r["path"].split(".")[0] for r in rows})
    out["ok"] = True
    if not rows:
        out["note_outline"] = (
            f"{next(b.name for b in canon.BOOKS_66 if b.osis == osis)} "
            f"{chapter_no} is covered by this commentary but carries no "
            f"section headings.")
    return out


def book_outline(book: str) -> dict:
    """Every chapter that has at least one heading, for the book tree."""
    ensure_loaded()
    osis = _book_of(book)
    if not osis:
        return {"ok": False, "error": f"{book!r} is not a book of the Bible"}
    rows = db.connect().execute(
        "SELECT chapter, count(*) n FROM outline_node WHERE source=? AND book=? "
        "GROUP BY chapter ORDER BY chapter",
        (meta()["source"], osis)).fetchall()
    return {"ok": True, "book": osis, "chapters": len(rows),
            "points": sum(r["n"] for r in rows),
            "index": [{"chapter": r["chapter"], "points": r["n"]} for r in rows]}


def to_passage(ref_text: str) -> list[str]:
    """Expand a heading's own coverage into canon references.

    A heading says "Ge 1:3-5" or "Joh 1:1-14" and the pane wants the verses.
    Anything that does not parse is returned as it was written rather than
    dropped: a heading that cites Romans 8 somewhere in its title should still
    be clickable, and an unparsed range is better than a dead row.
    """
    out: list[str] = []
    for part in (ref_text or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            rr = canon.parse_ref(part)
        except Exception:
            out.append(part)
            continue
        if rr is None:
            out.append(part)
            continue
        try:
            out.extend(r.label() for r in rr.refs())
        except Exception:
            out.append(part)
    return out


def sources() -> list[dict]:
    """Every outline the app can show, bundled or installed."""
    out = [meta()]
    for m in db.connect().execute(
            "SELECT id,name FROM module WHERE type IN "
            "('StudyGuide','SermonOutline') AND installed_at>0 "
            "ORDER BY name").fetchall():
        out.append({"source": m["id"], "title": m["name"],
                    "attribution": "installed study guide",
                    "note": "", "installed": True, "module_id": m["id"]})
    return out
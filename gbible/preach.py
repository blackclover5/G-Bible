"""Sermon outlines and counseling topics from installed PD works.

Extractive throughout: outline points are the source's own headings and
numbered points, counseling passages are seed references plus what the
installed library actually says. Nothing is composed, and every line names
the work it came from. A topic with no installed coverage says so.
"""

from __future__ import annotations

import re

from . import canon, db, library


def _sermon_modules() -> list:
    mods = []
    for m in library.list_all():
        if m.type == "SermonOutline":
            mods.append(m)
        elif m.type == "Book" and re.search(
                r"spurgeon|sermon|homil|preach|pulpit|murray|moody",
                (m.name or ""), re.I):
            mods.append(m)
    return mods


def _points(text: str, limit: int = 12) -> list[str]:
    """The source's own structure: numbered/lettered points and headings."""
    lines = [ln.strip() for ln in re.split(r"[\r\n]+", text or "") if ln.strip()]
    pts = [ln for ln in lines
           if re.match(r"^(?:[IVXLC]+\.|[0-9]+[.)]|[a-z][.)]|[-•])\s+\S", ln)]
    if len(pts) < 2:
        # Fall back to short lines that read like headings.
        pts = [ln for ln in lines if len(ln) <= 90][:limit]
    seen, out = set(), []
    for p in pts:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
        if len(out) >= limit:
            break
    return out


def sermon_outlines(ref: str, limit: int = 8) -> dict:
    """Installed sermon-form works bearing on a passage."""
    rr = canon.parse_ref(ref)
    if rr is None:
        return {"ok": False, "error": f"Cannot read {ref!r}"}
    f = next(iter(rr.refs()))
    mods = _sermon_modules()
    if not mods:
        return {"ok": True, "items": [],
                "note": "No sermon-form work installed. Spurgeon or Murray "
                        "from Project Gutenberg would fill this in."}
    conn = db.connect()
    likes = [f"%{f.book} {f.chapter}:%", f"%{f.book} {f.chapter} %"]
    out = []
    for m in mods:
        rows = conn.execute(
            "SELECT key, title, text FROM unit WHERE module_id=? AND "
            "(text LIKE ? OR text LIKE ? OR title LIKE ?) LIMIT 6",
            (m.id, likes[0], likes[1], f"%{f.book}%")).fetchall()
        for r in rows:
            pts = _points(r["text"] or "")
            if not pts:
                continue
            out.append({"module_id": m.id, "module": m.name,
                        "title": r["title"] or r["key"], "points": pts})
            if len(out) >= limit:
                break
        if len(out) >= limit:
            break
    if not out:
        return {"ok": True, "items": out,
                "note": "Installed sermon works mention nothing here."}
    return {"ok": True, "ref": ref, "items": out,
            "note": "The authors' own points — not composed, not rearranged."}


# Topics are pastoral situations, not doctrines. Seed references are
# long-settled public-domain knowledge (references are facts, not prose);
# everything else is read out of the installed library.
COUNSEL_TOPICS = {
    "grief": ["Ps 34:18", "Matt 5:4", "John 11:35", "Rom 8:38-39", "Rev 21:4"],
    "fear": ["Ps 23:4", "Ps 56:3", "Isa 41:10", "John 14:27", "2 Tim 1:7"],
    "anxiety": ["Ps 55:22", "Matt 6:25-34", "Phil 4:6-7", "1 Pet 5:7"],
    "anger": ["Ps 37:8", "Prov 15:1", "Eph 4:26-27", "Jas 1:19-20"],
    "forgiveness": ["Ps 103:12", "Matt 6:14-15", "Luke 23:34", "Eph 4:32"],
    "marriage": ["Gen 2:24", "Eph 5:25", "Eph 5:33", "1 Cor 13:4-7"],
    "parenting": ["Deut 6:6-7", "Prov 22:6", "Eph 6:4", "Col 3:21"],
    "temptation": ["1 Cor 10:13", "Jas 1:14-15", "Heb 4:15-16"],
    "suffering": ["Rom 5:3-5", "Rom 8:18", "2 Cor 4:17", "Jas 1:2-4", "1 Pet 4:12-13"],
    "death": ["Ps 23:4", "John 11:25-26", "1 Cor 15:55-57", "1 Thess 4:13-14"],
    "hope": ["Ps 42:11", "Rom 15:13", "Heb 6:19", "1 Pet 1:3"],
    "loneliness": ["Ps 68:6", "Isa 49:15-16", "Matt 28:20", "Heb 13:5"],
}


def counsel_topics() -> dict:
    return {"ok": True, "topics": sorted(COUNSEL_TOPICS),
            "note": "Pastoral situations with seed passages; coverage beyond "
                    "that comes from your installed library."}


def counsel_guide(topic: str, limit: int = 8) -> dict:
    key = (topic or "").strip().lower()
    if key not in COUNSEL_TOPICS:
        close = [t for t in COUNSEL_TOPICS if key and key in t]
        return {"ok": False, "error": f"No counsel topic {topic!r}",
                "topics": sorted(COUNSEL_TOPICS), "close": close}
    from . import search as _search
    seeds = COUNSEL_TOPICS[key]
    books = []
    try:
        opts = _search.SearchOpts(scope="books", limit=20, snippets=False,
                                  smart=False, fast=True)
        res = _search.search(key, opts)
        for h in (res.get("hits") or [])[:limit]:
            if not isinstance(h, dict):
                continue
            books.append({"module_id": h.get("module_id", ""),
                          "ref": h.get("label") or h.get("key", ""),
                          "snippet": (h.get("snippet") or "")[:220]})
    except Exception:  # noqa: BLE001
        pass
    # Related verses: what the installed Bibles hold with the word in them.
    verses = []
    try:
        opts = _search.SearchOpts(scope="bible", limit=12, snippets=False,
                                  smart=False, fast=True)
        res = _search.search(key, opts)
        for h in (res.get("hits") or [])[:limit]:
            if isinstance(h, dict):
                verses.append(h.get("label") or h.get("key", ""))
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "topic": key, "seed_passages": seeds,
            "verses": verses, "books": books,
            "note": "Seed passages are long-settled references; the rest is "
                    "what your installed library holds on the topic."}

"""The daily dashboard: what to read, where you were, what you wrote.

This is a landing view, not a feature of its own -- it composes what is already
installed.  Two things it deliberately does not do:

* It does not invent a "verse of the day".  Picking a verse by date is a hash,
  and a hash hands you the harshest verses on the same days as the kindest.
  The devotionals were written for this job and are installed.
* It does not read `history` for "where you left off".  That table records
  installs and removals, not reading.  Where you were is the cursor on the
  panes you actually have open, which is the honest answer.
"""

from __future__ import annotations

import time

from . import db, library, notes, workspace


def _today() -> tuple[str, str, str]:
    t = time.localtime()
    weekday = time.strftime("%a", t)   # e.g. Sun
    month = time.strftime("%b", t)     # e.g. Nov
    label = f"{weekday} {month} {t.tm_mday}, {t.tm_year}"
    return (f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}",
            time.strftime("%A", t), label)


def _devotional(day: str) -> list[dict]:
    """Today's entry from every devotional installed."""
    conn = db.connect()
    key = f"{time.localtime().tm_mon:02d}.{time.localtime().tm_mday:02d}"
    out = []
    for m in library.list_all():
        if m.type != "Devotional":
            continue
        r = conn.execute("SELECT key, title, text FROM unit WHERE module_id=? "
                         "AND key=?", (m.id, key)).fetchone()
        if r is None or not (r["text"] or "").strip():
            continue
        out.append({"module_id": m.id, "module": m.name, "title": r["title"] or day,
                    "text": (r["text"] or "")[:2400]})
    return out


def _where_you_left_off() -> list[dict]:
    """The panes you have open, with whatever position each one is at.

    A pane whose cursor is empty is still worth showing -- it is one click to
    open a resource you set up -- but it is listed after the ones that have a
    position, so the useful half of the answer comes first.
    """
    lay = workspace.current()
    if not lay:
        return []
    out = []
    for p in lay.get("panes", []):
        m = library.get(p.get("module_id") or "")
        if m is None:
            continue
        cur = p.get("cursor") or {}
        pos = cur.get("ref") or cur.get("key") or cur.get("date") or ""
        out.append({
            "pane_id": p["id"], "module_id": m.id, "module": m.name,
            "type": m.type, "reader": m.reader, "lang": m.lang,
            "position": pos, "span": cur.get("span") or "",
            "placed": bool(pos),
        })
    out.sort(key=lambda x: (not x["placed"], x["module"].lower()))
    return out


def build() -> dict:
    day, weekday, date_label = _today()
    notes_today = notes.listing(limit=6, since=time.time() - 86400 * 2)
    conn = db.connect()
    highlights = conn.execute(
        "SELECT count(*) c FROM highlight").fetchone()["c"]
    mods = conn.execute(
        "SELECT count(*) c FROM module WHERE installed_at>0").fetchone()["c"]
    units = conn.execute("SELECT count(*) c FROM unit").fetchone()["c"]
    return {
        "ok": True,
        "day": day,
        "weekday": weekday,
        "date": date_label,
        "readings": _devotional(day),
        "recent_notes": notes_today,
        "prayer": notes.prayer_day(),
        "where": _where_you_left_off(),
        "library": {"modules": mods, "units": units, "highlights": highlights},
        "notes_stats": notes.stats(),
        "layout": (workspace.current() or {}).get("name") or "",
    }

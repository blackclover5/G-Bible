"""Bring legacy Study-Tools sermons into the canonical note store.

For a while "Sermon import" wrote to its own on-the-fly ``sermons`` table while
the Sermon Manager, Sermons, Sermon Editor, Documents search, calendar and
backups all used ``note`` rows with ``kind='sermon'``.  A sermon imported from
Study Tools was therefore invisible everywhere else and never synced.

The move is idempotent and non-destructive: legacy rows are left in place, and
a note is created with a deterministic id so a second run does nothing.
"""

from __future__ import annotations

import json
import time

from . import db


def migrate_legacy_sermons() -> int:
    """Copy any unmigrated legacy sermons into note rows.  Returns the count."""
    conn = db.connect()
    if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sermons'"
    ).fetchone():
        return 0
    moved = 0
    try:
        rows = conn.execute(
            "SELECT id,title,series,text,created_at FROM sermons").fetchall()
    except Exception:  # noqa: BLE001 - a partial table must not block startup
        return 0
    for r in rows:
        nid = "legacy-" + str(r["id"] or "")
        if conn.execute("SELECT 1 FROM note WHERE id=?", (nid,)).fetchone():
            continue
        stamp = float(r["created_at"] or time.time())
        meta = {"series": r["series"] or ""} if r["series"] else {}
        conn.execute(
            "INSERT INTO note(id,kind,title,body,meta,tags,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (nid, "sermon", r["title"] or "Untitled Sermon",
             r["text"] or "", json.dumps(meta), "[]", stamp, stamp))
        moved += 1
    if moved:
        conn.commit()
    return moved

"""Spaced repetition (SM-2) for verses and passages.

A card is a single reference the reader wants to memorise.  Each review
updates an ease factor and an interval (in days) and moves the due date
forward.  Nothing here depends on a particular module: a card stores the
reference string and, when available, the module/unit it came from, so the
review screen can show the verse text.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from datetime import date, timedelta

from . import db


def _today() -> str:
    return date.today().isoformat()


def _row(r) -> dict:
    return {"id": r["id"], "ref": r["ref"], "module_id": r["module_id"],
            "unit_key": r["unit_key"], "ease": r["ease"],
            "interval": r["interval_days"], "due": r["due"],
            "reps": r["reps"], "lapses": r["lapses"],
            "created_at": r["created_at"], "last_reviewed": r["last_reviewed"]}


def add(ref: str, *, module_id: str = "", unit_key: str = "") -> dict:
    conn = db.connect()
    ref = (ref or "").strip()
    if not ref:
        return {"ok": False, "error": "reference required"}
    existing = conn.execute("SELECT id FROM srs_card WHERE ref=?", (ref,)).fetchone()
    if existing:
        return {"ok": True, "id": existing["id"], "already": True}
    cid = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO srs_card(id,ref,module_id,unit_key,ease,interval_days,due,"
        "reps,lapses,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (cid, ref, module_id or None, unit_key or None, 2.5, 0, _today(),
         0, 0, time.time()))
    conn.commit()
    return {"ok": True, "id": cid, "already": False}


def remove(card_id: str) -> dict:
    conn = db.connect()
    cur = conn.execute("DELETE FROM srs_card WHERE id=?", (card_id,))
    conn.commit()
    if cur.rowcount:
        try:
            from . import sync
            sync.tombstone(card_id, "srs-card")
        except Exception:
            pass
    return {"ok": True, "removed": bool(cur.rowcount)}


def due(limit: int = 50) -> list[dict]:
    conn = db.connect()
    today = _today()
    rows = conn.execute(
        "SELECT * FROM srs_card WHERE due <= ? ORDER BY due ASC, created_at ASC "
        "LIMIT ?", (today, limit)).fetchall()
    return [_row(r) for r in rows]


def all_cards() -> list[dict]:
    conn = db.connect()
    rows = conn.execute("SELECT * FROM srs_card ORDER BY due ASC").fetchall()
    return [_row(r) for r in rows]


def stats() -> dict:
    conn = db.connect()
    today = _today()
    total = conn.execute("SELECT count(*) c FROM srs_card").fetchone()["c"]
    due_n = conn.execute("SELECT count(*) c FROM srs_card WHERE due <= ?",
                         (today,)).fetchone()["c"]
    return {"total": total, "due": due_n, "today": today}


def review(card_id: str, grade: int) -> dict:
    """SM-2 update.  grade is 0 (again) .. 5 (easy); we accept 0/2/3/5."""
    conn = db.connect()
    row = conn.execute("SELECT * FROM srs_card WHERE id=?", (card_id,)).fetchone()
    if row is None:
        return {"ok": False, "error": "no such card"}
    ease = float(row["ease"] or 2.5)
    interval = int(row["interval_days"] or 0)
    reps = int(row["reps"] or 0)
    lapses = int(row["lapses"] or 0)
    grade = max(0, min(5, int(grade)))
    if grade < 3:
        reps = 0
        interval = 1
        lapses += 1
    else:
        if reps == 0:
            interval = 1
        elif reps == 1:
            interval = 6
        else:
            interval = max(1, round(interval * ease))
        reps += 1
    ease = ease + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
    if ease < 1.3:
        ease = 1.3
    due_date = (date.today() + timedelta(days=interval)).isoformat()
    conn.execute(
        "UPDATE srs_card SET ease=?, interval_days=?, due=?, reps=?, lapses=?, "
        "last_reviewed=? WHERE id=?",
        (ease, interval, due_date, reps, lapses, time.time(), card_id))
    conn.commit()
    return {"ok": True, "id": card_id, "ease": ease, "interval": interval,
            "due": due_date, "reps": reps, "lapses": lapses}


def grade_for(label: str) -> int:
    return {"again": 0, "hard": 2, "good": 3, "easy": 5}.get(
        (label or "").lower(), 3)

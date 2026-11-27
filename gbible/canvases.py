"""The single canvas model, and the one-time move of old canvases into it.

For a while G-Bible kept two things called a canvas: a list of JSON elements in
the ``canvases`` setting (shown on the Today tab) and proper ``canvas_board`` /
``canvas_node`` / ``canvas_edge`` rows (shown in the Canvas view).  They held
the same kind of study — boxes of notes and verses joined by arrows — but could
not see each other.

This module copies the old setting-based canvases into boards.  It is idempotent
and deliberately non-destructive: the original setting is left exactly where it
was, so a restore of an older backup can still be migrated later.
"""

from __future__ import annotations

import json
import time
import uuid

from . import db

LEGACY_KEY = "canvases"
_NODE_KINDS = ("heading", "text", "verse")


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


def migrate_legacy_canvases() -> int:
    """Copy any unmigrated legacy canvases into boards.

    Returns how many boards were created.  Nothing is deleted or rewritten: a
    canvas whose id is already a board is skipped, so the function is safe to
    run at every startup and after every restore.
    """
    legacy = db.get_setting(LEGACY_KEY, [])
    if not isinstance(legacy, list) or not legacy:
        return 0
    conn = db.connect()
    created = 0
    for c in legacy:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "").strip()
        if not cid:
            continue
        if conn.execute("SELECT 1 FROM canvas_board WHERE id=?", (cid,)).fetchone():
            continue
        stamp = float(c.get("updated_at") or time.time())
        conn.execute(
            "INSERT INTO canvas_board(id,name,created_at,updated_at) VALUES(?,?,?,?)",
            (cid, str(c.get("name") or "Canvas"), stamp, stamp))
        elements = [e for e in (c.get("elements") or []) if isinstance(e, dict)]
        remap: dict[str, str] = {}
        for e in elements:
            if str(e.get("kind") or "") == "arrow":
                continue                      # arrows become edges, not cards
            old_id = str(e.get("id") or "")
            nid = _short_id()
            if old_id:
                remap[old_id] = nid
            kind = str(e.get("kind") or "text")
            if kind not in _NODE_KINDS and kind != "arrow":
                # An unrecognised element is kept as a card and its exact JSON
                # is stored in `data`, just as the old renderer kept it in the
                # save without drawing it.
                kind = "text"
            conn.execute(
                "INSERT INTO canvas_node(id,board_id,kind,x,y,w,h,text,ref,color,"
                "module_id,data,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (nid, cid, kind,
                 float(e.get("x") or 0), float(e.get("y") or 0),
                 float(e.get("w") or 220), float(e.get("h") or 100),
                 str(e.get("text") or ""), str(e.get("ref") or ""),
                 str(e.get("color") or "yellow"),
                 str(e.get("module_id") or ""),
                 json.dumps(e, ensure_ascii=False), stamp))
        for e in elements:
            if str(e.get("kind") or "") != "arrow":
                continue
            f = remap.get(str(e.get("from") or ""))
            t = remap.get(str(e.get("to") or ""))
            if f and t and f != t:
                conn.execute(
                    "INSERT INTO canvas_edge(id,board_id,from_id,to_id) VALUES(?,?,?,?)",
                    (_short_id(), cid, f, t))
        created += 1
    if created:
        conn.commit()
    return created

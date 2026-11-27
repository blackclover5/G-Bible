"""Freeform study canvas: boards, cards and connector lines.

A board is a single named plane.  Cards hold text or a verse reference
(clicking the ref opens the passage).  Edges are directional connections
between cards.  Boards are stored in SQLite; saving replaces the whole board.
"""
import html
import uuid
from .common import *


def esc(s):
    return html.escape(str(s or ''), quote=True)


def _ensure_board():
    conn = db.connect()
    if not conn.execute("SELECT COUNT(*) FROM canvas_board").fetchone()[0]:
        bid = str(uuid.uuid4().hex)[:12]
        conn.execute(
            "INSERT INTO canvas_board(id,name,created_at,updated_at) VALUES(?,?,?,?)",
            (bid, "My Canvas", time.time(), time.time()))
        conn.commit()
    return conn.execute("SELECT id FROM canvas_board ORDER BY updated_at DESC LIMIT 1").fetchone()["id"]


def _load_board(conn, board_id):
    nodes = [dict(r) for r in conn.execute(
        "SELECT * FROM canvas_node WHERE board_id=? ORDER BY created_at", (board_id,))]
    edges = [dict(r) for r in conn.execute(
        "SELECT * FROM canvas_edge WHERE board_id=?", (board_id,))]
    b = conn.execute("SELECT * FROM canvas_board WHERE id=?", (board_id,)).fetchone()
    return {"board": dict(b) if b else None, "nodes": nodes, "edges": edges}


@endpoint("canvas/boards")
def _canvas_boards(parts, q):
    # A restored backup may have brought back old setting-based canvases.
    canvases.migrate_legacy_canvases()
    default = _ensure_board()
    conn = db.connect()
    rows = [dict(r) for r in conn.execute(
        "SELECT id, name, created_at, updated_at FROM canvas_board ORDER BY updated_at DESC")]
    return _ok(boards=rows, default=default)


@endpoint("canvas/board")
def _canvas_board(parts, q):
    canvases.migrate_legacy_canvases()
    conn = db.connect()
    action = (q.get("action") or "").strip()
    if action == "create":
        name = (q.get("name") or "Canvas").strip() or "Canvas"
        bid = str(uuid.uuid4().hex)[:12]
        conn.execute(
            "INSERT INTO canvas_board(id,name,created_at,updated_at) VALUES(?,?,?,?)",
            (bid, name, time.time(), time.time()))
        conn.commit()
        return _ok(board=_load_board(conn, bid)["board"])
    if action == "rename":
        name = (q.get("name") or "Canvas").strip() or "Canvas"
        cur = conn.execute(
            "UPDATE canvas_board SET name=?, updated_at=? WHERE id=?",
            (name, time.time(), q.get("board", "")))
        if not cur.rowcount:
            return {"ok": False, "error": "no such board"}
        conn.commit()
        return _ok()
    if action == "remove":
        bid = q.get("board", "")
        if conn.execute("SELECT 1 FROM canvas_board WHERE id=?", (bid,)).fetchone() is None:
            return {"ok": False, "error": "no such board"}
        with conn:
            conn.execute("DELETE FROM canvas_node WHERE board_id=?", (bid,))
            conn.execute("DELETE FROM canvas_edge WHERE board_id=?", (bid,))
            conn.execute("DELETE FROM canvas_board WHERE id=?", (bid,))
        try:
            sync.tombstone(bid, "canvas-board")
        except Exception:                                   # noqa: BLE001
            pass
        return _ok()
    bid = q.get("board") or _ensure_board()
    return _ok(**_load_board(conn, bid))


@endpoint("canvas/save")
def _canvas_save(parts, q):
    conn = db.connect()
    board = q.get("board", "")
    if not board:
        return {"ok": False, "error": "no board"}
    if conn.execute("SELECT 1 FROM canvas_board WHERE id=?", (board,)).fetchone() is None:
        return {"ok": False, "error": "no such board"}
    nodes = q.get("nodes") if isinstance(q.get("nodes"), list) else []
    edges = q.get("edges") if isinstance(q.get("edges"), list) else []
    now = time.time()
    try:
        with conn:     # rollback the whole board if one row fails
            conn.execute("DELETE FROM canvas_node WHERE board_id=?", (board,))
            conn.execute("DELETE FROM canvas_edge WHERE board_id=?", (board,))
            ids = set()
            for n in nodes:
                nid = str(n.get("id") or uuid.uuid4().hex)[:12]
                ids.add(nid)
                conn.execute(
                    "INSERT INTO canvas_node(id,board_id,kind,x,y,w,h,text,ref,color,"
                    "module_id,data,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (nid, board,
                     str(n.get("kind") or "text"), float(n.get("x", 0)),
                     float(n.get("y", 0)), float(n.get("w", 200)),
                     float(n.get("h", 100)), str(n.get("text") or ""),
                     str(n.get("ref") or ""), str(n.get("color") or "yellow"),
                     str(n.get("module_id") or ""), str(n.get("data") or ""), now))
            for e in edges:
                f, t = str(e.get("from") or ""), str(e.get("to") or "")
                if f and t and f != t and f in ids and t in ids:
                    conn.execute(
                        "INSERT INTO canvas_edge(id,board_id,from_id,to_id) "
                        "VALUES(?,?,?,?)",
                        (uuid.uuid4().hex[:12], board, f, t))
            conn.execute("UPDATE canvas_board SET updated_at=? WHERE id=?",
                         (now, board))
    except (ValueError, TypeError) as e:
        return {"ok": False, "error": f"invalid board data: {e}"}
    return _ok()


@endpoint("canvas/export")
def _canvas_export(parts, q):
    """A printable HTML snapshot of the board (for Print.save as PDF)."""
    conn = db.connect()
    bid = q.get("board") or _ensure_board()
    state = _load_board(conn, bid)
    rows = []
    for n in state["nodes"]:
        ref = n.get("ref") or ""
        body = esc(n.get("text") or "").replace("\n", "<br>")
        if n.get("kind") == "verse" and ref:
            rows.append(f'<div class="cv-card cv-{esc(n.get("color") or "yellow")}">'
                        f'<div class="cv-ref">{esc(ref)}</div>'
                        f'<div class="cv-text">{body}</div></div>')
        elif n.get("kind") == "heading":
            rows.append(f'<h3 class="cv-card cv-{esc(n.get("color") or "yellow")}">'
                        f'{body}</h3>')
        else:
            rows.append(f'<div class="cv-card cv-{esc(n.get("color") or "yellow")}">'
                        f'<div class="cv-text">{body}</div></div>')
    return _ok(html="".join(rows), name=(state["board"] or {}).get("name", "Canvas"))

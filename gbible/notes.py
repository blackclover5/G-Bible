"""Notes, journal entries, prayer lists and sermon preparation.

These are one object with four intents, so they live in one table.  What differs
between them is not the storage but the shape a reader expects:

  note     -- anchored to a verse, short, usually with a quote
  journal  -- dated, free, belongs to a day rather than a passage
  prayer   -- dated, with a list of items that can be marked off
  sermon   -- a text, an outline, and the passages gathered for it

Keeping them together means a passage you highlighted while preaching can be
promoted into the sermon note, and the prayer list is a note you can tick.
"""

from __future__ import annotations

import json
import time
import uuid

from . import db, library

KINDS = ("note", "journal", "sermon", "prayer")


def _row_to_note(r) -> dict:
    def loads(v, default):
        try:
            return json.loads(v) if v else default
        except (json.JSONDecodeError, TypeError):
            return default
    return {
        "id": r["id"], "kind": r["kind"], "title": r["title"] or "",
        "body": r["body"] or "", "module_id": r["module_id"] or "",
        "unit_key": r["unit_key"] or "", "ref_label": r["ref_label"] or "",
        "tags": loads(r["tags"], []), "meta": loads(r["meta"], {}),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def save(data: dict) -> dict:
    """Create or update one note.  `id` absent means create.

    `created_at` and `updated_at` are taken from the record when it carries
    them.  A note restored from sync was written on another machine, and
    stamping it with *this* machine's clock would rewrite the date the reader
    wrote it -- a journal entry from last month would arrive dated today.  It
    also breaks sync itself, because the record's content would differ from the
    version that was sent, and no two devices could agree on anything.
    """
    conn = db.connect()
    now = time.time()
    created = float(data.get("created_at") or now)
    updated = float(data.get("updated_at") or now)
    nid = (data.get("id") or "").strip() or uuid.uuid4().hex[:12]
    kind = (data.get("kind") or "").strip()
    if kind and kind not in KINDS:
        kind = ""
    row = conn.execute("SELECT * FROM note WHERE id=?", (nid,)).fetchone()
    # A partial update -- one that carries only `meta`, say, the way the sermon
    # outline and builder save their fields -- must not silently re-file the
    # note.  Defaulting an absent kind to "note" meant saving a sermon's
    # outline demoted it to a plain note, so it then vanished from the sermon
    # manager and from the list it had always appeared in.  An update with no
    # kind keeps the stored one.
    if row is not None and not kind:
        kind = row["kind"]
    kind = kind or "note"
    if row is None:
        conn.execute(
            "INSERT INTO note(id,kind,title,body,module_id,unit_key,ref_label,"
            "tags,meta,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (nid, kind, data.get("title") or "", data.get("body") or "",
             data.get("module_id") or "", data.get("unit_key") or "",
             data.get("ref_label") or "",
             json.dumps(data.get("tags") or []),
             json.dumps(data.get("meta") or {}), created, updated))
    else:
        old = _row_to_note(row)
        conn.execute(
            "UPDATE note SET kind=?,title=?,body=?,module_id=?,unit_key=?,"
            "ref_label=?,tags=?,meta=?,updated_at=? WHERE id=?",
            (kind,
             data.get("title") if data.get("title") is not None else old["title"],
             data.get("body") if data.get("body") is not None else old["body"],
             data.get("module_id", old["module_id"]),
             data.get("unit_key", old["unit_key"]),
             data.get("ref_label", old["ref_label"]),
             json.dumps(data.get("tags") if data.get("tags") is not None
                        else old["tags"]),
             json.dumps(data.get("meta") if data.get("meta") is not None
                        else old["meta"]),
             updated, nid))
    conn.commit()
    return _row_to_note(conn.execute("SELECT * FROM note WHERE id=?", (nid,)).fetchone())


def get(note_id: str) -> dict | None:
    r = db.connect().execute("SELECT * FROM note WHERE id=?", (note_id,)).fetchone()
    return _row_to_note(r) if r else None


def remove(note_id: str) -> bool:
    conn = db.connect()
    cur = conn.execute("DELETE FROM note WHERE id=?", (note_id,))
    conn.commit()
    if cur.rowcount:
        _tombstone(note_id, "note")
    return cur.rowcount > 0


def clear(kind: str = "") -> dict:
    """Delete notes, optionally only one kind. The count is reported, and an
    empty library afterwards is the success state — not an error."""
    conn = db.connect()
    if kind:
        kinds = [k for k in kind.split(",") if k in KINDS]
        if not kinds:
            return {"ok": False, "error": f"Unknown kind {kind!r}"}
        gone = [r["id"] for r in conn.execute(
            "SELECT id FROM note WHERE kind IN "
            f"({','.join('?' * len(kinds))})", kinds)]
        cur = conn.execute(
            f"DELETE FROM note WHERE kind IN ({','.join('?' * len(kinds))})",
            kinds)
    else:
        gone = [r["id"] for r in conn.execute("SELECT id FROM note")]
        cur = conn.execute("DELETE FROM note")
    conn.commit()
    for nid in gone:
        _tombstone(nid, "note")
    return {"ok": True, "removed": cur.rowcount,
            "scope": kind or "everything"}


def _tombstone(note_id: str, kind: str) -> None:
    """Record a delete so sync does not bring the note back.

    Only recorded when the note had been synced: one written and deleted while
    sync was off was never anywhere else, and a tombstone for it would only
    grow the folder.
    """
    try:
        from . import sync
        sync.tombstone(note_id, kind)
    except Exception:
        pass


def listing(kind: str = "", *, q: str = "", tag: str = "",
            limit: int = 500, since: float = 0.0) -> list[dict]:
    """Notes, newest first, optionally filtered by kind, text and tag."""
    sql = "SELECT * FROM note WHERE 1=1"
    a: list = []
    if kind:
        kinds = [k for k in kind.split(",") if k in KINDS]
        if kinds:
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            a += kinds
    if since:
        sql += " AND (created_at>=? OR updated_at>=?)"
        a += [since, since]
    sql += " ORDER BY COALESCE(updated_at, created_at) DESC LIMIT ?"
    a.append(limit)
    out = [_row_to_note(r) for r in db.connect().execute(sql, a)]
    if q:
        ql = q.lower()
        out = [n for n in out
               if ql in (n["title"] + " " + n["body"] + " " + n["ref_label"]).lower()]
    if tag:
        out = [n for n in out if tag in (n["tags"] or [])]
    return out


def notes_at(module_id: str, unit_key: str) -> list[dict]:
    return [_row_to_note(r) for r in db.connect().execute(
        "SELECT * FROM note WHERE module_id=? AND unit_key=? "
        "ORDER BY updated_at DESC", (module_id, unit_key))]


def stats() -> dict:
    conn = db.connect()
    out = {}
    for r in conn.execute("SELECT kind, count(*) c FROM note GROUP BY kind"):
        out[r["kind"]] = r["c"]
    words = conn.execute(
        "SELECT count(*) c FROM (SELECT 1 FROM note WHERE body<>'')").fetchone()[0]
    return {"by_kind": out, "total": sum(out.values()), "with_body": words}


# ------------------------------------------------------------------ prayer

def prayer_day(day: str | None = None) -> dict | None:
    """The prayer list for a day, or for today."""
    conn = db.connect()
    row = None
    if day:
        row = conn.execute(
            "SELECT * FROM note WHERE kind='prayer' AND ref_label=? LIMIT 1",
            (day,)).fetchone()
    if row is None:
        today = time.localtime()
        day = f"{today.tm_year:04d}-{today.tm_mon:02d}-{today.tm_mday:02d}"
        row = conn.execute(
            "SELECT * FROM note WHERE kind='prayer' AND ref_label=? LIMIT 1",
            (day,)).fetchone()
    return _row_to_note(row) if row else None


# ------------------------------------------------------------- export

def export_markdown(kind: str = "") -> str:
    """Every note as one Markdown file -- the format a person keeps forever.

    Notebook, Obsidian and plain git all read Markdown, and a local app that
    keeps your writing in a SQLite table the user cannot reach is a worse place
    to keep it than a file.
    """
    out: list[str] = ["# Notes", ""]
    for kind_name in ([kind] if kind else list(KINDS)):
        items = listing(kind_name, limit=100000)
        if not items:
            continue
        out.append(f"## {kind_name.title()}")
        out.append("")
        for n in items:
            when = time.strftime("%Y-%m-%d", time.localtime(n["updated_at"] or 0))
            head = f"### {n['title'] or '(untitled)'}"
            bits = [when]
            if n["ref_label"]:
                bits.append(n["ref_label"])
            if n["tags"]:
                bits.append(", ".join(n["tags"]))
            out.append(f"{head} — {' · '.join(bits)}")
            if n["body"]:
                out.append("")
                out.append(n["body"])
            if n["kind"] == "sermon" and n["meta"].get("passages"):
                out.append("")
                out.append("**Passages**")
                for p in n["meta"]["passages"]:
                    out.append(f"- {p}")
            out.append("")
    return "\n".join(out)

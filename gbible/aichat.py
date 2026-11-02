"""The conversations the reader has had with the assistant.

The assistant's history used to live in one array in the browser, which meant
two things a reader notices immediately: the conversation was gone when the
app was closed, and there was no way back to a question asked last week.  A
question is worth keeping for both reasons.  The question asked on Sunday is
usually the question being asked again on Wednesday, and the answer that
settled it is not something to have to re-derive.

So the exchange is written down, and the reader can pick it up again.

What is kept
------------
The turns, and the citations of each answer.  The citations matter as much as
the words: a conversation whose answers cannot be traced back to the passages
they came from is a record of a claim, and the whole design of the assistant
is that a claim can be checked.

What is not kept
----------------
Nothing leaves the machine.  A conversation is a local record like the usage
record, and it is not synced: it is a transcript of what the reader asked and
what was said back, and a reader who does not want one on another machine
should not have one there.
"""

from __future__ import annotations

import json
import time
import uuid

from . import db

#: How many conversations the reader is shown.  Enough to find last month's
#: question without a search box, few enough that the list is a list.
RECENT = 50

#: A title is a question the reader asked, shortened.  It is the only thing
#: shown in the list, so it has to be recognisable at a glance.
_TITLE_MAX = 60


def _id() -> str:
    return uuid.uuid4().hex[:12]


def title_for(turns: list[dict]) -> str:
    """A conversation's title, taken from the first question in it.

    The reader's own words, because a title that is written by the software is
    a title that means the same thing for every conversation: "New chat" is
    not a title, it is a shrug.
    """
    for t in turns or []:
        if t.get("role") != "user":
            continue
        text = (t.get("content") or "").strip()
        if not text:
            continue
        # The overview is asked with an instruction the model was given, not
        # one the reader typed, and it is not a title.
        if t.get("internal"):
            continue
        text = " ".join(text.split())
        if len(text) > _TITLE_MAX:
            text = text[:_TITLE_MAX].rsplit(" ", 1)[0] + "…"
        return text
    return "Untitled"


def new(title: str = "") -> dict:
    """Start a conversation.  The title is filled in from the first question."""
    cid = _id()
    now = time.time()
    conn = db.connect()
    conn.execute(
        "INSERT INTO ai_chat(id,title,created_at,updated_at) VALUES(?,?,?,?)",
        (cid, (title or "").strip() or "New chat", now, now))
    conn.commit()
    return {"id": cid, "title": (title or "").strip() or "New chat",
            "created_at": now, "updated_at": now, "turns": []}


def save(chat_id: str, turns: list[dict], title: str = "") -> dict:
    """Write the exchange down, replacing whatever was there.

    The whole exchange is written each time rather than appended to: the
    reader can edit a question and ask again, and a conversation that
    remembers an abandoned attempt is a conversation that lies about what was
    asked.
    """
    chat_id = (chat_id or "").strip() or new()["id"]
    now = time.time()
    conn = db.connect()
    row = conn.execute("SELECT id,created_at FROM ai_chat WHERE id=?",
                       (chat_id,)).fetchone()
    created = float(row["created_at"]) if row else now
    if row is None:
        conn.execute(
            "INSERT INTO ai_chat(id,title,created_at,updated_at) "
            "VALUES(?,?,?,?)", (chat_id, "", created, now))
    conn.execute("DELETE FROM ai_chat_turn WHERE chat_id=?", (chat_id,))
    for i, t in enumerate(turns or []):
        role = t.get("role")
        if role not in ("user", "assistant"):
            continue
        content = str(t.get("content") or "")
        cites = t.get("citations") or []
        try:
            cites_json = json.dumps(cites, ensure_ascii=False)
        except (TypeError, ValueError):
            cites_json = "[]"
        conn.execute(
            "INSERT INTO ai_chat_turn(chat_id,ord,role,content,cites) "
            "VALUES(?,?,?,?,?)", (chat_id, i, role, content, cites_json))
    name = (title or "").strip() or title_for(turns)
    if name:
        conn.execute("UPDATE ai_chat SET title=?, updated_at=? WHERE id=?",
                     (name, now, chat_id))
    else:
        conn.execute("UPDATE ai_chat SET updated_at=? WHERE id=?",
                     (now, chat_id))
    conn.commit()
    return {"id": chat_id, "title": name, "created_at": created,
            "updated_at": now}


def listing(limit: int = RECENT) -> list[dict]:
    """The conversations, most recently touched first."""
    try:
        limit = max(1, min(200, int(limit or RECENT)))
    except (TypeError, ValueError):
        limit = RECENT
    rows = db.connect().execute(
        "SELECT id,title,created_at,updated_at FROM ai_chat "
        "ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        n = db.connect().execute(
            "SELECT count(*) c FROM ai_chat_turn WHERE chat_id=?",
            (r["id"],)).fetchone()["c"]
        out.append({"id": r["id"], "title": r["title"] or "Untitled",
                    "created_at": r["created_at"], "updated_at": r["updated_at"],
                    "turns": int(n)})
    return out


def get(chat_id: str) -> dict | None:
    """One conversation, with its exchange."""
    row = db.connect().execute("SELECT * FROM ai_chat WHERE id=?",
                               (chat_id,)).fetchone()
    if row is None:
        return None
    turns = []
    for t in db.connect().execute(
            "SELECT role,content,cites FROM ai_chat_turn WHERE chat_id=? "
            "ORDER BY ord", (chat_id,)):
        try:
            cites = json.loads(t["cites"]) if t["cites"] else []
        except (json.JSONDecodeError, TypeError):
            cites = []
        if not isinstance(cites, list):
            cites = []
        turns.append({"role": t["role"], "content": t["content"] or "",
                      "citations": cites})
    return {"id": row["id"], "title": row["title"] or "Untitled",
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "turns": turns}


def remove(chat_id: str) -> bool:
    """Forget a conversation.  The reader's own record is theirs to erase."""
    conn = db.connect()
    cur = conn.execute("DELETE FROM ai_chat WHERE id=?", (chat_id,))
    conn.execute("DELETE FROM ai_chat_turn WHERE chat_id=?", (chat_id,))
    conn.commit()
    return bool(cur.rowcount)


def rename(chat_id: str, title: str) -> dict:
    """Give a conversation a name of the reader's own choosing."""
    name = (title or "").strip() or "Untitled"
    conn = db.connect()
    cur = conn.execute("UPDATE ai_chat SET title=? WHERE id=?",
                       (name, chat_id))
    conn.commit()
    if not cur.rowcount:
        return {"ok": False, "error": "No such conversation."}
    return {"ok": True, "id": chat_id, "title": name}


def latest() -> dict | None:
    """The conversation that was last being had, if there was one.

    This is what makes the assistant pick up where the reader left off
    rather than starting blank every time the app is opened.
    """
    rows = listing(1)
    return get(rows[0]["id"]) if rows else None


# ==========================================================================
# Export
# ==========================================================================
# A conversation is the reader's own writing, and the way to share that
# writing is a file they attach to a message themselves -- not a link, which
# would put the whole thing in a URL bar and in whatever logs the link
# reaches.  The export carries the citations as text, so the reader can see
# where an answer came from even on a machine that does not have the books.

def _when() -> str:
    return time.strftime("%d %B %Y", time.localtime())


def export_filename(title: str) -> str:
    """A safe file name for the export."""
    t = " ".join((title or "").split()) or "conversation"
    t = "".join(c if c.isalnum() or c in " -_" else "" for c in t)
    t = " ".join(t.split())[:60] or "conversation"
    return t.lower().replace(" ", "-") + ".md"


def export_markdown(turns: list[dict], title: str = "") -> str:
    """The conversation as a Markdown document.

    Each answer carries its sources, with the passage each one came from, so
    the document can be checked on a machine that does not have the library.
    """
    out: list[str] = []
    heading = (title or "").strip() or "Conversation"
    out.append("# " + heading)
    out.append("")
    out.append(f"*Exported from G-Bible on {_when()}.*")
    out.append("")
    n = 0
    for t in turns or []:
        role = t.get("role")
        text = (t.get("content") or "").strip()
        if role == "user":
            n += 1
            out.append(f"## {n}. {text}")
            out.append("")
        elif role == "assistant" and text:
            out.append(text)
            out.append("")
            cites = t.get("citations") or []
            if cites:
                out.append("**Sources**")
                out.append("")
                for i, c in enumerate(cites, 1):
                    label = c.get("label") or c.get("title") or ""
                    where = c.get("module_name") or ""
                    head = f"{i}. {label}" + (f" — {where}" if where else "")
                    out.append(head)
                    body = (c.get("text") or "").strip()
                    if body:
                        for line in body.splitlines():
                            out.append("   > " + line)
                out.append("")
    return "\n".join(out).rstrip() + "\n"


def count() -> int:
    try:
        return int(db.connect().execute(
            "SELECT count(*) c FROM ai_chat").fetchone()["c"])
    except Exception:                                    # noqa: BLE001
        return 0

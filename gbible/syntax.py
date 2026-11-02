"""Stored syntax trees: search and display.

Complements the spaCy dependency parse (statistical, English) with treebank
data (human- or rule-annotated, Greek/Hebrew/...) where a CoNLL-U module is
installed. Edges live in `unit.extra["syntax"]`; this module only reads them.
No treebank installed means every query says so rather than falling back to a
guess.
"""

from __future__ import annotations

import json

from . import db, library


def _syntax_modules(module_id: str = "") -> list:
    mods = [m for m in library.list_all() if m.type == "Syntax"]
    if module_id:
        mods = [m for m in mods if m.id == module_id]
    return mods


def _edges_of(extra: str) -> list[dict]:
    try:
        d = json.loads(extra or "{}")
    except (json.JSONDecodeError, TypeError):
        return []
    edges = d.get("syntax")
    return edges if isinstance(edges, list) else []


def syntax_search(*, module_id: str = "", upos: str = "", deprel: str = "",
                  form: str = "", lemma: str = "",
                  limit: int = 100) -> dict:
    """Find treebank tokens by annotation: `upos=VERB deprel=obj` and the
    like. LIKE-prefiltered in SQL, then exact-matched in Python."""
    mods = _syntax_modules(module_id)
    if not mods:
        return {"ok": True, "items": [], "total": 0,
                "note": "No syntax treebank installed. Import a CoNLL-U file "
                        "from 'This computer' with its licence stated."}
    conn = db.connect()
    likes, args = [], []
    for needle in (upos, deprel, form, lemma):
        if needle:
            likes.append("extra LIKE ?")
            args.append(f"%{needle}%")
    out = []
    for m in mods:
        sql = ("SELECT key, ref_label, extra FROM unit WHERE module_id=?")
        a = [m.id]
        if likes:
            sql += " AND (" + " OR ".join(likes) + ")"
            a += args
        sql += " LIMIT 5000"
        for r in conn.execute(sql, a).fetchall():
            for e in _edges_of(r["extra"]):
                if upos and e.get("upos", "").lower() != upos.lower():
                    continue
                if deprel and e.get("deprel", "").lower() != deprel.lower():
                    continue
                if form and form.lower() not in e.get("form", "").lower():
                    continue
                if lemma and lemma.lower() not in e.get("lemma", "").lower():
                    continue
                out.append({"module_id": m.id, "module": m.name,
                            "key": r["key"], "ref": r["ref_label"],
                            "token": e})
                if len(out) >= limit:
                    return {"ok": True, "items": out, "total": len(out),
                            "truncated": True}
    return {"ok": True, "items": out, "total": len(out), "truncated": False}


def syntax_sentence(module_id: str, key: str) -> dict:
    """One stored tree: edges plus an indented rendering (roots first)."""
    m = library.get(module_id)
    if m is None or m.type != "Syntax":
        return {"ok": False, "error": "Not a syntax treebank module"}
    conn = db.connect()
    r = conn.execute("SELECT ref_label, text, extra FROM unit "
                     "WHERE module_id=? AND key=?", (module_id, key)).fetchone()
    if r is None:
        return {"ok": False, "error": "No such sentence"}
    edges = _edges_of(r["extra"])
    if not edges:
        return {"ok": False, "error": "That unit carries no tree"}
    by_id = {e["id"]: e for e in edges}
    children: dict[str, list[dict]] = {}
    roots = []
    for e in edges:
        h = str(e.get("head") or 0)
        if h == "0" or h not in by_id:
            roots.append(e)
        else:
            children.setdefault(h, []).append(e)
    lines: list[str] = []

    def walk(e: dict, depth: int) -> None:
        lines.append("  " * depth + f"{e['form']} "
                     f"({e.get('upos', '?')} : {e.get('deprel', '?')})")
        for c in children.get(str(e["id"]), []):
            walk(c, depth + 1)

    for rt in roots:
        walk(rt, 0)
    return {"ok": True, "module_id": module_id, "key": key,
            "ref": r["ref_label"], "text": r["text"], "edges": edges,
            "tree": "\n".join(lines),
            "note": "Stored treebank analysis — not a parser guess."}

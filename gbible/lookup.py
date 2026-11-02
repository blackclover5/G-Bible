"""Cited By, Information lookup, Important Words — from installed content.

* **Cited By** answers "where is this verse cited": outgoing cross-refs from
  the verse plus incoming ones (other verses' entries citing it), grouped by
  resource, scoped to open panes, the whole library, or one collection.
* **Information** is the follow-pane card: the verse in the Top Bible, its
  people/places/words, and how much of the library bears on it.
* **Important Words** ranks the verse's tagged words by how often the
  installed commentaries discuss them — commentary attention, not a licensed
  dataset.
"""

from __future__ import annotations

from . import canon, db, library


def cited_by(ref: str, module_ids: list[str] | None = None,
             collection_id: str = "") -> dict:
    rr = canon.parse_ref(ref)
    if rr is None:
        return {"ok": False, "error": f"Cannot read {ref!r}"}
    key = next(iter(rr.refs())).osis_id()
    if collection_id:
        from . import organise
        scope = set(organise.collection_members(collection_id))
    elif module_ids:
        scope = set(module_ids)
    else:
        scope = set()
    conn = db.connect()
    mods = {m.id: m for m in library.list_all()}
    out = {"outgoing": {}, "incoming": {}}
    for (mid, fk, tk) in conn.execute(
            "SELECT module_id, from_key, to_key FROM xref "
            "WHERE from_key=? OR to_key=? LIMIT 2000", (key, key)).fetchall():
        if scope and mid not in scope:
            continue
        m = mods.get(mid)
        name = m.name if m else mid
        if fk == key:
            out["outgoing"].setdefault(name, [])
            if tk not in out["outgoing"][name]:
                out["outgoing"][name].append(tk)
        else:
            out["incoming"].setdefault(name, [])
            if fk not in out["incoming"][name]:
                out["incoming"][name].append(fk)
    n_out = sum(len(v) for v in out["outgoing"].values())
    n_in = sum(len(v) for v in out["incoming"].values())
    return {"ok": True, "ref": ref, "key": key,
            "outgoing": out["outgoing"], "incoming": out["incoming"],
            "cited_by_count": n_in, "cites_count": n_out,
            "scope": "collection" if collection_id else (
                "selected" if module_ids else "library"),
            "note": "Cross-reference-table citations only — commentaries "
                    "discussing the verse without a formal cross-ref are in "
                    "the Commentaries section, not here."}


def info_lookup(ref: str = "", word: str = "") -> dict:
    """One follow-pane card for a verse or a word."""
    from . import study
    from . import workspace as _ws
    card: dict = {"ok": True}
    if word:
        num = canon.normalise_strongs(word) or ""
        conn = db.connect()
        try:
            entries = study.lexicon_entries_for(conn, num or word, limit=3)
        except Exception:  # noqa: BLE001
            entries = []
        card["word"] = word
        card["gloss"] = (entries[0]["text"][:220] if entries else "")
        card["sources"] = [e["module"] for e in entries]
        if not entries:
            card["note"] = "No installed lexicon has this word."
        return card
    rr = canon.parse_ref(ref or "")
    if rr is None:
        return {"ok": False, "error": f"Cannot read {ref!r}"}
    f = next(iter(rr.refs()))
    top = _ws.top_bible_module()
    text = ""
    if top is not None:
        conn = db.connect()
        r = conn.execute("SELECT text FROM unit WHERE module_id=? AND book=? "
                         "AND chapter=? AND verse=? LIMIT 1",
                         (top.id, f.book, f.chapter or 0, f.verse or 1)).fetchone()
        if r:
            text = (r["text"] or "").strip()
    try:
        people = study.fact_tags(
            f"{f.book} {f.chapter}:{f.verse or 1}", limit=8) or []
    except Exception:  # noqa: BLE001
        people = []
    try:
        places = study.places_at(f.book, f.chapter or 0, f.verse or 1) or []
    except Exception:  # noqa: BLE001
        places = []
    conn = db.connect()
    osis = f"{f.book}.{f.chapter}.{f.verse or 1}"
    xr = conn.execute("SELECT COUNT(*) c FROM xref WHERE from_key=? OR to_key=?",
                      (osis, osis)).fetchone()["c"]
    comm = conn.execute("SELECT COUNT(*) c FROM unit u JOIN module m "
                        "ON m.id=u.module_id WHERE m.type='Commentary' AND "
                        "u.book=? AND u.chapter=?", (f.book, f.chapter or 0)
                        ).fetchone()["c"]
    card.update({"ref": ref, "text": text,
                 "bible": top.name if top else "",
                 "people": people, "places": places,
                 "crossrefs": xr, "commentary_notes": comm})
    return card


def important_words(ref: str, limit: int = 10) -> dict:
    """The verse's tagged words, ranked by commentary attention.

    Attention is literal: occurrences of the word's surface forms in the
    installed commentary notes anchored at this verse or chapter. A word no
    commentary discusses scores zero and is listed as such rather than
    dropped.
    """
    from . import study
    rr = canon.parse_ref(ref)
    if rr is None:
        return {"ok": False, "error": f"Cannot read {ref!r}"}
    f = next(iter(rr.refs()))
    conn = db.connect()
    tagged = [m.id for m in library.list_all()
              if m.is_bible and (m.has_strongs or m.has_morph)]
    if not tagged:
        return {"ok": True, "items": [],
                "note": "No tagged Bible installed."}
    key = f"{f.book}.{f.chapter}.{f.verse or 1}"
    words = study.strongs_in_unit(conn, tagged[0], key) or []
    notes = study.commentaries_at(conn, f.book, f.chapter or 0, f.verse or 1,
                                  limit=60) or []
    bodies = "\n".join(n.get("text", "") for n in notes).lower()
    items = []
    for w in words:
        surfs = [s.lower() for s in w.get("surfaces", []) if s]
        hits = sum(bodies.count(s) for s in surfs) if surfs else 0
        items.append({"number": w["number"], "surfaces": w.get("surfaces", []),
                      "mentions": hits})
    items.sort(key=lambda x: (-x["mentions"], x["number"]))
    return {"ok": True, "ref": ref, "items": items[:limit],
            "commentaries": len(notes),
            "note": "Mentions in installed commentaries at this verse or "
                    "chapter — attention, not importance."}

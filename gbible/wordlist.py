"""Word lists: every occurrence of a term, kept.

A search tells you where a word is now, and is gone by the time you have read
the third result.  A word list is the answer you keep: the occurrences of a
Greek lemma across a book, of a Strong's number across the library, of a
morphology code, or of any query you can write.  It can be reordered, annotated,
printed, exported to a spreadsheet, and turned into a passage list so you can
actually read the verses it found.

The occurrences are not stored.  They are recomputed from the search engine
every time the list is opened, so a list cannot disagree with the library: if a
translation is removed or a word is conjugated differently, the list is right
without being rebuilt.  What *is* stored is the query that fills it and the
user's own ordering and notes on top of the results, because those are
judgements and no engine can reproduce them.
"""

from __future__ import annotations

import csv
import io
import json
import time
import uuid

from . import canon, db, library, morphq, search as searchmod

KINDS = ("term", "strongs", "morph", "lemma")


def _id(prefix: str = "wl") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:11]}"


def _row(r) -> dict:
    def loads(v, default):
        try:
            return json.loads(v) if v else default
        except (json.JSONDecodeError, TypeError):
            return default
    return {"id": r["id"], "name": r["name"], "note": r["note"] or "",
            "query": r["query"] or "", "kind": r["kind"],
            "options": loads(r["options"], {}),
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


# ------------------------------------------------------------------- CRUD

def _pick(data: dict, field: str, old: dict):
    """The new value for a column, or the one already stored.

    `None` means "not mentioned", so a partial update leaves the rest alone.
    """
    v = data.get(field)
    return old.get(field, "") if v is None else v


def save(data: dict) -> dict:
    """Create or update a list.  `id` absent means create."""
    conn = db.connect()
    now = time.time()
    wid = (data.get("id") or "").strip() or _id()
    kind = (data.get("kind") or "term").strip()
    if kind not in KINDS:
        kind = "term"
    row = conn.execute("SELECT * FROM word_list WHERE id=?", (wid,)).fetchone()
    old = _row(row) if row is not None else {}
    # The name may be left out of a partial update -- "just change the note" --
    # in which case the stored one stands.  Demanding it again meant editing a
    # note required retyping the name, and doing it through the API returned
    # "a word list needs a name" for a request that named the list perfectly
    # well by id.
    name = (data.get("name") or old.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "a word list needs a name"}
    if row is None:
        conn.execute(
            "INSERT INTO word_list(id,name,note,query,kind,options,created_at,"
            "updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (wid, name, data.get("note") or "", data.get("query") or "", kind,
             json.dumps(data.get("options") or {}), now, now))
    else:
        # One binding per column, in order.  As with workflows, a stray `name,`
        # sat at the head of this list, so updating an existing word list raised
        # "Incorrect number of bindings supplied" -- a rename, a note, or a
        # changed query all failed.
        options = data.get("options")
        conn.execute(
            "UPDATE word_list SET name=?,note=?,query=?,kind=?,options=?,"
            "updated_at=? WHERE id=?",
            (name, _pick(data, "note", old), _pick(data, "query", old), kind,
             json.dumps(old["options"] if options is None else options),
             now, wid))
    conn.commit()
    # `ok` is part of the shape every other function here returns, and its
    # absence made a successful save indistinguishable from a refusal.
    return {"ok": True, **_row(conn.execute(
        "SELECT * FROM word_list WHERE id=?", (wid,)).fetchone())}


def get(list_id: str) -> dict | None:
    r = db.connect().execute("SELECT * FROM word_list WHERE id=?",
                             (list_id,)).fetchone()
    return _row(r) if r else None


def listing(*, kind: str = "", q: str = "") -> list[dict]:
    conn = db.connect()
    sql = ("SELECT w.*, (SELECT count(*) FROM word_list_item i "
           "WHERE i.list_id=w.id) AS pinned FROM word_list w WHERE 1=1")
    a: list = []
    if kind:
        sql += " AND w.kind=?"
        a.append(kind)
    sql += " ORDER BY COALESCE(w.updated_at, w.created_at) DESC"
    out = []
    for r in conn.execute(sql, a):
        d = _row(r)
        d["pinned"] = r["pinned"]
        out.append(d)
    if q:
        ql = q.lower()
        out = [w for w in out if ql in (w["name"] + " " + w["query"]).lower()]
    return out


def remove(list_id: str) -> dict:
    conn = db.connect()
    conn.execute("DELETE FROM word_list_item WHERE list_id=?", (list_id,))
    cur = conn.execute("DELETE FROM word_list WHERE id=?", (list_id,))
    conn.commit()
    if cur.rowcount:
        try:
            from . import sync
            sync.tombstone(list_id, "word-list")
        except Exception:
            pass
    return {"ok": cur.rowcount > 0}


def rename(list_id: str, name: str) -> dict:
    return save({"id": list_id, "name": name})


# ----------------------------------------------------------------- filling

def occurrences(list_id: str, *, limit: int = 2000, offset: int = 0) -> dict:
    """Re-run the list's query and return what it finds now."""
    w = get(list_id)
    if not w:
        return {"ok": False, "error": "no such word list"}
    opts = dict(w["options"] or {})
    limit = int(opts.get("limit") or limit)
    try:
        if w["kind"] == "strongs":
            res = _from_strongs(w["query"], limit=limit, offset=offset,
                                module_id=opts.get("module_id", ""))
        elif w["kind"] in ("morph", "lemma"):
            res = _from_morph(w["query"], kind=w["kind"], limit=limit,
                              offset=offset, module_id=opts.get("module_id", ""))
        else:
            res = _from_query(w["query"], opts, limit=limit, offset=offset)
    except searchmod.QueryError as e:
        return {"ok": False, "error": str(e)}
    if not res.get("ok"):
        return res
    res["list"] = w
    res["pinned"] = pinned_items(list_id)
    res["note"] = res.get("note", "")
    return res


def _from_query(query: str, opts: dict, *, limit: int, offset: int) -> dict:
    so = searchmod.SearchOpts(
        modules=[opts["module_id"]] if opts.get("module_id") else [],
        limit=limit, offset=offset,
        match_case=bool(opts.get("match_case")),
        match_all_forms=bool(opts.get("match_forms")),
        search_headings=bool(opts.get("search_headings", False)),
        sort=opts.get("sort") or "passage")
    r = searchmod.search(query, so)
    if not r.get("ok"):
        return r
    items = []
    for h in r.get("hits", []):
        items.append({
            "term": h.get("matched") and h["matched"][0] or "",
            "surface": (h.get("text") or "").strip()[:180],
            "module_id": h["module_id"], "unit_key": h["key"],
            "ref_label": h.get("label") or "", "book": _book(h),
            "chapter": _int(h.get("chapter")), "verse": _int(h.get("verse")),
            "snippet": h.get("snippet", ""),
        })
    return {"ok": True, "source": "search", "total": r.get("total", 0),
            "items": items, "groups": r.get("groups", {}),
            "group_meta": r.get("group_meta", {}),
            "query": query, "ms": r.get("ms", 0),
            "note": f"Found by searching for {query!r}. The list holds the "
                    f"query, not the results, so this is always current."}


def _from_strongs(num: str, *, limit: int, offset: int,
                  module_id: str = "") -> dict:
    """Every place a Strong's number is marked."""
    n = canon.normalise_strongs(num)
    if not n:
        return {"ok": False, "error": "no Strong's number"}
    conn = db.connect()
    sql = ("SELECT m.module_id, m.unit_key, m.pos, m.surface, u.ref_label, "
           "u.book, u.chapter, u.verse, u.text, mo.name FROM marker m "
           "JOIN unit u ON u.module_id=m.module_id AND u.key=m.unit_key "
           "JOIN module mo ON mo.id=m.module_id "
           "WHERE m.kind='strongs' AND m.value=?")
    a: list = [n]
    if module_id:
        sql += " AND m.module_id=?"
        a.append(module_id)
    sql += " ORDER BY mo.priority DESC, u.book, u.chapter, u.verse, m.pos LIMIT ? OFFSET ?"
    a += [limit, offset]
    rows = conn.execute(sql, a).fetchall()
    total = conn.execute("SELECT count(*) c FROM marker WHERE kind='strongs' "
                         "AND value=?", (n,)).fetchone()["c"]
    row = conn.execute("SELECT word, lemma FROM strongs WHERE strongs=?",
                       (n,)).fetchone()
    items = [{"term": n, "surface": r["surface"] or "",
              "module_id": r["module_id"], "unit_key": r["unit_key"],
              "ref_label": r["ref_label"] or "",
              "book": r["book"] or "", "chapter": r["chapter"] or 0,
              "verse": r["verse"] or 0,
              "snippet": (r["text"] or "")[:180]} for r in rows]
    out = {"ok": True, "source": "strongs", "number": n, "total": total,
           "items": items,
           "word": (row["word"] if row else "") or "",
           "lemma": (row["lemma"] if row else "") or ""}
    if total and not items:
        out["note"] = (f"{n} is not marked in any Bible you have open. "
                       f"Strong's numbers come from the module's own text, so "
                       f"a translation without them cannot report occurrences.")
    return out


def _from_morph(code: str, *, kind: str, limit: int, offset: int,
                module_id: str = "") -> dict:
    conn = db.connect()
    column = "morph"
    if kind == "lemma":
        column = "lemma"
    sql = ("SELECT m.module_id, m.unit_key, m.pos, m.surface, m.value, "
           "u.ref_label, u.book, u.chapter, u.verse, u.text FROM marker m "
           "JOIN unit u ON u.module_id=m.module_id AND u.key=m.unit_key "
           "WHERE m.kind=? AND m.value=?")
    a: list = [column, code]
    if module_id:
        sql += " AND m.module_id=?"
        a.append(module_id)
    sql += " ORDER BY u.book, u.chapter, u.verse, m.pos LIMIT ? OFFSET ?"
    a += [limit, offset]
    rows = conn.execute(sql, a).fetchall()
    total = conn.execute("SELECT count(*) c FROM marker WHERE kind=? AND "
                         "value=?", (column, code)).fetchone()["c"]
    items = [{"term": code, "surface": r["surface"] or "",
              "module_id": r["module_id"], "unit_key": r["unit_key"],
              "ref_label": r["ref_label"] or "",
              "book": r["book"] or "", "chapter": r["chapter"] or 0,
              "verse": r["verse"] or 0,
              "snippet": (r["text"] or "")[:180]} for r in rows]
    out = {"ok": True, "source": kind, "code": code, "total": total,
           "items": items}
    if kind == "morph":
        f = morphq.parse_code(code)
        out["features"] = {k: v for k, v in f.items() if v not in (None, "", [])}
        out["gloss"] = f.get("pos_label") or ""
    if total and not items:
        out["note"] = (f"{code} is not marked in any module you have. "
                       f"Morphology comes from the text itself, so it exists "
                       f"only where a tagged original-language Bible is "
                       f"installed.")
    return out


# ------------------------------------------------------- pinned items

def pinned_items(list_id: str) -> list[dict]:
    """The occurrences the user kept by hand, in their order."""
    return [{"id": r["id"], "term": r["term"], "surface": r["surface"] or "",
             "module_id": r["module_id"] or "", "unit_key": r["unit_key"] or "",
             "ref_label": r["ref_label"] or "", "book": r["book"] or "",
             "chapter": r["chapter"] or 0, "verse": r["verse"] or 0,
             "gloss": r["gloss"] or "", "note": r["note"] or ""}
            for r in db.connect().execute(
                "SELECT * FROM word_list_item WHERE list_id=? "
                "ORDER BY pos, added_at", (list_id,))]


def pin(list_id: str, item: dict) -> dict:
    """Keep one occurrence, so it stays whatever the search finds later."""
    conn = db.connect()
    if get(list_id) is None:
        # Without this check the row was written with a list_id that names
        # nothing, and the item sat in the table for ever: no list to show it
        # in, no way to delete it, and `remove()` never looks at a list_id that
        # is not there.  It happened from a click that arrived after the list
        # had been deleted in another tab.
        return {"ok": False, "error": "no such word list"}
    nxt = conn.execute("SELECT COALESCE(MAX(pos), -1) + 1 p FROM "
                       "word_list_item WHERE list_id=?", (list_id,)).fetchone()["p"]
    iid = _id("wi")
    conn.execute(
        "INSERT INTO word_list_item(id,list_id,term,surface,module_id,"
        "unit_key,ref_label,book,chapter,verse,pos,gloss,note,added_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (iid, list_id, item.get("term") or "", item.get("surface") or "",
         item.get("module_id") or "", item.get("unit_key") or "",
         item.get("ref_label") or "", item.get("book") or "",
         _int(item.get("chapter")), _int(item.get("verse")), nxt,
         item.get("gloss") or "", item.get("note") or "", time.time()))
    conn.commit()
    return {"ok": True, "id": iid}


def unpin(item_id: str) -> dict:
    cur = db.connect().execute("DELETE FROM word_list_item WHERE id=?",
                               (item_id,))
    db.connect().commit()
    return {"ok": cur.rowcount > 0}


def annotate(item_id: str, note: str = "", gloss: str = "") -> dict:
    conn = db.connect()
    row = conn.execute("SELECT * FROM word_list_item WHERE id=?",
                       (item_id,)).fetchone()
    if row is None:
        return {"ok": False, "error": "no such item"}
    conn.execute("UPDATE word_list_item SET note=?, gloss=? WHERE id=?",
                 (note if note != "" else (row["note"] or ""),
                  gloss if gloss != "" else (row["gloss"] or ""), item_id))
    conn.commit()
    return {"ok": True}


def move(item_id: str, delta: int) -> dict:
    """Move a kept item up or down, then renumber densely."""
    conn = db.connect()
    row = conn.execute("SELECT * FROM word_list_item WHERE id=?",
                       (item_id,)).fetchone()
    if row is None:
        return {"ok": False, "error": "no such item"}
    rows = conn.execute("SELECT id FROM word_list_item WHERE list_id=? "
                        "ORDER BY pos, added_at", (row["list_id"],)).fetchall()
    ids = [r["id"] for r in rows]
    i = ids.index(item_id)
    j = max(0, min(len(ids) - 1, i + (1 if delta > 0 else -1)))
    ids[i], ids[j] = ids[j], ids[i]
    for n, iid in enumerate(ids):
        conn.execute("UPDATE word_list_item SET pos=? WHERE id=?", (n, iid))
    conn.commit()
    return {"ok": True}


# ----------------------------------------------------------------- makers

def from_search(query: str, *, name: str = "", options: dict | None = None,
                kind: str = "term") -> dict:
    """Keep a search as a list.  The name defaults to the query, which is
    usually the most descriptive thing available."""
    w = save({"name": name or f"Word list: {query}",
              "query": query, "kind": kind, "options": options or {}})
    return {"ok": True, "list": w}


def from_results(hits: list[dict], *, name: str, note: str = "",
                 kind: str = "term") -> dict:
    """Keep the results already on screen as a list of kept items.

    Used by "save this search as a word list" when the query has more hits than
    the engine will re-run, so what is kept is exactly what was looked at.
    """
    w = save({"name": name, "note": note, "kind": kind,
              "query": "", "options": {"kept": len(hits)}})
    conn = db.connect()
    now = time.time()
    for i, h in enumerate(hits):
        conn.execute(
            "INSERT INTO word_list_item(id,list_id,term,surface,module_id,"
            "unit_key,ref_label,book,chapter,verse,pos,note,added_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_id("wi"), w["id"], h.get("term") or "",
             (h.get("text") or "")[:200], h.get("module_id") or "",
             h.get("key") or "", h.get("label") or "", _book(h),
             _int(h.get("chapter")), _int(h.get("verse")), i, "", now))
    conn.commit()
    return {"ok": True, "list": w}


def to_passage_list(list_id: str, *, name: str = "", module_id: str = "") -> dict:
    """Turn a word list into a passage list, so the verses can be read."""
    from . import organise
    res = occurrences(list_id, limit=1000)
    if not res.get("ok"):
        return res
    items = res.get("items") or []
    kept = [i for i in (res.get("pinned") or []) if i.get("unit_key")]
    rows = kept or items
    if not rows:
        return {"ok": False, "error": "nothing to make a list from"}
    mod = module_id or next((i["module_id"] for i in rows if i.get("module_id")), "")
    pl = organise.save_passage_list(name or f"From {res['list']['name']}")
    n = 0
    for i in rows:
        mid = i.get("module_id") or mod
        key = i.get("unit_key") or ""
        if not key:
            continue
        if mid and mod and mid != mod:
            continue            # one version only, or the keys mean nothing
        try:
            organise.add_passage(pl["id"], key, i.get("ref_label") or "", mid)
            n += 1
        except Exception:
            continue
    return {"ok": n > 0, "list": pl, "added": n,
            "error": None if n else "none of the items carry a unit key"}


# ------------------------------------------------------------------ export

def export(list_id: str, fmt: str = "csv") -> dict:
    """The list as a file the user can keep."""
    res = occurrences(list_id, limit=5000)
    if not res.get("ok"):
        return res
    w = res["list"]
    # One lookup per module, not two per row: a 5,000-occurrence export was
    # doing 10,000 module reads to fill in a column that repeats.
    names: dict[str, str] = {}

    def _name(mid: str) -> str:
        if mid not in names:
            m = library.get(mid) if mid else None
            names[mid] = (m.name if m else mid) or ""
        return names[mid]

    rows = [{"term": i.get("term") or "", "surface": i.get("surface") or "",
             "reference": i.get("ref_label") or "",
             "book": i.get("book") or "", "chapter": i.get("chapter") or 0,
             "verse": i.get("verse") or 0,
             "module": _name(i.get("module_id") or ""),
             "text": i.get("snippet") or ""}
            for i in (res.get("items") or [])]
    pinned = [{"term": i["term"], "surface": i["surface"],
               "reference": i["ref_label"], "book": i["book"],
               "chapter": i["chapter"], "verse": i["verse"],
               "module": i["module_id"], "text": "",
               "note": i.get("note") or ""}
              for i in (res.get("pinned") or [])]
    if fmt == "csv":
        buf = io.StringIO()
        wtr = csv.writer(buf)
        wtr.writerow(["term", "surface", "reference", "book", "chapter",
                      "verse", "module", "text", "note"])
        for r in pinned + rows:
            wtr.writerow([r["term"], r["surface"], r["reference"], r["book"],
                          r["chapter"], r["verse"], r["module"], r["text"],
                          r.get("note", "")])
        return {"ok": True, "format": "csv", "count": len(pinned) + len(rows),
                "text": buf.getvalue()}
    if fmt in ("txt", "md"):
        out = [f"# {w['name']}", ""]
        if w["query"]:
            out += [f"Query: `{w['query']}`", ""]
        if w["note"]:
            out += [w["note"], ""]
        out += [f"{len(rows)} occurrence(s)"
                + (f", {len(pinned)} kept by hand" if pinned else ""), ""]
        for r in pinned + rows:
            out.append(f"- {r['reference'] or '—'}  **{r['term'] or ''}**  "
                       f"{r['text'][:160]}")
        return {"ok": True, "format": fmt, "count": len(pinned) + len(rows),
                "text": "\n".join(out)}
    return {"ok": False, "error": f"unknown format {fmt!r}",
            "formats": ["csv", "txt", "md"]}


def stats() -> dict:
    conn = db.connect()
    return {
        "lists": conn.execute("SELECT count(*) c FROM word_list").fetchone()["c"],
        "kept": conn.execute(
            "SELECT count(*) c FROM word_list_item").fetchone()["c"],
        "by_kind": {r["kind"]: r["c"] for r in conn.execute(
            "SELECT kind, count(*) c FROM word_list GROUP BY kind")},
    }


def _book(h: dict) -> str:
    b = h.get("book")
    if b:
        return str(b)
    label = h.get("label") or ""
    try:
        rr = canon.parse_ref(label)
        return rr.book if rr else ""
    except Exception:
        return ""


def _int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0
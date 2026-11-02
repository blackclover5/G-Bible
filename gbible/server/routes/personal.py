from .common import *

# ---------------------------------------------------------------- highlights
def _verse_of(module_id: str, unit_key: str):
    """The canonical place of a unit, if it is a verse.

    The unit key belongs to its module -- the same verse is "John.3.16" in one
    Bible and "John 3:16" in another -- so the place is read from the unit
    table rather than parsed out of the key.  This is what lets a highlight
    follow its verse to a different translation.
    """
    if not module_id or not unit_key:
        return (None, None, None)
    r = db.connect().execute(
        "SELECT book, chapter, verse FROM unit WHERE module_id=? AND key=?",
        (module_id, unit_key)).fetchone()
    if r is None or not r["book"] or not r["chapter"] or not r["verse"]:
        return (None, None, None)
    return (r["book"], r["chapter"], r["verse"])


@endpoint("highlights")
def _highlights(parts, q):
    conn = db.connect()
    if q.get("action") == "add":
        import uuid
        book, chapter, verse = _verse_of(q.get("id", ""), q.get("key", ""))
        conn.execute("INSERT OR REPLACE INTO highlight(id,module_id,unit_key,"
                     "quote,color,note,label,created_at,book,chapter,verse) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (str(uuid.uuid4())[:12], q.get("id", ""), q.get("key", ""),
                      q.get("quote", ""), q.get("color", "yellow"),
                      q.get("note", ""), q.get("label", ""), time.time(),
                      book, chapter, verse))
        conn.commit()
        return _ok(ok=True)
    if q.get("action") == "delete":
        hid = q.get("hid", "")
        cur = conn.execute("DELETE FROM highlight WHERE id=?", (hid,))
        conn.commit()
        if cur.rowcount:
            try:
                from ... import sync as _sync
                _sync.tombstone(hid, "highlight")
            except Exception:
                pass
        return _ok(ok=True)
    sql = "SELECT * FROM highlight"
    params = []
    if q.get("label"):
        sql += " WHERE label=?"
        params.append(q.get("label"))
    sql += " ORDER BY created_at DESC LIMIT 500"
    rows = [dict(r) for r in conn.execute(sql, params)]
    return _ok(highlights=rows, labels=[r[0] for r in conn.execute(
        "SELECT DISTINCT label FROM highlight WHERE label<>'' ORDER BY label")])


@endpoint("tags")
def _tags(parts, q):
    """The reader's tags, and what is in them.

    A tag is a named category, and a thing can be in more than one: a passage
    can be "grace", "Romans" and "sermon series" at the same time.  That is
    the difference from a label, which can only be one thing.

    A verse is stored by its canonical place, not by the key of the module it
    was tagged in, so a tag follows the passage from one translation to the
    next -- which is the point of tagging it rather than highlighting it.
    """
    conn = db.connect()
    action = (q.get("action") or "").strip()
    try:
        if action == "create":
            name = (q.get("name") or "").strip()
            if not name:
                return {"ok": False, "error": "A tag needs a name."}
            tid = uuid.uuid4().hex[:12]
            conn.execute("INSERT INTO tag(id,name,color,created_at) "
                         "VALUES(?,?,?,?)",
                         (tid, name, q.get("color", "") or "", time.time()))
            conn.commit()
            return _ok(ok=True, tag={"id": tid, "name": name,
                                      "color": q.get("color", "") or "",
                                      "count": 0})
        if action == "rename":
            name = (q.get("name") or "").strip()
            if not name:
                return {"ok": False, "error": "A tag needs a name."}
            conn.execute("UPDATE tag SET name=? WHERE id=?", (name, q.get("id")))
            conn.commit()
            return _ok(ok=True)
        if action == "delete":
            tid = q.get("id", "")
            conn.execute("DELETE FROM tag_item WHERE tag_id=?", (tid,))
            conn.execute("DELETE FROM tag WHERE id=?", (tid,))
            conn.commit()
            try:
                from ... import sync
                sync.tombstone(tid, "tag")
            except Exception:
                pass
            return _ok(ok=True)
        if action == "add":
            tid = q.get("tag_id", "")
            if not conn.execute("SELECT 1 FROM tag WHERE id=?",
                                (tid,)).fetchone():
                return {"ok": False, "error": "No such tag."}
            book, chapter, verse = _verse_of(q.get("module_id", ""),
                                             q.get("unit_key", ""))
            kind = "verse" if book else "unit"
            have = conn.execute(
                "SELECT id FROM tag_item WHERE tag_id=? AND module_id=? "
                "AND unit_key=? AND ifnull(book,'')=? AND ifnull(chapter,0)=? "
                "AND ifnull(verse,0)=?",
                (tid, q.get("module_id", ""), q.get("unit_key", ""),
                 book or "", chapter or 0, verse or 0)).fetchone()
            if have:
                return _ok(ok=True, id=have["id"])
            iid = uuid.uuid4().hex[:12]
            conn.execute(
                "INSERT INTO tag_item(id,tag_id,kind,module_id,unit_key,book,"
                "chapter,verse,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (iid, tid, kind, q.get("module_id", ""), q.get("unit_key", ""),
                 book, chapter, verse, time.time()))
            conn.commit()
            return _ok(ok=True, id=iid)
        if action == "remove":
            conn.execute("DELETE FROM tag_item WHERE id=?", (q.get("id", ""),))
            conn.commit()
            return _ok(ok=True)

        tags = [{"id": r["id"], "name": r["name"], "color": r["color"] or ""}
                for r in conn.execute(
                    "SELECT id,name,color FROM tag ORDER BY name COLLATE NOCASE")]
        counts = {r["tag_id"]: r["n"] for r in conn.execute(
            "SELECT tag_id, count(*) n FROM tag_item GROUP BY tag_id")}
        for t in tags:
            t["count"] = counts.get(t["id"], 0)
        items = [dict(r) for r in conn.execute(
            "SELECT id,tag_id,kind,module_id,unit_key,book,chapter,verse "
            "FROM tag_item ORDER BY created_at DESC")]
        out = {"tags": tags, "items": items}
        # When the reader asks about one particular verse, the tags it is
        # already in come back with it.  The client cannot work this out for
        # itself: the unit key belongs to the module, and the verse it names
        # is spelled differently in every other translation.
        if q.get("module_id") and q.get("unit_key"):
            b, c, v = _verse_of(q.get("module_id"), q.get("unit_key"))
            if b:
                out["verse"] = {
                    "osis": f"{b}.{c}.{v}",
                    "items": [i for i in items
                              if i.get("book") == b and i.get("chapter") == c
                              and i.get("verse") == v]}
        return _ok(**out)
    except Exception as e:                              # noqa: BLE001
        return _ai_error(e)


# ----------------------------------------------------------------------- srs
@endpoint("srs/add")
def _srs_add(parts, q):
    from ... import srs as _srs
    return _ok(**_srs.add(q.get("ref", ""), module_id=q.get("id", ""),
                           unit_key=q.get("key", "")))


@endpoint("srs/remove")
def _srs_remove(parts, q):
    from ... import srs as _srs
    return _ok(**_srs.remove(q.get("id", "")))


@endpoint("srs/due")
def _srs_due(parts, q):
    from ... import srs as _srs
    cards = _srs.due(int(q.get("limit") or 50))
    # attach verse text when we can
    conn = db.connect()
    for c in cards:
        if c.get("module_id") and c.get("unit_key"):
            r = conn.execute("SELECT text FROM unit WHERE module_id=? AND key=?",
                             (c["module_id"], c["unit_key"])).fetchone()
            if r:
                c["text"] = r["text"] or ""
    return _ok(cards=cards, stats=_srs.stats())


@endpoint("srs/all")
def _srs_all(parts, q):
    from ... import srs as _srs
    return _ok(cards=_srs.all_cards(), stats=_srs.stats())


@endpoint("app/reset")
def _app_reset(parts, q):
    """Wipe the local database and installed modules, mirroring reset-gbible.

    The server exits after responding so the files can be removed safely; the
    user restarts G-Bible afterwards.
    """
    if q.get("confirm") != "RESET":
        return {"ok": False, "error": "confirmation required"}
    import os
    import shutil
    import sys
    import threading
    import time
    from pathlib import Path

    from ... import db as _db

    db_path = _db.db_path()
    app_dir = _db.app_dir()
    modules_dir = _db.modules_dir()

    def worker():
        time.sleep(0.7)
        for name in (db_path.name, db_path.name + "-wal", db_path.name + "-shm"):
            try:
                (app_dir / name).unlink()
            except FileNotFoundError:
                pass
        try:
            if modules_dir.exists():
                shutil.rmtree(modules_dir, ignore_errors=True)
            modules_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print("reset: could not clear modules:", e, file=sys.stderr)
        print("G-Bible reset complete. Restart the app.", flush=True)
        os._exit(0)

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "message": "Resetting. Please restart G-Bible."}
@endpoint("srs/review")
def _srs_review(parts, q):
    from ... import srs as _srs
    grade = _srs.grade_for(q.get("grade", "good"))
    if q.get("grade") and str(q.get("grade")).isdigit():
        grade = int(q.get("grade"))
    return _ok(**_srs.review(q.get("id", ""), grade))


# -------------------------------------------------------------------- sync



# -------------------------------------------------------------------- misc
@endpoint("reference")
def _reference(parts, q):
    text = q.get("ref", "")
    rr = canon.parse_ref(text)
    if rr is None:
        return {"ok": False, "error": "not a scripture reference",
                "tried": text}
    return _ok(ref=canon.format_ref(rr.start), key=rr.start.osis_id(),
               end=canon.format_ref(rr.end) if rr.end != rr.start else "",
               book=rr.start.book, chapter=rr.start.chapter,
               verse=rr.start.verse,
               next=canon.format_ref(canon.next_ref(rr.start)),
               prev=canon.format_ref(canon.prev_ref(rr.start)))


@endpoint("auto-refs")
def _auto_refs(parts, q):
    text = q.get("text", "")
    out = []
    for rr in canon.find_all_refs(text):
        out.append({"label": rr.label(), "key": rr.start.osis_id()})
    return _ok(refs=out[:200])


@endpoint("suggest")
def _suggest(parts, q):
    """Autocomplete for the reference box."""
    text = (q.get("q") or "").strip()
    out = []
    if not text:
        return _ok(suggestions=[])
    m = re.match(r"^([A-Za-z0-9 ]*?)\s*(\d.*)?$", text)
    bookpart = (m.group(1) or "").strip() if m else text
    if bookpart:
        for b in canon.BOOKS_KJA:
            keys = [b.name, b.short, b.osis, *b.abbrevs]
            for k in keys:
                if k and k.lower().startswith(bookpart.lower()):
                    out.append({"kind": "book", "label": b.name,
                                "insert": b.short})
                    break
    return _ok(suggestions=out[:20])


@endpoint("reindex")
def _reindex(parts, q):
    from ... import indexer
    mid = q.get("id", "")
    m = library.get(mid)
    if not m:
        return {"ok": False, "error": "not installed"}
    # Resolved rather than read off the row: `path` records where the module was
    # installed, which stops being true the moment the project folder moves. A
    # re-index that reported "the files are gone" while they sat in the new
    # library directory was the visible symptom of that.
    src = library.module_dir(mid)
    if src is None:
        return {"ok": False,
                "error": "the files are not where this library says they are; "
                         "re-import from the Store"}
    from ... import formats
    files = [p for p in src.rglob("*") if p.is_file()]
    units = []
    for p in files:
        try:
            if p.suffix.lower() in (".zip", ".usfm", ".txt"):
                units.extend(formats.load_text(p) if p.suffix == ".txt"
                             else formats.load_usfm_zip(p.read_bytes()))
        except Exception:
            continue
    if not units:
        return {"ok": False, "error": "nothing to re-index"}
    # Re-indexing *replaces* the module's units, so a parse that disagrees with
    # what is installed is not a repair -- it is a different module. And it
    # routinely is a different module: the installer split the file by chapters
    # or sections, and the files left behind are re-split here by the crude
    # splitter in formats.load_text. Measured on this library: a 4-unit book
    # reparsed to 21, an 8-unit commentary to 171, a 49-unit one to 1,052.
    #
    # So a yield that does not closely match what is installed is refused and
    # nothing is written. This is the rule the zLD dictionary import already
    # follows -- "a partial decode used to install them as four- or five-entry
    # stubs, which is worse than refusing, so the reader still requires a
    # plausible yield before trusting a parse". A maintenance action that can
    # quietly restructure a book is worse than one that declines.
    had = db.connect().execute(
        "SELECT COUNT(*) c FROM unit WHERE module_id=?", (mid,)).fetchone()["c"]
    if had and not (0.9 <= len(units) / had <= 1.1):
        return {"ok": False,
                "error": f"refusing to re-index: the files here re-parse to "
                         f"{len(units)} units against the {had} installed, so "
                         f"this is not the same import. Nothing was changed. "
                         f"Re-import it from the Store instead.",
                "parsed": len(units), "installed": had, "refused": True}
    st = indexer.run_import(mid, iter(units), name=m.name, abbrev=m.abbrev,
                            type=m.type, subject=m.subject, lang=m.lang,
                            source=m.source, license=m.license, v11n=m.v11n,
                            folder=m.folder, path=str(src))
    return _ok(**st)




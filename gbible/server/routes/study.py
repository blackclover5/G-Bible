from .common import *

# ------------------------------------------------------------------ NT/OT use
@endpoint("ntuseot/modules")
def _ntuseot_modules(parts, q):
    return {"ok": True, **ntuseot.capable_modules()}


def _both_ends(nt: str, ot: str) -> dict | None:
    """Refuse a pair where one side has no Old Testament, and say why."""
    if nt and ot:
        cap = ntuseot.capable_modules()
        known = {m["id"]: m for m in cap["modules"]}
        a, b = known.get(nt), known.get(ot)
        for mod, role in ((a, "the New Testament side"),
                          (b, "the Old Testament side")):
            if mod is None or mod["both"]:
                continue
            # Name the testament that is actually absent, not the one the
            # picker was standing in.  Saying the Basque New Testament "has no
            # New Testament text" is nonsense -- it is missing the other half.
            missing = ("Old Testament" if mod["nt_verses"] else "New Testament")
            usable = [m["name"] for m in cap["both"]][:6]
            return {"ok": False,
                    "error": f"{mod['name']} has no {missing} text, so it cannot "
                    f"be used as {role}. Choose one with both, such as: "
                    + ", ".join(usable)}
    return None


@endpoint("ntuseot/list")
def _ntuseot_list(parts, q):
    """The standard list, each entry re-checked against the installed text."""
    nt = q.get("nt", "")
    ot = q.get("ot", "")
    if not nt or not ot:
        cap = ntuseot.capable_modules()
        if cap["both"]:
            d = cap["both"][0]
            return ntuseot.classify(d["id"], d["id"],
                                    size=int(q.get("size") or ntuseot.WINDOW))
        return {"ok": False, "error": "install a Bible with both testaments first"}
    bad = _both_ends(nt, ot)
    if bad:
        return bad
    return ntuseot.classify(nt, ot, size=int(q.get("size") or ntuseot.WINDOW))


@endpoint("ntuseot/find")
def _ntuseot_find(parts, q):
    """Unlisted matches: verses sharing wording the standard list does not have."""
    nt = q.get("nt", "")
    ot = q.get("ot", "")
    if not nt or not ot:
        return {"ok": False, "error": "choose a New Testament and an Old Testament resource"}
    return ntuseot.find(nt, ot, min_hits=int(q.get("min_hits") or 2),
                        limit=int(q.get("limit") or 300))


@endpoint("ntuseot/verse")
def _ntuseot_verse(parts, q):
    return ntuseot.for_verse(q.get("nt", ""), q.get("ref", ""), q.get("ot", ""))


# ---------------------------------------------------------------- concordance
@endpoint("concordance")
def _concordance(parts, q):
    """Every word in a chapter, or every use of one word in it."""
    return concordance.build(q.get("id", ""), q.get("ref", ""),
                             word=q.get("word", ""),
                             tagged_only=q.get("tagged_only") in (True, "1", "true"))


# --------------------------------------------------------------------- merge
@endpoint("study/merge")
def _study_merge(parts, q):
    """Merge a passage across translations, marking where they disagree."""
    return merge.merge(q.get("ref", ""), _id_list(q.get("modules")),
                       spine=int(q.get("spine") or 0))


@endpoint("study/crossrefs")
def _study_crossrefs(parts, q):
    """Cross-references for a reference, both directions, as a panel."""
    return study.crossref_panel(q.get("ref", ""),
                                module_ids=_id_list(q.get("modules")) or None)


@endpoint("audio/cues")
def _audio_cues(parts, q):
    """Verse timings for a recording, so the text can follow it."""
    mid = q.get("id", "")
    if not mid:
        return {"ok": False, "error": "which recording?"}
    return audio.cues_for(mid, q.get("ref", ""))


@endpoint("compare/diff")
def _compare_diff(parts, q):
    """The same verse, with the differing runs marked in every column.

    Same alignment the merge view uses, reported per version.  See `merge.diff`
    for why this is not a second algorithm.
    """
    return merge.diff(q.get("ref", ""), _id_list(q.get("modules")))


def _id_list(v) -> list:
    """Module ids from a query value that may be a list, a JSON list, or a string.

    The front end's api() helper JSON-stringifies an array into the query
    string, so "modules" arrives as '["a","b"]' -- not as words.  Splitting on
    whitespace gave back '["a"' and '"b"]', which match no module, and the
    merge reported that you had not installed two translations.
    """
    if v is None or v == "":
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if str(x)]
    s = str(v).strip()
    if s.startswith("["):
        try:
            out = json.loads(s)
            if isinstance(out, list):
                return [str(x) for x in out if str(x)]
        except (json.JSONDecodeError, TypeError):
            pass
    return [x for x in s.replace(",", " ").split() if x]


# --------------------------------------------------------------------- audio
@endpoint("audio/register")
def _audio_register(parts, q):
    """Register a folder of audio you already have.  Nothing is downloaded."""
    return _ok(**audio.register(q.get("folder", ""), q.get("name", ""),
                                q.get("license", ""), q.get("author", "")))


@endpoint("audio/remove")
def _audio_remove(parts, q):
    return _ok(**audio.remove(q.get("id", "")))


@endpoint("library/integrity")
def _library_integrity(parts, q):
    """Which installed Bibles are missing the end of their chapters.

    A truncated Bible is silent about it: the pane stops at the last verse that
    is there and looks complete.  The Library asks for this so it can warn.
    """
    if q.get("id"):
        return {"ok": True, **concordance.completeness(q["id"])}
    conn = db.connect()
    truncated, abridged = [], []
    for r in conn.execute("SELECT id FROM module WHERE type='Bible' "
                          "AND installed_at>0"):
        c = concordance.completeness(r["id"])
        if not c.get("ok"):
            continue
        if c["truncated"]:
            truncated.append(c)
        elif c["abridged"] and c["warning"]:
            abridged.append(c)
    return {"ok": True, "truncated": truncated, "abridged": abridged}


@endpoint("audio/scan")
def _audio_scan(parts, q):
    folder = q.get("folder", "")
    if not folder:
        return _ok(files=[])
    try:
        return _ok(files=audio.scan(folder))
    except OSError as exc:
        return _ok(files=[], error=str(exc))


@endpoint("audio/serve")
def _audio_serve(parts, q):
    """Stream one registered file.

    The path is taken from the *stored* unit, never from the request, so this
    cannot be used to read arbitrary files: a caller can only reach what was
    registered for that module.
    """
    import os as _os
    mid = q.get("id", "")
    key = q.get("key", "")
    conn = db.connect()
    row = conn.execute("SELECT extra FROM unit WHERE module_id=? AND key=?",
                       (mid, key)).fetchone()
    if row is None:
        return _ok(error="no such recording")
    try:
        ex = json.loads(row["extra"] or "{}")
    except (json.JSONDecodeError, TypeError):
        ex = {}
    path = ex.get("file", "")
    if not path or not _os.path.isfile(path):
        return _ok(error="the audio file is not where it was registered")
    # The handler serves this one directly: a recorded file is binary, and the
    # dispatcher JSON-encodes everything else.
    return {"ok": True, "file": path,
            "mime": mimetypes.guess_type(path)[0] or "audio/mpeg"}


# ----------------------------------------------------------------------- tts
@endpoint("tts/status")
def _tts_status(parts, q):
    """Is there a voice to read with, and which ones?

    Asked before anything is offered, not after: on a machine where the model is
    not installed the front end has to fall back to the browser's own speech
    engine instead of playing a button that quietly does nothing.
    """
    return _ok(**tts.status())


@endpoint("tts/install")
def _tts_install(parts, q):
    """Install the read-aloud voice (Kitten TTS) into .venv.

    Runs tools/install_voice.py in the background; the front end polls
    store/job for progress.  Only meaningful when tts/status reports the
    voice as unavailable.
    """
    import threading
    import subprocess
    import sys
    import uuid
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    script = root / "tools" / "install_voice.py"
    jid = "job_" + uuid.uuid4().hex[:16]
    _remember_job(jid, {"state": "running", "message": "starting",
                        "done": 0, "total": 1, "failures": []})

    def work():
        state = "done"
        msg = "Voice installed."
        try:
            proc = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(root), capture_output=True, text=True,
                timeout=1800)
            if proc.returncode != 0:
                state = "error"
                tail = (proc.stderr or proc.stdout or "").strip()
                msg = (tail[-500:] if tail else "install failed")
        except Exception as exc:  # noqa: BLE001
            state = "error"
            msg = f"{type(exc).__name__}: {exc}"
        with _job_lock:
            if jid in _jobs:
                _jobs[jid].update(state=state, message=msg, done=1)

    threading.Thread(target=work, daemon=True).start()
    return _ok(job=jid)


# ------------------------------------------- collections, lists, favourites
@endpoint("favorites")
def _favorites(parts, q):
    if q.get("action") == "set":
        return _ok(**organise.set_favourite(q.get("id", ""),
                                            q.get("value", "1") not in ("0", "false")))
    return _ok(favorites=organise.favourites())


@endpoint("collection")
def _collection(parts, q):
    if q.get("action") == "delete":
        return _ok(**organise.delete_collection(q.get("id", "")))
    if q.get("action") == "add":
        return _ok(**organise.add_to_collection(q.get("id", ""), q.get("module", "")))
    if q.get("action") == "save":
        mods = q.get("modules") or []
        if isinstance(mods, str):
            mods = [m for m in mods.split(",") if m]
        return _ok(**organise.save_collection(
            q.get("name", ""), q.get("note", ""), mods, q.get("id", "")))
    if q.get("action") == "rule":
        import json as _j
        plus = q.get("plus", [])
        minus = q.get("minus", [])
        if isinstance(plus, str):
            try:
                plus = _j.loads(plus)
            except Exception:  # noqa: BLE001
                plus = [m for m in plus.split(",") if m]
        if isinstance(minus, str):
            try:
                minus = _j.loads(minus)
            except Exception:  # noqa: BLE001
                minus = [m for m in minus.split(",") if m]
        return _ok(**organise.set_collection_rule(
            q.get("id", ""), q.get("rule", ""), plus, minus))
    if q.get("id"):
        return _ok(id=q["id"], rule=organise.collection_rule(q["id"]),
                   members=organise.collection_members(q["id"]))
    return _ok(collections=organise.collections())


@endpoint("library/query")
def _library_query(parts, q):
    return _ok(results=organise.library_query(q.get("q", "")))


@endpoint("library/tags")
def _library_tags(parts, q):
    if q.get("action") == "set":
        import json as _j
        tags = q.get("tags", [])
        if isinstance(tags, str):
            try:
                tags = _j.loads(tags)
            except Exception:  # noqa: BLE001
                tags = [t for t in tags.split(",") if t]
        return _ok(**organise.set_module_tags(q.get("id", ""), tags))
    return _ok(tags=organise.module_tags())


@endpoint("library/availability")
def _availability(parts, q):
    return _ok(availability=organise.availability())


@endpoint("library/print")
def _library_print(parts, q):
    act = q.get("action")
    if act == "save":
        return _ok(**organise.save_print_book(
            q.get("title", ""), q.get("author", ""), q.get("isbn", ""),
            q.get("publisher", ""), q.get("year", ""), q.get("note", ""),
            q.get("id", "")))
    if act == "delete":
        return _ok(**organise.delete_print_book(q.get("id", "")))
    if act == "check":
        return _ok(**organise.validate_isbn(q.get("isbn", "")))
    if act == "lookup":
        return _ok(**organise.lookup_isbn(q.get("isbn", "")))
    return _ok(books=organise.print_books())


@endpoint("community/pack")
def _community_pack(parts, q):
    act = q.get("action", "export")
    if act == "export":
        r = community.export_pack(
            note_ids=[x for x in (q.get("ids") or "").split(",") if x],
            name=q.get("name", ""))
        # Return the pack as JSON text so the client can save it as a file.
        import json as _j
        return _ok(pack=r["pack"], filename=r["filename"],
                   counts=r["counts"], text=_j.dumps(r["pack"], ensure_ascii=False))
    if act == "import":
        payload = q.get("pack")
        if isinstance(payload, str):
            try:
                import json as _j
                payload = _j.loads(payload)
            except Exception:  # noqa: BLE001
                payload = None
        if not isinstance(payload, dict):
            return _ok(ok=False, error="no pack provided")
        return _ok(**community.import_pack(payload))
    return _ok(ok=False, error="unknown action")


@endpoint("notebook")
def _notebook(parts, q):
    if q.get("action") == "save":
        return _ok(**organise.save_notebook(
            q.get("name", ""), q.get("kind", ""), q.get("tag", ""),
            q.get("query", ""), q.get("id", "")))
    if q.get("action") == "delete":
        return _ok(**organise.delete_notebook(q.get("id", "")))
    if q.get("id"):
        return _ok(id=q["id"], notes=organise.notebook_notes(q["id"]))
    return _ok(notebooks=organise.notebooks())


@endpoint("passagelist")
def _passagelist(parts, q):
    act = q.get("action")
    if act == "delete":
        return _ok(**organise.delete_passage_list(q.get("id", "")))
    if act == "add":
        return _ok(**organise.add_passage(q.get("id", ""), q.get("key", ""),
                                          q.get("ref", ""), q.get("module", "")))
    if act == "remove":
        return _ok(**organise.remove_passage(q.get("item", "")))
    if act == "move":
        try:
            d = int(q.get("delta") or 1)
        except ValueError:
            d = 1
        return _ok(**organise.move_passage(q.get("item", ""), d))
    if act == "save":
        return _ok(**organise.save_passage_list(q.get("name", ""),
                                                q.get("note", ""), q.get("id", "")))
    if q.get("id"):
        return _ok(id=q["id"], items=organise.passage_items(q["id"]))
    return _ok(lists=organise.passage_lists())


@endpoint("search/template")
def _search_template(parts, q):
    if q.get("action") == "delete":
        return _ok(**organise.delete_template(q.get("id", "")))
    if q.get("action") == "save":
        return _ok(**organise.save_template(q.get("name", ""), q.get("query", ""),
                                            _obj(q.get("options"), {})))
    if q.get("action") == "gallery":
        return _ok(**organise.template_gallery())
    return _ok(templates=organise.templates())


@endpoint("charts")
def _charts(parts, q):
    return _ok(**organise.charts(q.get("kind", "type"), q.get("arg", "")))


@endpoint("search/browser")
def _search_browser(parts, q):
    return _ok(**organise.browser_query(_obj(q.get("spec"), {}) or {}))


# ------------------------------------------------------------------ genealogy
@endpoint("bible/chapter")
def _bible_chapter(parts, q):
    """Verses of one chapter of one module, in order, for copying/export."""
    mid = q.get("id") or ""
    book = q.get("book") or ""
    try:
        chapter = int(q.get("chapter") or 0)
    except (TypeError, ValueError):
        chapter = 0
    if not mid or not book or not chapter:
        return {"ok": False, "error": "need id, book, chapter"}
    rows = db.connect().execute(
        "SELECT verse, ref_label, text FROM unit "
        "WHERE module_id=? AND book=? AND chapter=? "
        "ORDER BY verse", (mid, book, chapter)).fetchall()
    verses = [{"verse": r["verse"], "ref": r["ref_label"], "text": (r["text"] or "").strip()}
              for r in rows]
    return {"ok": True, "module_id": mid, "book": book, "chapter": chapter,
            "verses": verses, "count": len(verses)}


@endpoint("bible/books")
def _bible_books(parts, q):
    """Which installed Bibles contain which books.

    Following a reference needs this.  Opening "Genesis 11:26" in the first Bible
    the catalogue happened to offer can land in a New Testament, which has no
    Genesis -- the reader then shows an empty pane and the link looks broken.
    """
    rows = db.connect().execute(
        "SELECT DISTINCT u.module_id, u.book FROM unit u JOIN module m"
        " ON m.id=u.module_id WHERE m.installed_at>0 AND m.type='Bible'"
        " AND u.book<>''").fetchall()
    books: dict = {}
    for r in rows:
        books.setdefault(r["module_id"], []).append(r["book"])
    for k in books:
        books[k].sort()
    return _ok(books=books)


# ------------------------------------------------------- original language
@endpoint("morph/facets")
def _morph_facets(parts, q):
    return _ok(**{"facets": morphq.facets()})


@endpoint("morph/query")
def _morph_query(parts, q):
    try:
        limit = int(q.get("limit") or 60)
        offset = int(q.get("offset") or 0)
    except ValueError:
        limit, offset = 60, 0
    allowed = ("pos", "gender", "number", "state", "conjugation", "tense",
               "person", "participle", "scheme", "pos_particle")
    filters = {k: q[k] for k in allowed if q.get(k) and q.get(k) != "any"}
    return _ok(**morphq.query(limit=limit, offset=offset,
                              order=q.get("order") or "count", **filters))


@endpoint("morph/reverse")
def _morph_reverse(parts, q):
    try:
        limit = int(q.get("limit") or 40)
        offset = int(q.get("offset") or 0)
    except ValueError:
        limit, offset = 40, 0
    return _ok(**morphq.reverse_interlinear(
        q.get("num", ""), limit=limit, offset=offset,
        order=q.get("order") or "canonical", script=q.get("script") or "auto"))


@endpoint("morph/concordance")
def _morph_concordance(parts, q):
    try:
        limit = int(q.get("limit") or 60)
        offset = int(q.get("offset") or 0)
    except ValueError:
        limit, offset = 60, 0
    return _ok(**morphq.concordance(
        q.get("num", ""), limit=limit, offset=offset,
        module_id=q.get("module", ""),
        include_context=q.get("context", "1") not in ("0", "false")))


@endpoint("timeline/linked")
def _timeline_linked(parts, q):
    return _ok(**timeline.linked())


@endpoint("genealogy/summary")
def _genealogy_summary(parts, q):
    return _ok(**genealogy.summary())


@endpoint("genealogy/person")
def _genealogy_person(parts, q):
    return _ok(**genealogy.person(q.get("name", "")))


@endpoint("genealogy/ancestry")
def _genealogy_ancestry(parts, q):
    try:
        d = int(q.get("depth") or 16)
    except ValueError:
        d = 16
    return _ok(**genealogy.ancestry(q.get("name", ""), min(d, 40)))


@endpoint("genealogy/subtree")
def _genealogy_subtree(parts, q):
    try:
        d = int(q.get("depth") or 3)
    except ValueError:
        d = 3
    return _ok(**genealogy.subtree(q.get("name", ""), min(d, 6)))


@endpoint("guides/timeline")
def _guides_timeline(parts, q):
    return _ok(**timeline.timeline(kind=q.get("kind", ""),
                                  period=q.get("period", "")))


@endpoint("guides/biblefacts")
def _guides_biblefacts(parts, q):
    from gbible import biblefacts
    return _ok(**biblefacts.bible_facts())


@endpoint("guides/canon")
def _guides_canon(parts, q):
    return guides.canon_table(q.get("tradition", "66"),
                              q.get("v11n", "KJV"))


@endpoint("guides/canons")
def _guides_canons(parts, q):
    return _ok(charts=guides.canon_charts())


@endpoint("guides/harmony")
def _guides_harmony(parts, q):
    return _ok(**guides.harmony())


@endpoint("guides/parallels")
def _guides_parallels(parts, q):
    return _ok(**guides.ot_parallels())


@endpoint("guides/chapter")
def _guides_chapter(parts, q):
    return guides.chapter_guide(q.get("ref", ""))


@endpoint("guide/sections")
def _guide_sections(parts, q):
    return _ok(sections=guides.guide_sections(),
               defaults={k: v for k, v in guides.DEFAULT_GUIDES.items()})


@endpoint("guide/config")
def _guide_config(parts, q):
    import json as _j
    guide = q.get("guide", "passage")
    if q.get("action") == "set":
        secs = q.get("sections", [])
        if isinstance(secs, str):
            try:
                secs = _j.loads(secs)
            except Exception:  # noqa: BLE001
                secs = []
        return _ok(**guides.set_config(guide, secs))
    return _ok(guide=guide, sections=guides.get_config(guide))


@endpoint("guide/section")
def _guide_section(parts, q):
    import json as _j
    opts = q.get("opts", {})
    if isinstance(opts, str):
        try:
            opts = _j.loads(opts)
        except Exception:  # noqa: BLE001
            opts = {}
    opts = dict(opts or {})
    for k in ("limit", "offset", "sort", "collection"):
        if k in q:
            opts[k] = q[k]
    return _ok(**guides.run_section(q.get("section", ""), q.get("key", ""),
                                   opts))


@endpoint("guide/run")
def _guide_run(parts, q):
    return _ok(**guides.run_guide(q.get("guide", "passage"), q.get("key", "")))


@endpoint("guide/list")
def _guide_list(parts, q):
    return _ok(guides=guides.guide_list())


@endpoint("guide/create")
def _guide_create(parts, q):
    import json as _j
    name = q.get("name", "")
    secs = q.get("sections", [])
    if isinstance(secs, str):
        try:
            secs = _j.loads(secs)
        except Exception:  # noqa: BLE001
            secs = []
    return _ok(**guides.guide_create(name, secs))


@endpoint("guide/delete")
def _guide_delete(parts, q):
    return _ok(**guides.guide_delete(q.get("name", "")))



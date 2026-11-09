from .common import *

# ------------------------------------------------------------------ documents
# Pack 5: clippings, quotations, cards, study questions, prayer templates,
# plan manager, lectionary selection, sermon helpers, workflow library,
# canvas, reminders.
@endpoint("clipping")
def _clipping(parts, q):
    act = q.get("action")
    if act == "save":
        return _ok(**docs.save_clipping(q.get("heading", ""), q.get("id", "")))
    if act == "add":
        return _ok(**docs.add_clip_item(
            q.get("id", ""), q.get("quote", ""), q.get("module", ""),
            q.get("ref", ""), q.get("key", "")))
    if act == "remove":
        return _ok(**docs.remove_clip_item(q.get("id", ""), q.get("item", "")))
    if act == "delete":
        return _ok(**docs.delete_clipping(q.get("id", "")))
    if act == "card":
        return _ok(**docs.selection_card(q.get("quote", ""),
                                         q.get("module", ""), q.get("ref", "")))
    return _ok(clippings=docs.clippings())


@endpoint("quotations")
def _quotations(parts, q):
    try:
        lim = int(q.get("limit") or 8)
    except ValueError:
        lim = 8
    return _ok(**docs.quotations(q.get("q", ""), lim))


@endpoint("questions")
def _questions(parts, q):
    return _ok(**docs.study_questions(q.get("ref", "")))


@endpoint("prayer/template")
def _prayer_template(parts, q):
    if q.get("action") == "save":
        try:
            freq = int(q.get("frequency_days") or 1)
        except ValueError:
            freq = 1
        return _ok(**docs.save_prayer_template(
            q.get("name", ""), q.get("body", ""), freq, q.get("id", "")))
    if q.get("action") == "delete":
        return _ok(**docs.delete_prayer_template(q.get("id", "")))
    if q.get("action") == "due":
        return _ok(**docs.prayer_due())
    return _ok(templates=docs.prayer_templates())


@endpoint("plans/manager")
def _plans_manager(parts, q):
    act = q.get("action")
    if act == "pace":
        return _ok(**docs.set_plan_pace(q.get("plan", ""), q.get("pace", "")))
    if act == "archive":
        return _ok(**docs.set_plan_archived(
            q.get("plan", ""), q.get("archived", True) is not False))
    if act == "estimate":
        try:
            n = int(q.get("day") or 0)
        except ValueError:
            n = 0
        return _ok(**docs.estimate_day(q.get("plan", ""), n))
    if act == "skip":
        return _ok(**docs.skip_to_latest(q.get("plan", "")))
    if act == "export":
        return _ok(**docs.export_plans())
    if act == "import":
        import json as _j
        payload = q.get("payload", {})
        if isinstance(payload, str):
            try:
                payload = _j.loads(payload)
            except Exception:  # noqa: BLE001
                payload = {}
        return _ok(**docs.import_plans(payload))
    if act == "lectionary":
        return _ok(**docs.builtin_lectionary())
    return _ok(**docs.plan_manager())


@endpoint("sermon")
def _sermon(parts, q):
    act = q.get("action")
    if act == "outline":
        return _ok(**docs.sermon_outline(q.get("id", "")))
    if act == "save_outline":
        import json as _j
        outline = q.get("outline", [])
        if isinstance(outline, str):
            try:
                outline = _j.loads(outline)
            except Exception:  # noqa: BLE001
                outline = [outline]
        return _ok(**docs.sermon_save_outline(q.get("id", ""), outline))
    if act == "schedule":
        return _ok(**docs.sermon_schedule(q.get("date", ""), q.get("id", "")))
    if act == "calendar":
        return _ok(calendar=docs.sermon_calendar())
    if act == "markers":
        return _ok(**docs.sermon_markers(q.get("ref", "")))
    if act == "export":
        kind = q.get("kind", "slides")
        if kind == "pptx":
            return _ok(ok=False, error="Sermon PPTX is not served over JSON; "
                                       "use the passage or notes export, or "
                                       "call sermon_export directly.")
        return _ok(**docs.sermon_export(q.get("id", ""), kind))
    if act == "builder_get":
        return _ok(**docs.sermon_builder_get(q.get("id", "")))
    if act == "builder_save":
        import json as _j
        structure = q.get("structure", {})
        if isinstance(structure, str):
            try:
                structure = _j.loads(structure)
            except Exception:  # noqa: BLE001
                structure = {}
        return _ok(**docs.sermon_builder_save(q.get("id", ""), structure))
    if act == "manager":
        return _ok(**docs.sermon_manager())
    if act == "import":
        return _ok(**docs.sermon_import(q.get("text", ""),
                                        q.get("title", ""),
                                        q.get("series", "")))
    return _ok(calendar=docs.sermon_calendar())


@endpoint("workflows/library")
def _workflows_library(parts, q):
    if q.get("action") == "install":
        return _ok(**docs.workflow_install(q.get("name", "")))
    return _ok(**docs.workflow_library())


@endpoint("canvas")
def _canvas(parts, q):
    import json as _j
    act = q.get("action")
    if act == "save":
        els = q.get("elements", [])
        if isinstance(els, str):
            try:
                els = _j.loads(els)
            except Exception:  # noqa: BLE001
                els = []
        return _ok(**docs.save_canvas(q.get("name", ""), els, q.get("id", "")))
    if act == "delete":
        return _ok(**docs.delete_canvas(q.get("id", "")))
    return _ok(canvases=docs.canvases())


@endpoint("reminders")
def _reminders(parts, q):
    return _ok(**docs.reminders())


@endpoint("syntax/search")
def _syntax_search(parts, q):
    from ... import syntax as _sx
    try:
        lim = int(q.get("limit") or 100)
    except ValueError:
        lim = 100
    return _ok(**_sx.syntax_search(
        module_id=q.get("id", ""), upos=q.get("upos", ""),
        deprel=q.get("deprel", ""), form=q.get("form", ""),
        lemma=q.get("lemma", ""), limit=lim))


@endpoint("syntax/sentence")
def _syntax_sentence(parts, q):
    from ... import syntax as _sx
    return _ok(**_sx.syntax_sentence(q.get("id", ""), q.get("key", "")))


@endpoint("sense/for")
def _sense_for(parts, q):
    from ... import senses as _se
    try:
        lim = int(q.get("limit") or 12)
    except ValueError:
        lim = 12
    return _ok(**_se.senses_for(q.get("num", ""), lim))


@endpoint("apparatus/collate")
def _apparatus_collate(parts, q):
    from ... import apparatus as _ap
    mods = q.get("modules", [])
    if isinstance(mods, str):
        mods = [m for m in mods.split(",") if m]
    return _ok(**_ap.collate(q.get("ref", ""), mods or None))


@endpoint("apparatus/chapter")
def _apparatus_chapter(parts, q):
    from ... import apparatus as _ap
    try:
        ch = int(q.get("chapter") or 0)
    except ValueError:
        ch = 0
    return _ok(**_ap.collate_chapter(q.get("book", ""), ch))


@endpoint("preach/outlines")
def _preach_outlines(parts, q):
    from ... import preach as _pr
    try:
        lim = int(q.get("limit") or 8)
    except ValueError:
        lim = 8
    return _ok(**_pr.sermon_outlines(q.get("ref", ""), lim))


@endpoint("counsel/topics")
def _counsel_topics(parts, q):
    from ... import preach as _pr
    return _ok(**_pr.counsel_topics())


@endpoint("counsel/guide")
def _counsel_guide(parts, q):
    from ... import preach as _pr
    try:
        lim = int(q.get("limit") or 8)
    except ValueError:
        lim = 8
    return _ok(**_pr.counsel_guide(q.get("topic", ""), lim))


@endpoint("explore/psalms")
def _explore_psalms(parts, q):
    from ... import explore as _ex
    return _ok(**_ex.psalms_explorer(q.get("id", "")))


@endpoint("explore/books")
def _explore_books(parts, q):
    from ... import explore as _ex
    return _ok(**_ex.books_stats(q.get("id", "")))


@endpoint("citedby")
def _citedby(parts, q):
    from ... import lookup as _lu
    mods = q.get("modules", [])
    if isinstance(mods, str):
        mods = [m for m in mods.split(",") if m]
    return _ok(**_lu.cited_by(q.get("ref", ""), mods or None,
                              q.get("collection", "")))


@endpoint("info/lookup")
def _info_lookup(parts, q):
    from ... import lookup as _lu
    return _ok(**_lu.info_lookup(q.get("ref", ""), q.get("word", "")))


@endpoint("words/important")
def _words_important(parts, q):
    from ... import lookup as _lu
    try:
        lim = int(q.get("limit") or 10)
    except ValueError:
        lim = 10
    return _ok(**_lu.important_words(q.get("ref", ""), lim))


@endpoint("flash")
def _flash(parts, q):
    act = q.get("action")
    if act == "start":
        try:
            lim = int(q.get("limit") or 200)
        except ValueError:
            lim = 200
        return _ok(**docs.flash_start(q.get("source", ""), q.get("id", ""), lim))
    if act == "score":
        return _ok(**docs.flash_score(q.get("known", True) is not False))
    return _ok(**docs.flash_state())


@endpoint("highlight/palettes")
def _highlight_palettes(parts, q):
    act = q.get("action")
    if act == "save":
        import json as _j
        colors = q.get("colors", [])
        if isinstance(colors, str):
            try:
                colors = _j.loads(colors)
            except Exception:  # noqa: BLE001
                colors = [colors]
        return _ok(**docs.save_palette(q.get("name", ""), colors,
                                       q.get("id", "")))
    if act == "delete":
        return _ok(**docs.delete_palette(q.get("id", "")))
    if act == "activate":
        return _ok(**docs.activate_palette(q.get("id", "")))
    return _ok(**docs.highlight_palettes())


# Pack 6: reader editions, pronunciation guide, outline export, ribbons.
@endpoint("reader/edition")
def _reader_edition(parts, q):
    if q.get("preset"):
        preset = docs.READER_EDITIONS.get(q["preset"], None)
        if preset is None:
            return _ok(ok=False, error="Unknown edition")
        return _ok(preset=q["preset"], options={k: v for k, v in preset.items()
                                                if k != "about"},
                   about=preset["about"])
    return _ok(**docs.reader_editions())


@endpoint("pronounce/guide")
def _pronounce_guide(parts, q):
    return _ok(**docs.pronounce_guide(q.get("word", "")))


@endpoint("export/outline")
def _export_outline(parts, q):
    return _ok(**docs.export_outline_doc(q.get("ref", "")))


@endpoint("reading/ribbons")
def _reading_ribbons(parts, q):
    try:
        ch = int(q.get("chapter") or 0)
    except ValueError:
        ch = 0
    return _ok(**docs.reading_ribbons(q.get("book", ""), ch))


@endpoint("passagelist/from_refs")
def _passagelist_from_refs(parts, q):
    refs = q.get("refs", [])
    if isinstance(refs, str):
        import json as _j
        try:
            refs = _j.loads(refs)
        except Exception:  # noqa: BLE001
            refs = [r.strip() for r in refs.split(";") if r.strip()]
    name = (q.get("name") or "From cross-references").strip()
    lst = organise.save_passage_list(name, "", "")
    conn = db.connect()
    m = library.get(q.get("module", "")) if q.get("module") else None
    added, missing = 0, []
    for ref in refs or []:
        rr = canon.parse_ref(ref, m.v11n if m else "KJV")
        if rr is None:
            missing.append(ref)
            continue
        # Resolve against the resource's own units by book/chapter/verse and
        # take the key *it* uses, rather than assuming the OSIS id.  `unit.key`
        # is the importer's spelling and is not always one -- see
        # filters.filtered_reading, which had the same assumption and the same
        # consequence: an empty reading from a Bible that plainly has the text.
        key = ""
        if m is not None:
            for v in rr.refs():
                row = conn.execute(
                    "SELECT key FROM unit WHERE module_id=? AND book=? AND "
                    "chapter=? AND verse=? LIMIT 1",
                    (m.id, v.book, v.chapter, v.verse)).fetchone()
                if row is not None:
                    key = row["key"]
                    break
        if not key:
            key = next(iter(rr.refs())).osis_id()
        r = organise.add_passage(lst["id"], key, ref,
                                 q.get("module", ""))
        if r.get("items") is not None:
            added += 1
    del conn
    return _ok(id=lst["id"], name=name, added=added, missing=missing,
               items=organise.passage_items(lst["id"]))


@endpoint("dashboard")
def _dashboard(parts, q):
    """The landing view: today's reading, where you were, what you wrote."""
    return dashboard.build()


@endpoint("notes/list")
def _notes_list(parts, q):
    return _ok(notes=notes.listing(q.get("kind", ""), q=q.get("q", ""),
                                   tag=q.get("tag", ""),
                                   limit=int(q.get("limit") or 500),
                                   since=float(q.get("since") or 0)),
               stats=notes.stats())


@endpoint("notes/get")
def _notes_get(parts, q):
    n = notes.get(q.get("id", ""))
    if n is None:
        return {"ok": False, "error": "no such note"}
    return _ok(note=n)


@endpoint("notes/save")
def _notes_save(parts, body):
    if not body:
        return {"ok": False, "error": "empty"}
    return _ok(note=notes.save(body))


@endpoint("notes/delete")
def _notes_delete(parts, body):
    body = body or {}
    if body.get("action") == "clear":
        return _ok(**notes.clear(body.get("kind", "")))
    return _ok(removed=notes.remove(body.get("id", "")))


@endpoint("notes/at")
def _notes_at(parts, q):
    """Notes anchored to one unit, so the reader can show them in the pane."""
    return _ok(notes=notes.notes_at(q.get("id", ""), q.get("key", "")))


@endpoint("notes/prayer")
def _notes_prayer(parts, q):
    return _ok(note=notes.prayer_day(q.get("day", "")), day=q.get("day", ""))


# ------------------------------------------------------ citation & export ---
@endpoint("cite/styles")
def _cite_styles(parts, q):
    return _ok(styles=[{"id": k, "label": v} for k, v in
                       citation.STYLES.items()],
               fields=[{"id": f, "label": l} for f, l in
                       citation.EDITABLE_FIELDS],
               formats=sorted(publish.FORMATS),
               # Per document, so a dialog can only offer what its own endpoint
               # can write.  Declared here by the module that does the writing,
               # which is the only place the answer can stay true.
               document={"passage": publish.document_formats("passage"),
                         "notes": publish.document_formats("notes"),
                         "bibliography": publish.document_formats("bibliography")})


@endpoint("cite/get")
def _cite_get(parts, q):
    """A citation for one work, plus what it could not say."""
    return citation.cite(q.get("id", ""), q.get("style", "sbl"),
                         full=q.get("full") in ("1", "true", "yes"))


@endpoint("cite/passage")
def _cite_passage(parts, q):
    """A citation for a passage.  This case is complete by construction."""
    return citation.passage_citation(
        q.get("ref", ""), q.get("id", ""), style=q.get("style", "sbl"),
        full=q.get("full") in ("1", "true", "yes"))


@endpoint("cite/field")
def _cite_field(parts, q, body=None):
    """Record what the user knows about a work, so later citations are correct."""
    return citation.set_field(q.get("id", ""), q.get("field", ""),
                              q.get("value", ""))


@endpoint("cite/completeness")
def _cite_completeness(parts, q):
    """How citable this library is, counted honestly."""
    conn = db.connect()
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM module WHERE installed_at>0 ORDER BY id")]
    return _ok(**citation.completeness(ids))


@endpoint("cite/bibliography")
def _cite_bibliography(parts, q):
    ids = [x for x in (q.get("ids") or "").split(",") if x]
    if not ids:
        ids = [r["id"] for r in db.connect().execute(
            "SELECT id FROM module WHERE installed_at>0 ORDER BY id")]
    return citation.bibliography(ids, style=q.get("style", "sbl"))


@endpoint("cite/attribution")
def _cite_attribution(parts, q):
    ids = [x for x in (q.get("ids") or "").split(",") if x]
    return _ok(text=publish.attribution_block(ids),
               lines=publish.licence_lines(ids))


_MIME = {"pdf": "application/pdf", "rtf": "application/rtf",
         "html": "text/html; charset=utf-8", "md": "text/markdown; charset=utf-8",
         "txt": "text/plain; charset=utf-8", "bib": "application/x-bibtex",
         "ris": "application/x-research-info-systems", "csv": "text/csv; charset=utf-8",
          "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}


def _module_ids(params: dict) -> list[str]:
    ids = [x for x in (params.get("ids") or "").split(",") if x]
    if not ids and params.get("id"):
        ids = [params["id"]]
    return ids


@file_route("study-guide")
def _file_study_guide(params: dict):
    r = publish.study_guide_document(
        params.get("ref", ""), _module_ids(params),
        fmt=params.get("fmt", "pdf"), title=params.get("title", ""))
    if not r.get("ok"):
        raise ValueError(r.get("error") or "nothing to export")
    ext = r.get("format", "pdf")
    return (r.get("binary") if "binary" in r else r["text"],
            _slug(params.get("title") or params.get("ref") or "study-guide")
            + f".{ext}", _MIME.get(ext, "application/octet-stream"))


@file_route("passage")
def _file_passage(params: dict):
    r = publish.passage_document(
        params.get("ref", ""), _module_ids(params),
        style=params.get("style", "sbl"), fmt=params.get("fmt", "pdf"),
        title=params.get("title", ""))
    if not r.get("ok"):
        raise ValueError(r.get("error") or "nothing to export")
    ext = r.get("format", "pdf")
    return (r.get("binary") if "binary" in r else r["text"],
            _slug(params.get("title") or params.get("ref") or "passage") + f".{ext}",
            _MIME.get(ext, "application/octet-stream"))


@file_route("notes")
def _file_notes(params: dict):
    r = publish.notes_document(kind=params.get("kind", ""),
                               fmt=params.get("fmt", "md"),
                               title=params.get("title", ""))
    if not r.get("ok"):
        raise ValueError(r.get("error") or "no notes")
    ext = r.get("format", "md")
    return (r.get("binary") if "binary" in r else r["text"],
            _slug(params.get("title") or "notes") + f".{ext}",
            _MIME.get(ext, "application/octet-stream"))


@file_route("sermon-pptx")
def _file_sermon_pptx(params: dict):
    r = docs.sermon_export(params.get("id", ""), kind="pptx")
    if not r.get("ok"):
        raise ValueError(r.get("error") or "no sermon")
    return (r["binary"],
            _slug(params.get("title") or "sermon") + ".pptx",
            _MIME["pptx"])


@file_route("bibliography")
def _file_bibliography(params: dict):
    r = publish.bibliography_document(
        _module_ids(params), style=params.get("style", "sbl"),
        fmt=params.get("fmt", "md"), title=params.get("title", ""))
    if not r.get("ok"):
        raise ValueError(r.get("error") or "nothing to cite")
    ext = r.get("format", "md")
    return (r.get("binary") if "binary" in r else r["text"],
            _slug(params.get("title") or "bibliography") + f".{ext}",
            _MIME.get(ext, "application/octet-stream"))


@endpoint("notes/export")
def _notes_export(parts, q):
    """Markdown, so the writing is a file and not only a database row."""
    text = notes.export_markdown(q.get("kind", ""))
    return _ok(markdown=text, filename="gbible-notes.md")


@endpoint("reference/scan")
def _reference_scan(parts, q):
    """Scan arbitrary text for Bible references.

    `texts` batches several strings in one round trip: the reader now links
    references across a whole pane, and one request per paragraph costs the
    book reader a couple of seconds.  The reply lines up one list of refs with
    each input string."""
    texts = q.get("texts")
    if texts is None:
        text = q.get("text") or ""
        return _ok(refs=canon.scan_refs(text))
    if isinstance(texts, str):
        try:
            texts = json.loads(texts)
        except ValueError:
            texts = []
    return _ok(refs=[canon.scan_refs(t or "", dedupe=False)
                     for t in list(texts)[:400]])


@endpoint("study/sensesearch")
def _study_sensesearch(parts, q):
    """Approximate Bible Sense Lexicon search by concept."""
    return _ok(**study.sense_search(db.connect(), q.get("q") or q.get("concept") or "",
                                    limit=int(q.get("limit") or 80)))


@endpoint("study/biblebrowser")
def _study_biblebrowser(parts, q):
    """Searchable index of Bible entities (places + fact-book headwords)."""
    return _ok(**study.bible_browser(db.connect()))


@endpoint("study/interlinear")
def _study_interlinear(parts, q):
    """One verse word by word: form, lemma, morphology, short gloss."""
    mid = q.get("id") or ""
    key = q.get("key") or ""
    if not mid or not key:
        return {"ok": False, "error": "need id and key"}
    row = db.connect().execute(
        "SELECT book, chapter, verse FROM unit WHERE module_id=? AND key=?",
        (mid, key)).fetchone()
    if row is None:
        return {"ok": False, "error": "no such unit"}
    return study.interlinear(db.connect(), mid, row["book"],
                             int(row["chapter"] or 0), int(row["verse"] or 0))


@endpoint("study/reverse_interlinear")
def _study_reverse_interlinear(parts, q):
    """One verse as a reverse interlinear: English on top, original beneath."""
    mid = q.get("id") or ""
    key = q.get("key") or ""
    if not mid or not key:
        return {"ok": False, "error": "need id and key"}
    row = db.connect().execute(
        "SELECT book, chapter, verse FROM unit WHERE module_id=? AND key=?",
        (mid, key)).fetchone()
    if row is None:
        return {"ok": False, "error": "no such unit"}
    return study.reverse_interlinear(db.connect(), mid, row["book"],
                                    int(row["chapter"] or 0), int(row["verse"] or 0))


@endpoint("study/morph")
def _study_morph(parts, q):
    """Morph search over the tagged original-language texts."""
    return study.morph_search(conn=db.connect(), code=q.get("code", ""),
                              module_id=q.get("module_id", ""),
                              limit=int(q.get("limit") or 400))


@endpoint("xrefs")
def _xrefs(parts, q):
    conn = db.connect()
    rows = conn.execute("SELECT to_key FROM xref WHERE module_id=? AND from_key=?",
                        (q.get("id", ""), q.get("key", ""))).fetchall()
    keys = [r["to_key"] for r in rows]
    if not keys:
        # fall back to the OSIS <reference> targets recorded at index time
        return _ok(refs=[])
    ph = ",".join("?" * len(keys))
    out = []
    for r in conn.execute(
            f"SELECT key, ref_label, text FROM unit WHERE module_id=? "
            f"AND key IN ({ph})", [q.get("id", ""), *keys]):
        out.append({"key": r["key"], "label": r["ref_label"],
                    "text": (r["text"] or "")[:300]})
    return _ok(refs=out)


@endpoint("places")
def _places(parts, q):
    """Bible places -- the map pane's data source."""
    term = (q.get("q") or "").strip().lower()
    raw = store.load_catalog("openbible-geo")
    places = raw.get("places", [])
    if term:
        def hit(p):
            if term in (p.get("name") or "").lower():
                return 3
            if any(term in (a or "").lower() for a in p.get("alt_names", [])):
                return 2
            if any(term in (c or "").lower() for c in p.get("passages", [])):
                return 1
            return 0
        scored = [(hit(p), p) for p in places]
        scored = [(s, p) for s, p in scored if s]
        scored.sort(key=lambda x: -x[0])
        places = [p for _s, p in scored]
    return _ok(places=places[:int(q.get("limit") or 400)],
               total=len(places),
               license=raw.get("license", ""),
               attribution=raw.get("attribution", ""))


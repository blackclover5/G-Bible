from .common import *

# --------------------------------------------------------------------- apis
@endpoint("apis")
def _apis(parts, q):
    apireg.sync()
    return _ok(apis=apireg.list_apis(category=q.get("category")),
               summary=apireg.summary(), categories=apireg.CATEGORIES)


@endpoint("apis/key")
def _apis_key(parts, q):
    return _ok(**apireg.set_key(q.get("id", ""), q.get("key", "")))


@endpoint("apis/enable")
def _apis_enable(parts, q):
    return _ok(**apireg.set_enabled(q.get("id", ""), bool(q.get("enabled"))))


@endpoint("apis/call")
def _apis_call(parts, q):
    """Call one enabled service.  Read-only GET; the gate is in registry.call.

    `params` arrives as text on a GET and as an object on a POST, so it is
    decoded the same way every other JSON-ish parameter is.  It was not, which
    meant the JS helper's `JSON.stringify` -- how every object parameter in
    this app is sent -- reached the transport as the literal string
    '{"q":"x"}' and failed in urlencode rather than at the call site.  The
    endpoint worked only over POST, with nothing in the front end to suggest it.
    """
    params = _obj(q.get("params"), {}) or {}
    if isinstance(params, str):
        params = {}
    try:
        result = apireg.call(q.get("id", ""), q.get("path", ""), params=params)
    except apireg.ApiError as e:
        # A refused call is a normal outcome -- the service is off, or has no
        # API -- not a server fault, so it is reported in the shape the rest of
        # the API uses and the traceback stays on the server.
        return _ok(result=None, error=str(e), hint=getattr(e, "hint", ""))
    return _ok(result=result)


# ----------------------------------------------------------------- outlines
@endpoint("outline/browser")
def _outline_browser(parts, q):
    """All books with their chapter/point index, for the Outline Browser."""
    import gbible.outline as _o
    _o.ensure_loaded()
    out = []
    for b in canon.BOOKS_66:
        r = _o.book_outline(b.osis)
        if r.get("ok"):
            out.append({"book": b.osis, "name": b.name, "chapters": r["chapters"],
                        "points": r["points"], "index": r["index"]})
        else:
            out.append({"book": b.osis, "name": b.name, "chapters": 0, "points": 0, "index": []})
    return _ok(books=out, source=_o.meta().get("source"), title=_o.meta().get("title"))


@endpoint("outline/meta")
def _outline_meta(parts, q):
    return _ok(sources=outline.sources(), current=outline.meta())


@endpoint("outline/book")
def _outline_book(parts, q):
    return outline.book_outline(q.get("book", ""))


@endpoint("outline/chapter")
def _outline_chapter(parts, q):
    r = outline.chapter(q.get("book", ""), int(q.get("chapter") or 0))
    # A heading says "Ge 1:3-5"; the pane wants the verses.  Resolving here
    # means the front end never has to know how a range is written.
    if r.get("ok"):
        for s in r["sections"]:
            s["verses"] = outline.to_passage(s.get("ref") or "")
    return _ok(**r)


# --------------------------------------------------------------- word lists
@endpoint("wordlist")
def _wordlist(parts, q):
    action = q.get("action", "")
    if action == "save":
        return _ok(**{"list": wordlist.save({
            "id": q.get("id", ""), "name": q.get("name", ""),
            "note": q.get("note", ""), "query": q.get("query", ""),
            "kind": q.get("kind", "term"),
            "options": _obj(q.get("options"), {}) or {}})})
    if action == "delete":
        return wordlist.remove(q.get("id", ""))
    if action == "pin":
        return wordlist.pin(q.get("id", ""), {
            "term": q.get("term", ""), "surface": q.get("surface", ""),
            "module_id": q.get("module", ""), "unit_key": q.get("key", ""),
            "ref_label": q.get("label", ""), "book": q.get("book", ""),
            "chapter": q.get("chapter"), "verse": q.get("verse"),
            "gloss": q.get("gloss", "")})
    if action == "unpin":
        return wordlist.unpin(q.get("item", ""))
    if action == "note":
        return wordlist.annotate(q.get("item", ""), q.get("note", ""),
                                 q.get("gloss", ""))
    if action == "move":
        return wordlist.move(q.get("item", ""), int(q.get("delta") or 0))
    if action == "from-search":
        return wordlist.from_search(q.get("query", ""),
                                    name=q.get("name", ""),
                                    options=_obj(q.get("options"), {}) or {})
    if action == "from-results":
        return wordlist.from_results(_obj(q.get("hits"), []) or [],
                                      name=q.get("name", ""),
                                      note=q.get("note", ""))
    if action == "passagelist":
        return wordlist.to_passage_list(q.get("id", ""),
                                        name=q.get("name", ""),
                                        module_id=q.get("module", ""))
    if action == "stats":
        return _ok(**{"stats": wordlist.stats()})
    return _ok(lists=wordlist.listing(kind=q.get("kind", ""),
                                      q=q.get("q", "")))


@endpoint("wordlist/occurrences")
def _wordlist_occurrences(parts, q):
    return wordlist.occurrences(q.get("id", ""),
                                limit=int(q.get("limit") or 2000),
                                offset=int(q.get("offset") or 0))


# ---------------------------------------------------------------- workflows
@endpoint("workflow")
def _workflow(parts, q):
    action = q.get("action", "")
    if action == "save":
        return _ok(**{"workflow": wordflow.save({
            "id": q.get("id", ""), "name": q.get("name", ""),
            "note": q.get("note", ""), "ref": q.get("ref", ""),
            "layout_id": q.get("layout", "")},
            steps=_obj(q.get("steps")))})
    if action == "delete":
        return wordflow.remove(q.get("id", ""))
    if action == "capture":
        return wordflow.capture(q.get("layout", ""), name=q.get("name", ""),
                                ref=q.get("ref", ""))
    if action == "run":
        return wordflow.run(q.get("id", ""), q.get("ref", ""))
    if action == "slots":
        return _ok(slots=wordflow.available_slots(),
                   kinds=list(wordflow.STEP_KINDS))
    if action == "get":
        w = wordflow.get(q.get("id", ""))
        return _ok(workflow=w) if w else {"ok": False, "error": "no such workflow"}
    return _ok(workflows=wordflow.listing())


# ------------------------------------------------------------------- clause
@endpoint("clause/search")
def _clause_search(parts, q):
    from ... import depparse
    rel = q.get("relation", "same") or "same"
    out = clause.clause_search(
        q.get("a", ""), q.get("b", ""), relation=rel,
        module_id=q.get("module", ""), book=q.get("book", ""),
        chapter=int(q.get("chapter") or 0), limit=int(q.get("limit") or 200),
        scan=int(q.get("scan") or 0))
    out["parser"] = depparse.available()[0]
    out["parser_note"] = depparse.available()[1]
    out["relations"] = [{"value": v, "label": lab}
                        for v, lab in depparse.RELATIONS]
    return out


@endpoint("clause/tokens")
def _clause_tokens(parts, q):
    """Distinct words of one verse, for the visual query builder."""
    return _ok(**clause.verse_tokens(q.get("ref", "")))


@endpoint("clause/diagram_export")
def _clause_diagram_export(parts, q):
    return _ok(**clause.diagram_export(q.get("ref", "")))


@endpoint("clause/parser")
def _clause_parser(parts, q):
    """Whether a dependency parse is available, and what it costs.

    Separate from the search because the panel needs to know before the reader
    presses Find -- offering "object of a verb" and then refusing is worse than
    not offering it, and a parser that took twenty seconds to warm up is worth
    saying out loud.
    """
    from ... import depparse
    ok, why = depparse.available()
    if not ok:
        return {"ok": True, "available": False, "reason": why,
                "relations": [{"value": v, "label": lab}
                              for v, lab in depparse.RELATIONS
                              if v not in ("object", "subject")]}
    st = depparse.stats()
    return {"ok": True, "available": True, "reason": "", "model": depparse.MODEL,
            "cached": st["cached"], "parsed": st["parsed"],
            "relations": [{"value": v, "label": lab}
                          for v, lab in depparse.RELATIONS]}


@endpoint("clause/diagram")
def _clause_diagram(parts, q):
    """The sentence diagram of one verse.

    `ref` picks the verse and the module is chosen from what is installed.  A
    tagged module is preferred, because its morphology is its own rather than
    worked out here.  Failing that, any installed Bible will do -- with the
    parser present an English verse gets real parts of speech and real clauses,
    which is strictly better than the punctuation-only diagram it used to get
    and better than nothing at all.

    Asking for the tagged module alone used to mean "John 3:16" was reported as
    absent from a library that contains it in three translations, because the
    Hebrew module has no John and the one tagged Greek work is not a Gospel.
    """
    ref = q.get("ref", "")
    mid = q.get("module", "")
    key = q.get("key", "")
    if not key:
        if not mid:
            from ..organise import _unit_for
            found = _unit_for(ref) if ref else None
            if not found:
                found = _unit_for(ref, tagged=False) if ref else None
            if not found:
                return {"ok": False,
                        "error": f"no verse {ref!r} in this library"}
            mid, key = found
        else:
            try:
                rr = canon.parse_ref(ref)
                key = next(iter(rr.refs())).osis_id() if rr else ""
            except Exception:
                key = ""
    if not key:
        return {"ok": False, "error": "no verse given"}
    r = clause.diagram(mid, key, ref=ref)
    if r.get("ok"):
        r["chart"] = organise.charts("morph", ref or key)
    return _ok(**r)


@endpoint("clause/segment")
def _clause_segment(parts, q):
    text = q.get("text", "")
    if not text:
        return {"ok": False, "error": "no text given"}
    return _ok(**clause.segment(text))


# --------------------------------------------------------------- translate
@endpoint("translate/status")
def _translate_status(parts, q):
    translate.sync()
    return _ok(**translate.status())


@endpoint("translate/languages")
def _translate_languages(parts, q):
    translate.sync()
    return _ok(languages=translate.languages(q.get("provider", "")))


@endpoint("translate/run")
def _translate_run(parts, q):
    translate.sync()
    return translate.translate(_obj(q.get("items"), []) or [],
                              target=q.get("target", "es"),
                              source=q.get("source", "auto"),
                              provider=q.get("provider", ""),
                              limit=int(q.get("limit") or 60))


# ------------------------------------------------------------------ catalog
@endpoint("catalog/summary")
def _catalog_summary(parts, q):
    return _ok(**publish.catalog_summary())


@file_route("catalog")
def _file_catalog(params: dict):
    r = publish.catalog_document(
        fmt=params.get("fmt", "pdf"), group=params.get("group", ""),
        title=params.get("title", ""),
        detail=params.get("detail", "1") not in ("0", "false", "no"),
        filters=_obj(params.get("filters"), {}) or {})
    if not r.get("ok"):
        raise ValueError(r.get("error") or "nothing to print")
    ext = r.get("format", "pdf")
    return (r.get("binary") if "binary" in r else r["text"],
            _slug(params.get("title") or "library-catalogue") + f".{ext}",
            _MIME.get(ext, "application/octet-stream"))


@file_route("wordlist")
def _file_wordlist(params: dict):
    r = wordlist.export(params.get("id", ""), params.get("fmt", "csv"))
    if not r.get("ok"):
        raise ValueError(r.get("error") or "nothing to export")
    ext = r.get("format", "csv")
    name = (params.get("name") or "word-list")
    return (r["text"], _slug(f"{name}.{ext}") if "." not in name
            else _slug(name), _MIME.get(ext, "text/plain; charset=utf-8"))


# ---------------------------------------------------------------- workspace
@endpoint("workspace")
def _workspace(parts, q):
    lay = workspace.current() or workspace.bootstrap()
    return _ok(layout=lay, arrangements=workspace.ARRANGEMENTS,
               guide=workspace.ARRANGEMENT_GUIDE,
               link_sets=workspace.LINK_SETS)


@endpoint("workspace/layouts")
def _layouts(parts, q):
    return _ok(layouts=workspace.list_layouts())


@endpoint("workspace/study")
def _study_layout(parts, q):
    """Build (or rebuild) the default multi-pane study layout."""
    return _ok(**{"layout": workspace.build_study_layout(
        q.get("name", "Study"))})


@endpoint("workspace/new")
def _new_layout(parts, q):
    return _ok(**{"layout": workspace.create_layout(
        q.get("name", "Layout"), arrangement=q.get("arrangement", "2 Columns"))})


@endpoint("workspace/save")
def _save_layout(parts, q):
    return _ok(**{"layout": workspace.save_layout(
        q.get("id", ""), q.get("name", "Layout"),
        q.get("tiles") or [], q.get("panes") or [])})


@endpoint("workspace/use")
def _use_layout(parts, q):
    return _ok(**{"layout": workspace.use_layout(q.get("id", ""))})


@endpoint("workspace/delete")
def _del_layout(parts, q):
    force = str(q.get("force", "")).lower() in ("1", "true", "yes")
    return workspace.delete_layout(q.get("id", ""), force=force)


@endpoint("workspace/pane")
def _pane(parts, q):
    if q.get("action") == "add":
        return _ok(**{"pane": _pane_dict(workspace.add_pane(
            q.get("layout", ""), q.get("module", ""), tile_id=q.get("tile", ""),
            link_set=q.get("link_set", ""), cursor=_obj(q.get("cursor"), {}) or {},
            view=q.get("view", "normal"), options=_obj(q.get("options"), {}) or {},
            text_size=int(q.get("text_size") or 100)))})
    if q.get("action") == "close":
        return _ok(**workspace.close_pane(q.get("pane", "")))
    p = workspace.update_pane(q.get("pane", ""), **{
        k: (_obj(v) if k in ("cursor", "options") else v)
        for k, v in q.items() if k not in ("action", "pane")})
    return _ok(**{"pane": _pane_dict(p) if p else None})


@endpoint("workspace/link")
def _link(parts, q):
    return _ok(**{"links": workspace.sync(q.get("pane", ""),
                                          _obj(q.get("cursor"), {}) or {})})


@endpoint("workspace/linksets")
def _linksets(parts, q):
    lay = workspace.current()
    if not lay:
        return _ok(groups={})
    groups = {L: [{"pane_id": p.id, "module_id": p.module_id,
                   "module_name": (library.get(p.module_id).name
                                   if library.get(p.module_id) else ""),
                   "follow_only": p.follow_only}
                  for p in workspace.link_group(lay["id"], L)]
              for L in workspace.LINK_SETS}
    return _ok(groups=groups)


@endpoint("workspace/clear_links")
def _clear_links(parts, q):
    lay = workspace.current()
    lid = q.get("layout", "") or (lay["id"] if lay else "")
    if not lid:
        return _ok(ok=False, error="No workspace is open")
    return _ok(**workspace.clear_links(lid))


@endpoint("workspace/arrange")
def _arrange(parts, q):
    lay = workspace.current()
    lid = q.get("layout", "") or (lay["id"] if lay else "")
    if not lid:
        return _ok(ok=False, error="No workspace is open")
    return _ok(**workspace.rearrange(lid, q.get("arrangement", "2 Columns")))


@endpoint("workspace/quickstarts")
def _quickstarts(parts, q):
    return _ok(quickstarts=workspace.quickstarts())


@endpoint("workspace/quickstart")
def _quickstart(parts, q):
    return _ok(**{"layout": workspace.build_quickstart(
        q.get("name", "Bible + Commentary"))})


@endpoint("workspace/top_bible")
def _top_bible(parts, q):
    if q.get("action") == "set":
        return _ok(**workspace.set_top_bible(q.get("id", "")))
    top = workspace.get_top_bible()
    m = library.get(top) if top else None
    return _ok(top_bible=top, name=m.name if m else "")


@endpoint("workspace/prioritize_rules")
def _prioritize_rules(parts, q):
    if q.get("action") == "set":
        import json as _j
        raw = q.get("rules", "[]")
        try:
            rules = _j.loads(raw) if isinstance(raw, str) else raw
        except Exception:  # noqa: BLE001
            rules = []
        return _ok(**workspace.set_prioritize_rules(rules))
    ref = q.get("ref", "")
    req_type = q.get("type", "")
    return _ok(rules=workspace.get_prioritize_rules(),
               resolved=workspace.resolve_priority(req_type, ref))


@endpoint("workspace/parallel")
def _parallel(parts, q):
    direction = q.get("direction", "")
    if direction in ("1", "next", "-1", "prev"):
        d = -1 if str(direction) in ("-1", "prev") else 1
        return _ok(**workspace.parallel_step(
            q.get("module", ""), d, q.get("collection", "")))
    return _ok(**workspace.parallel_group(
        q.get("module", ""), q.get("collection", "")))


@endpoint("workspace/progress")
def _progress(parts, q):
    if q.get("action") == "mark":
        return _ok(**workspace.mark_progress(
            q.get("module", ""), q.get("key", ""), q.get("label", ""),
            float(q.get("pct") or 0.0)))
    if q.get("action") == "reset":
        return _ok(**workspace.reset_progress(q.get("module", "")))
    return _ok(progress=workspace.get_progress())


@endpoint("workspace/copy_location")
def _copy_location(parts, q):
    return _ok(**workspace.copy_location(q.get("pane", "")))



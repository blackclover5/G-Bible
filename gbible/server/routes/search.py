from .common import *

# ------------------------------------------------------------------ search
@endpoint("search")
def _search(parts, q):
    opts = search.SearchOpts(
        modules=_obj(q.get("modules"), []) or [],
        scope=q.get("scope") or "",
        match_case=_flag(q.get("match_case")),
        match_all_forms=_flag(q.get("match_all_forms")),
        limit=_bounded_int(q.get("limit"), 200, low=1, high=2000),
        offset=_bounded_int(q.get("offset"), 0, low=0, high=100000),
        sort=q.get("sort", "relevance"),
        snippets=_flag(q.get("snippets", True)),
        context=_bounded_int(q.get("context"), 0, low=0, high=5),
        include_resolved=str(q.get("include_resolved", "1")).lower()
        not in ("0", "false", "no"),
    )
    return search.search(q.get("q", ""), opts)


@endpoint("search/analysis")
def _search_analysis(parts, q):
    """A result set as a sortable grid plus facets, counted server-side.

    The ordinary search endpoint ships a page of hits for reading.  Analysis
    re-runs the query with a bound and attaches the tags from the marker table,
    so a column can be sorted and a facet can count all the hits -- not just
    the page the browser happened to receive.
    """
    from ... import analysis as _a
    opts = search.SearchOpts(
        modules=_obj(q.get("modules"), []) or [],
        scope=q.get("scope") or "",
        match_case=_flag(q.get("match_case")),
        match_all_forms=_flag(q.get("match_all_forms")),
        include_resolved=str(q.get("include_resolved", "1")).lower()
        not in ("0", "false", "no"),
    )
    try:
        max_hits = int(q.get("max_hits") or 5000)
    except (TypeError, ValueError):
        max_hits = 5000
    descending = str(q.get("dir", "desc")).lower() != "asc"
    return _ok(**_a.analyse(q.get("q", ""), opts=opts, max_hits=max_hits,
                            sort=q.get("sort") or "score",
                            descending=descending))


@endpoint("search/help")
def _search_help(parts, q):
    return _ok(operators=search.OPERATOR_HELP,
               warnings=search.operator_warnings(q.get("q", "")))


@endpoint("search/spell")
def _spell(parts, q):
    """Suggestions for one bare word, checked as it was typed.

    A single word goes to search.word_notes(), which looks the word up before
    anything is stemmed.  Anything with an operator in it is handed to the
    ordinary smart_notes(), which is the right thing there: the suggestion is
    about the query as a whole, not about one of its words.

    This endpoint answers with nothing until the spelling tables have been
    warmed (search.prewarm_spelling(), started by run.py at startup).  They
    cost about eight seconds to build between them, and this is the one
    caller that cannot wait -- it runs on every debounced keystroke, so an
    unwarmed answer is a frozen tab.  A submitted search is unaffected: those
    go through search.search() and always get their suggestions.
    """
    mods = library.list_all()
    raw = (q.get("q") or "").strip()
    if not search.spelling_ready():
        return _ok(smart=[])
    # "H3096" is already a query the box understands, and it is split by the
    # parser into two junk tokens -- which then each get a spelling note, so
    # typing a Strong's number produces advice about the digits in it. It is
    # not a misspelling of anything, so it gets no spelling note.
    if re.fullmatch(r"[GgHh]\d{1,5}", raw):
        return _ok(smart=[])
    if re.fullmatch(r"[A-Za-z][A-Za-z'-]{1,}", raw):
        return _ok(smart=search.word_notes(raw, mods))
    qy = search.parse(raw or "love")
    return _ok(smart=search.smart_notes(qy, mods, search.SearchOpts()))


@endpoint("search/ranges")
def _search_ranges(parts, q):
    from ... import filters as _f
    if q.get("action") == "search":
        opts = _obj(q.get("opts"), {}) or {}
        return _ok(**_f.search_in_range(
            q.get("q", ""), q.get("range", "New Testament"), opts))
    return _ok(ranges=_f.ranges())


@endpoint("search/equivalent")
def _search_equivalent(parts, q):
    from ... import filters as _f
    return _ok(**_f.equivalent_refs(q.get("id", ""), q.get("ref", "")))


@endpoint("search/panel_link")
def _panel_link(parts, q):
    from ... import filters as _f
    if q.get("action") == "set":
        return _ok(**_f.set_panel_link(q.get("link_set", "")))
    return _ok(link_set=_f.get_panel_link(), link_sets=workspace.LINK_SETS)


@endpoint("visualfilter")
def _visualfilter(parts, q):
    from ... import filters as _f
    act = q.get("action")
    if act == "save":
        return _ok(**_f.save_visual_filter(
            q.get("name", ""), q.get("query", ""), q.get("style", "yellow"),
            q.get("morph", ""), _flag(q.get("enabled", True)),
            q.get("id", "")))
    if act == "delete":
        return _ok(**_f.delete_visual_filter(q.get("id", "")))
    if act == "apply":
        if q.get("key"):
            return _ok(**_f.apply_for_key(q.get("id", ""), q.get("key", "")))
        try:
            ch = int(q.get("chapter") or 0)
        except ValueError:
            ch = 0
        return _ok(**_f.apply_visual_filters(
            q.get("id", ""), q.get("book", ""), ch))
    return _ok(filters=_f.visual_filters())


@endpoint("bible/filtered")
def _bible_filtered(parts, q):
    from ... import filters as _f
    refs = q.get("refs", [])
    if isinstance(refs, str):
        try:
            refs = _j.loads(refs)
        except Exception:  # noqa: BLE001
            refs = [r.strip() for r in refs.split(";") if r.strip()]
    return _ok(**_f.filtered_reading(q.get("id", ""), refs or []))



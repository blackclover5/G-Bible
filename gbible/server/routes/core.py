from .common import *

# ---------------------------------------------------------------------- meta
@endpoint("status")
def _status(parts, q):
    conn = db.connect()
    n = conn.execute("SELECT COUNT(*) c FROM module WHERE installed_at>0"
                     ).fetchone()["c"]
    from ... import posindex
    return _ok(**store.installed_summary(), database=str(db.db_path()),
               version=VERSION, api_summary=apireg.summary(),
               index=posindex.brief())


@endpoint("taxonomy")
def _taxonomy(parts, q):
    return _ok(
        types=[{"id": t.id, "label": t.label, "group": t.group,
                "reader": t.reader, "index_types": list(taxonomy.index_types_for(t.id))}
               for t in taxonomy.TYPES],
        subjects=taxonomy.SUBJECTS,
        index_types=taxonomy.INDEX_TYPES,
        languages=taxonomy.language_options(),
        licenses=taxonomy.LICENSES,
        reader_kinds=["verse", "article", "book", "date", "image", "topic"],
    )


@endpoint("books")
def _books(parts, q):
    scheme = q.get("scheme", "KJV")
    out = []
    for b in canon.books_for(scheme):
        vc = canon.verse_counts(scheme, b.osis)
        if not vc:
            continue
        out.append({"osis": b.osis, "name": b.name, "short": b.short,
                    "group": b.group, "chapters": len(vc),
                    "verses": sum(vc),
                    "abbrevs": list(b.abbrevs)[:10]})
    return _ok(books=out, scheme=scheme)


# ----------------------------------------------------------------------- ai
# AI assistant. Retrieval-grounded chat over the local library, with the
# provider chosen by the reader (local Ollama or a cloud one).
def _ai_context(q: dict) -> dict:
    """The passage the reader put in front of the assistant, if any.

    It arrives as flat fields rather than a nested object, because a form
    post and a query string both carry it more easily that way.
    """
    text = (q.get("context_text") or "").strip()
    if not text:
        return {}
    return {
        "text": text,
        "label": (q.get("context_label") or "").strip(),
        "module_id": (q.get("context_module_id") or "").strip(),
        "module_name": (q.get("context_module_name") or "").strip(),
        "key": (q.get("context_key") or "").strip(),
    }


@endpoint("ai/providers")
def _ai_providers(parts, q):
    return _ok(providers=ai.providers_view(),
               settings=ai.get_settings(),
               # How much of the reader's own material there is to cite.  The
               # settings screen shows it, because a switch that says "include
               # my own material" and then quietly includes nothing is a lie
               # told by omission.
               mine=mine.count(),
               summary={"total": len(ai.PROVIDERS),
                        "local": sum(1 for p in ai.PROVIDERS if p.local),
                        "free": sum(1 for p in ai.PROVIDERS if p.free)})


@endpoint("ai/settings")
def _ai_settings(parts, q):
    if q:
        return _ok(settings=ai.set_settings(
            provider=q.get("provider"), model=q.get("model"),
            use_library=(_flag(q.get("use_library"))
                         if "use_library" in q else None),
            use_mine=(_flag(q.get("use_mine"))
                      if "use_mine" in q else None),
            scope=q.get("scope") if "scope" in q else None,
            semantic=(_flag(q.get("semantic"))
                      if "semantic" in q else None),
            smart_query=(_flag(q.get("smart_query"))
                         if "smart_query" in q else None),
            max_sources=q.get("max_sources")))
    return _ok(settings=ai.get_settings())


@endpoint("ai/scope")
def _ai_scope(parts, q):
    """The scopes the library can be narrowed to.

    A scope is the reader's *intent* -- "the commentary collection" -- and
    not the list of modules it resolves to, so a book added to a collection
    is included the moment it is added.
    """
    return _ok(scopes=ai.scope_options(), scope=ai.get_settings().get("scope", ""))


@endpoint("ai/chats")
def _ai_chats(parts, q):
    """The conversations the reader has had with the assistant.

    A local record, like the usage log: it stays on this machine and is never
    sent anywhere.  `action` is open, rename, delete or get; without one it
    lists them.
    """
    action = (q.get("action") or "").strip()
    try:
        if action == "open":
            cid = (q.get("id") or "").strip()
            chat = (aichat.latest() if cid in ("", "latest")
                    else aichat.get(cid))
            if not chat:
                return {"ok": False, "error": "No such conversation."}
            return _ok(chat=chat)
        if action == "rename":
            return aichat.rename(q.get("id", ""), q.get("title", ""))
        if action == "delete":
            return _ok(ok=True, removed=aichat.remove(q.get("id", "")))
        if action == "save":
            saved = aichat.save(q.get("id", ""), q.get("turns") or [],
                                q.get("title", ""))
            return _ok(ok=True, chat=saved)
        return _ok(chats=aichat.listing(int(q.get("limit") or aichat.RECENT)))
    except Exception as e:                              # noqa: BLE001
        return _ai_error(e)


@endpoint("ai/chat")
def _ai_chat(parts, q):
    try:
        return ai.chat(
            question=q.get("question", ""),
            history=q.get("history") or [],
            provider_id=q.get("provider") or None,
            model=q.get("model") or None,
            use_library=(_flag(q["use_library"])
                         if "use_library" in q else None),
            use_mine=(_flag(q["use_mine"]) if "use_mine" in q else None),
            scope=q.get("scope") if "scope" in q else None,
            semantic=(_flag(q.get("semantic"))
                      if "semantic" in q else None),
            smart_query=(_flag(q.get("smart_query"))
                         if "smart_query" in q else None),
            context=_ai_context(q),
            max_sources=int(q["max_sources"]) if q.get("max_sources") else None,
        )
    except ai.AiError as e:
        return _ai_error(e)
    except Exception as e:                              # noqa: BLE001
        return _ai_error(e)


@endpoint("ai/key")
def _ai_key(parts, q):
    """Store or clear the API key for a provider (0600 file, beside the DB)."""
    pid = q.get("provider", "")
    if not any(p.id == pid for p in ai.PROVIDERS):
        return {"ok": False, "error": f"no such provider: {pid}"}
    ai.set_key(pid, q.get("key", ""))
    return _ok(provider=pid, key_set=bool(q.get("key", "").strip()))


@endpoint("ai/models")
def _ai_models(parts, q):
    """List a provider's models and, in the same call, whether it is reachable.

    One request answers both the Test button and the model picker, because they
    are the same question asked twice, and asking it twice would mean two round
    trips to a local server that may not be up.
    """
    return ai.probe(q.get("provider") or None,
                    timeout=int(q.get("timeout") or 8))


@endpoint("ai/action")
def _ai_action(parts, q):
    """Explain, summarise or translate one selection (whole answer at once)."""
    try:
        return ai.run_action(
            kind=q.get("action", ""),
            text=q.get("text", ""),
            label=q.get("label", ""),
            target=q.get("target", ""),
            provider_id=q.get("provider") or None,
            model=q.get("model") or None,
            use_library=(_flag(q["use_library"]) if "use_library" in q else None),
            use_mine=(_flag(q["use_mine"]) if "use_mine" in q else None),
            scope=q.get("scope") if "scope" in q else None,
            semantic=(_flag(q.get("semantic"))
                      if "semantic" in q else None),
            smart_query=(_flag(q.get("smart_query"))
                         if "smart_query" in q else None),
            max_sources=int(q["max_sources"]) if q.get("max_sources") else None,
        )
    except ai.AiError as e:
        return _ai_error(e)
    except Exception as e:                              # noqa: BLE001
        return _ai_error(e)


@endpoint("ai/smart-search")
def _ai_smart_search(parts, q):
    """A plain-English question in, one search query out.

    Separate from `ai/chat` on purpose: this returns a *query* for the reader's
    own engine rather than an answer, because the engine recalls and the reader
    can edit what came back.
    """
    try:
        return ai.smart_search(q.get("q", "") or q.get("question", ""),
                               provider_id=q.get("provider") or None,
                               model=q.get("model") or None)
    except ai.AiError as e:
        return _ai_error(e)
    except Exception as e:                              # noqa: BLE001
        return _ai_error(e)


@endpoint("ai/sermon")
def _ai_sermon(parts, q):
    """Sermon research -- outline, illustration or exposition -- in one shot.

    The streaming endpoint serves the same request (see `_serve_ai_stream`); this
    one exists for callers that want the whole note at once, and for tests.
    """
    try:
        return ai.run_sermon(
            kind=q.get("action", "") or q.get("kind", ""),
            ref=q.get("ref", ""),
            theme=q.get("theme", ""),
            provider_id=q.get("provider") or None,
            model=q.get("model") or None,
            use_library=(_flag(q["use_library"]) if "use_library" in q else None),
            max_sources=int(q["max_sources"]) if q.get("max_sources") else None,
        )
    except ai.AiError as e:
        return _ai_error(e)
    except Exception as e:                              # noqa: BLE001
        return _ai_error(e)


@endpoint("ai/topic")
def _ai_topic(parts, q):
    """One question about a topic, answered from the topic guide's own material.

    The streaming endpoint serves the same request (see `_serve_ai_stream`); this
    one exists for callers that want the whole answer at once, and for tests.
    """
    try:
        return ai.run_topic(
            topic=q.get("topic", ""),
            question=q.get("question", "") or q.get("q", ""),
            provider_id=q.get("provider") or None,
            model=q.get("model") or None,
            max_sources=int(q["max_sources"]) if q.get("max_sources") else None,
        )
    except ai.AiError as e:
        return _ai_error(e)
    except Exception as e:                              # noqa: BLE001
        return _ai_error(e)


@endpoint("ai/topic-questions")
def _ai_topic_questions(parts, q):
    """The questions a topic guide should offer.

    A separate call from the answer, and a small one: the questions are four
    short lines, and a reader should not have to wait for an overview to
    finish before they can see what they might ask about.  The question the
    reader then clicks is answered by the ordinary topic call, grounded in the
    same material these were written from.
    """
    try:
        return ai.topic_questions(
            topic=q.get("topic", ""),
            provider_id=q.get("provider") or None,
            model=q.get("model") or None,
            max_sources=int(q["max_sources"]) if q.get("max_sources") else None,
        )
    except ai.AiError as e:
        return _ai_error(e)
    except Exception as e:                              # noqa: BLE001
        return _ai_error(e)


@endpoint("ai/fact-questions")
def _ai_fact_questions(parts, q):
    """The questions the fact book should offer, and a one-line answer each.

    The lens is the reader's question of the term, and it changes the
    questions: the theological lens asks about doctrine and the counseling
    lens about people, the way a topic guide does.
    """
    try:
        return ai.fact_questions(
            term=q.get("term", ""),
            lens=q.get("lens", "") or "",
            provider_id=q.get("provider") or None,
            model=q.get("model") or None,
            max_sources=int(q["max_sources"]) if q.get("max_sources") else None,
        )
    except ai.AiError as e:
        return _ai_error(e)
    except Exception as e:                              # noqa: BLE001
        return _ai_error(e)


@endpoint("ai/chat-export")
def _ai_chat_export(parts, q):
    """The conversation as a Markdown document.

    A file, not a link.  A link would put the conversation in a URL, where it
    is copied into browser history and the URL bar and anywhere a link is
    pasted -- and the conversation is the reader's own writing.  A file the
    reader attaches to an email themselves is a share they chose.
    """
    try:
        turns = q.get("turns") or []
        md = aichat.export_markdown(turns, q.get("title", ""))
        return _ok(ok=True, markdown=md,
                    filename=aichat.export_filename(q.get("title", "")))
    except Exception as e:                              # noqa: BLE001
        return _ai_error(e)


@endpoint("ai/usage")
def _ai_usage(parts, q):
    """What the AI calls have been, so a cloud bill is never a surprise.

    `days` bounds the window; `reset` clears the record.  Nothing here contacts
    a provider -- the numbers are the ones the provider itself reported as the
    answers streamed in, written down at the time.
    """
    if _flag(q.get("reset")):
        return ai.reset_usage()
    return ai.usage_summary(int(q.get("days") or 30))


# ------------------------------------------------------------------ library
@endpoint("library")
def _library(parts, q):
    mods = library.list_all(
        type_=q.get("type"), lang=q.get("lang"), source=q.get("source"),
        search=q.get("q"), installed_only=q.get("installed_only", True),
        subject=q.get("subject"),
        order=q.get("order", "priority DESC, name ASC"))
    out = []
    for m in mods:
        d = {
            "id": m.id, "name": m.name, "abbrev": m.abbrev, "type": m.type,
            "type_label": taxonomy.TYPE_BY_ID[m.type].label
            if m.type in taxonomy.TYPE_BY_ID else m.type,
            "subject": m.subject, "lang": m.lang, "lang_name": m.lang_name,
            "version": m.version, "source": m.source,
            "source_name": m.source_name, "source_url": m.source_url,
            "license": m.license, "rights": m.rights, "author": m.author,
            "year": m.year, "format": m.format, "description": m.description,
            "about": m.about, "size_bytes": m.size_bytes,
            "size_label": store.human_size(m.size_bytes),
            "installed_at": m.installed_at, "v11n": m.v11n,
            "v11n_source": m.v11n_source, "units": m.entries,
            "chapters": m.chapters, "verses": m.verses,
            "has_strongs": m.has_strongs, "has_morph": m.has_morph,
            "has_notes": m.has_notes, "has_xref": m.has_xref,
            "has_redletter": m.has_redletter,
            "index_types": m.index_types or list(taxonomy.index_types_for(m.type)),
            "reader": m.reader, "priority": m.priority, "favorite": m.favorite,
            "error": m.error,
            # A property, not a column, so it is absent from the SELECT * and
            # was never sent.  app.js uses it to find a Bible to follow a cross
            # reference into, so with it missing "open this verse anywhere"
            # silently found nothing.
            "is_bible": m.is_bible,
        }
        out.append(d)
    return _ok(modules=out, total=len(out),
               links=library.link_map() if q.get("links") else None)


@endpoint("library/module")
def _library_module(parts, q):
    mid = q.get("id") or (parts[2] if len(parts) > 2 else "")
    m = library.get(mid)
    if not m:
        return {"ok": False, "error": "not installed"}
    conn = db.connect()
    v11n = {}
    for r in conn.execute("SELECT book, chapters FROM versification WHERE module_id=?",
                          (mid,)):
        try:
            v11n[r["book"]] = json.loads(r["chapters"])
        except json.JSONDecodeError:
            pass
    return _ok(module={
        "id": m.id, "name": m.name, "type": m.type, "lang": m.lang,
        "abbrev": m.abbrev, "license": m.license, "rights": m.rights,
        "author": m.author, "description": m.description, "about": m.about,
        "source": m.source, "source_name": m.source_name,
        "source_url": m.source_url, "format": m.format, "year": m.year,
        "version": m.version, "size_label": store.human_size(m.size_bytes),
        "v11n": m.v11n, "v11n_source": m.v11n_source,
        "index_types": m.index_types or list(taxonomy.index_types_for(m.type)),
        "reader": m.reader, "has_strongs": m.has_strongs,
        "has_morph": m.has_morph, "has_notes": m.has_notes,
        "has_xref": m.has_xref, "has_redletter": m.has_redletter,
        "units": m.entries, "subject": m.subject,
    }, versification=v11n,
        linkable=library.link_map().get(mid, []))


@endpoint("library/remove")
def _library_remove(parts, q):
    return library.remove_module(q.get("id", ""))


@endpoint("library/priority")
def _library_priority(parts, q):
    library.set_priority(q.get("id", ""), int(q.get("value") or 0))
    library.set_favorite(q.get("id", ""), bool(q.get("favorite")))
    return _ok(id=q.get("id"))


@endpoint("library/attribution")
def _attribution(parts, q):
    return _ok(entries=library.attributions())


@endpoint("library/outline")
def _outline(parts, q):
    m = library.get(q.get("id", ""))
    if not m:
        return {"ok": False, "error": "not installed"}
    if m.reader == "verse":
        return _ok(kind="chapters", books=library.chapter_list(m))
    if m.reader == "date":
        return _ok(kind="dates", dates=library.date_list(m))
    return _ok(kind="sections", sections=library.outline(m)[:4000])


# -------------------------------------------------------------------- read
@endpoint("read")
def _read(parts, q):
    mid = q.get("id") or ""
    if not mid:
        return {"ok": False, "error": "no module"}
    cursor = _obj(q.get("cursor"), {}) or {}
    opts = _obj(q.get("options"), {}) or {}
    c = library.read(mid, cursor, opts, span=q.get("span", "chapter"),
                     context=int(q.get("context") or 0))
    out = {k: v for k, v in c.__dict__.items() if k != "items"}
    out["items"] = [_item_dict(i) for i in c.items]
    return _ok(**out, module={
        "id": mid, "name": c.module_name, "reader": c.kind,
        "type": library.get(mid).type if library.get(mid) else "",
    })


@endpoint("article/index")
def _article_index(parts, q):
    """The contents page of an article-keyed resource.

    Lexicons, dictionaries, encyclopaedias and concordances are navigated by
    key, and there was no way to see what keys exist -- the only route was
    typing something you already knew was in there, which is not navigation.
    """
    m = library.get(q.get("id", ""))
    if m is None or not m.installed_at:
        return {"ok": False, "error": "not installed"}
    return _ok(**library.article_index(m, q.get("bucket", ""),
                                       limit=int(q.get("limit") or 400)))


@endpoint("read/around")
def _read_around(parts, q):
    """Verse-window navigation: next / prev / chapter / book."""
    mid = q.get("id", "")
    m = library.get(mid)
    if not m:
        return {"ok": False, "error": "not installed"}
    cur = q.get("ref") or ""
    rr = canon.parse_ref(cur, m.v11n)
    if rr is None:
        rr = canon.parse_ref("Gen 1", m.v11n)
    r = rr.start
    act = q.get("action", "next")
    if act == "next":
        n = canon.next_ref(r, m.v11n)
    elif act == "prev":
        n = canon.prev_ref(r, m.v11n)
    elif act == "nextchapter":
        n = canon.next_chapter(r, m.v11n)
    elif act == "prevchapter":
        n = canon.prev_chapter(r, m.v11n)
    elif act == "nextbook":
        n = canon.next_book(r, m.v11n)
    elif act == "prevbook":
        n = canon.prev_book(r, m.v11n)
    elif act == "verse":
        n = canon.Ref(r.book, r.chapter, r.verse + 1)
    else:
        n = r
    return _ok(ref=canon.format_ref(n),
               key=workspace.nearest_verse(mid, canon.format_ref(n)))


@endpoint("unit")
def _unit(parts, q):
    """One unit verbatim -- used by the verse popup."""
    conn = db.connect()
    r = conn.execute("SELECT * FROM unit WHERE module_id=? AND key=?",
                     (q.get("id", ""), q.get("key", ""))).fetchone()
    if not r:
        return {"ok": False, "error": "not found"}
    item = library._mk_item(r, library._opts(q.get("options")))
    return _ok(item={"key": item.key, "label": item.label, "title": item.title,
                     "text": item.text, "html": item.html})


@endpoint("strongs")
def _strongs(parts, q):
    """Strong's / lemma lookup -- the lexicon pane's whole job."""
    conn = db.connect()
    num = canon.normalise_strongs(q.get("number", ""))
    if not num:
        return {"ok": False, "error": "no Strong's number"}
    r = conn.execute("SELECT * FROM strongs WHERE strongs=?", (num,)).fetchone()
    try:
        mods = json.loads((r["modules"] if r else "") or "[]")
    except (json.JSONDecodeError, TypeError):
        # the roll-up is a JSON array of module ids; a malformed entry must not
        # take the whole lookup down
        mods = [x.strip().strip('"') for x in
                (r["modules"] if r else "").split(",") if x.strip().strip('"')]
    mods = [m for m in mods if library.get(m)]
    names = [library.get(m).name for m in mods]
    occurrences = []
    if mods:
        occurrences = [dict(x) for x in conn.execute(
            "SELECT module_id, unit_key, surface FROM marker "
            "WHERE kind='strongs' AND value=? AND module_id IN "
            f"({','.join('?' * len(mods))}) LIMIT 300", [num, *mods])]
    return _ok(strongs=num, word=(r["word"] if r else "") or "",
               lemma=(r["lemma"] if r else "") or "",
               count=(r["count"] if r else 0), modules=names,
               occurrences=occurrences,
               prefix=num[0], gloss=gloss_for(num))


@endpoint("study/verse")
def _study_verse(parts, q):
    """Everything installed that bears on one verse, in a single call.

    The panel needs commentaries, cross-references, topics, places and the
    word list at once; asking for them one endpoint at a time is five round
    trips and a visibly slower panel.
    """
    mid = q.get("id") or ""
    key = q.get("key") or ""
    if not mid or not key:
        return {"ok": False, "error": "need id and key"}
    return study.verse_bundle(mid, key)


@endpoint("study/word")
def _study_word(parts, q):
    """Everything installed that bears on one Strong's number."""
    return study.word_bundle(q.get("number", ""),
                             module_ids=[x for x in (q.get("modules") or "").split(",")
                                         if x] or None)


@endpoint("study/topic")
def _study_topic(parts, q):
    """Every installed resource on one topic, gathered under one heading."""
    return study.topic_guide(q.get("q", ""),
                             per_section=int(q.get("n") or 6))


@endpoint("study/wordfind")
def _study_wordfind(parts, q):
    """Build a word-find puzzle from text you supply or from a passage."""
    text = q.get("text") or ""
    if not text and q.get("ref"):
        g = study.passage_guide(q.get("ref"))
        if not g.get("ok"):
            return g
        text = " ".join(t["text"] for t in g.get("texts") or [])
    r = wordfind.make(text, size=q.get("size", 14), seed=q.get("seed"))
    if r.get("ok") and not q.get("reveal"):
        r.pop("answer", None)
    return r


@endpoint("study/pronounce")
def _study_pronounce(parts, q):
    """Say a Greek or Hebrew word in Latin letters."""
    return canon.transliterate(q.get("word", ""))


@endpoint("study/gematria")
def _study_gematria(parts, q):
    """Numeric value of a Hebrew word (mispar hechri)."""
    return canon.gematria(q.get("word", ""))


@endpoint("study/passage")
def _study_passage(parts, q):
    """Everything known about a passage, in one place."""
    return study.passage_guide(q.get("ref", ""))


@endpoint("study/tags")
def _study_tags(parts, q):
    """Which words in this text the fact books have a meaning for."""
    text = q.get("text", "")
    if len(text) > 20000:
        text = text[:20000]
    return {"ok": True, "tags": study.fact_tags(text, limit=int(q.get("n") or 40)),
            "indexed": len(study.tag_index())}


@endpoint("study/fact")
def _study_fact(parts, q):
    """The fact-book entries on one term, sorted into name, place and article."""
    return study.fact_guide(q.get("q", ""),
                            per_section=int(q.get("n") or 8),
                            lens=q.get("lens", ""))


@endpoint("compare")
def _compare(parts, q):
    """The same verse in several translations, side by side."""
    ids = [x for x in (q.get("modules") or "").split(",") if x]
    if not ids:
        ids = [m.id for m in library.list_all()
               if m.type == "Bible" and m.lang == "eng"][:6]
    return study.compare(q.get("ref", ""), ids)


@endpoint("readingplan")
def _readingplan(parts, q):
    """A day's reading from the installed devotionals.

    Devotional modules are keyed by date, so a reading plan is already in the
    library -- it only needed somewhere to be read from.
    """
    conn = db.connect()
    day = (q.get("day") or "").strip()
    if not day:
        today = time.localtime()
        day = f"{today.tm_mon:02d}.{today.tm_mday:02d}"
    out = []
    for m in library.list_all():
        if m.type != "Devotional":
            continue
        row = conn.execute(
            "SELECT key, title, text FROM unit WHERE module_id=? AND key=?",
            (m.id, day)).fetchone()
        if row is None or not (row["text"] or "").strip():
            continue
        out.append({"module_id": m.id, "module": m.name, "day": day,
                    "key": row["key"], "title": row["title"] or day,
                    "text": row["text"][:6000]})
    if not out:
        return {"ok": False, "error": f"no devotional for {day}"}
    return _ok(day=day, readings=out)


@endpoint("readingplan/plans")
def _rp_plans(parts, q):
    """Every plan this library can offer, with its length."""
    return _ok(plans=readingplan.plans(),
               progress=readingplan.progress())


@endpoint("readingplan/day")
def _rp_day(parts, q):
    """One day of a plan.  Day 0 is the first day not yet marked."""
    plan = q.get("plan", "")
    n = int(q.get("day") or 0)
    return readingplan.day(plan, n)


@endpoint("readingplan/overview")
def _rp_overview(parts, q):
    """The whole plan as a list, so its shape is visible."""
    return readingplan.overview(q.get("plan", ""))


@endpoint("readingplan/mark")
def _rp_mark(parts, q):
    """Mark a day read or unread."""
    plan = q.get("plan", "")
    n = int(q.get("day") or 0)
    done = str(q.get("done", "1")).lower() not in ("0", "false", "no")
    if not plan:
        return {"ok": False, "error": "which plan?"}
    return _ok(**readingplan.set_progress(plan, n, done))


@endpoint("readingplan/clear")
def _rp_clear(parts, q):
    return _ok(**readingplan.clear_progress(q.get("plan", "")))


@endpoint("readingplan/create")
def _rp_create(parts, q):
    import json as _j
    refs = q.get("refs", [])
    if isinstance(refs, str):
        try:
            refs = _j.loads(refs)
        except Exception:  # noqa: BLE001
            refs = []
    return _ok(**readingplan.save_custom_plan(q.get("name", ""), refs))


@endpoint("readingplan/delete")
def _rp_delete(parts, q):
    return _ok(**readingplan.delete_custom_plan(q.get("name", "")))


@endpoint("timeline/spans")
def _timeline_spans(parts, q):
    """The chronology as a number line, for drawing."""
    return timeline.spans()


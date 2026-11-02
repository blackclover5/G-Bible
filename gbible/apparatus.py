"""A fuller collation across installed editions — not an apparatus.

What a critical apparatus does (manuscript witnesses, sigla, editorial
judgement) cannot be computed from translations. What *can* be computed,
honestly, is:

* every installed edition's rendering of a verse — translations *and*
  source-language texts (OriginalLanguage, Manuscript), labelled by language
  so a Greek difference is never mistaken for an English variant;
* word-level disagreement across them, reusing merge's alignment;
* a chapter scan ranking verses by how much the editions part company.

Differences across languages are translation, not textual variation, and the
responses say so.
"""

from __future__ import annotations

from . import canon, db, library


def _editions() -> list:
    return [m for m in library.list_all()
            if m.type in library.VERSE_TEXT_TYPES
            and m.installed_at]


def editions_at(book: str, chapter: int, verse: int) -> list[dict]:
    conn = db.connect()
    out = []
    for m in _editions():
        r = conn.execute("SELECT text FROM unit WHERE module_id=? AND book=? "
                         "AND chapter=? AND verse=? LIMIT 1",
                         (m.id, book, chapter, verse)).fetchone()
        if r is None or not (r["text"] or "").strip():
            continue
        out.append({"module_id": m.id, "name": m.name,
                    "abbrev": m.abbrev or "", "type": m.type,
                    "lang": m.lang or "", "text": r["text"].strip()})
    return out


_LANG_FAMILY = {
    "eng": "English", "enm": "English", "ang": "English",
    "grc": "Greek", "gr": "Greek", "ell": "Greek",
    "hbo": "Hebrew", "heb": "Hebrew", "he": "Hebrew", "arc": "Aramaic",
    "lat": "Latin", "fra": "French", "spa": "Spanish", "ita": "Italian",
    "por": "Portuguese", "ron": "Romanian",
    "deu": "German", "nld": "Dutch", "swe": "Swedish", "nor": "Norwegian",
    "dan": "Danish",
    "bul": "Slavic", "rus": "Slavic", "srp": "Slavic", "hrv": "Slavic",
    "ces": "Slavic", "pol": "Slavic", "ukr": "Slavic",
    "ara": "Arabic", "arb": "Arabic",
    "zho": "Chinese", "chi": "Chinese", "cmn": "Chinese",
    "jpn": "Japanese", "kor": "Korean", "vie": "Vietnamese",
    "tha": "Thai", "hin": "Indic", "tam": "Indic", "mal": "Indic",
    "hun": "Other", "eus": "Other", "sqi": "Other", "tur": "Other",
}


def language_family(lang: str) -> str:
    return _LANG_FAMILY.get((lang or "").lower(), "Other")


#: Languages with more than one independent *textual witness* installed, which
#: is what makes "do these disagree" a question about the text rather than about
#: translation style.  Two English translations never agree word for word, so
#: scoring them together produces a number that means nothing.
WITNESS_FAMILIES = ("Greek", "Hebrew", "Aramaic")


def missing_at(book: str, chapter: int, verse: int) -> list[dict]:
    """Installed text editions with no text at this verse — a gap is data."""
    have = {e["module_id"] for e in editions_at(book, chapter, verse)}
    return [{"module_id": m.id, "name": m.name, "type": m.type}
            for m in _editions() if m.id not in have]


def collate(ref: str, module_ids: list[str] | None = None) -> dict:
    """Word-level disagreement across editions at one verse.

    **Aligned within a language, not across all of them.**  One alignment over
    every edition produced a single "agreement" figure for John 3:16 -- 93.3% --
    across Basque, Bulgarian, Chinese, Thai, Russian and English at once.  That
    number is not a measurement of anything: it is dominated by the fact that
    translations of the same verse are not translations *of each other*, and it
    obscured the two comparisons a reader of a critical text actually wants,
    Greek against Greek and Hebrew against Hebrew.  Each family is now aligned
    on its own and reports its own figure, and a top-level number is given only
    when there is exactly one family to speak for -- otherwise it is left null
    rather than invented.

    **All installed verse texts are aligned, not only the ones typed `Bible`.**
    The old code filtered to `type == "Bible"` before diffing and then reported
    every other edition's text beside the result, so SBLGNT and the Aleppo
    Codex were displayed but never took part in the comparison.
    """
    from . import merge as _merge
    rr = canon.parse_ref(ref)
    if rr is None:
        return {"ok": False, "error": f"Cannot read {ref!r}"}
    f = next(iter(rr.refs()))
    eds = editions_at(f.book, f.chapter or 0, f.verse or 1)
    if module_ids:
        want = set(module_ids)
        eds = [e for e in eds if e["module_id"] in want]
    if len(eds) < 2:
        return {"ok": False,
                "error": "Need two or more installed editions with text "
                         "at that verse"}
    families: dict[str, list] = {}
    for e in eds:
        families.setdefault(language_family(e["lang"]), []).append(e)

    compared: list[dict] = []
    for fam, group in sorted(families.items()):
        if len(group) < 2:
            compared.append({"family": fam, "editions": group,
                             "agreement": None, "variants": None,
                             "words": None, "columns": [],
                             "note": "only one edition installed in this "
                                     "language, so there is nothing to "
                                     "compare it with"})
            continue
        d = _merge.diff(ref, [e["module_id"] for e in group])
        compared.append({
            "family": fam, "editions": group,
            "agreement": d.get("agreement"),
            "variants": d.get("variants"),
            "words": d.get("words"),
            "columns": d.get("columns") or [],
            "note": "",
        })
    scored = [c for c in compared if c["agreement"] is not None]
    # Only speak for the whole set when one family is the whole set.  Picking
    # the "largest" and labelling it as the overall figure would be inventing a
    # number that nobody measured.
    single = scored[0] if len(scored) == 1 else None
    langs = sorted({e["lang"] for e in eds if e["lang"]})
    note = ""
    if len(langs) > 1:
        note += ("Editions are grouped by language and aligned within each "
                 "group: a difference between two translations is translation, "
                 "not textual variation, and one figure across all of them "
                 "measures nothing. ")
    note += ("Word alignment is difflib over words — a reading aid, "
             "not an apparatus.")
    return {"ok": True, "ref": ref, "editions": eds,
            "agreement": single["agreement"] if single else None,
            "variants": single["variants"] if single else None,
            "words": single["words"] if single else None,
            "columns": single["columns"] if single else [],
            "families": compared,
            "missing": missing_at(f.book, f.chapter or 0, f.verse or 1),
            "note": note}


def collate_chapter(book: str, chapter: int) -> dict:
    """Rank a chapter's verses by how much installed editions disagree.

    Cheap agreement: group editions by normalised text; the largest group
    over the total is the agreement. No alignment is run per verse — the
    scan stays a scan.

    **Counted within a language, and only across witnesses.**  Two corrections
    in one, because grouping all editions together measured nothing: no two
    translations of a verse render it in the same words, so every verse scored
    near 0% and the ranking was decided by language coverage rather than by any
    disagreement.  Restricted to one language it is still 12.5% for eight
    English versions, which measures translation style, not textual variation --
    two English translations agreeing word-for-word is not what "the witnesses
    agree" means.  So a verse is scored by the source languages where independent
    textual witnesses actually exist and can disagree: Greek and Hebrew, where
    Textus Receptus against SBLGNT and the Aleppo against the Leningrad codices
    are real comparisons.  Translations are counted and reported but never
    ranked, and a verse with no witness pair is left out rather than presented as
    total disagreement.
    """
    import re as _re
    b = canon.lookup_book((book or "").strip())
    if b is None:
        return {"ok": False, "error": f"Cannot read {book!r} as a book"}
    conn = db.connect()
    verses = [r["verse"] for r in conn.execute(
        "SELECT DISTINCT verse FROM unit WHERE book=? AND chapter=? "
        "AND verse>0 ORDER BY verse", (b.osis, chapter)).fetchall()]
    mods = _editions()
    rows = []
    for v in verses:
        by_fam: dict[str, list] = {}
        translations = 0
        for m in mods:
            r = conn.execute("SELECT text FROM unit WHERE module_id=? "
                             "AND book=? AND chapter=? AND verse=? LIMIT 1",
                             (m.id, b.osis, chapter, v)).fetchone()
            if r is None or not (r["text"] or "").strip():
                continue
            fam = language_family(m.lang)
            if fam not in WITNESS_FAMILIES:
                translations += 1
                continue
            norm = _re.sub(r"\s+", " ", r["text"].strip().lower())
            by_fam.setdefault(fam, []).append((m.id, m.name, norm))
        scored = []
        for fam, texts in by_fam.items():
            if len(texts) < 2:
                continue
            groups: dict[str, list] = {}
            for _mid, name, norm in texts:
                groups.setdefault(norm, []).append(name)
            biggest = max(len(g) for g in groups.values())
            scored.append({
                "family": fam,
                "editions": len(texts),
                "readings": len(groups),
                "agreement": round(100 * biggest / len(texts), 1),
                "witnesses": sorted({n for g in groups.values() for n in g}),
            })
        if not scored:
            continue
        worst = min(scored, key=lambda s: (s["agreement"], -s["editions"]))
        rows.append({"verse": v, "ref": f"{b.name} {chapter}:{v}",
                     "family": worst["family"],
                     "families_compared": len(scored),
                     "editions": worst["editions"],
                     "readings": worst["readings"],
                     "agreement": worst["agreement"],
                     "translations_available": translations,
                     "witnesses": worst["witnesses"]})
    rows.sort(key=lambda r: (r["agreement"], -r["editions"]))
    return {"ok": True, "book": b.name, "chapter": chapter,
            "verses": rows, "count": len(rows),
            "note": "Agreement is identical normalised renderings between "
                    "witnesses in one source language, so it measures textual "
                    "variation rather than translation style. Translations "
                    "installed are counted but not ranked; a verse with fewer "
                    "than two witnesses in a source language is not listed."}

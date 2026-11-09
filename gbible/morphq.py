"""Query the morphology properly, by decoding it rather than pattern-matching.

Morph Search as it stands finds every tag that starts with a given string, which
is useful but blunt: you can type `HNcms` and get common masculine singular
nouns, but there is no way to say "every perfect verb that is not qal, in the
third person" without knowing where in the code each feature sits.

There are only about 4,300 distinct codes installed, so rather than guess at
positions this decodes every one of them into its features, filters the features
you asked for, and counts the matches.  A mis-guessed wildcard would silently
return the wrong words; a decoder is checked once, against the codes themselves.

The three tagging schemes installed are Robinson codes in the three flavours
they come in:

    HNcmsa        H + noun, common, masculine, singular, absolute
    HNp           noun, plural (no gender given)
    HVqw3ms       verb, qal, wayyiqtol, 3rd person masculine singular
    HC/Vqw3ms     conjunction followed by a verb -- a particle then the head
    HR/Ncmsc      preposition followed by a noun
    HTd/Ncmsa     article marked as direct object, then the noun

So a code is one or more components joined by "/": the first is a particle and
the last is the head, the word that actually carries the grammatical features.
"""

from __future__ import annotations

import re

from . import db

# ---------------------------------------------------------------- vocabulary
# The codes are a closed vocabulary, so the options can be offered as a list
# rather than as free text.  These are the values that actually occur in the
# installed text; `facets()` reports counts so the UI can show what is there.

NOUNS_GENDER = {"m": "masculine", "f": "feminine", "b": "common (both)"}
NOUNS_NUMBER = {"s": "singular", "p": "plural", "d": "dual"}
NOUNS_STATE = {"a": "absolute", "c": "construct", "e": "emphatic"}

# Verb codes are V + conjugation + tense + [person] + gender + number [+ state].
# The person digit is *optional*: HVqp3ms is "perfect, third, masculine
# singular" and HVqrmsa is the same tense with no person, which means third.
VERBS_CONJ = {
    "q": "qal", "Q": "qutal", "n": "niphal", "N": "naqal", "p": "piel",
    "P": "pual", "h": "hithpael", "H": "hithpael", "m": "maqqef", "M": "maqqef",
    "f": "polal", "F": "polal", "C": "Hithpael", "T": "Tirasha",
}
# Tense, by the letter that carries it.  Recorded as the *category* rather than
# the exact stem form: hatta and yiqtol are both imperfect, and a filter that
# only matched one of them would silently miss half the imperfect verbs.  The
# letter detail is still available as `stem_class`.
VERBS_TENSE = {}
_CATEGORY = {
    "perfect": "pznoqQOiPmM",
    "wayyiqtol": "vrawuRSVWUDN",
    "imperfect": "iytegj xXBGIEhcdklmsbKLAJCTFHYQPf",
}
for _cat, _letters in _CATEGORY.items():
    for _ch in _letters.strip():
        VERBS_TENSE[_ch] = _cat
VERBS_TENSE["T"] = "infinitive (absolute)"
VERBS_TENSE["x"] = "imperfect"
# letter meanings, kept so the letter is not lost, just not used as the category
VERB_LETTERS = dict(VERBS_TENSE)

# Participles carry their own stem marker: Sp1cs is a piel participle, Hncfsa a
# niphal one, Hcbsa a hithpael one.
PARTICIPLE_STEM = {
    "S": "piel participle", "H": "hithpael participle", "C": "polal participle",
    "N": "niphal participle", "M": "hithpael participle", "T": "Tirasha participle",
    "P": "pual participle", "F": "polal participle", "X": "participle",
}

PARTS_OF_SPEECH = {
    "N": "noun", "V": "verb", "T": "article", "R": "preposition",
    "C": "conjunction", "K": "conjunctive particle", "D": "demonstrative",
    "S": "possessive pronoun", "P": "indefinite article", "M": "interrogative",
    "A": "indefinite pronoun", "F": "definite article", "X": "verb prefix",
    "H": "relative particle", "Z": "relative particle", "Y": "relative particle",
    "O": "direct object marker", "Q": "relative particle", "B": "conjunction",
    "L": "relative particle", "W": "relative particle",
}


def parse_code(code: str) -> dict:
    """Decode one morphology code into its grammatical features.

    Anything not recognised comes back as None rather than a guess, so a filter
    on a feature a code does not carry excludes it instead of matching it.

    Two things this gets right that a positional guess does not:

    * The letter after N in a noun is a constant marker, not "common".  הַשָּׁמַיִם
      (heavens) is HNcmpa -- masculine plural absolute -- and רֵאשִׁית
      (beginning) is HR/Ncfsa, feminine singular absolute.  Reading the c as a
      gender left both with no number or state at all.
    * A verb's person digit is optional: HVqp3ms carries one and HVqrmsa does
      not, the second meaning third person.
    """
    raw = (code or "").strip()
    # MACULA/PROIEL Greek tags use a compact, explicit POS + feature code
    # (for example N-NSM, V-AAI-3S, V-PAP-NSM). Decode these before the
    # Hebrew/Robinson parser; treating them as OSHB codes loses every feature.
    greek = re.sub(r"^(?:MACULA|PROIEL):", "", raw, flags=re.I)
    gm = re.fullmatch(r"([A-Z]+)(?:-([A-Z0-9-]+))?", greek.upper())
    if gm and gm.group(1) in {"N", "V", "A", "C", "D", "I", "P", "RA", "RD", "RI", "RP", "RR", "X", "T"}:
        pos, codepart = gm.group(1), gm.group(2) or ""
        f = {"raw": raw, "scheme": "MACULA", "pos": {
            "N":"noun", "V":"verb", "A":"adjective", "C":"conjunction",
            "D":"adverb", "I":"interjection", "P":"preposition",
            "RA":"article", "RD":"demonstrative pronoun", "RI":"interrogative pronoun",
            "RP":"personal pronoun", "RR":"relative pronoun", "X":"particle", "T":"particle"}.get(pos, pos),
            "pos_label":"", "gender":None, "number":None, "case":None,
            "degree":None, "state":None, "conjugation":None, "tense":None,
            "voice":None, "mood":None, "person":None, "participle":None,
            "particles":[], "stem":None}
        names = {"N":"nominative", "G":"genitive", "D":"dative", "A":"accusative", "V":"vocative"}
        gnames = {"M":"masculine", "F":"feminine", "N":"neuter"}
        nums = {"S":"singular", "P":"plural", "D":"dual"}
        if pos in ("N", "A", "RA", "RD", "RI", "RP", "RR"):
            if codepart and codepart[0] in names: f["case"] = names[codepart[0]]
            if len(codepart)>1 and codepart[1] in nums: f["number"] = nums[codepart[1]]
            if len(codepart)>2 and codepart[2] in gnames: f["gender"] = gnames[codepart[2]]
            if pos == "A" and len(codepart)>0 and codepart[0] in {"C","S"}:
                f["degree"] = {"C":"comparative", "S":"superlative"}[codepart[0]]
        elif pos == "V":
            parts = codepart.split("-")
            vm = parts[0] if parts else ""
            f["tense"] = {"P":"present", "I":"imperfect", "F":"future", "A":"aorist", "X":"perfect", "Y":"pluperfect"}.get(vm[:1])
            f["voice"] = {"A":"active", "M":"middle", "P":"passive", "E":"middle/passive"}.get(vm[1:2])
            f["mood"] = {"I":"indicative", "S":"subjunctive", "O":"optative", "M":"imperative", "N":"infinitive", "P":"participle"}.get(vm[2:3])
            tail = parts[-1] if len(parts)>1 else ""
            if f["mood"] == "participle":
                if tail and tail[0] in names: f["case"] = names[tail[0]]
                if len(tail)>1 and tail[1] in nums: f["number"] = nums[tail[1]]
                if len(tail)>2 and tail[2] in gnames: f["gender"] = gnames[tail[2]]
                f["participle"] = "participle"
            else:
                pm = re.match(r"([123])([SDP])", tail)
                if pm:
                    f["person"] = {"1":"first", "2":"second", "3":"third"}[pm.group(1)]
                    f["number"] = nums[pm.group(2)]
        return f
    f: dict = {"raw": raw, "scheme": "", "pos": None, "pos_label": "",
               "gender": None, "number": None, "state": None,
               "conjugation": None, "tense": None, "person": None,
               "participle": None, "particles": [], "stem": None}
    if not raw:
        return f
    if raw.lower().startswith("robinson:"):
        f["scheme"] = "Robinson"
        raw = raw.split(":", 1)[1]
    elif raw.lower().startswith("strongmorph:"):
        f["scheme"] = "strongMorph"
        raw = raw.split(":", 1)[1]
    else:
        f["scheme"] = "OSHB"
    body = raw[1:] if raw[:1].upper() == "H" else raw

    parts = [p for p in body.split("/") if p]
    if not parts:
        return f

    # Which component is the head?  The one that is a noun or a verb.  In
    # HNcmsc/Sp3ms the noun comes first and the participle modifies it, so
    # taking the last component made a noun look like a possessive pronoun; in
    # HR/Ncfsa the noun is last.  Nouns and verbs claim the head, and anything
    # before it is a leading particle.
    head_at = 0
    for i, p in enumerate(parts):
        if p[:1].upper() in ("N", "V"):
            head_at = i
            break
    head = parts[head_at]

    for p in parts[:head_at]:
        if p and p[0].upper() in PARTS_OF_SPEECH and p[0].upper() not in ("N", "V"):
            f["particles"].append(PARTS_OF_SPEECH[p[0].upper()])

    # A component after the head is a participle modifying it, but only if it
    # actually parses as one: HNcmsc/Sp3ms is a noun with a piel participle,
    # while HR/Ncfsa's trailing component is just the head's own tail.
    for p in parts[head_at + 1:]:
        if p[:1] not in PARTICIPLE_STEM:
            continue
        rest = p[1:]
        if rest[:1] not in VERBS_TENSE:
            continue                      # not a participle after all
        f["participle"] = PARTICIPLE_STEM[p[0]]
        f["tense"] = VERBS_TENSE[rest[0]]
        rest = rest[1:]
        if rest[:1] in ("1", "2", "3"):
            f["person"] = {"1": "first", "2": "second", "3": "third"}[rest[0]]
            rest = rest[1:]
        elif rest[:1].lower() in NOUNS_GENDER:
            f["person"] = "third"
        if rest[:1].lower() in NOUNS_GENDER:
            f["gender"] = NOUNS_GENDER[rest[0].lower()]
            rest = rest[1:]
        if rest[:1].lower() in NOUNS_NUMBER:
            f["number"] = NOUNS_NUMBER[rest[0].lower()]
        break

    kind = head[:1].upper()

    if kind == "N":
        f["pos"] = "noun"
        rest = head[1:]
        if rest[:1].lower() == "c":        # the constant marker, not a gender
            rest = rest[1:]
        if rest[:1].lower() in NOUNS_GENDER:
            f["gender"] = NOUNS_GENDER[rest[0].lower()]
            rest = rest[1:]
        if rest[:1].lower() in NOUNS_NUMBER:
            f["number"] = NOUNS_NUMBER[rest[0].lower()]
            rest = rest[1:]
        if rest[:1].lower() in NOUNS_STATE:
            f["state"] = NOUNS_STATE[rest[0].lower()]
            rest = rest[1:]
        f["stem"] = rest or None

    elif kind == "V":
        f["pos"] = "verb"
        rest = head[1:]
        if rest[:1] in VERBS_CONJ:
            f["conjugation"] = VERBS_CONJ[rest[0]]
            rest = rest[1:]
        if rest[:1] in PARTICIPLE_STEM:
            f["participle"] = PARTICIPLE_STEM[rest[0]]
            rest = rest[1:]
        else:
            if rest[:1] in VERBS_TENSE:
                f["tense"] = VERBS_TENSE[rest[0]]
                rest = rest[1:]
            if rest[:1] in ("1", "2", "3"):
                f["person"] = {"1": "first", "2": "second", "3": "third"}[rest[0]]
                rest = rest[1:]
            elif f["tense"] and rest[:1] in NOUNS_GENDER:
                # no person digit: HVqrmsa is a wayyiqtol with an understood third
                f["person"] = "third"
        if rest[:1].lower() in NOUNS_GENDER:
            f["gender"] = NOUNS_GENDER[rest[0].lower()]
            rest = rest[1:]
        if rest[:1].lower() in NOUNS_NUMBER:
            f["number"] = NOUNS_NUMBER[rest[0].lower()]
            rest = rest[1:]
        if rest[:1].lower() in NOUNS_STATE:
            f["state"] = NOUNS_STATE[rest[0].lower()]
            rest = rest[1:]
        f["stem"] = rest or None

    elif kind in PARTS_OF_SPEECH:
        f["pos"] = PARTS_OF_SPEECH[kind]
        f["stem"] = head[1:] or None
    else:
        f["stem"] = head or None
    return f


_FILTERS = ("pos", "gender", "number", "case", "degree", "state", "conjugation", "tense",
            "voice", "mood", "person", "participle", "scheme", "pos_particle")


def query(*, limit: int = 300, offset: int = 0, order: str = "count",
          **filters) -> dict:
    """Morph query: filter the tagging by its grammatical features."""
    want = {}
    for k, v in filters.items():
        if k in _FILTERS and v not in (None, "", "any"):
            want[k] = str(v)
    conn = db.connect()

    scheme_want = want.pop("scheme", None)
    rows = conn.execute(
        "SELECT value AS v, count(*) AS n FROM marker WHERE kind='morph' "
        "GROUP BY value").fetchall()
    codes = []
    for r in rows:
        code = r["v"]
        if scheme_want and not code.lower().startswith(scheme_want.lower()):
            continue
        f = parse_code(code)
        ok = True
        for key, val in want.items():
            if key == "pos_particle":
                if val not in f["particles"]:
                    ok = False
                    break
                continue
            got = f.get(key)
            # "not X" is written as "not:X"
            if val.startswith("not:"):
                if got == val[4:]:
                    ok = False
                    break
                continue
            if got != val:
                ok = False
                break
        if ok:
            codes.append((code, f, r["n"]))

    if order == "code":
        codes.sort(key=lambda x: x[0])
    elif order == "alpha":
        codes.sort(key=lambda x: str(parse_code(x[0]).get("stem") or ""))
    else:
        codes.sort(key=lambda x: -x[2])

    total = sum(c[2] for c in codes)
    page = codes[offset:offset + limit] if limit else codes

    # Samples of the words themselves, so a query shows what it found rather
    # than only how many.
    samples: list[dict] = []
    for code, _f, n in page[:12]:
        s = conn.execute(
            "SELECT m.module_id, m.unit_key, m.surface, u.book, u.chapter, u.verse,"
            " u.ref_label FROM marker m LEFT JOIN unit u"
            " ON u.module_id=m.module_id AND u.key=m.unit_key "
            "WHERE m.kind='morph' AND m.value=? LIMIT 4", (code,)).fetchall()
        for r in s:
            label = ""
            if r["book"]:
                label = f'{r["book"]} {r["chapter"]}:{r["verse"]}'
            samples.append({
                "code": code, "surface": r["surface"] or "",
                "module_id": r["module_id"], "key": r["unit_key"],
                "ref": label,
            })

    return {
        "ok": True,
        "filters": want,
        "codes": len(codes),
        "total": total,
        "offset": offset,
        "next": offset + limit if offset + limit < len(codes) else 0,
        "results": [{"code": c, "count": n, "features": _plain(f)}
                    for c, f, n in page],
        "samples": samples[:60],
    }


def _plain(f: dict) -> dict:
    return {k: v for k, v in f.items() if k != "raw"}


def facets(module_id: str = "") -> dict:
    """What is actually installed, with counts, so the form can be built from
    the data rather than from a guess at the grammar."""
    conn = db.connect()
    sql = "SELECT value AS v, count(*) AS n FROM marker WHERE kind='morph'"
    args = []
    if module_id:
        sql += " AND module_id=?"; args.append(module_id)
    rows = conn.execute(sql + " GROUP BY value", args).fetchall()
    tally: dict[str, dict[str, int]] = {k: {} for k in _FILTERS}
    for r in rows:
        f = parse_code(r["v"])
        n = r["n"]
        for key in _FILTERS:
            val = f.get(key)
            if val:
                tally[key][val] = tally[key].get(val, 0) + n
        for p in f["particles"]:
            tally["pos_particle"][p] = tally["pos_particle"].get(p, 0) + n
    out = {k: [{"value": v, "n": c} for v, c in
               sorted(d.items(), key=lambda x: -x[1])]
           for k, d in tally.items()}
    out["codes"] = len(rows)
    out["total"] = sum(r["n"] for r in rows)
    return out


def suggest_lemmas(module_id: str, prefix: str, *, limit: int = 20) -> dict:
    """Offer only lemma spellings indexed in the chosen tagged resource."""
    prefix = (prefix or "").strip()
    if len(prefix) < 2:
        return {"ok": True, "suggestions": []}
    limit = max(1, min(50, int(limit)))
    rows = db.connect().execute(
        "SELECT value,COUNT(*) AS n FROM marker WHERE module_id=? AND kind='lemma' "
        "AND value LIKE ? GROUP BY value ORDER BY n DESC,value LIMIT ?",
        (module_id, prefix + "%", limit)).fetchall()
    return {"ok": True, "suggestions": [{"lemma":r["value"],"count":r["n"]} for r in rows]}


def search_fields(module_id: str) -> dict:
    """Searchable fields carried by this resource's tagged word markers."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT value,COUNT(*) AS n FROM marker WHERE module_id=? AND kind='field' "
        "GROUP BY value ORDER BY value", (module_id,)).fetchall()
    if not rows:
        # Existing libraries acquire explicit field markers on re-index. Until
        # then, their known morphology markers are all in the verse text.
        n = conn.execute("SELECT COUNT(*) FROM marker WHERE module_id=? AND kind='morph'",
                         (module_id,)).fetchone()[0]
        if n:
            return {"fields": [{"value": "main-text", "label": "Main text", "n": n}]}
    return {"fields": [{"value": r["value"],
                         "label": r["value"].replace("-", " ").title(),
                         "n": r["n"]} for r in rows]}


def wordforms(module_id: str, word: str, *, limit: int = 20) -> dict:
    """Every morphology code carried by one word (lemma or surface) in a module.

    This is the engine behind the Logos-style "type a word, press @, pick the
    grammatical form you want" picker.  A word is looked up by lemma first
    (Logos defaults to the lemma), then by its surface form.  Each matching code
    is decoded into its grammatical features so the user can choose by meaning
    (e.g. "verb, present, active, indicative, 3rd singular") rather than by a
    raw code such as `V-PAI-3S`.
    """
    conn = db.connect()
    word = (word or "").strip()
    if not module_id or not word:
        return {"ok": False, "error": "need a module and a word"}

    # Try by lemma first, then fall back to the surface form.
    rows = []
    matched_by = None
    for by in ("lemma", "surface"):
        if by == "lemma":
            rows = conn.execute(
                "SELECT m.value AS code, m.surface AS surface, COUNT(*) AS n "
                "FROM marker m JOIN marker l ON l.module_id=m.module_id "
                "AND l.unit_key=m.unit_key AND l.pos=m.pos "
                "WHERE m.module_id=? AND m.kind='morph' AND l.kind='lemma' "
                "AND l.value=? GROUP BY m.value, m.surface ORDER BY n DESC",
                (module_id, word)).fetchall()
        else:
            rows = conn.execute(
                "SELECT value AS code, surface, COUNT(*) AS n FROM marker "
                "WHERE module_id=? AND kind='morph' AND surface=? "
                "GROUP BY value, surface ORDER BY n DESC",
                (module_id, word)).fetchall()
        if rows:
            matched_by = by
            break

    if not rows:
        return {"ok": True, "word": word, "module_id": module_id,
                "matched_by": None, "forms": []}

    out = []
    for r in rows[:limit]:
        code = r["code"]
        f = parse_code(code)
        # Example references where this code occurs for this word.
        if matched_by == "lemma":
            ex_q = ("SELECT u.book, u.chapter, u.verse, u.ref_label "
                    "FROM marker m JOIN unit u "
                    "ON u.module_id=m.module_id AND u.key=m.unit_key "
                    "WHERE m.module_id=? AND m.kind='morph' AND m.value=? "
                    "AND EXISTS (SELECT 1 FROM marker l "
                    "WHERE l.module_id=m.module_id AND l.unit_key=m.unit_key "
                    "AND l.pos=m.pos AND l.kind='lemma' AND l.value=?) "
                    "LIMIT 5")
            ex_args = [module_id, code, word]
        else:
            ex_q = ("SELECT u.book, u.chapter, u.verse, u.ref_label "
                    "FROM marker m JOIN unit u "
                    "ON u.module_id=m.module_id AND u.key=m.unit_key "
                    "WHERE m.module_id=? AND m.kind='morph' AND m.value=? "
                    "AND m.surface=? LIMIT 5")
            ex_args = [module_id, code, word]
        ex_rows = conn.execute(ex_q, ex_args).fetchall()
        examples = [{"ref": (e["ref_label"] or
                           f"{e['book']} {e['chapter']}:{e['verse']}"),
                     "book": e["book"], "chapter": e["chapter"],
                     "verse": e["verse"]} for e in ex_rows]
        out.append({
            "code": code,
            "surface": r["surface"] or "",
            "count": r["n"],
            "features": _plain(f),
            "examples": examples,
        })

    return {"ok": True, "word": word, "module_id": module_id,
            "matched_by": matched_by, "forms": out}


def pattern(module_id: str, terms: list[dict], *, ref: str = "", max_gap: int = 0,
            boundary: str = "verse", search_field: str = "", limit: int = 100,
            offset: int = 0) -> dict:
    """Find ordered, word-level morphology patterns within one tagged module."""
    from . import canon
    if not module_id:
        return {"ok": False, "error": "Choose a tagged resource."}
    if not isinstance(terms, list) or not 1 <= len(terms) <= 6:
        return {"ok": False, "error": "A pattern needs between one and six word positions."}
    try: max_gap = max(0, min(10, int(max_gap)))
    except (TypeError, ValueError): max_gap = 0
    conn = db.connect()
    where = "module_id=? AND kind='morph'"
    args: list = [module_id]
    if ref:
        rr = canon.parse_ref(ref)
        if rr is None:
            return {"ok": False, "error": "Enter a valid Bible passage."}
        lo = canon.BOOK_BY_NAME.get(rr.start.book)
        hi = canon.BOOK_BY_NAME.get(rr.end.book)
        if lo and hi:
            books = [b.osis for b in canon.BOOK_BY_ORDINAL.values()
                     if lo.ordinal <= b.ordinal <= hi.ordinal]
            if books:
                marks = ",".join("?" for _ in books)
                where += f" AND unit_key IN (SELECT key FROM unit WHERE module_id=? AND book IN ({marks}))"
                args += [module_id, *books]
    rows = conn.execute("SELECT unit_key,pos,value,surface FROM marker WHERE " + where, args).fetchall()
    if search_field:
        field_rows = conn.execute(
            "SELECT unit_key,pos FROM marker WHERE module_id=? AND kind='field' AND value=?",
            (module_id, search_field)).fetchall()
        if field_rows:
            allowed_positions = {(r["unit_key"], int(r["pos"] or 0)) for r in field_rows}
            rows = [r for r in rows if (r["unit_key"], int(r["pos"] or 0)) in allowed_positions]
        elif search_field != "main-text":
            rows = []
    ref_keys = None
    if ref:
        units = conn.execute("SELECT key,book,chapter,verse FROM unit WHERE module_id=?", (module_id,)).fetchall()
        lo, hi = canon.parse_ref(ref).start, canon.parse_ref(ref).end
        def at_or_after(u, r):
            ub, rb = canon.BOOK_BY_NAME.get(u["book"]), canon.BOOK_BY_NAME.get(r.book)
            return bool(ub and rb and (ub.ordinal, u["chapter"] or 0, u["verse"] or 0) >=
                        (rb.ordinal, r.chapter or 0, r.verse or 0))
        def at_or_before(u, r):
            ub, rb = canon.BOOK_BY_NAME.get(u["book"]), canon.BOOK_BY_NAME.get(r.book)
            end_ch = r.chapter or 999999
            end_vs = r.verse or 999999
            return bool(ub and rb and (ub.ordinal, u["chapter"] or 0, u["verse"] or 0) <=
                        (rb.ordinal, end_ch, end_vs))
        ref_keys = {u["key"] for u in units if at_or_after(u, lo) and at_or_before(u, hi)}
        rows = [r for r in rows if r["unit_key"] in ref_keys]
    # Morph Query can constrain a pattern to one verse or let it span a chapter.
    # Convert chapter scope into a virtual word stream while retaining a map
    # back to each verse's local marker positions for result links/details.
    boundary = "chapter" if boundary == "chapter" else "verse"
    source_units = conn.execute(
        "SELECT key,book,chapter,verse,ref_label,text,word_count FROM unit WHERE module_id=?",
        (module_id,)).fetchall()
    if ref_keys is not None:
        source_units = [u for u in source_units if u["key"] in ref_keys]
    unit_info = {u["key"]: u for u in source_units}
    source_map: dict[str, list[tuple[str, int, int]]] = {}
    unit_group: dict[str, tuple[str, int]] = {}
    transformed = []
    if boundary == "chapter":
        grouped_units: dict[str, list] = {}
        for u in source_units:
            grouped_units.setdefault(f'{u["book"]}.{u["chapter"]}', []).append(u)
        for group, us in grouped_units.items():
            us.sort(key=lambda u: (u["verse"] or 0, u["key"]))
            offset_words = 0
            for u in us:
                count = max(1, int(u["word_count"] or 0))
                unit_group[u["key"]] = (group, offset_words)
                source_map.setdefault(group, []).append((u["key"], offset_words, count))
                offset_words += count
        for r in rows:
            info = unit_group.get(r["unit_key"])
            if info:
                transformed.append({"unit_key": info[0], "pos": int(r["pos"] or 0) + info[1], "value": r["value"], "surface": r["surface"]})
        rows = transformed
    else:
        for u in source_units:
            source_map[u["key"]] = [(u["key"], 0, max(1, int(u["word_count"] or 0)))]
            unit_group[u["key"]] = (u["key"], 0)
        rows = [dict(unit_key=r["unit_key"], pos=int(r["pos"] or 0), value=r["value"], surface=r["surface"]) for r in rows]
    if not rows:
        return {"ok": True, "total": 0, "results": [], "message": "No morphology tags are indexed for this resource."}
    decoded = {}
    for r in rows:
        decoded.setdefault(r["value"], parse_code(r["value"]))
    wanted: list[dict] = []
    for term in terms:
        filters = {k: str(v) for k, v in (term or {}).items() if k in _FILTERS and v not in (None, "", "any")}
        lemma = str((term or {}).get("lemma") or "").strip().casefold()
        form = str((term or {}).get("form") or "").strip().casefold()
        if not filters and not lemma and not form:
            return {"ok": False, "error": "Choose at least one feature or lemma for each word position."}
        codes = set()
        for code, f in decoded.items():
            if all(f.get(k) == v for k, v in filters.items()): codes.add(code)
        wanted.append({"codes": codes, "has_filter": bool(filters), "lemma": lemma, "form": form,
                       "exclude": bool((term or {}).get("exclude"))})
    # Candidate word positions are narrowed by feature/lemma, then joined in
    # Python on the indexed one-based ordinals. Verse patterns never cross units.
    hits: list[dict[str, dict[int, set[int]]]] = [dict() for _ in wanted]
    for i, term in enumerate(wanted):
        feature_hits: dict[str, set[int]] = {}
        for r in rows:
            if r["value"] in term["codes"] and (not term["form"] or str(r["surface"] or "").strip().casefold() == term["form"]):
                feature_hits.setdefault(r["unit_key"], set()).add(int(r["pos"] or 0))
        lemma_hits: dict[str, set[int]] = {}
        if term["lemma"]:
            lr = conn.execute("SELECT unit_key,pos FROM marker WHERE module_id=? AND kind='lemma' AND lower(value)=?", (module_id, term["lemma"])).fetchall()
            for r in lr:
                target = unit_group.get(r["unit_key"])
                if target:
                    lemma_hits.setdefault(target[0], set()).add(int(r["pos"] or 0) + target[1])
        if term["lemma"] and (term["has_filter"] or term["form"]):
            unitkeys = feature_hits.keys() & lemma_hits.keys()
            accepted = {k: feature_hits[k] & lemma_hits[k] for k in unitkeys}
        elif term["lemma"]:
            accepted = lemma_hits
        else:
            accepted = feature_hits
        for key, ps in accepted.items():
            for p in ps: hits[i].setdefault(key, {})[p] = {i}
    positive = [i for i, t in enumerate(wanted) if not t["exclude"]]
    excluded = [i for i, t in enumerate(wanted) if t["exclude"]]
    if not positive:
        return {"ok": False, "error": "Keep at least one included word in the pattern."}
    keys = set(hits[positive[0]])
    for i in positive[1:]: keys.intersection_update(hits[i])
    matches = []
    for key in keys:
        if any(hits[i].get(key) for i in excluded):
            continue
        starts = sorted(hits[positive[0]][key])
        for first in starts:
            positions = [first]
            for i in positive[1:]:
                lo, hi = positions[-1] + 1, positions[-1] + max_gap + 1
                nxt = next((p for p in sorted(hits[i].get(key, {})) if lo <= p <= hi), None)
                if nxt is None: break
                positions.append(nxt)
            if len(positions) != len(positive): continue
            spans = source_map.get(key, [])
            if not spans: continue
            def locate(position):
                return next(((uk, off, count) for uk, off, count in spans if off < position <= off + count), spans[-1])
            verse_units = [unit_info[uk] for uk, _, _ in spans if uk in unit_info]
            if not verse_units: continue
            u = verse_units[0]
            detail = []
            text_offsets: dict[str, int] = {}
            char_cursor = 0
            for vu in verse_units:
                text_offsets[vu["key"]] = char_cursor
                char_cursor += len(vu["text"] or "") + 1
            for p in positions:
                uk, off, _count = locate(p); local_pos = p - off
                wr = conn.execute("SELECT surface FROM marker WHERE module_id=? AND unit_key=? AND kind='strongs' AND pos=? LIMIT 1", (module_id,uk,local_pos)).fetchone()
                sr = conn.execute("SELECT value FROM marker WHERE module_id=? AND unit_key=? AND kind='strongs' AND pos=? LIMIT 1", (module_id,uk,local_pos)).fetchone()
                mr = conn.execute("SELECT value FROM marker WHERE module_id=? AND unit_key=? AND kind='morph' AND pos=? LIMIT 1", (module_id,uk,local_pos)).fetchone()
                lr = conn.execute("SELECT value,surface FROM marker WHERE module_id=? AND unit_key=? AND kind='lemma' AND pos=? LIMIT 1", (module_id,uk,local_pos)).fetchone()
                tokens = db.words(unit_info[uk]["text"] or "")
                char_range = tokens[local_pos - 1][1:] if 0 < local_pos <= len(tokens) else (None, None)
                base = text_offsets.get(uk, 0)
                mcode = mr["value"] if mr else ""
                detail.append({"position":local_pos,"ref":unit_info[uk]["ref_label"],"surface":(wr["surface"] if wr else (lr["surface"] if lr else "")),"morph":mcode,"features":_plain(parse_code(mcode)) if mcode else {},"lemma":(lr["value"] if lr else ""),"strongs":(sr["value"] if sr else ""),"start":(base + char_range[0] if char_range[0] is not None else None),"end":(base + char_range[1] if char_range[1] is not None else None)})
            text = "\n".join(x["text"] or "" for x in verse_units)
            result_ref = detail[0]["ref"] if detail else u["ref_label"]
            matches.append({"key":key,"book":u["book"],"chapter":u["chapter"],"verse":u["verse"],"ref":result_ref,"text":text,"positions":positions,"matched":detail,"verses":[x["ref_label"] for x in verse_units]})
            break
    matches.sort(key=lambda x:(canon.BOOK_BY_NAME.get(x["book"]).ordinal if canon.BOOK_BY_NAME.get(x["book"]) else 999, x["chapter"] or 0, x["verse"] or 0))
    return {"ok":True,"total":len(matches),"offset":offset,"next":offset+limit if offset+limit<len(matches) else 0,"results":matches[offset:offset+limit]}


# ------------------------------------------------- reverse interlinear

# The languages Scripture is written in.  Anything else -- Spanish, Dutch,
# English -- is a translation whatever it is tagged with.
ORIGINAL_LANGS = {"hbo", "he", "heb", "grc", "el", "ell", "cop", "arc",
                  "syc", "egy"}

_LEMMA_RE = re.compile(r"^[A-Za-z]+$")

def _pick_script(rows, script: str, num: str) -> tuple:
    """Decide which language's occurrences to show, and say so.

    "Original language" has to mean a Bible in a source language.  Spanish is
    not one, and the only Greek module carrying morphology is the Didache,
    which is a non-biblical text -- neither may pass for it.
    """
    langs: dict[str, int] = {}
    orig_bible: dict[str, int] = {}
    for r in rows:
        lang = r["lang"] or "?"
        langs[lang] = langs.get(lang, 0) + 1
        if (r["lang"] or "").lower() in ORIGINAL_LANGS and \
                (r["type"] or "") in ("Bible", "OriginalLanguage"):
            orig_bible[lang] = orig_bible.get(lang, 0) + 1
    want = script
    if want in ("", "auto"):
        want = (sorted(orig_bible, key=lambda l: -orig_bible[l])[0]
                if orig_bible else "eng")
    elif script in langs:
        want = script
    note = ""
    if not orig_bible:
        note = ("No tagged original-language Bible is installed for this word, "
                "so what follows is a translation that carries the number. "
                + ("Install a Greek Bible with word-level morphology tags (such "
                   "as MACULA Greek) to see original-language results here."
                   if num.upper().startswith("G") else
                   "The Hebrew Bible (Open Scriptures morphhb) is tagged, so a "
                   "Hebrew word does show the Hebrew."))
    elif want not in orig_bible:
        note = "Showing " + want + " rather than an original-language text."
    return want, langs, orig_bible, note


_SPAN_CACHE: dict = {}


def _readable_line(module_id: str, key: str, text: str) -> str:
    """Put the spaces back into an unsegmented original-language line.

    The Hebrew stored here has no word spaces at all: Genesis 1:1 reads
    "\u05d1\u05e9/\u05e8\u05d0\u05e9\u05d9\u05ea\u05d1\u05e8\u05d0\u05e2\u05d0\u05dc\u05d5\u05d4\u05d9\u05dd" as one run.  The span
    table knows where every word begins and ends, so the boundaries are put
    back from it rather than guessed at from the text.
    """
    from . import study
    ck = (module_id, key)
    if ck not in _SPAN_CACHE:
        _SPAN_CACHE[ck] = study._spans(db.connect(), module_id, key)
    spans, _ = _SPAN_CACHE[ck]
    if not spans:
        return " ".join((text or "").split())
    cuts = set()
    for sp in spans:
        try:
            start, ln = sp[0], sp[1]
        except (TypeError, IndexError):
            continue
        if start is None or ln is None:
            continue
        cuts.add(int(start))
        cuts.add(int(start) + int(ln))
    out = []
    prev = 0
    for cut in sorted(cuts):
        if cut > prev:
            out.append((text or "")[prev:cut])
            prev = cut
    if prev < len(text or ""):
        out.append((text or "")[prev:])
    return " ".join(w for w in out if w.strip())


def _book_order(name: str) -> int:
    """Canonical position of a book.

    canon.BOOK_BY_ORDINAL is keyed by *integer*, not by name, so looking a book
    up in it by name always missed and every book sorted equal.
    """
    from . import canon
    b = canon.BOOK_BY_NAME.get(name or "")
    if b is not None and getattr(b, "ordinal", None):
        return b.ordinal
    return 999


def reverse_interlinear(num: str, *, limit: int = 40, offset: int = 0,
                        order: str = "canonical",
                        script: str = "auto") -> dict:
    """Every occurrence of a word, with the spelling and a gloss.

    The reverse of the interlinear: the interlinear starts from a verse and shows
    the words in it; this starts from a word and shows the verses it is in.

    On "original language": it can only be one if a tagged original text is
    actually installed.  The Hebrew here is (Open Scriptures morphhb carries both
    morphology and Strong's), and Greek MACULA resources can provide Greek word
    tags when installed. Otherwise this panel explains which text is available.
    """
    from . import canon, study
    num = canon.normalise_strongs(num or "")
    if not num:
        return {"ok": False, "error": "no Strong's number"}
    conn = db.connect()
    row = conn.execute("SELECT word, lemma FROM strongs WHERE strongs=?",
                       (num,)).fetchone()
    wb = study.word_bundle(num)
    if not wb.get("ok"):
        return {"ok": False, "error": wb.get("error", "no such word")}

    rows = conn.execute(
        "SELECT m.module_id, m.unit_key, m.surface, m.value, md.lang AS lang,"
        " md.type AS type FROM marker m LEFT JOIN module md ON md.id=m.module_id "
        "WHERE m.kind='strongs' AND m.value=? LIMIT ?", (num, 4000)).fetchall()
    if not rows:
        return {"ok": False, "error": "no tagged occurrences"}

    want, langs, orig_bible, note = _pick_script(rows, script, num)

    seen = set()
    out: list[dict] = []
    for r in rows:
        if (r["unit_key"], r["surface"] or "") in seen:
            continue
        seen.add((r["unit_key"], r["surface"] or ""))
        u = conn.execute(
            "SELECT book, chapter, verse, ref_label, text FROM unit "
            "WHERE module_id=? AND key=?", (r["module_id"], r["unit_key"])
        ).fetchone()
        if not u or not u["book"]:
            continue
        surface = r["surface"] or ""
        if not surface:
            surface = study._surface_for(conn, r["module_id"], r["unit_key"],
                                         r["value"] or "", "")
        out.append({
            "surface": surface,
            "code": r["value"] or "",
            "ref": f'{u["book"]} {u["chapter"]}:{u["verse"]}',
            "book": u["book"], "chapter": u["chapter"], "verse": u["verse"],
            "module_id": r["module_id"], "key": r["unit_key"],
            "line": _readable_line(r["module_id"], r["unit_key"],
                                   u["text"] or "")[:200],
        })

    def sortkey(o):
        # canon exposes the ordinal map as BOOK_BY_ORDINAL; there is no
        # BOOKS_INDEX, which is what a name-based sort guessed at.
        book = _book_order(o["book"])
        return (book, o["chapter"] or 0, o["verse"] or 0)

    if order == "canonical":
        out.sort(key=sortkey)
    elif order == "surface":
        out.sort(key=lambda o: (o["surface"], sortkey(o)))
    else:
        out.sort(key=lambda o: o["ref"])

    gloss = study._gloss_for(conn, num)
    page = out[offset:offset + limit] if limit else out
    return {
        "ok": True, "num": num,
        "script": want, "languages": langs, "note": note,
        "word": (row["word"] if row else "") or wb.get("headword", ""),
        "lemma": (row["lemma"] if row else "") or "",
        "gloss": gloss,
        "total": len(out),
        "offset": offset,
        "next": offset + limit if offset + limit < len(out) else 0,
        "occurrences": page,
        "by_book": [{"book": b, "n": n} for b, n in wb.get("by_book", [])],
    }


# ------------------------------------------------------------- concordance

def concordance(num: str, *, limit: int = 60, offset: int = 0,
                module_id: str = "", include_context: bool = True) -> dict:
    """Every occurrence in context, as a concordance page reads: book, chapter,
    verse, the line, and a gloss.  Distinct forms are listed, because a word's
    forms are half of what a concordance is for."""
    from . import canon, study
    num = canon.normalise_strongs(num or "")
    if not num:
        return {"ok": False, "error": "no Strong's number"}
    conn = db.connect()
    wb = study.word_bundle(num)
    if not wb.get("ok"):
        return {"ok": False, "error": wb.get("error", "no such word")}

    q = ("SELECT m.module_id, m.unit_key, m.surface, u.book, u.chapter, u.verse,"
         " u.ref_label, u.text, md.lang AS lang, md.type AS type FROM marker m"
         " JOIN unit u ON u.module_id=m.module_id AND u.key=m.unit_key"
         " LEFT JOIN module md ON md.id=m.module_id"
         " WHERE m.kind='strongs' AND m.value=? AND u.book<>''")
    args: list = [num]
    if module_id:
        q += " AND m.module_id=?"
        args.append(module_id)
    q += " LIMIT 8000"
    rows = conn.execute(q, args).fetchall()
    want, langs, orig_bible, note = "", {}, {}, ""
    if not module_id:
        want, langs, orig_bible, note = _pick_script(rows, "auto", num)
        rows = [r for r in rows if (r["lang"] or "eng") == want] or rows

    gloss = study._gloss_for(conn, num)
    entries: list[dict] = []
    seen = set()
    for r in rows:
        k = (r["book"], r["chapter"], r["verse"], r["surface"] or "")
        if k in seen:
            continue
        seen.add(k)
        line = (_readable_line(r["module_id"], r["unit_key"], r["text"] or "")
                if include_context else "")
        entries.append({
            "ref": f'{r["book"]} {r["chapter"]}:{r["verse"]}',
            "book": r["book"], "chapter": r["chapter"], "verse": r["verse"],
            "surface": r["surface"] or "", "line": line[:220],
            "module_id": r["module_id"], "key": r["unit_key"],
        })

    def bkey(b):
        return _book_order(b)
    entries.sort(key=lambda e: (bkey(e["book"]), e["chapter"] or 0,
                                e["verse"] or 0))

    forms: dict[str, int] = {}
    for e in entries:
        if e["surface"]:
            forms[e["surface"]] = forms.get(e["surface"], 0) + 1

    page = entries[offset:offset + limit] if limit else entries
    return {
        "ok": True, "num": num,
        "script": want or module_id or "any", "languages": langs, "note": note,
        "headword": wb.get("headword", num),
        "gloss": gloss,
        "total": len(entries),
        "offset": offset,
        "next": offset + limit if offset + limit < len(entries) else 0,
        "forms": [{"surface": s, "n": n} for s, n in
                  sorted(forms.items(), key=lambda x: -x[1])[:40]],
        "entries": page,
        "by_book": [{"book": b, "n": n} for b, n in wb.get("by_book", [])],
    }

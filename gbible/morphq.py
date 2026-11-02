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


_FILTERS = ("pos", "gender", "number", "state", "conjugation", "tense",
            "person", "participle", "scheme", "pos_particle")


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


def facets() -> dict:
    """What is actually installed, with counts, so the form can be built from
    the data rather than from a guess at the grammar."""
    conn = db.connect()
    rows = conn.execute("SELECT value AS v, count(*) AS n FROM marker "
                        "WHERE kind='morph' GROUP BY value").fetchall()
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
                + ("The Greek New Testament here (SBLGNT) has no morphology or "
                   "Strong's tagging at all."
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
    morphology and Strong's), so a Hebrew word gives you Hebrew.  The Greek does
    not -- the SBLGNT is untagged, and the only Greek module with morphology is a
    non-biblical text -- so a Greek number comes back showing *English*, and says
    so rather than pretending otherwise.
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

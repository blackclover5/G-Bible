"""Clause and sentence structure, for clause search and the sentence diagram.

Two features need the same thing and neither can get it from a word list: where
one clause stops and the next begins, and what part of speech each word is.
The second is already in the database -- the OSHB and SBLGNT modules carry a
morphology tag per word in `marker` -- so the diagram can be exact.  The first
has to be worked out, and this module is where it is worked out.

What this is, honestly
----------------------
A real clause search needs a dependency parser: to know that "God" is the
*object* of "glorified" you have to know the two are joined by an accusative
marker and that nothing sits between them that changes the reading.  Building
that parser is not a weekend, and a bad one is worse than none, because it
answers confidently and wrongly.

So this does the part that can be done without one, and says which part that is:

  SAME CLAUSE   both terms fall inside one clause.  This is a real narrowing
                and it is what most clause work actually needs: it separates
                "faith AND Lord" in one thought from the same two words a
                sentence apart.
  DIFFERENT     the terms are in the same sentence but not the same clause.
                Usually the more interesting of the two -- it finds the
                contrast, the distinction, "not this but that".

Boundaries are found at punctuation and at conjunctions.  Conjunction lists are
per language, and for Greek and Hebrew they are the word's own tagged part of
speech where a tagged module is installed, so the boundary falls where the
grammar says rather than where a guess says.  English has no tags, so English
falls back to punctuation and a closed list of subordinators -- good enough to
narrow, and reported as a heuristic in the response so nothing overstates it.
"""

from __future__ import annotations

import re
import unicodedata

from . import db, morphq

#: Sentence end: full stop, question, exclamation, or a semicolon long enough
#: to be a stop in a text without modern punctuation.
_SENT_END = re.compile(r"([.!?]+[\"'’”\)\]]*)(\s+|$)")

#: Clause end: a comma, semicolon or colon.  Not every one of these is a clause
#: boundary -- a comma inside a list is not -- so a candidate boundary is only
#: accepted when a conjunction follows it, or when it is a semicolon or colon,
#: which in this corpus really are clause boundaries.
_CLAUSE_PUNCT = re.compile(r"([,;:—–]+)(\s+)")

#: English clause-initial words that start a new clause.  Closed list on
#: purpose: an open list turns "and" inside a quotation into a boundary, and it
#: is why "so", "yet" and "nor" are absent -- they read as particles far more
#: often than as coordinators, and splitting after every "so" turned "For God
#: so loved the world" into two clauses at the wrong place.
ENGLISH_MARKERS = frozenset("""
and but or because although though while whereas since when whenever where
wherever unless until after before if whether than as
""".split())

#: Greek subordinators and coordinators, as they appear in the tagged texts.
GREEK_MARKERS = frozenset("""
καί καί δέ ἀλλά ἀλλ' γάρ οὖν οὐν ἄρα Ἐὰν ἐὰν ὅτι ὡς ὅπως ὅθεν ποῦ
ἵνα ὅπως ἵνα ἀφ' ὅθεν ἕως ἄχρι καθ' μετά πρὸ παρά διὰ εἰς ἐκ ἀπὸ ὑπὸ
ἐπί κατά περί ὑπέρ ἀνά μετὰ σύν ἅμα σὺν κατὰ πλὴν ὅμως ἀλλὰ μέν γε
διὰ ἕνεκα ἕνεκεν ὡς οἵ
""".split())

#: Hebrew conjunctions and subordinators, unpointed and pointed.
HEBREW_MARKERS = frozenset("""
וּ וְ וַ וַּ וּלְ וְלִי וּבְ כִּי כִּי כַּי כְּ שֶׁ שֶׁה־ אֲשֶׁר אֲשַׁר אַשְׁרֵי
כְּאַשֶׁר לְמַעַן כִּי אוֹתִי לָכֵן אָבַּל הִנֵּה וּלְשַׁן אֲלֶף הַאֲחַר
""".split())

_SCRIPT_HINT = re.compile(r"[֐-׿]")          # Hebrew
_GREEK_HINT = re.compile(r"[Ͱ-Ͽἀ-῿]")   # Greek + polytonic

_WORDLIKE = re.compile(r"[^\W\d_]+", re.UNICODE)

#: A word, for alignment with the markers.  Whitespace-delimited rather than a
#: letter class, because the OSHB writes a maqaf-joined pair as one token but
#: marks each morpheme separately, and a regex over letters would cut a
#: pointed Hebrew word into single letters (Python's `\w` excludes the vowel
#: points entirely).
_TOKEN_RE = re.compile(r"\S+")


def script_of(text: str) -> str:
    """`hebrew`, `greek` or `latin` -- decided by the text, not by the module."""
    if _SCRIPT_HINT.search(text or ""):
        return "hebrew"
    if _GREEK_HINT.search(text or ""):
        return "greek"
    return "latin"


def markers_for(text: str) -> frozenset:
    s = script_of(text)
    if s == "hebrew":
        return HEBREW_MARKERS
    if s == "greek":
        return GREEK_MARKERS
    return ENGLISH_MARKERS


def _strip_accents(word: str) -> str:
    """Match Greek and Hebrew regardless of diacritics.

    SBLGNT writes NIKA, the JFB notes write Nika, and a search for one has to
    find the other -- so the comparison form drops the marks entirely.
    """
    decomposed = unicodedata.normalize("NFD", word)
    return "".join(c for c in decomposed
                   if not unicodedata.combining(c)).lower()


# ---------------------------------------------------------------- structure

def _token_start(text: str, i: int) -> int:
    """The start of the word touching position `i`."""
    j = i
    while j > 0 and _WORDLIKE.match(text[j - 1]):
        j -= 1
    return j


def text_slice(text: str, clause: dict) -> str:
    """A clause exactly as it appears in `text`.

    Exposed because the offsets are a contract: clause search decides "are both
    words inside one clause" by comparing character positions, so if a clause's
    bounds do not reproduce its own text then every answer built on them is
    about something other than the verse.  Cheap to check, and it was wrong
    before it was checked.
    """
    return (text or "")[clause["start"]:clause["end"]].strip()


def segment(text: str) -> dict:
    """Split `text` into sentences and each sentence into clauses.

    Returns character offsets throughout, because clause search has to say
    *both words are inside these bounds*, and a re-search of the text to find
    the bounds again would be a second opinion about the same string.
    """
    text = text or ""
    out: dict = {"text": text, "script": script_of(text),
                 "sentences": [], "clauses": [], "markers": 0}
    marks = markers_for(text)
    folded = {_strip_accents(m) for m in marks}
    pos = 0
    sent_index = 0
    for m in _SENT_END.finditer(text):
        end = m.end(1)
        chunk = text[pos:end]
        if chunk.strip():
            clauses = _clauses(chunk, pos, marks, folded)
            out["sentences"].append({"index": sent_index,
                                     "start": pos, "end": end,
                                     "clauses": len(clauses)})
            for c in clauses:
                c["sentence"] = sent_index
                out["clauses"].append(c)
            out["markers"] += sum(1 for c in clauses if c["marker"])
        pos = m.end()
        sent_index += 1
    tail = text[pos:]
    if tail.strip():
        clauses = _clauses(tail, pos, marks, folded)
        out["sentences"].append({"index": sent_index, "start": pos,
                                 "end": len(text), "clauses": len(clauses)})
        for c in clauses:
            c["sentence"] = sent_index
            out["clauses"].append(c)
        out["markers"] += sum(1 for c in clauses if c["marker"])
    return out


def _clauses(chunk: str, offset: int, marks: frozenset,
             folded: set) -> list[dict]:
    """The clauses of one sentence, as character ranges into the whole text.

    Two kinds of boundary, and the second one is a judgement call worth naming:
    a semicolon or colon, and a clause that opens on a conjunction.  Splitting
    only at punctuation leaves most English verses as a single clause, which
    makes "both words in one clause" true of nearly every verse and so narrows
    nothing -- and it reads "the faith of Jesus Christ" and "the gift of God"
    as one thought when nobody would.
    """
    cuts: set[int] = set()
    punct: dict[int, str] = {}
    for m in _CLAUSE_PUNCT.finditer(chunk):
        after = m.end()
        start = _token_start(chunk, after)
        word = _WORDLIKE.search(chunk, start)
        token = _strip_accents(word.group(0)) if word else ""
        # A comma is only a boundary when a conjunction follows it; a comma
        # inside a list is not one.
        if m.group(1) in (";", ":", "—", "–") or token in folded:
            cuts.add(after)
            punct[after] = m.group(1)

    # A conjunction opening a clause.  Only when something precedes it, so the
    # first word of a sentence is never treated as a boundary.
    for m in _WORDLIKE.finditer(chunk):
        if m.start() == 0:
            continue
        if not chunk[m.start() - 1:m.start()].isspace():
            continue
        if _strip_accents(m.group(0)) in folded:
            cuts.add(m.start())
            punct.setdefault(m.start(), "")

    bounds = [offset] + sorted(c + offset for c in cuts) + [offset + len(chunk)]
    out: list[dict] = []
    for i in range(len(bounds) - 1):
        start, end = bounds[i], bounds[i + 1]
        body = chunk[start - offset:end - offset]
        if not body.strip():
            continue
        word = _WORDLIKE.search(body)
        token = _strip_accents(word.group(0)) if word else ""
        out.append({"start": start, "end": end, "text": body.strip(),
                    "marker": token if token in folded else "",
                    "punct": punct.get(start - offset, "")})
    if not out:
        out.append({"start": offset, "end": offset + len(chunk),
                    "text": chunk.strip(), "marker": "", "punct": ""})
    for i, c in enumerate(out):
        c["index"] = i
    return out


#: How many candidate verses a dependency search is willing to parse.

#: The answer rate is low by nature: ask where *faith* is the object of a verb
#: and most places faith occurs it is not -- it is in a prepositional phrase, or
#: the subject, or a noun modifying something.  So the window has to be much
#: wider than the page of results, and how wide it was has to be reported, or a
#: short answer looks exhaustive when it is not.
SCAN_DEFAULT = 600
SCAN_MAX = 4000


def clause_search(term_a: str, term_b: str = "", *, relation: str = "same",
                  module_id: str = "", book: str = "", chapter: int = 0,
                  limit: int = 200, scan: int = 0) -> dict:
    """Verses where one or two terms stand in the relation asked for.

    Relations, in the order a reader wants them:

      object     the term is the direct object of a verb     <- what was asked
      subject    the term is the subject of a verb
      same       both terms are governed by one and the same verb
      different  both terms are in one sentence but under different verbs
      sentence   both terms are anywhere in one sentence

    `object` and `subject` are the reason this feature exists and they need a
    dependency parse, so they go through `depparse`.  When that parser is not
    installed, or the text is Hebrew or Greek, this says so in `method` and
    falls back to the punctuation-and-conjunction splitter -- which can do
    `same`, `different` and `sentence`, and cannot do `object` at all, because
    without the parse there is no way to know what is an object.  It says that
    rather than answering from punctuation.
    """
    from . import search as searchmod
    from . import depparse

    if relation in ("object", "subject", "prepositional") and not depparse.available()[0]:
        why = depparse.available()[1]
        return {"ok": False, "error": (
            f"a dependency parser is needed for the '{relation}' relation, "
            f"and there is none here: {why}"),
            "needs": "parser", "reason": why}

    conn = db.connect()
    want = max(SCAN_DEFAULT, min(SCAN_MAX, scan or 0) or SCAN_DEFAULT)
    terms = [t for t in (term_a, term_b) if t and t.strip()]
    if not terms:
        return {"ok": False, "error": "nothing to look for"}
    if relation == "different" and len(terms) < 2:
        return {"ok": False,
                "error": "'different clauses' needs two terms"}

    # Quote only what actually needs quoting.  Wrapping a *single* word in
    # quotes makes the parser build a phrase node, and the phrase matcher
    # re-evaluates positions for every candidate unit -- which turned a
    # two-word clause query over a full library into eighteen seconds of
    # work re-deriving an answer a plain conjunction gets from the index in
    # one.  A one-word phrase is also just the word.
    def _q(t: str) -> str:
        return f'"{t}"' if " " in t else t

    q = " AND ".join(_q(t.strip()) for t in terms)
    opts = searchmod.SearchOpts(modules=[module_id] if module_id else [],
                                limit=want, snippets=False,
                                search_bible_text=True,
                                search_headings=False,
                                smart=False)
    if book:
        opts.reference_matching = "broad"
        q += f' AND bible:"{book}"'
    res = searchmod.search(q, opts)
    if not res.get("ok"):
        return res

    if depparse.available()[0]:
        dep = _dependency_search(res, terms, relation, limit, want)
        if dep is not None:
            return dep

    folded = {t: _strip_accents(t.strip()) for t in terms}
    kept: list[dict] = []
    scripts: set[str] = set()
    for h in res.get("hits", []):
        seg = segment(h.get("text") or "")
        hits = _where(seg, folded)
        if relation == "same":
            ok = bool(_in_one_clause(hits))
        elif relation == "different":
            ok = bool(_in_two_clauses(hits, seg))
        else:
            ok = any(hits.values())
        if not ok:
            continue
        scripts.add(seg["script"])
        h = dict(h)
        h["clauses"] = [{"index": c["index"], "sentence": c["sentence"],
                         "text": c["text"], "marker": c["marker"]}
                        for c in seg["clauses"]]
        h["where"] = hits
        kept.append(h)
    method = ("the morphology in the text" if scripts - {"latin"}
              else "punctuation and a closed list of conjunctions")
    return {"ok": True, "relation": relation, "query": q,
            "script": (sorted(scripts)[0] if scripts else ""),
            "candidates": res.get("total", 0), "total": len(kept),
            "hits": kept[:limit], "method": method, "note": _NOTE[relation]}


# ------------------------------------------------------- dependency search

def _dependency_search(res: dict, terms: list[str], relation: str,
                       limit: int, want: int) -> dict | None:
    """Answer the question from a real dependency parse, or decline to.

    Returns None when the hits are not something a dependency parse can speak
    about -- a Hebrew or Greek verse, say -- so the caller can use the
    punctuation splitter and label the answer honestly.  A parse that answered
    an Aramaic sentence by guessing would be worse than no answer.
    """
    from . import depparse

    hits = res.get("hits", [])
    if not hits:
        return {"ok": True, "relation": relation,
                "query": res.get("query", ""), "script": "",
                "candidates": res.get("total", 0), "scanned": 0,
                "total": 0, "hits": [],
                "method": "a dependency parse", "parsed": 0,
                "note": _DEP_NOTE.get(relation, "")}

    # Only Latin script.  Hebrew and Greek would need a model of their own, and
    # the morphology in the database is the honest source for those.
    latin = [h for h in hits
             if script_of(h.get("text") or "") not in ("hebrew", "greek")]
    if not latin:
        return None

    parses = depparse.parse_many([h.get("text") or "" for h in latin],
                                 [h.get("ref_label") or "" for h in latin])
    kept: list[dict] = []
    parsed = 0
    for h, pr in zip(latin, parses):
        if not pr.get("ok"):
            continue
        parsed += 1
        sent_hits = h.get("text") or ""
        for si, sent in enumerate(pr["sentences"]):
            # A sentence must contain every term, and for two-term relations
            # both of them in the same sentence -- otherwise the relation
            # cannot hold, so there is no reason to look at the roles.
            per_term = [depparse.locate(sent, t) for t in terms]
            if not all(per_term):
                continue
            # Every match of each term in this sentence; the relation decides
            # which pair counts.  For two terms a sentence only counts if both
            # words are in it, and for one term if the word is.
            lists = [m for m in per_term if m]
            if len(lists) != len(terms):
                continue
            m_a, m_b = (lists + [[]])[:2]
            if len(terms) == 2:
                pair = _cross_sentence(m_a, m_b)
                if pair is None:
                    continue
                m_a, m_b = pair
            holds, why = depparse.relation_holds(m_a, m_b, relation)
            if not holds:
                continue
            # The matches the relation actually accepted, not the first ones in
            # the sentence.  "God" is an object of "honour" and the subject of
            # "came" in the same verse, and a search for subjects was quoting the
            # object because that was word one.
            shown = [m for m in ([why.get("a"), why.get("b")] if relation in
                                  ("same", "different") else [why.get("a")]) if m]
            # The matches travel back to the panel so it can show what it
            # accepted, not what happened to be word one.  They are not part of
            # the answer, and 120 hits carrying two extra token records each is
            # a response nobody wants.
            why = {k: v for k, v in why.items() if k not in ("a", "b")}
            kept.append({**h,
                         "clauses": _dep_clauses(sent),
                         "where": {t: [depparse.role_of(m)]
                                   for t, m in zip(terms, shown)},
                         "evidence": why,
                         "roles": {t: depparse.role_label(m["dep"])
                                   for t, m in zip(terms, shown)},
                         "match": {"word": shown[0]["word"],
                                   "dep": shown[0]["dep"],
                                   "verb": shown[0]["head"],
                                   "clause": shown[0]["clause"],
                                   "sentence": si}})
            break   # one sentence per verse is enough; a verse is one result

    # Rank by what kind of text it is, not by relevance.

    # A lexicon answers "where is *faith* the object of a verb" with the entry
    # for FAITHED, and the entry for BELIEVING, and the entry for TRUST: those
    # are sentences in a dictionary, they are real, and they are the first three
    # hits and the last three useful ones.  Somebody asking this about a word is
    # nearly always asking about a text, so the Bible and the running prose come
    # first and everything else follows.
    _rank = {"Bible": 0, "Book": 1, "Commentary": 2, "Devotional": 3,
             "StudyGuide": 4}
    kept.sort(key=lambda h: (_rank.get(h.get("module_type") or "", 5),
                             h.get("key") or ""))

    total = len(kept)
    found = res.get("total", 0)
    out = {"ok": True, "relation": relation, "query": res.get("query", ""),
           "script": "latin",
           "candidates": found, "total": total,
           "hits": kept[:limit], "parsed": parsed, "scanned": len(latin),
           "exhausted": len(latin) >= min(found, want),
           "method": "a dependency parse",
           "note": _DEP_NOTE.get(relation, "")}
    if not out["exhausted"] and found > len(latin):
        out["more"] = found - len(latin)
    return out


def _cross_sentence(a: list[dict], b: list[dict]):
    """The pair of matches to test, preferring ones in different clauses.

    A sentence can hold the same word twice.  For `different` the interesting
    pair is the two that sit under different verbs; for `same` it is two under
    one.  `relation_holds` checks every pair anyway, so returning the first
    non-empty pair would be enough -- but preferring a pair that differs avoids
    answering "different clauses" from the first coincidental match.
    """
    if not a or not b:
        return None
    for x in a:
        for y in b:
            if x["clause"] != y["clause"]:
                return [x], [y]
    return [a[0]], [b[0]]


def _dep_clauses(sent) -> list[dict]:
    return [{"index": c["index"], "verb": c["verb"], "text": c["text"],
             "sentence": sent.index} for c in sent.clauses()]


_DEP_NOTE = {
    "object": ("The word is the direct object of the verb named in each "
               "result. This is a dependency parse, so it knows the "
               "difference between an object and a prepositional object -- "
               "'in his name' is not the object of a verb."),
    "subject": ("The word is the subject of the verb named in each result."),
    "same": ("Both words are governed by the same verb. That is a narrower "
             "claim than 'between the same pair of commas', and it holds "
             "across commas when the grammar holds it."),
    "different": ("The words are in one sentence under different verbs -- a "
                  "contrast or a distinction."),
    "sentence": "The words are anywhere in one sentence.",
}


_NOTE = {
    "same": ("Both terms fall inside one clause. Boundaries are found at "
             "punctuation and at conjunctions; nothing here is a dependency "
             "parse, so 'clause' means 'the stretch between two clause "
             "boundaries' and not a claim about grammatical dependency."),
    "different": ("The terms are in the same sentence but not the same clause. "
                  "This is how a contrast or a distinction reads."),
    "sentence": ("The terms are anywhere in the same sentence."),
}


def _where(seg: dict, folded: dict) -> dict:
    """{term: [clause index, ...]} for each term."""
    out: dict = {t: [] for t in folded}
    for c in seg["clauses"]:
        body = _strip_accents(c["text"])
        for t, f in folded.items():
            if f in body:
                out[t].append(c["index"])
    return out


def _in_one_clause(hits: dict) -> list[int]:
    """The clause indices that hold every term.

    An intersection, which is the whole of "same clause": if the first term is
    in clauses 2 and 5 and the second in 5 and 9, the answer is clause 5 and
    nothing else.  The earlier version of this walked the terms pairwise and
    returned a set per pair, which is not the same question and produced clause
    lists that were neither a subset of anything nor complete.
    """
    if not hits:
        return []
    shared: set[int] | None = None
    for idxs in hits.values():
        here = set(idxs)
        shared = here if shared is None else (shared & here)
        if not shared:
            return []
    return sorted(shared)


def _in_two_clauses(hits: dict, seg: dict) -> list[list[int]]:
    """Pairs of clauses in one sentence where the terms do not coincide.

    The interesting relation: this is what finds a contrast, a distinction, a
    "not this but that".  Both clauses have to be in the same sentence, or every
    unrelated pair in a chapter would match.
    """
    terms = list(hits)
    if len(terms) < 2:
        return []
    out: list[list[int]] = []
    a, b = terms[0], terms[1]
    for ca in hits[a]:
        for cb in hits[b]:
            if ca == cb or ca in hits[b]:
                continue
            if seg["clauses"][ca]["sentence"] == seg["clauses"][cb]["sentence"]:
                pair = sorted((ca, cb))
                if pair not in out:
                    out.append(pair)
    return out


# ------------------------------------------------------------------ diagram

#: The POS letters the diagram colours and groups by, in the order a reader
#: expects them rather than the order the codes happen to be stored in.
_DIAGRAM_ORDER = ("V", "N", "R", "C", "K", "T", "D", "P", "S", "M", "A",
                  "F", "X", "H", "Z", "Y", "O", "Q", "B", "L", "W")

#: OSHB codes decode to a part of speech *by name* ("noun") where Robinson's
#: decode to the letter ("N").  The diagram groups by letter, so the name is
#: mapped back; a single tag for both schemes is what lets one set of colours
#: and one ordering work on Hebrew and Greek alike.
_POS_BY_NAME = {v.upper(): k for k, v in morphq.PARTS_OF_SPEECH.items()}


def _pos_tag(f: dict) -> str:
    raw = (f.get("pos") or "").strip()
    if not raw:
        return ""
    return raw if len(raw) <= 2 else _POS_BY_NAME.get(raw.upper(), "")


#: spaCy's universal part-of-speech tags onto the diagram's own letters, so one
#: colour scheme and one legend serve a tagged Hebrew Bible and an English one.
#: The letters are a colour key, not a claim about morphology; the readable name
#: travels beside them in `pos_label`, which is what the legend prints.
_UPOS_LETTER = {
    "VERB": "V", "AUX": "X", "NOUN": "N", "PROPN": "N", "NUM": "N",
    "ADP": "R", "CCONJ": "C", "SCONJ": "C", "DET": "T", "PRON": "S",
    "ADV": "K", "ADJ": "A", "PUNCT": "F", "PART": "M", "INTJ": "W",
    "PARTIAL": "M", "X": "X", "SYM": "N", "SPACE": "X",
}
_UPOS_NAME = {
    "VERB": "verb", "AUX": "auxiliary", "NOUN": "noun", "PROPN": "proper noun",
    "NUM": "number", "ADP": "preposition", "CCONJ": "coordinating conjunction",
    "SCONJ": "subordinating conjunction", "DET": "determiner",
    "PRON": "pronoun", "ADV": "adverb", "ADJ": "adjective", "PUNCT": "punctuation",
    "PART": "particle", "INTJ": "interjection", "SYM": "symbol",
}


def diagram(module_id: str, key: str, *, ref: str = "") -> dict:
    """Lay a verse out by clause and by part of speech.

    Three sources, in order of how exact they are, and the response says which
    one answered:

    * a tagged original-language module -- the morphology is in the database,
      so the tags are the module's own rather than anything worked out here;
    * an English Bible with the parser installed -- a dependency parse gives
      the parts of speech *and* what attaches to what, so the clauses are real
      clauses governed by real verbs;
    * an English Bible without it -- clause structure from punctuation and a
      conjunction list, no parts of speech, and the panel says so.
    """
    from . import library
    from . import depparse

    conn = db.connect()
    row = conn.execute("SELECT * FROM unit WHERE module_id=? AND key=?",
                       (module_id, key)).fetchone()
    if row is None:
        return {"ok": False, "error": f"no unit {key!r} in {module_id!r}"}
    m = library.get(module_id)
    text = row["text"] or ""
    seg = segment(text)

    words: list[dict] = []
    for r in conn.execute(
            "SELECT pos, value, surface FROM marker WHERE module_id=? AND "
            "unit_key=? AND kind='morph' ORDER BY pos", (module_id, key)):
        f = morphq.parse_code(r["value"])
        words.append({
            "pos": r["pos"], "surface": r["surface"] or "",
            "code": r["value"],
            "pos_tag": _pos_tag(f),
            "pos_label": (f.get("pos_label")
                          or morphq.PARTS_OF_SPEECH.get(_pos_tag(f), "")
                          or _pos_tag(f)),
            "tense": f.get("tense") or "", "person": f.get("person") or "",
            "mood": f.get("conjugation") or "",
            "gender": f.get("gender") or "", "number": f.get("number") or "",
            "case": f.get("state") or "",
        })
    source = "morphology in the database"
    dep_clauses = None
    if not words:
        dep = _dependency_words(text)
        if dep is not None:
            words, dep_clauses = dep
            source = "a dependency parse"

    clauses: list[dict] = []
    if words and dep_clauses is not None:
        # Real clauses: each is one finite verb's subtree, with the verb named.
        clauses = [{"index": c["index"], "sentence": c.get("sentence", 0),
                    "start": -1, "end": -1, "text": c["text"], "marker": "",
                    "verb": c["verb"], "words": list(c["words"]),
                    "dep": c.get("dep", ""), "parent": c.get("parent", -1),
                    "depth": c.get("depth", 0)}
                   for c in dep_clauses]
    else:
        for c in seg["clauses"]:
            c = {**c, "words": []}
            clauses.append(c)
        # Word offsets are not stored, so locate each tagged word in the text.
        # The n-th tagged word is matched against the n-th occurrence of its
        # surface form, which is what the marker recorded -- searching for each
        # word independently would put every occurrence of a common noun in the
        # first clause that mentions it.
        _attach_by_order(words, clauses, text)

    if words and dep_clauses is None:
        tag_note = ""
    elif words:
        tag_note = ("Parts of speech and clause structure from a dependency "
                    "parse. Each clause is one finite verb and the words that "
                    "verb governs, and the line under each word says what it "
                    "is attached to.")
    else:
        tag_note = ("This module carries no morphology, so the clauses are "
                    "real but the parts of speech are not shown. Open a tagged "
                    "original-language Bible for those, or install the English "
                    "parser.")

    return {"ok": True, "module_id": module_id,
            "module": m.name if m else "", "key": key,
            "ref": ref or row["ref_label"] or "", "text": text,
            "script": seg["script"], "tagged": bool(words),
            "source": source,
            "tag_note": tag_note,
            "sentences": seg["sentences"],
            "clauses": [{"index": c["index"], "sentence": c["sentence"],
                         "start": c.get("start", -1),
                         "end": c.get("end", -1),
                         "text": c["text"], "marker": c.get("marker", ""),
                         "verb": c.get("verb", ""),
                         "dep": c.get("dep", ""),
                         "parent": c.get("parent", -1),
                         "depth": c.get("depth", 0),
                         "words": c["words"]} for c in clauses],
            "words": words,
            "kinds": _kind_counts(words),
            "order": [k for k in _DIAGRAM_ORDER
                      if any(w.get("pos_tag") == k for w in words)]}


def _dependency_words(text: str):
    """Words and clauses for an English verse, from the dependency parse.

    Returns (words, clauses) or None when there is no parser, so the caller can
    fall back to punctuation rather than show nothing.
    """
    from . import depparse

    if script_of(text) in ("hebrew", "greek"):
        return None
    ok, _why = depparse.available()
    if not ok:
        return None
    pr = depparse.parse(text)
    if not pr.get("ok"):
        return None
    sents = pr["sentences"]
    if not sents:
        return None

    words: list[dict] = []
    clauses: list[dict] = []
    for sent in sents:
        # A comma has a place in the parse -- it is what the parser hangs a
        # clause boundary on -- but it is not a word, and a diagram that lists
        # one card per comma is a diagram of punctuation.
        keep = [t for t in sent.tokens
                if (t["pos"] or "") not in ("PUNCT", "SPACE", "SYM")]
        if not keep:
            keep = sent.tokens
        base = len(words)
        # Keyed by the parse's own token number, so a clause can pick its own
        # words back out without matching on the text a second time.
        made: dict[int, dict] = {}
        for t in keep:
            upos = t["pos"] or ""
            w = {
                "pos": len(words),
                "surface": t["word"],
                "code": f"{upos}/{t['dep']}",
                "pos_tag": _UPOS_LETTER.get(upos, "X"),
                "pos_label": _UPOS_NAME.get(upos, upos.lower() or "word"),
                "lemma": t["lemma"],
                "dep": t["dep"],
                "head": t["head"],
                "role": depparse.role_label(t["dep"]),
                "tense": "", "person": "", "mood": "", "gender": "",
                "number": "", "case": "",
                "sentence": sent.index,
                "clause": sent.clause_of.get(t["n"], 0),
                "offset": -1,
            }
            made[t["n"]] = w
            words.append(w)
        # Word objects, not indices: the tagged path puts objects in
        # `clause["words"]` and the panel reads `w.surface` off them.  Indices
        # here drew a card of "—" and "?" for every word in the verse.
        sent_clauses = []
        for c in sent.clauses():
            sent_clauses.append({**c, "sentence": sent.index,
                                 "words": [made[k] for k in c["words"]
                                           if k in made]})
        # Propositional depth: a clause is subordinate when its verb hangs off
        # a verb in another clause.  Root clauses sit at depth 0; everything
        # else is indented under the clause that governs it.  This is the
        # honest, dependency-based version of a propositional outline, and it
        # only exists for English (the parser is English-only).
        # Map token number -> clause index, so a verb's head can be resolved
        # to the clause it belongs to.
        tok2clause = {t["n"]: sent.clause_of.get(t["n"], -1)
                      for t in sent.tokens}
        for ci, c in enumerate(sent_clauses):
            # Find this clause's verb token.
            verb_tok = None
            for t in sent.tokens:
                if t["word"] == c.get("verb") and tok2clause.get(t["n"]) == ci:
                    verb_tok = t
                    break
            parent = -1
            if verb_tok is not None:
                head_n = verb_tok.get("head")
                if head_n is not None and head_n in tok2clause:
                    pc = tok2clause[head_n]
                    if pc != ci and pc >= 0:
                        parent = pc
            c["dep"] = verb_tok.get("dep", "") if verb_tok else ""
            c["parent"] = parent
        # Depth by walking parents, with a guard against cycles.
        for ci, c in enumerate(sent_clauses):
            depth = 0
            seen = {ci}
            cur = c.get("parent", -1)
            while cur is not None and cur >= 0 and cur not in seen:
                seen.add(cur)
                depth += 1
                cur = sent_clauses[cur].get("parent", -1) if cur < len(sent_clauses) else -1
            c["depth"] = depth
        clauses.extend(sent_clauses)
    return words, clauses


def _attach_by_order(words: list[dict], clauses: list[dict], text: str) -> None:
    """Line the tagged words up with the text and give each its clause.

    The n-th marker is the n-th word of the verse, so the words are taken by
    position rather than searched for by name.  That matters twice over here:
    the OSHB records the *code* in its `surface` field rather than the word, so
    there is nothing to search for, and a search by name would put every
    occurrence of a common noun into the first clause that mentions it.
    """
    tokens = [(m.start(), m.group(0)) for m in _TOKEN_RE.finditer(text)]
    for i, w in enumerate(words):
        w["offset"] = -1
        if i < len(tokens):
            w["offset"], w["surface"] = tokens[i]
        elif (w.get("surface") or "").strip():
            hits = [m.start() for m in
                    re.finditer(re.escape(w["surface"].strip()), text)]
            if len(hits) > i:
                w["offset"] = hits[i]
    for c in clauses:
        c["words"] = [w for w in words
                      if c["start"] <= w["offset"] < c["end"]]


def _kind_counts(words: list[dict]) -> list[dict]:
    tally: dict[str, dict] = {}
    for w in words:
        k = w.get("pos_tag") or "?"
        d = tally.setdefault(k, {"tag": k, "label": w.get("pos_label") or k,
                                 "n": 0})
        d["n"] += 1
    return sorted(tally.values(), key=lambda d: -d["n"])

def verse_tokens(ref: str) -> dict:
    """Distinct words of one verse, for the visual query builder.

    The builder's dropdowns offer the verse's own words, so a query is built
    by pointing rather than by spelling — and every offered word is really
    in the verse, because the list is read off installed text.
    """
    from . import canon, library
    rr = canon.parse_ref(ref or "")
    if rr is None:
        return {"ok": False, "error": f"Cannot read {ref!r}"}
    f = next(iter(rr.refs()))
    conn = db.connect()
    mods = [m for m in library.list_all() if m.is_bible]
    try:
        from . import workspace as _ws
        fav = _ws.top_bible_module()
    except Exception:  # noqa: BLE001
        fav = None
    if fav is not None and fav in mods:
        mods.sort(key=lambda m: (m.id != fav.id, m.lang != "eng"))
    else:
        mods.sort(key=lambda m: (m.lang != "eng"))
    row = None
    for m in mods:
        row = conn.execute("SELECT module_id, text FROM unit WHERE module_id=? "
                           "AND book=? AND chapter=? AND verse=? LIMIT 1",
                           (m.id, f.book, f.chapter or 0, f.verse or 1)
                           ).fetchone()
        if row is not None and (row["text"] or "").strip():
            break
    if row is None or not (row["text"] or "").strip():
        return {"ok": False, "error": f"No installed Bible has {ref!r}"}
    seen, words = set(), []
    for w, _s, _e in db.words(row["text"]):
        wl = w.lower()
        if wl not in seen and len(wl) > 1:
            seen.add(wl)
            words.append(w)
    return {"ok": True, "ref": ref, "module_id": row["module_id"],
            "words": words}


def diagram_export(ref: str) -> dict:
    """The sentence diagram as a standalone HTML document (print/PDF via the
    browser, Word/PowerPoint by opening the file). Same data the modal
    paints — clauses with governing verbs and words — as nested lists."""
    from . import canon as _canon
    rr = _canon.parse_ref(ref or "")
    if rr is None:
        return {"ok": False, "error": f"Cannot read {ref!r}"}
    key = next(iter(rr.refs())).osis_id()
    best = None
    try:
        from . import library as _lib
        for m in _lib.list_all():
            if not m.is_bible:
                continue
            d = diagram(m.id, key, ref=ref)
            if d.get("ok"):
                best = d
                break
    except Exception:  # noqa: BLE001
        best = None
    if best is None or not best.get("ok"):
        return {"ok": False,
                "error": (best or {}).get("error") or f"No diagram for {ref!r}"}
    import html as _h
    parts = [f"<h1>Sentence diagram: {_h.escape(best['ref'])}</h1>",
             f"<p><em>{_h.escape(best.get('module', ''))} — "
             f"{_h.escape(best.get('source', ''))}</em></p>"]
    if best.get("tag_note"):
        parts.append(f"<p>{_h.escape(best['tag_note'])}</p>")
    for c in best.get("clauses", []):
        head = f"Clause {c['index'] + 1}"
        if c.get("verb"):
            head += f" — governed by {_h.escape(c['verb'])}"
        if c.get("marker"):
            head += f" [{_h.escape(c['marker'])}]"
        parts.append(f"<h2>{head}</h2><p>{_h.escape(c.get('text', ''))}</p><ul>")
        for w in c.get("words", []):
            lab = w.get("surface", "")
            pos = w.get("pos_label") or w.get("pos_tag") or ""
            rel = w.get("relation") or ""
            extra = " — ".join(x for x in (pos, rel) if x)
            parts.append(f"<li>{_h.escape(lab)}"
                         + (f" <em>({_h.escape(extra)})</em>" if extra else "")
                         + "</li>")
        parts.append("</ul>")
    from . import publish as _pub
    page = _pub._html_page(f"Sentence diagram: {best['ref']}",
                           "\n".join(parts), _pub.attribution_block([]))
    fname = "diagram-" + re.sub(r"[^A-Za-z0-9]+", "-", best["ref"]).strip("-") \
        + ".html"
    return {"ok": True, "filename": fname, "html": page,
            "note": "Open in a browser to print, or in Word/PowerPoint."}

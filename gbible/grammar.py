"""The grammar, as a thing you can read and search.

`placement.py` has carried a `grammar` slot since before this file existed: a
grammar-typed module can be put in the reader beside the verse, and the
morphology decoder in `morphq.py` can turn `HVqp3ms` into "verb, qal, perfect,
third person, masculine singular".  What neither of them does is *use* any of
it, because nothing in the interface asked a grammar a question.  A reader with
Gesenius installed had 173 sections and 2.7 MB of Hebrew grammar in their
library and no way in.

So this module is the way in, in three shapes, because there are three questions:

* **What is in it?**  A grammar is a numbered sequence of sections and its
  structure *is* its table of contents -- "44. Flexion of the Perfect of Qal" is
  a finding aid, not metadata.  `sections()` lists them in order.
* **What does it say about this word?**  `morph()` takes a morphology code,
  decodes it with the same decoder the Morph Search uses, and then finds the
  passages that discuss those features.  This is the one that needs care: a
  code says "Piel, perfect, third person masculine singular", a grammar says
  "Piel" in one section and "perfect" in another and "masculine singular" in a
  third, and returning three sections titled with the matched features says
  more about the search than about the word.
* **What does it say about this?**  `search()` is ordinary full-text search,
  scoped to the grammar, because a grammar is also just a large book.

On coverage, the honest part.  The Wikisource edition of Gesenius is 173
sections; the CrossWire catalogue entry for it claims 352 units, and the
difference is not a missing half of a grammar but the catalogue counting
headings that are not sections.  `health()` reports the count it actually has,
the sections that carry no text at all, and how much of the book is in the
library -- rather than either claiming completeness or letting a gap read as an
accident of the text.
"""
from __future__ import annotations

import re

from . import db, library, markup, morphq

#: The type the Store files grammars under.  Stated as data so a module
#: re-typed by hand reappears here rather than vanishing from the guide.
GRAMMAR_TYPES = ("Grammar",)

#: Feature -> the words a grammar uses for it.
#:
#: The decoder's vocabulary is lower case and English ("qal", "wayyiqtol"), and a
#: nineteenth-century Hebrew grammar spells the same features differently --
#: Gesenius writes Hithpaʿēl where the decoder writes "hithpael", and calls the
#: waw consecutive what everybody else calls the wayyiqtol.  Each entry is the
#: spellings worth looking for, and both sides are folded (see `_fold_table`)
#: before they are compared, so a term here need not carry the book's accents.
#: A feature with no entry is simply not searched for rather than guessed at.
_TERMS: dict[str, tuple[str, ...]] = {
    "qal": ("Qal",),
    "qutal": ("Quṭal", "Qutal"),
    "niphal": ("Niphal", "Nif'al"),
    "naqal": ("Naqal",),
    "piel": ("Piel", "Pi'el"),
    "pual": ("Pual", "Pu'al"),
    "hithpael": ("Hithpael",),
    "maqqef": ("Maqqef", "Makkeph"),
    "polal": ("Polal", "Po'al"),
    "perfect": ("perfect",),
    "imperfect": ("imperfect",),
    # Gesenius does not write "wayyiqtol" anywhere -- he calls it the waw
    # consecutive, and a search that looked for the modern spelling found
    # nothing in the book that is entirely about it.
    "wayyiqtol": ("wayyiqtol", "waw consecutive", "imperfect consecutive"),
    "participle": ("participle",),
    "infinitive": ("infinitive",),
    "noun": ("noun",),
    "verb": ("verb",),
    "preposition": ("preposition",),
    "conjunction": ("conjunction",),
    "article": ("article",),
    "relative": ("relative",),
    "demonstrative": ("demonstrative",),
    "masculine": ("masculine",),
    "feminine": ("feminine",),
    "singular": ("singular",),
    "plural": ("plural",),
    "dual": ("dual",),
    "absolute": ("absolute state", "absolute"),
    "construct": ("construct state", "construct"),
    "emphatic": ("emphatic",),
    "third": ("third person",),
    "second": ("second person",),
    "first": ("first person",),
}


def modules() -> list[dict]:
    """Installed grammar-typed modules."""
    out = []
    for m in library.list_all():
        if m.type in GRAMMAR_TYPES and m.installed_at:
            out.append({"id": m.id, "name": m.name, "abbrev": m.abbrev or "",
                        "license": m.license or "", "source": m.source_name or "",
                        "source_url": m.source_url or "",
                        "author": m.author or "", "year": m.year or "",
                        "path": m.path or ""})
    return out


def _ids() -> list[str]:
    return [m["id"] for m in modules()]


#: A section number, from the heading it is filed under.  Two shapes occur in
#: the installed module: "44. Flexion of the Perfect of Qal", and the Wikisource
#: pages that are *only* a number ("84"), which are real sections -- page 84
#: carries 28,915 characters -- and a heading that matched nothing because it
#: had nothing after the digits.
_SECTION_NUM = re.compile(r"^(?:.*/)?(\d+)(?:[\.\s].*)?$")


def sections(module_id: str = "") -> list[dict]:
    """Every section, in order, with the number and title it is filed under.

    Ordered by the number in the heading where there is one rather than by the
    storage key, because "c10" sorts before "c9" as text and after it as a
    number, and a grammar whose table of contents runs 1, 10, 100, 101, 11 is
    not a table of contents.
    """
    ids = [module_id] if module_id else _ids()
    if not ids:
        return []
    conn = db.connect()
    ph = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT key, title, length(COALESCE(text,'')) n, "
        f"length(COALESCE(markup,'')) h "
        f"FROM unit WHERE module_id IN ({ph}) ORDER BY key", ids).fetchall()
    out = []
    for r in rows:
        key = r["key"] or ""
        m = _SECTION_NUM.match(r["title"] or "") or _SECTION_NUM.match(key)
        out.append({
            "key": key,
            "title": (r["title"] or "").split("/")[-1],
            "full_title": r["title"] or "",
            "number": int(m.group(1)) if m else None,
            "chars": r["n"] or 0,
            "heads": r["h"] or 0,
            "empty": (r["n"] or 0) < 40,
            "module_id": ids[0] if len(ids) == 1 else "",
        })
    out.sort(key=lambda s: (s["number"] is None, s["number"] or 0, s["key"]))
    return out


def read(module_id: str, key: str) -> dict:
    """One section, rendered.  The `unit` endpoint's own job, under a name that
    says what is being read."""
    m = library.get(module_id)
    if m is None or not m.installed_at:
        return {"ok": False, "error": "no grammar module installed"}
    conn = db.connect()
    r = conn.execute("SELECT * FROM unit WHERE module_id=? AND key=?",
                     (module_id, key)).fetchone()
    if r is None:
        return {"ok": False, "error": f"no section {key!r} in {m.name}"}
    item = library._mk_item(r, library._opts(""))
    return {"ok": True, "module_id": module_id, "module": m.name,
            "key": item.key, "label": item.label, "title": item.title,
            "html": item.html}


def search(query: str, *, module_id: str = "", limit: int = 20) -> dict:
    """Full-text search inside the grammar.

    **Over the corpus this module already builds, not over the shared search
    index** -- and the reason is this book rather than the engine.

    A Hebrew grammar spells the same stem several ways: Qal, Qāl, Piel, Piēl,
    Hithpael, Hithpaʿel.  The shared index tokenises with
    `unicode61 remove_diacritics`, which folds the macrons and leaves the
    transliteration mark, so a search for `Hithpael` finds nothing in a grammar
    that discusses Hithpaʿel in fifteen sections.  A reader who knows the word
    and spells it the ordinary way is not asking for a lesson in ʿayin.  A
    substring match over the template-free text finds all of them.

    A shared index over 1.18 million units is also the wrong instrument for a
    book of 173: it ranks a grammar section against a Bible verse, which says
    nothing about which section answers the question.  The ranking here is
    plain and stated -- sections containing every term first, then by how often
    the terms occur, then by how early -- and it is the same corpus `morph()`
    matches against, so a term one finds the other finds too.
    """
    q = " ".join((query or "").split())
    if not q:
        return {"ok": True, "query": "", "results": [], "total": 0}
    ids = [module_id] if module_id else _ids()
    if not ids:
        return {"ok": False, "error": "no grammar module installed"}
    terms = _terms_of(q)
    if not terms:
        return {"ok": True, "query": q, "terms": [], "results": [], "total": 0,
                "note": "Nothing to search for."}
    phrase = " ".join(terms)
    rows = []
    for d in _corpus(ids):
        low = d["norm"]
        title = d.get("title_norm") or ""
        counts = [low.count(t) for t in terms]
        # **A section named for the term counts, even if its body never says
        # it.**  §54 is titled "Hithpaʿēl" and defines the stem in Hebrew
        # letters, calling it "this stem" for twenty pages -- so a search for
        # "Hithpael" that only reads bodies misses the one section in the book
        # that is about it, and returns eight sections that merely compare
        # their conjugations with it.  The heading is the strongest piece of
        # evidence a book offers about its own organisation.
        titled = sum(1 for t in terms if t in title)
        if not all(counts) and not titled:
            continue
        first = min((low.find(t) for t in terms if low.find(t) >= 0), default=0)
        together = low.count(phrase) if len(terms) > 1 else sum(counts)
        rows.append({
            "module_id": module_id or ids[0],
            "module": "",
            "key": d["key"],
            "label": d["title"] or d["key"],
            "snippet": _window(d, terms),
            "terms": terms,
            "count": sum(counts),
            "phrase": together,
            "all_terms": len(counts),
            "titled": titled,
            "at": first,
            "chars": len(d["text"]),
        })
    # A section named for the term first, then every term present, then the
    # terms used together, then the most occurrences.  "Absolute state" is one
    # grammatical term and a section that says it once is the right answer; a
    # section that says "absolute" nine times and "state" twelve times,
    # separately, is not.
    rows.sort(key=lambda r: (-r["titled"], -r["all_terms"], -r["phrase"],
                             -r["count"], r["at"], r["key"]))
    total = len(rows)
    where = "this grammar" if module_id else "the grammar"
    if not total:
        said = ("No section of " + where + " has"
                + (" all of " if len(terms) > 1 else " ")
                + ", ".join(f"“{t}”" for t in terms) + ".")
    else:
        said = (f"{total} section{'s' if total != 1 else ''} of {where} "
                + ("contain" if total != 1 else "contains")
                + (" all " + str(len(terms)) + " terms" if len(terms) > 1
                   else " it")
                + (", sections that use them together first, then the most "
                   "occurrences" if len(terms) > 1
                   else ", most occurrences first")
                + ". The count is a hint, not a score: a short section uses a "
                  "word once and a long one uses it in passing.")
    return {"ok": True, "query": q, "terms": terms,
            "results": rows[:max(1, limit)], "total": total, "note": said}


#: What counts as a term in a query.  A phrase in quotes is one term, because
#: "absolute state" is a term and searching it as two words matches every
#: sentence that happens to contain "state".
_QUOTED = re.compile(r'"([^"]+)"')
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")


def _terms_of(q: str) -> list[str]:
    """The query's terms, folded the same way the book is.

    Both sides have to agree.  The book writes `Hithpaʿēl` and the reader writes
    `Hithpael`, which the fold makes equal; a reader who pastes the book's own
    spelling back in writes `Hithpaʿēl`, which without this would be the one
    query that finds nothing.
    """
    out = [m.group(1).strip() for m in _QUOTED.finditer(q)]
    rest = _QUOTED.sub(" ", q)
    out.extend(m.group(0).strip() for m in _WORD.finditer(rest))
    return [t.translate(_MARKS).lower() for t in out if len(t.translate(_MARKS)) > 1]


def _window(doc: dict, terms: list[str], width: int = 240) -> str:
    """One passage around the earliest term, for the result list.

    Cut from the reader's text at the offset the matched form has after the
    transliteration marks were dropped, so the passage opens on a word rather
    than half of one.  A section that matches only in its heading has nothing
    to cut, and says so by returning nothing -- the heading is the finding, and
    padding it with the first two hundred characters of the chapter it opens
    would hide that.
    """
    text = doc.get("text") or ""
    low = doc.get("norm") or text.lower()
    at = min((low.find(t) for t in terms if low.find(t) >= 0), default=-1)
    if at < 0:
        return "This section is titled for the term; its text reaches it in "
        + "Hebrew letters."
    a = max(0, at - width // 3)
    oa = _back(doc, a)
    return _WS2.sub(" ", text[oa:oa + width * 2]).strip()


def _features(code: str) -> list[dict]:
    """The decoded features of one morphology code, as search terms.

    Each feature that a grammar can be asked about becomes one row: the
    decoder's own label, and the spellings to look for.  A feature with no
    spelling (a scheme this module does not know) is dropped rather than
    guessed at, so a code from a tagging scheme with different vocabulary finds
    nothing and says so instead of returning the whole book.
    """
    f = morphq.parse_code(code)
    out: list[dict] = []
    seen: set[str] = set()

    def add(key: str, label: str) -> None:
        terms = _TERMS.get(key)
        if not terms or key in seen:
            return
        seen.add(key)
        out.append({"feature": key, "label": label, "terms": list(terms)})

    if f.get("pos"):
        add(f["pos"], f["pos"])
    for part in (f.get("particles") or []):
        add(part, part)
    if f.get("conjugation"):
        add(f["conjugation"], f["conjugation"])
    if f.get("tense"):
        add(f["tense"], f["tense"])
    if f.get("person"):
        add(f["person"], f["person"] + " person")
    if f.get("gender"):
        add(f["gender"], f["gender"])
    if f.get("number"):
        add(f["number"], f["number"])
    if f.get("state"):
        add(f["state"], f["state"] + " state")
    if f.get("participle"):
        add("participle", f["participle"])
    return out


def _corpus(ids: list[str]) -> list[dict]:
    """Every grammar section as plain prose, kept in two forms, once.

    The stored text still carries the MediaWiki templates the importer kept
    (`{{GHGheb|text=מֶלֶךְ}}`, `{{GHGbible-ref|book=Is|chapter=13}}`).  Searching
    that raw text finds terms *inside the templates* -- and one of those
    templates is `{{GHGterm|...}}`, a glossary of exactly the words this module
    searches for, so the phrase "Piel" is in the book whether or not any section
    discusses it.  The templates are removed once here, so what is matched is
    what a reader would read.

    **Two forms of the text are kept, because one of them does not match what
    readers type.**  `text` is the prose, and snippets are cut from it.  `norm`
    is the same prose with the transliteration marks dropped, and it is what is
    matched against: this grammar writes Hithpaʿel and Niphʿal with an ʿayin, so
    a reader typing the ordinary `Hithpael` -- how the word appears in every
    English grammar, in every morphology list in this application, and in the
    transliterations of the Strong's numbers -- finds nothing in the book that is
    *about* it.  Fifteen sections discuss Hithpaʿel and the search returned zero.

    Cached against the module ids and the byte count, so a library that has not
    changed answers the next request from memory and one that has does not.
    """
    conn = db.connect()
    ph = ",".join("?" * len(ids))
    r = conn.execute(
        f"SELECT count(*) n, sum(length(COALESCE(text,''))) chars "
        f"FROM unit WHERE module_id IN ({ph})", ids).fetchone()
    key = f"{'|'.join(ids)}:{r['n']}:{r['chars']}"
    if _CORPUS.get("key") == key:
        return _CORPUS["docs"]
    docs = []
    for row in conn.execute(
            f"SELECT key, title, text FROM unit WHERE module_id IN ({ph}) "
            f"ORDER BY key", ids).fetchall():
        text = _strip_templates(row["text"] or "")
        title = (row["title"] or "").split("/")[-1]
        docs.append({
            "key": row["key"] or "",
            "title": title,
            "full_title": row["title"] or "",
            "text": text,
            "norm": text.translate(_MARKS).lower(),
            "title_norm": title.translate(_MARKS).lower(),
            "drops": [m.start() for m in _MARK_RE.finditer(text)],
        })
    _CORPUS.update({"key": key, "docs": docs})
    return docs


_CORPUS: dict = {}

#: The characters dropped or folded when matching, and why.
#:
#: A transliteration is not the word.  This grammar writes Hithpaʿēl with an
#: ʿayin, wayyiqtôl with a circumflex, ṭôḇ with a dot under the first letter --
#: and a reader typing any of them writes `hithpael`, `wayyiqtol`, `tov`,
#: because that is how they appear in every morphology list, every Strong's entry
#: and every other grammar.  This book is worse than most: it spells the same
#: stem three ways with three different characters for the ʿayin alone
#: (`Hithpaʿēl`, `Hithpa‛ēl` with U+201B, and a third the transcriber mangled),
#: so the fold is built from the book rather than guessed at.
#:
#: They are letters rather than diacritics, so the shared index's
#: `remove_diacritics` keeps every one of them; that is the whole reason the
#: corpus carries a second form of the text.  Nothing is dropped from the text a
#: reader sees -- `drops` records where they were, and every snippet is cut from
#: the original at the mapped offset.
def _fold_table() -> dict:
    """Characters to fold when matching, derived rather than listed.

    Every accented Latin letter in the Basic Latin, Latin-1 and Latin Extended
    ranges is folded to its unaccented base, and the modifier letters used for
    transliteration marks are dropped, because neither survives into the word a
    reader types.  Built this way rather than as a hand-kept list because the
    list would be missing one character the first time this grammar -- or the
    next one -- spells something differently, and a missing character is a
    search that silently returns nothing.

    Only one-to-one folds are used: a character whose decomposition is more
    than one letter is dropped rather than replaced by several, so positions in
    the folded text still line up with the original except where `drops` says
    they do not.
    """
    import unicodedata
    out: dict = {}
    for cp in range(0x00C0, 0x0250):
        ch = chr(cp)
        if not ch.isalpha():
            continue
        base = "".join(c for c in unicodedata.normalize("NFKD", ch)
                       if not unicodedata.combining(c))
        if base != ch:
            out[cp] = base if len(base) == 1 else None
    for cp in range(0x0300, 0x0370):        # combining marks, if any survive
        out[cp] = None
    # Transliteration marks and the quote characters this book uses for them.
    for ch in ("\u02bf" "\u02be" "\u02bc" "\u02bb" "\u02c1"
               "\u02b9" "\u201a" "\u201b" "\u2019"
               "\u2018" "\u00b4" "\u02dd" "\u02de"):
        out[ord(ch)] = None
    return {k: v for k, v in out.items() if v != chr(k)}


_FOLD = _fold_table()
_MARKS = str.maketrans(_FOLD)
_MARK_RE = re.compile("[" + re.escape("".join(
    chr(cp) for cp, to in _FOLD.items() if to is None)) + "]")



def _back(doc: dict, pos: int) -> int:
    """A position in `norm` back to the same character in `text`.

    The two strings differ only by the dropped marks, so the mapping is a count
    of how many marks fall before the position -- which is why their positions
    are kept.  A snippet cut at the wrong offset is still English, but it opens
    half a word early and closes half a word late.
    """
    drops = doc.get("drops") or []
    if not drops:
        return pos
    import bisect
    return pos + bisect.bisect_right(drops, pos)


def _strip_templates(s: str) -> str:
    """The prose, with the wiki markup read the way Wikisource reads it.

    **The existing unwrapper, not a second one.**  `markup.strip_wikitext` was
    written for exactly this text and already decides what a template carries:
    positional arguments are kept, a `text=` argument is kept whatever it looks
    like, page furniture like `GHGcite` is dropped, and nesting is expanded from
    the inside out until nothing is left to expand.  Writing a second, narrower
    version here would have thrown away exactly the part that matters for
    searching: this book's vocabulary lives in `{{GHGterm|Qal}}`, `{{GHGpron|…}}`
    and `{{GHGtranslit|…}}`, and a stripper that keeps only `text=` deletes
    every occurrence of the very terms it is looking for.

    That is not hypothetical.  The narrow version found "Piel" in fifteen
    sections and "wayyiqtol" in none, because every one of them was inside a
    template.  The project's unwrapper finds both.
    """
    if not s:
        return ""
    out = markup.strip_wikitext_uncached(s)
    # A dozen sections still carry templates the unwrapper deliberately keeps
    # -- GHGheb with its Hebrew example, GHGbible-ref with its reference --
    # because in the *article* they are content.  In a one-line search result
    # they are not: the reader sees "{{GHGpar-heading|54|Hithpaʿēl}}" and learns
    # nothing.  So they come out here, keeping a `text=` argument where there is
    # one, because that argument is a Hebrew word the section is about.
    prev = None
    while prev != out and "{{" in out:
        prev = out
        out = _TEMPLATE.sub(lambda m: _text_arg(m.group(0)), out)
    if "{{" in out or "}}" in out:
        out = out.replace("{{", " ").replace("}}", " ")
    return _WS.sub(" ", out).strip()


_TEMPLATE = re.compile(r"\{\{([^{}]*)\}\}")
_WS = re.compile(r"[ \t]{2,}")


def _text_arg(tpl: str) -> str:
    """`{{GHGheb|text=מֶלֶךְ}}` -> `מֶלֶךְ`; anything else -> nothing.

    The value stops at the next pipe.  `{{GHGheb|text=מֶלֶךְ|translate=to mourn}}`
    otherwise yields "מֶלֶךְ|translate=to mourn", which puts the wiki's argument
    names in the middle of a sentence -- "ate=to mourn, in Qal only in poetic
    style" -- and reads as though the grammar were corrupt when it is the strip
    that is.
    """
    import re as _re
    m = _re.search(r"\|\s*text\s*=\s*([^|]*)", tpl[2:-2])
    return m.group(1).strip() if m else ""


def morph(code: str, *, limit: int = 6) -> dict:
    """What the grammar says about the word carrying this morphology code.

    `HVqp3ms` is "verb, qal, perfect, third person, masculine, singular".  A
    reader who has just clicked that code in a Bible pane is asking a
    grammatical question, and the answer is not a link to the whole grammar: it
    is the sections that treat those features, ranked by how much they actually
    say about them.

    **Ranking is by distinct features matched, weighted by how rare each term
    is.**  Gesenius prints "masculine" and "singular" in most of his paradigms
    and "Piel" in a handful of sections, so a section that discusses Piel,
    perfect *and* third person is more use than one that happens to contain the
    word "verb" five hundred times.  A term that appears in one section in ten
    counts three times as much as one in every third of the book, and a section
    matching three features still beats a section matching two of the common
    ones.

    Snippets are cut around the *rarest* matched term rather than the first one
    found, because the first "verb" in a section is usually in a footnote about
    somebody else's grammar, and that is not what the reader asked for.
    """
    ids = _ids()
    if not ids:
        return {"ok": False, "error": "no grammar module installed"}
    feats = _features(code)
    if not feats:
        f = morphq.parse_code(code)
        what = f.get("pos") or f.get("scheme") or "nothing"
        return {"ok": True, "code": code, "features": [], "sections": [],
                "note": "Nothing in this code that a grammar can be asked "
                        f"about — it decoded as {what}. The tagging scheme may "
                        "be one this library does not know."}
    docs = _corpus(ids)
    lowered = [(d, d["norm"]) for d in docs]
    # How common each term is, so the ranking can weigh it.  One pass per term
    # over the corpus; the counts are what separate "this section is about the
    # Piel" from "this section has the word noun in it".
    df: dict[str, int] = {}
    chosen: dict[str, str] = {}
    for ft in feats:
        for term in ft["terms"]:
            n = sum(1 for _d, low in lowered if term.lower() in low)
            if n:
                df[term] = n
                chosen[ft["feature"]] = term
                break           # the first spelling that occurs is the term
    hits: dict[str, dict] = {}
    for ft in feats:
        term = chosen.get(ft["feature"])
        if not term:
            continue
        want = term.lower()
        # A word, not a fragment: "perfect" is not in the title "The Imperfect
        # and its Inflexion".  A title match is worth several mentions in the
        # prose, because a section *named* "44. Flexion of the Perfect of Qal"
        # is the section the reader wants and one that mentions the phrase in
        # passing is not.
        title_re = re.compile(r"\b" + re.escape(want) + r"\b")
        for doc, low in lowered:
            in_title = bool(title_re.search(doc.get("title_norm") or ""))
            if want not in low and not in_title:
                continue
            h = hits.setdefault(doc["key"], {
                "key": doc["key"], "title": doc["title"],
                "full_title": doc["full_title"], "text": doc["text"],
                "matched": {}, "score": 0.0})
            times = low.count(want)
            h["matched"][ft["feature"]] = {"label": ft["label"], "term": term,
                                           "df": df[term], "title": in_title,
                                           "times": times}
            # How *often* the term occurs, up to a point.  One section is about
            # Hithpaʿel and mentions it two hundred times; another mentions it
            # once in a footnote and is not about it at all, and a scheme that
            # only counts "is it here" cannot tell them apart.  Capped, so a
            # long section cannot win on length alone.
            h["score"] += (_weight(df[term]) * min(times, 4)
                           + (4.0 if in_title else 0.0))
    sections_out = []
    for h in hits.values():
        titled = sum(1 for v in h["matched"].values() if v.get("title"))
        sections_out.append({
            "key": h["key"],
            "title": h["title"],
            "full_title": h["full_title"],
            "matched": [{"feature": k, "label": v["label"], "term": v["term"],
                         "df": v["df"], "in_title": v.get("title", False),
                         "times": v.get("times", 0)}
                        for k, v in h["matched"].items()],
            "features": len(h["matched"]),
            "titled": titled,
            "score": round(h["score"], 1),
            # The ranking figure, and why it is not simply the score.
            #
            # The raw score is wrong in both directions, and each error was
            # measured.  Counting alone puts §93 "Paradigms of Masculine Nouns"
            # at the top of every list, because it is three times the length of
            # §44 and mentions every gender, number and state in the book.  A
            # pure rate -- score per thousand characters -- overcorrects, and
            # puts a short section that mentions "hithpael" once at the top of
            # a query about the Hithpael.
            #
            # So: a title match is worth half as much again (a section *named*
            # for the feature is the section to read), and the length is damped
            # rather than divided out -- one extra mention in a short section is
            # real, but three mentions in a long one are not.
            "rank": round(h["score"] * (1 + 0.5 * titled) /
                          (1 + len(h["text"]) / 20000.0), 2),
            "snippets": _snippets(h, h["matched"]),
            "chars": len(h["text"]),
        })
    sections_out.sort(key=lambda s: (-s["titled"], -s["rank"], -s["features"],
                                     s["key"]))
    found = len(sections_out)
    return {
        "ok": True,
        "code": code,
        "decoded": morphq.parse_code(code),
        "features": feats,
        "sections": sections_out[:max(1, limit)],
        "total_sections": found,
        "note": (f"{found} section{'s' if found != 1 else ''} of the grammar "
                 f"mention{' these features' if found != 1 else ' this feature'}, "
                 "ranked by whether a section is *named* for one of them, then "
                 "by how much of the section is about them rather than how long "
                 "it is. This finds the sections to read; it is not a parse."),
    }


def _weight(df: int) -> float:
    """How much a term found in `df` sections is worth as evidence.

    Three scale steps, not a curve: a term in a handful of sections is *about*
    those things; a term in most of the book is a word.
    """
    if df <= 10:
        return 3.0
    if df <= 40:
        return 2.0
    return 1.0


def _snippets(doc: dict, matched: dict[str, dict], width: int = 190,
              want: int = 2) -> list[dict]:
    """Windows of the text around the most specific matched terms.

    Rarest first, so the passage shown is the one that mentions the thing the
    reader asked about rather than the first occurrence of a word that appears
    in a third of the book.  The text is already template-free, so the window
    is prose on both sides.
    """
    text = doc.get("text") or ""
    low = doc.get("norm") or text.lower()
    order = sorted(matched.items(), key=lambda kv: (kv[1].get("df", 999), kv[0]))
    out: list[dict] = []
    taken: list[int] = []
    for feature, info in order:
        term = (info.get("term") or "").lower()
        if not term or len(out) >= want:
            continue
        at = low.find(term)
        while at >= 0 and len(out) < want:
            a = max(0, at - width)
            if all(abs(a - x) > width for x in taken):
                taken.append(a)
                # Cut from the reader's text, at the offset the matched form
                # has *after* the marks were dropped.
                oa, ob = _back(doc, a), _back(doc, at + len(term) + width)
                out.append({"feature": feature, "label": info.get("label", ""),
                            "term": term, "text": _WS2.sub(
                                " ", text[oa:ob]).strip()})
            at = low.find(term, at + len(term))
    return out


_WS2 = re.compile(r"\s+")


def health() -> dict:
    """What is installed, and what of it is here.

    The comparison that matters is against the *catalogue's* count, and for this
    module that count comes with its own explanation: the Wikisource index page
    for Gesenius lists 351 subpages and marks itself `{{incomplete}}` -- content
    pages not transcribed.  So the library holding 173 of them is not a
    half-installed grammar that could be finished by re-indexing; it is a
    complete copy of what Wikisource has, and the remaining 178 pages do not
    exist there to be fetched.  Saying so is the difference between a reader
    chasing a missing half of a book and a reader who knows the book's other
    half is not transcribed anywhere.
    """
    mods = modules()
    if not mods:
        return {"available": False, "modules": [], "sections": 0, "notes": [
            "No module typed `Grammar` is installed. The Store carries "
            "Gesenius' Hebrew Grammar from Wikisource."]}
    catalogue = _catalogue()
    conn = db.connect()
    rows = []
    notes: list[str] = []
    for m in mods:
        r = conn.execute(
            "SELECT count(*) n, sum(length(COALESCE(text,''))) chars, "
            "sum(CASE WHEN length(COALESCE(text,'')) < 40 THEN 1 ELSE 0 END) empty "
            "FROM unit WHERE module_id=?", (m["id"],)).fetchone()
        secs = sections(m["id"])
        nums = sorted(s["number"] for s in secs if s["number"] is not None)
        run = _run(nums)
        listed = catalogue.get(m["id"])
        rows.append({
            "id": m["id"], "name": m["name"], "license": m["license"],
            "author": m["author"], "source": m["source"],
            "source_url": m["source_url"],
            "sections": r["n"] or 0, "chars": r["chars"] or 0,
            "empty": r["empty"] or 0,
            "numbered": len(nums),
            "run": run,                       # e.g. "1–167"
            "beyond_run": [n for n in nums if run and n > run[1]],
            "listed": (listed or {}).get("subpage_count"),
            "listed_status": (listed or {}).get("status", ""),
            "listed_url": (listed or {}).get("page_url", ""),
        })
        if listed and listed.get("subpage_count"):
            have, want = r["n"] or 0, listed["subpage_count"]
            pct = round(100 * have / want, 1)
            # The status string carries the Wikisource template the index page
            # uses to say so; the braces are the wiki's punctuation and are
            # noise in a sentence a reader has to parse.
            status = (listed.get("status") or "incomplete")
            status = re.sub(r"\{+|\}+", "", status).strip(" ()")
            notes.append(
                f"{m['name']}: {have} of the {want} pages Wikisource lists "
                f"({pct}%). The index page marks itself “{status}” — the "
                "rest are not transcribed there, so this is the whole of it "
                "that exists.")
        if (r["empty"] or 0):
            notes.append(
                f"{m['name']}: {r['empty']} section(s) carry no text at all "
                "and are listed rather than hidden, so the gap is visible.")
    return {"available": True, "modules": rows,
            "sections": sum(r["sections"] for r in rows),
            "chars": sum(r["chars"] for r in rows),
            "notes": notes,
            "note": "A grammar is a book: its sections are the contents, and "
                    "what is missing from the contents is missing from the "
                    "library."}


def _catalogue() -> dict:
    """The Store's record for each grammar module, keyed by module id.

    Read from the catalogue rather than hard-coded, because the count it carries
    -- how many pages Wikisource lists -- is the only figure a reader can check
    this library against, and it changes when the catalogue is re-synced.
    """
    from . import store
    raw = store.load_catalog("wikisource") or {}
    out = {}
    for it in raw.get("items") or []:
        if str(it.get("category", "")).lower() != "grammar":
            continue
        out[f"wikisource-{it.get('id')}"] = it
    return out


def _run(nums: list[int]) -> tuple[int, int] | None:
    """The longest unbroken run of section numbers, as `(first, last)`."""
    if not nums:
        return None
    best = cur_start = prev = nums[0]
    best_len = 1
    for n in nums[1:]:
        if n == prev + 1:
            if prev + 1 - cur_start > best_len:
                best, best_len = (cur_start, prev + 1), prev + 1 - cur_start
        else:
            cur_start = n
        prev = n
    return best
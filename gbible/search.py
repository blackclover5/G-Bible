"""The search engine.

Implements the search query language:

  term1 AND term2            implicit AND between adjacent terms
  term1 OR term2             either
  term NOT term2             first without the second
  "exact phrase"             order + adjacency, no stemming
  lord*  lord?               wildcards (* = 0+ chars, ? = 0 or 1 in a word)
  a BEFORE b                a occurs before b
  a AFTER  b                a occurs after b
  a NEAR b                  within 48 characters, ~8-10 words
  a WITHIN 5 WORDS b        distance in words (range and n-n forms)
  a WITHIN 30 CHARS b       distance in characters (counts separators)
  a EQUALS b                at the very same location
  a IN b                    a wholly inside b
  a INTERSECTS b            a and b overlap
  bible:"Gen 1:1"           reference
  strongs:G2316             datatype / field scoping
  lemma.g:ἀγαπάω           original-language scoping
  field.bible:Joshua        disambiguating field modifier
  term:(a OR b OR c)        one highlight colour for a set

Two things are done *without* a language model, which is the whole point of the
"no AI" constraint:

  * **smart term normalisation** -- case folding, diacritics, orthographic
    variants, conservative stemming, and a spell-correct suggestion built from
    the library's own headword/Strong's vocabulary;
  * **ranking** -- BM25 over the term frequencies, boosted by coverage of the
    whole query, by proximity when a proximity operator was used, and by
    reference-context (a title/heading hit outranks a body hit).

Both are computed from the library's own statistics, so they improve as the
library grows and never leave the machine.
"""

from __future__ import annotations

import bisect
import math
import re
import time
import unicodedata
from dataclasses import dataclass
from dataclasses import field as dcfield
from typing import Iterable

from . import canon, db, markup
from .library import Module, get as get_module, list_all

#: Scripts whose vowel points survive FTS5's `unicode61` tokenizer.
#:
#: `remove_diacritics 2` strips Latin, Greek and Cyrillic marks and nothing
#: else, so a pointed Hebrew word is indexed as itself -- `בָּרָ֣א`, points and
#: all -- and a query for `ברא` matches nothing.  That is not a subtlety at the
#: edges: it means the entire Hebrew Bible in this library returned zero hits
#: for every word in it, while `fold()` reduced the same strings correctly and
#: the FTS table plainly held the verses.
#:
#: So for these scripts the candidate pool is built by scanning the selected
#: modules with the same tokeniser the exact pass uses, rather than by asking
#: FTS5 something it cannot answer.  A scan of a Hebrew Bible is a few hundred
#: thousand tokens; a wrong answer is every one of them.
_UNFOLDABLE_FTS = re.compile(r"[֐-׿؀-ۿݐ-ݿ]")


#: Which modules hold text FTS5 cannot fold, decided once per module per run.
_NEEDS_SCAN: dict[str, bool] = {}


def _module_needs_scan(module_id: str) -> bool:
    """Does this module's text carry marks that FTS5 leaves in?

    Asked of the module rather than of the query, because the query is usually
    *unpointed*: a reader types `ברא` and means `בָּרָ֣א`, so a test on the query
    finds nothing to complain about and the search returns nothing.  The
    decision has to be made from the text that is actually stored.
    """
    cached = _NEEDS_SCAN.get(module_id)
    if cached is not None:
        return cached
    row = db.connect().execute(
        "SELECT text FROM unit WHERE module_id=? AND text<>'' LIMIT 3",
        (module_id,)).fetchall()
    out = any(_UNFOLDABLE_FTS.search(r["text"] or "") for r in row)
    _NEEDS_SCAN[module_id] = out
    return out


def _scan_candidates(mods: list[Module], fts_terms: list[Term],
                     opts: SearchOpts) -> dict[str, dict]:
    """Candidate units found by reading the text, for scripts FTS cannot fold.

    Two stages, and the first one matters: SQLite narrows with `LIKE` and only
    the survivors are tokenised in Python.  Tokenising every unit of every module
    that quotes Hebrew was forty-two seconds for a two-word query across a full
    library -- `db.words` ran a quarter of a million times over texts that
    could not possibly hold the answer -- while the same `LIKE` reduces the same
    question to a few hundred rows before a single regex is compiled.

    The `LIKE` is deliberately a plain substring test, not a word test: it is a
    *superset* of every word the stemmer could match, and the exact tokeniser
    decides afterwards.  Being wrong here only costs a little work; being wrong
    in the other direction drops units, which is the failure this whole fallback
    exists to avoid.

    The tokens are folded the same way the exact pass folds them, so this pool
    and the exact pass agree about what a word is.
    """
    conn = db.connect()
    groups = [_term_stems(t) for t in fts_terms]
    groups = [g for g in groups if g]
    if not groups:
        return {}
    # Narrow per term, OR across terms.  A term requires ALL of its own stems --
    # a quoted phrase contains every word it quotes -- so ANDing them is still
    # a superset of the answer while being vastly narrower than one flat OR.
    # The OR is what made this fallback degenerate: `"in the beginning"` includes
    # the stem "the", `LIKE '%the%'` matches nearly every unit in the module, and
    # ten Hebrew-quoting modules became a full read-and-tokenise of themselves.
    # A bare word has one stem, so AND degenerates to the original single LIKE
    # and the common path is unchanged.
    out: dict[str, dict] = {}
    for m in mods:
        if not m or not m.id or not _module_needs_scan(m.id):
            continue
        clauses, like = [], []
        for g in groups:
            clauses.append("(" + " AND ".join(
                "text LIKE ? ESCAPE '\\'" for _ in g) + ")")
            like += ["%" + w.replace("\\", "\\\\").replace("%", "\\%")
                     .replace("_", "\\_") + "%" for w in g]
        where = " OR ".join(clauses)
        hits: dict[str, object] = {}
        for r in conn.execute(
                f"SELECT key, text FROM unit WHERE module_id=? AND ({where})",
                [m.id, *like]):
            seen = {db.token_key(w[0]) for w in db.words(r["text"] or "")}
            # All of a term's stems, because all of them have to be there for the
            # term to match at all.  See `_term_stems`.
            if any(all(w in seen for w in g) for g in groups):
                hits[r["key"]] = r
        out[m.id] = hits
    return out


def _term_stems(t: Term) -> list[str]:
    """The stems a term's tokens must match, and nothing else.

    The scan pool below tests candidates against `seen`, which is built from
    `db.token_key` and therefore holds the *stem* of every token: "loves"
    contributes "lov", never "love".  So the pool has to be phrased in stems.

    Phrasing it in surface forms as well -- which `_term_keys` returns -- looks
    like a harmless extra needle and is not.  `all(...)` over ['lov', 'love']
    asks whether the literal "love" is a stem, which it never is, so every bare
    word whose spelling differs from its stem failed the test and the fallback
    returned nothing.  `love` silently lost 1,047 units that way: the text path
    answered 7,658 where the index said 8,705.
    """
    out = list(t.words or [])
    for ph in t.phrases or []:
        out.extend(ph)
    return [w for w in out if len(w) >= 2]


def _term_keys(t: Term) -> list[str]:
    """Every token a term looks for, folded the way `db.token_key` folds.

    A phrase keeps its words in `phrases` and leaves `words` empty, so reading
    only `words` found nothing to scan for and every `"..."` query fell through
    to the FTS path that cannot answer it.
    """
    out = list(t.words or [])
    for ph in t.phrases or []:
        out.extend(ph)
    out.extend(t.raw or [])
    return out


# ==========================================================================
# Query parsing
# ==========================================================================

class QueryError(Exception):
    pass


AND, OR, NOT = "AND", "OR", "NOT"

_PROX_UNITS = ("WORDS", "CHARS", "CHARS_LITERAL")

_DATATYPES = {
    "bible", "reference", "ref", "crossref", "strongs", "strong", "lemma",
    "morph", "morphology", "person", "place", "topic", "sense", "culture",
    "event", "heading", "title", "field", "lemma.g", "lemma.h", "strongs.g",
    "strongs.h", "greek", "hebrew", "louwNida".lower(), "preachingTheme".lower(),
    "date", "word", "type", "passageList".lower(), "milestone", "term",
}


@dataclass
class Term:
    """One leaf of the query: a phrase with optional scoping."""
    text: str                       # the raw term, e.g. '"faith" OR lord*'
    words: list[str] = dcfield(default_factory=list)   # folded + stemmed
    # FTS5 indexes the stored surface text, so the pre-filter needs the surface
    # forms; the exact pass is what applies stemming.  Using the stemmed forms in
    # the FTS expression silently loses every hit whose stem differs from the
    # printed word.
    raw: list[str] = dcfield(default_factory=list)
    wildcards: bool = False
    phrases: list[list[str]] = dcfield(default_factory=list)  # quoted runs (stemmed)
    raw_phrases: list[list[str]] = dcfield(default_factory=list)  # surface form
    field: str = ""                 # heading / title / bible / surface / ...
    datatype: str = ""              # strongs / lemma / person / topic / ...
    ref: canon.RefRange | None = None
    strongs: list[str] = dcfield(default_factory=list)
    lemma: str = ""
    morph: str = ""
    is_morph: bool = False
    #: A topic:/sense: request, answered from the topic marker index rather
    #: than by looking for the word in the text.
    topic: str = ""
    negated: bool = False

    def __str__(self):
        return self.text


@dataclass
class Op:
    kind: str                       # AND | OR | proximity op
    a: object = None
    b: object = None
    words: int = 0
    chars: int = 0
    #: Upper bounds, for the range forms `WITHIN 3-5 WORDS` and, now, the
    #: bounded order operators.  Declared rather than attached on demand, so
    #: that a missing bound reads as 0 -- "no window" -- instead of raising:
    #: `_distance_window` asks for these on every order operator, and an
    #: operator that had never carried one was the case that raised.
    words_hi: int = 0
    chars_hi: int = 0

    def __str__(self):
        if self.kind in (AND, OR, NOT):
            return f"({self.a} {self.kind} {self.b})"
        if self.kind == "WITHIN":
            unit = "WORDS" if self.words else "CHARS"
            n = self.words or self.chars
            return f"({self.a} WITHIN {n} {unit} {self.b})"
        return f"({self.a} {self.kind} {self.b})"


# Operator recognition is case-sensitive on purpose: an uncapitalised "and"
# in the query is the word "and".
_OPS = {
    "AND", "OR", "NOT", "NEAR", "BEFORE", "AFTER", "THEN",
    "EQUALS", "NOT_EQUALS", "NOT EQUALS", "IN", "NOT IN",
    "INTERSECTS", "NOT INTERSECTS", "WITHIN",
}

_PROX_WORDS = re.compile(r"(\d+)(?:\s*-\s*(\d+))?\s+(WORDS|CHARS|CHARS_LITERAL)\b",
                         re.I)

# Tokenise a query into terms, operators, parentheses, quotes and scopes.
#
# The dotted forms -- `lemma.g:`, `strongs.g:`, `morph.h:` -- carry their colon
# and their value here, and that is load-bearing rather than cosmetic.  When the
# dotted alternative stopped at the letter, `lemma.g:ἀγαπάω` tokenised as a scope
# `lemma.g` followed by a bare word `:ἀγαπάω`, which parsed without complaint into
# a term with no datatype at all whose text was the literal string ":ἀγαπάω".
# `strongs.g:G2316` therefore searched the stored text for ":G2316", found
# nothing, and reported zero hits with no error and no warning -- the worst
# possible failure for a scoping form, which is a request the reader addressed
# to a field the engine simply did not look at.  Requiring the colon makes the
# scope and its value one token, so the form either works or fails loudly.
_QTOK = re.compile(
    r"""\s*(?:
        (?P<lparen>\()
      | (?P<rparen>\))
      | (?P<quote>"[^"]*")
      | (?P<scope>[A-Za-z][A-Za-z0-9_]*\s*/\s*[A-Za-z][A-Za-z0-9_]*
                |[A-Za-z][A-Za-z0-9_]*\.(?:g|h|a)\s*:\s*(?:"[^"]*"|[^\s()]+)
                |(?:field\.)?[A-Za-z][A-Za-z0-9_]*\s*:\s*(?:"[^"]*"|[^\s()]+))
      | (?P<word>[^\s()"]+)
    )""",
    re.X,
)


@dataclass
class Query:
    root: object
    raw: str
    terms: list[Term] = dcfield(default_factory=list)
    has_proximity: bool = False
    has_scoping: bool = False
    has_operator: bool = False
    warnings: list[str] = dcfield(default_factory=list)

    def all_terms(self) -> list[Term]:
        return self.terms


def parse(q: str) -> Query:
    """Parse a query string into a tree of Term / Op nodes.

    Precedence: AND binds tighter than OR, and proximity binds tighter than
    AND.  Parentheses are the documented escape hatch, and the result carries
    the warnings that make an un-parenthesised mixed query predictable.
    """
    if not q or not q.strip():
        return Query(None, q)
    toks = _tokenize(q)
    st = _Parser(toks)
    tree = st.parse_or()
    if st.i < len(st.toks):
        raise QueryError(f"unexpected {st.toks[st.i][1]!r} in query")
    qy = Query(tree, q)
    qy.terms = _collect(tree)
    qy.warnings.extend(st.warnings)
    qy.has_proximity = any(getattr(n, "kind", "") in _PROX_KINDS for n in _walk(tree))
    qy.has_scoping = any(t.field or t.datatype for t in qy.terms)
    qy.has_operator = any(isinstance(n, Op) for n in _walk(tree))
    if re.search(r"\b(and|or|not|near|within|before|after|intersects|equals)\b", q) \
       and not re.search(r"\b(AND|OR|NOT|NEAR|WITHIN|BEFORE|AFTER|INTERSECTS|EQUALS)\b", q):
        qy.warnings.append(
            "Operators are only recognised in capitals: use AND, OR, NOT, NEAR, "
            "WITHIN, BEFORE, AFTER, INTERSECTS, EQUALS.")
    return qy


_PROX_KINDS = {"NEAR", "BEFORE", "AFTER", "THEN", "WITHIN", "EQUALS",
               "NOT_EQUALS", "IN", "INTERSECTS",
               # The spaced spellings supported by the parser.  They are listed
               # beside the underscore forms rather than instead of them, so both
               # parse and `NOT IN` cannot be read as a `NOT` binding an `IN`.
               "NOT EQUALS", "NOT IN", "NOT INTERSECTS"}


def _tokenize(q: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    i = 0
    n = len(q)
    while i < n:
        m = _QTOK.match(q, i)
        if not m or m.end() == i:
            out.append(("word", q[i]))
            i += 1
            continue
        i = m.end()
        if m.group("lparen"):
            out.append(("(", "("))
        elif m.group("rparen"):
            out.append((")", ")"))
        elif m.group("quote") is not None:
            out.append(("quote", m.group("quote")))
        elif m.group("scope") is not None:
            out.append(("scope", m.group("scope")))
        else:
            out.append(("word", m.group("word")))
    # A capitalised bare word that matches an operator name becomes an operator.
    fixed = []
    for kind, val in out:
        if kind == "word" and val in _OPS:
            fixed.append(("op", val))
        else:
            fixed.append((kind, val))
    # `NOT EQUALS`, `NOT IN` and `NOT INTERSECTS` are three words to naive
    # whitespace splitting, and the tokenizer has already turned the tail of
    # each into an operator of its own: `a NOT EQUALS b` arrived as `a`, NOT,
    # EQUALS, `b`, so `EQUALS` bound to the NOT and the expression either raised
    # "empty term" or built a tree nothing meant.  The query language writes
    # these spaced, so they are merged back into the single operator the parser
    # already knows how to build.  Only `NOT` + one of these three is merged;
    # `NOT` followed by a term keeps its meaning as an exclusion.
    _SPACED_NEG = ("EQUALS", "IN", "INTERSECTS")
    merged: list[tuple[str, str]] = []
    i = 0
    while i < len(fixed):
        k, v = fixed[i]
        if (k == "op" and v == NOT and i + 1 < len(fixed)
                and fixed[i + 1][0] == "op" and fixed[i + 1][1] in _SPACED_NEG):
            merged.append(("op", f"{NOT} {fixed[i + 1][1]}"))
            i += 2
            continue
        merged.append((k, v))
        i += 1
    fixed = merged
    # "WITHIN 5 WORDS x" is three tokens by naive splitting; glue the distance
    # and its unit back together so the parser sees one atom.
    glued: list[tuple[str, str]] = []
    i = 0
    while i < len(fixed):
        k, v = fixed[i]
        if (k == "word" and re.fullmatch(r"\d+(?:\s*-\s*\d+)?", v)
                and i + 1 < len(fixed) and fixed[i + 1][0] == "word"
                and fixed[i + 1][1].upper() in ("WORDS", "CHARS", "CHARS_LITERAL")):
            glued.append(("prox", f"{v} {fixed[i + 1][1]}"))
            i += 2
            continue
        glued.append((k, v))
        i += 1
    return glued


#: The smallest separation a window can ask for, per metric.
#:
#: In words, two matches at different positions are at least one word apart, so
#: one is the floor.  In characters, two matches at the *same* position would
#: have a gap of minus the word's own length, so zero is the floor: it excludes
#: a term from counting as near itself and nothing else.
_FLOOR = {"WORDS": 1, "CHARS": 0, "CHARS_LITERAL": 0}


def _set_bound(op: Op, m: re.Match) -> None:
    """Record a distance on `op` from a `<n> [ - <m> ] UNIT` match.

    A single number is a **ceiling**, and a range is a real range.  These used to
    be stored identically -- both ends set to the number written -- and that is
    what made `WITHIN n CHARS` mean a gap of *exactly* n.  The counts said so
    plainly and it had not been noticed: `WITHIN 50 CHARS` found 15 units,
    `WITHIN 500 CHARS` found 8, and `WITHIN 5000 CHARS` found none.  A wider
    window returning fewer hits is not a subtle inaccuracy, it is a window that
    is not a window.  A reader who trusted the number got a result that could
    not be reconciled with the query they typed.

    The same fix makes the bounded order operators mean what they say, because
    they come through here too: `BEFORE 9 CHARS` is now "nine characters or
    fewer, and earlier", not "the gap is nine characters, and earlier".
    """
    unit = m.group(3).upper()
    first = int(m.group(1))
    second = m.group(2)
    if second is None:
        lo, hi = _FLOOR.get(unit, 0), first
    else:
        lo, hi = first, int(second)
        if hi < lo:
            lo, hi = hi, lo
    if unit == "WORDS":
        op.words, op.words_hi = lo, hi
    else:
        op.chars, op.chars_hi = lo, hi


class _Parser:
    def __init__(self, toks):
        self.toks = toks
        self.i = 0
        #: Query-level notes, collected while parsing and handed to the `Query`.
        #: A parse that changed nothing about the tree still has to be able to
        #: tell the reader, which is what these are for.
        self.warnings: list[str] = []

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def parse_or(self):
        node = self.parse_and()
        while self.peek() == ("op", OR):
            self.i += 1
            node = Op(OR, node, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_prox()
        while True:
            k, v = self.peek()
            if k == "op" and v == AND:
                self.i += 1
                node = Op(AND, node, self.parse_prox())
            elif k == "op" and v == NOT:
                self.i += 1
                rhs = self.parse_prox()
                node = Op(NOT, node, rhs)
                if isinstance(node.a, Op) and node.a.kind == NOT and node.a.b is None:
                    pass
            elif k in (None, ")", "op") and k != "op":
                break
            elif k == "op":
                break
            elif k is None or k == ")":
                break
            else:
                # implicit AND:  `Jesus Lord` == `Jesus AND Lord`
                node = Op(AND, node, self.parse_prox())
        return node

    def parse_prox(self):
        node = self.parse_unary()
        while True:
            k, v = self.peek()
            if k != "op" or v not in _PROX_KINDS:
                break
            self.i += 1
            if v in ("BEFORE", "AFTER", "NEAR", "THEN"):
                k2, v2 = self.peek()
                if k2 == "prox":
                    m = _PROX_WORDS.fullmatch(v2)
                    if m:
                        self.i += 1
                        op = Op(v, node, self.parse_unary())
                        _set_bound(op, m)
                        if v == "THEN" and (op.words_hi or op.chars_hi):
                            # Said rather than dropped: the number cannot apply
                            # without making THEN the same operator as NEAR.
                            self.warnings.append(
                                f"THEN means the immediately following word, so "
                                f"the {v2} does not apply. Use NEAR for a window.")
                        node = op
                        continue
            if v == "WITHIN":
                k2, v2 = self.peek()
                if k2 != "prox":
                    raise QueryError(
                        "WITHIN needs a distance, e.g. WITHIN 5 WORDS")
                m = _PROX_WORDS.fullmatch(v2)
                if not m:
                    raise QueryError(
                        f"WITHIN expects '<n> WORDS' or '<n> CHARS', got {v2!r}")
                self.i += 1
                op = Op("WITHIN", node, self.parse_unary())
                _set_bound(op, m)
                node = op
                continue
            rhs = self.parse_unary()
            if v == "NOT EQUALS":
                node = Op("NOT_EQUALS", node, rhs)
            elif v == "NOT IN":
                node = Op("NOT", Op("IN", node, rhs), None)
            elif v == "NOT INTERSECTS":
                node = Op("NOT", Op("INTERSECTS", node, rhs), None)
            else:
                node = Op(v, node, rhs)
        return node

    def parse_unary(self):
        k, v = self.peek()
        # "term:(a OR b)" / "field:(a b)" -- a bare modifier followed by a group
        # scopes every term inside the group.
        if k in ("word", "scope") and isinstance(v, str) and v.endswith(":"):
            nxt = self.toks[self.i + 1] if self.i + 1 < len(self.toks) else None
            if nxt and nxt[0] == "(":
                self.i += 2
                node = self.parse_or()
                if self.peek() == (")", ")"):
                    self.i += 1
                _apply_modifier(node, v[:-1])
                return node
        if k == "(":
            self.i += 1
            node = self.parse_or()
            if self.peek() == (")", ")"):
                self.i += 1
            return node
        if k == "op" and v == NOT:
            self.i += 1
            return Op(NOT, self.parse_unary(), None)
        return self.parse_atom()

    def parse_atom(self):
        """One term: optional scope, optional quoted phrase, one bare word.

        Consecutive bare words are NOT merged into a single term.  Keeping them
        separate is what makes `Jesus Lord` an explicit AND whose parts are
        reported and highlighted individually, and what lets proximity operators
        be built from them.
        """
        parts: list[str] = []
        phrases: list[list[str]] = []
        raw_phrases: list[list[str]] = []
        while True:
            k, v = self.peek()
            if k == "quote":
                toks = [w for w, _a, _b in db.words(v.strip('"'))]
                phrases.append([db.token_key(x) for x in toks])
                raw_phrases.append([db.fold(x) for x in toks])
                self.i += 1
                continue
            if k in (None, ")", "op", "("):
                break
            if k == "scope":
                self.i += 1
                if ":" in v and not self.pending_field:
                    # strongs:G2316 / bible:"Gen 1:1" -- the scope IS the term
                    head, _, val = v.partition(":")
                    if head.lower() in _DATATYPES or "." in head.lower():
                        self.scopes.append(head.lower())
                        val = val.strip().strip('"')
                        if val:
                            parts.append(val)
                        continue
                # `field` / `field/name` are attached to the *next* term
                if self.pending_field is None:
                    self.pending_field = v
                else:
                    self.pending_scope = v
                continue
            if k == "word":
                if parts:
                    break            # a second bare word starts a new term
                parts.append(v)
                self.i += 1
                continue
            break
        if self.pending_field is not None or self.pending_scope is not None:
            self.pending_field = None
            self.pending_scope = None
        if not parts and not phrases:
            raise QueryError("empty term")
        self._raw_phrases = []
        return _make_term(parts, phrases, raw_phrases, self)

    pending_field: str | None = None
    pending_scope: str | None = None
    scopes: list = []


def _make_term(parts: list[str], phrases: list[list[str]],
                raw_phrases: list[list[str]], p: _Parser) -> Term:
    raw = " ".join(parts) + (" " + " ".join('"%s"' % " ".join(q) for q in phrases)
                             if phrases else "")
    t = Term(text=raw)
    if p.pending_scope:
        t.field = p.pending_scope
        p.pending_scope = None
    if p.pending_field:
        t.field = p.pending_field
        p.pending_field = None
    while p.scopes:
        t.datatype = p.scopes.pop(0)
        break
    if parts and not t.datatype:
        w = parts[0]
        if ":" in w:
            head, _, val = w.partition(":")
            head_l = head.lower()
            if head_l in _DATATYPES or "." in head_l:
                t.datatype = head_l
                parts[0] = val
                w = val
    # INLINE scope on a word: strongs:G2316
    if t.datatype:
        val = " ".join(parts) if parts else (
            " ".join(phrases[0]) if phrases else "")
        _apply_datatype(t, t.datatype, val)
        if t.strongs or t.is_morph or t.lemma or t.ref:
            t.words = []
        return t
    joined = " ".join(parts)
    if phrases:
        t.phrases = [p_ for p_ in phrases if p_]
        t.raw_phrases = [x for x in raw_phrases if x]
    t.wildcards = "*" in joined or "?" in joined
    toks = []
    for w in joined.split():
        toks.extend(db.words(w))
    t.words = [db.token_key(w) for w, _a, _b in toks]
    t.raw = [db.fold(w) for w, _a, _b in toks]
    if t.words and not t.datatype:
        rr = canon.parse_ref(joined)
        if rr:
            t.ref = rr
    return t


def _tk(s: str) -> list[str]:
    """Tokenise a bare string into folded+stemmed keys (db.words yields tuples)."""
    return [db.token_key(w) for w, _a, _b in db.words(s or "")]


def _apply_datatype(t: Term, dtype: str, val: str) -> None:
    d = dtype.lower()
    v = val.strip().strip('"')
    if d in ("strongs", "strong", "strongs.g", "strongs.h", "greek", "hebrew"):
        nums = []
        for part in re.split(r"[,\s]+", v):
            if not part:
                continue
            m = re.match(r"^([GHgh])0*(\d+)$", part)
            if m:
                nums.append(canon.normalise_strongs(m.group(1) + m.group(2)))
            elif part.isdigit():
                nums.append(canon.normalise_strongs(part))
        t.strongs = [n for n in nums if n]
        t.words = []
    elif d.startswith("lemma"):
        t.lemma = v
        t.words = _tk(v)
        t.raw = [db.fold(x) for x, _a, _b in db.words(v)]
    elif d in ("morph", "morphology"):
        t.morph = v
        t.is_morph = True
        t.words = []
    elif d in ("bible", "reference", "ref"):
        t.ref = canon.parse_ref(v)
        t.words = []
    elif d in ("topic", "sense"):
        # Resolved through the topic marker index rather than as a text term.
        # `topic:faith` means "the Fact book article on faith"; treating it as
        # the words "faith" returned every unit in the library containing the
        # word -- the datatype was parsed, recorded and then thrown away.
        t.topic = v
        t.words = []
    elif d in ("heading", "title", "text", "surface", "bible/content",
               "crossref", "person", "place", "sense", "culture", "event",
               "date", "word", "type", "preachingtheme", "passagelist",
               "milestone", "term"):
        if d in ("heading", "title"):
            t.field = d
        t.words = _tk(v)
    else:
        t.words = _tk(v)


def _apply_modifier(node, modifier: str) -> None:
    """Scope every Term in a subtree, e.g. term:(Jesus OR Christ)."""
    m = modifier.strip().lower()
    for n in _walk(node):
        if isinstance(n, Term):
            if m in ("term", "field"):
                continue
            if m in _DATATYPES:
                n.datatype = m
            else:
                n.field = n.field or m


def _collect(node) -> list[Term]:
    out: list[Term] = []
    for n in _walk(node):
        if isinstance(n, Term):
            out.append(n)
    return out


def _walk(node):
    if node is None:
        return
    if isinstance(node, Term):
        yield node
    elif isinstance(node, Op):
        yield node
        yield from _walk(node.a)
        if node.b is not None:
            yield from _walk(node.b)


# ==========================================================================
# Search options
# ==========================================================================

@dataclass
class SearchOpts:
    modules: list[str] = dcfield(default_factory=list)
    scope: str = ""                 # resource id | "all" | "bible" | "books" | ""
    search_bible_text: bool = True
    search_headings: bool = True
    match_case: bool = False
    match_all_forms: bool = False
    match_forms: str = ""           # per-term override, e.g. "case,form"
    reference_matching: str = "default"   # narrow | default | broad
    limit: int = 200
    offset: int = 0
    sort: str = "relevance"         # relevance | passage | resource | newest
    snippets: bool = True
    context: int = 0                # verses of context per hit
    verb: str = "words"             # words | chapter | verse | book
    fast: bool = True               # skip the exact-proximity pass
    interface: str = "local"        # local | api
    # Spelling suggestions cost a scan of the library's own vocabulary to build,
    # which is worth it for a query someone typed and worth nothing to a caller
    # that is going to discard them.  Clause search builds the same vocabulary
    # and then throws it away, which was fifteen seconds of the first clause
    # query in a session spent on advice nobody reads.
    smart: bool = True


# ==========================================================================
# Execution
# ==========================================================================

@dataclass
class Hit:
    module_id: str
    module_name: str
    module_type: str
    key: str
    label: str
    title: str
    snippet: str = ""
    snippet_html: str = ""
    text: str = ""
    score: float = 0.0
    _row: object = None
    matched: list[str] = dcfield(default_factory=list)
    #: Folded query word -> word indices where it occurs, gathered during
    #: evaluation.  Ranking needs term frequency and proximity, and the
    #: evaluation has just walked the tokens to work out whether this candidate
    #: matches at all; re-tokenising the text to ask the same question again
    #: cost twelve million extra fold() calls on one query, because the token
    #: cache was keyed differently here than it is there.
    positions: dict[str, list[int]] = dcfield(default_factory=dict)
    strongs: list[str] = dcfield(default_factory=list)
    context: list[dict] = dcfield(default_factory=list)
    rank: int = 0


def _modules(opts: SearchOpts) -> list[Module]:
    if opts.modules:
        return [m for m in (get_module(i) for i in opts.modules) if m]
    mods = list_all()
    if opts.scope == "bible":
        mods = [m for m in mods if m.is_bible]
    elif opts.scope == "books":
        mods = [m for m in mods if not m.is_bible]
    elif opts.scope and opts.scope != "all":
        m = get_module(opts.scope)
        mods = [m] if m else []
    return mods


def _fts_expr(term: Term, opts: SearchOpts) -> str:
    """Build the FTS5 MATCH expression for one leaf term."""
    parts: list[str] = []
    if term.strongs:
        return ""            # handled by the marker index, not FTS
    if term.lemma and term.datatype.startswith("lemma"):
        return ""
    if term.ref and not term.words:
        return ""

    def lit(w: str) -> str:
        s = w.replace('"', "")
        return f'"{s}"' if s else ""

    for ph in (term.raw_phrases or term.phrases):
        if ph:
            # A phrase is a single FTS5 quoted string; quoting each word
            # separately would degrade to an AND of separate terms.
            parts.append('"' + " ".join(x.replace('"', "") for x in ph) + '"')
    # The pre-filter has to reach everything the exact pass will accept, and no
    # more than it, or `fast` cannot treat the pool as the answer.
    #
    # By default the engine matches the word as written, so the exact folded
    # form is exactly right.  With "match all forms" on it matches the stem, and
    # a prefix on the stem is the cheapest way to reach every inflection --
    # `love` stems to `lov`, and an FTS expression of `"love"` puts not one of
    # the units containing only `loved` or `loving` into the candidate set, so
    # the exact pass would have nothing to widen.
    #
    # An earlier version widened unconditionally, on the reasoning that the
    # engine "always stems".  It does not: it stems only under that toggle, and
    # widening by default turned every plain word into a prefix scan over a large
    # part of the library for no gain in correctness.
    source = term.raw or term.words
    for i, w in enumerate(source):
        if w.endswith("*") or w.endswith("?"):
            core = w.rstrip("*?")
            parts.append(f'"{core.replace(chr(34), "")}"*' if core else '"a"*')
            continue
        if opts.match_all_forms and term.words:
            stem = term.words[min(i, len(term.words) - 1)]
            parts.append(f'"{stem.replace(chr(34), "")}"*')
        else:
            parts.append(lit(w))
    if not parts:
        return ""
    return " AND ".join(parts)


def _fts_query(tree, opts: SearchOpts) -> str:
    """Compile a whole boolean tree into one FTS5 expression.

    FTS5 does the coarse filtering; the exact work (proximity, wildcards with
    real semantics, set algebra over spans) happens afterwards against the unit
    text.  That split is what keeps a multi-GB library responsive.
    """
    def build(node) -> str:
        if node is None:
            return ""
        if isinstance(node, Term):
            e = _fts_expr(node, opts)
            return e
        k = node.kind
        if k == NOT:
            inner = build(node.a)
            return f'NOT ({inner})' if inner else ""
        a = build(node.a)
        b = build(node.b) if node.b is not None else ""
        if k in (AND, OR):
            if not a:
                return b
            if not b:
                return a if k == AND else ""
            if k == OR:
                return f"({a} OR {b})"
            return f"({a} AND {b})"
        # Proximity and set operators: both sides must match; distance is
        # checked exactly afterwards.
        #
        # A plain AND is used as the pre-filter rather than FTS5's own
        # `NEAR/N`.  That was tried and measured, and it lost: FTS5's NEAR builds a
        # position-list intersection per term, so a generous N -- which is what
        # correctness demands, since this app measures 48 characters and FTS5
        # counts tokens, and a token may be one character or twenty -- costs more
        # inside SQLite than the AND it replaces.  `lord NEAR faith` went from 38s
        # to 47s.  Reverted rather than kept on the strength of the idea.
        if not a or not b:
            return a or b
        return f"({a} AND {b})"
    return build(getattr(tree, "root", tree))


_TOK_CACHE: dict[str, list] = {}


def _tokens(text: str, key: str = "") -> list[tuple[str, int, int]]:
    """Tokenise a unit once per search.

    A commentary unit can be tens of thousands of characters, and a query
    evaluates every term against every candidate.  Re-tokenising per term turns
    a 5-second search into a two-minute one, so the token stream is memoised on
    the unit key for the lifetime of the query.
    """
    if key:
        hit = _TOK_CACHE.get(key)
        if hit is not None and hit is not _MISS:
            return hit
    toks = db.words(text)
    if key:
        if len(_TOK_CACHE) > 60000:
            _TOK_CACHE.clear()
        _TOK_CACHE[key] = toks
    return toks


_MISS = object()
_CAND_LIMIT = [8000]


def _hit_dict(h: "Hit") -> dict:
    return {k: v for k, v in h.__dict__.items() if not k.startswith("_")}


def _is_plain_and(query: Query) -> bool:
    """True when the tree is a conjunction of unadorned words.

    In that case FTS5 has already proven every term is present (it matched the
    conjunction of the surface forms), so the Python pass has nothing to add and
    can be skipped.  This is the common case -- a plain multi-word search -- and
    skipping it is the difference between milliseconds and minutes on a library
    holding several commentaries.
    """
    for n in _walk(query.root):
        if isinstance(n, Op) and n.kind != AND:
            return False
        if isinstance(n, Term):
            if n.wildcards or n.field or n.strongs or n.is_morph or n.lemma:
                return False
            if n.ref and not n.words and not n.phrases:
                return False
            if not n.words and not n.phrases:
                return False
    return True


#: Set by _candidates when a query resolved a topic term, so `search` knows to
#: run the exact pass.  Cleared at the start of every search.
_topic_only: list[bool] = [False]


# ------------------------------------------------------------ posindex ---
#
# The positional index can answer a proximity or phrase query outright, which
# turns the slowest query in the app from a minute into a fifth of a second.
#
# Two rules govern its use, and both exist because the alternative is silently
# wrong results rather than slow ones:
#
# **Only when it can answer completely.**  A tree is only handed to the index if
# every leaf is a plain term the index has seen, and every operator in it is one
# the index implements.  A single unknown term, or a `field:` scope, or a
# wildcard, sends the whole query down the text path instead.  A partial answer
# filtered against the full library looks right and is wrong.
#
# **The index is never the only copy.**  If it is absent, stale or being rebuilt,
# every lookup returns nothing and the text path runs exactly as before.  So the
# feature is an optimisation that can be deleted without changing any answer.
_posindex_used: list[bool] = [False]

#: Longest posting list the index will read in full.
_POSINDEX_LIMIT = 250_000


def _candidates_from_uids(query: Query, mods: list[Module],
                          opts: SearchOpts, uids: set[int]) -> dict[str, dict]:
    """Load exactly the units the index says match, and nothing else."""
    from . import posindex
    conn = db.connect()
    keys = posindex.keys_for_uids(sorted(uids))
    wanted = {m.id for m in mods}
    by_mod: dict[str, list[str]] = {}
    for module_id, key in keys:
        if module_id in wanted:
            by_mod.setdefault(module_id, []).append(key)
    out: dict[str, dict] = {}
    for mid, ks in by_mod.items():
        rows: dict[str, object] = {}
        for i in range(0, len(ks), 400):
            chunk = ks[i:i + 400]
            ph = ",".join("?" * len(chunk))
            for r in conn.execute(
                    f"SELECT * FROM unit WHERE module_id=? AND key IN ({ph})",
                    [mid, *chunk]):
                rows[r["key"]] = r
        out[mid] = rows
    return out


def _empty_result(query: Query, opts: SearchOpts, t0: float,
                  *, note: str = "") -> dict:
    warnings = ["empty query"] if note == "empty query" else []
    if note:
        warnings.append(note)
    return {"ok": True, "hits": [], "total": 0,
            "ms": round((time.time() - t0) * 1000, 1),
            "query": query.raw, "warnings": warnings,
            "groups": {}, "group_meta": {}, "operators": [], "smart": [],
            "truncated": False, "returned": 0, "limit": opts.limit}


def _posi_ready() -> bool:
    from . import posindex
    try:
        return posindex.available()
    except Exception:
        return False


def _plain_leaves(node) -> list | None:
    """The tree's leaf terms, or None if it contains anything unusual.

    Terms with a field scope, a wildcard, a datatype, a reference or a phrase are
    refused: the index knows one folded word per position and nothing about
    headings, reference ranges or patterns.
    """
    out: list[Term] = []
    for n in _walk(node):
        if isinstance(n, Term):
            if (n.field or n.wildcards or n.strongs or n.is_morph or n.lemma
                    or n.topic or n.phrases or (n.ref and not n.words)):
                return None
            if not n.words:
                return None
            out.append(n)
    return out


def _needs_the_stemmer(query) -> bool:
    """Could any other word in the library share a stem with one of these?

    The FTS pre-filter for a plain word is a prefix on its stem, which is
    deliberately wider than the answer -- so the pool cannot be taken as the
    result.  A quoted phrase is the exception: FTS5 evaluates `"a b"` as real
    adjacency, which is exactly what the engine checks, so a phrase needs no
    widening and no exact pass.
    """
    for t in query.terms:
        if t.strongs or t.is_morph or t.lemma or t.topic or t.ref:
            continue
        if t.phrases and not t.raw:
            continue
        # A plain word is matched exactly by default now, so its pre-filter is
        # exact too.  Only "match all forms" widens it -- and `fast` is already
        # off in that case.
        if t.raw and t.raw[0].endswith(("*", "?")):
            return True
    return False


def _posindex_answer(node, *, limit: int, forms: bool = False
                     ) -> set[int] | None:
    """uids satisfying the whole tree, or None when the index cannot say.

    "Cannot say" covers more than an unknown term.  A posting list longer than
    the limit is also unsayable: reading the first 32,000 of `lord`'s 57,640 and
    reporting that as the answer is not a smaller result, it is a wrong one, and
    nothing in the answer would indicate it.  So the count is taken first, and a
    term too common to read whole hands the whole query back to the text path.

    `forms` decides whether inflections count, and it is the reader's setting
    rather than a detail of this function: the engine matches the word as
    written by default and its stem under "match all forms", so the index has to
    follow it exactly.  Getting this wrong is not a rounding difference -- an
    index that always stemmed answered `love` with 12,098 units where the reader
    had asked for the literal word, and the toggle appeared to do nothing.
    """
    from . import posindex
    if not _posi_ready():
        return None
    if node is None:
        return None
    if isinstance(node, Term):
        leaves = _plain_leaves(node)
        if not leaves or len(leaves) != 1:
            return None
        w = leaves[0].raw[0] if leaves[0].raw else leaves[0].words[0]
        if not posindex.known(w):
            return None
        count = posindex.posting_count_stem if forms else posindex.posting_count
        fetch = posindex.postings_stem if forms else posindex.postings
        if count(w) > limit:
            return None
        return set(fetch(w, limit=limit)) | _possessive_postings(w, forms)
    if not isinstance(node, Op) or node.kind == NOT:
        return None
    k = node.kind
    # Distance and order come before the boolean cases, and deliberately so.
    # Answering the two sides as a boolean first -- which is what the `a` and `b`
    # below are for -- reads every posting of both words to build a set the
    # operator then throws away, because the operator needs the *positions* in
    # those postings rather than the units they name.  `lord NEAR faith` was
    # reading `lord`'s 57,640 postings twice for that reason.
    if k in ("NEAR", "THEN", "BEFORE", "AFTER", "WITHIN"):
        return _posindex_relate(node, k, limit=limit, forms=forms)
    a = _posindex_answer(node.a, limit=limit, forms=forms)
    if a is None:
        return None
    b = (_posindex_answer(node.b, limit=limit, forms=forms)
         if node.b is not None else None)
    if node.b is not None and b is None:
        return None
    if k == AND:
        return a if b is None else (a & b)
    if k == OR:
        return a if b is None else (a | b)
    # EQUALS, IN, INTERSECTS and their negations are span questions -- whether
    # one match *contains* another -- and they need the same text a positional
    # index does not keep: `IN` and `INTERSECTS` normalise a match against the
    # whole unit's length, so a unit that repeats a word has a different scale
    # for every occurrence.  They stay on the exact path rather than be
    # approximated.
    return None


def _posindex_relate(node, kind: str, *, limit: int, forms: bool
                     ) -> set[int] | None:
    """Answer one distance or order operator from the stored positions.

    Every proximity operator in the engine reduces to the same two questions --
    *where* does this word occur in this unit, and how do two lists of places
    compare -- so this is the whole of the second-order half of the search stack.

    Getting here took four attempts, and the first three explanations were wrong.
    The gap was small each time, a handful of units per query in one direction or
    the other, and small is not a standard: a confidently short list tells nobody
    a hit was dropped, which is the one failure this index exists to prevent.

    *What was actually happening.* The engine did not match a query word against
    the token -- it matched `db.token_key(token)`, the **stem**, against the
    stemmed query word, and the index held surface forms.  So `love` reached
    "loves" in the text path and not in the index, and every proximity answer came
    up short: `king NEAR kingdom` gave 483 where the engine gave 735, almost
    entirely on inflected forms.

    *Then the tokeniser.* FTS5's `unicode61` treats an apostrophe as a separator,
    so `love's` is two tokens there and one in `db.words`, which the exact pass
    reads.  The index had been built with FTS's rule -- right for a word query,
    wrong for a proximity one, and one set of postings cannot serve both -- so it
    began finding the possessive forms the exact pass rejects and came out
    *over* instead: `king NEAR kingdom` 760 against 735.

    *And then the engine moved.* A plain word is matched as written now, with the
    possessive forms added to the needle list, and "match all forms" is what
    compares stems.  Both paths had changed; only one had been told.

    So the remaining gap was closed from the other end.  `posindex.occurrences`
    makes the engine's four decisions rather than its own -- which forms count,
    where a title's positions sit, that a character gap needs word *ends*, and
    when to refuse -- and `posindex.relate` is written branch by branch against
    `_relate` so the two can be read side by side.  A query either gets the
    engine's answer in a fraction of the time, or it is declined and the text path
    runs exactly as it did before.
    """
    from . import posindex as _pi
    la, lb = _posindex_answer_leaves(node.a), _posindex_answer_leaves(node.b)
    if la is None or lb is None or not la or not lb:
        return None
    # Only a term opposite a term.  `a NEAR (b OR c)` asks whether *a* is near
    # either *b* or *c*; flattening both sides into one list of words and taking
    # the closest pair instead also accepts a *b*-*c* pair that never involves *a*
    # -- 88 units where the engine had 463.  So a subtree opposite a term stays on
    # the exact path rather than be approximated.
    if len(la) != 1 or len(lb) != 1:
        return None
    # No count check here: `occurrences` takes one per term id, over exactly the
    # posting lists it is about to read, which is both the precise question and
    # the same one answered a moment earlier by `posting_count` over the single
    # surface form -- a check that could pass while the possessive forms it also
    # reads were over the limit.
    lo_w = hi_w = lo_c = hi_c = 0
    metric = "chars"
    windowed = None
    want_lengths = False
    if kind == "WITHIN":
        # The *upper* bound is what says a window exists.  A single number is
        # stored as the ceiling with the metric's floor beneath it, so the lower
        # slot is 0 for `WITHIN 30 CHARS` and testing it here read every
        # character query as having no window at all -- which fell through to the
        # bare-order reading below and answered `WITHIN n CHARS` as `BEFORE`.
        # One number, one answer, no matter how large: that was the symptom.
        if node.words_hi:
            lo_w, hi_w = node.words, node.words_hi
            metric = "words"
        elif node.chars_hi:
            lo_c, hi_c = node.chars, node.chars_hi
            want_lengths = True
        else:
            # No bound at all, and `WITHIN 0 WORDS` counts as none: `_relate`
            # tries the word bound, then the character bound, and falls through
            # to `any(x[0] < y[0])` when both are zero.  So the engine's answer
            # to `a WITHIN 0 WORDS b` is its answer to `a BEFORE b`, and a
            # reader that computed an empty proximity window instead would
            # report nothing at all.
            kind, metric = "BEFORE", "words"
    elif kind in ("BEFORE", "AFTER", "NEAR", "THEN"):
        # The window is resolved by the same helper `_relate` reads, rather than
        # by a second set of defaults written here.  That is the whole reason a
        # written `BEFORE 9 CHARS` used to look honoured in the query builder and
        # be ignored in both evaluators: the bounds were parsed, carried on the
        # node, and then never consulted, and there was one more copy of "NEAR
        # is 48" to keep agreeing with.
        lo, hi, metric, windowed = _distance_window(node)
        # The pair goes into the slots for the metric it was measured in.  Filing
        # a character window under the word slots left the character bounds at
        # zero, so the comparison became `0 <= gap <= 0` and every bounded query
        # returned nothing -- which is why `BEFORE 30 CHARS` and bare
        # `loved NEAR world` were both empty.
        if metric == "words":
            lo_w, hi_w = lo, hi
        else:
            lo_c, hi_c = lo, hi
            want_lengths = bool(windowed)
        if kind in ("BEFORE", "AFTER") and metric == "chars":
            # Order is decided on token indices, so an operator that has an
            # order to test needs the indices whatever the window is measured
            # in.  Asking for characters alone returns 0 in that slot for every
            # position, which made the comparison `0 < 0` and answered every
            # bounded order operator "no" -- not a near miss, a total one, and
            # indistinguishable from a query that genuinely had no hits.
            metric = "both"
    # A character gap needs to know where a word *ends*, which is the one thing
    # a list of start offsets cannot say; everything else is answered from starts
    # and token indices.
    need_lengths = want_lengths
    occ_a = _pi.occurrences(la[0], forms=forms, limit=limit,
                            metric=metric, lengths=need_lengths)
    if occ_a is None:
        return None
    occ_b = _pi.occurrences(lb[0], forms=forms, limit=limit,
                            metric=metric, lengths=need_lengths)
    if occ_b is None:
        return None
    return _pi.relate(occ_a, occ_b, kind, lo_w=lo_w, hi_w=hi_w,
                      lo_c=lo_c, hi_c=hi_c,
                      windowed=windowed, by_words=(metric == "words"))


def _possessive_postings(w: str, forms: bool = False) -> set:
    """Postings of a word's possessive form, so the index sees what FTS sees.

    FTS5's `unicode61` treats an apostrophe as a separator, so `Faith's` is two
    tokens and a query for *faith* matches it; `db.words`, which the exact pass
    uses, keeps it as one.  The index has to land on one side, and it lands on
    FTS, because that is what the text path does today.

    Aligning all three -- this index, the exact pass, and the search semantics
    -- means `tokenchars` on the FTS5 table, joining the apostrophe so *faith*
    stops matching "Faith's".  That was built and measured: it works, and it is
    the right change.  It also moved `king` from 30,190 to 27,999 hits
    and left a two-unit disagreement between this index and the text path, so
    it is a decision to make on its own rather than a side effect.  See the note
    on the FTS5 schema in db.py.
    """
    from . import posindex as _pi
    out: set = set()
    for suf in ("'s", "\u2019s"):
        got = (_pi.postings_stem if forms else _pi.postings)(
            w + suf, limit=_POSINDEX_LIMIT)
        if got:
            out |= set(got)
    return out


def _posindex_answer_leaves(node) -> list[str] | None:
    leaves = _plain_leaves(node)
    if not leaves:
        return None
    # The surface form, never the stem.  `Term.words` are stemmed -- "love"
    # becomes "lov" -- and the index holds folded surface forms, so looking up
    # the stem found the few units that literally contain the letters "lov" and
    # reported them as the entire result: `love` came back as 82 hits instead of
    # nine thousand.
    return [(t.raw[0] if t.raw else t.words[0]) for t in leaves]


def search(q: str | Query, opts: SearchOpts | None = None) -> dict:
    t0 = time.time()
    _TOK_CACHE.clear()
    _PHRASE_CACHE.clear()
    _topic_only[0] = False
    opts = opts or SearchOpts()
    if isinstance(q, str):
        try:
            query = parse(q)
        except QueryError as e:
            return {"ok": False, "error": str(e), "hits": [], "total": 0,
                    "warnings": [], "ms": 0, "query": q,
                "groups": {}, "group_meta": {}}
    else:
        query = q
    mods = _modules(opts)
    if query.root is None:
        return {"ok": True, "hits": [], "total": 0, "ms": 0, "query": query.raw,
                "warnings": ["empty query"], "groups": {}, "group_meta": {}}
    if not mods:
        return {"ok": True, "hits": [], "total": 0, "ms": 0, "query": query.raw,
                "warnings": [], "groups": {}, "group_meta": {}}

    marker_terms = [t for t in query.terms if t.strongs or t.is_morph or t.lemma]
    text_terms = [t for t in query.terms if not (t.strongs or t.is_morph or t.lemma)]

    # Try the positional index first.  It answers proximity, order, phrase and
    # conjunction from postings, without reading a single unit's text -- which is
    # the difference between a minute and a fifth of a second on `lord NEAR
    # faith`.  It declines anything it cannot answer completely, and returns None
    # when it has not been built, so the text path below still runs.
    _posindex_used[0] = False
    candidates = None
    if _posi_ready() and not marker_terms and not opts.match_case:
        # High enough that ordinary content words qualify -- `lord` has 57,640
        # postings -- and low enough that "the", with nearly 400,000, declines
        # and lets the text path answer instead.
        uids = _posindex_answer(query.root, limit=_POSINDEX_LIMIT,
                                forms=bool(opts.match_all_forms))
        if uids is not None:            # not truthiness: {} means "no hits"
            _posindex_used[0] = True
            candidates = _candidates_from_uids(query, mods, opts, uids)
    if candidates is None:
        candidates = _candidates(query, text_terms, marker_terms, mods, opts)
    # A pure conjunction of plain words has already been proven by FTS5, so the
    # exact pass would only re-derive the same answer at a hundred times the cost.
    # `_topic_only` is a one-element list, and `not` on a non-empty list is
    # always False -- so this read as "never fast" and put every query back
    # through the full Python evaluation pass.  Index the flag.
    # `fast` means "the candidate pool is already the answer".  That is true of
    # an index answer, and of an FTS phrase.  It is not true of a widened
    # pre-filter for a plain word, where the pool is a superset -- which is the
    # other half of the fix: the pool used to be *narrower* than the answer, and
    # neither half was detectable from the query.
    # An index answer needs no exact pass at all: `_posindex_answer` returns
    # None for anything it cannot settle completely -- a NOT, a subtree opposite
    # a term, a term too common to read whole -- so a set it did return *is* the
    # answer, for any boolean.  Re-checking it in Python is ten thousand unit
    # texts to re-derive what the postings already said, which is what left
    # `faith OR hope` at thirty-five seconds.
    #
    # Without the index, `fast` is only honest for a query FTS5 has already
    # proven: a plain conjunction whose pre-filter is exact.  A widened prefix
    # is a superset, so it cannot be taken as the result.
    fast = (not opts.match_all_forms and not opts.match_case
            and not _topic_only[0]    # a topic term needs the exact pass
            and (_posindex_used[0]
                 or (_is_plain_and(query) and not _needs_the_stemmer(query))))
    # A module read by the scan fallback was not narrowed by FTS5, so its
    # candidate pool is an OR where FTS5 would have given an AND -- and a
    # quoted phrase, which FTS5 would have narrowed to the exact adjacency, is
    # just a bag of words.  The exact pass has to run, or the answer is wider
    # than the query asked for.
    #
    # Only when the pool really did come from the scan.  When the index
    # answered, every candidate came from postings and no module was scanned at
    # all -- and since a handful of commentaries quote Hebrew, the check fired on
    # nearly every query over a real library and put `faith` from half a second
    # to twenty-three, re-reading ten thousand unit texts to re-derive an answer
    # the index had already computed from postings.
    if (fast and not _posindex_used[0]
            and any(_module_needs_scan(m.id) for m in mods if m and m.id)):
        fast = False
    # The same fan-out is used either way: the fast path never evaluates its
    # candidates, so a larger cap costs nothing there, and using different caps
    # would make "match all forms" look like it loses hits when it only scanned
    # a smaller candidate set.
    _CAND_LIMIT[0] = 8000
    mods_by_id = {m.id: m for m in mods}
    hits = _evaluate(candidates, query, opts, mods_by_id=mods_by_id, fast=fast)
    hits = _rank(hits, query, opts)
    total = len(hits)
    page = hits[opts.offset:opts.offset + opts.limit]
    # Only the returned page pays for snippets and context.
    for i, h in enumerate(page, opts.offset + 1):
        h.rank = i
        if h._row is not None:
            m = mods_by_id.get(h.module_id)
            h.snippet, h.snippet_html = _snippet(
                h._row, query, opts, key=f"{h.module_id}|{h.key}")
            if opts.context and m is not None:
                h.context = _context(m, h._row, opts.context)
            h._row = None
    # Per-resource totals for the grouped view.  Counted over *all* matched
    # hits, not the returned page, so a group header can say how many there
    # really are when the page was cut at the limit.  Keyed by id: two
    # resources can share a name, and grouping them together would silently
    # merge two different books.
    groups: dict[str, int] = {}
    gmeta: dict[str, dict] = {}
    for h in hits:
        groups[h.module_id] = groups.get(h.module_id, 0) + 1
        if h.module_id not in gmeta:
            m = mods_by_id.get(h.module_id)
            gmeta[h.module_id] = {
                "name": h.module_name,
                "type": (m.type if m is not None else ""),
                "reader": (m.reader if m is not None else ""),
            }
    return {
        "ok": True,
        "query": query.raw,
        "hits": [_hit_dict(h) for h in page],
        "total": total,
        "returned": len(page),
        "truncated": total > opts.offset + len(page),
        "limit": opts.limit,
        "groups": groups,
        "group_meta": gmeta,
        "warnings": query.warnings,
        "ms": int((time.time() - t0) * 1000),
        "operators": sorted({n.kind for n in _walk(query.root) if isinstance(n, Op)}),
        "smart": smart_notes(query, mods, opts) if opts.smart else [],
    }


def _candidates(query: Query, text_terms: list[Term], marker_terms: list[Term],
                mods: list[Module], opts: SearchOpts) -> dict[str, dict]:
    """module_id -> {unit_key: row}.  Narrow with FTS5 and the marker index."""
    conn = db.connect()
    mids = [m.id for m in mods]
    ph = ",".join("?" * len(mids))
    out: dict[str, dict] = {m: {} for m in mids}

    def load(keys_by_mod: dict[str, list[str]]):
        for mid, keys in keys_by_mod.items():
            if not keys:
                continue
            qp = ",".join("?" * len(keys))
            for r in conn.execute(
                    f"SELECT u.* FROM unit u WHERE u.module_id=? AND u.key IN ({qp})",
                    [mid, *keys]):
                out[mid][r["key"]] = r

    # --- Strong's / lemma / morphology ---------------------------------
    if marker_terms:
        per_mod: dict[str, set[str]] = {m: set() for m in mids}
        for t in marker_terms:
            for m in mids:
                if not m:
                    continue
                if t.strongs:
                    vals = ",".join("?" * len(t.strongs))
                    kind = "strongs"
                    for r in conn.execute(
                            f"SELECT DISTINCT unit_key FROM marker WHERE module_id=? "
                            f"AND kind='{kind}' AND value IN ({vals})",
                            [m, *t.strongs]):
                        per_mod[m].add(r["unit_key"])
                elif t.is_morph and t.morph:
                    for r in conn.execute(
                            "SELECT DISTINCT unit_key FROM marker WHERE module_id=? "
                            "AND kind='morph' AND value LIKE ?",
                            (m, f"%{t.morph}%")):
                        per_mod[m].add(r["unit_key"])
                elif t.lemma:
                    for r in conn.execute(
                            "SELECT DISTINCT unit_key FROM marker WHERE module_id=? "
                            "AND kind='morph' AND value IN "
                            "(SELECT value FROM marker WHERE module_id=? AND kind='morph' "
                            " AND value LIKE ?)",
                            (m, m, f"%{t.lemma}%")):
                        per_mod[m].add(r["unit_key"])
        load({m: list(v) for m, v in per_mod.items()})
        if not any(out.values()):
            return out
        if not text_terms:
            return out

    # --- topic / sense: the Fact-book articles themselves ----------------
    # `topic:faith` is a request for the article on faith, so the answer is the
    # article -- not every unit in the library that contains the word "faith",
    # which is what this returned when the datatype was treated as a text term.
    topic_terms = [t for t in text_terms if t.topic]
    if topic_terms:
        from . import topicindex
        fbm = [m.id for m in mods if m.type in topicindex.TOPIC_TYPES]
        for t in topic_terms:
            for art in topicindex.find_articles(t.topic, fbm or None):
                mid = art["module_id"]
                if mid in out:
                    row = conn.execute(
                        "SELECT * FROM unit WHERE module_id=? AND key=?",
                        (mid, art["key"])).fetchone()
                    if row is not None:
                        out[mid][row["key"]] = row
        remaining = [t for t in text_terms if not t.topic]
        if not remaining:
            return out
        # A topic term combined with ordinary words is answered *within* the
        # topic articles, and the candidate set stops here.
        #
        # `topic:faith AND lord` means "the article on faith, which mentions
        # lord".  Letting the FTS text pass widen the candidates afterwards
        # returned every unit in the library containing "lord" -- 57,558 of them
        # -- because the topic term is satisfied by an index lookup rather than
        # by a match, and so constrains nothing once other rows are in the set.
        # The exact pass re-checks the whole tree against these article rows, so
        # the ordinary term is still verified; it is just verified against the
        # articles instead of the library.
        _topic_only[0] = True
        return out

    # --- reference ------------------------------------------------------
    refs = [t for t in text_terms if t.ref and not t.words]
    if refs and len(refs) == len(text_terms):
        for m in mids:
            for t in refs:
                for r in _ref_units(conn, m, t.ref):
                    out[m][r["key"]] = r
        if not any(out.values()):
            return out

    # --- a passage asked for alongside other terms ----------------------
    # `faith AND bible:"John 3:16"` asks for the word *in that verse*.  FTS5
    # has no notion of a verse range, and `_positions` answers a reference
    # term with None, which `_check_tree` reads as "satisfied" -- so before
    # this the passage scoped nothing at all and the query quietly meant
    # `faith` over the whole library.  This mirrors the topic branch above:
    # the passage fixes the candidates, and the exact pass, which is
    # guaranteed to run for a query carrying a reference, checks the words
    # inside them.  Only a reference the query *requires* may narrow: under
    # an OR it is one alternative, and after a NOT it has to be absent.
    req = _conjunctive_refs(query.root)
    if req and (marker_terms or len(refs) < len(text_terms)):
        resolved = 0
        for m in mids:
            per = [{r["key"]: r for r in _ref_units(conn, m, t.ref)}
                   for t in req]
            if not all(per):
                out[m] = {}
                continue
            resolved += 1
            rows = per[0]
            for got in per[1:]:
                rows = {k: v for k, v in rows.items() if k in got}
            out[m] = ({k: v for k, v in out[m].items() if k in rows}
                      if out[m] else rows)
        if resolved:
            _topic_only[0] = True    # the candidates are narrowed; check them
            return out
        # No module in this library holds that passage.  Narrowing to nothing
        # would report "no results" as though the words had been looked for
        # there and not found, so say what happened.
        query.warnings.append(
            "not found in any searched resource: "
            + " and ".join(t.text for t in req))

    # --- FTS ------------------------------------------------------------
    fts_terms = [t for t in text_terms
                 if (t.words or t.phrases) and not t.ref and not t.topic]
    if not fts_terms:
        return out
    # Modules whose text carries marks FTS5 leaves in are answered by reading
    # the text; the rest go to FTS as usual.  Both sets can be non-empty in one
    # search, because a library with a Hebrew Bible in it has English in it too.
    scanned = _scan_candidates(mods, fts_terms, opts)
    if scanned:
        load({mid: list(hits) for mid, hits in scanned.items()})
        mods = [m for m in mods if m.id not in scanned]
        if not mods:
            return out
        mids = [m.id for m in mods]
        if not mids:
            return out
    # Which tree to hand FTS5 depends on whether the exact pass will run.
    #
    # For a plain conjunction, the real tree is used so FTS5 emits a genuine
    # `AND`.  It used to be given `_FtsTree`, which is a flat OR over the term
    # list -- correct as a *superset* pre-filter, since the exact pass then
    # re-applies the boolean.  But `search()` sets fast=True for exactly these
    # plain conjunctions, skipping that pass, so the relaxed OR was taken as the
    # answer: `faith hope` returned every unit containing either word, 13,803 of
    # them, not one of which contained both.  Every multi-word search in the app
    # was silently an OR.
    #
    # Anything else keeps the relaxed tree, because there the exact pass does run
    # and the OR is only widening the candidate pool.
    if _is_plain_and(query):
        expr = _fts_query(query.root, opts)
    else:
        expr = _fts_query(_FtsTree(fts_terms), opts)
    if not expr:
        return out
    # ONE query for all the modules, not one per module.
    #
    # `module_id` is UNINDEXED in the FTS table, so a MATCH cannot be narrowed by
    # module: every query scans the whole 1.2M-unit index and throws most of it
    # away.  Doing that once per module -- 250 times for a full-library search --
    # is what made an unscoped search take twenty seconds.  A single scan with the
    # module set as a filter turns it into one pass.
    #
    # The per-module cap is kept as a window function rather than dropped, so a
    # common word still cannot let one enormous module crowd out the rest.
    ph_m = ",".join("?" * len(mids))
    try:
        # Joined on (module_id, unit_key), NOT on rowid.
        #
        # `unit_fts` is an FTS5 virtual table and its rowid is its own insertion
        # sequence; it has nothing to do with `unit.rowid`.  The two only line up
        # while both tables happen to be filled in lockstep from empty, and they
        # stop lining up the moment a module is re-imported, repaired, or added
        # out of sequence.  In this library the two were three apart.
        #
        # The damage is not a missing row.  It is a *misattributed* one: a search
        # for `faith hope` returned the article on the Church of England under the
        # title "THIS VOLUME", because FTS's row for `tCHURCH` was joined to
        # `unit`'s row number for `tTHIS`.  The reader is shown text that has
        # nothing to do with the title, the resource and the hit.  FTS itself
        # returned no such row at all; the join invented it.
        #
        # `module_id` and `unit_key` are declared UNINDEXED precisely so they can
        # be carried alongside the index and joined on like this; `unit`'s primary
        # key makes the lookup an index seek.
        rows = conn.execute(
            "SELECT * FROM ("
            "  SELECT u.*, ROW_NUMBER() OVER (PARTITION BY u.module_id "
            "                             ORDER BY rank) AS rn"
            "  FROM unit_fts f JOIN unit u"
            "    ON u.module_id = f.module_id AND u.key = f.unit_key"
            f"  WHERE unit_fts MATCH ? AND f.module_id IN ({ph_m})"
            ") WHERE rn <= ?",
            [expr, *mids, _CAND_LIMIT[0]]).fetchall()
    except Exception as e:
        # An expression FTS5 will not take, or a build without window functions.
        # Fall back to one query per module rather than to no results: slower,
        # but correct, and it is why this is a fallback and not the main path.
        _note_fallback(e)
        rows = []
        for m in mids:
            for r in _fts_fallback(conn, expr, m):
                r = dict(r)
                r["rn"] = 1
                rows.append(r)

    # Keep FTS5's own ranking order.  The query above is `ORDER BY rank`, and
    # rank in FTS5 is bm25 -- so the candidate list arrives already ordered by a
    # full BM25 pass done inside SQLite, over the whole index.  Bucketing by
    # module and reassembling throws that away, and it is what lets the
    # two-stage ranking downstream hand most of the work to SQLite.
    order = 0
    for r in rows:
        r = dict(r)
        r["_fts_order"] = order
        order += 1
        out[r["module_id"]][r["key"]] = r
    return out


def _loose(node):
    """Broaden a tree for the FTS pre-filter.

    FTS5 is only used to narrow candidates cheaply; the exact boolean, proximity
    and set-algebra evaluation happens afterwards against the unit text.  So
    every operator is relaxed to OR here.  Compiling the real tree would make
    FTS reject expressions it cannot express (proximity, EQUALS, IN) and, worse,
    a tree built as a flat AND over the term list would silently turn `a OR b`
    into `a AND b`.
    """
    if node is None:
        return None
    if isinstance(node, Term):
        return node
    a = _loose(node.a)
    b = _loose(node.b) if node.b is not None else None
    if b is None:
        return a
    return Op(OR, a, b)


class _FtsTree:
    """A throwaway tree so _fts_query can be reused for a term list."""

    def __init__(self, terms: list[Term]):
        node = terms[0]
        for t in terms[1:]:
            node = Op(OR, node, t)
        self.root = node


_FTS_FALLBACK_NOTE: list[str] = []


def _note_fallback(e: Exception) -> None:
    """Record once why the single-query path was not usable."""
    msg = f"{type(e).__name__}: {e}"
    if msg not in _FTS_FALLBACK_NOTE:
        _FTS_FALLBACK_NOTE.append(msg)


def fts_fallback_note() -> str:
    return _FTS_FALLBACK_NOTE[0] if _FTS_FALLBACK_NOTE else ""


def _fts_fallback(conn, expr: str, mid: str) -> list:
    rows = []
    try:
        for r in conn.execute(
                "SELECT u.* FROM unit_fts f JOIN unit u "
                "ON u.module_id=f.module_id AND u.key=f.unit_key "
                "WHERE f.unit_fts MATCH ? AND f.module_id=? LIMIT ?",
                (expr, mid, _CAND_LIMIT[0])):
            rows.append(r)
    except Exception:
        pass
    return rows


def _conjunctive_refs(node) -> list[Term]:
    """The reference terms every result has to fall inside.

    Only the ones reached from the root through AND count.  A reference under
    an OR is one alternative among several, and a reference under a NOT has to
    be *absent* -- on the right of `A NOT B`, or anywhere inside `NOT X` -- so
    narrowing the candidates by either would invert the query:
    `faith OR bible:"John"` is the word everywhere plus everything in John,
    and `faith NOT bible:"John"` is the word everywhere but John.
    """
    out: list[Term] = []

    def walk(n, required: bool) -> None:
        if n is None:
            return
        if isinstance(n, Term):
            if required and n.ref and not n.words and not n.phrases:
                out.append(n)
            return
        if isinstance(n, Op):
            if n.kind == OR:
                walk(n.a, False)
                walk(n.b, False)
            elif n.kind == NOT:
                if n.b is None:
                    # `NOT X`: X is what has to be *absent*, so nothing inside
                    # it is required.  Walking it as required would narrow the
                    # candidates to the very passage the query excludes.
                    walk(n.a, False)
                else:
                    walk(n.a, required)  # `X NOT Y`: X still has to be there
                    walk(n.b, False)     # and Y has to be absent
            else:                       # AND and the proximity operators
                walk(n.a, required)
                walk(n.b, required)

    walk(node, True)
    return out


def _ref_units(conn, mid: str, rr: canon.RefRange) -> list:
    """Every unit of `mid` that lies inside a reference range.

    The passage is matched on the unit's book/chapter/verse columns rather
    than on its key.  Keys are written two ways in this library -- `John.3.16`
    in the OSIS-keyed modules and `John 3:16` in the rest -- so a key match
    found one half and missed the other, and a book-only range (`bible:"John"`)
    found nothing at all, because `RefRange.refs()` does not expand a book down
    to its verses and so never produced a verse key to look for.
    """
    out: list = []
    for r in rr.refs():
        if not r.chapter:
            out.extend(conn.execute(
                "SELECT * FROM unit WHERE module_id=? AND book=?",
                (mid, r.book)))
        elif not r.verse:
            out.extend(conn.execute(
                "SELECT * FROM unit WHERE module_id=? AND book=? AND chapter=?",
                (mid, r.book, r.chapter)))
        else:
            out.extend(conn.execute(
                "SELECT * FROM unit WHERE module_id=? AND book=? AND "
                "chapter=? AND verse=?",
                (mid, r.book, r.chapter, r.verse)))
    return out


# --------------------------------------------------------------------------

def _positions(text: str, words: list[str], *, fold_only: bool = False,
               wildcards: bool = False, key: str = "",
               toks: list | None = None) -> list[tuple[int, int, int]]:
    """Matching word positions as (word_index, char_start, char_len)."""
    toks = toks if toks is not None else _tokens(text, key)
    out: list[tuple[int, int, int]] = []
    keys = [db.fold(w) for w in words] if fold_only else words
    kset = set(keys)
    for i, (w, cs, ce) in enumerate(toks):
        if fold_only:
            if db.fold(w) in kset:
                out.append((i, cs, ce - cs))
            continue
        k = db.token_key(w)
        if wildcards and ("*" in k or "?" in k):
            if _wild_match(k, keys):
                out.append((i, cs, ce - cs))
        elif k in kset:
            out.append((i, cs, ce - cs))
    return out


def _wild_match(pat: str, words: list[str]) -> bool:
    rx = "^" + "".join(
        ".*" if c == "*" else ("." if c == "?" else re.escape(c)) for c in pat) + "$"
    try:
        rx = re.compile(rx)
    except re.error:
        return False
    return any(rx.match(w) for w in words)


_PHRASE_CACHE: dict[tuple, list] = {}


def _phrase_pos(text: str, phrase: list[str], *, key: str = "",
                toks: list | None = None) -> list[int]:
    ck = (key, tuple(phrase))
    hit = _PHRASE_CACHE.get(ck)
    if hit is not None:
        return hit
    toks = toks if toks is not None else _tokens(text, key)
    keys = [db.token_key(w) for w, _a, _b in toks]
    if not phrase or not keys:
        _PHRASE_CACHE[ck] = []
        return []
    n = len(phrase)
    out = []
    for i in range(len(keys) - n + 1):
        if keys[i:i + n] == list(phrase):
            out.append(i)
    _PHRASE_CACHE[ck] = out
    return out


def _phrase_pos_uncached(text: str, phrase: list[str]) -> list[int]:
    toks = [db.token_key(w) for w, _a, _b in db.words(text)]
    if not phrase or not toks:
        return []
    return []

def _term_match(term: Term, text: str, *, match_case: bool,
                match_all_forms: bool, title: str = "", key: str = ""
                ) -> list[tuple[int, int, int]] | None:
    """Positions a term matches in a unit's text, or None if it does not."""
    if term.strongs or term.is_morph or term.lemma or term.topic:
        # Proven by an index, not by matching the text.  None tells _check_tree
        # to treat the term as satisfied.
        return None
    if term.ref and not term.words and not term.phrases:
        return None
    toks = _tokens(text, key)
    # The title's token stream is cached separately from the body's, and the key
    # has to carry the unit's identity or it carries nothing at all: `key` is
    # empty whenever a caller does not supply one, and `"|t"` alone then names the
    # *first* title seen for the whole query.  Every unit after the first was then
    # matched against the first unit's heading -- a word found in a heading that
    # was not there, and a word in the real heading that went missing, with no
    # error anywhere.  Every production caller passes `module|key`, so this only
    # bit a direct call, but a cache that is wrong when its key is empty is a trap
    # rather than a fallback, so the empty case simply does not cache.
    tkey = f"{key}|t" if key else ""
    if term.field in ("heading", "title"):
        # field: scoping -- the term is looked for in the tagged heading only
        got = _positions(title, term.words or [], wildcards=term.wildcards)
        return [(0, h[1], h[2]) for h in got]
    hits: list[tuple[int, int, int]] = []
    # The unit's title is searchable too: FTS5 indexes it, and a hymn whose
    # title is "Christ Also Loved the Church" must be findable by "loved"
    # even though the word is nowhere in the body.
    if title:
        for ph in term.phrases:
            tl = _tokens(title)
            for i in _phrase_pos(title, ph, key=tkey):
                if i < len(tl):
                    hits.append((-1, tl[i][1], len(title)))
    for ph in term.phrases:
        if not ph:
            continue
        keys = list(ph) if match_all_forms else [db.token_key(x) for x in ph]
        for i in _phrase_pos(text, keys, key=key, toks=toks):
            cs = toks[i][1] if i < len(toks) else 0
            hits.append((i, cs, sum(len(toks[j][0]) for j in
                                    range(i, min(i + len(ph), len(toks))))))
    # Three matchers, because `_positions` compares a needle against the text
    # one way or the other and the needle decides which:
    #
    #   fold_only=True   needle folded == token folded   -> the word as written
    #   fold_only=False  needle == db.token_key(token)  -> the needle must be a
    #                                                        *stem*
    #
    # `term.words` holds stems.  Passing it to the default branch therefore made
    # the default mode stem as well, which left "match all forms" with nothing
    # to do: `love` reached `loved` either way, and the toggle changed only how
    # wide the FTS pre-filter was -- an implementation detail the reader cannot
    # see and should not be able to feel.
    words = list(term.words)
    forms = term.raw or words
    # What "match all forms" looks for: the stem of the word as written.
    #
    # `term.words` already *is* that -- it is `db.token_key` of the query word --
    # and it was being stemmed again on the way to the comparison.  That is not a
    # no-op, because the stemmer is not idempotent for every word: `sense` stems
    # to `sens` and `sens` to `sen`, `verse` to `vers` and `vers` to `ver`.  So
    # the toggle was asking a different question from the one the setting names,
    # and answering it confidently: in the KJV, `verse`, `sense`, `close`,
    # `those`, `course` and `suppose` returned **nothing** with "match all forms"
    # on and 584, 40, 16, 11 and 3 with it off.  9,052 of the library's 1.4
    # million forms -- 0.65%, and the words are ordinary ones -- are affected.
    #
    # The stems come from the surface forms when there are any, and from
    # `term.words` otherwise, so a term built from a phrase rather than a word
    # does not get stemmed twice either.
    form_stems = ([db.stem(db.fold(f)) for f in forms] if term.raw
                  else list(words))
    # FTS5's `unicode61` treats the apostrophe as a separator, so `Faith's` is
    # two tokens there and a query for *faith* matches it -- while `db.words`,
    # which this pass reads, keeps it as one.  The index was already landing on
    # FTS's side, which left the three answers differing by however many
    # possessives a query touched: `love` was 9,113 through the index and 9,081
    # here.  Adding the possessive forms to the exact pass puts all three on the
    # same side instead of leaving a known disagreement in place.
    exact_needles = [w for f in forms for w in (f, f + "'s", f + "\u2019s")]
    if match_case and not match_all_forms:
        for w in exact_needles:
            hits += _positions(text, [w], fold_only=True, key=key, toks=toks)
    elif match_all_forms:
        for w in form_stems:
            hits += _positions(text, [w], fold_only=False,
                              key=key, toks=toks)
    elif term.wildcards:
        # A wildcard needle is a pattern, not a word, so it goes down the
        # stem-comparing path where `_wild_match` can apply it.
        for w in forms:
            hits += _positions(text, [db.fold(w)], wildcards=True, key=key,
                               toks=toks)
    else:
        for w in exact_needles:
            hits += _positions(text, [w], fold_only=True, key=key, toks=toks)
    if title:
        for w in (exact_needles if not (term.wildcards or match_all_forms)
                  else forms):
            if term.wildcards:
                th = _positions(title, [db.fold(w)], wildcards=True,
                                key=tkey)
            elif match_all_forms:
                # The stem, not the stem of the stem: see `form_stems`.
                th = _positions(title, [db.stem(db.fold(w)) if term.raw else w],
                                key=tkey)
            else:
                th = _positions(title, [w], fold_only=True, key=tkey)
            for h in th:
                hits.append((-1, h[1], h[2]))
    # dedupe by (word_index, char_start)
    seen = set()
    out = []
    for h in sorted(set(hits)):
        if h[:2] in seen:
            continue
        seen.add(h[:2])
        out.append(h)
    return out


def _evaluate(candidates: dict[str, dict], query: Query, opts: SearchOpts,
              mods_by_id: dict[str, Module], fast: bool = False) -> list[Hit]:
    """Filter the candidates.  Snippets and context are added later, to the page
    that is actually returned -- computing them for every candidate is what made
    a plain two-word search take minutes over a library holding commentaries."""
    hits: list[Hit] = []
    for mid, rows in candidates.items():
        if not rows:
            continue
        m = mods_by_id.get(mid)
        if m is None:
            continue
        for key, row in rows.items():
            text = row["text"] or ""
            # Positions are computed for EVERY term.  Filtering with AND
            # semantics here would break OR and NOT, which is the classic
            # way a hand-rolled search engine silently loses results.
            term_pos: dict[int, list] = {}
            if not fast:
                for t in query.terms:
                    if t.strongs or t.is_morph or t.lemma or t.topic:
                        # Already proven by the marker index; leaving the entry
                        # out makes _check_tree treat it as satisfied rather than
                        # as a failed text match.
                        continue
                    term_pos[id(t)] = _term_match(
                        t, text, match_case=opts.match_case,
                        match_all_forms=opts.match_all_forms,
                        title=row["title"] or "", key=f"{mid}|{key}")
                if not _check_tree(query.root, text, term_pos, opts, m, row):
                    continue
            matched = sorted({w for t in query.terms for w in t.words
                              if w} | {s for t in query.terms for s in t.strongs}
                              | {t.morph for t in query.terms
                                 if t.is_morph and t.morph}
                              | {db.fold(t.topic) for t in query.terms
                                 if t.topic})
            strongs = sorted({s for t in query.terms for s in t.strongs})
            # Positions for ranking, from the token stream that _term_match has
            # already built.  This is a cache hit: the key is the same one the
            # term matching used, so nothing is tokenised a second time.
            positions: dict[str, list[int]] = {}
            if term_pos:
                toks = _tokens(text, f"{mid}|{key}")
                for t in query.terms:
                    plist = term_pos.get(id(t))
                    if not plist:
                        continue
                    for entry in plist:
                        wi = entry[0]
                        if wi < len(toks):
                            w = db.fold(toks[wi][0])
                            positions.setdefault(w, []).append(wi)
                for v in positions.values():
                    v.sort()
            hit = Hit(
                module_id=mid, module_name=m.name, module_type=m.type,
                key=key, label=row["ref_label"], title=row["title"] or "",
                matched=matched, strongs=strongs, positions=positions,
                score=0.0,
            )
            hit.text = text
            hit._row = row
            hits.append(hit)
    return hits


def _row_field(row, name: str):
    """A unit column from a candidate row, or None where it has no such column.

    Candidates are `SELECT ... FROM unit` rows everywhere today, so `book`,
    `chapter` and `verse` are always there.  A row that did not carry them
    would raise out of _check_tree and fail the whole search, which is a much
    worse answer than treating the row as unaddressed.
    """
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return None


def _unit_in_ref(row, rr: canon.RefRange) -> bool:
    """Whether a unit row sits inside a reference range.

    Both bounds name the same book: `parse_ref` returns None for input that
    would cross one, such as `John 21 - Acts 2`.  A bound carrying no verse
    means "through the whole chapter", so `John 3` covers every verse of
    chapter 3 rather than only verse-less rows, and `John` covers the book
    whatever the row's chapter and verse hold.
    """
    book = _row_field(row, "book")
    if not book:
        # No address to test: a lexicon entry, an analysis node.  Treated as
        # inside, because under AND the candidates were already narrowed to the
        # passage, and a row with no address cannot be shown to lie outside it
        # either -- dropping it would lose hits no part of the query excluded.
        return True
    start, end = rr.start, rr.end
    if book != start.book:
        return False
    if not start.chapter:
        return True                       # a whole book, and the book matched
    ch = _row_field(row, "chapter")
    if ch is None:
        return False                      # a book-level row, asked for a chapter
    if ch < start.chapter or ch > end.chapter:
        return False
    v = _row_field(row, "verse") or 0
    if ch == end.chapter and end.verse and v > end.verse:
        return False
    if ch == start.chapter and start.verse and v < start.verse:
        return False
    return True


def _check_tree(node, text: str, term_pos: dict, opts: SearchOpts,
                m: Module, row) -> bool:
    """Evaluate the boolean/proximity tree exactly, against the unit text."""
    if node is None:
        return True
    if isinstance(node, Term):
        if node.strongs or node.is_morph or node.lemma or node.topic:
            return True          # satisfied by the marker/topic index
        p = term_pos.get(id(node))
        if p is None:
            # A reference carries no positions in the text: it asks where this
            # unit *sits*, and the row already knows.  Returning True
            # unconditionally was load-bearing under AND, because the
            # candidates had been narrowed to the passage by then -- but under
            # NOT nothing narrows, so `faith NOT bible:"Luke 19"` read "B is
            # present" as true and excluded every unit in the library,
            # returning nothing at all.
            if node.ref and not node.words and not node.phrases:
                return _unit_in_ref(row, node.ref)
            return True
        return bool(p)
    k = node.kind
    if k == NOT:
        if node.b is None:
            return not _check_tree(node.a, text, term_pos, opts, m, row)
        # `A NOT B` is "A present and B absent".  Evaluating it as `not A`
        # returns every verse that lacks A, which silently widens the result set
        # instead of narrowing it.
        return (_check_tree(node.a, text, term_pos, opts, m, row)
                and not _check_tree(node.b, text, term_pos, opts, m, row))
    a = _check_tree(node.a, text, term_pos, opts, m, row)
    if k == OR:
        return a or _check_tree(node.b, text, term_pos, opts, m, row)
    b = _check_tree(node.b, text, term_pos, opts, m, row) if node.b is not None else True
    if k == AND:
        return a and b
    if k in ("BEFORE", "AFTER", "NEAR", "THEN", "WITHIN", "EQUALS",
             "NOT_EQUALS", "IN", "INTERSECTS"):
        if not (a and b):
            return False
        # Five arguments, not seven: _relate works from the term positions
        # alone and never looks at the module row. Passing m and row on anyway
        # raised TypeError and took every proximity operator down with it.
        return _relate(k, node, text, term_pos, opts)
    return a and b


def _pos_of(node, text: str, term_pos: dict) -> list[tuple[int, int, int]]:
    if isinstance(node, Term):
        return term_pos.get(id(node)) or []
    a = _pos_of(node.a, text, term_pos) if node.a is not None else []
    b = _pos_of(node.b, text, term_pos) if node.b is not None else []
    if node.kind in (AND, OR):
        return sorted(set(a) | set(b))
    if node.kind == NOT:
        return []
    return sorted(set(a) | set(b))


#: The window `NEAR` means when it is written without a distance.  It is defined
#: as "technically WITHIN 48 CHARS", and it is measured on the same character
#: metric a written `CHARS` bound uses.
NEAR_CHARS = 48
#: The window `THEN` means without a distance: the next word.
THEN_CHARS = 1


def _distance_window(op: Op) -> tuple[int, int, str, bool]:
    """The question an order or distance operator actually asks.

    Lower bound, upper bound, the metric (``words`` or ``chars``), and whether
    there is a window at all.

    A bare operator keeps its own default, because that default *is* the
    documented meaning: `NEAR` is a 48-character window, `THEN` is adjacency,
    and `BEFORE` and `AFTER` are order with no distance whatsoever.

    A bound written with the operator replaces that default rather than being
    read past, which is the whole content of the difference between
    `law BEFORE prophets` and `law BEFORE 9 CHARS prophets`.  Those are
    not the same question, and answering both with "A came before B" made the
    number decorative -- a query that looked narrowed and was not, returning
    silently more than it appeared to.
    """
    kind = op.kind
    if kind == "THEN":
        # `THEN` is adjacency, and that is the whole of what it is.  A bound
        # written with it cannot be honoured without turning it into `NEAR`:
        # `THEN 20 CHARS` and `NEAR 20 CHARS` would then be the same query, and
        # the operator that means "immediately after" would mean "somewhere
        # near".  So the bound does not apply and the query says so, which is
        # better than either silently redefining the operator or silently
        # ignoring what looks like a narrowing.
        return 0, THEN_CHARS, "chars", True
    by_words = bool(op.words or op.words_hi)
    by_chars = bool(op.chars or op.chars_hi)
    if by_words:
        # Same lower bound `_relate` has always used: intervening punctuation is
        # not a word, so the nearest two matching words are one apart.
        return 1, op.words_hi, "words", True
    if by_chars:
        return op.chars, op.chars_hi, "chars", True
    if kind == "NEAR":
        return 0, NEAR_CHARS, "chars", True
    return 0, 0, "words", False


def _relate(kind: str, op: Op, text: str, term_pos: dict, opts: SearchOpts) -> bool:
    A = _pos_of(op.a, text, term_pos)
    B = _pos_of(op.b, text, term_pos)
    if not A or not B:
        return False
    n = len(text) or 1

    if kind in ("BEFORE", "AFTER", "NEAR", "THEN"):
        lo, hi, metric, bounded = _distance_window(op)
        ordered = kind in ("BEFORE", "AFTER")
        after = kind == "AFTER"

        def gap(near, far) -> int:
            if metric == "words":
                return near[0] - far[0]
            # Measured from the end of the earlier word to the start of the
            # later one, as `WITHIN n CHARS` has always been: two start offsets
            # cannot give the gap between one word's end and the next word's
            # beginning.
            return near[1] - (far[1] + far[2])

        for x in A:
            for y in B:
                if ordered:
                    near, far = (x, y) if after else (y, x)
                    # Order is decided on token indices, never on character
                    # offsets: a word can begin sooner and still come later in
                    # the sentence, and an order operator measured on the wrong
                    # one is wrong in a way no result count would reveal.
                    if not far[0] < near[0]:
                        continue
                    if not bounded or lo <= gap(near, far) <= hi:
                        return True
                else:
                    # NEAR and THEN are symmetric: either side may come first,
                    # and only one of the two orderings can give a positive
                    # gap, so both are tested rather than assuming one.
                    g = gap(y, x)
                    if g < 0:
                        g = gap(x, y)
                    if lo <= g <= hi:
                        return True
        return False
    if kind == "WITHIN":
        # The *upper* bound says a window exists; the lower one is the metric's
        # floor and is 0 for `WITHIN 30 CHARS`.  Testing the lower bound asked
        # "does this query have a window?" and answered no for every single
        # character window, so `WITHIN n CHARS` fell through to the order-only
        # line below and returned the same count for every n.  Identical counts
        # across 1, 50 and 500 characters is what gave it away.
        lo_w, hi_w = op.words, op.words_hi
        lo_c, hi_c = op.chars, op.chars_hi
        if hi_w:
            # WORDS: intervening punctuation is ignored, so the minimum
            # separation between two matching words is 1.
            return any(lo_w <= (y[0] - x[0]) <= hi_w for x in A for y in B)
        if hi_c:
            # CHARS: separators and markers count, so the minimum separation
            # between two words is 2.
            return any(lo_c <= (y[1] - (x[1] + x[2])) <= hi_c
                       for x in A for y in B)
        return any(x[0] < y[0] for x in A for y in B)
    if kind == "EQUALS":
        return any(x[:2] == y[:2] for x in A for y in B)
    if kind == "NOT_EQUALS":
        return not any(x[:2] == y[:2] for x in A for y in B)
    if kind == "IN":
        return any(_contains(span(x), span(y)) for x in A for y in B)
    if kind == "INTERSECTS":
        return any(_overlaps(span(x), span(y)) for x in A for y in B)
    return False


def _contains(a, b) -> bool:
    return a[0] >= b[0] and a[1] <= b[1]


def _overlaps(a, b) -> bool:
    return a[0] < b[1] and b[0] < a[1]


# --------------------------------------------------------------------------

def _snippet(row, query: Query, opts: SearchOpts, key: str = "") -> tuple[str, str]:
    text = row["text"] or ""
    # The title is optional context for `_term_match`, not a requirement, and a
    # caller that selected only the columns it needed has no `title` to give.
    # `sqlite3.Row` raises IndexError on a key it was not selected with rather
    # than yielding None, so this made every snippet of a narrow query raise
    # instead of return -- the self-test's `SELECT text FROM unit` included.
    try:
        title = row["title"] or ""
    except (IndexError, KeyError):
        title = ""
    # Wikisource text is stored with its MediaWiki markup still on it, so a
    # snippet cut from it shows the reader `{{GHGheb|text=אֵת}}` where the
    # article says אֵת.  Cleaning is done per chunk rather than once over the
    # window, because the character offsets below were computed against the raw
    # text and cleaning the whole thing first would move every <mark>.
    def clean(s: str) -> str:
        return markup.strip_wikitext(s) if s else s

    if not opts.snippets:
        return clean(text[:400]), markup.esc(clean(text[:400]))
    positions: list[tuple[int, int, int]] = []
    for t in query.terms:
        p = _term_match(t, text, match_case=opts.match_case,
                        match_all_forms=opts.match_all_forms,
                        title=title, key=key)
        if p:
            positions.extend(p)
    if not positions:
        s = clean(text[:260])
        return s, markup.esc(s)
    positions.sort()
    # group nearby hits into windows
    windows: list[list[tuple[int, int, int]]] = []
    for p in positions:
        if windows and p[0] - windows[-1][-1][0] <= 6:
            windows[-1].append(p)
        else:
            windows.append([p])
    if len(windows) > 1:
        best = max(windows, key=lambda w: len(w))
        windows = [best]
    w = windows[0]
    lo = max(0, w[0][1] - 70)
    hi = min(len(text), w[-1][1] + w[-1][2] + 90)
    pre = "..." if lo > 0 else ""
    post = "..." if hi < len(text) else ""
    # html with <mark> on the matched words
    marks = sorted((p[1], p[1] + p[2]) for p in w)
    plain_parts: list[str] = []
    out: list[str] = []
    cur = lo
    for a, b in marks:
        a2, b2 = max(a, lo), min(b, hi)
        if a2 >= b2:
            continue
        plain_parts.append(clean(text[cur:a2]))
        out.append(markup.esc(clean(text[cur:a2])))
        out.append(f'<mark>{markup.esc(clean(text[a2:b2]))}</mark>')
        plain_parts.append(clean(text[a2:b2]))
        cur = b2
    tail = clean(text[cur:hi])
    plain_parts.append(tail)
    out.append(markup.esc(tail))
    return pre + "".join(plain_parts) + post, pre + "".join(out) + post


def _context(m: Module, row, n: int) -> list[dict]:
    from . import library as lib
    conn = db.connect()
    out = []
    if m.reader == "verse" and row["book"]:
        lo = max(1, (row["verse"] or 1) - n)
        hi = (row["verse"] or 1) + n
        for r in conn.execute(
                "SELECT key, ref_label, text FROM unit WHERE module_id=? AND book=? "
                "AND chapter=? AND verse BETWEEN ? AND ? ORDER BY verse",
                (m.id, row["book"], row["chapter"], lo, hi)):
            out.append({"key": r["key"], "label": r["ref_label"],
                        "text": (r["text"] or "")[:400],
                        "current": r["key"] == row["key"]})
    else:
        for r in conn.execute(
                "SELECT key, ref_label, title FROM unit WHERE module_id=? "
                "AND ord BETWEEN ? AND ? ORDER BY ord",
                (m.id, (row["ord"] or 1) - n, (row["ord"] or 1) + n)):
            out.append({"key": r["key"], "label": r["ref_label"],
                        "title": r["title"] or "",
                        "current": r["key"] == row["key"]})
    return out


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------

# --------------------------------------------------------------- BM25 -----
#
# The ranking the module docstring promises, and the terms it uses are BM25's:
#
#   score(D,Q) = SUM over t in Q   IDF(t) * ( tf * (k1 + 1) ) / ( tf + k1 * (1 - b + b * len(D)/avgdl) )
#
# with IDF(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5)).
#
# Three things in the previous scoring were not this, and one of them made
# results worse rather than merely naive:
#
#   * **There was no IDF at all.**  Every term contributed the same regardless of
#     how common it is, so a hit on "the" outranked a hit on "ephemeral" -- the
#     whole point of the measure.
#   * **Term frequency was linear and uncapped.**  A word repeated forty times
#     counted forty times as much.  BM25 saturates: the fortieth "lord" in a
#     verse tells you far less than the first, and the formula's numerator grows
#     while the denominator grows faster, so the curve flattens.
#   * **The length prior had the sign backwards.**  It added `0.35 * len(text)`,
#     so the longer a unit the higher it scored, up to a cap -- a six-thousand
#     character commentary note outranked a tight verse for matching exactly as
#     many query terms.  BM25's length normalisation is a *divisor*; a long unit
#     is harder to match by chance.  That term is now a negative.
#
# Document frequencies come from SQLite's own FTS5 vocabulary table, which is a
# view over the existing index rather than another copy of it: no reindex, no
# extra storage, and the counts are the ones the matcher actually uses.  It is
# created on first use and the numbers are cached for the process, because df
# does not change while the app is running.
#
# Page numbers and locators do not exist here, so a hit carries no positional
# bonus the way a page-accurate engine would.  Proximity is scored from real
# token distances instead, which is a different thing and is labelled as such.

#: How many candidates get the exact BM25 treatment.  See _rank.
_SCORE_WINDOW = [400]

_K1 = 1.2          # BM25 term-frequency saturation
_B = 0.75          # BM25 length normalisation
_PROX_WEIGHT = 1.4 # how much a genuine proximity match is worth

_stat_cache: dict = {}
_idf_cache: dict[str, float] = {}
_vocab_ready: list[bool] = [False]


def _ensure_vocab() -> bool:
    """Attach SQLite's vocabulary view to the FTS index.  Idempotent."""
    if _vocab_ready[0]:
        return True
    try:
        db.connect().execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS unit_fts_vocab "
            "USING fts5vocab(unit_fts, 'row')")
        _vocab_ready[0] = True
    except Exception as e:
        _note_fallback(e)
        _vocab_ready[0] = False
    return _vocab_ready[0]


def _corpus_stats() -> tuple[int, float]:
    """(N, average document length in words) for the indexed corpus.

    N is the number of units, because a unit -- a verse, a note, an article -- is
    what the user is searching over and therefore what counts as a document.
    """
    if "stats" in _stat_cache:
        return _stat_cache["stats"]
    conn = db.connect()
    try:
        # Persisted rather than recomputed.  AVG(word_count) has to read all
        # 1.2 million unit rows -- about three seconds -- and it only changes
        # when something is installed, so it is cached in `meta` and refreshed
        # by the indexer.  Recomputing it per search meant every fresh process
        # paid three seconds before ranking a single hit.
        row = conn.execute(
            "SELECT value FROM meta WHERE key='bm25_corpus'").fetchone()
        if row:
            n_s, avg_s = row["value"].split(",", 1)
            _stat_cache["stats"] = (int(n_s), float(avg_s))
            return _stat_cache["stats"]
        n = conn.execute("SELECT COUNT(*) c FROM unit").fetchone()["c"]
        avg = conn.execute(
            "SELECT AVG(COALESCE(word_count,0)) a FROM unit").fetchone()["a"]
        conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('bm25_corpus',?)",
            (f"{int(n)},{float(avg or 0.0)}",))
        conn.commit()
    except Exception:
        n, avg = 0, 0.0
    # A corpus with no word_count recorded still has to score sensibly, so fall
    # back to a plausible average rather than dividing by zero.
    avg = float(avg or 0.0) or 120.0
    _stat_cache["stats"] = (n or 1, avg)
    return _stat_cache["stats"]


def doc_freq(term: str) -> int:
    """Units containing `term`.  0 when unknown -- never a guess."""
    t = db.fold(term or "")
    if not t:
        return 0
    if t in _idf_cache:
        return _idf_cache[t]
    df = 0
    if _ensure_vocab():
        try:
            row = db.connect().execute(
                "SELECT doc FROM unit_fts_vocab WHERE term=?", (t,)).fetchone()
            if row is not None:
                df = int(row["doc"] or 0)
        except Exception:
            df = 0
    _idf_cache[t] = df
    return df


def idf(term: str) -> float:
    """Inverse document frequency, BM25's form."""
    n, _avg = _corpus_stats()
    df = doc_freq(term)
    if df <= 0:
        # An unknown term is treated as maximally rare rather than dropped, so a
        # word the vocabulary has not seen still contributes instead of silently
        # scoring zero and pushing its hits down the list.
        df = 0
    return math.log(1.0 + (n - df + 0.5) / (df + 0.5))


def _term_positions(toks: list, wanted: set[str]) -> dict[str, list[int]]:
    """Folded-token positions for every wanted term, in one pass.

    One tokenisation per hit rather than one per term: a candidate that matched
    six query terms should cost one walk of its text, not six.
    """
    out: dict[str, list[int]] = {}
    if not wanted:
        return out
    for i, (w, _cs, _cl) in enumerate(toks):
        f = db.fold(w)
        if f in wanted:
            out.setdefault(f, []).append(i)
    return out


def _proximity_bonus(pos: dict[str, list[int]]) -> float:
    """Reward query terms that actually sit next to each other.

    BM25 has no notion of this: it scores a document for containing the words
    regardless of whether they are adjacent.  But "faith" and "works" three
    hundred words apart is not the same result as "faith works", and a search
    engine that cannot tell them apart is not doing what the operator asked.
    The measure is the smallest gap between the two closest lists, saturating so
    that adjacent is worth a lot and twenty words apart is worth almost nothing.
    """
    lists = [v for _k, v in sorted(pos.items()) if v]
    if len(lists) < 2:
        return 0.0
    best = None
    for a in range(len(lists)):
        for b in range(a + 1, len(lists)):
            la, lb = lists[a], lists[b]
            i = j = 0
            while i < len(la) and j < len(lb):
                gap = lb[j] - la[i]
                if gap < 0:
                    i += 1
                else:
                    if best is None or gap < best:
                        best = gap
                    if gap == 0:
                        return 1.0
                    j += 1
    if best is None:
        return 0.0
    return 1.0 / (1.0 + best / 4.0)


def _bm25_one(tf: int, length: float, avgdl: float, term_idf: float) -> float:
    if tf <= 0:
        return 0.0
    norm = 1.0 - _B + _B * (length / avgdl if avgdl else 1.0)
    return term_idf * (tf * (_K1 + 1.0)) / (tf + _K1 * norm)


def _rank(hits: list[Hit], query: Query, opts: SearchOpts) -> list[Hit]:
    if not hits:
        return hits
    if opts.sort == "resource":
        for h in hits:
            h.score = 0.0
        return sorted(hits, key=lambda h: (h.module_name, h.label))
    if opts.sort == "passage":
        def key(h):
            b = canon.parse_osis_id(h.key)
            return (b.sort_key if b else (999, 0, 0))
        return sorted(hits, key=key)
    # Every folded query word, with its IDF, computed once for the whole result
    # set rather than per hit.
    wanted: set[str] = set()
    for t in query.terms:
        if t.topic:
            wanted.add(db.fold(t.topic))
        for w in (t.words or []):
            wanted.add(db.fold(w))
        for ph in (t.phrases or []):
            for w in ph:
                wanted.add(db.fold(w))
    wanted.discard("")
    idfs = {w: idf(w) for w in wanted}

    n_units, avgdl = _corpus_stats()
    n_terms = len(query.terms) or 1

    # Two-stage scoring.
    #
    # Exact BM25 needs the token positions of every query word inside every
    # candidate, which means walking that candidate's text.  Doing it for ten
    # thousand candidates is what made a one-word search take fifteen seconds --
    # and it is wasted work, because nobody looks past the first few hundred
    # results and FTS5 has already bm25-ordered the whole set for us, inside
    # SQLite, where it is fast.
    #
    # So: a cheap score using only what is already in hand (which terms matched,
    # a title hit, the resource type, whether it is Strong's-tagged) ranks
    # everything, and the exact formula runs on the best few hundred.  This is an
    # ordinary retrieval arrangement -- a cheap first pass over everything and an
    # exact rerank of the head -- and the boundary is stated rather than hidden:
    # beyond the window, ordering is the cheap score, not full BM25.
    if len(hits) > _SCORE_WINDOW[0]:
        def cheap(h):
            c = 0.0
            c += 6.0 * min(1.0, len(h.matched) / n_terms)
            if h.title and any(db.fold(w) in db.fold(h.title) for w in h.matched):
                c += 3.0
            if h.strongs:
                c += 1.0
            if h.module_type in ("Bible", "Commentary"):
                c += 0.5
            try:
                order = h._row["_fts_order"] if h._row is not None else 0
            except (TypeError, KeyError, IndexError):
                order = 0
            return (-c, order)
        # Partitioned by index.  `h not in head` looks equivalent and is not:
        # Hit is a dataclass, so `in` compares every field including the whole
        # text of each unit, which is quadratic in the number of hits and
        # compares thousands of characters per test.
        order_idx = sorted(range(len(hits)), key=lambda i: cheap(hits[i]))
        n_head = _SCORE_WINDOW[0]
        head = [hits[i] for i in order_idx[:n_head]]
        # Everything outside the window is KEPT, not dropped.  Dropping it made
        # `faith` report 400 results instead of the 10,118 that actually match,
        # which is the sort of quiet truncation that makes a search engine lie
        # about its own corpus.  They are simply scored below the window.
        tail = [hits[i] for i in order_idx[n_head:]]
        n_tail = len(tail)
        for i, h in enumerate(tail):
            h.score = 0.0
        # Descending, and strictly below every exactly-scored hit.
        floor = min((h.score for h in head), default=0.0)
        for i, h in enumerate(tail):
            c = cheap(h)[0] * -1.0                       # cheap score, larger better
            frac = (n_tail - i) / (n_tail + 1.0)
            h.score = round((floor * 0.5) * frac * min(1.0, max(0.0, c / 10.0)), 6)
        hits = head + tail
    # Proximity is weighted fully when a proximity operator was used, and more
    # gently otherwise -- two query words sitting next to each other is still a
    # better result, just not what was asked for.
    prox_w = _PROX_WEIGHT if query.has_proximity else _PROX_WEIGHT * 0.35

    for h in hits:
        pos = {w: p for w, p in h.positions.items() if w in wanted}
        # In fast mode FTS5 has already proved presence without walking the
        # text, so there are no positions to use.  A single occurrence is the
        # honest assumption there: not evidence of frequency, and not a claim of
        # proximity either.
        if not pos:
            pos = {w: [0] for w in wanted
                   if any(db.fold(x) == w for x in h.matched)}

        # -- the BM25 sum proper
        length = 0.0
        if h._row is not None:
            try:
                length = float(h._row["word_count"] or 0)
            except (TypeError, ValueError, IndexError, KeyError):
                length = 0.0
        if not length:
            length = float(len(h.text or "")) / 6.0
        s = 0.0
        for w, wl in pos.items():
            s += _bm25_one(len(wl), length, avgdl, idfs.get(w, 0.0))

        # -- coverage: a unit that matched every query term beats one that
        #    matched a common word and one rare word.  BM25 alone does not know
        #    about AND, so this restores the distinction the operator asked for.
        matched_terms = sum(1 for t in query.terms
                            if any(db.fold(w) in pos for w in (t.words or [])))
        coverage = matched_terms / n_terms
        s *= (0.5 + 0.5 * coverage)

        # -- proximity
        s += prox_w * _proximity_bonus(pos)

        # -- reference context: a title or heading hit outranks a body hit.
        if h.title:
            tf_title = db.fold(h.title)
            if any(w in tf_title for w in pos):
                s += 0.35 * max(idfs.get(w, 0.0) for w in pos if w in tf_title)

        # -- small secondary priors, deliberately minor now that the term
        #    statistics are doing the work.
        if h.strongs:
            s += 0.25
        if h.module_type in ("Bible", "Commentary"):
            s += 0.15
        h.score = round(s, 4)
        h.context = [{"prox": round(_proximity_bonus(pos), 3)}] if pos else []
    # Ties broken by the shorter unit: equal term weight in half the words is the
    # better answer, and an earlier version had the sign of this backwards.
    return sorted(hits, key=lambda h: (-h.score, len(h.text or "")))


# ==========================================================================
# "Smart" without a language model
# ==========================================================================

def surface_counts(mods: list[Module]) -> dict[str, int]:
    """The library's words *as written*, with how often each occurs.

    Folded, but not stemmed.  `_vocab` is built with db.token_key, which stems,
    because the query parser stems and the two have to agree.  That makes it
    useless for spelling: a vocabulary of stems contains "pray", "hop" and
    "clos", so a reader who typed "pryaer" is told the nearest word is "pray" --
    an internal form, not a word anyone types.  Stemming also destroys the
    distinction the check turns on, since "prayer" and "prays" both reduce to
    "pray" while a misspelling reduces to something else ("pryaer" -> "prya").

    Three sources, because a spelling check is only as good as its vocabulary:

    * the surface forms on Strong's markers of tagged modules;
    * the words of short units, which is where ordinary English prose lives;
    * the head of every entry in a lexicon or grammar.  This is the one that
      matters for the original languages: an English Bible renders the Greek for
      love as *love*, so without it the reader who types "agape" is told it is
      misspelled and offered a Hebrew noun two edits away.  A lexicon entry is
      longer than the 400-character cutoff the prose scan uses, so only its
      opening is read -- where every one of these formats puts its headword.

    The counts are not decoration.  Edit distance alone cannot choose between
    two words that are both one edit away: "hoep" is one deletion from "hep" and
    one transposition from "hope", and they tie.  Every real spell-checker
    breaks that tie on frequency, and the frequency is right here.

    Cached against the set of module ids and the library generation, which is
    bumped whenever the library's words change -- installed, re-indexed, removed
    -- so the cache is invalidated by the event that makes it wrong rather than
    by a clock.  The hour is now only a backstop.  This is expensive to build:
    four seconds, almost all of it tokenizing 166,000 text blobs in Python,
    since the three SQL passes together take only 0.4 seconds.  Built by
    prewarm_spelling() at startup rather than inside the hint.
    """
    conn = db.connect()
    key = ("surface-counts", db.GENERATION) + tuple(sorted(m.id for m in mods))
    hit = _VOCAB_CACHE.get(key)
    if hit is not None and time.time() - hit[0] < 3600:
        return hit[1]
    counts: dict[str, int] = {}

    def add(text: str) -> None:
        for w, _a, _b in db.words(text or ""):
            k = db.fold(w)
            if len(k) > 2:
                counts[k] = counts.get(k, 0) + 1

    ids = [m.id for m in mods]
    if ids:
        marks = ",".join("?" * len(ids))
        for r in conn.execute(
                f"SELECT surface FROM marker WHERE module_id IN ({marks}) "
                "AND kind='strongs' LIMIT 40000", ids):
            add(r["surface"])
        for r in conn.execute(
                f"SELECT text FROM unit WHERE module_id IN ({marks}) "
                "AND length(text) < 400 LIMIT 6000", ids):
            add(r["text"])
    # Headwords, from lexica and grammars only.  NOT from the Dictionary
    # modules: those are English dictionaries, and Webster alone is 114,712
    # entries, so they cost the most and add the least -- the words in them are
    # ordinary English, which the prose scan above already collects.  The lexica
    # are what the prose scan is missing, because a lexicon entry is longer than
    # its 400-character cutoff.  Measured: 10 modules, 68,116 entries; with
    # the other two sources the vocabulary is 79,599 words.
    #
    # ORDER BY rather than a bare LIMIT, so a ceiling truncates the same entries
    # every time instead of an arbitrary set that varies with the query plan.
    # The index it sorts on (module_id, ord) already exists, so this costs no
    # extra sort.
    ref_ids = [m.id for m in mods if m.type in ("Lexicon", "Grammar")]
    for start in range(0, len(ref_ids), 300):
        chunk = ref_ids[start:start + 300]
        if not chunk:
            continue
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(
                f"SELECT substr(text,1,120) t FROM unit "
                f"WHERE module_id IN ({marks}) ORDER BY module_id, ord "
                f"LIMIT 120000", chunk):
            add(r["t"])
    _VOCAB_CACHE[key] = (time.time(), counts)
    return counts


def surface_vocab(mods: list[Module]) -> set[str]:
    """The keys of surface_counts() — membership only, no frequencies."""
    return set(surface_counts(mods))


# A Strong's dictionary entry opens with its headword in the original script,
# then the transliterations, then the pronunciation in braces:
#
#     \n \u1f00\u03b3\u03ac\u03c0\u03b7\n\n ajgavph   agape   {ag-ah'-pay} \n
#
# and is keyed by its own Strong's number ("00026").  Both the Strong's
# transliteration and the dictionary's lemma are kept, since a reader may type
# either and "ajgavph" is the form Strong's concordance itself prints.
_HEADWORD_RUN = re.compile(r"[A-Za-z][A-Za-z'\u2019]*")

_HEADWORD_CACHE: dict = {}


def _strongs_prefix(script: str) -> str:
    """G for a Greek headword, H for a Hebrew one, "" for anything else."""
    for ch in script:
        o = ord(ch)
        if not ch.isalpha():
            continue
        if 0x370 <= o <= 0x3FF or 0x1F00 <= o <= 0x1FFF or o == 0x3F2:
            return "G"
        if 0x5D0 <= o <= 0x5EA:
            return "H"
        return ""
    return ""


def headword_strongs(mods: list[Module]) -> dict[str, tuple[str, str]]:
    """Lexicon headwords mapped to their Strong's number.

    Returns ``folded headword -> (number, original script)``, so "agape" gives
    ("G0026", "\u1f00\u03b3\u03ac\u03c0\u03b7").

    This exists because no other route can reach those words.  `_strongs_for`
    reads `_surface_index`, which is built from `marker` rows, and the Strong's
    dictionaries emit none -- both report has_strongs 0, because a dictionary
    *defines* the numbers rather than tagging Bible text with them.  An English
    Bible renders the Greek noun as "love", so no Bible in the library has the
    surface form "agape" for it and the word appears in no surface index however
    they are queried.  The reader who types "agape" is told nothing at all.

    The number comes from `unit.key`, which is the entry's own number, NOT from
    the "see GREEK for N" line that closes each entry.  That line looks like a
    self-reference and is not one: it cites the word the entry is derived from,
    so reading it hands out \u03bb\u03cc\u03b3\u03bf\u03c2 as G3004 when it is keyed 03056 and is
    G3056 everywhere else in the library.  Verified against the Bible markers
    themselves: keyed 03056 \u03bb\u03cc\u03b3\u03bf\u03c2, keyed 04102 \u03c0\u03af\u03c3\u03c4\u03b9\u03c2 and keyed 05485 \u03c7\u03ac\u03c1\u03b9\u03c2 all
    match the numbers their Bible modules tag.

    Entries are detected by shape, not by module id, so this survives a module
    being re-imported under another name and cannot mistake an unrelated lexicon
    for a Strong's dictionary.  Both conditions have to hold: a numeric key, and
    a braced pronunciation after a headword in a known script.

    That shape currently matches Strong's Greek Bible Dictionary (5,487 of its
    5,742 entries; the rest are the front matter) and nothing else.  Strong's
    Hebrew Bible Dictionary has 22,079 units but no parseable entries at all --
    no numeric keys, and the "entries" are the file's preamble, one sentence per
    row -- so it contributes nothing and is left out rather than guessed at.  Its
    numbers are unavailable until that module is re-imported, which is the same
    missing-source problem that leaves 178 module folders empty.
    """
    key = ("headword-strongs", db.GENERATION) + tuple(sorted(m.id for m in mods))
    hit = _HEADWORD_CACHE.get(key)
    if hit is not None and time.time() - hit[0] < 3600:
        return hit[1]
    out: dict[str, tuple[str, str]] = {}
    ref_ids = [m.id for m in mods if m.type in ("Lexicon", "Grammar")]
    conn = db.connect()
    # "key NOT GLOB '*[^0-9]*'" is SQLite's idiom for "every character is a
    # digit".  Scoped to lexica so the module_id index does the work: about 68,000
    # entries examined, 5,487 kept.  Only the first 140 characters are read,
    # which is where the whole headword run lives.
    for start in range(0, len(ref_ids), 300):
        chunk = ref_ids[start:start + 300]
        if not chunk:
            continue
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(
                f"SELECT key, substr(text,1,140) t FROM unit "
                f"WHERE module_id IN ({marks}) AND key <> '' "
                f"AND key NOT GLOB '*[^0-9]*' "
                f"AND length(key) <= 5 ORDER BY module_id, ord", chunk):
            num_raw = r["key"] or ""
            head = r["t"] or ""
            brace = head.find("{")
            if brace < 0 or "}" not in head[brace:brace + 40]:
                continue
            script = ""
            for tok in head[:brace].split():
                if any(ord(ch) > 127 for ch in tok) and any(ch.isalpha() for ch in tok):
                    script = tok.strip(".,;:*()")
                    break
            prefix = _strongs_prefix(script)
            if not prefix:
                continue
            num = prefix + num_raw.lstrip("0").zfill(4)
            # The headword run is what sits between the script word and the
            # pronunciation.  Brackets are Strong's marker for an inserted
            # initial vowel and are part of the word, not a separator: "a[logos"
            # is \u1f04\u03bb\u03bf\u03b3\u03bf\u03c2, and splitting on the bracket instead of removing it
            # emits a bogus headword "logos" under \u1f04\u03bb\u03bf\u03b3\u03bf\u03c2's number.
            run = head[:brace].replace("[", "").split(script, 1)[-1]
            for tok in _HEADWORD_RUN.findall(run):
                k = db.fold(tok)
                # Under three characters is an article or a fragment of the
                # pronunciation, not a headword: otherwise the Greek entry for
                # "a" would claim that number for every reader who typed it.
                if len(k) < 3 or k in out:
                    continue
                out[k] = (num, script)
    _HEADWORD_CACHE[key] = (time.time(), out)
    return out


_LEN_BUCKETS: dict[int, tuple] = {}


def _near_candidates(counts: dict[str, int], word: str,
                     max_d: int) -> set[str]:
    """The words close enough in length to be a typo of `word`.

    Named `_near_candidates` and not `_candidates` because this module already
    has a `_candidates()` -- the five-argument one that narrows a parsed query
    to candidate rows -- and a later definition of the same name silently
    replaces it.  Nothing about that failure announces itself: the spelling
    helper works perfectly and the search engine raises "takes 3 positional
    arguments but 5 were given" somewhere else entirely.

    The vocabulary is ~80,000 words and this runs on every debounced
    keystroke.  Narrowing by length first is exact rather than approximate:
    _closest already discards any candidate whose length differs by more than
    max_d, so those words were never scored.  Buckets are cached against the
    counts object, so they are built once per vocabulary.
    """
    key = id(counts)
    got = _LEN_BUCKETS.get(key)
    if got is None or got[0] is not counts:
        by_len: dict[int, set[str]] = {}
        for w in counts:
            by_len.setdefault(len(w), set()).add(w)
        _LEN_BUCKETS.clear()
        _LEN_BUCKETS[key] = (counts, by_len)
        got = _LEN_BUCKETS[key]
    by_len = got[1]
    out: set[str] = set()
    for n in range(max(1, len(word) - max_d), len(word) + max_d + 1):
        bucket = by_len.get(n)
        if bucket:
            out |= bucket
    return out


_SPELL_READY: list[bool] = [False]


def spelling_ready() -> bool:
    """Whether the spelling tables have been built and hints can be answered."""
    return _SPELL_READY[0]


def prewarm_spelling(mods: list[Module]) -> bool:
    """Build the spelling tables off the request path.  Returns True on success.

    surface_counts() costs ~4 seconds and _surface_index() ~4, and between them
    they were being built synchronously inside the search box's as-you-type
    hint -- so the first word typed after a restart froze the tab for eight
    seconds before caching the result for an hour.  Warming them at startup
    turns that one visible stall into a background thread nobody waits on.

    Only the as-you-type endpoint consults spelling_ready() while this is still
    running, and it answers with no suggestion rather than building the tables
    inline.  A search the reader actually submitted is answered properly
    regardless -- which is why the check lives at that boundary and not inside
    word_notes(), where it would silently strip the Strong's hint from every
    ordinary search.
    """
    try:
        surface_counts(mods)
        _surface_index(mods)
        headword_strongs(mods)
        _SPELL_READY[0] = True
    except Exception:
        _SPELL_READY[0] = False
    return _SPELL_READY[0]


def word_notes(word: str, mods: list[Module]) -> list[dict]:


    """Suggestions for one bare word, checked as it was typed.

    smart_notes() works on the *parsed* query, and the parser stems: "agape"
    arrives as "agap".  Checking that against anything reports a correctly
    spelled word as misspelled and offers a near-miss in its place -- the reader
    is told "agap is not found as typed" when what they typed was agape.  That
    is worse than saying nothing.

    So the word is checked as written, against the library's words as written
    (see surface_vocab).  The stem is only offered when it would actually help:
    when the word is not in the library at all, and its stem is.

    `strongs` comes last and only for a word that is a known surface form, which
    is the one hint here that adds something the search box does not already
    know how to say -- or for a lexicon headword, which no Bible prints and so
    no surface index can ever contain (see headword_strongs).
    """
    w = (word or "").strip()
    if not w or not _SPELL_READY[0]:
        return []
    out: list[dict] = []
    counts = surface_counts(mods)
    k = db.fold(w)
    if k and k not in counts:
        # Tolerance scaled to length. A flat two-edit budget turns every short
        # word into a lottery: "agape" is two edits from "agam", a Hebrew
        # headword in the same vocabulary, and the reader is told their word is
        # misspelled and offered a different language's noun. One edit on a
        # short word is a genuine typo; two is a different word.
        #
        # `max_d` is an *exclusive* bound -- _closest returns nothing unless it
        # beats it -- so "at most one edit" is asked for as 2, not 1. Passing 1
        # would demand an exact match and reject every suggestion.
        max_d = 2 if len(k) <= 6 else 3
        near = _closest(k, _near_candidates(counts, k, max_d),
                        max_d=max_d, counts=counts)
        if near:
            out.append({"kind": "spelling", "from": w, "to": near,
                        "note": "Not found as typed."})
        else:
            stem = db.stem(k)
            if len(w) > 3 and stem and stem != k and db.token_key(w) in _vocab(mods):
                out.append({"kind": "forms", "from": w, "to": stem,
                            "note": "Try 'Match all forms'."})
    # Only for a word the library actually contains.  A misspelling has no
    # tagged surface to find, so the lookup could only ever miss -- but it is
    # the one call in this function that needs _surface_index(), and asking it
    # unconditionally meant the first cold keystroke after a restart paid that
    # index's ~14 second build inline, on the request path, in a debounced
    # handler.  Gating on membership makes that path impossible: counts is
    # already built, so a typo costs one dict lookup and nothing else.
    #
    # A prefix like "lov" is not in the vocabulary either, so it no longer gets
    # the Strong's hint here.  It has already earned a spelling suggestion
    # above, which is the more useful thing to tell someone mid-word, and a
    # search they actually submit still reaches _strongs_for via smart_notes().
    if k in counts:
        s = _strongs_for(mods, k)
        if s:
            out.append({"kind": "strongs", "from": w, "to": s[0],
                        "note": f"'{w}' is tagged {s[0]} here."})
    # A lexicon headword is a real word that no Bible prints.  "agape" is in
    # the vocabulary -- surface_counts() deliberately reads lexicon openings for
    # exactly that reason -- so it is not a typo and earns nothing above, but no
    # Bible tags it either, so the branch above adds nothing and the reader is
    # left staring at silence.  Give them the number instead.
    #
    # Tested only when the tag lookup came back empty, and separately rather
    # than as an `elif` on `k in counts`: the headwords are themselves in
    # `counts`, so a headword always takes the first branch and the fallback
    # would never be reached.
    if k and not any(n["kind"] == "strongs" for n in out):
        hw = headword_strongs(mods).get(k)
        if hw:
            num, script = hw
            tail = f" ({script})" if script else ""
            out.append({"kind": "strongs", "from": w, "to": num,
                        "note": f"'{w}' is a Strong's headword{tail}."})
    return out[:6]


def smart_notes(query: Query, mods: list[Module], opts: SearchOpts
                ) -> list[dict]:
    """Suggestions computed from the library itself.

    Three things, none of which needs a model:
      * spelling correction against the headword/Strong's vocabulary;
      * a datatype hint when a word is a known Strong's surface form;
      * a stem hint when a term is a surface form that also occurs stemmed.
    """
    out: list[dict] = []
    vocab = _vocab(mods)
    for t in query.terms:
        for w in list(t.words):
            if w in vocab:
                continue
            near = _closest(w, vocab)
            if near:
                out.append({"kind": "spelling", "from": w, "to": near,
                            "note": "Not found as typed."})
            elif len(w) > 4 and db.stem(w) in vocab:
                out.append({"kind": "forms", "from": w, "to": db.stem(w),
                            "note": "Try 'Match all forms'."})
    for t in query.terms:
        if t.strongs or t.is_morph:
            continue
        for w in t.words:
            s = _strongs_for(mods, w)
            if s and not t.datatype:
                out.append({"kind": "strongs", "from": w, "to": s[0],
                            "note": f"'{w}' is tagged {s[0]} here."})
    return out[:12]


_VOCAB_CACHE: dict = {}


def _vocab(mods: list[Module]) -> set[str]:
    conn = db.connect()
    key = ("vocab", db.GENERATION) + tuple(sorted(m.id for m in mods))
    hit = _VOCAB_CACHE.get(key)
    if hit is not None and time.time() - hit[0] < 3600:
        return hit[1]
    words: set[str] = set()
    for r in conn.execute(
            "SELECT surface FROM marker WHERE module_id IN "
            f"({','.join('?' * len(mods))}) AND kind='strongs' LIMIT 40000",
            [m.id for m in mods]):
        if r["surface"]:
            for w, _a, _b in db.words(r["surface"]):
                words.add(db.token_key(w))
    for r in conn.execute(
            "SELECT text FROM unit WHERE module_id IN "
            f"({','.join('?' * len(mods))}) AND length(text) < 400 LIMIT 6000",
            [m.id for m in mods]):
        for w, _a, _b in db.words(r["text"] or ""):
            k = db.token_key(w)
            if len(k) > 2:
                words.add(k)
    out = {w for w in words if len(w) > 2}
    _VOCAB_CACHE[key] = (time.time(), out)
    return out


def _closest(w: str, vocab, *, max_d: int = 2,
             counts: dict[str, int] | None = None) -> str:
    """The most likely correction for `w` in the library vocabulary.

    `counts`, when given, breaks ties: two words can both be one edit away
    ("hoep" from "hep" by deletion and from "hope" by transposition) and the
    more frequent one is almost always the one that was meant.  This is what
    every working spell-checker does, and without it the choice is arbitrary
    and -- as it was here -- decided by set iteration order.

    A much more frequent word may also beat a candidate one edit closer. This
    keeps a rare typo present in an imported text from outranking the common
    correct spelling.

    No early exit at distance 1.  It was there for speed and it made the answer
    depend on hash order: "glose" is one edit from both "close" and "lose", and
    whichever the set handed over first won.  The caller passes a
    length-bucketed candidate set, so a whole bucket is a few hundred words and
    there is nothing to save by stopping early.
    """
    if not w or len(w) < 3:
        return ""
    ranked = []
    for cand in vocab:
        if abs(len(cand) - len(w)) > max_d:
            continue
        d = _lev(w, cand, max_d)
        if d < max_d:
            ranked.append((d, counts.get(cand, 0) if counts else 0, cand))
    if not ranked:
        return ""
    best_distance = min(d for d, _count, _cand in ranked)
    closest = [(count, cand) for d, count, cand in ranked
               if d == best_distance]
    best_count, best = min(closest, key=lambda x: (-x[0], x[1]))
    # A rare misspelling in one imported source should not beat a much more
    # common correct spelling just because it is one edit closer. Allow a
    # strong frequency signal to break a one-edit distance gap, but otherwise
    # preserve edit distance as the primary ranking.
    if counts:
        more_common = [(count, cand) for d, count, cand in ranked
                       if d == best_distance + 1
                       and count >= max(5, best_count * 10)]
        if more_common:
            best_count, best = min(more_common, key=lambda x: (-x[0], x[1]))
    return best


def _lev(a: str, b: str, cap: int = 3) -> int:
    """Damerau-Levenshtein, capped.

    Adjacent transposition counts as **one** edit, which is what makes this
    usable for typing.  Plain Levenshtein scores "pryaer" against "prayer" as
    two, so with a tight budget the most common mistake there is -- two fingers
    landing out of order -- was silently uncorrectable, while the budget had to
    stay loose enough to admit genuine near-misses.  With transposition counted
    correctly, "pryaer" is one edit and "agape"/"agam" is still two, so the
    budget can be tightened instead of loosened.  That is the whole trade.

    Optimal string alignment rather than the unrestricted variant: adjacent
    transpositions only, one pass, no exponential cases.  A typo is a typo, and
    an unrestricted Damerau on arbitrary vocabulary would buy nothing here.
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev2 = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            val = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if (i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb):
                val = min(val, prev2[j - 2] + 1)
            cur.append(val)
        if min(cur) > cap:
            return cap + 1
        prev2, prev = prev, cur
    return prev[-1]


#: surface form -> Strong's numbers, built once and cached.  Spelling suggestions
#: run on every single search, including ones where the user typed a perfectly
#: good word, so this lookup has to be cheap.
_SURFACE_CACHE: dict[tuple, dict[str, list[str]]] = {}


def _surface_index(mods: list[Module]) -> dict[str, list[str]]:
    key = (db.GENERATION,) + tuple(sorted(m.id for m in mods))
    hit = _SURFACE_CACHE.get(key)
    if hit is not None and time.time() - hit[0] < 3600:
        return hit[1]
    out: dict[str, list[str]] = {}
    conn = db.connect()
    # ~214k distinct surfaces, read once.  The previous version was
    # `SELECT DISTINCT value ... WHERE surface LIKE '%w%'`, which cannot use an
    # index because of the leading wildcard and so scanned all 3 million
    # marker rows on every search -- about eight seconds, for a suggestion the
    # user may not even look at.
    #
    # `marker` has no index on `surface` (its primary key is
    # module_id/kind/value/unit_key/pos, so an exact lookup cannot use it
    # either), which is why the surfaces are collected once into a dict rather
    # than queried per word.  Building this costs ~4 seconds, so it happens on a
    # background thread at startup -- see prewarm_spelling -- and never inside a
    # keystroke.
    ph = ",".join("?" * len(mods))
    # DISTINCT, and it is not a micro-optimisation.  The table holds 2,707,991
    # strongs marker rows, but only 311,931 distinct (surface, value) pairs
    # among them -- the same tag is re-emitted on every word of every verse it
    # covers.  Measured: 4.1s to iterate the raw rows, 2.7s to let SQLite
    # collapse them, and the collapse pays for itself about six times over in
    # the loop below, which is 7.1s for the raw rows against ~3s for the
    # distinct ones.
    #
    # It changes nothing about the result.  The builder lowercases each surface
    # and keeps at most three numbers per surface, so rows identical in both
    # columns could only ever have been discarded by it anyway, and case variants
    # of one surface still arrive as separate rows and still fold together here.
    for r in conn.execute(
            "SELECT DISTINCT surface, value FROM marker WHERE kind='strongs' "
            f"AND module_id IN ({ph})",
            [m.id for m in mods]):
        surf = (r["surface"] or "").lower()
        if not surf:
            continue
        lst = out.setdefault(surf, [])
        if r["value"] and r["value"] not in lst and len(lst) < 3:
            lst.append(r["value"])
    _SURFACE_CACHE[key] = (time.time(), out)
    return out


def _strongs_for(mods: list[Module], w: str) -> list[str]:
    """Strong's numbers for a surface form, matched exactly.

    This used to match as a substring, on the reasoning that "a typo is often in
    the middle of the word".  It does not work that way.  A typo is not a
    substring of the word it was meant to be -- "pryaer" is not a substring of
    "prayer" -- so every real misspelling missed, which was the only case the
    hint existed for, while every correctly spelled word that merely sat inside
    a longer tagged surface matched the wrong numbers.  Measured side by side:

        hope    substring -> H3176, H7663   exact -> G1679, G1680, H0986
        faith   substring -> G0569          exact -> G4100, G4102, H0530
        prayer  substring -> G1162          exact -> G1783, G2171, G4335

    "hope" is H3176 *hope* and H7663 *hopping*; the reader meant Greek G1679.
    Substring matching bought noise, missed every typo, and cost a scan of all
    213,794 surfaces on each keystroke.  Exact matching is a dict lookup, and
    the spelling correction in word_notes() is what handles the typos.
    """
    needle = (w or "").lower()
    if not needle:
        return []
    idx = _surface_index(mods)
    hit = idx.get(needle)
    if hit:
        return list(hit)
    # The query parser stems, so smart_notes() asks about "lov" where the
    # surface the reader typed is "love" -- and an exact lookup finds nothing.
    # This is what the old substring scan was really for: not typos, as its
    # comment claimed, but recovering a surface from its own stem.  A prefix
    # lookup is the honest version of that.  It stays a bisect over a sorted
    # key list rather than a scan of 213,794 entries, and it stops at the first
    # surface that is not prefixed, so it returns "love" rather than every word
    # containing it.
    out: list[str] = []
    for surf in _prefix_surfaces(mods, needle):
        for n in idx[surf]:
            if n not in out:
                out.append(n)
                if len(out) >= 3:
                    return out
    return out


_SURFACE_KEYS: dict[tuple, tuple] = {}


def _prefix_surfaces(mods: list[Module], prefix: str) -> list[str]:
    """The indexed surfaces that start with `prefix`, shortest first.

    Cached against the surface index's own identity, so the sort happens once
    per library rather than once per keystroke.  Keys are sorted, so everything
    beginning with the prefix is contiguous; a bisect finds the start and the
    loop stops at the first key that does not match.

    Tied to the index object, not to the module set, and that is the whole
    point of checking `id`.  _SURFACE_CACHE expires after five minutes and
    rebuilds; keying only on the module ids left this list pointing at the
    *previous* index forever, so a surface added or removed in between was
    either invisible to the bisect or indexed straight into a dict that no
    longer had it -- which is a KeyError inside a suggestion.
    """
    idx = _surface_index(mods)
    key = (db.GENERATION,) + tuple(sorted(m.id for m in mods))
    got = _SURFACE_KEYS.get(key)
    if got is None or got[0] is not idx:
        keys = sorted(idx)
        got = (time.time(), keys)
        _SURFACE_KEYS[key] = got
    keys = got[1]
    i = bisect.bisect_left(keys, prefix)
    out: list[str] = []
    while i < len(keys) and keys[i].startswith(prefix):
        out.append(keys[i])
        i += 1
    return out


# ==========================================================================
# Helpers used by the UI
# ==========================================================================

OPERATOR_HELP = [
    {"op": "AND", "syntax": "term1 AND term2", "note": "Both. Also the default "
     "between adjacent terms: 'faith Lord' is 'faith AND Lord'."},
    {"op": "OR", "syntax": "term1 OR term2", "note": "Either."},
    {"op": "NOT", "syntax": "term1 NOT term2", "note": "term1 without term2."},
    {"op": '"phrase"', "syntax": '"people of Israel"',
     "note": "Order and adjacency. No stemming inside quotes."},
    {"op": "wildcard", "syntax": "lord*   lord?",
     "note": "* = zero or more characters in a word, ? = one."},
    {"op": "BEFORE", "syntax": "term1 BEFORE term2",
     "note": "term1 occurs before term2."},
    {"op": "AFTER", "syntax": "term1 AFTER term2", "note": "term1 follows term2."},
    {"op": "NEAR", "syntax": "term1 NEAR term2", "note": "Within 48 characters."},
    {"op": "WITHIN n WORDS", "syntax": "term1 WITHIN 5 WORDS term2",
     "note": "Distance in words; ranges like 2-3 WORDS work too. Punctuation "
             "does not count, so the minimum separation is 1."},
    {"op": "WITHIN n CHARS", "syntax": "term1 WITHIN 30 CHARS term2",
     "note": "Distance in characters, counting separators. Useful for Hebrew "
             "morph segments."},
    {"op": "EQUALS", "syntax": "term1 EQUALS term2", "note": "The same location."},
    {"op": "IN", "syntax": "term1 IN term2", "note": "term1 is wholly inside term2."},
    {"op": "INTERSECTS", "syntax": "term1 INTERSECTS term2",
     "note": "They overlap. The most forgiving of the three."},
    {"op": "field:", "syntax": "heading:baptism   field.bible:Joshua",
     "note": "Restrict a term to a tagged field."},
    {"op": "datatype:", "syntax": "strongs:G2316   lemma.g:ἀγαπάω   morph.g:VF",
     "note": "Strong's, lemma and morphology are searched directly."},
    {"op": "reference:", "syntax": 'bible:"Gen 1:1"   reference:"Gen 1:1"',
     "note": "A passage. 'reference:' restricts to cross-references only."},
    {"op": "term:(...)", "syntax": "term:(Jesus OR Christ OR Messiah)",
     "note": "Counted and highlighted as one term."},
]

# Words that look like operators but are not capitalised -- the single most
# common query mistake, so it is worth a first-class warning.
def operator_warnings(q: str) -> list[str]:
    out = []
    for m in re.finditer(r"\b(and|or|not|near|within|before|after|intersects|equals)\b",
                         q or "", re.I):
        w = m.group(0)
        if w.upper() != w:
            out.append(f"'{w}' was read as a word, not an operator. "
                       f"Did you mean {w.upper()}?")
    return out

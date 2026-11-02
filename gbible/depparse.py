"""Real dependency parsing, for clause search and the sentence diagram.

Why this exists
---------------
Clause search was asked for one specific thing: find a word *as the object of a
verb*.  That question cannot be answered without knowing how the words are
joined -- "God glorified his name" and "he believed in his name" have the same
word in the same sentence, and the name is the object in the first and a
prepositional object in the second.  Punctuation cannot tell those apart, and a
conjunction list cannot either.

So this runs an actual dependency parser (spaCy's statistical model) and reports
the relation the parser found.  The three relations that answer the question
asked for:

  object     the term is the direct object of a verb   (`dobj`/`obj`)
  subject    the term is the subject of a verb         (`nsubj`)
  governed   the term stands in the same clause as another term -- the same
             finite verb governs both

What "clause" means here
------------------------
A dependency clause is the subtree of one finite verb.  So "same clause" is not
"the text between two commas": it is "governed by the same verb".  Two words can
be separated by half a page of commas and still be in one clause, and two words
either side of a semicolon can be in one clause if the semicolon does not
actually separate the verb from its object.

Every hit reports the verb that governs the match and the relation to it, so a
result can be checked rather than trusted.

Optional, and honest when absent
--------------------------------
Like the voice (see `tts`), the parser is optional: it is a statistical model
worth about 13 MB.  Without it there is no dependency parse, and `clause` says
so in `method` and falls back to the punctuation-and-conjunction splitter rather
than pretending.  With it, English is parsed exactly.  Hebrew and Greek are not
-- no model is installed for either -- and for a tagged original-language module
`clause` uses the morphology already in the database and says *that* is what it
used.

Cost
----
spaCy's small English model parses roughly 8,000 words a second, so a verse is
about two milliseconds.  Parsing every hit of a broad query would be minutes, so
the caller pre-filters with the ordinary search index first and parses only what
survives.  Results are cached by text, because a word list re-run asks about the
same verses again and again.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict

from . import db

MODEL = "en_core_web_sm"

_install_hint = (
    "the English parser is not installed -- "
    f"python3 -m spacy download {MODEL}"
)

_lock = threading.Lock()
_nlp = None
_error = ""


class Unavailable(RuntimeError):
    """Raised when a dependency parse was asked for and cannot be given."""


def available() -> tuple[bool, str]:
    """(can parse?, why not).  Never raises, and never loads the model."""
    if _error:
        return False, _error
    try:
        import importlib.util
        if importlib.util.find_spec("spacy") is None:
            return False, ("spaCy is not installed -- pip install spacy")
        import spacy.util
        if not spacy.util.get_installed_models():
            return False, _install_hint
        if MODEL not in spacy.util.get_installed_models():
            others = ", ".join(sorted(spacy.util.get_installed_models()))
            return False, f"{MODEL} is not installed (found: {others or 'none'})"
    except Exception as exc:  # pragma: no cover - import guards only
        return False, f"the English parser could not be checked: {exc}"
    return True, ""


def nlp():
    """The loaded pipeline, or Unavailable with the reason."""
    global _nlp, _error
    if _nlp is not None:
        return _nlp
    ok, why = available()
    if not ok:
        _error = why
        raise Unavailable(why)
    with _lock:
        if _nlp is not None:
            return _nlp
        try:
            import spacy
            _nlp = spacy.load(MODEL)
        except Exception as exc:
            _error = f"{MODEL} could not be loaded: {type(exc).__name__}: {exc}"
            raise Unavailable(_error) from exc
    return _nlp


def warm() -> bool:
    """Load the model in the background at startup.  Returns whether it worked."""
    try:
        nlp()
        return True
    except Unavailable:
        return False


# --------------------------------------------------------------------- cache

_CACHE_MAX = 4096
_cache: "OrderedDict[str, dict]" = OrderedDict()
_cache_lock = threading.Lock()
_stats = {"parsed": 0, "cache_hits": 0}


def stats() -> dict:
    return {**_stats, "cached": len(_cache), "available": available()[0]}


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# ------------------------------------------------------------------ relations

#: spaCy dependency labels that mean "the object of the verb above it".
OBJECT_DEPS = frozenset({"dobj", "obj", "iobj", "dative", "attr", "oprd"})
SUBJECT_DEPS = frozenset({"nsubj", "nsubjpass", "csubj", "expl"})
#: Labels that are arguments *of a preposition*, not of the verb directly.  Kept
#: apart because "in his name" is a prepositional object and the word above
#: "in" is the verb -- but the relation a reader wants to see is that it hangs
#: off the verb by way of a preposition.
PREP_OBJ_DEPS = frozenset({"pobj", "pobj", "dobj"})

ROLE_LABELS = {
    "dobj": "direct object of the verb",
    "obj": "direct object of the verb",
    "iobj": "indirect object of the verb",
    "dative": "indirect object of the verb",
    "attr": "the complement of the verb",
    "oprd": "the complement of the verb",
    "nsubj": "subject of the verb",
    "nsubjpass": "subject of the verb (passive)",
    "csubj": "subject of the verb",
    "expl": "the subject of the verb",
    "pobj": "object of a preposition, attached to the verb",
    "poss": "possessive of the noun above it",
    "prep": "a preposition governing the verb's object",
    "advmod": "an adverb of the verb",
    "advcl": "a clause adverbial of the verb",
    "ccomp": "a clause that is the complement of the verb",
    "xcomp": "a clause the verb asks for",
    "acomp": "a clause that complements the verb",
    "relcl": "a relative clause on the noun above it",
    "acl": "a clause attached to the noun above it",
    "amod": "an adjective modifying the noun above it",
    "compound": "part of a noun phrase",
    "obl": "an oblique phrase of the verb",
    "conj": "a coordinated verb",
    "cc": "a conjunction joining the verbs",
    "ROOT": "the main verb of the sentence",
}


def role_label(dep: str) -> str:
    return ROLE_LABELS.get(dep, f"attached as {dep or 'unlabelled'}")


# --------------------------------------------------------------------- input

#: Reference prefixes and anything else that is not sentence text.  Verse text
#: from a tagged module can carry Strong's numbers or morphology codes inline.
_REF_PREFIX = re.compile(r"^\s*(?:[1-3]?\s?[A-Za-z]+\s+)?[\d:.\-]+\s+")
_STRONGS = re.compile(r"\b[GHD]\d{3,5}\b")
_MORPH = re.compile(r"\b[A-Z]{1,3}\d{1,4}[a-z]?\b")
_WORDY = re.compile(r"[^\W\d_]+", re.UNICODE)


def clean(text: str) -> str:
    """The sentence text a parser should see, with apparatus removed."""
    s = _REF_PREFIX.sub("", text or "")
    s = _STRONGS.sub(" ", s)
    s = _MORPH.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _key(text: str) -> str:
    return clean(text)


# ------------------------------------------------------------------- parsing

def _finite_head(dep: str, pos: str) -> bool:
    """Does this token head a clause?  A verb that is not a participle."""
    if pos not in ("VERB",):
        return False
    if dep in ("acl", "relcl", "amod", "advcl", "dep", "npadvmod", "ROOT"):
        # Still a clause head; only participles are not, and those are AUX/VERB
        # with a different tag, handled below.
        return True
    return True


class Sentence:
    """One sentence, with the dependency structure a reader would want to see."""

    __slots__ = ("text", "ref", "index", "tokens", "clause_of", "verb_of",
                 "clause_verb", "root_verb")

    def __init__(self, text: str, ref: str, index: int):
        self.text = text
        self.ref = ref
        self.index = index
        self.tokens: list[dict] = []
        self.clause_of: dict[int, int] = {}   # token index -> clause index
        self.clause_verb: list[str] = []      # clause index -> verb surface
        self.verb_of: dict[int, str] = {}     # token index -> governing verb
        self.root_verb = ""

    def words(self) -> list[dict]:
        return list(self.tokens)

    def clauses(self) -> list[dict]:
        out = []
        for i in range(len(self.clause_verb)):
            idxs = [k for k, v in self.clause_of.items() if v == i]
            # The indices stay complete -- punctuation is in the subtree, and
            # the diagram uses them -- but the text a reader sees skips it,
            # because "loved the world , ." is not a clause anyone reads.
            shown = " ".join(self.tokens[k]["word"] for k in idxs
                             if self.tokens[k]["pos"] not in ("PUNCT", "SPACE"))
            out.append({"index": i, "verb": self.clause_verb[i],
                        "text": shown, "words": idxs})
        return out


def _build(doc, ref: str, offset: int, text: str) -> list[Sentence]:
    """Turn spaCy's parse into sentences with clause membership resolved.

    A clause is the subtree of one finite verb, so membership is a question
    with an exact answer: walk up from each token until a clause head is
    reached, and that head owns the token.  Walking up rather than taking the
    span between the verb and the next verb is what makes "same clause" mean
    *governed by the same verb* -- a complement stays with its head verb even
    though another verb comes later in the sentence.
    """
    sents: list[Sentence] = []

    for si, sent in enumerate(doc.sents):
        s = Sentence(sent.text.strip(), ref, offset + si)
        toks = [t for t in sent if not t.is_space]
        if not toks:
            continue

        # spaCy's token indices are sentence-global; ours are per sentence.
        n_of = {t.i: k for k, t in enumerate(toks)}
        t_of = {k: t for k, t in enumerate(toks)}

        s.tokens = [{
            "word": t.text, "lemma": (t.lemma_ or t.text).lower(),
            "pos": t.pos_, "dep": t.dep_, "head": t.head.text,
            "n": k,
        } for k, t in enumerate(toks)]

        # Clause heads: the root verb, plus every verb that is coordinated
        # with or subordinated to another verb (conj, advcl, ccomp, xcomp,
        # acomp, parataxis).  A verb reached by acl/relcl/amod is a participle
        # inside a noun phrase and does not head a clause of its own.
        root = next((k for k, t in enumerate(toks) if t.dep_ == "ROOT"), 0)
        heads: list[int] = []
        for k, t in enumerate(toks):
            if t.pos_ != "VERB" or t.dep_ in ("acl", "relcl", "amod"):
                continue
            if k == root or t.dep_ in ("conj", "advcl", "ccomp", "xcomp",
                                        "acomp", "parataxis"):
                heads.append(k)
        if root not in heads:
            heads.append(root)
        heads.sort()
        head_set = set(heads)

        # Every token to its nearest clause head, walking up the head chain.
        for k in range(len(toks)):
            j = k
            for _ in range(60):
                if j in head_set:
                    break
                h = t_of[j].head.i
                if h == t_of[j].i or h not in n_of:
                    j = root
                    break
                j = n_of[h]
            s.clause_of[k] = heads.index(j)
            s.verb_of[k] = (toks[heads[s.clause_of[k]]].lemma_ or "").lower()

        s.clause_verb = [(toks[h].lemma_ or toks[h].text).lower() for h in heads]
        s.root_verb = s.clause_verb[s.clause_of.get(root, 0)] if s.clause_verb else ""
        sents.append(s)
    return sents



def parse(text: str, ref: str = "") -> dict:
    """Dependency structure for a verse or passage.  Cached by its text.

    Returns {ok, sentences: [...], method, note, reason}.
    """
    k = _key(text)
    if not k:
        return {"ok": False, "reason": "no text to parse"}
    with _cache_lock:
        hit = _cache.get(k)
        if hit is not None:
            _cache.move_to_end(k)
            _stats["cache_hits"] += 1
            return hit
    try:
        pipeline = nlp()
    except Unavailable as exc:
        return {"ok": False, "reason": str(exc)}
    doc = pipeline(k)
    return _store(k, doc)


def parse_many(texts, refs=None) -> list[dict]:
    """Parse a batch of verses at once.

    One at a time the model does about 100 verses a second; piped in batches of
    32 it does nearly 500, and the named-entity pass nobody here needs costs
    another doubling.  A clause search over a few hundred candidates is the
    difference between a second and half a minute.
    """
    keys = [_key(t) for t in texts]
    out: list[dict | None] = [None] * len(keys)
    todo: list[int] = []
    with _cache_lock:
        for i, k in enumerate(keys):
            if not k:
                out[i] = {"ok": False, "reason": "no text to parse"}
                continue
            hit = _cache.get(k)
            if hit is not None:
                _cache.move_to_end(k)
                _stats["cache_hits"] += 1
                out[i] = hit
            else:
                todo.append(i)
    if not todo:
        return [o or {} for o in out]
    try:
        pipeline = nlp()
    except Unavailable as exc:
        return [{"ok": False, "reason": str(exc)}] * len(keys)

    # `ner` off: the diagram colours parts of speech, not entities, and it is
    # about half the time.
    pipe = pipeline
    try:
        if "ner" in pipeline.pipe_names:
            pipeline.remove_pipe("ner")
            pipe = pipeline
    except Exception:
        pipe = pipeline

    refs = refs or []
    for i, doc in zip(todo, pipe.pipe([keys[i] for i in todo], batch_size=32)):
        ref = refs[i] if i < len(refs) else ""
        out[i] = _store(keys[i], doc, ref)
    return [o or {} for o in out]


def _store(k: str, doc, ref: str = "") -> dict:
    sents = _build(doc, ref, 0, k)
    res = {"ok": True, "sentences": sents, "method": "a dependency parse",
           "note": "Roles come from a statistical parser, so they are very "
                   "reliable and not certain. Each result names the verb that "
                   "governs the word, so it can be checked.",
           "model": MODEL}
    _stats["parsed"] += 1
    with _cache_lock:
        _cache[k] = res
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return res


# ------------------------------------------------------------------ analysis

def locate(sentence: Sentence, term: str) -> list[dict]:
    """Every token in `sentence` matching `term`, with its dependency role.

    Matching is on the lemma, which is what makes `faith` find *faithful* and
    `abide` find *abides*, and on the surface for forms the lemma lost.
    """
    want = (term or "").strip().lower()
    if not want:
        return []
    out = []
    for t in sentence.tokens:
        if t["lemma"] == want or t["word"].lower() == want:
            out.append({**t,
                        "clause": sentence.clause_of.get(t["n"], 0),
                        "verb": sentence.clause_verb[
                            sentence.clause_of.get(t["n"], 0)] if sentence.clause_verb else "",
                        "role": role_label(t["dep"])})
    return out


def role_of(match: dict) -> str:
    """`object`, `subject`, `prep_object`, `attributive` or `other`."""
    dep = match["dep"]
    if dep in ("dobj", "obj"):
        return "object"
    if dep in SUBJECT_DEPS:
        return "subject"
    if dep == "pobj":
        return "prep_object"
    return "other"


def describe(match: dict) -> str:
    """One sentence a reader can check the match against."""
    dep = match["dep"]
    if dep in ("dobj", "obj", "iobj", "dative"):
        return f"{match['word']!r} is the object of {match['head']!r}"
    if dep in SUBJECT_DEPS:
        return f"{match['word']!r} is the subject of {match['head']!r}"
    if dep == "pobj":
        return (f"{match['word']!r} is the object of the preposition "
                f"{match['head']!r}")
    return f"{match['word']!r} is {role_label(dep)} ({dep})"


def relation_holds(matches_a: list[dict], matches_b: list[dict],
                   relation: str) -> tuple[bool, dict]:
    """Does the relation hold between the two sets of matches?

    Returns (holds, evidence) where evidence explains it in one line, so a
    result can be shown with its reason rather than just asserted.
    """
    if relation == "sentence":
        if matches_a and matches_b:
            return True, {"why": "both words are in this sentence",
                          "a": matches_a[0], "b": matches_b[0]}
        return False, {"why": "a word is missing from the sentence"}

    if relation == "same":
        for a in matches_a:
            for b in matches_b:
                if a["clause"] == b["clause"] and a["verb"] == b["verb"]:
                    return True, {"why": f"both stand in the clause of {a['verb']!r}",
                                  "a": a, "b": b, "verb": a["verb"],
                                  "clause": a["clause"]}
        return False, {"why": "no clause governs both words"}

    if relation == "different":
        for a in matches_a:
            for b in matches_b:
                if a["clause"] != b["clause"]:
                    return True, {"why": f"{a['word']!r} is in the clause of "
                                         f"{a['verb']!r} and {b['word']!r} in "
                                         f"that of {b['verb']!r}",
                                  "a": a, "b": b,
                                  "clauses": [a["clause"], b["clause"]]}
        return False, {"why": "both words stand in the same clause"}

    if relation in ("object", "subject", "prepositional"):
        if relation == "object":
            want = "object"
        elif relation == "subject":
            want = "subject"
        else:
            want = "prep_object"
        for m in matches_a:
            if role_of(m) == want:
                return True, {"why": describe(m), "a": m, "b": None,
                              "verb": m["head"], "role": role_label(m["dep"]),
                              "match": m["n"]}
        return False, {"why": f"the word is not the {want.replace('_', ' ')} "
                             f"of any verb here"}

    return False, {"why": f"unknown relation {relation!r}"}


#: What the UI offers, in the order a reader wants them.
RELATIONS = (
    ("object", "Object of a verb"),
    ("subject", "Subject of a verb"),
    ("prepositional", "Object of a preposition"),
    ("same", "Same dependency clause"),
    ("different", "Different clauses, one sentence"),
    ("sentence", "Anywhere in the same sentence"),
)


def reset_model_error() -> None:
    """Forget a load failure, so a later install can be picked up."""
    global _error
    _error = ""

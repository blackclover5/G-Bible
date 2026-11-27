"""Conservative pronoun resolution for CoNLL-U treebanks.

A clause search for ``subject:Jesus`` finds verses that *name* Jesus.  It also
ought to find "he came…" when the pronoun follows a verse that names him, but a
language model is the wrong tool here: it would send the library off the
machine, and a guess about who "he" means is worse than no answer at all.

So this is deliberately rule-based and local.  A third-person pronoun is linked
to a named antecedent only when:

* the pronoun occupies a clause role (subject, object, …);
* exactly one name in a short recent window has agreement features compatible
  with the pronoun's person, gender and number;
* both sides are from the same treebank.

The resulting role rows are marked ``resolved=1`` and carry the pronoun as their
surface, so every hit can say "this was inferred from *he*".  No features means
no constraint, never a guess: a window with two compatible names resolves
nothing.
"""

from __future__ import annotations

from . import db

#: The same relation-to-role map the indexer uses for explicit words.
ROLE_BY_DEPREL = {
    "nsubj": "subject", "nsubjpass": "subject", "csubj": "subject",
    "obj": "object", "dobj": "object", "cobj": "object",
    "iobj": "indirect_object", "obl": "oblique",
}

_GENDER = {"masc": "masculine", "fem": "feminine", "neut": "neuter",
           "m": "masculine", "f": "feminine", "n": "neuter"}
_NUMBER = {"sing": "singular", "plur": "plural", "dual": "dual",
           "s": "singular", "p": "plural", "d": "dual"}
_PERSON = {"1": "first", "2": "second", "3": "third"}

#: Greek articles carry the gender a following proper noun often omits.
#: Folded forms avoid a thicket of accent variants (ὁ / ο, ἡ / η, τό / το).
_ARTICLE_GENDER = {"ο": "masculine", "η": "feminine", "το": "neuter"}


def _feats(raw) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in str(raw or "").split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _normal(key: str, value: str, table: dict[str, str]) -> str:
    return table.get(str(value or "").lower(), str(value or "").lower())


def _compatible(pron: dict[str, str], name: dict[str, str]) -> bool:
    """Reject only contradictions; a missing feature is not a match."""
    for key, table in (("Person", _PERSON), ("Gender", _GENDER),
                       ("Number", _NUMBER)):
        a = _normal(key, pron.get(key, ""), table)
        b = _normal(key, name.get(key, ""), table)
        if a and b and a != b:
            return False
    return True


def _token_pos(edge: dict) -> int:
    try:
        return int(edge.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def _infer_gender(edges: list, index: int, number: str) -> str:
    """Gender of a name from a nearby determiner, when its own feats omit it.

    Only a single, unambiguous value is returned.  A name between two articles
    of different genders gets nothing, which is the conservative answer.
    """
    values: set[str] = set()
    for j in range(max(0, index - 2), min(len(edges), index + 3)):
        if j == index:
            continue
        edge = edges[j]
        if not isinstance(edge, dict):
            continue
        if str(edge.get("upos") or "").upper() not in ("DET", "ART"):
            continue
        feats = _feats(edge.get("feats"))
        if number:
            got_number = _normal("Number", feats.get("Number", ""), _NUMBER)
            if got_number and got_number != number:
                continue
        gender = _normal("Gender", feats.get("Gender", ""), _GENDER)
        if gender:
            values.add(gender)
            continue
        key = db.fold(str(edge.get("lemma") or edge.get("form") or ""))
        if key in _ARTICLE_GENDER:
            values.add(_ARTICLE_GENDER[key])
    return next(iter(values)) if len(values) == 1 else ""


class Resolver:
    """Carries recent named entities across sentences of one treebank."""

    def __init__(self, *, window: int = 3):
        self.window = max(1, int(window))
        self._seq = 0
        self._history: list[tuple[int, str, dict]] = []

    def resolve(self, unit_key: str, edges: list) -> list[dict]:
        self._seq += 1
        named: list[dict] = []
        pronouns: list[tuple[dict, str, dict]] = []
        for index, edge in enumerate(edges or []):
            if not isinstance(edge, dict):
                continue
            upos = str(edge.get("upos") or "").upper()
            form = str(edge.get("form") or "")
            if not form or form == "_":
                continue
            feats = _feats(edge.get("feats"))
            if upos == "PROPN":
                number = _normal("Number", feats.get("Number", ""), _NUMBER)
                gender = _normal("Gender", feats.get("Gender", ""), _GENDER)
                if not gender:
                    gender = _infer_gender(edges or [], index, number)
                named.append({
                    "form": form,
                    "lemma": str(edge.get("lemma") or ""),
                    "Person": feats.get("Person", ""),
                    "Gender": gender,
                    "Number": number,
                })
            role = ROLE_BY_DEPREL.get(str(edge.get("deprel") or "").lower())
            if upos == "PRON" and role:
                pronouns.append((edge, role, feats))

        # Distance is measured in sentences, not in named entities: a name in
        # one verse must not stay an antecedent forever just because no other
        # name happened to appear in between.
        first = self._seq - self.window + 1
        recent = [e for seq, _key, e in self._history if seq >= first]
        out: list[dict] = []
        for edge, role, feats in pronouns:
            if _normal("Person", feats.get("Person", ""), _PERSON) not in ("third", ""):
                # A first- or second-person pronoun names the speaker or the
                # reader, not an entity in the text; "third" or unmarked only.
                continue
            # Key by form *and* features: two people with the same name but
            # different Gender/Number are two candidates, not one, and must
            # keep the resolution ambiguous rather than collapse into a guess.
            matches: dict[tuple, dict] = {}
            for name in recent + named:
                if _compatible(feats, name):
                    matches.setdefault(
                        (name["form"], name["Gender"], name["Number"]), name)
            if len(matches) != 1:
                continue
            name = next(iter(matches.values()))
            out.append({
                "role": role,
                "value": db.fold(name["form"]),
                "lemma": db.fold(name["lemma"]) if name["lemma"] else "",
                "surface": str(edge.get("form") or ""),
                "pos": _token_pos(edge),
                "antecedent": name["form"],
            })

        self._history.extend((self._seq, unit_key, e) for e in named)
        self._history = [h for h in self._history if h[0] >= first]
        return out

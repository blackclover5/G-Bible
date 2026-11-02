"""Genealogies, extracted from the Bible text that is installed rather than typed
in by hand.

The reason to extract rather than hardcode a family tree: a hardcoded tree is
somebody's memory, and memory of a genealogy is exactly the thing that goes
wrong quietly.  The text is right here, and it states the relationships itself --
"X became the father of Y", "X begat Y", "the sons of X were A, B, C".  So the
edges are read out of the text, and every edge keeps the verse it came from and
the sentence it matched, so any claim in the resulting tree can be checked
against the Bible rather than taken on trust.

Three things this deliberately does not do.

* It does not infer a parent from context.  Every edge needs an explicit
  relation word in the text.  Nothing is derived from "and then the next name
  is his son", because that is a guess.
* It does not merge the two messianic lines into one tree.  Matthew and Luke
  give different ancestors for Jesus between David and Azariah, and both are
  right; a merged tree would have to pick one.  Where the same name arrives with
  two different fathers, the module reports the divergence rather than
  averaging it away.
* It does not guess at a name's gender from a pronoun, or assign a mother from a
  "bare" verb, because the text often withholds which parent a verse is naming.

What you get is a person graph with citations, an ancestor walk, and a list of
the places where the sources disagree with each other.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------- source

# Where genealogies actually are.  Genesis, the Chroniclers, Ruth, the divided
# monarchy, and the two infancy narratives.  Each entry is a book and a chapter
# range; everything in them that states a relationship explicitly is read.
SOURCES: list[tuple[str, int, int]] = [
    ("Gen", 3, 12),      # Adam, Seth, the line to Noah, the nations, Shem
    ("Gen", 14, 14),     # the kings of the valley
    ("Gen", 19, 19),     # Lot's daughters
    ("Gen", 21, 22),     # Isaac, Ishmael, Esau, Jacob
    ("Gen", 25, 26),     # Ishmael's line, Isaac's sons
    ("Gen", 28, 30),     # Jacob's sons
    ("Gen", 35, 36),     # Jacob's sons in order, Esau's line
    ("Gen", 38, 38),     # Judah, Perez and Zerah
    ("Gen", 46, 46),     # the sons of Jacob who went to Egypt
    ("Exod", 1, 6),      # Moses and Aaron, the Levites
    ("Ruth", 4, 4),      # Perez, Jesse, David
    ("1Sam", 7, 9),      # Samuel's sons, the rise of Saul
    ("1Sam", 16, 16),    # Jesse's seven sons
    ("2Sam", 5, 5),      # David's sons
    ("2Sam", 12, 12),    # Solomon's birth, and Bathsheba as his mother
    ("1Chr", 22, 22),    # "David ... to help Solomon his son"
    ("1Kgs", 3, 3),      # Solomon
    ("1Kgs", 11, 11),    # Rehoboam
    ("2Kgs", 25, 25),    # Jeconiah and the royal line
    ("1Chr", 1, 9),      # the genealogies proper
    ("Ezra", 9, 9),      # the returned households
    ("Neh", 7, 7),       # the second register
    ("Esth", 2, 2),      # Mordecai's house
    ("Matt", 1, 1),      # Matthew's line
]

# Luke 3 states the line backwards ("the son of X, the son of Y"), so it needs
# its own reader; see _inverse_chain.
INVERSE_SOURCES: list[tuple[str, int, int, int]] = [("Luke", 3, 23, 38)]

# Prefer a plain modern translation: the pattern is a clean
# "<name> became the father of <child>" rather than a pronoun with an
# understood subject.
PREFERRED = ["open-bibles-eng-web", "open-bibles-eng-bbe", "crosswire-acv",
             "open-bibles-eng-web", "ebible-eng-web", "open-bibles-eng-kjv",
             "crosswire-kjv"]

# Words that end a name.  Anything capitalised and not in here continues it, so
# "Absalom" survives but "Israel" stops the scan at "son of Israel".
STOP = {
    "a", "after", "all", "also", "an", "and", "another", "as", "at", "be",
    "because", "been", "before", "being", "begat", "bore", "bare", "born",
    "brought", "by", "call", "called", "children", "daughter", "daughters",
    "days", "died", "first", "for", "from", "gave", "had", "has", "he", "her",
    "him", "his", "in", "into", "is", "it", "its", "lived", "many", "named",
    "of", "old", "one", "other", "others", "our", "she", "son", "sons", "the",
    "their", "then", "these", "this", "those", "to", "two", "unto", "was",
    "were", "which", "who", "whom", "whose", "with", "years", "yours",
    # Sentence openers and pronouns.  Without these, "Now this is the history
    # of Perez" makes Now the father of Jesse, and "He is the father of Jesse"
    # makes He a person with children called "he", "nathan" and "those".
    "now", "they", "he", "she", "it", "thus", "therefore", "after", "before",
    "when", "while", "and", "but", "so", "if", "behold", "lo", "behold",
    "neither", "nor", "yet", "also", "even", "howbeit", "wherefore", "moreover",
    "according", "unto", "unto", "likewise", "whereas", "there", "here",
    # demonstratives: "David was the son of that Ephrathite" must not make
    # "that" a man
    "that", "such", "same", "each", "every", "any", "one", "other",
    # first person: "This time will I praise Yahweh. Therefore she named him
    # Judah" made Judah a son of I
    "i", "me", "my", "mine", "we", "us", "our", "ours", "your", "yours",
    "thou", "thee", "thy", "thine", "ye",
    # "God" appears inside quoted speech far more often than as the subject of
    # a naming: 'Leah said, "God has given me my hire." She named him Issachar.'
    # The nearest capitalised word before "named" is God, and it is the wrong
    # one.  Luke 3:38 does say "the son of God" outright, and _inverse_chain
    # keeps that deliberately.
    "god", "gods", "lord", "yahweh", "jehovah", "yhwh", "adonai",
    "elohim", "holy", "spirit", "son", "man", "woman", "hand",
    # Narrative verbs, which are capitalised at the start of a sentence and so
    # are picked up as the nearest name before a naming verb: Gen 29:35 "She
    # said, 'This time will I praise Yahweh.' Therefore she named him Judah"
    # made Judah the son of "Said".
    "said", "says", "say", "told", "answered", "replied", "asked", "cried",
    "thought", "saw", "heard", "spake", "sent", "took", "gave", "made", "put",
    "set", "brought", "came", "went", "arose", "rose", "sat", "stood", "speak",
    "look", "looked", "turn", "turned", "behold", "behold", "lifted", "greeted",
    "wished", "swore", "slept", "awoke", "built", "made",
}

NAME_RE = re.compile(r"[A-Z][A-Za-z']*")
STOP_RE = "|".join(sorted(STOP, key=len, reverse=True))


def _norm(name: str) -> str:
    """Fold spelling variants so the same person is one person.

    Transliterations differ between translations and this matters in exactly
    the places that matter: Cainan/Kenan, Enosh/Enos, Methuselah/Methusaleh,
    Peleg/Peleg.  Only differences we have actually seen are listed; anything
    else is left alone rather than guessed at.
    """
    n = re.sub(r"[^A-Za-z]", "", name or "").lower()
    return VARIANTS.get(n, n)


VARIANTS = {
    # Transliteration differences between English versions of the same Hebrew
    # or Greek name.  Only pairs actually seen in the text are listed, and each
    # is folded to the form the chosen translation uses, so the two spellings
    # come out as one person instead of two.
    "kenan": "cainan", "cainan": "cainan",       # Gen 5:9, "Enosh begat Cainan"
    "enos": "enosh", "enosh": "enosh",           # vs KJV "Enos"
    "methusaleh": "methuselah", "mathusala": "methuselah",
    "jered": "jared", "jared": "jared",
    "mahalaleel": "mahalalel", "mahaleel": "mahalalel",
    "rebekah": "rebecca", "rebecca": "rebecca",
    "abreham": "abraham", "abraham": "abraham", "abram": "abraham",
    "iphthael": "jephthah", "jephthah": "jephthah",
    "jehoshua": "joshua", "joshua": "joshua",
    "nazareth": "nazareth",
    # Jacob is Israel: the same man under both names, and the text says so.
    "jacob": "israel", "israel": "israel",
    "perez": "perez", "pharez": "perez", "fares": "perez", "peretz": "perez",
    "zeruah": "zeruah", "zeruach": "zeruah",
    "judah": "judah", "jude": "judah",
    "salmon": "salmon",
    "boaz": "boaz",
    "amminadab": "amminadab", "aminadab": "amminadab",
    "nahshon": "nahshon", "nahesson": "nahshon",
    "zaccur": "zaccur", "zachur": "zaccur",
}

# Pairs of names the text uses interchangeably for one man, but which are
# spelled differently enough that a name-keyed graph treats them as two people.
# A conflict involving one of these is a spelling difference, not a
# contradiction in the sources, and is labelled as such.
NAME_EQUIV = {
    frozenset({"aram", "ram"}),      # 1 Chr 2:10 "Ram" / Luke 3:33 "Aram"
}


# ----------------------------------------------------------------- extraction

def _sentences(text: str) -> list[str]:
    """Split into sentences.

    Sentence boundaries matter more than they look: in a verse with two
    relationships ("Now this is the history of Terah. Terah became the father of
    Abram. Haran became the father of Lot.") the subject of each is the first
    name *of that sentence*.  Taking the first name of the whole verse would
    attribute all three to Terah.
    """
    t = " ".join((text or "").split())
    if not t:
        return []
    parts = re.split(r"(?<=[.;:])\s+(?=[A-Z0-9])", t)
    return [p for p in parts if p.strip()]


def _first_name(sent: str) -> str:
    """The first real name in a sentence, skipping capitalised stop words.

    NAME_RE happily matches "The", and "The days of Adam..." would then name
    nobody, which is how the whole Gen 5 chain came out empty.
    """
    for m in NAME_RE.finditer(sent):
        nm = m.group(0)
        if nm in STOP or _norm(nm) in STOP:
            continue
        return nm
    return ""


# Words that can sit between a relation verb and the first name.  "bore him
# Perez", "had two sons named Dan and ..." -- these are part of the statement,
# not the end of it.  Only honoured before any name has been collected: once a
# name is in hand, a lowercase word means the list has ended.
# Words that can sit between a relation verb and the first *person's* name:
# "bore him Perez", "had two sons named Dan".  Articles and possessives are
# deliberately absent -- peeling "the" off "the Lord" produced a son of the
# Lord called "Lord" out of 1 Kings 2:26.
FILLER = {"him", "her", "them", "it", "two", "three", "four", "five", "six",
          "seven", "eight", "nine", "ten", "son", "sons", "daughter",
          "daughters", "named", "called", "also", "both", "another",
          "other", "others"}


def _names_after(sent: str, pos: int) -> tuple[list[str], bool]:
    """Names after a relation verb, and whether the list was cut short.

    The rule is deliberately strict: a token is only a name if it is *exactly*
    one capitalised word.  Lists in the text are often interrupted by a
    description -- "Reuben, Jacob's firstborn, and Simeon" -- and loosening the
    rule to "take the first capitalised word" turns that description into a
    child called "Jacob", who is not one.  A descriptive token therefore ends
    the list and reports that it ended early, so the caller can mark the
    sibling list as partial rather than let it read as complete.
    """
    out: list[str] = []
    tail = re.split(r"[;:]", sent[pos:])[0]
    filler_word = re.compile(
        r"^(?:" + "|".join(sorted(FILLER, key=len, reverse=True)) + r")\s+", re.I)
    for tok in re.split(r",|\band\b", tail):
        tok = tok.strip().rstrip(".")
        if not tok:
            continue                       # the " and " connector leaves a blank
        # "bore him Perez" is a single comma-token, so the filler has to be
        # peeled off the front of the token rather than skipped as a token.
        while not out and filler_word.match(tok):
            tok = filler_word.sub("", tok, count=1).strip()
        m = re.match(r"^(" + NAME_RE.pattern + r")$", tok)
        if not m:
            return out, bool(out)          # descriptive phrase: list truncated
        nm = m.group(1)
        if nm in STOP or _norm(nm) in STOP:
            return out, bool(out)
        out.append(nm)
    return out, False


# A subject stated as a bare name before the verb.
FORWARD = [
    re.compile(r"\bbecame the father of\b\s*", re.I),
    re.compile(r"\b(?:is|was|became) the father of\b\s*", re.I),
    re.compile(r"\bbegat\b\s*", re.I),
    re.compile(r"\bbore\b\s*", re.I),
    re.compile(r"\bbare\b\s*", re.I),
    re.compile(r"\bhad a son,\s*(?:and|who)\s+(?:he|they)\s+called (?:his|her) name\b\s*", re.I),
    re.compile(r"\bcalled (?:his|her) name\b\s*", re.I),
]

# "He named him Noah" / "she gave him the name X": the child is named in a
# different sentence, and sometimes a different verse, from the one that says a
# son was born.  The parent is a pronoun here, so the caller supplies the
# subject it was already tracking.  These edges are marked "named", not
# "stated", because the relationship is carried across a sentence boundary.
REVEAL = [
    re.compile(r"\bnamed (?:him|her) ([A-Z][A-Za-z']*)", re.I),
    re.compile(r"\b(?:called|whose name was not) (?:his|her|its) name ([A-Z][A-Za-z']*)", re.I),
    re.compile(r"\bgave (?:him|her) the name ([A-Z][A-Za-z']*)", re.I),
    # Deliberately absent: "whose name was X".  In "David was the son of that
    # Ephrathite of Bethlehem, whose name was Jesse" it describes the Ephrathite
    # already named, and treating it as a reveal attached Jesse to David -- the
    # relationship exactly backwards.
]

# An appositive names a second relationship with the noun just mentioned:
# "He is the father of Jesse, the father of David" says Jesse is David's father.
# Ruth 4:17 states the whole Davidic line this way and nothing else does, so
# without this the line breaks exactly where it matters most.
APPOS_FATHER = re.compile(r",\s*the father of\s+([A-Z][A-Za-z']*)", re.I)

# "David said ... to help Solomon his son."  A modern translation states
# fatherhood possessively rather than with a verb of begetting, and Chronicles is
# full of it.  The parent here is the sentence's *subject*, not the nearest
# preceding name: in "David commanded all the princes of Israel to help Solomon
# his son" the nearest name before Solomon is Israel.
# 1 Chronicles 3:10 runs the whole succession in one sentence: "Solomon's son
# was Rehoboam, Abijah his son, Asa his son, Jehoshaphat his son".  Each "X his
# son" is the son of the child named just before it, not of the first name in the
# sentence -- reading it as the latter invented Solomon as the father of Abijah
# and of Asa.
SON_POSSESSIVE = re.compile(
    r"\b([A-Z][A-Za-z']*)'?s? son(?: was)?\s+([A-Z][A-Za-z']*)"
    r"|\b([A-Z][A-Za-z']*) (?:his|her) son\b", re.I)


def _last_name_before(sent: str, pos: int) -> str:
    """The most recent real name before pos, skipping the ones being defined."""
    best = ""
    for m in NAME_RE.finditer(sent[:pos]):
        nm = m.group(0)
        if nm in STOP or _norm(nm) in STOP:
            continue
        best = nm
    return best


# The same relationship stated from the other end.  Here the *captured* name is
# the father and the sentence's subject is the son, which is the opposite of
# every other pattern in this module, so it is handled on its own.
SON_OF = re.compile(r"\b(?:was|is)\s+the son of\s+([A-Z][A-Za-z']*)", re.I)

SONS_OF = re.compile(r"\b(?:the\s+)?sons of ([A-Z][A-Za-z']*) (?:were|are)\s+([^.;:]+)", re.I)
# Two shapes, because a lazy "any chars in between" match latches onto the
# shortest span and then hands _names_after the wrong half of the sentence.
CHILDREN_OF = [
    re.compile(r"\bchildren of ([A-Z][A-Za-z']*)[^.;:]{0,120}:\s*([^.;]+)"),
    re.compile(r"\bchildren of ([A-Z][A-Za-z']*)[^.;:]{0,40}\bwere\s+([^.;]+)"),
]


def extract(text: str, ref: str) -> list[dict]:
    """Read every explicit parent-child statement out of one verse."""
    return extract_verse(text, ref)[0]


def extract_verse(text: str, ref: str,
                  last_subject: str = "") -> tuple[list[dict], str]:
    """Edges from one verse, plus the subject the next verse inherits.

    Genesis 5 needs this.  "Lamech lived one hundred eighty-two years, then
    became the father of a son."  names no child, and the next verse says
    "He named him Noah" -- the son and the father are both pronouns, and the only
    thing connecting them is the paragraph.  So the subject is carried forward
    and a reveal links back to it.  Those edges are marked "named" rather than
    "stated" so the weaker provenance is visible in the tree instead of being
    quietly presented as the same kind of evidence.
    """
    edges: list[dict] = []
    revealed: list[dict] = []

    # List patterns ("the sons of X were A, B, C", "children of X: A, B, C") run
    # over the whole verse.  They must not: a colon is a sentence boundary for
    # the FORWARD patterns, but in "Jacob and his sons: Reuben, Simeon" that
    # colon is precisely what joins the parent to his children, and splitting on
    # it leaves both halves with nothing to attach to.
    whole = " ".join((text or "").split())
    for rx, verb in ((SONS_OF, "sons of"),
                     (CHILDREN_OF[0], "children of"),
                     (CHILDREN_OF[1], "children of")):
        for m in rx.finditer(whole):
            parent = m.group(1)
            if parent in STOP or _norm(parent) in STOP:
                continue
            # start(2), not end(1): the children are group 2, and handing the
            # scan the text between the parent and the children hands it the
            # wrong half of the sentence -- "who came into Egypt, Jacob and
            # his sons" -- which contains no names at all.
            kids, cut = _names_after(whole, m.start(2))
            for kid in kids:
                if kid.lower() == parent.lower():
                    continue
                edges.append({"parent": parent, "child": kid, "ref": ref,
                              "verb": verb, "text": whole,
                              "confidence": "partial" if cut else "stated"})

    # Forward patterns run per sentence, because that is where the subject is.
    # In "Now this is the history of Terah. Terah became the father of Abram.
    # Haran became the father of Lot." the subject of each is the first name of
    # its own sentence; taking the first name of the verse would hand all three
    # relationships to Terah.
    for sent in _sentences(text):
        subject = _first_name(sent)   # fallback; FORWARD prefers the nearer name
        # The subject is the nearest name *before* the verb, not the first name
        # in the sentence.  In "After the exile to Babylon, Jechoniah became
        # the father of Shealtiel" the first name is Babylon and the father is
        # Jechoniah; and in "Seth lived a hundred years, then became the father
        # of Enosh" the first name happens to be the right one.  The nearest
        # preceding name is right in both.
        # Walked in order, and the parent of each is the child named before it.
        # With no earlier child the parent is the sentence's subject, which is
        # what "David ... to help Solomon his son" needs.
        last_child = ""
        last_child = ""
        for m in SON_POSSESSIVE.finditer(sent):
            kid = m.group(2) or m.group(3)
            if not kid or kid in STOP or _norm(kid) in STOP:
                continue
            father = last_child or _first_name(sent)
            if not father or father.lower() == kid.lower():
                continue
            if father in STOP or _norm(father) in STOP:
                continue
            edges.append({"parent": father, "child": kid, "ref": ref,
                          "verb": "his son", "text": sent,
                          "confidence": "stated"})
            last_child = kid
        for m in APPOS_FATHER.finditer(sent):
            kid = m.group(1)
            father = _last_name_before(sent, m.start(1))
            if not father or not kid or father.lower() == kid.lower():
                continue
            if kid in STOP or _norm(kid) in STOP:
                continue
            edges.append({"parent": father, "child": kid, "ref": ref,
                          "verb": "the father of", "text": sent,
                          "confidence": "stated"})
        for m in SON_OF.finditer(sent):
            father = m.group(1)
            if not subject or father.lower() == subject.lower():
                continue
            if father in STOP or _norm(father) in STOP:
                continue
            edges.append({"parent": father, "child": subject, "ref": ref,
                          "verb": "son of", "text": sent, "confidence": "stated"})
        for rx in FORWARD:
            for m in rx.finditer(sent):
                subject = _last_name_before(sent, m.start()) or _first_name(sent)
                kids, cut = _names_after(sent, m.end())
                if not kids or not subject:
                    continue
                if subject in STOP or _norm(subject) in STOP:
                    continue
                for kid in kids:
                    if kid.lower() == subject.lower():
                        continue
                    edges.append({"parent": subject, "child": kid, "ref": ref,
                                  "verb": rx.pattern.split("\\b")[1], "text": sent,
                                  "confidence": "partial" if cut else "stated"})
                break
    # A reveal names a child without naming its parent ("He named him Noah", "She
    # named him Issachar").  The parent is looked for across the *whole verse*,
    # not just the sentence the reveal sits in: Leah is named two sentences
    # earlier in Gen 30:18, and only the verse knows that.
    for rx in REVEAL:
        m = rx.search(whole)
        if not m:
            continue
        child = m.group(1)
        parent = _last_name_before(whole, m.start(1))
        if not parent or parent in STOP or parent.lower() == child.lower():
            parent = last_subject
        if not parent or parent.lower() == child.lower():
            continue
        edges.append({"parent": parent, "child": child, "ref": ref,
                      "verb": "named", "text": whole, "confidence": "named"})
        revealed.append(child)
        break
        if not parent or parent.lower() == r["child"].lower():
            continue
        edges.append({"parent": parent, "child": r["child"], "ref": r["ref"],
                      "verb": "named", "text": r["text"], "confidence": "named"})

    # Who does the next verse inherit?  The most recently named child.  A
    # reveal wins, because "he named him Noah" is what advances the chain; then
    # any stated child.  The fallback to `last_subject` only applies when this
    # verse named nobody -- and it has to be a fallback, not a default, or the
    # chain sticks on the first child it ever found.
    nxt = ""
    for e in edges:
        if e["confidence"] == "named":
            nxt = e["child"]
    if not nxt:
        for e in edges:
            if e["confidence"] == "stated":
                nxt = e["child"]
    if not nxt:
        nxt = _first_name(text) or last_subject
    return edges, nxt


def _inverse_chain(text: str, ref: str,
                   carry: str = "") -> tuple[list[dict], str]:
    """Read Luke 3, which states the line as a chain of "the son of".

    Returns the edges and the last name in the chain, which is what the next
    verse has to continue from.  It is the *last* name, not the child of the last
    edge: in "the son of Amminadab, the son of Aram" the line has reached Aram,
    and carrying Amminadab forward instead made Jacob the father of Amminadab
    and left Aram parentless.

    "...being the son of Heli, which was the son of Matthat, which was the son of
    Levi..."  Reading left to right, each name is the father of the one before
    it.  It is the same relationship as "begat", said the other way round.
    """
    t = " ".join((text or "").split())
    if "son of" not in t.lower():
        # The caller unpacks a pair -- the edges and the carry -- so this has
        # to return a pair too.  It returned a bare list, and a verse with no
        # "son of" in it raised "not enough values to unpack" instead of
        # simply contributing nothing.  A Bible that phrases the line
        # differently is not a crash.
        return [], carry
    # the first name before the first "son of" is the subject of the sentence
    # Which name starts the chain?  In "And Jesus himself was about thirty
    # years old, being the son of Mary" the subject is named before the first
    # "son of", so it belongs at the front.  In a continuation verse -- "the son
    # of David, which was the son of Nathan" -- there is no subject at all: the
    # first name *is* the object of the first "son of".  Prepending it anyway
    # duplicates it and turns the whole line round, which made David the father
    # of Nathan when Luke calls Nathan his father.
    first_son = re.search(r"\bson of\b", t)
    lead = _first_name(t[:first_son.start()]) if first_son else _first_name(t)
    chain = [lead] if lead else ([carry] if carry else [])
    if not chain:
        return [], carry
    for m in re.finditer(r"\bson of\s+([A-Z][A-Za-z']*)", t):
        nm = m.group(1)
        if (nm in STOP or _norm(nm) in STOP) and _norm(nm) != "god":
            continue          # but "the son of God" is stated outright
        chain.append(nm)
    edges = []
    chain[0] = chain[0] or carry
    if len(chain) < 2:
        return [], (chain[0] if chain else carry)
    for i in range(len(chain) - 1):
        child, parent = chain[i], chain[i + 1]
        if _norm(child) == _norm(parent):
            continue
        edges.append({"parent": parent, "child": child, "ref": ref,
                      "verb": "son of", "text": t, "confidence": "stated"})
    return edges, chain[-1]


# ---------------------------------------------------------------- the graph

def pick_source() -> str:
    """An installed English Bible to read the genealogies out of.

    The translation is only a carrier; the relationships are the text's.  A
    plain modern one is preferred because the pattern is explicit ("X became the
    father of Y") rather than a pronoun with an understood subject.
    """
    from . import db
    conn = db.connect()
    have = {r["id"] for r in conn.execute(
        "SELECT id FROM module WHERE installed_at>0 AND type='Bible' "
        "AND lang='eng'")}
    for mid in PREFERRED:
        if mid in have:
            return mid
    return sorted(have)[0] if have else ""


_CACHE: dict = {}


def _verse_in(key: str, lo: int, hi: int) -> bool:
    """True when a unit key names a verse inside lo..hi.

    Luke 3's lineage is a single sentence that spills over verse boundaries, and
    the later verses are continuations of it -- "which was the son of Salmon,
    which was the son of Boaz" -- so the chain has to be read across them rather
    than restarting at each one.

    The verse number is read from the end of the key, and a key belongs to its
    module: "Luke 3:38" in a USFX Bible and "Luke.3.38" in an e-Sword one.  Only
    the colon form was read, so the whole of Luke 3 was skipped on a library of
    e-Sword modules -- and with it the line from Jesus to Adam, and the one
    edge in the whole genealogy that Scripture states outright: Adam's father
    is God.
    """
    for sep in (":", "."):
        if sep in key:
            try:
                return lo <= int(key.rsplit(sep, 1)[-1]) <= hi
            except ValueError:
                continue
    return False


def _verses(mid: str, book: str, lo: int, hi: int) -> list[tuple[str, str]]:
    """The verses of a chapter range, in order.

    Read by the book and chapter the unit *is*, not by the shape of its key.
    A unit key belongs to its module: the same verse is "Gen.5.1" in an e-Sword
    Bible and "Gen 5:1" in a USFX one, and matching the key text found the
    verses of the second and none of the first -- so on a library of e-Sword
    modules the genealogy was empty, and said so by being empty.
    """
    from . import db
    conn = db.connect()
    out = []
    for r in conn.execute(
            "SELECT key, text FROM unit WHERE module_id=? AND book=? AND "
            "chapter BETWEEN ? AND ? AND verse>0 ORDER BY chapter, verse",
            (mid, book, lo, hi)):
        out.append((r["key"], r["text"] or ""))
    return out


def build(*, force: bool = False) -> dict:
    """Read every source chapter and assemble the person graph.

    Edges are merged on (parent, child) after name normalisation, keeping every
    verse that states them: the antediluvian line appears in both Genesis 5 and
    1 Chronicles 1, and two witnesses are worth showing rather than discarding.
    """
    if not force and _CACHE.get("graph"):
        return _CACHE["graph"]
    mid = pick_source()
    if not mid:
        return {"ok": False, "error": "no installed English Bible to read"}

    edges: dict[tuple[str, str], dict] = {}
    subject = ""                     # carried across verses, per chapter
    for book, lo, hi in SOURCES:
        subject = ""
        for key, text in _verses(mid, book, lo, hi):
            found, subject = extract_verse(text, key, subject)
            for e in found:
                k = (_norm(e["parent"]), _norm(e["child"]))
                if not k[0] or not k[1] or k[0] == k[1]:
                    continue
                rec = edges.setdefault(k, {
                    "parent": e["parent"], "child": e["child"],
                    "refs": [], "verbs": set(),
                    "confidence": e["confidence"], "text": e["text"]})
                if key not in rec["refs"]:
                    rec["refs"].append(key)
                rec["verbs"].add(e["verb"])
                # stated beats partial beats named: the strongest evidence wins
                order = {"named": 0, "partial": 1, "stated": 2}
                if order[e["confidence"]] > order[rec["confidence"]]:
                    rec["confidence"] = e["confidence"]

    carry = ""
    for book, chap, v0, v1 in INVERSE_SOURCES:
        # One chapter only.  Passing the verse range to _verses looked right but
        # its bounds are chapters, so Luke 3..38 was read -- which dragged in
        # Luke 18:38, where a blind man cries "you son of David" and became
        # David's son in the tree.
        for key, text in _verses(mid, book, chap, chap):
            if not _verse_in(key, v0, v1):
                continue
            found, carry = _inverse_chain(text, key, carry)
            for e in found:
                k = (_norm(e["parent"]), _norm(e["child"]))
                k = (_norm(e["parent"]), _norm(e["child"]))
                if not k[0] or not k[1] or k[0] == k[1]:
                    continue
                rec = edges.setdefault(k, {
                    "parent": e["parent"], "child": e["child"],
                    "refs": [], "verbs": set(),
                    "confidence": e["confidence"], "text": e["text"]})
                if key not in rec["refs"]:
                    rec["refs"].append(key)
                rec["verbs"].add(e["verb"])

    people: dict[str, dict] = {}
    for (p, c), e in edges.items():
        for key, name in ((p, e["parent"]), (c, e["child"])):
            if key not in people:
                people[key] = {"id": key, "name": name, "variants": set(),
                               "parents": set(), "children": set(), "refs": []}
            if name != people[key]["name"]:
                people[key]["variants"].add(name)
        people[p]["children"].add(c)
        people[c]["parents"].add(p)
        for r in e["refs"]:
            if r not in people[p]["refs"]:
                people[p]["refs"].append(r)
            if r not in people[c]["refs"]:
                people[c]["refs"].append(r)

    for p in people.values():
        p["variants"] = sorted(p["variants"])
        p["parents"] = sorted(p["parents"])
        p["children"] = sorted(p["children"])
        p["refs"] = sorted(set(p["refs"]))

    # Where the sources give one person two different fathers, say so.  Matthew
    # and Luke disagree about Jesus' line between David and Azariah, and both
    # are right; silently keeping one would be a claim the text does not make.
    conflicts = []
    for p in people.values():
        if len(p["parents"]) < 2:
            continue
        pnames = [people[q]["name"] for q in p["parents"]]
        # Why does one name carry more than one father?  Three different reasons,
        # and they are not interchangeable, so they are not reported as one
        # undifferentiated pile:
        #
        #   variant  the two fathers are spelling variants of one name
        #   shared   the fathers belong to unrelated lines, so these are almost
        #            certainly two different men who happen to share a name
        #            (Aaron's son Eleazar the priest, and Eliud's son Eleazar in
        #            Matthew's line)
        #   listed   the same line appears twice with different names, as the
        #            two Benjamite lists in 1 Chronicles 8 and 9 do
        #
        # The verses are listed in every case.  Resolving which it is needs a
        # judgement about the text that a name-keyed graph cannot make, so the
        # graph reports and stops.
        variant = any(frozenset({_norm(a), _norm(b)}) in NAME_EQUIV
                      for i, a in enumerate(pnames) for b in pnames[i + 1:])
        books = {r.split()[0] for r in p["refs"]}
        parent_books = [{r.split()[0] for r in people[q]["refs"]}
                        for q in p["parents"]]
        # Compare the fathers with *each other*, not with the child.  A child
        # naturally appears in the same book as each of its fathers, so testing
        # them against the child's books can never show the lines are separate.
        unrelated = all(not (parent_books[i] & parent_books[j])
                        for i in range(len(parent_books))
                        for j in range(i + 1, len(parent_books)))
        if variant:
            kind = "variant"
        elif unrelated:
            kind = "shared"
        else:
            kind = "listed"
        conflicts.append({
            "name": p["name"], "id": p["id"], "kind": kind,
            "parents": p["parents"], "refs": p["refs"],
            "parent_names": pnames,
            "parent_refs": {people[q]["name"]: people[q]["refs"]
                            for q in p["parents"]},
        })
    conflicts.sort(key=lambda c: (c["kind"], c["name"]))

    graph = {
        "ok": True, "source": mid, "people": people,
        "edges": list(edges.values()),
        "conflicts": conflicts,
        "partial": sorted({e["parent"] + " → " + e["child"]
                           for e in edges.values() if e["confidence"] == "partial"}),
        "counts": {
            "people": len(people), "edges": len(edges),
            "refs": len({r for e in edges.values() for r in e["refs"]}),
        },
    }
    _CACHE["graph"] = graph
    return graph


def person(name: str) -> dict:
    g = build()
    p = g["people"].get(_norm(name))
    if not p:
        return {"ok": False, "error": f"no person called {name!r} in the text read"}
    def show(ids):
        return [{"id": i, "name": g["people"][i]["name"],
                 "refs": g["people"][i]["refs"]} for i in ids if i in g["people"]]
    return {"ok": True, "person": {**p, "variants": p["variants"],
                                   "parent_list": show(p["parents"]),
                                   "child_list": show(p["children"])}}


def ancestry(name: str, depth: int = 12) -> dict:
    """Walk up the parents, breadth first, one generation per level."""
    g = build()
    start = g["people"].get(_norm(name))
    if not start:
        return {"ok": False, "error": f"no person called {name!r} in the text read"}
    levels = [[{"id": start["id"], "name": start["name"], "refs": start["refs"]}]]
    seen = {start["id"]}
    frontier = [start["id"]]
    for _ in range(depth):
        nxt = []
        for pid in frontier:
            for par in g["people"][pid]["parents"]:
                if par in seen:
                    continue
                seen.add(par)
                nxt.append(par)
        if not nxt:
            break
        levels.append([{"id": i, "name": g["people"][i]["name"],
                        "refs": g["people"][i]["refs"],
                        "parents": g["people"][i]["parents"]} for i in nxt])
        frontier = nxt
    return {"ok": True, "start": start["name"], "levels": levels,
            "generations": len(levels) - 1}


def subtree(name: str, depth: int = 3) -> dict:
    """Walk down the children, breadth first."""
    g = build()
    start = g["people"].get(_norm(name))
    if not start:
        return {"ok": False, "error": f"no person called {name!r} in the text read"}
    seen = {start["id"]}
    out = []
    frontier = [(start["id"], 1)]
    while frontier:
        pid, d = frontier.pop(0)
        if d > depth:
            continue
        kids = g["people"][pid]["children"]
        if not kids:
            continue
        out.append({"id": pid, "name": g["people"][pid]["name"],
                    "depth": d, "children": [
                        {"id": k, "name": g["people"][k]["name"],
                         "refs": g["people"][k]["refs"]}
                        for k in kids if k in g["people"]]})
        for k in kids:
            if k not in seen:
                seen.add(k)
                frontier.append((k, d + 1))
    return {"ok": True, "start": start["name"], "branches": out}


def summary() -> dict:
    """What the panel leads with."""
    g = build()
    if not g.get("ok"):
        return g
    people = g["people"]
    by_ref = {}
    for p in people.values():
        by_ref.setdefault(p["refs"][0].split()[0] if p["refs"] else "?", []).append(p)
    return {
        "ok": True,
        "source": g["source"],
        "counts": g["counts"],
        "conflicts": g["conflicts"],
        "partial": g["partial"],
        "longest": max((len(r) for r in by_ref.values()), default=0),
        "books": sorted({r.split()[0] for p in people.values()
                         for r in p["refs"]}),
        "conflicts_note": "A name with more than one father is not a mistake in "
            "the text, and not a mistake here either: it is two people sharing "
            "a name, or one line given twice, or a spelling variant. Each is "
            "labelled and the verses are listed, so which one it is can be "
            "checked rather than guessed at.",
        "note": "Every relationship here was read out of the text of one "
                "installed translation, and each edge keeps the verses that "
                "state it. Where a list was cut short by a description the edge "
                "is marked partial rather than presented as the whole family.",
    }

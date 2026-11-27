"""Resolve a question into likely Scripture references.

The chat pipeline used to depend on the language model guessing an exact
``bible:"Num 20:12"`` query.  That works with a large model and fails with a
small one — the person and the event are in different verses, so no keyword
search that requires both in one unit finds the answer.  This module does the
resolution with the app's own structured data instead:

1. explicit references written in the question;
2. chapter-level co-occurrence of a named subject with the event words around it.

Nothing here invents a reference: every candidate comes from a reference the
reader typed or a passage found in an installed Bible.  The caller uses these
as *candidates* to fetch and show, not as proof that any of them is the answer.
"""

from __future__ import annotations

import re
from collections import defaultdict

from . import canon, library, search

_STOP = {
    "what", "who", "whom", "where", "when", "why", "how", "does", "did",
    "do", "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "about", "bible", "say", "says", "tell", "me", "of", "in", "on", "to",
    "for", "and", "or", "can", "could", "would", "should", "i", "you",
    "many", "much", "while", "though", "there", "their", "them", "then",
    "than", "into", "onto", "during", "he", "she", "him", "his", "her",
    "it", "its", "we", "us", "our", "they", "these", "those", "this",
    "that", "please", "explain", "give", "show", "according", "not",
    "actually", "wrong", "correct", "meant", "following", "mean", "means",
}

_NAME_RE = re.compile(r"\b[A-Z][A-Za-z]{2,}\b")
_WORD_RE = re.compile(r"[^\W\d_]+")


def content_terms(text: str) -> set[str]:
    """Meaningful, lightly stemmed words in a question or passage."""
    out: set[str] = set()
    for word in _WORD_RE.findall((text or "").lower()):
        if word in _STOP or len(word) < 3:
            continue
        if len(word) > 5 and word.endswith("ing"):
            word = word[:-3]
        elif len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith("s"):
            word = word[:-1]
        elif len(word) > 4 and word.endswith("ed"):
            word = word[:-2]
        if word not in _STOP:
            out.add(word)
    return out


def named_terms(text: str) -> set[str]:
    """Likely proper subjects, lowercased, excluding question scaffolding."""
    return {
        m.lower() for m in _NAME_RE.findall(text or "")
        if m.lower() not in _STOP
    }


def explicit_refs(question: str) -> list[canon.Ref]:
    """References the reader actually wrote in the question."""
    out: list[canon.Ref] = []
    for found in canon.scan_refs(question or ""):
        rr = canon.parse_ref(str(found.get("ref") or ""))
        if not rr:
            continue
        if (rr.start == rr.end and rr.start.chapter and not rr.start.verse):
            # "Numbers 20" means the whole chapter.  Expanding it into verses
            # would take only the first three after the limit is applied, which
            # is exactly the wrong thing when the answer is in verse 12.
            out.append(canon.Ref(rr.start.book, rr.start.chapter))
            continue
        for r in rr.refs():
            ref = canon.Ref(r.book, r.chapter, r.verse)
            if ref not in out:
                out.append(ref)
    return out


def chapter_refs(question: str, limit: int = 3,
                 module_ids: list[str] | None = None) -> list[canon.Ref]:
    """Chapters where a named subject and the event words occur together.

    A broad one-word search is run for each distinctive word, then hits are
    grouped by (book, chapter).  A chapter qualifies only when it contains both
    a subject name and at least one event word, so "Moses" alone cannot pull in
    every chapter that mentions him.  Ranking favours chapters that hold more
    of the question's distinctive words and have several event-bearing verses.
    """
    names = sorted(named_terms(question))
    raw = content_terms(question)
    events = [w for w in sorted(raw) if w not in names]
    if not names or not events:
        return []
    allowed = set(module_ids) if module_ids else None
    bible_ids = [m.id for m in library.list_all()
                 if m.is_bible and (allowed is None or m.id in allowed)]
    if not bible_ids:
        return []
    hits: list[dict] = []
    seen: set[tuple] = set()
    for term in names[:2] + events[:5]:
        try:
            res = search.search(term, search.SearchOpts(
                modules=bible_ids, limit=200, context=0,
                snippets=False, smart=False))
        except Exception:                                   # noqa: BLE001
            continue
        for h in res.get("hits") or []:
            key = (h.get("module_id", ""), h.get("key", ""))
            if key in seen:
                continue
            seen.add(key)
            hits.append(h)
    if not hits:
        return []

    name_set, event_set = set(names), set(events)
    chapter_words: dict[tuple[str, int], set[str]] = defaultdict(set)
    chapter_verses: dict[tuple[str, int], set[int]] = defaultdict(set)
    for h in hits:
        rr = (canon.parse_osis_ref(str(h.get("key") or ""))
              or canon.parse_ref(str(h.get("label") or "")))
        if not rr:
            continue
        first = next(iter(rr.refs()), None)
        if first is None or not first.chapter:
            continue
        chapter = (first.book, first.chapter)
        found = content_terms((h.get("label") or "") + " " + (h.get("text") or ""))
        chapter_words[chapter].update(found)
        if len(found & event_set) >= min(2, len(event_set)):
            chapter_verses[chapter].add(first.verse)

    ranked: list[tuple[int, tuple[str, int]]] = []
    for chapter, found in chapter_words.items():
        name_hits = found & name_set
        event_hits = found & event_set
        if not name_hits or not event_hits:
            continue
        score = (4 * len(name_hits) + 3 * len(event_hits)
                 + min(4, len(chapter_verses.get(chapter, ()))))
        ranked.append((score, chapter))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [canon.Ref(book, chapter) for _score, (book, chapter)
            in ranked[:limit]]


def resolve(question: str, provider=None, limit: int = 4,
            module_ids: list[str] | None = None) -> list[canon.Ref]:
    """Candidate references for a question, best first, without duplication.

    Explicit references in the question win; chapter-level co-occurrence of a
    named subject with the event words is the fallback.
    """
    out: list[canon.Ref] = []

    def add(refs: list[canon.Ref]) -> None:
        for ref in refs:
            if ref not in out:
                out.append(ref)

    add(explicit_refs(question))
    if len(out) < limit:
        add(chapter_refs(question, limit=limit - len(out),
                         module_ids=module_ids))
    return out[:limit]


def as_queries(refs: list[canon.Ref]) -> list[str]:
    """The app's search syntax for a list of references."""
    return [f'bible:"{canon.format_ref(ref)}"' for ref in refs]

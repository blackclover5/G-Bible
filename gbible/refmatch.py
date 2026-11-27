"""Reference matching that keeps whole-book and whole-chapter granularity.

``canon.parse_ref(...).refs()`` expands a book-level reference to only verse 1
of every chapter, which is fine for reading a verse but wrong for asking "does
this event, cited as 'Isa', cover Isaiah 7:2?".  Here a reference is a small set
of milestones whose zero means "any": ``('Gen', 0, 0)`` is the whole book,
``('Gen', 21, 0)`` the whole chapter.
"""

from __future__ import annotations

import re

from . import canon


def milestones(text: str) -> list[tuple[str, int, int]]:
    """Parse a reference into (book, chapter, verse) milestones, 0 = any."""
    rr = canon.parse_ref(text or "")
    if rr is None:
        return []
    s = rr.start
    if s.chapter == 0:
        return [(s.book, 0, 0)]
    e = rr.end
    if s.verse == 0 and e.verse == 0:
        if s.chapter == e.chapter:
            return [(s.book, s.chapter, 0)]
        return [(s.book, s.chapter, 0), (e.book, e.chapter, 0)]
    out = [(s.book, s.chapter, s.verse)]
    tail = (e.book, e.chapter, e.verse)
    if tail != out[0]:
        out.append(tail)
    return out


def covers(milestone, target) -> bool:
    """Does a (possibly wildcard) milestone include a concrete reference?"""
    return (milestone[0] == target[0]
            and (milestone[1] == 0 or milestone[1] == target[1])
            and (milestone[2] == 0 or milestone[2] == target[2]))


def _bounds(milestones):
    """Turn a milestone list into an inclusive (low, high) interval."""
    if len(milestones) == 1:
        book, chapter, verse = milestones[0]
        if chapter == 0:
            return (book, 0, 0), (book, 999, 999)
        if verse == 0:
            return (book, chapter, 0), (book, chapter, 999)
        return (book, chapter, verse), (book, chapter, verse)
    return milestones[0], milestones[-1]


def intersects(left, right) -> bool:
    """Do two reference sets overlap, including whole books and ranges?"""
    for a in left:
        lo_a, hi_a = _bounds(a)
        for b in right:
            lo_b, hi_b = _bounds(b)
            if lo_a[0] == lo_b[0] and lo_a <= hi_b and lo_b <= hi_a:
                return True
    return False


def parse_cited(text: str) -> list[list[tuple[str, int, int]]]:
    """Parse a citation list such as 'Gen 21:1–24; 26' or '2 Kgs 24; 25'.

    A bare number after a named book repeats that book as a chapter, which is
    how the timeline's compact reference lists are written.
    """
    out: list[list[tuple[str, int, int]]] = []
    last_book = ""
    for piece in re.split(r"[;,]\s*", text or ""):
        piece = piece.strip()
        if not piece or piece == "—":
            continue
        bare = re.match(r"^\d{1,3}(?::\d{1,3})?$", piece)
        if bare and last_book:
            piece = last_book + " " + piece
        else:
            named = re.match(r"^([1-3]?\s?[A-Za-z]{2,})", piece)
            if named:
                last_book = named.group(1)
        found = milestones(piece)
        if found:
            out.append(found)
    return out

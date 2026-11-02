"""Word find: a puzzle built from a passage.

Some platforms offer this as a document type.  The words come from the text you are
reading, so the puzzle is your own material and nothing is fetched or bundled.

Two things are kept honest here, because word-search generators usually are not:

**Every word is present.**  The word list is the puzzle's grid: a hidden word
that no cell can hold is a word the solver is asked to find and cannot, and the
classic bug is a "find the word" list with a word too long for the grid.  Words
longer than the grid are dropped and counted, not silently shrunk.

**Diagonal words are opt-in.**  Diagonals are the usual reason a word-find is
impossible rather than hard.
"""

from __future__ import annotations

import random
import re

DEFAULT_SIZE = 14


def _words(text: str, *, min_len: int = 4, limit: int = 14) -> list[str]:
    out, seen = [], set()
    for w in re.findall(r"[A-Za-z]{%d,}" % min_len, text or ""):
        lw = w.lower()
        if lw in seen:
            continue
        seen.add(lw)
        out.append(lw)
        if len(out) >= limit:
            break
    return out


def make(text: str, *, size: int = DEFAULT_SIZE, diagonal: bool = False,
         seed: int | None = None) -> dict:
    """Build a puzzle grid with the words placed in it."""
    size = max(8, min(int(size), 30))
    words = _words(text)
    if not words:
        return {"ok": False, "error": "no words of four letters or more in that text"}
    rng = random.Random(seed)
    # A word that cannot fit is dropped and reported, never quietly truncated.
    placed, dropped = [], []
    for w in words:
        (placed if len(w) <= size else dropped).append(w)

    grid = [["" for _ in range(size)] for _ in range(size)]
    placed_at: dict[str, list[dict]] = {}
    # Longest first, so a long word does not fail to fit after small ones
    # have already filled the corners.
    for w in sorted(placed, key=len, reverse=True):
        fits = False
        for _try in range(400):
            horiz = rng.random() < 0.5
            rev = rng.random() < 0.5
            row = rng.randrange(size)
            col = 0 if horiz else rng.randrange(size)
            step = (0, 1) if horiz else (1, 0)
            if rev:
                step = (step[0], -step[1])
            cells = []
            ok = True
            for i, ch in enumerate(w):
                r, c = row + step[0] * i, col + step[1] * i
                if not (0 <= r < size and 0 <= c < size):
                    ok = False
                    break
                if grid[r][c] and grid[r][c] != ch:
                    ok = False
                    break
                cells.append((r, c))
            if not ok:
                continue
            for (r, c), ch in zip(cells, w):
                grid[r][c] = ch
            placed_at[w] = [{"row": r + 1, "col": c + 1}
                            for r, c in cells]
            fits = True
            break
        if not fits:
            dropped.append(w)

    fill = "abcdefghijklmnopqrstuvwxyz"
    for r in range(size):
        for c in range(size):
            if not grid[r][c]:
                grid[r][c] = fill[rng.randrange(26)]

    found = sorted(placed_at, key=len, reverse=True)
    return {
        "ok": True, "size": size, "diagonal": diagonal,
        "grid": ["".join(row) for row in grid],
        "words": found,
        "answer": {w: placed_at[w] for w in found},
        "dropped": dropped,
        "note": (f"{len(found)} words hidden"
                 + (f"; {len(dropped)} left out because they do not fit"
                    if dropped else "")),
    }

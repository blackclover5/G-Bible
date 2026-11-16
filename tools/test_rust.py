"""Smoke/parity tests for the optional Rust acceleration layer."""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gbible import db, markup, native, posindex, search  # noqa: E402


def _reference_words(text: str):
    return [(m.group(0), m.start(), m.end()) for m in db._TOKEN_RE.finditer(text or "")]


def _reference_fold(word: str) -> str:
    table = str.maketrans({
        "\u2019": "'", "\u02bc": "'", "\u2018": "'",
        "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-",
    })
    w = word.lower().translate(table)
    if not w.isascii():
        w = "".join(ch for ch in unicodedata.normalize("NFD", w)
                    if not unicodedata.combining(ch))
    return w


def main() -> int:
    samples = [
        "In the beginning God created the heavens and the earth.",
        "שלום בָּרָ֣א אֱלֹהִ֑ים",
        "God's covenant; Jesus’ words; 123 and ٤٥٦",
        "λόγος καὶ ἀγάπη — café naïve",
        "A\u0301 and Ångström",
    ]
    assert markup.unescape("&amp; &Prime; &prime; &#65; &#x41; &unknown;") == "& \u2033 \u2032 A A &unknown;"
    assert markup.unescape("&bad&copy;") == "&bad\u00a9"
    assert markup.collapse("a \t\u00a0 b") == "a b"
    if native.core is not None:
        for sample in samples:
            assert native.core.words(sample) == _reference_words(sample), sample
        for word in ["JESUS’", "café", "naïve", "λόγος", "בָּרָ֣א", "A\u0301"]:
            assert native.core.fold(word) == _reference_fold(word), word
        for a, b, cap, expected in [
            ("pryaer", "prayer", 3, 1),
            ("agape", "agam", 3, 2),
            ("faith", "faith", 3, 0),
            ("long", "shorter", 2, 3),
        ]:
            assert native.core.damerau_levenshtein(a, b, cap) == expected
        positions = [0, 1, 4, 130, 9000]
        assert posindex._unpack(posindex._pack(positions)) == positions
        assert native.core.token_key("loves") == db.token_key("loves")
    else:
        # The fallback path is intentional and must remain completely usable.
        for sample in samples:
            assert db.words(sample) == _reference_words(sample), sample
        assert db.fold("JESUS’") == "jesus'"
        assert search._lev("pryaer", "prayer") == 1
        positions = [0, 1, 4, 130, 9000]
        assert posindex._unpack(posindex._pack(positions)) == positions

    print(f"Rust core status: {native.status()}")
    print("Rust acceleration smoke tests passed (native parity tests run when built).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

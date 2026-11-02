"""Re-type modules the importer filed under the wrong kind.

    python3 tools/fix_module_types.py            # report
    python3 tools/fix_module_types.py --apply

A module's type is not decoration.  It decides which reader opens it, which
facets list it, whether it appears among the lexicons when a reader clicks a
Strong's number, and whether `topicindex.py` indexes its entries to verses.  So
a module filed under the wrong type is not merely labelled oddly -- it is wired
into the wrong features, and the features that would have served it never see
it.

This was written for two modules, and it exists because the classification is
not something to fix by hand in a database.  A hand edit is unrepeatable,
unreviewable, and gone the next time the module is re-installed from the Store,
which is the only way the reader will ever get a newer copy of it.

    crosswire-klven-iklingon    Klingon -> English, 1,019 entries
    crosswire-klviklingon-en    English -> Klingon,   808 entries

Both arrived typed `FactBook`.  A Fact book is one article per *topic*, addressed
to scripture -- Nave, Torrey, Hitchcock, the Cyclopedia -- which is what
`topicindex.py` assumes when it builds a topic-to-verse index.  A bilingual
glossary is none of those things: its entries are word-for-word translations
with no scripture in them, so the topic index spent work on it, produced
nothing usable, and neither the concordance nor the word lists nor the lexicon
readers ever offered it.  `Lexicon` is what it is, and the two together then
appear where a reader looking up a word would look.

The rules are stated as data rather than as a list of module ids, so that a
module re-installed from the Store is corrected again rather than reverting:

  * `FactBook` or `Dictionary` with `subject` naming Linguistics, and a language
    that is not English, and entries that are two-way word lists -- corrected to
    `Lexicon`.

Nothing is written unless `--apply` is given, and `--apply` still prints every
row it intends to change first.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gbible import db, library                       # noqa: E402


def candidates() -> list[tuple]:
    """Installed modules whose type does not match what they contain."""
    out = []
    for m in library.list_all(installed_only=False):
        want = wanted_type(m)
        if want and want != m.type:
            out.append((m, want))
    return out


def wanted_type(m) -> str | None:
    """The type this module should have, or None if its type is fine."""
    # FactBook and nothing else.  `topicindex.TOPIC_TYPES` is exactly
    # `("FactBook",)` -- that single tuple is what decides which modules get
    # their entries indexed as topics addressed to verses -- so FactBook is the
    # only type whose mis-filing has this consequence.  Dictionary is left
    # alone: a word list is a reasonable Dictionary, and this library has
    # Swedish and English ones that are correctly typed.
    if m.type != "FactBook":
        return None
    subjects = m.subject if isinstance(m.subject, list) else []
    if isinstance(subjects, str):
        import json
        try:
            subjects = json.loads(subjects)
        except (json.JSONDecodeError, TypeError):
            subjects = []
    subjects = [str(s).lower() for s in (subjects or [])]
    # `Linguistics` narrows it to word lists rather than topic books -- but on
    # its own it decides nothing, because Crosswire tags *every* Bible
    # reference work with it, Hitchcock's names dictionary and the Condensed
    # Cyclopedia included.  Both of those are correctly FactBook and are left
    # alone.
    if "linguistics" not in subjects:
        return None
    # The language is what actually separates them, and it is worth being
    # explicit about why it is safe.  A Fact book's entries are topics addressed
    # to scripture, and the scripture they address is the English Bible: all
    # eight of this library's topic books are English.  A FactBook in some other
    # language is not addressing this library's scripture at all -- it is a
    # bilingual glossary for that language, which is a lexicon, and indexing its
    # entries as topics produces nothing usable.  It also comes with the reader
    # it deserves: `placement.OVERRIDES` files both Klingon modules as
    # `Lexicon` so they open by headword.
    if (m.lang or "").lower() in ("eng", "en", ""):
        return None
    return "Lexicon"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--apply", action="store_true",
                    help="actually write the change (default: report only)")
    args = ap.parse_args()
    db.init()
    found = candidates()
    if not found:
        print("Every installed module is filed under the right type.")
        return 0
    for m, want in found:
        print(f"  {m.id}")
        print(f"      {m.name}  ({m.entries or 0} entries, lang {m.lang})")
        print(f"      {m.type} -> {want}")
        if m.subject:
            print(f"      subject: {m.subject}")
    if not args.apply:
        print(f"\n{len(found)} module(s) would change. Re-run with --apply.")
        return 0
    conn = db.connect()
    for m, want in found:
        # Through library.register, so the module row is written by the same
        # path an install uses -- including bumping the library generation,
        # which is what retires the search vocabularies built from it.
        row = conn.execute("SELECT * FROM module WHERE id=?", (m.id,)).fetchone()
        fields = {k: row[k] for k in row.keys()
                  if k not in ("type", "id", "installed_at")}
        fields["type"] = want
        library.register(conn, id=m.id, **fields)
        db.log_history("retype", f"{m.id}: {m.type} -> {want}")
    conn.commit()
    print(f"\n{len(found)} module(s) re-typed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build the positional index.

The index maps a word to every unit it occurs in and every position it occurs
at, so that proximity, order, phrases and conjunctions can be answered from
postings instead of by re-reading the text of every candidate.

    python3 tools/build_pos_index.py              # build anything missing
    python3 tools/build_pos_index.py --rebuild    # discard and start over
    python3 tools/build_pos_index.py --status     # what is indexed

It is a tool rather than part of installation because it is large: about 36
million rows and roughly 800 MB on a library of 1.2 million units, and around
thirteen minutes to build.  Search works without it -- every lookup returns
nothing and the engine falls back to reading text -- so this is an optimisation
that can be deleted without changing a single answer.

Rebuild after installing or removing modules, or after any repair that rewrites
`unit.text`, since the index is derived from it.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gbible import db, posindex  # noqa: E402


USAGE = """\
usage: build_pos_index.py [--status] [--verify] [--rebuild] [--ends] [--quiet]
                          [module name ...]

  (no arguments)   build or top up the positional index, incrementally
  --status         report what is built, and exit
  --verify         prove the index matches the unit table (slow, ~20s)
  --rebuild        discard and rebuild from scratch
  --ends           fill in the word lengths that `WITHIN n CHARS` needs, for an
                   index that was built without them.  Safe to interrupt, and
                   the index keeps answering every other operator while it runs.
  --quiet          less commentary; with --verify, skip the deep check
  module name ...  restrict to matching modules

Installing a book needs none of this: the app keeps the index current in the
background, and only falls back to a command line for a whole-library rebuild.
"""


def main(argv: list[str]) -> int:
    if "--help" in argv or "-h" in argv:
        print(USAGE)
        return 0
    if "--status" in argv:
        cov = posindex.coverage()
        print(f"  built: {cov['built']}")
        print(f"  terms: {cov['terms']:,}   rows: {cov['rows']:,}   "
              f"units: {cov['units']:,}")
        if cov["built"]:
            print(f"  positions capped at {cov['max_positions']} per word per unit")
            print(f"  word lengths: {cov['ends_rows']:,} rows"
                  + ("" if cov.get("ends")
                     else "  -- incomplete; run with --ends"))
        if "--verify" in argv:
            rep = posindex.audit(deep="--quiet" not in argv)
            print(("  audit: ok -- " if rep.get("ok") else "  audit: PROBLEM -- ")
                  + (rep.get("note") or "coverage is consistent"))
            if not rep.get("ok"):
                return 1
        return 0 if cov["built"] else 1

    names = [a for a in argv if not a.startswith("-")]
    rebuild = "--rebuild" in argv
    modules = None
    if names:
        from gbible.library import list_all
        picked = [m.id for m in list_all()
                  if any(n.lower() in m.id.lower() or n.lower() in (m.name or "").lower()
                         for n in names)]
        if not picked:
            print(f"  no module matches {names}")
            return 1
        modules = picked

    # The length table on its own: an index built before it existed answers every
    # operator except `WITHIN n CHARS`, so filling it in must not wait for a
    # rebuild of the postings, and must not take them offline while it runs.
    if "--ends" in argv and not rebuild:
        cov0 = posindex.coverage()
        if posindex.ends_available() and modules is None:
            print(f"  word lengths are already complete "
                  f"({cov0['ends_rows']:,} rows).")
            return 0
        units_now = max(posindex.staleness().get("units", 0), cov0["units"])
        print(f"  filling in word lengths over {units_now:,} units; "
              f"this takes some minutes")
        t0 = time.time()
        r = posindex.build_ends(modules, verbose=True)
        print(f"  {r['rows']:,} lengths over {r['units']:,} units in "
              f"{time.time() - t0:.0f}s")
        if not posindex.ends_available():
            print("  incomplete: run it again to finish the remaining modules")
        return 0

    # `coverage()` reports what exists; `available()` reports whether it can be
    # trusted.  An index overtaken by new installs is retired, not finished, and
    # saying "already built" there means the user never learns why their searches
    # have got slow again.
    if posindex.available() and not rebuild and modules is None:
        cov0 = posindex.coverage()
        print(f"  up to date: {cov0['rows']:,} rows. Use --rebuild to redo it.")
        if not cov0.get("ends"):
            print("  word lengths are missing; run with --ends for "
                  "`WITHIN n CHARS`")
        return 0
    stale = posindex.staleness()
    if stale.get("built") and stale.get("reason"):
        print(f"  retired: {stale['reason']}")

    units_now = max(stale.get("units", 0), posindex.coverage()["units"])
    print(f"  building the positional index over {units_now:,} units; "
          f"this takes some minutes")
    t0 = time.time()
    r = posindex.build(modules, verbose=True, rebuild=rebuild)
    print(f"  {r['rows']:,} rows, {r['terms']:,} terms, "
          f"{r['positions']:,} positions in {time.time() - t0:.0f}s")
    if r["capped"]:
        print(f"  {r['note']}")
    st = posindex.ensure_stems()
    if st.get("updated"):
        print(f"  stems: {st['updated']:,} terms marked "
              f"({st.get('terms', 0):,} total)")
    if "--verify" in argv:
        # The explicit proof, deliberately kept off every request path: it costs
        # about twenty seconds.  See posindex.audit() for why it cannot be cheap.
        rep = posindex.audit(deep="--quiet" not in argv)
        print(("  audit: ok -- " if rep.get("ok") else "  audit: PROBLEM -- ")
              + (rep.get("note") or "coverage is consistent"))
        if not rep.get("ok"):
            return 1
    cov = posindex.coverage()
    print(f"  coverage: {cov['rows']:,} rows over {cov['units']:,} units"
          + (f", {cov['ends_rows']:,} word lengths" if cov.get("ends")
             else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
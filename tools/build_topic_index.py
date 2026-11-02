"""Build the topic marker index.

The topic index turns "what does this verse have an article about?" from a scan
of the Fact-book bodies into an index lookup.  It is built once per Fact-book
module and stored in the `xref` table under `kind='topic'`, so there is nothing
new to store and nothing new to keep in step with the text.

Run it after installing or removing a Fact book:

    python3 tools/build_topic_index.py            # every topic-indexed module
    python3 tools/build_topic_index.py nave torrey   # just these

It is safe to re-run: markers for a module are replaced rather than accumulated,
so a module that has been re-imported does not keep references pointing at text
that has changed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gbible import topicindex  # noqa: E402


def main(argv: list[str]) -> int:
    verbosity = "--quiet" not in argv
    names = [a for a in argv if not a.startswith("-")]
    modules = None
    if names:
        # Accept a partial module id or a fragment of its name.
        from gbible.library import list_all
        picked = []
        for m in list_all():
            if m.type not in topicindex.TOPIC_TYPES:
                continue
            low = (m.name or "").lower()
            if any(n.lower() in m.id.lower() or n.lower() in low for n in names):
                picked.append(m.id)
        if not picked:
            print(f"  no topic-indexed module matches {names}")
            return 1
        modules = picked
    r = topicindex.build(modules, verbose=verbosity)
    print(f"  {r['rows']:,} topic markers across {r['modules']} modules")
    if r["truncated"]:
        print(f"  {r['note']}")
    cov = topicindex.coverage()
    print(f"  coverage: {cov['markers']:,} markers over {cov['units']:,} entries; "
          f"{cov['note']}")
    if cov["indexed_but_no_references"]:
        print("  no scripture references, so nothing to index: "
              + ", ".join(cov["indexed_but_no_references"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
"""Score the conservative pronoun resolver against a hand-labelled set.

The gold file lives in ``gbible/tests/data/coref_gold.conllu``.  Each sentence
carries an optional ``# expect`` comment naming the resolutions that should
happen there; a sentence with none should produce no resolution.  The set is
synthetic and hand-written by this project, not a published annotated corpus,
so its score measures whether the rules do what we intend -- not how well they
would do on real Scripture.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gbible import coref, db, formats          # noqa: E402

GOLD = ROOT / "gbible" / "tests" / "data" / "coref_gold.conllu"


def expectations(path: Path = GOLD) -> list[list[tuple[str, str, str]]]:
    """Expected (pronoun, folded antecedent, role) triples per sentence."""
    out: list[list[tuple[str, str, str]]] = []
    for block in path.read_text(encoding="utf-8").strip().split("\n\n"):
        lines = block.splitlines()
        # The leading comment block has no tokens; load_conllu skips it too.
        if not any(line[:1].isdigit() for line in lines):
            continue
        spec = ""
        for line in lines:
            if line.startswith("# expect"):
                spec = line.split("=", 1)[1].strip()
        items: list[tuple[str, str, str]] = []
        if spec:
            for part in spec.split(";"):
                pron, rest = part.split(">", 1)
                name, role = rest.split(":", 1)
                items.append((pron.strip().lower(), db.fold(name.strip()),
                              role.strip()))
        out.append(items)
    return out


def evaluate(path: Path = GOLD, *, window: int = 3) -> dict:
    units = list(formats.conllu.load_conllu(path))
    want = expectations(path)
    resolver = coref.Resolver(window=window)
    got: list[list[tuple[str, str, str]]] = []
    for unit in units:
        rows = resolver.resolve(unit.key, (unit.extra or {}).get("syntax") or [])
        got.append([
            (str(row.get("surface") or "").lower(),
             row.get("value") or "", row.get("role") or "")
            for row in rows
        ])
    tp = fp = fn = 0
    mistakes = []
    for index, (expected, actual) in enumerate(zip(want, got), 1):
        e, a = set(expected), set(actual)
        tp += len(e & a)
        fp += len(a - e)
        fn += len(e - a)
        if e != a:
            mistakes.append({"sentence": index, "expected": sorted(e),
                             "got": sorted(a)})
    return {
        "sentences": len(got), "tp": tp, "fp": fp, "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else 1.0,
        "recall": tp / (tp + fn) if tp + fn else 1.0,
        "mistakes": mistakes,
    }


def main() -> int:
    r = evaluate()
    print(f"sentences: {r['sentences']}")
    print(f"true positives: {r['tp']}  false positives: {r['fp']}  "
          f"false negatives: {r['fn']}")
    print(f"precision: {r['precision']:.3f}  recall: {r['recall']:.3f}")
    for m in r["mistakes"]:
        print(f"  sentence {m['sentence']}: expected {m['expected']}, "
              f"got {m['got']}")
    ok = r["precision"] >= 0.95 and r["recall"] >= 0.90
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

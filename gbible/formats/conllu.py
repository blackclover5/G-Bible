"""CoNLL-U syntax treebank reader (Universal Dependencies and friends).

A `.conllu` file is sentences of tab-separated tokens with `#` comment lines.
Each sentence becomes one unit: the surface text for reading and search, and
the dependency edges in `extra["syntax"]` for the syntax panel. Where a
sentence names its verse — `# sent_id = John 3:16`, `# reference = Gen-1-1`,
`# newdoc id = Matt-1` — the unit is keyed to that verse (`John.3.16`) and
carries book/chapter/verse, so it links with Bibles and commentaries through
the ordinary milestone rule. Sentences with no readable reference are kept as
`syn-NNNNN` units instead of dropped: an unmapped tree is still searchable.

Only the open formats are read: plain CoNLL-U. Anything else in the file is
left out and counted, never guessed at.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from .. import canon
from ..indexer import UnitIn
from ..markup import Seg


def sniff_conllu(data: bytes | None, name: str = "") -> bool:
    n = (name or "").lower()
    if n.endswith((".conllu", ".conll", ".conll-u", ".conllu.txt")):
        return True
    if data:
        try:
            head = data[:4000].decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return False
        lines = [ln for ln in head.splitlines()
                 if ln.strip() and not ln.startswith("#")]
        if len(lines) >= 3 and sum(1 for ln in lines[:10]
                                   if len(ln.split("\t")) >= 6) >= 3:
            return True
    return False


_REF_HINTS = ("sent_id", "reference", "ref", "verse", "newdoc", "newpar")


def _ref_from_meta(meta: dict[str, str]) -> str:
    for k in _REF_HINTS:
        v = (meta.get(k) or "").strip()
        if not v:
            continue
        # "John-3-16", "John_3_16", "John.3.16" are all the same reference.
        cand = re.sub(r"[_.\-]", " ", v)
        cand = re.sub(r"\s+", " ", cand).strip()
        rr = canon.parse_ref(cand)
        if rr is not None:
            return cand
        # Bare sent ids like "grc_proiel-0421" name nothing biblical.
        m = re.search(r"([1-3]?\s?[A-Za-z]+)\s+(\d+)[\s:._\-]+(\d+)", cand)
        if m:
            rr = canon.parse_ref(f"{m.group(1)} {m.group(2)}:{m.group(3)}")
            if rr is not None:
                return f"{m.group(1)} {m.group(2)}:{m.group(3)}"
    return ""


def _sentences(text: str) -> Iterator[tuple[dict[str, str], list[list[str]]]]:
    meta: dict[str, str] = {}
    toks: list[list[str]] = []
    skipped = 0

    def flush():
        nonlocal meta, toks, skipped
        if toks or meta:
            yield meta, toks
        meta, toks = {}, []

    for raw in text.splitlines():
        ln = raw.rstrip("\n")
        if not ln.strip():
            yield from flush()
            continue
        if ln.startswith("#"):
            m = re.match(r"#\s*([\w\-]+)\s*=\s*(.*)", ln)
            if m:
                meta[m.group(1).strip()] = m.group(2).strip()
            continue
        cols = ln.split("\t")
        if len(cols) < 4:
            skipped += 1
            continue
        toks.append(cols)
    yield from flush()


def load_conllu_bytes(data: bytes, *, source: str = "") -> Iterator[UnitIn]:
    text = data.decode("utf-8-sig", "replace")
    n, unmapped, skipped = 0, 0, 0
    for meta, toks in _sentences(text):
        words: list[str] = []
        edges: list[dict] = []
        for cols in toks:
            tid = cols[0]
            form = cols[1] if len(cols) > 1 else ""
            if re.fullmatch(r"\d+-\d+", tid):
                continue  # multiword token line: the parts follow separately
            if re.fullmatch(r"\d+\.\d+", tid):
                continue  # empty node: no surface form to read or search
            if not form or form == "_":
                continue
            words.append(form)
            try:
                head = int((cols[6] if len(cols) > 6 else "0") or 0)
            except ValueError:
                head = 0
            edges.append({
                "id": tid,
                "form": form,
                "lemma": (cols[2] if len(cols) > 2 else "") or "",
                "upos": (cols[3] if len(cols) > 3 else "") or "",
                "xpos": (cols[4] if len(cols) > 4 else "") or "",
                "feats": (cols[5] if len(cols) > 5 else "") or "",
                "head": head,
                "deprel": (cols[7] if len(cols) > 7 else "") or "",
            })
        if not words:
            skipped += 1
            continue
        n += 1
        ref = _ref_from_meta(meta)
        key, book, ch, vs = f"syn-{n:05d}", "", 0, 0
        label = meta.get("sent_id", "") or f"sentence {n}"
        if ref:
            f = next(iter(canon.parse_ref(ref).refs()))
            key = f.osis_id()
            book, ch, vs = f.book, f.chapter or 0, f.verse or 0
            label = canon.format_ref(f)
        else:
            unmapped += 1
        surface = " ".join(words)
        yield UnitIn(
            key=key, label=label, title=label,
            segs=[Seg("text", surface)],
            book=book, chapter=ch, verse=vs,
            extra={"syntax": edges,
                   "sent_id": meta.get("sent_id", ""),
                   "treebank": source,
                   "word_count": len(words)})


def load_conllu(path: Path, *, source: str = "") -> Iterator[UnitIn]:
    yield from load_conllu_bytes(path.read_bytes(), source=source or path.stem)

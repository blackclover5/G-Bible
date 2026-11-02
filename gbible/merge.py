"""Version merging: several translations, read as one text.

Some platforms call this Version Merging, and it is not the same as Compare.  Compare
puts translations in columns and leaves the reader to spot the differences.
Merging produces a single text where wording every version agrees on appears
once, and every point of disagreement becomes a small cluster you can open to
see each version's reading.  The result reads like a critical text you can
study rather than a grid you have to decode.

The alignment is honest about what it is.  It is word-level and it is
best-effort: `difflib` on tokens, not a real apparatus criticus, and no claim
is made that any reading is original.  A merge is a reading aid, not an edition.
Where versions disagree about word *count* the extra words are kept rather than
dropped -- silently discarding a word is how a merge ends up quietly
misrepresenting a translation.

Translators bracket their additions ("the Lord God", "records of Jesus Christ")
with different punctuation in different versions, so agreement is reported as a
percentage of *word runs* rather than a claim of identity.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

from . import canon, db, library

# A word with any trailing punctuation kept, because that punctuation is often
# the only evidence of a translator's aside: "God, who is rich in mercy".
_TOKEN = re.compile(r"\S+")


def _norm(w: str) -> str:
    """Compare words loosely enough to catch real agreement, not just identity.

    Case and surrounding punctuation are noise; an apostrophe style is noise.
    Two spellings that differ only in those are the same word as far as a reader
    is concerned.  A different *stem* is not, and stays a disagreement.
    """
    w = unicodedata.normalize("NFKD", w.lower())
    w = "".join(c for c in w if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\u0370-\u03ff\u0590-\u05ff']+", "", w)


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text or "")


def _merge_verse(texts: list[str]) -> dict:
    """Align several renderings of one verse into runs.

    The first version is the spine.  Every other version is aligned against it
    once, giving a word-for-word map; consecutive spine positions where the
    versions disagree are then gathered into a single run.

    Runs, not individual words, are what a reader needs: "whoever believes"
    against "whosoever believeth" is one disagreement, and pairing the words off
    one at a time turns it into nonsense pairs that say nothing.

    Nothing is dropped.  Words only another version has are kept as that
    version's reading of the run, because quietly discarding a word is how a
    merge ends up misrepresenting a translation.
    """
    toks = [t.split() for t in texts]
    n = len(toks)
    if n == 0 or not any(toks):
        return {"segments": [], "agreement": None, "variants": 0, "words": 0}

    spine = toks[0] if toks[0] else next((t for t in toks if t), [])
    L = len(spine)

    # aligned[vi][i] = that version's word for spine position i ("" if it has none)
    # extra[vi][i]   = words that version has *in addition* at position i
    aligned: list[dict[int, str]] = []
    extra: list[dict[int, list[str]]] = []
    for vi in range(n):
        amap: dict[int, str] = {}
        xmap: dict[int, list[str]] = {}
        if not toks[vi]:
            for i in range(L):
                amap[i] = ""
            aligned.append(amap)
            extra.append(xmap)
            continue
        sm = difflib.SequenceMatcher(None, spine, toks[vi], autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "insert":
                # Words this version has that the spine does not.  They belong
                # at position i1, which is where the run will be cut.
                xmap.setdefault(i1, []).extend(toks[vi][j1:j2])
            elif tag == "equal":
                for k, i in enumerate(range(i1, i2)):
                    amap[i] = toks[vi][j1 + k]
            elif tag == "replace":
                # Pair the two sides position by position over the spine's
                # width, then keep any surplus new words as an extra.  The old
                # version walked a single index across both sides, which read
                # past the end of the replacement -- and, worse, pulled in words
                # from *after* this opcode's range.
                n_spine = i2 - i1
                n_new = j2 - j1
                for k in range(n_spine):
                    i = i1 + k
                    amap[i] = toks[vi][j1 + k] if k < n_new else ""
                if n_new > n_spine:
                    xmap.setdefault(i2, []).extend(toks[vi][j1 + n_spine:j2])
            elif tag == "delete":
                for i in range(i1, i2):
                    amap[i] = ""
        aligned.append(amap)
        extra.append(xmap)

    def reading_at(vi: int, i: int) -> str:
        words = []
        w = aligned[vi].get(i, "")
        if w:
            words.append(w)
        words.extend(extra[vi].get(i, []))
        return " ".join(words)

    # The last spine index each version actually has a word for.  A version
    # with nothing at index i and nothing after it has simply ended; a version
    # with nothing at i but words later has *skipped* one, which is a
    # disagreement the old test could not see.
    last_at = []
    for vi in range(n):
        last_at.append(max((i for i, w in aligned[vi].items() if w), default=-1))

    def differs(i: int) -> bool:
        seen = set()
        for vi in range(n):
            if not reading_at(vi, i) and i < last_at[vi]:
                # A dropped word mid-sentence.  Reading "only Son" against the
                # spine's "only begotten Son" is a difference, and it used to be
                # scored as agreement -- the version was simply skipped over at
                # that index, so the other readings all matched and the segment
                # came out "same" while quietly listing a reading that omits a
                # word.
                return True
            w = reading_at(vi, i)
            if not w:
                continue
            key = _norm(w)
            if key in seen:
                continue
            if len(seen) > 0 and not _same_shape(key, seen):
                return True
            seen.add(key)
        # A version that has extra words the spine lacks is itself a difference.
        return len(seen) > 1

    segments: list[dict] = []
    variants = 0
    words = 0
    i = 0
    while i < L:
        kind = "variant" if differs(i) else "same"
        j = i
        while j < L:
            jkind = "variant" if differs(j) else "same"
            if jkind != kind:
                break
            j += 1
        run = list(range(i, j))
        spine_txt = " ".join(spine[k] for k in run)
        # Attach any extra words that fell at the end of the run.
        readings = []
        for vi in range(n):
            txt = " ".join(x for x in (reading_at(vi, k) for k in run) if x)
            if txt:
                readings.append({"v": vi, "w": txt})
        if not readings:
            readings = [{"v": 0, "w": spine_txt}]
        words += len(spine_txt.split())
        if kind == "variant":
            variants += 1
        segments.append({"t": kind, "w": spine_txt, "readings": readings})
        i = j

    agreement = round(100.0 * (words - variants) / words, 1) if words else None
    return {"segments": segments, "agreement": agreement,
            "variants": variants, "words": words}


def _same_shape(a: str, seen: set) -> bool:
    """Is `a` the same word as everything in `seen`?

    Compare against the first entry only.  A chain like "God"/"god"/"God's"
    normalises to god/god/gods, and holding each against the *whole* set makes
    the third word look like a disagreement with both.
    """
    first = next(iter(seen))
    return a == first or a.startswith(first) or first.startswith(a)


def _plain(seg: dict) -> str:
    """The merged text, using the first version's wording as the spine."""
    return seg["w"]


def diff(ref: str, module_ids: list[str]) -> dict:
    """The same verse in several translations, with the disagreements marked.

    Each version comes back as a list of runs, `{"w": text, "t": "same" |
    "variant"}`, so a reader can see *where* the versions part company rather
    than being handed two blocks of text and left to find the difference.

    This is the alignment `merge` already computes, reported per version instead
    of gathered into one merged text.  It is deliberately not a new algorithm:
    two implementations of "what differs here" would be two answers, and the
    merge view and the diff view disagreeing would be worse than either being
    approximate.  A dropped word counts as a difference, for the same reason it
    does in the merge -- a version that omits a word the others have has not
    agreed with them.

    Agreement is reported per verse and is a property of the versions *chosen*,
    which is why it is returned with them rather than fixed.
    """
    rr = canon.parse_ref(ref)
    if rr is None:
        return {"ok": False, "error": f"cannot read {ref!r} as a reference"}
    if len(module_ids) < 2:
        return {"ok": False, "error": "a diff needs two or more translations"}

    conn = db.connect()
    versions = []
    texts = []
    for mid in module_ids:
        m = library.get(mid)
        if m is None or m.type not in library.VERSE_TEXT_TYPES \
                or not m.installed_at:
            continue
        row = conn.execute(
            "SELECT text FROM unit WHERE module_id=? AND book=? AND chapter=? "
            "AND verse=? LIMIT 1",
            (mid, rr.start.book, rr.start.chapter, rr.start.verse)).fetchone()
        if row is None or not (row["text"] or "").strip():
            continue
        versions.append({"module_id": mid, "name": m.name,
                         "abbrev": m.abbrev or "", "version": m.version or "",
                         "lang": m.lang})
        texts.append(row["text"])
    if len(versions) < 2:
        return {"ok": False, "error":
                "need two or more installed translations with text for that verse"}

    merged = _merge_verse(texts)
    columns = []
    for vi, v in enumerate(versions):
        runs = []
        for seg in merged["segments"]:
            # Each version's own reading of the run, or the spine's if it has
            # none there -- an empty reading would render as a gap the reader
            # cannot tell from the version having said nothing.
            txt = ""
            for r in seg["readings"]:
                if r["v"] == vi:
                    txt = r["w"]
                    break
            if not txt and seg["t"] == "variant":
                txt = ""
            if txt:
                runs.append({"w": txt, "t": seg["t"]})
        columns.append({**v, "runs": runs,
                        "text": " ".join(r["w"] for r in runs)})
    return {"ok": True, "ref": rr.label(), "columns": columns,
            "agreement": merged["agreement"], "variants": merged["variants"],
            "words": merged["words"]}


def merge(ref: str, module_ids: list[str], *, spine: int = 0) -> dict:
    """Merge a passage across translations, verse by verse.

    Verses where the versions do not all have text are reported rather than
    padded -- a verse missing from one translation is a fact about that
    translation, and hiding it makes the agreement figure a lie.
    """
    rr = canon.parse_ref(ref)
    if rr is None:
        return {"ok": False, "error": f"cannot read {ref!r} as a reference"}
    verses = list(rr.refs())
    if not verses:
        return {"ok": False, "error": "no verse in that reference"}
    if not module_ids:
        return {"ok": False, "error": "choose at least one translation"}
    if len(module_ids) < 2:
        return {"ok": False, "error":
                "merging needs two or more translations to compare"}

    conn = db.connect()
    versions = []
    for mid in module_ids:
        m = library.get(mid)
        # library.get() answers for uninstalled modules too -- it has to, since
        # removal looks a module up.  Without this check a removed Bible still
        # appeared as a column in a merge, with nothing behind it.
        if m is None or m.type not in library.VERSE_TEXT_TYPES \
                or not m.installed_at:
            continue
        versions.append({"module_id": mid, "name": m.name, "abbrev": m.abbrev or "",
                         "version": m.version or "", "lang": m.lang})
    if len(versions) < 2:
        return {"ok": False, "error":
                "need two or more installed translations, not one resource"}
    if spine >= len(versions):
        spine = 0

    out_verses = []
    agree_sum = 0.0
    agree_n = 0
    for vref in verses:
        texts = []
        for ver in versions:
            r = conn.execute(
                "SELECT text FROM unit WHERE module_id=? AND book=? AND chapter=? "
                "AND verse=? LIMIT 1",
                (ver["module_id"], vref.book, vref.chapter, vref.verse)).fetchone()
            texts.append(r["text"].strip() if r and (r["text"] or "").strip() else "")
        if not any(texts):
            continue
        mg = _merge_verse(texts)
        # A missing verse is a coverage gap, not agreement with the text that
        # is present. Keep the available wording, but do not score a comparison
        # unless at least two versions actually supplied this verse.
        if sum(bool(t) for t in texts) < 2:
            mg["agreement"] = None
        if mg["agreement"] is not None:
            agree_sum += mg["agreement"]
            agree_n += 1
        label = vref.label
        out_verses.append({
            "verse": vref.verse, "key": label, "label": label,
            "segments": mg["segments"],
            "text": " ".join(_plain(s) for s in mg["segments"]),
            "agreement": mg["agreement"], "variants": mg["variants"],
            "words": mg["words"],
            "missing": [versions[i]["abbrev"] or versions[i]["name"]
                        for i, t in enumerate(texts) if not t],
        })

    if not out_verses:
        return {"ok": False, "error": f"none of those translations have {ref}"}

    # A single verse is a comparison, not a merge worth opening a pane for.
    note = ""
    if len(out_verses) == 1:
        note = ("One verse only, so this is a direct comparison rather than a "
                "merged passage. Open a range to see merging across verses.")
    first, last = verses[0], verses[-1]
    if len(verses) == 1:
        ref_label = first.label
    elif (first.book, first.chapter) == (last.book, last.chapter):
        # "John 3:1\u20134", not "John 3:1\u2013John 3:4": repeating the book and
        # chapter in a pane title is just noise.
        ref_label = f"{first.book} {first.chapter}:{first.verse}\u2013{last.verse}"
    else:
        ref_label = f"{first.label}\u2013{last.label}"
    return {
        "ok": True,
        "ref": ref_label,
        "versions": versions, "spine": spine,
        "verses": out_verses,
        "agreement": round(agree_sum / agree_n, 1) if agree_n else None,
        "variants": sum(v["variants"] for v in out_verses),
        "notes": [note] if note else [],
        "caveat": ("Word-level alignment by difflib, not a critical apparatus. "
                   "Agreement is a figure of speech about these translations, "
                   "not a judgement about any reading's originality."),
    }

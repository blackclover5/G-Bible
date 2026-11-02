"""Audio: play a recording you already have, legally.

**This does not download anything.**  That is a deliberate line.  A recording of
the Bible carries its own licence, separate from the text's, and the honest
thing for software to do is make the audio work and make the licence visible --
not to go looking for media, decide that a particular recording is free, and
re-bundle it.  So:

* You point this at a folder of files you have obtained yourself.
* You state the licence when you register the folder, and it is recorded per
  module and shown in the Library and the Store, because a recording whose terms
  you cannot name is one you should not be playing.
* Nothing is copied, moved, or re-encoded.  The files are served where they
  are.

The usual sources for this are recordings released into the public domain or
under CC0 / CC-BY, or read-aloud recordings made by the person who owns the
rights.  Anything you downloaded from a subscription service generally is not
yours to redistribute, and this will not pretend otherwise.

File names are read for a reference, so the recording can follow the Bible pane.
`Gen 01.mp3`, `Gen_01_KJV.mp3`, `John.3.16.mp3` and `01 - John 3 - The Word
became flesh.mp3` all resolve, because the reference is looked for rather than
demanded.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import time
from pathlib import Path

from . import canon, db, taxonomy

#: For a recording the user made themselves.  Not a public licence, and never
#: presented as one: the Library shows it as personal, and the Attribution view
#: keeps it apart from material that may be redistributed.
PERSONAL_LABEL = "Personal — not for redistribution"
PERSONAL_FORMS = {PERSONAL_LABEL.lower(), "personal", "private", "mine",
                  "my own recording", "own work", "personal use only"}

AUDIO_EXT = {".mp3", ".ogg", ".oga", ".m4a", ".wav", ".flac", ".opus", ".aac",
              ".webm"}

#: Cue files that say when each verse is spoken.  A recording carries no verse
#: boundary of its own -- the times live outside the audio, in a subtitle file or
#: a sidecar -- so this is the only honest source of them.
#:
#: The alternative, detecting silence in the waveform, needs an audio decoder,
#: and this application ships without dependencies by design.  Inventing timings
#: from a bitrate would be worse than having none: the verse highlight would
#: advance confidently and be wrong.
CUE_EXT = {".vtt": "vtt", ".srt": "srt", ".json": "json", ".cues": "json"}


def _ts(v: str) -> float | None:
    """Seconds from `HH:MM:SS.mmm`, `MM:SS.mmm`, or `SS.mmm`."""
    if not v:
        return None
    v = v.strip().replace(",", ".")
    if "-->" in v:
        v = v.split("-->")[0].strip()
    parts = v.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    sec = 0.0
    for n in nums:
        sec = sec * 60.0 + n
    return sec


_TS_RANGE = re.compile(
    r"(\d[\d:.,]*)\s*-->\s*(\d[\d:.,]*)")


def parse_cues(path: str) -> dict:
    """Verse -> (start seconds, end seconds), from a cue file.

    Reads three shapes, because three are what exist in the wild:

    * **WebVTT** and **SRT** -- timed blocks whose *text* is the verse.  The
      reference is read out of that text with the same parser used for file
      names, so `John 3:16` in a subtitle opens John 3:16, and a verse quoted
      with no reference at all is skipped rather than guessed at.
    * **JSON** -- `{"John.3.16": [start, end]}`, or a list of
      `{"ref": ..., "start": ..., "end": ...}`.  Written by hand for a recording
      someone timed themselves.

    A cue whose text is a verse of scripture but carries no reference is ignored,
    and the count is reported, because the alternative -- attaching it to whatever
    verse was played last -- would put the highlight somewhere plausible and
    wrong.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError:
        return {"cues": {}, "skipped": 0, "format": "", "note": "unreadable"}
    ext = os.path.splitext(path)[1].lower()
    kind = CUE_EXT.get(ext, "vtt")
    cues: dict[str, list[float]] = {}
    skipped = 0

    if kind == "json":
        try:
            data = json.loads(raw)
        except ValueError:
            return {"cues": {}, "skipped": 0, "format": "json",
                    "note": "not valid JSON"}
        if isinstance(data, dict):
            data = data.get("cues") or data.get("verses") or data
        if isinstance(data, dict):
            items = [{"ref": k, "start": v[0], "end": v[1]}
                     for k, v in data.items()
                     if isinstance(v, (list, tuple)) and len(v) >= 2]
        else:
            items = [d for d in (data or []) if isinstance(d, dict)]
        for d in items:
            ref = _cue_ref(str(d.get("ref") or d.get("label") or ""))
            start, end = d.get("start"), d.get("end")
            s = _ts(str(start)) if start is not None else None
            e = _ts(str(end)) if end is not None else None
            if not ref or s is None:
                skipped += 1
                continue
            cues[ref] = [s, e if e is not None else s]
        return {"cues": cues, "skipped": skipped, "format": "json", "note": ""}

    # WebVTT and SRT are the same shape: a timing line, then the text.
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n").replace("\r", "\n"))
    for block in blocks:
        m = _TS_RANGE.search(block)
        if not m:
            continue
        start, end = _ts(m.group(1)), _ts(m.group(2))
        if start is None:
            continue
        text = " ".join(ln.strip() for ln in block[m.end():].splitlines()
                        if ln.strip())
        text = re.sub(r"<[^>]+>", "", text).strip()
        if not text:
            continue
        ref = _cue_ref(text)
        if not ref:
            skipped += 1
            continue
        cues[ref] = [start, end if end is not None else start]
    return {"cues": cues, "skipped": skipped, "format": kind, "note": ""}


def _cue_ref(text: str) -> str:
    """The OSIS id a cue's text names, or "".

    **Not** `_guess_ref`.  That one deliberately normalises a *file name* to
    book and chapter, because "Gen 1.mp3" is a chapter and reading it as verse 1
    would be an accident rather than an answer.  A cue's text is the opposite
    case: `John 3:16` means verse 16, and `_guess_ref` returned `John 3` for it.
    Every cue in a chapter therefore collided on one key, so a recording of
    John 3 came out with a single entry at John 3:1 and the rest of the timings
    discarded -- a wrong answer, and an invisible one, because the file had read
    cleanly and the panel simply had nothing to show.

    So the reference is parsed as written, and the verse is kept.
    """
    text = (text or "").strip()
    if not text or not re.search(r"[A-Za-z]", text):
        return ""
    try:
        rr = canon.parse_ref(text)
    except Exception:
        return ""
    f = next(iter(rr.refs()), None) if rr else None
    if f is None or not f.book:
        return ""
    return f.osis_id()


def _cue_ref_label(key: str) -> str:
    """A human label for a cue key, for the note text."""
    parts = str(key or "").split(".")
    if len(parts) >= 3:
        return f"{parts[0]} {parts[1]}:{parts[2]}"
    return ".".join(parts)


def find_cues(folder: str) -> list[str]:
    """Cue files sitting beside the audio, if any."""
    folder = _confine(folder) or folder
    out = []
    for root, _dirs, files in os.walk(folder):
        for fn in sorted(files):
            if os.path.splitext(fn)[1].lower() in CUE_EXT:
                out.append(os.path.join(root, fn))
    return out

def _guess_ref(name: str) -> str:
    """Best reference from a file name, or '' when there is not one.

    Every candidate is checked with canon.parse_ref rather than against a list
    of abbreviations written here: parse_ref already knows that "Gen", "Psa" and
    "1Cor" are books, and guessing at that list is how "concerning" and
    "killing" ended up as people in the genealogy.  A recording of a whole book
    is still worth having, so a book on its own counts.
    """
    stem = os.path.splitext(os.path.basename(name))[0]
    # A leading track number, but never the "1" of "1Cor": the digits must be
    # followed by a separator, or they are part of the book's name.  Stripping
    # them anyway turned "1Cor 13.4" into "Cor 13.4", which is not a book.
    stem = re.sub(r"^\s*\d{1,3}(?=[^A-Za-z0-9])[-_.)\]\s]*", "", stem)
    stem = re.sub(r"\s*\(\s*(?:cc0|public domain|cc[- ]?by[^)]*)\s*\)\s*$", "",
                  stem, flags=re.I)
    # "1Cor 13.4-8.13" names a range; the recording starts at 13:4, so take the
    # head.  Only a tail that *starts with a digit* is a range -- in
    # "01 - John 3 - The Word became flesh" the tail is a title, and cutting it
    # would throw away the only reference in the name.
    stem = re.sub(r"\s*[-–]\s*\d[\d:.]*\s*$", "", stem)
    stem = re.sub(r"[\s\-_]+$", "", stem)
    toks = [t for t in re.split(r"[\s\-_]+", stem) if t]
    # Try the longest plausible runs first: a whole-book file should win over a
    # stray number inside its title.
    for width in (4, 3, 2, 1):
        for i in range(len(toks) - width + 1):
            run = toks[i:i + width]
            if not any(re.search(r"[A-Za-z]", t) for t in run):
                continue
            joined = " ".join(run)
            for form in (joined.replace(".", ":").replace(":", ": "),
                         joined.replace(".", " "),
                         joined.replace(":", " "),
                         joined):
                rr = _try_ref(form)
                if rr:
                    return rr
    return ""


def _try_ref(form: str) -> str:
    form = (form or "").strip()
    if not form or not re.search(r"[A-Za-z]", form):
        return ""
    rr = canon.parse_ref(form)
    if rr is None:
        return ""
    first = next(iter(rr.refs()), None)
    if first is None or not first.book:
        return ""
    out = f"{first.book} {first.chapter or 1}"
    # "Gen 01" is a chapter file, not verse one.  parse_ref hands back verse 1
    # for a bare book-and-number, and appending it would put every chapter in the
    # list down as "Gen 1:1" and send follow-along to verse one.
    explicit_verse = bool(re.search(r"[.:]\s*\d", form))
    if first.verse and explicit_verse:
        out += f":{first.verse}"
    return out


#: Where audio may be read from.  The API takes a folder from the request, and
#: walking an arbitrary tree is how "list everything under /home/you" turns into
#: a feature.  The user's own home directory is the whole legitimate use case.
def _confine(folder: str) -> str:
    """Resolve a folder, and refuse anything outside the user's home.

    Symlinks are resolved before the check, so a link pointing out of the home
    directory does not become a way around it.
    """
    p = Path(os.path.abspath(os.path.expanduser(folder or "")))
    try:
        real = p.resolve()
    except OSError:
        return ""
    home = Path.home().resolve()
    try:
        real.relative_to(home)
    except ValueError:
        return ""
    return str(real)


def scan(folder: str) -> list[dict]:
    """Audio files under a folder, with a best-guess reference for each."""
    folder = _confine(folder)
    if not folder:
        return []
    out = []
    for root, _dirs, files in os.walk(folder):
        for fn in sorted(files):
            if os.path.splitext(fn)[1].lower() not in AUDIO_EXT:
                continue
            full = os.path.join(root, fn)
            out.append({
                "file": full,
                "name": fn,
                "ref": _guess_ref(fn),
                "bytes": os.path.getsize(full) if os.path.exists(full) else 0,
            })
    # Book order first, then track order, so the chapter list reads in order.
    def key(o):
        rr = canon.parse_ref(o["ref"]) if o["ref"] else None
        f = next(iter(rr.refs()), None) if rr else None
        ordinal = canon.BOOK_BY_NAME.get(f.book).ordinal if (f and f.book
                                                            and canon.BOOK_BY_NAME.get(f.book)) else 999
        return (ordinal, f.chapter if f else 0, f.verse if f else 0, o["name"])
    out.sort(key=key)
    return out


def register(folder: str, name: str = "", license_: str = "",
             author: str = "") -> dict:
    """Register a folder as a playable module.

    The licence is required.  Not as a nag: a recording whose terms are unknown
    cannot be shown to be usable, and refusing to index it silently is how a
    library quietly acquires material it has no right to.
    """
    raw = folder
    folder = _confine(folder)
    if not folder:
        return {"ok": False, "error":
                "choose a folder inside your home directory. Anything outside it "
                "is refused: this reads file names off your disk, and it is not "
                "something to point at a system directory."}
    if not os.path.isdir(folder):
        return {"ok": False, "error": f"not a folder: {raw!r}"}
    if not license_.strip():
        return {"ok": False, "error":
                "state the licence for this recording (for example "
                "Public Domain, CC0, or CC-BY-4.0)"}
    # Put the declared licence through the same gate the Store uses.  Without
    # this, anything could be typed in -- "all rights reserved" included -- and
    # the Attribution view would then list it alongside genuinely free
    # material as though the app had checked it.
    ok, why = taxonomy.redistributable({"id": "", "license": license_.strip()})
    if not ok:
        if license_.strip().strip().lower() in PERSONAL_FORMS:
            # Legitimate and common: a recording of the user's own voice has no
            # public licence at all.  It is registered, but recorded as personal
            # so nothing here ever describes it as redistributable.
            pass
        else:
            return {"ok": False, "error":
                    f"“{license_.strip()}” is not freely redistributable: {why} "
                    f"If this is your own recording, say "
                    f"“{PERSONAL_LABEL}” instead and it will be recorded as "
                    f"personal, not for sharing."}
    files = scan(folder)
    if not files:
        return {"ok": False, "error": f"no audio files in {folder}"}

    name = (name or "").strip() or os.path.basename(folder.rstrip("/")) or "Audio"
    personal = license_.strip().lower() in PERSONAL_FORMS
    stored_lic = PERSONAL_LABEL if personal else taxonomy.normalise_license(license_)
    mid = "local-audio-" + re.sub(r"[^a-z0-9]+", "-",
                                  name.lower()).strip("-")[:24]
    conn = db.connect()
    now = time.time()
    conn.execute(
        "INSERT OR REPLACE INTO module(id,name,abbrev,type,subject,lang,"
        "license,rights,author,description,format,folder,path,installed_at,"
        "size_bytes,entries,has_notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
        (mid, name, name[:4], "Audio", "Audio", "eng", stored_lic,
         stored_lic, author, f"Audio files in {folder}", "audio",
         "local", folder, now, sum(f["bytes"] for f in files), len(files)))
    conn.execute("DELETE FROM unit WHERE module_id=?", (mid,))
    # The unit rows just written are part of the vocabulary the search box's
    # spelling hint is built from, and this path writes its module row directly
    # rather than through library.register, so it has to announce the change
    # itself or the hint goes on offering a word this scan just removed.
    db.bump_generation()
    _CUE_CACHE.pop(mid, None)
    with_ref = 0
    for i, f in enumerate(files):
        ref = f["ref"] or ""
        book = chapter = verse = ""
        if ref:
            with_ref += 1
            rr = canon.parse_ref(ref)
            first = next(iter(rr.refs()), None) if rr else None
            if first:
                book = first.book or ""
                chapter = first.chapter or 0
                verse = first.verse or 0
        conn.execute(
            "INSERT OR REPLACE INTO unit(module_id,key,ord,ref_label,book,"
            "chapter,verse,text,extra) VALUES(?,?,?,?,?,?,?,?,?)",
            (mid, ref or f["name"], i, ref or f["name"], book, chapter, verse,
             "", json.dumps({"file": f["file"], "bytes": f["bytes"]})))
    conn.commit()
    # Cues, if the recording came with any.  Found after the units are written,
    # because the cue reader needs the same reference parser and it is cheaper
    # to do it once at the end than per file.
    cue_files = find_cues(folder)
    all_cues: dict[str, list[float]] = {}
    cue_skipped = 0
    cue_format = ""
    for cf in cue_files:
        got = parse_cues(cf)
        all_cues.update(got["cues"])
        cue_skipped += got["skipped"]
        cue_format = cue_format or got["format"]
    note = ("The files are played where they are; nothing was copied "
            "or re-encoded.")
    if all_cues:
        conn.execute("UPDATE module SET description=? WHERE id=?",
                     (f"Audio files in {folder}; {len(all_cues)} verses cued",
                      mid))
        conn.commit()
        note += (f" {len(all_cues)} verse timings were found in "
                 f"{os.path.basename(cue_files[0])}, so the text can follow "
                 f"the recording.")
        if cue_skipped:
            note += (f" {cue_skipped} cue(s) named no verse and were left out "
                     f"rather than attached to the wrong one.")
    elif cue_files:
        note += (" A cue file was present but yielded no verse timings, so the "
                 "text will not follow the recording.")
    return {"ok": True, "id": mid, "name": name, "files": len(files),
            "with_reference": with_ref, "license": stored_lic,
            "personal": personal,
            "folder": folder,
            "cues": len(all_cues),
            "cue_files": [os.path.basename(c) for c in cue_files],
            "cue_skipped": cue_skipped,
            "note": note}


def files_dir(module_id: str, m=None) -> str:
    """Where an audio module's files are, resolved rather than merely recorded.

    An audio folder is usually *outside* the library: `folder` holds the literal
    string "local" as an origin marker and `path` names wherever the reader
    pointed at the time.  So this is mostly the recorded path, and it has to
    keep working as the fallback -- but going through `library.module_dir`
    first means a recording that does live in the library resolves through the
    library's own `modules` directory and so survives the folder being moved,
    which is the same guarantee the rest of the library now has.

    Never raises: an unreadable module row must not stop a recording playing.
    """
    from . import library
    try:
        d = library.module_dir(module_id)
    except Exception:                                   # noqa: BLE001
        d = None
    if d:
        return str(d)
    if m is None:
        try:
            m = library.get(module_id)
        except Exception:                               # noqa: BLE001
            m = None
    return (getattr(m, "path", "") or "") or (getattr(m, "folder", "") or "")


def remove(module_id: str) -> dict:
    """Stop offering a local recording.  The files themselves are left alone."""
    conn = db.connect()
    # `folder` holds the origin marker "local"; the directory the files are in
    # is `path`.  Reading `folder` here reported the literal string "local" as
    # the folder that had been left alone, which is a sentence about nothing.
    row = conn.execute("SELECT path, folder FROM module WHERE id=?",
                       (module_id,)).fetchone()
    panes = conn.execute("SELECT COUNT(*) FROM pane WHERE module_id=?",
                         (module_id,)).fetchone()[0]
    conn.execute("DELETE FROM unit WHERE module_id=?", (module_id,))
    # Close panes first.  A layout row pointing at a module that no longer
    # exists renders as an empty tile with the module's name still on its tab,
    # and the user is left with a pane they cannot explain.
    conn.execute("DELETE FROM pane WHERE module_id=?", (module_id,))
    conn.execute("DELETE FROM module WHERE id=?", (module_id,))
    conn.execute("DELETE FROM store_item WHERE module_id=?", (module_id,))
    conn.commit()
    db.bump_generation()
    _CUE_CACHE.pop(module_id, None)
    return {"ok": True, "removed": module_id, "panes_closed": panes,
            "folder_left_alone": ((row["path"] or row["folder"]) if row else "")}


def read(module_id: str, cursor: dict | None = None) -> dict:
    """The chapter list, in canonical order, with the audio file for each."""
    from . import library
    from .library import Content, Item
    m = library.get(module_id)
    if m is None:
        raise KeyError(module_id)
    conn = db.connect()
    items: list = []
    for r in conn.execute("SELECT key, ref_label, book, chapter, verse, extra"
                          " FROM unit WHERE module_id=? ORDER BY ord",
                          (module_id,)):
        try:
            ex = json.loads(r["extra"] or "{}")
        except (json.JSONDecodeError, TypeError):
            ex = {}
        path = ex.get("file", "")
        it = Item(key=r["key"], label=r["ref_label"] or r["key"],
                  title=os.path.basename(path), text="", html="")
        it.extra = {
            "file": path,
            "bytes": ex.get("bytes", 0),
            "mime": mimetypes.guess_type(path)[0] or "audio/mpeg",
            "book": r["book"] or "", "chapter": r["chapter"] or 0,
            "verse": r["verse"] or 0,
            "name": os.path.basename(path),
        }
        items.append(it)
    c = Content(module_id, m.name, "audio", cursor=cursor or {}, items=items)
    cues, cue_note = load_cues(module_id, m.folder or "")
    c.extra = {"license": m.license or "",
               "folder": files_dir(module_id, m),
               "cues": cues,
               "cue_note": cue_note,
               "note": "Played from where the files already are."}
    return c


_CUE_CACHE: dict = {}


def load_cues(module_id: str, folder: str = "") -> tuple[dict, str]:
    """The verse timings for a recording, and a sentence about them.

    Returns a dict of OSIS verse id to `[start, end]`, sorted by start time.

    **One file per verse needs no cue file at all** and is reported as synced on
    its own terms: the file's reference *is* the boundary, so playing it plays
    that verse.  That is the case for most free recordings -- one file per verse
    or per chapter, named for the passage -- and it means the feature works
    without the reader having to time anything.

    Otherwise the answer is whatever a cue file beside the audio says, and where
    there is none the sentence returned says so plainly, because "the text does
    not follow the recording" is a fact about the material and not a fault in the
    player.
    """
    m = module_id in _CUE_CACHE
    if m:
        return _CUE_CACHE[module_id]
    from . import library
    mod = library.get(module_id)
    # `folder` on a local audio module holds the literal string "local" -- the
    # origin marker -- and the directory the files are actually in is `path`.
    # Reading `folder` here found a non-existent directory, found no cue file,
    # and reported the recording as having no timings at all.
    folder = folder or files_dir(module_id, mod)
    files = [f for f in find_cues(folder)] if folder else []
    if not files:
        per_verse = _per_verse_sync(module_id)
        if per_verse:
            _CUE_CACHE[module_id] = (per_verse,
                "Each file is one verse, so the text follows the recording "
                "without any timings being needed.")
        else:
            _CUE_CACHE[module_id] = ({}, (
                "This recording has no verse timings, so the text will not "
                "follow it: a recording carries no verse boundary of its own, "
                "and inventing one from the waveform would need an audio "
                "decoder. Put a .vtt, .srt or .json cue file beside the audio "
                "and re-register the folder."))
        return _CUE_CACHE[module_id]
    cues: dict[str, list[float]] = {}
    skipped = 0
    for cf in files:
        got = parse_cues(cf)
        for k, pair in got["cues"].items():
            cues[k] = list(pair)
        skipped += got["skipped"]
    ordered = {k: cues[k] for k in sorted(cues, key=lambda x: cues[x][0])}
    note = (f"{len(ordered)} verse timings from "
            f"{os.path.basename(files[0])}, so the text follows the recording.")
    if skipped:
        note += (f" {skipped} cue(s) named no verse and were left out rather "
                 f"than attached to the wrong one.")
    _CUE_CACHE[module_id] = (ordered, note)
    return _CUE_CACHE[module_id]


def _per_verse_sync(module_id: str) -> dict:
    """Cues implied by having one file per verse.

    Each file becomes a zero-length cue at its own reference, and the player
    treats "the file being played" as the verse -- so nothing needs timing and
    nothing needs pretending.

    **The file must actually name a verse.**  `canon.parse_ref("John 3")`
    answers with `John 3:1`, because a chapter reference has a first verse, so
    asking whether `verse > 0` says yes for a file that names a whole chapter.
    A recording kept as one file per *chapter* was therefore reported as synced,
    with a single zero-length cue at verse 1 of each chapter -- the highlight
    would advance to the chapter and then stop, and nothing would say why.

    So this tests the reference as written: a verse is named when the key ends in
    two numbers.  A recording kept per chapter gets no cues from this path and
    says so, which is the truth about it.
    """
    conn = db.connect()
    rows = conn.execute(
        "SELECT key, book, chapter, verse FROM unit WHERE module_id=? "
        "AND book<>'' ORDER BY ord", (module_id,)).fetchall()
    if not rows:
        return {}
    named_verse = re.compile(r"\d+\s*[:.]\s*\d+\s*$")
    if not all(named_verse.search((r["key"] or "").strip()) for r in rows):
        return {}
    out: dict[str, list[float]] = {}
    t = 0.0
    for r in rows:
        try:
            f = canon.Ref(r["book"], r["chapter"], r["verse"])
        except Exception:
            return {}
        if not f.verse:
            return {}
        out[f.osis_id()] = [t, t]
        t += 1.0
    return out


def cues_for(module_id: str, ref: str = "") -> dict:
    """The timings for one reference, or all of them.

    Given a reference, returns the times for every verse of it, which is what the
    player needs to advance a highlight inside a chapter recording.
    """
    cues, note = load_cues(module_id)
    if not ref:
        return {"ok": True, "cues": cues, "note": note}
    rr = canon.parse_ref(ref)
    if rr is None:
        return {"ok": False, "error": f"cannot read {ref!r} as a reference"}
    inside = {}
    for v in rr.refs():
        k = v.osis_id()
        if k in cues:
            inside[k] = cues[k]
    return {"ok": True, "cues": inside, "all": len(cues), "note": note,
            "matched": len(inside)}

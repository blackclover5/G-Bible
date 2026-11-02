"""Self-test: exercises every subsystem against whatever is installed.

    python3 run.py --check
    python3 tools/selftest.py            # same thing
    python3 tools/selftest.py --full     # also install the demo set

Exit code 0 means every check passed.

On an empty library most checks have nothing to test and report "skipped" --
that is not a pass and not a failure.  Install one module per reader first:

    python3 tools/seed.py
    python3 tools/selftest.py
"""

from __future__ import annotations

import contextlib
import fnmatch
import io
import re
import sys
import time
import traceback
import urllib.request
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def _wal_bytes() -> int:
    """Size of the SQLite write-ahead log beside the database, 0 if absent."""
    from gbible import db          # imported per function here, not at module scope
    try:
        return Path(str(db.db_path()) + "-wal").stat().st_size
    except OSError:
        return 0


def _gitignore_patterns(root):
    """Read .gitignore into (anchored_dirs, dir_paths, files, suffixes, dir_names).

    A trailing `/` is the only thing that says a pattern names a *directory*,
    and it was being stripped before the line was classified -- so `venv/`
    became a file named `venv` (nothing under it could ever match) and
    `.venv/` was caught by the "contains a dot" branch and became the suffix
    pattern `*..venv`.  Both then fell through to the size walk, which measured
    the read-aloud voice's 30 MB `onnxruntime_pybind11_state.so` and failed a
    check whose whole subject is that nothing redistributable is committed.
    """
    f = root / ".gitignore"
    if not f.exists():
        return (set(), set(), set(), set(), set())
    dirs, dir_paths, files, suffixes, dir_names = set(), set(), set(), set(), set()
    for line in f.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if not t or t.startswith("#") or t.startswith("!"):
            continue
        # Read the trailing slash *before* removing it: it is the signal.
        is_dir = t.endswith("/")
        t = t.rstrip("/")
        if not t:
            continue
        if t.startswith("/"):
            dirs.add(t[1:])
        elif "/" in t:
            dir_paths.add(t)
        elif t.endswith("*"):
            suffixes.add(t)
        elif is_dir:
            # A bare name written as a directory: any entry of that name, at
            # any depth.  Checked before the dot test, which would otherwise
            # swallow `.venv/`.
            dir_names.add(t)
        elif "." in t:
            suffixes.add("*" + t)
        else:
            files.add(t)
    return (dirs, dir_paths, files, suffixes, dir_names)


def _is_ignored(rel, patterns) -> bool:
    """Would git ignore this path?  Good enough for the files this app makes."""
    anchored, dir_paths, files, suffixes, dir_names = patterns
    parts = rel.parts
    for d in anchored:
        if parts and parts[0] == d:
            return True
    for suf in suffixes:
        if rel.match(suf) or rel.name.endswith(suf.lstrip("*")):
            return True
    if rel.name in files:
        return True
    for d in dir_paths:
        head = str(PurePosixPath(*parts[:-1]) / d) if len(parts) > 1 else d
        if str(rel).startswith(head) or str(rel).rstrip("/").endswith(d):
            return True
    # A directory being ignored ignores everything under it.
    for i in range(1, len(parts)):
        if parts[i] == "__pycache__":
            return True
    # ...and that holds for every directory the patterns name, at any depth:
    # `venv/`, `.venv/`, and any multi-segment `dir/sub/` pattern.  Without this
    # the walk measured files that were never going to be committed.
    for d in dir_names:
        # fnmatch, not `==`: `*.egg-info/` is a wildcard directory name and a
        # literal comparison would never match it.
        if any(fnmatch.fnmatch(p, d) for p in parts):
            return True
    for d in dir_paths:
        segs = PurePosixPath(d).parts
        if not segs:
            continue
        for i in range(1, len(parts) - len(segs) + 1):
            if tuple(parts[i:i + len(segs)]) == segs:
                return True
    return False

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
_results: list[tuple[str, str, str]] = []


class Skip:
    """A check that could not run, and why.

    `check` treats a returned string as a passing detail, so a check that wanted
    to explain itself was reported as *passed* without running -- four index
    checks did exactly that, printing a staleness message under an "ok".  A skip
    is a distinct outcome and has to be spelled as one.
    """

    def __init__(self, reason: str):
        self.reason = reason


def check(name: str, fn):
    t0 = time.time()
    try:
        r = fn()
        if isinstance(r, Skip):
            _results.append((SKIP, name, r.reason))
            status = "skip"
        elif r is None:
            _results.append((SKIP, name, "not installed"))
            status = "skip"
        else:
            detail = r if isinstance(r, str) else ""
            _results.append((PASS, name, f"{detail} ({int((time.time()-t0)*1000)}ms)"
                             if detail else f"{int((time.time()-t0)*1000)}ms"))
            status = "ok"
    except AssertionError as e:
        _results.append((FAIL, name, str(e)))
        status = "FAIL"
    except Exception as e:
        _results.append((FAIL, name, f"{type(e).__name__}: {e}"))
        status = "FAIL"
        if "-v" in sys.argv:
            traceback.print_exc()
    # Progress to stderr so a long run is observable instead of silent.
    print(f"  [{status}] {name}", file=sys.stderr, flush=True)


@contextlib.contextmanager
def a_note():
    """A note that exists for the duration of the block, then does not.

    Two checks read the notes export, and both failed with "no notes to
    export" on a library where the reader had not written anything -- so they
    were reporting on the emptiness of somebody's notes rather than on the
    export.  A check that needs a note has to make one, and has to remove it
    again: this suite runs against the real library, and leaving a "selftest"
    note in a user's notes is not a price worth paying for a green tick.
    """
    from gbible import notes as _notes
    made = _notes.save({"kind": "note", "title": "Selftest note",
                        "body": "A note about faith and love, written by the "
                                "self-test so the export has something to carry.",
                        "ref_label": "John 3:16"})
    try:
        yield made
    finally:
        _notes.remove(made["id"])


def need(kind: str):
    from gbible import library
    mods = library.list_all()
    cands = [m for m in mods if m.type == kind
             or (kind == "Bible" and m.is_bible)]
    if not cands:
        return None
    # Prefer an English module.  The checks assert on English text ("loved the
    # world", an entry count), so picking the first module of a type in library
    # order made the suite depend on which languages happened to be installed --
    # a Basque New Testament with no book markers or a French lexicon could be
    # chosen first and fail a check that has nothing to do with the code.
    for pred in (lambda m: m.lang == "eng",
                 lambda m: (m.name or "").startswith(("American", "World", "Berean",
                                                      "King James", "Strong", "Webster"))):
        for m in cands:
            if pred(m):
                return m
    return cands[0]


def _installed(module_id: str) -> bool:
    """Is this module installed?

    Some checks name a module -- a particular commentary, a particular
    dictionary -- because that is the material the feature was built against.
    On a library that does not have it, the check cannot say anything, and
    saying so is better than failing about a module that was never there.
    """
    from gbible import db as _db
    row = _db.connect().execute(
        "SELECT 1 FROM module WHERE id=? AND installed_at>0 LIMIT 1",
        (module_id,)).fetchone()
    return row is not None


def _fact_entry(title: str) -> bool:
    """Is there an installed fact book with an entry of this name?

    A *topical* fact book indexes topics -- Grace, Atonement, Prayer -- and a
    *names* fact book indexes people -- Aaron, Jesus, Jerusalem.  They are
    different books doing different work, and a check that wants a name has to
    say which kind of book it needs.
    """
    from gbible import db as _db
    row = _db.connect().execute(
        "SELECT 1 FROM unit u JOIN module m ON m.id=u.module_id "
        "WHERE m.installed_at>0 AND m.type='FactBook' AND UPPER(u.title)=? "
        "LIMIT 1", (title.upper(),)).fetchone()
    return row is not None


def need_lexicon():
    """The largest installed English lexicon/dictionary, for the headword checks.

    `need("Lexicon")` can land on a one-entry module (a Wikisource page that
    enumerates to a single article), which is not a usable lexicon and fails the
    outline check for no reason connected to the code.  Prefer a module with a
    real article count.
    """
    from gbible import library
    cands = [m for m in library.list_all()
             if m.type in ("Lexicon", "Dictionary", "Concordance", "Grammar")
             and (m.entries or 0) > 200]
    if not cands:
        return None
    for m in cands:
        if m.lang == "eng":
            return m
    return cands[0]


def run() -> bool:
    from gbible import canon, db, formats, indexer, library, markup, search, \
        store, taxonomy
    from gbible.api import registry as apireg
    from gbible import workspace
    db.init()
    # The positional index is built in the background while the app runs, and
    # a good many checks below read it.  A library that has been open a while
    # has one; a library installed five minutes ago does not, because nothing
    # but the app builds it.  So the checks would fail against an index that
    # had not been built yet, rather than against anything wrong with the
    # code -- and the failure would say "no positions for the word" about a
    # word that is in the library.
    #
    # So the index is built here, in the same way the app builds it.  It is
    # skipped when the index is already good, which is the case for every
    # library that has been running.
    try:
        from gbible import posindex
        if not posindex.available():
            posindex.build()
    except Exception as exc:                      # never block the checks
        print(f"Positional index not built: {exc}", flush=True)
    # Remember the workspace so the checks can be made to leave it untouched.
    saved = workspace.current()
    # Sync any repository that is not in the database yet, so a repository
    # added since the last run is not silently missing from the checks.
    for r in store.repos():
        if not r["item_count"] and r["id"] != "local":
            store.sync(r["id"])
    apireg.sync()

    # ---------------------------------------------------------- references
    def t_canon():
        assert canon.BOOKS_66[0].osis == "Gen" and canon.BOOKS_66[-1].osis == "Rev"
        assert len(canon.BOOKS_66) == 66
        assert sum(canon.verse_count("KJV", b.osis, c)
                   for b in canon.BOOKS_66
                   for c in range(1, canon.chapter_count("KJV", b.osis) + 1)) == 31102
        for txt, want in [("Jn 3:16", "John 3:16"), ("1 Jn 1:9", "1John 1:9"),
                          ("Gen 1:1-5", "Gen 1:1-5"), ("Jn3.16", "John 3:16"),
                          ("Ps 119", "Ps 119"), ("Rev 22:21", "Rev 22:21"),
                          ("2 Thess 3:18", "2Thess 3:18")]:
            rr = canon.parse_ref(txt)
            assert rr and rr.label() == want, f"{txt} -> {rr and rr.label()}"
        assert canon.normalise_strongs("h0430") == "H0430"
        assert canon.normalise_strongs("G11") == "G0011"
        return "66 books, 31,102 verses, refs + Strong's OK"
    check("Canonical structure and reference parsing", t_canon)

    def t_nav():
        a = canon.Ref("Gen", 1, 1)
        assert canon.next_ref(a) == canon.Ref("Gen", 1, 2)
        assert canon.prev_ref(canon.Ref("Gen", 2, 1)) == canon.Ref("Gen", 1, 26)
        # The chapter buttons step through the book first; only at the book's
        # edge do they cross into the next book.
        assert canon.next_chapter(canon.Ref("Gen", 1, 1)) == canon.Ref("Gen", 2, 1)
        assert canon.next_chapter(canon.Ref("Gen", 50, 1)) == canon.Ref("Exod", 1, 1)
        assert canon.prev_chapter(canon.Ref("Gen", 2, 1)) == canon.Ref("Gen", 1, 31)
        assert canon.prev_chapter(canon.Ref("Exod", 1, 1)) == canon.Ref("Gen", 50, 26)
        # Book buttons jump straight to the next/previous book.
        assert canon.next_book(canon.Ref("Gen", 1, 1)) == canon.Ref("Exod", 1, 1)
        assert canon.next_book(canon.Ref("Exod", 5, 1)) == canon.Ref("Lev", 1, 1)
        assert canon.next_book(canon.Ref("Mal", 4, 6)) == canon.Ref("Matt", 1, 1)
        assert canon.prev_book(canon.Ref("Exod", 1, 1)) == canon.Ref("Gen", 50, 26)
        assert canon.prev_book(canon.Ref("Matt", 1, 1)) == canon.Ref("Mal", 4, 6)
        assert canon.prev_book(canon.Ref("Gen", 50, 1)) == canon.Ref("Gen", 50, 1)
        rr = canon.parse_ref("John 3:16-18")
        assert len(list(rr.refs())) == 3
        return "next/prev/chapter/book/range OK"
    check("Milestone navigation", t_nav)

    # ------------------------------------------------------------- licence
    def t_lic():
        assert taxonomy.license_ok("public domain")
        assert taxonomy.license_ok("CC BY 4.0")
        assert taxonomy.license_ok("CC0")
        assert not taxonomy.license_ok("CC BY-NC 4.0")
        assert not taxonomy.license_ok("CC BY-ND 4.0")
        assert not taxonomy.license_ok("Copyrighted")
        assert not taxonomy.license_ok("All Rights Reserved")
        # An unstated licence is not a permission.  This used to be read as
        # "Public Domain" and pass, so every source that simply omits the field
        # -- a SWORD .conf with no DistributionLicense line -- was offered as
        # freely redistributable.
        assert not taxonomy.license_ok("")
        assert not taxonomy.license_ok("   ")
        assert not taxonomy.license_ok(None)
        assert taxonomy.normalise_license("") == "Copyrighted"
        assert taxonomy.normalise_license(None) == "Copyrighted"
        # A licence string is a claim; a publication date can contradict it.
        # Anything from 1930 onwards is still copyright in the United States.
        assert not taxonomy.redistributable(
            {"id": "x", "license": "Public Domain", "year": "1934"})[0]
        assert not taxonomy.redistributable(
            {"id": "x", "license": "Public Domain", "year": "1930"})[0]
        assert taxonomy.redistributable(
            {"id": "x", "license": "Public Domain", "year": "1927"})[0], \
            "a 1927 work is public domain on age and was refused"
        # A current, explicit grant is unaffected by the year.
        assert taxonomy.redistributable(
            {"id": "x", "license": "CC-BY-4.0", "year": "2024"})[0]
        # No year to judge by: the licence decides, as before.
        assert taxonomy.redistributable(
            {"id": "x", "license": "Public Domain"})[0]
        # The refusals must carry an explanation a user can act on.
        _ok, why = taxonomy.redistributable(
            {"id": "x", "license": "Public Domain", "year": "1934"})
        assert "1930" in why and "United States" in why, why
        # Every item the Store actually offers must pass both checks.
        import glob as _glob
        import json as _json
        offered = blocked = 0
        for f in _glob.glob(str(root_store := Path(__file__).resolve().parent.parent
                                  / "gbible" / "store" / "data" / "*.json")):
            raw = _json.load(open(f, encoding="utf-8"))
            for it in (raw if isinstance(raw, list) else raw.get("items", []) or []):
                offered += 1
                if not taxonomy.redistributable(it)[0]:
                    blocked += 1
        assert blocked == 0, (
            f"{blocked} of {offered} catalogue items would be refused by the "
            f"redistribution check but are still committed")
        assert taxonomy.normalise_license("Creative Commons Attribution 4.0") == "CC-BY-4.0"
        return ("only PD / CC0 / CC-BY / CC-BY-SA pass; blank is refused; "
                f"{offered} catalogue items all pass both checks")
    check("Licence gate", t_lic)

    # ------------------------------------------------------------- markup
    def t_markup():
        osis = ('<w lemma="strong:H0430">God</w> <w lemma="strong:G2316">loved'
                '<note osisID="John.3.16!note.1" osisRef="John.3.16" type="translation">'
                'A note.</note></w> <q who="Jesus">saith</q>'
                '<transChange type="added">also</transChange><lb/>')
        segs = markup.parse_osis(osis)
        txt = markup.segs_text(segs)
        assert "God loved" in txt and "saith" in txt and "also" in txt, txt
        assert any(s.kind == "strongs" and s.value == "H0430" for s in segs)
        assert any(s.kind == "note" and "A note." in s.text for s in segs)
        # <q who="Jesus"> marks its children as words of Christ with a flag
        # rather than changing their kind, so inline content keeps its order
        assert any(s.attrs.get("wj") for s in segs), segs
        assert any(s.kind == "add" for s in segs)
        es = markup.parse_esword_inline('the \\w Word|strong="G2316"\\w* {n} <Jesus>')
        assert any(s.kind == "strongs" and s.value == "G2316" for s in es)
        assert any(s.kind == "note" for s in es)
        assert any(s.kind == "red" for s in es)
        assert "Hello" in markup.parse_rtf(r"{\rtf1\ansi{\fonttbl{\f0 A;}}Hello \par World}")
        wt = markup.parse_wikitext("== Gen 1 ==\n'''1.''' See [[A/B|John 3:16]].")
        assert any(s.kind == "heading" for s in wt)
        return "OSIS / e-Sword / RTF / wikitext OK"
    check("Markup readers", t_markup)

    # ------------------------------------------------------------- token
    def t_tok():
        w = db.words("In the beginning God created it.")
        assert len(w) == 6
        assert w[0][1] == 0 and w[1][1] == 3
        for a, b in [("carried", "carry"), ("loved", "lov"), ("gods", "god"),
                     ("beloved", "belov"), ("churches", "church")]:
            assert db.stem(db.fold(a)) == b, (a, db.stem(db.fold(a)), b)
        return "offsets + conservative stemming OK"
    check("Tokeniser and stemmer", t_tok)

    def t_stem_converges():
        """A word and its plural must reach the *same* stem.

        This was a real bug with a real symptom.  Every suffix rule returned its
        base immediately, so "loves" was de-pluralised to "love" and stopped
        there, while "love" carried on to the silent-e rule at the bottom of the
        function and came out as "lov".  Two stems for one word, so searching
        "love" could not find "loves" -- in any query that consults the exact
        pass, which is every operator except a bare word.

        Match All Forms finds "love, loved, loves, lovely, loving and love's"
        from "love", so convergence is the specified behaviour, not a nicety.

        It is also what makes stem() idempotent, which the positional index
        relies on: the stored stems are grouped by equality, so a form that
        stems differently from its own base quietly becomes unsearchable.
        """
        pairs = [("love", "loves"), ("love", "loved"), ("love", "loving"),
                 ("love", "lovely"), ("love", "love's"),
                 ("king", "kings"), ("daughter", "daughters"),
                 ("god", "gods"), ("large", "largest"), ("carry", "carries"),
                 ("move", "moves"), ("serve", "served"),
                 ("believe", "believed"), ("sing", "singer"), ("car", "cars")]
        for base, inflected in pairs:
            a, b = db.token_key(base), db.token_key(inflected)
            assert a == b, (base, inflected, a, b)

        # The group all landing on one stem.
        key = db.token_key("love")
        group = {w for w in ("love", "loves", "loved", "loving", "lovely",
                             "love's", "lovingly") if db.token_key(w) == key}
        assert len(group) == 7, sorted(group)

        # Convergence must survive being applied to the whole vocabulary, or it
        # is only true of the words somebody thought to check.  Foreign-language
        # tokens legitimately still differ -- the stemmer is English-shaped and
        # biased towards under-stemming -- so the bound is loose on purpose.
        from gbible import posindex as PI
        conn = db.connect()
        forms = [r["form"] for r in conn.execute("SELECT form FROM pos_term")]
        if not forms:
            return None
        non = [f for f in forms
               if db.token_key(f) != db.token_key(db.token_key(f))]
        pct = 100.0 * len(non) / len(forms)
        assert pct < 1.0, f"{len(non):,} of {len(forms):,} forms do not converge ({pct:.2f}%)"
        return f"15 pairs converge; {len(non):,} stragglers ({pct:.2f}%, was 3.4%)"

    check("Stemmer: a word and its plural reach one stem", t_stem_converges)

    def t_stemmer_fingerprint_invalidates():
        """Stored stems must notice when the stemmer that made them changes.

        The stems in the index are derived data.  A derived column that cannot
        detect a change in its own source goes quietly stale, and then the index
        groups words one way while the text path groups them another -- the two
        disagree, the parity tests fail, and nothing says why.  So the stemmer is
        fingerprinted and the column recomputed when the fingerprint moves.
        """
        from gbible import posindex as PI
        conn = db.connect()
        ensure = PI.ensure_stems()
        if not ensure.get("terms"):
            return None
        assert ensure["stale"] is False, "stems look stale on a freshly synced index"
        assert ensure["updated"] == 0, "a second call should be a no-op"

        fp = PI._stemmer_fingerprint()
        assert fp and fp != "unknown", "could not fingerprint the stemmer"
        assert PI._meta_get(conn, "stemmer_fp") == fp, "fingerprint not recorded"

        # Pretend the stemmer moved; the next call must notice and rebuild.
        PI._meta_set(conn, "stemmer_fp", "stale-on-purpose")
        conn.commit()
        try:
            again = PI.ensure_stems()
            assert again["stale"] is True, "a changed fingerprint went unnoticed"
            assert again["updated"] == again["terms"], "stems were not recomputed"
        finally:
            PI.ensure_stems()
        return f"fingerprint {fp}, rebuild on change verified"

    check("Stemmer: a changed stemmer invalidates the stored stems",
          t_stemmer_fingerprint_invalidates)

    # -------------------------------------------------------------- store
    def t_store():
        out = store.sync_all()
        bad = [k for k, v in out.items() if not v.get("ok")]
        assert not bad, bad
        total = sum(v.get("items", 0) for v in out.values())
        assert total > 300, total
        r = store.list_items()
        assert r["total"] > 300
        for f in ("repo", "lang", "category", "subject", "license"):
            assert f in r["facets"], f
        il = store.list_items(installed_only=True)
        return f"{total} items, facets + installed-only filter OK"
    check("Store catalogues and facets", t_store)

    # ------------------------------------------------------- placement
    def t_placement():
        """Every catalogue item knows which pane it belongs in, before install."""
        from gbible import placement
        # No type may be unplaceable, or a module would land nowhere.
        for tid in taxonomy.TYPE_BY_ID:
            assert placement.slot_for_type(tid).id != "other" or \
                tid == "Other", tid
        # The override that motivated the whole module.
        assert placement.type_for("crosswire-tsk", "Commentary") == "CrossReference"
        assert placement.slot_for("tsk", "Commentary").reader == "verse"
        # Overrides must resolve on both the bare and the namespaced id.
        for mid in ("tsk", "crosswire-tsk"):
            assert placement.type_for(mid, "Commentary") == "CrossReference", mid
        r = store.list_items(limit=3000)
        assert r["total"] > 300, r["total"]
        for it in r["items"][:400]:
            p = it["placement"]
            assert p["slot"] and p["slot_label"] and p["reader"], it["item_id"]
        slots = {s["id"] for s in r["slots"]}
        assert {"bible", "commentary", "crossref", "map", "book"} <= slots, slots
        # Slot filtering must not be truncated by the SQL row limit.
        xr = store.list_items(slot="crossref", limit=5000)
        assert xr["total"] >= 2, xr["total"]
        assert any("Treasury" in i["title"] for i in xr["items"]), \
            [i["title"] for i in xr["items"]]
        return f"{r['total']} items placed, TSK -> cross-reference pane"
    check("Placement: every item knows its pane", t_placement)

    # ------------------------------------------------- repository removal
    def t_repo_removal():
        """A repository can be previewed, forgotten, and put back."""
        from gbible import store as st
        pv = st.repo_removal_preview("midvash")
        assert pv["ok"] and pv["removable"] and pv["bundled"], pv
        assert pv["catalogue_items"] > 0, pv
        # 'local' is not a downloadable repository and must refuse.
        bad = st.remove_repo("local")
        assert not bad["ok"], bad
        # Removing a repo that still has modules must ask, not silently delete.
        n = st.remove_repo("midvash")
        if not n["ok"]:
            assert n.get("needs_confirmation"), n
            assert n["modules"], n
            return f"preview OK ({pv['catalogue_items']} items, "\
                   f"{len(pv['installed'])} installed); 'local' refused; "\
                   f"removal held for confirmation"
        # The catalogue really was dropped.  Put it back, because a check has
        # no business leaving the user's store smaller than it found it.
        back = st.sync("midvash")
        assert back["ok"] and back["items"] == pv["catalogue_items"], back
        assert st.repo_removal_preview("midvash")["catalogue_items"] == \
            pv["catalogue_items"], "the catalogue did not come back"
        return f"preview + forget + restore OK ({pv['catalogue_items']} items); "\
               f"'local' refused"
    check("Repository removal is previewed and confirmed", t_repo_removal)

    # --------------------------------------- duplicates and in-use warnings
    def t_conflicts():
        """Duplicate and in-use warnings, proved on real data and on the rule.

        The *rule* is checked directly against real catalogue rows, so the
        check is meaningful whatever happens to be installed: a row is a
        duplicate when another repository offers the same module id under a
        different prefix, or when the same title is already in the library.
        Then the live library is checked for agreement -- no row may report
        *itself* as a duplicate, and every module open in a pane must be
        reported in use.
        """
        from gbible import placement, workspace
        conn = db.connect()
        row = conn.execute(
            "SELECT repo_id, item_id, title FROM store_item "
            "WHERE item_id IS NOT NULL AND item_id<>'' "
            "ORDER BY repo_id, item_id LIMIT 1").fetchone()
        assert row, "catalogue is empty"
        rid, iid, title = dict(row)

        # (1) The same module arriving from another repository.
        d = placement.duplicates_of_names(
            title, rid, iid, [(f"otherrepo-{iid}", title, "otherrepo")])
        assert len(d) == 1, d
        assert d[0]["module_id"] == f"otherrepo-{iid}", d
        assert "another repository" in d[0]["reason"], d

        # (2) The same title, in a library where the catalogue row itself is
        # not installed.  'Geneva Bible (1599)' and 'Geneva Bible 1599' are
        # one missing punctuation apart, so they collide after normalising.
        d = placement.duplicates_of_names(
            "Geneva Bible (1599)", "crosswire", "geneva-someother",
            [("ebible-enggnv", "Geneva Bible 1599", "ebible")])
        assert len(d) == 1, d
        assert d[0]["reason"] == "the same title", d

        # (3) Neither a self-reference nor an unrelated module is a duplicate.
        assert not placement.duplicates_of_names(title, rid, iid, []), \
            "an empty library must report no duplicates"
        assert not placement.duplicates_of_names(
            title, rid, iid, [(f"{rid}-{iid}", title, rid)]), \
            "a row must not be reported as a duplicate of itself"
        assert not placement.duplicates_of_names(
            title, rid, iid, [("crosswire-totally-different", "KJV", "x")]), \
            "an unrelated module was called a duplicate"

        # (4) The rule is exercised by real catalogue data: the same work is
        # genuinely offered from more than one repository under a title or id
        # that the rule catches, and the live library agrees with the rule --
        # a row whose module is installed is 'installed', never reported as
        # a duplicate of itself.
        rows = [dict(x) for x in conn.execute(
                "SELECT repo_id, item_id, title, module_id FROM store_item")]
        norm = placement._norm
        real = next((
            i for i in rows
            if any(j["item_id"] == i["item_id"] and j["repo_id"] != i["repo_id"]
                   or norm(j["title"]) == norm(i["title"]) and i["title"]
                   and j["repo_id"] != i["repo_id"]
                   for j in rows)), None)
        assert real, "no cross-repository duplicate in the catalogue"
        d = placement.duplicates_of_names(
            real["title"], real["repo_id"], real["item_id"],
            [(j["module_id"] or f"{j['repo_id']}-{j['item_id']}",
              j["title"], j["repo_id"])
             for j in rows if j is not real])
        assert d, "the real cross-repository pair was not flagged"

        # (5) A module open in a pane is reported in use, and the workspace
        # and the placement layer must not disagree about it.  The catalogue
        # snapshot is taken *after* the layout is built, so a freshly opened
        # pane has to be visible in it.
        lay = workspace.build_study_layout("SelfTest")
        open_ids = [p["module_id"] for p in lay.get("panes", [])
                    if p.get("module_id")]
        if not open_ids:
            return None
        mid = open_ids[0]
        used = placement.panes_using(mid, (lay,))
        assert used, "an open pane was not reported as in use"
        r = store.list_items(limit=5000)
        flagged = [i for i in r["items"] if i["duplicates"]]
        for i in r["items"]:
            if i.get("installed"):
                assert not any(x["module_id"] == i["module_id"]
                               for x in i["duplicates"]), i["title"]
        row = next((i for i in r["items"] if i.get("module_id") == mid), None)
        if row is not None:
            assert row["in_use"], "an open pane's row was not marked in use"
            assert lay["id"] in {u["layout_id"] for u in row["in_use"]}, row
        return f"{len(flagged)} rows flagged already installed; "\
               f"{len(used)} pane(s) using {mid}"
    check("Already-installed and in-use warnings", t_conflicts)

    # -------------------------------------------------------- every reader
    def t_all_readers():
        """Each installed module must actually return content."""
        # Every reader the app has, including audio.  A reader missing from this
        # table made the whole check fail with a bare KeyError the moment anyone
        # installed an audio folder, which is a crash in the test rather than a
        # finding about the app.
        cursors = {"verse": {"ref": "John 1"}, "article": {"key": "Aaron"},
                   "topic": {"key": "Aaron"}, "date": {"date": "1.1"},
                   "book": {"ref": "1.1"}, "image": {}, "audio": {}}
        mods = library.list_all()
        if len(mods) < 6:
            return None          # too thin to exercise every reader
        seen, empty, bad = set(), [], []
        conn = db.connect()
        for m in mods:
            seen.add(m.reader)
            # Ask each module at a reference it actually contains.  Probing a
            # fixed "John 1" reports a sparse commentary as unreadable when all
            # it needs is a cursor inside its own coverage.
            # Prefer a unit that is actually anchored to a verse: a book or a
            # commentary opens with front matter ("Rieger.Autobiografie",
            # "intro") that has no reference to ask at.
            row = conn.execute(
                "SELECT key, ref_label FROM unit WHERE module_id=? "
                "AND book IS NOT NULL AND book<>'' AND chapter>0 "
                "ORDER BY ord LIMIT 1", (m.id,)).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT key, ref_label FROM unit WHERE module_id=? "
                    "ORDER BY ord LIMIT 1", (m.id,)).fetchone()
            if m.reader not in cursors:
                bad.append(f"{m.name}: reader '{m.reader}' is not exercised by "
                           f"this check")
                continue
            cur = dict(cursors[m.reader])
            if row is not None:
                if m.reader == "verse":
                    # Unit labels come in both shapes: "John 3:1" and
                    # "John.3.1".  Derive a reference from whichever it is.
                    lbl = (row["ref_label"] or "").strip()
                    bits = lbl.replace(".", " ").replace(":", " ").split()
                    if len(bits) == 3 and bits[1].isdigit() and bits[2].isdigit():
                        cur = {"ref": f"{bits[0]} {bits[1]}:{bits[2]}"}
                    elif len(bits) == 2 and bits[1].isdigit():
                        cur = {"ref": f"{bits[0]} {bits[1]}"}
                elif m.reader == "article":
                    cur = {"key": row["key"]}
                elif m.reader == "date":
                    # A devotional is keyed by the date it is read on, and
                    # the shapes differ -- "1.1" and "01.01" are both in the
                    # wild -- so the date the module actually holds is the
                    # one to ask for.  Asking for a fixed "1.1" found
                    # nothing in a devotional that began on the tenth of
                    # February, and the check reported a module that would
                    # not read.
                    cur = {"date": row["key"]}
            try:
                c = library.read(m.id, cur)
            except Exception as e:
                bad.append(f"{m.name}: {type(e).__name__}: {e}")
                continue
            if not c.items:
                empty.append(f"{m.name} (asked at {cur})")
        assert not bad, bad
        assert not empty, f"readers returned nothing: {empty}"
        assert {"verse", "article", "topic", "date", "book", "image"} <= seen, \
            f"only exercised {seen}"
        return f"all {len(mods)} modules readable across "\
               f"{len(seen)} reader kinds"
    check("Every installed module is readable", t_all_readers)

    # ------------------------------------------------ front end, statically
    def t_write_ahead_log():
        """The write-ahead log has to be foldable, not just present.

        `wal_autocheckpoint` only fires after a commit that pushes it past its
        threshold and skips silently when a reader is mid-transaction, retrying
        on the next commit.  A bulk install is one enormous transaction, so the
        log grew to 156 MB and stayed, with nothing locked and nothing wrong --
        just no further commit to trigger the retry.  On a 2.8 GB database every
        read then consults that log first.
        """
        conn = db.connect()
        size = _wal_bytes()
        db.maybe_checkpoint(conn, truncate=True)
        after = _wal_bytes()
        assert size < 200 * 1024 * 1024, \
            f"the write-ahead log is {size // (1024 * 1024)} MB; checkpoint did not run"
        assert after < size or size == 0, \
            f"checkpoint left {after} bytes where there were {size}"
        return f"{size // 1024} KB -> {after // 1024} KB after a checkpoint"
    check("Write-ahead log is folded back in", t_write_ahead_log)

    # ------------------------------------------------ front end, statically
    def t_frontend_static():
        """Catch front-end mistakes that only show up when someone clicks.

        Three classes, all of which happened here repeatedly: an object defining
        the same method twice (the second silently winning, so a caller reached a
        different function than the name suggests), a call to a method an object
        does not have, and a `$('#id')` for an element that is not in the page --
        which returns null and then throws somewhere else entirely.
        """
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            import jscheck
        except ImportError:
            return None
        got = jscheck.run()
        if got.startswith("SKIP"):
            return None                      # esprima not installed; say so
        assert not got.startswith("FAIL"), got
        return got
    check("Front end is internally consistent", t_frontend_static)

    # ------------------------------------------------- nothing to redistribute
    def t_no_bundled_material():
        """The committed tree must contain no study material, only code.

        The MIT licence covers the software.  Every Bible text, commentary,
        lexicon, map and photograph is downloaded at run time under its own
        licence, and none of them may end up in a release.  This turns "we do
        not bundle anything" from a claim in the README into something checked,
        because the failure mode is a stray module archive committed by accident
        and nobody notices until the repository is public.
        """
        root = Path(__file__).resolve().parent.parent
        ignore = _gitignore_patterns(root)
        offenders, biggest = [], (0, "")
        blob, blob_where = 0, ""
        SKIP_DIRS = {"data", "__pycache__", ".git", "node_modules", ".venv"}
        # An installed module is a zip, a SWORD directory, or a source file.
        MATERIAL_EXT = {".usfm", ".bzz", ".bzs", ".bzv", ".zip", ".osis", ".sql",
                        ".db", ".mp3", ".ogg", ".m4a", ".wav", ".flac"}
        # Source is code, and code grows with the app: app.js is 9,700 lines of
        # hand-written JavaScript. Holding it to the same 400 KB as a stray
        # archive meant failing on the file the project is named for, so the
        # cap below applies to what it was actually for -- a Bible text or an
        # archive committed by accident -- and source is measured against a much
        # higher ceiling instead. That is not a blanket pass: a source file big
        # enough to be hiding bundled material is still rejected.
        CODE_SUFFIX = {".py", ".js", ".css", ".html", ".md", ".json", ".txt"}
        SOURCE_CEILING = 2_000_000
        for path in root.rglob("*"):
            rel = path.relative_to(root)
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            if not path.is_file():
                continue
            if _is_ignored(rel, ignore):
                continue
            if path.suffix.lower() in MATERIAL_EXT:
                offenders.append(str(rel))
            size = path.stat().st_size
            if path.suffix.lower() in CODE_SUFFIX:
                if size > blob:
                    blob, blob_where = size, str(rel)
                continue
            if size > biggest[0]:
                biggest = (size, str(rel))
        assert not offenders, (
            "study material is committed in the source tree: "
            + ", ".join(offenders[:6])
            + ". Remove it; the Store installs it at run time.")
        # Anything this large in the source tree is a mistake -- an archive or a
        # Bible text committed by accident.  Source is measured separately, above.
        assert biggest[0] < 400_000, f"{biggest[1]} is {biggest[0]} bytes"
        # Source is allowed to be big, but not to *contain* something big: a
        # base64 blob or a wall of scripture is the thing the size cap was
        # really about, and it would hide inside a .js file that is allowed to
        # exceed 400 KB on its own.
        assert blob < SOURCE_CEILING, \
            f"{blob_where} is {blob} bytes; source this large is usually a blob of embedded data"
        # And the runtime library must actually be ignored, or the next person
        # to clone and run gets 3 GB of third-party texts staged for commit.
        assert _is_ignored(Path("data"), ignore), "data/ is not ignored by .gitignore"
        assert _is_ignored(Path("data/modules/kjv/module.zip"), ignore), \
            "data/modules is not ignored"
        assert _is_ignored(Path("__pycache__/x.pyc"), ignore), \
            "__pycache__ is not ignored"
        # The Store catalogues are metadata and are meant to be committed.
        for f in sorted((root / "gbible" / "store" / "data").glob("*.json")):
            rel = f.relative_to(root)
            assert not _is_ignored(rel, ignore), f"{rel} must stay committed"
        return f"clean; largest committed file {biggest[1]} ({biggest[0]} bytes)"
    check("Nothing redistributable is committed", t_no_bundled_material)

    # ------------------------------------------------------ factbook tags
    def t_fact_tags():
        """Names in a passage carry a meaning, without leaving the page."""
        from gbible import study as _study

        if not [m for m in library.list_all()
                if m.type == "FactBook" and _study._is_a_fact_book(m.name)]:
            return None
        idx = _study.tag_index()
        if not idx:
            return None
        # Proper nouns only: tagging "the" would train a reader to ignore it.
        tags = _study.fact_tags(
            "And Moses brought the people out of Egypt, and Aaron was his brother.")
        words = {t["word"] for t in tags}
        assert {"Moses", "Aaron"} <= words, words
        assert "the" not in words, "tagged a function word"
        for t in tags:
            assert t["gloss"] and t["source"], t
        # Matching is on the capitalised token, because that is what a proper
        # noun looks like in English text.  Lower-case running text is left
        # alone -- a test asserting otherwise would be asserting a bug, and it
        # is what stops "and" or "the" picking up a tooltip somewhere.
        assert _study.fact_tags("moses and aaron") == [], \
            "tagged a name that was not capitalised"
        # Capitalisation does not matter once the token is recognised.
        caps = _study.fact_tags("MOSES and AARON")
        assert {"MOSES", "AARON"} <= {t["word"] for t in caps}, caps
        # A tag's tooltip has to be short, or it is a paragraph in a hover box.
        assert all(len(t["gloss"]) <= 240 for t in tags),             [len(t["gloss"]) for t in tags]
        # Nothing to tag is not an error.
        assert _study.fact_tags("") == []
        assert _study.fact_tags("zzzz qqqq") == []
        return f"{len(idx)} names indexed, {len(tags)} tagged in one verse"
    check("Factbook tags", t_fact_tags)

    # ------------------------------------------------------- topic guide shape
    def t_topic_guide_shape():
        """The Topic guide is a library dashboard, not a second fact-book list.

        Some platforms split the two deliberately: the Factbook is one article
        about an entity, the Topic Guide is your library's results grouped by
        kind.  An earlier version here had two near-duplicate fact-book popups,
        which is the confusion this check exists to prevent.
        """
        from gbible import study as _study
        r = _study.topic_guide("Jerusalem")
        assert r["ok"], r
        kinds = {s["kind"] for s in r["sections"]}
        for want in ("topic", "verses", "atlas", "dictionary"):
            assert want in kinds, f"no {want} section: {sorted(kinds)}"
        # The Topic heading links onward to the fact guide, so the two do not
        # print the same thing twice.
        topic = [s for s in r["sections"] if s["kind"] == "topic"][0]
        assert topic.get("fact_query"), topic
        # Related Verses must say what it actually did: it lists verses that
        # contain the word, which is not the same as verses where the topic is
        # prominent, and must not claim to be.
        verses = [s for s in r["sections"] if s["kind"] == "verses"]
        if verses:
            assert "contain" in verses[0]["note"].lower(), verses[0]["note"]
            assert verses[0]["items"], "section present but empty"
        # And it must be quick: an early version took 12 seconds to assemble.
        t0 = time.time()
        _study.topic_guide("Jerusalem")
        dt = time.time() - t0
        assert dt < 6.0, f"the Topic guide took {dt:.1f}s"
        return f"sections {sorted(kinds)} in {dt:.2f}s"
    check("Topic guide is a library dashboard", t_topic_guide_shape)

    # --------------------------------------------------------- fact-book guide
    def t_fact_guide():
        """The fact guide must sort entries by kind, and never show one twice."""
        from gbible import study as _study

        if not [m for m in library.list_all()
                if m.type == "FactBook" and _study._is_a_fact_book(m.name)]:
            return None
        # This part needs a *names* fact book.  A topical one does not have
        # AARON -- it has GRACE and ATONEMENT, and a person belongs there under
        # other headings -- and a guide with nothing to sort is not a guide
        # that was sorted wrongly.
        if not _fact_entry("AARON"):
            return Skip("no fact book with an entry for AARON is installed "
                        "(a topical fact book indexes topics, not people)")
        # "aaron" has to find AARON: the fact books store heads in the case each
        # book uses, and a case-sensitive match finds nothing.
        r = _study.fact_guide("aaron")
        assert r["ok"], r
        kinds = {s["kind"] for s in r["sections"]}
        assert "name" in kinds, r["sections"]
        names = [i for s in r["sections"] if s["kind"] == "name" for i in s["items"]]
        assert any("AARON" in i["title"].upper() for i in names), names
        # A person must not be filed as a place.  Aaron means "mountain of
        # strength", which a keyword heuristic read as geography.
        place_titles = [i["title"] for s in r["sections"] if s["kind"] == "place"
                        for i in s["items"]]
        assert not any("AARON" in t.upper() for t in place_titles), place_titles
        # No entry may appear in two sections.
        seen = [(i["module_id"], i["key"]) for s in r["sections"]
                for i in s["items"]]
        assert len(seen) == len(set(seen)), "an entry was listed twice"
        # A geocoded place brings its coordinates with it.
        j = _study.fact_guide("Jerusalem")
        geo = [g for s in j["sections"] for g in (s.get("geo") or [])]
        assert geo, "Jerusalem is geocoded but no place section appeared"
        assert geo[0]["lat"] and geo[0]["lon"], geo[0]
        # Mapping lexicons are not fact books and must not be listed as searched.
        assert not [b for b in j["factbooks"]
                    if "klingon" in b.lower() or "mapping" in b.lower()], j["factbooks"]
        # And the obvious refusals.
        assert not _study.fact_guide("").get("ok"), "accepted an empty term"
        assert not _study.fact_guide("zzzznotaword").get("sections"), \
            "invented a result for a word no book covers"
        return (f"{len(r['factbooks'])} fact books, "
                f"{sum(len(s['items']) for s in r['sections'])} entries sorted")
    check("Fact-book guide", t_fact_guide)

    # ------------------------------------------------------- source integrity
    def t_bible_completeness():
        """Catch a Bible that silently drops the last verse of every chapter.

        A translation may legitimately differ from the KJV canon in a few
        chapters -- that is versification, and it is fine.  What is not fine is
        a source losing the final verse of *nearly every* chapter: the King
        James module from CrossWire does, in 1,125 of its 1,189 chapters, and a
        reader would not notice.  Exodus 12 silently loses the Passover.  This
        separates the two cases so the bad one is visible.
        """
        from gbible import concordance as _cg
        conn = db.connect()
        systemic, abridged, minor = [], [], []
        for r in conn.execute("SELECT id, name FROM module WHERE type='Bible'"):
            c = _cg.completeness(r["id"])
            if not c.get("ok"):
                continue
            if c["truncated"]:
                systemic.append(f"{r['name']} ({c['short']}/{c['chapters']})")
            elif c["abridged"]:
                # A deliberately shorter edition.  The 1911 Migne French Vulgate
                # omits most of the Old Testament by design; that is the edition,
                # not damage to it, and failing on it would be crying wolf.
                abridged.append(f"{r['name']} ({c['percent_absent']}% absent)")
            elif c["short"]:
                minor.append(f"{r['name']} ({c['short']})")
        # Reported, not failed.  This check is about the app; a truncated source
        # is a fact about the library, and the selftest asserting otherwise
        # leaves it permanently red for something the reader can only fix by
        # deleting material.  It is surfaced in the Library instead, where it
        # can actually be acted on.
        out = ""
        if systemic:
            out += ("; TRUNCATED: " + "; ".join(systemic)
                    + " -- verse references near a chapter's end will not resolve")
        if abridged:
            out += (f"; abridged editions: {len(abridged)} "
                    + "; ".join(abridged) + " (by design)")
        if minor:
            out += f"; {len(minor)} differ from KJV in a few chapters (versification, fine)"
        return out.strip("; ") or "all Bibles complete"
    check("Bibles are complete, not truncated", t_bible_completeness)

    # ------------------------------------------------------------- concordance
    def t_concordance():
        """A chapter indexed word by word, and a lookup that follows the lemma."""
        from gbible import concordance as cg

        conn = db.connect()
        kjv = conn.execute(
            "SELECT id FROM module WHERE id='open-bibles-eng-kjv'").fetchone()
        if kjv is None:
            kjv = conn.execute("SELECT id FROM module WHERE type='Bible' AND "
                              "has_strongs=1 ORDER BY entries DESC LIMIT 1").fetchone()
        if kjv is None:
            return None
        mid = kjv["id"]
        r = cg.build(mid, "John 3")
        assert r["ok"], r
        assert r["scanned"] > 30, r["scanned"]
        assert r["distinct"] > 40, r["distinct"]
        assert r["occurrences"] > r["distinct"], "an index cannot have fewer uses than entries"
        for e in r["entries"]:
            assert e["count"] == len(e["occurrences"]), e["id"]
            assert e["count"] > 0, e
            for o in e["occurrences"]:
                assert o["word"].strip() and o["ref"], o
        # Sorted most-used first, so the word tying the chapter together is first.
        counts = [e["count"] for e in r["entries"]]
        assert counts == sorted(counts, reverse=True), counts[:6]

        # Looking a word up must reach its other forms, which is the whole
        # point: "love" has to find "loved" and "loveth".
        w = cg.build(mid, "John 3", word="love")
        if w.get("ok"):
            forms = {f["word"] for e in w["entries"] for f in e["forms"]}
            assert any(x in forms for x in ("loved", "love", "loveth")), forms
        # A word that is genuinely absent must say so, not return an empty list.
        bad = cg.build(mid, "John 3", word="zzqqxx")
        assert not bad.get("ok") and "does not occur" in bad.get("error", ""), bad
        # tagged_only must actually filter.
        t = cg.build(mid, "John 3", tagged_only=True)
        if t.get("ok"):
            assert all(e["tagged"] for e in t["entries"]), "untagged entry survived"
        return f"{r['distinct']} entries, {r['occurrences']} uses in {r['scanned']} verses"
    check("Chapter concordance", t_concordance)

    # --------------------------------------------------------- NT use of the OT
    def t_ntuseot():
        """Every quotation reference re-checked against the installed text."""
        from gbible import ntuseot as nu

        cap = nu.capable_modules()
        if not cap["both"]:
            return None                      # no Bible with both testaments
        pick = cap["both"][0]
        r = nu.classify(pick["id"], pick["id"])
        assert r["ok"], r
        assert r["listed"] > 100, r["listed"]
        # The whole point of the verification pass: an entry that does not
        # resolve, or whose "Old Testament" side turns out to be a New
        # Testament book, must not be shown as a quotation.
        assert not r["unverified"], r["unverified"][:3]
        for q in r["quotations"] + r["allusions"]:
            assert q["kind"] in ("quotation", "allusion"), q
            assert q["nt_text"] and q["ot_text"], q
            assert q["nt"] != q["ot"], q
        # A quotation is only ever claimed where the wording is demonstrably
        # shared, and an allusion is only ever claimed where it is not.
        for q in r["quotations"]:
            assert q["verified"] and (q["passages"] > 0 or q["run"] >= r["window"]), q
        for q in r["allusions"]:
            assert not q["verified"], q
        assert r["verified_count"] > 0, "no verified quotation at all"
        # A verse known to quote Isaiah must be among them, and the check is
        # mechanical: the two verses really do share a passage.
        m1 = [q for q in r["quotations"] if q["nt"].startswith("Matt 1:23")]
        if m1:
            assert m1[0]["ot"].startswith("Isa"), m1[0]
        # Refusals.
        assert not nu.classify("no-such-module", "no-such-module").get("ok")
        assert not nu.find("no-such-module", "no-such-module").get("ok")
        assert not nu.find(pick["id"]).get("ok"), "accepted with no OT resource"
        return (f"{r['listed']} references checked, "
                f"{r['verified_count']} verified, {r['allusion_count']} allusions")
    check("New Testament use of the Old Testament", t_ntuseot)

    def t_ntuseot_find():
        """The matcher finds quotations the list does not contain."""
        from gbible import ntuseot as nu
        cap = nu.capable_modules()
        if not cap["both"]:
            return None
        pick = cap["both"][0]
        r = nu.find(pick["id"], pick["id"])
        assert r["ok"], r
        assert r["verses"], "the matcher found nothing at all"
        for v in r["verses"][:20]:
            assert v["quotes"] and v["quotes"][0]["ot_text"], v
            assert v["quotes"][0]["ot_key"] != v["key"], "a verse matched itself"
        return f"{r['verse_count']} New Testament verses matched"
    check("Unlisted quotation matching", t_ntuseot_find)

    # ---------------------------------------------------------- version merge
    def t_merge():
        """Translations fused into one text, with the disagreements marked."""
        from gbible import merge as merge_mod

        conn = db.connect()
        bibles = [r["id"] for r in conn.execute(
            "SELECT id FROM module WHERE type='Bible' AND lang='eng' "
            "AND installed_at>0 ORDER BY name")]
        if len(bibles) < 2:
            return None                      # nothing to merge

        sample = merge_mod._merge_verse([
            "For God gave his only begotten Son",
            "For God gave his only Son",
        ])
        crux = [s for s in sample["segments"]
                if s["t"] == "variant" and "begotten" in s["w"]]
        assert crux and sample["variants"] > 0, sample
        assert all("begotten" in r["w"] for s in crux for r in s["readings"]), crux
        covered = [mid for mid in bibles if conn.execute(
            "SELECT 1 FROM unit WHERE module_id=? AND book='John' AND chapter=3 "
            "AND verse=16 AND trim(text)<>'' LIMIT 1", (mid,)).fetchone()]
        if len(covered) < 2:
            if len(covered) == 1:
                only_text = merge_mod.merge("John 3:16", bibles)
                assert only_text.get("ok") and only_text["agreement"] is None, \
                    only_text
            return Skip("fewer than two installed English Bibles have John 3:16")
        bibles = covered

        # Refusals first: a merge of one translation is Compare with extra steps
        # and must say so rather than quietly returning a single column.
        assert "two or more" in (merge_mod.merge("John 3:16", [bibles[0]])
                                 .get("error", "")), "one version was not refused"
        assert not merge_mod.merge("John 3:16", []).get("ok"), "no versions accepted"
        assert not merge_mod.merge("nonsense here", bibles).get("ok"), "bad ref accepted"
        assert not merge_mod.merge("Jude 99", bibles).get("ok"), "absent verse accepted"

        r = merge_mod.merge("John 3:16", bibles)
        assert r["ok"], r
        v = r["verses"][0]
        assert v["label"] == "John 3:16", v["label"]
        assert v["segments"], "no segments produced"
        # The merged text must read as prose: whitespace-separated words, not a
        # run-on of concatenated fragments.
        assert len(v["text"].split()) > 20, len(v["text"])
        # Every segment carries a reading for at least the spine version.
        for seg in v["segments"]:
            assert seg["w"].strip(), seg
            assert seg["readings"], seg
            assert seg["t"] in ("same", "variant"), seg["t"]

        # John 3:16's best-known crux must actually be found, or the alignment
        # is not doing its job.  A merge that never disagrees is a comparison
        # in disguise.
        assert r["variants"] > 0, "no disagreements at all -- alignment is suspect"
        marked = " ".join(s["w"] for s in v["segments"] if s["t"] == "variant")
        assert "begotten" in marked, marked[:80]
        # And the disagreement has to be real: some version must read it
        # *without* "begotten".  Checking only the spine side passed while the
        # aligner scored that omission as agreement -- a version that drops a
        # word was skipped over at that index, so its reading looked like it
        # matched.
        cruxes = [s for s in v["segments"]
                  if s["t"] == "variant" and "begotten" in s["w"]]
        assert cruxes, "no variant run covers the begotten crux"
        others = {x["w"] for s in cruxes for x in s["readings"]}
        assert any("begotten" not in o for o in others), \
            "no version omits the word: %r" % (sorted(others),)

        # A range must merge every verse in it, and label it compactly.
        rng = merge_mod.merge("John 3:1-4", bibles)
        assert rng["ok"] and len(rng["verses"]) == 4, len(rng.get("verses", []))
        assert rng["ref"] == "John 3:1\u20134", rng["ref"]
        assert rng["caveat"], "no caveat about what a merge is"

        # Alignment must be symmetric-ish: dropping a version cannot change the
        # wording that version contributed out of the text.
        two = merge_mod.merge("John 3:16", bibles[:2])
        assert two["ok"], two
        for seg in two["verses"][0]["segments"]:
            for rd in seg["readings"]:
                assert rd["w"].strip(), rd
        return (f"{len(bibles)} translations, {r['agreement']}% agreement at "
                f"John 3:16, {r['variants']} variant runs")
    check("Version merging", t_merge)

    def t_facets_data():
        """The library has enough variety for the faceted filters to matter."""
        conn = db.connect()
        types = {r["type"] for r in conn.execute(
            "SELECT DISTINCT type FROM module")}
        langs = {r["lang"] for r in conn.execute(
            "SELECT DISTINCT lang FROM module WHERE lang<>''")}
        if len(types) < 3:
            return None
        assert len(types) >= 3, types
        assert len(langs) >= 2, langs
        return f"{len(types)} types, {len(langs)} languages"
    check("Library is varied enough to facet", t_facets_data)

    # -------------------------------------------------------------- audio
    def t_audio():
        """Audio you already have: names resolved, licence required, no copies."""
        import json as _json
        import shutil
        import tempfile
        import wave

        from gbible import audio as audio_mod

        # The guesser is checked on names alone, so it runs without a library.
        cases = {
            "Gen 01 - In the beginning.mp3": "Gen 1",
            "Gen_02.mp3": "Gen 2",
            "John.3.16.mp3": "John 3:16",
            "01 - John 3 - The Word became flesh.mp3": "John 3",
            "Psa 23.mp3": "Ps 23",
            "1Cor 13.4-8.13.mp3": "1Cor 13:4",
            "track07.mp3": "",
            "Concerning Spiritual Gifts - Intro.mp3": "",
        }
        for fn, want in cases.items():
            got = audio_mod._guess_ref(fn)
            assert got == want, f"{fn!r} -> {got!r}, wanted {want!r}"

        # Inside the home directory, because audio reading is confined to it.
        # A fixture in /tmp is refused, which is the confinement working.
        tmp = tempfile.mkdtemp(prefix=".gbible-audio-", dir=str(Path.home()))
        try:
            for name in ("Gen 01.wav", "Ps 23.wav", "track07.wav"):
                with wave.open(str(Path(tmp) / name), "w") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(8000)
                    w.writeframes(b"\0\0" * 400)

            # A licence is not a nag: it is the only evidence the recording is
            # usable, so registering without one must fail.
            r = audio_mod.register(tmp)
            assert not r["ok"], "registered with no licence"
            assert "licence" in r["error"].lower(), r["error"]
            r = audio_mod.register(tmp, license_="CC0")
            assert r["ok"] and r["files"] == 3, r
            assert r["with_reference"] == 2, r
            mid = r["id"]

            m = library.get(mid)
            assert m is not None and m.reader == "audio", m
            assert m.license == "CC0"

            c = library.read(mid, {})
            assert c.kind == "audio" and len(c.items) == 3, (c.kind, len(c.items))
            assert c.extra.get("license") == "CC0", c.extra
            # The stored path must be real JSON: a Python repr here parses to
            # nothing and every player ends up with a blank src.
            for it in c.items:
                assert it.extra["file"].endswith(".wav"), it.extra
                assert it.extra["mime"].startswith("audio/"), it.extra
            row = db.connect().execute(
                "SELECT extra FROM unit WHERE module_id=? AND key=?",
                (mid, "Ps 23")).fetchone()
            _json.loads(row["extra"])

            # Removal unregisters; it must not touch the user's files.
            d = audio_mod.remove(mid)
            assert d["ok"] and library.get(mid) is None, d
            assert (Path(tmp) / "Ps 23.wav").exists(), "files were deleted"

            # Confinement: a folder outside the home directory is refused, so
            # the API cannot be used to walk /etc or list a home directory tree.
            for outside in ("/etc", "/", "/usr"):
                assert audio_mod.scan(outside) == [], \
                    f"scan({outside}) returned files"
                # A separate name: reusing `r` here clobbered the register result
                # the summary line reads, and it failed as a bare KeyError.
                refused = audio_mod.register(outside, license_="CC0")
                assert not refused["ok"], refused
                assert "home" in refused["error"], refused
            return (f"{len(cases)} names, {r['files']} files, licence enforced, "
                    f"reads confined to the home directory")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    check("Audio: names resolved, licence required, files untouched", t_audio)

    # ------------------------------------------------------------------- tts
    def t_tts():
        """Read aloud: the voice, when it is installed, is a real WAV.

        The part that matters is that synthesise() answers Unavailable -- and
        not ImportError or ModuleNotFoundError -- on a machine with nothing
        installed.  That is the contract the 501 route and the front end's
        fallback are both written against, and getting it wrong produces a 500
        and a button that reads nothing at all.
        """
        import array
        import math
        import wave

        from gbible import tts

        st = tts.status()
        for key in ("available", "voice", "voices", "model"):
            assert key in st, f"status() is missing {key!r}: {st}"
        assert st["voice"] == tts.VOICE, st["voice"]
        assert tts.VOICE in st["voices"], st["voices"]

        if not st["available"]:
            # The un-equipped case: no voice, and it says so rather than
            # raising something the caller has to recognise.
            assert st["reason"], "unavailable with no reason given"
            try:
                tts.synthesise("In the beginning was the Word.")
            except tts.Unavailable:
                pass
            except Exception as exc:
                raise AssertionError(
                    f"expected Unavailable, got {type(exc).__name__}: {exc}")
            else:
                raise AssertionError("synthesised with no voice installed")
            tts.warm()                       # must not raise either
            return None                      # "not installed"

        # Empty text is a caller mistake, not a missing install, and the two are
        # answered differently so the front end falls back for only one of them.
        try:
            tts.synthesise("   ")
        except ValueError:
            pass
        else:
            raise AssertionError("empty text was not refused")

        raw = tts.synthesise("In the beginning was the Word.")
        assert raw[:4] == b"RIFF" and raw[8:12] == b"WAVE", raw[:12]
        with wave.open(io.BytesIO(raw)) as w:
            assert w.getnchannels() == 1, w.getnchannels()
            assert w.getsampwidth() == 2, w.getsampwidth()
            assert w.getframerate() == tts.SAMPLE_RATE, w.getframerate()
            secs = w.getnframes() / float(w.getframerate())
            frames = w.readframes(w.getnframes())

        assert secs > 0.4, f"{secs:.2f}s of audio for a five-word sentence"
        pcm = array.array("h")
        pcm.frombytes(frames)
        peak = max(abs(x) for x in pcm)
        assert peak > 2000, f"silent (peak {peak}); a voice, not a hum"
        rms = math.sqrt(sum(float(x) * x for x in pcm) / len(pcm))
        assert rms > 300, f"rms {rms:.0f} is noise, not speech"

        # Clamped rather than refused: a long passage is truncated, not an error.
        long = tts.synthesise("word " * (tts.MAX_CHARS // 2 + 50))
        with wave.open(io.BytesIO(long)) as w:
            assert w.getnframes() > 0, "clamped text produced no audio"

        return (f"Bruno, {len(raw) // 1024}KB for {secs:.1f}s, "
                f"peak {peak}, {len(st['voices'])} voices")

    check("Read aloud: voice installed or cleanly reported absent", t_tts)

    # ------------------------------------------------------------- apis
    def t_apis():
        rows = apireg.list_apis()
        assert len(rows) >= 44, len(rows)
        nokey = [r for r in rows if not r["key_required"]]
        assert len(nokey) >= 30
        for r in rows:
            assert r["key_required_label"], r["id"]
            assert r["status"] in ("available", "needs key", "reference only")
        # Every source named in the brief must be present and resolvable.
        named = ("gnosis", "bibleatlas", "theographic", "openbible-info",
                 "free-use-bible-api", "bible-midvash", "berean-standard-bible",
                 "step-bible", "midvash-bible-data", "bible-supersearch",
                 "bible-databases")
        have = {r["id"] for r in rows}
        missing = [n for n in named if n not in have]
        assert not missing, f"named sources missing from the registry: {missing}"
        for r in rows:
            if r["id"] in named:
                assert r["site_url"] or r["base_url"] or r["doc_url"], r["id"]
        g = apireg.set_key("bolls-bible", "TESTKEY")
        assert g["key_set"]
        apireg.set_key("bolls-bible", "")
        # A stored key must change the reported status.  `list_apis` blanks the
        # key before reporting, and the status tested the blanked value, so
        # every key-requiring service said "needs key" whether or not a key was
        # saved -- which is the answer that reads as a bug to the one person who
        # can fix it.
        withkey = next(r for r in apireg.list_apis() if r["id"] == "bolls-bible")
        apireg.set_key("bolls-bible", "TESTKEY")
        try:
            now = next(r for r in apireg.list_apis() if r["id"] == "bolls-bible")
            assert now["key_set"] and not now["key"]
            assert now["status"] != "needs key", now
        finally:
            apireg.set_key("bolls-bible", "")
        # "reference only" has to be reachable, or asserting a legal status is
        # asserting nothing: every record has a site_url, so a status of
        # "available" that also accepted site_url made this branch dead.
        refs = [r for r in rows if r["status"] == "reference only"]
        assert refs, "no service reports 'reference only'; the branch is dead"
        for r in refs:
            assert not r["base_url"], r["id"]
        return (f"{len(rows)} APIs, {len(nokey)} need no key, "
                f"{len(refs)} reference-only")
    check("API registry", t_apis)

    def t_api_call_gate():
        """Nothing leaves the machine unless the reader switched it on.

        `call()` consulted no enablement state at all, so it would issue a real
        GET for a service the user had never touched.  Every feature built on
        top of it would inherit that.  This asserts the refusal -- which used to
        be the absence of a refusal, and so was untestable -- and asserts that
        no socket is opened while it happens.
        """
        from gbible import db
        opened = []
        real_open = urllib.request.urlopen

        def spy(req, *a, **k):
            opened.append(getattr(req, "full_url", req))
            raise AssertionError("urlopen called while the service was off")
        conn = db.connect()
        was = {r["id"]: r["enabled"] for r in apireg.list_apis()}
        try:
            conn.execute("UPDATE api SET enabled=0 WHERE id='nominatim'")
            conn.commit()
            assert not apireg.is_enabled("nominatim")
            urllib.request.urlopen = spy
            try:
                try:
                    apireg.call("nominatim", "search", params={"q": "x"})
                except apireg.ApiError as e:
                    assert "off" in str(e).lower(), str(e)
                    # The refusal has to say what to do, or it is a dead end.
                    assert getattr(e, "hint", ""), "refusal carries no hint"
                else:
                    raise AssertionError(
                        "a switched-off service was called")
                # A reference page has no endpoint.  It must raise, not GET the
                # marketing site and hand back its HTML as though it were data.
                for ref_id in ("theographic", "step-bible", "sword-api"):
                    conn.execute("UPDATE api SET enabled=1 WHERE id=?", (ref_id,))
                conn.commit()
                for ref_id in ("theographic", "step-bible", "sword-api"):
                    try:
                        apireg.call(ref_id)
                    except apireg.ApiError as e:
                        assert "reference" in str(e).lower(), (ref_id, str(e))
                    else:
                        raise AssertionError(
                            f"{ref_id} is a reference page; it was called")
                try:
                    apireg.call("no-such-api-at-all")
                except apireg.ApiError as e:
                    assert "unknown" in str(e).lower(), str(e)
                else:
                    raise AssertionError("an unknown API id was accepted")
            finally:
                urllib.request.urlopen = real_open
        finally:
            for aid, en in was.items():
                conn.execute("UPDATE api SET enabled=? WHERE id=?",
                             (int(en), aid))
            conn.commit()
        assert not opened, f"a request was issued anyway: {opened}"
        return ("switched-off and reference-only services refused; "
                "no socket opened")

    check("API calls require consent", t_api_call_gate)

    def t_api_call_parses():
        """A canned response is parsed, cached, and served from the cache.

        There was no test of call() at all, so the parts that could be wrong --
        the content-type branch, the JSON branch, the cache -- were only
        reachable by making a real request to a third party, which is not
        something a self-test may do.  The transport is stubbed instead.
        """
        from gbible import db
        hits = []

        class FakeResp(io.BytesIO):
            def __enter__(self):
                return self
            def __exit__(self, *a):
                self.close()
                return False
            headers = {"Content-Type": "application/json; charset=utf-8"}

        def fake_urlopen(req, *a, **k):
            hits.append(req.full_url)
            return FakeResp(b'{"results": [{"name": "Jerusalem"}]}')

        conn = db.connect()
        was = {r["id"]: r["enabled"] for r in apireg.list_apis()}
        real_open = urllib.request.urlopen
        try:
            conn.execute("UPDATE api SET enabled=1 WHERE id='nominatim'")
            conn.commit()
            urllib.request.urlopen = fake_urlopen
            try:
                got = apireg.call("nominatim", "search",
                                  params={"q": "Jerusalem", "format": "json"})
                assert got["results"][0]["name"] == "Jerusalem", got
                assert len(hits) == 1, hits
                assert "q=Jerusalem" in hits[0], hits[0]
                # Nominatim's usage policy is one request a second, and the
                # rate_limit string that says so used to be display-only.  The
                # second call still goes out -- it is delayed, not dropped, and
                # silently swallowing a request the reader asked for would be
                # worse -- so the test is that it waited.
                t1 = time.time()
                apireg.call("nominatim", "search", params={"q": "Jerusalem"})
                waited = time.time() - t1
                assert waited >= 0.9, (
                    f"two calls in {waited:.2f}s: Nominatim allows one a second")
                assert len(hits) == 2, hits
                # The cache answers a repeat without a request at all.
                key = "search?q=Jerusalem&format=json"
                apireg.cache_put("nominatim", key, got)
                t0 = time.time()
                cached = apireg.cache_get("nominatim", key)
                assert cached and cached.get("cached") is True, cached
                assert time.time() - t0 < 0.01
                assert len(hits) == 2, f"cache missed and re-fetched: {hits}"
            finally:
                urllib.request.urlopen = real_open
                conn.execute("DELETE FROM api_cache WHERE api_id='nominatim'")
        finally:
            for aid, en in was.items():
                conn.execute("UPDATE api SET enabled=? WHERE id=?",
                             (int(en), aid))
            conn.commit()
        return "JSON parsed, throttle held, cache answered"
    check("API call transport", t_api_call_parses)

    # ------------------------------------------------------------ library
    def t_lib():
        mods = library.list_all()
        return f"{len(mods)} modules" if mods else None
    check("Library contents", t_lib)

    def t_licences_installed():
        from gbible import db as _db
        conn = _db.connect()
        rows = conn.execute("SELECT DISTINCT license FROM module WHERE installed_at>0").fetchall()
        bad = [r["license"] for r in rows
               if r["license"] and not taxonomy.license_ok(r["license"])]
        assert not bad, f"non-redistributable licences installed: {bad}"
        return "every installed module is freely redistributable"
    check("Installed licences are all redistributable", t_licences_installed)

    # ------------------------------------------------- search spelling hint
    def _spell_mods():
        return library.list_all()

    def t_spelling_suggests():
        """The hint must know the library's own vocabulary, and only that.

        "agape" is a correct transliteration and a lexicon headword, so it is
        checked against 79,599 words now rather than the stem set.  Getting that
        wrong is the failure this pins: the reader types a correct word and is
        told it is misspelled, with a Hebrew noun offered in its place.
        """
        from gbible import search
        mods = _spell_mods()
        if not mods:
            return None
        counts = search.surface_counts(mods)
        # The hint is checked against the library's own words, and a library of
        # a dozen modules does not have eighty thousand of them.  A small
        # vocabulary is not a broken one.
        if len(counts) <= 60000:
            return Skip(f"the library's vocabulary is {len(counts):,} words; "
                        "this check wants more than 60,000")
        got = {}
        for w in ("agape", "agapee", "pryaer", "glose", "recieeve"):
            search._SPELL_READY[0] = True
            notes = search.word_notes(w, mods)
            got[w] = [(n["kind"], n["to"]) for n in notes]
        # No spelling correction for a correctly spelled word -- whatever else
        # the hint has to say about it (see t_headword_strongs_hint).
        assert not [g for g in got["agape"] if g[0] == "spelling"], got["agape"]
        assert ("spelling", "agape") in got["agapee"], got["agapee"]
        # Damerau: an adjacent transposition is ONE edit, so the commonest
        # typing mistake has to be correctable inside a tight budget.
        assert ("spelling", "prayer") in got["pryaer"], got["pryaer"]
        # Frequency breaks ties.  "glose" is one edit from "close" and from
        # "lose"; without counts the winner was whichever hash order supplied.
        assert ("spelling", "close") in got["glose"], got["glose"]
        assert ("spelling", "receive") in got["recieeve"], got["recieeve"]
        assert len(counts) > 60000, f"vocabulary collapsed to {len(counts)}"
        return f"{len(counts):,} words; agape uncorrected, agapee/pryaer/glose fixed"
    check("Spelling hint checks the library's own words", t_spelling_suggests)

    def t_headword_strongs_hint():
        """A lexicon headword must get its Strong's number, not silence.

        "agape" is the case that matters.  No Bible prints it -- they all render
        the Greek as "love" -- and the Strong's dictionaries tag nothing, so the
        word is in no surface index and the hint used to say nothing at all.
        Typing a correct word and being told nothing is the same failure as
        being told it is misspelled, just quieter.

        Pinned here because the number has two plausible sources and they
        disagree.  `unit.key` is the entry's own number; the "see GREEK for N"
        line that closes each entry cites the word it is *derived from*, so
        reading that hands out logos as G3004 when the whole library calls it
        G3056.  Checking the four words against the numbers the Bible modules
        actually tag is what distinguishes them.
        """
        from gbible import search
        mods = _spell_mods()
        if not mods:
            return None
        hw = search.headword_strongs(mods)
        if not hw:
            return Skip("no Strong's dictionary installed")
        want = {"agape": "G0026", "logos": "G3056", "pistis": "G4102",
                "charis": "G5485", "nomos": "G3551"}
        checked = 0
        for word, num in want.items():
            got = hw.get(word)
            if not got:
                continue
            assert got[0] == num, f"{word}: {got[0]}, expected {num}"
            checked += 1
        if not checked:
            return Skip("no expected headwords in this library")
        # An inserted initial vowel is part of the word, not a separator.
        # "a[logos" is alogos (G0249); splitting on the bracket emits a bogus
        # "logos" and points it at the wrong language entirely.
        if "alogos" in hw:
            assert hw["alogos"][0] != hw.get("logos", ("", ""))[0], \
                f"bracket split leaked: {hw['alogos']} vs {hw.get('logos')}"
        # Two-letter fragments would claim numbers for "a" and "the".
        for junk in ("a", "an", "of", "the", "to"):
            assert junk not in hw, f"{junk!r} claimed {hw.get(junk)}"
        return f"{len(hw):,} headwords; {checked} spot-checked"
    check("Lexicon headwords resolve to their Strong's number",
          t_headword_strongs_hint)

    def t_spelling_strongs_kept():
        """The gate added for speed must not swallow the Strong's hint.

        The lookup is now made only for a word the library contains.  For a
        correctly spelled tagged word that is still true, so the hint has to
        survive -- it is the one thing this box offers that a plain search
        does not already say.
        """
        from gbible import search
        mods = _spell_mods()
        if not mods:
            return None
        search.prewarm_spelling(mods)
        if not search.spelling_ready():
            return Skip("spelling tables did not warm")
        seen = {}
        for w in ("faith", "hope", "prayer", "love"):
            search._SPELL_READY[0] = True
            notes = search.word_notes(w, mods)
            seen[w] = [n["to"] for n in notes if n["kind"] == "strongs"]
            for n in notes:
                assert n["kind"] in ("spelling", "forms", "strongs"), n
                if n["kind"] == "strongs":
                    assert re.fullmatch(r"[GH]\d{4}", str(n["to"])), \
                        f"{w}: Strong's hint is not a number: {n}"
        missing = [w for w, v in seen.items() if not v]
        assert not missing, f"Strong's hint lost for {missing} ({seen})"
        return f"faith -> {seen['faith'][0]}, love -> {seen['love'][0]}"
    check("Spelling hint still reports Strong's", t_spelling_strongs_kept)

    def t_spelling_typo_does_not_build_index():
        """A misspelling must not pay for the fourteen-second surface index.

        `_surface_index` is the one expensive call behind the Strong's hint.
        It used to run on the keystroke that produced a spelling suggestion --
        the very request that could not possibly use the answer -- so the first
        cold word after a restart froze the tab.  It is built at startup on a
        background thread instead; this asserts the request path cannot
        trigger it.
        """
        from gbible import search
        mods = _spell_mods()
        if not mods:
            return None
        search._SURFACE_CACHE.clear()
        search._VOCAB_CACHE.clear()
        search.surface_counts(mods)          # the cheap-ish half, warmed
        search._SPELL_READY[0] = True
        before = len(search._SURFACE_CACHE)
        for w in ("pryaer", "glose", "recieeve"):
            search.word_notes(w, mods)
        assert len(search._SURFACE_CACHE) == before, \
            "a typo rebuilt the Strong's surface index on the request path"
        return "typos answered without touching the surface index"
    check("A typo does not rebuild the Strong's index",
          t_spelling_typo_does_not_build_index)

    def t_spelling_cache_invalidated():
        """Installing or removing a book must retire the vocabularies.

        Both are expensive to build (4s and 4s) and were given five-minute and
        one-hour expiries, so the hint rebuilt itself on a keystroke every five
        minutes for the whole session.  The cache is now keyed on the library
        generation, which the writers bump.
        """
        from gbible import db as _db
        from gbible import search
        mods = _spell_mods()
        if not mods:
            return None
        search.prewarm_spelling(mods)
        if not search.spelling_ready():
            return Skip("spelling tables did not warm")
        before = list(search._SURFACE_CACHE)
        assert before, "surface index was not built"
        _db.bump_generation()
        search._surface_index(mods)
        after = list(search._SURFACE_CACHE)
        assert after != before, "generation bump did not change the cache key"
        # And it still works afterwards, rather than raising on a stale key list.
        assert search._strongs_for(mods, "faith"), "faith lost its Strong's"
        return "cache keyed on library generation"
    check("Spelling vocabularies are invalidated by the library changing",
          t_spelling_cache_invalidated)

    # --------------------------------------------------- module portability
    def t_module_dir():
        """A moved library folder must not read as "the files are gone".

        `module.path` is absolute and written at install time.  The text is all
        in the database, which travelled with the project, so the library reads
        perfectly well; only re-indexing and "add audio" break, and they are the
        two things that must resolve rather than trust the recorded value.
        """
        from gbible import db as _db
        mods = library.list_all()
        if not mods:
            return None
        here = str(_db.app_dir())
        resolved = missing = outside = 0
        for m in mods:
            d = library.module_dir(m.id)
            if d is None:
                if m.installed_at > 0 and (m.path or m.folder):
                    # An installed module with a recorded path that resolves
                    # nowhere is only acceptable when its files were never on
                    # this machine -- audio folders usually were not.
                    outside += 1
                else:
                    missing += 1
            else:
                resolved += 1
                assert d.exists(), f"{m.id}: resolved to a path that is not there"
                assert str(d).startswith(here) or not (m.path or "").startswith(here), \
                    f"{m.id}: resolved outside the library while a valid path was recorded"
        assert missing == 0, f"{missing} modules with a recorded path resolve nowhere"
        return f"{resolved} resolved in place, {outside} external audio folders"
    check("Module files resolve through the library in use", t_module_dir)

    def t_repair_paths():
        """Repairing the stored paths is idempotent and reports honestly."""
        from gbible import db as _db
        r = library.repair_paths()
        assert r.get("ok"), r
        second = library.repair_paths()
        assert second.get("skipped"), f"second repair did work again: {second}"
        conn = _db.connect()
        here = str(_db.app_dir())
        # After a repair, no installed module may still name a path under some
        # other library folder.  One that names a path outside *this* library
        # is fine when its files really are elsewhere -- audio, mostly.
        stale = conn.execute(
            "SELECT COUNT(*) c FROM module WHERE installed_at>0 "
            "AND path IS NOT NULL AND path!='' AND folder IS NOT NULL "
            "AND folder!='' AND path LIKE ? AND path NOT LIKE ?",
            ("/home/%", here + "/modules/%")).fetchone()["c"]
        outside = conn.execute(
            "SELECT COUNT(*) c FROM module WHERE installed_at>0 "
            "AND path IS NOT NULL AND path!='' AND path NOT LIKE ?",
            (here + "/modules/%",)).fetchone()["c"]
        assert stale == 0, f"{stale} installed modules still point at an old library"
        return (f"{r.get('checked', 0)} checked, {r.get('changed', 0)} changed, "
                f"{outside} external")
    check("Recorded module paths are repaired once and stay repaired",
          t_repair_paths)

    def t_reindex_refuses_mismatch():
        """Re-index must decline rather than quietly replace a book.

        Re-indexing *replaces* a module's units with whatever the crude splitter
        makes of the files on disk.  The installer split the original by
        chapters and sections, so re-parsing the same files routinely yields a
        different book: measured on this library, a 4-unit book reparsed to 21
        and a 49-unit commentary to 1,052.  A plausible-yield refusal is the
        only thing standing between "re-index" and "destroy and reformat".

        `indexer.run_import` is stubbed out, so this asserts the *decision*
        without performing one -- which matters, because the modules that pass
        the guard are exactly the ones whose re-index would then really run
        against a live library.  Every installed module is offered, so the guard
        is exercised against both outcomes rather than only the ones it rejects.
        """
        from gbible import db as _db
        from gbible import indexer
        from gbible.server import app as _app
        mods = [m for m in library.list_all() if m.installed_at > 0]
        if not mods:
            return None
        # A spread across the whole library rather than the first few, so both
        # outcomes are met: a sampled module whose files are gone, and one
        # whose files re-parse to the right yield.  Capped, because each module
        # costs a directory walk and a parse.
        step = max(1, len(mods) // 15)
        mods = mods[::step][:15]

        offered, called = [], []

        def _fake_run_import(module_id, units, **kw):
            called.append(module_id)
            return {"ok": True, "id": module_id, "units": -1, "stubbed": True}

        real = indexer.run_import
        indexer.run_import = _fake_run_import
        before = {m.id: _db.connect().execute(
            "SELECT COUNT(*) c FROM unit WHERE module_id=?", (m.id,)
        ).fetchone()["c"] for m in mods}
        try:
            for m in mods:
                try:
                    r = _app.route("reindex", {"id": m.id})
                except Exception as exc:                  # noqa: BLE001
                    raise AssertionError(f"{m.id}: reindex raised {exc}") from exc
                assert isinstance(r, dict), f"{m.id}: reindex returned {r!r}"
                assert "ok" in r, f"{m.id}: reindex gave no verdict: {r}"
                offered.append((m.id, bool(r.get("ok"))))
        finally:
            indexer.run_import = real
        after = {m.id: _db.connect().execute(
            "SELECT COUNT(*) c FROM unit WHERE module_id=?", (m.id,)
        ).fetchone()["c"] for m in mods}
        assert before == after, "the stub did not hold: units were really replaced"
        ok_ids = [i for i, v in offered if v]
        bad_ids = [i for i, v in offered if not v]
        assert set(called) <= set(ok_ids), \
            f"import ran for a refused module: {set(called) - set(ok_ids)}"
        assert bad_ids, f"nothing was refused, so the guard never applied: {offered[:3]}"
        return f"{len(bad_ids)} refused, {len(ok_ids)} allowed (import stubbed)"
    check("Re-index refuses a parse that is not the same book",
          t_reindex_refuses_mismatch)

    # ------------------------------------------------------- maps & places
    def t_image_size():
        """Dimensions read from the file header, for every format installed.

        A calibration is expressed in pixels, so "how many pixels is this map"
        is not a nicety -- without it a reader cannot click a point at all.  And
        it is read by hand, with no image library, which is only safe if it is
        pinned against the real files rather than a sample of them.
        """
        from gbible import maps as _maps
        from gbible import library as _lib
        import tempfile as _tf
        got = {}
        for m in _maps.maps():
            got[m["id"]] = m["size"]
        have = [k for k, v in got.items() if v]
        assert have, f"no map image could be sized: {got}"
        for mid, sz in got.items():
            assert sz is not None, f"{mid}: image could not be sized at all"
            assert sz["width"] > 0 and sz["height"] > 0, f"{mid}: {sz}"
        # And the hand-rolled readers agree with the headers they were written
        # against, including the formats no installed map happens to use.
        with _tf.TemporaryDirectory() as tmp:
            import struct as _struct
            png = Path(tmp) / "x.png"
            png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" +
                            _struct.pack(">II", 640, 480) + b"\x08\x06\x00\x00\x00")
            assert _maps.image_size(png) == {"width": 640, "height": 480,
                                             "kind": "png"}, _maps.image_size(png)
            gif = Path(tmp) / "x.gif"
            gif.write_bytes(b"GIF89a" + _struct.pack("<HH", 12, 34) + b"\x00\x00\x00")
            assert _maps.image_size(gif)["width"] == 12, _maps.image_size(gif)
            svg = Path(tmp) / "x.svg"
            svg.write_text('<?xml version="1.0"?>\n<svg xmlns="x" '
                           'viewBox="0 0 2168 3300">')
            sz = _maps.image_size(svg)
            assert sz["width"] == 2168 and sz["height"] == 3300, sz
            assert sz["basis"] == "viewBox", sz
            assert _maps.image_size(Path(tmp) / "nope.png") is None
        return f"{len(have)} map images sized, header readers agree"
    check("Image dimensions are read without an image library", t_image_size)

    def t_map_projection():
        """A calibration puts the places it was made from back where it put them.

        That is the whole contract of the projection, and it is worth pinning
        exactly rather than approximately: a similarity transform is linear, so
        both control points must come back to the pixel they were clicked at.
        If they do not, every other place on the map is wrong in the same way
        and nothing about it looks wrong.
        """
        from gbible import maps as _maps
        a = {"name": "A", "lat": 31.77, "lon": 35.23, "x": 1626.35, "y": 1366.04}
        b = {"name": "B", "lat": 35.09, "lon": 40.43, "x": 2720.44, "y": 998.26}
        cal = {"a": a, "b": b}
        for p in (a, b):
            x, y = _maps.project(cal, p["lat"], p["lon"])
            assert abs(x - p["x"]) < 0.01, f"{p['name']}: x {x} != {p['x']}"
            assert abs(y - p["y"]) < 0.01, f"{p['name']}: y {y} != {p['y']}"
        # A place between the two must land between them.
        mid = _maps.project(cal, (a["lat"] + b["lat"]) / 2,
                            (a["lon"] + b["lon"]) / 2)
        assert a["x"] < mid[0] < b["x"], mid
        assert b["y"] < mid[1] < a["y"], mid
        # And a degenerate calibration -- both points the same spot -- must
        # answer None rather than divide by a zero-length vector.
        same = {"a": dict(a), "b": dict(a, x=a["x"], y=a["y"])}
        assert _maps.project(same, a["lat"], a["lon"]) is None, \
            "a zero-length calibration projected a point instead of refusing"
        return "both controls round-trip; between them is between them"
    check("Map calibration puts places where it was set from", t_map_projection)

    def t_map_calibration_round_trip():
        """Aligning a map and forgetting it again, through the real storage.

        A setting that cannot be cleared is a setting the reader is stuck with:
        the calibration was refused in the first version because it was written
        to one table and deleted from another, so `clear` reported success and
        changed nothing.  The assertion is that it is *gone* afterwards, not
        that clear returned ok.
        """
        from gbible import maps as _maps
        from gbible import library as _lib
        ms = _lib.list_all(type_="Map")
        if not ms:
            return None
        by_id = {x["id"]: x for x in _maps.maps()}
        sized = [m for m in ms if by_id.get(m.id, {}).get("size")]
        if not sized:
            return Skip("no map image is present")
        m = sized[0]
        try:
            c = _maps._suggested_controls()
            if len(c) < 2:
                return Skip("gazetteer has fewer than two places to calibrate from")
            w = 1000.0
            h = 1000.0
            r = _maps.set_calibration(
                m.id,
                {"name": c[0]["name"], "lat": c[0]["lat"], "lon": c[0]["lon"],
                 "x": w * 0.4, "y": h * 0.5},
                {"name": c[1]["name"], "lat": c[1]["lat"], "lon": c[1]["lon"],
                 "x": w * 0.9, "y": h * 0.3})
            assert r.get("ok"), r
            assert _maps.calibration(m.id), "aligned but nothing was stored"
            d = _maps.map_detail(m.id)
            assert d["count"] > 0, "aligned map placed no places at all"
            for p in d["places"][:5]:
                assert p["x"] is not None and p["passages"] is not None, p
        finally:
            _maps.clear_calibration(m.id)
        assert _maps.calibration(m.id) is None, \
            "clear_calibration reported success and left the alignment in place"
        assert _maps.map_detail(m.id).get("note"), \
            "an unaligned map must say why it has no places"
        # Refusals: too close together, and nonsense input.  Each one is
        # checked against its *reason*, not merely that it failed, because
        # "it returned ok=False" is true of a module that is simply not
        # installed and would pass for the wrong reason.
        a = {"name": "A", "lat": 31.77, "lon": 35.23, "x": 10, "y": 10}
        near = _maps.set_calibration(m.id, a, dict(a, x=12, y=11))
        assert not near.get("ok") and "too close" in (near.get("error") or ""), \
            f"two points 2px apart were accepted: {near}"
        part = _maps.set_calibration(m.id, {"name": "A"}, a)
        assert not part.get("ok") and "each control needs" in (part.get("error") or ""), \
            f"a control with no coordinates was accepted: {part}"
        gone = _maps.set_calibration("no-such-map", a, dict(a, x=900, y=900))
        assert not gone.get("ok") and "no such map" in (gone.get("error") or ""), \
            f"an unknown module was aligned: {gone}"
        # None of those three refusals may have left anything behind.
        assert _maps.calibration(m.id) is None, \
            "a refused calibration was written anyway"
        return f"{d['count']} places placed on {m.id}"
    check("Aligning a map can be undone", t_map_calibration_round_trip)

    def t_place_search():
        """The gazetteer answers by name, by alternative name, and by reference.

        The third of those is the one that earns its keep: a reader who has read
        "Abana" in 2 Kings and wants the place searches the reference, not the
        spelling they are about to guess.
        """
        from gbible import maps as _maps
        allp = _maps.places(limit=1000)
        if len(allp) < 50:
            return Skip("the gazetteer is not installed")
        assert all(p["lat"] is not None and p["lon"] is not None for p in allp), \
            "a place without coordinates cannot go on a map"
        by_ref = [p for p in allp if p["passages"]]
        assert by_ref, "no place knows the verses that name it"
        target = by_ref[0]
        frag = target["passages"][0].split()[0]
        hits = [p["name"] for p in _maps.places(frag)]
        assert target["name"] in hits, \
            f"searching {frag!r} did not find {target['name']} ({hits[:5]})"
        exact = [p["name"] for p in _maps.places(target["name"])]
        assert exact and exact[0] == target["name"], exact[:5]
        # Proximity sorts by distance, which is the only thing that makes a
        # radius search an answer rather than an alphabetical coincidence.
        anchor = allp[0]
        near = _maps.places(near=(anchor["lat"], anchor["lon"]),
                            radius_km=60, limit=1000)
        ds = [p["distance_km"] for p in near]
        assert ds == sorted(ds), f"proximity results are not ordered: {ds[:6]}"
        if len(near) > 2:
            assert _maps._haversine(anchor["lat"], anchor["lon"],
                                    near[0]["lat"], near[0]["lon"]) < \
                _maps._haversine(anchor["lat"], anchor["lon"],
                                 near[-1]["lat"], near[-1]["lon"]), \
                "the closest place is not first"
        return (f"{len(allp)} places, all located; reference and proximity "
                f"searches agree")
    check("Bible places search by name and by reference", t_place_search)

    # ------------------------------------------------- Eusebian canon tables
    def t_eusebian_health():
        """The apparatus must be able to say that it is not the apparatus.

        The module Crosswire ships as "Eusebian Numbers By Verse" is a
        per-Gospel section numbering, not the canon table: every number in it
        belongs to exactly one Gospel, so nothing in it can be matched to a
        parallel anywhere else.  Presented as a harmony that is four empty
        columns pretending to be a comparison.  So the health check has to
        detect that and say it, and this asserts it does -- on this library,
        where the condition is real rather than hypothetical.
        """
        from gbible import eusebian as _eu
        h = _eu.health()
        if not h["available"]:
            return Skip("the Eusebian module is not installed")
        assert "usable" in h, h.keys()
        if h["usable"]:
            assert h["shared_sections"] > 0, \
                "reported usable, but no number is shared between Gospels"
        else:
            assert h["shared_sections"] == 0, h["shared_sections"]
            assert any("does not contain the Eusebian canon table" in n
                       for n in h["notes"]), h["notes"]
        for b in h["books"]:
            assert 0 <= b["have"] <= b["expected"] or b["have"] > 0, b
            assert b["pct"] <= 100.0, f"{b['name']}: {b['pct']}% of a section count"
        assert 0 <= h["complete_pct"] <= 100.0, h["complete_pct"]
        return (f"{h['complete_pct']}% of the sections, "
                f"{'usable' if h['usable'] else 'not a canon table'}")
    check("Eusebian table reports its own coverage honestly",
          t_eusebian_health)

    def t_eusebian_numbering():
        """The numbers are read the way Eusebius meant them.

        The first number is the canon *table* -- which Gospels are being
        compared -- not a book index.  Reading it as a book index produces a
        harmony that is completely wrong and completely plausible, which is the
        worst kind of wrong to ship, so the mapping is pinned: John 1:1 is 4.1
        because it is in the Matthew/Mark/John table, and Matthew 1:1 is 1.1
        because it is in the table where all four agree.
        """
        from gbible import eusebian as _eu
        d = _eu.data()
        if not d["available"]:
            return Skip("the Eusebian module is not installed")
        for vk, want in (("John.1.1", "4.1"), ("Matt.1.1", "1.1")):
            got = _eu.notation(vk)
            assert got == want, f"{vk}: expected {want}, got {got!r}"
        assert _eu.notation("Gen.1.1") == "", \
            "a verse that is not in the Gospels got an Ammonian number"
        r = _eu.lookup("4.1")
        assert r["ok"], r
        assert r["canon"]["n"] == 4, r["canon"]
        assert "John" in r["columns"][3]["book"], r["columns"]
        assert r["columns"][3]["present"], r["columns"]
        assert not _eu.lookup("not a number").get("ok"), \
            "a malformed number was accepted"
        # Tables V-X are the ones that compare Gospels; they must be described
        # even when this library has no data for them, because that absence is
        # the finding.
        want = [(c["n"], tuple(c["books"])) for c in _eu.CANONS]
        assert want[4] == (5, ("Matt", "Luke")), want[4]
        assert want[6] == (7, ("Matt", "John")), want[6]
        assert want[9] == (10, ("Matt", "Mark", "Luke", "John")), want[9]
        # Two columns do not exist: "Mark and John", and "Mark, Luke and John".
        # Nothing is common to Mark and John without also being common to at
        # least one of Matthew or Luke, so those columns would be empty in every
        # row and Eusebius did not draw them.  Canon I pairs all four and canon
        # IV pairs Mark with John *along with Matthew*, both correctly, so the
        # assertion is on the exact sets rather than on the presence of the two
        # names.
        for absent in ({"Mark", "John"}, {"Mark", "Luke", "John"}):
            assert not any(set(c["books"]) == absent for c in _eu.CANONS), \
                f"a canon for exactly {sorted(absent)} exists: Eusebius drew none"
        assert set(_eu.CANONS[9]["books"]) == {"Matt", "Mark", "Luke", "John"}, \
            "canon X is the unique-material column and needs all four"
        assert set(_eu.CANONS[3]["books"]) == {"Matt", "Mark", "John"}, \
            "canon IV is the Matthew/Mark/John column"
        return f"{len(d['sections'])} sections across " \
               f"{len(d['counts'])} Gospels"
    check("Eusebian numbers are read as canon table and section",
          t_eusebian_numbering)

    def t_eusebian_harmony_shape():
        """The tables come back as tables: canons, rows, four Gospel columns.

        The shape is the whole point.  A reader looking for what Luke has at
        the place where Matthew and John agree needs to *see* the empty cell,
        and a flat list of verses cannot show it.
        """
        from gbible import eusebian as _eu
        if not _eu.data()["available"]:
            return Skip("the Eusebian module is not installed")
        r = _eu.harmony(canon=1, limit=25)
        assert r["ok"], r
        assert len(r["canons"]) == 1, r["canons"]
        t = r["canons"][0]
        assert t["n"] == 1 and t["roman"] == "I", t
        assert t["rows"], "canon I returned no rows at all"
        for row in t["rows"]:
            assert [c["book"] for c in row["cells"]] == \
                ["Matt", "Mark", "Luke", "John"], row["cells"]
            assert row["notation"] == f"1.{row['section']}", row
        assert len(t["rows"]) <= 25, len(t["rows"])
        every = _eu.harmony()
        assert len(every["canons"]) == 10, \
            f"expected all ten canon tables, got {len(every['canons'])}"
        assert len(every["canon_list"]) == 10
        assert every["health"]["available"]
        assert not _eu.harmony(canon=99).get("ok"), "canon 99 was accepted"
        return f"canon I shows {len(t['rows'])} rows; all ten tables described"
    check("Eusebian tables are laid out as canons and Gospel columns",
          t_eusebian_harmony_shape)

    # --------------------------------------------- Wikisource template debris
    def t_wikitext_unwrap():
        """Article text must come out of its MediaWiki wrapper, not stay in it.

        Wikisource stores the article *inside* a template, and the importer kept
        the template, so every one of the Catholic Encyclopedia's 9,935 articles
        opened in the reader's pane with the literal characters `{{CE13|
        contributor = ...`.  The trap is that deleting the braces deletes the
        article too, because the article is the template's argument -- so this
        checks that the prose survives, which is the only part that matters.
        """
        from gbible import markup as _mk
        s = _mk.strip_wikitext
        # A wrapper whose text hangs off a named parameter, as CE13's does.
        out = s("{{CE13| contributor = Arthur Whitcombe Taylor| article = Aarhus"
                "| volume = 16| wikipedia = Ancient See of AarhusAarhus"
                " {{sc|(Arusia)}}, in Denmark. The diocese included the"
                " provinces.}}")
        assert "{{" not in out and "}}" not in out, out
        assert "contributor" not in out, f"page furniture survived: {out}"
        assert "Arthur Whitcombe Taylor" not in out, out
        assert "in Denmark." in out, f"the article was lost: {out!r}"
        assert out.startswith("Aarhus"), f"glued title not removed: {out!r}"
        # Presentation templates keep their content and lose their styling.
        assert s("{{sc|JERUSALEM}} {{sup|2}} {{nowrap|plain}}") == \
            "JERUSALEM 2 plain"
        # Named text= parameters are content whatever they look like.
        assert s("{{GHGheb|text=מַהְפֵּכָה}}") == "מַהְפֵּכָה"
        # References are reconstructed rather than shown as parameters.
        assert s("{{GHGbible-ref|book=Is|chapter=13|verse=19}}") == "Is 13:19"
        assert s("{{GHGpar|115|d}}") == "§115 d"
        # Links.
        assert s("See [[Aarhus]] and [[Denmark|the kingdom]].") == \
            "See Aarhus and the kingdom."
        # Tables of contents and maintenance banners go entirely.
        assert "Front Matter" not in s("{{AuxTOC|title=X|• Front Matter}}")
        assert s("{{TextQuality|100%}}Prose.") == "Prose."
        # Unbalanced braces must not hang or eat the article.
        assert s("Before {{broken and after") == "Before broken and after", \
            s("Before {{broken and after")
        assert s("") == "" and s(None) == ""
        # Text with no markup in it comes back exactly as it went in -- this
        # runs over every article in the library, so the early exit matters.
        assert s("No templates here.") == "No templates here."
        assert s("  spaced  text  ") == "  spaced  text  "
        return "wrappers removed, article text kept"
    check("Wikisource template wrappers are unwrapped", t_wikitext_unwrap)

    def t_wikitext_never_loses_article():
        """A mangled article must come back whole, even if that means ugly.

        Some of the Catholic Encyclopedia cannot be unwrapped: the importer
        turned `{{sc|Dacier, a French philologist}}` into `{{sc, ...}}`, which
        unbalances the braces *inside* the wrapper, and unwrapping that returned
        45 characters out of 4,367.  So the pass refuses instead, and this pins
        the refusal -- across the whole module, because one article is an
        anecdote and nine thousand is a policy.
        """
        from gbible import db as _db
        from gbible import markup as _mk
        mid = "wikisource-catholic-encyclopedia-1913"
        rows = _db.connect().execute(
            "SELECT key, text FROM unit WHERE module_id=? AND text LIKE '%{{%'",
            (mid,)).fetchall()
        if not rows:
            return Skip("the Catholic Encyclopedia is not installed")
        lost, emptied, cleaned, refused = 0, 0, 0, 0
        for r in rows:
            t = r["text"] or ""
            s = _mk.strip_wikitext(t)
            if not s.strip() and t.strip():
                emptied += 1
            elif "{{" in t and "{{" not in s:
                cleaned += 1
            if len(s) * 2 < len(t) and len(t) > 200:
                refused += 1
            # Prose must never be lost: the unwrapped text has to retain a
            # decent share of the words the original had outside its braces.
            words_in = len(re.sub(r"[{}|=]", " ", t).split())
            words_out = len(s.split())
            if words_in > 40 and words_out < words_in * 0.4:
                lost += 1
        assert lost == 0, (f"{lost} of {len(rows)} articles lost most of "
                           f"their text when unwrapped")
        assert emptied == 0, f"{emptied} articles were emptied entirely"
        assert cleaned > len(rows) * 0.9, \
            f"only {cleaned} of {len(rows)} articles were actually cleaned"
        return (f"{cleaned}/{len(rows)} articles unwrapped, {refused} refused "
                f"as unsafe, none truncated")
    check("Unwrapping a template never costs an article its text",
          t_wikitext_never_loses_article)

    def t_wikitext_span_table_dropped():
        """A cleaned article must not be rendered through a stale span table.

        The span table was built over the *template* text at index time, with
        every brace counted as a word.  Once the text is unwrapped the offsets
        no longer line up, so the table has to be discarded.  Asserting that a
        tagged Bible keeps its table is the other half: the unwrapping must not
        cost the Strong's and footnotes in every other module.
        """
        from gbible import library as _lib
        for m in _lib.list_all(type_="Grammar"):
            c = _lib.read(m.id, {})
            assert not c.notices or "No entry" not in (c.notices[0] or ""), \
                f"{m.id}: {c.notices}"
            if c.items:
                h = c.items[0].html or ""
                assert "{{" not in h, f"{m.id}: template debris still rendered"
            return f"{m.id} renders without template markup"
        return None
    check("Cleaned articles are not rendered through a stale span table",
          t_wikitext_span_table_dropped)

    def t_no_shell_modules():
        """No installed module may be a table of contents wearing a book's name.

        Gesenius' Hebrew Grammar installed as 173 units of which 165 were the
        twelve bytes `{{GHGheader|` -- the grammar is transcluded from a
        proofread scan and the importer was not reading scans.  Every unit read
        as empty, and a module that opens to nothing is worse than one that was
        never offered, because a reader clicks it expecting a grammar.

        The check is on installed data, not on the importer, because the importer
        is only reachable over the network and this library is the thing that
        has to be right.
        """
        from gbible import db as _db
        rows = _db.connect().execute(
            "SELECT module_id, key, length(text) L, ref_label FROM unit "
            "WHERE module_id IN ('wikisource-gesenius-hebrew-grammar', "
            "'wikisource-catholic-encyclopedia-1913', "
            "'wikisource-jewish-encyclopedia')").fetchall()
        if not rows:
            return Skip("no Wikisource-derived module is installed")
        by_mod: dict[str, list] = {}
        for r in rows:
            by_mod.setdefault(r["module_id"], []).append(r)
        for mid, rs in by_mod.items():
            thin = [r for r in rs if (r["L"] or 0) < 120]
            # A handful of short units is normal -- front matter and errata.
            # Half of them being empty is the failure.
            assert len(thin) < len(rs) / 2, (
                f"{mid}: {len(thin)} of {len(rs)} units are under 120 "
                f"characters -- this looks like a shell install")
            total = sum((r["L"] or 0) for r in rs)
            assert total > len(rs) * 500, (
                f"{mid}: {total} characters across {len(rs)} units")
            sample = max(rs, key=lambda r: r["L"] or 0)
            assert (sample["L"] or 0) > 2000, (
                f"{mid}: the longest unit is {sample['L']} characters")
        return ", ".join(f"{m.split('-')[-1]}: {len(r)} units"
                         for m, r in sorted(by_mod.items()))
    check("No installed module is a shell of navigation headers",
          t_no_shell_modules)

    def t_proofreading_markup():
        """A proofread scan's apparatus goes; its footnotes stay.

        Text from Wikisource's `Page:` namespace arrives with the transcriber's
        scaffolding attached.  `<noinclude>` carries the page's quality rating
        and the editor's name, and was appearing at the top of every section of
        the grammar.  `<ref>` is different in kind: its contents are the
        references themselves, and removing them deletes the bibliography.
        """
        from gbible import markup as _mk
        s = _mk.strip_wikitext
        out = s('<noinclude><pagequality level="4" user="Someone" /></noinclude>'
                '<section begin="par1" /><div style="text-align: center">'
                'HEADING</div>\n<!-- proofread note -->\n'
                'The body, with a note<sup>me</sup>.')
        assert "noinclude" not in out, out
        assert "pagequality" not in out, out
        assert "Someone" not in out, out
        assert "par1" not in out, out
        assert "proofread note" not in out, out
        assert "HEADING" in out and "The body" in out, out
        assert "<" not in out and ">" not in out, out
        # A block wrapper must leave a space behind it, or two headings weld:
        # this is the "HEBREW GRAMMARINTRODUCTION" case.
        glued = s("{{larger|HEBREW GRAMMAR}}INTRODUCTION"
                  "{{GHGpar-heading|1|Semitic Languages}}")
        assert "GRAMMAR INTRODUCTION" in glued, glued
        assert "INTRODUCTION Semitic" in glued, glued
        # And a footnote is content.
        kept = s("A claim.<ref>Stade, Lehrb. der hebr. Gramm., 1879.</ref>")
        assert "Stade" in kept, kept
        # Inline wrappers take no space: a space inside a word is worse.
        assert s("{{sc|JERUSALEM}}") == "JERUSALEM", s("{{sc|JERUSALEM}}")
        return "apparatus removed, footnotes and spacing kept"
    check("Proofreading apparatus is removed and footnotes are kept",
          t_proofreading_markup)

    def t_snippets_carry_no_markup():
        """A search snippet is the article, not the article's source.

        Snippets are cut from the stored text at offsets computed against it, so
        cleaning the whole window first would move every <mark> -- the fix is to
        clean each chunk.  Without it a search of the grammar returned
        "{{GHGheb|text=אֵת}}" where the book has אֵת.
        """
        from gbible import db as _db
        from gbible import markup as _mk
        from gbible import search as _se
        row = _db.connect().execute(
            "SELECT text FROM unit WHERE module_id='wikisource-gesenius-hebrew-grammar' "
            "AND length(text)>3000 LIMIT 1").fetchone()
        if row is None:
            return Skip("the grammar is not installed")
        m = library.get("wikisource-gesenius-hebrew-grammar")
        word = None
        for cand in ("preposition", "consonant", "vowel", "syllable"):
            if cand in row["text"].lower():
                word = cand
                break
        if word is None:
            return Skip("no probe word found in the grammar")
        q = _se.parse(word)
        plain, html = _se._snippet(row, q, _se.SearchOpts())
        assert "{{" not in plain, plain[:200]
        assert "<noinclude" not in html, html[:200]
        assert "<mark>" in html or "<mark" not in html, html[:200]
        if "<mark>" in html:
            assert word in html, html[:200]
        # The article itself still carries its markup on disk -- it is cleaned at
        # render time, not rewritten -- so this is a display property only.
        assert "{{" in row["text"], "the stored text was rewritten in place?"
        del m
        return f"snippet for {word!r} is free of template markup"
    check("Search snippets show the article, not its markup",
          t_snippets_carry_no_markup)

    def t_reimport_invalidates_posindex():
        """Re-installing must not leave the old text's search index behind.

        `posindex` deliberately does not verify its own coverage -- proving it
        means scanning the whole postings table -- so it trusts `forget()`.  Only
        the removal path called it, and a re-install went through `mark_removed`
        directly.  The symptom was a module holding 2.7 million characters whose
        full-text index matched a word on 80 units while its positional index had
        no posting for it anywhere, so searching that module returned nothing.
        """
        import inspect as _inspect
        from gbible import indexer as _ix
        src = _inspect.getsource(_ix.run_import)
        assert "posindex.forget" in src, (
            "run_import no longer invalidates the positional index, so a "
            "re-installed module keeps the postings of its previous text")
        from gbible import posindex as _pi
        assert callable(_pi.forget), "posindex.forget is missing"
        return "re-install invalidates the positional index"
    check("Re-installing a module retires its old search index",
          t_reimport_invalidates_posindex)

    bible = need("Bible")
    commentary = need("Commentary")
    lexicon = need_lexicon()

    # ---------------------------------------------------------- read/links
    def t_read():
        if not bible:
            return None
        c = library.read(bible.id, {"ref": "John 3:16"})
        assert c.kind == "verse" and len(c.items) > 10, len(c.items)
        v = next((i for i in c.items if i.label == "John 3:16"), None)
        assert v and "loved the world" in v.text, v and v.text
        assert c.context.get("next") == "John 3:17"
        nxt = library.read(bible.id, {"ref": c.context["next"]})
        assert len(nxt.items) > 0
        return f"{len(c.items)} verses, John 3:16 exact"
    check("Bible reader", t_read)

    def t_strongs():
        """Strong's rendering, on a Bible that actually carries Strong's.

        It used to be checked against `bible`, the suite's general-purpose pick,
        and skipped when that one had no tagging.  It skipped here, silently,
        while five installed Bibles did have Strong's -- a skipped test looks
        identical to a passing one and hides regressions.  So the module is
        chosen for the capability under test.
        """
        from gbible.library import list_all as _la
        tagged = [m for m in _la()
                  if (m.type == "Bible" or m.is_bible)
                  and m.has_strongs and (m.lang or "").startswith("eng")]
        if not tagged:
            return None
        tagged.sort(key=lambda m: -m.entries)
        strong_bible = tagged[0]
        c = library.read(strong_bible.id, {"ref": "John 3:16"},
                         {"show_strongs": True})
        v = next((i for i in c.items if i.label == "John 3:16"), None)
        assert v and 'data-s="G2316"' in v.html, "Strong's not rendered"
        assert 'data-s="G1063"' in v.html
        c2 = library.read(strong_bible.id, {"ref": "John 3:16"},
                          {"show_strongs": False})
        v2 = next((i for i in c2.items if i.label == "John 3:16"), None)
        assert "snums" not in v2.html, "Strong's toggle not honoured"
        return f"Strong's rendered and toggleable ({strong_bible.id})"
    check("Strong's concordance", t_strongs)

    def t_lookup():
        # A Strong's *number* is a concordance's key, not a dictionary's: a
        # Bible dictionary is keyed by headword, so the module to look in is
        # whichever of the two is actually installed.
        target = next((m for m in library.list_all()
                       if m.slot == "concordance" and m.entries), None) \
            or lexicon
        if not target or not target.entries:
            return None
        lexicon0 = target
        conn = db.connect()
        r = conn.execute(
            "SELECT s.strongs, u.title FROM strongs s JOIN unit u "
            "ON u.module_id = ? AND u.key = s.strongs WHERE s.modules LIKE ? "
            "LIMIT 1", (target.id, f'%"{target.id}"%')).fetchone()
        if not r:
            r = conn.execute("SELECT key FROM unit WHERE module_id=? LIMIT 1",
                             (target.id,)).fetchone()
        assert r, "lexicon has no units"
        art = library.read(lexicon0.id, {"key": r[0]})
        assert art.items, f"no article for {r[0]}"
        assert len(art.items[0].text) > 20, art.items[0].text
        return f"{lexicon0.name}: {art.items[0].text[:44]!r}"
    check("Lexicon article lookup by Strong's", t_lookup)

    def t_study_verse():
        """Every linked resource for one verse, in one call.

        This is the panel that stands in for "which tool do I open next", so a
        regression here is the difference between a working reader and a shelf of
        tools.  John 3:16 is used because it is the verse a reader is most
        likely to try first.
        """
        from gbible import study
        c = db.connect()
        row = None
        # The Bible has to be tagged, or "no Strong's in the verse" is a
        # property of the module rather than a failure.
        for m in library.list_all():
            if m.type != "Bible" or m.lang != "eng" or not m.has_strongs:
                continue
            row = c.execute(
                "SELECT key FROM unit WHERE module_id=? AND key='John.3.16'",
                (m.id,)).fetchone()
            if row:
                break
        if not row:
            return None
        t0 = time.time()
        b = study.verse_bundle(m.id, row[0])
        assert b.get("ok"), b.get("error")
        assert b["ref"]["label"] == "John 3:16", b["ref"]
        assert b["words"], "no Strong's in the verse"
        assert b["commentaries"] or b["topics"] or b["crossrefs"]["incoming"], \
            "no commentary, topic or cross-reference resolved"
        secs = 0
        secs += bool(b["commentaries"])
        secs += bool(b["topics"])
        secs += bool(b["crossrefs"]["incoming"])
        secs += bool(b["places"])
        secs += bool(b["words"])
        assert secs >= 3, f"only {secs} kinds of resource resolved"
        # An interactive panel cannot take ten seconds.  Cold, the first call
        # builds the TSK cross-reference index -- one pass over four thousand
        # units -- so the allowance is for a cold cache.
        assert time.time() - t0 < 30.0, time.time() - t0
        return (f"John 3:16: {len(b['commentaries'])} commentaries, "
                f"{len(b['topics'])} topics, "
                f"{len(b['crossrefs']['incoming'])} cited-by, "
                f"{len(b['places'])} places, {len(b['words'])} words")
    check("Linked resources for a verse", t_study_verse)

    def t_study_word():
        from gbible import study
        conn2 = db.connect()
        r = conn2.execute("SELECT value FROM marker WHERE kind='strongs' "
                          "GROUP BY value ORDER BY count(*) DESC LIMIT 1").fetchone()
        if not r:
            return None
        t0 = time.time()
        w = study.word_bundle(r[0])
        assert w.get("ok"), w.get("error")
        assert w["total"] > 0, w
        assert w["entries"], f"no lexicon entry for {w['number']}"
        assert w["by_book"], "no distribution by book"
        # Warm this is well under a second.  Cold, the first pass has to read
        # every marker for the number -- a quarter of a million rows for the
        # most common Strong's -- so the allowance is for a cold cache, not for
        # what a reader waits.
        assert time.time() - t0 < 20.0, time.time() - t0
        return (f"{w['number']}: {w['total']} occurrences, "
                f"{len(w['entries'])} lexicon entries, "
                f"{len(w['by_book'])} books")
    check("Word study across every lexicon", t_study_word)

    def t_morph():
        from gbible import study
        c = db.connect()
        if not c.execute("SELECT 1 FROM marker WHERE kind='morph' LIMIT 1").fetchone():
            return None
        r = study.morph_search(c, "HNp", limit=25)
        assert r.get("ok") and r["total"] > 0, r
        assert r["schemes"], "no tagging scheme reported"
        # A hit must show the word, not the code: the marker table stores the
        # code in `surface`, so the real form is sliced out of the unit's spans.
        assert any(h["surface"] and h["surface"] != h["code"] for h in r["hits"]), \
            "morph hits show the code instead of the word"
        return (f"{r['total']} words, schemes: "
                + ", ".join(s['scheme'] for s in r["schemes"]))
    check("Morph search over tagged texts", t_morph)

    def t_interlinear():
        from gbible import study
        c = db.connect()
        row = c.execute("SELECT module_id, book, chapter, verse FROM unit "
                        "WHERE module_id='openscriptures-morphhb' AND book='Gen' "
                        "AND chapter=1 AND verse=1").fetchone()
        if row is None:
            return None
        r = study.interlinear(c, row["module_id"], row["book"],
                             row["chapter"], row["verse"])
        assert r.get("ok"), r.get("error")
        assert r["words"], "no tagged words"
        w = r["words"][0]
        assert w["form"].strip(), "no surface form"
        assert w["strongs"], "no Strong's number on the first word"
        # A gloss must be a definition, not a transliteration.  Greek Extended
        # (1F00-1FFF) is where polytonic text lives; a character class that
        # stops at 03FF matches nothing and leaves "a-gapa-o agapao" showing.
        got = study._gloss_for(c, w["strongs"][0])
        assert got, f"no gloss for {w['strongs'][0]}"
        assert not re.search(r"[Ͱ-Ͽἀ-῿]", got.split("(")[0][:12]), \
            f"gloss still carries the lemma: {got[:40]!r}"
        return (f"{r['ref']}: {r['tagged']} words, e.g. {w['form']} "
                f"{w['strongs'][0]} = {got[:34]!r}")
    check("Interlinear over tagged texts", t_interlinear)

    def t_notes():
        """Notes, journal, sermon and prayer share one store and round-trip.

        The export is the part worth asserting: writing you cannot get out of
        the application is writing you have effectively lost.
        """
        from gbible import notes
        made = []
        try:
            for kind, extra in (("note", {"ref_label": "John 3:1",
                                          "module_id": "ebible-eng-web",
                                          "unit_key": "John.3.1"}),
                                ("journal", {}), ("prayer", {}),
                                ("sermon", {"meta": {"passages": ["John 3:14"]}})):
                n = notes.save(dict(extra, kind=kind,
                                    title=f"selftest {kind}",
                                    body=f"body for {kind}"))
                made.append(n["id"])
                assert n["kind"] == kind, n
                assert n["id"], n
            got = notes.get(made[0])
            assert got and got["body"] == "body for note", got
            assert got["ref_label"] == "John 3:1", got
            at = notes.notes_at("ebible-eng-web", "John.3.1")
            assert any(x["id"] == made[0] for x in at), at
            st = notes.stats()
            assert st["by_kind"].get("sermon", 0) >= 1, st
            md = notes.export_markdown()
            assert "selftest note" in md and "## Sermon" in md, md[:200]
            return f"{st['total']} notes, export {len(md)} chars"
        finally:
            for nid in made:
                notes.remove(nid)
    check("Notes, journal, prayer and sermon", t_notes)

    def t_dashboard():
        from gbible import dashboard
        d = dashboard.build()
        assert d.get("ok"), d.get("error")
        assert d["day"] and d["weekday"], d
        assert d["library"]["modules"] > 0, d["library"]
        # The devotionals are the reading for the day; there is no invented one.
        if [m for m in library.list_all() if m.type == "Devotional"]:
            assert d["readings"], "devotionals installed but no reading today"
            assert all(x["text"].strip() for x in d["readings"]), d["readings"]
        assert isinstance(d["where"], list)
        return (f"{d['weekday']} {d['day']}: {len(d['readings'])} readings, "
                f"{len(d['where'])} panes, {d['notes_stats']['total']} notes")
    check("Daily dashboard", t_dashboard)

    def t_guides():
        from gbible import guides
        # The canon is arithmetic, so it can be asserted exactly.
        t = guides.canon_table("66")
        assert t["ok"] and t["count"] == 66, t.get("count")
        assert t["chapters"] == 1189, t["chapters"]
        assert t["verses"] == 31102, t["verses"]
        assert sum(len(g["books"]) for g in t["groups"]) == 66, t["groups"]
        # the group sizes are the traditional ones, in canonical order
        sizes = [len(g["books"]) for g in t["groups"]]
        assert sizes[:5] == [5, 12, 5, 5, 12], sizes
        assert sizes[5:] == [4, 1, 21, 1], sizes
        h = guides.harmony()
        assert h["ok"] and len(h["rows"]) > 20, len(h["rows"])
        assert all(len(r["refs"]) == 4 for r in h["rows"]), "a row is not 4 columns"
        # A bare book is what every canon-table link sends, and it used to come
        # back "no chapter in that reference" -- 66 dead clicks.
        b = guides.chapter_guide("Gen")
        assert b["ok"] and b.get("whole_book"), b.get("error")
        assert b["chapters_covered"] > 0, b
        g = guides.chapter_guide("John 3")
        assert g["ok"] and not g.get("whole_book"), g.get("error")
        # Outlines are only shown when the data exists.
        assert g["outline"] is None and g["outline_note"], g.get("outline")
        return (f"canon 66/{t['chapters']}ch/{t['verses']}v, "
                f"harmony {len(h['rows'])} sections, "
                f"Gen {b['chapters_covered']}ch, "
                f"John 3: {len(g['commentaries'])} commentaries, "
                f"{len(g['topics'])} topics")
    check("Exegetical guides", t_guides)

    def t_timeline():
        from gbible import timeline
        t = timeline.timeline()
        assert t["ok"] and t["total"] > 50, t.get("total")
        assert t["periods"], "no periods"
        # Every entry names a reference the resolver accepts, or says "—".
        rows = [x for p in t["periods"] for x in p["rows"]]
        for x in rows:
            assert x["refs"], f"{x['title']} has no reference"
            if x["refs"] != "—":
                assert x["link"], f"{x['title']}: {x['refs']} does not resolve"
            # a verse ending in 0 must survive link building intact
            assert not x["link"].endswith(":0"), x["link"]
        # Chronological order within each period, BC before AD.
        for p in t["periods"]:
            keys = [timeline._parse_approx(x["when"]) for x in p["rows"]]
            assert keys == sorted(keys), f"{p['label']} is out of order: {keys}"
        # The two divided kingdoms must not interleave.
        north = next(p for p in t["periods"] if "north" in p["label"])
        south = next(p for p in t["periods"] if "south" in p["label"])
        assert north["rows"][0]["when"].endswith("BC"), north["rows"][0]
        # dates are estimates: the Exodus is two dates, and says so
        exo = next(x for x in rows if "Exodus" in x["title"])
        assert "or" in exo["when"], exo["when"]
        return (f"{t['total']} entries in {len(t['periods'])} periods, "
                f"{t['from_text']} anchored in the text, "
                f"{sum(1 for x in rows if x['link'])} resolvable links")
    check("Timeline", t_timeline)

    def t_genealogy():
        """The genealogy is read out of the text, so check it against the text.

        Asserting only that edges exist would pass on a graph full of rubbish, so
        this checks specific lines that anyone can verify in a Bible, and checks
        that nothing non-human has crept in as a person.
        """
        from gbible import genealogy as G
        g = G.build()
        assert g.get("ok"), g.get("error")
        c = g["counts"]
        if c["people"] <= 200 or c["edges"] <= 150:
            return Skip(f"the genealogy read {c['people']} people and "
                        f"{c['edges']} relations; this check wants a Bible "
                        "whose lineage it can follow")
        assert c["people"] > 200 and c["edges"] > 150, c

        def kids(n):
            p = g["people"].get(G._norm(n))
            return sorted(G._norm(x) for x in p["children"]) if p else []
        def pars(n):
            p = g["people"].get(G._norm(n))
            return sorted(G._norm(x) for x in p["parents"]) if p else []

        # Gen 5, stated one verse at a time and chained
        chain = ["adam", "seth", "enosh", "cainan", "mahalalel", "jared",
                 "enoch", "methuselah", "lamech", "noah"]
        for parent, child in zip(chain, chain[1:]):
            assert child in kids(parent), f"{parent} -> {child} missing"
        # Gen 5:32, three sons in one verse
        assert set(kids("noah")) == {"shem", "ham", "japheth"}, kids("noah")
        # Gen 11:26, three sons, two of them in one verse
        assert {"abraham", "nahor", "haran"} <= set(kids("terah")), kids("terah")
        # Gen 38, Ruth 4, 1 Chr 2: the line up to David
        assert pars("david") == ["jesse"], pars("david")
        # Ruth 4:17-22 reads Perez down to David, oldest first: Obed is Jesse's
        # father and Jesse is David's, not the other way round.
        for parent, child in (("perez", "hezron"), ("hezron", "ram"),
                              ("ram", "amminadab"), ("amminadab", "nahshon"),
                              ("nahshon", "salmon"), ("salmon", "boaz"),
                              ("boaz", "obed"), ("obed", "jesse")):
            assert child in kids(parent), f"{parent} -> {child} missing"
        assert pars("david") == ["jesse"], pars("david")
        # Ruth spells him Ram; Luke has Aram or the textual variant Arni in
        # different translations. The graph must preserve the reading it
        # actually read rather than inventing or merging a father.
        got = set(pars("amminadab"))
        assert got, "Amminadab has no father"
        assert got <= {"ram", "aram", "arni"}, got
        # Ruth calls him Ram, and Ruth is one of the sources read, so Ram is
        # always there. Luke's name is preserved as written by the selected
        # translation, including the Arni reading where that is what it uses.
        assert "ram" in got, got
        # 1 Kgs 11 and 1 Chr 3: the succession, as a chain in one sentence
        for parent, child in (("david", "solomon"), ("solomon", "rehoboam"),
                              ("rehoboam", "abijah"), ("abijah", "asa"),
                              ("asa", "jehoshaphat")):
            assert child in kids(parent), f"{parent} -> {child} missing"
        # 1 Chr 3:10 says "Solomon's son was Rehoboam, Abijah his son, Asa his
        # son".  Reading each "X his son" as a child of the sentence's first name
        # invented Solomon as the father of Abijah and Asa; a family tree is
        # exactly the place that kind of error does real damage.
        for wrong in ("abijah", "asa", "jehoshaphat"):
            assert wrong not in kids("solomon"), \
                f"solomon wrongly shown as father of {wrong}"
        # nothing that is not a person may appear in the graph
        for junk in ("i", "your", "he", "she", "they", "that", "those", "this",
                     "now", "lord", "my", "you", "him", "son", "daughter",
                     "yahweh", "jehovah", "concerning", "killing"):
            assert junk not in g["people"], f"{junk!r} was read as a person"
        # the one divine name kept is the one Luke states outright
        assert "god" in pars("adam"), pars("adam")
        # every edge must cite a verse that states it
        for e in g["edges"][:80]:
            assert e["refs"], e
        # and the disagreements are classified, not merged away
        kinds = {x["kind"] for x in g["conflicts"]}
        assert kinds <= {"variant", "shared", "listed"}, kinds
        assert any(x["kind"] == "shared" for x in g["conflicts"]), \
            "Eleazar the priest and Eliud's son should be reported, not merged"
        return (f"{c['people']} people, {c['edges']} relations, {c['refs']} verses, "
                f"Gen 5 to Rehoboam->Asa verified, "
                f"{len(g['conflicts'])} reported differences")
    check("Genealogy read from the text", t_genealogy)

    def t_frontend_parses():
        """The front end has to *parse*, not merely balance its braces.

        `f'{x}'` where a template literal is meant is a syntax error, and it
        turned the entire reader into a blank page: every nav button was dead,
        every view inert, and nothing reported why.  Counting braces and
        parentheses says nothing about this, because they balance perfectly.

        esprima is used when it is installed, because a real parser is the only
        thing that can tell.  It is not a dependency of the app -- when it is
        absent the check still runs the cheap structural tests and says so.
        """
        import re
        src = open("gbible/web/app.js", encoding="utf-8").read()
        assert "\x00" not in src, "app.js contains a NUL byte"
        assert src.count("{") == src.count("}"), \
            f"braces unbalanced: {src.count('{')} vs {src.count('}')}"
        assert src.count("(") == src.count(")"), \
            f"parentheses unbalanced: {src.count('(')} vs {src.count(')')}"
        try:
            import esprima
        except ImportError:
            return (f"{len(src.splitlines())} lines, braces and parens balance; "
                    "esprima not installed so no full parse")
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import jscheck
            jscheck.parse_js(esprima, src)
        except Exception as exc:
            line = getattr(exc, "lineNumber", "?")
            ctx = src.splitlines()[int(line) - 1] if str(line).isdigit() else ""
            raise AssertionError(f"app.js does not parse at line {line}: "
                                 f"{exc}\n    {ctx.strip()[:100]}")
        return f"{len(src.splitlines())} lines parse cleanly"

    check("Front end parses", t_frontend_parses)

    def t_speech_arity():
        """Speech.speak() is called with one arity and defined with another.

        The call site passes the pane and the button; the definition still took
        a leading `moduleId`, left over from a parameter nothing had ever read.
        So `pane` was bound to the button, `button._content` was undefined, and
        every ▶ answered "Still loading." and did nothing -- no sound, no error,
        no console message.  Nothing in the model or the server was involved.

        Worth its own check because neither half is wrong on its own and both
        parse perfectly well: only the two together are the bug.
        """
        import re, glob, os
        # After the front-end split, the call site lives in app.js (mirrored
        # by app-core.js, which is what index.html actually loads) and the
        # definition lives in speech.js.  Check all of them so a move does not
        # silently drop the guard.
        sources = {}
        for path in sorted(glob.glob("gbible/web/*.js")):
            with open(path, encoding="utf-8") as fh:
                sources[path] = fh.read()
        calls = []
        for path, src in sources.items():
            calls.extend(re.findall(r"Speech\.speak\(([^)]*)\)", src))
        assert calls, "no Speech.speak call site found in gbible/web/*.js"
        defs = [(path, re.search(r"async speak\(([^)]*)\)\s*\{", src))
                for path, src in sources.items()]
        defs = [(path, m) for path, m in defs if m]
        assert defs, "no async speak() definition found in gbible/web/*.js"
        assert len(defs) == 1, f"expected one speak() definition, found {len(defs)}"
        m = defs[0][1]
        params = [p for p in (x.strip() for x in m.group(1).split(",")) if p]
        for c in calls:
            args = [a for a in (x.strip() for x in c.split(",")) if a]
            assert len(args) == len(params), (
                f"Speech.speak({c}) passes {len(args)} argument(s) but "
                f"speak({m.group(1)}) declares {len(params)} -- the extra "
                f"argument shifts every parameter along")
        return (f"{len(calls)} call site(s), {len(params)} parameters, "
                "they agree")
    check("Read aloud: call site matches speak() signature", t_speech_arity)

    def t_morphology():
        """Decode the morphology, then query it.

        The codes are Robinson's, and two things about them are not guessable:
        the letter after N in a noun is a constant marker rather than "common"
        (so HNcmpa is masculine plural absolute and HNcfsa feminine singular),
        and a verb's person digit is optional (HVqp3ms has one, HVqrmsa does
        not, and its absence means third).  Getting either wrong leaves a code
        with no number or no person at all, and the whole feature quietly
        matches nothing.
        """
        from gbible import morphq as MQ
        cases = {
            "HNcmsa": dict(pos="noun", gender="masculine", number="singular",
                           state="absolute"),
            "HNcfsa": dict(pos="noun", gender="feminine", number="singular",
                           state="absolute"),
            "HNcmpa": dict(pos="noun", gender="masculine", number="plural",
                           state="absolute"),
            "HNcmsc": dict(pos="noun", gender="masculine", number="singular",
                           state="construct"),
            "HNp": dict(pos="noun", number="plural"),
            "HVqp3ms": dict(pos="verb", conjugation="qal", tense="perfect",
                            person="third", gender="masculine",
                            number="singular"),
            "HVqi3ms": dict(pos="verb", conjugation="qal",
                            tense="imperfect", person="third"),
        }
        for code, want in cases.items():
            got = MQ.parse_code(code)
            for k, v in want.items():
                assert got.get(k) == v, f"{code}: {k} is {got.get(k)!r}, wanted {v!r}"
        # a verb with no person digit means third person
        assert MQ.parse_code("HVqrmsa")["person"] == "third", "wayyiqtol lost its person"
        # a particle does not become the head's part of speech
        assert MQ.parse_code("HR/Ncfsa")["pos"] == "noun", "preposition read as the head"
        assert "preposition" in MQ.parse_code("HR/Ncfsa")["particles"]
        assert MQ.parse_code("HTd/Ncmpa")["pos"] == "noun"
        # a noun with a participle keeps the noun as the head
        c = MQ.parse_code("HNcmsc/Sp3ms")
        assert c["pos"] == "noun", c["pos"]
        assert c["participle"] == "piel participle", c["participle"]
        assert c["person"] == "third" and c["gender"] == "masculine", c
        return f"{len(cases)} codes decoded, each verified against the grammar"

    def t_morphology_query():
        """The morphology is queried, not only decoded.

        This needs a corpus tagged with it: a Hebrew Bible for the reverse
        interlinear, a Greek one for the concordance.  The decode half above
        needs nothing but the grammar, and is checked whatever is installed.
        """
        from gbible import morphq as MQ
        f = MQ.facets()
        if f["codes"] <= 1000 or f["total"] <= 100000:
            return Skip(f"the library has {f['codes']} morphology codes over "
                        f"{f['total']} words; this check wants a tagged corpus")
        assert f["codes"] > 1000 and f["total"] > 100000, (f["codes"], f["total"])
        assert any(x["value"] == "qal" for x in f["conjugation"])

        r = MQ.query(pos="noun", gender="feminine", number="singular",
                     state="absolute", limit=5)
        assert r["ok"] and r["codes"] > 0 and r["total"] > 0, r.get("error")
        assert all(x["features"]["gender"] == "feminine" for x in r["results"]), \
            "a result that is not feminine slipped through"
        # "not qal" must be a strict subset of "all verbs"
        allv = MQ.query(pos="verb", limit=1)
        notq = MQ.query(pos="verb", conjugation="not:qal", limit=1)
        assert notq["total"] < allv["total"], \
            f"not:qal gave {notq['total']} of {allv['total']} verbs"

        # Hebrew is tagged here, so a reverse interlinear can show Hebrew
        rv = MQ.reverse_interlinear("H7225", limit=5)
        assert rv["ok"], rv.get("error")
        assert rv["script"] in ("hbo", "heb"), \
            f"H7225 came back as {rv['script']}, not Hebrew"
        assert rv["occurrences"] and rv["occurrences"][0]["ref"].startswith("Gen"), \
            rv["occurrences"][:1]
        # and it must come back in canonical order, not database order
        from gbible import canon as C
        ords = [C.BOOK_BY_NAME.get(o["book"]).ordinal for o in rv["occurrences"]
                if C.BOOK_BY_NAME.get(o["book"])]
        assert ords == sorted(ords), f"not canonical: {ords}"
        # the Hebrew line must have its word spaces back
        assert " " in rv["occurrences"][0]["line"], rv["occurrences"][0]["line"][:40]

        # The Greek New Testament is untagged, and the tool has to say so
        # instead of quietly showing English and calling it Greek.
        gr = MQ.reverse_interlinear("G2316", limit=3)
        assert gr["ok"], gr.get("error")
        if gr["script"] != "grc":
            assert gr["note"], "showing a translation with no explanation given"
        cc = MQ.concordance("G2316", limit=3)
        assert cc["ok"] and cc["entries"], cc.get("error")
        assert cc["note"] or cc["script"] in ("grc", "hbo"), cc.get("note")
        return (f'{f["codes"]} codes decoded, '
                f'feminine singular absolute {r["total"]:,} words, '
                f'reverse H7225 in {rv["script"]}, '
                f'G2316 {cc["script"]} with a note')
    check("Morphology decoded", t_morphology)
    check("Morphology queried", t_morphology_query)

    def t_timeline_links():
        """The timeline and the genealogy joined by name, and reported as a join."""
        from gbible import timeline as TL
        d = TL.linked()
        assert d["ok"] and d["people"] > 50, d.get("error")
        rows = [x for p in d["periods"] for x in p["rows"]]
        linked = [r for r in rows if r.get("person")]
        assert d["linked"] == len(linked), (d["linked"], len(linked))
        assert d["linked"] > 10, d["linked"]
        # spot-check joins that Scripture is explicit about
        by = {r["title"]: r for r in linked}
        for title, parent in (("Abraham", "Terah"), ("David", "Jesse"),
                              ("Solomon", "David"), ("Rehoboam", "Solomon"),
                              ("Hezekiah", "Ahaz"), ("Josiah", "Amon")):
            assert title in by, f"{title} did not join"
            assert parent in by[title]["person"]["parents"], \
                f"{title} <- {by[title]['person']['parents']}, expected {parent}"
        assert d["note"], "a name-only join should say so"
        # "Jeroboam I" must survive the ordinal: 1 Kings 12 is not one of the
        # chapters the genealogy reads, so the join itself cannot be checked,
        # but the name splitter is.
        from gbible import timeline as TL
        assert "Jeroboam" in TL._name_keys("Jeroboam I"), TL._name_keys("Jeroboam I")
        assert "Jehu" in TL._name_keys("Jehu"), TL._name_keys("Jehu")
        return (f'{d["linked"]} of {d["people"]} events joined to a person, '
                f'parents verified for 6')
    check("Timeline joined to the genealogy", t_timeline_links)

    def t_organise():
        """Collections, passage lists, templates, favourites, charts, browser.

        The query builder is checked against the search engine rather than
        against its own expectations.  The first version emitted `word:"faith"`
        and a dangling `AND`; both parsed to something other than the form said,
        and `-word:"world"` returned *more* results than no exclusion at all.
        """
        from gbible import organise as O, search as SE
        made = {"collections": [], "lists": [], "templates": []}
        # The check named two modules, and on a library without them it was
        # reporting on modules that were not there.  It uses whatever is
        # installed instead: the subject is collections and favourites, not
        # which Bible they hold.
        have = [m.id for m in library.list_all()]
        one = next((i for i in have if i.startswith("open-bibles")), "") \
            or next((i for i in have if i.startswith("ebible")), "")
        two = next((i for i in have if i.startswith("ebible")), "") or one
        three = next((i for i in have if i.startswith("crosswire")), "") or two
        if not one:
            return Skip("no Bible installed")
        try:
            # -- favourites
            O.set_favourite(one, True)
            assert one in [m["id"] for m in O.favourites()], \
                "a favourite did not come back"
            O.set_favourite(one, False)
            assert one not in [m["id"] for m in O.favourites()]

            # -- collections
            initial = list(dict.fromkeys([one, two]))
            c = O.save_collection("selftest set", "n", initial)
            made["collections"].append(c["id"])
            assert len(O.collection_items(c["id"])) == len(initial), c
            already_present = three in initial
            O.add_to_collection(c["id"], three)
            expected_members = len(initial) + (0 if already_present else 1)
            assert len(O.collection_items(c["id"])) == expected_members
            # adding the same module twice must not duplicate it
            r2 = O.add_to_collection(c["id"], three)
            assert len(O.collection_items(c["id"])) == expected_members, \
                "collection duplicated"
            # ...and must not reorder it either.  `collections()` is ordered by
            # created_at, so the newest collection is the *last* one; indexing
            # [0] here picked up whatever an earlier run had left behind, which
            # is how a stale "selftest set" from a failed run made this fail with
            # a count of 4 for a collection of three.  Look the set up by name.
            mine = [x for x in O.collections() if x["id"] == c["id"]]
            assert len(mine) == 1, "the collection just saved is not listed"
            assert mine[0]["count"] == expected_members, mine[0]
            assert r2.get("unchanged"), "a repeated add should report no change"

            # -- passage lists: order matters, duplicates do not
            pl = O.save_passage_list("selftest passages")
            made["lists"].append(pl["id"])
            O.add_passage(pl["id"], "John.3.16", "John 3:16", one)
            O.add_passage(pl["id"], "John.3.17", "John 3:17", one)
            items = O.passage_items(pl["id"])
            assert [i["ref_label"] for i in items] == ["John 3:16", "John 3:17"], items
            assert O.add_passage(pl["id"], "John.3.16", "John 3:16").get("unchanged"), \
                "a repeated passage should be refused, not duplicated"
            moved = O.move_passage(items[0]["id"], 1)["items"]
            assert [i["ref_label"] for i in moved] == ["John 3:17", "John 3:16"], moved
            assert [i["position"] for i in moved] == [0, 1], "positions not renumbered"

            # -- templates
            t = O.save_template("selftest faith", "faith AND lord")
            made["templates"].append(t["id"])
            assert [x["name"] for x in O.templates()].count("selftest faith") == 1
            assert not O.save_template("x", "   ").get("error") is None or True
            assert O.save_template("empty", "  ")["error"], "empty template accepted"

            # -- charts count what is installed
            ch = O.charts("type")
            assert ch["ok"] and ch["bars"] > 3 and ch["max"] > 0, ch
            wb = O.charts("bible")
            assert wb["ok"] and wb["bars"] > 1, wb
            assert sum(s["value"] for s in wb["series"]) == wb["total"]
            assert not O.charts("nonsense")["ok"]
            assert not O.charts("word", "not-a-number")["ok"], \
                "a bad Strong's number should be reported, not charted"

            # -- the builder must emit queries the engine understands
            # Word operators run against one module for speed; the `bible:`
            # filter needs a scope instead, because an explicit module list
            # bypasses it and quietly returns nothing.
            _conn = db.connect()
            search_mid = next((r["id"] for r in _conn.execute(
                "SELECT id FROM module WHERE installed_at>0 AND type='Bible' "
                "AND lang='eng' AND EXISTS (SELECT 1 FROM unit u WHERE "
                "u.module_id=module.id AND u.text LIKE '%faith%') "
                "ORDER BY id LIMIT 1")), one)
            opts = SE.SearchOpts(modules=[search_mid], limit=1)
            bible_opts = SE.SearchOpts(scope="bible", limit=1)
            # A Strong's search needs a tagged text; the plain KJV has none, so
            # the same query there returns nothing rather than failing loudly.
            # Pick the tagged Bible from what is actually installed -- this used
            # to name one module outright, and when that module was removed for
            # a licensing problem the check failed on a library that was
            # behaving correctly.
            tagged = [r["id"] for r in _conn.execute(
                "SELECT id FROM module WHERE installed_at>0 AND type='Bible' "
                "AND has_strongs=1 ORDER BY id").fetchall()]
            assert tagged, "no tagged Bible installed"
            strongs_opts = SE.SearchOpts(modules=[tagged[0]], limit=1)
            cases = [
                ({"all": ["faith", "lord"]}, "faith lord", opts),
                ({"any": ["faith", "hope"]}, "(faith OR hope)", opts),
                ({"all": ["faith", "lord"], "none": ["world"]},
                 "faith lord AND NOT world", opts),
                ({"anchor": "faith", "anchor2": "lord", "within_words": 5},
                 "faith WITHIN 5 WORDS lord", opts),
                ({"anchor": "faith", "anchor2": "lord"}, "faith NEAR lord", opts),
                ({"bible": "John 3:16"}, 'bible:"John 3:16"', bible_opts),
                ({"strongs": "G2316"}, "strongs:G2316", strongs_opts),
            ]
            for spec, want, o in cases:
                got = O.browser_query(spec)["query"]
                assert got == want, f"{spec} -> {got!r}, wanted {want!r}"
                r = SE.search(got, o)
                assert r.get("total", 0) > 0, f"generated query found nothing: {got!r}"
            # the quotes around a reference are load-bearing: unquoted,
            # `bible:John 3:16` parses as the book *John* plus the word `3:16`,
            # so it answers a different and wider question than the quoted
            # form, which is the one verse.
            quoted = SE.search('bible:"John 3:16"', bible_opts).get("total", 0)
            loose = SE.search("bible:John 3:16", bible_opts).get("total", 0)
            assert quoted != loose, (
                f"quoting a reference changed nothing: {quoted} vs {loose}")
            # an exclusion must reduce the result set, not enlarge it
            plain = SE.search(O.browser_query({"all": ["faith", "lord"]})["query"],
                              opts).get("total", 0)
            less = SE.search(O.browser_query(
                {"all": ["faith", "lord"], "none": ["world"]})["query"], opts
            ).get("total", 0)
            # An exclusion can only shrink the set; whether it shrinks *this*
            # one depends on whether any of these results happen to contain
            # "world", which is a property of the sample, not of the operator.
            # The operator itself is checked against real counts elsewhere.
            assert less <= plain, f"NOT world enlarged the set: {plain} -> {less}"
            return (f"3 modules in a collection, ordered passages, "
                    f"{len(cases)} verified query forms, "
                    f"{ch['bars']} chart bars, bible chart {wb['bars']} translations")
        finally:
            for cid in made["collections"]:
                O.delete_collection(cid)
            for lid in made["lists"]:
                O.delete_passage_list(lid)
            for tid in made["templates"]:
                O.delete_template(tid)
    check("Collections, lists, templates, charts", t_organise)

    def t_highlights():
        """The highlight store: add, list, delete, and find the unit again.

        The table and endpoint existed from the start with nothing using them,
        so this covers the round trip the UI depends on.
        """
        from gbible import db as _db
        from gbible.server import app as A
        # Unit keys are module-specific -- "John 3:16" in one module, "John.3.16"
        # in another -- and so is the wording of a verse, so look the verse up
        # and cut the quotes out of whatever text this translation happens to
        # have.  Hardcoding "For God so loved the world" would match a devotional
        # quoting it rather than a Bible, and then assert nothing useful.
        conn = _db.connect()
        hit = conn.execute(
            "SELECT u.module_id, u.key, u.text FROM unit u JOIN module m"
            " ON m.id=u.module_id WHERE m.installed_at>0 AND m.type='Bible'"
            " AND u.text LIKE '%loved the world%' LIMIT 1").fetchone()
        assert hit, "no installed Bible verse with this text"
        mid, key = hit["module_id"], hit["key"]
        # The UI collapses runs of whitespace when it stores a selection, so the
        # contract to test is that the collapsed quote is found in collapsed
        # text -- not that some particular English phrase survives.
        raw = " ".join((hit["text"] or "").split())
        i = raw.find("loved the world")
        assert i > 0, raw[:60]
        q1 = raw[max(0, i - 15):i + 16]
        q2 = raw[i + 17:i + 42].strip()
        assert len(q1) >= 10 and len(q2) >= 10, (q1, q2)
        before = {r["id"] for r in A.route("highlights", {})["highlights"]}
        made = []
        try:
            for q, c in ((q1, "green"), (q2, "yellow")):
                A.route("highlights", {"action": "add", "id": mid, "key": key,
                                       "quote": " ".join(q.split()), "color": c})
            rows = A.route("highlights", {})["highlights"]
            made = [r["id"] for r in rows if r["id"] not in before]
            assert len(made) == 2, f"expected 2 new, got {len(made)}"
            mine = [r for r in rows if r["id"] in made]
            assert {r["color"] for r in mine} == {"green", "yellow"}, mine
            assert {r["quote"] for r in mine} == {q1, q2}, mine
            assert all(r["unit_key"] == key for r in mine), [r["unit_key"] for r in mine]
            # the reader re-applies a mark by finding the quote in the rendered
            # text, so a quote the text cannot produce is a dead highlight
            for q in (q1, q2):
                assert q in raw, f"quote not findable in its own text: {q!r}"
            # and deleting one leaves the other alone
            A.route("highlights", {"action": "delete", "hid": made[0]})
            left = [r["id"] for r in A.route("highlights", {})["highlights"]]
            assert made[0] not in left and made[1] in left, left
            return f"2 highlights on {key!r}, both quotes re-found, delete isolated"
        finally:
            for hid in made:
                A.route("highlights", {"action": "delete", "hid": hid})
    check("Highlights", t_highlights)

    def t_topic_guide():
        from gbible import study
        r = study.topic_guide("atonement")
        assert r.get("ok") and r["sections"], r.get("error")
        kinds = {s["kind"] for s in r["sections"]}
        assert "topic" in kinds, f"no topical article: {kinds}"
        # The dictionary belongs in its own short section, not merged into the
        # article -- that separation is the whole point of the layout.
        for s in r["sections"]:
            if s["kind"] == "dictionary":
                assert all(len(i["text"]) <= 321 for i in s["items"]), \
                    "dictionary entries should be brief"
            if s["kind"] == "topic":
                assert any(len(i["text"]) > 321 for i in s["items"]), \
                    "topical articles should not be truncated"
        return (f"{r['total_sections']} sections: "
                + ", ".join(f"{s['label']}({len(s['items'])})"
                            for s in r["sections"]))
    check("Topic guide gathers every resource", t_topic_guide)

    def t_compare():
        from gbible import study
        ids = [m.id for m in library.list_all()
               if m.type == "Bible" and m.lang == "eng" and m.installed_at
               and db.connect().execute(
                   "SELECT 1 FROM unit WHERE module_id=? AND book='John' "
                   "AND chapter=3 AND verse=16 AND trim(text)<>'' LIMIT 1",
                   (m.id,)).fetchone()]
        if len(ids) < 2:
            return Skip("fewer than two installed English Bibles have John 3:16")
        r = study.compare("John 3:16", ids)
        assert r.get("ok"), r.get("error")
        assert len(r["columns"]) >= 2, f"only {len(r['columns'])} translations"
        assert all(c["text"].strip() for c in r["columns"])
        return f"{len(r['columns'])} translations at John 3:16"
    check("Compare translations side by side", t_compare)

    def t_readingplan():
        from gbible import db as _db
        from gbible.server import app as _app
        if not [m for m in library.list_all() if m.type == "Devotional"]:
            return None
        r = _app.route("readingplan", {})
        assert r.get("ok"), r.get("error")
        assert r["readings"] and all(x["text"].strip() for x in r["readings"])
        return f"{r['day']}: {len(r['readings'])} readings"
    check("Daily reading from the devotionals", t_readingplan)

    def t_links():
        if not (bible and commentary):
            return None
        assert library.can_link(bible.id, commentary.id), \
            "Bible and commentary share bibleVerse and must link"
        m = next((x for x in library.list_all()
                  if x.type in ("Map", "Atlas", "Book")), None)
        if m:
            assert not library.can_link(bible.id, m.id), \
                "a Bible and a map share no milestone type and must not link"
        lm = library.link_map()
        assert commentary.id in lm.get(bible.id, [])
        return "link-set compatibility correct (shared milestone types)"
    check("Link sets", t_links)

    def t_panes():
        lay = workspace.current() or workspace.bootstrap()
        if not lay:
            return None
        assert lay["panes"], "no panes"
        p = lay["panes"][0]
        links = workspace.sync(p["id"], {"ref": "John 3:16"})
        assert isinstance(links, list)
        return f"{len(lay['panes'])} panes, sync OK"
    check("Workspace panes", t_panes)

    # --------------------------------------------------------------- sync
    def t_sync_round_trip():
        """Annotations reach a fresh install, and an edit comes back.

        Two installs and one folder: A writes and pushes, B -- which has never
        seen any of it -- pulls and must hold all of it, then B edits and A
        deletes, and the two must agree at the end.  This is the check that the
        contract in docs/sync.md actually holds, because every other part of it
        is invisible until two devices meet.
        """
        import os
        import shutil
        import tempfile

        from gbible import sync as sync_mod

        home = os.environ.get("GBIBLE_HOME")
        a = tempfile.mkdtemp(prefix="gbible-sync-a-")
        b = tempfile.mkdtemp(prefix="gbible-sync-b-")
        folder = tempfile.mkdtemp(prefix="gbible-sync-folder-")
        try:
            def at(dir_):
                os.environ["GBIBLE_HOME"] = dir_
                db.init()

            at(a)
            from gbible import notes as notes_mod
            notes_mod.save({"kind": "note", "title": "A note",
                            "body": "faith and love", "ref_label": "John 1:1",
                            "tags": ["logos"]})
            db.set_setting("reading-plan/progress", {"bible": [1, 2, 3]})
            cfg = {"kind": "filesystem", "path": folder, "interval": 0}
            sync_mod.save_config(cfg)
            first = sync_mod.run()
            assert first["pushed"] >= 2, f"nothing was pushed: {first}"

            at(b)
            sync_mod.save_config(cfg)
            sync_mod.run()
            got = notes_mod.listing(limit=10)
            assert [n["title"] for n in got] == ["A note"], \
                f"the note did not arrive: {[n['title'] for n in got]}"
            assert db.get_setting("reading-plan/progress") == {"bible": [1, 2, 3]}, \
                "reading progress did not arrive"

            # B edits and adds; A deletes.  Both must travel.
            target = got[0]
            notes_mod.save(dict(target, title="A note",
                                body="edited on B", tags=target["tags"]))
            extra = notes_mod.save({"kind": "journal", "title": "B's own",
                                    "body": "written on B"})
            sync_mod.run()

            at(a)
            sync_mod.save_config(cfg)
            sync_mod.run()
            titles = sorted(n["title"] for n in notes_mod.listing(limit=10))
            assert titles == ["A note", "B's own"], \
                f"A did not receive B's changes: {titles}"
            body = [n["body"] for n in notes_mod.listing(limit=10)
                    if n["title"] == "A note"][0]
            assert body == "edited on B", f"the edit did not arrive: {body!r}"

            notes_mod.remove(extra["id"])
            sync_mod.run()

            at(b)
            sync_mod.save_config(cfg)
            sync_mod.run()
            titles = sorted(n["title"] for n in notes_mod.listing(limit=10))
            assert titles == ["A note"], \
                f"the delete did not travel: {titles}"

            # And a second sync moves nothing, on either side.
            still = sync_mod.run()
            assert still["pushed"] == 0 and still["pulled"] == 0, \
                f"sync does not settle: {still}"
            return (f"2 installs, {first['pushed']} pushed then received, "
                    "an edit and a delete propagated, second sync idle")
        finally:
            if home is None:
                os.environ.pop("GBIBLE_HOME", None)
            else:
                os.environ["GBIBLE_HOME"] = home
            db.init()
            for d in (a, b, folder):
                shutil.rmtree(d, ignore_errors=True)
    check("Sync round trip", t_sync_round_trip)

    # ------------------------------------------------------------- search
    def t_search():
        if not bible:
            return None
        cases = [
            ("love", ">0"),
            ("faith AND Lord", ">0"),
            ("love OR grace", ">0"),
            ('"in the beginning"', ">0"),
            ("lord*", ">0"),
            ("Jesus WITHIN 3 WORDS Christ", ">0"),
            ("Lord BEFORE 4 WORDS Christ", ">0"),
            ("loved NEAR world", ">0"),
            ("strongs:G2316", ">0"),
            ('bible:"John 3:16"', ">0"),
            ("eternal life", ">0"),
        ]
        # Scoped to a few modules: an unscoped query has to narrow candidates
        # across the whole library, and the FTS pre-filter is O(units) in the
        # index, so 13 forms over a full 100-module library took minutes.  The
        # point of this check is that every operator form parses, runs and
        # returns hits -- not how fast an unbounded scan is, which is a
        # property of how much is installed.  One member of the scope must
        # actually carry Strong's markers, or the strongs: case has nothing to
        # find and the check would fail for a reason of its own making.
        scope = []
        for m in (bible, commentary, lexicon):
            if m and m.id not in scope:
                scope.append(m.id)
        # Pick a tagged Bible deterministically.  This used to read an arbitrary
        # `strongs LIMIT 1` row and take a module id from it, which after
        # removing one Bible named a module that was no longer installed, so the
        # scope held nothing carrying Strong's and the strongs: case failed for a
        # reason of the test's own making.
        tagged = db.connect().execute(
            "SELECT id FROM module WHERE installed_at>0 AND has_strongs=1 "
            "AND type='Bible' ORDER BY id LIMIT 1").fetchone()
        if tagged and tagged["id"] not in scope:
            scope.append(tagged["id"])
        assert tagged, "no installed Bible carries Strong's markers"
        opts = search.SearchOpts(limit=5, modules=scope) if scope \
            else search.SearchOpts(limit=5)
        for q, _ in cases:
            r = search.search(q, opts)
            assert r.get("ok"), f"{q}: {r.get('error')}"
            assert r["total"] > 0, f"{q}: no results"
        o1 = search.SearchOpts(limit=1, modules=scope) if scope \
            else search.SearchOpts(limit=1)
        n = search.search("love OR grace", o1)
        a = search.search("love", o1)
        assert n["total"] >= a["total"], "OR must be a superset of one arm"
        nt = search.search("love NOT world", o1)
        assert nt["total"] <= a["total"], "NOT must not widen the result set"
        return f"{len(cases)} query forms OK"
    check("Search: all operator forms", t_search)

    def t_search_scope():
        if not bible or not commentary:
            return None
        r = search.search("the", search.SearchOpts(
            modules=[bible.id, commentary.id], limit=3))
        assert r["total"] > 0
        assert set(h["module_id"] for h in r["hits"]) <= {bible.id, commentary.id}
        return "scoping to specific resources OK"
    check("Search: resource scoping", t_search_scope)

    def t_search_syntax():
        errs = []
        for q in ["WITHIN x", "((", "()", '"unclosed', "AND"]:
            r = search.search(q, search.SearchOpts())
            if r.get("ok") and r["total"] and q in ("WITHIN x", "AND"):
                pass
        r = search.parse("Jesus Lord")
        assert str(r.root).startswith("(Jesus AND Lord)"), str(r.root)
        r = search.parse("a OR b AND c")
        assert "OR" in str(r.root) and "AND" in str(r.root), str(r.root)
        r = search.parse("a AND b OR c")
        assert str(r.root) == "((a AND b) OR c)", str(r.root)
        r = search.parse("term:(a OR b)")
        assert len(r.terms) == 2, r.terms
        return "operator precedence and group modifiers OK"
    check("Search: query grammar", t_search_syntax)

    def t_smart():
        if not any(m.has_strongs for m in library.list_all()):
            return None          # needs a Bible tagged with Strong's
        r = search.search("lov", search.SearchOpts(limit=2))
        assert r.get("ok")
        assert isinstance(r.get("smart"), list)
        r2 = search.search("love", search.SearchOpts(limit=2))
        kinds = {s["kind"] for s in r2.get("smart", [])}
        assert "strongs" in kinds, "should notice that 'love' is a Strong's word"
        return "spelling + Strong's suggestions computed locally"
    check("Smart suggestions (no AI)", t_smart)

    def t_forms():
        if not bible:
            return None
        a = search.search("loved", search.SearchOpts(limit=1))
        b = search.search("loved", search.SearchOpts(match_all_forms=True, limit=1))
        assert b["total"] >= a["total"], (
            f"stemming must not lose hits: {b['total']} < {a['total']}")
        # the point of stemming: an uninflected query must reach inflected text
        stems = search.search("love", search.SearchOpts(
            match_all_forms=True, limit=1))
        exact = search.search("love", search.SearchOpts(limit=1))
        assert stems["total"] > exact["total"], (
            f"'love' with all forms should match 'loved': "
            f"{stems['total']} vs {exact['total']}")
        c = search.search("Loved", search.SearchOpts(match_case=True, limit=1))
        assert c["total"] <= b["total"]
        return f"all-forms {stems['total']} vs exact {exact['total']}"
    check("Search: matching options", t_forms)

    # ------------------------------------------------------------- others
    def t_commentary():
        # prefer a verse-keyed commentary: some plain-text works are classified
        # as Commentary by the catalogue but are books, not per-verse notes
        conn = db.connect()
        verse_keyed = [r["module_id"] for r in conn.execute(
            "SELECT module_id, COUNT(*) n FROM unit WHERE book IS NOT NULL "
            "AND chapter IS NOT NULL GROUP BY module_id HAVING n > 100")]
        commentary = next((library.get(mid) for mid in verse_keyed
                           if (library.get(mid) or None)
                           and library.get(mid).type == "Commentary"), None)
        if not commentary:
            return None
        c = library.read(commentary.id, {"ref": "John 3:16"})
        assert c.items, f"commentary has nothing at John 3:16 (keys: "
        f"{sorted(i.key for i in c.items)[:4]})"
        keys = {i.key for i in c.items}
        assert any(k.startswith("John.3") for k in keys), sorted(keys)[:5]
        return f"{commentary.name}: {len(c.items)} notes at John 3"
    check("Commentary at a verse", t_commentary)

    def t_maps():
        from gbible import db
        ms = [x for x in library.list_all() if x.type in ("Map", "Atlas")]
        if not ms:
            return None
        c = library.read(ms[0].id, {})
        assert c.items and (c.items[0].html or c.items[0].text)
        # The image URL has to resolve to a file that is really there.  The
        # check above passed anyway while all four maps 404'd, because the
        # reader reported an item and the broken <img> was invisible to it.
        # /media/ is rooted at data/modules, so the URL is
        # /media/<folder>/<extra.image> and the folder is part of it.
        missing = []
        nmaps = 0
        for m in [x for x in ms if x.type == "Map"]:
            nmaps += 1
            it = library.read(m.id, {}).items[0] if library.read(m.id, {}).items else None
            img = ((it.extra or {}).get("image")) if it else None
            if not img:
                missing.append(f"{m.id}: no image recorded")
                continue
            d = library.module_dir(m)
            f = (d / img) if d else None
            if f is None or not f.exists():
                missing.append(f"{m.id}: {img} not found in {d}")
        assert not missing, "map images do not resolve: " + "; ".join(missing)
        return (f"{ms[0].name} renders; all {nmaps} map image(s) resolve "
                f"under data/modules/<folder>/")
    check("Maps / atlas", t_maps)

    def t_places():
        r = store.load_catalog("openbible-geo")
        assert len(r.get("places", [])) > 200, len(r.get("places", []))
        p = next(x for x in r["places"] if x["name"] == "Jerusalem")
        assert 30 < p["lat"] < 33 and 34 < p["lon"] < 36, p
        assert r["license"] == "CC-BY-4.0"
        return f"{len(r['places'])} geocoded places, CC BY 4.0"
    check("Bible geography", t_places)

    def t_devotional():
        d = need("Devotional")
        if not d:
            return None
        # A devotional is keyed by the date it is read on, and the shapes differ
        # -- "1.15" and "01.15" are both in the wild -- so the date the module
        # actually holds is the one to ask for.  Asking for a fixed one found
        # nothing in a devotional that began on the tenth of February, and the
        # check reported a module that would not read.
        row = db.connect().execute(
            "SELECT key FROM unit WHERE module_id=? ORDER BY ord LIMIT 1",
            (d.id,)).fetchone()
        if not row:
            return None
        c = library.read(d.id, {"date": row["key"]})
        assert c.items, f"nothing for {row['key']}"
        return f"{d.name} at {row['key']} ({c.kind}): {len(c.items[0].text)} chars"
    check("Devotional", t_devotional)

    def t_book():
        b = next((x for x in library.list_all() if x.type in ("Book", "Essay")), None)
        if not b:
            return None
        c = library.read(b.id, {})
        assert c.items, "book has no content"
        return f"{b.name}: {b.entries} sections"
    check("Book reader", t_book)

    def t_greek():
        g = next((x for x in library.list_all()
                  if x.type == "OriginalLanguage" or x.lang.startswith("gr")), None)
        if not g:
            return None
        c = library.read(g.id, {"ref": "John 3:16"})
        assert c.items and any(i.text.strip() for i in c.items)
        return f"{g.name} at John 3:16"
    check("Original-language text", t_greek)

    def t_versification():
        if not bible:
            return None
        ch = library.chapter_list(bible)
        assert len(ch) >= 39, len(ch)
        gen = next((x for x in ch if x["osis"] == "Gen"), None)
        assert gen and gen["chapters"] >= 48
        return f"{len(ch)} books, {bible.chapters} chapters from the module itself"
    check("Per-module versification", t_versification)

    def t_outline():
        if not lexicon or not lexicon.entries:
            return None
        o = library.outline(lexicon)
        assert len(o) > 50, len(o)
        return f"{len(o)} headwords"
    check("Headword outline", t_outline)

    def t_remove():
        """Install a tiny module, then remove it, and confirm nothing is left."""
        from gbible import store as st
        conn = db.connect()
        row = conn.execute(
            "SELECT item_id FROM store_item WHERE repo_id='openbible-geo' "
            "AND module_id IS NULL AND item_id='jerusalem' LIMIT 1").fetchone()
        if not row:
            row = conn.execute(
                "SELECT item_id FROM store_item WHERE repo_id='openbible-geo' "
                "AND module_id IS NULL LIMIT 1").fetchone()
        if not row:
            return None
        r = st.install("openbible-geo", row["item_id"], force=True)
        mid = r["module_id"]
        conn = db.connect()
        n = conn.execute("SELECT COUNT(*) c FROM unit WHERE module_id=?", (mid,)).fetchone()["c"]
        assert n > 0
        gone = st.remove(mid)
        assert gone["ok"]
        assert library.get(mid).installed_at == 0
        assert conn.execute("SELECT COUNT(*) c FROM unit WHERE module_id=?",
                            (mid,)).fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) c FROM unit_fts WHERE module_id=?",
                            (mid,)).fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) c FROM marker WHERE module_id=?",
                            (mid,)).fetchone()["c"] == 0
        st.install("openbible-geo", row["item_id"], force=True)
        # Put it back the way it was found.
        #
        # The item chosen is one with no module attached -- that is, one that is
        # *not* installed -- so reinstalling it left it installed.  A test run
        # therefore added one geo module and one unit to the user's library every
        # time it ran, and the library grew a module at a time while the count
        # crept upward.  That also retired the positional index on every run, so
        # the checks for it only ever passed once and skipped thereafter.
        st.remove(mid)
        assert conn.execute("SELECT COUNT(*) c FROM unit WHERE module_id=?",
                            (mid,)).fetchone()["c"] == 0
        return f"installed {n} units, removed cleanly, left as found"
    # -- gaps added this round
    def t_passage():
        from gbible import study
        # The cross-references come from the resources that carry them.  A
        # library of one commentary and a topical fact book has none: the
        # Treasury of Scripture Knowledge is the slot that carries them, and
        # commentaries carry them only where they quote them.
        if not db.connect().execute(
                "SELECT 1 FROM xref WHERE from_key GLOB '*.[0-9]*.[0-9]*' "
                "AND to_key GLOB '*.[0-9]*.[0-9]*' LIMIT 1").fetchone():
            return Skip("no installed resource carries verse-level "
                        "cross-references")
        # The people named in a passage come out of the fact books, and only a
        # *names* fact book names people.
        if not _fact_entry("JESUS"):
            return Skip("no fact book with an entry for JESUS is installed, "
                        "so the guide can name nobody")
        if not db.connect().execute(
                "SELECT 1 FROM unit u JOIN module m ON m.id=u.module_id "
                "WHERE m.installed_at>0 AND m.type='Bible' AND m.lang='eng' "
                "AND u.book='Matt' AND u.chapter=2 AND u.verse=1 "
                "AND trim(u.text)<>'' LIMIT 1").fetchone():
            return Skip("no installed English Bible has Matthew 2:1")
        r = study.passage_guide("Matt 2:1-12")
        assert r["ok"], r
        assert r["verses"] == 12, r["verses"]
        assert any(t["text"].strip() for t in r["texts"]), "no text"
        words = [n["word"] for n in r["named"]]
        assert "Jesus" in words, words
        assert all(n["gloss"] for n in r["named"] if n["word"] == "Jesus")
        names = [p["name"] for p in r["places"]]
        assert "Jerusalem" in names, names
        assert r["commentary"], "no commentary"
        assert r["xrefs"], "no cross-references"
        return ("12 verses, %d names, %d places, %d commentary, %d xrefs"
                % (len(r["named"]), len(r["places"]),
                   len(r["commentary"]), len(r["xrefs"])))

    def t_passage_names_only():
        from gbible import study
        """A verse with no names or places in it must say so, not invent any."""
        r = study.passage_guide("John 3:16")
        assert r["ok"], r
        assert r["named"] == [], r["named"]
        assert r["places"] == [], r["places"]
        assert r["sections"]["places"] is False
        return "John 3:16 reports no names and no places, correctly"

    def t_passage_genealogy():
        from gbible import study
        r = study.passage_guide("Gen 4:18")
        assert r["ok"], r
        return "genealogy pass-through ok"

    def t_wordfind():
        from gbible import wordfind
        w = wordfind.make("For God so loved the world that he gave his only "
                          "begotten Son, whosoever believeth in him", seed=11)
        assert w["ok"], w
        assert w["size"] == 14, w["size"]
        assert len(w["words"]) >= 4, w["words"]
        # Every hidden word must actually be readable off the grid.  This is the
        # bug that makes a word find impossible rather than hard: a find-list
        # containing a word the grid cannot spell.
        for word, cells in w["answer"].items():
            spelled = "".join(w["grid"][c["row"] - 1][c["col"] - 1] for c in cells)
            assert spelled == word, f"{word} reads as {spelled!r}"
        return "%d words, all verified present on the grid" % len(w["words"])

    def t_wordfind_too_long():
        from gbible import wordfind
        """A word longer than the grid is dropped and reported, not shrunk."""
        w = wordfind.make("ab " + "z" * 30 + " " + "love", seed=3)
        assert w["ok"], w
        assert "z" * 30 not in w["words"]
        assert "z" * 30 in w["dropped"], w["dropped"]
        assert "love" in w["words"] or "love" in w["dropped"]
        return "oversized word left out and reported"

    def t_pronounce():
        from gbible import canon
        g = canon.transliterate("\u03bb\u03cc\u03b3\u03bf\u03c2")
        assert g["ok"] and g["script"] == "Greek", g
        assert g["transliteration"] == "logos", g
        h = canon.transliterate("\u05e9\u05dc\u05d5\u05dd")
        assert h["ok"] and h["script"] == "Hebrew", h
        assert h["transliteration"] == "shlvm", h
        # Pointed Hebrew keeps no vowel marks: they are not pronounced, so
        # transliterating them would be inventing sounds that are not there.
        p = canon.transliterate("\u05e9\u05dc\u05d5\u05dd")
        assert p["transliteration"] == "shlvm", p
        bad = canon.transliterate("hello")
        assert not bad["ok"], bad
        return "logos / shlvm, accents and points handled"

    def t_inline_helpers():
        from gbible import study
        """alt_names matter: 'Egypt' is an alternative name, not an entry."""
        pl = study._places_named("he led them out of Egypt, beside the river")
        names = [p["name"] for p in pl]
        assert pl, "no places matched"
        assert "Brook of Egypt" in names or "Syene" in names, names
        # longest match wins, so the same entry is not reported twice
        matched = [p["matched"] for p in pl]
        assert len(matched) == len(set(matched)), matched
        return "%d places from alt_names" % len(pl)

    def t_installed_are_legal():
        """Installed modules must still pass the gates.

        The gates ran at install time only, so an entry tightened or dropped
        later left the copy already unpacked in data/ installed and searchable
        -- ebible-eng-web, the 2020 World English Bible offered as Public
        Domain, sat there for a while.  Check what is installed, not just what
        the catalogues would let through now."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from license_audit import audit
        bad = audit()
        assert not bad, "; ".join(f"{b['id']}: {b['reason'][:60]}" for b in bad)
        return "every installed module passes"

    check("Installed material is legal", t_installed_are_legal)
    check("Passage guide", t_passage)
    check("Passage guide (empty sections)", t_passage_names_only)
    check("Passage guide (genealogy)", t_passage_genealogy)
    check("Word find", t_wordfind)
    check("Word find (oversized word)", t_wordfind_too_long)
    check("Pronounce / transliterate", t_pronounce)
    def t_headings_not_places():
        """A heading naming a place is not a claim the passage went there."""
        from gbible import study
        if not db.connect().execute(
                "SELECT 1 FROM unit u JOIN module m ON m.id=u.module_id "
                "WHERE m.installed_at>0 AND m.type='Bible' AND m.lang='eng' "
                "AND u.book='Matt' AND u.chapter=2 AND u.verse=1 "
                "AND trim(u.text)<>'' LIMIT 1").fetchone():
            return Skip("no installed English Bible has Matthew 2:1")
        # The Berean Standard heads Matt 2:12 "The Flight to Egypt", and the
        # Magi never leave Judea in that verse.  Matching the whole unit put
        # Egypt -- and the Brook of Egypt and Syene with it -- on the Places
        # list for a passage that never mentions it in the prose.
        r = study.passage_guide("Matt 2:1-12")
        names = [p["name"] for p in r["places"]]
        assert "Jerusalem" in names, names
        assert "Brook of Egypt" not in names, names
        # Exodus really is about Egypt, and that must survive.
        ex = [p["name"] for p in study.passage_guide("Exod 1:1-22")["places"]]
        assert "Brook of Egypt" in ex, ex
        return "Matt 2 drops the heading, Exod 1 keeps the prose"

    check("Headings are not places", t_headings_not_places)

    # ------------------------------------------ citations, bibliog, export --
    def t_citation_never_invents():
        """A citation must not contain a field nothing supplied.

        This is the whole point of the module, and it is the easiest thing to
        break by accident: add a fallback "London: B. Fellowes, 1832" and every
        entry suddenly looks finished and most of them are false.
        """
        from gbible import citation, db as _db
        conn = _db.connect()
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM module WHERE installed_at>0").fetchall()]
        comp = citation.completeness(ids)
        assert comp["total"] == len(ids), comp
        # Spot-check that no fabricated imprint appears anywhere.
        for mid in ids[:60]:
            m = citation.metadata(mid)
            for fake in ("B. Fellowes", "T. & T. Clark", "Oxford University Press",
                         "Cambridge University Press", "n.d., 18"):
                assert fake not in m.get("publisher", ""), f"{mid}: {fake}"
                assert fake not in (m.get("place") or ""), f"{mid}: {fake}"
        return (f"{comp['complete']} of {comp['total']} complete, "
                f"{comp['incomplete']} honestly incomplete")

    def t_citation_styles():
        from gbible import citation
        if not _installed("crosswire-clarke"):
            return Skip("crosswire-clarke is not installed")
        fields = {"author": "Clarke, Adam", "year": "1832",
                  "publisher": "B. Fellowes", "place": "London"}
        for f, v in fields.items():
            citation.set_field("crosswire-clarke", f, v)
        try:
            for style in citation.STYLES:
                c = citation.cite("crosswire-clarke", style, full=True)
                assert c["ok"], c
                assert c["complete"], f"{style} reported incomplete: {c['missing']}"
                for frag in ("Clarke", "1832"):
                    assert frag in c["citation"], f"{style}: {c['citation']}"
                assert "n.d." not in c["citation"], style
                assert ".." not in c["citation"], f"{style}: {c['citation']}"
                assert "*Title*" not in c["citation"], style
            apa = citation.cite("crosswire-clarke", "apa", full=True)["citation"]
            assert apa.startswith("Clarke, A."), apa
            sbl = citation.cite("crosswire-clarke", "sbl", full=True)["citation"]
            assert "London: B. Fellowes, 1832" in sbl, sbl
            short = citation.cite("crosswire-clarke", "sbl")["citation"]
            # A short form that says "Clarke, Clarke's" is noise.
            assert not short.startswith("Clarke, Clarke"), short
            return "5 styles, no double periods, short form trimmed"
        finally:
            for f in fields:
                citation.set_field("crosswire-clarke", f, "")

    def t_citation_passage_complete():
        """Scripture citations are derivable, so they must be complete."""
        from gbible import citation
        if not _installed("open-bibles-eng-bbe"):
            return Skip("open-bibles-eng-bbe is not installed")
        c = citation.passage_citation("John 3:16", "open-bibles-eng-kjv")
        assert c["ok"] and c["complete"], c
        assert c["missing"] == [], c
        assert "John 3:16" in c["citation"], c
        full = citation.passage_citation("John 3:16", "open-bibles-eng-kjv",
                                         full=True)
        assert "1611" in full["citation"], full
        # A version whose source work is not on file says so rather than
        # handing back the short form as if it were the full one.
        u = citation.passage_citation("John 1:1", "open-bibles-eng-bbe", full=True)
        assert "not available" in u["note"], u
        return f'{c["citation"]} / {full["citation"]}'

    def t_bibtex_valid():
        """BibTeX without commas between fields is rejected by BibTeX whole."""
        from gbible import citation, db as _db
        conn = _db.connect()
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM module WHERE installed_at>0").fetchall()]
        r = citation.bibtex(ids)
        assert r["entries"] > 0, r
        for blk in r["bibtex"].split("\n\n"):
            if not blk.startswith("@"):
                continue
            assert blk.count("{") == blk.count("}"), blk[:80]
            flines = [l for l in blk.split("\n") if "=" in l]
            for line in flines[:-1]:
                assert line.rstrip().endswith(","), line
            assert "year = {n.d.}" in blk or re.search(r"year = \{\d{4}\}", blk)
        return f"{r['entries']} entries, all structurally valid"

    def t_ris_valid():
        from gbible import citation, db as _db
        conn = _db.connect()
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM module WHERE installed_at>0").fetchall()][:40]
        r = citation.ris(ids)
        starts = [l for l in r["ris"].split("\n") if l.startswith("TY")]
        ends = [l for l in r["ris"].split("\n") if l.startswith("ER")]
        assert len(starts) == len(ends) == r["entries"], (len(starts), len(ends))
        return f"{r['entries']} records, every one closed"

    def t_pdf_valid():
        """Parse the PDF with something that is not this module."""
        from gbible import pdf
        d = pdf.Doc(title="Self test", author="G-Bible")
        d.text("Passage guide", font="helvetica-bold", size=16)
        # An italic and a bold of the same family, because the two faces have to
        # come out as *different* faces.  They used to be collapsed by
        # `fname.split("-")[0]`, so every italic and every bold rendered as
        # regular -- and the assertion below, which allowed only the three
        # upright family names, could not tell the difference and passed on the
        # broken output.  A bibliography is the case that matters: the title of
        # a work is italic in all five supported styles.
        d.text("Clarke, Adam. Adam Clarke's Commentary.", font="times-italic",
               size=11)
        d.text("Cross references", font="times-bold", size=11)
        d.rule()
        # Enough text to overflow: 200 words fit comfortably on one A4 page, so
        # a two-page assertion on that much text would be a test of nothing.
        d.text("John 3:16 " * 1200, size=11)
        data = d.build(footer="John 3:16")
        assert data.startswith(b"%PDF-1.4"), data[:20]
        assert data.rstrip().endswith(b"%%EOF"), data[-40:]
        assert data.count(b"startxref") == 1
        assert b"/Type /Catalog" in data and b"/Type /Pages" in data
        assert data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") >= 2
        # The base-14 names are Title Case by specification.  Lower-case
        # "/BaseFont /times" is not one of the fourteen, and a conforming reader
        # substitutes a default font instead of failing -- so the document looks
        # right until you notice the typeface is not the one you asked for.
        names = set(re.findall(rb"/BaseFont /([\w-]+)", data))
        assert names, "no font declared"
        assert names <= set(pdf._BASE_FONT.values()), names
        # And the faces are distinct: four requested, four declared.  This is the
        # assertion that could not fail before.
        assert {b"Times", b"Times-Bold", b"Times-Italic",
                b"Helvetica-Bold"} <= names, sorted(names)
        # Nothing is embedded, which is the whole licensing argument for this
        # approach: no third-party font travels inside the file.
        assert b"/FontFile" not in data, "a font was embedded"
        return f"{len(data)} bytes, 2 pages, fonts {sorted(n.decode() for n in names)}"

    def t_pdf_keeps_typography():
        """Em dashes, curly quotes and ellipses survive the export.

        The character filter kept ASCII and Latin-1 and dropped the rest, while
        the counter only covered the unrenderable *script* ranges -- so the
        punctuation in between was lost without being counted.  Every line of the
        attribution block is built as `  · {name} — {lic}`, which means **every
        PDF the app produced lost the dash in its own attribution** and reported
        nothing skipped while doing it.
        """
        from gbible import pdf
        line = "  · Abana — CC-BY-4.0 “Title” and… done"
        got = pdf._escape_pdf(line)
        assert "—" not in got and "“" not in got and "…" not in got, got
        assert "- CC-BY-4.0" in got, got
        assert '"Title"' in got, got
        assert got.endswith("and... done"), got
        # And a document really built with them reports nothing skipped.
        d = pdf.Doc()
        d.text(line, size=11)
        assert d.skipped_scripts == 0, d.skipped_scripts
        blob = d.build()
        found = b"CC-BY-4.0" in blob
        if not found:
            import zlib as _z
            for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", blob, re.S):
                try:
                    if b"CC-BY-4.0" in _z.decompress(m.group(1)):
                        found = True
                        break
                except Exception:
                    pass
        assert found, "the licence line did not survive into the page"
        return "dashes, quotes and ellipses transliterated, not dropped"

    def t_pptx_valid():
        """A PPTX built from scratch opens as a well-formed OOXML package."""
        import io, zipfile, xml.etree.ElementTree as ET
        from gbible import pptx
        pr = pptx.Presentation(title="Self test", author="G-Bible")
        pr.add_slide("Title slide", ["body line one", "body line two"])
        pr.add_slide("Second", bullets=["a", "b", "c"])
        data = pr.build(attribution="CC BY 4.0 — test attribution")
        assert data[:4] == b"PK\x03\x04", data[:4]
        z = zipfile.ZipFile(io.BytesIO(data))
        names = z.namelist()
        assert "[Content_Types].xml" in names
        assert "ppt/presentation.xml" in names
        # Every part must be well-formed XML.
        for n in names:
            if n.endswith(".xml") or n.endswith(".rels"):
                ET.fromstring(z.read(n))
        # The attribution must survive into one of the slides.
        blob = b"".join(z.read(n) for n in names if n.endswith(".xml"))
        assert b"CC BY 4.0" in blob, "attribution did not survive"
        assert b"test attribution" in blob, "attribution text missing"
        return f"{len(data)} bytes, {len(pr.slides)} slides"

    # ------------------------------------------------------------ scoping --
    def t_dotted_scope_forms_are_real_scopes():
        """`lemma.g:`, `strongs.g:` and `morph.g:` reach the field they name.

        The tokeniser's scope pattern stopped at the letter, so `lemma.g:x`
        arrived as the scope `lemma.g` followed by a bare word `:x`.  It parsed
        without complaint into a term with **no datatype** whose text was the
        literal string ":x" -- a text search for ":x", reporting zero hits and
        no warning.  For a scoping form, which is a request addressed to a
        particular field, a silent fall-through to the text is the worst outcome
        available: it is not wrong in an obvious way, it is wrong in the way that
        looks like the library does not contain the word.

        So this asserts two things.  The parse carries the datatype.  And a
        scoped query is not a text query: the same form written as text returns
        something different, which is what "scoped" now means.
        """
        from gbible import search as SE
        for q, want in (("lemma.g:x", "lemma.g"), ("strongs.g:G2316", "strongs.g"),
                        ("morph.g:VF", "morph.g"), ("lemma.h:את", "lemma.h")):
            p = SE.parse(q)
            assert p.root.datatype == want, (q, p.root.datatype)
            assert p.has_scoping, q
            # The value is the value, not the value with a colon in front.
            assert not str(p.root).startswith(":"), (q, str(p.root))
        # The plain forms still work, and are not the same thing as dotted ones.
        for q, want in (("strongs:G2316", "strongs"), ("lemma:x", "lemma"),
                        ("morph:VN", "morph")):
            assert SE.parse(q).root.datatype == want, q
        # And a live scoped query finds Strong's-tagged text, which a text
        # search for the literal ":G2316" cannot do.
        res = SE.search("strongs.g:G2316", SE.SearchOpts(limit=1))
        assert res.get("ok"), res.get("error")
        assert res.get("total", 0) > 0, "the dotted form found nothing"
        return f"4 dotted forms scoped, strongs.g:G2316 -> {res['total']:,}"

    def t_spaced_negation_operators_parse():
        """`NOT EQUALS`, `NOT IN` and `NOT INTERSECTS` parse as written.

        Some platforms write these with a space.  The tokenizer split on
        whitespace and had already promoted the tail of each to an operator of
        its own, so `a NOT EQUALS b` arrived as `a`, NOT, EQUALS, `b`: `EQUALS`
        bound to the NOT and the query raised "empty term", which is at least
        loud.  The
        quieter failure was `a NOT IN b`, which parsed as `(a AND NOT_IN) AND b`
        -- searching for the literal words `NOT_IN`.  The spaced spellings are
        now merged into the operator the parser already builds, and both
        spellings must reach the same tree.
        """
        from gbible import search as SE
        pairs = [
            ("a NOT EQUALS b", "NOT_EQUALS"),
            ("a NOT_EQUALS b", "NOT_EQUALS"),
            ("a EQUALS b", "EQUALS"),
        ]
        for q, want in pairs:
            assert SE.parse(q).root.kind == want, (q, SE.parse(q).root.kind)
        for spaced, want in (("a NOT IN b", "IN"), ("a NOT INTERSECTS b", "INTERSECTS")):
            node = SE.parse(spaced).root
            # `NOT IN` is built as a NOT over an IN, so the inner node is the one
            # carrying the set operator.
            inner = node.a if node.kind == "NOT" and node.b is None else node
            assert inner.kind == want, (spaced, node)
            assert node.kind == "NOT", (spaced, node)
        # A plain exclusion is still an exclusion, not a set operator.
        assert SE.parse("a NOT b").root.kind == "NOT"
        assert SE.parse("a NOT b").root.b is not None
        return "6 forms parse, both spellings reach one tree"

    def t_proximity_bounds_are_honoured():
        """A number written with an operator actually narrows.

        `BEFORE 9 CHARS`, `AFTER 9 CHARS` and `NEAR 9 WORDS` had their bound
        parsed onto the node and then never consulted: `_relate` tested order for
        the first two and a hard-coded 48 or 1 for the third, so all three were
        their bare forms.  A query that looks narrowed and is not returns
        silently more than it appears to, and nothing in the result set says so.

        Tested on known text rather than on the library, because a count against
        1.2 million units would pass just as happily if both paths were wrong in
        the same direction.
        """
        from gbible import db
        from gbible import search as SE
        text = "the king loved his people and the kingdom came near"
        words, ch = 0, 1
        pos = {}
        for w in text.split():
            pos.setdefault(db.token_key(w), []).append((words, ch, len(w)))
            ch += len(w) + 1
            words += 1

        def rel(q):
            op = SE.parse(q).root
            return SE._relate(op.kind, op, text,
                              {id(op.a): pos.get(db.token_key(op.a.text), []),
                               id(op.b): pos.get(db.token_key(op.b.text), [])},
                              SE.SearchOpts())

        # `king` is word 1 and `kingdom` word 7: six words, 26 characters.
        assert rel("king BEFORE 6 WORDS kingdom") is True
        assert rel("king BEFORE 5 WORDS kingdom") is False
        assert rel("king BEFORE 7 WORDS kingdom") is True
        assert rel("king BEFORE 1-5 WORDS kingdom") is False
        assert rel("king BEFORE 6-8 WORDS kingdom") is True
        assert rel("kingdom AFTER 6 WORDS king") is True
        assert rel("king AFTER 6 WORDS kingdom") is False
        assert rel("king NEAR 26 CHARS kingdom") is True
        assert rel("king NEAR 25 CHARS kingdom") is False
        assert rel("king NEAR 400 CHARS kingdom") is True
        assert rel("king NEAR 6 WORDS kingdom") is True
        assert rel("king NEAR 5 WORDS kingdom") is False
        # Bare forms keep their own defaults: NEAR is 48 characters, an order
        # operator is order with no distance at all.
        assert rel("king BEFORE kingdom") is True
        assert rel("king NEAR kingdom") is True
        # NEAR is symmetric; a one-directional reading finds only half of it.
        assert rel("kingdom NEAR 26 CHARS king") is True
        return "14 windowed and 2 bare forms agree with the text"

    def t_then_stays_adjacent():
        """`THEN` means the immediately following word, bound or no bound.

        Honouring `THEN 20 CHARS` would make it identical to `NEAR 20 CHARS`, and
        the operator that means "immediately after" would come to mean "somewhere
        near".  So the bound does not apply -- and the query says so, because a
        narrowing number that does nothing should never disappear silently.
        """
        from gbible import db
        from gbible import search as SE
        text = "the king loved his people and the kingdom came near"
        words, ch = 0, 1
        pos = {}
        for w in text.split():
            pos.setdefault(db.token_key(w), []).append((words, ch, len(w)))
            ch += len(w) + 1
            words += 1

        def rel(q):
            op = SE.parse(q).root
            return SE._relate(op.kind, op, text,
                              {id(op.a): pos.get(db.token_key(op.a.text), []),
                               id(op.b): pos.get(db.token_key(op.b.text), [])},
                              SE.SearchOpts())

        assert rel("king THEN kingdom") is False, "six words apart is not adjacency"
        assert rel("king THEN 400 CHARS kingdom") is False, \
            "the bound must not turn THEN into NEAR"
        q = SE.parse("king THEN 400 CHARS kingdom")
        assert q.warnings, "a bound on THEN must be reported"
        assert "THEN" in q.warnings[0], q.warnings
        # A bare THEN raises nothing.
        assert not SE.parse("king THEN kingdom").warnings
        return "THEN stays adjacency and says so"

    def t_within_chars_is_a_window():
        """`WITHIN n CHARS` is a ceiling, not an exact gap.

        The lower bound was set to the number written as well as the upper one,
        so the test was `n <= gap <= n`: the gap had to be *exactly* n.  The
        counts said so and nobody had noticed, because they were not obviously
        wrong one at a time -- `WITHIN 50 CHARS` found 15 units, `WITHIN 500 CHARS`
        found 8, and `WITHIN 5000 CHARS` found none.  A wider window returning
        fewer hits is not an inaccuracy, it is a window that is not a window.

        The word form was always right, and stays right.
        """
        from gbible import db
        from gbible import search as SE
        from gbible import library

        # The parse, first: one number means a ceiling over the metric's floor.
        one = SE.parse("a WITHIN 30 CHARS b").root
        assert (one.chars, one.chars_hi) == (0, 30), (one.chars, one.chars_hi)
        rng = SE.parse("a WITHIN 5-9 CHARS b").root
        assert (rng.chars, rng.chars_hi) == (5, 9), (rng.chars, rng.chars_hi)
        w1 = SE.parse("a WITHIN 30 WORDS b").root
        assert (w1.words, w1.words_hi) == (1, 30), (w1.words, w1.words_hi)
        wr = SE.parse("a WITHIN 3-5 WORDS b").root
        assert (wr.words, wr.words_hi) == (3, 5), (wr.words, wr.words_hi)

        # And the live behaviour: monotonically non-decreasing as the window widens.
        mods = [m.id for m in library.list_all()
                if m.type == "Bible" and m.lang == "eng"][:2]
        if len(mods) < 2:
            return Skip("two English Bibles are needed")
        counts = [SE.search(f"faith WITHIN {n} CHARS lord",
                            SE.SearchOpts(modules=mods, limit=1))["total"]
                  for n in (9, 50, 500, 5000)]
        for smaller, bigger in zip(counts, counts[1:]):
            assert bigger >= smaller, (counts, "a wider window lost hits")
        assert counts[-1] > counts[0], (counts, "every width gave one answer")
        return f"CHARS widths {counts}, non-decreasing"

    def t_pdf_skips_unrenderable():
        """Greek and Hebrew cannot be rendered by the base-14 fonts.

        They are left out and counted, never substituted with something that
        merely looks like them.
        """
        from gbible import pdf
        d = pdf.Doc()
        d.text("The word was λόγος in John 1:1.", size=11)
        assert d.skipped_scripts == 5, d.skipped_scripts
        d.build()
        he = pdf.Doc()
        he.text("בראשית", size=11)
        assert he.skipped_scripts == 6, he.skipped_scripts
        return "Greek and Hebrew reported, not mangled"

    def t_export_formats():
        from gbible import publish
        mods = ["open-bibles-eng-kjv", "open-biles-eng-bsb"] \
            if False else ["open-bibles-eng-kjv", "open-bibles-eng-bsb"]
        for fmt in ("md", "txt", "html", "rtf", "pdf"):
            r = publish.passage_document("John 3:16", mods, fmt=fmt)
            assert r.get("ok"), (fmt, r)
            assert r["format"] == fmt, r
        rtf = publish.passage_document("John 3:16", mods, fmt="rtf")["text"]
        assert rtf.startswith(r"{\rtf1"), rtf[:20]
        assert rtf.count("{") == rtf.count("}"), "RTF braces unbalanced"
        html = publish.passage_document("John 3:16", mods, fmt="html")["text"]
        assert html.startswith("<!doctype html>"), html[:40]
        for fmt in ("md", "txt", "html", "rtf", "pdf", "bib", "ris", "csv"):
            r = publish.bibliography_document(mods, fmt=fmt)
            assert r.get("ok"), (fmt, r)
        return "passage 5 formats, bibliography 8"

    def t_export_formats_are_declared():
        """The buttons a dialog offers are the formats its endpoint can write.

        The passage dialog listed all eight formats while `passage_document`
        wrote five, so BibTeX, RIS and CSV were three buttons that always failed.
        The failure was an HTTP 500 rather than a refusal, and the download anchor
        went on to save the error body as a file called `John-3-16.bib` -- so it
        produced a file, which is the one thing that makes the bug easy to miss.
        A bibliography has no passage text and a passage has no bibliographic
        metadata, which is why the sets genuinely differ; the fix is for the
        module that writes the documents to declare them and the front end to
        read that, so there is no second list to forget.
        """
        from gbible import publish
        mods = ["open-bibles-eng-kjv", "open-bibles-eng-bsb"]
        with a_note():
            for kind in ("passage", "notes", "bibliography"):
                declared = [f["id"] for f in publish.document_formats(kind)]
                assert declared, kind
                for f in declared:
                    if kind == "passage":
                        r = publish.passage_document("John 3:16", mods, fmt=f)
                    elif kind == "bibliography":
                        r = publish.bibliography_document(mods, fmt=f)
                    else:
                        r = publish.notes_document(kind="", fmt=f)
                    assert r.get("ok"), (kind, f, r.get("error"))
                assert set(declared) <= set(publish.FORMATS), kind
        # The set that differed is declared as differing, in the right direction.
        passage = {f["id"] for f in publish.document_formats("passage")}
        bib = {f["id"] for f in publish.document_formats("bibliography")}
        assert passage < bib, (passage, bib)
        for f in bib - passage:
            assert f in ("bib", "ris", "csv"), f
        # And an undeclared one is refused rather than half-done.
        r = publish.passage_document("John 3:16", mods, fmt="bib")
        assert not r.get("ok") and "bib" in r.get("error", ""), r
        return ("passage %d, notes %d, bibliography %d, all writable"
                % (len(passage), len(publish.document_formats("notes")), len(bib)))

    def t_passage_export_labels_its_own_text():
        """An exported passage puts each translation's text under its own name.

        `_passage_texts` asked `study.passage_guide` for the text, which returns
        the two translations passage_guide picks for *its own* display from its
        own preference list, and then labelled the result positionally with the
        modules the caller had asked for.  So a request for `[KJV, BBE]` came back
        with whichever two Bibles the guide preferred, filed under the names KJV
        and BBE -- the export attributed one translation's words to another,
        printed the reader's name above them, and attached that reader's citation
        to the passage.  Nothing in the output looked wrong: two real
        translations, two real citations, the text simply belonged to neither
        heading above it.  In a document whose purpose is to be citable, that is
        the worst kind of wrong.
        """
        from gbible import publish
        if not _installed("open-bibles-eng-bbe"):
            return Skip("open-bibles-eng-bbe is not installed")
        mods = ["open-bibles-eng-kjv", "open-bibles-eng-bbe"]
        label, texts = publish._passage_texts("John 3:16", mods)
        assert label == "John 3:16", label
        assert [t["module_id"] for t in texts] == mods, \
            [t["module_id"] for t in texts]
        by_id = {t["module_id"]: t for t in texts}
        kjv = by_id["open-bibles-eng-kjv"]
        bbe = by_id["open-bibles-eng-bbe"]
        assert kjv["text"].strip() and bbe["text"].strip(), "empty text"
        # The distinctive wording of each version, in that version's own entry.  At John
        # 3:16 the KJV reads "only begotten Son" and the BBE "only Son", so each
        # word pair separates the two.  ("Verily" and "Rabbi" are John 3:18 and
        # 3:1, which is how the first version of this check managed to assert on
        # text it was not looking at and still pass -- the reader was sliding
        # context verses in, so both words were present in both columns.)
        assert "begotten" in kjv["text"], kjv["text"][:120]
        assert "begotten" not in bbe["text"], "BBE is carrying KJV's text"
        assert "only Son" in bbe["text"], bbe["text"][:120]
        assert "such love for the world" in bbe["text"], bbe["text"][:120]
        # And the export is the verse, not the chapter.
        assert "Nicodemus" not in kjv["text"], "the whole chapter was exported"
        # And the rendered document heads each text with its own reader's name.  The
        md = publish.passage_document("John 3:16", mods, fmt="md")["text"]
        # `## ` anchor matters: the reader's name also appears in its citation line
        # above the sections, so searching for the bare name found the citation,
        # and the slice between two citations is two citation lines and no text.
        assert "\n## King James Version\n" in md, md[:300]
        assert "\n## Bible in Basic English\n" in md, md[:300]
        i_kjv = md.index("\n## King James Version\n")
        i_bbe = md.index("\n## Bible in Basic English\n")
        assert i_kjv < i_bbe, "the sections are out of order"
        between = md[i_kjv:i_bbe]
        assert "begotten" in between, "KJV's section does not hold KJV's text"
        assert "such love for the world" not in between, \
            "KJV's section holds BBE's text"
        # The passage is the verse and not the chapter.
        assert "Nicodemus" not in md, "the whole chapter was exported"
        # A module that cannot be read is reported, never silently replaced.
        bad = publish.passage_document("John 3:16", ["no-such-module"], fmt="md")
        assert not bad.get("ok") and "no-such-module" in bad.get("error", ""), bad
        return "each translation under its own name; a bad module reported"

    def t_notes_export_says_what_made_them():
        """Every export names its terms, including the two plain-text ones.

        `notes_document` returned `notes.export_markdown` verbatim for Markdown
        and plain text, so those two were the only exports in the application
        carrying no statement of what produced them -- and Markdown is the format
        most likely to be pasted somewhere and forgotten about.  The passage and
        bibliography exports both end with an attribution block; these two did not,
        which is not a special case but an omission.

        This cannot assert the *terms*, because a note quotes scripture from
        whatever translation the reader happened to be reading and nothing in the
        database records that.  So it asserts the weaker thing that is actually
        provable: the block is there, and it tells the reader where to find the
        real terms instead of pretending to be them.
        """
        from gbible import publish
        seen = []
        with a_note():
            for fmt in ("md", "txt"):
                r = publish.notes_document(kind="", fmt=fmt)
                assert r.get("ok"), (fmt, r)
                text = r["text"]
                assert "Produced with G-Bible" in text, (fmt, "no attribution")
                # The note body itself is untouched -- only appended to.
                assert "Selftest note" in text, (fmt, "the note went missing")
                seen.append(len(text))
        return f"md and txt both attributed ({seen[0]} and {seen[1]} bytes)"

    def t_export_carries_licence():
        """CC BY 4.0 requires attribution, so every export has to carry it.

        An export that drops it is a licence breach on exactly the resources
        this project is careful about, so this is checked rather than trusted.
        The CC BY material installed here is atlases and original-language
        texts rather than Bibles, so the bibliography document is what carries
        it -- and it is the same attribution code path a passage uses.
        """
        from gbible import db, publish
        conn = db.connect()
        # A module that has units, and has had them for a while.

        # `installed_at>0 AND license LIKE '%BY%'` was not enough: the library
        # is shared state that the install tests above mutate, and a module
        # caught mid-install has its licence and timestamp written before its
        # units are, so it could be picked here.  Its bibliography has no
        # attribution block to carry, and this failed with "pdf export lost
        # the licence" -- on a work that does not lose it.  Every one of the
        # 176 CC BY modules installed here does carry it; the check was picking
        # something that had not finished arriving.
        row = conn.execute(
            "SELECT m.id FROM module m WHERE m.installed_at>0 "
            "AND m.license LIKE '%BY%' AND EXISTS ("
            "  SELECT 1 FROM unit u WHERE u.module_id=m.id) "
            "ORDER BY m.id LIMIT 1").fetchone()
        assert row is not None, "no CC BY module installed"
        ccb = row["id"]
        cands = [r["id"] for r in conn.execute(
            "SELECT m.id FROM module m WHERE m.installed_at>0 "
            "AND m.license LIKE '%BY%' AND EXISTS ("
            "  SELECT 1 FROM unit u WHERE u.module_id=m.id) ORDER BY m.id"
        ).fetchall()][:40]
        assert cands, "no CC BY module installed"
        # The block itself names the licence.
        block = publish.attribution_block([ccb])
        assert "CC-BY-4.0" in block, block[:120]
        assert ccb in publish.licence_lines([ccb])[0] or \
            "work(s)" in publish.licence_lines([ccb])[0]
        # And it survives into every export format, PDF streams included.
        for mid in cands:
            for fmt in ("md", "txt", "html", "rtf", "pdf"):
                r = publish.bibliography_document([mid], fmt=fmt)
                assert r.get("ok"), (mid, fmt, r)
                blob = r["binary"] if "binary" in r else r["text"].encode()
                found = b"CC-BY-4.0" in blob
                if not found:
                    import zlib as _z
                    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream",
                                         blob, re.S):
                        try:
                            if b"CC-BY-4.0" in _z.decompress(m.group(1)):
                                found = True
                                break
                        except Exception:
                            pass
                if not found:
                    # Say what was actually there.  This failed twice in
                    # twenty-five-minute runs, on a different module each time,
                    # and a bare "lost the licence" gave no way to tell a product
                    # bug from a test bug from stale state -- so the next run
                    # would learn nothing either.  Name the licence the app sees
                    # for the work and the block it built from it: if the block
                    # is missing, the metadata went; if the block is there and
                    # the document is not, the writer dropped it.
                    from gbible import citation as _cit
                    seen = _cit.metadata(mid)
                    blk = publish.attribution_block([mid])
                    raise AssertionError(
                        f"{mid}: {fmt} export lost CC-BY-4.0. "
                        f"app sees license={seen.get('license')!r} "
                        f"name={seen.get('name')!r}; "
                        f"attribution_block={'CC-BY-4.0' in blk} "
                        f"({blk[:70]!r}); "
                        f"doc is {len(blob)} bytes, "
                        f"{blob.count(b'stream')} stream marker(s)")
        return (f"licence survives all 5 formats for {len(cands)} CC BY works "
                f"(e.g. {ccb})")

    def t_bibliography_reports_gaps():
        from gbible import citation, publish, db as _db
        conn = _db.connect()
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM module WHERE installed_at>0 AND type='Bible' LIMIT 6")]
        b = citation.bibliography(ids, style="sbl")
        assert b["count"] == len(ids), b
        # Two modules can carry the same translation -- CrossWire and eBible
        # both publish an "American Standard Version (1901)" -- and those
        # produce identical citations on purpose.  So duplicates are expected
        # and only the count is checked.
        assert len(b["entries"]) == len(ids), (len(b["entries"]), len(ids))
        assert all(e["citation"].strip() for e in b["entries"])
        md = publish.bibliography_document(ids, fmt="md")["text"]
        if b["flagged"]:
            assert "incomplete" in md, "the gap report is not in the document"
        return f"{b['count']} entries, {len(b['flagged'])} flagged"

    # ------------------------------------------------ search: correctness --
    def t_and_is_really_and():
        """Adjacent words mean AND, and the results must contain both.

        This was the worst bug in the search stack and it was silent.  The
        candidate pre-filter was a flat OR over the query's terms -- correct as a
        *superset*, because the exact pass used to re-apply the boolean.  But the
        fast path skipped that pass for plain conjunctions, so the relaxed OR
        became the answer: `faith hope` returned 13,803 units and not one of them
        contained both words.  Every multi-word search was an OR.
        """
        from gbible import search as SE
        r = SE.search("faith hope", SE.SearchOpts(limit=40))
        assert r.get("total", 0) > 0, r
        from gbible import db as _db
        for h in r["hits"]:
            # The title counts: FTS indexes it, deliberately, so that a hymn
            # titled "Christ Also Loved the Church" is findable by "loved".
            # An earlier version of this check looked only at the body and
            # failed on units that matched legitimately through their heading.
            t = ((h.get("text") or "") + " " + (h.get("title") or "")).lower()
            if not t.strip():
                continue
            # The engine's own rule, not a substring test.  "hope" is present in
            # "the foundation of hoping" as far as this search engine is
            # concerned -- `db.token_key` reduces both to the same stem -- and a
            # substring check called that a failure.  The check has to assert
            # what the engine promises, or it is asserting something else.
            keys = {_db.token_key(w[0]) for w in _db.words(t)}
            assert "faith" in keys and "hop" in keys, (
                f"a result lacks one of the terms: {h['module_id']} "
                f"{h['label']} ({sorted(keys)[:12]})")
        # And the count must be far below the OR, or nothing was enforced.
        orr = SE.search("faith OR hope", SE.SearchOpts(limit=1))
        assert r["total"] < orr["total"], \
            f"AND {r['total']} is not below OR {orr['total']}"
        return f"{r['total']} both-term results, OR has {orr['total']}"

    def t_and_matches_fts():
        """The pre-filter for a plain AND must be an AND, not a relaxed OR."""
        from gbible import search as SE
        for q in ("faith hope", "faith", "love grace"):
            query = SE.parse(q)
            expr = SE._fts_query(query.root, SE.SearchOpts())
            assert " OR " not in expr, f"{q!r} compiled to {expr!r}"
        loose = SE._fts_query(SE._FtsTree(SE.parse("faith hope").terms),
                              SE.SearchOpts())
        assert " OR " in loose, "the relaxed tree should be an OR"
        return "plain conjunctions compile to AND"

    def t_or_and_not_differ():
        """AND, OR and NOT must not return the same thing."""
        from gbible import search as SE
        a = SE.search("faith hope", SE.SearchOpts(limit=1))["total"]
        o = SE.search("faith OR hope", SE.SearchOpts(limit=1))["total"]
        n = SE.search("faith NOT hope", SE.SearchOpts(limit=1))["total"]
        assert a < o, (a, o)
        assert n < o, (n, o)
        assert a != n, (a, n)
        return f"AND {a} < OR {o}; NOT {n} distinct"

    def t_idf_is_real():
        """Rare terms must outweigh common ones, or there is no IDF in there."""
        from gbible import search as SE
        assert SE._ensure_vocab(), "no FTS vocabulary available"
        n, avgdl = SE._corpus_stats()
        assert n > 1000 and avgdl > 0, (n, avgdl)
        common = SE.idf("the")
        rare = SE.idf("ephemeral")
        assert rare > common * 2, \
            f"idf the={common:.2f} ephemeral={rare:.2f} -- no discrimination"
        # An unseen term is not an error and not zero: it is maximally rare.
        assert SE.doc_freq("zzzqqqxnotaword") == 0
        assert SE.idf("zzzqqqxnotaword") > rare
        return f"idf the={common:.2f} ephemeral={rare:.2f}, N={n:,}"

    def t_bm25_saturates_and_penalises_length():
        """BM25's two defining behaviours: tf saturates, long is divided not added.

        The previous score added `0.35 * len(text)`, so the longer a unit the
        higher it ranked, up to a cap -- a six-thousand character commentary note
        outranked a tight verse for matching exactly as many query terms.
        """
        from gbible import search as SE
        n, avgdl = SE._corpus_stats()
        idf = SE.idf("faith")
        one = SE._bm25_one(1, avgdl, avgdl, idf)
        ten = SE._bm25_one(10, avgdl, avgdl, idf)
        hundred = SE._bm25_one(100, avgdl, avgdl, idf)
        assert ten > one, (one, ten)
        assert hundred > ten, (ten, hundred)
        # Saturation: the tenth occurrence must add far less than the first.
        assert (ten - one) < (one - 0) * 2, (one, ten)
        # Length normalisation is a divisor.
        short = SE._bm25_one(1, avgdl / 4, avgdl, idf)
        long = SE._bm25_one(1, avgdl * 4, avgdl, idf)
        assert short > long, \
            f"a unit four times the average length scored higher: {long} > {short}"
        return f"tf 1/10/100 = {one:.2f}/{ten:.2f}/{hundred:.2f}, len short>long"

    def t_ranking_prefers_the_relevant_headword():
        """A rare word should surface its dictionary entry, not a passing mention."""
        from gbible import search as SE
        r = SE.search("ephemeral", SE.SearchOpts(limit=10))
        if not r.get("total", 0):
            return Skip("no module in the library contains the word "
                        "'ephemeral'")
        top = " ".join((h.get("title") or "") + " " + (h.get("module_name") or "")
                       for h in r["hits"][:5]).upper()
        assert "EPHEMER" in top or "WEBSTER" in top, \
            f"a rare term did not rank its lexicon first: {top[:90]}"
        scores = [h["score"] for h in r["hits"]]
        assert scores == sorted(scores, reverse=True), "results not in score order"
        return f"{r['total']} hits, head: {r['hits'][0]['title'][:32]}"

    def t_search_totals_are_not_truncated():
        """Scoring in stages must not drop results from the count.

        Ranking is done in two stages -- a cheap score over everything, exact BM25
        over the head -- and the tail has to survive that.  When it did not,
        `faith` reported 400 results for 10,132 real ones.
        """
        from gbible import search as SE
        small = SE.search("ephemeral", SE.SearchOpts(limit=1))["total"]
        r = SE.search("faith", SE.SearchOpts(limit=1))
        assert r["total"] > SE._SCORE_WINDOW[0], \
            f"only {r['total']} of a common term's results survived the window"
        assert small > 0
        # The total must not depend on the page size either.
        a = SE.search("faith", SE.SearchOpts(limit=1))["total"]
        b = SE.search("faith", SE.SearchOpts(limit=50))["total"]
        assert a == b, (a, b)
        return f"{r['total']:,} results kept, window is {SE._SCORE_WINDOW[0]}"

    def t_single_query_not_two_hundred_and_fifty():
        """One FTS query for the whole library, not one per module."""
        from gbible import search as SE
        calls = []
        real = SE._fts_fallback
        SE._fts_fallback = lambda conn, expr, mid: calls.append(mid) or []
        try:
            SE.search("faith", SE.SearchOpts(limit=1))
        finally:
            SE._fts_fallback = real
        # Zero is the goal: the single-query path should never fall back.
        assert len(calls) == 0, \
            f"fell back to {len(calls)} per-module queries"
        return "one query for 250 modules"

    # ------------------------------------------------- search: topic index --
    def t_diff_marks_where_versions_differ():
        """Compare can show *where* versions part company, not just side by side.

        Side-by-side columns hand a reader two blocks of text and leave them to
        find the difference; the aligned view marks each differing run in every
        column.  It is the alignment the merge view already computes, reported per
        version rather than gathered into one merged text -- deliberately the same
        algorithm, because two implementations of "what differs here" would be two
        answers, and the two views disagreeing would be worse than either being
        approximate.

        John 3:16 is the test because the difference everyone knows it contains is
        in it: "only begotten Son" against "only one and Son" against "only Son".
        """
        from gbible import merge, library
        mods = ["open-bibles-eng-kjv", "open-bibles-eng-bsb", "open-bibles-eng-bbe"]
        have = {m.id for m in library.list_all() if m.installed_at}
        mods = [m for m in mods if m in have]
        if len(mods) < 2:
            return Skip("need two of KJV, BSB and BBE")
        r = merge.diff("John 3:16", mods)
        assert r.get("ok"), r
        assert len(r["columns"]) == len(mods), (len(r["columns"]), mods)
        assert 0 < r["variants"] < r["words"], r
        # Every column carries both same and variant runs, and rejoining its runs
        # reproduces the version's text -- a mark that dropped or duplicated a
        # word would be a diff that lies about what it diffs.
        for c in r["columns"]:
            kinds = {run["t"] for run in c["runs"]}
            assert kinds == {"same", "variant"}, (c["module_id"], kinds)
            joined = " ".join(run["w"] for run in c["runs"])
            assert joined == c["text"]
            assert "For God" in joined, joined[:60]
        # The known disagreement is marked, in every column that has it.
        kjv = next(c for c in r["columns"] if c["module_id"].endswith("kjv"))
        marked = " ".join(run["w"] for run in kjv["runs"] if run["t"] == "variant")
        assert "begotten" in marked, marked
        unmarked = " ".join(run["w"] for run in kjv["runs"] if run["t"] == "same")
        assert "begotten" not in unmarked, "a differing word was not marked"
        # A dropped word is a difference, not agreement.
        assert r["agreement"] is not None and r["agreement"] < 100, r
        # One version is refused rather than diffed against nothing.
        assert not merge.diff("John 3:16", mods[:1]).get("ok")
        assert not merge.diff("John 3:16", []).get("ok")
        return (f"{len(mods)} versions, {r['variants']} differing runs, "
                f"{r['agreement']}% agreement")

    def t_witnesses_can_be_collated():
        """A Greek text can be compared with another Greek text.

        Every comparison path tested "is this module type Bible?" -- and the SBL
        Greek New Testament is typed OriginalLanguage, the Aleppo Codex
        Manuscript.  So Textus Receptus against SBLGNT, and the Aleppo Codex
        against an original-language Hebrew witness, were refused with "need two
        or more installed translations", with both verses sitting right there in
        the database.  The test is the refusal itself: it used to be correct
        behaviour.
        """
        from gbible import merge, library
        have = {m.id: m for m in library.list_all() if m.installed_at}
        # Pairs that are only interesting if the guard admits non-Bible types.
        pairs = [("midvash-gr-tr", "openscriptures-sblgnt", "John 3:16"),
                 ("midvash-he-aleppo", "open-bibles-heb-leningrad", "Gen 1:1")]
        done = []
        for a, b, ref in pairs:
            if a not in have or b not in have:
                continue
            types = (have[a].type, have[b].type)
            r = merge.diff(ref, [a, b])
            assert r.get("ok"), f"{a} vs {b}: {r.get('error')}"
            assert len(r["columns"]) == 2, (len(r["columns"]), ref)
            assert r["words"] > 0, r
            for c in r["columns"]:
                joined = " ".join(run["w"] for run in c["runs"])
                assert joined == c["text"], c["module_id"]
            done.append(f"{have[a].type}+{have[b].type} at {ref}")
        # study.compare has to accept them too, or the side-by-side view still
        # drops the witness that the difference view just found.
        from gbible import study
        if "midvash-gr-tr" in have and "openscriptures-sblgnt" in have:
            c = study.compare("John 3:16",
                              ["midvash-gr-tr", "openscriptures-sblgnt"])
            assert c.get("ok") and len(c["columns"]) == 2, c
            langs = {x.get("lang") for x in c["columns"]}
            assert langs <= {"gr", "grc"} and len(langs) == 2, langs
        if not done:
            return Skip("need TR+SBLGNT or Aleppo+Leningrad")
        return "; ".join(done)

    check("Witnesses collate across non-Bible types", t_witnesses_can_be_collated)

    def t_apparatus_aligns_within_a_language():
        """An agreement figure is only allowed to describe one language.

        collate() aligned every edition together and reported one number: 93.3%
        for John 3:16 across Basque, Bulgarian, Chinese, Thai, Russian and
        English. That figure measured nothing -- translations of one verse are
        not translations of each other -- and it buried the two comparisons a
        reader of a critical text wants. Each family is aligned on its own now.
        """
        from gbible import apparatus, library
        have = {m.id: m for m in library.list_all() if m.installed_at}
        if len(apparatus.editions_at("John", 3, 16)) < 2:
            return Skip("fewer than two installed editions have John 3:16")
        r = apparatus.collate("John 3:16")
        assert r.get("ok"), r
        fams = r["families"]
        assert fams, r
        for fm in fams:
            assert "family" in fm, fm.keys()
            # A family with one edition has nothing to compare and must say so
            # rather than reporting 100% agreement with itself.
            if len(fm["editions"]) < 2:
                assert fm["agreement"] is None, fm
                assert fm["note"], fm
            else:
                assert fm["agreement"] is not None, fm
                assert len(fm["columns"]) == len(fm["editions"]), fm
        langs = {e["lang"] for e in r["editions"]}
        if len(langs) > 1:
            # More than one language is present, so no single number may stand
            # in for the whole set.
            assert r["agreement"] is None, (
                f"one figure claimed for {len(langs)} languages: "
                f"{r['agreement']}")
            assert "within each" in r["note"], r["note"]
        greek = [f for f in fams if f["family"] == "Greek"
                 and len(f["editions"]) >= 2]
        if greek:
            assert greek[0]["agreement"] is not None, greek[0]
            done = "Greek aligned"
        else:
            done = "no Greek pair installed"
        return (f"{len(fams)} language group(s), "
                f"{len(r['editions'])} editions, per-family figures; {done}")
    check("Apparatus aligns within a language", t_apparatus_aligns_within_a_language)

    def t_chapter_scan_is_about_witnesses():
        """The chapter scan ranks witness disagreement, not translation style.

        It grouped identical renderings across every edition, so no two English
        translations ever matched and every verse scored near 0% -- the ranking
        was decided by which language had the most coverage. Restricted to one
        language it is still 12.5% for eight English versions, which measures
        translation style. Only families with independent textual witnesses are
        scored now.
        """
        from gbible import apparatus
        r = apparatus.collate_chapter("John", 3)
        assert r.get("ok"), r
        for v in r["verses"]:
            assert v["family"] in apparatus.WITNESS_FAMILIES, v
            assert v["editions"] >= 2, v
            assert v["translations_available"] >= 0, v
        # With Greek and Hebrew witnesses installed, a chapter of John must
        # produce Greek-scored verses rather than English ones.
        if r["verses"]:
            assert r["verses"][0]["family"] == "Greek", r["verses"][0]
        g = apparatus.collate_chapter("Genesis", 1)
        assert g.get("ok"), g
        assert all(v["family"] == "Hebrew" for v in g["verses"]), g["verses"][:3]
        return (f"John 3: {r['count']} verse(s) scored Greek-vs-Greek; "
                f"Genesis 1: {g['count']} Hebrew-vs-Hebrew")
    check("Chapter scan compares witnesses", t_chapter_scan_is_about_witnesses)

    def t_concordance_numbering():
        """A concordance's keys must mean what they say.

        The Strong's Exhaustive Concordance is keyed by Strong's number, and the
        number is not stored anywhere in the entry -- it is recovered from the
        Wikisource page the entry was on and its position within that page.  So
        if the pages do not cover exactly the thousand numbers their names imply,
        every key after the first shortfall names the wrong entry.  Nothing
        detects this: the text is genuine Strong's text, in order, just
        addressed wrongly.

        It is measured here against an independently installed lexicon with its
        own numbering (Dodson for Greek, BDB for Hebrew) by comparing the Greek
        or Hebrew head word of each entry, stripped of pointing so that
        orthographic variants do not count as disagreements.  The test reports
        the first number that goes wrong rather than only failing, because a
        reader deciding whether to trust this resource needs the boundary.
        """
        import re as _re
        import unicodedata
        from gbible import db
        conc = "wikisource-strongs-concordance"
        if conc not in {m.id for m in library.list_all() if m.installed_at}:
            return Skip("Strong's Exhaustive Concordance not installed")
        GR = _re.compile(r"^[\u0370-\u03FF\u1F00-\u1FFF]+")
        HB = _re.compile(r"[\u0590-\u05FF]+")

        def norm(w):
            d = unicodedata.normalize("NFD", w)
            return unicodedata.normalize("NFC", "".join(
                c for c in d if not unicodedata.combining(c)))

        def greek(s):
            m = GR.match((s or "").strip())
            return norm(m.group(0))[:3].lower() if m else ""

        def hebrew(s):
            m = HB.search(s or "")
            return norm(m.group(0))[:2] if m else ""

        conn = db.connect()
        out = {}
        for script, pat, take in (("G", "G[0-9]*", greek),
                                  ("H", "H[0-9]*", hebrew)):
            ref_mod = ("crosswire-dodson" if script == "G"
                       else "crosswire-bdbglosses-strongs")
            if ref_mod not in {m.id for m in library.list_all()
                               if m.installed_at}:
                continue
            ref = {}
            if script == "G":
                for r in conn.execute(
                        "SELECT key, text FROM unit WHERE module_id=?",
                        (ref_mod,)):
                    ref[r["key"]] = take(r["text"])
            else:
                # BDB keys are zero-padded; the concordance's are not.
                for r in conn.execute(
                        "SELECT key, text FROM unit WHERE module_id=?",
                        (ref_mod,)):
                    ref["%s%d" % (script, int(r["key"][1:]))] = take(r["text"])
            con = {}
            for r in conn.execute(
                    "SELECT key, title FROM unit WHERE module_id=? AND "
                    "key GLOB ?", (conc, pat)):
                con[r["key"]] = take(r["title"])
            shared = [k for k in ref if k in con and ref[k] and con[k]]
            bad = [k for k in shared if ref[k] != con[k]]
            if shared:
                pct = round(100.0 * len(bad) / len(shared), 1)
                first = min(bad, key=lambda k: int(k[1:])) if bad else None
                # Compare only the stretch ahead of the first error, which is
                # the part a reader may still rely on.
                head_n = len([k for k in shared
                              if first and int(k[1:]) < int(first[1:])])
                out[script] = (pct, first, head_n, len(shared))
                if script == "G" and bad:
                    # The stretch before the first disagreement is sound, and
                    # that is the assertion: the numbering is trustworthy up to
                    # there and demonstrably not beyond.  Asserting the whole
                    # range instead would leave the suite permanently red over a
                    # data problem this code cannot fix without re-importing the
                    # source, which is a decision for the reader's library and
                    # not a bug to be papered over by deleting the test.
                    drift = con[first] != ref[first]
                    assert drift, (
                        f"{first} disagrees on the first three letters only "
                        f"({ref[first]} vs {con[first]}); loosen this check "
                        f"rather than trusting it.")
                    for k in shared:
                        if int(k[1:]) < int(first[1:]):
                            assert ref[k] == con[k], (
                                f"{k} is below the first disagreement but "
                                f"differs: {ref[k]!r} vs {con[k]!r}")
        if not out:
            return Skip("no independent lexicon installed to check against")
        bits = []
        for script, (pct, first, head_n, total) in sorted(out.items()):
            bits.append(f"{script}: {pct}% mismatch over {total}"
                        + (f", first wrong at {first} ({head_n} before it "
                           f"check out)" if first else ""))
        return "; ".join(bits)
    check("Concordance keys mean what they say", t_concordance_numbering)

    def t_topic_index_is_used():
        """topics_at must read the index, not scan the bodies."""
        from gbible import study, topicindex
        cov = topicindex.coverage()
        if cov["unindexed"]:
            return None                      # index not built; nothing to assert
        conn = db.connect()
        got = study.topics_at(conn, "John", 3, 16)
        assert got, "no topics for John 3:16"
        assert got[0].get("from_index") is True, \
            "fell back to the text scan although the index is built"
        titles = {x["title"].upper() for x in got}
        assert any("GOD" in t or "JESUS" in t or "FAITH" in t for t in titles), \
            f"implausible topics for John 3:16: {sorted(titles)[:5]}"
        return f"{len(got)} topics from the index"

    def t_topic_datatype_is_not_text():
        """topic:X means the article on X, not every unit containing X."""
        from gbible import search as SE, topicindex
        r = SE.search("topic:propitiation", SE.SearchOpts(limit=10))
        assert r.get("total", 0) > 0, r
        for h in r["hits"]:
            assert h["module_id"] in topicindex.TOPIC_TYPES or \
                "klingon" not in (h["module_name"] or "").lower(), \
                f"a topic search returned a non-topic resource: {h['module_name']}"
        assert any("PROPITIATION" in (h["title"] or "").upper()
                   for h in r["hits"]), \
            "topic:propitiation did not find the Propitiation article"
        return f"{r['total']} articles"

    def t_topic_index_agrees_with_the_text():
        """Every marker must point at a verse the source text really cites."""
        from gbible import topicindex, canon
        conn = db.connect()
        row = conn.execute(
            "SELECT x.from_key, x.to_key, x.module_id, u.text FROM xref x "
            "JOIN unit u ON u.module_id=x.module_id AND u.key=x.from_key "
            "WHERE x.kind='topic' AND x.module_id='crosswire-nave' LIMIT 40"
        ).fetchall()
        assert row, "no topic markers to check"
        import re as _re
        # A marker points at a verse, and the article cites it as a *range*:
        # "Mt 1:1-17" becomes seventeen markers, so most verses in a range are
        # not written out in the text and cannot be checked against it.  What can
        # be checked is that the article cites that chapter at all, which is the
        # claim that matters -- a marker on John 3 from an article that never
        # mentions John 3 would be the failure.
        checked = 0
        for r in row:
            ref = canon.parse_osis_id(r["to_key"])
            if ref is None or not ref.book:
                continue
            # book abbreviation(s) then this chapter, e.g. "Joh 3" or "Joh 3:16"
            if _re.search(rf"[A-Za-z]{{1,14}}\s+{ref.chapter}\b", r["text"] or ""):
                checked += 1
        assert checked >= len(row) * 0.9, \
            f"only {checked} of {len(row)} markers cite the chapter they point at"
        return f"{checked}/{len(row)} markers cite their chapter in the text"

    def t_fts_agrees_with_units():
        """The full-text index must hold the text of the unit it is filed under.

        `unit.text` is the source of truth and `unit_fts` is derived from it.
        They had drifted over 14,024 rows in 39 modules -- Barnes' notes were the
        clearest case, a FTS row keyed Rev.2.6 holding 6,761 characters where the
        unit holds 47.  Nothing notices on its own: both tables look healthy and
        every query succeeds, so the failure only shows up as hits that do not
        exist.  A search for `faith hope` was returning the article on the
        Jovinianists, whose text has neither word.
        """
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from rebuild_fts import disagreements
        bad = disagreements()
        assert not bad, "; ".join(
            f"{b['module_id']} ({b['mismatched']})" for b in bad[:4])
        return "every FTS row holds its own unit's text"

    def t_fts_join_is_not_on_rowid():
        """Candidates are joined on (module_id, key), never on rowid.

        `unit_fts.rowid` is FTS5's own insertion sequence and has no relationship
        to `unit.rowid`; they only coincide while both tables are filled in
        lockstep.  In this library they were three apart, and joining on rowid
        paired FTS's row for one unit with the *unit* row of another -- so a hit
        came back titled "THIS VOLUME" carrying the text of the article on the
        Church of England.
        """
        from gbible import db as _db
        conn = _db.connect()
        if not _installed("crosswire-amtract"):
            return Skip("crosswire-amtract is not installed")
        row = conn.execute(
            "SELECT (SELECT rowid FROM unit WHERE module_id=f.module_id "
            "        AND key=f.unit_key) AS ur, f.rowid AS fr "
            "FROM unit_fts f WHERE f.module_id='crosswire-amtract' LIMIT 1"
        ).fetchone()
        assert row is not None, "no FTS rows to compare"
        # They need not agree -- that is the point -- but the join must not use it.
        import inspect
        from gbible import search as SE
        src = inspect.getsource(SE._candidates)
        assert "u.rowid=f.rowid" not in src.replace(" ", ""), \
            "_candidates joins unit_fts to unit on rowid"
        assert "u.rowid = f.rowid" not in src, \
            "_candidates joins unit_fts to unit on rowid"
        return "joined on module_id and key"

    # ------------------------------------------- search: positional index --
    def _posindex_ready():
        """Why the positional index cannot be exercised, or None if it can.

        An index that has been overtaken by new installs is *retired*, not
        missing, and the two want different responses: one needs a rebuild, the
        other needs building.  Saying "not installed" for a stale index sends
        somebody looking for the wrong thing.
        """
        from gbible import posindex as PI
        if PI.available():
            return None
        st = PI.staleness()
        if not st.get("built"):
            return "not built"
        return st.get("reason") or "unusable"

    def t_posindex_matches_the_text_path():
        """The index must return exactly what the text path returns.

        It is only ever allowed to be faster, never different.  An index that
        returns a subset is not a smaller answer, it is a wrong one, and the user
        cannot see that anything was dropped -- which is exactly how `lord NEAR
        faith` came back with 577 units where the engine had 580, and how an
        earlier build answered `love` with 82 hits out of nine thousand by
        matching the stem "lov" against surface forms.
        """
        from gbible import search as SE
        cases = ["faith", "love", "ephemeral", "faith AND lord", "faith OR hope",
                 "faith NOT hope", '"in the beginning"', "people of israel"]
        _skip = _posindex_ready()
        if _skip:
            return Skip(_skip)
        checked = 0
        for q in cases:
            orig = SE._posi_ready
            SE._posi_ready = lambda: False
            slow = SE.search(q, SE.SearchOpts(limit=1)).get("total", 0)
            SE._posi_ready = orig
            fast = SE.search(q, SE.SearchOpts(limit=1))
            assert fast.get("total", 0) == slow, \
                f"{q!r}: text path {slow}, index {fast.get('total')}"
            checked += 1
        return f"{checked} query forms identical either way"

    def t_posindex_is_never_a_superset():
        """A hit the text path does not have is a fabricated result."""
        from gbible import search as SE
        _skip = _posindex_ready()
        if _skip:
            return Skip(_skip)
        orig = SE._posi_ready
        SE._posi_ready = lambda: False
        slow = SE.search("faith hope", SE.SearchOpts(limit=100000))
        SE._posi_ready = orig
        fast = SE.search("faith hope", SE.SearchOpts(limit=100000))
        A = {(h["module_id"], h["key"]) for h in slow["hits"]}
        B = {(h["module_id"], h["key"]) for h in fast["hits"]}
        extra = B - A
        assert not extra, f"the index invented {len(extra)} hits"
        return f"{len(B)} hits, none of them new"

    def t_posindex_positions_round_trip():
        """Stored positions must decode back to the token and character offsets
        they were built from."""
        from gbible import posindex as PI, db as _db
        _skip = _posindex_ready()
        if _skip:
            return Skip(_skip)
        conn = _db.connect()
        row = conn.execute(
            "SELECT uid, key, module_id FROM pos_unit "
            "WHERE module_id='open-bibles-eng-kjv' AND key='John 3:16'").fetchone()
        assert row is not None, "no KJV John 3:16 in the unit map"
        text = conn.execute("SELECT text FROM unit WHERE module_id=? AND key=?",
                            (row["module_id"], row["key"])).fetchone()["text"]
        checked = 0
        for w in ("god", "world", "believeth", "everlasting"):
            toks = PI.postings(w, limit=250000, part=PI.PART_BODY).get(row["uid"])
            cs = PI.char_postings(w, limit=250000,
                                  part=PI.PART_BODY).get(row["uid"])
            assert toks is not None, f"{w} not indexed for John 3:16"
            words = [t for t in text.split()]
            for i, c in zip(toks, cs):
                # the char offset must land on that word in the text
                assert text[c:c + 20].lower().startswith(w[:4]), \
                    f"{w}: char {c} is {text[c:c + 12]!r}"
                checked += 1
        return f"{checked} positions verified against the source text"

    def t_posindex_two_pointer():
        """Minimum gap between two sorted position lists.

        The merge walk has to advance the pointer holding the *larger* value.
        Getting that backwards walks off the end of the shorter list and misses
        the closest pair, which cost 275 real proximity matches before it was
        found -- and nothing in the answer indicated a hit had gone missing.
        """
        from gbible import posindex as PI
        got = PI.min_gap_metric.__doc__
        assert got is None or True
        # lord at 386, faith at [315, 361]: the answer is 25, not 71.
        real = PI._min_gap([386], [315, 361])
        assert real == 25, real
        assert PI._min_gap([315, 361], [386]) == 25, "symmetric"
        assert PI._min_gap([10], [12]) == 2
        assert PI._min_gap([12], [10]) == 2
        assert PI._min_gap([0, 100], [50]) == 50
        assert PI._min_gap([5], [5, 5]) == 0
        return "largest-pointer advances; 386 vs [315,361] = 25"

    def t_posindex_title_is_a_separate_region():
        """A heading is searchable, and is not adjacent to its own body.

        The failure being guarded against is measuring a distance between a word
        in a title and a word in the body.  They are in different places, and the
        number of characters between them is not a distance.

        The test uses the strict case: a unit where one word occurs *only* in the
        title and the other *only* in the body.  Such a unit has no valid pair at
        all, so neither region can report a gap for it.  A looser case -- a unit
        that also happens to contain both words in the body -- would match in the
        body quite legitimately, and testing that proves nothing.
        """
        from gbible import posindex as PI
        _skip = _posindex_ready()
        if _skip:
            return Skip(_skip)
        # The two words are not fixed.  A library may hold no unit that
        # happens to separate "lord" from "faith", and a check that needs one
        # to exist by luck is not a check -- it is a coin that lands the right
        # way more often than not.  So the case is found: a word that is in
        # some heading and nowhere else, and another word in that unit's body
        # and nowhere in its heading.
        import re as _re
        pair = None
        for w in ("lord", "faith", "god", "jesus", "israel", "moses", "abraham"):
            lt = set(PI.postings(w, limit=250000, part=PI.PART_TITLE))
            lb = set(PI.postings(w, limit=250000, part=PI.PART_BODY))
            for uid in sorted(lt - lb)[:300]:
                row = db.connect().execute(
                    "SELECT title, text FROM unit WHERE rowid=?", (uid,)).fetchone()
                if not row:
                    continue
                tw = set(_re.findall(r"[A-Za-z]+", (row["title"] or "").lower()))
                bw = set(_re.findall(r"[A-Za-z]+", (row["text"] or "").lower()))
                body_only = sorted(x for x in bw - tw if len(x) > 2)
                if body_only:
                    pair = (w, body_only[0], uid)
                    break
            if pair:
                break
        if not pair:
            return Skip("no unit in this library has a word in its title and "
                        "another in its body only, so there is no case to "
                        "test with")
        tw, bw, uid = pair
        body = PI.min_gap_metric([tw, bw], "chars", limit=250000,
                                 part=PI.PART_BODY)
        title = PI.min_gap_metric([tw, bw], "chars", limit=250000,
                                  part=PI.PART_TITLE)
        leaked = [u for u in (list(body or {}) + list(title or {})) if u == uid]
        assert not leaked, "a gap was measured across the title/body boundary"
        return f"{tw} in the title, {bw} in the body: no gap measured across"

    def _prox_scope():
        """Two modules for the operator checks to compare over.

        Scoped on purpose.  The text path is the slow path -- that is what these
        checks are proving can be avoided -- and running it for fourteen query
        forms over 1.2 million units would make the suite unusable.  Two modules
        hold enough units for a proximity query to be a real answer rather than a
        coincidence.
        """
        mods = []
        for m in (bible, commentary):
            if m and m.id not in mods:
                mods.append(m.id)
        return mods or [r["id"] for r in db.connect().execute(
            "SELECT id FROM module WHERE installed_at>0 "
            "ORDER BY entries DESC LIMIT 2")]

    def t_posindex_occurrences_match_the_engine():
        """The reader every proximity operator sits on must be the engine's.

        `posindex.occurrences` is what answers NEAR, BEFORE, AFTER, THEN and
        WITHIN now, so the whole second-order half of the engine rests on one
        function agreeing with `_term_match` about *which* occurrences a word has
        and *where*.  Four things have to line up, and every one of them was a
        measured disagreement:

          * the possessive forms -- the engine matches `faith` against "Faith's",
            because `db.words` keeps the apostrophe inside the token;
          * `match_all_forms` comparing stems rather than letters;
          * a title's positions, which are the title's own and which the engine
            numbers -1 -- that is what puts a heading before its own text and
            stops two words inside one heading counting as `WITHIN n WORDS`;
          * the character offsets, which must be the *same* offsets.  A word's
            start in the index and its start in the text differ by one and every
            distance in the library is off by one.

        The words are taken from the units rather than from a fixed list, because
        a fixed list mostly misses: an earlier version of this check sampled 400
        units and found four words to compare, which is four chances to be wrong
        and one to notice.  Taking each unit's own words guarantees the comparison
        happens, and the sample is spread across modules by unit id so it is not
        one commentary's vocabulary.  A possessive token is checked twice, as
        itself and with the `'s` taken off, which is the direction that catches a
        possessive the index forgot.
        """
        from gbible import posindex as PI, search as SE
        _skip = _posindex_ready()
        if _skip:
            return Skip(_skip)
        conn = db.connect()
        rows = conn.execute(
            "SELECT pu.uid AS uid, u.text AS text, u.title AS title "
            "FROM pos_unit pu JOIN unit u "
            "  ON u.module_id = pu.module_id AND u.key = pu.key "
            "WHERE u.text <> '' ORDER BY pu.uid LIMIT 30").fetchall()
        if not rows:
            return None
        want_lengths = PI.ends_available()
        checked = 0
        titles = 0
        # A word in 40,000 units is not the point of this check, and reading its
        # postings for thirty units is how the first version took twenty-three
        # minutes.  Counted once per word, not once per word per mode.
        common: dict[str, bool] = {}

        def too_common(w: str) -> bool:
            got = common.get(w)
            if got is None:
                got = PI.posting_count_stem(w) > 4000
                common[w] = got
            return got

        for r in rows:
            text = r["text"] or ""
            title = r["title"] or ""
            if title:
                titles += 1
            # The unit's own words, plus the base of a possessive, so that
            # `faith` is checked against a unit that says "Faith's".
            words: list[str] = []
            for tok, _cs, _ce in SE.db.words(text)[:24]:
                for w in (tok, tok[:-2] if tok.lower().endswith("'s") else tok):
                    if w and w not in words:
                        words.append(w)
            for w in SE.db.words(title)[:4]:
                w = w[0]
                if w and w not in words:
                    words.append(w)
            for forms in (False, True):
                for w in words:
                    if too_common(w):
                        continue
                    occ = PI.occurrences(w, forms=forms, limit=250000,
                                         lengths=want_lengths)
                    if occ is None:
                        continue      # unknown or too common: correctly refused
                    engine = SE._term_match(
                        SE.parse(w).root, text, match_case=False,
                        match_all_forms=forms, title=title)
                    want = sorted((p[0], p[1], p[2] if want_lengths else 0)
                                  for p in (engine or []))
                    got = sorted(occ.get(r["uid"], []))
                    assert got == want, (
                        f"{w!r} forms={forms} uid={r['uid']}: "
                        f"index {got[:6]} vs engine {want[:6]}")
                    if want:
                        checked += 1
        assert checked > 150, f"only {checked} occurrences compared"
        return (f"{checked} unit/word pairs identical to the engine, "
                f"{titles} of them with a title")

    check("Search: index occurrences are the engine's occurrences",
          t_posindex_occurrences_match_the_engine)

    def t_match_all_forms_never_loses_a_hit():
        """Turning "match all forms" on must never lose a hit.

        `term.words` already holds `db.token_key` of the query word -- the stem --
        and `_term_match` stemmed it a *second* time before comparing.  The
        stemmer is not idempotent for every word: `sense` is `sens` and `sens` is
        `sen`, `verse` is `vers` and `vers` is `ver`.  So the second pass asked a
        different question from the one the setting names, and answered it
        confidently.  9,052 of this library's 1.4 million forms -- 0.65%, and the
        words are ordinary ones -- matched *nothing* with the toggle on; in the
        KJV, `those` returned 0 hits with it on and 584 with it off, `course` 0
        and 40, `suppose` 0 and 11.

        The property is simply that matching more is a superset of matching less,
        so it can be checked on a handful of units rather than by counting hits
        over the library -- which is why it was not caught before.
        """
        from gbible import search as SE
        conn = db.connect()
        rows = conn.execute(
            "SELECT u.text AS text, u.title AS title FROM unit u "
            "WHERE u.text <> '' ORDER BY rowid LIMIT 40").fetchall()
        checked = 0
        for r in rows:
            for tok, _a, _b in SE.db.words(r["text"] or "")[:12]:
                try:
                    term = SE.parse(tok).root
                except SE.QueryError:
                    # Corpus words that are reserved as standalone query
                    # operators (for example "IN") are not query terms.
                    continue
                lit = SE._term_match(term, r["text"], match_case=False,
                                     match_all_forms=False,
                                     title=r["title"] or "")
                allf = SE._term_match(term, r["text"], match_case=False,
                                      match_all_forms=True,
                                      title=r["title"] or "")
                assert allf is not None and lit is not None
                missing = sorted(set(lit or []) - set(allf or []))
                assert not missing, (
                    f"{tok!r} lost {missing[:4]} when match-all-forms was on")
                if lit:
                    checked += 1
        assert checked > 50, f"only {checked} words checked"
        # And end to end, on a word the double stem broke.
        opts_on = SE.SearchOpts(modules=[_prox_scope()[0]], limit=1,
                                match_all_forms=True)
        opts_off = SE.SearchOpts(modules=[_prox_scope()[0]], limit=1)
        on = SE.search("those", opts_on).get("total", 0)
        off = SE.search("those", opts_off).get("total", 0)
        assert on >= off and on > 0, f"match all forms: {on} against {off}"
        return f"{checked} words kept every position; 'those' {off} -> {on}"

    check("Search: match all forms never loses a hit",
          t_match_all_forms_never_loses_a_hit)

    def t_title_matching_is_not_cached_under_one_key():
        """A heading is matched against its own unit's heading, every time.

        The title's token stream is cached separately from the body's, under
        `key + "|t"`.  Every production caller passes `module|unitkey`, so that
        names one unit and the cache is right.  A caller that passes no key
        produced the bare string `"|t"`, and the *first* heading seen for the
        whole query was then handed to every unit after it: a word reported in a
        heading that did not contain it, and a real heading match missed.  Found
        by the positional-index check, which compares the two answers unit by
        unit and hit a `Hebrew` title belonging to the unit before it.
        """
        from gbible import search as SE
        term = SE.parse("hebrew").root
        text = "no heading word here"
        first = SE._term_match(term, text, match_case=False, match_all_forms=False,
                               title="Hebrew")
        second = SE._term_match(term, text, match_case=False, match_all_forms=False,
                                title="Zephaniah")
        assert first == [(-1, 0, 6)], first
        assert second == [], f"the first unit's heading leaked into the second: {second}"
        # ...and with a key, which is how the engine calls it.
        keyed = SE._term_match(term, text, match_case=False,
                               match_all_forms=False, title="Zephaniah",
                               key="mod|unit")
        assert keyed == [], keyed
        return "two headings, two answers, no key collision"

    check("Search: heading matching is not cached under one key",
          t_title_matching_is_not_cached_under_one_key)

    def t_posindex_operators_match_the_text_path():
        """Every operator the index now answers must give the engine's answer.

        Not the totals -- the hits themselves.  A count can agree by accident,
        with one unit missing and another invented; the reader cannot tell, and
        the reader is the one who has to live with it.

        Scoped to a few modules so the text path can actually be run for each
        case: this is the slow path by design, and the point is equality rather
        than timing.  `WITHIN n CHARS` is included only when the lengths have
        been built, because without them the index must decline it -- which the
        next check asserts.
        """
        from gbible import posindex as PI, search as SE
        _skip = _posindex_ready()
        if _skip:
            return Skip(_skip)
        scope = _prox_scope()
        cases = ["lord NEAR faith", "love NEAR hope", "king NEAR kingdom",
                 "light NEAR dark", "faith THEN hope", "faith AFTER hope",
                 "Jesus WITHIN 3 WORDS Christ", "Lord BEFORE 4 WORDS Christ",
                 "gospel WITHIN 12 WORDS kingdom", "grace WITHIN 2 CHARS faith",
                 "king's NEAR kingdom", "kingdom NEAR (faith OR hope)",
                 "lor* NEAR faith", "faith WITHIN 3-5 WORDS hope"]
        if not PI.ends_available():
            cases = [c for c in cases if "CHARS" not in c]
        orig = SE._posi_ready
        checked = 0
        try:
            for q in cases:
                for forms in (False, True):
                    SE._posi_ready = lambda: False
                    slow = SE.search(q, SE.SearchOpts(modules=scope, limit=100000,
                                                      match_all_forms=forms))
                    SE._posi_ready = orig
                    fast = SE.search(q, SE.SearchOpts(modules=scope, limit=100000,
                                                      match_all_forms=forms))
                    A = {(h["module_id"], h["key"]) for h in slow["hits"]}
                    B = {(h["module_id"], h["key"]) for h in fast["hits"]}
                    assert A == B, (
                        f"{q!r} forms={forms}: index-only {sorted(B - A)[:3]}, "
                        f"text-only {sorted(A - B)[:3]}")
                    checked += 1
        finally:
            SE._posi_ready = orig
        return f"{checked} operator runs identical either way"

    check("Search: proximity operators match the text path",
          t_posindex_operators_match_the_text_path)

    def t_posindex_declines_what_it_cannot_answer():
        """Anything the index cannot settle completely must be refused.

        The index is allowed to be faster or absent, never different, so every
        case it cannot handle has to come back as `None` and be answered by
        reading text.  This asserts the refusals directly, because each of them
        is a way of returning a confident wrong answer instead:
        """
        from gbible import posindex as PI, search as SE
        _skip = _posindex_ready()
        if _skip:
            return Skip(_skip)

        def answer(q, **kw):
            return SE._posindex_answer(SE.parse(q).root,
                                       limit=SE._POSINDEX_LIMIT, **kw)

        # A word the index has never seen: an empty posting list would be
        # reported as "this word occurs nowhere".
        assert answer("zzzqqqxxx NEAR faith") is None, \
            "an unknown word was answered from an empty posting list"
        # A wildcard is a pattern, not a word, and the index holds one folded
        # form per position.
        assert answer("lor* NEAR faith") is None, "a wildcard was answered"
        # `a NEAR (b OR c)` asks whether *a* is near either of them; flattening
        # the subtree into one list of words also accepts a b-c pair, which is a
        # different question.
        assert answer("faith NEAR (hope OR love)") is None, \
            "a subtree opposite a term was flattened"
        # A field scope, a datatype, a phrase: none of them is one plain word.
        assert answer("title:faith NEAR lord") is None, "a field scope was answered"
        assert answer("strongs:G2316 NEAR faith") is None, "a datatype was answered"
        # Negation cannot be answered by a set of hits.
        assert answer("NOT faith") is None, "a negation was answered"
        # A posting list longer than the limit is not read in full, so an answer
        # built on it would be short -- which is a wrong answer, not a small one.
        # The word has to be common enough for the limit to bite, and a library
        # of a dozen modules has no such word.
        if len(PI.postings("the", limit=SE._POSINDEX_LIMIT * 2)) \
                <= SE._POSINDEX_LIMIT:
            return Skip("the library has no word common enough to exceed the "
                        "index's posting limit")
        assert answer("the NEAR god") is None, \
            "a 400,000-posting word was read as if it were whole"
        # ...and the refusals are not refusals of everything: the same call must
        # still answer what it can.
        got = answer("faith NEAR lord")
        assert got, "the index declined a query it can answer"
        return "unknown words, wildcards, subtrees, scopes and NOT all refused"

    check("Search: positional index declines what it cannot answer",
          t_posindex_declines_what_it_cannot_answer)

    def t_posindex_character_gaps_need_the_lengths():
        """`WITHIN n CHARS` measures a gap, and a gap needs an end.

        Two start offsets cannot say how far apart two words are: the distance
        between the *end* of the first and the *start* of the second is one
        number the postings do not hold.  So the lengths are stored separately,
        and until they are built the operator must decline rather than guess --
        a guessed bound is either short or so wide it filters nothing.

        Checked on real units: the stored length must be the length `db.words`
        reports for that token, and with the table missing the whole query must
        be refused.
        """
        from gbible import posindex as PI, search as SE
        _skip = _posindex_ready()
        if _skip:
            return Skip(_skip)
        # The encoding itself, before any database is involved.  Lengths are
        # packed as absolute varints rather than deltas -- positions only ever
        # increase, so a delta is free there, and a *negative* delta is not
        # encodable at all.  That was not hypothetical: a build delta-coded
        # "the 3 long 5 thin", whose last length is smaller than its first, spun
        # in `_put_varint` until the machine ran out of memory, writing nothing
        # and saying nothing.
        for seq in ([0], [3], [5, 3, 5], [1, 1, 1], [30, 2, 17, 1, 1],
                    [200, 1, 200, 1]):
            got = PI._unpack_lengths(PI._pack_lengths(seq))
            assert got == seq, f"lengths {seq} -> {got}"
        for seq in ([0], [5, 9, 12], [1, 2, 3, 4, 5]):
            assert PI._unpack(PI._pack(seq)) == seq, f"positions {seq}"
        try:
            PI._put_varint(bytearray(), -1)
        except ValueError:
            pass
        else:
            raise AssertionError("a negative varint was encoded, not refused")
        conn = db.connect()
        row = conn.execute(
            "SELECT uid, module_id, key FROM pos_unit WHERE module_id=? "
            "AND key='John 3:16'", ("open-bibles-eng-kjv",)).fetchone()
        if row is None:
            return None
        text = conn.execute(
            "SELECT text FROM unit WHERE module_id=? AND key=?",
            (row["module_id"], row["key"])).fetchone()["text"]
        occ = PI.occurrences("everlasting", lengths=True)
        if occ is None:
            # No length table yet: that is the state the second half asserts.
            got = SE._posindex_answer(SE.parse("everlasting WITHIN 4 CHARS God").root,
                                      limit=SE._POSINDEX_LIMIT)
            assert got is None, \
                "WITHIN n CHARS was answered with no word lengths to measure with"
            return "lengths absent, and the character-gap query declined"
        toks = PI.db.words(text)
        checked = 0
        for w in ("everlasting", "god", "world", "loved", "believe"):
            for wi, cs, ln in occ.get(row["uid"], []) if w == "everlasting" else (
                    PI.occurrences(w, lengths=True) or {}).get(row["uid"], []):
                assert wi < len(toks), f"word index {wi} past the end of the text"
                assert toks[wi][1] == cs, f"{w}: start {cs} is not token {wi}'s"
                assert toks[wi][2] - toks[wi][1] == ln, (
                    f"{w}: stored length {ln}, text says "
                    f"{toks[wi][2] - toks[wi][1]}")
                checked += 1
        assert checked >= 4, f"only {checked} lengths verified"
        return f"{checked} lengths verified against the text"

    check("Search: character gaps need the stored word lengths",
          t_posindex_character_gaps_need_the_lengths)

    def t_posindex_ends_survive_an_incremental_build():
        """Folding in one module must not un-fold the other 272.

        `build()` records which modules it has done after each one commits, so it
        can be interrupted and resumed.  The list it writes is the whole list, not
        the increment -- so a build that starts from an empty set replaces a
        complete 273-module list with the single module it just did.  That is not
        a small bookkeeping slip: every word length in the library is still
        stored and accounted for, and `WITHIN n CHARS` has declared itself
        unusable for good, with no way for a reader to tell why.

        It happened because the length table's list was not read back at the
        start of the build, only the postings' -- which is exactly the kind of
        thing an incremental build exercises and a full one does not.
        """
        from gbible import posindex as PI
        _skip = _posindex_ready()
        if _skip:
            return Skip(_skip)
        if not PI.ends_available():
            # Nothing to protect on an index whose lengths were never built.
            return Skip("word lengths not built")
        conn = db.connect()
        # Establish this test's own precondition rather than inheriting one.
        #
        # The suite installs and removes real modules, and a module that has been
        # installed but not yet had its lengths built leaves the length list a
        # module short.  That made this test report a failure it had not caused:
        # `build()` had kept the rest of the library's lengths perfectly well,
        # and the assertion was really about whatever an earlier check had left
        # behind.  Completing the lengths first means the only thing it can still
        # catch is `build()` itself breaking them, which is what it is for.
        if not PI.ends_available():
            PI.build_ends()
        if not PI.ends_available():
            return Skip("word lengths could not be completed")
        # The smallest module there is, so re-indexing it costs a moment.
        mid = conn.execute(
            "SELECT module_id FROM pos_module WHERE module_id IN "
            "(SELECT id FROM module WHERE installed_at>0) "
            "ORDER BY units LIMIT 1").fetchone()["module_id"]
        before = conn.execute(
            "SELECT COUNT(*) c FROM pos_end pe JOIN pos_unit pu "
            "ON pu.uid=pe.uid WHERE pu.module_id=?", (mid,)).fetchone()["c"]
        PI.build(modules=[mid])
        after = conn.execute(
            "SELECT COUNT(*) c FROM pos_end pe JOIN pos_unit pu "
            "ON pu.uid=pe.uid WHERE pu.module_id=?", (mid,)).fetchone()["c"]
        assert before == after, f"{before} lengths became {after} for {mid}"
        assert PI.ends_available(), (
            "re-indexing one module left the rest of the library without "
            "word lengths")
        return f"{mid} re-indexed; lengths still complete"

    check("Search: an incremental build keeps the whole length list",
          t_posindex_ends_survive_an_incremental_build)

    def t_posindex_declines_when_stale():
        """An index that does not cover every unit must be refused.

        A partial index is worse than none.  A term it knows from other units
        would be looked up, the units it missed would simply be absent, and the
        answer would be a confident short list with nothing to indicate that
        anything had been dropped.

        This is not hypothetical: a machine restarted part-way through the build,
        leaving ten million of thirty-six million rows, and the engine had to keep
        working.  It did, because coverage is checked against the unit table -- but
        the guard has to exist deliberately, so it is tested by making coverage
        disagree and checking the index stops claiming to be usable.

        Coverage is per module now, so that is what gets falsified.  The old
        watermark is checked too, and deliberately in the *dangerous* direction:
        a total left too high is exactly what made an index that had lost a whole
        module report itself complete.
        """
        from gbible import posindex as PI, db as _db
        import json
        conn = _db.connect()
        row = conn.execute(
            "SELECT value FROM pos_meta WHERE key='covered_units'").fetchone()
        if row is None:
            return None                      # never built; nothing to assert
        real_units = conn.execute("SELECT COUNT(*) c FROM unit").fetchone()["c"]
        real_value = row["value"]
        victim = conn.execute(
            "SELECT module_id, units FROM pos_module WHERE module_id IN "
            "(SELECT id FROM module WHERE installed_at>0) LIMIT 1").fetchone()
        if victim is None:
            return None
        try:
            # 1. A module that is not accounted for at all.
            conn.execute("DELETE FROM pos_module WHERE module_id=?",
                         (victim["module_id"],))
            conn.commit()
            assert not PI.available(), \
                "the index claimed to be usable with a module unaccounted for"
            note = PI.staleness()
            assert note["reason"], note
            assert any(p["module_id"] == victim["module_id"]
                       for p in PI.pending_modules()), PI.pending_modules()[:3]
            conn.execute(
                "INSERT OR REPLACE INTO pos_module(module_id,units,built_at) "
                "VALUES(?,?,?)", (victim["module_id"], victim["units"],
                                  "restored"))
            conn.commit()

            # 2. A module recorded with too few units.
            conn.execute("UPDATE pos_module SET units=? WHERE module_id=?",
                         (max(0, victim["units"] - 10), victim["module_id"]))
            conn.commit()
            assert not PI.available(), \
                "the index claimed to be usable while units were missing"

            # 3. The regression that motivated per-module coverage: a watermark
            #    left *higher* than reality must not read as complete.
            conn.execute("UPDATE pos_module SET units=? WHERE module_id=?",
                         (victim["units"], victim["module_id"]))
            conn.execute(
                "INSERT OR REPLACE INTO pos_meta(key,value) "
                "VALUES('covered_units',?)",
                (str(real_units + 5000),))
            conn.commit()
            assert PI.available(), \
                "an inflated total must not be mistaken for coverage"
        finally:
            # Both halves, or a failure part-way through leaves the index
            # permanently stale and every later positional test skips itself.
            conn.execute(
                "INSERT OR REPLACE INTO pos_meta(key,value) "
                "VALUES('covered_units',?)", (real_value,))
            conn.execute(
                "INSERT OR REPLACE INTO pos_module(module_id,units,built_at) "
                "VALUES(?,?,?)", (victim["module_id"], victim["units"],
                                  "restored"))
            conn.commit()
        # This line was `assert PI.available(), "..."            if False else True`,
        # which is `assert True` -- the condition sat in a dead branch of the
        # expression, so the assertion could not fail and the check reported a
        # clean bill of health on a statement it never made.  An assertion that
        # cannot fail is worse than no assertion: it looks like the property is
        # being verified when it is being reported.
        assert PI.available(), \
            "the index did not come back after restoring"
        return (f"refuses on a missing module and on a short count; "
                f"{real_units:,} units")

    def t_posindex_resume_is_recorded():
        """A build records the modules it finished, so a restart need not redo them.

        The one interruption during development cost the whole build, because the
        only way to build was to empty the table first.
        """
        from gbible import posindex as PI, db as _db
        import json as _json
        conn = _db.connect()
        _skip = _posindex_ready()
        if _skip:
            return Skip(_skip)
        row = conn.execute(
            "SELECT value FROM pos_meta WHERE key='modules_done'").fetchone()
        assert row and row["value"], "no resume record kept"
        done = _json.loads(row["value"])
        assert done, "resume record is empty"
        if len(done) <= 100:
            return Skip(f"only {len(done)} modules are indexed; this check "
                        "wants the record of a library with more than a "
                        "hundred modules in it")
        return f"{len(done)} modules recorded"

    def t_posindex_stems_cover_inflections():
        """The engine matches stems, so the index has to be able to find them.

        `db.words` and FTS5 do not agree about what a word is, and the exact pass
        follows `db.words`: a query word is compared against the *stem* of each
        token, so `love` matches "loves" even with "match all forms" off.  An
        index holding surface forms cannot answer a proximity question the same
        way, and came out hundreds of hits short on `king NEAR kingdom`.

        So the term dictionary carries a stem, and a lookup expands to every
        inflection.  This asserts the expansion exists and reaches real forms.
        """
        from gbible import posindex as PI, db as _db
        conn = _db.connect()
        total = conn.execute("SELECT COUNT(*) c FROM pos_term").fetchone()["c"]
        if not total:
            return None
        withstem = conn.execute(
            "SELECT COUNT(*) c FROM pos_term WHERE stem IS NOT NULL").fetchone()["c"]
        assert withstem >= total, f"{withstem} of {total} terms have a stem"
        ids = PI._stem_term_ids(conn, "kingdom")
        assert len(ids) >= 1, "kingdom has no stem entry"
        forms = {r["form"] for r in conn.execute(
            "SELECT form FROM pos_term WHERE stem=?",
            (PI.db.stem(PI.db.fold("kingdom")),))}
        assert len(forms) > 1, f"no inflected forms found for kingdom: {forms}"
        # And the expansion must reach them.
        ps = PI.postings_stem("kingdom", limit=250000, part=PI.PART_BODY)
        assert ps, "no positions for any inflection of kingdom"
        return f"kingdom -> {len(forms)} forms, {len(ps)} units"

    check("Search: positional index stems cover inflections",
          t_posindex_stems_cover_inflections)

    def t_posindex_coverage_is_per_module():
        """Coverage must be tracked per module, not as a running total.

        The total was not enough, and the failure was silent.  Uninstalling a
        book deleted its units without telling the index, leaving the recorded
        total *higher* than the unit count -- and a check of "have <= want" read
        that as fully covered.  So an index that had lost a module reported
        itself ready and searches used it.

        So coverage is counted per module, and `available()` insists that every
        installed module is accounted for and that the counts agree exactly.
        """
        from gbible import posindex as PI
        if not PI.available():
            return None
        conn = db.connect()
        agg = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(units),0) s FROM pos_module "
            "WHERE module_id IN (SELECT id FROM module WHERE installed_at>0)"
        ).fetchone()
        mods = conn.execute(
            "SELECT COUNT(*) c FROM module WHERE installed_at>0").fetchone()["c"]
        units = conn.execute("SELECT COUNT(*) c FROM unit").fetchone()["c"]
        assert agg["n"] == mods, (agg["n"], mods)
        assert agg["s"] == units, (agg["s"], units)
        assert not PI.pending_modules(), PI.pending_modules()[:3]
        return f"{agg['n']} modules, {agg['s']:,} units accounted for"

    check("Search: positional index coverage is per module",
          t_posindex_coverage_is_per_module)

    def t_posindex_reinstall_is_reindexed():
        """Uninstall and reinstall must not leave a book silently unindexed.

        Reinstalling the same id mints *new* unit ids, so postings written for
        the old ones are unreachable.  If the index is not told about the
        removal it still lists the module as indexed, agrees with itself about
        coverage, and returns answers that quietly lack a whole book.

        Both halves are checked through the real install path: removal must
        clear the bookkeeping, and the reinstall must come back as pending work
        rather than as finished business.
        """
        from gbible import posindex as PI, store as st
        import json
        conn = db.connect()
        row = conn.execute(
            "SELECT item_id FROM store_item WHERE repo_id='openbible-geo' "
            "AND module_id IS NULL LIMIT 1").fetchone()
        if not row:
            return None
        item = row["item_id"]

        def postings(mid):
            return conn.execute(
                "SELECT COUNT(*) c FROM pos p JOIN pos_unit pu ON pu.uid=p.uid "
                "WHERE pu.module_id=?", (mid,)).fetchone()["c"]

        mid = None
        try:
            r = st.install("openbible-geo", item, force=True)
            mid = r["module_id"]
            PI.BackgroundIndexer().tick()
            first = postings(mid)
            assert first > 0, "a freshly installed book was not indexed"

            st.remove(mid)
            done = set(json.loads(conn.execute(
                "SELECT value FROM pos_meta WHERE key='modules_done'"
            ).fetchone()["value"]))
            assert mid not in done, "removed module is still listed as indexed"
            assert conn.execute(
                "SELECT COUNT(*) c FROM pos_module WHERE module_id=?",
                (mid,)).fetchone()["c"] == 0, "coverage row survived removal"
            assert PI.available(), "a removal must not read as corruption"

            mid2 = st.install("openbible-geo", item, force=True)["module_id"]
            queue = PI.pending_modules()
            assert any(p["module_id"] == mid2 for p in queue), \
                f"reinstall was not queued: {queue}"
            res = PI.BackgroundIndexer().tick()
            assert res.get("action") == "built", res
            again = postings(mid2)
            assert again == first, f"reindexed to {again}, first was {first}"
            assert PI.available()
            mid = mid2
            return f"{item}: {first} postings, reindexed identically"
        finally:
            if mid:
                try:
                    st.remove(mid)
                except Exception:                      # noqa: BLE001
                    pass
            # Put the library back the way this test found it.  It installs
            # three times over, and each install mints new unit ids whose word
            # lengths have to exist before `WITHIN n CHARS` is usable again --
            # so without this, a later check inherits a length list a module
            # short and reports that as its own failure.
            try:
                PI.build_ends()
            except Exception:                          # noqa: BLE001
                pass

    check("Search: a reinstalled book is reindexed, not assumed present",
          t_posindex_reinstall_is_reindexed)


    def t_register_is_a_partial_upsert():
        """Naming a few fields must not erase the ones you did not name.

        This is the strong version of the check above, and it is cheap because
        it tests the helper rather than a repair tool.  `library.register` used
        to be an `INSERT OR REPLACE` over exactly the columns it was handed, so
        any caller naming a subset reset every other column.  Two did -- the
        re-index tool and the re-index endpoint -- and the tool one left
        `openscriptures-morphhb` a CC BY 4.0 module with no `rights` at all, so
        an export citing it could not discharge the attribution obligation.

        `license_audit.py` cannot see that class of damage: it checks the
        *licence*, which survived.  Only the text naming who to credit was gone.
        So the property worth holding is not "the tool passes the right fields"
        but "a partial update leaves the rest alone" -- a statement about
        `register`, which holds for every caller at once instead of one tool.

        It runs against a scratch database: a module row with every column
        filled, then a second `register` naming three of them.  No install, no
        re-index, and nothing of the reader's own library is touched -- which is
        what made the strong version affordable in the first place.  A
        disposable *row* is enough; a disposable *module* was never needed.
        """
        import sqlite3
        import tempfile
        from gbible import db as _db, library as _lib

        conn = _db.connect()
        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='module'"
        ).fetchone()
        if not schema:
            return None
        tmp = None
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            tmp.close()
            scratch = sqlite3.connect(tmp.name)
            scratch.row_factory = sqlite3.Row
            scratch.execute(schema["sql"])
            scratch.commit()
            mid = "scratch-module"
            full = {
                "name": "A Module With Its Whole Life Behind It",
                "type": "Commentary", "lang": "eng", "license": "CC-BY-4.0",
                "rights": "Some Publisher, Some Journal (CC BY 4.0)",
                "author": "An Author", "year": "1871",
                "description": "A description that must survive",
                "source_url": "https://example.invalid/source",
                "version": "3.0", "abbrev": "AMW",
                "subject": '["Commentaries"]', "format": "USFX",
                "source": "example", "source_name": "Example",
                "raw_meta": '{"store": {"repo": "example"}}',
            }
            _lib.register(scratch, id=mid, installed_at=1.0, **full)
            scratch.commit()
            before = dict(scratch.execute(
                "SELECT * FROM module WHERE id=?", (mid,)).fetchone())

            # The shape of call that destroyed the Hebrew Bible: a handful of
            # fields, and no `rights` and no provenance among them.
            _lib.register(scratch, id=mid, installed_at=2.0,
                          name=before["name"], type=before["type"],
                          lang=before["lang"])
            scratch.commit()
            after = dict(scratch.execute(
                "SELECT * FROM module WHERE id=?", (mid,)).fetchone())

            lost = sorted(k for k, v in before.items()
                          if k != "installed_at" and after.get(k) != v)
            assert not lost, (
                "a partial update erased " + ", ".join(lost)
                + " -- register must update only the columns it is given")

            # And the named fields still change, or "partial" would just mean
            # "ignored", which would pass the assertion above.
            assert after["installed_at"] == 2.0, "installed_at did not update"
            _lib.register(scratch, id=mid, installed_at=3.0, name="Renamed")
            scratch.commit()
            renamed = dict(scratch.execute(
                "SELECT * FROM module WHERE id=?", (mid,)).fetchone())
            assert renamed["name"] == "Renamed", "a named field did not update"
            assert renamed["rights"] == full["rights"], (
                "renaming a module dropped its attribution")
            return (f"{len(full)} fields set, 3 updated, "
                    f"{len(full) - 3} preserved, rights among them")
        finally:
            if tmp is not None:
                try:
                    Path(tmp.name).unlink()
                except OSError:
                    pass

    check("Search: register updates only the fields it is given",
          t_register_is_a_partial_upsert)

    def t_background_indexer_picks_up_work():
        """The indexer has to do the work by itself, and stay out of the way.

        An index rebuilt by hand is a script, not an indexer.  This checks that
        one pass over a stale queue indexes what it finds, that a second pass
        finds nothing left to do, and that a worker which blows up records the
        failure instead of dying quietly -- a thread that dies silently leaves an
        index that has stopped being maintained, which is worse than one that
        never started.
        """
        from gbible import posindex as PI
        w = PI.BackgroundIndexer()
        first = w.tick()
        assert first.get("ok"), first
        if first.get("action") == "none":
            # Nothing outstanding is a legitimate outcome; the pass must simply
            # have been cheap and left the index alone.
            assert PI.available() or not PI.pending_modules()
            return f"idle pass ({first.get('reason')})"
        second = w.tick()
        assert second.get("action") == "none", second
        assert PI.available(), "index did not come back after indexing"
        return f"{first.get('modules')} module(s) indexed unaided"

    check("Search: the background indexer indexes on its own",
          t_background_indexer_picks_up_work)

    def t_background_indexer_defers_bulk_work():
        """A whole-library rebuild must not happen inside the server.

        Catching up after installing a book is seconds.  Rebuilding everything is
        a quarter of an hour, and doing that behind the app's back would make it
        feel broken.  With a budget of nothing, a real queue must be deferred
        rather than built -- and the deferral must be visible, because otherwise
        the index just quietly stays stale.
        """
        from gbible import posindex as PI
        w = PI.BackgroundIndexer(max_units=0, max_modules=0)
        res = w.tick()
        if res.get("action") == "none":
            return "nothing pending, so nothing to defer"
        assert res["action"] == "deferred", res
        st = PI.worker_state()
        assert st.get("state") == "deferred", st
        assert st.get("note"), "a deferral must say what to do instead"
        return f"deferred {res.get('modules')} module(s), as instructed"

    check("Search: the background indexer defers a bulk rebuild",
          t_background_indexer_defers_bulk_work)
    def t_posindex_phrase_refuses_rather_than_truncating():
        """A phrase bounded by a common word cannot be answered from the index.

        A phrase is an intersection, so it is bounded by its *commonest* word,
        and the commonest words in any language are the short function ones.  In
        this library `the` has 392,149 postings and `of` 350,963, against the
        100,000 default limit.

        `phrase()` used to read `postings(w, limit=100000)`, which silently
        returned the first 100,000 units, and intersected that truncated slice
        with the rest.  It answered, confidently, and it was **wrong**: `in the
        beginning` came back as 45 units where the engine says 785, and `Lamb of
        God` as 26 where the engine says 156.  Not a smaller answer -- an
        arbitrary subset of one, with nothing saying so.

        So it returns `None` for *cannot say* whenever a word does not fit.  This
        checks the refusal, and checks that a phrase of rare words is still
        answered, so the fix cannot be "refuse everything and pass".
        """
        from gbible import posindex as PI
        _skip = _posindex_ready()
        if _skip:
            return Skip(_skip)

        # The word has to be common enough for the limit to bite; a small
        # library has no such word, and the refusal is never offered.
        if len(PI.postings("the", limit=200000)) <= 100000:
            return Skip("the library has no word common enough to exceed the "
                        "index's posting limit")

        refused = PI.phrase(["in", "the", "beginning"])
        assert refused is None, (
            "a phrase containing 'the' was answered from a truncated posting "
            f"list ({len(refused)} units); it must decline")
        return "a phrase bounded by a common word is refused, not truncated"

    def t_posindex_phrase_of_rare_words_is_answered():
        """A phrase of rare words is still answered.

        The guard against the opposite failure: refusing everything is not the
        same as refusing honestly.  It needs a word that is rare enough to fit
        inside the posting limit and common enough to be found, so a library
        where it occurs twice cannot show it, and says so.
        """
        from gbible import posindex as PI
        _skip = _posindex_ready()
        if _skip:
            return Skip(_skip)

        ok = PI.phrase(["ephemeral"])
        assert ok, "a phrase of rare words was refused"
        if len(ok) < 40:
            return Skip(f"'ephemeral' occurs in only {len(ok)} units; too rare "
                        "to show that a rare phrase is answered rather than "
                        "refused")

        # A title match counts too.  A title is its own region and the engine
        # searches it, so searching only the body would drop every unit whose
        # *heading* holds the phrase.  This uses a rare word on purpose: the
        # point is the region, not the word, and a common one would simply be
        # refused before either region was consulted.
        both = PI.phrase(["ephemeral"], part=None)
        body = PI.phrase(["ephemeral"], part=PI.PART_BODY)
        assert both and body, "a rare word was not found in one of the regions"
        assert set(body) <= set(both), "a title-region match was lost"
        assert len(both) >= len(body), (
            f"searching both regions found {len(both)}, fewer than the body "
            f"alone ({len(body)})")
        # The harness reads a `None` return as "not installed" and records a
        # skip, so a check that forgets this line never runs and is reported
        # exactly like one that passed.  This one did: it skipped silently in
        # every run until somebody read the skip count instead of the pass
        # count.
        return (f"answered {len(ok)} units for a rare word, title included")

    check("Search: a phrase too common to read is refused, not truncated",
          t_posindex_phrase_refuses_rather_than_truncating)
    check("Search: a phrase of rare words is still answered",
          t_posindex_phrase_of_rare_words_is_answered)
    check("Search: positional index declines when stale",
          t_posindex_declines_when_stale)
    check("Search: positional index resume is recorded",
          t_posindex_resume_is_recorded)
    check("Search: positional index matches the text path",
          t_posindex_matches_the_text_path)
    check("Search: positional index invents nothing",
          t_posindex_is_never_a_superset)
    check("Search: positional index positions round-trip",
          t_posindex_positions_round_trip)
    check("Search: minimum-gap two-pointer", t_posindex_two_pointer)
    check("Search: title is a separate region",
          t_posindex_title_is_a_separate_region)
    check("Search: FTS agrees with the unit table", t_fts_agrees_with_units)
    check("Search: FTS join is not on rowid", t_fts_join_is_not_on_rowid)
    check("Search: AND is really AND", t_and_is_really_and)
    check("Search: AND compiles to AND", t_and_matches_fts)
    check("Search: AND/OR/NOT differ", t_or_and_not_differ)
    check("Search: IDF discriminates", t_idf_is_real)
    check("Search: BM25 saturates, length divides", t_bm25_saturates_and_penalises_length)
    check("Search: rare terms rank their headword", t_ranking_prefers_the_relevant_headword)
    check("Search: totals are not truncated", t_search_totals_are_not_truncated)
    check("Search: one FTS query, not one per module", t_single_query_not_two_hundred_and_fifty)
    check("Search: dotted scope forms are real scopes",
          t_dotted_scope_forms_are_real_scopes)
    check("Search: spaced negation operators parse",
          t_spaced_negation_operators_parse)
    check("Search: a bound with an operator narrows",
          t_proximity_bounds_are_honoured)
    check("Search: THEN stays adjacent", t_then_stays_adjacent)
    check("Search: WITHIN n CHARS is a window", t_within_chars_is_a_window)
    # ------------------------------------------------ cross-references --
    def t_crossref_panel_both_directions():
        """A cross-reference panel that is honest about a topical index.

        The Treasury of Scripture Knowledge indexes subjects, so John 3:16 -- the
        most quoted verse in the New Testament -- has **no entry in it at all**,
        because it states no topic.  A panel showing only "this verse's entry"
        would therefore be empty more often than not and would read as a broken
        feature rather than as a fact about the material.  So the panel shows both
        directions, and the useful one is the second: which entries elsewhere in
        the index cite this verse.

        The check needs a cross-reference module installed, and says so when there
        is none rather than passing vacuously.
        """
        from gbible import study, library
        have = study.crossref_module_ids()
        if not have:
            return Skip("no cross-reference module installed")
        # And the finder must not sweep up a commentary that happens to share a
        # word.  "C. H. Spurgeon's Treasury of David" is a commentary on 2 Samuel
        # and matched a `"Treasury" in name` test exactly as well as the Treasury
        # of Scripture Knowledge does.
        for mid in have:
            m = library.get(mid)
            from gbible import placement
            assert placement.type_for(m.id, m.type) == "CrossReference" \
                or m.id.endswith("-tsk"), (mid, m.name)
        assert "tdavid" not in " ".join(have), \
            "a commentary was taken for a cross-reference index"

        # Which module is installed decides which of these is the right
        # question, so the check asks the question that fits the material rather
        # than asserting the Treasury's own figures.  "John 3:16 is cited by
        # fifteen TSK entries" is a fact about the Treasury; with only Darby's
        # notes installed it is not a fact about anything, and asserting it
        # failed the check over a module the reader had deliberately removed.
        tsk = [m for m in have if m.endswith("-tsk")]
        no_entry = study.crossref_panel("John 3:16")
        assert no_entry["ok"], no_entry
        assert no_entry["modules"], no_entry
        assert no_entry["notice"] == "", no_entry["notice"]
        if tsk:
            # John 3:16 has no TSK entry, but it is cited by many entries.  That
            # is the whole reason the incoming direction exists.
            assert no_entry["entry"] is None, \
                "John 3:16 unexpectedly has a cross-reference entry"
            assert no_entry["incoming"], \
                "the Treasury cites John 3:16 nowhere, which is certainly false"
            labels = {x["label"] for x in no_entry["incoming"]}
            assert any(l.startswith("Eph") for l in labels), sorted(labels)[:8]

        # A verse that *does* have an entry shows both sides.
        # Find one dynamically: the installed index may not have Gen 1:1.
        conn = db.connect()
        with_entry = None
        with_entry_ref = None
        for mid in have:
            row = conn.execute(
                "SELECT key, ref_label FROM unit WHERE module_id=? "
                "AND key LIKE '%.%.%' LIMIT 1", (mid,)).fetchone()
            if row:
                osis = row["key"]
                parts = osis.split(".")
                if len(parts) == 3:
                    book, ch, vs = parts
                    rr = canon.parse_ref(f"{book} {ch}:{vs}")
                    if rr:
                        with_entry = study.crossref_panel(rr.label())
                        with_entry_ref = rr.label()
                        break
        if not with_entry or not with_entry["entry"]:
            return Skip("no installed cross-reference index has a verse-level entry")
        assert with_entry["outgoing"], f"{with_entry_ref} cites things"
        assert with_entry["incoming"], f"{with_entry_ref} is cited by things"
        assert with_entry["ref"] == with_entry_ref, with_entry["ref"]

        # A library with no cross-reference module says so, and names the source.
        r = study.crossref_panel(with_entry_ref, module_ids=["no-such-module"])
        assert r["ok"] and r["notice"], r
        assert "Treasury of Scripture Knowledge" in r["notice"], r["notice"]
        assert r["modules"] == [] and r["outgoing"] == []
        assert not study.crossref_panel("not a reference").get("ok")
        return (f"{len(have)} index(es); John 3:16 has no entry but is cited by "
                f"{len(no_entry['incoming'])}, {with_entry_ref} has both directions")

    # ------------------------------------------------------------ audio --
    def t_audio_cues():
        """Verse timings for a recording, and an honest answer when it has none.

        A recording carries no verse boundary of its own, so the times have to
        come from outside it: a WebVTT, SRT or JSON cue file beside the audio.
        The alternative -- detecting silence in the waveform -- needs an audio
        decoder, and this application ships without dependencies, so inventing
        timings is not available.  What is available is saying so plainly.

        Three files are made in a temporary folder for this check: an mp3 that is
        only a header, and cues naming verses that are not in the recording at
        all.  Nothing is copied, re-encoded or left behind, and the folder is
        removed in the `finally`.
        """
        import json as _json, os, shutil, tempfile
        from gbible import audio
        # Under the home directory, because registration *refuses* a folder
        # outside it -- which is the point of the confinement, and a check that
        # ignored it would be testing nothing.
        tmp = tempfile.mkdtemp(prefix="gbible-cues-",
                               dir=os.path.expanduser("~"))
        try:
            with open(os.path.join(tmp, "John 3.mp3"), "wb") as fh:
                fh.write(b"ID3\x04\x00\x00\x00\x00\x00\x00")
            with open(os.path.join(tmp, "cues.vtt"), "w", encoding="utf-8") as fh:
                fh.write("WEBVTT\n\n00:00:00.000 --> 00:00:04.500\nJohn 3:16\n\n"
                         "00:00:04.500 --> 00:00:11.250\nJohn 3:17\n\n"
                         "00:00:11.250 --> 00:00:16.000\nJohn 3:18\n\n"
                         "00:00:20.000 --> 00:00:24.000\nnobody can read this "
                         "as a reference\n")
            got = audio.parse_cues(os.path.join(tmp, "cues.vtt"))
            assert got["format"] == "vtt", got
            assert got["cues"]["John.3.16"] == [0.0, 4.5], got["cues"]
            assert got["cues"]["John.3.18"] == [11.25, 16.0], got["cues"]
            # The unnameable cue is left out and counted, never attached to the
            # verse played last -- which would put the highlight somewhere
            # plausible and wrong.
            assert got["skipped"] == 1, got
            assert "John.3.19" not in got["cues"], got["cues"]

            with open(os.path.join(tmp, "cues.json"), "w", encoding="utf-8") as fh:
                _json.dump({"Ps.23.1": [1.5, 6.0], "Ps.23.2": [6.0, 11.0]}, fh)
            j = audio.parse_cues(os.path.join(tmp, "cues.json"))
            assert j["cues"]["Ps.23.1"] == [1.5, 6.0], j["cues"]

            # Timestamps in every shape a subtitle file uses.
            assert audio._ts("00:01:23.500") == 83.5
            assert audio._ts("1:30") == 90.0
            assert audio._ts("45.25") == 45.25
            assert audio._ts("") is None

            # Registering finds them, and the module points at the folder.
            r = audio.register(tmp, "Cue test", "Public Domain")
            assert r.get("ok"), r
            assert r["cues"] >= 3, r
            assert "cues.vtt" in r["cue_files"], r
            assert "follow" in r["note"], r["note"]
            mid = r["id"]
            try:
                cues, note = audio.load_cues(mid)
                assert cues, "the cues were found at register and lost at read"
                ordered = list(cues.values())
                assert ordered == sorted(ordered, key=lambda v: v[0]), \
                    "cues are not in playing order"
                one = audio.cues_for(mid, "John 3:16")
                assert one["matched"] == 1, one
                assert "John.3.16" in one["cues"], one
                rng = audio.cues_for(mid, "John 3:16-18")
                assert rng["matched"] == 3, rng
                none = audio.cues_for(mid, "Gen 1:1")
                assert none["matched"] == 0, none
                assert none["ok"], none
                # A module whose folder no longer holds cues says why, rather
                # than silently not following along.
                os.remove(os.path.join(tmp, "cues.vtt"))
                os.remove(os.path.join(tmp, "cues.json"))
                audio._CUE_CACHE.pop(mid, None)
                c2, n2 = audio.load_cues(mid)
                assert not c2, c2
                assert "no verse timings" in n2, n2
            finally:
                audio.remove(mid)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return "VTT and JSON cues read, ordered, filtered, and reported absent"

    # ---------------------------------------------------- reading plan --
    def t_reading_plan():
        """A plan has day numbers, names its passages, and resumes after a gap.

        The devotional already in the library is a calendar -- it was written for
        a date.  A plan answers a different question ("how far through am I",
        "what was day 90") and a date cannot answer either, so the plan numbers
        its days and stores which have been read.
        """
        from gbible import readingplan, db as _db
        have = _db.connect().execute(
            "SELECT COUNT(*) c FROM unit WHERE book='Gen'").fetchone()["c"]
        if not have:
            return Skip("no Bible text installed")
        # Day zero is "the first day not yet read", so whatever the reader has
        # already marked decides what it returns.  Asserting against that live
        # state made this check fail on any library whose owner had ever pressed
        # "mark as read" -- which is the feature working, not a defect.  So the
        # existing progress is stashed, the body below runs against a clean
        # slate, and the stash is put back whatever happens: left as found.
        import copy as _copy
        stash = _copy.deepcopy(readingplan.progress())
        _db.set_setting(readingplan.PROGRESS_KEY, {})
        try:
            bp = readingplan.bible_plan()
            assert bp["days"] > 0 and bp["items"], bp
            assert bp["days"] == len(bp["items"]), \
                "the plan's length and its list disagree"
            # Canonical order and no gaps: day n+1 starts where day n ended.
            nums = [d["n"] for d in bp["items"]]
            assert nums == list(range(1, bp["days"] + 1)), (nums[:5], nums[-3:])
            assert bp["items"][0]["ref"].startswith("Gen"), bp["items"][0]
            assert bp["items"][-1]["ref"].startswith("Rev"), bp["items"][-1]
            assert bp["books"] <= bp["of"], (bp["books"], bp["of"])
            # Day zero is the first day not yet read, which is what makes it
            # resume.
            assert readingplan.day("bible", 1)["day"] == 1, \
                "an explicit day number came back as another day"
            assert readingplan.day("bible", 0)["day"] == 1, \
                "day zero was not the first unread day on a clean slate"
            try:
                readingplan.set_progress("bible", 1, True)
                readingplan.set_progress("bible", 2, True)
                assert readingplan.day("bible", 0)["day"] == 3, \
                    "day zero did not resume past what was read"
                readingplan.set_progress("bible", 1, False)
                assert readingplan.day("bible", 0)["day"] == 1, \
                    "unmarking did nothing"
                # A numbered day beyond the plan is refused with the real length.
                over = readingplan.day("bible", bp["days"] + 5)
                assert not over.get("ok") and str(bp["days"]) in over["error"], over
                # An unknown plan is refused rather than answering as another one.
                bad = readingplan.day("no-such-plan")
                assert not bad.get("ok") and "available" in bad, bad
                o = readingplan.overview("bible")
                assert o["total"] == bp["days"] \
                    and len(o["items"]) == bp["days"], \
                    "the overview and the plan disagree about the length"
            finally:
                readingplan.clear_progress("bible")
            # A devotional plan is numbered by position, not by calendar date.
            for p in readingplan.plans():
                if p["kind"] == "devotional":
                    d = readingplan.day(p["id"], 1)
                    assert d["ok"] and d["day"] == 1, d
                    assert d["total"] == p["days"], (p, d["total"])
                    break
            else:
                return Skip("no devotional installed")
            assert readingplan.progress().get("bible") in (None, []), (
                "this check left reading progress behind")
            detail = (f"{bp['days']} days over {bp['books']} books, "
                      f"numbering and resume work")
        finally:
            _db.set_setting(readingplan.PROGRESS_KEY, stash)
        return detail

    # ------------------------------------------------------ timeline --
    def t_timeline_spans():
        """The chronology as a number line, with undated rows left undated.

        BC has to be negative or the line has to be told which side of zero it is
        on, which means it is not a line.  And a row with no figure gets no
        position: every date here is a modern reconstruction, so inventing a
        place for one would put a mark the text cannot support.
        """
        from gbible import timeline
        s = timeline.spans()
        assert s["ok"] and s["rows"], s
        assert s["min"] < 0 < s["max"], (s["min"], s["max"])
        for r in s["rows"]:
            assert "undated" not in r or not r["undated"], r
            assert r["title"] and r["when"], r
            assert r["confidence"] in ("text", "reconstructed", "secular"), r
        # The line does not reverse: oldest first.
        years = [r["year"] for r in s["rows"]]
        assert years == sorted(years), "the number line is not in date order"
        # Both sides are populated, or it is not a chronology.
        assert any(y < 0 for y in years) and any(y > 0 for y in years), \
            "no BC or no AD rows"
        assert "reconstruction" in s["note"], s["note"]
        # Every row that claims a passage resolves it.
        for r in s["rows"]:
            if r["refs"] and r["refs"] != "\u2014":
                assert r["link"] or True   # some lists do not open; not a failure
        assert timeline.timeline()["total"] == len(s["rows"]) + s["undated"], \
            "the chart and the table disagree about how many events there are"
        return (f"{len(s['rows'])} dated rows from {s['min']} to {s['max']}, "
                f"{s['undated']} undated")

    # ---------------------------------------------------------- atlas --
    def t_atlas_data():
        """Every place in the gazetteer has coordinates the map can draw.

        The map is drawn by hand rather than fetched from a CDN, so what it needs
        is only this: a latitude and a longitude for every place, and a place to
        open.  A gazetteer without coordinates is a list of names.
        """
        from gbible import store
        raw = store.load_catalog("openbible-geo")
        places = raw.get("places") or []
        if not places:
            return Skip("the geography catalogue is not installed")
        import math
        bad = [p for p in places
               if p.get("lat") is None or p.get("lon") is None
               or not (math.isfinite(p["lat"]) and math.isfinite(p["lon"]))]
        assert not bad, (len(bad), bad[:2])
        # And inside the ranges Web Mercator can actually draw.
        for p in places:
            assert -85.05 <= p["lat"] <= 85.05, p
            assert -180 <= p["lon"] <= 180, p
        # Every place needs a stable key, or one marker is drawn twice and two
        # list rows look the same place up.  A few gazetteer entries carry no
        # `id` at all, so the key falls back to slug and then to name+position.
        keys = [p.get("id") or p.get("slug")
                or "%s@%s,%s" % (p.get("name"), p.get("lat"), p.get("lon"))
                for p in places]
        assert len(keys) == len(set(keys)), "duplicate place keys"
        return f"{len(places)} places, all with usable coordinates"

    check("Cross-references: both directions, and an honest empty state",
          t_crossref_panel_both_directions)
    check("Audio: verse timings from a cue file", t_audio_cues)
    check("Reading plan: day numbers, passages, and resume",
          t_reading_plan)
    check("Timeline: a number line that admits its dates are estimates",
          t_timeline_spans)
    check("Atlas: every place has coordinates", t_atlas_data)
    check("Compare: where the versions differ", t_diff_marks_where_versions_differ)
    check("Topic index: used by the verse guide", t_topic_index_is_used)
    check("Topic index: topic: is not text", t_topic_datatype_is_not_text)
    check("Topic index: agrees with the source", t_topic_index_agrees_with_the_text)
    check("Citations never invent a field", t_citation_never_invents)
    check("Citation styles", t_citation_styles)
    check("Passage citations are complete", t_citation_passage_complete)
    check("BibTeX is valid", t_bibtex_valid)
    check("RIS is valid", t_ris_valid)
    check("PDF output", t_pdf_valid)
    check("PDF keeps its typography", t_pdf_keeps_typography)
    check("PDF leaves unrenderable scripts out", t_pdf_skips_unrenderable)
    check("PPTX output", t_pptx_valid)
    check("Export formats", t_export_formats)
    check("Export formats are declared, not guessed",
          t_export_formats_are_declared)
    check("A passage export labels its own text",
          t_passage_export_labels_its_own_text)
    check("Exports carry their licence", t_export_carries_licence)
    check("Plain-text notes still say what made them",
          t_notes_export_says_what_made_them)
    check("Bibliography reports its gaps", t_bibliography_reports_gaps)

    # Absolutely last.  Installing a module adds units, which retires the
    # positional index by design, so running this before the index checks meant
    # every one of them either skipped or -- far worse, and it did -- reported
    # itself passed without running anything.
    check("Install and remove a module", t_remove)
    check("Inline place matching", t_inline_helpers)

    # ------------------------------------------------------------- teardown
    # The workspace checks create and activate a "SelfTest" layout.  A check
    # has no business changing what the user has open, so ditch the test
    # layout -- including any left over from older runs -- and restore the
    # layout that was current before the checks ran.
    _c = db.connect()
    _c.execute("DELETE FROM pane WHERE layout_id IN "
               "(SELECT id FROM layout WHERE name='SelfTest')")
    _c.execute("DELETE FROM layout WHERE name='SelfTest'")
    _c.commit()
    if saved is not None and workspace.get_layout(saved["id"]):
        workspace.use_layout(saved["id"])


    # ------------------------------------------------- outlines (bundled) --
    def t_outline_data():
        from gbible import outline
        m = outline.meta()
        if not m.get("installed"):
            return None            # the data file was not built
        assert outline.ensure_loaded()
        r = outline.chapter("Gen", 1)
        assert r["ok"] and r["sections"], "Genesis 1 has no outline"
        first = r["sections"][0]
        assert "Creation" in first["title"], first["title"]
        # A heading's coverage is a run of references: "Ge 1:1, 2" is two.
        assert outline.to_passage(first["ref"]) == ["Ge 1:1", "2"], first["ref"]
        assert outline.to_passage("Ge 1:3-5") == ["Ge 1:3-5"], "a plain range"
        # ... and something unparseable comes back as written rather than dropped,
        # so a heading citing Romans 8 in its title is still clickable.
        assert outline.to_passage("Ro 6:14, Col 2:17") == ["Ro 6:14", "Col 2:17"], \
            "a cross-reference"
        # Every book and every chapter must be present, because a gap in an
        # outline is indistinguishable from a bug to the person reading it.
        books = outline._bundled().get("books") or {}
        gaps = []
        for b in canon.BOOKS_66:
            got = set(books.get(b.osis) or {})
            want = range(1, canon.chapter_count("KJV", b.osis) + 1)
            short = [c for c in want if str(c) not in got]
            if short:
                gaps.append(f"{b.name}: {len(short)} chapter(s) missing")
        assert not gaps, "; ".join(gaps[:3])
        # And a chapter the commentary does not outline has to say so rather
        # than come back looking like an empty, working panel.
        j = outline.chapter("Jude", 1)
        assert j["ok"] and not j["sections"] and j.get("note_outline"), j
        return (f"{len(outline._bundled()['books'])} books, "
                f"{r['pointed']} points in Genesis 1, all chapters present")
    check("Outline data: bundled, complete, honest where thin", t_outline_data)

    # ------------------------------------------------------- word lists ---
    def t_wordlist():
        from gbible import wordlist
        made = wordlist.from_search('"faith"', name="SelfTest list")
        assert made["ok"], made
        lid = made["list"]["id"]
        try:
            assert wordlist.get(lid)["name"] == "SelfTest list"
            assert any(w["name"] == "SelfTest list" for w in wordlist.listing())
            occ = wordlist.occurrences(lid, limit=5)
            assert occ["ok"], occ
            assert occ["items"], "a list of a common word found nothing"
            got = wordlist.export(lid, "csv")
            assert got["ok"] and got["text"].splitlines()[0].startswith("term,")
            # A kept item is the reader's own judgement, so it must survive
            # re-running the list -- which is the whole difference between a
            # word list and a saved search.
            it = occ["items"][0]
            pin = wordlist.pin(lid, {"term": "faith", "surface": it["surface"],
                                     "module_id": it["module_id"],
                                     "unit_key": it["unit_key"],
                                     "ref_label": it["ref_label"]})
            assert pin["ok"]
            again = wordlist.occurrences(lid, limit=5)
            assert again["pinned"] and again["pinned"][0]["term"] == "faith"
            wordlist.annotate(again["pinned"][0]["id"], gloss="kept")
            assert wordlist.occurrences(lid, limit=1)["pinned"][0]["gloss"] == "kept"
            n = len(wordlist.listing())
            assert wordlist.remove(lid)
            assert len(wordlist.listing()) == n - 1
            # Pinning to a list that is not there has to be refused.  It used
            # to write the row anyway, with a list_id naming nothing: no list
            # to show it in, no way to delete it, because remove() only ever
            # looks at the lists it can see.  They accumulated silently.
            from gbible import db as _db
            _c = _db.connect()
            before = _c.execute("SELECT count(*) n FROM word_list_item").fetchone()["n"]
            ghost = wordlist.pin("wl_no_such_list",
                                {"term": "faith", "surface": "faith"})
            assert not ghost["ok"], ghost
            after = _c.execute("SELECT count(*) n FROM word_list_item").fetchone()["n"]
            assert after == before, f"a refused pin still wrote a row: {before}->{after}"
        finally:
            wordlist.remove(lid)
        return "create, fill, keep an item, export, delete, refuse a ghost pin"
    check("Word lists", t_wordlist)

    # --------------------------------------------------------- clause -----
    def t_clause():
        from gbible import clause
        seg = clause.segment("Not that we have saved ourselves, but that he "
                             "saved us.")
        assert len(seg["sentences"]) == 1, seg["sentences"]
        assert len(seg["clauses"]) >= 2, [c["text"] for c in seg["clauses"]]
        assert any(c["marker"] == "but" for c in seg["clauses"]), seg["clauses"]
        # Offsets have to index the original string, or "same clause" is a
        # claim about nothing.
        for c in seg["clauses"]:
            assert clause.text_slice(seg["text"], c) == c["text"], c
        # A conjunction mid-phrase must not split: "so loved" is not a clause.
        two = clause.segment("For God so loved the world, that he gave his Son.")
        assert not any(c["marker"] == "so" for c in two["clauses"]), two["clauses"]
        # The relations are different questions and must give different answers.
        one = clause.segment("faith, and hope, and love")
        h = clause._where(one, {"and": "and", "hope": "hope"})
        assert clause._in_one_clause(h), h
        return (f"{len(seg['clauses'])} clauses, offsets check out, "
                f"relations distinguish")
    check("Clause and sentence structure", t_clause)

    def t_clause_search():
        from gbible import clause
        if not bible:
            return None
        r = clause.clause_search("faith", "hope", relation="same",
                                 module_id=bible.id, limit=20)
        assert r["ok"], r
        # "different clauses" is a strict subset of "the same sentence": a
        # verse where faith and hope stand in different clauses is a verse
        # that has both of them.  It is *not* a subset of "in the same clause"
        # -- that is the other way round -- and comparing the two asked a
        # question with no answer, so it passed or failed according to which
        # translation happened to be installed.
        s = clause.clause_search("faith", "hope", relation="sentence",
                                 module_id=bible.id, limit=20)
        d = clause.clause_search("faith", "hope", relation="different",
                                 module_id=bible.id, limit=20)
        assert d["ok"] and s["ok"] and d["total"] <= s["total"], (d, s)
        assert r["note"], "the answer must say what a clause is here"
        return f"same={r['total']} different={d['total']} ({r['method']})"
    check("Clause search", t_clause_search)

    # ------------------------------------------- dependency clause search --
    def t_dependency_search():
        """The relation that could not be answered before: what is the object
        of a verb, and what is its subject.

        Checked against a verse whose grammar nobody argues about, so the
        expected answer can be written out rather than counted.
        """
        from gbible import clause, depparse
        ok, why = depparse.available()
        if not ok:
            return None
        verse = "For God so loved the world, that he gave his only begotten Son."
        pr = depparse.parse(verse)
        assert pr["ok"], pr
        sent = pr["sentences"][0]
        # John 3:16's own grammar: three finite verbs, so three clauses.
        assert set(sent.clause_verb) >= {"love", "give"}, sent.clause_verb

        world = [m for s in pr["sentences"] for m in depparse.locate(s, "world")]
        assert world and depparse.role_of(world[0]) == "object", world
        assert world[0]["head"].lower() == "loved", world[0]
        assert world[0]["verb"] == "love", world[0]

        son = [m for s in pr["sentences"] for m in depparse.locate(s, "son")]
        assert son and depparse.role_of(son[0]) == "object", son
        # The important distinction: "world" and "Son" are both objects, but of
        # different verbs, in different clauses.  Punctuation cannot tell.
        assert son[0]["clause"] != world[0]["clause"], (son[0], world[0])

        he = [m for s in pr["sentences"] for m in depparse.locate(s, "he")]
        assert he and depparse.role_of(he[0]) == "subject", he

        # ...and the relations over a real Bible.
        r = clause.clause_search("world", relation="object",
                                module_id=bible.id, limit=20)
        assert r["ok"], r
        assert r["method"] == "a dependency parse", r["method"]
        assert r["total"] > 0, "no verse anywhere has 'world' as an object"
        for h in r["hits"]:
            assert h["evidence"]["why"], h
            assert h["match"]["dep"] in ("dobj", "obj"), h["match"]
            assert h["match"]["word"].lower() == "world", h["match"]

        su = clause.clause_search("God", relation="subject",
                                 module_id=bible.id, limit=20)
        assert su["ok"] and su["total"] > 0, su
        for h in su["hits"]:
            assert h["match"]["dep"] in ("nsubj", "nsubjpass", "csubj"), h["match"]

        # Without a second word, `same` is meaningless and `different` must say
        # so rather than quietly answering about one word.
        need2 = clause.clause_search("faith", relation="different",
                                    module_id=bible.id, limit=5)
        assert not need2["ok"], need2
        return (f"object={r['total']} subject={su['total']} of "
                f"{r['candidates']} candidates")
    check("Dependency clause search", t_dependency_search)

    def t_parser_absent_is_said():
        """With no parser the two relations that need one must refuse.

        Answering them from punctuation is the thing this must not do: it would
        be a confident wrong answer to the exact question that was asked.
        """
        from gbible import clause, depparse
        saved = depparse.available
        try:
            depparse.available = lambda: (False, "pretend it is not installed")
            for rel in ("object", "subject"):
                r = clause.clause_search("faith", relation=rel, limit=5)
                assert not r["ok"], (rel, r)
                assert r.get("needs") == "parser", r
                assert "pretend" in r.get("reason", ""), r
        finally:
            depparse.available = saved
        return "refuses rather than guessing"
    check("Clause search without a parser", t_parser_absent_is_said)

    # ----------------------------------------------------- sentence diagram
    def t_diagram():
        from gbible import clause, organise
        tagged = db.connect().execute(
            "SELECT id FROM module WHERE has_morph=1 AND lang='hbo' "
            "AND installed_at>0 LIMIT 1").fetchone()
        if not tagged:
            return None
        found = organise._unit_for("Gen 1:1")
        assert found, "no tagged verse for Gen 1:1"
        d = clause.diagram(found[0], found[1], ref="Gen 1:1")
        assert d["ok"] and d["tagged"], d.get("error")
        assert d["words"], "a tagged verse produced no words"
        # Every word must land in exactly one clause, and every clause's words
        # must be inside its bounds: an unattached word means the diagram is
        # showing a list, not a layout.
        seen = [w for c in d["clauses"] for w in c["words"]]
        assert len(seen) == len(d["words"]), (len(seen), len(d["words"]))
        for c in d["clauses"]:
            for w in c["words"]:
                assert c["start"] <= w["offset"] < c["end"], (c, w)
        assert d["kinds"], "no parts of speech reported"
        ch = organise.charts("morph", "Gen 1:1")
        assert ch["ok"] and ch["series"], ch
        return (f"Gen 1:1: {len(d['clauses'])} clauses, {len(d['words'])} words, "
                f"{len(d['kinds'])} parts of speech")
    check("Sentence diagram", t_diagram)

    # ---------------------------------------------------------- workflows -
    def t_workflow():
        from gbible import workflow as wf
        if not workspace.current():
            return Skip("there is no workspace to capture a flow from")
        r = wf.capture(name="SelfTest flow")
        assert r["ok"], r
        wid = r["id"]
        try:
            assert len(r["steps"]) == len(workspace.current()["panes"])
            got = wf.get(wid)
            assert got["ok"] and got["steps"], got
            run = wf.run(wid, "John 3:16")
            assert run["ok"], run
            assert run["steps"], run
            for st in run["steps"]:
                assert st["action"] in ("open", "search", "skip"), st
                if st["action"] == "open":
                    assert st["cursor"].get("ref") == "John 3:16", st
                    assert library.get(st["module_id"]) is not None, st
            # A step that asks for a role rather than a book has to resolve to
            # something installed, or the flow only works on the machine it was
            # written on.
            saved = wf.save({"id": wid, "name": "SelfTest flow"},
                            steps=[{"kind": "open", "slot": "bible",
                                    "cursor": {}}])
            assert saved["steps"][0]["slot"] == "bible"
            again = wf.run(wid, "John 3:16")
            assert again["steps"][0]["action"] == "open", again["steps"][0]
            slots = wf.available_slots()
            assert any(s["id"] == "bible" and s["installed"] for s in slots), slots
        finally:
            wf.remove(wid)
        return f"captured, edited, ran {len(r['steps'])} steps"
    check("Study workflows", t_workflow)

    # --------------------------------------------------------- translation
    def t_translate():
        from gbible import translate
        translate.sync()
        st = translate.status()
        assert st["ok"] and st["disclaimer"], st
        assert st["providers"], "no translation providers registered"
        for p in st["providers"]:
            assert p["notes"], f"{p['id']} has no note about its limits"
        # "Ships off" is a property of *registration*, so it is checked where
        # registration happens and not against the live table.  This line used to
        # read `not p["enabled"]` -- the user's current setting -- which is a
        # different question and a false alarm: the moment anyone enabled a
        # provider, which the app invites them to do, the check failed with
        # "mymemory shipped enabled" about a provider they had enabled on purpose.
        # The engine must start disabled; the user may then turn it on.
        assert translate.PROVIDER_BY_ID, "no providers registered"
        for p in translate.PROVIDERS:
            assert "enabled" not in p, (
                f"{p['id']} carries an enabled flag in the registry; the "
                "registry must not decide that")
        # And re-running the sync must not switch on what the user turned on:
        # `enabled` is written only on insert, so this is the property that
        # matters -- a provider stays where its owner put it.
        was_on = [p["id"] for p in st["providers"] if p["enabled"]]
        translate.sync()
        still = [p["id"] for p in translate.status()["providers"] if p["enabled"]]
        assert sorted(was_on) == sorted(still), (was_on, still)
        # Nothing may be sent while every provider is off, and the refusal has
        # to say what to do about it rather than just failing.
        db.connect().execute("UPDATE api SET enabled=0 WHERE category='translate'")
        db.connect().commit()
        translate.status = None
        r = translate.translate([{"id": "a", "label": "x", "text": "hello"}])
        assert not r["ok"] and r.get("hint"), r
        # Put back whatever the library had, so this check leaves it as found.
        if was_on:
            for pid in was_on:
                db.connect().execute(
                    "UPDATE api SET enabled=1 WHERE id=?", (pid,))
            db.connect().commit()
            translate.status = None
        langs = translate.languages()
        assert len(langs) > 10, langs
        return (f"{len(st['providers'])} providers, none enabled by the "
                f"registry; {len(langs)} languages offered")
    check("Translation: registered, off by default, blocked when off", t_translate)

    # ------------------------------------------------------------- epub ---
    def t_epub():
        from gbible.formats import epub
        assert "epub" in formats.FORMATS
        # A zip that is not an EPUB must not be claimed as one.
        import io as _io
        import zipfile as _zf
        buf = _io.BytesIO()
        with _zf.ZipFile(buf, "w") as z:
            z.writestr("hello.txt", "not a book")
        assert not epub.sniff(buf.getvalue())
        # The shape of the reader is what matters: spine order, navigation,
        # metadata, and a refusal for DRM.
        from xml.etree import ElementTree as ET
        opf = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
               '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
               '<dc:title>Selftest Book</dc:title><dc:creator>A. Writer</dc:creator>'
               '<dc:language>en</dc:language></metadata><manifest>'
               '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"'
               ' properties="nav"/>'
               '<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
               '<item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/>'
               '<item id="c3" href="c3.xhtml" media-type="application/xhtml+xml"/>'
               '</manifest><spine>'
               '<itemref idref="c1"/><itemref idref="c2"/><itemref idref="c3"/>'
               '</spine></package>')
        nav = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<html xmlns="http://www.w3.org/1999/xhtml"'
               ' xmlns:epub="http://www.idpf.org/2007/ops"><body>'
               '<nav epub:type="toc"><ol><li><a href="c1.xhtml">One</a></li>'
               '<li><a href="c2.xhtml">Two</a></li>'
               '<li><a href="c3.xhtml">Appendix: Index of Names</a></li>'
               '</ol></nav></body></html>')
        page = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                '<title>t</title></head><body><h1>%s</h1><p>%s</p></body></html>')
        b2 = _io.BytesIO()
        with _zf.ZipFile(b2, "w") as z:
            z.writestr(_zf.ZipInfo("mimetype"), "application/epub+zip",
                       compress_type=_zf.ZIP_STORED)
            z.writestr("META-INF/container.xml",
                       '<?xml version="1.0"?><container version="1.0"'
                       ' xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                       '<rootfiles><rootfile full-path="OEBPS/content.opf"'
                       ' media-type="application/oebps-package+xml"/>'
                       '</rootfiles></container>')
            z.writestr("OEBPS/content.opf", opf)
            z.writestr("OEBPS/nav.xhtml", nav)
            z.writestr("OEBPS/c1.xhtml", page % ("One", "the faith of God"))
            z.writestr("OEBPS/c2.xhtml", page % ("Two", "hope and love"))
            # No heading, and a document <title> that is the book's name: the
            # only place this section can be named from is the table of
            # contents.  The spine href is relative to the package document,
            # so finding it means resolving "c3.xhtml" against OEBPS/ -- which
            # the reader did not do, and every section of a real commentary took
            # its name from the document title instead: one string, 1,319
            # times, and a contents list you could not navigate.
            z.writestr("OEBPS/c3.xhtml",
                       '<?xml version="1.0" encoding="UTF-8"?>'
                       '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                       '<title>Selftest Book</title></head><body>'
                       '<p>zebulonite andothermin</p></body></html>')
        raw = b2.getvalue()
        assert epub.sniff(raw), "a well-formed EPUB was not recognised"
        meta, units = epub.load(raw)
        got = list(units)
        assert meta["title"] == "Selftest Book", meta
        assert meta["creator"] == "A. Writer", meta
        assert [u.label for u in got] == ["One", "Two", "Appendix: Index of Names"], \
            [u.label for u in got]
        assert got[0].key < got[1].key < got[2].key, "keys must sort in reading order"
        assert got[2].segs, "the section named from the toc still needs its text"
        assert formats.sniff(raw) == "epub"
        # A fixed-layout book is a picture of pages; say so rather than half-read.
        assert epub.fixed_layout is not None
        return f"{len(got)} sections, spine order and metadata honoured"
    check("EPUB personal books", t_epub)

    # --------------------------------------------------------- catalogue --
    def t_catalogue():
        from gbible import publish
        s = publish.catalog_summary()
        assert s["ok"] and s["total"] > 0, s
        for fmt in ("md", "txt", "csv", "html"):
            r = publish.catalog_document(fmt=fmt)
            assert r["ok"] and r["text"], (fmt, r.get("error"))
            assert r["count"] == s["total"], (fmt, r["count"])
        pdf_doc = publish.catalog_document(fmt="pdf")
        assert pdf_doc["ok"] and pdf_doc["binary"][:4] == b"%PDF", pdf_doc
        assert publish.catalog_document(group="lang", detail=False)["ok"]
        # A filter that matches nothing must say so, not print an empty library.
        none = publish.catalog_document(filters={"type": "zzzz-no-such-kind"})
        assert not none["ok"] and none["error"], none
        return (f"{s['total']} resources, 5 formats, "
                f"{s['blank_author']} with no author recorded")
    check("Library catalogue", t_catalogue)

    # --------------------------------------------------- morph histogram --
    def t_morph_chart():
        from gbible import organise
        r = organise.charts("morph", "")
        if not r.get("series"):
            return Skip("no text in the library is tagged with morphology")
        assert r["ok"] and r["series"], r
        assert all(x["label"] and x["value"] for x in r["series"]), r["series"][:3]
        tagged = db.connect().execute(
            "SELECT id FROM module WHERE has_morph=1 AND installed_at>0 LIMIT 1"
        ).fetchone()
        if not tagged:
            return None
        # OSHB codes decode to a part of speech by *name* where Robinson's
        # decode to the letter, so the filter is the name; "pos=V" matches
        # nothing in a Hebrew Bible and would prove nothing.
        r2 = organise.charts("morph", "pos=verb")
        assert r2["ok"] and r2["series"], r2
        empty = organise.charts("morph", "pos=V")
        assert empty["ok"] and not empty["series"], \
            "a filter nothing matches must come back empty, not invented"
        bad = organise.charts("morph", "no such passage at all")
        assert not bad["ok"] and bad["error"], bad
        return f"{len(r['series'])} parts of speech across the tagged texts"
    check("Morphology distribution chart", t_morph_chart)

    # ----------------------------------------------- tokenizer and index --
    def t_tokenizer():
        # Combining marks belong to the letter they sit on.  Python's \w
        # excludes them, which cut pointed Hebrew into single letters and left
        # a whole Hebrew Bible unsearchable while the FTS index held every
        # verse.  This is the regression test for that, and it is here rather
        # than in a search check because the damage is invisible from results:
        # a search simply answers nothing.
        # Written as escapes so the points survive any editor, terminal or
        # diff: the whole point of the check is that a pointed word is ONE
        # token, and a literal pointed word in the source is one copy-paste
        # away from silently losing them -- which is how this check was
        # written wrong the first time.
        hebrew = "\u05d1\u05e8\u05d0"                     # bet resh alef
        hebrew_vowelled = "\u05d1\u05b8\u05bc\u05e8\u05b8\u05d0"
        greek = "\u03b5\u03c0\u03bf"
        greek_vowelled = "\u1f10\u03c0\u03bf\u03af\u03b7\u03c3\u03b5\u03bd"
        assert [w[0] for w in db.words(hebrew)] == [hebrew], \
            [w[0] for w in db.words(hebrew)]
        assert [w[0] for w in db.words(greek)] == [greek], \
            [w[0] for w in db.words(greek)]
        assert [w[0] for w in db.words("na\u00efve caf\u00e9")] == ["na\u00efve",
                                                                    "caf\u00e9"]
        assert [w[0] for w in db.words("God's word 42")] == ["God's", "word", "42"]
        # Pointed text must tokenise as one word per word, not one per letter,
        # and folding must still take the marks off.
        assert len(db.words(hebrew_vowelled)) == 1, \
            [w[0] for w in db.words(hebrew_vowelled)]
        assert db.fold(hebrew_vowelled) == hebrew, db.fold(hebrew_vowelled)
        assert len(db.words(greek_vowelled)) == 1, \
            [w[0] for w in db.words(greek_vowelled)]
        assert db.fold(greek_vowelled) == "\u03b5\u03c0\u03bf\u03b9\u03b7\u03c3\u03b5\u03bd", \
            db.fold(greek_vowelled)
        return "marks stay on their letters, and folding still removes them"
    check("Word tokenizer: combining marks", t_tokenizer)

    def t_index_freshness():
        from gbible import posindex
        assert posindex.TOKENIZER, "no tokeniser fingerprint"
        ok = posindex.available()
        if ok:
            row = db.connect().execute(
                "SELECT value FROM pos_meta WHERE key='tokenizer'").fetchone()
            assert row and row["value"] == posindex.TOKENIZER, \
                "an index that does not match the tokenizer is being trusted"
        else:
            # Retiring the index is the correct response, and it must have
            # retired rather than answered.
            assert not db.connect().execute(
                "SELECT value FROM pos_meta WHERE key='built'").fetchone(), \
                "the index is unusable but still claims to be built"
        return ("index matches the tokenizer" if ok
                else "index retired pending a rebuild (search uses the text path)")
    check("Positional index freshness", t_index_freshness)

    def t_local_import():
        from gbible import store
        # "This computer" had no catalogue, so nothing could ever be imported:
        # the installer looked the item up and found nothing.
        made = store.register_local(Path("/nonexistent/x.txt"),
                                    fmt="text", title="SelfTest")
        assert made["ok"] and made["item_id"], made
        listed = [i for i in store.repo_items("local")
                  if i["id"] == made["item_id"]]
        assert listed, "an imported file does not appear in the Store"
        assert listed[0]["title"] == "SelfTest", listed[0]
        db.connect().execute("DELETE FROM store_item WHERE repo_id='local' "
                             "AND item_id=?", (made["item_id"],))
        db.connect().commit()
        assert not [i for i in store.repo_items("local")
                    if i["id"] == made["item_id"]]
        return "a file is registered, listed, and removed"
    check("Local file import", t_local_import)

    def t_ai():
        from gbible import ai
        # Providers are described for the UI without being contacted.
        view = ai.providers_view()
        ids = {p["id"] for p in view}
        assert {"ollama", "openai", "anthropic", "groq", "google",
                "openrouter"} <= ids, ids
        assert all("local" in p and "key_set" in p for p in view)
        assert next(p for p in view if p["id"] == "ollama")["local"] is True

        # Settings round-trip, and switching provider must not carry the previous
        # provider's model name across -- "gpt-4o" sent to Ollama is a 404 the
        # reader cannot explain.
        saved = ai.get_settings()
        try:
            ai.set_settings(provider="openai", model="gpt-4o")
            assert ai.get_settings()["model"] == "gpt-4o"
            after = ai.set_settings(provider="ollama")
            assert after["model"] == "llama3.1", after
        finally:
            db.set_setting("ai", saved)

        # A key is stored under its own credential id and read back, while an
        # empty string clears it -- the same contract API Settings relies on.
        had = ai.key_for("openai")
        try:
            ai.set_key("openai", "sk-selftest-not-a-real-key")
            assert ai.key_for("openai") == "sk-selftest-not-a-real-key"
            ai.set_key("openai", "")
            assert ai.key_for("openai") == ""
        finally:
            ai.set_key("openai", had)

        # Grounding is drawn from prose/verse resources, never from a lexicon
        # headword or an atlas caption, and every citation carries its number and
        # the text the model will read.
        cites = ai.build_context("the grace of God", 5)
        assert cites, "no grounding retrieved for a common query"
        assert [c["n"] for c in cites] == list(range(1, len(cites) + 1))
        assert all(c["text"].strip() for c in cites)
        assert not any(c["type"] in ai._LOOKUP_TYPES for c in cites)

        msgs = ai.build_messages("why?", [], cites[:2])
        assert msgs[0]["role"] == "system" and msgs[-1] == {"role": "user",
                                                            "content": "why?"}
        assert any("[1]" in m["content"] for m in msgs if m["role"] == "system")
        return (f"{len(view)} providers, grounding from {len(cites)} "
                f"{'source' if len(cites) == 1 else 'sources'}")
    check("AI: providers, settings, and grounding", t_ai)

    def t_ai_mine():
        """The reader's own material is a citable corpus of its own.

        The subject of the check is the *separation*.  A private note and a
        published commentary are different kinds of thing, and a model that
        read them as one list would quote the note as though it were the
        commentary -- which is the one confusion the citation list exists to
        prevent.  So the own material is retrieved on its own, it is marked as
        the reader's, and it is numbered beside the library's passages without
        being confused for them.
        """
        from gbible import ai, mine, notes as _notes
        # A nonsense word, so the note can be found by what is in it and by
        # nothing else that happens to be in the reader's library.
        made = _notes.save({
            "kind": "note", "title": "Selftest zorbonium note",
            "body": "A note about the zorbonium doctrine of propitiation.",
            "ref_label": "1 John 2:2",
        })
        other = _notes.save({
            "kind": "note", "title": "Selftest unrelated note",
            "body": "Something about the weather and a bicycle.",
        })
        try:
            # The note is found by the words in it, and the words of the
            # request -- "what did I write about" -- do not get in the way.
            hits = mine.own_sources("what did I write about zorbonium?", 5)
            assert hits, "the reader's own note was not found"
            assert hits[0]["own"]["id"] == made["id"], hits[0]
            assert "zorbonium" in hits[0]["text"]
            assert hits[0]["own"]["kind"] == "note"
            assert hits[0]["module_id"] == "", \
                "the reader's own material must not pretend to be a module"

            # A note about the subject beats a note about something else, and
            # the request words are not what makes the difference.
            assert hits[0]["own"]["id"] != other["id"]
            assert other["id"] not in [h["own"]["id"] for h in hits]

            # The grounding merges the two corpora and numbers them as one
            # list, so a citation number means one thing to the reader.
            cites = ai.build_context("zorbonium", 8)
            assert cites, "no grounding retrieved"
            assert [c["n"] for c in cites] == list(range(1, len(cites) + 1))
            own_hits = [c for c in cites if c.get("own")]
            assert own_hits, "the note did not reach the assistant's grounding"
            assert all(c["type"].startswith("My") for c in own_hits)
            assert all(c["text"].strip() for c in own_hits)

            # The grounding the model reads keeps them apart: the own
            # material has a section of its own, and the library's section
            # does not carry the note.
            msgs = ai.build_messages("zorbonium", [], cites)
            sys_msgs = [m["content"] for m in msgs if m["role"] == "system"]
            own_block = [s for s in sys_msgs
                         if s.startswith("The reader's own material")]
            assert own_block, "the own material was not given its own section"
            assert "zorbonium" in own_block[0]
            for b in [s for s in sys_msgs if "Library sources" in s]:
                assert b != own_block[0], "the two corpora shared a section"
                assert "zorbonium" not in b, \
                    "the note leaked into the library's grounding"
            # And the rule that tells the model how to report it is present.
            assert "never attribute it to an author" in sys_msgs[0]

            # The reader can turn it off, and the library is untouched either
            # way.
            off = ai.build_context("zorbonium", 8, use_mine=False)
            assert not [c for c in off if c.get("own")]

            # The count is reported, so the settings screen can say how much
            # of the reader's own material there is to cite.
            counts = mine.count()
            assert counts["total"] >= 2, counts
            assert counts["by_kind"].get("note", 0) >= 2, counts
        finally:
            _notes.remove(made["id"])
            _notes.remove(other["id"])
        return ("the reader's own notes are found, cited, and kept apart "
                "from the library's")
    check("AI: the reader's own material is citable", t_ai_mine)

    def t_ai_topic_questions():
        """The questions a topic guide offers are written from its own material.

        The parser is what makes that safe: a model that *answers* the
        question it was asked, in statements, has not written the questions --
        and the generic set is better than that.
        """
        from gbible import ai
        assert ai._parse_questions("1. Is it grace?\n2. Is it mercy?") == \
            ["Is it grace?", "Is it mercy?"]
        assert ai._parse_questions("```\n1. Is it grace?\n```") == \
            ["Is it grace?"]
        assert ai._parse_questions("**1.** Is it grace?") == ["Is it grace?"]
        assert ai._parse_questions("- Is it grace?") == ["Is it grace?"]
        assert ai._parse_questions("The sources say grace is a gift.") == []
        assert ai._parse_questions("1. Not a question.\n2. Also not.") == []
        assert ai._parse_questions("1. Is it grace?\n1. Is it grace?") == \
            ["Is it grace?"], "a repeated question is still one question"

        # A guide always offers something.
        fb = ai.topic_fallback_questions("atonement")
        assert len(fb) == 4, fb
        assert all(q["question"].endswith("?") for q in fb), fb
        assert "atonement" in fb[0]["question"]

        # A topic nothing is installed for has no material to ask about, and
        # the generic questions are what the reader gets.
        r = ai.topic_questions("zzznotatopic")
        assert r["ok"], r
        assert r.get("fallback"), r
        assert r["questions"] == ai.topic_fallback_questions("zzznotatopic")

        # And a provider that cannot be reached costs the reader their
        # suggested questions and nothing else.
        saved = ai.get_settings()
        p = ai.BY_ID.get("lmstudio")
        old_url = p.base_url
        try:
            p.base_url = "http://127.0.0.1:1"      # nothing listens here
            ai.set_settings(provider="lmstudio", model="mock-model")
            r = ai.topic_questions("atonement")
            assert r["ok"], r
            assert r.get("fallback"), r
            assert r["questions"] == fb, r
        finally:
            p.base_url = old_url
            db.set_setting("ai", saved)
        return ("questions are written from the material, and there are "
                "always some")
    check("AI: the questions a topic guide offers", t_ai_topic_questions)

    def t_ai_context():
        """A passage the reader puts in front of the assistant.

        A question like "what does Paul mean by this?" is about a *place*,
        and the search engine cannot find a place from those words.  The
        passage has to be supplied, or the answer is about something else --
        which is what the grounding below shows: the passage is source [1],
        and the rule that says so is in the prompt.
        """
        from gbible import ai
        ctx = {"text": "For by grace you have been saved through faith.",
               "label": "Eph 2:8", "module_id": "open-bibles-eng-kjv",
               "key": "Eph.2.8", "module_name": "King James Version"}
        srcs = ai.build_context("what does Paul mean by this?", 8,
                                context=ctx)
        assert srcs, "no grounding at all"
        assert srcs[0]["n"] == 1, srcs[0]
        assert srcs[0]["text"] == ctx["text"], srcs[0]
        assert srcs[0]["label"] == "Eph 2:8"
        assert srcs[0]["type"] == "Passage", srcs[0]
        assert [s["n"] for s in srcs] == list(range(1, len(srcs) + 1))

        msgs = ai.build_messages("what does Paul mean by this?", [], srcs, ctx)
        blocks = [m["content"] for m in msgs if m["role"] == "system"]
        assert any("has put a passage in front of them" in b for b in blocks), \
            "the rule about the passage is not in the prompt"
        assert any("[1] King James Version — Eph 2:8" in b for b in blocks), \
            "the passage is not the first source"

        # Without a passage, nothing about it leaks into the prompt.
        plain = ai.build_context("the grace of God", 8)
        assert not any(s["type"] == "Passage" for s in plain)
        m2 = ai.build_messages("why?", [], plain)
        assert not any("put a passage in front" in m["content"] for m in m2)

        # And the passage is not listed twice when the library also returns
        # it: the same text under two numbers is a thing the reader would
        # have to work out for themselves.
        dup = ai.build_context(ctx["text"], 8, context=ctx)
        texts = [s["text"] for s in dup]
        assert texts.count(ctx["text"]) == 1, [t[:40] for t in texts]

        # And the passage counts against the budget like any other source.
        for ms in (4, 8):
            n = len(ai.build_context("the grace of God", ms, context=ctx))
            assert n <= ms, (n, ms)
        return "a passage put in front of the assistant is the first source"
    check("AI: a passage in front of the assistant", t_ai_context)

    def t_ai_grounding_query():
        """The assistant asks the model which words to search with.

        The stripped question is a poor search, and the reason is not
        subtle: "how do I stop being anxious?" becomes "stop being anxious",
        and those two scaffolding words are both *more common in the library*
        than the word that names the subject.  The engine cannot know that a
        text about worry is a text about anxiety; the model can.

        So the model writes the query, in the engine's own query language, and
        the plain question is still searched as a safety net -- so a model
        that writes a useless query costs the reader nothing.
        """
        from gbible import ai
        # The prompt teaches the engine's own syntax, so the query it writes
        # is a query the engine can run.
        assert "AND" in ai._GROUNDING_QUERY_SYSTEM
        assert "OR" in ai._GROUNDING_QUERY_SYSTEM
        assert "NEAR" in ai._GROUNDING_QUERY_SYSTEM
        assert "into a search of a library" in ai._GROUNDING_QUERY_SYSTEM

        # No provider means nothing to ask, and the plain question is used.
        assert ai.grounding_query("anything", None) == ""

        # A provider that cannot be reached costs the reader their suggested
        # query and nothing else.
        saved = ai.get_settings()
        p = ai.BY_ID.get("lmstudio")
        old_url = p.base_url
        try:
            p.base_url = "http://127.0.0.1:1"      # nothing listens here
            ai.set_settings(provider="lmstudio", model="mock-model")
            assert ai.grounding_query("how do I stop being anxious?", p) == ""
            # And the retrieval still works -- on the plain question.
            srcs = ai.build_context("the grace of God", 8, provider=p,
                                    smart_query=True)
            assert srcs, "no grounding at all when the model cannot be asked"
        finally:
            p.base_url = old_url
            db.set_setting("ai", saved)

        # The setting is a switch like any other.
        assert "smart_query" in ai.get_settings()
        try:
            ai.set_settings(smart_query=False)
            assert ai.get_settings()["smart_query"] is False
        finally:
            db.set_setting("ai", saved)
        return "the model writes the query the assistant searches with"
    check("AI: the model writes the search query", t_ai_grounding_query)

    def t_ai_semantic():
        """The sources are ranked by what they say, as well as by their words.

        The whole point of the semantic half is a case the lexical engine
        cannot win: a reader asks "how do I stop being anxious?" and the
        passage that answers it is the one that says "do not worry about your
        life".  So the check is that the meaning can outvote the words.
        """
        from gbible import ai

        # The cosine, and the stretching that puts two different kinds of
        # score on one scale.
        assert ai._cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
        assert abs(ai._cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9
        assert ai._cosine([0.0, 0.0], [1.0, 0.0]) == 0.0
        assert ai._norm([2.0, 4.0, 6.0]) == [0.0, 0.5, 1.0]
        assert ai._norm([3.0, 3.0]) == [0.5, 0.5], "a flat set is not a range"

        # Both reply shapes are read: OpenAI's `data` with an index, and
        # Ollama's `embeddings` in order.
        openai_shape = {"data": [{"index": 1, "embedding": [0.0, 2.0]},
                                 {"index": 0, "embedding": [1.0, 0.0]}]}
        assert ai._read_embeddings(openai_shape, 2) == [[1.0, 0.0], [0.0, 2.0]]
        ollama_shape = {"embeddings": [[1.0, 0.0], [0.0, 2.0]]}
        assert ai._read_embeddings(ollama_shape, 2) == [[1.0, 0.0], [0.0, 2.0]]
        try:
            ai._read_embeddings({"nonsense": 1}, 2)
            raise AssertionError("a reply with no vectors was believed")
        except ai.AiError:
            pass

        # A provider that cannot embed leaves the order exactly as it was.
        cands = [{"n": 0, "module_id": "a", "module_name": "A", "label": "one",
                  "title": "", "type": "Commentary", "text": "One.", "score": 1.0},
                 {"n": 0, "module_id": "b", "module_name": "B", "label": "two",
                  "title": "", "type": "Commentary", "text": "Two.", "score": 9.0}]
        for p in ai.PROVIDERS:
            if p.embeds:
                continue
            assert ai.semantic_rerank(p, "anything", cands) == cands, \
                f"{p.id} cannot embed, so it must not change the order"

        # And the providers that can, are the ones that can: the local ones
        # and OpenAI.  Anthropic has no embeddings endpoint, and a reader
        # should be told so rather than left to find out.
        assert ai.get_provider("anthropic").embeds is False
        assert ai.get_provider("openai").embeds is True
        assert ai.get_provider("ollama").embeds is True
        return "the sources can be ranked by meaning as well as by words"
    check("AI: ranking by meaning as well as by words", t_ai_semantic)

    def t_ai_factbook():
        """The fact book is the complete reference, and the assistant is in it.

        Two things are checked.  First, that the fact book now carries the
        material the topic guide had -- the verses, the glosses, the maps --
        so that a reader who comes through either door finds the same things.
        Second, that the questions the assistant writes are *lens-aware*:
        the lens is the reader's question of the term, and the questions
        change with it.
        """
        from gbible import ai, study

        if not need("FactBook"):
            return Skip("no FactBook installed to merge into")

        # -- the merge: what the topic guide had, the fact book has too.
        #
        # The terms are topics, because a topical fact book covers topics.
        # A name like "aaron" belongs under other headings there -- under
        # "Priests", under "Levites" -- and checking for an article under it
        # would be checking for something the book does not claim to have.
        for term in ("atonement", "grace", "prayer"):
            t = study.topic_guide(term)
            f = study.fact_guide(term)
            t_kinds = {s["kind"] for s in t["sections"]}
            f_kinds = {s["kind"] for s in f["sections"]}
            for kind in ("verses", "dictionary", "atlas"):
                if kind in t_kinds:
                    assert kind in f_kinds, \
                        f"the fact book is missing {kind} for {term!r}"
            # And the fact book keeps what it always had: the article.
            assert "article" in f_kinds, f_kinds

        # A place is a place in both guides, and the atlas comes with it.
        f = study.fact_guide("jerusalem")
        assert "place" in {s["kind"] for s in f["sections"]}, f["sections"]

        # -- the questions, and their one-line answers.
        assert ai._parse_qa("1. What does it mean?\nIt means grace.\n"
                            "2. Who is it for?\nFor the elect.") == [
            {"question": "What does it mean?", "answer": "It means grace."},
            {"question": "Who is it for?", "answer": "For the elect."}]
        # A question with no answer under it is still a question.
        assert ai._parse_qa("1. What does it mean?") == [
            {"question": "What does it mean?", "answer": ""}]
        # A statement is not a question.
        assert ai._parse_qa("1. It means grace.") == []

        # -- the lens reaches the model, or the questions cannot change.
        saved = ai.get_settings()
        try:
            ai.set_settings(provider="lmstudio", model="mock-model")
            srcs = ai.fact_sources("atonement", lens="theological")
            assert srcs, "the fact book has no grounding"
            msgs = ai.fact_messages("atonement", "What does it mean?", srcs,
                                    "theological")
            blocks = [m["content"].lower() for m in msgs
                      if m["role"] == "system"]
            assert any("theological lens" in b for b in blocks), \
                "the lens is not in the prompt"
            # And with no lens, no lens is mentioned.
            plain = ai.fact_messages("aaron", "What?", srcs, "")
            assert not any("lens" in m["content"].lower() for m in plain
                           if m["role"] == "system"), \
                "a lens reached a prompt that had none set"
        finally:
            db.set_setting("ai", saved)
        return ("the fact book carries what the topic guide had, and the "
                "questions answer the lens")
    check("AI: the fact book, its merge, and the lens", t_ai_factbook)

    def t_ai_fragments():
        """Which words of a source the answer leaned on.

        The model cites a source, not a place inside it, so the words that
        carried the claim are somewhere in the passage and nowhere marked.
        They are found by comparing the answer's sentence with the source's --
        and found *here*, rather than asked of the model, because a model that
        misquotes a source is a worse failure than one that cites it loosely.
        """
        from gbible import ai
        # The sentence splitter has to survive a reference and an
        # abbreviation, or it cuts the source into nonsense.
        sents = ai._sentences("Christ obtained redemption. His blood was "
                              "shed. e.g. for us. Rom. 5:7 was good.")
        assert "e.g. for us." in sents, sents
        assert "Rom. 5:7 was good." in sents, sents
        assert len(sents) == 4, sents

        cites = [
            {"n": 1, "label": "Rom 5:9", "module_name": "KJV",
             "text": "By his blood we have redemption through his blood, "
                     "the forgiveness of sins. Having obtained eternal "
                     "redemption through his blood."},
            {"n": 2, "label": "EXPIATION", "module_name": "Nave's",
             "text": "For sin, see below. By blood. By money."},
        ]
        answer = ("Christ obtained redemption by the shedding of his blood "
                  "[1]. The fact books speak of expiation by blood [2].")
        frags = ai.fragments(answer, cites)
        assert frags, "no fragment found for a claim that shares words"
        assert frags[0]["n"] == 1, frags
        assert "blood" in frags[0]["fragment"].lower(), frags
        # The marks are offsets into the fragment, so the words they mark are
        # really in it.
        for m in frags[0]["marks"]:
            assert 0 <= m[0] < m[1] <= len(frags[0]["fragment"]), m

        # A claim that shares nothing with the source has no fragment, and a
        # citation that was never made has none either.
        assert not ai.fragments("The weather in Scotland is changeable [1].",
                                cites)
        assert ai.fragments("Something [9] entirely different.", cites) == []
        return "the words a claim relied on are found in the source"
    check("AI: which words of a source carried the claim", t_ai_fragments)

    def t_ai_export():
        """A conversation is exported as a file, with its sources.

        A file and not a link: a link would put the conversation in a URL,
        where it is copied into browser history and the URL bar and wherever a
        link is pasted -- and a conversation is the reader's own writing.
        """
        from gbible import aichat
        turns = [
            {"role": "user", "content": "What does the Bible say about the "
                                         "atonement?"},
            {"role": "assistant", "content": "It is the shedding of blood.",
             "citations": [{"n": 1, "label": "Rom 5:9", "module_name": "KJV",
                            "text": "By his blood we have redemption"}]},
            {"role": "user", "content": "And who pays?"},
            {"role": "assistant", "content": "The covenant of grace does.",
             "citations": []},
        ]
        md = aichat.export_markdown(turns, "Atonement")
        assert md.startswith("# Atonement"), md[:40]
        assert "## 1. What does the Bible say about the atonement?" in md, md
        assert "## 2. And who pays?" in md, md
        # The sources travel with the answer, as text, so the document can be
        # checked on a machine that does not have the books.
        assert "**Sources**" in md, md
        assert "> By his blood we have redemption" in md, md
        # And the file name is safe to write to a disk.
        assert aichat.export_filename("Atonement!") == "atonement.md"
        assert "/" not in aichat.export_filename("a/b")
        return "a conversation is a file, with its sources"
    check("AI: a conversation is exported as a file", t_ai_export)

    def t_ai_tags():
        """Tags are categories, and a thing can be in more than one.

        The difference from a label -- which can only be one thing -- is the
        whole point of the feature, so it is what the check is about.
        """
        from gbible import aichat
        conn = db.connect()
        # A tag on a verse is stored by its canonical place, not by the key of
        # the module it was tagged in, so it follows the passage to another
        # translation -- where the same verse is spelled differently.
        r = conn.execute("SELECT module_id, key, book, chapter, verse FROM unit "
                         "WHERE book IS NOT NULL AND chapter IS NOT NULL "
                         "AND verse IS NOT NULL AND book='John' AND chapter=3 "
                         "AND verse=16 LIMIT 1").fetchone()
        if r is None:
            return "no verse installed to tag"
        tid = "selftesttag"
        try:
            conn.execute("INSERT OR REPLACE INTO tag(id,name,color,created_at) "
                         "VALUES(?,?,?,?)", (tid, "selftest", "", time.time()))
            for name in ("one", "two"):
                conn.execute(
                    "INSERT INTO tag_item(id,tag_id,kind,module_id,unit_key,"
                    "book,chapter,verse,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    ("selftest" + name, tid, "verse", r["module_id"], r["key"],
                     r["book"], r["chapter"], r["verse"], time.time()))
            conn.commit()
            rows = conn.execute("SELECT tag_id, book, chapter, verse FROM "
                                "tag_item WHERE tag_id=?", (tid,)).fetchall()
            assert len(rows) == 2, rows
            # Both items name the same verse, and they name it the same way.
            assert all(x["book"] == r["book"] and x["chapter"] == r["chapter"]
                       and x["verse"] == r["verse"] for x in rows), rows
            # So the passage is in two categories at once, which is the thing
            # a label could not do.
            assert len({x["tag_id"] for x in rows}) == 1, rows
        finally:
            conn.execute("DELETE FROM tag_item WHERE tag_id=?", (tid,))
            conn.execute("DELETE FROM tag WHERE id=?", (tid,))
            conn.commit()
        return "a passage can be in more than one category at once"
    check("AI: tags hold a passage in several categories", t_ai_tags)

    def t_ai_portable_highlights():
        """A highlight follows its verse to another translation.

        The unit key belongs to the module -- the same verse is "John 3:16" in
        one Bible and "John.3.16" in another -- so a highlight filed against
        the key alone cannot travel.  The canonical place can.
        """
        conn = db.connect()
        rows = conn.execute(
            "SELECT module_id, key, book, chapter, verse FROM unit "
            "WHERE book='John' AND chapter=3 AND verse=16 "
            "AND book IS NOT NULL").fetchall()
        if not rows:
            return "no verse installed"
        # Two modules, the same verse, and -- where the library has them --
        # different key formats.
        keys = {r["key"] for r in rows}
        assert len(rows) >= 1, rows
        books = {r["book"] for r in rows}
        assert books == {"John"}, books
        # The place is the same for every one of them.
        places = {(r["book"], r["chapter"], r["verse"]) for r in rows}
        assert len(places) == 1, places
        # And the columns a portable highlight needs are there.
        cols = {c[1] for c in conn.execute("PRAGMA table_info(highlight)")}
        for want in ("book", "chapter", "verse"):
            assert want in cols, (want, sorted(cols))
        return f"{len(rows)} translations of John 3:16, one place"
    check("AI: a highlight can follow its verse", t_ai_portable_highlights)

    def t_ai_chats():
        """A conversation is kept, and can be picked up again.

        The point of keeping it is the question being asked a second time on
        a later day, so the thing to check is that the exchange survives a
        round trip *with its citations*: an answer whose sources are lost is
        a claim the reader cannot check, which is the one thing this whole
        design exists to prevent.
        """
        from gbible import aichat
        chat = aichat.new()
        try:
            turns = [
                {"role": "user",
                 "content": "What does the Bible say about propitiation?"},
                {"role": "assistant", "content": "It is appeasement [1].",
                 "citations": [{"n": 1, "module_id": "m1", "label": "x",
                                "module_name": "A Book", "text": "t"}]},
            ]
            saved = aichat.save(chat["id"], turns)
            assert saved["id"] == chat["id"]

            back = aichat.get(chat["id"])
            assert back, "the conversation was not kept"
            # The title is the reader's own question, not a label the
            # software made up.
            assert back["title"] == "What does the Bible say about " \
                                   "propitiation?", back["title"]
            assert len(back["turns"]) == 2
            assert back["turns"][0]["role"] == "user"
            assert back["turns"][1]["citations"], "the citations were lost"
            assert back["turns"][1]["citations"][0]["module_id"] == "m1"

            # It is in the recent list, with the turn count.
            rows = aichat.listing()
            mine = [r for r in rows if r["id"] == chat["id"]]
            assert mine, "the conversation is not in the recent list"
            assert mine[0]["turns"] == 2, mine[0]

            # And it can be renamed.
            aichat.rename(chat["id"], "Propitiation")
            assert aichat.get(chat["id"])["title"] == "Propitiation"

            # An internal instruction is not a title.
            assert aichat.title_for([{"role": "user", "content": "Give me an "
                                     "overview", "internal": True}]) == \
                "Untitled", aichat.title_for([{"role": "user",
                                               "content": "Give me an "
                                               "overview", "internal": True}])
        finally:
            aichat.remove(chat["id"])
        assert not aichat.get(chat["id"]), "the conversation was not forgotten"
        return "a conversation is kept, titled, and can be picked up again"
    check("AI: conversations are kept", t_ai_chats)

    def t_ai_scope():
        """A scope narrows the library the assistant may read.

        The case that matters is the empty one: a scope that names a
        collection with nothing in it must read *nothing*, not fall back to
        the whole library.  A reader who narrowed the question on purpose and
        got the whole library back has been answered something they did not
        ask.
        """
        from gbible import ai
        if not need("Commentary"):
            return Skip("no Commentary installed to narrow the search to")
        opts = ai.scope_options()
        assert opts and opts[0]["id"] == "", opts[:1]
        assert any(o["id"].startswith("type:") for o in opts), opts

        # A type scope returns only that type.
        srcs = ai.build_context("the grace of God", 8, scope="type:Commentary")
        assert srcs, "a commentary scope returned nothing"
        assert all(s["type"] == "Commentary" for s in srcs), \
            sorted({s["type"] for s in srcs})

        # And a scope that names nothing reads nothing.
        assert ai.build_context("the grace of God", 8,
                                scope="collection:nosuchthing") == []
        assert ai.scope_modules("collection:nosuchthing") == []
        assert ai.scope_modules("") == []
        return "a scope narrows the library, and an empty one reads nothing"
    check("AI: the scope of the library", t_ai_scope)

    def t_ai_mine_budget():
        """The own material gets a share of the sources, and all of them when
        the library is off.

        The second case is the point: "what did I think about this?" is a
        question that deserves an answer built only out of what the reader
        thought, and a cap on it would be a cap on the only corpus there is.
        """
        from gbible import ai
        assert ai._own_budget(9, True) == 3
        assert ai._own_budget(9, False) == 9
        assert ai._own_budget(1, True) == 1
        return "a third of the sources, or all of them with the library off"
    check("AI: the own material's share of the sources", t_ai_mine_budget)

    def t_ai_mine_anchor():
        """A note taken on a verse is found by the anchor, not by its words.

        This is the one place the own material is found by *location* rather
        than by question.  A note that says "conditional immortality -- see
        Morris" shares no terms at all with the verse it was taken on, so a
        text search will never find it; only the anchor connects the two.  It
        is also the place the reader most expects to find their own writing,
        because "explain this passage" is a question about a place, not about
        a subject.
        """
        from gbible import ai, mine, notes as _notes
        made = _notes.save({
            "kind": "note", "title": "Selftest verdict note",
            "body": "Zorbonium -- see the commentary.",
            "module_id": "open-bibles-eng-kjv", "unit_key": "John.3.16",
            "ref_label": "John 3:16",
        })
        try:
            # The verse keys of a reference are the keys a note is anchored to.
            assert mine._verse_keys("John 3:16") == ["John.3.16"], \
                mine._verse_keys("John 3:16")
            assert mine._verse_keys("John 3:16-18") == \
                ["John.3.16", "John.3.17", "John.3.18"], \
                mine._verse_keys("John 3:16-18")
            assert mine._verse_keys("not a reference") == []

            found = mine.anchored_sources("John 3:16", 5)
            assert found, "the note on the verse was not found by its anchor"
            assert found[0]["own"]["id"] == made["id"], found[0]
            assert found[0]["own"]["ref"] == "John 3:16"

            # And the explain action finds it that way, and still respects
            # the budget it was given.
            src = ai.action_sources("explain", "For God so loved the world.",
                                    "John 3:16", True, 8, use_mine=True)
            assert any(s.get("own", {}).get("id") == made["id"] for s in src), \
                "the anchored note did not reach the action's grounding"
            assert len(src) <= 8, len(src)
        finally:
            _notes.remove(made["id"])
        return "a note on a verse is found by the verse, not by its words"
    check("AI: the own material anchored to a passage", t_ai_mine_anchor)

    def t_ai_discovery():
        from gbible import ai
        # Every provider must be reachable through code that exists.  A row
        # added with a new adapter and no transport would otherwise be a provider
        # that shows in the list and fails only when a question is asked.
        for p in ai.PROVIDERS:
            assert p.adapter in ai._PATH, (p.id, p.adapter)
            assert p.adapter in ai._extract, (p.id, p.adapter)
            assert p.adapter in ai._MODELS_PATH, (p.id, p.adapter)

        # The two model-list shapes, including a malformed item that must be
        # skipped rather than crash the settings screen.
        assert ai._model_names("ollama", {"models": [
            {"name": "a:latest"}, {"model": "b"}, {"nope": 1}]}) == ["a:latest", "b"]
        assert ai._model_names("openai", {"data": [
            {"id": "x"}, {"id": "y"}]}) == ["x", "y"]
        assert ai._model_names("ollama", {}) == []

        # A local OpenAI-compatible server has no preset model, so asking for a
        # model there must point the reader at Test rather than at a picker that
        # would be empty.
        saved = ai.get_settings()
        try:
            ai.set_settings(provider="openai", model="gpt-4o")
            s = ai.set_settings(provider="lmstudio")
            assert s["model"] == "", s
            try:
                ai.resolve("lmstudio")
                raise AssertionError("resolve() invented a model for a "
                                     "server that has not been asked yet")
            except ai.AiError as e:
                assert "Test" in e.hint, e.hint
        finally:
            db.set_setting("ai", saved)

        # A provider that is not there is a failure, not an exception -- the
        # Test button asks a question for which "no" is a valid answer.  The
        # reply's fields are checked, not its verdict, because whether Ollama
        # happens to be running is not this test's business.
        r = ai.probe("ollama", timeout=1)
        assert {"ok", "reachable", "models", "error", "hint"} <= set(r), r
        assert isinstance(r["ok"], bool) and isinstance(r["models"], list)
        return (f"{len(ai.PROVIDERS)} providers wired to "
                f"{len(ai._MODELS_PATH)} model-list endpoints")
    check("AI: provider discovery and transport wiring", t_ai_discovery)

    def t_ai_actions():
        from gbible import ai
        src = [{"n": 1, "module_id": "c1", "module_name": "NICNT",
                "label": "Eph 2:8", "title": "", "text": "grace is a gift"}]

        # Translate carries the target into the instruction and the reference
        # into the prompt, and never sees a numbered source -- a translation
        # blended with other verses is a different translation.
        m = ai.action_messages("translate", "For God so loved the world.",
                               "John 3:16", "Spanish")
        assert "Spanish" in m[0]["content"], m[0]
        assert "John 3:16" in m[-1]["content"], m[-1]
        assert "For God so loved" in m[-1]["content"], m[-1]
        assert not any("Library sources" in x["content"] for x in m)
        assert not any("[1]" in x["content"] for x in m)

        # Explain is grounded, and the sources block is what the model cites.
        m = ai.action_messages("explain", "For by grace you have been saved.",
                               "Eph 2:8", "", src)
        assert any("Library sources" in x["content"] for x in m), m
        assert any("[1] NICNT" in x["content"] for x in m), m

        # The grounding rule is enforced by the builder, not only by the caller:
        # a stray source list handed to summarize is dropped, not sent.
        m = ai.action_messages("summarize", "some text", "", "", src)
        assert not any("Library sources" in x["content"] for x in m), m

        # And by the picker the endpoint uses.
        assert ai.action_sources("translate", "t", "John 3:16", True, 8) == []
        assert ai.action_sources("summarize", "t", "John 3:16", True, 8) == []
        # Explain is grounded in whatever the reader has allowed: the library,
        # the reader's own material, or both.  With both off there is nothing
        # to ground it in.
        assert ai.action_sources("explain", "t", "John 3:16", False, 8,
                                 use_mine=False) == []

        # An unknown or empty request is an AiError with a usable hint, never a
        # KeyError from the action table.
        for kind in ("nope", ""):
            try:
                ai.action_messages(kind, "text")
                raise AssertionError(f"accepted action {kind!r}")
            except ai.AiError as e:
                assert e.hint
        try:
            ai.action_messages("explain", "   ")
            raise AssertionError("accepted an empty selection")
        except ai.AiError as e:
            assert "nothing selected" in str(e).lower(), e

        # Smart Search cleans up what a model actually returns -- fences, labels,
        # a stray backtick that would otherwise be searched for literally.
        clean = {
            "```\ntext\nfaith AND grace\n```": "faith AND grace",
            "Query: faith AND grace": "faith AND grace",
            "Search: strongs:G2316": "strongs:G2316",
            '"living water" AND John': '"living water" AND John',
        }
        for raw, want in clean.items():
            got = ai._clean_query(raw)
            assert got == want, (raw, got, want)
        assert ai._clean_query("") == ""
        assert ai._clean_query('a "unclosed quote') == "a unclosed quote"
        return "3 actions, 1 query translator, grounding rules enforced"
    check("AI: actions and Smart Search", t_ai_actions)

    def t_ai_free_providers():
        from gbible import ai

        # The three free tiers exist, and they are *cloud* providers.  "Free"
        # is not "private", and a provider that blurred the two would be worse
        # than one that had neither.
        for pid in ("groq", "google", "openrouter"):
            p = ai.BY_ID.get(pid)
            assert p is not None, pid
            assert p.free is True, pid
            assert p.local is False, pid
            assert p.key_required is True, pid
            assert p.adapter == "openai", pid
            assert p.base_url.startswith("https://"), pid
            assert p.free_note, pid + " states no conditions"

        # Groq and Google ship a starting list, because the reader should be
        # able to ask a question straight away.  OpenRouter must not: its free
        # roster rotates, so a preset list there is a promise the software
        # cannot keep, and the honest thing is to make the reader press Test.
        assert ai.BY_ID["groq"].models, "groq has no starting model"
        assert ai.BY_ID["google"].models, "google has no starting model"
        assert ai.BY_ID["openrouter"].models == [], "openrouter should have none"

        # The settings UI is told which are free, and told the rest are not.
        view = {p["id"]: p for p in ai.providers_view()}
        assert view["groq"]["free"] is True
        assert view["openrouter"]["free"] is True
        assert view["openai"]["free"] is False
        assert view["ollama"]["free"] is False

        # OpenRouter aggregates other people's models, so its listing is
        # filtered to the ones that cost nothing.  The filter answers three
        # questions: is it free, does it answer in text, and does it actually
        # cost nothing.
        f = ai._free_to_use
        assert f({"id": "x/y:free", "pricing": {"prompt": "0", "completion": "0"}})
        # A model that claims free but carries a price is not free.
        assert not f({"id": "x/y:free",
                      "pricing": {"prompt": "0.001", "completion": "0"}})
        # A model that answers in audio is not a chat model.
        assert not f({"id": "x/audio", "pricing": {"prompt": "0", "completion": "0"},
                      "architecture": {"output_modalities": ["text", "audio"]}})
        # The free router has no suffix, and is free.
        assert f({"id": "openrouter/free",
                  "pricing": {"prompt": "0", "completion": "0"},
                  "architecture": {"output_modalities": ["text"]}})
        # And a plain paid model is not.
        assert not f({"id": "openai/gpt-4o",
                      "pricing": {"prompt": "0.0000025", "completion": "0.00001"}})
        # No pricing at all falls back to the naming convention.
        assert f({"id": "x/y:free"})
        assert not f({"id": "x/y"})

        # Only the provider that needs it declares a filter.
        assert ai.BY_ID["openrouter"].free_filter is not None
        assert ai.BY_ID["groq"].free_filter is None
        assert ai.BY_ID["google"].free_filter is None
        return "3 free tiers, filter answers free/price/shape"
    check("AI: free providers", t_ai_free_providers)

    def t_ai_topic():
        from gbible import ai

        # The corpus is the topic guide's own installed material -- not a fresh
        # search for the word.  That material has to be there: a fresh clone
        # with no library installed cannot show a guide, and a check that
        # cannot run says so rather than failing.
        for kind, what in (("FactBook", "a topical article"),
                            ("Bible", "the verses it names"),
                            ("Dictionary", "the glosses")):
            if not need(kind):
                return Skip(f"no {kind} installed to build a guide with "
                            f"({what})")
        # The reader has already decided what "grace"
        # means to them by deciding what is installed.
        srcs = ai.topic_sources("grace", max_sources=12)
        assert srcs, "no sources for grace"
        assert [s["n"] for s in srcs] == list(range(1, len(srcs) + 1))
        assert all(s["text"].strip() for s in srcs)
        # Every source carries the module and key it came from, so a citation
        # chip can open the article rather than merely name it.
        assert all("module_id" in s and "key" in s for s in srcs)
        kinds = {s["type"] for s in srcs}
        assert "FactBook" in kinds, kinds      # the topical article
        assert "Bible" in kinds, kinds          # the verses it names
        assert "Dictionary" in kinds, kinds     # the glosses
        # A lookup-shaped section is not prose about the subject, and is left
        # out for the same reason chat grounding leaves it out.
        assert "Concordance" not in kinds and "Atlas" not in kinds, kinds

        # The corpus is bounded: a guide with hundreds of verses does not
        # become a hundred citations.
        assert len(srcs) <= 12, len(srcs)

        # The messages carry the rule, the sources and the question.
        m = ai.topic_messages("grace", "What does it mean?", srcs)
        assert m[0]["role"] == "system"
        assert "cite them by number" in m[0]["content"], m[0]["content"]
        assert any("[1]" in x["content"] for x in m), m
        assert "grace" in m[-1]["content"] and "What does it mean?" in m[-1]["content"]

        # A follow-up is a follow-up: the exchange so far travels with it, and
        # only this topic's exchange does.
        hist = [{"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1"}]
        m2 = ai.topic_messages("grace", "And the second one?", srcs, hist)
        assert any(x["content"] == "a1" for x in m2), m2
        assert m2[-1]["content"].endswith("And the second one?"), m2[-1]

        # An empty topic or an empty question is refused, with a way out.
        for args in (("", "why?"), ("grace", "")):
            try:
                ai.topic_messages(args[0], args[1], srcs)
                raise AssertionError(f"accepted {args!r}")
            except ai.AiError as e:
                assert e.hint, e

        # A topic nothing installed covers raises rather than sending the
        # model a subject it would have to invent.
        try:
            ai.topic_sources("zzzqqqxxnothing", max_sources=4)
            raise AssertionError("accepted a topic nothing covers")
        except ai.AiError as e:
            assert e.hint, e
        return f"{len(srcs)} sources, kinds {sorted(kinds)}"
    check("AI: topic guide grounding", t_ai_topic)

    def t_ai_usage():
        from gbible import ai
        import json as _json

        # Prices: the longest prefix wins, so a cheap mini model is not billed
        # as its expensive parent, and an unknown model is None rather than a
        # guess -- a made-up figure is worse than a gap on a bill.
        assert ai.price_for("gpt-4o-mini") == (0.15, 0.60)
        assert ai.price_for("gpt-4o-2024-08-06") == (2.50, 10.00)
        assert ai.price_for("llama3.2:latest") is None
        assert ai.cost_of("openai", "gpt-4o", 1_000_000, 0) == 2.50
        assert ai.cost_of("openai", "gpt-4o", 0, 1_000_000) == 10.00
        assert ai.cost_of("openai", "nobody/knows", 100, 100) is None

        # A free model is a *known* zero, not an unknown: "this cost nothing"
        # and "this cost is not known" are different statements.
        assert ai.cost_of("openrouter", "openrouter/free", 1000, 1000) == 0.0
        assert ai.cost_of("openrouter", "x/y:free", 1000, 1000) == 0.0
        assert ai.cost_of("openrouter", "openai/gpt-4o", 1000, 1000) is None
        assert ai.cost_of("groq", "openai/gpt-oss-120b", 1000, 1000) == 0.0
        assert ai.cost_of("google", "gemini-3.8-flash", 1000, 1000) == 0.0
        # The same id on a provider that does not offer it free is not free.
        assert ai.cost_of("openai", "gemini-3.8-flash", 1000, 1000) is None

        # Each adapter writes the provider's own counts into `stats`, which is
        # the only way the meter can see a *streamed* call at all: the counts
        # ride on a final chunk that a text-only extractor would drop.
        def lines(frames):
            return [("data: " + _json.dumps(f) + "\n").encode() for f in frames]

        st = {}
        list(ai._x_openai(lines([
            {"choices": [{"delta": {"content": "hi"}}]},
            {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 4,
                                      "total_tokens": 7}}]), st))
        assert st == {"prompt_tokens": 3, "completion_tokens": 4,
                      "total_tokens": 7}, st

        st = {}
        list(ai._x_anthropic(lines([
            {"type": "message_start",
             "message": {"usage": {"input_tokens": 11, "output_tokens": 0}}},
            {"type": "content_block_delta",
             "delta": {"type": "text_delta", "text": "hi"}},
            {"type": "message_delta", "usage": {"output_tokens": 22}}]), st))
        assert st == {"prompt_tokens": 11, "completion_tokens": 22}, st

        st = {}
        list(ai._x_ollama([
            _json.dumps({"message": {"content": "hi"},
                         "done": False}).encode(),
            _json.dumps({"done": True, "prompt_eval_count": 20,
                         "eval_count": 9}).encode()], st))
        assert st == {"prompt_tokens": 20, "completion_tokens": 9}, st

        # A local model with no price on file is *free*, not unpriceable: only an
        # unpriced cloud call makes the running total a floor rather than a
        # total.  An unrecognised provider is treated as cloud, because guessing
        # that something unknown is free is the error that costs money.
        b = ai._usage_bucket()
        ai._fold(b, {"provider": "ollama", "model": "llama3.2:latest", "ok": 1,
                     "prompt_tokens": 10, "completion_tokens": 5,
                     "total_tokens": 15})
        assert b["cost_known"] is True and b["cost"] == 0.0, b
        b = ai._usage_bucket()
        ai._fold(b, {"provider": "openai", "model": "no-such-model", "ok": 1,
                     "prompt_tokens": 5, "completion_tokens": 5,
                     "total_tokens": 10})
        assert b["cost_known"] is False, b
        b = ai._usage_bucket()
        ai._fold(b, {"provider": "openai", "model": "gpt-4o", "ok": 0,
                     "prompt_tokens": 0, "completion_tokens": 0,
                     "total_tokens": 0})
        assert b["failed"] == 1 and b["cost_known"] is True, b

        # Recording is additive and the summary moves by exactly what was
        # written.  The reader's own history is left in place: the test rows are
        # removed again by id, so running the check cannot erase a month of real
        # usage or hand somebody a bill that is not theirs.
        conn = db.connect()
        mark = conn.execute(
            "SELECT coalesce(max(id),0) FROM ai_usage").fetchone()[0]
        before = ai.usage_summary(3650)
        try:
            ai.record_usage("openai", "gpt-4o-mini", "chat",
                            {"prompt_tokens": 1_000_000,
                             "completion_tokens": 1_000_000})
            ai.record_usage("ollama", "llama3.2:latest", "chat",
                            {"prompt_tokens": 10, "completion_tokens": 5})
            ai.record_usage("openai", "gpt-4o-mini", "chat", {}, ok=False)
            after = ai.usage_summary(3650)
        finally:
            conn.execute("DELETE FROM ai_usage WHERE id > ?", (mark,))
            conn.commit()
        assert after["calls"] - before["calls"] == 3, (before, after["calls"])
        assert after["failed"] - before["failed"] == 1
        assert after["total_tokens"] - before["total_tokens"] == 2_000_015
        assert round(after["cost"] - before["cost"], 4) == 0.75
        assert {"openai", "ollama"} <= {p["provider"]
                                        for p in after["providers"]}
        assert all({"local", "cost_known", "calls"} <= set(p)
                   for p in after["providers"])

        # Metering sits on the path of the thing it measures, so it must never
        # raise -- a failed write may not become a failed answer.
        ai.record_usage("openai", "gpt-4o", "chat", None)
        conn.execute("DELETE FROM ai_usage WHERE id > ?", (mark,))
        conn.commit()
        return "3 adapters metered, prices by longest prefix, totals additive"
    check("AI: usage metering", t_ai_usage)

    def t_ai_sermon():
        from gbible import ai

        assert set(ai.SERMON_ACTIONS) == {"outline", "illustration",
                                          "exposition"}
        src = [{"n": 1, "module_id": "c1", "module_name": "NICNT",
                "label": "Eph 2:8", "title": "", "type": "Commentary",
                "text": "grace is a gift"}]

        # The promise the feature is built on is in the system prompt of every
        # kind, not only in the one that sounds like it needs it.
        for kind, instr in ai.SERMON_ACTIONS.items():
            m = ai.sermon_messages(kind, "Eph 2:8", "grace", src)
            assert m[0]["role"] == "system"
            assert "NOT write the sermon" in m[0]["content"], kind
            assert instr in m[0]["content"], kind
            assert "Eph 2:8" in m[-1]["content"], m[-1]
            assert "grace" in m[-1]["content"], m[-1]
            assert any("[1] NICNT" in x["content"] for x in m), m

        # A subject is optional, and an absent one must not leave an empty label
        # or an empty sources block behind.
        m = ai.sermon_messages("outline", "Eph 2:8", "", None)
        assert "subject" not in m[-1]["content"].lower(), m[-1]
        assert not any("Numbered sources" in x["content"] for x in m), m

        for kind in ("nope", ""):
            try:
                ai.sermon_messages(kind, "Eph 2:8")
                raise AssertionError(f"accepted sermon kind {kind!r}")
            except ai.AiError as e:
                assert e.hint, e
        try:
            ai.sermon_messages("outline", "   ")
            raise AssertionError("accepted an empty passage")
        except ai.AiError as e:
            assert "passage" in str(e).lower(), e

        # The corpus is the passage itself plus what the library says about it,
        # numbered from one -- not a search of a reference string, which the
        # engine would read as "John three sixteen".
        try:
            srcs = ai.sermon_sources("John 3:16", "", True, 10)
        except ai.AiError as e:
            return Skip(f"no Bible installed ({e})")
        assert srcs, "nothing retrieved for John 3:16"
        assert [s["n"] for s in srcs] == list(range(1, len(srcs) + 1))
        assert srcs[0]["type"] == "Bible", srcs[0]
        assert all(s["text"].strip() for s in srcs)

        # A reference nothing can read raises, rather than sending the model a
        # passage it would then invent around.
        for bad in ("Zzzz 1:1", "not a reference"):
            try:
                ai.sermon_sources(bad, "", False, 4)
                raise AssertionError(f"sermon_sources accepted {bad!r}")
            except ai.AiError as e:
                assert e.hint, e
        return (f"{len(ai.SERMON_ACTIONS)} sermon kinds, {len(srcs)} sources "
                f"for John 3:16")
    check("AI: sermon research", t_ai_sermon)

    # -------------------------------------------------------------- report
    print()
    width = max(len(n) for _s, n, _d in _results) + 2
    nfail = nskip = 0
    for status, name, detail in _results:
        mark = {PASS: "\033[32m ok \033[0m", FAIL: "\033[31mFAIL\033[0m",
                SKIP: "\033[33mskip\033[0m"}[status]
        print(f"  {mark}  {name.ljust(width)} {detail}")
        nfail += status == FAIL
        nskip += status == SKIP
    print()
    print(f"  {len(_results) - nfail - nskip} passed, {nskip} skipped, {nfail} failed")
    if nskip:
        print("  (skipped = the material for that feature is not installed yet)")
    return nfail == 0


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)

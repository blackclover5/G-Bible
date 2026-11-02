"""A positional index: word -> unit -> where in that unit.

Why this exists.  Everything else in the search stack was made fast, and one
query stayed slow: `lord NEAR faith` took a minute.  The reason is structural
rather than a missing optimisation.  Answering a proximity query needs to know
how close two words are, and the only place that knowledge lived was the unit's
text -- so the engine fetched every candidate containing both words and walked
each one in Python, re-tokenising with a regular expression.  Three and a half
thousand candidates, fifty-odd million characters, one minute.

Fetching the positions from an index instead of recovering them from the text
turns that into arithmetic on two short lists.

**What "second order" means here.**  A first-order index answers "which units
contain *faith*".  This also answers "and where in each of them", which is what
makes second-order questions possible: two words adjacent (a phrase), two words
within a distance (proximity), and the intersection of two postings without
touching the unit table at all.  The phrase case is what a bigram index is for;
bigrams are deliberately not stored separately, because a phrase is a position
range and positions answer it exactly, where a bigram index can only answer it
for pairs of *known* adjacent words and would still need positions for the gaps.
SQLite's own FTS5 also holds positions, but not exposed as rows a caller can
intersect.

**The cost, stated up front.**  Roughly 27 million (unit, term) pairs over 1.2
million units.  Stored as a WITHOUT ROWID table keyed on (term_id, uid) with the
positions as varint deltas, that is a few hundred megabytes — a real addition to
a database that is already 2.8 GB — and about a minute and a half to build.  So
it is built by a tool rather than at install time, it is optional, and search
works without it: every lookup returns nothing when the index is absent and the
caller falls back.  Nothing here is required for the app to function.

**Positions are capped, and the cap is honest.**  A unit of 6,000 characters can
contain a term 300 times; only the first 512 occurrences are stored.  Term
frequency is stored separately and exactly, so BM25 -- which saturates well
before 300 -- is unaffected.  Proximity uses the stored positions, so for a unit
with more than 512 occurrences of a word the nearest pair found is the nearest
among those 512.  That is recorded in `build()`'s report rather than passed off
as exact.
"""

from __future__ import annotations

import json
import sqlite3
import re
import threading
import time
from bisect import bisect_left

from . import db

#: Occurrences of one term in one unit whose positions are kept.
MAX_POS = 512

#: Rows per insert batch.
BATCH = 20000

#: `part` values.  A unit's title is a searchable field in its own right, and
#: FTS indexes it, so the index does too -- but as a separate region.  A word in
#: a heading and a word in the body are not adjacent to each other, and merging
#: the two position lists would invent adjacencies that do not exist.
PART_BODY = 0
PART_TITLE = 1


# --------------------------------------------------------------- varints ---

def _put_varint(out: bytearray, n: int) -> None:
    if n < 0:
        # Refused rather than encoded.  A right shift on a negative int in Python
        # is arithmetic, so `n >>= 7` leaves -1 in place forever and the loop
        # below never ends: it appends 0xFF until the machine has no memory left.
        # It was reached by delta-coding word *lengths*, which unlike positions
        # do not increase -- "the 3 long 5 thin" ends lower than it started -- and
        # the build it stopped was a 5.4 GB process spinning at 100% CPU with
        # nothing written and nothing in the log to say why.
        raise ValueError(f"varint must not be negative, got {n}")
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


def _get_varints(buf: bytes) -> list[int]:
    """Decode a run of varints, treating the first as an absolute position."""
    out, val, shift = [], 0, 0
    for byte in buf:
        val |= (byte & 0x7F) << shift
        if byte & 0x80:
            shift += 7
        else:
            out.append(val)
            val, shift = 0, 0
    return out


def _pack(positions: list[int]) -> bytes:
    out = bytearray()
    prev = -1
    for p in positions[:MAX_POS]:
        _put_varint(out, p - prev - 1)
        prev = p
    return bytes(out)


def _unpack(buf: bytes) -> list[int]:
    out, pos = [], -1
    for delta in _get_varints(buf):
        pos += delta + 1
        out.append(pos)
    return out


def _pack_lengths(lengths: list[int]) -> bytes:
    """Pack word lengths, one absolute varint each.

    Not delta-coded, unlike `_pack`.  A position list only ever goes forwards, so
    a delta is always positive and the encoding shrinks; lengths do not, and a
    negative delta is not encodable at all (see `_put_varint`).  An absolute
    varint costs one byte for anything under 128 characters, which is every word
    in every language this library holds, so the saving would have been small and
    the correctness cost was a build that never returned.
    """
    out = bytearray()
    for n in lengths[:MAX_POS]:
        _put_varint(out, n if n > 0 else 0)
    return bytes(out)


def _unpack_lengths(buf: bytes) -> list[int]:
    """Decode `_pack_lengths`: the same varints, read as absolute values."""
    return _get_varints(buf) if buf else [0]


# --------------------------------------------------------------- schema ----

def ensure(conn) -> None:
    """Create the index tables if they do not exist.

    A `stem` column was added to `pos_term` after some databases were built, and
    `CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists --
    so the column is absent and the index on it cannot be created.  It is added
    here instead of by a rebuild, because the million-row term dictionary is
    cheap to migrate and the thirty-six million postings are not.

    The tables are created *first*.  The index on `stem` came before them, and
    creating an index on a table that does not exist raises -- and `ensure` is
    the first thing the indexer does, so on a fresh database it raised before
    anything was built.  The background indexer caught the exception and
    carried on, and the app used the text path for ever after without saying
    so: a fresh install never had a positional index at all.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pos_term (
            id    INTEGER PRIMARY KEY,
            form  TEXT NOT NULL UNIQUE,
            stem  TEXT
        );
        CREATE TABLE IF NOT EXISTS pos_meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        -- Per-module coverage.  `covered_units` in pos_meta is a single running
        -- total, which is enough to answer "is this stale?" but not "what is
        -- missing?"  An indexer needs a work queue, so each module records how
        -- many units it contributed.  A module whose count no longer matches is
        -- out of date whether it gained a unit or lost one, which a running
        -- total cannot tell apart.
        CREATE TABLE IF NOT EXISTS pos_module (
            module_id TEXT PRIMARY KEY,
            units     INTEGER NOT NULL DEFAULT 0,
            built_at  TEXT
        );
        """)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(pos_term)")}
    if cols and "stem" not in cols:
        try:
            conn.execute("ALTER TABLE pos_term ADD COLUMN stem TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    conn.execute("CREATE INDEX IF NOT EXISTS ix_pos_term_stem ON pos_term(stem)")


def ensure_ends(conn) -> bool:
    """Create the word-length table, and report whether it has been filled.

    A separate table from `pos` because `pos` is WITHOUT ROWID: adding a column
    means dropping and rewriting thirty-seven million rows, which takes the whole
    index offline, and the one thing worse than a slow character-gap query is a
    search that cannot be answered at all.

    The table existing is not the same as the table being usable, so the answer
    is the second: a half-written length table would let a `WITHIN n CHARS`
    answer silently skip every unit it had not reached, and the gap between a
    word's end and the next word's start is exactly the kind of number that looks
    fine and is not.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pos_end (
            term_id INTEGER NOT NULL,
            uid     INTEGER NOT NULL,
            part    INTEGER NOT NULL DEFAULT 0,
            elen    BLOB,
            PRIMARY KEY (term_id, uid, part)
        ) WITHOUT ROWID;
        """)
    return ends_available(conn)


def ends_available(conn=None) -> bool:
    """Whether every indexed module also has its word lengths.

    Two facts, both cheap, in the order that matters: the table must exist and
    must have been written to completion -- a marker row in `pos_meta`, recorded
    in the same transaction as the last module -- and every installed module must
    appear in that marker's list.

    The module list comes from `module`, not from `pos_unit`.  Asking
    `pos_unit` is the obvious way to word it and it costs 81 ms -- a distinct
    scan over 1.2 million rows -- on a function that every `WITHIN n CHARS` query
    calls before it does anything else.  The question is the same one, though:
    `available()` has already established that the installed modules are exactly
    the indexed ones, so a module that is installed and indexed is a module whose
    lengths have to be there.
    """
    conn = conn or db.connect()
    try:
        if not _meta_get(conn, "ends_built"):
            return False
        row = conn.execute(
            "SELECT value FROM pos_meta WHERE key='ends_modules_done'").fetchone()
        done = set(json.loads(row["value"])) if row and row["value"] else set()
        want = {r["id"] for r in conn.execute(
            "SELECT id FROM module WHERE installed_at>0")}
        return bool(want) and want <= done
    except Exception:
        return False


def pending_modules(conn=None, *, repair: bool = True) -> list[dict]:
    """Installed modules whose postings are missing or out of date.

    This is the indexer's work queue, and the reason indexing can be incremental:
    the answer names the modules to do rather than merely reporting that
    something is wrong.

    `modules_done` says *which* modules were indexed; `pos_module` says *how many
    units* each one contributed, which is what catches a module that was edited
    after the fact.  An index built before `pos_module` existed has the first and
    not the second, so a module with no count row is recorded from what is
    already there rather than reported as work to redo -- otherwise every
    existing database would present its whole library as unindexed and the
    indexer would helpfully rebuild all of it.

    Precise, and therefore not free: it groups over the unit table.  So it must
    not run on a search.  `available()` stays a cheap count comparison for the hot
    path; this is for the background worker and for status.
    """
    # `db.connect()` hands back a thread-local connection that the rest of the
    # application is holding too, so it is deliberately not closed here.  Closing
    # it leaves `_local.conn` pointing at a dead handle, which the next
    # `db.connect()` returns as though it were live -- so every later query in
    # this thread raises "Cannot operate on a closed database".
    conn = conn if conn is not None else db.connect()
    if True:
        ensure(conn)
        try:
            row = conn.execute(
                "SELECT value FROM pos_meta WHERE key='modules_done'").fetchone()
            done = set(json.loads(row["value"])) if row and row["value"] else set()
        except (json.JSONDecodeError, TypeError):
            done = set()
        counts = {r["module_id"]: r["units"] for r in conn.execute(
            "SELECT module_id, units FROM pos_module")}
        cur = {r["module_id"]: r["n"] for r in conn.execute(
            "SELECT module_id, COUNT(*) AS n FROM unit "
            "WHERE module_id IN (SELECT id FROM module WHERE installed_at>0) "
            "GROUP BY module_id")}

        healed = []
        out = []
        # `modules_done` records that a module was indexed once.  Trusting that
        # blindly was how a book went missing: uninstalling deleted the units
        # without telling the index, so a reinstall looked already-indexed while
        # its postings had gone with the old unit ids.  `forget()` is what stops
        # that now, and it is called from the removal path.
        #
        # Proving the claim instead -- checking each module really has postings --
        # would mean joining `pos` on uid, and `pos` is keyed on (term_id, uid,
        # part) with no index on uid, so that scan reads all thirty-six million
        # rows.  It cost a two-minute hang when it was tried here.  So the cheap
        # path trusts the bookkeeping that is now maintained, and
        # `audit()` -- run explicitly by `tools/build_pos_index.py --verify` --
        # is where the expensive proof belongs.
        # Installed modules that the index claims to cover but has no count for:
        # a database built before per-module coverage existed.
        to_heal = [mid for mid, n in sorted(cur.items())
                   if mid in done and counts.get(mid) is None]

        # Healing is a one-time migration, recorded so it never runs again.
        # Re-running it on every call would be worse than not having it: it would
        # restore a coverage row the moment anyone deleted one to see what happens,
        # so a genuinely broken index would quietly declare itself whole again --
        # which is the failure this whole mechanism exists to prevent.  After the
        # first pass, `forget()` is what keeps this honest.
        marker = conn.execute(
            "SELECT value FROM pos_meta WHERE key='coverage_healed'").fetchone()
        migrated = bool(marker and marker["value"])
        # `to_heal` is computed above; the migration closes either way, so a
        # database that needed no healing is not left permanently eligible to
        # heal -- which would let the next deleted coverage row be papered over.
        may_heal = repair and not migrated and bool(to_heal)
        for mid, n in sorted(cur.items()):
            if mid not in done:
                out.append({"module_id": mid, "units": n, "state": "new"})
                continue
            have = counts.get(mid)
            if have is None:
                if may_heal:
                    # Indexed, but before per-module counts existed.  Record what
                    # it covers, once, and from then on trust `forget()`.
                    #
                    # Column order is (module_id, units, built_at); passing these
                    # the other way round writes unit counts into module_id,
                    # which is the primary key -- so 273 modules collapse into
                    # however many *distinct counts* there are, and the queue
                    # looks empty forever after.
                    healed.append((mid, n, time.strftime("%Y-%m-%dT%H:%M:%S")))
                else:
                    # The migration has closed, so a missing coverage row is a
                    # real discrepancy and not a legacy one.  Reporting it is the
                    # point: silently ignoring it is how an index loses a module
                    # without anybody noticing.
                    out.append({"module_id": mid, "units": n,
                                "state": "unrecorded",
                                "note": "listed as indexed but has no coverage "
                                        "row; rebuild it"})
                continue
            if have != n:
                out.append({"module_id": mid, "units": n, "state": "changed",
                            "indexed_units": have})
        if (healed or not to_heal) and not migrated:
            # Record the migration as finished whether or not it had work to do.
            conn.execute("INSERT OR REPLACE INTO pos_meta(key,value) "
                         "VALUES('coverage_healed',?)",
                         (time.strftime("%Y-%m-%dT%H:%M:%S"),))
        if healed:
            conn.executemany(
                "INSERT OR REPLACE INTO pos_module(module_id,units,built_at) "
                "VALUES(?,?,?)", healed)
            conn.commit()
        return out


def _unit_uids(conn) -> dict:
    """A dense integer id per unit, so index rows carry 4 bytes not two strings.

    `unit` is keyed on (module_id, key), so its rowid is an implicit one that
    VACUUM is free to renumber -- and an index built against those rowids would
    quietly point at the wrong units after a vacuum, which is the same class of
    bug as the rowid join this project had in the FTS path.  So units get an
    explicit, stable, dense id in `pos_unit`, and the join is on that.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pos_unit (
            uid       INTEGER PRIMARY KEY,
            module_id TEXT NOT NULL,
            key       TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ix_pos_unit
            ON pos_unit(module_id, key);
        """)
    n = conn.execute("SELECT COUNT(*) c FROM pos_unit").fetchone()["c"]
    total = conn.execute("SELECT COUNT(*) c FROM unit").fetchone()["c"]
    if n != total:
        # Rebuilt from scratch on any mismatch: a half-populated map is worse
        # than none, because it would silently miss units.
        conn.execute("DELETE FROM pos_unit")
        conn.execute(
            "INSERT INTO pos_unit(uid, module_id, key) "
            "SELECT rowid, module_id, key FROM unit "
            "WHERE rowid NOT IN (SELECT uid FROM pos_unit)")
        conn.commit()
    return n



def _region_terms(region: str) -> dict[str, tuple[list[int], list[int], list[int]]]:
    """term -> (token indices, char starts, char lengths) in one region.

    Positions are capped at MAX_POS; the caller stores the true frequency
    separately so that only the positions are ever approximate.

    The lengths are the third list because `WITHIN n CHARS` measures the gap
    *between* two words -- from the end of the left one to the start of the right
    one -- and a gap cannot be recovered from two start offsets.  Without them
    the operator has to be answered by reading text, which is the whole reason
    this index exists.
    """
    occ: dict[str, tuple[list[int], list[int], list[int]]] = {}
    if not region:
        return occ
    # Tokenised by `db.words`, the same function the engine uses, and that is not
    # a detail -- it is the whole contract.
    #
    # A regex of `[^\W\d_]+` was used here, and it disagrees with the engine in
    # two ways that both move the numbers.  It drops numerals, so in "Jesus loves
    # the 12 elders" the engine calls *elders* token 4 and this called it token 3;
    # and it splits on an apostrophe, so "king's own" was *king* 1, *s* 2, *own* 3
    # where the engine says *own* 2.  `WITHIN n WORDS` counts token indices, so a
    # single numeral anywhere earlier in the unit silently shifted every distance
    # after it -- `Jesus WITHIN 5 WORDS love` came back with 24 units where the
    # engine had 229.
    #
    # Sharing the function removes the possibility of the two drifting apart
    # again, which a hand-rolled pattern cannot promise.
    for i, (word, cs, ce) in enumerate(db.words(region)):
        w = db.fold(word)
        if not w:
            continue
        got = occ.get(w)
        if got is None:
            occ[w] = ([i], [cs], [ce - cs])
        elif len(got[0]) < MAX_POS:
            got[0].append(i)
            got[1].append(cs)
            got[2].append(ce - cs)
    return occ


# ------------------------------------------------------------- building ----

def _module_rows(conn, mid: str, term_ids: dict[str, int]):
    """Yield the insertable rows of one module, reading its text once.

    Each row is `(term_id, uid, part, tf, pos, cpos, elen, stored)`: the token
    indices, the character starts, the character lengths, and how many positions
    actually survived the cap.  `tf` is non-zero only for a word the cap caught,
    which is how a reader knows the stored positions are a subset.

    Both `build()` and `build_ends()` take their rows from here.  That is not
    tidiness: a start offset written to `pos` by one pass and a length written
    to `pos_end` by another, from tokenisations that had drifted apart, would
    measure the gap between two different words and answer confidently.
    """
    seen_terms: set[str] = set()
    cur = conn.execute(
        # uid lives on pos_unit, not on unit.
        "SELECT pu.uid AS uid, u.text AS text, u.title AS title "
        "FROM pos_unit pu "
        "JOIN unit u ON u.module_id = pu.module_id AND u.key = pu.key "
        "WHERE pu.module_id = ?", (mid,))
    for r in cur:
        for part, region in ((PART_BODY, r["text"] or ""),
                             (PART_TITLE, r["title"] or "")):
            for w, (ps, cs, cl) in _region_terms(region).items():
                tid = term_ids.get(w)
                if tid is None:
                    if w not in seen_terms:
                        row = conn.execute(
                            "SELECT id FROM pos_term WHERE form=?",
                            (w,)).fetchone()
                        if row:
                            tid = row["id"]
                        else:
                            try:
                                conn.execute(
                                    "INSERT INTO pos_term(form) VALUES(?)",
                                    (w,))
                                tid = conn.execute(
                                    "SELECT id FROM pos_term WHERE form=?",
                                    (w,)).fetchone()["id"]
                            except Exception:
                                continue
                        term_ids[w] = tid
                        seen_terms.add(w)
                tf = len(ps) or 1
                yield (tid, r["uid"], part, tf if tf > MAX_POS else 0,
                       _pack(ps), _pack(cs), _pack_lengths(cl),
                       min(tf, MAX_POS))
    cur.close()

def build(modules: list[str] | None = None, *, verbose: bool = False,
          rebuild: bool = False, ends: bool = True) -> dict:
    """Build the positional index.  Safe to interrupt and re-run."""
    conn = db.connect()
    ensure(conn)
    _unit_uids(conn)
    t0 = time.time()

    # `cpos` holds character offsets as well as `pos` holding token indices,
    # because this app's NEAR means 48 *characters* while WITHIN n WORDS means n
    # *tokens*, and the two cannot be converted into one another -- a token can be
    # one character or twenty.  Answering NEAR from token positions would mean
    # guessing a conversion, and a guessed bound either loses hits or keeps almost
    # everything, which is no filter at all.
    have = conn.execute(
        "SELECT COUNT(*) c FROM sqlite_master WHERE type='table' "
        "AND name='pos'").fetchone()["c"]
    cols = []
    if have:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(pos)")]
    if rebuild or not have or "cpos" not in cols or "part" not in cols:
        # WITHOUT ROWID tables cannot add a column, so the table is rebuilt.
        # pos_term is kept: a million-term dictionary does not need re-reading
        # out of 1.2 million unit texts to exist again.
        conn.execute("DROP TABLE IF EXISTS pos")
        conn.executescript(
            """
            CREATE TABLE pos (
                term_id INTEGER NOT NULL,
                uid     INTEGER NOT NULL,
                part    INTEGER NOT NULL DEFAULT 0,
                tf      INTEGER NOT NULL DEFAULT 0,
                pos     BLOB,
                cpos    BLOB,
                PRIMARY KEY (term_id, uid, part)
            ) WITHOUT ROWID;
            """)
    else:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pos (
                term_id INTEGER NOT NULL,
                uid     INTEGER NOT NULL,
                part    INTEGER NOT NULL DEFAULT 0,
                tf      INTEGER NOT NULL DEFAULT 0,
                pos     BLOB,
                cpos    BLOB,
                PRIMARY KEY (term_id, uid, part)
            ) WITHOUT ROWID;
            """)
    done: set[str] = set()
    edone: set[str] = set()
    if rebuild:
        # A rebuild starts the resume list over as well, or it would skip every
        # module as "already done" against a table it has just emptied.
        conn.execute("DELETE FROM pos_meta WHERE key IN "
                     "('modules_done','built','covered_units')")
        # Per-module coverage describes rows that have just been dropped, so it
        # goes with them.  Left behind, every module would look current and the
        # indexer would be handed an empty queue on an emptied table.
        conn.execute("DELETE FROM pos_module")
        # The lengths are keyed the same way as the postings and describe the
        # same occurrences, so they go with them: rows left behind by a rebuild
        # would belong to units that no longer exist.
        conn.execute("DROP TABLE IF EXISTS pos_end")
        conn.execute("DELETE FROM pos_meta WHERE key IN "
                     "('ends_built','ends_modules_done')")
        conn.commit()

    if modules is None:
        mods = [r["id"] for r in conn.execute(
            "SELECT module_id AS id FROM pos_unit GROUP BY module_id")]
    else:
        mods = list(modules)

    # Resume.  A full build writes tens of millions of rows and takes a quarter
    # of an hour.  A machine that restarted mid-way used to throw all of that
    # away, because the only way to build was to empty the table first -- so the
    # one interruption cost the whole thirteen minutes and then some.  Modules
    # already finished are recorded as they commit, so an interrupted build
    # picks up where it stopped.
    if not rebuild:
        row = conn.execute(
            "SELECT value FROM pos_meta WHERE key='modules_done'").fetchone()
        if row and row["value"]:
            try:
                done = set(json.loads(row["value"]))
            except (json.JSONDecodeError, TypeError):
                done = set()
        # The length table keeps its own completion list, and it has to be read
        # before the loop as well.  It was not, at first, and an *incremental*
        # build -- one module, which is what the background indexer runs after an
        # install -- finished by writing a list holding only that module.  Every
        # length in the library was still there and accounted for, and the
        # character-gap operators had declined themselves for good.
        row = conn.execute(
            "SELECT value FROM pos_meta WHERE key='ends_modules_done'").fetchone()
        if row and row["value"]:
            try:
                edone = set(json.loads(row["value"]))
            except (json.JSONDecodeError, TypeError):
                edone = set()
        remaining = [m for m in mods if m not in done]
        if len(remaining) != len(mods):
            if verbose:
                print(f"  resuming: {len(mods) - len(remaining)} module(s) "
                      f"already indexed, {len(remaining)} to go", flush=True)
        mods = remaining

    term_ids: dict[str, int] = {}
    rows_written = 0
    pos_stored = 0
    capped = 0
    units_done = 0
    if ends:
        ensure_ends(conn)
    end_rows = 0

    for mid in mods:
        mod_units = conn.execute(
            "SELECT COUNT(*) c FROM pos_unit WHERE module_id=?",
            (mid,)).fetchone()["c"]
        buf: list[tuple] = []
        ebuf: list[tuple] = []
        for row in _module_rows(conn, mid, term_ids):
            stored = row[7]
            if row[3]:
                capped += 1
            pos_stored += stored
            buf.append(row[:6])
            if ends:
                ebuf.append((row[0], row[1], row[2], row[6]))
            if len(buf) >= BATCH:
                conn.executemany(
                    "INSERT OR REPLACE INTO pos"
                    "(term_id,uid,part,tf,pos,cpos) "
                    "VALUES(?,?,?,?,?,?)", buf)
                rows_written += len(buf)
                if ends:
                    conn.executemany(
                        "INSERT OR REPLACE INTO pos_end"
                        "(term_id,uid,part,elen) VALUES(?,?,?,?)", ebuf)
                    end_rows += len(ebuf)
                buf = []
                ebuf = []
                if rows_written % (BATCH * 20) == 0:
                    conn.commit()
                    db.maybe_checkpoint(conn)
        units_done += mod_units
        if buf:
            conn.executemany(
                "INSERT OR REPLACE INTO pos(term_id,uid,part,tf,pos,cpos) "
                "VALUES(?,?,?,?,?,?)", buf)
            rows_written += len(buf)
        if ends and ebuf:
            conn.executemany(
                "INSERT OR REPLACE INTO pos_end(term_id,uid,part,elen) "
                "VALUES(?,?,?,?)", ebuf)
            end_rows += len(ebuf)
        conn.commit()
        # Fold the log back into the database as the build goes.
        #
        # Inserting tens of millions of rows in one transaction leaves a
        # write-ahead log the same size as everything written -- 767 MB after the
        # first full build -- and until something else checkpoints, every read
        # has to consult that log before the main file.  The project's own
        # self-test checks the WAL stays small, and rightly failed.
        db.maybe_checkpoint(conn, truncate=True)
        done.add(mid)
        conn.execute("INSERT OR REPLACE INTO pos_meta(key,value) "
                     "VALUES('modules_done',?)", (json.dumps(sorted(done)),))
        # Recorded in the same transaction as the postings it describes, so the
        # queue can never list a module as done whose rows were rolled back.
        conn.execute(
            "INSERT OR REPLACE INTO pos_module(module_id,units,built_at) "
            "VALUES(?,?,?)",
            (mid, mod_units, time.strftime("%Y-%m-%dT%H:%M:%S")))
        if ends:
            edone.add(mid)
            conn.execute(
                "INSERT OR REPLACE INTO pos_meta(key,value) VALUES(?,?)",
                ("ends_modules_done", json.dumps(sorted(edone))))
        conn.commit()
        if verbose:
            print(f"  {mid:<34} {rows_written:>10,} rows so far", flush=True)

    # The stem column is what lets a proximity query find inflected forms, and it
    # is filled here rather than lazily so that a fresh build is complete the
    # moment it finishes.
    ensure_stems()
    covered = conn.execute("SELECT COUNT(*) c FROM unit").fetchone()["c"]
    conn.execute("INSERT OR REPLACE INTO pos_meta(key,value) VALUES('built',?)",
                 (str(int(time.time())),))
    conn.execute("INSERT OR REPLACE INTO pos_meta(key,value) "
                 "VALUES('covered_units',?)", (str(covered),))
    conn.execute("INSERT OR REPLACE INTO pos_meta(key,value) "
                 "VALUES('tokenizer',?)", (TOKENIZER,))
    if ends:
        _meta_set(conn, "ends_built", int(time.time()))
    conn.execute("DELETE FROM pos_meta WHERE key='retired'")
    conn.commit()
    terms = conn.execute("SELECT COUNT(*) c FROM pos_term").fetchone()["c"]
    return {"ok": True, "modules": len(mods), "units": units_done,
            "rows": rows_written, "terms": terms,
            "positions": pos_stored,
            "lengths": end_rows if ends else 0,
            "capped": capped,
            "seconds": round(time.time() - t0, 1),
            "note": (f"{capped} (unit,term) pairs had more than {MAX_POS} "
                     "occurrences; their term frequency is exact and only "
                     "the stored positions are capped") if capped else ""}


def build_ends(modules: list[str] | None = None, *, verbose: bool = False,
               rebuild: bool = False) -> dict:
    """Fill in the word-length table, without touching the postings.

    `WITHIN n CHARS` measures the gap between two words, so it needs to know
    where a word *ends* and not only where it starts; without that it has to
    read the unit's text, which is the minute-long path this index exists to
    replace.  The lengths are kept in their own table rather than as another
    column of `pos`, because `pos` is a WITHOUT ROWID table -- adding a column
    means dropping and rewriting thirty-seven million rows, which takes the
    whole index offline for a quarter of an hour.  A second table costs disk and
    nothing else: it is filled in the same pass, resumably, and the app carries
    on using the index for every other operator while it is being written.

    Until it is complete the character-gap operators decline and take the exact
    path, which is slow and correct.
    """
    conn = db.connect()
    ensure(conn)
    ensure_ends(conn)
    _unit_uids(conn)
    t0 = time.time()

    if modules is None:
        mods = [r["id"] for r in conn.execute(
            "SELECT module_id AS id FROM pos_unit GROUP BY module_id")]
    else:
        mods = list(modules)

    edone: set[str] = set()
    if rebuild:
        conn.execute("DROP TABLE IF EXISTS pos_end")
        conn.commit()
        ensure_ends(conn)
    else:
        row = conn.execute(
            "SELECT value FROM pos_meta WHERE key='ends_modules_done'"
        ).fetchone()
        if row and row["value"]:
            try:
                edone = set(json.loads(row["value"]))
            except (json.JSONDecodeError, TypeError):
                edone = set()
        remaining = [m for m in mods if m not in edone]
        if verbose and len(remaining) != len(mods):
            print(f"  resuming: {len(mods) - len(remaining)} module(s) "
                  f"already have lengths, {len(remaining)} to go", flush=True)
        mods = remaining

    term_ids: dict[str, int] = {}
    rows_written = 0
    units_done = 0
    for mid in mods:
        mod_units = conn.execute(
            "SELECT COUNT(*) c FROM pos_unit WHERE module_id=?",
            (mid,)).fetchone()["c"]
        buf: list[tuple] = []
        for row in _module_rows(conn, mid, term_ids):
            buf.append((row[0], row[1], row[2], row[6]))
            if len(buf) >= BATCH:
                conn.executemany(
                    "INSERT OR REPLACE INTO pos_end(term_id,uid,part,elen) "
                    "VALUES(?,?,?,?)", buf)
                rows_written += len(buf)
                buf = []
                if rows_written % (BATCH * 20) == 0:
                    conn.commit()
                    db.maybe_checkpoint(conn)
        units_done += mod_units
        if buf:
            conn.executemany(
                "INSERT OR REPLACE INTO pos_end(term_id,uid,part,elen) "
                "VALUES(?,?,?,?)", buf)
            rows_written += len(buf)
        conn.commit()
        db.maybe_checkpoint(conn, truncate=True)
        edone.add(mid)
        conn.execute("INSERT OR REPLACE INTO pos_meta(key,value) "
                     "VALUES('ends_modules_done',?)",
                     (json.dumps(sorted(edone)),))
        conn.commit()
        if verbose:
            print(f"  {mid:<34} {rows_written:>10,} lengths so far",
                  flush=True)
    _meta_set(conn, "ends_built", int(time.time()))
    conn.commit()
    return {"ok": True, "modules": len(mods), "units": units_done,
            "rows": rows_written, "seconds": round(time.time() - t0, 1),
            "note": "character-gap operators can now be answered from the index"}


# -------------------------------------------------------------- querying ---

def _fingerprint() -> str:
    """A hash of the tokeniser the postings were built with.

    The postings store word ordinals, so they are only meaningful for the
    tokeniser that produced them.  Changing how text is split into words
    invalidates every one of them, and the failure is silent and total: an
    index built with a tokeniser that split pointed Hebrew into single letters
    knows the word `ב` and has never heard of `ברא`, so a search for it returns
    an empty, confident answer.

    Coverage checks cannot catch that -- the index covers every unit there is.
    Only the tokeniser's own identity can, so it is recorded and compared.
    """
    import hashlib
    return hashlib.sha256(
        (db._TOKEN_RE.pattern + "|" + db._TOKEN_RE.flags.__str__())
        .encode("utf-8")).hexdigest()[:16]


TOKENIZER = _fingerprint()


def _retire(conn, why: str) -> None:
    """Stand the index down so the next run rebuilds it, and say why.

    The postings are dropped rather than merely marked unusable.  Marking them
    would leave `build()` -- which rebuilds the table only when it is missing or
    a column is absent -- free to reuse it, and the result would be new postings
    laid over old ones: a tokeniser that used to split pointed Hebrew into the
    letters `ב`, `ר`, `א` would leave those three terms resolvable by stem
    alongside the correct `ברא`, answering confidently from both.  Dropping the
    table makes `build()` take its rebuild path by itself, which is the same
    signal "no index at all" gives it.
    """
    conn.execute("INSERT OR REPLACE INTO pos_meta(key,value) "
                 "VALUES('retired',?)", (why,))
    conn.execute("INSERT OR REPLACE INTO pos_meta(key,value) "
                 "VALUES('retired_at',?)", (str(int(time.time())),))
    conn.execute("DELETE FROM pos_meta WHERE key IN "
                 "('modules_done', 'built', 'covered_units', 'stemmer_fp', "
                 "'ends_built', 'ends_modules_done')")
    conn.execute("DELETE FROM pos_module")
    try:
        conn.execute("DROP TABLE IF EXISTS pos")
        conn.execute("DROP TABLE IF EXISTS pos_end")
    except sqlite3.OperationalError:
        pass
    conn.commit()


def available() -> bool:
    """Whether the index can be trusted to answer.

    Not merely whether it exists.  A stale index is worse than none: a term the
    index knows from other units would be looked up, and the units added since
    the build would simply be missing from the answer.  The query returns a
    confident, slightly short list, and nothing anywhere says a hit was dropped --
    which is the whole class of bug this index has to avoid being.

    So coverage is checked against the unit table, and any shortfall retires the
    index until it is rebuilt.  Search then takes the text path, which is slow and
    correct.
    """
    conn = db.connect()
    try:
        seen = conn.execute(
            "SELECT value FROM pos_meta WHERE key='tokenizer'").fetchone()
        if not seen or seen["value"] != TOKENIZER:
            # The postings were built by a different tokeniser.  Retire the
            # index outright rather than let it answer: a stale index here is
            # not a slightly short list, it is an empty one that looks
            # authoritative.
            _retire(conn, "the word tokeniser changed since the index was built")
            return False
        built = conn.execute(
            "SELECT value FROM pos_meta WHERE key='built'").fetchone()
        if not built or not built["value"]:
            return False
        # Two independent facts, both cheap, rather than one running total.
        #
        # The total was not enough.  Uninstalling a book left `covered_units`
        # *higher* than the unit count, and `have <= want` read that as complete --
        # so an index that had lost a whole module reported itself ready, and
        # searches used it.  A total cannot tell "covers more than exists" from
        # "covers everything"; counting the modules can.
        agg = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(units),0) s FROM pos_module "
            "WHERE module_id IN (SELECT id FROM module WHERE installed_at>0)"
        ).fetchone()
        want_mods = conn.execute(
            "SELECT COUNT(*) c FROM module WHERE installed_at>0").fetchone()["c"]
        if not agg["n"]:
            return False                      # never built per-module coverage
        if agg["n"] != want_mods:
            return False                      # a module is missing entirely
        have = conn.execute("SELECT COUNT(*) c FROM unit").fetchone()["c"]
        return agg["s"] == have
    except Exception:
        return False


def staleness() -> dict:
    """Why the index cannot be used, if it cannot -- and what would fix it.

    Reports the same per-module truth `available()` decides on, so the message a
    person reads and the decision the engine makes cannot disagree.  The old
    running total is still reported, but only as context: it is what made a
    missing module look complete, so it is not the thing being believed.
    """
    conn = db.connect()
    out = {"built": False, "complete": False, "units": 0, "covered": 0,
           "uncovered": 0, "reason": "", "pending": []}
    try:
        ensure(conn)
        b = conn.execute(
            "SELECT value FROM pos_meta WHERE key='built'").fetchone()
        if not b or not b["value"]:
            out["reason"] = "never built"
            return out
        out["built"] = True
        out["units"] = conn.execute("SELECT COUNT(*) c FROM unit").fetchone()["c"]
        row = conn.execute(
            "SELECT value FROM pos_meta WHERE key='covered_units'").fetchone()
        out["covered"] = int(row["value"]) if row else 0
        # No repair here: this is a read-only report, and healing is
        # `pending_modules`' business.
        pend = pending_modules(conn, repair=False)
        out["pending"] = [{k: v for k, v in p.items() if k != "note"}
                          for p in pend[:20]]
        n = len(pend)
        units = sum(p["units"] for p in pend)
        out["uncovered"] = units
        if not n:
            out["complete"] = True
            return out
        out["reason"] = (
            f"{n} module{'s' if n != 1 else ''} awaiting indexing "
            f"({units:,} unit{'s' if units != 1 else ''}); "
            f"the app does this in the background, or run "
            f"python3 tools/build_pos_index.py")
    except Exception as e:
        out["reason"] = f"{type(e).__name__}: {e}"
    return out


def coverage() -> dict:
    conn = db.connect()
    ensure(conn)
    _unit_uids(conn)
    try:
        terms = conn.execute("SELECT COUNT(*) c FROM pos_term").fetchone()["c"]
        rows = conn.execute("SELECT COUNT(*) c FROM pos").fetchone()["c"]
        built = conn.execute(
            "SELECT value FROM pos_meta WHERE key='built'").fetchone()
        units = conn.execute("SELECT COUNT(*) c FROM pos_unit").fetchone()["c"]
    except Exception:
        return {"built": False, "terms": 0, "rows": 0, "units": 0}
    ends_rows = 0
    try:
        ends_rows = conn.execute("SELECT COUNT(*) c FROM pos_end").fetchone()["c"]
    except Exception:
        pass
    return {"built": bool(built), "terms": terms, "rows": rows, "units": units,
            "max_positions": MAX_POS,
            "ends_rows": ends_rows, "ends": ends_available(conn)}


def _meta_get(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM pos_meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def _meta_set(conn, key: str, value) -> None:
    conn.execute("INSERT OR REPLACE INTO pos_meta(key,value) VALUES(?,?)",
                 (key, str(value)))


def _stemmer_fingerprint() -> str:
    """A cheap signature of the stemmer's behaviour.

    The stored stems are derived data, and a derived column that cannot notice
    its own source changing goes quietly stale: fix the stemmer, and the index
    keeps answering with the old grouping while the text path answers with the
    new one.  That is exactly the kind of drift the index exists to avoid, so
    the stemmer is fingerprinted and the column recomputed when it moves.

    Fingerprinting the source rather than the behaviour is deliberate: it also
    catches an edit to `_NO_STEM`, which changes no probe word's stem until you
    happen to probe that word.
    """
    import hashlib
    import inspect
    try:
        src = inspect.getsource(db.stem) + repr(sorted(db._NO_STEM))
    except (OSError, TypeError, AttributeError):
        return "unknown"
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]


def ensure_stems(*, force: bool = False) -> dict:
    """Give every term its stem, and index it.

    The engine matches a query word against `db.token_key(token)` -- the *stem* of
    the token -- not against the token itself.  So `love` matches "loves" as well
    as "love" even with "match all forms" off, because that is what the stemmer
    is for.  The index held surface forms only, which is why every proximity
    answer came up short: `king NEAR kingdom` gave 483 where the engine gave 735,
    almost entirely on inflected forms.

    Only the one-million-row term dictionary needs this.  The thirty-six million
    postings already hold the positions of every surface form, so a query finds
    them by stem without any of it being rebuilt.
    """
    conn = db.connect()
    ensure(conn)
    total = conn.execute("SELECT COUNT(*) c FROM pos_term").fetchone()["c"]
    fp = _stemmer_fingerprint()
    was = _meta_get(conn, "stemmer_fp")
    stale = was != fp
    if not force and not stale and total:
        have = conn.execute(
            "SELECT COUNT(*) c FROM pos_term WHERE stem IS NOT NULL").fetchone()["c"]
        if have >= total:
            return {"ok": True, "terms": total, "updated": 0, "stale": False}
    rows = conn.execute("SELECT id, form FROM pos_term").fetchall()
    buf = [(db.stem(r["form"]), r["id"]) for r in rows]
    for i in range(0, len(buf), 20000):
        conn.executemany("UPDATE pos_term SET stem=? WHERE id=?",
                         buf[i:i + 20000])
    _meta_set(conn, "stemmer_fp", fp)
    conn.commit()
    return {"ok": True, "terms": total, "updated": len(buf),
            "stale": stale, "fingerprint": fp}


def _stem_term_ids(conn, form: str) -> list[int]:
    """Every term id whose stem matches -- that is, every inflection."""
    stem = db.stem(db.fold(form))
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM pos_term WHERE stem=?", (stem,))]
    row = conn.execute("SELECT id, stem FROM pos_term WHERE form=?",
                       (db.fold(form),)).fetchone()
    if row is not None and row["id"] not in ids:
        ids.insert(0, row["id"])
    return ids


def _pooled(conn, term: str, column: str, *, limit: int,
            part: int | None) -> dict[int, list[int]]:
    """Every occurrence of every inflection of `term`, in one pass per form."""
    out: dict[int, list[int]] = {}
    for tid in _stem_term_ids(conn, term):
        if part is None:
            rows = conn.execute(
                f"SELECT uid, {column} FROM pos WHERE term_id=? LIMIT ?",
                (tid, limit))
        else:
            rows = conn.execute(
                f"SELECT uid, {column} FROM pos WHERE term_id=? AND part=? "
                f"LIMIT ?", (tid, part, limit))
        for r in rows:
            out.setdefault(r["uid"], []).extend(_unpack(r[column]) if r[column] else [0])
    for v in out.values():
        v.sort()
    return out


def postings_stem(term: str, *, limit: int = 100000,
                  part: int | None = None) -> dict[int, list[int]]:
    """Token positions of every inflection of `term`."""
    return _pooled(db.connect(), term, "pos", limit=limit, part=part)


def char_postings_stem(term: str, *, limit: int = 100000,
                       part: int | None = None) -> dict[int, list[int]]:
    """Character offsets of every inflection of `term`."""
    return _pooled(db.connect(), term, "cpos", limit=limit, part=part)


def _term_id(conn, form: str) -> int | None:
    row = conn.execute("SELECT id FROM pos_term WHERE form=?",
                       (db.fold(form),)).fetchone()
    return row["id"] if row else None


def char_postings(term: str, *, limit: int = 100000,
                  part: int | None = None) -> dict[int, list[int]]:
    """uid -> character offsets, for the operators measured in characters."""
    conn = db.connect()
    tid = _term_id(conn, term)
    if tid is None:
        return {}
    out: dict[int, list[int]] = {}
    if part is None:
        for r in conn.execute(
                "SELECT uid, cpos FROM pos WHERE term_id=? LIMIT ?", (tid, limit)):
            out[r["uid"]] = _unpack(r["cpos"]) if r["cpos"] else [0]
        return out
    for r in conn.execute(
            "SELECT uid, cpos FROM pos WHERE term_id=? AND part=? LIMIT ?",
            (tid, part, limit)):
        out[r["uid"]] = _unpack(r["cpos"]) if r["cpos"] else [0]
    return out


def _min_gap(a: list[int], b: list[int]) -> int | None:
    """Smallest |difference| between two sorted position lists.

    Exposed on its own because it is worth testing on its own: it was wrong in a
    way that only showed up as missing results a long way downstream.
    """
    best = None
    x = y = 0
    while x < len(a) and y < len(b):
        d = b[y] - a[x]
        ad = -d if d < 0 else d
        if best is None or ad < best:
            best = ad
            if best == 0:
                return 0
        # Advance whichever pointer holds the smaller value: only moving that
        # list towards the other can narrow the gap.
        if d < 0:
            y += 1
        else:
            x += 1
    return best


def _getter(metric: str, stem: bool):
    """The postings reader for a metric.

    Stem-aware by default, because the engine compares `db.token_key(token)` --
    the stem -- against the stemmed query word, so `love` reaches "loves".  An
    index holding surface forms answers a proximity question about a different
    set of words than the one being asked, which is how `king NEAR kingdom` came
    back 250 hits short.
    """
    if stem:
        return postings_stem if metric == "words" else char_postings_stem
    return postings if metric == "words" else char_postings


def min_gap_metric(terms: list[str], metric: str = "words", *,
                   limit: int = 100000, part: int = PART_BODY,
                   stem: bool = True) -> dict[int, int]:
    """uid -> the smallest distance between any two of the terms.

    `metric` is "words" for a token distance, as `WITHIN n WORDS` counts, or
    "chars" for a character distance, as `NEAR` and `WITHIN n CHARS` count.  The
    two are stored separately because they are not interchangeable, and a
    candidate that satisfies neither is not evidence about the other.
    """
    if len(terms) < 2:
        return {}
    getter = _getter(metric, stem)
    lists = [getter(t, limit=limit, part=part) for t in terms]
    if any(not p for p in lists):
        return {}
    keys = set(lists[0])
    for p in lists[1:]:
        keys &= set(p)
    out: dict[int, int] = {}
    for uid in sorted(keys)[:limit]:
        best = None
        for i in range(len(lists)):
            for j in range(i + 1, len(lists)):
                g = _min_gap(lists[i][uid], lists[j][uid])
                if g is not None and (best is None or g < best):
                    best = g
                if best == 0:
                    break
            if best == 0:
                break
        if best is not None:
            out[uid] = best
    return out


def satisfies(terms: list[str], *, metric: str = "words", lo: int = 0,
              hi: int | None = None, limit: int = 100000,
              part: int = PART_BODY, stem: bool = True) -> set[int]:
    """Units where some pair of the terms lies within [lo, hi].

    `lo` is the operator's own floor: this app treats the minimum
    separation of two *different* words as one, because the punctuation between
    them is ignored -- so `WITHIN 1 WORDS` means adjacent tokens, which is a gap
    of one index.  For characters the floor is two, since a separator counts.
    """
    gaps = min_gap_metric(terms, metric, limit=limit, part=part, stem=stem)
    if hi is None:
        return {u for u, g in gaps.items() if g >= lo}
    return {u for u, g in gaps.items() if lo <= g <= hi}


def order_ok(terms: list[str], metric: str = "words",
             *, ordered: bool = True, limit: int = 100000,
             part: int = PART_BODY, stem: bool = True) -> set[int]:
    """Units where the terms occur in the given order (or in any order).

    Distance alone cannot answer BEFORE and AFTER: two words can be close and
    still be the wrong way round, and "close" knows nothing about which came
    first.
    """
    if len(terms) < 2:
        return set()
    getter = _getter(metric, stem)
    lists = [getter(t, limit=limit, part=part) for t in terms]
    if any(not p for p in lists):
        return set()
    keys = set(lists[0])
    for p in lists[1:]:
        keys &= set(p)
    out = set()
    for uid in keys:
        seq = [ps[uid] for ps in lists]
        ok = True
        for k in range(len(seq) - 1):
            if ordered:
                if not any(a < b for a in seq[k] for b in seq[k + 1]):
                    ok = False
                    break
            else:
                if not any(a != b for a in seq[k] for b in seq[k + 1]):
                    ok = False
                    break
        if ok:
            out.add(uid)
    return out


def _needle_forms(word: str) -> list[str]:
    """The surface forms a word as written is allowed to match.

    The engine adds the possessives to its needle list, because `db.words` keeps
    "Faith's" as one token and a reader asking for *faith* means the word in it.
    Leaving them out here is how `love NEAR hope` came back 211 units where the
    engine had 213: every unit whose only occurrence was "Love's" was in the
    answer on one side and not the other.
    """
    return [word, word + "'s", word + "’s"]


def occurrences(word: str, *, forms: bool = False, limit: int = 250_000,
                metric: str = "both", lengths: bool = False
                ) -> dict[int, list[tuple[int, int, int]]] | None:
    """uid -> every occurrence of `word`, as (word index, char start, char length).

    One reader for every second-order operator, written to agree with the engine's
    `_term_match` exactly.  Three decisions are what that takes, and each of them
    was a measured disagreement at some point:

    * **Which forms count.**  The engine matches a word as written by default and
      its stem under "match all forms", and the possessive forms belong to the
      first while the stem already covers them in the second.  One reader that
      knows both is the only way the two modes cannot drift apart.
    * **Where a title match sits.**  A title is a separate region, so its word
      indices do not continue the body's -- and the engine gives them -1.  That
      is not a rounding detail: -1 is what puts a heading before its own text,
      and what stops two words in one heading from counting as `WITHIN n WORDS`
      of each other.  The regions are returned as one list in the order the
      engine's own sorted set produces, because that is the list it compares.
    * **When to refuse.**  None -- never an empty answer -- when the word is one
      the index has never seen, when a posting list is longer than the caller's
      limit, or when any unit's positions were capped at `MAX_POS`.  Each of
      those makes an answer built on it *wrong* rather than small, and a caller
      that cannot take the whole list has to decline rather than answer part.

    `metric` says which positions the caller is going to compare, so that it only
    pays for those: `NEAR` needs character starts and would otherwise decode
    `lord`'s token indices -- a quarter of a million varints -- to throw them
    away.  Whatever is not asked for comes back as 0.
    """
    conn = db.connect()
    if forms:
        ids = _stem_term_ids(conn, word)
        if not ids:
            return None
    else:
        ids = []
        for f in _needle_forms(word):
            tid = _term_id(conn, f)
            # `dedupe`, because the two apostrophes fold to the same character:
            # `faith’s` and `faith's` are one form in the dictionary, and asking
            # for it twice would read its postings twice and pool every position
            # into every unit that has one.
            if tid is not None and tid not in ids:
                ids.append(tid)
        if not ids:
            return None
    ph = ",".join("?" * len(ids))
    # Read whole or not at all.  `lord` occurs in 57,640 units; reading the first
    # 32,000 of them and reporting every proximity match in that range is not a
    # smaller answer, it is a wrong one, and nothing in it would say so.
    for tid in ids:
        if conn.execute("SELECT COUNT(*) c FROM pos WHERE term_id=?",
                        (tid,)).fetchone()["c"] > limit:
            return None
    if conn.execute(
            f"SELECT 1 FROM pos WHERE term_id IN ({ph}) AND tf>0 LIMIT 1",
            ids).fetchone():
        # One unit somewhere repeats this word more than MAX_POS times, so its
        # stored positions are a subset.  Proximity over a subset is a shorter
        # list presented as a whole one, which is the failure this module exists
        # to refuse -- so the word is declined for every query.
        return None

    want_idx = metric in ("words", "both")
    want_cs = metric in ("chars", "both")
    lens: dict[tuple, list[int]] = {}
    if lengths:
        if not ends_available(conn):
            return None
        for tid in ids:
            for r in conn.execute(
                    "SELECT uid, part, elen FROM pos_end WHERE term_id=? LIMIT ?",
                    (tid, limit)):
                lens[(tid, r["uid"], r["part"])] = (
                    _unpack_lengths(r["elen"]))

    cols = "uid, part, " + (("pos" if want_idx else "")
                            + (", " if want_idx and want_cs else "")
                            + ("cpos" if want_cs else ""))
    out: dict[int, list[tuple[int, int, int]]] = {}
    for tid in ids:
        rows = conn.execute(
            f"SELECT {cols} FROM pos WHERE term_id=? LIMIT ?",
            (tid, limit)).fetchall()
        for r in rows:
            # Only the lists that were asked for take part in `n`: the others
            # come back as [0] so that a missing blob cannot make `n` zero and
            # drop every word the row does have.
            ps = _unpack(r["pos"]) if (want_idx and r["pos"]) else [0]
            cs = _unpack(r["cpos"]) if (want_cs and r["cpos"]) else [0]
            ls = (lens.get((tid, r["uid"], r["part"])) or []) if lengths else []
            if lengths and not ls:
                return None          # no lengths for a row that has positions
            n = None
            for lst in ((ps if want_idx else None),
                        (cs if want_cs else None),
                        (ls if lengths else None)):
                if lst is None:
                    continue
                n = len(lst) if n is None else min(n, len(lst))
            if not n:
                continue
            got = out.setdefault(r["uid"], [])
            # `sorted(set(...))` below collapses any duplicate the pooled forms
            # produced, exactly as the engine's own set does.
            for i in range(n):
                got.append((-1, cs[i] if want_cs else 0, ls[i] if lengths else 0)
                           if r["part"] == PART_TITLE
                           else (ps[i] if want_idx else 0,
                                 cs[i] if want_cs else 0,
                                 ls[i] if lengths else 0))
    for uid, lst in out.items():
        # Sorted and de-duplicated, because that is what the engine does before
        # anything compares two positions: two entries with the same word index
        # and start are one place, and an unsorted list would make the
        # two-pointer walk below walk off the end of the shorter one.
        out[uid] = sorted(set(lst))
    return out


def _ordered_in_window(A: list, B: list, after: bool, lo_w: int, hi_w: int,
                       lo_c: int, hi_c: int, by_words: bool,
                       windowed: bool) -> bool:
    """`A BEFORE B` / `A AFTER B`, optionally inside a distance window.

    The two questions are kept apart.  Order is `near[0] > far[0]` on token
    indices -- never on character offsets -- because a word can start sooner and
    still come later in the sentence, and an order operator that measured the
    wrong thing would be wrong in a way no result count reveals.  The window is
    then applied on the metric that was asked for.
    """
    for x in A:
        for y in B:
            near, far = (x, y) if after else (y, x)
            if not far[0] < near[0]:
                continue
            if not windowed:
                return True
            if by_words:
                if lo_w <= near[0] - far[0] <= hi_w:
                    return True
            elif lo_c <= near[1] - (far[1] + far[2]) <= hi_c:
                return True
    return False


def _window_symmetric(A: list, B: list, lo_w: int, hi_w: int, lo_c: int,
                      hi_c: int, by_words: bool) -> bool:
    """`A NEAR B` and `A THEN B`: either side may come first.

    Sorted once per pair list and scanned, rather than the quadratic walk the
    engine does, because the question is a closest-pair question: what matters
    is whether *any* pair from the two lists falls inside the window, so the two
    sorted runs are advanced against each other.
    """
    if by_words:
        ax = sorted(x[0] for x in A)
        bx = sorted(y[0] for y in B)
        i = j = 0
        while i < len(ax) and j < len(bx):
            gap = bx[j] - ax[i]
            if gap < 0:
                gap = -gap
            if lo_w <= gap <= hi_w:
                return True
            if ax[i] <= bx[j]:
                i += 1
            else:
                j += 1
        return False
    # A character gap is measured from the end of the earlier word to the start
    # of the later one, which is why `occurrences` was asked for lengths.  Both
    # directions have to be considered, because either side may come first, and
    # reading only A-ends against B-starts finds every pair where A precedes B
    # and none of the ones where B does -- which is why `kingdom NEAR king`
    # answered 249 where the engine had 524.  Sorting every interval from both
    # sides by its start and tracking the furthest end seen per side gives the
    # closest approach in one pass, since the nearest earlier interval of the
    # other side is the one that ends last.
    items = [(x[1], x[1] + x[2], 0) for x in A]
    items += [(y[1], y[1] + y[2], 1) for y in B]
    items.sort()
    far = [-1, -1]
    for start, end, side in items:
        seen = far[1 - side]
        if seen >= 0:
            gap = start - seen
            if lo_c <= gap <= hi_c:
                return True
        if end > far[side]:
            far[side] = end
    return False


def relate(a: dict[int, list], b: dict[int, list], kind: str, *,
           lo_w: int = 0, hi_w: int = 0, lo_c: int = 0, hi_c: int = 0,
           windowed: bool | None = None,
           by_words: bool = False) -> set[int]:
    """uids whose two occurrence lists satisfy a distance or order operator.

    Each branch is the arithmetic reading of one line in the engine's `_relate`,
    and the correspondence is the whole point: this index is allowed to be
    faster, never different, so every one of these has to be the same question
    the engine asked.

    One of the engine's behaviours is reproduced rather than corrected, because
    correcting it here would leave the index disagreeing with the text path: an
    order operator written with no number is order and nothing else, so a bare
    `BEFORE` has no window to apply.

    `BEFORE n CHARS`, `AFTER n CHARS` and `NEAR n WORDS` *do* apply the
    distance they are given.  They used to ignore it here in the same way the
    engine did, which was at least consistent; the engine no longer ignores it,
    so this no longer may.  `windowed` and `by_words` are the engine's own
    answers to "is there a window" and "which metric", passed in rather than
    re-derived, so the two paths cannot drift apart on a default.

    The bounds arrive already resolved by the engine's `_set_bound`: a single
    number is a ceiling with the metric's floor beneath it, and a range carries
    both ends.  Passing a raw `n` through as both ends here is what used to make
    `WITHIN 50 CHARS` mean a gap of exactly fifty.
    """
    out: set[int] = set()
    for uid in set(a) & set(b):
        A, B = a[uid], b[uid]
        if not A or not B:
            continue
        if kind in ("BEFORE", "AFTER", "NEAR", "THEN"):
            if windowed is None:
                windowed = kind in ("NEAR", "THEN") or bool(hi_w or hi_c)
            if kind in ("BEFORE", "AFTER"):
                # Order is decided on token indices, which is what keeps it
                # independent of the metric, and the window is then applied on
                # whichever metric was asked for: two separate questions.
                if _ordered_in_window(A, B, kind == "AFTER",
                                      lo_w, hi_w, lo_c, hi_c, by_words, windowed):
                    out.add(uid)
            else:
                # NEAR and THEN are symmetric: either side may come first.
                if _window_symmetric(A, B, lo_w, hi_w, lo_c, hi_c, by_words):
                    out.add(uid)
            continue
        if kind == "WITHIN" and hi_c:
            # `_relate`: lo <= y.start - (x.start + x.len) <= hi.  The
            # separation is measured from the *end* of the left word, which is
            # why the lengths are stored: two start offsets cannot give it.
            bstart = [y[1] for y in B]
            for x in A:
                end = x[1] + x[2]
                i = bisect_left(bstart, end + lo_c)
                if i < len(bstart) and bstart[i] <= end + hi_c:
                    out.add(uid)
                    break
        elif kind == "WITHIN":
            # `_relate`: lo_w <= y.word_index - x.word_index <= hi_w.
            # The lower bound is read, because the engine now reads it too: a
            # range like `WITHIN 3-5 WORDS` used to be measured as 1 to 5 on both
            # paths, and when the engine was corrected this branch was not, so
            # `faith WITHIN 3-5 WORDS hope` answered 1-5 from the index and 3-5
            # from the text -- the index returning units the engine had excluded.
            bwi = [y[0] for y in B]
            for x in A:
                i = bisect_left(bwi, x[0] + lo_w)
                if i < len(bwi) and bwi[i] <= x[0] + hi_w:
                    out.add(uid)
                    break
    return out


def posting_count(term: str, part: int | None = None) -> int:
    """How many (unit, region) rows a term has, without reading them.

    The search engine asks this first, because a truncated posting list is not a
    smaller answer -- it is a wrong one.  `lord` occurs in 57,640 units; a query
    that read only the first 32,000 of them reported every proximity match in
    that range and none of the rest, with nothing to say so.  So a caller that
    cannot take the whole list must decline rather than answer partially.
    """
    conn = db.connect()
    tid = _term_id(conn, term)
    if tid is None:
        return 0
    if part is None:
        return conn.execute("SELECT COUNT(*) c FROM pos WHERE term_id=?",
                            (tid,)).fetchone()["c"]
    return conn.execute(
        "SELECT COUNT(*) c FROM pos WHERE term_id=? AND part=?",
        (tid, part)).fetchone()["c"]


def postings(term: str, *, limit: int = 100000, part: int | None = None
             ) -> dict[int, list[int]]:
    """uid -> positions, for one term.

    `part` narrows to one region: the body, or the unit's title.  Leaving it
    None unions the two, which is right for "does this term occur here at all" and
    wrong for anything about distance -- a heading and its body are not adjacent
    to one another, so a proximity check that mixed them would report pairs that
    do not exist.

    A term the index has never seen returns an empty dict, and a caller that
    treats that as "no postings" would wrongly conclude the term occurs
    nowhere.  `known()` is how a caller tells the two apart.
    """
    conn = db.connect()
    tid = _term_id(conn, term)
    if tid is None:
        return {}
    out: dict[int, list[int]] = {}
    if part is None:
        for r in conn.execute(
                "SELECT uid, pos FROM pos WHERE term_id=? LIMIT ?", (tid, limit)):
            out[r["uid"]] = _unpack(r["pos"]) if r["pos"] else [0]
        return out
    for r in conn.execute(
            "SELECT uid, pos FROM pos WHERE term_id=? AND part=? LIMIT ?",
            (tid, part, limit)):
        out[r["uid"]] = _unpack(r["pos"]) if r["pos"] else [0]
    return out


def posting_count_stem(term: str, part: int | None = None) -> int:
    """How many (unit, region) rows every inflection of `term` has.

    The stem-aware counterpart of `posting_count`, and the one a boolean answer
    needs.  `posting_count` counts the literal surface form only, so asking it
    about `love` reported 9,111 units while `loved`, `loves`, `loving`,
    `lovely`, `lover` and `lovers` sit in six more -- and the search engine
    answered with the 9,111, because it had asked the wrong question.  The
    engine matches a query word against the *stem* of each token, so a count of
    surface forms answers a question nobody asked, and the shortfall looked
    exactly like a short posting list: a smaller result with nothing to say so.
    """
    conn = db.connect()
    ids = _stem_term_ids(conn, term)
    if not ids:
        return 0
    # Distinct units, for the same reason as `posting_count`: the caller holds
    # the answer as a set of uids.
    ph = ",".join("?" * len(ids))
    if part is None:
        return conn.execute(
            f"SELECT COUNT(DISTINCT uid) c FROM pos WHERE term_id IN ({ph})",
            ids).fetchone()[0]
    return conn.execute(
        f"SELECT COUNT(DISTINCT uid) c FROM pos "
        f"WHERE term_id IN ({ph}) AND part=?", [*ids, part]).fetchone()[0]


def known(term: str) -> bool:
    """Whether the index has ever seen this term at all."""
    conn = db.connect()
    return _term_id(conn, term) is not None


def term_frequency(term: str, uid: int, *, part: int = PART_BODY) -> int:
    conn = db.connect()
    tid = _term_id(conn, term)
    if tid is None:
        return 0
    row = conn.execute(
        "SELECT tf, pos FROM pos WHERE term_id=? AND uid=? AND part=?",
        (tid, uid, part)).fetchone()
    if row is None:
        return 0
    return row["tf"] or (len(_unpack(row["pos"])) if row["pos"] else 0)


def intersect(*terms: str, limit: int = 100000) -> list[int]:
    """Units containing every one of `terms`.  Posting-list intersection.

    Only the shared uids are ever materialised, so this does not read the unit
    table at all -- which is the point: intersecting three thousand postings costs
    three thousand small reads, where verifying the same conjunction by reading
    units and re-checking their text costs a walk of every candidate's characters.
    """
    if not terms:
        return []
    lists = []
    for t in terms:
        p = postings(t, limit=limit)
        if not p:
            return []
        lists.append(set(p))
    acc = set.intersection(*lists)
    return sorted(acc)[:limit]


def min_gap(terms: list[str], *, limit: int = 100000) -> list[tuple[int, int]]:
    """(uid, smallest token gap between any two of the terms).

    The gap is measured the way `NEAR` means it here -- a difference of token
    indices, so 0 is adjacency.  Only units where every term occurs are
    considered, because a unit missing a term has no pair to measure.
    """
    if len(terms) < 2:
        return []
    lists = [postings(t, limit=limit) for t in terms]
    if any(not p for p in lists):
        return []
    keys = set(lists[0])
    for p in lists[1:]:
        keys &= set(p)
    out = []
    for uid in sorted(keys)[:limit]:
        best = None
        for i in range(len(lists)):
            for j in range(i + 1, len(lists)):
                a, b = lists[i][uid], lists[j][uid]
                # Merge walk over both sorted lists, and record the absolute
                # difference at every comparison.  Recording only the
                # non-negative branch was the bug: with `faith` at [12] and
                # `love` at [10], the walk advanced past the end of the first
                # list having never stored the gap of 2 that was sitting right
                # there, so the unit was dropped from the result entirely.
                x = y = 0
                while x < len(a) and y < len(b):
                    d = b[y] - a[x]
                    ad = -d if d < 0 else d
                    if best is None or ad < best:
                        best = ad
                        if best == 0:
                            break
                    # Advance whichever pointer holds the *larger* value, since
                    # only moving that list towards the other can narrow the
                    # gap.  These branches were the wrong way round: when
                    # a[x] > b[y] the code advanced a, walking off the end of a
                    # and discarding a closer value sitting at b[y+1].  With
                    # lord at [386] and faith at [315, 361] that reported 71
                    # instead of 25, and 275 real proximity matches vanished
                    # with nothing to indicate it.
                    if d < 0:
                        y += 1
                    else:
                        x += 1
        if best is not None:
            out.append((uid, best))
    return out


def phrase(term_forms: list[str], *, limit: int = 100000,
           part: int | None = None, stem: bool = True
           ) -> list[int] | None:
    """Units where the words appear consecutively and in order.

    `part=None` searches **both** regions a unit has, and that is the default
    because the engine searches both.  A title is a separate region rather than
    a prefix of the body, and `search._term_match` runs every phrase against the
    title as well as the text -- "Christ Also Loved the Church" has to be
    findable by "loved".  Searching only the body therefore answers with the
    units whose *heading* holds the phrase missing: 44 of 785 for
    `in the beginning`, 26 of 156 for `Lamb of God`.

    Pass `part=PART_BODY` (or `PART_TITLE`) to restrict it deliberately.

    ## It refuses rather than answering part of one

    `None` means *cannot say*, and it is the honest answer far more often than
    it looks.  A phrase is an intersection, so it is bounded by its **commonest**
    word -- and the commonest words in any language are the short function ones.
    In this library `the` has 392,149 postings, `of` 350,963 and `in` 226,696,
    against a default limit of 100,000.

    The first version of this function read `postings(w, limit=100000)`, which
    silently returned the first 100,000 units, and intersected that truncated
    slice with the rest.  It answered, confidently, and it was **wrong**: `in the
    beginning` came back as 45 units where the engine says 785, `Lamb of God` as
    26 where the engine says 156.  The number was not a smaller answer, it was an
    arbitrary subset of one, and nothing in it said so.

    So the count is taken first and the whole call declines if any word's
    postings do not fit -- which is the rule `occurrences`, `postings_stem` and
    the whole proximity path already follow, and the one this function was the
    exception to.  The practical consequence is that a phrase containing a
    function word cannot be answered from the index at all and belongs on the
    text path, which is the correct outcome rather than a limitation to hide.

    ## Stems, because that is what the engine compares

    `search._term_match` stems both sides: the phrase words are already stems and
    each token is put through `db.token_key`.  Matching surface forms here
    answered a *different question* -- `beginning` matched, `began` and
    `begins` did not -- which is another way of being wrong rather than small.
    """
    if not term_forms:
        return []
    parts = (PART_BODY, PART_TITLE) if part is None else (part,)
    forms = ([db.token_key(w) for w in term_forms] if stem
             else [db.fold(w) for w in term_forms])
    # Refuse before reading anything.
    for f in forms:
        for pt in parts:
            n = (posting_count_stem(f, pt) if stem else posting_count(f, pt))
            if n > limit:
                return None
    out: set[int] = set()
    for pt in parts:
        out.update(_phrase_region(forms, limit=limit, part=pt, stem=stem))
        if len(out) >= limit:
            break
    return sorted(out)[:limit]


def _phrase_region(term_forms: list[str], *, limit: int, part: int,
                   stem: bool = True) -> list[int]:
    """The phrase answer within one region of each unit.

    The caller has already checked that every list fits inside `limit`.
    """
    get = postings_stem if stem else postings
    lists = [get(w, limit=limit, part=part) for w in term_forms]
    if any(not p for p in lists):
        return []
    keys = set(lists[0])
    for p in lists[1:]:
        keys &= set(p)
    out = []
    for uid in sorted(keys)[:limit]:
        first = lists[0][uid]
        # ps is a postings *dict* (uid -> positions), so it has to be indexed
        # by uid.  `set(ps)` built a set of uids instead, and the test then
        # asked whether a token index was one of them -- always false, so the
        # function returned nothing at all for any phrase.
        rest = [(set(ps[uid]), k) for k, ps in enumerate(lists[1:], start=1)]
        ok = False
        for start in first:
            if all((start + k) in st for st, k in rest):
                ok = True
                break
        if ok:
            out.append(uid)
    return out


def unit_row(conn, uid: int):
    return conn.execute(
        "SELECT u.* FROM pos_unit pu JOIN unit u "
        "ON u.module_id = pu.module_id AND u.key = pu.key WHERE pu.uid=?",
        (uid,)).fetchone()


def uids_for_keys(module_id: str, keys: list[str]) -> list[int]:
    if not keys:
        return []
    conn = db.connect()
    ph = ",".join("?" * len(keys))
    return [r["uid"] for r in conn.execute(
        f"SELECT uid FROM pos_unit WHERE module_id=? AND key IN ({ph})",
        [module_id, *keys])]


def keys_for_uids(uids: list[int]) -> list[tuple[str, str]]:
    if not uids:
        return []
    conn = db.connect()
    out = []
    for i in range(0, len(uids), 500):
        chunk = uids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        for r in conn.execute(
                f"SELECT module_id, key FROM pos_unit WHERE uid IN ({ph})",
                chunk):
            out.append((r["module_id"], r["key"]))
    return out

# ------------------------------------------------- background indexer -------

#: Written by the worker so any process can see what it is doing.
WORKER_KEY = "worker"


def worker_state() -> dict:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT value FROM pos_meta WHERE key=?", (WORKER_KEY,)).fetchone()
        return json.loads(row["value"]) if row and row["value"] else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _set_worker_state(**kw) -> None:
    conn = db.connect()
    st = worker_state()
    st.update(kw)
    st["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute("INSERT OR REPLACE INTO pos_meta(key,value) VALUES(?,?)",
                 (WORKER_KEY, json.dumps(st)))
    conn.commit()


def brief() -> dict:
    """A cheap status readout, safe to poll.

    Deliberately not `staleness()`: that one counts uncovered units with a
    correlated subquery, which is far too slow for a status poll that the front
    end refreshes.  This reports what a person needs to know -- is it in use, and
    is anything being done to it -- from a count and a row of metadata.
    """
    conn = db.connect()
    try:
        w = worker_state()
        ok = available()
        units = conn.execute("SELECT COUNT(*) c FROM unit").fetchone()["c"]
        row = conn.execute(
            "SELECT value FROM pos_meta WHERE key='covered_units'").fetchone()
        covered = int(row["value"]) if row else 0
        out = {"available": ok, "units": units, "covered_units": covered,
               "state": w.get("state") or ("current" if ok else "stale")}
        for k in ("modules", "units_queued", "note", "error", "at"):
            if w.get(k) is not None:
                out[k] = w[k]
        if w.get("units") is not None and w.get("state") == "building":
            out["units_queued"] = w.get("units")
        return out
    except Exception as exc:                          # noqa: BLE001
        return {"available": False, "state": "error",
                "error": f"{type(exc).__name__}: {exc}"}


class BackgroundIndexer:
    """Keeps the positional index current without being asked.

    An index that has to be rebuilt by hand is not an indexer, it is a script.
    The indexer keeps itself current.  Newly indexed books are merged into the
    main index in the background.
    this does the same, using the incremental build that already exists -- only
    the modules that are actually missing get read.

    Two limits keep it from becoming a nuisance:

    * **A size budget.**  A module is normally thousands of units, so catching up
      after installing a book is a second or two.  Rebuilding an entire library is
      a quarter of an hour, and doing that inside the server process would make
      the app feel broken while it ran.  Past the budget the work is reported and
      left to ``tools/build_pos_index.py``, which is the right tool for a bulk
      build.
    * **It never raises.**  A background thread that dies quietly leaves an index
      that silently stops being maintained, which is worse than one that never
      started.  Failures are recorded in the worker state instead.

    Until it finishes, `available()` is false and searches take the text path, so
    a half-built index is never the one answering anything.
    """

    def __init__(self, *, interval: float = 30.0, max_units: int = 25_000,
                 max_modules: int = 25) -> None:
        self.interval = interval
        self.max_units = max_units
        self.max_modules = max_modules
        self._stop = False
        self._thread: threading.Thread | None = None

    # -- one pass, exposed so a test can drive it without a timer ------------
    def tick(self) -> dict:
        """Do any indexing that is currently warranted.  Returns what happened."""
        try:
            return self._tick()
        except Exception as exc:                      # noqa: BLE001
            # Recorded rather than raised: a dead worker is invisible, and an
            # index that quietly stops being maintained is the exact failure
            # this whole design refuses elsewhere.
            _set_worker_state(state="error", error=f"{type(exc).__name__}: {exc}")
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _tick(self) -> dict:
        if self.available():
            st = worker_state()
            if st.get("state") not in (None, "idle"):
                _set_worker_state(state="idle")
            return {"ok": True, "action": "none", "reason": "already current"}

        pend = pending_modules()
        if not pend:
            # Stale by the watermark but nothing per-module is outstanding: a
            # module was removed, so there is nothing to read.
            _set_worker_state(state="idle")
            return {"ok": True, "action": "none", "reason": "nothing pending"}

        mods = [p["module_id"] for p in pend]
        units = sum(p["units"] for p in pend)
        if len(mods) > self.max_modules or units > self.max_units:
            _set_worker_state(state="deferred", modules=len(mods), units=units,
                              note=f"over budget ({len(mods)} modules, "
                                   f"{units:,} units); run tools/build_pos_index.py")
            return {"ok": True, "action": "deferred", "modules": len(mods),
                    "units": units}

        _set_worker_state(state="building", modules=len(mods), units=units)
        res = build(modules=mods)
        _set_worker_state(state="idle", modules=0, units=0, last=res)
        return {"ok": True, "action": "built", "result": res,
                "modules": len(mods), "units": units}

    def available(self) -> bool:
        return available()

    # -- thread plumbing ----------------------------------------------------
    def _loop(self) -> None:
        # Give the app a moment to finish starting before competing for the disk.
        while not self._stop:
            try:
                self.tick()
            except Exception:                          # noqa: BLE001
                pass
            for _ in range(int(max(1, self.interval / 0.5))):
                if self._stop:
                    return
                time.sleep(0.5)

    def start(self) -> "BackgroundIndexer":
        if self._thread and self._thread.is_alive():
            return self
        self._stop = False
        self._thread = threading.Thread(
            target=self._loop, name="posindex", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop = True


def forget(module_id: str) -> dict:
    """Drop a removed module from the index, completely.

    Uninstalling has to reach in here.  It deletes the module's units, but it
    does not know that a derived index exists, and the leftovers are worse than
    nothing:

    * `modules_done` still lists the module, so a later install of the same id
      looks already-indexed and is skipped;
    * `pos_unit` rows go with the units, so the postings that were written for it
      become orphans that no query can reach;
    * reinstalling produces *new* unit ids, and nothing indexes them.

    The result is a library that looks fully indexed and returns answers that are
    quietly missing a whole book -- and `available()` agreeing with it, because it
    only compared totals.  That is the failure this whole design exists to avoid,
    so removal is not allowed to leave the index lying about coverage.

    A removed book stays in the library index until you rebuild deliberately --
    but the index is a separate file, and
    here the units themselves are deleted, so the postings would be unreachable
    regardless.  Deleting them is both cheaper and honest.
    """
    conn = db.connect()
    ensure(conn)
    uids = [r["uid"] for r in conn.execute(
        "SELECT uid FROM pos_unit WHERE module_id=?", (module_id,))]
    pos_rows = 0
    if uids:
        # Chunked: a Bible has ~30,000 units and SQLite caps a statement at
        # 999 host parameters by default.
        step = 500
        for i in range(0, len(uids), step):
            chunk = uids[i:i + step]
            ph = ",".join("?" * len(chunk))
            cur = conn.execute(f"DELETE FROM pos WHERE uid IN ({ph})", chunk)
            pos_rows += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            try:
                cur = conn.execute(
                    f"DELETE FROM pos_end WHERE uid IN ({ph})", chunk)
            except sqlite3.OperationalError:
                pass          # no length table yet: nothing to forget
    conn.execute("DELETE FROM pos_unit WHERE module_id=?", (module_id,))
    conn.execute("DELETE FROM pos_module WHERE module_id=?", (module_id,))
    try:
        row = conn.execute(
            "SELECT value FROM pos_meta WHERE key='modules_done'").fetchone()
        done = set(json.loads(row["value"])) if row and row["value"] else set()
        if module_id in done:
            done.discard(module_id)
            conn.execute("INSERT OR REPLACE INTO pos_meta(key,value) "
                         "VALUES('modules_done',?)", (json.dumps(sorted(done)),))
    except (json.JSONDecodeError, TypeError):
        pass
    # The length table keeps its own completion list, and a module dropped from
    # one but not the other would leave `ends_available()` comparing a set with a
    # uid it no longer has.  It is removed from both.
    try:
        row = conn.execute(
            "SELECT value FROM pos_meta WHERE key='ends_modules_done'"
        ).fetchone()
        edone = set(json.loads(row["value"])) if row and row["value"] else set()
        if module_id in edone:
            edone.discard(module_id)
            conn.execute("INSERT OR REPLACE INTO pos_meta(key,value) "
                         "VALUES('ends_modules_done',?)",
                         (json.dumps(sorted(edone)),))
    except (json.JSONDecodeError, TypeError):
        pass
    conn.commit()
    # Totals are recomputed from pos_module rather than decremented, so a module
    # removed while the index was already stale cannot leave the count too high --
    # which would make `available()` agree with an index that is not there.
    tot = conn.execute(
        "SELECT COALESCE(SUM(units),0) s FROM pos_module WHERE module_id IN "
        "(SELECT id FROM module WHERE installed_at>0)").fetchone()["s"]
    conn.execute("INSERT OR REPLACE INTO pos_meta(key,value) "
                 "VALUES('covered_units',?)", (str(int(tot)),))
    conn.commit()
    return {"ok": True, "module_id": module_id, "uids": len(uids),
            "pos_rows": pos_rows, "covered_units": int(tot)}


def audit(*, deep: bool = False) -> dict:
    """Prove the index matches the unit table.  Slow, and deliberately explicit.

    `available()` trusts bookkeeping, because the alternative costs minutes: `pos`
    is keyed on (term_id, uid, part) with no index on uid, so asking "does this
    particular unit have postings" one unit at a time is quadratic.  That was
    tried, and it hung.  So the proof lives here, run by
    `tools/build_pos_index.py --verify`, and nowhere on a request path.

    Two levels:

    * **Bookkeeping** (instant) -- every installed module has a coverage row, and
      the counts agree with the unit table.
    * **Rows** (`deep`, about twenty seconds) -- how many mapped units actually
      have postings, compared with how many could.

    The comparison is not "every unit has postings", because some legitimately do
    not: the builder indexes *words*, and a unit whose text is a bare numeric
    marker -- EUSEBIUS and Strong's number files are full of them, text like
    "@@@@5656" -- has none.  The text path tokenises those as numbers, so a search
    for one is answered by the text path; the index declines the term rather than
    matching it wrongly.  Slower, never wrong.
    """
    conn = db.connect()
    out: dict = {"ok": True, "units": 0, "indexed_units": 0, "note": ""}
    try:
        agg = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(units),0) s FROM pos_module "
            "WHERE module_id IN (SELECT id FROM module WHERE installed_at>0)"
        ).fetchone()
        mods = conn.execute(
            "SELECT COUNT(*) c FROM module WHERE installed_at>0").fetchone()["c"]
        units = conn.execute("SELECT COUNT(*) c FROM unit").fetchone()["c"]
        out["units"] = units
        notes = []
        if agg["n"] != mods:
            out["ok"] = False
            notes.append(f"{mods - agg['n']} installed module(s) have no "
                         f"coverage row")
        if agg["s"] != units:
            out["ok"] = False
            notes.append(f"coverage sums to {agg['s']:,} but there are "
                         f"{units:,} units")
        if deep:
            t0 = time.time()
            mapped = conn.execute("SELECT COUNT(*) c FROM pos_unit").fetchone()["c"]
            got = conn.execute(
                "SELECT COUNT(*) c FROM (SELECT DISTINCT uid FROM pos)").fetchone()["c"]
            out["indexed_units"] = got
            out["seconds"] = round(time.time() - t0, 1)
            if got > mapped:
                out["ok"] = False
                notes.append(f"{got - mapped:,} posting(s) point at unit ids that "
                             f"no longer exist")
            blank = conn.execute(
                "SELECT COUNT(*) c FROM pos_unit pu JOIN unit u "
                "ON u.module_id=pu.module_id AND u.key=pu.key "
                "WHERE u.text IS NOT NULL AND u.text <> '' "
                "AND u.text NOT GLOB '*[a-zA-Z]*' "
                "AND COALESCE(u.title,'') NOT GLOB '*[a-zA-Z]*'"
            ).fetchone()["c"]
            if mapped - got > blank:
                out["ok"] = False
                notes.append(f"{mapped - got - blank:,} mapped unit(s) hold a "
                             f"word but have no postings")
            else:
                notes.append(f"{mapped - got:,} unit(s) hold no indexable word "
                             f"(numeric markers), which is expected")
        # The length table is separate, so it can be out of step with the
        # postings: a module added since the last `--ends` run would have
        # positions and no lengths.  That combination is safe -- the operators
        # that need lengths decline -- so it is only a failure once the table
        # claims to be finished.
        have_ends = conn.execute(
            "SELECT COUNT(*) c FROM sqlite_master WHERE type='table' "
            "AND name='pos_end'").fetchone()["c"]
        if have_ends:
            n_pos = conn.execute("SELECT COUNT(*) c FROM pos").fetchone()["c"]
            n_end = conn.execute("SELECT COUNT(*) c FROM pos_end").fetchone()["c"]
            out["ends_rows"] = n_end
            if ends_available(conn):
                out["ends"] = True
                if n_end != n_pos:
                    out["ok"] = False
                    notes.append(f"{n_pos - n_end:,} posting(s) have no word "
                                 f"length, and a `WITHIN n CHARS` answer would "
                                 f"skip them")
            else:
                out["ends"] = False
                notes.append(f"word lengths are incomplete ({n_end:,} of "
                             f"{n_pos:,} rows); run "
                             f"tools/build_pos_index.py --ends")
        out["note"] = "; ".join(notes)
        return out
    except Exception as exc:                          # noqa: BLE001
        return {"ok": False, "note": f"{type(exc).__name__}: {exc}"}

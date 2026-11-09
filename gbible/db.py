"""SQLite storage.

One database holds the whole library: installed modules, their content index and
the search index.  FTS5 does the heavy lifting for text search; everything the
search engine needs that FTS cannot express (proximity, set algebra over
markers, stemming control, hit highlighting) is computed against the `marker`
table, which stores the position of every indexed token.

Why store every token rather than lean purely on FTS5:
  * `WITHIN n WORDS` / `WITHIN n CHARS` need word and character offsets.
  * `EQUALS` / `IN` / `INTERSECTS` need to know whether two things share a
    milestone, and how much of each is inside the other.
  * Strong's / lemma / morphology searches are marker queries, not text queries.

The token stream is built so punctuation is discarded but its position is
retained, making WORDS and CHARS the same engine with two metrics.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA_VERSION = 3

_local = threading.local()


def app_dir() -> Path:
    return Path(os.environ.get(
        "GBIBLE_HOME",
        Path(__file__).resolve().parent.parent / "data",
    )).resolve()


def db_path() -> Path:
    app_dir().mkdir(parents=True, exist_ok=True)
    return app_dir() / "gbible.db"


def cache_dir() -> Path:
    d = app_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def modules_dir() -> Path:
    d = app_dir() / "modules"
    d.mkdir(parents=True, exist_ok=True)
    return d


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ---------------------------------------------------------------- modules --
CREATE TABLE IF NOT EXISTS module (
    id            TEXT PRIMARY KEY,          -- slug, e.g. ebible-eng-web
    name          TEXT NOT NULL,
    abbrev        TEXT,
    type          TEXT NOT NULL,             -- taxonomy.ResourceType.id
    subject       TEXT NOT NULL DEFAULT '[]',-- JSON array
    lang          TEXT,
    lang_name     TEXT,
    version       TEXT,
    source        TEXT,                      -- repository id
    source_name   TEXT,
    source_url    TEXT,                      -- canonical page
    download_url  TEXT,                      -- what we actually fetched
    format        TEXT,
    license       TEXT,
    rights        TEXT,                      -- attribution string
    attribution   TEXT,                      -- attribution string
    description   TEXT,
    about         TEXT,
    author        TEXT,
    year          TEXT,
    size_bytes    INTEGER DEFAULT 0,
    installed_at  REAL,
    folder        TEXT,                      -- relative to modules_dir
    path          TEXT,                      -- absolute, for raw-source modules
    v11n          TEXT,                      -- versification scheme
    v11n_source   TEXT,                      -- 'builtin' | 'module'
    chapters      INTEGER DEFAULT 0,
    verses        INTEGER DEFAULT 0,
    entries       INTEGER DEFAULT 0,         -- articles / sections / records
    has_strongs   INTEGER DEFAULT 0,
    has_morph     INTEGER DEFAULT 0,
    has_lemma     INTEGER DEFAULT 0,
    has_notes     INTEGER DEFAULT 0,
    has_xref      INTEGER DEFAULT 0,
    has_redletter  INTEGER DEFAULT 0,
    index_types   TEXT NOT NULL DEFAULT '[]',-- JSON array
    priority      INTEGER DEFAULT 0,         -- 'Prioritize books' equivalent
    favorite      INTEGER DEFAULT 0,
    enabled       INTEGER DEFAULT 1,         -- visual filters master switch
    verified      INTEGER DEFAULT 0,
    notes_count   INTEGER DEFAULT 0,
    xrefs_count   INTEGER DEFAULT 0,
    heads_count   INTEGER DEFAULT 0,
    redwords      INTEGER DEFAULT 0,
    heading_count INTEGER DEFAULT 0,
    error         TEXT,
    raw_meta      TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_module_type ON module(type);
CREATE INDEX IF NOT EXISTS ix_module_lang ON module(lang);
CREATE INDEX IF NOT EXISTS ix_module_src  ON module(source);
CREATE INDEX IF NOT EXISTS ix_module_abbrev ON module(abbrev);

-- Per-module discovered versification: module -> book -> [verse counts]
CREATE TABLE IF NOT EXISTS versification (
    module_id TEXT NOT NULL,
    book      TEXT NOT NULL,
    chapters  INTEGER NOT NULL,
    PRIMARY KEY (module_id, book)
);

-- ------------------------------------------------------------------ units --
-- One row per addressable unit.  For a Bible that is a verse; for a lexicon an
-- article; for a devotional a date; for a book a section.  `key` is the
-- milestone used for link-set synchronisation.
-- rowid is used as the external-content key for unit_fts, so it must not be
-- WITHOUT ROWID.
CREATE TABLE IF NOT EXISTS unit (
    module_id  TEXT NOT NULL,
    key        TEXT NOT NULL,          -- 'Gen.1.1' | 'H0430' | '1.15' | 's3'
    ord        INTEGER NOT NULL,       -- sort/sequence within the module
    book       TEXT,                   -- convenience for bibles
    chapter    INTEGER,
    verse      INTEGER,
    ref_label  TEXT NOT NULL,          -- display label
    title      TEXT,                   -- heading / headword / article title
    text       TEXT NOT NULL,          -- rendered plain text (searchable)
    markup     TEXT,                   -- original markup (OSIS/ThML/HTML)
    char_start INTEGER DEFAULT 0,      -- offset of this unit in the module text
    char_len   INTEGER DEFAULT 0,
    word_count INTEGER DEFAULT 0,
    extra      TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (module_id, key)
);
CREATE INDEX IF NOT EXISTS ix_unit_ord  ON unit(module_id, ord);
CREATE INDEX IF NOT EXISTS ix_unit_bcv  ON unit(module_id, book, chapter, verse);
CREATE INDEX IF NOT EXISTS ix_unit_chap ON unit(module_id, book, chapter);

-- ---------------------------------------------------------------- markers --
-- NON-WORD markers only: Strong's, lemma, morphology, topic.
--
-- Ordinary words are deliberately *not* stored here.  A unit's text is already
-- in `unit.text`, and db.words() recovers exact word ordinals and character
-- offsets from it in microseconds -- so a row per word would triple the database
-- size to hold information that is already present, and would let the index
-- drift out of step with the text it describes.  Proximity operators
-- (WITHIN n WORDS / CHARS) are evaluated against the unit text directly.
--
-- WITHOUT ROWID with the filter columns as the leading primary key: the table
-- *is* the index, so "all markers of this module" and "all units carrying this
-- Strong's" are both primary-key lookups with nothing duplicated.
CREATE TABLE IF NOT EXISTS marker (
    module_id  TEXT NOT NULL,
    kind       TEXT NOT NULL,     -- strongs | lemma | morph | field | topic | sense
    value      TEXT NOT NULL,     -- H0430, the lemma, the topic key
    unit_key   TEXT NOT NULL,
    pos        INTEGER,           -- word ordinal within the unit
    surface    TEXT,              -- the surface form, when one applies
    PRIMARY KEY (module_id, kind, value, unit_key, pos)
) WITHOUT ROWID;
-- The primary key leads with module_id, so a lookup by Strong's number alone
-- ("where does H0430 occur?") had no usable index and scanned the whole table.
-- That made a single word-study panel take seconds and was the whole cost of
-- building a verse's word list.  This is the index that query needs.
CREATE INDEX IF NOT EXISTS ix_marker_kindval ON marker(kind, value);

-- Strong's -> lemma word list, and lemma -> Strong's, built from imported text.
CREATE TABLE IF NOT EXISTS strongs (
    strongs   TEXT PRIMARY KEY,         -- H0430
    word      TEXT,                     -- surface form as printed
    lemma     TEXT,                     -- underlying form
    count     INTEGER DEFAULT 0,
    modules   TEXT NOT NULL DEFAULT '[]'
);

-- ------------------------------------------------------------------- FTS --
-- A self-contained FTS5 table rather than an external-content or contentless
-- one: external content goes out of sync (and can report "database disk image
-- is malformed") if an import is interrupted, and a contentless table cannot be
-- DELETEd from at all, which would make "remove this module" impossible.
-- The duplication costs a few MB per Bible and buys a delete that always works.
-- `tokenchars` joins the apostrophe into the token instead of splitting on it,
-- which is what `db.words` does.  Its wildcard rules give it
-- away: `lord*` finds "lord's" but `lord?` does not, and the only way both can
-- be true of a six-character token is that the apostrophe is *part of the word*.
-- So a bare `lord` does not match "lord's" there, and it did here -- FTS5 was
-- treating the apostrophe as a separator, so a search for *faith* returned units
-- whose only match was "Faith's".  Roughly 95,000 units hold a straight
-- apostrophe and 33,000 a curly one, so this is not a rare corner; both are
-- listed, and the quoting is FTS5's own doubled-quote escape for a quote
-- character.  Changing this changes result counts, deliberately:
--   python3 tools/rebuild_fts.py --repair
CREATE VIRTUAL TABLE IF NOT EXISTS unit_fts USING fts5(
    module_id UNINDEXED,
    unit_key  UNINDEXED,
    title,
    text,
    tokenize="unicode61 remove_diacritics 2"
);

-- ------------------------------------------------------------- references --
-- Cross-reference pairs harvested from OSIS <reference> and e-Sword scripref.
CREATE TABLE IF NOT EXISTS xref (
    module_id TEXT NOT NULL,
    from_key  TEXT NOT NULL,
    to_key    TEXT NOT NULL,
    kind      TEXT NOT NULL DEFAULT 'ref',  -- ref | parallel | person | place
    PRIMARY KEY (module_id, from_key, to_key, kind)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_xref_to ON xref(to_key, module_id);

-- ------------------------------------------------------------- workspace --
-- Panes hold a milestone cursor, never a pixel offset: that is what lets two
-- resources with intersecting index types stay synchronised.
CREATE TABLE IF NOT EXISTS layout (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    tiles      TEXT NOT NULL DEFAULT '[]',   -- JSON tile arrangement
    is_current INTEGER DEFAULT 0,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS pane (
    id          TEXT PRIMARY KEY,
    layout_id   TEXT,
    tile_id     TEXT,
    module_id   TEXT,
    link_set    TEXT,               -- 'A'..'F' or NULL
    follow_only INTEGER DEFAULT 0,
    follow_active INTEGER DEFAULT 0,
    text_size   INTEGER DEFAULT 100,
    cursor      TEXT NOT NULL DEFAULT '{}',  -- JSON milestone cursor
    view        TEXT NOT NULL DEFAULT 'normal',  -- normal | headings | clean | verses
    options     TEXT NOT NULL DEFAULT '{}',     -- per-panel visual filters
    is_focus    INTEGER DEFAULT 0
);

-- ------------------------------------------------------------ user state --
CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Named Morph Query documents belong to this library, not to one browser's
-- local storage, so they remain available after clearing browser data.
CREATE TABLE IF NOT EXISTS saved_morph_query (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    query_json  TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_saved_morph_updated ON saved_morph_query(updated_at DESC);

CREATE TABLE IF NOT EXISTS highlight (
    id         TEXT PRIMARY KEY,
    module_id  TEXT,
    unit_key   TEXT NOT NULL,
    quote      TEXT NOT NULL,
    color      TEXT DEFAULT 'yellow',
    note       TEXT,
    label      TEXT DEFAULT '',
    created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_hl_quote ON highlight(quote);

CREATE TABLE IF NOT EXISTS srs_card (
    id            TEXT PRIMARY KEY,
    ref           TEXT NOT NULL,
    module_id     TEXT,
    unit_key      TEXT,
    ease          REAL DEFAULT 2.5,
    interval_days INTEGER DEFAULT 0,
    due           TEXT NOT NULL,
    reps          INTEGER DEFAULT 0,
    lapses        INTEGER DEFAULT 0,
    created_at    REAL,
    last_reviewed REAL
);
CREATE INDEX IF NOT EXISTS ix_srs_due ON srs_card(due);

-- ------------------------------------------------------------------ sync --
-- Annotation sync (docs/sync.md).  `sync_meta` is the local memory of what was
-- last pushed or pulled for each record: the revision, the device that wrote
-- it, the hybrid logical clock stamp, and the hash of the payload that stamp
-- describes.  Without it a device cannot tell "I changed this" from "the other
-- device changed this", which is the whole question a merge asks.
--
-- `sync_tombstone` exists because notes, highlights, collections and templates
-- are deleted outright.  A delete that is not recorded reappears on the next
-- sync from any device that was not watching.
CREATE TABLE IF NOT EXISTS sync_meta (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    rev        INTEGER NOT NULL DEFAULT 1,
    dev        TEXT NOT NULL,
    ctr        INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0,
    hash       TEXT,
    base       TEXT
);
CREATE INDEX IF NOT EXISTS ix_sync_meta_kind ON sync_meta(kind);

CREATE TABLE IF NOT EXISTS sync_tombstone (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    deleted_at REAL NOT NULL,
    rev        INTEGER NOT NULL DEFAULT 1,
    dev        TEXT NOT NULL DEFAULT '',
    ctr       INTEGER NOT NULL DEFAULT 0
);

-- ----------------------------------------------------------------- notes --
-- Notes, journal entries, prayer lists and sermon preparation are the same
-- object with a different intent, so they are one table with a `kind` rather
-- than four tables that would drift apart.  A note may be anchored to a verse
-- (module_id + unit_key) or stand alone, which is what lets a journal entry sit
-- beside a note taken on John 3:16.
CREATE TABLE IF NOT EXISTS note (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL DEFAULT 'note',  -- note|journal|sermon|prayer
    title      TEXT,
    body       TEXT,
    module_id  TEXT,
    unit_key   TEXT,
    ref_label  TEXT,
    tags       TEXT,                          -- JSON array
    meta       TEXT,                          -- JSON object (sermon outline, ...)
    created_at REAL,
    updated_at REAL
);
CREATE INDEX IF NOT EXISTS ix_note_kind ON note(kind, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_note_anchor ON note(module_id, unit_key);

-- ------------------------------------------------- collections of resources
-- A named set of modules to search and open together.  Search already scopes to
-- a list of module ids; this just lets that list have a name and persist.
CREATE TABLE IF NOT EXISTS collection (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    note       TEXT,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS collection_item (
    collection_id TEXT NOT NULL,
    module_id     TEXT NOT NULL,
    position      INTEGER DEFAULT 0,
    added_at      REAL,
    PRIMARY KEY (collection_id, module_id)
);
CREATE INDEX IF NOT EXISTS ix_coll_item ON collection_item(collection_id);

-- ------------------------------------------------------- passage lists
-- A saved list of references, read side by side.  unit_key is module-specific
-- ("John 3:16" in one module, "John.3.16" in another), so the module it was
-- taken from is kept alongside; ref_label is what is shown.
CREATE TABLE IF NOT EXISTS passage_list (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    note       TEXT,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS passage_item (
    id         TEXT PRIMARY KEY,
    list_id    TEXT NOT NULL,
    unit_key   TEXT NOT NULL,
    ref_label  TEXT,
    module_id  TEXT,
    position   INTEGER DEFAULT 0,
    added_at   REAL
);
CREATE INDEX IF NOT EXISTS ix_passage_item ON passage_item(list_id, position);

-- ------------------------------------------------------ search templates
CREATE TABLE IF NOT EXISTS search_template (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    query      TEXT NOT NULL,
    options    TEXT,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_note_day ON note(kind, created_at);

-- ------------------------------------------------------------- word lists ---
-- Every occurrence of a term, kept.  A search tells you where a word is now and
-- is gone by the time you have read the third result; a word list is the answer
-- you keep.  The occurrences themselves are recomputed from the search engine
-- rather than stored, so a word list cannot drift out of step with the library:
-- this table is the list and its query, and `word_list_item` is the user's own
-- ordering and notes on top of it.
CREATE TABLE IF NOT EXISTS word_list (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    note       TEXT,
    query      TEXT NOT NULL DEFAULT '',   -- the search that fills it
    kind       TEXT NOT NULL DEFAULT 'term',  -- term | strongs | morph | lemma
    options    TEXT NOT NULL DEFAULT '{}',
    created_at REAL,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS word_list_item (
    id         TEXT PRIMARY KEY,
    list_id    TEXT NOT NULL,
    term       TEXT NOT NULL,       -- the word, Strong's number or code
    surface    TEXT,                -- as printed here, when it differs
    module_id  TEXT,
    unit_key   TEXT,
    ref_label  TEXT,
    book       TEXT,
    chapter    INTEGER,
    verse      INTEGER,
    pos        INTEGER DEFAULT 0,
    gloss      TEXT,
    note       TEXT,
    added_at   REAL
);
CREATE INDEX IF NOT EXISTS ix_wordlist_item ON word_list_item(list_id, pos);
CREATE INDEX IF NOT EXISTS ix_wordlist_term ON word_list_item(list_id, term);

-- --------------------------------------------------------------- outlines ---
-- A Bible outline: the section headings of a chapter, and what they cover.
--
-- The app used to answer every request for an outline with an honest "there is
-- none installed", which was true and useless.  Outlines are editorial, so they
-- cannot be derived from the text; they have to come from somewhere.  This table
-- is where a public-domain one lands, keyed by book and chapter, with `path` as
-- a slash-separated ordinal path ("3.1.2" is the second sub-point of the first
-- point of the third section) so a parent and its children stay adjacent however
-- deep the nesting goes.
CREATE TABLE IF NOT EXISTS outline_node (
    id         TEXT PRIMARY KEY,
    source     TEXT NOT NULL,       -- 'jfb1871', or a module id
    book       TEXT NOT NULL,
    chapter    INTEGER NOT NULL,
    path       TEXT NOT NULL,
    depth      INTEGER NOT NULL DEFAULT 0,
    title      TEXT NOT NULL,
    refs       TEXT,                -- what it covers, e.g. "Ge 1:1-5"
    ord        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_outline_bc ON outline_node(source, book, chapter);
CREATE INDEX IF NOT EXISTS ix_outline_book ON outline_node(source, book);

-- -------------------------------------------------------------- workflows ---
-- A saved arrangement of panes *with a sequence*: a study flow rather than a
-- layout.  A layout says "Bible on the left, notes on the right"; a workflow says
-- "read this, then look up this, then open this, and stop here".
--
-- The steps are stored as rows rather than a JSON blob so a step can be edited
-- without rewriting the whole flow, and so the run log can point at one.
CREATE TABLE IF NOT EXISTS workflow (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    note       TEXT,
    ref        TEXT,                -- the passage it starts from
    layout_id  TEXT,
    created_at REAL,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS workflow_step (
    id          TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    kind        TEXT NOT NULL DEFAULT 'open',  -- open | search | outline | word
    module_id   TEXT,
    slot        TEXT,               -- placement slot, when the step picks by kind
    cursor      TEXT NOT NULL DEFAULT '{}',
    query       TEXT,               -- for a search step
    link_set    TEXT,
    text_size   INTEGER DEFAULT 100,
    options     TEXT NOT NULL DEFAULT '{}',
    note        TEXT
);
CREATE INDEX IF NOT EXISTS ix_wf_step ON workflow_step(workflow_id, position);

-- ------------------------------------------------------------- citations ---
-- What the user has told us about a work, so that citations can be correct.
--
-- Almost none of this arrives with the module: 246 installed resources carry an
-- author for 18 of them and a year for 13, and no publisher at all, because
-- CrossWire strips Author/Publisher/Date from its .conf files.  A citation
-- engine cannot invent those, so the fields the user fills in live here and
-- override whatever the catalogue said.
--
-- Values are stored per field rather than as one blob so that filling in a
-- publisher cannot clobber an author, and so that "unknown" stays unknown: a
-- missing row means the field is still missing, which is a different and more
-- honest thing than an empty string.
CREATE TABLE IF NOT EXISTS citation_meta (
    module_id  TEXT NOT NULL,
    field      TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_at REAL,
    PRIMARY KEY (module_id, field)
);

-- ---------------------------------------------------------------- store ---
CREATE TABLE IF NOT EXISTS repo (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    vendor      TEXT,
    home        TEXT,
    kind        TEXT,          -- catalog | files | web
    enabled     INTEGER DEFAULT 1,
    priority    INTEGER DEFAULT 0,
    last_sync   REAL,
    item_count  INTEGER DEFAULT 0,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS store_item (
    repo_id      TEXT NOT NULL,
    item_id      TEXT NOT NULL,     -- unique within repo
    title        TEXT NOT NULL,
    type         TEXT NOT NULL,
    subject      TEXT NOT NULL DEFAULT '[]',
    lang         TEXT,
    lang_name    TEXT,
    license      TEXT,
    rights       TEXT,
    version      TEXT,
    author       TEXT,
    year         TEXT,
    year_from    INTEGER,
    year_to      INTEGER,
    description  TEXT,
    download_url TEXT,
    page_url     TEXT,
    format       TEXT,
    size_bytes   INTEGER,
    checksum     TEXT,
    module_id    TEXT,              -- set once installed
    extra        TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (repo_id, item_id)
);
CREATE INDEX IF NOT EXISTS ix_item_type  ON store_item(type);
CREATE INDEX IF NOT EXISTS ix_item_lang  ON store_item(lang);
CREATE INDEX IF NOT EXISTS ix_item_mod   ON store_item(module_id);

-- ------------------------------------------------------------------ apis --
CREATE TABLE IF NOT EXISTS api (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    vendor      TEXT,
    category    TEXT,
    base_url    TEXT,
    doc_url     TEXT,
    site_url    TEXT,
    key_required INTEGER DEFAULT 0,
    auth        TEXT,            -- none | header | query | bearer | basic
    key_name    TEXT,
    rate_limit  TEXT,
    terms_url   TEXT,
    license     TEXT,
    notes       TEXT,
    enabled     INTEGER DEFAULT 0,
    position    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS api_key (
    api_id   TEXT PRIMARY KEY,
    value    TEXT,
    set_at   REAL
);

CREATE TABLE IF NOT EXISTS api_cache (
    api_id  TEXT NOT NULL,
    kind    TEXT NOT NULL,
    key     TEXT NOT NULL,
    payload TEXT NOT NULL,
    fetched REAL NOT NULL,
    PRIMARY KEY (api_id, kind, key)
);

-- --------------------------------------------------------------- backups ---
CREATE TABLE IF NOT EXISTS transfer (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,   -- install | remove | import
    repo_id    TEXT,
    item_id    TEXT,
    title      TEXT,
    status     TEXT NOT NULL,   -- running | ok | error
    message    TEXT,
    started    REAL,
    finished   REAL,
    log        TEXT
);

-- --------------------------------------------------------------- history --
CREATE TABLE IF NOT EXISTS history (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    at       REAL,
    kind     TEXT,
    text     TEXT,
    payload  TEXT
);
CREATE INDEX IF NOT EXISTS ix_history_at ON history(at DESC);

-- --------------------------------------------------------------- ai usage --
-- One row per AI call, so a reader can see what cloud use has been.  Tokens are
-- best-effort: a provider that does not report them writes 0 and the call is
-- still counted, because "three calls, tokens unknown" is truer than no row at
-- all.  `ok` is 0 for a call that failed after being sent, which is exactly the
-- case a reader most wants to see when a bill does not match their impression.
CREATE TABLE IF NOT EXISTS ai_usage (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    at                REAL,
    provider          TEXT,
    model             TEXT,
    kind              TEXT,
    prompt_tokens     INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens      INTEGER DEFAULT 0,
    ok                INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_ai_usage_at ON ai_usage(at DESC);
CREATE INDEX IF NOT EXISTS ix_ai_usage_provider ON ai_usage(provider, at DESC);

-- --------------------------------------------------------------- AI chats --
-- A conversation with the assistant, kept so that it can be picked up again.
-- The turns are rows rather than one JSON blob: a conversation grows, and the
-- turn being read is usually the last one, so a row per turn is both smaller
-- to write and easier to read back.
--
-- The citations of a turn are kept with it as JSON, because they are the
-- record of where the answer came from and they belong to that answer --
-- losing them would leave a claim the reader cannot check.
CREATE TABLE IF NOT EXISTS ai_chat (
    id         TEXT PRIMARY KEY,
    title      TEXT,
    created_at REAL,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS ai_chat_turn (
    chat_id  TEXT NOT NULL,
    ord      INTEGER NOT NULL,
    role     TEXT NOT NULL,           -- user | assistant
    content  TEXT,
    cites    TEXT,                    -- JSON array of citation records
    PRIMARY KEY (chat_id, ord)
);
CREATE INDEX IF NOT EXISTS ix_ai_chat_updated ON ai_chat(updated_at DESC);

-- ------------------------------------------------------------------- tags
-- A tag is a named category the reader puts things into, and a thing can be
-- in more than one: a passage can be "grace", "Romans" and "sermon series" at
-- the same time.  The old answer was one label per highlight, which meant a
-- passage could only be in one place, and a second label meant a second
-- highlight.
--
-- An item is a verse or any other unit.  A verse is stored the same way a
-- highlight's verse is -- by book, chapter and verse -- so a tag follows the
-- passage from one translation to the next, which is the whole point of
-- tagging it rather than highlighting it.
CREATE TABLE IF NOT EXISTS tag (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    color      TEXT DEFAULT '',
    created_at REAL
);
CREATE TABLE IF NOT EXISTS tag_item (
    id         TEXT PRIMARY KEY,
    tag_id     TEXT NOT NULL,
    kind       TEXT NOT NULL,          -- verse | unit
    module_id  TEXT,
    unit_key   TEXT,
    book       TEXT,
    chapter    INTEGER,
    verse      INTEGER,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_tag_item_tag ON tag_item(tag_id);
CREATE INDEX IF NOT EXISTS ix_tag_item_verse ON tag_item(book, chapter, verse);
"""


def connect() -> sqlite3.Connection:
    """Per-thread connection.  The server is threaded, so the connection must
    be thread-local or SQLite will complain."""
    conn = getattr(_local, "conn", None)
    p = db_path()
    if conn is not None and getattr(_local, "path", None) == str(p):
        return conn
    if conn is not None:
        conn.close()
    conn = sqlite3.connect(str(p), timeout=120, check_same_thread=False)
    # Set this explicitly on every thread-local connection.  `timeout` already
    # configures it, but the PRAGMA makes the intended lock-wait policy clear
    # and protects against later connection configuration changes.
    conn.execute("PRAGMA busy_timeout=120000")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    _run_migrations(conn)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_item_year ON store_item(year_from)"
    )
    conn.commit()
    _local.conn = conn
    _local.path = str(p)
    return conn


def maybe_checkpoint(conn: sqlite3.Connection | None = None,
                    *, truncate: bool = False) -> int:
    """Fold the write-ahead log back into the database, if it has grown.

    `wal_autocheckpoint` only fires *after* a commit that pushes the log past
    its threshold, and it silently skips when a reader is mid-transaction --
    retrying on the next commit.  A bulk import is one enormous transaction, so
    the log jumped from a few megabytes to 156 MB in a single step and then sat
    there, because the import was the last thing that wrote.  Nothing was
    corrupt and nothing was locked; there was simply no further commit to
    trigger the retry.

    On a database this size that matters: every read then has to consult a
    156 MB log before the main file.  Cheap to fix, so it is fixed rather than
    left as a mystery someone inherits.
    """
    c = conn or connect()
    try:
        mode = "TRUNCATE" if truncate else "PASSIVE"
        row = c.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
        # (busy, log pages, checkpointed pages); busy != 0 means a reader held
        # it off this time, which is fine -- the next write will try again.
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 1


def init() -> sqlite3.Connection:
    conn = connect()
    _run_migrations(conn)
    return conn


_ADDED_COLUMNS = {
    "module": [
        ("heading_count", "INTEGER DEFAULT 0"),
        ("verified", "INTEGER DEFAULT 0"),
        ("error", "TEXT"),
        ("priority", "INTEGER DEFAULT 0"),
        ("favorite", "INTEGER DEFAULT 0"),
        ("v11n_source", "TEXT"),
    ],
    "unit": [
        ("char_start", "INTEGER DEFAULT 0"),
        ("char_len", "INTEGER DEFAULT 0"),
        ("word_count", "INTEGER DEFAULT 0"),
    ],
    "marker": [
        ("span_start", "INTEGER DEFAULT 0"),
        ("span_end", "INTEGER DEFAULT 1000"),
    ],
    "highlight": [
        ("updated_at", "REAL"),
        ("label", "TEXT DEFAULT ''"),
        # The canonical place of a highlighted verse.  A unit key belongs to
        # the module it came from, and the same verse is "John.3.16" in one
        # Bible and "John 3:16" in another, so a highlight filed against the
        # key cannot follow the verse to a different translation.  These three
        # are the verse itself, and they are the same everywhere.
        ("book", "TEXT"),
        ("chapter", "INTEGER"),
        ("verse", "INTEGER"),
    ],
    "store_item": [
        ("year_from", "INTEGER"),
        ("year_to", "INTEGER"),
        ("checksum", "TEXT"),
    ],
    "repo": [
        ("item_count", "INTEGER DEFAULT 0"),
    ],
    "module": [
        ("attribution", "TEXT"),
    ],
}


def _migrate_to_2(conn: sqlite3.Connection) -> None:
    for table, cols in _ADDED_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    _backfill_highlight_refs(conn)


def _migrate_to_3(conn: sqlite3.Connection) -> None:
    for table, cols in _ADDED_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


_MIGRATIONS = {2: _migrate_to_2, 3: _migrate_to_3}


def _run_migrations(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            version = 1
            conn.execute("INSERT INTO meta(key,value) VALUES('schema_version',?)",
                         (str(version),))
            conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES"
                         "('created_at',?)", (str(time.time()),))
        else:
            try:
                version = int(row["value"])
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"invalid database schema version: {row['value']!r}") from exc
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"database schema version {version} is newer than supported "
                f"version {SCHEMA_VERSION}")
        while version < SCHEMA_VERSION:
            target = version + 1
            migration = _MIGRATIONS.get(target)
            if migration is None:
                raise RuntimeError(
                    f"missing database migration {version} -> {target}")
            migration(conn)
            conn.execute("UPDATE meta SET value=? WHERE key='schema_version'",
                         (str(target),))
            version = target
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _backfill_highlight_refs(conn: sqlite3.Connection) -> None:
    """Give the older highlights the verse they are on.

    A highlight made before this existed knows only the module and the unit
    key, and the key is module-specific -- the same verse is "John.3.16" in
    one Bible and "John 3:16" in another -- so a highlight could not follow
    its verse to a different translation.  The unit table knows the real
    place, so the place is copied across, once, for the highlights that
    already exist.

    The work is done in one pass over the units that are actually verses
    rather than a query per highlight, because a library with a few thousand
    highlights and a million units would otherwise take minutes.
    """
    if conn.execute("SELECT value FROM meta WHERE key="
                    "'highlight_refs_backfilled'").fetchone():
        return
    rows = conn.execute(
        "SELECT h.id, u.book, u.chapter, u.verse FROM highlight h "
        "JOIN unit u ON u.module_id=h.module_id AND u.key=h.unit_key "
        "WHERE h.book IS NULL AND u.book IS NOT NULL "
        "AND u.chapter IS NOT NULL AND u.verse IS NOT NULL").fetchall()
    for r in rows:
        conn.execute(
            "UPDATE highlight SET book=?, chapter=?, verse=? WHERE id=?",
            (r["book"], r["chapter"], r["verse"], r["id"]))
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES"
                 "('highlight_refs_backfilled','1')")


def get_setting(key: str, default=None):
    conn = connect()
    row = conn.execute("SELECT value FROM setting WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return row["value"]


def set_setting(key: str, value) -> None:
    conn = connect()
    conn.execute("INSERT INTO setting(key,value) VALUES(?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, json.dumps(value)))
    conn.commit()


def log_history(kind: str, text: str, payload=None) -> None:
    conn = connect()
    conn.execute("INSERT INTO history(at,kind,text,payload) VALUES(?,?,?,?)",
                 (time.time(), kind, text, json.dumps(payload or {})))
    conn.commit()


# --------------------------------------------------------------------------
# Tokenisation -- the search engine's product is the token stream
# --------------------------------------------------------------------------

#: Combining marks belong to the letter they sit on.
#:
#: Python's `\w` excludes them -- `str.isalnum()` is False for a vowel point --
#: so `[^\W\d_]+` cut a pointed Hebrew word into single letters.  That is not a
#: cosmetic problem: `fold()` reduces `בָּרָ֣א` to `ברא` correctly, the FTS index
#: finds it correctly, and then the exact pass compared the term `ברא` against
#: the tokens `ב`, `ר`, `א` and found nothing.  A search for one Hebrew word
#: across the whole Hebrew Bible returned zero hits while the index plainly
#: held them.
#:
#: The ranges cover what this app actually indexes: Latin with combining
#: diacritics, Greek (monotonic and polytonic), Hebrew points, and Arabic
#: harakat.  A maqaf or a hyphen is still a boundary, which is right: OSHB marks
#: each side of a maqaf separately.
_COMBINING = (
    "̀-ͯ҃-҉"
    "֑-ׇֽֿׁׂׅׄ"
    "ً-ٰٟۖ-ۜ"
    "ัิ-ฺ᪰-᫿᷀-᷿"
    "⃐-⃰︠-︯"
    "ัิ-ฺ"
)
#: One word: a letter, then any run of further letters and combining marks,
#: with an apostrophe allowed inside so that "God's" stays one token.
#:
#: The continuation is an *alternation* rather than one character class, and it
#: has to be.  Folding the mark ranges into the class that starts with
#: `[^\W\d_]` does not work, because that class is a negated set containing
#: `\W` -- and `\W` matches every vowel point, so the marks were excluded by the
#: very part of the class meant to admit letters.  Hebrew stayed split into
#: single letters however many ranges were added.
_MARK = "[" + _COMBINING + "]"
_WORD = (r"[^\W\d_](?:[^\W\d_]|" + _MARK + r")*"
         r"(?:['’\u2019][^\W\d_](?:[^\W\d_]|" + _MARK + r")*)*")
_TOKEN_RE = re.compile(_WORD + r"|\d+", re.UNICODE)

#: The ordinary English function words.
#:
#: They are not worth matching on: every text has them, so they carry no
#: information about what a passage is *about*, and a question made of them
#: matches everything and therefore nothing.  This lives beside the tokenizer
#: because that is what uses it -- the search engine, the reader's own
#: material, and the fragment matcher all fold the same words the same way.
STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "so", "as",
    "at", "by", "for", "from", "in", "into", "of", "on", "to", "with",
    "without", "within", "is", "are", "was", "were", "be", "been", "being",
    "am", "do", "does", "did", "doing", "have", "has", "had", "having",
    "can", "could", "shall", "should", "will", "would", "may", "might",
    "must", "what", "which", "who", "whom", "whose", "how", "when", "where",
    "why", "that", "this", "these", "those", "it", "its", "there", "here",
    "not", "no", "yes", "any", "some", "each", "every", "all", "both",
    "more", "most", "much", "many", "other", "another", "such", "own",
}

# Words whose forms are not usefully reduced.  Over-stemming English prose is
# the classic complaint about "match all forms"; these keep the worst offenders
# out of it.
_NO_STEM = {
    "this", "his", "her", "its", "their", "ours", "yours", "was", "were", "been",
    "being", "has", "had", "having", "does", "did", "doing", "is", "are", "am",
    "be", "as", "us", "them", "him", "who", "whom", "whose", "which", "what",
    "shall", "should", "will", "would", "can", "could", "may", "might", "must",
    "he", "she", "they", "we", "you", "i", "it", "not", "no", "nor", "but", "and",
    "or", "if", "then", "than", "that", "so", "such", "there", "here", "when",
    "where", "while", "unto", "upon",
}


def words(text: str) -> list[tuple[str, int, int]]:
    """Token stream: (word, char_start, char_end).

    Punctuation is discarded but its position is retained in the offsets, which
    is what makes `WITHIN n WORDS` and `WITHIN n CHARS` the same engine with two
    metrics.  This is the single most important function in the search stack.
    """
    out = []
    for m in _TOKEN_RE.finditer(text or ""):
        w = m.group(0)
        # Treat a trailing apostrophe-s as part of the word ("God's").
        out.append((w, m.start(), m.end()))
    return out


def stem(word: str) -> str:
    """A conservative, suffix-stripping stemmer.

    Deliberately simple and deliberately conservative: stemming that matches
    words by their perceived stem can catch words outside the original
    language, so we bias towards under-stemming rather than over-stemming.
    """
    w = word.lower()
    if len(w) <= 3 or w in _NO_STEM:
        return w
    if w.endswith("'s") or w.endswith("\u2019s"):
        w = w[:-2]
    if len(w) <= 3:
        return w
    # plural / 3rd person
    #
    # Every branch below recurses instead of returning its base directly.  The
    # reason is convergence: a query word and its plural have to arrive at the
    # *same* stem, or the query cannot find the word it was looking for.
    #
    # Returning early used to break that.  "loves" hit the plural rule and came
    # back as "love", while "love" fell all the way through to the silent-e rule
    # at the bottom and came back as "lov" -- two stems for one word, so a search
    # for "love" could not find "loves".  Same for "lovely" ("love") against
    # "love" ("lov"), and "largest" ("larg") against "large" ("larg", by luck).
    # Recursing lets the de-inflected base meet the remaining rules, which is
    # what makes stem() idempotent.  It terminates because each step is shorter
    # and len <= 3 is a base case.
    if w.endswith("ies") and len(w) > 4:
        return stem(w[:-3] + "y")
    if w.endswith("sses") or w.endswith("shes") or w.endswith("ches") or w.endswith("xes"):
        return stem(w[:-2])
    if w.endswith("ss"):
        return w
    if w.endswith("s") and not w.endswith("us") and not w.endswith("is"):
        return stem(w[:-1])
    # comparatives / adverbs
    for suf in ("ingly", "edly"):
        if w.endswith(suf) and len(w) > len(suf) + 3:
            return stem(w[:-len(suf)])
    if w.endswith("ing") and len(w) > 5:
        base = w[:-3]
        if len(base) > 2 and base[-1] == base[-2] and base[-1] not in "lsz":
            base = base[:-1]
        if base.endswith(("bl", "at", "iz", "iv", "us", "ur", "os", "io", "ia")):
            base += "e"
        return stem(base)
    if w.endswith("ied") and len(w) > 4:
        return stem(w[:-3] + "y")
    if w.endswith("ed") and len(w) > 4:
        base = w[:-2]
        if len(base) > 2 and base[-1] == base[-2] and base[-1] not in "lsz":
            base = base[:-1]
        return stem(base)
    if w.endswith("ly") and len(w) > 4:
        return stem(w[:-2])
    if w.endswith("er") and len(w) > 5:
        return stem(w[:-2])
    if w.endswith("est") and len(w) > 6:
        return stem(w[:-3])
    if w.endswith("ness") and len(w) > 6:
        return stem(w[:-4])
    if w.endswith("ment") and len(w) > 7:
        return stem(w[:-4])
    if w.endswith("tion") and len(w) > 6:
        return stem(w[:-3])
    # A final silent "e" is dropped on both sides of the comparison, so that
    # "love" and "loved" meet at "lov".  Without this the stemmer is *too*
    # conservative in the commonest case there is: love/loved, move/moved,
    # believe/believed, serve/served.  The length guard keeps short words whole.
    if len(w) > 3 and w.endswith("e") and w[-2] not in "aeiou":
        return w[:-1]
    return w


#: Typographic characters folded to their ASCII equivalents before anything
#: else.  Applied as a translate table rather than seven passes of ``str.replace``
#: -- see ``fold``.
_FOLD_PUNCT = str.maketrans({
    "\u2019": "'", "\u02bc": "'", "\u2018": "'",
    "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-",
})


def fold(word: str) -> str:
    """Case-fold + strip diacritics + fold orthographic variants.

    This is called for every token of every candidate unit, and a library of
    commentaries holds tens of millions of them, so it has to be cheap in a way
    that is not obvious from the size of the function:

    * ``unicodedata`` is imported at module scope.  It used to be imported
      *inside* this function, twice per call -- once to normalise and once to
      test each character -- which is millions of ``__import__`` calls on the
      hot path.
    * The punctuation folding is one ``str.translate`` over a table, not seven
      sequential ``str.replace`` calls, each of which builds a new string.
    * Pure-ASCII words skip normalisation entirely.  Nearly every token in an
      English Bible is ASCII with no accents, and a str.isascii() test is a
      single flag check against a full pass over the string plus a generator.
    * The result is memoised.  The vocabulary behind tens of millions of tokens
      is a few hundred thousand distinct forms, so the cache hit rate is very
      high and it bounds the cache rather than growing without limit.

    The output is unchanged from the straightforward implementation; the
    self-test asserts that against a reference.
    """
    hit = _FOLD_CACHE.get(word)
    if hit is not None:
        return hit
    w = word.lower().translate(_FOLD_PUNCT)
    if not w.isascii():
        w = "".join(ch for ch in unicodedata.normalize("NFD", w)
                    if not unicodedata.combining(ch))
    if len(_FOLD_CACHE) > 400000:
        _FOLD_CACHE.clear()
    _FOLD_CACHE[word] = w
    return w


import unicodedata  # noqa: E402  -- used by fold() on the search hot path

_FOLD_CACHE: dict[str, str] = {}
_KEY_CACHE: dict[str, str] = {}


def token_key(word: str) -> str:
    """Folded + stemmed form, memoised.

    This is the hottest function in the search path: evaluating one query over a
    library holding commentaries means folding several million words, and the
    vocabulary behind them is only a few thousand distinct forms.  Without the
    cache a plain OR search takes seconds instead of milliseconds.
    """
    hit = _KEY_CACHE.get(word)
    if hit is not None:
        return hit
    v = stem(fold(word))
    if len(_KEY_CACHE) > 200000:
        _KEY_CACHE.clear()
    _KEY_CACHE[word] = v
    return v


def clear_token_cache() -> None:
    _KEY_CACHE.clear()
    _FOLD_CACHE.clear()


#: Bumped whenever the library's words change -- a module installed, re-indexed
#: or removed.  In-process only, because it exists to invalidate in-process
#: caches, and it lives here rather than in the module that would want it so
#: that both the writers (library) and the readers (search) can reach it without
#: an import cycle.
#:
#: The alternative was a time-to-live.  The vocabularies behind the search box's
#: spelling hint take ~4s and ~14s to build, so they were given five-minute and
#: one-hour expiries -- which means the hint rebuilt itself on a keystroke every
#: five minutes, for the whole session, to answer a suggestion of at most six
#: lines.  A library only changes when the reader changes it, so the cache is
#: invalidated by the change instead of by the clock.
GENERATION = 0


def bump_generation() -> int:
    global GENERATION
    GENERATION += 1
    return GENERATION

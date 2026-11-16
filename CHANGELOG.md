# Changelog

## 1.0.0 — out of beta

### Backups, the G-Bible way — one mechanism, .gbz
- Sync and backup are now the same thing. **Settings → Synchronization** has one artefact, `gbible-backup.gbz`, written to the target configured there — a folder on this computer, WebDAV, or Nextcloud — and restored from the same target. The interval worker and the network policy (Wi-Fi only) apply to it as they did to the old v1 sync.
- Restore offers three sources: **From this computer…** (any `.gbz`), **From WebDAV** and **From Nextcloud** (available when configured; they GET the same file sync wrote). Restore is additive: nothing is deleted, nothing is overwritten — identical records are skipped, differing records keep yours; deleted markers in the backup are ignored.
- The `.gbz` carries AI settings, API keys, AI conversations with turns, saved morphological searches, and AI usage history (which restores only onto a machine with no usage history — counters can't be summed without double counting). Modules are not copied by design; G-Bible names the ones it expects so the Store can reinstall them.
- The standalone "Create backup (.gbz)" download button is gone — Sync now is the backup action. The .gbz offline-restore tool (`tools/restore_backup.py`) is unchanged. Sync exports *and* pulls through one code path.
- **The file picker for restore now shows folders + `.gbz` files only** — hidden entries and all non-backup extensions are filtered, server-side.

### First-run tour
- A short guided tour of the top bar shows itself once, on first launch. It can be replayed any time from About G-Bible → "Take the tour".
- New: "Get started in 5 minutes" and "Known issues" docs, linked from the README ([Getting started](docs/GETTING_STARTED.md), [Known issues](docs/KNOWN_ISSUES.md)).
- Still-settling components carry an "Experimental" pill: the Assistant tab, AI providers, Synchronization.
- Unit tests added (parser → span table → render round-trips; database migrations), wired into CI ahead of the seeded self-test and browser smoke. The seeded full self-test is green (174 passed, 0 failed).

### The Words of Christ, rebuilt
- The red-letter feature was removed and rebuilt on the Bibles' own markup — no corpus, no guessed spans, no whole-verse colouring.
- USFM: nested \wj marking now carries red onto the inner \w words themselves (the "one word at a time in red" bug is gone).
- OSIS: `<q who="Jesus">` marks with Strong's words inside it, narration stays plain; milestone-style `<q sID=…/>…<q eID=…/>` (used by the open-bibles KJV) is supported too.
- e-Sword `<red>`/inline red markup renders.
- Uploads of OSIS/USFX and other sniffed formats now flow through the same working parser — not just Store downloads. Re-deriving a module from its own source is one command: `tools/reindex.py`.

### Parsing fixes
- The OSIS importer was silently discarding translator-added text (`<transChange type="added">the son</transChange>`), which gutted Luke 3:23-38 and left the genealogy tool with an empty Adam lineage. Fixed — the whole chain from Jesus to God reads again.
- Unit-test gate now runs before the seeded self-test in CI.

### Reliability and hygiene
- Unbounded process-wide caches in the search engine are now capped (IDF, phrase positions, IDF, headwords, surface keys) — long sessions no longer grow without limit.
- `target/` covered by .gitignore at any depth (rust/target was being flagged as uncommitted material).
- Genealogy: KJV spellings now fold correctly (Salma/Sala → Salmon; Abia → Abijah) — the 1 Chronicles 3 chain resolves.

### Logs
- New **Settings → Logs** view lists every error G-Bible has logged — the server, the sync worker and the renderer. A red **N errors found** pill sits in the top-right header, to the left of the module count, and links straight to the Logs view.
- Errors from the app itself only — browser- and extension-side faults are not logged. Entries are capped, paths normalised, and personal data is never captured.
- **Clear logs** empties the log and hides the pill. **Report this error** files a real GitHub issue on the G-Bible repository with version, source, message and stack. A one-time device authorization on github.com/login/device ties the report to your account — no credentials stored here, no anonymous filings.

### Optional Rust performance core
- Optional PyO3/maturin Rust extension for Unicode tokenization, normalization, conservative stemming, HTML/XML entity decoding, whitespace normalization, positional-index varints, and spelling-distance calculations.
- The Python search, indexing, and markup hot paths use the native code when installed; Python implementations remain as automatic fallbacks.
- Linux/Windows build instructions and a Rust CI build job; `python run.py --rust-status` reports what's active.
- Database schema and resource formats unchanged.

### Interface redesign
_(carried forward from 0.9.8 — included here)_
- Modern, cohesive UI: deep slate surfaces, indigo accent, unified component system
- Consistent view headers across all 23 views
- Keyboard shortcuts (⌘1–⌘5) on main navigation tabs
- Sectioned context menus: Quick Actions, Word & Topic Study, Passage Research,
  Open in Study Panes, Personal Study
- Keyboard accessibility preserved (arrow keys, Home/End, Escape, focus return)

### Parallel Bible reading (milestone 1)
- Translation switcher in each Bible pane — switch translations while preserving
  pane, tile, link set, and reading position

### Saved workspace restoration (milestone 2)
- Restored workspaces sync linked panes to the same passage on load
- Named layout save/restore via the Layouts dialog

### Search reliability (milestone 4)
- Fixed BM25/IDF bugs: corpus stats validated against the unit table
- Search totals no longer truncated across pagination

### Resource installation (milestone 3)
- 15 modules installed through the Store workflow (Bibles, commentary, FactBook,
  lexicons, dictionary, atlas, map, devotional)

### Devotional creator
- New tool under My study that turns any installed Bible or chaptered book into
  a daily devotion: pick the whole Bible, the Old Testament, the New Testament
  or an individual book or chapter, pick a start and finish date (a month
  dropdown fills the finish date), and G-Bible builds the day-by-day portions.
- Bibles split by chapter, never mid-chapter, balanced by word count; other
  texts split at sentence boundaries, never mid-sentence.
- The created devotion renders real chapter headings (e.g. Genesis 1 on its own
  line) and preserves line breaks, so the daily entry reads as headed sections
- The result is a real devotional module (title, reference and full text per
  day, MM.DD keys), so it appears on the Today screen and opens in panes like
  any other devotion; created devotions can be reopened or deleted in the tool
- Created devotions open in any pane with the day's entry, and can be jumped
  to any date with a date picker and day arrows

### Reader
- The raw `MM.DD` key box in devotional panes is gone; devotional panes are
  built from the same toolbar as Bible panes — only the picker is a month
  calendar (a devotion has no books and chapters).
- Removed the "Through the Bible · day N" ribbon chip from Bible panes, and
  the endpoint and helper behind it
- Read Aloud no longer fails silently when the machine has no speech voices;
  it says so instead
- Yellow highlighter marks had no rule of their own; the default `.hl` fell to a
  dark olive accent that disappears on the dark theme. Added the missing
  `mark.hl-yellow` rule matching the other four colors.
- Notes are linked to their verse across every module that contains it — Bible,
  commentary, devotion — not just the module they were written in.
- Devotional panes render exactly like Bible panes: each copied verse is its
  own `.verse` with a blue superscript number linking to the verse popup, the
  verse text is clickable (selecting just it), word-study on the copied Strong's
  markings works in place, and Read Aloud reads verse by verse, marking each
  as it goes. Chapter boundaries get a rule and their own heading.
- The created devotion now stores each passage's markup span table and verse
  keys verbatim, so Strong's numbers, notes and highlights
  all ride along from the source Bible.
- Devotional panes were rebuilt around the verse reader: one item per verse,
  chapter headings, and the full Bible-pane toolbar (copy, SRS, Mem, Study,
  Passage, Compare, Visual, Read aloud).

### Under the hood
- Database integrity: zero foreign-key violations
- Python compilation, JavaScript syntax, and database migrations all pass

## 0.9.0 — initial public beta

First public beta release of G-Bible: an open-source, offline Bible study application.

- Multi-pane tiled workspace with link sets (A–F) and milestone-intersection linking.
- Real search query language with FTS5, positional index, and BM25 ranking.
- Module browser and installers for SWORD, USFM, USFX, OSIS, e-Sword, EPUB, ThML and plain text.
- Version merging, concordance, topic guide, Topics, Passage, Maps, genealogy, and read-aloud.
- Citations and export (SBL, MLA, APA, Chicago, Turabian, BibTeX, RIS, PDF/RTF/HTML/Markdown/text/CSV).
- Optional read-aloud voice via `.venv` (`tools/install_voice.py`); core uses only the Python standard library.
- Store catalogues for 9 repositories, filtered to freely redistributable material.
- Sync (WebDAV / Nextcloud / local folder), API settings for 47 services, AI assistant and translation providers (opt-in).

See `README.md` for full documentation. Report issues on the project's GitHub page.
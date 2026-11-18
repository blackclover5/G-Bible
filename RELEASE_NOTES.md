# G-Bible — Release Notes

**Version:** 1.0.1
**Date:** 2026-11-17
**Status:** Patch release. Free, open source, MIT; no telemetry.

---

## What this release is

G-Bible is an open-source, offline-first Bible study application. It brings
Scripture, study tools, reference materials, and personal notes together in a
single, customizable workspace — no account, no subscription, no cloud
dependency required.

This is the first release labeled stable: the interface redesign, search
fixes, and Store installation work from 0.9.0/0.9.8 all carry, the Words of
Christ feature was rebuilt on the Bibles' own markup (no guessing), and
the OSIS importer no longer discards translator-added text. The full seeded
self-test passes with zero failures.

## What's new in this release

### Backup and update hardening
- Hardened backup credential handling and encrypted backup operations.
- Added backup security tests and coverage for intermittent Store resources.
- Improved Gutenberg seed retries when resources are temporarily unavailable.
- Updated dependency setup and CI coverage for backup tests.

### Logs
- A red "N errors found" pill in the top-right header opens **Settings → Logs**, listing G-Bible's own errors (server, sync worker, renderer). Only the app's own faults are logged — not the browser, not extensions. Entries are capped, paths normalised, no personal data.
- Each entry can be reported as a pre-filled GitHub issue (you review and submit — nothing is sent without you pressing the button). **Clear logs** empties the list and hides the pill.

### Personal backups, the G-Bible way (.gbz)
- Sync and backup are one mechanism. **Settings → Synchronization** holds a single artefact — `gbible-backup.gbz` — written to the target you select (this computer, WebDAV, Nextcloud) and pulled back from the same place. One button, one file, one restore.
- The `.gbz` carries notes, highlights, plans, tags, layouts, workflows, word lists, citations, reading progress, appearance, sermon material — plus the AI bundle by default (settings, API keys, conversations, saved morphological searches, usage history). Unencrypted, so keep it like a password; sync passwords never travel.
- Restore is additive: nothing is deleted, nothing is overwritten — identical records are skipped, differing records keep yours. Restore offers three sources (this computer / WebDAV / Nextcloud) — the network ones GET the file sync wrote. Usage history is only restored onto a machine with no usage history, because usage counters cannot be summed without double counting.
- Modules are not copied by design; G-Bible tells you which ones the backup expects so the Store can reinstall them.

### Interface redesign (modern, cohesive, navigable)
- Redesigned topbar navigation with keyboard shortcuts (⌘1–⌘5) and grouped
  dropdown menus (Study tools, My study, Library, Settings)
- Consistent view headers across all 23 destination views
- Refined color palette (deep slate surfaces, indigo accent — G-Bible's own
  identity, not a Logos clone)
- Unified component system: buttons, cards, inputs, modals, badges, chips
- Softer borders, better focus states, hover elevations, responsive layout
- Sectioned context menus (Quick Actions, Word & Topic Study, Passage Research,
  Open in Study Panes, Personal Study) — selecting text is now a study entry point
- Keyboard accessibility preserved: arrow keys, Home/End, Escape to close,
  focus return on menu dismissal

### Parallel Bible reading (milestone 1)
- Translation switcher dropdown in each Bible pane — swap translations while
  keeping the same pane, tile, link set, and reading position
- No new pane is created when switching translations; link relationships are preserved

### Saved workspace restoration (milestone 2)
- Restored workspaces bring linked panes into step on load — a link set shows
  the same passage everywhere
- Named layout save/restore: save any workspace as a named layout, reopen it
  later with all open panes, translations, positions, and link sets intact
- Layout dialog lists saved layouts with pane counts, module names, and current indicator

### Search reliability (milestone 4)
- Fixed BM25 ranking bugs: corpus statistics now validated against the actual
  unit table instead of trusting stale metadata
- IDF discrimination restored (rare words score higher than common words)
- Search totals no longer truncated across pagination

### Resource installation (milestone 3)
- 15 modules installed through G-Bible's supported Store workflow:
  - Bibles: WEB, KJV (×3), BSB, German 1912
  - Commentary: Barnes (7,359 entries)
  - FactBook: Nave's Topical Bible (5,322 entries)
  - Lexicons: Abbott-Smith, Strong's Hebrew, BDB glosses
  - Dictionary: Webster 1806
  - Atlas: Jerusalem place data
  - Map: Ortelius Exodus 1624
  - Devotional: Daily Light (366 entries)

### Under the hood
- Database integrity verified: zero foreign-key violations
- Python compilation, JavaScript syntax, and database migrations all pass
- All previously reported interface changes (selection action hub, Passage /
  Exegetical guides, linked-pane sync) confirmed present in source

---

## Test results

Selftest is run each commit against a seeded install of the public-domain
library (Bibles, commentary, lexicons, a dictionary, devotional, map, and
more).

| Result | Passed | Skipped | Failed |
|--------|--------|---------|--------|
| Seeded library (18 modules, this release) | **174** | **28** | **0** |

Skipped checks indicate modules not installed or features unavailable — not
failures.

Skipped tests indicate material not installed — not a defect.

---

## Known limitations

- Not every installed Bible marks Jesus' words (Brenton's LXX, SBLGNT, WLC,
  most OT texts) — those render plainly. Nothing is inferred.
- Sync is opt-in and experimental; folders and WebDAV work today. Encryption
  is deliberately not supported yet.
- The AI Assistant needs your own provider key; without one it produces nothing.
- Some self-test checks require modules not yet installed (morphology-tagged
  texts, apparatus modules).

---

## How to run

```bash
# Start the local server
python3 run.py

# Open http://127.0.0.1:8777 in your browser

# Or run the self-test suite
python3 tools/selftest.py

# Run self-test with full output
python3 tools/selftest.py --full
```

---

## License

G-Bible is open source. See LICENSE. Study modules are downloaded at run time
and carry their own licences — see ATTRIBUTIONS.md.

No study material is bundled except a 52 KB file of public-domain section
headings (Jamieson–Fausset–Brown, 1871).


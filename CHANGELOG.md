# Changelog

## Unreleased — Guides tool buttons & Search auxiliary tools audit

- **Outline export was empty but reported success.** `export_outline_doc()` looked for `headings`/`chapters` while the outline actually returns `sections` (and a chapter *count* for whole books), so the downloaded HTML had no outline at all. Fixed, headings escaped, and the export re-resolves the live reference box instead of a stale tab state.
- **Bible Browser's filter accepted one character only** — every keystroke re-rendered the modal and dropped focus. Focus and caret are now restored after filtering.
- **Reference Scanner links were effectively dead** — blur re-render replaced the result anchors before a click could land; API failures were disguised as "No references found". Now an explicit Scan button, surfaced errors, a request token and no blur handler.
- **Guide tool results are properly actionable.** Outline headings now carry clickable verse chips; duplicate `data-ref` handlers that opened a passage modal then navigated away (leaving stale work) were removed so the document router owns the action once. Sense-search Strong's values are escaped; Names for God now says it is a text filter, not a curated list; the Syntax Search button is honestly labelled "Clause search →".
- **Sentence diagram "Open it" is no longer a stub** and the toolbar button reads the dedicated verse box (`#cl-ref`) instead of the book filter. Diagram export now uses the displayed module and includes the grammatical role.
- **Search auxiliary fixes:** parser probe reports failures instead of emptying the relation list; `prepositional` is hidden without a parser; search help passes the current query and shows operator warnings; gallery/browse failures are surfaced; Smart Search is guarded against overlapping replies; the click-link button reflects a saved link set immediately; clause-search from the verse menu opens the panel visibly.
- Added 3 regression tests; 256 tests pass.

## Unreleased — Research & ministry audit

- **Sermon import sent the whole sermon in a GET URL.** Long or multi-line sermons failed with HTTP 414 and prompts could not accept line breaks. It now uses a proper modal with a textarea and a POST. Also fixed an explicit title deleting a matching line of the manuscript.
- **Two tools were fake.** Confessional documents keyword-searched verse text and presented lexicon headwords as creeds; Catholic daily readings searched for a literal date string in text (the `unit` table has no date column) and returned lexicon entries as "readings". Both now require an actual confessional/Lectionary source and say plainly when none is installed.
- **Popular quotes showed the wrong text and counted the wrong thing.** `unit.key` is not unique across modules, so Greek/Hebrew text appeared under English references; topic-index links were mixed into the "occurrences" count. It now reads the verse from an installed Bible, counts only scripture cross-references, names the source and labels the metric honestly; refs are clickable.
- **Visual copy used an arbitrary module** (often original-language text) and silently dropped ranges. It now honours the requested module, attributes the translation on the image, reports when only the first verse was rendered, and the menu button uses the focused pane's Bible.
- **Bibliography menu** now delegates to the full citation tool (style choice, flagged gaps, all export formats) instead of a lossy duplicate. Invalid styles and unknown module ids are reported rather than returning an empty, reassuring result. GPL is no longer mislabelled as CC BY-SA in citations.
- Sermon documents no longer silently cap at 500 and reject non-sermon ids. Fold-looking headers in report modals are now actually foldable, empty states are shown, result references are links, and the date picker for readings has a real CSS width and no dead Clear button.
- Added 5 regression tests; 253 tests pass.

## Unreleased — Workspace audit

- **Merge was a dead button** — created and wired, never added to the pane toolbar; fixed. Verse right-click could not find the word under the pointer because of a stray character in its regex, so Word Study/Topics/pronunciation disappeared on untagged text; fixed.
- **Guide, Word Study and FactBook panes broke global repaints** — `Reader.repaint()` dereferenced their empty `module_id` and threw, so deleting a highlight or changing a tag left stale text. Module-less panes are now skipped. Fullscreen on such a pane now clones the rendered body instead of showing a blank dialog.
- **Pane focus was never tracked.** Article/map navigation, "Print pane" and fullscreen fell back to the first pane, often rewriting or printing the wrong resource. Tab clicks now set and remember the focused pane, and those actions use it. The active tab also survives a workspace reload.
- **Guide pane references were not saved**, so switching tabs or reloading returned to the old passage; fixed. Toggle buttons showed inverted state under a clean edition; fixed. Find-in-pane ✕ permanently removed the widget so Ctrl+F never reopened it; it now hides and reopens.
- **Linked panes were not persisted** — propagated cursors lived only in memory, so a reload undid them; they are now POSTed, renders are awaited, and date/keyed link sets are restored too. The `follow_only` check was inverted; fixed.
- **QuickStart layouts for Passage Guide, Exegetical Guide and both Word Studies silently dropped their second pane** because module-less panes were filtered out; fixed. Saving a layout against a missing id wrote orphan panes and could leave a partial transaction; now rejected and wrapped. Switching to a missing layout left no current workspace; now rejected. Bootstrap no longer replaces a legitimate one-pane workspace.
- **Soft-deleted modules were still treated as installed** in link sets, parallel groups, top Bible, priority rules, strongs and `library/module`. Removed parallel targets now report an error instead of an empty pane. `read` now says when a reference cannot be parsed or a module has no text for it, instead of silently showing Genesis 1. `bible/chapter` validates installation, book and chapter; `read/around` clamps at the last verse of a chapter.
- **Several actions reported false success** (Close all, Close pane, Clear links, Study layout, highlight save); they now surface API errors. "Reopen last" records every opened module, and the dead duplicate Layouts button was removed. Workflow `text_size`/`link_set` now reach the server.
- Removed dead helpers and stale comments. Added 5 regression tests; 248 tests pass.

## Unreleased — Search audit

- **Four documented search operators were completely broken.** `IN`, `INTERSECTS` and their `NOT` forms called `span()`, which was never defined, so every such query failed with NameError. It now converts a term position into a character range.
- **String booleans and limits were wrong at the API boundary.** `?match_case=false` and `?snippets=false` were silently enabled because `bool("false")` is true; `limit=-1` meant "all but one" or an unbounded scan. Both now use the shared flag/bounded-int helpers, as do notes, clause and media endpoints.
- **Analysis described a different result set** from the one on screen: it re-sent the raw query and all modules instead of the resolved passage scope and translation filter. It now analyses exactly the displayed query and carries a token so an older analysis cannot repaint a newer search.
- **Every result's "send to…" button threw** because it called a bare `sendTo` that only exists as `Search.sendTo`. Fixed, and the labels are escaped before the menu renders them.
- **Sentence-diagram "Export" was hijacked** by the "Open it" handler, which was a no-op. Each button now owns its own handler.
- **Templates, gallery and workflow searches were ignored in Morph** because they inject a query into the main box, which that type never reads. They now switch back to All first.
- **"Showing the first 400 of 5057" had no way to reach the rest.** A "Show N more" control now grows the result window; per-type totals also use the server's real count rather than the page length.
- **Documents results had blank snippets** (read `preview` instead of `body`); Books results opened the module's default location instead of the matched reference; the Maps type filter was a dead control; the click-link button was hidden in seven of eight search types; duplicate "open only this" buttons and false "Saved" toasts were fixed.
- Backend honesty: `notes/list` filtered *after* LIMIT so older matching notes were invisible; `factbook_search` and `search_synopsis` treated `%`/`_` as wildcards; media API failures returned `ok:true` with an error; analysis facets were presented as exhaustive when bounded; visual-filter truncation was recorded then discarded; clause search accepted a chapter it never used. All fixed, with a warning for requested-but-uninstalled modules.
- Removed dead search helpers and stale code. Added 3 regression tests; 243 tests pass.

## Unreleased — Settings audit and in-place updates

- **Check for Updates now updates this installation in place.** It no longer opens a browser on an AppImage. New local endpoints check the release, download the source archive that every release publishes, stage it, and copy only app source files over this tree. The database, modules, appearance, credentials and virtual environment are never touched; every replaced file is backed up under `data/backups/app-update-*/` with a manifest, and the app restarts itself. The About modal explains this and requires an explicit confirmation. The pywebview `checkForUpdates` shim that only called `webbrowser.open` was removed.
- **Passage guide Save was throwing** `on is not defined` and never saved anything; fixed. Reset now checks the response before claiming success.
- **The Logs report flow was broken** — the device-flow poll called `_fileIssue(title, body)` with variables that did not exist, so every successful poll threw. Title and body are now passed through, polling stops on Cancel/Escape/success, duplicate reporting is guarded, and the Clear/Close buttons work on an empty log. Missing `r.ok` checks no longer show "Nothing logged" on a failed fetch.
- **The three AI chat toggles were inert** (Use my library, My own material, Deep research): they changed the checkbox but never saved. They now post to `ai/settings` and revert on failure. AI settings gained response checks, request tokens, and a live `max_sources` update; `deep_research` now has a default.
- **API settings** kept losing the selected category because the response replaced the object holding it; the selection now lives outside the response. Failed loads and mutations are surfaced instead of rendering `undefined` or reporting false success.
- **Sync UI** no longer reports "turned off" when the server refused; it stops claiming everything synced when the module check failed, rejects empty passphrases, and honours the metered-connection policy on a manual press unless you explicitly choose "sync anyway". The label now says "Skip sync on metered connections" because the check reads metered state, not Wi-Fi type.
- **Read aloud settings** now cap and cancel voice-install polling, check job errors, escape voice names, and disclose the internet requirement. Appearance values are escaped and numbers clamped. Appearance is finally included in backup exports.
- **API exceptions are now written to the app log**, so Settings → Logs really does show endpoint failures. Reset now removes credentials, the error log and backups as well as the database. TTS checks the local model cache before loading, so an offline status call cannot hang.
- Removed dead code: `tools-catalogue.js` orphaned sync comment, `.sync-chip` CSS, `tts.available()`, `sync.configured()`, unused parameters and fields, and stale comments about merge-based sync and bundled appearance. Updated labels/docs to match what the code does.
- Added 11 regression tests; 240 tests pass.

## Unreleased — Check updates

- **Check updates can now see seeded modules.** It joined on `store_item.module_id`, which seeds and restores never set, so 33 of 40 installed modules were invisible and the button always said "up to date". The link is rebuilt from the installer's `repo-item` naming rule on each check.
- **It now admits what it cannot check.** Resources whose catalogue records no version are counted separately; the button reports "Nothing to update among the resources with recorded versions. N more could not be checked" instead of claiming everything is current. The response also carries `unchecked`, examples and an explanatory note, and the update confirmation carries the same caveat.
- Checksum detection was considered but is not possible: no installed module or catalogue row records a checksum.

## Unreleased — Library and Store audit

- **Prioritise saves no longer wipe favourites.** The `library/priority` endpoint also called `set_favorite(id, false)`, so every reorder silently deleted the reader's favourites and wrote sync tombstones. Priority and favourite are now separate endpoints.
- **Fixed SQL injection** in `library.list_all` — the `order` parameter was concatenated straight into `ORDER BY`. It is now whitelisted. Query-string `installed_only=false` is parsed as a boolean; `limit`/`offset` are validated and clamped on library, store and word-list routes.
- **Store filters now work past the first page.** `installed_only` was applied in Python *after* SQL `LIMIT`, dropping installed items that sorted later; it is now in the SQL predicate. `total` is counted before limiting, with `returned`/`has_more`, and facets are computed honestly. Added a request token so fast filter changes cannot be overwritten by older replies.
- **Removed 34 duplicate catalogue IDs.** Eighteen Latin Fathers works (Confessions, City of God, De Trinitate…) shared one id per volume, so only the last survived and installing one fetched another's text; the CCEL "fragments" collision is fixed too. The builders now derive ids from the work file, and a regression test asserts every catalogue id is unique.
- **Install, re-install and update flows** now check job errors, bound polling, hide spinners, refresh the store on "already installed", and count failures honestly instead of reporting false success. Removing a repository no longer forces deletion of installed modules — that is an explicit opt-in checkbox.
- **Module removal** refuses duplicate removes, writes a sync tombstone so a deliberate removal stays removed, and deletes the work directory after a failed install. Download URLs must be HTTPS.
- **Dead ends cleaned:** "Linkable: N" now opens a modal, the inert Licence facet chips became a plain breakdown, `Library.filtered()`, an unused variable and parameter, and a dead assignment were removed. Fixed the priority-rule remove link (duplicate `class`, no handler on new rows), the Catalogue format select, Store "Open" not switching views, subject chips reading the wrong field, `javascript:` URLs in attribution/source links, and missing `r.ok` guards that produced confident-but-empty panels. Attribution copy no longer overstates licences for local imports.
- Added 6 regression tests; 231 tests pass.

## Unreleased — Study tools audit, group 2 (Text tools)

- **Copy Bible verses copied the whole chapter, not the verse.** `span:'verse'` was accepted but ignored by the reader. It now resolves the reference to an exact unit key, uses the Bible on the focused pane (or any installed Bible instead of assuming KJV), and uses the app's clipboard helper with its fallback.
- **Visual filters failed silently.** Save/delete/toggle discarded the server response, so a failure reopened the old list as if it had worked, and open panes kept stale highlights. Mutations now check `ok`, repaint the workspace, and a whole-Bible search that hits its cap before reaching this chapter reports the affected filters rather than showing an empty result. Morph-only filters are labelled `morph:` and `?enabled=false` is parsed as a boolean.
- **Information tool mixed data from every module** that happened to share a verse label, ignored the requested module, and showed duplicated Strong's numbers under "Notes". It now scopes to the chosen installed module and reads the reader's actual notes. Cross-reference labels are human-readable.
- **Books search reported page length as the total**, applied an unbounded `LIMIT` (a negative limit scanned the whole library, a non-numeric one errored), and treated `%` as a wildcard that matched everything. Now returns a true total/`more`, validates the cap, escapes LIKE wildcards, orders results, and exposes matched references as clickable links.
- **Bibliography now uses the shared citation engine**, so the requested style is actually applied and entries missing fields are flagged; explicit module ids no longer bypass the installed filter.
- **Text comparison reports which translations were skipped** and says when only the first verse of a range was compared. Removed modules no longer count as available in `read`, `compare`, visual filters, and the cross-reference panel.
- **Search synopsis samples are clickable** via a returned `sample_ref`, and Insights are honestly labelled "Common words" and "Passage excerpt" instead of claiming AI-style themes and summaries. Empty searches now say so.
- Fixed comma-separated module ids in six endpoints (`a,b` was iterated one character at a time) and added 7 regression tests.

## Unreleased — Study tools audit, group 1 (Explore Scripture)

- **NT use of the OT lost 13 real quotations.** Literal `\n` sequences inside comments in `ntuseot.py` commented out the entry on the same physical line. Restored (173 → 186 references), removed the 12-verse cap that made labels claim more text than was compared, fixed `for_verse` counts, added `offset`/`more`, and dropped unused alias/run constants rather than leaving a claim the code did not honour.
- **Word lists reported wrong totals.** Strong's and morph counts ignored the module filter (90,386 claimed vs 6,157 reachable for H3068 in KJV); results also sorted books lexically, so Genesis came after 1 Chronicles. Counts now apply the filter and join the unit table, ordering follows the canon, and exports report when they were truncated. A stored `limit` can no longer raise a caller's cap.
- **Maps geocoding asked Nominatim for the wrong rectangle** — the Near East box is stored south/west/north/east but was passed through verbatim where lon/lat order is required. Alternate-name search tested list membership instead of substrings, so "banah" never found Abana; fixed, with honest `total`/`more` and a `limit` in the geocode cache key.
- **`Gen 1-3` was parsed as 58 verses instead of 80** because a chapter-only range required both ends to be the same chapter. Fixed in the shared reference parser, which also corrects concordance ranges.
- **Verse memorization:** a card's "review" link opened the first due card instead of that one; review grades did not refresh the due list; double-clicking a grade skipped two cards; the Add/Review buttons did nothing until two requests finished. All fixed, and typed references now resolve to a module and unit key so review shows the verse text.
- **Concordance and NT/OT resource pickers** were built once and stayed stale for the session; they now rebuild on each visit preserving the selection. Added request tokens to prevent older responses overwriting newer ones. Strong's head clicks no longer open a popup that the document-level closer hides in the same click.
- **Word lists:** "Add to word list" from a selection toasted `[object Promise]` because an async call was not awaited; it now names the chosen list. Added request guards, keyboard-accessible references, an honest empty-filter message, reliable delete, and a "showing N of total" note.
- **Maps UI:** inert "+N more" and modern-location pins are actionable, historical-map errors are distinguished from an empty list, calibration markers no longer trigger a second prompt, Enter submits calibration, stale global handlers no longer fight remounts, and dead `Atlas.clearMeasure()` was removed.
- Added 9 regression tests; 218 tests pass.

## Unreleased — Guides follow-up

- Bible facts **Festivals → When** was blank: the data has a `date` field for all ten festivals, but the table asked for `month`. Fixed.
- The **Outline** tab ignored a bare book name ("Job", "Exodus") because its splitter required a chapter number. It now resolves the whole-book response to the canonical book id and chapter 1.
- **Counseling → In your books** entries were visible but inert. They now open the resource at the entry key in a pane, with keyboard activation.
- **Bible Browser** now says what it is (an index of places and installed headwords, not passages), its headword links open the entry rather than pretending to be a Bible passage, and "Open on map" dismisses the modal.
- **Eusebian Tables now contain the real canon tables.** The installed CrossWire module was only a per-Gospel section index — it numbered tables by Gospel, so nothing was ever shared and V–X were empty. A curated, public-domain transcription of the actual ten tables (1,161 sections with their cross-references to the other Gospels) is now bundled from CrossWire's `Eusebian_num` utility module, recorded in `ATTRIBUTIONS.md` and checked by the licence audit. All ten tables render, 306 sections are shared between Gospels, and the health card names its source. Fixed a latent `lookup()` error on canon X rows and expanded verse ranges with split-verse markers (`Matt.10.25b-26a`).

## Unreleased — Guides audit

- **Genealogy "…and N more" is now a real control.** Each conflict group expands independently, refs in those rows are clickable, and the whole list was already in `genealogy/summary` — nothing is held back. Parent/child refs are no longer silently cut to three or two.
- **Scripture links work.** The document-wide `data-ref` router was turning dotted OSIS keys like `1Chr.6.3` into `1Chr 6 3`, which the parser rejects — genealogy and cross-reference links looked fine but always failed. It now passes the ref through unchanged. Bible-facts scripture cells, harmony pericopes, outline refs and configured-guide pericopes are links; duplicate local handlers that fired alongside the router were removed.
- **Backend data fixes.** Cross-references read `outgoing`/`incoming` from `crossref_panel` instead of keys that do not exist (the section was always empty); People and Media now count the full set, honour `offset` and report `more` truthfully; Places, Variants, Grammars and Extra-biblical sections page and count honestly; commentary notes are no longer capped at 60; section limits are clamped. Genealogy edges no longer contain a Python `set` (a latent JSON failure), dead code after a `break` was removed, and conflict `parent_refs` are keyed by id so same-named fathers no longer collide.
- **Dead UI, fixed.** The Morphology tab rebuilt nothing on a second visit (and held a copy-pasted block referencing an undefined variable); outline verse/chapter links had `wire()` defined but never called; word-study/exegetical panes now render the configured guide from `guide/run` rather than passing the guide name as if it were the result; unescaped Strong's/morph codes were escaped; the configured-guide section uses the same fold mechanism as every other section. Added cache versions for the changed files and regression tests for the section paging fixes.

## Unreleased — export labels

- The top-bar Export dialog now names the pane button after the Bible actually open (instead of the opaque "This pane"), calls the passage export "All Panes" because it exports every pane's module, and drops "This view" as a duplicate. The print heading uses the same name.
- Export now offers **one button per open pane**, each titled with that pane's resource (and its current reference) and printing only that pane. A pane behind a tab is selected before it is printed.

## Unreleased — sync transparency

- **"What travels?" in Sync.** A new button beside "Sync now" opens a panel that answers exactly what a sync or backup carries. Its data comes from `sync.scope()`, derived from `KINDS`, `SETTINGS_ALLOWLIST` and the backup behaviour in `gbz.py` — the UI keeps no second copy of the lists. It states plainly that AI conversations, usage and API keys are excluded from ordinary sync (encrypted AI-inclusive backup only), that AI *settings* do travel, that deletes need the opt-in and tombstones are kept 90 days, and that standard sync archives are plaintext unless encryption is on.
- **The encrypted AI backup is now reachable.** The Backup card has an "Export with AI data…" button that asks for a passphrase and calls the existing `backup/export` endpoint, so the panel's claim about where private AI data goes is a door the reader can actually use.
- Corrected the Sync summary copy that claimed appearance and AI settings were in an ordinary backup. Updated the stale docs that said encryption was deferred and that AI data was unconditionally in a `.gbz`.
- Added tests tying the panel to the source-of-truth lists and to the AI/deletion/encryption facts.

## Unreleased — connection audit fixes

- Fixed the reference matching behind the new verse connections: whole-book and whole-chapter citations ("Isa", "2 Kgs 24") and shorthand lists ("Gen 21:1–24; 26") now resolve correctly, and book/chapter wildcards are honoured in ranges. Gazetteer and genealogy references are parsed once and cached, and chapter-level passage lookups match the whole chapter.
- The plan day panel now has the same Study… menu as the Today card; search results can send to tools from both the list and the analysis grid; the command palette no longer lists every view twice and follows keyboard navigation; the export dialog reuses the passage exporter and prints the focused pane. Search-result map links now resolve the verse's place through `study/verse`, and Timeline links open the scoped event card.
- Added regression tests for whole-book refs, shorthand lists, ranges, chapter-level gazetteer lookups and genealogy keys.

## Unreleased — connected tools

- **Search results → tools.** Each result has a "send to…" menu with Word Study, Concordance, Passage/Exegetical Guide, sermon research, map places and Timeline.
- **Reading plans → study.** The Today plan card has a "Study…" menu: Passage Guide, Concordance for the chapter, or a search over the day's passages.
- **Verse → geography / history / people.** The right-click menu has a "CONNECT THIS VERSE" group. Places use the gazetteer; Timeline uses a new `timeline/at` lookup by cited passages; Genealogy validates fact-book names against the graph. Fixed two lookups that made these misleading: `places_at` no longer matches on the numeric tail of a different book, and `_people_in` parses genealogy keys instead of comparing formatted strings.
- **Panes over modals.** The word-study modal offers "Open in a study pane", and guide modals offer the same, reusing the existing pane renderers.
- **Ctrl/⌘+K command palette** searches every view and tool and calls its existing click handler.
- **One Export / print door.** A topbar button opens a small dialog for passage, notes, the current view or the focused pane, reusing the existing exporters and printer.

## Unreleased — external AI providers only

- **The bundled on-device AI is gone.** No model is downloaded, stored or loaded, and the Local/Hybrid modes, their fallback flags, the "Prepare on-device model" control and the semantic index are removed. The Assistant still starts opt-in via `ai_enabled`; setup is now one step — enable it and choose a provider. External providers remain: Ollama, LM Studio, llama.cpp, OpenAI, Anthropic, Groq, Google AI Studio and OpenRouter. Stale settings from an older install are ignored on read. Schema v8 drops the retired `ai_embedding` table. Model caches and the torch/transformers/optimum wheels were removed from this install.
- **Clean sweep.** Removed the unused embedding fields from the provider model, the no-op `semantic` parameters threaded through retrieval, the dead `wordtip` endpoint and helper, the unreferenced SermonCal and PassageAnalysis views with their CSS, and several orphaned comments/helpers. Corrected remaining stale documentation. No user data was changed.

## Unreleased — full-app audit fixes and find-in-pane

- **Find in this pane.** Every reading pane now has a compact find box; Ctrl/⌘+F while reading searches the open passage instead of leaving for the library search. Matches are highlighted, counted, and steppable with Enter / ‹ / ›.
- **Study buttons follow the selected verse.** Study, Compare, Info, Interlinear, Merge and Copy resolve the passage at click time rather than using the chapter's first verse.
- **One context menu per verse.** A right-click on a verse no longer bubbles to a second, poorer menu that replaced the word-study and note items.
- **Tag toggling works after the first change**; the picker now reloads the passage it was tagging, not an empty one.
- **Search filters are live.** Bible translation/passage, book collection/type, and media source/licence now reach the search; empty selects are populated from the installed library and the media service. Word clicks reset to plain library search.
- **Parallel resource buttons keep the passage** when cycling translations instead of opening at the next Bible's first chapter.
- **Reader navigation race fixed.** Stale reads can no longer overwrite a newer pane cursor; pane find highlights are cleared on repaint.
- **Course progress** actually saves (missing `completed` parameter); the lesson-complete button now checks the result.
- **Passage Guide People** searches the verse text, not the reference string; the parallel-harmony section filters to the current gospel.
- **Catholic daily readings** query the correct `module.id` column; **Bible Sense Lexicon** accepts a bare word; unsupported export content types are refused instead of producing empty files; notes export reads the `note` table.
- **Licensing is stricter.** GFDL and "freely distributable" are no longer treated as public domain; a Public Domain claim with no publication year is refused; in-file licence/copyright wins over catalogue metadata; unstated licences on local imports are recorded honestly.
- **Genealogy, backup and import hardening.** Person views no longer crash when no English Bible is installed; backups bound declared member sizes; POST bodies are capped; module folders from a restored DB cannot escape the library; SWORD zip scratch directories are cleaned up; failed installs prune stale Strong's entries; custom reading plans sync.
- **Smaller fixes.** Greek digraph transliteration, roman-numeral lookup, sniffing `.bzz2` / `.osis.xml`, duplicate IDs and global key listeners, escaped Strong's values, persisted Visual Filters toggle, and stale documentation about offline catalogues, AI setup and backup encryption.
- **Removed modules no longer pose as installed.** A soft-removed module keeps its row and every note, highlight, card, collection, list entry, workflow step and pane that references it — nothing is deleted. A shared `library.get_installed()` resolver (and a `modLabel()` in the UI) makes those personal records say "removed" instead of showing a stale resource name, a dead "open" link or a bogus "Continue" card. Regression tests lock in both the retention and the honest labelling.
- **Both Visual copy buttons now save a real PNG.** Tools → Visual copy used to show box-drawing ASCII text; it now draws the verse with the same shared `VisualCopy` renderer as the pane's Visual button. The backend supplies the verse text (the ASCII preview remains for text-only callers).
- **The two canvas systems are one.** The old setting-based canvases are migrated once into proper board rows (idempotently, without deleting the original setting), so headings, verse cards, arrows and even unrecognised elements survive. Boards gained `module_id` (a verse card reopens its own translation) and `data` (original element JSON), and a **Heading** card kind. The Dashboard's Canvases list now opens the same board UI as the Canvas view — one renderer, one save path. Schema is v7.
- **No more "database is locked" on ordinary reads.** Every new request thread used to re-run the whole schema DDL and a `BEGIN IMMEDIATE` migration check, so reads took a write lock and contended with each other and the indexer. Schema is now built only for a new/partial database, migrations only when the version is actually behind, and the two post-v6 indexes moved into a migration. Regression tests cover a read holding up while another connection owns the write lock.
- **Recommended starter modules install again.** A stricter licence check had hidden every bundled catalogue item that omits a publication year, and a shadowed `library` import made installer cleanup raise `UnboundLocalError`. Bundled curated catalogues now count as the provenance for their public-domain claim; unknown repositories remain strict. All 39 recommended items are offerable again.
- **Clean startup on a fresh library.** The positional-indexer status was read before its tables existed; `pos_meta` is now created before the worker starts, and the status helpers tolerate an early read.
- **Recommended-set prompt stops repeating.** Status now counts installed modules by their deterministic ids instead of requiring a `store_item` row, so a seeded/restored library is recognised; a clean install run also dismisses the prompt. The right-click menu has a **Topics: word** item again, grouped into THIS WORD / THIS PASSAGE / VISUALISE / OPEN IN STUDY PANES / COPY & CITE / PERSONAL & SAVE, and word detection falls back to the clicked word or selection when the caret API is unavailable. Underlined-name clicks are unchanged.
- **One sermon library.** Study Tools "Sermon import" and "Sermon documents" used a private `sermons` table, so imported sermons never appeared in Sermon Manager, Sermons, Sermon Editor, Documents search or backups. Both now use the same `note` rows as the Manager; existing legacy sermons are migrated once, without deleting the originals. Imported multi-line text also keeps real newlines.
- **Sermon Manager links work.** The Sermons "edit" link was bounced back to the home tab because `App.show()` reset the tab it had just set. The editor also hid the manuscript text of a plain imported sermon and silently ignored edits to title/reference/text; it now shows and saves all of them. "Unschedule" no longer writes an empty-date calendar entry.
- **One date picker for the whole app.** A new reusable `DatePicker` provides a month/year calendar with Today and Clear, emitting canonical `YYYY-MM-DD`. It replaces the free-text sermon date and the two `prompt()` dialogs, and is attached to devotion dates and prayer answered dates. Plan pace gained a "pick finish date" button, and the devotional pane's own month grid now has direct month and year selectors. Sermon scheduling now writes both the calendar and the note so the Manager and Editor agree, and rescheduling moves the date instead of duplicating it.
- **Word definitions now reach headword dictionaries.** A new definition lookup combines a Strong's gloss with headword entries from Dictionary/Lexicon/FactBook modules, so Smith's, Easton, Webster and TIPNR answer a word click or hover. The Strong's superscript opens a definition popup (not a modal) with a "Full word study" button; hovering a tagged word shows dictionary glosses; the right-click menu has a **Dictionary: word** item; a morph code shows its decode on click instead of opening a broken Word Study pane; and `openWord("love")` resolves a surface word through the marker table. Topics search now includes dictionaries, and the dead `_FACT_ROLES` table that contradicted the code is gone.
- **Topics sections reordered.** Dictionary now follows Name directly (Name → Dictionary → Article → …) instead of appearing last, so the lookup reads naturally: a one-line name meaning first, then the full headword article. The generic guide toolbar was removed from the Topics popup, so it now reads Lens → AI answer → sections; that toolbar's guide-type selector used to default to "Passage guide" and sent the term to the passage endpoint when changed. Guide editing and switching remain in the Guides view and guide modals.
- **Outline dictionaries are readable.** Nave (and other `→ Heading  refs` sword outlines) now render as a styled list with bold headings, tidy reference punctuation and clickable passages, instead of raw arrow glyphs and ragged whitespace. Entry summaries show the outline's headings rather than a truncated reference chain. Stored text is untouched. **"See also" cross-references are now links** that open the named entry in the same module.
- **Dead links fixed.** Passage Guide cross-references and map gazetteer passage chips now carry real handlers and open the passage in the workspace; the notebooks "show" link, which had no filter behind it, was removed.

## Unreleased — word notes, reader topics, guide meaning and conflict choices

- **Word-level notes.** A note can be anchored to an original-language word (`meta.anchor_strongs`) from the word menu; it is marked on that word in every translation that tags it, with no schema change. Tagged words now carry a word ordinal (`data-p`), so a note can be pinned to one occurrence of a Strong's number rather than every occurrence in the verse.
- **Reader topic tags feed Topics.** Your own verse tags now appear as a "My topics" section in topic/fact guides and in the verse's topic list, alongside published FactBook articles but labelled as yours.
- **Conflict choices on restore.** Preview lists differing records with both hashes; choose **Keep mine** or **Take theirs** per record. The client sends only ids and choices — the archive is re-read and every record re-verified server-side.
- **Semantic guide retrieval.** When the provider could embed, guide sources were re-ordered by meaning as well as the guide's own order, renumbering citations. (Superseded by the external-AI-only change above.)
- **Browse builder** now has rows for clause roles, morphology features and `~word` fuzzy matching, generated from the engine's own syntax.
- **Analysis export** to CSV or Markdown, including facets, entirely in the browser.
- `tools/bench_search.py` measures the optional Rust core against the Python fallbacks — there were no numbers before.

## Unreleased — structured search, analysis, sync and AI hardening

- **Structured morphology.** `morph:` requests are decoded to grammatical features and resolved to exact tags instead of `LIKE '%fragment%'`. Scheme prefixes (`robinson:`, `strongMorph:`) now decode correctly, and the documented `morph.g:` / `morph.h:` forms work. Lemma search was broken (it queried the morphology table) and now folds accents and case. A **pronoun resolver** links third-person pronouns to a single compatible name in a short window, marked as inferred with an **Inferred** toggle; its hand-checked set scores 1.000/1.000 via `tools/eval_coref.py`.
- **Fuzzy `~word`.** A typo is replaced by the most likely spelling in the library's own vocabulary, with the substitution shown in the search warnings.
- **Analysis view.** Search results can be read as a sortable grid with a **Resolution** column and clickable facets that drill back into the search. Rows can open a word study, concordance, passage guide or stored syntax tree.
- **CoNLL-U treebanks.** A `Syntax` module enables `subject:` / `object:` / `verb:` / `role:` searches; the reader's scope now applies to guides and their AI, and a follow-up carried into the assistant keeps that scope.
- **AI guide improvements.** The guide is gathered once and shared by the questions call and the overview answer; suggested questions are generated after the overview instead of competing with it. Each Topics entry has a **Summarise** button. Citation chips briefly mark the passage they open.
- **Deep research.** Opt-in setting and per-question switch: maximum source budget, always a second retrieval pass, and forced reference resolution, without extra provider calls.
- **Sync hardening.** Real tombstones (opt-in on restore), manifest integrity digest including tombstones, app-version warnings, named conflicts, bounded WebDAV retries and `Retry-After`, a working in-app auto-backup timer, and one-click reinstall of modules a restore reports as missing. Restore remains additive and best-effort by default.
- **Reliability.** Strong's counts no longer double on re-import; re-imports clear stale vectors; the library generation is bumped when content is removed. Parser state is per query, broad marker lookups are chunked, and a suite of regressions was added.

## Unreleased — opt-in AI + retrieval quality

- A fresh install now has **no AI features at all**: the Assistant tab, Ask AI, selection-card AI actions, passage-guide AI and sermon research are absent until the reader enables AI in Settings → AI Assistant. One setup choice: enable the Assistant and choose a provider. No model is downloaded; the same page can disable AI again.
- All `ai/*` and `webresearch/*` endpoints (including the streaming answer) are gated server-side, with setup endpoints as the only exception. Startup skips AI warm-ups while disabled. In-app installs target a writable `data/venv`, and `localai` finds wheels there or in the legacy `.venv`. `GBIBLE_VENV_REEXEC` replaces the old dual-use of `GBIBLE_VENV` as a boolean.

- The assistant now resolves named people and events to likely passages before searching, and reads those passages in full — so a person in one verse and the reason a few verses later both reach the model.
- Added one extra retrieval pass when the first sources barely cover the question.
- Drafts are now audited by a different provider when one is configured. Added UI controls for the new switches (`Settings → AI`).
- Database schema is v8 (the retired semantic-index table is dropped).

## 1.0.1 — backup and update hardening

- Hardened backup credential handling and protected encrypted backup operations.
- Added backup security coverage and checks for transient Store seed failures.
- Improved Gutenberg seed retry behavior for temporarily unavailable resources.
- Updated the README with the latest app and update information.

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
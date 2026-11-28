# G-Bible

### Your Bible. Your library. Your study. On your computer.

G-Bible is a **free, open-source Bible study application** that runs locally.
Read several translations and reference works side by side, search everything
you have installed, dig into the original languages, and keep your own notes,
highlights and study material — offline by default.

There is no account, no subscription and no cloud service to sign up for. The
app is MIT-licensed; your library and your study data stay on your disk.

---

## Run it

### The quick way (Linux)

Download the Flatpack from the [releases page](https://github.com/blackclover5/G-Bible/releases),
and open it. Everything after that happens in the app.

### From source (Windows, macOS, Linux)

You need **Python 3.10 or newer**. The app itself uses only the standard
library; a virtual environment beside the app is used automatically when it
exists (it is needed only for the optional offline read-aloud voice).

```bash
git clone https://github.com/blackclover5/G-Bible.git
cd G-Bible
python3 run.py
```

Then open the address printed in the terminal, usually
<http://127.0.0.1:8777>. The launcher stays in the foreground while the app
runs; close it with `Ctrl+C`.

On first launch, G-Bible offers a short tour and a **recommended starter
library** (Bibles, commentaries, maps and reference works). Both are optional —
you can skip them and install resources later from **Library → Resource
store**. The bundled catalogues work offline; only the resource files
themselves need a download.

Useful launcher options:

| Command | What it does |
|---|---|
| `python3 run.py --port 8899` | Use a different port if 8777 is taken |
| `python3 run.py --no-open` | Don't open the browser automatically |
| `python3 run.py --check` | Run the built-in self-test and exit |
| `python3 run.py --rust-status` | Report whether the optional Rust search core is active |
| `python3 run.py --sync` | Reload the bundled Store catalogues (custom repos may fetch) |
| `python3 run.py --desktop` | Start in desktop-window mode (when supported) |

New to the app? Follow the five-minute walkthrough in
[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md).

---

## What G-Bible can do

### Read and compare

- **A flexible workspace.** Open Bibles, commentaries, dictionaries, maps and
  guides in split panes. Link panes so they follow one another as you move
  through Scripture, save layouts, and switch between them later.
- **Clear reading text.** Footnotes, headings, cross-references and words of
  Christ are rendered from the markup the resource actually contains. G-Bible
  never guesses which words should be red: if a Bible doesn't tag them, they
  stay plain.
- **A selection card.** Select text in a pane and turn it into a quote,
  citation, highlight, note, tag, passage-list item or clipping without
  leaving your place.

### Search and study

- **Library-wide search** for words, phrases, references, Strong's numbers,
  morphology, original-language lemmas, grammatical roles such as
  `subject:Jesus object:Peter`, and typo-tolerant `~word` matching. An
  **Analysis** view groups results by book, lemma, morphology or Strong's
  number.
- **Concordances, word lists, clause search and sentence diagrams**, plus
  reverse interlinear and morphological tools for tagged original-language
  texts.
- **Guides.** Passage and exegetical guides, topic and fact-book guides,
  chapter outlines, gospel harmony, chronology, genealogy, Bible facts and
  maps. Most are assembled from the resources you already own.
- **Study tools.** Old Testament use in the New Testament, cross-references,
  "who cites this verse", important words, visual filters, Bible Browser,
  reference scanner, pronunciation, transliteration and gematria.

### Keep what you learn

- **Notes and highlights** anchored to verses rather than to one translation,
  so they follow you when you switch Bibles. Tags, colours and labels help
  group them.
- **Personal tools.** Favourites, collections, passage lists, notebooks, a
  freeform canvas, clippings, saved search workflows, word lists, flashcards,
  prayer lists, reading plans, a devotional creator and sermon planning and
  writing tools.
- **Home** gives you a daily landing page: today's reading, where you left off,
  recent notes, prayer, tags, highlights, reading plan and anything due for
  attention.

### Listen, research, and move data

- **Read aloud** using your browser's voices or an optional locally installed
  neural voice. Nothing is uploaded to produce speech.
- **AI Assistant (opt-in).** G-Bible bundles no AI model and downloads none.
  You choose a provider: a local server (Ollama, LM Studio or llama.cpp) keeps
  requests on your machine; a cloud provider needs your own key. The assistant
  is a research aid grounded in your library, not an authority. Optional web
  research asks for permission before consulting outside study sites.
- **Backup and sync.** A single `.gbz` archive can be written to a folder or
  WebDAV/Nextcloud and restored later. Deletions only propagate if you opt in.
  An encrypted export can include AI settings and keys; ordinary sync backups
  do not.
- **In-app updates.** **Settings → About** checks the project's releases and
  updates this installation in place, keeping your database, modules and
  credentials untouched. Backups of replaced files are kept under
  `data/backups/`.

### Keyboard shortcuts

| Key | Action |
|---|---|
| `/` or `Ctrl/Cmd+F` | Search the library, or find within the open pane |
| `Ctrl/Cmd+K` | Command palette |
| `Ctrl/Cmd+W` | Workspace |
| `Ctrl/Cmd+S` | Resource store |
| `Ctrl/Cmd+P` | Preaching mode |
| `Escape` | Close a menu or dialog |

---

## Where your data lives

Everything is local:

| Path | Contents |
|---|---|
| `data/gbible.db` | Library index, notes, highlights, plans, layouts and settings |
| `data/modules/` | Installed resource files |
| `data/api-credentials.json` | API keys you choose to add (mode `0600`) |
| `data/backups/` | Backups made by an in-place update |

The `data/` directory is intentionally excluded from version control: it holds
third-party material and personal data that do not belong in the source tree.
**Back up `data/` (or use the app's backup feature) and you have backed up your
study.** Restoring a backup does not copy module files — reinstall those from
the Store on the new machine.

Network access happens only when you ask for it: installing Store resources,
syncing, contacting an AI provider you configured, approved web research, an
update check, or optional error reporting. There is no telemetry.

---

## Troubleshooting

**The app won't start.** Use Python 3.10+ and read the first error in the
terminal. If the port is occupied, try `python3 run.py --port 8899`.

**The browser shows an old version of a page.** Hard-refresh the page. Static
files are served with `no-store`; cache tags on scripts are bumped whenever a
file changes.

**The library is empty.** Install a Bible from **Library → Resource store**.
The bundled catalogues are offline JSON files under `gbible/store/data/`;
`python3 run.py --sync` only reloads those into the local database. A catalogue
you added yourself is the only one that needs the network.

**A resource is installed but its reading or search is empty after an
update.** Close the app and rebuild its index:

```bash
python3 tools/reindex.py <module-id>
```

If full-text search disagrees with the text, repair it with
`python3 tools/rebuild_fts.py --repair` (app closed).

**Search misses a resource.** Confirm it is installed and indexed. Morphology
and grammatical-role searches need a tagged resource; not every module has
that markup.

**Jesus' words aren't red.** That follows the source markup. KJV and WEB tag
these words; many translations and original-language texts do not. Nothing is
inferred.

**Read aloud makes no sound.** Install the optional local voice with
`python3 tools/install_voice.py`, or pick a browser voice in
**Settings → Read aloud**. A local server must be running before its provider
can be tested.

**AI does nothing.** It starts disabled. Open **Settings → AI Assistant**,
enable it and choose a provider. No model ships with the app.

**Sync or restore fails.** Check that the target is reachable and the
credentials are correct, use the same app version on both machines, and keep a
separate backup. A restore never overwrites differing records and does not
bring module files with it. Deletes only apply when you explicitly opt in.

**An update left something broken.** Replaced files are saved under
`data/backups/app-update-*` so an update can be undone. If the app won't start
at all, restore a database backup with
`python3 tools/restore_backup.py /path/to/gbible.db` while the app is closed —
it makes a safety copy and asks for typed confirmation first.

**Something else went wrong.** Open **Settings → Logs**. G-Bible records only
its own errors, with a red error count in the top bar. You can inspect them and
choose whether to file a report. Include your OS, the app version and the steps
that caused the problem. See [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) and
the [Troubleshooting wiki page](wiki/Troubleshooting.md).

Do not delete `gbible.db` as a repair step: it holds your notes and study
data.

---

## For developers

The code is plain Python plus browser JavaScript; there is no build step for
the app itself. An optional Rust core can accelerate search
([docs/rust-migration.md](docs/rust-migration.md)).

Run the checks from the project root:

```bash
.venv/bin/python -m unittest discover -s gbible/tests -q
.venv/bin/python -m compileall -q gbible tools run.py
for f in gbible/web/*.js; do node --check "$f" || exit 1; done
.venv/bin/python tools/test_migrations.py
.venv/bin/python tools/eval_coref.py
python3 tools/selftest.py          # broad end-to-end sweep; takes ~25 minutes
```

Test-only dependencies are listed in `requirements-test.txt`. The wiki page
[For Developers](wiki/For-Developers.md) describes the layout and how to
contribute. More detail is in the [wiki](wiki/Home.md), the
[release notes](RELEASE_NOTES.md), the [changelog](CHANGELOG.md) and
[ATTRIBUTIONS.md](ATTRIBUTIONS.md).

---

## Licence and credits

G-Bible is released under the [MIT Licence](LICENSE). The software is free to
use, study, modify and fork.

The app ships **no proprietary Logos content**. Its catalogues contain only
metadata (title, author, licence, source URL) for freely redistributable
resources, and every installed work carries its own licence and attribution.
See [ATTRIBUTIONS.md](ATTRIBUTIONS.md) for the details.

**G-Bible — Your Bible. Your Library. Your Study.**

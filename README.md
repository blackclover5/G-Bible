##A new update coming Wednesday.

Fixes the Update on the App Image and new Features. Windows APP soon!

#G-Bible

### Your Bible. Your Library. Your Study.

A **free, open-source Bible study app that lives on your computer.**

Read Scripture side by side, dig into the original languages, search your whole library, keep notes and highlights, and build a personal study workspace — all offline by default. No account. No subscription. No cloud. Your notes, your highlights, your library, **All yours**.

> “The app itself is free and open source, released under the MIT License — use it, study it, modify it, fork it however you like.”

---

## Get started in 60 seconds

**Linux (easiest):** download the AppImage from the [releases page](https://github.com/blackclover5/G-Bible/releases), make it executable, launch it. Done.

**Windows / macOS / Linux (source):**

```
git clone https://github.com/blackclover5/G-Bible.git
cd G-Bible
python3 run.py
```

Then open the address the terminal prints (usually `http://127.0.0.1:8777`).

On first launch G-Bible offers its **recommended starter library** (Bibles, commentaries, maps, lexica and more), or you can skip it and install only what you want from **Library → Resource store**.

New here? Read [**Get started in 5 minutes**](docs/GETTING_STARTED.md) for a guided first study session.

---

## What's inside

- **A study workspace** — open Bibles, commentaries, dictionaries, maps and guides in split panes, linked together so they follow your reading. Save and restore layouts.
- **Search across your whole library** — words, phrases, Strong's numbers, morphology and references, across Scripture and reference works.
- **Words of Christ in red** — marked only where the Bible itself tags them (KJV, WEB), never guessed. Bibles that don't tag them render plainly, on purpose.
- **Notes \& highlights** — tied to the verse, not the module, so they travel with your reading across translations.
- **Guides** — passage guides, topic guides, outlines, harmonies, timelines, genealogies, maps.
- **Store** — freely redistributable Bibles, commentaries and reference works, one click to install.
- **Read Aloud** and an optional **AI Assistant** (bring your own provider key; it's a research aid, not an oracle).
- **Sync \& backup** — keep your study data in sync across machines, with optional encryption.
- **Update checker** — one click in **About** checks GitHub for a new release.
- **Keyboard shortcuts** — press `/` to jump to Search.

## Optional extras

- **Read Aloud** — download the voice from **Settings → Read aloud**, or run `python3 tools/install_voice.py`.
- **AI Assistant** — off by default; configure a provider under **Settings → AI**.
- **Sync** — works through a folder or WebDAV/Nextcloud; encryption optional.
- **Auto-backup** — set `GBIBLE_AUTO_BACKUP=1` (optionally `GBIBLE_AUTO_BACKUP_HOURS=24`) to write a timestamped `.gbz` into `data/backups` in the background.
- **Rust core** — optional acceleration for search; see [docs/rust-migration.md](docs/rust-migration.md).

## Honest notes

- This is a **1.0.0** open-source application. This is a Hobby Project that I think Turned out well -— Any issues, please report them in Settings → Logs. Every help is needed.
- **Not every Bible marks Jesus' words** — only ones whose own text does (KJV, WEB). See [words of Christ](docs/GETTING_STARTED.md#4-your-first-five-minutes).
- **Synchronisation is still settling.** It works for folders and WebDAV, but expect rough edges. Don't point it at a library you can't afford to lose teeth to.
- **AI Assistant is optional and key-driven.** Without your own provider key, nothing happens.

## Privacy and ownership

- Everything stays on your disk. No account, no telemetry.
- Network is used only for: downloading Store materials, sync (if you enable it), your own AI provider (if you configure one), Sending errors (If you choose too), and checking for updates.
- Your library lives at `data/gbible.db` — back that up and you have backed up everything.

## Troubleshooting

- **Won't start?** Make sure Python 3.11+ is installed and check the terminal for error messages.
- **Port in use?** `python3 run.py --port 8899`
- **Empty module after an update?** Re-index it: `python3 tools/reindex.py <module-id>` (app closed).
- **Want to undo a bad restore / start over?** `python3 tools/restore_backup.py /path/to/gbible.db` (app closed; asks for a typed confirmation before replacing the live database).
- **Something else?** See [known issues](docs/KNOWN_ISSUES.md).

---

**G-Bible — Your Bible. Your Library. Your Study.**

Free under the MIT license. Contribute, fork, report, and use it well.

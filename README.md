# G-Bible

**G-Bible** is a free, offline Bible study app that runs entirely on your
own computer. No account, no cloud, no tracking — your notes, highlights and
reading stay on your machine unless you choose to sync them yourself.

Current version: **0.9.6 (beta)**.

```
python3 run.py
```

Then open the address it prints (usually `http://127.0.0.1:8777`).

---

## Getting started

1. Run `python3 run.py`.
2. Open the printed address in your browser.
3. On first launch you will be offered a **recommended set** of Bibles,
   commentaries, maps and reference works. Accept it (needs internet) or skip.
4. Start reading in **Workspace**, search in **Search**, and install more
   material from **Modules** (under Library).

Python 3.11+ is all you need. No pip install, no build step. The optional
read-aloud voice is one extra: `python3 tools/install_voice.py`.

---

## Main screens

- **Home** — today's date, today's reading, your reading plans, prayer list,
  highlights, notes and tags.
- **Workspace** — the reading area. Panes tile side by side; tabs inside
  panes. Link panes (A–F) so a Bible and a commentary scroll together.
- **Search** — search every installed resource with a powerful query language.
- **Guides** — timelines, maps, genealogy, gospel harmony, outlines and more.
- **AI Assistant** — optional; off until you add your own provider.

Menus give you **Concordance, Maps, Notes, Organise, Clips, Reading plans,
Prayer, Memorization, My Library** and **Settings**.

---

## Key features

- **Multi-pane reading** with link sets, resizing and saved layouts.
- **Store** of freely-redistributable Bibles, commentaries, lexica, maps
  and books — install with one click.
- **Search** across your whole library, with filters and Strong's numbers.
- **Notes, highlights, clips and tags** that stay with your verses.
- **Reading plans and prayer lists** to keep a daily rhythm.
- **Memorization** with spaced repetition (SM-2).
- **Sync** your notes and progress to a folder, WebDAV or Nextcloud.
- **Import** your own EPUBs and modules.
- **Appearance, read-aloud and passage settings** to make it yours.

Everything works offline once material is installed.

---

## Privacy

G-Bible never phones home. There is no account, no telemetry, no analytics.
Network is used only when *you* ask it to — installing from the Store,
syncing, or using an AI provider you configure yourself.

---

## Resetting

To wipe the library and start over: **About → Reset G-Bible** in the app,
or run `./reset-gbible` from the project folder. Then restart the app.

---

## Troubleshooting

- **Port already in use** — run `python3 run.py --port 8899`.
- **Nothing shows after install** — restart the app; the index updates on
  launch.
- **Offline use** — installed modules read fully offline; only the Store
  needs internet.

---

## License

G-Bible is free and open source, released under the **MIT License**.
You may use, study, modify and share it freely.
# Get started in 5 minutes

The short path for a first-time user. If you already know what you want, skip
to [Your first five minutes](#4-your-first-five-minutes).

## 1. Launch G-Bible

- **Linux, easiest:** download the AppImage, make it executable, double-click it.
- **Windows / macOS / Linux (portable):** unzip the project and run:

  ```bash
  python3 run.py
  ```

  Then open the address the terminal prints, usually `http://127.0.0.1:8777`.

G-Bible is a local-first application. Nothing in your study leaves your
computer unless you explicitly turn a feature on (synchronisation, an AI
provider, etc.).

**The first time you launch it**, G-Bible offers a short guided tour of the
top bar — about a minute, and easy to dismiss. It never runs again unless you
re-trigger it from About G-Bible → "Take the tour".

## 2. First launch: get a Bible

On a fresh library, G-Bible offers a recommended set of resources — a few
Bibles, a commentary, a map, and some reference works. Press **Install
recommended** and wait. (It can be a few hundred MB.) Internet access is
required for this step only.

Skip it and install later through **Library → Resource store** whenever you
want — every freely redistributable Bible and commentary on the Store is
licensed for exactly that. Your library stays yours.

If you see this prompt and press **No**, don't worry — the Store is always
there, and installing nothing changes how the app opens.

Your notes, highlights, plans and prayers live in G-Bible's database on your
disk — never on a server. Back up the app from **Settings → Synchronization**
(the top card) and you back up everything in one `.gbz` file — see the next
section.

**If something breaks**, a small red pill appears in the top-right corner
("N errors found"). Open **Settings → Logs** to see everything G-Bible ran
into — each entry tagged with its source.

For an entry you want to report: press **Report this error**. The first time,
G-Bible asks you to authorise it on github.com/login/device (a one-time
step; your GitHub password never reaches G-Bible). After that, one tap files
the issue with the message and stack attached — as you, not anonymously.
Use **Clear logs** to empty the list and hide the pill when you're done.
Only G-Bible's own errors are logged; nothing from the browser or from
other apps is.

### Backing up and restoring

In **Settings → Synchronization**, one card does both directions. It is the
same mechanism for backup and sync: a single artefact, `gbible-backup.gbz`,
that G-Bible writes to the target you pick — a folder on this computer, or a
WebDAV/Nextcloud server — and pulls back from the same place on restore.

The `.gbz` carries your notes, highlights, plans, tags, layouts, workflows,
word lists, citations, reading progress, saved morphological searches and
sermon material, along with your AI *settings* (provider and model). A standard
sync backup is **not encrypted** and does **not** include appearance, AI
conversations, AI usage history or API keys; keep it like a password, and note
that the sync password never travels in it. To move those private items, use
**Export with AI data…** on the Backup card — it asks for a passphrase and is
always encrypted. See [Backup and Synchronization](../wiki/Backup-and-Synchronization.md).
Modules themselves are not copied — a fresh install reinstalls them from the
Store. The **What travels?** button in Sync lists the exact scope.

Choose a target, press **Sync now** (or leave the interval to do it for you),
and `gbible-backup.gbz` lands wherever you said. To restore, pick where the
backup lives: **From this computer…** (any `.gbz` on disk), **From WebDAV**
and **From Nextcloud** (available when that target is configured — they pull
the same file sync wrote). Restore never deletes and never overwrites:
identical records are skipped, differing records keep yours, and deleted
markers in the backup are ignored.

After a restore, appearance is applied if the archive actually carries it, AI
keys already set on this machine keep their live values (only missing ones are
restored), and G-Bible tells you which modules the backup expects but this
machine doesn't have — install them from the Store and everything is readable
again.

## 3. What you're looking at

The top bar is your whole map:

| Tab | What it's for |
| --- | --- |
| **Home** | Your study day at a glance — today's reading, where you left off, notes, prayer, tags, highlights, reading plan, and cards for eStudySource (premium modules) and BibleSupport (free community modules) |
| **Workspace** | The reading room: Bible panes, commentaries, dictionaries, Strong's study, side by side |
| **Search** | Search your whole library — Strong's, morphology, phrases, words |
| **Guides** | Passage guide, topic guide, chronological facts, harmony and more |
| **Assistant** | Optional AI: connect a local server or add a cloud key. Nothing is sent until you enable it and choose a provider |
| **Study tools** | Concordance, word study, maps, images, import/export tools |
| **My study** | Notes & highlights, favourites, canvas, collections, prayer lists |
| **Library** | **My library** (your books) and **Resource store** (the catalogue) |
| **Settings** | Appearance, synchronisation, Logs, Read-aloud, about |

The cards on Home are yours to arrange. Hold briefly on a card, then drag it to
another spot or column; the arrangement is remembered on this device. The small
**×** in a card's top-right corner removes it from Home. A **gear** button then
appears in the Home header — click it to restore any card you removed, one at a
time or all at once.

## 4. Your first five minutes

1. **Workspace.** It is a grid. Click **Open Bible…** (or use a bookmark in
   the list) and pick a passage. The pane remembers where you left off.
2. **Two panes, one reading.** Right-click the pane and choose **Split this
   pane** (below or right), then pull a commentary or a lexicon into the new
   pane. Drag the splitter to resize it.
3. **Search.** Click **Search** and type `"passion week"` or `"ἀγάπη"` or
   `agape` or a Strong's number like `G0026`. Results update as you type; it is
   a full library search (Strong's morphology is built into it), not just Ctrl-F.
4. **Words of Christ in red.** Where the Bible itself marks them — KJV and
   WEB do, for example — the words Jesus speaks render in red, in the verse,
   not the whole verse. If your Bible doesn't tag them upstream (Brenton's LXX,
   the SBLGNT, the Hebrew Bible), nothing is highlighted, on purpose: nothing
   is guessed and nothing is invented.
5. **Make a note or a highlight.** Select text in the pane and highlight it,
   or attach a note to a verse. Notes are filed against the verse itself,
   not the translation, so the note still shows if you switch Bibles.
6. **Guides.** Open **Guides → Passage guide** on the passage you were
   reading. It shows you the passage's context, outlines, cross-references,
   and places related to it. That is usually enough to stop reading anything
   else for an hour.

## 5. Where it keeps what you make

- Your **notes, highlights, plans, prayers and collections** live in G-Bible's
   database on your disk — not on a server. In a portable source install that
   is `data/gbible.db` inside the folder.
- If you're going to carry G-Bible between computers, configure **sync** first
   (Settings → Synchronisation). The sync is intentionally simple: a folder or
   a WebDAV endpoint you control. There is no G-Bible account, licence, or
   server.

## 6. Honest first impressions

- This is a **1.0.3, open-source** application. It does a great deal and it
   does most of it well, but it is a hobby project, not a commercial product.
  - Occasionally a re-import (or an unfamiliar closing of a module) needs
    re-indexing from its source — easiest from the module's own page.
  - The AI Assistant is optional and off until you turn it on with your own
    provider (a local server or a cloud key). It is a research aid, not a pope.
  - Synchronisation is still settling — make sure you have a backup of your
    library before you try it, and test it on one folder before trusting it with two.

If you are stuck or something behaves strangely, the honest place to look
first is [KNOWN_ISSUES.md](KNOWN_ISSUES.md) — almost every surprise is there
with the reason. Then open an issue on the repo; a screenshot and a sentence
about what you did before is usually enough to reproduce it.

Welcome. The Bible is worth the effort.

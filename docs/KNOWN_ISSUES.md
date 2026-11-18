# Known issues

Nothing here is hidden: everything below is what you'd hit anyway. For a
short version, see the [Troubleshooting section of the README](../README.md#troubleshooting).
If you hit something not listed here, say so — a bug report honestly helps.

## Words of Christ

**Some of my Bibles show red words and others don't — is one of them broken?**

No. Jesus' words in red are marked where the Bible text itself tags them,
never by anything this app guesses:

- **KJV** and **WEB** (and its variants) mark Jesus' words in their source
  markup → they render in red, exactly in the verse, exactly the span the
  text says they are.
- **Brenton's LXX** is not affected (it's the Old Testament).
- The **SBLGNT** and the **Westminster Leningrad Codex** do not tag Jesus'
  words → plain text. This is deliberate, and no amount of expectation will
  change it unless someone upstream adds the tagging.
- If your translation tags them but the app shows them in plain text, you've
  hit a bug: check that you're on the latest build, and that the module was
  imported with the current importer (see re-indexing, below).

If in doubt, the test is simple: open the same passage as Web and KJV. If
neither renders Jesus' words in red, your build is not doing the work — open
an issue with the passage reference.

## Installing and installing again

**I changed something (for example, re-encoding an import or upgrading the app), and now my Bible is empty.**

Delete the `data/modules/<module-id>` folder and re-install the module from
the Store. All user data (highlights, notes, reading progress) is keyed on the
module id, which is stable, so those return.

If that still fails, re-index from the source files already on disk:

```bash
python3 tools/reindex.py <module-id>            # one module
python3 tools/reindex.py --all                  # everything eligible
```

Run these with **the app closed**. The tool rebuilds only the search rows;
your data is untouched. Modules built by purpose-built importers
(openscriptures, macula, stepbible-data, wikisource, wikimedia) are skipped
with a message and are not harmed — they can only be reinstalled via the Store.

**My Store catalogue shows nothing installable.**

Check the connection to the Store server from inside G-Bible. The
catalogues are downloaded from the Store and cached; if the very first
request happens on a machine with no internet access, nothing is listed.
Load G-Bible once with internet access, then everything shows up.

## Performance

**The app ran out of memory / got killed while I was doing a big reindex or installing many modules.**

The app and any one heavy batch job (a full re-index, installing 40 modules at
once, building the positional index for the whole library) are each greedy
consumers of RAM. On a small machine, don't run both at the same time: close
G-Bible, do the batch job, then open G-Bible. The positional index is rebuilt
incrementally and can be interrupted without harm — just pick it up again.

Idle memory for G-Bible is ~47 MB. After its first search warms up the
spelling tables, it hovers around ~96 MB, and search-heavy sessions plateau
under half a GB. It is not a memory leak, just appetite.

**Do not delete `data/gbible.db` or `data/modules/`.** Your notes, highlights,
and all installed resources live there. If you ever want a fresh start, use
About → Reset G-Bible, and take a copy of `data/` first.

## Synchronisation

**Sync is not finished.** The sync engine works for what it knows — a folder,
or WebDAV/Nextcloud — and it does multi-way merge. But regular consumers will
be disappointed by anything beyond that:

- **AI credentials are never included in ordinary sync backups.** Encryption
  protects the rest of the backup when enabled and requires a passphrase on
  every restoring device.
- **Large attachments / images / audio do not sync.** Only study data, notes,
  highlights, plans and markers.
- **Sync participants must have the same G-Bible version.** Don't mix builds or
  with a future sync-less build and expect it to work.
- Try it on a test folder first; keep the option turned off until you've seen
  it work end-to-end.

## AI Assistant

**Nothing happens when I ask the assistant anything.**

Correct. The Assistant is off until you configure your own provider key
(Settings → AI). G-Bible does not ship a provider and does not send your data
anywhere on its own.

**The answer feels wrong.**

Ground it well: paste the passage in front of the assistant (a verse, a range,
or a whole list), ask for context, not for answers about the Bible instead of
reading it. The assistant will cite what it was given; it will not "know" a
translation it wasn't supplied, and it is not a substitute for your own
judgment — it is a tool, nothing more.

**Free providers have rate limits.**

If you used one of the free-tier providers, expect quota exhaustion quickly;
the UI surfaces that properly when it happens. Upgrade, switch providers, or
wait — it is not a bug.

## Miscellaneous

**Read aloud doesn't produce sound on Linux.**

The voice is usually installed by the AppImage; on a source install you can
install it with:

```bash
python3 tools/install_voice.py
```

Then Settings → Read aloud settings → pick a voice.

**Comparison shows some translations as "unknown" / compares wrongly.**

Install both translations, re-index if you hit a bug, and compare
verse-by-verse, not by passage-by-passage, when you want a precise check.

**Something breaks silently and nothing shows up.**

Open a browser devtools console: if there's an error, it shows up there.
Open an issue on the repo with your platform and what you were doing —
that's enough for a repro most of the time.

**I want to roll back a restore — how?**

For an ordinary restore, install a `.gbz` backup from **Settings →
Synchronization** instead (additive: it never deletes anything). For
catastrophic rollback — `data/gbible.db` itself is broken — `tools/restore_backup.py`
is the safest path. It refuses to run
while the app is holding the database, refuses to overwrite without a typed
confirmation, verifies the backup is a valid library (quick_check + schema
version), and writes a timestamped safety copy beside the live database
before touching anything. No web call reaches this path; the restore is an
offline CLI operation only.

# Annotation Sync — Specification

Status: **partly implemented.** The engine, the filesystem target, the WebDAV
target (with the Nextcloud preset), the interval worker and the settings screen
exist; the mobile client does not yet. This document is the contract for moving
a user's annotations between installs — this desktop app now, the mobile app
later.

It is written to be implemented *and* to be implemented against from a second
codebase. Nothing here is private to this app.

---

## Read this first

1. **Nextcloud is WebDAV.** There are two drivers to write, not three: a WebDAV
   client, and a filesystem driver. "Nextcloud" is a WebDAV target with a preset
   base URL (`/remote.php/dav/files/<user>/`) and app-password authentication.
   S3, Google Drive and OneDrive can join later behind the same target
   interface; none are needed for v1.
2. **The library is never synced.** Bibles, commentaries and the positional
   index are large and re-installable from the Store. What syncs is the small
   set of records a person creates by reading: notes, highlights, plan marks,
   layouts, collections, and the settings that describe how they read.
3. **The sync folder is a contract, not a cache format.** The phone writes the
   same files with the same manifest. It does not talk to this computer, and it
   does not need this app to be running. That is the whole reason the layout is
   documented rather than left as an implementation detail.
4. **Deletes need tombstones.** Notes, highlights, collections, passage lists
   and templates are hard-deleted today. Without a tombstone, a note removed on
   one device comes back from any device that was offline at the time.
5. **Clock skew is the one thing that silently loses data.** Two devices whose
   clocks disagree by an hour will lose edits with no error anywhere. See §6;
   do not resolve merges on wall-clock time.

---

## Contents

1. [Scope](#1-scope--what-syncs-and-what-does-not)
2. [Folder layout](#2-folder-layout)
3. [The record envelope](#3-the-record-envelope)
4. [The manifest](#4-the-manifest)
5. [Merge rules](#5-merge-rules)
6. [Clocks](#6-clocks)
7. [Schema changes this requires](#7-schema-changes-this-requires)
8. [Sync targets](#8-sync-targets)
9. [Networking policy](#9-networking-policy)
10. [Security](#10-security)
11. [Guidance for the mobile client](#11-guidance-for-the-mobile-client)
12. [Build order](#12-build-order)
13. [Open questions](#13-open-questions)

---

# 1. Scope — what syncs and what does not

| Kind | Record path | Source today | Ids today | Merge |
|---|---|---|---|---|
| `note` | `notes/<id>.json` | `note` table (kinds: note, journal, sermon, prayer) | 12-hex uuid, no prefix | last-writer-wins |
| `highlight` | `highlights/<id>.json` | `highlight` table | 12-hex uuid slice | last-writer-wins |
| `plan-mark` | `plan-marks/<plan>.json` | setting `reading-plan/progress` → `{plan: [days]}` | plan id | **union** per plan |
| `layout` | `layouts/<id>.json` | `layout` + `pane` tables, one record per layout | `lay…`, panes `p…` | last-writer-wins |
| `collection` | `collections/<id>.json` | `collection` + `collection_item` (pinned) | `col…` | last-writer-wins |
| `passage-list` | `passage-lists/<id>.json` | `passage_list` | `pl…` | last-writer-wins |
| `passage` | `passages/<id>.json` | `passage_item` (ordered inside a list) | `pi…` | last-writer-wins |
| `template` | `templates/<id>.json` | `search_template` | `st…` | last-writer-wins |
| `favourite` | `favourites/<module_id>.json` | `module.favorite` flag | module id | last-writer-wins |
| `setting` | `settings/<key>.json` | allowlisted keys in `setting` table | key name | last-writer-wins |
| `tag` | `tags/<id>.json` | `tag` + `tag_item` tables | 12-hex uuid | last-writer-wins |
| `word-list` | `word-lists/<id>.json` | `word_list` + `word_list_item` | `wl…` | last-writer-wins |
| `workflow` | `workflows/<id>.json` | `workflow` + `workflow_step` | `wf…` | last-writer-wins |
| `srs-card` | `srs-cards/<id>.json` | `srs_card` table | 12-hex uuid | last-writer-wins |
| `citation-meta` | `citation-metas/<module_id>.json` | `citation_meta` table | module id | last-writer-wins |
| `tombstone` | `tombstones/<id>.json` | derived from deletes | — | GC after 90 days |

Not synced, deliberately:

- **The library files** — modules, the positional index, the genealogy graph.
  These are large and re-installable from the Store. What *does* travel is the
  list of installed module ids (in the `installed_modules` setting), so a new
  computer knows what to install.
- **`is_current` on a layout** — which layout is open is a property of the
  device in front of you, not of the data. The record carries `id`, `name`,
  `tiles` and `panes`; which one is open stays local.
- **Device-local settings** — `flash_session` (transient UI state),
  `highlight_palette_active` (which palette is selected), and anything added
  later that describes the screen rather than the reader.
- **Appearance** (theme, font, size) unless it is later decided to travel. The
  reader of a phone at night may want a different theme from the desktop.
- **AI conversations and the AI usage record** — a conversation is a
  transcript of what the reader asked and what was said back, and the usage
  record is a list of billable calls. Both stay on the machine they were made
  on. A reader who does not want a transcript of their questions on another
  device should not have one there, and the answer to that is not to ask.

The settings allowlist for v1, in full:

`reading-plan/progress`, `module_tags`, `highlight_palettes`, `top_bible`,
`prioritize_rules`, `visual_filters`, `plan_paces`, `plans_archived`,
`sermon_calendar`, `notebooks`, `clippings`, `canvases`, `print_books`,
`guide_configs`, `collection_rules`, `search_panel_link`, `prayer_templates`.

A key not in this list does not sync. Adding one is an additive change: an
older client ignores the record it does not know.

---

# 2. Folder layout

The target's own folder is the root — the directory or cloud path the reader
named when they chose the target — and one version folder sits inside it:

```
<the target folder>/v1/
  manifest.json
  notes/<id>.json
  highlights/<id>.json
  plan-marks/<plan>.json
  layouts/<id>.json
  collections/<id>.json
  passage-lists/<id>.json
  passages/<id>.json
  templates/<id>.json
  favourites/<module_id>.json
  settings/<key>.json
  tags/<id>.json
  tag-items/<id>.json
  word-lists/<id>.json
  word-list-items/<id>.json
  workflows/<id>.json
  workflow-steps/<id>.json
  srs-cards/<id>.json
  citation-metas/<module_id>.json
  tombstones/<id>.json
```

The `v1/` segment is the contract version. Everything under it must remain
readable for as long as any client is in the field. A breaking change adds
`v2/` beside it; a reader reads every version directory it knows and merges,
with the highest version winning on a per-record basis.

Record ids are globally unique and device-independent — every existing id
already is: `note` ids are a bare 12-hex uuid slice, highlights a 12-hex slice,
and `lay_`, `p_`, `col_`, `pl_`, `pi_` and `st_` are prefixed hex from one
helper. Ids, not paths, are the identity of a record; the path is derived from
the id and must never be parsed back for meaning.

File names are `<id>.json`, URL-encoded for targets whose names may not hold
every character an id can.

---

# 3. The record envelope

Every file under `v1/` holds exactly this shape:

```json
{
  "schema": 1,
  "kind": "note",
  "id": "9f1c2ab34d56",
  "rev": 7,
  "updated_at": 1791577734.325,
  "clock": { "dev": "d_3f9a…", "ctr": 12 },
  "hash": "sha256:1f3b…",
  "deleted": false,
  "payload": {
    "kind": "note",
    "title": "A note on John 1",
    "body": "…",
    "module_id": "ebible-engasvbt",
    "unit_key": "John.1.1",
    "ref_label": "John 1:1",
    "tags": ["logos"],
    "meta": {},
    "created_at": 1791480000.0
  }
}
```

Field by field, and why each is there:

- **`schema`** — envelope version. Same role as the `v1/` path segment, carried
  in the file so a record can be identified without trusting its path.
- **`kind`** — one of the kinds in the §1 table. A reader dispatches on this and ignores
  kinds it does not implement. Unknown kinds are never fatal.
- **`id`** — the record's identity. Never changes, including across a rename or
  a move between devices.
- **`rev`** — a per-record monotonically increasing integer, incremented by
  the writing device on every change. This is the primary ordering signal.
- **`updated_at`** — wall-clock seconds, carried for human display ("last
  edited 3 hours ago") and for nothing else. Never the basis of a merge
  decision; see §6.
- **`clock`** — the hybrid logical clock stamp at write time. The ordering
  signal when `rev` cannot decide (a record created on two devices that have
  never met).
- **`hash`** — SHA-256 of the canonical JSON of `payload`, prefixed with the
  algorithm. Lets a client decide "same content" without fetching the payload,
  and lets the manifest stay small.
- **`deleted`** — true makes the record a tombstone. Tombstones still carry
  their kind so a reader knows which table to delete from.
- **`payload`** — the entity itself, in the same shape the app's own API
  already returns for it. One representation per record, so the phone and the
  desktop never drift into two formats for the same data.

Payload shapes, per kind, taken from what the app stores today:

- **`note`** — `id, kind, title, body, module_id, unit_key, ref_label, tags,
  meta, created_at, updated_at`.
- **`highlight`** — `id, module_id, unit_key, quote, color, note, created_at`.
- **`plan-mark`** — `{ "plan": "<plan id>", "days": [3, 7, 12] }`. The whole
  set for one plan in one record, because the set is the unit a reader thinks
  in, and because it merges by union rather than by winner.
- **`layout`** — `id, name, tiles, panes[]` where each pane is `id, module_id,
  link_set, tile_id, cursor, options, text_size, view, is_focus, follow_only,
  follow_active`. `is_current` is dropped, per §1.
- **`collection`** — `id, name, note, pinned[]` (ordered module ids). What is
  *pinned*, not what the collection currently contains: membership is derived
  from a rule plus the pinned items, so a derived list would freeze a snapshot
  and drop the rule. The rule itself rides along in the `collection_rules`
  setting, which is in the allowlist below for exactly this reason.
- **`passage-list`** — `id, name, note`.
- **`passage`** — `id, list_id, unit_key, ref_label, module_id, position`.
- **`template`** — `id, name, query, options`.
- **`favourite`** — `{ "module_id": "<id>", "favorite": true }`. Favourites are
  a flag on the module row today, so the record is per module and a `false` is
  written as a tombstone rather than parking a record that means "not
  favourite".
- **`setting`** — `{ "key": "<key>", "value": <whatever the key holds> }`.

Writes are atomic: write to a sibling temporary file, then rename over the
target. A client that reads a partially written record is a bug, and rename is
the fix that works on every filesystem and on every WebDAV target that can
serve files at all.

---

# 4. The manifest

`manifest.json` is the index. It is rewritten at the end of every sync:

```json
{
  "schema": 1,
  "generated_at": 1791577734.325,
  "generated_by": "d_3f9a…",
  "records": {
    "9f1c2ab34d56": {
      "kind": "note", "rev": 7, "hash": "sha256:1f3b…",
      "updated_at": 1791577734.325, "clock": { "dev": "d_3f9a…", "ctr": 12 }
    },
    "4c7b2d1e9a0f": {
      "kind": "highlight", "rev": 2, "hash": "sha256:9d2c…",
      "deleted": true, "clock": { "dev": "d_88b1…", "ctr": 4 }
    }
  }
}
```

Rules:

- The manifest lists **every** record, not a diff. At annotation scale (a few
  thousand records) it is tens of kilobytes, and a full listing is what makes
  the algorithm simple enough to be correct.
- A record present as a file but absent from the manifest is **not** data. It
  is an interrupted write: delete it. Files are content; the manifest is truth.
- The manifest is written last, atomically. Any client that reads a manifest
  that mentions a record whose file is missing treats that record as "needs
  pulling" and pulls it.
- `generated_by` records which device wrote it, for diagnostics only.

# 5. Merge rules

Given a local record and the manifest's entry for the same id:

1. **Present in one place only** → take it.
2. **Same hash** → nothing to do.
3. **Different, one is a tombstone** → delete locally, keep the tombstone.
4. **Different, both alive:**
   a. Compare `clock`. The greater clock wins.
   b. If the clocks are equal, compare `rev`. The greater rev wins.
   c. If both are equal and the payloads still differ (a genuine conflict), the
      winner is the one with the greater `updated_at`, and **the loser is kept
      as a separate record** named `<title> (conflicted <date>)`. Nothing is
      ever silently discarded.

**Union merge** for `plan-mark`, because a set of marked days is additive: a
day marked on the phone and a day marked on the desktop are both true, and
there is no conflict to resolve. The merged payload's `rev` is the max of the
two, and its clock is the greater of the two.

**Tombstone GC**: a tombstone is deleted from the target once every device that
has synced in the last 90 days has seen it. In practice: a tombstone carries the
device id of its last writer, and it is removed once its `updated_at` is older
than 90 days. Until then it stays, which is what stops a resurrected note.

**Deleting on the receiving side is always applied from a tombstone, never from
a missing file.** A missing file with no tombstone is an incomplete download.

---

# 6. Clocks

Wall-clock time is not a safe ordering signal, and the failure is silent:

- A laptop with a dead battery comes back with a clock months behind. Its notes
  then carry an `updated_at` older than everything else, and every merge
  resolves against them. Edits vanish with no error.
- A tablet with a flat battery and no NTP drifts by minutes or hours. Two
  devices both confidently report a time, and the later one is simply wrong.

So ordering is a hybrid logical clock, one per device:

```
device id: uuid4, generated once, stored in the app's data directory
counter:   an integer, monotonic for the life of this install
```

On every write, `ctr = max(local ctr, highest ctr seen from any remote) + 1`,
stamped with the device id. On receiving a manifest, `local ctr = max(local
ctr, every ctr in the manifest)`. This gives a total order that two devices
agree on without either trusting its own clock, and it needs no server, no
consensus, and no network beyond the target.

`updated_at` remains in the record, is still written from the local clock, and
is used for display and for the last-resort tie-break in §5.4c only. That
tie-break is the one place a skewed clock can matter, and it produces a
conflicted copy rather than a lost edit.

---

# 7. Schema changes this requires

Honest list, small but not empty:

1. **`highlight` has no `updated_at`.** Add the column. Highlights are the most
   frequently written records in the app, and without it there is no rev to
   increment. Existing rows get `updated_at = created_at`.
2. **Tombstones.** A `sync_tombstone(id TEXT PRIMARY KEY, kind TEXT, deleted_at
   REAL)` table, or a `deleted_at` column per entity table. One shared table is
   easier to reason about and easier to GC. Every hard delete in `notes`,
   highlights, collections, passage lists, templates, layouts and favourites
   becomes a tombstone write.
3. **Revision numbers.** `rev` per record. A shared `sync_record(id PRIMARY
   KEY, kind, rev, updated_at)` table holds it for every kind, rather than
   adding a column to eight tables.
4. **Device id and sync state.** `device_id` uuid, `sync_state` (target, last
   run, last error, enabled, interval, wifi_only), one row each in `setting` or
   a `sync` table. Secrets are not stored here — see §10.
5. **`plan-mark` is derived from a setting row today** and becomes a record per
   plan. Read `reading-plan/progress`, emit a record per plan, and on merge
   write the union back. No table change.

Nothing here changes an existing API response shape, so the mobile app and this
app can share representations from day one.

---

# 8. Sync targets

A target is an object with four methods. `list()` is not one of them: the
manifest is a file like any other record, so a target that can store and
retrieve a named blob is the whole requirement.

```
read(path)        -> bytes | None
write(path, body) -> atomic (temp file, then rename/MOVE)
remove(path)     -> unlink
exists(path)      -> bool
```

**Filesystem.** A directory on any mounted volume — a second disk, a NAS
mount, a USB drive. Fastest path, no credentials, and the right target for
"another computer I have". Writes are the atomic rename of §3. A sync against a
disconnected drive must report "target not available" rather than error.

**WebDAV**, covering Nextcloud and any WebDAV server:

- Methods used: `PROPFIND` (list), `GET`, `PUT`, `DELETE`, `MKCOL`. No
  `LOCK`, no WebDAV revision properties, no search.
- **Nextcloud preset**: base path
  `/remote.php/dav/files/<user>/<path>`, and authentication with an **app
  password**, never the account password. Nextcloud refuses basic auth with the
  account password for many operations and app passwords are revocable.
- **HTTPS for anything reachable.** A password over plain HTTP is readable by
  anything on the path, so a public host is refused at save time, with the
  reason. One exception: loopback and private (RFC1918/link-local) addresses are
  allowed, because a NAS or a home server cannot hold a certificate and its
  traffic never leaves the building. A name resolving to a public address is
  refused — the safe answer when it cannot be told.
- One writer at a time. Two clients syncing the same folder concurrently will
  produce conflicted copies, not corruption. Before starting, warn when the
  manifest's `generated_by` is another device that ran in the last minute.
- Chunked upload for the largest records if a target chokes on a big `PUT`.
  Annotations are small; this is a fallback, not a feature.
- Stdlib only (`urllib`/`http.client`) is sufficient. The app has no HTTP
  dependency beyond the standard library, and sync should not be the reason one
  appears.

**Later targets** (S3, Google Drive, OneDrive) implement the same five methods.
They are not needed for v1 and none of the design above anticipates them being
hard.

---

# 9. Networking policy

Mirrors what the reader asked for, in the terms the codebase already has:

- **Off by default.** Sync is opt-in, target and interval chosen by the user.
- **Interval** — a choice of manual, 5, 15, 60 minutes, and on quit.
- **"Only over Wi-Fi / Ethernet"** — honest caveat: on a desktop there is no
  portable way to know whether a connection is metered. If NetworkManager is
  present, `nmcli -t -f GENERAL.METERED device show` answers it; if it is not,
  the option reports *"cannot tell — NetworkManager not found"* rather than
  silently doing nothing. An option that lies is worse than no option.
- **Never blocks startup.** The app opens and reads instantly whether or not
  the target is reachable. This follows the existing background-thread pattern
  (`posindex.BackgroundIndexer`, the genealogy warm-up): a worker, a job
  registry, a status line.
- **Backoff** on failure — successive failures double the wait, capped, and the
  last error is surfaced in the UI ("sync failing since 14:02: 401").
- **Manual "Sync now"** always available, and the status strip shows the last
  successful time.

---

# 10. Security

- **Credentials live outside `gbible.db`**, in a file beside it with `0600`
  permissions, keyed by target. The database is the file people copy, back up,
  and send to a developer for support; a sync password must not be in it.
- **No credentials in the sync folder.** The manifest and records hold user
  text and module ids, nothing else.
- **HTTPS required** for WebDAV. No exceptions, no "allow insecure" toggle.
- **No library content in the records.** A note's `body` is the user's own
  words; the module text it points at stays on the device.
- **Optional later**: encrypt the payloads at rest on the target with a
  passphrase the user holds. Deferred deliberately — it makes the mobile client
  harder and most users' Nextcloud is already encrypted at rest on the server.

---

# 11. Guidance for the mobile client

The phone is a first-class client of the same folder:

1. Generate its own device id (uuid4) and keep it forever. Never reuse the
   desktop's.
2. First sync: read the manifest, pull everything it does not have, push
   everything the manifest does not have. Do not special-case "first run".
3. Write records atomically; rewrite the manifest last.
4. Advance its clock counter from every manifest it reads, before writing
   anything, so a device that only ever reads cannot stall the other's counter.
5. Implement one kind at a time and ignore the rest. A client that reads notes
   and ignores layouts loses nothing.
6. Same target, same credentials, no desktop involvement. The phone may sync
   on mobile data while the desktop is asleep; that is fine, and is the reason
   Wi-Fi-only is a per-device policy rather than a property of the folder.

---

# 12. Build order

Each step is independently useful and safely stops there:

1. **Filesystem target + manifest + notes only.** Proves the envelope, the
   atomic write, the manifest-last rule, and the tombstones. Nothing else can
   be built until this is right.
2. **WebDAV target, with the Nextcloud preset.** Adds the credential file, the
   HTTPS rule, and the offline-target failure path.
3. **Remaining record kinds** — highlights, layouts, collections, passage
   lists, templates, then the settings allowlist. One PR each, no reordering.
4. **Interval, Wi-Fi/metered policy, status surface.**
5. **The mobile client**, reading the same `v1/` folder.

---

# 13. Open questions

Not decided, and none of them block step 1:

- **Should the theme and font travel?** Leaning no — a phone at night wants a
  different theme from a desktop, and appearance is a device property like
  `is_current`.
- **Encrypted payloads on the target** — see §10. Deferred to when there is a
  second client to protect.
- **Does the phone ever sync *through* the desktop** rather than to the cloud
  directly? Designed against; direct-to-cloud is simpler and works when the
  desktop is off.
- **Tombstone GC cadence** — 90 days is a guess. It trades folder clutter
  against a resurrected note on a device that has been in a drawer, and 90 days
  is the safe side.
- **What happens when two layouts have the same name on two devices?** Two
  records, two layouts, no merge — names are not identifiers and the app
  already refuses to deduplicate them.

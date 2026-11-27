# Backup and Synchronization

G-Bible can write a `.gbz` backup to a local folder or a configured WebDAV/Nextcloud target. Synchronization is optional and marked experimental; keep an independent backup while evaluating it.

## What is included

The archive contains supported study records such as notes, highlights, plans, tags, layouts, workflows, word lists, citations, reading progress, saved searches and sermon material, plus AI *settings* (provider and model). It does not include installed Bibles, commentaries, or other module content; reinstall those from the Store on another machine. Appearance is carried only by an explicit export that includes it, not by ordinary sync. Large attachments, images, and audio are not synchronized. A Sync screen **What travels?** button lists the exact scope from the same code that builds the archive.

Ordinary backups do not include AI credentials, conversations or usage history. Choose **Export with AI data…** on the Backup card to include them; that requires a passphrase of at least 12 characters and the resulting archive is always encrypted. A standard backup without that option is not encrypted, so treat it as sensitive and store it privately.

## Create a backup

1. Open **Settings → Synchronization**.
2. Select a folder or configure a WebDAV/Nextcloud destination.
3. Choose manual or scheduled behavior and use **Sync now** to write `gbible-backup.gbz`.
4. Keep a second copy somewhere separate from the computer being backed up.

For a local backup, you can also set `GBIBLE_AUTO_BACKUP=1`; optionally set `GBIBLE_AUTO_BACKUP_HOURS=24`. Automatic backups are written under `data/backups`.

## Restore

From Synchronization, choose a local `.gbz` or pull it from the configured remote target. Restore is additive by default: identical records are skipped and differing records retain the current local value. If records differ, the restore summary names them as conflicts so you can see what was left alone. A backup whose contents do not match its manifest is refused before anything is applied, and a backup made by a newer G-Bible version is reported rather than silently misread. Missing modules may need to be installed again from the Store.

Deletions are a separate, explicit choice. Enable **Apply deletes from the backup** only when you want a delete made on another device to remove the matching record here. It applies only to records this device already knows and whose stored delete is newer than its local revision; records with no known revision are left alone. Ordinary restores remain non-destructive.

For database-level recovery, close G-Bible and use the guarded tool:

```bash
python3 tools/restore_backup.py /path/to/gbible.db
```

This is for a database backup, not a `.gbz` archive.

## Encryption and security

When you choose to include AI credentials, G-Bible requires an encryption passphrase and encrypts the archive. Keep the passphrase safe; G-Bible cannot recover it. Standard backups are not encrypted. Use HTTPS for remote WebDAV services and an app password for Nextcloud. Only sync to a target you control or trust.

## Limitations

The sync feature is still settling. It writes one complete `.gbz` snapshot to the target; it does not do a two-way record-by-record merge, so the last device to write wins the file. Use the same G-Bible version on participating devices, test with a noncritical folder first, and keep a standalone backup. See [[Troubleshooting]] for target and restore issues.

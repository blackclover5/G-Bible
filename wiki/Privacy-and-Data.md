# Privacy and Data

G-Bible is designed to work locally. It has no account, subscription, or telemetry. Your library and personal study records live on your computer.

## Local files

The default data directory is `data/` under the application folder. You can choose a different directory with `GBIBLE_HOME`. The main files include:

- `gbible.db` — library index and personal study records.
- `modules/` — installed module content.
- `api-credentials.json` and `sync-credentials.json` — provider or sync credentials stored separately from the database.
- `data/backups/` — automatic `.gbz` backups when automatic backup is enabled.

Keep the app’s data directory private: it can contain personal notes, sermons, prayers, AI conversations, and provider configuration. API keys are stored outside the database with restricted file permissions where supported.

## Content you import

G-Bible never uploads, shares, or redistributes files you import; they stay on your computer. You are responsible for having the right to use any material you add. The app does not check your rights and does not bundle commercial third-party resources — the Store and the importers only handle openly licensed material, with the licence stated before a treebank is installed. See [[Importing Bible Modules]].

## Network connections

Network use occurs for features you choose or invoke, including:

- downloading Store catalogue data and resources;
- checking for app updates;
- optional synchronization to a folder or WebDAV/Nextcloud target;
- AI requests to your selected provider;
- map tiles when displaying the map;
- GitHub error reporting only when you submit a report.

AI requests may include the question and retrieved passages. If enabled, relevant notes, highlights, and clippings can also be included. Cloud providers receive those contents; local providers keep the request on your machine. See [[AI Assistant]] for details.

## Backups and sync

A regular `.gbz` backup may contain private study records and AI conversation/history data. Treat it as sensitive. Encryption is available for sync/backups where configured. API credentials are handled separately and are not ordinary backup payloads. See [[Backup and Synchronization]].

## Remove data

Use the in-app reset control when you want a clean start, and make a copy first if you may want to restore your data. Removing the application files alone does not necessarily remove a separately configured `GBIBLE_HOME` directory.

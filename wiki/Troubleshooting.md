# Troubleshooting

## The app will not start

Use Python 3.10 or newer and run `python3 run.py` from the project directory. Read the terminal output for the first error. If the default port is occupied, try `python3 run.py --port 8899`.

## The library is empty

Install a Bible from **Library → Resource store**. The built-in catalogues ship with the app and work offline; only repositories you add yourself are fetched over the network. If the resource is installed but its content/search is empty after an update, close the app and run:

```bash
python3 tools/reindex.py <module-id>
```

Do not delete the database as a repair step. See the [known issues](../docs/KNOWN_ISSUES.md) page for details.

## Jesus’ words are not red

Red-letter rendering follows markup supplied by each Bible module. KJV and WEB commonly tag these words; many original language texts and translations do not. G-Bible does not guess which words should be red.

## Store catalogue is empty

The bundled catalogues are offline files under `gbible/store/data/`; `python3 run.py --sync` only re-imports that local JSON into SQLite. If they are missing, restore them. A repository you added yourself is the only catalogue that needs a network connection.

## Search misses a resource

Confirm it is installed. Re-index eligible modules with `tools/reindex.py`; some purpose-built modules must be reinstalled from their source instead. Morphology requires a tagged resource.

## Read aloud has no sound

See [[Read Aloud]]. Install the optional neural voice on source installs or try another browser voice.

## Sync or restore problem

Check that the target is available and the credentials are correct. Use the same app version across devices and keep a separate backup. A restore does not bring over module files. See [[Backup and Synchronization]].

## Collect information for a report

Open **Settings → Logs**. You can inspect errors there and choose to submit a report. Include your OS, app version, the steps that caused the issue, and a screenshot if useful. Remove private information before sharing logs publicly.

More known limitations are documented in [docs/KNOWN_ISSUES.md](../docs/KNOWN_ISSUES.md).

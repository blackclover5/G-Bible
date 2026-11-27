# Library and Resource Store

**My library** lists installed resources; the **Resource store** lists downloadable materials. G-Bible stores resource text locally and indexes it for reading and search.

## Install resources

On first launch, you can install a recommended starter set. Later, open **Library → Resource store**, browse the catalogue, and install individual items. The built-in catalogues are bundled with the app and work fully offline; only the module *downloads* need internet access. A repository you add yourself is fetched over the network. `python3 run.py --sync` just re-imports the bundled catalogue JSON into SQLite — it is not a download.

The Store includes Bibles, commentaries, dictionaries and lexicons, books, maps, images, and other study resources. Catalogue entries retain resource-specific license and attribution information. Check **Attribution** in a resource’s library details before reusing its content.

## Import a file

Use **My library → This computer → Import a file…** to import supported files you already have. Supported importer families include SWORD, USFM, OSIS/XML Bible, e-Sword, ThML, EPUB, plain text, and selected tabular or PDF workflows. Actual support depends on the particular file structure; see [[Importing Bible Modules]].

Only import and redistribute materials you have the right to use. The app’s MIT software license does not change the license of downloaded or imported works.

## Manage and repair

Open a module’s details to inspect metadata, attribution, and available management actions. If a module becomes empty after an update or import, close G-Bible and rebuild its search index:

```bash
python3 tools/reindex.py <module-id>
python3 tools/reindex.py --all
```

Purpose-built modules that cannot be reconstructed by the generic reindexer are skipped safely; reinstall those modules from their source or Store entry.

## Storage

Modules are stored below the application data directory in `modules/`; the SQLite database is `gbible.db`. Together they can be several gigabytes. Avoid deleting these folders unless you intend to remove your library and study data.

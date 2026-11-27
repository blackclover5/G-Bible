# Importing Bible Modules

G-Bible can import compatible Bible and reference resources from files on your computer. Open **Library → My library → This computer → Import a file…** and select the source. The importer detects supported formats and asks for metadata or options when needed.

## Supported format families

The project includes readers for SWORD, USFM, OSIS/XML Bible, e-Sword, ThML, EPUB, plain text, and selected tabular, PDF, and Bible module formats. A format extension does not guarantee every file using it is supported: producers vary, and some formats have multiple incompatible versions.

- **SWORD** packages typically contain a `mods.d` configuration file and module data.
- **USFM/USFX/OSIS** are structured scripture formats; book identifiers and markup affect verse mapping.
- **e-Sword** may mean modern SQLite modules or older module/container versions.
- **EPUB/plain text** are useful for reference books but may need cleanup or unit splitting.
- **PDF** is intended for supported text extraction flows; image-only scans may not yield searchable text.
- **CoNLL-U** (`.conllu`) is a dependency-treebank format used by Universal Dependencies. It installs as a **Syntax** resource rather than a book, and powers [[Search|clause-role searches]] such as `subject:Jesus object:Peter`.

See [OPEN_BIBLE_MODULE_FORMATS_SPEC.md](../OPEN_BIBLE_MODULE_FORMATS_SPEC.md) for verified format research and importer details.

## Installing a CoNLL-U treebank

Use the same **This computer → Import a file…** path and select the `.conllu` file. Treebanks are licensed data, so the importer asks you to state the licence before installing it — Universal Dependencies releases are usually **CC BY-SA 4.0**, which must be entered exactly. A file with no licence stated is refused rather than silently imported.

Sentences whose metadata names a verse (for example `# sent_id = John 3:16` or `# reference = Gen-1-1`) are keyed to that verse and link with your Bibles; other sentences remain searchable as `syn-NNNNN` units. Once installed, `subject:`, `object:`, `indirect_object:`, `oblique:`, `verb:` and `role:` queries work across the treebank. The roles are decoded from the dependency relations — they are not a guess from English word order, and pronouns are not resolved to the people they stand for.

## Before importing

1. Confirm you have permission to use the material.
2. Keep the original source file; import creates G-Bible’s local indexed copy.
3. Ensure the file is complete and not still downloading.
4. Close the app before using offline reindex/repair scripts.

## After import

Check the resource in **My library**, open it in the Workspace, and try a search. Review the stored title, language, type, and license/attribution metadata. If it appears empty, use the module details to reindex if supported or remove and re-import from the original source.

## Content ownership and licences

G-Bible's MIT licence applies to the **software**, not to any text you import. The Store offers only openly licensed resources, and the importer asks you to state a licence for a CoNLL-U treebank before installing it.

Files you import from your own computer are **your responsibility**. You must have the right to use the material you add. G-Bible does not host, share, or redistribute your files, and it has no way to know what rights you hold. Bringing in a book you are not licensed to use is your own legal exposure, not the app's: the software is a general-purpose reader and importer with many lawful uses, and it neither encourages nor helps you obtain material without permission.

Do not redistribute a module unless its own licence permits it.


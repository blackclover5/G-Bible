# For Developers

G-Bible is a Python application with a local HTTP server, HTML/CSS/JavaScript interface, and SQLite database. An optional Rust extension accelerates selected hot paths; Python fallbacks remain available.

## Setup

```bash
git clone https://github.com/blackclover5/G-Bible.git
cd G-Bible
python3 run.py
```

Python 3.10+ is required. `cryptography` is the declared runtime dependency. Development checks use `requirements-test.txt`. The Rust extension is optional; instructions are in [docs/rust-migration.md](../docs/rust-migration.md).

## Project map

- `gbible/` — Python application and domain modules.
- `gbible/server/` — local HTTP server and routes.
- `gbible/web/` — front-end HTML, CSS, and JavaScript.
- `gbible/store/` — catalogue and resource installation logic.
- `gbible/importers/` and `gbible/formats/` — import orchestration and format readers.
- `rust/` — optional PyO3 acceleration core.
- `tools/` — maintenance, indexing, migration, and audit utilities.
- `docs/` — user and technical specifications.

## Data and safety

Runtime data under `data/` is deliberately excluded from Git: modules may be large and have their own licenses, and the database contains personal study material. Tests use temporary `GBIBLE_HOME` directories. Never commit library databases, credentials, downloaded modules, or user backups.

## Checks

The project’s CI compiles/imports the code, runs unit tests and database migration checks, exercises a seeded library and browser flow, and separately checks Rust parity. To run the quick app self-check against a prepared library:

```bash
python3 run.py --check
```

For tests and details, inspect `.github/workflows/checks.yml` and `requirements-test.txt`. The conservative pronoun resolver has a small hand-labelled evaluation set: run `python3 tools/eval_coref.py` to see its precision and recall before changing any of its rules. Do not run broad or destructive maintenance scripts against a user’s live library without a backup.

## Contributing

Keep changes focused, preserve Python fallback behavior for optional native code, and update user documentation when visible behavior changes. Resource content has separate licenses from the MIT-licensed app. See [ATTRIBUTIONS.md](../ATTRIBUTIONS.md) and the module format specification before adding material or importer support.

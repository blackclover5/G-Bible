# Rust migration and native build

G-Bible now has an optional Rust performance core. The application remains
Python-first for compatibility, while the existing HTML/CSS/JavaScript reader,
SQLite database, module files, and public Python interfaces are unchanged.

## Converted hot-path primitives

The `rust/` crate exposes the following through the `gbible._rust_core` Python
extension:

- Unicode-aware tokenization with Python-compatible character offsets;
- case/diacritic/typographic normalization;
- HTML/XML entity decoding and the app's whitespace-collapse operation;
- the existing conservative suffix stemmer and token-key operation;
- positional-index varint packing and decoding;
- capped optimal-string-alignment Damerau-Levenshtein distance.

The Python call sites in `gbible/db.py`, `gbible/posindex.py`, and
`gbible/search.py` automatically use these Rust implementations when the
extension is installed. If the extension is missing or cannot be loaded, the
original Python implementations remain active. Existing databases and indexes
are not changed by installing the extension.

## Linux build

Install a Rust toolchain (rustup/cargo), Python development headers, and a
virtual environment. From the project root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip maturin
maturin develop --release
python tools/test_rust.py
python run.py
```

On Debian/Ubuntu, the Python headers are usually provided by
`python3-dev`; a C toolchain may also be required by native Python dependencies.

## Windows build

Install the stable Rust toolchain from <https://rustup.rs/> and the Microsoft
C++ Build Tools (MSVC workload). Then, in PowerShell from the project root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip maturin
maturin develop --release
python tools\test_rust.py
python run.py
```

To build a distributable wheel instead of installing into the active virtual
environment, run `maturin build --release`. The wheel is written under
`target/wheels/` and can be installed with `python -m pip install <wheel>`.

## Build without Rust

No Rust toolchain is required to run the current source tree. Simply run
`python run.py`; G-Bible automatically uses its Python fallback. The Rust core
is an optional acceleration, not a startup requirement.

## What is intentionally still Python

The query-language parser/evaluator, database schema and transactions, importer
orchestration, and format-specific OSIS/USFM/SWORD/e-Sword/EPUB/ThML/XML readers
remain Python. They contain substantial domain-specific behavior and format
edge cases. Replacing them safely requires fixture-by-fixture parity tests and
would be a larger migration than moving isolated hot-path primitives. This
crate is designed so more Rust modules can be added behind the same optional
boundary without changing the reader or stored data.

## CI

The regular Python checks continue to run without Rust. A separate CI job builds
the extension on Linux and runs `tools/test_rust.py`, so the native code is
compiled and exercised in a Rust-enabled environment.

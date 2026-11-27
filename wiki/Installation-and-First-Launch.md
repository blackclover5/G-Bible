# Installation and First Launch

## Linux AppImage

Download the current AppImage from [GitHub Releases](https://github.com/blackclover5/G-Bible/releases), make it executable, and launch it. The AppImage is the simplest path for Linux users.

## Run from source (Linux, Windows, macOS)

Install Python 3.10 or newer, then:

```bash
git clone https://github.com/blackclover5/G-Bible.git
cd G-Bible
python3 run.py
```

Open the local address printed in the terminal (normally `http://127.0.0.1:8777`). To choose a different port, use `python3 run.py --port 8899`. Use `--no-open` to start without opening a browser. The app listens on loopback by default.

The ordinary source runtime uses the Python standard library plus the declared `cryptography` dependency. Read-aloud neural voices and the optional Rust acceleration have additional installation steps; neither is required to run G-Bible.

## First launch

1. Follow or dismiss the brief tour.
2. On a new library, choose whether to install the recommended starter set. Downloads require internet and can be large.
3. Or open **Library → Resource store** and choose resources individually.
4. Open **Workspace → Open Bible…** and select a passage.

You can skip resource installation. The Store remains available later. G-Bible does not require an account or subscription.

## Data location

By default, the app stores its database and modules in the project’s `data/` directory. Set `GBIBLE_HOME` to use another data directory. Back up the database and module directory together if you want a full copy of the installed library; a `.gbz` backup covers study records but does not contain the resource modules.

## Useful launch commands

```bash
python3 run.py --port 8899     # use another port
python3 run.py --no-open        # do not open a browser
python3 run.py --check          # run the app self-check (requires a seeded library)
python3 run.py --rust-status    # report whether optional Rust acceleration is active
python3 run.py --sync           # refresh Store catalogues
```

## Update

Use the in-app About page to check for a release, or download a newer build from [Releases](https://github.com/blackclover5/G-Bible/releases). Preserve your data directory when replacing application files.

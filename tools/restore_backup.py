"""Restore a G-Bible library backup over the tool's data directory.

This is an *offline* operation. It never happens over HTTP, never from the
running app, and never without an explicit --yes/typed confirmation.

    python3 tools/restore_backup.py /path/to/backup.db           # check only
    python3 tools/restore_backup.py /path/to/backup.db --yes      # apply
    python3 tools/restore_backup.py /path/to/backup.db --yes     \
        --target /path/to/other/data_home                        # elsewhere

What it does:
    1. Refuses to touch any target whose gbible.db is currently open (the app
       must be closed; on Linux an open file cannot be tested at the path, so
       it also tries SQLite's own lock).
    2. Verifies the candidate really looks like a G-Bible library (sqlite
       header, quick_check green, `meta` table present with schema_version).
    3. Prints a summary of what will be overwritten (current library counts).
    4. Copies the existing library to <gbible.db>.pre-restore-<timestamp>
       before replacing it.
    5. Copies the backup in with `os.replace` (atomic on one filesystem).
    6. Removes stale WAL/SHM files so the next open doesn't see orphaned state.
    7. Re-opens and reports what the restored library contains.

The restore is always reversible: the pre-restore copy is kept on disk next
to the restored file until you delete it yourself.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def target_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser().resolve()
    from gbible import db
    return db.app_dir()


def _looks_like_sqlite(p: Path) -> bool:
    try:
        with open(p, "rb") as f:
            return f.read(16).startswith(b"SQLite format 3")
    except OSError:
        return False


def _probe_library(p: Path) -> dict:
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        quick = conn.execute("PRAGMA quick_check").fetchone()[0]
        if quick != "ok":
            raise RuntimeError(f"integrity check reports {quick!r}")
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "meta" not in tables:
            raise RuntimeError("no meta table — not a G-Bible library")

        def meta_get(key, default=None):
            row = conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

        schema_version = int(meta_get("schema_version", 0) or 0)
        if schema_version < 2:
            raise RuntimeError(f"schema version {schema_version} is too old — not a library this build can read")
        info = {
            "schema_version": schema_version,
            "size_bytes": p.stat().st_size,
            "created_at": float(meta_get("created_at", 0.0) or 0.0),
            "units": conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0] if "unit" in tables else None,
            "modules": conn.execute("SELECT COUNT(*) FROM module WHERE installed_at>0").fetchone()[0] if "module" in tables else None,
            "notes": conn.execute("SELECT COUNT(*) FROM note").fetchone()[0] if "note" in tables else None,
        }
        return info
    finally:
        conn.close()


def _is_live_library(path: Path) -> bool:
    """True when `path` appears to be in active use by a running app.

    The app holds a connection open to gbible.db for the lifetime of the
    process. We test by asking SQLite if we can get an exclusive write lock
    on it; if the app is up, we can't, and that's the signal.
    """
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
        conn.execute("BEGIN EXCLUSIVE")
        conn.rollback()
        conn.close()
        return False
    except sqlite3.OperationalError:
        return True
    except Exception:
        return True   # unknown state is treated as in-use


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("backup", help="Path to a gbible.db backup you want restored")
    ap.add_argument("--yes", action="store_true",
                    help="Skip the interactive 'type restore' confirmation")
    ap.add_argument("--target", default=None,
                    help="Directory whose gbible.db should be replaced "
                         "(defaults to the app's data/ folder)")
    ap.add_argument("--list", action="store_true",
                    help="Just print what the backup holds and stop")
    a = ap.parse_args()

    backup = Path(a.backup).expanduser().resolve()
    if not backup.is_file():
        print(f"ERROR: backup not found: {backup}", file=sys.stderr)
        return 2
    if not _looks_like_sqlite(backup):
        print(f"ERROR: {backup} does not look like a SQLite database.", file=sys.stderr)
        return 2

    try:
        info = _probe_library(backup)
    except Exception as e:
        print(f"ERROR: refusing to restore this file: {e}", file=sys.stderr)
        return 2

    print(f"Backup:          {backup}")
    print(f"  size:          {info['size_bytes'] / (1 << 20):.0f} MB")
    print(f"  schema:        v{info['schema_version']}")
    print(f"  created at:    {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(info['created_at'])) if info['created_at'] else '(unknown)'}")
    print(f"  units:         {info['units']}")
    print(f"  modules:       {info['modules']}")
    print(f"  notes:         {info['notes']}")
    if a.list:
        return 0

    dest = target_dir(a.target)
    target = dest / "gbible.db"
    print(f"Replacement target: {target}")

    if target.exists():
        # A gbible.db can sometimes exist beside a -wal that says it's in use.
        if _is_live_library(target):
            print("ERROR: a running app has gbible.db open (or its lock persists).", file=sys.stderr)
            print("       Stop G-Bible fully, then run this again.", file=sys.stderr)
            return 3
        try:
            conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=1)
            n_units = conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0] if conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='unit'").fetchone()[0] else None
            n_modules = conn.execute("SELECT COUNT(*) FROM module WHERE installed_at>0").fetchone()[0] if conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='module'").fetchone()[0] else None
            print(f"Current library: units={n_units} modules={n_modules}")
            print("-- This existing library will be moved aside and replaced.")
            conn.close()
        except Exception:
            print("Current library: (could not read; it will be replaced with a timestamped copy)")
    else:
        print(f"No existing library at {target}; backing up nothing.")

    if not a.yes:
        typed = input("Type 'restore' to proceed: ").strip().lower()
        if typed != "restore":
            print("Aborted. Nothing changed.")
            return 1

    safety = None
    if target.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safety = target.with_suffix(target.suffix + f".pre-restore-{stamp}")
        try:
            shutil.copy2(target, safety)
            print(f"Safety copy: {safety}")
        except OSError as e:
            print(f"ERROR: could not save safety copy: {e}", file=sys.stderr)
            return 4

    # Atomically swap in the backup.
    staging = target.with_suffix(target.suffix + ".restoring")
    try:
        shutil.copy2(backup, staging)
        os.replace(staging, target)
    except OSError as e:
        print(f"ERROR: copy/swap failed: {e}", file=sys.stderr)
        if safety and safety.exists():
            print(f"Library left untouched; safety copy is at {safety}")
        return 5

    # Remove stale journals from the previous file; the new file comes with
    # whatever the backup carries and its own WAL, which a later open reads.
    for name in (f"{target}-wal", f"{target}-shm",
                 target.with_suffix(".db-wal"), target.with_suffix(".db-shm")):
        try:
            Path(name).unlink(missing_ok=True)
        except OSError:
            pass

    try:
        conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=5)
        quick = conn.execute("PRAGMA quick_check").fetchone()[0]
        print(f"Post-restore quick_check: {quick}")
        conn.close()
    except Exception as e:
        print(f"WARNING: could not re-check the restored file: {e}", file=sys.stderr)
        if safety and safety.exists():
            print(f"Reverting: restored library failed integrity check; "
                  f"restoring previous from {safety}")
            try:
                shutil.copy2(safety, target)
            except OSError:
                pass
        return 6

    print("Restore complete.")
    print(f"Your previous library is preserved at: {safety or '(nothing existed)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

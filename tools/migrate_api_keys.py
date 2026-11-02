#!/usr/bin/env python3
"""Move API keys out of `gbible.db` and into a 0600 file beside it.

Run once.  Safe to run again: it only moves what is still in the table.

    python3 tools/migrate_api_keys.py            # report what would move
    python3 tools/migrate_api_keys.py --apply    # do it
    python3 tools/migrate_api_keys.py --verify   # confirm nothing is left

Why
---
`docs/sync.md` already says it: the database is the file people copy, back up
and attach to a support email, so a sync password must not be in it.  The same
argument applies to a key for somebody else's account, and more strongly -- a
sync password protects this user's own data, while an API key authorises the
holder to spend that service's quota and read what it returns.  `gnosis` is a
proprietary service; a token for one was stored in `api_key.value` in plain
text.

The table is emptied, not dropped, so the schema does not move under anybody's
feet, and `registry.key_for()` still reads the table as a fallback for a library
that has not been migrated yet.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gbible import db                                     # noqa: E402
from gbible.api import registry as R                      # noqa: E402


def rows() -> list[tuple[str, str]]:
    conn = db.connect()
    return [(r["api_id"], r["value"] or "")
            for r in conn.execute(
                "SELECT api_id, value FROM api_key "
                "WHERE value IS NOT NULL AND trim(value)<>''")]


def main() -> int:
    apply = "--apply" in sys.argv
    verify = "--verify" in sys.argv
    found = rows()

    if verify:
        left = rows()
        path = R.credentials_path()
        print(f"credential file: {path}")
        print(f"  exists: {path.exists()}"
              + (f"  mode: {oct(path.stat().st_mode & 0o777)}"
                 if path.exists() else ""))
        stored = R._read_credentials()
        print(f"  keys in file: {sorted(stored)}")
        print(f"keys still in the database: {len(left)}")
        if left:
            for api_id, _ in left:
                print(f"  STILL IN DB: {api_id}")
        print("OK" if not left else "NOT DONE")
        return 0 if not left else 1

    if not found:
        print("no keys in the database -- nothing to move")
        return 0

    print(f"{len(found)} key(s) in gbible.db:")
    for api_id, value in found:
        lic = R.API_BY_ID.get(api_id)
        print(f"  {api_id:24} {len(value):>4} chars  "
              f"{lic.license if lic else '(unknown service)'}")
    if not apply:
        print("\nnothing moved.  Re-run with --apply.")
        return 0

    creds = R._read_credentials()
    for api_id, value in found:
        if api_id in creds:
            # The file wins: it was written deliberately, and the table is the
            # copy that is on its way out.
            print(f"  {api_id:24} already in the file -- keeping that one")
            continue
        creds[api_id] = {"value": value, "set_at": 0.0, "migrated_from": "api_key"}
        print(f"  {api_id:24} moved")
    R._write_credentials(creds)

    conn = db.connect()
    n = conn.execute("DELETE FROM api_key "
                     "WHERE value IS NOT NULL AND trim(value)<>''").rowcount
    conn.commit()
    # SQLite does not return freed pages to the filesystem without a VACUUM,
    # and the file is 4 GB, so this is not done here: the reader should close the
    # app and run it deliberately if the size matters to them.
    print(f"\nemptied {n} row(s) from api_key")
    path = R.credentials_path()
    print(f"wrote {path} (mode {oct(path.stat().st_mode & 0o777)})")
    print("\nThe freed pages are still inside gbible.db until it is VACUUMed.")
    print("To reclaim them, close the app and run:")
    print(f"    sqlite3 {db.app_dir() / 'gbible.db'} 'VACUUM;'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
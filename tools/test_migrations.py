"""Exercise database upgrades from the previous on-disk schema."""

from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gbible import db


def _close_thread_connection() -> None:
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        del db._local.conn
        del db._local.path


def _legacy_schema() -> str:
    schema = db.SCHEMA
    columns = {
        "module": ("heading_count", "verified", "error", "priority",
                   "favorite", "v11n_source"),
        "unit": ("char_start", "char_len", "word_count"),
        "marker": ("span_start", "span_end"),
        "highlight": ("updated_at", "label", "book", "chapter", "verse"),
        "store_item": ("year_from", "year_to", "checksum"),
        "repo": ("item_count",),
    }
    for table, names in columns.items():
        pattern = re.compile(
            rf"(CREATE TABLE IF NOT EXISTS {table} \()(.*?)(\n\);)",
            re.DOTALL,
        )
        match = pattern.search(schema)
        assert match, f"could not find {table} in schema"
        lines = match.group(2).splitlines()
        def column_name(line: str) -> str:
            parts = line.strip().split(maxsplit=1)
            return parts[0].rstrip(",") if parts else ""
        lines = [line for line in lines if column_name(line) not in names]
        schema = schema[:match.start(2)] + "\n".join(lines) + schema[match.end(2):]
    return schema


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="gbible-migrations-") as temp:
        home = Path(temp)
        db_file = home / "gbible.db"
        conn = sqlite3.connect(db_file)
        conn.executescript(_legacy_schema())
        conn.execute("INSERT INTO meta(key,value) VALUES('schema_version','1')")
        conn.execute("INSERT INTO module(id,name,type) VALUES('test','Test','Bible')")
        conn.execute(
            "INSERT INTO unit(module_id,key,ord,book,chapter,verse,ref_label,text) "
            "VALUES('test','John.3.16',1,'John',3,16,'John 3:16','For God so loved')"
        )
        conn.execute(
            "INSERT INTO highlight(id,module_id,unit_key,quote) "
            "VALUES('highlight-1','test','John.3.16','so loved')"
        )
        conn.commit()
        conn.close()

        old_home = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = str(home)
        try:
            upgraded = db.init()
            version = upgraded.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()["value"]
            assert version == str(db.SCHEMA_VERSION)
            actual_columns = {
                table: {row["name"] for row in upgraded.execute(
                    f"PRAGMA table_info({table})")}
                for table in ("module", "unit", "marker", "highlight",
                              "store_item", "repo")
            }
            for table, required in db._ADDED_COLUMNS.items():
                assert {name for name, _ in required} <= actual_columns[table], table
            ref = upgraded.execute(
                "SELECT book,chapter,verse FROM highlight WHERE id='highlight-1'"
            ).fetchone()
            assert tuple(ref) == ("John", 3, 16), tuple(ref)

            db.init()
            assert upgraded.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()["value"] == str(db.SCHEMA_VERSION)
        finally:
            _close_thread_connection()
            if old_home is None:
                os.environ.pop("GBIBLE_HOME", None)
            else:
                os.environ["GBIBLE_HOME"] = old_home

    with tempfile.TemporaryDirectory(prefix="gbible-fresh-schema-") as temp:
        old_home = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = temp
        try:
            fresh = db.init()
            version = fresh.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()["value"]
            assert version == str(db.SCHEMA_VERSION)
            for table, required in db._ADDED_COLUMNS.items():
                have = {row["name"] for row in fresh.execute(
                    f"PRAGMA table_info({table})")}
                assert {name for name, _ in required} <= have, table
        finally:
            _close_thread_connection()
            if old_home is None:
                os.environ.pop("GBIBLE_HOME", None)
            else:
                os.environ["GBIBLE_HOME"] = old_home

    print("schema migration, fresh database schema, and repeat initialization passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

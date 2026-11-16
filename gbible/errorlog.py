"""G-Bible's own error log.

Only errors that belong to this application are recorded: the server hitting
an exception, the sync worker, and the renderer reporting one of its own
faults.  Nothing from outside the app is logged — a generic browser failure
(e.g. an extension) is not, by design.

The log is a capped JSON-lines file beside the database; the UI reads the
newest entries and can clear it.  Tracebacks are trimmed and home-directory
paths are normalised before storage.
"""

from __future__ import annotations

import json
import os
import time
import traceback

from . import db

MAX_ENTRIES = 200
MAX_TB_BYTES = 2000
MAX_MSG_BYTES = 500


def _path():
    return db.app_dir() / "error-log.jsonl"


def _trim(s: str | None, limit: int) -> str:
    s = s or ""
    home = os.path.expanduser("~")
    if home:
        s = s.replace(home, "~")
    raw = s.encode("utf-8", "replace")[:limit]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", "replace")


def _trim_tb(tb: str | None) -> str:
    return _trim(tb, MAX_TB_BYTES)


def log_error(source: str, message: str, tb: str | None = None) -> dict:
    rec = {
        "t": round(time.time(), 3),
        "source": _trim(source, 40),
        "message": _trim(message, MAX_MSG_BYTES),
        "tb": _trim_tb(tb),
    }
    try:
        lines = []
        p = _path()
        if p.is_file():
            lines = [l for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        # Cap first: append, then trim the oldest.
        lines.append(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
        while len(lines) > MAX_ENTRIES:
            lines.pop(0)
        tmp = p.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass
    return rec


def read_errors(limit: int = 200) -> list[dict]:
    out: list[dict] = []
    try:
        p = _path()
        if not p.is_file():
            return out
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if isinstance(rec, dict):
                    out.append(rec)
            except json.JSONDecodeError:
                continue
    except OSError:
        return out
    return out[-int(limit):]


def count() -> int:
    return len(read_errors(MAX_ENTRIES))


def clear_errors() -> int:
    n = count()
    try:
        _path().unlink(missing_ok=True)
    except OSError:
        pass
    return n


def log_exception(source: str, e: BaseException) -> None:
    log_error(source, f"{type(e).__name__}: {e}",
              traceback.format_exc(limit=30))

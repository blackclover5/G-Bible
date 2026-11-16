"""The logs screen: read, count and clear G-Bible's own error log.

No personal data, no database content — only what made the app fail,
already trimmed and path-normalised by errorlog.
"""

from .common import *
from ... import errorlog


@endpoint("logs/list")
def _logs_list(parts, q):
    try:
        limit = int(q.get("limit") or 100)
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 500))
    entries = errorlog.read_errors(limit)
    return _ok(entries=entries, count=len(entries))


@endpoint("logs/count")
def _logs_count(parts, q):
    return _ok(count=errorlog.count())


@endpoint("logs/clear")
def _logs_clear(parts, q):
    return _ok(ok=True, removed=errorlog.clear_errors())


@endpoint("logs/client-error")
def _logs_client_error(parts, q):
    """The renderer reports one of its own faults. UI-sourced only."""
    source = (q.get("source") or "ui").strip() or "ui"
    message = (q.get("message") or "").strip()
    if not message:
        return _ok(ok=False, error="nothing to log")
    tb = (q.get("stack") or "").strip()
    return _ok(**errorlog.log_error(source, message, tb or None))

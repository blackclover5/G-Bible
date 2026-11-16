"""Issue reporting, backed by a device-flow the reader starts themselves."""

import time
import urllib.error

from .common import *
from ... import githubapp


@endpoint("logs/report/start")
def _report_start(parts, q):
    try:
        r = githubapp.start_device_code()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        return _ok(ok=False, error=f"GitHub returned HTTP {e.code}: {body}")
    except Exception as e:
        return _ok(ok=False, error=str(e))
    return _ok(ok=True,
               device_code=r.get("device_code"),
               user_code=r.get("user_code"),
               verification_uri=r.get("verification_uri"),
               interval=r.get("interval") or 5,
               expires_in=r.get("expires_in") or 900)


@endpoint("logs/report/poll")
def _report_poll(parts, q):
    device_code = (q.get("device_code") or "").strip()
    if not device_code:
        return _ok(ok=False, error="missing device_code")
    try:
        res = githubapp.poll_access_token(device_code)
    except urllib.error.HTTPError as e:
        return _ok(ok=False, error=f"GitHub returned HTTP {e.code}")
    except Exception as e:
        return _ok(ok=False, error=str(e))
    err = res.get("error")
    if err == "authorization_pending":
        return _ok(ok=True, pending=True)
    if err == "slow_down":
        return _ok(ok=True, pending=True, slow_down=True)
    if err in ("access_denied", "expired_token"):
        return _ok(ok=False, error=err)
    if err:
        return _ok(ok=False, error=err)
    # Authorized exactly once per device flow.
    try:
        githubapp.save_token(res["access_token"], res.get("scope"))
    except OSError as e:
        return _ok(ok=False, error=f"could not save the token: {e}")
    return _ok(ok=True, authorized=True)


@endpoint("logs/report/file")
def _report_file(parts, q):
    title = (q.get("title") or "").strip()[:250]
    body = (q.get("body") or "").strip()[:8000]
    if not title or not body:
        return _ok(ok=False, error="title and body are required")
    tok = githubapp.load_token()
    if not tok:
        return _ok(ok=False, error="not authorized — run the device flow first")
    try:
        issue = githubapp.create_issue(tok, title, body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        return _ok(ok=False, error=f"GitHub rejected the issue (HTTP {e.code}): {detail}")
    except Exception as e:
        return _ok(ok=False, error=str(e))
    return _ok(ok=True, number=issue.get("number"),
               url=issue.get("html_url"),
               title=issue.get("title") or title)


@endpoint("logs/report/status")
def _report_status(parts, q):
    return _ok(authorized=githubapp.has_token())


@endpoint("logs/report/forget")
def _report_forget(parts, q):
    githubapp.forget_token()
    return _ok(ok=True)

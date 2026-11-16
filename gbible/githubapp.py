"""GitHub reporting for the Logs pane.

A device authorization flow: the reader starts a one-time authorization on
github.com/login/device, approves G-Bible there, and the app then files issues
as them.  No app-wide credential is stored — the token issued to this app is
the reader's choice of scope, never shared with anyone, and kept only on this
machine.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error

from . import db

CLIENT_ID = "Ov23lin12GGlN4j3tEE4"
ISSUES_REPO = "blackclover5/G-Bible"
ISSUES_URL = f"https://api.github.com/repos/{ISSUES_REPO}/issues"
CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"

SCOPE = "public_repo"          # narrowest reporting-capable scope for OAuth apps
UA = "G-Bible/1.0 (+local Bible study app)"

# Once authorized, GitHub access goes through this file — held in the app
# directory, same file discipline as the API credentials.
_TOKEN_FILE = "github-token.json"


def start_device_code() -> dict:
    body = json.dumps({"client_id": CLIENT_ID, "scope": SCOPE}).encode()
    req = urllib.request.Request(CODE_URL, data=body,
        headers={"Content-Type": "application/json",
                 "Accept": "application/json",
                 "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def poll_access_token(device_code: str) -> dict:
    body = json.dumps({
        "client_id": CLIENT_ID,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body,
        headers={"Content-Type": "application/json",
                 "Accept": "application/json",
                 "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _token_path():
    return db.app_dir() / _TOKEN_FILE


def save_token(access_token: str, scope: str | None = None) -> None:
    p = _token_path()
    data = {"access_token": access_token, "scope": scope or SCOPE,
            "saved_at": time.time()}
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except Exception:
        try:
            os.unlink(str(p))
        except OSError:
            pass
        raise


def load_token() -> str | None:
    try:
        data = json.loads(_token_path().read_text(encoding="utf-8"))
        tok = data.get("access_token")
        return str(tok) if tok else None
    except Exception:
        return None


def forget_token() -> None:
    try:
        _token_path().unlink()
    except FileNotFoundError:
        pass


def has_token() -> bool:
    return bool(load_token())


def create_issue(access_token: str, title: str, body: str) -> dict:
    payload = json.dumps({"title": title, "body": body}).encode()
    req = urllib.request.Request(ISSUES_URL, data=payload,
        headers={"Content-Type": "application/json",
                 "Accept": "application/vnd.github+json",
                 "Authorization": "Bearer " + access_token,
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())

"""In-place application updates from the project's own source release.

The old "Check for Updates" button opened a browser on the latest release's
AppImage: a new, separate application for the reader to install by hand.  This
module updates the *current* installation instead.  It downloads the source
archive that every GitHub release publishes, stages it, and copies only app
source files over this tree.  The reader's database, modules, backups, virtual
environment and credentials are never touched, and every file that is replaced
is saved first so the update can be undone.

Nothing here runs automatically.  ``check`` is a read; ``prepare`` downloads;
``apply`` is called only after the reader explicitly confirms.
"""
from __future__ import annotations

import email.utils
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from . import db

REPO = "blackclover5/G-Bible"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
_ROOT = Path(__file__).resolve().parent.parent
_STAGE = db.app_dir() / "update-staging"

_CACHE: dict = {}
_TTL = 3600                     # unauthenticated GitHub API: 60 requests/hour
_MAX_SOURCE_BYTES = 40 * 1024 * 1024

#: Never written by an update.  These are the reader's, not the app's.
PROTECTED = ("data", ".venv", ".git", "__pycache__", "node_modules")


def _version(v: str) -> tuple:
    parts = re.split(r"[.\-+]", str(v or "").strip().lstrip("vV"))
    out = []
    for p in parts[:3]:
        out.append(int(p) if p.isdigit() else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def _retry_delay(value: str | None, default: float) -> float:
    """Honour Retry-After in either seconds or HTTP-date form."""
    if not value:
        return default
    try:
        return min(30.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
        now = email.utils.parsedate_to_datetime(
            email.utils.formatdate(usegmt=True))
        return min(30.0, max(0.0, (when - now).total_seconds()))
    except Exception:  # noqa: BLE001
        return default


def _open(url: str, *, timeout: int = 20, headers: dict | None = None):
    """Open a URL with bounded retries for transient network failures."""
    hdrs = {"User-Agent": "G-Bible-Updater",
            "Accept": "application/vnd.github+json"}
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(4):
        if attempt:
            time.sleep(min(8.0, 1.5 * attempt))
        try:
            req = urllib.request.Request(url, headers=hdrs)
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            last = exc
            limited = (exc.code == 429 or 500 <= exc.code < 600
                       or (exc.code == 403
                           and exc.headers.get("X-RateLimit-Remaining") == "0"))
            if not limited:
                break
            time.sleep(_retry_delay(exc.headers.get("Retry-After"), 1.5 * attempt))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
    raise last


def _get(url: str, timeout: int = 20) -> bytes:
    with _open(url, timeout=timeout) as r:
        return r.read()


def _download(url: str, dest: Path, max_bytes: int, timeout: int = 90) -> int:
    """Stream a download to ``dest``, resuming from a partial file."""
    tmp = dest.with_name(dest.name + ".part")
    size = tmp.stat().st_size if tmp.is_file() else 0
    if size > max_bytes:
        tmp.unlink(missing_ok=True)
        size = 0
    last = None
    for attempt in range(4):
        try:
            headers = {"Range": f"bytes={size}-"} if size else None
            with _open(url, timeout=timeout, headers=headers) as r:
                if size and getattr(r, "status", 200) != 206:
                    size = 0
                ctype = (r.headers.get("Content-Type") or "").lower()
                if "text/html" in ctype:
                    raise ValueError("the release server returned a web page")
                with open(tmp, "ab" if size else "wb") as fh:
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError("the download is too large")
                        fh.write(chunk)
            with open(tmp, "rb") as fh:
                if fh.read(2) != b"PK":
                    raise ValueError("the download is not a zip archive")
            tmp.replace(dest)
            return size
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last = exc
            if attempt < 3:
                time.sleep(min(8.0, 1.5 * (attempt + 1)))
    raise last


def current_version() -> str:
    from . import __version__
    return str(__version__)


def check(*, force: bool = False) -> dict:
    """What release is available, and is it newer than this installation."""
    hit = _CACHE.get("release")
    if (not force and hit and time.time() - hit["at"] < _TTL):
        return dict(hit["data"], cached=True)
    try:
        raw = _get(API)
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"Could not reach the release list: {exc}"}
    tag = str(data.get("tag_name") or "")
    latest = tag.lstrip("vV")
    current = current_version()
    notes = str(data.get("body") or "").strip()
    if len(notes) > 900:
        cut = notes.rfind(" ", 0, 900)
        notes = notes[:cut if cut > 300 else 900].rstrip() + "\u2026"
    out = {
        "ok": True,
        "current": current,
        "latest": latest,
        "tag": tag,
        "available": bool(latest) and _version(latest) > _version(current),
        "notes": notes,
        "published": str(data.get("published_at") or "")[:10],
        "page_url": str(data.get("html_url") or ""),
        "source_url": str(data.get("zipball_url") or ""),
    }
    _CACHE["release"] = {"at": time.time(), "data": out}
    return dict(out, cached=False)


def _safe_root(zf: zipfile.ZipFile) -> str:
    """The single top folder in a GitHub source archive."""
    names = [n for n in zf.namelist() if not n.endswith("/")]
    tops = {n.split("/", 1)[0] for n in names if "/" in n}
    if len(tops) != 1:
        raise ValueError("the source archive has no single top folder")
    top = tops.pop()
    expected = (f"{top}/run.py", f"{top}/gbible/__init__.py",
                f"{top}/gbible/web/index.html")
    names_set = set(zf.namelist())
    if not all(e in names_set for e in expected):
        raise ValueError("the archive is not a G-Bible source release")
    return top + "/"


def prepare(tag: str) -> dict:
    """Download and stage a validated source archive for ``tag``."""
    # Cached release data may be an hour old.  Re-check before staging so a
    # newly published release is not refused as "no longer the latest".
    rel = check(force=True)
    if not rel.get("ok"):
        return rel
    if tag != rel.get("tag"):
        return {"ok": False, "error": "that release is no longer the latest"}
    if not rel.get("available"):
        return {"ok": False, "error": "this release is already installed"}
    url = rel.get("source_url")
    if not url.startswith("https://"):
        return {"ok": False, "error": "the source URL is not HTTPS"}
    dest = _STAGE / tag
    try:
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        archive = dest / "source.zip"
        downloaded = _download(url, archive, _MAX_SOURCE_BYTES, timeout=90)
    except Exception as exc:
        return {"ok": False, "error": f"Could not download the source: {exc}"}
    try:
        with zipfile.ZipFile(archive) as zf:
            prefix = _safe_root(zf)
            # A compressed blob can be small while expanding to gigabytes.
            # Bound both each member and the whole archive before extracting.
            total = sum(i.file_size for i in zf.infolist()
                        if i.filename.startswith(prefix))
            if total > 200 * 1024 * 1024:
                raise ValueError("the source archive expands beyond 200 MiB")
            if any(i.file_size > 40 * 1024 * 1024 for i in zf.infolist()
                   if i.filename.startswith(prefix)):
                raise ValueError("a file in the source archive is too large")
            for info in zf.infolist():
                name = info.filename
                if not name.startswith(prefix):
                    continue
                rel_path = name[len(prefix):]
                if not rel_path or rel_path.endswith("/"):
                    continue
                target = (dest / "src" / rel_path).resolve()
                if not target.is_relative_to(dest.resolve()):
                    raise ValueError("the archive contains a path outside its folder")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(info))
    except Exception as exc:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        return {"ok": False, "error": f"Could not stage the source: {exc}"}
    src = dest / "src"
    files = [p for p in src.rglob("*") if p.is_file()]
    return {"ok": True, "tag": tag, "files": len(files),
            "bytes": downloaded, "staged": str(src)}


def _protected(rel: str) -> bool:
    parts = Path(rel).parts
    if any(p in PROTECTED for p in parts):
        return True
    if any(p.endswith((".pyc", ".pyo")) for p in parts):
        return True
    return False


def _schedule_restart() -> None:
    """Start a fresh process with the same arguments, then leave this one.

    Delayed so the HTTP response (and its CSRF token) reaches the browser first.
    Set GBIBLE_NO_RESTART=1 to apply files without restarting, for tests.
    """
    if os.environ.get("GBIBLE_NO_RESTART") == "1":
        return

    def worker():
        time.sleep(0.5)
        try:
            cmd = "sleep 1; exec " + " ".join(
                shlex.quote(a) for a in
                [sys.executable, str(_ROOT / "run.py"), *sys.argv[1:]])
            subprocess.Popen(["sh", "-c", cmd], cwd=str(_ROOT),
                             start_new_session=True,
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception:
            pass
        # Leave the port before the replacement process tries to bind it.
        os._exit(0)

    threading.Thread(target=worker, daemon=True).start()


def apply(tag: str, *, confirm: str = "") -> dict:
    """Copy staged source files into this installation, with a full backup."""
    if confirm != "APPLY":
        return {"ok": False, "error": "confirmation required"}
    rel = check()
    if not rel.get("ok") or tag != rel.get("tag"):
        return {"ok": False, "error": "the staged release is no longer current"}
    src = _STAGE / tag / "src"
    if not src.is_dir():
        return {"ok": False, "error": "nothing has been staged for that release"}
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = db.app_dir() / "backups" / f"app-update-{stamp}"
    manifest = {"tag": tag, "at": time.time(), "new": [], "replaced": [],
                "unchanged": [], "protected": [], "backup": str(backup)}
    try:
        backup.mkdir(parents=True, exist_ok=True)
        plan = []
        # Decide and back up everything first.  Writing the manifest before any
        # target is touched means a partial copy is still recoverable.
        for path in sorted(src.rglob("*")):
            if not path.is_file():
                continue
            target_rel = path.relative_to(src).as_posix()
            if _protected(target_rel):
                manifest["protected"].append(target_rel)
                continue
            target = _ROOT / target_rel
            new_bytes = path.read_bytes()
            if target.is_file() and target.read_bytes() == new_bytes:
                manifest["unchanged"].append(target_rel)
                continue
            if target.exists():
                saved = backup / target_rel
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
                manifest["replaced"].append(target_rel)
            else:
                manifest["new"].append(target_rel)
            plan.append((target_rel, target, new_bytes))
        (backup / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        written = []
        for target_rel, target, new_bytes in plan:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(new_bytes)
            written.append((target_rel, target))
    except Exception as exc:
        # Undo whatever was copied before the failure, so the tree is either
        # updated or unchanged -- never a half-updated app with no manifest.
        for target_rel, target in locals().get("written", []):
            try:
                saved = backup / target_rel
                if saved.is_file():
                    shutil.copy2(saved, target)
                elif target.is_file():
                    target.unlink()
            except Exception:
                pass
        return {"ok": False, "error": f"Could not apply the update: {exc}",
                "backup": str(backup)}
    shutil.rmtree(_STAGE / tag, ignore_errors=True)
    _CACHE.clear()
    _schedule_restart()
    applied = len(manifest["new"]) + len(manifest["replaced"])
    return {"ok": True, "tag": tag,
            "applied": applied,
            "unchanged": len(manifest["unchanged"]),
            "protected": len(manifest["protected"]),
            "backup": str(backup),
            "restarting": os.environ.get("GBIBLE_NO_RESTART") != "1"}


def rollback(tag: str) -> dict:
    """Restore the backup made by ``apply`` (manual recovery)."""
    folders = sorted((db.app_dir() / "backups").glob("app-update-*"))
    if not folders:
        return {"ok": False, "error": "no application update backup found"}
    chosen = None
    for folder in reversed(folders):
        mp = folder / "manifest.json"
        if not mp.is_file():
            continue
        try:
            man = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not tag or man.get("tag") == tag:
            chosen = (folder, man, mp)
            break
    if chosen is None:
        return {"ok": False, "error":
                ("no backup found for that release" if tag
                 else "no application update backup found")}
    folder, manifest, manifest_path = chosen
    restored = removed = 0
    for rel in manifest.get("replaced", []):
        saved = folder / rel
        if not saved.is_file():
            continue
        target = _ROOT / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(saved, target)
        restored += 1
    # Files the update introduced have no saved copy; removing them is the
    # only way to put the tree back as it was.
    for rel in manifest.get("new", []):
        target = _ROOT / rel
        if target.is_file():
            target.unlink()
            removed += 1
    _schedule_restart()
    return {"ok": True, "from": manifest.get("tag", ""),
            "restored": restored, "removed_new": removed}

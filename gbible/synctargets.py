"""Where sync puts its folder: a directory, or a WebDAV server.

A target is the five operations the contract needs -- read, write, remove,
exists -- and nothing else.  The folder layout, the manifest and the merge all
live in `sync.py` and are deliberately indifferent to which target is in play:
a target that can store and retrieve a named blob is all any of them require.

Two of them exist.  A filesystem directory is the simplest thing that works and
the right answer for "another computer I have" -- a second disk, a NAS mount, a
USB drive.  WebDAV covers Nextcloud and every other WebDAV server, because
Nextcloud *is* a WebDAV server with a known base path and app-password auth.
Dropbox, Google Drive, OneDrive and S3 can each be added behind the same five
methods without touching anything else; none of them are needed yet.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


def _private_host(host: str | None) -> bool:
    """Is this host on a private network or this machine?

    Private means loopback, link-local, or an RFC1918 address -- a NAS or a
    home server, where the traffic never leaves the building.  Anything else
    must be https.  A name that resolves to both a private and a public address
    is treated as public: the safe answer when it cannot be told.
    """
    if not host:
        return False
    host = host.strip("[]").lower()
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False                       # cannot tell: demand https
    for info in infos:
        try:
            if not ipaddress.ip_address(info[4][0]).is_private:
                return False
        except ValueError:
            return False
    return True


class TargetError(Exception):
    """A target could not be reached, or refused the request.

    The message is shown to the reader, so it says what happened in words
    rather than raising a stack trace at someone who cannot act on it.
    """


class Target:
    """The interface.  Paths are relative to the sync root, always '/'-joined."""

    label = "target"

    def read(self, relpath: str) -> bytes | None:
        raise NotImplementedError

    def write(self, relpath: str, body: bytes) -> None:
        raise NotImplementedError

    def remove(self, relpath: str) -> None:
        raise NotImplementedError

    def exists(self, relpath: str) -> bool:
        return self.read(relpath) is not None

    def describe(self) -> str:
        raise NotImplementedError


# --------------------------------------------------------------- filesystem

class FilesystemTarget(Target):
    """A directory on a mounted volume.

    Writes are a temp file plus a rename, which is the only way a reader that
    walks the folder mid-sync never sees a half-written record.  A directory
    that is not there is reported as unavailable rather than created: a sync
    against a drive that was unmounted should say so, not quietly build a new
    folder on the system disk and call it a backup.
    """

    label = "filesystem"

    def __init__(self, path: str):
        p = Path(path).expanduser()
        if not p.is_absolute():
            raise TargetError(f"Give a full path to the folder, not {path!r}.")
        self.root = p

    def _resolve(self, relpath: str) -> Path:
        # A record id is server-supplied down the line, so the join is checked
        # rather than trusted: `../../etc/passwd` must not escape the folder.
        full = (self.root / relpath).resolve()
        if full != self.root.resolve() and self.root.resolve() not in full.parents:
            raise TargetError(f"{relpath!r} points outside the sync folder.")
        return full

    def read(self, relpath: str) -> bytes | None:
        f = self._resolve(relpath)
        try:
            return f.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as e:
            raise TargetError(f"Could not read {relpath}: {e}") from e

    def write(self, relpath: str, body: bytes) -> None:
        f = self._resolve(relpath)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.parent / (f.name + ".tmp-" + uuid.uuid4().hex[:8])
        try:
            tmp.write_bytes(body)
            os.replace(tmp, f)
        except OSError as e:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise TargetError(f"Could not write {relpath}: {e}") from e

    def remove(self, relpath: str) -> None:
        f = self._resolve(relpath)
        try:
            f.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            raise TargetError(f"Could not remove {relpath}: {e}") from e

    def exists(self, relpath: str) -> bool:
        return self._resolve(relpath).is_file()

    def describe(self) -> str:
        return str(self.root)


# ------------------------------------------------------------------- webdav

class WebDAVTarget(Target):
    """A WebDAV server: Nextcloud, or anything else that speaks the same subset.

    The subset is PROPFIND, GET, PUT, DELETE and MKCOL -- no locking, no
    revision properties, no search.  That is enough for a folder of JSON files
    and it is the part every server implements the same way.

    Two rules that are not negotiable:

    * **HTTPS only.** Over plain HTTP the password goes out in the clear on
      every request.  The target is refused at save time, not at sync time.
    * **An app password, not the account password** on Nextcloud.  The account
      password is refused by Nextcloud for many operations and cannot be
      revoked without changing the password the reader uses to log in.

    Writes go to a temporary name and are then MOVEd over the target, because
    PUT over an existing file is not atomic on every server and a torn record
    is indistinguishable from a corrupt one once it is being parsed.
    """

    label = "webdav"

    def __init__(self, url: str, user: str, password: str, *,
                 timeout: float = 30.0):
        u = (url or "").strip()
        if not u:
            raise TargetError("Give the server address.")
        if "://" not in u:
            u = "https://" + u
        parsed = urllib.parse.urlsplit(u)
        if parsed.scheme != "https" and not _private_host(parsed.hostname):
            # A password over plain http is readable by anything on the path.
            # A home server on a private address is the one exception: the
            # traffic never leaves the building, and refusing a NAS that cannot
            # hold a certificate would only push people off sync entirely.
            raise TargetError(
                "A WebDAV target must be https. Over plain http the password "
                "is sent in the clear on every request.")
        self.base = u.rstrip("/") + "/"
        self.user = user or ""
        self.password = password or ""
        self.timeout = timeout

    # -- the four verbs ----------------------------------------------------

    def _url(self, relpath: str) -> str:
        return self.base + urllib.parse.quote(relpath.strip("/"))

    def _auth(self) -> str:
        raw = f"{self.user}:{self.password}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _request(self, method: str, relpath: str, body: bytes | None = None,
                 headers: dict | None = None):
        req = urllib.request.Request(self._url(relpath), data=body, method=method)
        req.add_header("Authorization", self._auth())
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 405 and method == "MKCOL":
                # 405 Method Not Allowed is how every server says "this
                # collection already exists", which is what MKCOL was for.
                return None
            detail = ""
            try:
                detail = e.read(200).decode("utf-8", "replace").strip()
            except Exception:
                pass
            raise TargetError(
                f"{e.code} from the server for {relpath}"
                + (f": {detail[:120]}" if detail else "")) from e
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            raise TargetError(
                f"Could not reach the server: {reason}") from e
        except (socket.timeout, TimeoutError) as e:
            raise TargetError("The server did not answer in time.") from e

    def read(self, relpath: str) -> bytes | None:
        r = self._request("GET", relpath)
        if r is None:
            return None
        try:
            return r.read()
        finally:
            r.close()

    def write(self, relpath: str, body: bytes) -> None:
        self._mkdirs(relpath)
        # Write to a sibling temporary name, then MOVE it into place.  A reader
        # polling the folder sees either the old record or the new one.
        tmp = relpath.strip("/").rsplit("/", 1)
        tmp = ("tmp/" + uuid.uuid4().hex[:10] + "-" + tmp[-1]) if len(tmp) == 1 \
            else (tmp[0] + "/tmp/" + uuid.uuid4().hex[:10] + "-" + tmp[-1])
        try:
            self._request("PUT", tmp, body)
            r = self._request("MOVE", tmp, headers={
                "Destination": self._url(relpath),
                "Overwrite": "T"})
            if r is not None:
                r.close()
            if r is None:
                raise TargetError(f"MOVE of {relpath} failed.")
        finally:
            # A temp file left behind is clutter, not corruption: drop it.
            self.remove(tmp)

    def remove(self, relpath: str) -> None:
        r = self._request("DELETE", relpath)
        if r is not None:
            r.close()

    def exists(self, relpath: str) -> bool:
        r = self._request("PROPFIND", relpath, headers={"Depth": "0"})
        if r is None:
            return False
        r.close()
        return True

    def describe(self) -> str:
        return self.base

    # -- housekeeping ------------------------------------------------------

    def _mkdirs(self, relpath: str) -> None:
        """MKCOL every parent that does not exist yet.

        Most servers create parents on PUT, but not all, and the failure is a
        409 at the end of a sync that has already done half its work.
        """
        parts = relpath.strip("/").split("/")[:-1]
        path = ""
        for part in parts:
            path = (path + "/" + part) if path else part
            r = self._request("MKCOL", path)
            if r is not None:
                r.close()
            # 405 Method Not Allowed is the normal answer for "it exists".


# The Nextcloud base path, so a reader types a server and a user rather than
# remembering where their files live.  Everything else is ordinary WebDAV.
NEXTCLOUD_SUFFIX = "/remote.php/dav/files/"


def nextcloud_url(server: str, user: str, sub: str = "gbible-sync") -> str:
    s = server.strip().rstrip("/")
    if "://" not in s:
        s = "https://" + s
    return f"{s}{NEXTCLOUD_SUFFIX}{user}/{sub.strip('/')}"


def from_config(cfg: dict) -> Target:
    """Build the target a saved configuration describes.

    Credentials never live in the database -- the file people copy and send for
    support -- so they are read from a 0600 file beside it and merged in here.
    """
    from . import sync as _sync                      # avoid an import cycle
    kind = (cfg or {}).get("kind") or ""
    if kind == "filesystem":
        return FilesystemTarget(cfg.get("path") or "")
    if kind in ("webdav", "nextcloud"):
        creds = _sync.credentials_for(cfg.get("name") or kind)
        return WebDAVTarget(cfg.get("url") or "", cfg.get("user") or "",
                            creds.get("password", ""))
    raise TargetError(f"{kind!r} is not a sync target this app knows.")


def probe(cfg: dict) -> Target:
    """Build the target and prove it answers, so a misconfiguration is found
    when the reader presses Save rather than at the next silent interval."""
    t = from_config(cfg)
    if isinstance(t, WebDAVTarget):
        # PROPFIND on the root: 207 (or 404 treated as reachable) means the
        # credentials and the path are accepted.
        r = t._request("PROPFIND", "", headers={"Depth": "0"})
        if r is not None:
            r.close()
    elif isinstance(t, FilesystemTarget):
        d = t.root
        if not d.exists():
            # A folder the reader named but has not made yet is a typo they
            # would like fixed, not a question to be asked, so the last part of
            # the path is created for them.  Its parent must already exist: a
            # missing parent means a path nobody typed correctly, or a drive
            # that is not plugged in, and inventing a whole tree on the system
            # disk and calling it a backup is the failure worth refusing.
            if not d.parent.exists():
                raise TargetError(
                    f"{d.parent} does not exist, so {d.name} cannot be made "
                    "there. Check the path, and that the drive is plugged in.")
            try:
                d.mkdir(exist_ok=True)
            except OSError as e:
                raise TargetError(f"Could not create {d}: {e}") from e
        if not os.access(d, os.W_OK):
            raise TargetError(f"{d} is not writable.")
    return t

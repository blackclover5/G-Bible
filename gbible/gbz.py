"""G-Bible's own portable backup: the `.gbz` file.

What it is: a zip archive containing the same record snapshot the sync engine
already writes (``v1/<kind>/<id>.json`` plus ``v1/manifest.json``), plus a
small ``restore/`` section for things that are not sync records —

    restore/manifest.json       this container's own header (format version)
    restore/appearance.json     the client's appearance (localStorage blob)
    restore/ai-settings.json    provider/model/toggles (setting key "ai")
    restore/sync-config.json    the sync target the backup came from
    restore/ai-credentials.json the user's API keys (0600 in the zip)

What it is not: a copy of the library.  Module text, FTS, indexes — none of
that travels.  A restored machine reinstalls modules from the Store; the
backup carries the *list* it expects, so the app can say which ones.

What restore does, deliberately:

    - Deletes only when asked.  By default a tombstone in the backup is
      recorded as skipped; ``restore_gbz(apply_deletes=True)`` applies it to
      records this device knows are older than the delete.
    - Never overwrites.  A record present with different content is kept,
      and reported as a conflict.
    - Only touches study records.  The library's module files and indexes are
      never written here.  The record merge is best-effort and additive apart
      from the opt-in deletes above; appliers commit their own records, so a
      restore is not one atomic transaction.
    - Never overwrites an existing API key.  Missing keys are restored,
      present keys stay yours, and both are reported.

Security note, honestly:

    ``ai-credentials.json`` makes the ``.gbz`` a password-like file.  Ordinary
    exports and sync backups exclude credentials unless the caller explicitly
    opts in and supplies a passphrase.  Sync *passwords* are never in here —
    sync-credentials.json is excluded by design, always.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import urllib.parse
import zipfile
from pathlib import Path

from . import __version__ as APP_VERSION
from . import db
from . import sync as _sync

FORMAT = "gbible-backup/1"
GZB_EXT = ".gbz"
#: The single artefact every sync target stores.  One file, one action.
GBZ_NAME = "gbible-backup.gbz"
MAX_BYTES = 64 * 1024 * 1024          # reading anything bigger is a mistake
MAX_RECORD_BYTES = 16 * 1024 * 1024

_KINDS = set(_sync.KINDS)


class GzError(RuntimeError):
    """Something about the backup is wrong, in words a reader can act on."""


# ------------------------------------------------------------------ helpers

def _filemode(perm: int):
    return (perm & 0o7777) << 16


def _zwrite(zf: zipfile.ZipFile, name: str, data: bytes, perm: int = 0o644) -> None:
    info = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = _filemode(perm)
    zf.writestr(info, data)


def _live_modules() -> set[str]:
    try:
        p = db.db_path()
        conn = db.connect()
        return {r["id"] for r in conn.execute(
            "SELECT id FROM module WHERE installed_at>0")}
    except Exception:
        return set()


def _load_json(raw: bytes, what: str):
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise GzError(f"{what} is not valid JSON: {e}")


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", value or "")[:4]) or (0,)


def _integrity(members: dict[str, tuple[bytes, int]]) -> str:
    """A hash over the record set and its manifest metadata.

    Zip CRCs catch a torn file, but they cannot tell a complete archive that
    had one member swapped for another valid one.  The manifest's tombstones
    drive deletions, so they are hashed too.  The digest itself is excluded
    from the metadata hash to avoid a chicken-and-egg problem.
    """
    h = hashlib.sha256()
    for name in sorted(members):
        if name == "restore/manifest.json":
            continue
        h.update(name.encode("utf-8"))
        h.update(b"\0")
        h.update(hashlib.sha256(members[name][0]).hexdigest().encode("ascii"))
        h.update(b"\0")
    manifest = members.get("restore/manifest.json")
    if manifest:
        meta = _load_json(manifest[0], "restore/manifest.json")
        if isinstance(meta, dict):
            fields = {k: meta.get(k) for k in (
                "format", "schema", "app_version", "tombstones",
                "kinds", "records", "modules_expected")}
            h.update(json.dumps(fields, sort_keys=True,
                                ensure_ascii=False).encode("utf-8"))
    return "sha256:" + h.hexdigest()


def _check_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    out = []
    total = 0
    for info in zf.infolist():
        # A tiny archive can claim enormous uncompressed members; the digest
        # reads every member, so bound the declared sizes before reading.
        if info.file_size > MAX_BYTES:
            raise GzError("a member of this backup is too large to be safe")
        total += info.file_size
        if total > MAX_BYTES * 2:
            raise GzError("this backup expands far beyond its safe size")
        name = info.filename
        if name.endswith("/"):
            continue
        p = Path(name)
        if p.is_absolute() or ".." in p.parts:
            raise GzError("the archive contains a path that points outside itself")
        if not (name.startswith("v1/")
                or name == "restore/manifest.json"
                or name.startswith("restore/")):
            raise GzError(f"unexpected member in the backup: {name!r}")
        out.append(info)
    return out


# ------------------------------------------------------------------ export

def create_gbz(*, appearance: dict | None = None, include_ai: bool = False,
               include_sync_config: bool = True,
               credential_passphrase: str = "") -> dict:
    """Build a .gbz backup.  Returns the archive bytes, its size and counts,
    plus flags describing which optional sections were included."""
    device = _sync.device_id()
    notes: list[str] = []

    # Records are collected from the modules that own them, straight into
    # the zip — no staging folder, no push.
    counts: dict[str, int] = {k: 0 for k in _KINDS}
    seq = 0
    records: dict[str, dict] = {}
    members: dict[str, tuple[bytes, int]] = {}
    expected: list[str] = []
    for kind in sorted(_sync.KINDS):
        try:
            payloads = list((_sync._COLLECTORS[kind])() or [])
        except Exception as e:
            notes.append(f"{kind}: {e}")
            payloads = []
        for p in payloads:
            rid = str(p.get("id") or "")
            if not rid:
                continue
            if kind == "setting" and (p.get("key") or "") == "installed_modules":
                value = p.get("value")
                if isinstance(value, list):
                    expected = [str(m) for m in value]
            seq += 1
            env_rec = _sync._envelope(kind, rid, p,
                                      rev=1,
                                      clock={"dev": device, "ctr": seq})
            rel = _sync.relpath(kind, rid)
            members[rel] = (json.dumps(env_rec, ensure_ascii=False,
                                       sort_keys=True).encode("utf-8"), 0o644)
            records[rid] = {"id": rid, "kind": kind, "key": f"{kind}:{rid}",
                            "rev": 1, "hash": env_rec["hash"], "base": "",
                            "deleted": False,
                            "updated_at": env_rec["updated_at"],
                            "clock": {"dev": device, "ctr": seq}}
            counts[kind] += 1
    total = sum(counts.values())
    members[f"{_sync.FOLDER_VERSION}/{_sync.MANIFEST}"] = (
        json.dumps({"schema": 1, "generated_at": time.time(),
                    "generated_by": device,
                    "records": records}, ensure_ascii=False, sort_keys=True)
        .encode("utf-8"), 0o644)
    env = {"format": FORMAT, "schema": 1,
           "created": time.time(),
           "app_version": APP_VERSION,
           "device": device,
           "records": total,
           "tombstones": _sync.tombstones(),
           "kinds": counts,
           "modules_expected": expected,
           "has_appearance": bool(appearance),
           "has_ai_settings": bool(_settings_or_none("ai")),
           "has_sync_config": bool(_settings_or_none("sync.config")) and
                              include_sync_config,
           "has_ai_credentials": False,
           "has_ai_usage": False,
           "ai_usage_records": 0}

    creds = _read_credentials()
    if include_ai and creds:
        env["has_ai_credentials"] = True
    usage_rows: list[dict] = []
    if include_ai:
        try:
            usage_rows = [dict(r) for r in db.connect().execute(
                "SELECT at, provider, model, kind, prompt_tokens, "
                "completion_tokens, total_tokens, ok "
                "FROM ai_usage ORDER BY id DESC LIMIT 10000")]
            usage_rows.reverse()  # oldest first; restores chronologically
        except Exception:
            usage_rows = []
        if usage_rows:
            env["has_ai_usage"] = True
            env["ai_usage_records"] = len(usage_rows)

    if not include_ai:
        members = {k: v for k, v in members.items()
                   if not k.startswith("v1/ai-chats/")}
        # The v1 manifest was written before this filter.  Drop the entries for
        # records that are no longer in the archive, or it advertises chats
        # nobody can read.
        manifest_name = f"{_sync.FOLDER_VERSION}/{_sync.MANIFEST}"
        manifest = json.loads(members[manifest_name][0])
        manifest["records"] = {
            k: v for k, v in manifest["records"].items()
            if v.get("kind") != "ai-chat"}
        members[manifest_name] = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True)
            .encode("utf-8"), 0o644)
        counts["ai-chat"] = 0
        total = sum(counts.values())

    members["restore/manifest.json"] = (
        json.dumps(env, indent=1, sort_keys=True).encode("utf-8"), 0o644)
    if appearance:
        members["restore/appearance.json"] = (
            json.dumps(appearance, indent=1, sort_keys=True)
            .encode("utf-8"), 0o644)
    ai = _settings_or_none("ai")
    if ai is not None:
        members["restore/ai-settings.json"] = (
            json.dumps(ai, indent=1, sort_keys=True).encode("utf-8"), 0o644)
    if include_sync_config:
        sc = _settings_or_none("sync.config")
        if sc is not None:
            members["restore/sync-config.json"] = (
                json.dumps(sc, indent=1, sort_keys=True).encode("utf-8"),
                0o644)
    if include_ai and creds:
        members["restore/ai-credentials.json"] = (
            json.dumps(creds, indent=1, sort_keys=True).encode("utf-8"),
            0o600)
    if include_ai and usage_rows:
        members["restore/ai-usage.json"] = (
            json.dumps({"rows": usage_rows}, indent=1, sort_keys=True)
            .encode("utf-8"), 0o644)

    # Written last so the digest covers every member that actually shipped.
    env["integrity"] = _integrity(members)
    members["restore/manifest.json"] = (
        json.dumps(env, indent=1, sort_keys=True).encode("utf-8"), 0o644)

    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, (data, perm) in sorted(members.items()):
            _zwrite(zf, name, data, perm)
    filename = time.strftime("gbible-backup-%Y%m%d-%H%M") + GZB_EXT
    data = buf.getvalue()
    if include_ai:
        if not credential_passphrase:
            raise GzError("AI credentials require an encryption passphrase.")
        data = encrypt_gbz(data, credential_passphrase)
    return {"ok": True, "filename": filename,
            "data": data, "size": len(data),
            "counts": counts, "has_ai_credentials":
            bool(env["has_ai_credentials"]),
            "has_appearance": bool(appearance), "notes": notes}


def _settings_or_none(key):
    try:
        v = db.get_setting(key)
    except Exception:
        return None
    return v if isinstance(v, (dict, list)) else v


def _read_credentials() -> dict:
    p = Path(db.app_dir()) / "api-credentials.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _write_credentials(creds: dict, keep_existing_absent: bool = True) -> tuple[int, int]:
    """Merge `creds` into the live credential file.  Live values win; missing
    ones are added.  Returns (added, kept)."""
    live = _read_credentials()
    added = 0
    for k, v in creds.items():
        if k not in live:
            live[k] = v
            added += 1
    kept = len(creds) - added
    p = Path(db.app_dir()) / "api-credentials.json"
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(live, fh)
    return added, kept


# -------------------------------------------------------------- inspection

#: Marker for an encrypted .gbz.  Kept short and ASCII so a reader can tell
#: an encrypted file from a plain one without parsing it.
ENC_MARKER = b"GBZENC1\\n"
ENC_SALT_LEN = 16
ENC_ITERS = 480000


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                      salt=salt, iterations=ENC_ITERS)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def encrypt_gbz(data: bytes, passphrase: str) -> bytes:
    """Encrypt a .gbz payload with a passphrase.  Returns bytes that carry
    their own salt, so the same passphrase on another machine can decrypt."""
    if not passphrase:
        return data
    from cryptography.fernet import Fernet
    salt = os.urandom(ENC_SALT_LEN)
    token = Fernet(_derive_key(passphrase, salt)).encrypt(data)
    return ENC_MARKER + salt + token


def decrypt_gbz(data: bytes, passphrase: str = "") -> bytes:
    """Decrypt if needed.  Plain data passes through unchanged."""
    if not data or not data.startswith(ENC_MARKER):
        return data
    if not passphrase:
        raise GzError("this backup is encrypted; a passphrase is required")
    salt = data[len(ENC_MARKER):len(ENC_MARKER) + ENC_SALT_LEN]
    token = data[len(ENC_MARKER) + ENC_SALT_LEN:]
    from cryptography.fernet import Fernet, InvalidToken
    try:
        return Fernet(_derive_key(passphrase, salt)).decrypt(token)
    except InvalidToken as e:
        raise GzError("could not decrypt this backup: wrong passphrase "
                      "or a damaged file") from e


def is_encrypted(data: bytes) -> bool:
    return bool(data) and data.startswith(ENC_MARKER)


def _open_checked(data: bytes, passphrase: str = "") -> zipfile.ZipFile:
    import io
    if not data:
        raise GzError("the file is empty")
    if len(data) > MAX_BYTES + 1024:
        raise GzError("the file is too large to be a backup")
    data = decrypt_gbz(data, passphrase)
    if len(data) > MAX_BYTES:
        raise GzError("the file is too large to be a backup")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise GzError("that is not a readable zip archive: " + str(e))
    names = {i.filename for i in zf.infolist()}
    if "restore/manifest.json" not in names:
        raise GzError("that is not a G-Bible backup "
                      "(no restore/manifest.json inside)")
    manifest = _load_json(zf.read("restore/manifest.json"), "restore/manifest.json")
    if not isinstance(manifest, dict):
        raise GzError("restore/manifest.json is not an object")
    if manifest.get("format") != FORMAT:
        raise GzError(f"this backup is format {manifest.get('format')!r}; "
                      f"this build reads {FORMAT!r}")
    if int(manifest.get("schema") or 0) > 1:
        raise GzError("this backup is newer than this build of G-Bible")
    infos = _check_members(zf)
    want = manifest.get("integrity")
    if want:
        got = _integrity({i.filename: (zf.read(i.filename), 0) for i in infos})
        if got != want:
            raise GzError("this backup's contents do not match its manifest; "
                          "the file may be damaged or altered")
    return zf


def _archive_conflicts(zf: zipfile.ZipFile) -> list[dict]:
    """Records that differ from this machine's copies, with both hashes.

    Preview needs this before applying anything, so a reader can decide which
    side to keep.  A record that fails its own hash check is not a conflict --
    it is damage, and is left alone.
    """
    live = _local_payloads()
    out: list[dict] = []
    for info in zf.infolist():
        name = info.filename
        if not name.startswith("v1/") or name.endswith("/"):
            continue
        parts = name[len("v1/"):].split("/")
        if len(parts) != 2 or not parts[1].endswith(".json"):
            continue
        kind = next((k for k, v in _sync.KINDS.items()
                     if v == urllib.parse.unquote(parts[0])), None)
        if kind is None:
            continue
        rid = urllib.parse.unquote(parts[1][:-len(".json")])
        rec = _load_json(zf.read(name), name)
        if rec.get("deleted"):
            continue
        payload = rec.get("payload") or {}
        want = rec.get("hash")
        if not want or _sync.payload_hash(payload) != want:
            continue
        local = live.get(rid)
        if local is not None and _sync.payload_hash(local) != want:
            out.append({
                "kind": kind, "id": rid,
                "label": str(payload.get("ref_label")
                             or payload.get("title") or "")[:120],
                "local_hash": _sync.payload_hash(local),
                "backup_hash": want,
            })
            if len(out) >= 50:
                break
    return out


def inspect_gbz(data: bytes, passphrase: str = "") -> dict:
    """Read-only summary: what the backup holds, what this machine has."""
    zf = _open_checked(data, passphrase)
    manifest = _load_json(zf.read("restore/manifest.json"),
                          "restore/manifest.json")
    counts = manifest.get("kinds") or {}
    total = int(manifest.get("records") or 0)
    try:
        expected = [str(m) for m in manifest.get("modules_expected") or []]
    except Exception:
        expected = []
    installed = _live_modules()
    missing = sorted(set(expected) - installed)
    return {"ok": True, "format": manifest.get("format"),
            "created": manifest.get("created"),
            "app_version": manifest.get("app_version") or "",
            "tombstones": len(manifest.get("tombstones") or []),
            "device": manifest.get("device"),
            "records": total,
            "counts": counts,
            "modules_expected": expected,
            "modules_missing": missing,
            "has_appearance": bool(manifest.get("has_appearance")),
            "has_ai_settings": bool(manifest.get("has_ai_settings")),
            "has_sync_config": bool(manifest.get("has_sync_config")),
            "has_ai_credentials": bool(manifest.get("has_ai_credentials")),
            "has_ai_usage": bool(manifest.get("has_ai_usage")),
            "ai_usage_records": manifest.get("ai_usage_records") or 0,
            "has_ai_chats": (manifest.get("kinds") or {}).get("ai-chat", 0) > 0,
            "conflicts": _archive_conflicts(zf)}


# ------------------------------------------------------------------ restore

def _local_payloads() -> dict[str, dict]:
    """rid -> live payload, across all kinds.  Read-only."""
    out: dict[str, dict] = {}
    for kind, fn in _sync._COLLECTORS.items():
        try:
            for p in fn() or []:
                rid = str(p.get("id") or "")
                if rid:
                    out[rid] = p
        except Exception:
            continue
    return out


def _remember(conn, kind: str, rid: str, rec: dict, payload: dict) -> None:
    h = _sync.payload_hash(payload)
    rev = int(rec.get("rev") or 1)
    clock = rec.get("clock") or {}
    conn.execute(
        "INSERT OR REPLACE INTO sync_meta(id,kind,rev,dev,ctr,updated_at,"
        "hash,base) VALUES(?,?,?,?,?,?,?,?)",
        (rid, kind, rev, str(clock.get("dev") or ""),
         int(clock.get("ctr") or 0),
         float(rec.get("updated_at") or time.time()), h,
         rec.get("base") or ""))


def restore_gbz(data: bytes, *, include_ai: bool = False, passphrase: str = "",
                apply_deletes: bool = False) -> dict:
    """Merge a .gbz backup into the live library.

    Additive by default: records are added, differing ones are reported and
    kept local.  With ``apply_deletes=True``, tombstones carried by the backup
    also remove records this device knows are older than the delete.  The
    opt-in matters: an ordinary restore of someone else's full snapshot must
    never be able to erase work just because that record was absent there.
    """
    zf = _open_checked(data, passphrase)
    members = {i.filename: i for i in zf.infolist()}
    if include_ai and not is_encrypted(data):
        if "restore/ai-credentials.json" in members:
            raise GzError("Plaintext backups containing AI credentials cannot be restored.")

    live = _local_payloads()

    applied = existed = conflict = 0
    skipped_unknown = skipped_deleted = failed = 0
    examples: list[str] = []
    conflict_examples: list[dict] = []
    tombstones_applied: list[dict] = []
    tombstones_skipped: list[dict] = []
    per_kind: dict[str, dict] = {}

    conn = db.connect()
    # The appliers own their own commits (they are the same functions the app
    # uses for normal edits), so this cannot be one atomic transaction.  Restore
    # is additive and best-effort: a bad record is reported as failed, and the
    # rest of the archive is still applied.  Do not pretend otherwise with a
    # BEGIN that the first applier would immediately commit.
    try:
        for name in sorted(members):
            if not name.startswith("v1/") or name.endswith("/"):
                continue
            parts = name[len("v1/"):].split("/")
            if len(parts) != 2 or not parts[1].endswith(".json"):
                continue
            kind = next((k for k, v in _sync.KINDS.items()
                         if v == urllib.parse.unquote(parts[0])), None)
            if kind is None:
                skipped_unknown += 1
                continue
            rid = urllib.parse.unquote(parts[1][:-len(".json")])
            raw = zf.read(name)
            if len(raw) > MAX_RECORD_BYTES:
                failed += 1
                continue
            rec = _load_json(raw, name)
            payload = rec.get("payload") or {}
            if rec.get("deleted"):
                skipped_deleted += 1
                continue
            # The manifest carries a hash for every record, but until now
            # nothing checked it: a damaged member with a valid JSON body was
            # applied as though it were the author's text.  Verify before any
            # write and report the record by name.
            want_hash = rec.get("hash")
            if want_hash and _sync.payload_hash(payload) != want_hash:
                failed += 1
                if len(examples) < 8:
                    examples.append(
                        f"{kind} {rid}: record hash does not match its contents")
                continue

            stat = per_kind.setdefault(
                kind, {"applied": 0, "existed": 0, "conflict": 0})
            if kind == "setting":
                key = payload.get("key") or payload.get("id") or ""
                if key == "installed_modules":
                    # Information about the backup machine, not a fact about
                    # this one.  The Store installs modules; we never write
                    # this into the live settings.
                    continue
                if key in _sync.SETTINGS_ALLOWLIST:
                    db.set_setting(key, payload.get("value"))
                    applied += 1
                    stat["applied"] += 1
                else:
                    skipped_unknown += 1
                continue

            local_payload = live.get(rid)
            if local_payload is None:
                try:
                    _sync._APPLIERS[kind](payload)
                    _remember(conn, kind, rid, rec, payload)
                    applied += 1
                    stat["applied"] += 1
                except Exception as e:
                    failed += 1
                    if len(examples) < 5:
                        examples.append(f"{kind} {rid}: {e}")
                continue
            if _sync.payload_hash(local_payload) == rec.get("hash"):
                existed += 1
                stat["existed"] += 1
                continue
            conflict += 1
            stat["conflict"] += 1
            if len(conflict_examples) < 50:
                conflict_examples.append({"kind": kind, "id": rid})

        if apply_deletes:
            env0 = _load_json(zf.read("restore/manifest.json"),
                              "restore/manifest.json")
            deleted = _sync.apply_tombstones(
                conn, env0.get("tombstones") or [])
            tombstones_applied = deleted["applied"]
            tombstones_skipped = deleted["skipped"]
        conn.commit()
    except GzError:
        raise
    except Exception as e:
        raise GzError(f"the restore could not continue: {e}")

    # --- restore/ section -------------------------------------------------
    notes: list[str] = []
    made_by = str(_load_json(zf.read("restore/manifest.json"),
                             "restore/manifest.json").get("app_version") or "")
    if made_by and _version_tuple(made_by) > _version_tuple(APP_VERSION):
        notes.append(
            f"This backup was written by G-Bible {made_by}, newer than this "
            f"build ({APP_VERSION}). Records it does not understand were left "
            "alone; update before relying on it.")
    appearance = None
    if "restore/appearance.json" in members:
        appearance = _load_json(zf.read("restore/appearance.json"),
                                  "restore/appearance.json")

    ai_added = 0
    ai_kept = 0
    if include_ai and "restore/ai-credentials.json" in members:
        want = _load_json(zf.read("restore/ai-credentials.json"),
                          "restore/ai-credentials.json")
        if isinstance(want, dict):
            ai_added, ai_kept = _write_credentials(want)
            notes.append(f"AI keys restored: {ai_added} added, "
                         f"{ai_kept} already set (kept yours).")

    ai_settings = None
    if "restore/ai-settings.json" in members:
        ai_settings = _load_json(zf.read("restore/ai-settings.json"),
                                 "restore/ai-settings.json")
        if isinstance(ai_settings, dict):
            try:
                db.set_setting("ai", ai_settings)
                notes.append("AI provider settings restored.")
            except Exception as e:
                notes.append(f"AI settings could not be restored: {e}")

    if include_ai and "restore/ai-usage.json" in members:
        usage = _load_json(zf.read("restore/ai-usage.json"),
                           "restore/ai-usage.json")
        rows = (usage or {}).get("rows") or [] if isinstance(usage, dict) else []
        try:
            have = db.connect().execute(
                "SELECT COUNT(*) AS n FROM ai_usage").fetchone()["n"]
        except Exception:
            have = -1
        if rows and have == 0:
            conn2 = db.connect()
            try:
                conn2.execute("BEGIN")
                for r in rows:
                    conn2.execute(
                        "INSERT INTO ai_usage(at, provider, model, kind, "
                        "prompt_tokens, completion_tokens, total_tokens, ok) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (r.get("at"), r.get("provider"), r.get("model"),
                         r.get("kind"),
                         int(r.get("prompt_tokens") or 0),
                         int(r.get("completion_tokens") or 0),
                         int(r.get("total_tokens") or 0),
                         1 if r.get("ok", True) else 0))
                conn2.execute("COMMIT")
                notes.append(f"AI usage restored: {len(rows)} records.")
            except Exception as e:
                try:
                    conn2.execute("ROLLBACK")
                except Exception:
                    pass
                notes.append(f"AI usage could not be restored: {e}")
        elif rows and have > 0:
            notes.append(f"AI usage kept as is — this machine already has "
                         f"{have} records, so nothing was added "
                         f"(restoring twice would double-count them).")
        elif not rows:
            pass

    sync_cfg_name = ""
    if "restore/sync-config.json" in members:
        cfg = _load_json(zf.read("restore/sync-config.json"),
                         "restore/sync-config.json")
        if isinstance(cfg, dict):
            try:
                db.set_setting("sync.config", cfg)
                sync_cfg_name = str(cfg.get("path") or cfg.get("url") or cfg.get("name") or "")
                notes.append(
                    "Sync target restored" + (f" ({sync_cfg_name})" if sync_cfg_name else "")
                    + ". The sync password was never in the backup; "
                      "re-enter it in the Sync screen.")
            except Exception as e:
                notes.append(f"Sync target could not be restored: {e}")

    expected = []
    if "restore/manifest.json" in members:
        env = _load_json(zf.read("restore/manifest.json"),
                         "restore/manifest.json")
        expected = [str(m) for m in env.get("modules_expected") or []]
    installed = _live_modules()
    missing = sorted(set(expected) - installed)

    return {"ok": failed == 0,
            "applied": applied, "existed": existed, "conflict": conflict,
            "conflicts": conflict_examples,
            "skipped_unknown": skipped_unknown, "skipped_deleted": skipped_deleted,
            "failed": failed, "errors": examples,
            "tombstones_applied": tombstones_applied,
            "tombstones_skipped": tombstones_skipped,
            "backup_version": made_by,
            "kinds": per_kind,
            "appearance": appearance,
            "ai_keys_added": ai_added, "ai_keys_kept": ai_kept,
            "notes": notes,
            "modules_expected": expected,
            "modules_missing": missing}


def apply_chosen(data: bytes, decisions: list[dict], *,
                 passphrase: str = "") -> dict:
    """Apply only the records the reader chose to take from a backup.

    The client sends ``{kind, id, choice}`` — never record text.  Every chosen
    record is re-read from the archive and re-verified against its own hash, so
    a tampered or damaged member cannot be smuggled in through this path.
    Records left as "mine" are not touched.
    """
    zf = _open_checked(data, passphrase)
    chosen = {(str(d.get("kind")), str(d.get("id")))
              for d in (decisions or [])
              if str(d.get("choice")) == "theirs"}
    if not chosen:
        return {"ok": True, "applied": [], "failed": []}
    conn = db.connect()
    applied: list[dict] = []
    failed: list[dict] = []
    for info in zf.infolist():
        name = info.filename
        if not name.startswith("v1/") or name.endswith("/"):
            continue
        parts = name[len("v1/"):].split("/")
        if len(parts) != 2 or not parts[1].endswith(".json"):
            continue
        kind = next((k for k, v in _sync.KINDS.items()
                     if v == urllib.parse.unquote(parts[0])), None)
        if kind is None:
            continue
        rid = urllib.parse.unquote(parts[1][:-len(".json")])
        if (kind, rid) not in chosen:
            continue
        try:
            rec = _load_json(zf.read(name), name)
            payload = rec.get("payload") or {}
            if rec.get("deleted"):
                continue
            want = rec.get("hash")
            if want and _sync.payload_hash(payload) != want:
                raise GzError("record hash does not match its contents")
            _sync._APPLIERS[kind](payload)
            _remember(conn, kind, rid, rec, payload)
            applied.append({"kind": kind, "id": rid})
        except Exception as e:                            # noqa: BLE001
            failed.append({"kind": kind, "id": rid,
                           "error": f"{type(e).__name__}: {e}"})
    conn.commit()
    return {"ok": True, "applied": applied, "failed": failed}


# -------------------------------------------------------------- base64 out

def gbz_as_base64(payload: dict) -> str:
    return base64.b64encode(payload["data"]).decode("ascii")

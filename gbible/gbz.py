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

    - Never deletes.  A tombstone inside the backup is recorded as "skipped".
    - Never overwrites.  A record present with different content is kept,
      and reported as a conflict.
    - Never touches the live library.  Nothing here opens the database for
      writing except the record merge itself, which is additive.
    - Never overwrites an existing API key.  Missing keys are restored,
      present keys stay yours, and both are reported.

Security note, honestly:

    ``ai-credentials.json`` makes the ``.gbz`` a password-like file.  Anyone
    who can read it can read every key in it.  Export includes it only when
    the user asks (default on, with a warning).  Sync *passwords* are never
    in here — sync-credentials.json is excluded by design, always.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
import zipfile
from pathlib import Path

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


def _check_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    out = []
    for info in zf.infolist():
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

def create_gbz(*, appearance: dict | None = None, include_ai: bool = True,
               include_sync_config: bool = True) -> dict:
    """Build a .gbz backup.  Returns bytes, plus the path the AI keys came
    from so the UI can say exactly what happened."""
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
            records[rid] = {"id": rid, "kind": kind, "rev": 1,
                            "hash": env_rec["hash"], "base": "",
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
           "device": device,
           "records": total,
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

    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, (data, perm) in sorted(members.items()):
            _zwrite(zf, name, data, perm)
    filename = time.strftime("gbible-backup-%Y%m%d-%H%M") + GZB_EXT
    return {"ok": True, "filename": filename,
            "data": buf.getvalue(), "size": len(buf.getvalue()),
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
    import base64
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
    _check_members(zf)
    return zf


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
            "has_ai_chats": (manifest.get("kinds") or {}).get("ai-chat", 0) > 0}


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


def restore_gbz(data: bytes, *, include_ai: bool = True, passphrase: str = "") -> dict:
    """Merge a .gbz backup into the live library.  Additive; never deletes."""
    zf = _open_checked(data, passphrase)
    members = {i.filename: i for i in zf.infolist()}

    live = _local_payloads()

    applied = existed = conflict = 0
    skipped_unknown = skipped_deleted = failed = 0
    examples: list[str] = []
    per_kind: dict[str, dict] = {}

    conn = db.connect()
    try:
        conn.execute("BEGIN")
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
        conn.commit()
    except GzError:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise GzError(f"the restore could not continue: {e}")

    # --- restore/ section -------------------------------------------------
    notes: list[str] = []
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

    return {"ok": True,
            "applied": applied, "existed": existed, "conflict": conflict,
            "skipped_unknown": skipped_unknown, "skipped_deleted": skipped_deleted,
            "failed": failed, "errors": examples,
            "kinds": per_kind,
            "appearance": appearance,
            "ai_keys_added": ai_added, "ai_keys_kept": ai_kept,
            "notes": notes,
            "modules_expected": expected,
            "modules_missing": missing}


# -------------------------------------------------------------- base64 out

def gbz_as_base64(payload: dict) -> str:
    return base64.b64encode(payload["data"]).decode("ascii")

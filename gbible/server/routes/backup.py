"""Backup and restore, via a portable .gbz archive.

Export streams the archive as base64 JSON (same machine, localhost) so the
download is a single user gesture with no separate file-download route to
guard.  Preview writes nothing.  Apply merges additively and never overwrites
a differing record or an existing API key; deletions are applied only when the
caller opts in with ``apply_deletes``.
"""

import base64

from .common import *


def _read_path(q):
    raw = (q.get("path") or "").strip()
    if not raw:
        raise ValueError("no .gbz file selected")
    from pathlib import Path
    from gbible import db
    root = db.app_dir().resolve()
    p = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    if not p.is_relative_to(root):
        raise ValueError("the backup must be inside the G-Bible data folder")
    if not p.is_file():
        raise ValueError(f"not a file: {raw}")
    if p.suffix.lower() != ".gbz":
        raise ValueError("that is not a .gbz backup")
    try:
        if p.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("the file is too large to be a backup")
        return p.read_bytes()
    except OSError as e:
        raise ValueError(f"could not read the file: {e}")


@endpoint("backup/export")
def _backup_export(parts, q):
    from gbible import gbz
    appearance = q.get("appearance")
    if appearance is not None and not isinstance(appearance, dict):
        appearance = None
    include_ai = q.get("include_ai") in (1, "1", True, "true")
    passphrase = str(q.get("passphrase") or "")
    if include_ai and not passphrase:
        return _ok(ok=False, error="Including AI credentials requires an encryption passphrase.")
    if include_ai and len(passphrase) < 12:
        return _ok(ok=False, error="The encryption passphrase must be at least 12 characters.")
    try:
        out = gbz.create_gbz(appearance=appearance,
                             include_ai=include_ai,
                             credential_passphrase=passphrase)
        data = out["data"]
    except Exception as e:
        return _ok(ok=False, error=f"{type(e).__name__}: {e}")
    return _ok(ok=True, filename=out["filename"], size=out["size"],
               data_base64=base64.b64encode(data).decode("ascii"),
               counts=out["counts"],
               has_ai_credentials=out["has_ai_credentials"],
               has_appearance=out["has_appearance"],
               notes=out["notes"])


@endpoint("backup/preview")
def _backup_preview(parts, q):
    from gbible import gbz
    try:
        data = _read_path(q)
        out = gbz.inspect_gbz(data, passphrase=q.get("passphrase", ""))
    except Exception as e:
        return _ok(ok=False, error=str(e))
    return _ok(**out)


@endpoint("backup/apply")
def _backup_apply(parts, q):
    from gbible import gbz
    try:
        data = _read_path(q)
        out = gbz.restore_gbz(data,
                              include_ai=q.get("include_ai") in (1, "1", True, "true"),
                              passphrase=q.get("passphrase", ""),
                              apply_deletes=str(q.get("apply_deletes", "")).lower()
                              in ("1", "true", "yes"))
    except Exception as e:
        return _ok(ok=False, error=str(e))
    return _ok(**out)


@endpoint("backup/apply-chosen")
def _backup_apply_chosen(parts, q):
    """Apply only the differing records the reader chose to take.

    A local file is named by ``path``; without one the configured sync target
    supplies the same archive.  The client sends ids and choices only, never
    record text.
    """
    import json
    from gbible import gbz, synctargets, sync
    try:
        cfg = sync.config()
        if q.get("path"):
            data = _read_path(q)
        else:
            target = synctargets.from_config(cfg)
            data = target.read(gbz.GBZ_NAME)
            if data is None:
                return _ok(ok=False, error="No backup on the sync target yet.")
        decisions = q.get("decisions") or []
        if isinstance(decisions, str):
            try:
                decisions = json.loads(decisions)
            except (ValueError, TypeError):
                decisions = []
        pw = q.get("passphrase") or (
            sync.encryption_passphrase(cfg) if cfg.get("encrypt") else "")
        out = gbz.apply_chosen(data, decisions, passphrase=pw)
    except Exception as e:
        return _ok(ok=False, error=str(e))
    return _ok(**out)

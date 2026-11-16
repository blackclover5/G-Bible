"""Backup and restore, via a portable .gbz archive.

Export streams the archive as base64 JSON (same machine, localhost) so the
download is a single user gesture with no separate file-download route to
guard.  Preview writes nothing.  Apply merges additively — it never deletes
and never overwrites an existing record or API key.
"""

import base64

from .common import *


def _read_path(q):
    raw = (q.get("path") or "").strip()
    if not raw:
        raise ValueError("no .gbz file selected")
    from pathlib import Path
    p = Path(raw).expanduser()
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
    try:
        out = gbz.create_gbz(appearance=appearance,
                             include_ai=bool(q.get("include_ai", True)))
    except Exception as e:
        return _ok(ok=False, error=f"{type(e).__name__}: {e}")
    return _ok(ok=True, filename=out["filename"], size=out["size"],
               data_base64=base64.b64encode(out["data"]).decode("ascii"),
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
                              include_ai=bool(q.get("include_ai", True)),
                              passphrase=q.get("passphrase", ""))
    except Exception as e:
        return _ok(ok=False, error=str(e))
    return _ok(**out)

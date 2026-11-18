from .common import *

@endpoint("sync/status")
def _sync_status(parts, q):
    try:
        return _ok(**sync.status())
    except Exception as e:
        return _ok(ok=False, error=str(e))


@endpoint("sync/configure")
def _sync_configure(parts, q):
    """Save a target, its interval and its network policy.

    The target is probed before it is stored, so a mistyped path or a server
    that refuses the password is found now, by someone who is looking at it,
    rather than at the next silent interval.
    """
    kind = (q.get("kind") or "").strip()
    try:
        if not kind:
            sync.disable()
            return _ok(**{"layout": None}, ok=True, disabled=True)
        cfg = sync.save_config({
            "kind": kind,
            "name": q.get("name") or "",
            "path": q.get("path") or "",
            "url": q.get("url") or "",
            "server": q.get("server") or "",
            "user": q.get("user") or "",
            "password": q.get("password") or "",
            "interval": q.get("interval") or 0,
            "wifi_only": q.get("wifi_only") in (1, "1", True, "true"),
            "encrypt": q.get("encrypt") in (1, "1", True, "true"),
            "passphrase": q.get("passphrase") or "",
            "auto_backup_hours": q.get("auto_backup_hours") or 0,
        })
    except Exception as e:
        return _ok(ok=False, error=str(e))
    return _ok(**{"config": cfg}, **sync.status())


@endpoint("sync/run")
def _sync_run(parts, q):
    """Sync once.  The work happens in this request's thread.

    Annotations are small, so a sync is a handful of files and a manifest, and
    doing it in the request keeps the error on screen where it can be read.  The
    interval worker runs the same function on its own thread; the lock inside
    sync.run() is what stops the two from overlapping.
    """
    force = str(q.get("force", "")).lower() in ("1", "true", "yes")
    try:
        summary = sync.run(force=force)
    except Exception as e:
        return _ok(ok=False, error=str(e))
    return _ok(**summary, **sync.status())


@endpoint("sync/metered")
def _sync_metered(parts, q):
    """Whether the connection can be told to be metered, and what it says."""
    m = sync.metered()
    return _ok(metered=m,
               known=m is not None,
               note="" if m is not None else
               "NetworkManager is not available, so this connection cannot be "
               "checked. Turn 'only over Wi-Fi' off to sync anyway.")


@endpoint("sync/missing_modules")
def _sync_missing_modules(parts, q):
    """List module ids referenced by personal records that aren't installed.

    After a sync from another computer, the personal records travel regardless
    of whether you installed the same modules there — notes still land here,
    they just can't be opened. This is how the sync completion modal tells the
    user honestly which records are orphaned by missing modules.
    """
    tables = [
        ("note", "module_id"), ("highlight", "module_id"),
        ("tag_item", "module_id"), ("collection_item", "module_id"),
        ("passage_item", "module_id"), ("pane", "module_id"),
        ("srs_card", "module_id"), ("word_list_item", "module_id"),
    ]
    conn = db.connect()
    referenced: set[str] = set()
    for name, col in tables:
        try:
            for r in conn.execute(f"SELECT DISTINCT {col} FROM {name} WHERE {col}<>''"):
                v = r[0]
                if v:
                    referenced.add(v)
        except Exception:
            continue
    try:
        installed = {r["id"] for r in conn.execute(
            "SELECT id FROM module WHERE installed_at>0")}
    except Exception:
        installed = set()
    return _ok(missing=sorted(referenced - installed))
@endpoint("sync/restore")
def _sync_restore(parts, q):
    """Restore from the .gbz sitting on the configured target — the same
    file `sync/run` writes.  Works for filesystem and WebDAV/Nextcloud."""
    from gbible import gbz, synctargets
    try:
        cfg = sync.config()
        if not cfg.get("kind"):
            return _ok(ok=False,
                       error="That sync target is not configured yet.")
        target = synctargets.from_config(cfg)
        data = target.read(gbz.GBZ_NAME)
        if data is None:
            return _ok(ok=False,
                       error="No backup on the target yet — press Sync now first.")
        pw = q.get("passphrase") or (sync.encryption_passphrase(cfg) if cfg.get("encrypt") else "")
        if gbz.is_encrypted(data) and not pw:
            return _ok(ok=False,
                       error="This backup is encrypted. Enter the passphrase "
                             "to restore it.")
        out = gbz.restore_gbz(data, include_ai=False, passphrase=pw)
    except Exception as e:
        return _ok(ok=False, error=str(e))
    return _ok(**out)

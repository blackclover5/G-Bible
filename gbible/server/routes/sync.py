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



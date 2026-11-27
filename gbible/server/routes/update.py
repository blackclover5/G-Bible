from .common import *


@endpoint("app/update/check")
def _app_update_check(parts, q):
    from ... import appupdate
    return _ok(**appupdate.check(force=str(q.get("force", "")).lower()
                                 in ("1", "true", "yes")))


@endpoint("app/update/prepare")
def _app_update_prepare(parts, q):
    from ... import appupdate
    try:
        return _ok(**appupdate.prepare(q.get("tag", "")))
    except Exception as e:
        return _ok(ok=False, error=f"{type(e).__name__}: {e}")


@endpoint("app/update/apply")
def _app_update_apply(parts, q):
    from ... import appupdate
    try:
        return _ok(**appupdate.apply(q.get("tag", ""),
                                     confirm=q.get("confirm", "")))
    except Exception as e:
        return _ok(ok=False, error=f"{type(e).__name__}: {e}")


@endpoint("app/update/rollback")
def _app_update_rollback(parts, q):
    from ... import appupdate
    try:
        return _ok(**appupdate.rollback(q.get("tag", "")))
    except Exception as e:
        return _ok(ok=False, error=f"{type(e).__name__}: {e}")

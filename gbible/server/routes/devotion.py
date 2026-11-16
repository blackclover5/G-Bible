from .common import *
from ... import devotion_creator

# --------------------------------------------------------- devotional creator --
# The devotional creator turns a Bible or a chaptered book into a daily
# devotion module.  See gbible/devotion_creator.py for the rules it keeps.
@endpoint("devotion/books")
def _devotion_books(parts, q):
    return _ok(**devotion_creator.books())

@endpoint("devotion/scopes")
def _devotion_scopes(parts, q):
    return _ok(**devotion_creator.scopes((q.get("module_id") or "").strip()))

@endpoint("devotion/mine")
def _devotion_mine(parts, q):
    return _ok(**devotion_creator.mine())

@endpoint("devotion/estimate")
def _devotion_estimate(parts, q):
    weekdays = q.get("weekdays")
    if isinstance(weekdays, str):
        try:
            weekdays = json.loads(weekdays)
        except ValueError:
            weekdays = [x.strip() for x in weekdays.split(",") if x.strip()]
    params = dict(q)
    params["weekdays"] = weekdays or []
    return _ok(**devotion_creator.estimate(params))

@endpoint("devotion/create")
def _devotion_create(parts, q):
    weekdays = q.get("weekdays") or []
    if isinstance(weekdays, str):
        weekdays = [x.strip() for x in weekdays.split(",") if x.strip()]
    params = dict(q)
    params["weekdays"] = weekdays
    return _ok(**devotion_creator.create(params))

@endpoint("devotion/delete")
def _devotion_delete(parts, q):
    return _ok(**devotion_creator.delete({"module_id": (q.get("module_id")
                                                        or "").strip()}))

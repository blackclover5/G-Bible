import uuid

from .common import *

# ------------------------------------------------------------------- store
@endpoint("store/repos")
def _repos(parts, q):
    return _ok(repos=store.repos())


@endpoint("store/sync")
def _store_sync(parts, q):
    only = q.get("repo")
    if only:
        return _ok(**{"result": store.sync(only)})
    return _ok(**store.sync_all())


@endpoint("store/items")
def _store_items(parts, q):
    return _ok(**store.list_items(
        repo=q.get("repo"), lang=q.get("lang"), category=q.get("category"),
        subject=q.get("subject"), search=q.get("q"),
        installed_only=_flag(q.get("installed_only")) if q.get("installed_only") is not None else False,
        sort=q.get("sort", "title"), limit=int(q.get("limit") or 2000),
        slot=q.get("slot") or None))


@endpoint("store/install")
def _store_install(parts, q):
    repo = q.get("repo", "")
    item = q.get("item", "")
    if not item:
        return {"ok": False, "error": "repo and item are required"}
    if not repo:
        # Fall back to the item's own repository when the caller (e.g. the
        # "All repositories" view) did not name one.  Only safe when the item id
        # identifies a single catalogue row.
        from ... import db as _db
        conn = _db.connect()
        rows = conn.execute(
            "SELECT repo_id FROM store_item WHERE item_id=?", (str(item),)
        ).fetchall()
        repos = {r["repo_id"] for r in rows}
        if len(repos) == 1:
            repo = next(iter(repos))
        elif len(repos) > 1:
            return {"ok": False, "error": "item exists in multiple repositories; pick one"}
        else:
            return {"ok": False, "error": "repo and item are required"}
    jid = "job_" + uuid.uuid4().hex[:16]
    # _remember_job takes _job_lock itself.  Calling it inside `with _job_lock:`
    # deadlocked every install outright, because threading.Lock is not
    # reentrant -- the request never returned and the page sat on "starting".
    _remember_job(jid, {"state": "running", "repo": repo, "item": item,
                        "started": time.time(), "message": "starting"})
    tid = f"job_{jid}"

    def work():
        def cb(phase, done=0, total=0, note=""):
            msg = note or (f"{phase} {done}" + (f"/{total}" if total else ""))
            with _job_lock:
                _jobs[jid].update(state="running", message=msg,
                                  phase=phase, done=done, total=total)
            # Deliberately outside the lock above: _prune_jobs() takes the same
            # one, and threading.Lock is not reentrant, so calling it inside
            # would deadlock the very request that reported the problem.
        from ...importers import runner
        real = runner.Progress
        runner.Progress = lambda _tid: cb  # route progress into the job record
        try:
            res = store.install(repo, item, fmt=q.get("format", ""))
            # Report where it landed, so the UI can say "into the commentary
            # pane" rather than making the user go and look.
            try:
                from ... import library as _lib, placement as _pl
                res["placement"] = _pl.describe(_lib.get(res["module_id"]))
            except Exception:
                pass
            with _job_lock:
                _jobs[jid].update(state="done", message="installed",
                                  result=res)
        except Exception as e:
            with _job_lock:
                _jobs[jid].update(state="error",
                                  message=f"{type(e).__name__}: {e}")
            _prune_jobs()          # outside the lock: see _prune_jobs()
            raise
        finally:
            runner.Progress = real

    th = threading.Thread(target=work, daemon=True, name=f"install-{jid}")
    th.start()
    return _ok(job=jid)


@endpoint("store/placement")
def _store_placement(parts, q):
    """Where a catalogue item will go, without installing it."""
    from ... import placement
    r = store.store_item_row(q.get("repo", ""), q.get("item", ""))
    if r is None:
        return {"ok": False, "error": "no such catalogue item"}
    return _ok(placement=placement.preview(
        r["repo_id"], r["item_id"], r["type"] or "Other", r["title"] or ""))


@endpoint("store/job")
def _store_job(parts, q):
    with _job_lock:
        j = dict(_jobs.get(q.get("job", ""), {}))
    if not j:
        return {"ok": False, "error": "no such job"}
    return _ok(job=j)


@endpoint("recommended/status")
def _recommended_status(parts, q):
    from ... import recommended as _rec, db, library
    conn = db.connect()
    total = len(_rec.RECOMMENDED)
    installed = 0
    for repo, item in _rec.RECOMMENDED:
        row = conn.execute(
            "SELECT module_id FROM store_item WHERE repo_id=? AND item_id=?",
            (repo, item)).fetchone()
        if row and row["module_id"]:
            m = library.get(row["module_id"])
            if m and getattr(m, "installed_at", 0):
                installed += 1
    dismissed = db.get_setting("recommended_prompt_dismissed", False)
    return _ok(total=total, installed=installed,
               dismissed=bool(dismissed))


@endpoint("recommended/dismiss")
def _recommended_dismiss(parts, q):
    from ... import db
    db.set_setting("recommended_prompt_dismissed", True)
    return _ok(ok=True)


@endpoint("recommended/cancel")
def _recommended_cancel(parts, q):
    """Ask a running recommendation install to stop after its current item."""
    jid = q.get("job", "")
    with _job_lock:
        job = _jobs.get(jid)
        if not job:
            return {"ok": False, "error": "no such job"}
        if job.get("state") in ("done", "cancelled", "error"):
            return _ok(state=job.get("state"))
        job["cancel_requested"] = True
        job["message"] = "Stopping after the current item…"
    return _ok(state="cancelling")


@endpoint("recommended/install")
def _recommended_install(parts, q):
    from ... import recommended as _rec, store, db
    jid = "job_" + uuid.uuid4().hex[:16]
    _remember_job(jid, {"state": "running", "message": "starting",
                        "done": 0, "total": len(_rec.RECOMMENDED),
                        "failures": []})
    items = list(_rec.RECOMMENDED)

    def work():
        done = 0; skipped = 0; failed = 0
        failures = []
        cancelled = False
        for repo, item in items:
            # An install already in progress is allowed to finish safely; do not
            # begin another item once the user has asked to stop.
            with _job_lock:
                if _jobs.get(jid, {}).get("cancel_requested"):
                    cancelled = True
                    break
            try:
                res = store.install(repo, item)
                if res.get("already"):
                    skipped += 1
                else:
                    done += 1
            except Exception as e:   # noqa: BLE001
                failed += 1
                detail = {"repo": repo, "item": item,
                          "error": f"{type(e).__name__}: {e}"[:500]}
                failures.append(detail)
                # Logging is best-effort: a second SQLite error must not kill
                # the worker and hide the actual installation failure.
                try:
                    db.log_history("recommended-install-failed",
                                   f"{repo}/{item}: {detail['error']}", detail)
                except Exception:
                    pass
            with _job_lock:
                _jobs[jid].update(
                    state="running",
                    message=(f"installed {done}, already present {skipped}, "
                             f"failed {failed}"),
                    done=done + skipped + failed,
                    total=len(items), failures=list(failures))
        # The user explicitly chose Install, then may have chosen Skip. In
        # either case don't immediately reopen the recommendation prompt after
        # the page refreshes; resources can still be installed manually later.
        try:
            db.set_setting("recommended_prompt_dismissed", True)
        except Exception:
            pass
        with _job_lock:
            _jobs[jid].update(
                state="cancelled" if cancelled else "done",
                message=((f"stopped: {done} installed, {skipped} already present, "
                          f"{failed} failed") if cancelled else
                         (f"done: {done} installed, {skipped} already present, "
                          f"{failed} failed")),
                result={"installed": done, "skipped": skipped,
                        "failed": failed, "failures": failures,
                        "cancelled": cancelled},
                failures=failures)
        _prune_jobs()

    th = threading.Thread(target=work, daemon=True,
                          name=f"recommended-{jid}")
    th.start()
    return _ok(job=jid)


@endpoint("store/remove")
def _store_remove(parts, q):
    return _ok(**library.remove_module(q.get("id", "")))


@endpoint("store/repo/remove")
def _store_repo_remove(parts, q):
    """Forget a repository, optionally with the modules it supplied.

    Removal of many modules is slow on a large library, so the actual work runs
    in a background thread and this call returns immediately with the list of
    modules that are being removed.  The Store refreshes afterwards.
    """
    repo_id = q.get("repo", "")
    remove_installed = _flag(q.get("modules"))
    permanent = _flag(q.get("permanent"))
    pv = store.repo_removal_preview(repo_id)
    if not pv.get("ok"):
        return _ok(**pv)
    installed = pv.get("installed", []) if remove_installed else []

    # Drop the catalogue and (if permanent) disable the repo immediately, so
    # the Store stops offering it without waiting for module deletion.
    try:
        store.remove_repo(repo_id, remove_installed=False, permanent=permanent,
                         allow_installed=True)
    except Exception as exc:                     # noqa: BLE001
        traceback.print_exc()
        print("repo removal failed:", exc, flush=True)
    installed_ids = [m.get("id") for m in installed if m.get("id")]

    def _run():
        if not remove_installed:
            return
        for mid in installed_ids:
            try:
                from gbible import library
                library.remove_module(mid)
            except Exception as exc:             # noqa: BLE001
                print("module removal failed:", mid, exc, flush=True)

    threading.Thread(target=_run, daemon=True).start()
    return _ok(ok=True, repo=repo_id, name=pv.get("name"),
               catalogue_items=pv.get("catalogue_items", 0),
               removed_modules=installed, permanent=permanent,
               background=True)


@endpoint("store/repo/preview")
def _store_repo_preview(parts, q):
    return _ok(**store.repo_removal_preview(q.get("repo", "")))


@endpoint("store/repo/add")
def _store_repo_add(parts, q):
    return _ok(**store.add_repo(
        q.get("url") or q.get("source") or q.get("repo") or "",
        name=q.get("name", "")))


@endpoint("store/transfers")
def _transfers(parts, q):
    return _ok(transfers=workspace.transfers(60),
               history=workspace.history(60))


@endpoint("store/transfers/clear")
def _transfers_clear(parts, q):
    return _ok(**workspace.clear_transfers())


# Aliases, so a caller that names the action differently still reaches it.
@endpoint("store/clear_transfers")
def _store_clear_transfers(parts, q):
    return _ok(**workspace.clear_transfers())


@endpoint("transfers/clear")
def _transfers_clear_bare(parts, q):
    return _ok(**workspace.clear_transfers())


@endpoint("workspace/clear_transfers")
def _workspace_clear_transfers(parts, q):
    return _ok(**workspace.clear_transfers())


# Extra aliases for clear/purge variants a caller might use.
for _alias in ("store/transfers/purge", "store/purge_transfers",
               "transfers/purge", "transfer/clear", "workspace/purge_transfers",
               "workspace/clear_transfer_history", "store/clear_transfer_history"):
    @endpoint(_alias)
    def _clear_alias(parts, q, _a=_alias):
        return _ok(**workspace.clear_transfers())


@endpoint("store/import")
def _store_import(parts, q):
    """Install from a file already on disk -- the 'This computer' path.

    Not confined to the home directory, unlike audio: a module on a USB stick
    at /media is a legitimate thing to install, and that path is not under
    $HOME.  What stands between this and a web page is the Host and Origin
    guard in Handler._guard -- a request from another origin is refused before
    it ever reaches a route.
    """
    path = q.get("path", "")
    if not path or not Path(path).exists():
        return {"ok": False, "error": f"file not found: {path}"}
    from ... import formats
    data = Path(path).read_bytes() if Path(path).is_file() else None
    kind = formats.sniff(data, path=Path(path))
    # A syntax treebank is data with its own licence, unlike a book you typed
    # yourself: UD treebanks are CC BY-SA, Perseus data has its own terms, and
    # "no licence stated" is not a permission. The gate every Store item passes
    # runs here too, before anything is installed.
    extra: dict = {}
    if kind == "conllu":
        from ... import taxonomy as _tax
        lic = (q.get("license") or "").strip()
        ok, why = _tax.redistributable(
            {"license": lic, "year": (q.get("year") or "").strip()})
        if not ok:
            return {"ok": False, "error":
                    f"Treebank refused: {why}. State the licence the treebank "
                    f"was released under (e.g. CC BY-SA 4.0)."}
        extra = {"rights": lic, "year": (q.get("year") or "").strip()}
    # Record the file before installing it.  "This computer" has no catalogue,
    # so without a row of its own the installer has no item to look up and the
    # whole path fails on the first click.
    reg = store.register_local(Path(path), fmt=kind,
                               category=q.get("type", "") or (
                                   "Syntax" if kind == "conllu" else ""),
                               title=q.get("title", ""), extra=extra or None)
    mid = library.slugify(f"local-{reg['item_id']}")
    jid = "local_" + uuid.uuid4().hex[:16]
    _remember_job(jid, {"state": "running", "message": "importing",
                        "started": time.time()})

    def work():
        from ...importers import runner
        try:
            res = store.install("local", reg["item_id"], fmt=kind)
            with _job_lock:
                _jobs[jid].update(state="done", message="imported", result=res)
            _prune_jobs()          # outside the lock: see _prune_jobs()
        except Exception as e:
            with _job_lock:
                _jobs[jid].update(state="error", message=f"{type(e).__name__}: {e}")
    threading.Thread(target=work, daemon=True, name=f"import-{jid}").start()
    return _ok(job=jid, sniffed=kind, item_id=reg["item_id"])


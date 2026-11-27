import uuid
import zipfile

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
        sort=q.get("sort", "title"), limit=_bounded_int(q.get("limit"), 2000),
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

    def work():
        def cb(phase, done=0, total=0, note=""):
            msg = note or (f"{phase} {done}" + (f"/{total}" if total else ""))
            with _job_lock:
                job = _jobs.get(jid)
                if job is None:      # the job was pruned; never abort the install
                    return
                job.update(state="running", message=msg,
                           phase=phase, done=done, total=total)

        try:
            res = store.install(repo, item, fmt=q.get("format", ""),
                                force=_flag(q.get("force")),
                                progress_factory=lambda _tid: cb)
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

    th = threading.Thread(target=work, daemon=True, name=f"install-{jid}")
    th.start()
    return _ok(job=jid)


@endpoint("store/updates")
def _store_updates(parts, q):
    """Which installed resources have a newer catalogue version.

    Two honest answers matter as much as the list.  Seeded modules used to be
    invisible because they had no store_item link; that is repaired here.  And
    a catalogue that records no version cannot be checked at all — reporting
    "up to date" for it would be a guess dressed as a fact.
    """
    from ... import db as _db, library as _lib, store as _store
    conn = _db.connect()
    linked = _store.link_installed_modules()
    mapped = {}
    for r in conn.execute(
            "SELECT repo_id, item_id, title, version, module_id "
            "FROM store_item WHERE module_id IS NOT NULL"):
        mapped[r["module_id"]] = r
    out, unchecked = [], []
    for m in _lib.list_all():
        row = mapped.get(m.id)
        if row is None:
            unchecked.append({"module_id": m.id, "title": m.name,
                              "why": "not linked to a catalogue entry"})
            continue
        available = str(row["version"] or "")
        if not available:
            unchecked.append({"module_id": m.id, "title": m.name,
                              "why": "the catalogue records no version"})
            continue
        def _v(v):
            return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))) or (0,)
        if _v(available) > _v(m.version or ""):
            out.append({"repo": row["repo_id"], "item": row["item_id"],
                        "title": row["title"] or m.name,
                        "installed_version": m.version or "",
                        "available_version": available,
                        "module_id": m.id})
    note = ("Checked " + str(len(mapped)) + " linked resources. "
            + (str(len(unchecked)) + " could not be checked: "
               + ", ".join(sorted({x["why"] for x in unchecked})) + "."
               if unchecked else "Every linked resource records a version."))
    return _ok(updates=out, count=len(out), linked=linked,
               unchecked=len(unchecked), unchecked_examples=unchecked[:8],
               note=note)


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
    from ... import store as _store
    by_repo = {repo: {str(x.get("id")) for x in _store.repo_items(repo)}
               for repo, _ in _rec.RECOMMENDED}
    pairs = [(repo, item) for repo, item in _rec.RECOMMENDED
             if item in by_repo.get(repo, set())]
    total = len(pairs)
    catalogue_missing = total == 0
    installed_ids = {m.id for m in library.list_all()
                     if getattr(m, "installed_at", 0)}
    ph = ",".join("(?,?)" for _ in pairs)
    mapped = {}
    if ph:
        for r in conn.execute(
                "SELECT repo_id,item_id,module_id FROM store_item "
                f"WHERE (repo_id,item_id) IN ({ph})",
                [v for pair in pairs for v in pair]):
            mapped[(r["repo_id"], r["item_id"])] = r["module_id"]
    installed = 0
    for repo, item in pairs:
        # The installer names a module after its repo and item id, so check
        # that first.  The store_item mapping is a fallback, not the source of
        # truth: modules installed by a seed, a restore or a local import have
        # no store_item row, and counting only mapped ones kept the prompt
        # appearing forever even after every recommended module was present.
        if library.slugify(f"{repo}-{item}") in installed_ids:
            installed += 1
            continue
        if mapped.get((repo, item)) in installed_ids:
            installed += 1
    dismissed = db.get_setting("recommended_prompt_dismissed", False)
    return _ok(total=total, installed=installed,
               catalogue_missing=catalogue_missing,
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
    dismiss_on_finish = _flag(q.get("dismiss"))
    _remember_job(jid, {"state": "running", "started": time.time(),
                        "message": "starting",
                        "done": 0, "total": len(_rec.RECOMMENDED),
                        "failures": [],
                        "dismiss_on_finish": dismiss_on_finish})
    items = list(_rec.RECOMMENDED)
    # A seed, a restore or a local import can leave a recommended module on
    # disk without a store_item row.  Link those first, then skip anything
    # already present instead of downloading and indexing it again.
    try:
        store.link_installed_modules()
        from ... import library as _lib
        installed_ids = {m.id for m in _lib.list_all()
                         if getattr(m, "installed_at", 0)}
    except Exception:  # noqa: BLE001
        installed_ids = set()

    def work():
        done = 0; skipped = 0; failed = 0
        failures = []
        cancelled = False
        # Route per-file and per-unit progress into this job.  Without it the
        # bar froze while a 25 MB module downloaded or the Gesenius scan ran.
        from ... import library as _lib

        def cb(phase, done_=0, total_=0, note=""):
            msg = note or (f"{phase} {done_}" + (f"/{total_}" if total_ else ""))
            with _job_lock:
                job = _jobs.get(jid, {})
                if job.get("cancel_requested"):
                    return
                job.update(phase=phase, progress_done=done_,
                           progress_total=total_, failures=list(failures))
                if not job.get("message", "").startswith("Stopping"):
                    job["message"] = msg

        try:
            for repo, item in items:
                if _lib.slugify(f"{repo}-{item}") in installed_ids:
                    skipped += 1
                    with _job_lock:
                        _jobs[jid].update(
                            state="running", done=done + skipped + failed,
                            total=len(items), current=f"{repo}/{item}",
                            message=f"already installed: {repo}/{item}")
                    continue
                # An install already in progress may finish safely, but do not
                # begin another item once the reader has asked to stop.
                with _job_lock:
                    if _jobs.get(jid, {}).get("cancel_requested"):
                        cancelled = True
                        break
                try:
                    res = store.install(repo, item,
                                        progress_factory=lambda _tid: cb)
                    if res.get("already"):
                        skipped += 1
                    else:
                        done += 1
                except Exception as e:   # noqa: BLE001
                    failed += 1
                    detail = {"repo": repo, "item": item,
                              "error": f"{type(e).__name__}: {e}"[:500]}
                    failures.append(detail)
                    try:
                        db.log_history("recommended-install-failed",
                                       f"{repo}/{item}: {detail['error']}", detail)
                    except Exception:
                        pass
                with _job_lock:
                    _jobs[jid].update(
                        state="running", current=f"{repo}/{item}",
                        message=(f"installed {done}, already present {skipped}, "
                                 f"failed {failed}"),
                        done=done + skipped + failed,
                        total=len(items), failures=list(failures))
        except Exception as e:   # noqa: BLE001
            with _job_lock:
                _jobs[jid].update(state="error",
                                  message=f"{type(e).__name__}: {e}")
            raise
        # Dismiss on an explicit choice, and also after a clean run: leaving
        # the checkbox unticked used to bring the same prompt back on every
        # start.  Failures stay retryable on the next launch.
        with _job_lock:
            dismiss_on_finish = bool(
                _jobs.get(jid, {}).get("dismiss_on_finish")
            )
        if dismiss_on_finish or (not cancelled and failed == 0):
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
    jid = "job_" + uuid.uuid4().hex[:16]
    if remove_installed:
        _remember_job(jid, {"state": "running", "started": time.time(),
                            "message": "removing modules", "kind": "repo-remove",
                            "repo": repo_id, "total": len(installed_ids),
                            "done": 0, "failed": []})

    def _run():
        if not remove_installed:
            return
        removed, failed = [], []
        try:
            from gbible import library
            for mid in installed_ids:
                try:
                    library.remove_module(mid)
                    removed.append(mid)
                except Exception as exc:         # noqa: BLE001
                    failed.append({"id": mid,
                                   "error": f"{type(exc).__name__}: {exc}"[:300]})
                with _job_lock:
                    job = _jobs.get(jid)
                    if job is not None:
                        job.update(done=len(removed), failed=list(failed),
                                   message=f"removed {len(removed)} of "
                                   f"{len(installed_ids)} module(s)")
        finally:
            with _job_lock:
                job = _jobs.get(jid)
                if job is not None:
                    job.update(state="done", removed=removed,
                               result={"removed": removed, "failed": failed,
                                       "catalogue_items": pv.get("catalogue_items", 0)},
                               message=f"removed {len(removed)} module(s)"
                               + (f"; {len(failed)} failed" if failed else ""))
            _prune_jobs()

    if remove_installed:
        threading.Thread(target=_run, daemon=True,
                         name=f"repo-remove-{jid}").start()
    return _ok(ok=True, repo=repo_id, name=pv.get("name"),
               catalogue_items=pv.get("catalogue_items", 0),
               removed_modules=installed, permanent=permanent,
               job=jid if remove_installed else "",
               background=bool(remove_installed))


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
    if not path or not Path(path).is_file():
        return {"ok": False, "error": f"not a file: {path}"}
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



# ------------------------------------------------------------------- local browse
# An in-app file browser for the local import flow.  The page cannot see
# absolute paths (browser sandbox), so this endpoint lists directories and
# hands paths back to the page instead.  Read-only: nothing here writes.
@endpoint("store/browse")
def _store_browse(parts, q):
    """List a folder for the in-app file browser.

    Hidden entries (dotfiles and dotfolders) are not shown — navigate the same
    as the OS file manager without a wall of system noise.  `only_ext`, a
    comma-separated allowlist such as `gbz`, restricts the file rows to those
    extensions; folders always show so navigation keeps working.
    """
    raw = (q.get("path") or "").strip()
    if not raw:
        raw = str(Path.home())
    try:
        p = Path(raw).expanduser().resolve()
    except (OSError, ValueError) as e:
        return {"ok": False, "error": "not a usable path: " + str(e)}
    if not p.exists():
        return {"ok": False, "error": "no such path: " + str(p)}
    if not p.is_dir():
        return {"ok": False, "error": "not a directory: " + str(p)}
    show_hidden = str(q.get("show_hidden") or "0").strip().lower() in ("1", "true", "yes")
    only_ext = {e.strip().lower() for e in (q.get("only_ext") or "").split(",")
                if e.strip()}
    entries = []
    try:
        children = list(p.iterdir())
    except PermissionError:
        return {"ok": False, "error": "permission denied: " + str(p)}
    for child in children:
        name = child.name
        if not show_hidden and name.startswith("."):
            continue
        try:
            st = child.stat()
            is_dir = child.is_dir()
        except OSError:
            continue
        ext = Path(name).suffix.lower().lstrip(".") if not is_dir else ""
        if only_ext and not is_dir and ext not in only_ext:
            continue
        e = {"name": name, "path": str(child), "is_dir": bool(is_dir),
             "size": int(st.st_size), "mtime": st.st_mtime}
        if not is_dir:
            e["ext"] = ext
        entries.append(e)
    entries.sort(key=lambda e: (0 if e["is_dir"] else 1, e["name"].lower()))
    return _ok(path=str(p),
               parent=(str(p.parent) if p.parent != p else ""),
               home=str(Path.home()),
               entries=entries)


@endpoint("store/inspect")
def _store_inspect(parts, q):
    """Read-only preview of one importable file, before anything is imported.

    Best effort: it never fails the import, only reports what it could learn.
    """
    raw = (q.get("path") or "").strip()
    p = Path(raw).expanduser()
    if not p.is_file():
        return {"ok": False, "error": "not a file: " + str(p)}
    try:
        st = p.stat()
        size = st.st_size
    except OSError as e:
        return {"ok": False, "error": str(e)}
    from ...formats import sniff
    try:
        with p.open("rb") as fh:
            # ZIP central directories live at the end; a head-only read made
            # USFM and e-Sword archives look like SWORD packages.
            head = fh.read()
            if len(head) > 64 * 1024 * 1024:
                head = head[:262144]
    except OSError:
        head = b""
    try:
        kind = sniff(head, path=p)
    except Exception:
        kind = "unknown"
    info = {"path": str(p), "name": p.name, "size": int(size), "format": kind}
    try:
        if kind == "sword-zip":
            info.update(_preview_sword_zip(p))
        elif kind == "usfm":
            info.update(_preview_usfm(p, head))
        elif kind == "epub":
            info.update(_preview_epub(p))
        elif kind in ("esword9", "esword-legacy", "esword-zip"):
            info.update(_preview_esword(p, kind))
        elif kind == "text":
            info.update(_preview_text(p))
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
    return _ok(**info)


def _preview_sword_zip(p):
    out = {"modules": []}
    with zipfile.ZipFile(p) as zf:
        confs = [n for n in zf.namelist()
                 if n.lower().startswith("mods.d/") and n.lower().endswith(".conf")]
        out["modules"] = confs
        if confs:
            text = zf.read(confs[0]).decode("utf-8", errors="replace")
            import re as _re
            def get(k):
                m = _re.search(r"(?im)^%s\s*=\s*(.+)$" % _re.escape(k), text)
                return m.group(1).strip() if m else ""
            out["title"] = get("ShortTitle") or get("Description") or Path(confs[0]).stem
            out["lang"] = get("Lang")
            about = get("About")
            if about:
                out["description"] = about[:400]
            cp = get("Copyright") or get("CopyrightNotes") or get("CopyRight")
            dist = get("DistributionLicense")
            out["license"] = cp or dist or ""
            out["abbrev"] = get("ModDrv")
            out["version"] = get("Version")
            out["category"] = get("Category")
            out["About"] = about[:400] if about else ""
    return out


def _preview_usfm(p, head):
    out = {}
    for line in head.decode("utf-8", errors="replace").splitlines():
        if line.startswith("\\id "):
            out["abbrev"] = line.split()[1] if len(line.split()) > 1 else ""
            break
    out["title"] = p.stem
    if p.suffix.lower() == ".zip" or p.name.lower().endswith((".zip", ".usfm.zip")):
        try:
            with zipfile.ZipFile(p) as zf:
                books = [n for n in zf.namelist() if n.lower().endswith(".usfm")]
                out["units"] = len(books)
                out["title"] = p.stem + "  (USFM)"
        except Exception:
            pass
    else:
        out["units"] = 1
    return out


def _preview_epub(p):
    import re as _re, xml.etree.ElementTree as ET
    out = {"title": p.stem}
    try:
        with zipfile.ZipFile(p) as zf:
            container = zf.read("META-INF/container.xml").decode("utf-8", errors="replace")
            m = _re.search(r'full-path="([^"]+)"', container)
            if not m:
                return out
            opf = zf.read(m.group(1)).decode("utf-8", errors="replace")
            root = ET.fromstring(opf)
            ns = {"opf": "http://www.idpf.org/2007/opf",
                  "dc": "http://purl.org/metadata/dublin_core"}
            def txt(tag):
                el = root.find(f".//dc:{tag}", ns)
                return (el.text or "").strip() if el is not None else ""
            out["title"] = txt("title") or out["title"]
            out["author"] = txt("creator")
            out["lang"] = txt("language")
            out["publisher"] = txt("publisher")
            out["license"] = txt("rights")
            out["description"] = txt("description")[:300]
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def _preview_esword(p, kind):
    out = {"title": p.stem}
    ext = p.suffix.lower().lstrip(".")
    kind_guess = {
        "bbl": "Bible", "bblx": "Bible",
        "cmt": "Commentary", "cmtx": "Commentary", "dev": "Devotional",
        "dct": "Dictionary", "dctx": "Dictionary", "bmap": "Map",
        "mapx": "Map", "mybible": "Bible", "notx": "Note", "brpx": "Biography",
        "harx": "Harmony", "bzz": "Bible", "bzs": "Bible", "bzu": "Bible",
    }.get(ext, "Book")
    out["category"] = kind_guess
    if kind == "esword9":
        try:
            import sqlite3
            conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            try:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                out["tables"] = [r[0] for r in rows]
                for cand in ("Entries", "Verses", "Articles", "Tsk", "Maps"):
                    if cand in out["tables"]:
                        try:
                            out["units"] = conn.execute(f"SELECT COUNT(*) FROM {cand}").fetchone()[0]
                        except Exception:
                            pass
                        break
                try:
                    meta = conn.execute("SELECT Name, Description FROM Details LIMIT 1").fetchone()
                    if meta:
                        out["title"] = meta[0] or out["title"]
                        if meta[1]:
                            out["description"] = meta[1]
                except Exception:
                    pass
            finally:
                conn.close()
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
    return out


def _preview_text(p):
    out = {}
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            data = fh.read(262144)
        text = data.decode("utf-8", errors="replace")
        lines = text.count("\n") + 1
        out["units"] = lines
        out["size"] = int(size)
    except Exception:
        pass
    return out


# Import every importable file in a folder (optionally recursively).  The files
# land in "This computer" and are installed exactly as if imported one by one.
@endpoint("store/folder")
def _store_folder(parts, q):
    raw = (q.get("path") or "").strip()
    if not raw:
        return {"ok": False, "error": "no path"}
    p = Path(raw).expanduser()
    if not p.is_dir():
        return {"ok": False, "error": "not a directory: " + str(p)}
    recursive = str(q.get("recursive", "")).lower() in ("1", "true", "yes")
    from ... import formats as _fmt
    ext_ok = {
        "zip", "bzz2", "bbl", "bblx", "cmt", "cmtx", "dct", "dctx", "dev",
        "bmap", "mybible", "epub", "usfm", "usfx", "osis", "txt", "md",
        "kmz", "kml", "jpg", "jpeg", "png", "svg", "gif", "tif", "tiff",
        "htm", "html", "wiki", "wikitext", "notx", "brpx", "memx", "prlx",
        "harx", "lstx", "ovlx", "bzs", "bzu", "bzz", "mapx", "conllu",
    }
    files = []
    it = p.rglob("*") if recursive else p.iterdir()
    for child in it:
        if not child.is_file() or child.name.startswith("."):
            continue
        ext = Path(child.name).suffix.lower().lstrip(".")
        try:
            size = child.stat().st_size
        except OSError:
            continue
        if size <= 0 or size > 4 * 1024 * 1024 * 1024:
            continue
        if ext not in ext_ok:
            continue
        # For archives, sniff the outer name only -- reading every archive in a
        # folder of thousands to test them costs real time.
        files.append({"name": child.name, "path": str(child),
                      "size": int(size),
                      "format": "sword-zip" if ext == "zip" else (
                          "esword9" if ext.endswith("x") and ext != "usfx" else {
                              "bbl": "esword-legacy", "cmt": "esword-legacy",
                              "dct": "esword-legacy", "usfm": "usfm",
                              "usfx": "usfx", "osis": "osis",
                              "epub": "epub", "txt": "text", "md": "text",
                              "kml": "osm-kml", "kmz": "osm-kml",
                          }.get(ext, ext))})
    files.sort(key=lambda f: f["name"].lower())
    total = sum(f["size"] for f in files)
    return _ok(path=str(p), files=files, total=len(files), size=int(total))


@endpoint("store/import-folder")
def _store_import_folder(parts, q):
    paths = q.get("paths") or []
    if isinstance(paths, str):
        paths = [x for x in paths.split("|") if x]
    files = []
    for raw in paths:
        p = Path(str(raw)).expanduser()
        if p.is_file():
            files.append(str(p))
    if not files:
        return {"ok": False, "error": "no files to import"}
    jid = "job_" + uuid.uuid4().hex[:16]
    _remember_job(jid, {"state": "running", "message": "importing files",
                        "started": time.time(), "total": len(files), "done": 0,
                        "failed": 0, "folder": True})

    def work():
        from ...importers import runner
        imported, failed, skipped = 0, [], 0
        try:
            for i, path in enumerate(files, start=1):
                with _job_lock:
                    if _jobs.get(jid, {}).get("cancel_requested"):
                        break
                base = Path(path)
                try:
                    from ... import formats as _formats, taxonomy as _tax
                    if _formats.sniff(base.read_bytes(), path=base) == "conllu":
                        lic = (q.get("license") or "").strip()
                        year = (q.get("year") or "").strip()
                        ok, why = _tax.redistributable({"license": lic,
                                                        "year": year})
                        if not ok:
                            raise ValueError(
                                f"Treebank refused: {why}. State its licence.")
                    reg = store.register_local(base)
                    res = store.install("local", reg["item_id"])
                    if res.get("already"):
                        skipped += 1
                        msg = f"already present: {base.name}"
                    else:
                        imported += 1
                        msg = f"imported {imported} of {len(files)}: {base.name}"
                except Exception as e:
                    failed.append({"path": path,
                                   "error": f"{type(e).__name__}: {e}"[:300]})
                    msg = f"failed: {base.name}"
                with _job_lock:
                    _jobs[jid].update(state="running", message=msg,
                                      done=imported, skipped=skipped,
                                      failed_count=len(failed), current=str(base))
        finally:
            with _job_lock:
                if _jobs.get(jid, {}).get("cancel_requested"):
                    _jobs[jid].update(state="cancelled",
                                      message=f"stopped after {imported} imports",
                                      done=imported, skipped=skipped, failed=failed)
                else:
                    _jobs[jid].update(state="done",
                                      message=f"imported {imported} of {len(files)}"
                                      + (f" ({skipped} already present)" if skipped else "")
                                      + (f" ({len(failed)} failed)" if failed else ""),
                                      done=imported, skipped=skipped, failed=failed)
            _prune_jobs()

    threading.Thread(target=work, daemon=True, name=f"import-folder-{jid}").start()
    return _ok(job=jid, total=len(files))

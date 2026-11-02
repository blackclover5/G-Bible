"""Launcher.

    python3 run.py            start the app and open a browser
    python3 run.py --port N   use a different port
    python3 run.py --no-open  do not open a browser
    python3 run.py --check    run the self-test and exit
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gbible import __version__ as _GBIBLE_VERSION


def _use_venv() -> None:
    """Re-exec into .venv if there is one, so the voice can be installed.

    Everything else in this project is standard library, so it runs on whatever
    `python3` happens to be.  The read-aloud voice is the exception: it needs
    onnxruntime, which is a wheel and a download rather than a line of code, so
    it lives in a virtualenv beside the app.  Without this you would have to
    remember to launch with `.venv/bin/python run.py`, and every command in the
    README would need two versions.

    Re-exec rather than a sys.path append: the venv has its own site-packages
    laid out for one interpreter version, and quietly merging another
    interpreter's search path into it is how you get a numpy built for the wrong
    ABI.  Replacing the process with the venv's own python cannot do that.
    Nothing is installed for you -- with no .venv this is a no-op and the app
    falls back to the browser's speech engine.
    """
    if os.environ.get("GBIBLE_VENV"):
        return
    venv = Path(__file__).resolve().parent / ".venv"
    py = venv / "bin" / "python"
    if not py.is_file():
        return
    # Already inside this venv?  Compared as prefixes, not as the executable:
    # a venv's bin/python is a symlink to the base interpreter, so
    # realpath() of the two is the same file by construction and asking
    # "are these the same?" that way is always yes -- which silently meant the
    # re-exec never happened and the voice was never found.
    try:
        if Path(sys.prefix).resolve() == venv.resolve():
            return
    except OSError:
        pass
    env = dict(os.environ, GBIBLE_VENV="1")
    os.execve(str(py), [str(py), str(Path(__file__).resolve()), *sys.argv[1:]], env)


def main() -> int:
    ap = argparse.ArgumentParser(prog="gbible", description="G-Bible")
    ap.add_argument("--port", type=int, default=int(os.environ.get("GBIBLE_PORT", 8777)))
    ap.add_argument("--host", default=os.environ.get("GBIBLE_HOST", "127.0.0.1"))
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--check", action="store_true", help="run the self-test and exit")
    ap.add_argument("--sync", action="store_true", help="refresh the Store catalogues")
    ap.add_argument("--desktop", action="store_true",
                    help="open a native window instead of the system browser")
    args = ap.parse_args()
    desktop = args.desktop or os.environ.get("GBIBLE_DESKTOP") == "1"

    from gbible import db
    db.init()

    if args.sync:
        from gbible import store
        for k, v in store.sync_all().items():
            print(f"  {k:16} {v.get('items', v.get('error'))}")
        return 0

    if args.check:
        from tools.selftest import run
        return 0 if run() else 1

    from gbible.api import registry as apireg
    from gbible import library, store, workspace
    apireg.sync()
    if not any(r["item_count"] for r in store.repos()):
        print("Priming the Store catalogue (one time)...")
        store.sync_all()
    # The library folder moved, or it is the first run.  Recorded module paths
    # are absolute and are written at install time, so a project that has been
    # moved or copied leaves every one of them naming a folder that is no longer
    # there.  Nothing breaks -- the text is in the index and reads normally --
    # but re-indexing a module and adding audio from one both fail, and the
    # stored value is what an export or a support answer would quote.  This is
    # one string comparison per start and nothing at all once it matches.
    try:
        rep = library.repair_paths()
        if rep.get("changed"):
            print(f"Library moved: repointed {rep['changed']} module "
                  f"path(s) at {rep['library_path']}")
    except Exception as exc:                      # never block startup
        print(f"Module path repair skipped: {exc}")
    workspace.bootstrap()

    from gbible.server.app import serve
    try:
        httpd = serve(args.host, args.port)
    except OSError as e:
        print(f"Could not bind {args.host}:{args.port} -- {e}")
        print("Try:  python3 run.py --port 8899")
        return 1

    url = f"http://{args.host}:{args.port}/"
    if desktop:
        print(f"G-Bible {_GBIBLE_VERSION}")
    else:
        print(f"G-Bible {_GBIBLE_VERSION}  ->  {url}")
    print(f"Library: {db.app_dir()}")

    # The genealogy is read out of the Bible text on first use, which takes a
    # few seconds for a large library.  Do it now in the background so the first
    # click on the tab is instant instead of watching "Loading…" for four
    # seconds.  Failure here is not fatal: the endpoint will just build it then.
    def _warm():
        try:
            from gbible import genealogy
            g = genealogy.build()
            if g.get("ok"):
                print(f"Genealogy ready: {g['counts']['people']} people, "
                      f"{g['counts']['edges']} relationships "
                      f"(from {g['source']})")
        except Exception as exc:                      # never block startup
            print(f"Genealogy warm-up skipped: {exc}")
    threading.Thread(target=_warm, daemon=True).start()

    # Same reasoning for the read-aloud voice: loading the model is a 4-5 second
    # one-off, and it belongs off the path a click has to wait on.  Only worth
    # starting if it is actually installed, and failing here is harmless either
    # way -- the front end falls back to the browser's own speech engine.
    def _warm_voice():
        try:
            from gbible import tts
            st = tts.status()
            if st.get("available"):
                print(f"Voice ready: {st['voice']} ({st['model']})")
            else:
                print(f"Read-aloud voice not available: {st.get('reason')}")
        except Exception as exc:                      # never block startup
            print(f"Voice warm-up skipped: {exc}")
    threading.Thread(target=_warm_voice, daemon=True).start()

    # And the search box's spelling hint needs two vocabularies -- the library's
    # words as written, and the surface forms on Strong's markers -- which cost
    # about eight seconds to build between them.  They used to be built
    # inside the hint itself, so the first word typed after a restart froze the
    # tab.  Built here instead, in the background; until they are ready the hint
    # simply stays quiet.
    def _warm_spelling():
        try:
            from gbible import search
            if search.prewarm_spelling(library.list_all()):
                print("Spelling tables ready.", flush=True)
            else:
                print("Spelling warm-up skipped.", flush=True)
        except Exception as exc:                      # never block startup
            print(f"Spelling warm-up skipped: {exc}", flush=True)
    threading.Thread(target=_warm_spelling, daemon=True).start()

    # And the positional index keeps itself current.  An index that has to be
    # rebuilt by hand is a script, not an indexer: installing a book used to
    # leave the index stale until someone remembered the command line, and
    # searches quietly took the slow path in the meantime.  This watches for
    # modules that are missing from the index and folds them in, the way some
    # platforms merge newly indexed books into the library index in the background.
    #
    # It indexes only small catch-ups.  A whole-library rebuild is a quarter of
    # an hour and belongs in tools/build_pos_index.py, so past a budget the
    # worker reports and waits rather than making the app feel broken.
    def _indexer():
        try:
            from gbible import posindex
            w = posindex.BackgroundIndexer().start()
            st = posindex.worker_state()
            # flush=True because the launcher re-execs into the venv, which
            # drops any -u flag, so a redirected stdout is block-buffered and a
            # failure here would otherwise be invisible until exit.
            if st.get("state") == "deferred":
                print(f"Index: {st.get('modules', 0)} module(s) awaiting a "
                      f"full build -- python3 tools/build_pos_index.py",
                      flush=True)
            else:
                print("Index: kept current in the background "
                      "(python3 tools/build_pos_index.py --status)", flush=True)
        except Exception as exc:                      # never block startup
            print(f"Positional indexer not started: {exc}", flush=True)
    threading.Thread(target=_indexer, daemon=True).start()

    desktop = args.desktop or os.environ.get("GBIBLE_DESKTOP") == "1"
    if desktop:
        # Native window mode: serve in the background, open a window, and
        # return when the window closes.  Falls back to the browser if the
        # webview library is not available in this environment.
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        time.sleep(0.5)
        try:
            import webview
            webview.create_window("G-Bible", url, width=1280, height=860)
            webview.start()
        except Exception as exc:
            print(f"Desktop window unavailable ({exc}); opening browser.")
            if not args.no_open:
                webbrowser.open(url)
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nStopped.")
        httpd.shutdown()
        httpd.server_close()
        return 0

    print("Ctrl-C to stop.")
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    _use_venv()
    raise SystemExit(main())

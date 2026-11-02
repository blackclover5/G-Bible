"""Browser-level smoke test for startup, search, and opening a passage."""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(port: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("local server did not start")


def _install_fixture() -> None:
    from gbible import db, workspace

    conn = db.init()
    conn.execute(
        "INSERT INTO module(id,name,type,lang,lang_name,installed_at,chapters,"
        "verses,index_types) VALUES(?,?,?,?,?,?,?,?,?)",
        ("browser-smoke-bible", "Browser Smoke Bible", "Bible", "eng",
         "English", 1, 1, 1, '["bibleVerse"]'),
    )
    conn.execute(
        "INSERT INTO unit(module_id,key,ord,book,chapter,verse,ref_label,text) "
        "VALUES(?,?,?,?,?,?,?,?)",
        ("browser-smoke-bible", "Gen.1.1", 1, "Gen", 1, 1, "Gen 1:1",
         "Browserfixture creation passage."),
    )
    conn.execute(
        "INSERT INTO unit_fts(module_id,unit_key,title,text) VALUES(?,?,?,?)",
        ("browser-smoke-bible", "Gen.1.1", "Gen 1:1",
         "Browserfixture creation passage."),
    )
    conn.commit()
    workspace.bootstrap()


def main() -> int:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="gbible-browser-") as home:
        os.environ["GBIBLE_HOME"] = home
        _install_fixture()
        from gbible.server.app import serve

        port = _free_port()
        server = serve("127.0.0.1", port)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            _wait_for_server(port)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page()
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                response = page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
                assert response and response.status == 200
                page.locator("#status").wait_for()
                page.locator("#status").get_by_text(
                    "1 module", exact=False
                ).wait_for()
                page.get_by_role("button", name="Skip").click()

                page.locator('#nav button[data-view="search"]').click()
                page.locator("#sq").fill("browserfixture")
                page.locator("#s-go").click()
                hit = page.locator("#search-results .hit")
                hit.wait_for()
                assert "Gen 1:1" in hit.inner_text()

                hit.click()
                passage = page.locator("#v-workspace.on .verse").filter(
                    has_text="Browserfixture creation passage."
                )
                try:
                    passage.wait_for(timeout=5000)
                except Exception:
                    state = page.evaluate("""async () => ({
                      workspace: await api('workspace'),
                      modules: (await api('library')).modules,
                      body: document.querySelector('#v-workspace').innerText
                    })""")
                    raise AssertionError(
                        f"passage did not open; browser errors={errors}; state={state}"
                    )
                assert not errors, "browser uncaught errors: " + "; ".join(errors)
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    print("browser startup, search, and open-passage smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

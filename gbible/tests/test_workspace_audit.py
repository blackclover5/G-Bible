"""Workspace regressions from the Workspace audit."""

import os
import shutil
import tempfile
import unittest


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="gbible-ws-")
        self.addCleanup(shutil.rmtree, home, True)
        old = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = home

        def restore():
            if old is None:
                os.environ.pop("GBIBLE_HOME", None)
            else:
                os.environ["GBIBLE_HOME"] = old
        self.addCleanup(restore)
        from gbible import db, workspace
        db.init()
        conn = db.connect()
        self.library = __import__("gbible.library", fromlist=["library"])
        self.library.register(conn, id="tst", name="Test Bible", type="Bible",
                              v11n="KJV", lang="eng", installed_at=1)
        conn.commit()
        self.ws = workspace

    def test_guide_quickstarts_keep_their_pane(self):
        for name in ("Passage Guide", "Exegetical Guide",
                     "Greek Word Study", "Hebrew Word Study"):
            lay = self.ws.build_quickstart(name)
            panes = lay.get("panes") or []
            self.assertTrue(
                any(p.get("view") in ("guide", "wordstudy") for p in panes),
                (name, [p.get("view") for p in panes]))

    def test_save_layout_rejects_missing_and_clamps_text_size(self):
        r = self.ws.save_layout("missing", "x", [[1.0]], [])
        self.assertFalse(r["ok"])
        lay = self.ws.create_layout("valid")
        p = self.ws.add_pane(lay["id"], "", tile_id="t0_0",
                             cursor={}, options={})
        r = self.ws.save_layout(lay["id"], "valid", [[1.0]],
                                [{"id": p.id, "tile_id": "t0_0",
                                  "text_size": 9999}])
        saved = (r.get("panes") or [{}])[0]
        size = saved.get("text_size") if isinstance(saved, dict) else saved.text_size
        self.assertLessEqual(size, 300)

    def test_use_layout_rejects_missing(self):
        self.assertFalse(self.ws.use_layout("missing")["ok"])

    def test_bootstrap_keeps_a_one_pane_workspace(self):
        lay = self.ws.create_layout("Single")
        self.ws.add_pane(lay["id"], "", tile_id="t0_0",
                         cursor={}, options={})
        self.ws.use_layout(lay["id"])
        again = self.ws.bootstrap()
        self.assertEqual(again["id"], lay["id"])

    def test_parallel_step_refuses_removed_module(self):
        g = self.ws.parallel_group("no-such-module")
        self.assertFalse(g["ok"])


if __name__ == "__main__":
    unittest.main()

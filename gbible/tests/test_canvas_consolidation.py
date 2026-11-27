"""The two canvas UIs now share one board model.

Old setting-based canvases must move across without losing a card, an arrow or
an unrecognised element — and the original setting must survive, because a
restore of an older backup may need migrating later.
"""

import json
import os
import shutil
import tempfile
import unittest


def _scratch_home(test_case):
    home = tempfile.mkdtemp(prefix="gbible-test-")
    test_case.addCleanup(shutil.rmtree, home, True)
    old = os.environ.get("GBIBLE_HOME")
    os.environ["GBIBLE_HOME"] = home

    def _restore():
        if old is None:
            os.environ.pop("GBIBLE_HOME", None)
        else:
            os.environ["GBIBLE_HOME"] = old

    test_case.addCleanup(_restore)
    return home


class CanvasConsolidationTests(unittest.TestCase):
    def setUp(self):
        _scratch_home(self)
        from gbible import db
        self.db = db
        self.conn = db.connect()

    def _legacy(self):
        return [{
            "id": "cv_legacy1", "name": "Old board", "updated_at": 1234.0,
            "elements": [
                {"id": "e1", "kind": "heading", "x": 10, "y": 20, "w": 220,
                 "h": 100, "text": "A title"},
                {"id": "e2", "kind": "verse", "x": 0, "y": 0, "w": 220,
                 "h": 100, "text": "For God so loved…", "ref": "John 3:16",
                 "module_id": "kjv"},
                {"id": "e3", "kind": "text", "x": 5, "y": 5, "w": 220,
                 "h": 100, "text": "A note"},
                {"id": "e4", "kind": "arrow", "from": "e1", "to": "e2"},
                {"id": "e5", "kind": "mystery", "x": 1, "y": 2,
                 "text": "kept verbatim"},
            ],
        }]

    def test_legacy_canvas_migrates_without_loss(self):
        from gbible import canvases
        self.db.set_setting("canvases", self._legacy())

        self.assertEqual(canvases.migrate_legacy_canvases(), 1)

        board = self.conn.execute(
            "SELECT * FROM canvas_board WHERE id='cv_legacy1'").fetchone()
        self.assertIsNotNone(board)
        self.assertEqual(board["name"], "Old board")
        self.assertEqual(board["updated_at"], 1234.0)

        nodes = [dict(n) for n in self.conn.execute(
            "SELECT * FROM canvas_node WHERE board_id='cv_legacy1'")]
        self.assertEqual(len(nodes), 4)           # arrow became an edge
        kinds = {n["kind"] for n in nodes}
        self.assertEqual(kinds, {"heading", "verse", "text"})
        verse = next(n for n in nodes if n["ref"] == "John 3:16")
        self.assertEqual(verse["module_id"], "kjv")
        self.assertIn("For God so loved", verse["text"])
        raw = next(n for n in nodes if "mystery" in (n["data"] or ""))
        self.assertEqual(json.loads(raw["data"])["kind"], "mystery")

        edges = [dict(e) for e in self.conn.execute(
            "SELECT * FROM canvas_edge WHERE board_id='cv_legacy1'")]
        self.assertEqual(len(edges), 1)
        by_id = {n["id"] for n in nodes if n["kind"] in ("heading", "verse")}
        self.assertIn(edges[0]["from_id"], by_id)
        self.assertIn(edges[0]["to_id"], by_id)

        # Nothing was deleted from the old setting.
        self.assertEqual(len(self.db.get_setting("canvases", [])), 1)

    def test_migration_is_idempotent(self):
        from gbible import canvases
        self.db.set_setting("canvases", self._legacy())
        canvases.migrate_legacy_canvases()
        before = (
            self.conn.execute("SELECT COUNT(*) FROM canvas_board").fetchone()[0],
            self.conn.execute("SELECT COUNT(*) FROM canvas_node").fetchone()[0],
            self.conn.execute("SELECT COUNT(*) FROM canvas_edge").fetchone()[0],
        )
        self.assertEqual(canvases.migrate_legacy_canvases(), 0)
        after = (
            self.conn.execute("SELECT COUNT(*) FROM canvas_board").fetchone()[0],
            self.conn.execute("SELECT COUNT(*) FROM canvas_node").fetchone()[0],
            self.conn.execute("SELECT COUNT(*) FROM canvas_edge").fetchone()[0],
        )
        self.assertEqual(before, after)

    def test_board_nodes_have_the_carried_columns(self):
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(canvas_node)")}
        self.assertIn("module_id", cols)
        self.assertIn("data", cols)


if __name__ == "__main__":
    unittest.main()

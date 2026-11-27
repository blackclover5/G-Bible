"""The bundled Eusebian canon tables are real comparison tables."""

import json
import re
import unittest
from pathlib import Path

from gbible import eusebian


class EusebianTableTests(unittest.TestCase):
    def test_bundled_file_has_provenance_and_all_ten_tables(self):
        doc = json.loads((Path(eusebian.__file__).parent / "data" /
                          "eusebian_tables.json").read_text(encoding="utf-8"))
        for field in ("source", "title", "attribution", "note", "license",
                      "year", "rights"):
            self.assertTrue(str(doc.get(field, "")).strip(), field)
        self.assertEqual(doc["license"], "Public Domain")
        tables = {e["table"] for e in doc["entries"]}
        self.assertEqual(tables, {"I", "II", "III", "IV", "V", "VI", "VII",
                                  "VIII", "IX", "X"})
        self.assertTrue(all(re.fullmatch(r"[IVX]+", e["table"])
                            for e in doc["entries"]))

    def test_health_reports_a_usable_comparison(self):
        h = eusebian.health()
        self.assertTrue(h["ok"])
        self.assertTrue(h["usable"])
        self.assertEqual(h["tables_present"], list(range(1, 11)))
        self.assertGreater(h["shared_sections"], 0)
        self.assertTrue(h["source"]["source"])

    def test_parallel_rows_have_blank_and_filled_columns(self):
        r = eusebian.lookup("3.1")          # Matt 1:1, a real three-way row
        self.assertTrue(r["ok"])
        self.assertIn("Matt", r["in_table"])
        self.assertIn("John", r["in_table"])
        self.assertNotIn("Mark", r["in_table"])
        self.assertEqual(len(r["columns"]), 4)

    def test_canon_x_rows_are_distinct_and_labelled(self):
        rows = eusebian.harmony(canon=10, limit=20)["canons"][0]["rows"]
        self.assertTrue(rows)
        self.assertEqual(len({r["notation"] for r in rows}), len(rows))
        self.assertTrue(all(r["section"] for r in rows))
        self.assertTrue(all(sum(bool(c["verses"]) for c in r["cells"]) == 1
                            for r in rows), "canon X is one Gospel per row")

    def test_verse_notation_uses_the_canon_table(self):
        # The old module called these 1.1 and 4.1 by Gospel.  The real tables
        # put both in canon III section 1.
        self.assertEqual(eusebian.notation("Matt.1.1"), "3.1")
        self.assertEqual(eusebian.notation("John.1.1"), "3.1")
        self.assertEqual(eusebian.notation("Gen.1.1"), "")


if __name__ == "__main__":
    unittest.main()

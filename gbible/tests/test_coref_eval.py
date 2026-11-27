"""The hand-checked coreference set must keep scoring cleanly.

This is a regression guard for the resolver's precision, not a measure of how
it performs on real Scripture: the gold file is synthetic and hand-labelled.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "eval_coref", ROOT / "tools" / "eval_coref.py")
eval_coref = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_coref)


class CorefEvalTests(unittest.TestCase):
    def test_gold_set_has_no_wrong_or_missed_resolutions(self):
        result = eval_coref.evaluate()
        self.assertGreaterEqual(result["sentences"], 20)
        self.assertEqual(result["tp"], 8)
        self.assertLessEqual(result["fp"], 1)
        self.assertLessEqual(result["fn"], 1)
        self.assertGreaterEqual(result["precision"], 0.95)
        self.assertGreaterEqual(result["recall"], 0.90)


if __name__ == "__main__":
    unittest.main()

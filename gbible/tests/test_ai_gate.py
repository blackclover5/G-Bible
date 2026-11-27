"""The AI Assistant is opt-in: nothing AI answers until it is enabled."""

import os
import shutil
import tempfile
import unittest

from gbible import aisetup, db
from gbible.server.routes.common import _ai_gate


class AiGateTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="gbible-ai-gate-")
        self.old = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = self.home
        self.addCleanup(shutil.rmtree, self.home, True)

        def restore():
            if self.old is None:
                os.environ.pop("GBIBLE_HOME", None)
            else:
                os.environ["GBIBLE_HOME"] = self.old
        self.addCleanup(restore)
        db.init()

    def test_fresh_app_has_no_ai(self):
        self.assertFalse(aisetup.enabled())
        status = aisetup.status()
        self.assertFalse(status["enabled"])

    def test_every_ai_route_is_blocked_until_enabled(self):
        for path in ("ai/providers", "ai/chat", "ai/usage", "ai/chats",
                     "webresearch/run"):
            with self.subTest(path=path):
                blocked = _ai_gate(path)
                self.assertIsNotNone(blocked)
                self.assertTrue(blocked["ai_disabled"])

    def test_setup_routes_are_always_available(self):
        for path in ("ai/status", "ai/setup/start", "ai/setup/disable"):
            with self.subTest(path=path):
                self.assertIsNone(_ai_gate(path))

    def test_non_ai_routes_are_unaffected(self):
        self.assertIsNone(_ai_gate("status"))
        self.assertIsNone(_ai_gate("library"))
        self.assertIsNone(_ai_gate("search"))

    def test_enabling_opens_the_gate(self):
        aisetup.set_enabled(True)
        self.assertTrue(aisetup.enabled())
        self.assertIsNone(_ai_gate("ai/providers"))
        self.assertIsNone(_ai_gate("webresearch/run"))
        aisetup.set_enabled(False)
        self.assertIsNotNone(_ai_gate("ai/providers"))

    def test_disable_keeps_conversations_and_keys(self):
        aisetup.set_enabled(True)
        result = aisetup.disable(remove_data=True)
        self.assertTrue(result["ok"])
        self.assertFalse(aisetup.enabled())


if __name__ == "__main__":
    unittest.main()

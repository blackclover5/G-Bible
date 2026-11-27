"""Provider-only routing: the assistant has no built-in model any more."""

from __future__ import annotations

import unittest
from unittest import mock

from gbible import ai


def settings(provider="ollama", **kw):
    s = {"provider": provider, "model": "llama3.1", "use_library": True,
         "use_mine": True, "scope": "", "smart_query": True,
         "max_sources": 20}
    s.update(kw)
    return s


class ProviderRoutingTests(unittest.TestCase):
    def test_no_internal_provider_is_offered(self):
        ids = [p["id"] for p in ai.providers_view()]
        self.assertNotIn("onnx", ids)
        self.assertTrue(ids)                       # external providers remain

    def test_resolve_honours_the_selected_provider(self):
        s = settings(provider="openai")
        with mock.patch.object(ai, "get_settings", return_value=s):
            provider, model = ai.resolve()
        self.assertEqual(provider.id, "openai")

    def test_a_discovered_model_survives_resolution(self):
        """A pulled Ollama model is real even though it is not in the preset."""
        s = settings(provider="ollama", model="llama3.2:latest")
        with mock.patch.object(ai, "get_settings", return_value=s):
            provider, model = ai._resolve_api(None, None, s)
        self.assertEqual(provider.id, "ollama")
        self.assertEqual(model, "llama3.2:latest")

    def test_removed_settings_keys_are_ignored(self):
        s = ai.get_settings()
        for key in ("mode", "local_model", "api_fallback", "hybrid_escalation",
                    "semantic", "use_vector_store"):
            self.assertNotIn(key, s)


class BackendPersistenceTests(unittest.TestCase):
    def test_backend_survives_a_saved_conversation(self):
        import os
        import shutil
        import tempfile
        home = tempfile.mkdtemp(prefix="gbible-modes-test-")
        self.addCleanup(shutil.rmtree, home, True)
        old = os.environ.get("GBIBLE_HOME")
        os.environ["GBIBLE_HOME"] = home

        def restore():
            if old is None:
                os.environ.pop("GBIBLE_HOME", None)
            else:
                os.environ["GBIBLE_HOME"] = old
        self.addCleanup(restore)

        from gbible import aichat
        c = aichat.new("provenance")
        aichat.save(c["id"], [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a", "backend": "local",
             "citations": []},
        ])
        turns = aichat.get(c["id"])["turns"]
        self.assertEqual(turns[1]["backend"], "local")


if __name__ == "__main__":
    unittest.main()

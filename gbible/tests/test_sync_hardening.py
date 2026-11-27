"""Backup hardening: integrity, honest conflict reports and opt-in deletes.

The `.gbz` is the one artefact sync moves, so the checks that matter live at
its edges: reject a damaged archive before applying anything, tell the reader
which records were skipped, and propagate a delete only when they ask for it.
"""

import io
import json
import os
import shutil
import tempfile
import time
import unittest
import zipfile


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


def _rebuild(data, mutate=None, *, recompute=True):
    """Rewrite a .gbz with one member changed, optionally fixing its digest."""
    from gbible import gbz
    zf = zipfile.ZipFile(io.BytesIO(data))
    members = {i.filename: (zf.read(i.filename), i.external_attr >> 16)
               for i in zf.infolist()}
    if mutate:
        mutate(members)
    if recompute:
        manifest = json.loads(members["restore/manifest.json"][0])
        manifest["integrity"] = gbz._integrity(members)
        members["restore/manifest.json"] = (
            json.dumps(manifest, sort_keys=True).encode("utf-8"), 0o644)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, (raw, perm) in sorted(members.items()):
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = perm << 16
            z.writestr(info, raw)
    return out.getvalue()


class SyncHardeningTests(unittest.TestCase):
    def setUp(self):
        self.home = _scratch_home(self)
        from gbible import db, gbz, sync
        self.db, self.gzb, self.sync = db, gbz, sync
        self.conn = db.connect()
        self.note_id = "hardeningnote"
        self._add_note("original text")

    def _add_note(self, body):
        now = time.time()
        self.conn.execute(
            "INSERT OR REPLACE INTO note(id,kind,title,body,module_id,unit_key,"
            "ref_label,tags,meta,created_at,updated_at) "
            "VALUES(?,'note','Note',?,'','','','[]','{}',?,?)",
            (self.note_id, body, now, now))
        self.conn.commit()

    def test_manifest_carries_version_integrity_and_kinded_keys(self):
        out = self.gzb.create_gbz()
        import json
        import zipfile
        info = self.gzb.inspect_gbz(out["data"])
        from gbible import __version__
        self.assertEqual(info["app_version"], __version__)
        with zipfile.ZipFile(__import__('io').BytesIO(out["data"])) as zf:
            manifest = json.loads(zf.read("restore/manifest.json"))
        self.assertTrue(manifest["integrity"].startswith("sha256:"))
        zf = zipfile.ZipFile(io.BytesIO(out["data"]))
        manifest = json.loads(zf.read("v1/manifest.json"))
        rec = next(r for r in manifest["records"].values()
                   if r.get("id") == self.note_id)
        self.assertEqual(rec["key"], "note:" + self.note_id)

    def test_damaged_archive_is_refused_before_apply(self):
        data = self.gzb.create_gbz()["data"]

        def break_one(members):
            name = "v1/notes/" + self.note_id + ".json"
            rec = json.loads(members[name][0])
            rec["payload"]["body"] = "tampered"
            members[name] = (json.dumps(rec).encode("utf-8"), members[name][1])

        damaged = _rebuild(data, break_one, recompute=False)
        with self.assertRaises(self.gzb.GzError):
            self.gzb.inspect_gbz(damaged)

    def test_record_hash_mismatch_is_reported_not_applied(self):
        data = self.gzb.create_gbz()["data"]

        def break_one(members):
            name = "v1/notes/" + self.note_id + ".json"
            rec = json.loads(members[name][0])
            rec["payload"]["body"] = "tampered"
            members[name] = (json.dumps(rec).encode("utf-8"), members[name][1])

        damaged = _rebuild(data, break_one, recompute=True)
        out = self.gzb.restore_gbz(damaged)
        self.assertEqual(out["applied"], 0)
        self.assertGreaterEqual(out["failed"], 1)
        self.assertTrue(any("hash" in e for e in out["errors"]))

    def test_conflicts_are_named(self):
        data = self.gzb.create_gbz()["data"]
        self._add_note("a different local edit")
        out = self.gzb.restore_gbz(data)
        self.assertEqual(out["conflict"], 1)
        self.assertEqual(out["conflicts"],
                         [{"kind": "note", "id": self.note_id}])

    def test_delete_is_opt_in_and_only_applied_to_known_older_records(self):
        # Teach this device about the record first, with an older revision.
        self.conn.execute(
            "INSERT OR REPLACE INTO sync_meta(id,kind,rev,dev,ctr,updated_at,hash,base)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (self.note_id, "note", 1, "peer", 1, 1000.0, "", ""))
        self.conn.commit()
        self.sync.tombstone(self.note_id, "note")
        rows = self.conn.execute(
            "SELECT kind FROM sync_tombstone WHERE id=?", (self.note_id,)).fetchall()
        self.assertEqual([r["kind"] for r in rows], ["note"])

        data = self.gzb.create_gbz()["data"]
        self.assertEqual(self.gzb.inspect_gbz(data)["tombstones"], 1)

        ordinary = self.gzb.restore_gbz(data)
        self.assertEqual(ordinary["tombstones_applied"], [])
        self.assertIsNotNone(self.conn.execute(
            "SELECT 1 FROM note WHERE id=?", (self.note_id,)).fetchone())

        with_deletes = self.gzb.restore_gbz(data, apply_deletes=True)
        self.assertEqual(with_deletes["tombstones_applied"],
                         [{"kind": "note", "id": self.note_id}])
        self.assertIsNone(self.conn.execute(
            "SELECT 1 FROM note WHERE id=?", (self.note_id,)).fetchone())

    def test_delete_without_known_revision_is_not_applied(self):
        self.sync.tombstone(self.note_id, "note")
        data = self.gzb.create_gbz()["data"]
        out = self.gzb.restore_gbz(data, apply_deletes=True)
        self.assertEqual(out["tombstones_applied"], [])
        self.assertEqual(out["tombstones_skipped"][0]["why"],
                         "local revision unknown")
        self.assertIsNotNone(self.conn.execute(
            "SELECT 1 FROM note WHERE id=?", (self.note_id,)).fetchone())

    def test_webdav_retries_a_transient_failure(self):
        import urllib.error
        from unittest import mock
        from gbible import synctargets

        calls = []

        def flaky(req, timeout=None):
            calls.append(req)
            if len(calls) < 3:
                raise urllib.error.URLError("connection reset")
            return object()

        target = synctargets.WebDAVTarget(
            "https://example.invalid/dav/", user="u", password="p")
        with mock.patch.object(synctargets.urllib.request, "urlopen", flaky), \
                mock.patch.object(synctargets.time, "sleep", lambda _s: None):
            result = target._request("GET", "gbible-backup.gbz")
        self.assertEqual(len(calls), 3)
        self.assertIsNotNone(result)


class ScopeTransparencyTests(unittest.TestCase):
    """The Sync panel's answer is derived from the lists that drive backups."""

    def test_scope_matches_source_of_truth(self):
        from gbible import sync
        s = sync.scope()
        self.assertTrue(s["ok"])
        self.assertEqual([k["key"] for k in s["kinds"]], list(sync.KINDS))
        self.assertEqual([x["key"] for x in s["settings"]],
                         list(sync.SETTINGS_ALLOWLIST))
        self.assertTrue(all(k["label"] and k["folder"] for k in s["kinds"]))

    def test_ai_conversations_are_flagged_not_ordinary(self):
        from gbible import sync
        kinds = {k["key"]: k for k in sync.scope()["kinds"]}
        self.assertTrue(kinds["ai-chat"]["ai_inclusive_only"])
        self.assertFalse(kinds["ai-chat"]["by_default"])
        self.assertTrue(kinds["note"]["by_default"])
        ai = sync.scope()["ai"]
        self.assertFalse(ai["conversations_by_default"])
        self.assertFalse(ai["credentials_by_default"])
        self.assertTrue(ai["settings_travel"])

    def test_deletion_and_encryption_facts(self):
        from gbible import sync
        d = sync.scope()["deletion"]
        self.assertFalse(d["default"])
        self.assertEqual(d["retention_days"], sync.TOMBSTONE_KEEP // 86400)
        e = sync.scope()["encryption"]
        self.assertTrue(e["ai_forces_encryption"])
        self.assertEqual(e["min_passphrase"], 12)

    def test_route_exposes_scope(self):
        from gbible.server.routes import sync as route
        r = route._sync_scope(None, {})
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["kinds"]), len(__import__("gbible").sync.KINDS))


if __name__ == "__main__":
    unittest.main()

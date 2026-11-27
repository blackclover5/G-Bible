"""Every recommended starter module must actually be offerable.

A licence gate that silently empties the catalogue turns the first-run prompt
into a wall of failures, so the curated bundled catalogues are treated as the
provenance for their public-domain claims.  Unknown repositories stay strict.
"""

import unittest


class CatalogueIntegrityTests(unittest.TestCase):
    def test_all_recommended_items_are_offerable(self):
        from gbible import recommended, store
        missing = []
        for repo, iid in recommended.RECOMMENDED:
            ids = {str(i.get("id")) for i in store.repo_items(repo)}
            if iid not in ids:
                missing.append(f"{repo}/{iid}")
        self.assertEqual(missing, [],
                         "recommended modules missing from the Store: "
                         + ", ".join(missing))

    def test_bundled_provenance_is_honoured_but_unknown_sources_are_not(self):
        from gbible import taxonomy
        bundled = {"license": "Public Domain", "id": "kjv",
                   "bundled_catalog": True}
        unknown = {"license": "Public Domain", "id": "mystery"}
        self.assertTrue(taxonomy.redistributable(bundled)[0])
        self.assertFalse(taxonomy.redistributable(unknown)[0])



class SwordLicenseTests(unittest.TestCase):
    def test_documented_unrestricted_grant_overrides_conf_field(self):
        from gbible.importers import runner
        it = {"license": "Public Domain",
              "license_source": "unrestricted grant in About/Copyright (GPL)"}
        lic, note = runner._sword_license(
            {"DistributionLicense": "GPL"}, it)
        self.assertEqual(lic, "Public Domain")
        self.assertIn("module declares", note)

    def test_conflict_without_documented_grant_is_still_refused(self):
        from gbible.importers import runner
        lic, note = runner._sword_license(
            {"DistributionLicense": "GPL"}, {"license": "Public Domain"})
        self.assertEqual(lic, "Copyrighted")
        self.assertEqual(note, "")


if __name__ == "__main__":
    unittest.main()

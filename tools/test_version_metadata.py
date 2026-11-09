"""Check that the README's AppImage version examples match the app version."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$"
)


def app_version() -> str:
    source = (ROOT / "gbible" / "__init__.py").read_text(encoding="utf-8")
    matches = re.findall(
        r"(?m)^[ \t]*__version__[ \t]*=[ \t]*(['\"])([^'\"]+)\1[ \t]*$",
        source,
    )
    if len(matches) != 1:
        raise AssertionError("Could not find one __version__ assignment in gbible/__init__.py")
    return matches[0][1]


class VersionMetadataTests(unittest.TestCase):
    def test_application_version_uses_release_format(self) -> None:
        self.assertRegex(app_version(), VERSION_PATTERN)

    def test_readme_appimage_versions_match_application(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        versions = re.findall(
            r"\bG-Bible (\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\b",
            readme,
        )
        self.assertTrue(versions, "README has no versioned G-Bible release examples")
        self.assertEqual(
            set(versions),
            {app_version()},
            "Update the README AppImage version examples to match gbible.__version__",
        )


if __name__ == "__main__":
    unittest.main()

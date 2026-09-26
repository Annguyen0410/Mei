"""One version, three artefacts: the code, the package metadata, the notes.

``pip install .`` reads ``pyproject.toml``, every screen and the updater read
``core/product.py``, and a user reads ``docs/CHANGELOG.md``. They drifted: the
package metadata still said 0.6.9.0 while the app shipped 0.7.0.0, so a wheel
built from this repo carried a version no release ever had. This gate makes the
three agree and names the file to bump.
"""
import os
import re
import unittest

from litebrowser.core import product

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pyproject_text() -> str:
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8-sig") as handle:
        return handle.read()


def _pyproject_version() -> str:
    """``[project] version`` — tomllib on 3.11+, one narrow regex on 3.10.

    pyproject declares ``requires-python = ">=3.10"``, and tomllib only exists
    from 3.11, so the fallback keeps this gate runnable on the oldest supported
    interpreter instead of skipping itself there.
    """
    text = _pyproject_text()
    try:
        import tomllib

        return str(tomllib.loads(text)["project"]["version"])
    except ImportError:
        match = re.search(r'(?ms)^\[project\]\s*$(.*?)(?=^\[|\Z)', text)
        section = match.group(1) if match else ""
        found = re.search(r'(?m)^version\s*=\s*"([^"]+)"', section)
        return found.group(1) if found else ""


class TestOneVersion(unittest.TestCase):
    def test_package_metadata_matches_the_app(self):
        self.assertEqual(
            _pyproject_version(),
            product.APP_VERSION,
            "bump [project] version in pyproject.toml to match core/product.py",
        )

    def test_changelog_documents_this_version(self):
        with open(os.path.join(ROOT, "docs", "CHANGELOG.md"), encoding="utf-8-sig") as handle:
            text = handle.read()
        headings = [
            line.strip().lstrip("> ").strip()
            for line in text.splitlines()
            if line.strip().lstrip("> ").strip().startswith("##")
        ]
        self.assertTrue(
            any(product.APP_VERSION in heading for heading in headings),
            f"docs/CHANGELOG.md has no section for {product.APP_VERSION} — write the notes first",
        )

    def test_version_is_the_four_part_pre_1_0_scheme(self):
        parts = product.APP_VERSION.split(".")
        self.assertEqual(len(parts), 4, "the updater compares padded four-part versions")
        self.assertTrue(all(part.isdigit() for part in parts), product.APP_VERSION)


if __name__ == "__main__":
    unittest.main()

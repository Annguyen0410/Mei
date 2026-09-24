"""One chain manifest, read the same way by dev and by a packaged build.

Covers the drift that used to exist: a stray chain.json higher up the tree won in
dev, `BUNDLED_SITES` carried a second folder mapping, and six deployed URLs were
hard-coded as fallbacks instead of living in the manifest.
"""
import json
import os
import unittest

from litebrowser.core import app_paths

HUB_IDS = {"hub"}
REQUIRED_FIELDS = ("id", "name", "glyph", "folder")


class TestManifestIsTheSource(unittest.TestCase):
    def test_packaged_manifest_exists(self):
        self.assertTrue(os.path.isfile(app_paths.PACKAGED_CHAIN_MANIFEST))

    def test_packaged_manifest_is_the_one_in_force(self):
        # Whatever else exists on the machine, the shipped manifest wins.
        self.assertEqual(app_paths.chain_manifest_path(), app_paths.PACKAGED_CHAIN_MANIFEST)

    def test_no_hard_coded_remote_fallbacks_remain(self):
        self.assertFalse(
            hasattr(app_paths, "REMOTE_SITE_FALLBACKS"),
            "deployed URLs must live in chain.json, not in app_paths",
        )

    def test_manifest_parses_with_apps(self):
        manifest = app_paths.chain_manifest()
        self.assertTrue(manifest.get("apps"))
        self.assertTrue(app_paths.manifest_apps())


class TestManifestContract(unittest.TestCase):
    """The desktop registry and the manifest must describe the same chain."""

    def setUp(self):
        self.manifest = {app["id"]: app for app in app_paths.manifest_apps()}

    def test_registry_and_manifest_cover_the_same_apps(self):
        registry = {spec["key"] for spec in app_paths.BUNDLED_SITES}
        from_manifest = set(self.manifest) - HUB_IDS
        self.assertEqual(registry, from_manifest)

    def test_every_entry_has_what_the_web_contract_needs(self):
        for app_id, app in self.manifest.items():
            with self.subTest(app=app_id):
                for field in REQUIRED_FIELDS:
                    self.assertTrue(app.get(field), f"{app_id} missing {field}")

    def test_manifest_folder_is_tried_first(self):
        for spec in app_paths.BUNDLED_SITES:
            with self.subTest(app=spec["key"]):
                candidates = app_paths._folder_candidates(spec)
                self.assertEqual(candidates[0], self.manifest[spec["key"]]["folder"])
                self.assertEqual(len(candidates), len(set(candidates)), "duplicate folder candidate")

    def test_manifest_folder_beats_a_conflicting_alias(self):
        spec = {"key": "mas", "folders": ("mas", "MAS - Mahoraga Adapt System")}
        self.assertEqual(app_paths._folder_candidates(spec)[0], self.manifest["mas"]["folder"])


class TestRemoteSites(unittest.TestCase):
    def setUp(self):
        self.manifest = {app["id"]: app for app in app_paths.manifest_apps()}

    def test_seeded_sites_match_the_manifest_exactly(self):
        seeded = {item["key"]: item["url"] for item in app_paths.chain_remote_sites()}
        expected = {
            app_id: app["remote"]
            for app_id, app in self.manifest.items()
            if app.get("remote")
        }
        self.assertEqual(seeded, expected)

    def test_every_remote_is_a_real_https_url(self):
        for item in app_paths.chain_remote_sites():
            with self.subTest(app=item["key"]):
                self.assertTrue(item["url"].startswith("https://"), item["url"])

    def test_remotes_are_unique(self):
        urls = [item["url"] for item in app_paths.chain_remote_sites()]
        self.assertEqual(len(urls), len(set(urls)))

    def test_blank_remote_in_manifest_seeds_nothing(self):
        # The hub has no deployed URL in the manifest and must not be invented.
        self.assertEqual(self.manifest["hub"].get("remote"), "")
        self.assertNotIn("hub", {item["key"] for item in app_paths.chain_remote_sites()})

    def test_bundled_sites_expose_remote_from_manifest(self):
        for item in app_paths.bundled_sites():
            with self.subTest(app=item["key"]):
                self.assertEqual(item["remote"], self.manifest[item["key"]]["remote"])


class TestPublishedCopyMatches(unittest.TestCase):
    """web_support/chain.json is only a publishing copy — it must not drift."""

    def _published(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "web_support", "chain.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def test_same_apps_folders_and_remotes(self):
        packaged = app_paths.manifest_apps()
        published = self._published().get("apps", [])
        self.assertEqual(
            [(a["id"], a["folder"], a.get("remote", "")) for a in packaged],
            [(a["id"], a["folder"], a.get("remote", "")) for a in published],
        )


class TestResolvedLocalSites(unittest.TestCase):
    def test_manifest_folder_resolution_agrees_with_the_filesystem(self):
        """If a folder exists in a search root, resolution must find it there."""
        for spec in app_paths.BUNDLED_SITES:
            with self.subTest(app=spec["key"]):
                expected = ""
                for root in app_paths._bundled_site_search_roots():
                    for folder in app_paths._folder_candidates(spec):
                        if os.path.isfile(os.path.join(root, folder, "index.html")):
                            expected = os.path.join(root, folder, "index.html")
                            break
                    if expected:
                        break
                self.assertEqual(app_paths.bundled_site_index_path(spec["key"]), expected)


if __name__ == "__main__":
    unittest.main()

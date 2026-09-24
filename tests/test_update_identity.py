"""Update identity: only this product's own channel and package may be installed.

Guards the failure mode where the desktop app polled the LinkLumina web app's
channel, read 6.2.4, called it newer than 0.6.9.0 and replaced Mei.exe with the
other product's binary.
"""
import json
import os
import tempfile
import time
import unittest
import urllib.request
from unittest import mock

from litebrowser.core import app_version, product
from litebrowser.services import update_service


def _newer_than_current() -> str:
    """A version strictly above APP_VERSION, whatever APP_VERSION currently is."""
    parts = [int(chunk) for chunk in app_version.APP_VERSION.split(".")]
    parts[-1] += 1
    return ".".join(str(part) for part in parts)


class TestChannelOwnership(unittest.TestCase):
    def _check(self, metadata, url="https://example.invalid/update.json"):
        with mock.patch.object(update_service, "_read_remote_json", return_value=metadata):
            return update_service.check_for_updates(url)

    def test_channel_serving_another_product_is_refused(self):
        # Exactly the payload the shared Netlify path serves today.
        with self.assertRaises(ValueError) as ctx:
            self._check(
                {
                    "version": "6.2.4",
                    "download_url": "https://github.com/x/y/releases/download/v6.2.4/LiteBrowser.exe",
                }
            )
        self.assertIn("not Mei", str(ctx.exception))

    def test_explicit_foreign_product_is_refused(self):
        with self.assertRaises(ValueError):
            self._check({"product": "linklumina", "version": "6.2.4", "download_url": "x"})

    def test_own_channel_with_newer_version_is_accepted(self):
        newer = _newer_than_current()
        info = self._check(
            {
                "product": product.PRODUCT_ID,
                "version": newer,
                "download_url": f"https://github.com/x/y/releases/download/v{newer}/Mei.exe",
            }
        )
        self.assertTrue(info.has_update)
        self.assertEqual(info.latest_version, newer)
        self.assertEqual(info.product, product.PRODUCT_ID)

    def test_same_version_is_not_an_update(self):
        info = self._check(
            {"product": product.PRODUCT_ID, "version": app_version.APP_VERSION, "download_url": ""}
        )
        self.assertFalse(info.has_update)

    def test_own_channel_with_foreign_asset_is_refused(self):
        newer = _newer_than_current()
        with self.assertRaises(ValueError) as ctx:
            self._check(
                {
                    "product": product.PRODUCT_ID,
                    "version": newer,
                    "download_url": f"https://github.com/x/y/releases/download/v{newer}/LiteBrowser.exe",
                }
            )
        self.assertIn(product.ASSET_NAME, str(ctx.exception))

    def test_default_channel_is_not_the_web_app_channel(self):
        self.assertIn("/mei-update/", product.DEFAULT_UPDATE_CHANNEL_URL)
        self.assertNotIn("/litebrowser-update/", product.DEFAULT_UPDATE_CHANNEL_URL)

    def test_local_metadata_file_is_product_tagged(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "litebrowser-update", "update.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle).get("product"), product.PRODUCT_ID)

    def test_wrong_channel_message_is_user_readable(self):
        self.assertIn("not Mei", update_service.format_error(update_service._wrong_channel_error("")))


class TestVersionComparison(unittest.TestCase):
    def test_padding_prevents_phantom_updates(self):
        self.assertFalse(update_service._version_is_newer("0.6.9", "0.6.9.0"))
        self.assertFalse(update_service._version_is_newer("0.6.9.0", "0.6.9"))

    def test_real_bumps_are_detected(self):
        self.assertTrue(update_service._version_is_newer("0.6.9.1", "0.6.9.0"))
        self.assertTrue(update_service._version_is_newer("1.0.0", "0.6.9.0"))
        self.assertTrue(update_service._version_is_newer(_newer_than_current(), app_version.APP_VERSION))

    def test_downgrades_are_not_updates(self):
        self.assertFalse(update_service._version_is_newer("0.6.8.9", "0.6.9.0"))

    def test_existing_normalize_contract_unchanged(self):
        self.assertEqual(update_service._normalize_version("0.6.8.0"), (0, 6, 8, 0))
        self.assertEqual(update_service._normalize_version("0.6.8.0-beta"), (0, 6, 8, 0))


class TestAssetIdentity(unittest.TestCase):
    def test_exact_asset_name_matches(self):
        self.assertTrue(update_service.asset_is_ours("https://h/p/v1/Mei.exe"))

    def test_query_string_does_not_confuse_matching(self):
        self.assertTrue(update_service.asset_is_ours("https://h/p/v1/Mei.exe?download=1"))
        self.assertTrue(update_service.asset_is_ours("https://h/p/v1/mei.exe"))

    def test_other_assets_are_rejected(self):
        for url in (
            "https://h/p/v1/LiteBrowser.exe",
            "https://h/p/v1/Mei.zip",
            "https://h/p/v1/",
            "",
        ):
            with self.subTest(url=url):
                self.assertFalse(update_service.asset_is_ours(url))

    def test_download_refuses_foreign_asset(self):
        with self.assertRaises(ValueError):
            update_service.download_update_package("https://h/p/v1/LiteBrowser.exe", "0.6.9.1")


class TestPackageVerification(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, data, name="pkg.exe"):
        path = os.path.join(self._tmp.name, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_missing_file_is_reported(self):
        with self.assertRaises(FileNotFoundError):
            update_service.verify_package(os.path.join(self._tmp.name, "nope.exe"))

    def test_http_error_page_saved_as_exe_is_refused(self):
        # A tiny non-executable download must never reach the installer.
        with self.assertRaises(ValueError):
            update_service.verify_package(self._write(b"<html>404</html>"))

    def test_non_executable_of_plausible_size_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            update_service.verify_package(self._write(b"PK\x03\x04" + b"\0" * product.MIN_PACKAGE_BYTES))
        self.assertIn("MZ", str(ctx.exception))

    def test_real_looking_package_passes(self):
        path = self._write(b"MZ" + b"\0" * product.MIN_PACKAGE_BYTES)
        update_service.verify_package(path)  # must not raise

    def test_install_refuses_unverified_package_before_touching_the_exe(self):
        path = self._write(b"<html>nope</html>")
        with self.assertRaises(ValueError):
            update_service.install_downloaded_update(path)

    def test_install_refuses_when_not_frozen(self):
        path = self._write(b"MZ" + b"\0" * product.MIN_PACKAGE_BYTES)
        with self.assertRaises(RuntimeError):
            update_service.install_downloaded_update(path)


class TestUpdateScriptSafety(unittest.TestCase):
    def test_script_backs_up_and_can_roll_back(self):
        script = update_service._update_script(r"C:\apps\Mei.exe", r"C:\tmp\Mei-0.6.9.1.exe", 4321)
        self.assertIn('set "BAK=%TARGET%.bak"', script)
        self.assertIn("copy /Y \"%TARGET%\" \"%BAK%\"", script)
        self.assertIn(":rollback", script)
        # Watchdog: a build that never comes up must restore the backup.
        self.assertIn("tasklist /FI \"IMAGENAME eq %IMAGE%\"", script)
        self.assertIn('copy /Y "%BAK%" "%TARGET%"', script)

    def test_script_waits_for_this_process_to_exit(self):
        script = update_service._update_script(r"C:\apps\Mei.exe", r"C:\tmp\pkg.exe", 99)
        self.assertIn(":wait_loop", script)
        self.assertIn('set "PID=99"', script)

    def test_script_deletes_the_previous_build_after_a_successful_swap(self):
        script = update_service._update_script(
            r"C:\apps\Mei.exe", r"C:\tmp\Mei-9.9.9.exe", 7, [r"C:\apps\update\Mei.exe"]
        )
        self.assertIn(r'del "C:\apps\update\Mei.exe" >nul 2>nul', script)
        # Cleanup belongs to the success path: a rollback must keep everything.
        self.assertLess(script.index(r'del "C:\apps\update\Mei.exe"'), script.index(":rollback"))

    def test_install_writes_the_stale_paths_into_the_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = os.path.join(tmp, product.ASSET_NAME)
            with open(package, "wb") as handle:
                handle.write(b"MZ" + b"\0" * product.MIN_PACKAGE_BYTES)
            with mock.patch.object(update_service.sys, "frozen", True, create=True), mock.patch.object(
                update_service.sys, "executable", package
            ), mock.patch.object(update_service.subprocess, "Popen") as popen:
                update_service.install_downloaded_update(package, [r"C:\apps\update\Mei.exe"])
            script_path = popen.call_args[0][0][2]
            with open(script_path, encoding="utf-8") as handle:
                written = handle.read()
        self.assertIn(r'del "C:\apps\update\Mei.exe"', written)


class TestLocalChannel(unittest.TestCase):
    """A build dropped into the ``update`` folder beside the exe is a channel.

    This is how a machine with no release server upgrades itself: copy
    ``update.json`` + ``Mei.exe`` into ``<exe dir>/update/`` and let the app
    replace its own executable on the next launch.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.app_dir = self._tmp.name
        self.update_dir = os.path.join(self.app_dir, update_service.LOCAL_CHANNEL_DIRNAME)
        os.makedirs(self.update_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def _manifest(self, **overrides) -> str:
        payload = {
            "product": product.PRODUCT_ID,
            "version": "9.9.9",
            "download_url": os.path.join(self.update_dir, product.ASSET_NAME),
        }
        payload.update(overrides)
        path = os.path.join(self.update_dir, update_service.LOCAL_CHANNEL_FILENAME)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return path

    def test_no_manifest_means_no_local_channel(self):
        self.assertEqual(update_service.local_channel_path(self.app_dir), "")
        self.assertEqual(update_service.local_channel_url(self.app_dir), "")

    def test_manifest_beside_the_exe_is_found(self):
        path = self._manifest()
        self.assertEqual(update_service.local_channel_path(self.app_dir), path)
        url = update_service.local_channel_url(self.app_dir)
        self.assertTrue(url.startswith("file:"))
        self.assertEqual(update_service.local_source(url), path)

    def test_local_channel_is_used_when_no_remote_is_given(self):
        self._manifest()
        info = update_service.check_for_updates(app_dir=self.app_dir)
        self.assertTrue(info.has_update)
        self.assertEqual(info.latest_version, "9.9.9")
        self.assertEqual(info.product, product.PRODUCT_ID)

    def test_an_explicit_remote_url_still_wins(self):
        self._manifest()
        with mock.patch.object(
            update_service,
            "_read_remote_json",
            return_value={"product": product.PRODUCT_ID, "version": app_version.APP_VERSION},
        ) as reader:
            info = update_service.check_for_updates("https://example.invalid/update.json", self.app_dir)
        reader.assert_called_once_with("https://example.invalid/update.json")
        self.assertFalse(info.has_update)

    def test_local_manifest_for_another_product_is_refused(self):
        self._manifest(product="linklumina")
        with self.assertRaises(ValueError):
            update_service.check_for_updates(app_dir=self.app_dir)

    def test_local_package_with_a_foreign_name_is_refused(self):
        self._manifest(download_url=os.path.join(self.update_dir, "LiteBrowser.exe"))
        with self.assertRaises(ValueError):
            update_service.check_for_updates(app_dir=self.app_dir)

    def test_local_package_is_copied_not_moved(self):
        package = os.path.join(self.app_dir, product.ASSET_NAME)
        with open(package, "wb") as handle:
            handle.write(b"MZ" + b"\0" * product.MIN_PACKAGE_BYTES)
        target = update_service.download_update_package(package, "9.9.9")
        self.addCleanup(lambda: os.path.isfile(target) and os.remove(target))
        self.assertTrue(os.path.isfile(target))
        self.assertTrue(os.path.isfile(package), "the dropped build must survive the install")
        self.assertEqual(os.path.getsize(target), os.path.getsize(package))

    def test_local_channel_packages_lists_only_executables(self):
        dropped = os.path.join(self.update_dir, product.ASSET_NAME)
        with open(dropped, "wb") as handle:
            handle.write(b"MZ")
        with open(os.path.join(self.update_dir, "readme.txt"), "w", encoding="utf-8") as handle:
            handle.write("notes")
        self.assertEqual(update_service.local_channel_packages(self.app_dir), [dropped])

    def test_local_metadata_reads_both_path_and_file_url(self):
        path = self._manifest()
        for candidate in (path, f"file:{urllib.request.pathname2url(path)}"):
            with self.subTest(candidate=candidate):
                self.assertEqual(
                    update_service._read_remote_json(candidate)["product"], product.PRODUCT_ID
                )

    def test_local_source_ignores_network_urls(self):
        for url in ("https://h/p/Mei.exe", "http://h/p/Mei.exe", ""):
            with self.subTest(url=url):
                self.assertEqual(update_service.local_source(url), "")


class TestCleanupOldArtifacts(unittest.TestCase):
    """An update must not cost disk space for good."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.app_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _file(self, name, size=16, age=10_000) -> str:
        path = os.path.join(self.app_dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"\0" * size)
        if age:
            os.utime(path, (time.time() - age, time.time() - age))
        return path

    def test_stale_swaps_are_removed_and_bytes_reported(self):
        live = self._file("Mei.exe")
        backup = self._file("Mei.exe.bak", size=1024)
        older = self._file("Mei.exe.old")
        partial = self._file("~Mei.exe")

        result = update_service.cleanup_old_artifacts(
            self.app_dir, min_age_seconds=0, downloaded=False
        )

        self.assertTrue(os.path.isfile(live), "the running build is never deleted")
        for gone in (backup, older, partial):
            with self.subTest(gone=gone):
                self.assertFalse(os.path.exists(gone))
        self.assertEqual(result["freed_bytes"], 1024 + 16 + 16)
        self.assertEqual(result["errors"], [])

    def test_hand_dropped_package_survives_until_it_is_installed(self):
        dropped = self._file(os.path.join(update_service.LOCAL_CHANNEL_DIRNAME, "Mei.exe"), size=2048)
        manifest = self._file(
            os.path.join(update_service.LOCAL_CHANNEL_DIRNAME, update_service.LOCAL_CHANNEL_FILENAME)
        )
        update_service.cleanup_old_artifacts(self.app_dir, min_age_seconds=0, downloaded=False)
        self.assertTrue(os.path.isfile(dropped))
        self.assertTrue(os.path.isfile(manifest))

    def test_a_fresh_backup_is_left_alone(self):
        # The update that is happening right now must keep its own .bak.
        fresh = self._file("Mei.exe.bak", age=0)
        result = update_service.cleanup_old_artifacts(
            self.app_dir, min_age_seconds=update_service.CLEANUP_MIN_AGE_SECONDS, downloaded=False
        )
        self.assertEqual(result["removed"], [])
        self.assertTrue(os.path.exists(fresh))

    def test_downloaded_packages_are_swept(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, app_version.APP_NAME, "updates")
            os.makedirs(folder)
            package = os.path.join(folder, f"{app_version.APP_NAME}-9.9.9.exe")
            with open(package, "wb") as handle:
                handle.write(b"MZ" + b"\0" * 4096)
            os.utime(package, (time.time() - 10_000, time.time() - 10_000))
            with mock.patch.object(update_service.tempfile, "gettempdir", return_value=tmp):
                result = update_service.cleanup_old_artifacts("", min_age_seconds=0)
        self.assertEqual(result["removed"], [package])
        self.assertEqual(result["freed_bytes"], 4098)
        self.assertFalse(os.path.exists(package))

    def test_no_app_dir_is_not_an_error(self):
        with mock.patch.object(update_service.tempfile, "gettempdir", return_value=self.app_dir):
            result = update_service.cleanup_old_artifacts(downloaded=False)
        self.assertEqual(result, {"removed": [], "freed_bytes": 0, "errors": []})


if __name__ == "__main__":
    unittest.main()

"""Regression tests for the 2026 engineering overhaul findings.

Each class pins one confirmed defect so the fix cannot silently regress:

* an EasyList ``@@`` exception rule was skipped, so a whitelisted site stayed
  blocked;
* full Client Hints were kept on every page of a whole registrable domain,
  not just on the sign-in origin that needs them;
* the "strict Referer" toggle wrote a preference no request path ever read;
* the download record had no MIME/size/timestamps, and the hibernation pause
  counter was incremented but never decremented;
* third-party cookie blocking was installed on the normal profile only, so
  private profiles kept storing third-party cookies.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import urllib.parse

import litebrowser  # noqa: F401 - activates the Qt shim before the binding
from hypothesis import given, settings
from hypothesis import strategies as st
from PyQt5.QtCore import QUrl

from litebrowser.browser import adblock
from litebrowser.core import prefs
from litebrowser.services import download_mgr, history_service, password_manager, safe_http
from litebrowser.ui.main_window.window import SearchWindow
from litebrowser.ui.main_window.window_tools import WindowToolsMixin

REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Credential capture must not run in the page's JavaScript context
# --------------------------------------------------------------------------- #
class TestPasswordCaptureRemoved:
    def test_no_page_context_capture_script_remains(self):
        for rel in (
            "litebrowser/services/password_manager.py",
            "litebrowser/ui/main_window/window.py",
            "litebrowser/ui/main_window/window_tools.py",
        ):
            source = (REPO_ROOT / rel).read_text(encoding="utf-8")
            assert "CAPTURE_INSTALL_SCRIPT" not in source
            assert "READ_CAPTURED_SCRIPT" not in source
            assert "__mei_pending_creds" not in source

    def test_autofill_keeps_credentials_out_of_page_scope(self):
        script = password_manager.build_autofill_script("user@example.com", "s3cret")
        assert "s3cret" in script
        assert "window.__lite_password" not in script
        assert "sessionStorage" not in script


class TestAutofillNeedsAUserGesture:
    """F-40: loading a page must never be what releases a vault secret."""

    def test_load_path_does_not_inject_the_autofill_script(self):
        source = (REPO_ROOT / "litebrowser/ui/main_window/window.py").read_text(encoding="utf-8")
        load_body = source.split("def on_load_finished", 1)[1].split("\n    def ", 1)[0]
        assert "build_autofill_script" not in load_body
        # A master-password prompt is a user action too, not a side effect.
        assert "ask_master_password" not in load_body
        assert "_arm_saved_login_hint" in load_body

    def test_fill_is_user_triggered_and_rechecks_the_origin(self):
        source = (REPO_ROOT / "litebrowser/ui/main_window/window.py").read_text(encoding="utf-8")
        assert 'QKeySequence("Ctrl+Shift+L")' in source
        fill_body = source.split("def fill_saved_login", 1)[1].split("\n    def ", 1)[0]
        assert "same_origin" in fill_body
        assert "build_autofill_script" in fill_body


# --------------------------------------------------------------------------- #
# URL normalisation invariants (property-based)
# ---------------------------------------------------------------------------
class TestUrlNormalisationInvariants:
    @settings(max_examples=250, deadline=None)
    @given(st.text(max_size=300))
    def test_normalizer_accepts_or_refuses_but_never_crashes(self, text):
        """Any string either raises ``UnsafeUrl`` or yields a real http(s) URL.

        This is the contract every caller of ``normalize_http_url`` relies on:
        no other exception type, no scheme it did not promise, no empty host.
        """
        try:
            normalized = safe_http.normalize_http_url(text)
        except safe_http.UnsafeUrl:
            return
        parts = urllib.parse.urlsplit(normalized)
        assert parts.scheme in ("http", "https")
        assert parts.hostname
        assert not parts.username and not parts.password


# --------------------------------------------------------------------------- #
# EasyList exception rules (@@)
# --------------------------------------------------------------------------- #
class TestExceptionRules:
    def test_exception_rules_are_parsed_separately(self, tmp_path):
        path = tmp_path / "filters.txt"
        path.write_text("||ads.example^\n@@||good.example^\n", encoding="utf-8")
        blocked, allowed = adblock.load_filter_file(str(path))
        assert blocked == {"ads.example"}
        assert allowed == {"good.example"}

    def test_back_compat_reader_returns_block_rules_only(self, tmp_path):
        path = tmp_path / "filters.txt"
        path.write_text("||ads.example^\n@@||good.example^\n", encoding="utf-8")
        assert adblock.load_domains_from_filter_file(str(path)) == {"ads.example"}

    def test_exception_wins_over_a_blocking_rule(self):
        blocker = adblock.TrackingBlocker(base_dir=None)
        blocker._all_blocked_domains = frozenset({"ads.example"})
        blocker._filter_file_allowed = {"good.example"}
        assert blocker._is_blocked_host("cdn.ads.example")
        assert not blocker._is_blocked_host("good.example")
        assert not blocker._is_blocked_host("login.good.example")

    def test_merged_cache_keeps_exception_lines(self):
        rules, problem = adblock._bounded_rules("||ads.example^\n@@||good.example^\n")
        assert problem == ""
        assert rules == ["||ads.example^", "@@||good.example^"]

    def test_unsupported_syntax_is_still_skipped(self):
        kind, domain = adblock._filter_rule("example.com##.ad-banner")
        assert (kind, domain) == ("", "")


# --------------------------------------------------------------------------- #
# Client Hints are sign-in-only
# --------------------------------------------------------------------------- #
class _FakeRequestInfo:
    def __init__(self, url):
        self._url = QUrl(url)
        self.headers = {}
        self.blocked = False
        self.redirected = None

    def requestUrl(self):
        return self._url

    def setHttpHeader(self, name, value):
        self.headers[name] = value

    def block(self, flag):
        self.blocked = bool(flag)

    def redirect(self, url):
        self.redirected = url


class TestClientHintScope:
    def test_device_hints_are_stripped_on_ordinary_google_pages(self):
        blocker = adblock.TrackingBlocker(base_dir=None)
        info = _FakeRequestInfo("https://www.google.com/search?q=mei")
        blocker.interceptRequest(info)
        assert info.headers.get(b"sec-ch-ua-arch") == b""
        assert info.headers.get(b"sec-ch-ua-bitness") == b""

    def test_sign_in_host_keeps_its_hints(self):
        blocker = adblock.TrackingBlocker(base_dir=None)
        blocker.sign_in_compat = True
        info = _FakeRequestInfo("https://accounts.google.com/signin")
        blocker.interceptRequest(info)
        # Kept, and the values name Chromium rather than impersonating Chrome.
        assert info.headers[b"sec-ch-ua-arch"] == b'"x86"'
        assert b"Chromium" in info.headers[b"sec-ch-ua"]
        assert b"Google Chrome" not in info.headers[b"sec-ch-ua"]

    def test_cloudflare_registrable_domain_is_not_a_challenge_host(self):
        blocker = adblock.TrackingBlocker(base_dir=None)
        assert blocker._is_trusted_challenge_url("challenges.cloudflare.com")
        assert not blocker._is_trusted_challenge_url("blog.cloudflare.com")


# --------------------------------------------------------------------------- #
# The dead "strict Referer" control
# --------------------------------------------------------------------------- #
class TestStrictReferrer:
    def test_privacy_dialog_no_longer_offers_the_no_op_toggle(self):
        source = (REPO_ROOT / "litebrowser/ui/dialogs/profiles_privacy.py").read_text(encoding="utf-8")
        assert "Send shortened Referer" not in source
        assert "chk_strict_ref" not in source

    def test_existing_preference_still_reads(self, tmp_path):
        # Backward compatibility: old profiles keep loading their stored value.
        assert prefs.get_strict_referrer(str(tmp_path)) is True


# --------------------------------------------------------------------------- #
# Download metadata and the hibernation pause counter
# --------------------------------------------------------------------------- #
class _FakeDownload:
    DownloadCompleted = 2
    DownloadCancelled = 3
    DownloadInterrupted = 4

    def __init__(self, state):
        self._state = state

    def state(self):
        return self._state

    def suggestedFileName(self):
        return "archive.zip"

    def mimeType(self):
        return "application/zip"

    def url(self):
        return QUrl("https://private.example/archive.zip")

    def totalBytes(self):
        return 1024

    def receivedBytes(self):
        return 1024


class _WindowStub:
    _download_attr = staticmethod(WindowToolsMixin._download_attr)
    _record_download = WindowToolsMixin._record_download

    def __init__(self, base_dir):
        self.base_dir = base_dir
        self._finalized_downloads = set()
        self._active_download_count = 1
        self.messages = []

    def _load_downloads_panel(self):
        pass

    def _flash_status(self, message):
        self.messages.append(message)

    def _host_shell(self):
        return None


class TestDownloadLifecycle:
    def test_records_mime_sizes_and_timestamps(self, tmp_path):
        base = str(tmp_path)
        download_id = download_mgr.add_download(
            base,
            "https://example.com/archive.zip",
            str(tmp_path / "archive.zip"),
            "archive.zip",
            mime_type="application/zip",
            total_bytes=1024,
        )
        row = download_mgr.load_list(base)[0]
        assert row["id"] == download_id
        assert row["mime_type"] == "application/zip"
        assert row["total_bytes"] == 1024
        assert row["received_bytes"] == 0
        assert row["started_at"] > 0
        assert row["finished_at"] == 0

        assert download_mgr.update_status(base, download_id, "completed", received_bytes=1024)
        row = download_mgr.load_list(base)[0]
        assert row["status"] == "completed"
        assert row["received_bytes"] == 1024
        assert row["finished_at"] > 0

    def test_finish_time_is_stamped_once(self, tmp_path):
        base = str(tmp_path)
        download_id = download_mgr.add_download(base, "https://example.com/f", "/tmp/f.bin")
        download_mgr.update_status(base, download_id, "cancelled")
        first = download_mgr.load_list(base)[0]["finished_at"]
        download_mgr.update_status(base, download_id, "cancelled")
        assert download_mgr.load_list(base)[0]["finished_at"] == first

    def test_missing_and_negative_sizes_are_normalised(self, tmp_path):
        base = str(tmp_path)
        download_id = download_mgr.add_download(
            base, "https://example.com/f", "/tmp/f.bin", total_bytes=-1, received_bytes=None
        )
        row = download_mgr.load_list(base)[0]
        assert row["total_bytes"] == 0
        assert row["received_bytes"] == 0
        download_mgr.update_status(base, download_id, "interrupted", received_bytes="not-a-number")
        assert download_mgr.load_list(base)[0]["received_bytes"] == 0

    def test_terminal_event_releases_the_hibernation_pause(self, tmp_path):
        base = str(tmp_path)
        window = _WindowStub(base)
        download_id = download_mgr.add_download(base, "https://example.com/archive.zip", "/tmp/archive.zip")
        download = _FakeDownload(_FakeDownload.DownloadCompleted)

        WindowToolsMixin._finalize_download(window, download_id, download)
        assert window._active_download_count == 0

        # stateChanged and finished both fire; the second must not double-count.
        WindowToolsMixin._finalize_download(window, download_id, download)
        assert window._active_download_count == 0

    def test_private_download_is_not_written_to_the_profile(self, tmp_path):
        base = str(tmp_path)
        window = _WindowStub(base)
        download = _FakeDownload(_FakeDownload.DownloadCompleted)

        assert window._record_download(download, str(tmp_path / "archive.zip"), private=True) is None
        assert download_mgr.load_list(base) == []
        assert history_service.list_activity(base) == []

    def test_regular_download_is_written_to_the_profile(self, tmp_path):
        base = str(tmp_path)
        window = _WindowStub(base)
        download = _FakeDownload(_FakeDownload.DownloadCompleted)

        download_id = window._record_download(download, str(tmp_path / "archive.zip"))
        assert download_id == 1
        assert download_mgr.load_list(base)[0]["mime_type"] == "application/zip"
        assert any(item.get("kind") == "download" for item in history_service.list_activity(base))

    def test_private_terminal_event_releases_the_pause_without_writing(self, tmp_path):
        base = str(tmp_path)
        window = _WindowStub(base)
        download = _FakeDownload(_FakeDownload.DownloadCompleted)
        key = ("private", id(download))

        WindowToolsMixin._finalize_download(window, key, download, persisted=False)
        assert window._active_download_count == 0
        assert download_mgr.load_list(base) == []

    def test_a_download_that_is_still_running_keeps_the_pause(self, tmp_path):
        base = str(tmp_path)
        window = _WindowStub(base)
        download_id = download_mgr.add_download(base, "https://example.com/archive.zip", "/tmp/archive.zip")
        WindowToolsMixin._finalize_download(window, download_id, _FakeDownload(1))
        assert window._active_download_count == 1
        assert download_mgr.load_list(base)[0]["status"] == "downloading"


# --------------------------------------------------------------------------- #
# Cookie policy covers every profile, including private ones
# --------------------------------------------------------------------------- #
class _FakeAction:
    def __init__(self, checked):
        self._checked = checked

    def isChecked(self):
        return self._checked


class _FakeCookieStore:
    def __init__(self):
        self.filters = []

    def setCookieFilter(self, cookie_filter):
        self.filters.append(cookie_filter)


class _FakeProfile:
    def __init__(self):
        self.cookie_store = _FakeCookieStore()

    def cookieStore(self):
        return self.cookie_store


class _CookieWindowStub(SimpleNamespace):
    """SearchWindow's two cookie methods, bound to a window-shaped namespace."""

    _third_party_cookie_filter = SearchWindow._third_party_cookie_filter
    _apply_cookie_policy = SearchWindow._apply_cookie_policy


class TestCookiePolicyScope:
    def _window(self, checked=True):
        return _CookieWindowStub(
            base_dir=str(Path.cwd()),
            profile=_FakeProfile(),
            _incognito_profiles=[_FakeProfile(), _FakeProfile()],
            act_block_3p_cookies=_FakeAction(checked),
            _flash_status=lambda *_args, **_kwargs: None,
            is_compatibility_host=lambda value: False,
        )

    def test_every_profile_gets_the_filter(self):
        window = self._window()
        window._apply_cookie_policy(show_message=False)
        assert len(window.profile.cookie_store.filters) == 1
        assert all(len(profile.cookie_store.filters) == 1 for profile in window._incognito_profiles)

    def test_thirds_are_refused_but_first_party_is_kept(self):
        window = self._window()
        window._apply_cookie_policy(show_message=False)
        installed = window.profile.cookie_store.filters[0]

        class _Request:
            def __init__(self, third_party):
                self._third_party = third_party

            def firstPartyUrl(self):
                return QUrl("https://example.com/")

            def thirdParty(self):
                return self._third_party

        assert installed(_Request(False)) is True
        assert installed(_Request(True)) is False

    def test_turning_the_policy_off_installs_a_pass_through(self):
        window = self._window(checked=False)
        window._apply_cookie_policy(show_message=False)
        installed = window.profile.cookie_store.filters[0]

        class _Request:
            def firstPartyUrl(self):
                return QUrl("https://example.com/")

            def thirdParty(self):
                return True

        assert installed(_Request()) is True

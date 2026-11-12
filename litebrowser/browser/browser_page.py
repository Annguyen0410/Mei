# Mei - Custom QWebEnginePage for permissions (notifications, geolocation)
import os

from PyQt5.QtCore import QUrl, pyqtSignal
from PyQt5.QtWebEngineWidgets import QWebEnginePage
from PyQt5.QtWidgets import QMessageBox

# QWebEngineScript lives in QtWebEngineWidgets under PyQt5 (Qt 5.x layout) but moved
# to QtWebEngineCore under PyQt6 / Qt 6. Try both so the file works in either runtime
# (our qt_compat shim also re-exports it on QtWebEngineWidgets when PyQt6 is active).
try:
    from PyQt5.QtWebEngineWidgets import QWebEngineScript  # PyQt5 / shim
except ImportError:  # pragma: no cover - PyQt6 without shim
    from PyQt5.QtWebEngineCore import QWebEngineScript

from litebrowser.core import prefs

# The global Chrome-spoofing DocumentCreation script that used to live here
# was removed: it rewrote navigator.webdriver / plugins / WebGL / userAgentData
# on every page and in every subframe. See litebrowser/browser/engine_identity.py
# and docs/audit/MEI_BROWSER_COMPATIBILITY_MATRIX.md. Never re-add a script that
# fabricates a browser fingerprint; the engine reports the truth now.
LEGACY_CHROME_SHIM_REMOVED = True


_CHROME_COMPAT_SCRIPT_NAME = "litebrowser_chrome_compat"
_FORCED_DARK_SCRIPT_NAME = "litebrowser_forced_dark"
_TEXT_HIGHLIGHT_SCRIPT_NAME = "litebrowser_text_highlight"


def build_forced_dark_js(enabled: bool = True) -> str:
    """Return JS that injects a durable dark-mode `<style>` or removes the one before.

    When enabled, light background/foreground is recast to the app's dark neutral so
    non-dark sites read comfortably at night. Images/video are left untouched to avoid
    color-inverting photos. Skips sites that already ask for dark (media-query) or that
    we know ship their own dark theme.
    """
    if not enabled:
        return (
            "var el = document.getElementById('lite-forced-dark');"
            " if (el) el.parentNode && el.parentNode.removeChild(el);"
        )
    return r"""
    (function() {
        try {
            if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
                return; // Site already renders dark; leave it alone.
            }
            if (document.getElementById('lite-forced-dark')) return;
            var style = document.createElement('style');
            style.id = 'lite-forced-dark';
            style.type = 'text/css';
            style.innerHTML =
                'html { color-scheme: dark; }' +
                'html, body { background: #141414 !important; color: #e6e6e6 !important; }' +
                'body * { background-color: transparent !important; }' +
                'a, a:link, a:visited { color: #8ec4ff !important; }' +
                'input, textarea, select, button { background: #1e1e1e !important; color: #ececec !important; border-color: #444 !important; }';
            (document.head || document.documentElement).appendChild(style);
        } catch (e) {}
    })();
    """


def ensure_forced_dark_script(profile, enabled: bool, base_dir=None) -> None:
    """Install or remove a per-profile DocumentCreation dark-mode script.

    Using a profile-scoped script (rather than run-on-load JavaScript) makes the
    override apply to every page from the first render, including pages that paint
    before loadFinished fires.
    """
    try:
        scripts = profile.scripts()
    except Exception:
        return
    if base_dir:
        # Guard was inverted in v6.4 (called prefs with the falsy base_dir and
        # read/wrote the wrong profile's prefs).
        try:
            from litebrowser.core import prefs
            # effective_force_dark_web, not the raw flag: pages follow the shell's
            # light/dark mode until the user sets the flag explicitly.
            enabled = prefs.effective_force_dark_web(base_dir) if enabled is None else enabled
        except Exception:
            pass
    existing = None
    if hasattr(scripts, "findScript"):
        try:
            existing = scripts.findScript(_FORCED_DARK_SCRIPT_NAME)
        except Exception:
            existing = None
    if existing is None or (hasattr(existing, "isNull") and existing.isNull()):
        try:
            for s in scripts.toList():
                if s.name() == _FORCED_DARK_SCRIPT_NAME:
                    existing = s
                    break
        except Exception:
            pass
    if not enabled:
        if existing is not None and not (hasattr(existing, "isNull") and existing.isNull()):
            try:
                scripts.remove(existing)
            except Exception:
                pass
        return
    if existing is not None and not (hasattr(existing, "isNull") and existing.isNull()):
        return
    script = QWebEngineScript()
    script.setName(_FORCED_DARK_SCRIPT_NAME)
    script.setSourceCode(build_forced_dark_js(True))
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(False)
    scripts.insert(script)


_WEBGL_DISABLE_SCRIPT_NAME = "litebrowser_webgl_disable"


def build_webgl_disable_js(enabled: bool = True) -> str:
    """Return JS that neuters WebGL so heavy 3D/shader pages fall back.

    ``QWebEngineSettings.WebGLEnabled`` is only read when a renderer is created,
    so toggling it at runtime has no visible effect on live pages. This
    profile-level script kills the WebGL entry points from the page's point of
    view, which takes effect immediately on reload (and on every new page).
    """
    if not enabled:
        return "window.__mei_webgl_disabled = false;"
    return r"""
    (function() {
        'use strict';
        try {
            if (window.__mei_webgl_disabled) return;
            window.__mei_webgl_disabled = true;
            function undef(name) {
                try {
                    Object.defineProperty(window, name, {
                        value: undefined, configurable: true, writable: true
                    });
                } catch (e) {
                    try { window[name] = undefined; } catch (e2) {}
                }
            }
            undef('WebGLRenderingContext');
            undef('WebGL2RenderingContext');
            var proto = HTMLCanvasElement && HTMLCanvasElement.prototype;
            if (proto && proto.getContext) {
                var orig = proto.getContext;
                proto.getContext = function(type) {
                    var t = String(type || '').toLowerCase();
                    if (t === 'webgl' || t === 'webgl2' || t === 'experimental-webgl') {
                        return null;
                    }
                    return orig.apply(this, arguments);
                };
            }
        } catch (e) {}
    })();
    """


def ensure_webgl_disable_script(profile, enabled: bool) -> None:
    """Install or remove the per-profile WebGL-disable script."""
    try:
        scripts = profile.scripts()
    except Exception:
        return
    existing = None
    if hasattr(scripts, "findScript"):
        try:
            existing = scripts.findScript(_WEBGL_DISABLE_SCRIPT_NAME)
        except Exception:
            existing = None
    if existing is None or (hasattr(existing, "isNull") and existing.isNull()):
        try:
            for s in scripts.toList():
                if s.name() == _WEBGL_DISABLE_SCRIPT_NAME:
                    existing = s
                    break
        except Exception:
            pass
    if not enabled:
        if existing is not None and not (hasattr(existing, "isNull") and existing.isNull()):
            try:
                scripts.remove(existing)
            except Exception:
                pass
        return
    if existing is not None and not (hasattr(existing, "isNull") and existing.isNull()):
        return
    script = QWebEngineScript()
    script.setName(_WEBGL_DISABLE_SCRIPT_NAME)
    script.setSourceCode(build_webgl_disable_js(True))
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(False)
    scripts.insert(script)


def build_text_highlight_js(enabled: bool = True) -> str:
    """Return JS that installs (or removes) the "highlight text to copy" helper.

    When enabled, selecting any text on the page paints it with a visible marker
    (amber ::selection) and a small floating "📋 Copy" bubble appears next to the
    selection. Clicking the bubble copies the highlighted text to the clipboard,
    so copying any text on any page (main browser tabs and embedded previews
    alike) takes a single click instead of a context-menu dance.
    """
    if not enabled:
        return (
            "try{var b=document.getElementById('lite-copy-bubble');"
            "if(b&&b.parentNode)b.parentNode.removeChild(b);"
            "var s=document.getElementById('lite-highlight-style');"
            "if(s&&s.parentNode)s.parentNode.removeChild(s);}catch(e){}"
            "try{delete window.__liteTextHighlightInstalled;}catch(e){}"
        )
    return r"""
    (function() {
        'use strict';
        try {
            if (window.__liteTextHighlightInstalled) return;
            window.__liteTextHighlightInstalled = true;

            function addStyle() {
                if (document.getElementById('lite-highlight-style')) return;
                var style = document.createElement('style');
                style.id = 'lite-highlight-style';
                style.type = 'text/css';
                style.innerHTML =
                    '::selection { background: rgba(245, 185, 66, 0.80) !important; color: #241a08 !important; }' +
                    '::-moz-selection { background: rgba(245, 185, 66, 0.80) !important; color: #241a08 !important; }';
                (document.head || document.documentElement).appendChild(style);
            }

            var bubble = null;
            function getBubble() {
                if (bubble) return bubble;
                bubble = document.createElement('div');
                bubble.id = 'lite-copy-bubble';
                bubble.setAttribute('role', 'button');
                bubble.textContent = '\uD83D\uDCCB Copy';
                bubble.style.cssText = [
                    'position:fixed', 'z-index:2147483647',
                    'background:#f5b942', 'color:#2b1c0a',
                    'border:1px solid #d99a2b', 'border-radius:7px',
                    'padding:5px 12px', 'cursor:pointer',
                    'font:600 13px/1.4 "Segoe UI", Arial, sans-serif',
                    'box-shadow:0 3px 10px rgba(0,0,0,.4)',
                    'display:none', 'user-select:none', '-webkit-user-select:none'
                ].join(';');
                bubble.addEventListener('mousedown', function(ev) {
                    ev.preventDefault();
                    ev.stopPropagation();
                });
                bubble.addEventListener('click', function(ev) {
                    ev.preventDefault();
                    ev.stopPropagation();
                    var text = '';
                    try {
                        var sel = window.getSelection();
                        if (sel) text = sel.toString();
                    } catch (e) {}
                    if (text) {
                        copyText(text);
                        flashCopied();
                    }
                    hideBubble();
                    try { window.getSelection().removeAllRanges(); } catch (e) {}
                });
                document.body.appendChild(bubble);
                return bubble;
            }

            function copyText(text) {
                var done = false;
                try {
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        navigator.clipboard.writeText(text).then(function(){}, function(){});
                        done = true;
                    }
                } catch (e) {}
                if (!done) {
                    try {
                        var ta = document.createElement('textarea');
                        ta.value = text;
                        ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;';
                        document.body.appendChild(ta);
                        ta.focus();
                        ta.select();
                        document.execCommand('copy');
                        document.body.removeChild(ta);
                    } catch (e) {}
                }
            }

            function flashCopied() {
                try {
                    if (!bubble) return;
                    var old = bubble.textContent;
                    bubble.textContent = '\u2713 Copied';
                    setTimeout(function() {
                        if (bubble) bubble.textContent = old;
                    }, 900);
                } catch (e) {}
            }

            function hideBubble() {
                try { if (bubble) bubble.style.display = 'none'; } catch (e) {}
            }

            function showBubble() {
                try {
                    var sel = window.getSelection();
                    if (!sel || sel.isCollapsed || !sel.toString().trim()) {
                        hideBubble();
                        return;
                    }
                    var rect = null;
                    try { rect = sel.getRangeAt(0).getBoundingClientRect(); } catch (e) {}
                    if (!rect || (!rect.width && !rect.height)) {
                        hideBubble();
                        return;
                    }
                    var b = getBubble();
                    var left = rect.left + rect.width / 2 - 40;
                    var top = rect.top - 36;
                    if (top < 4) top = rect.bottom + 8;
                    left = Math.max(4, Math.min(left, window.innerWidth - 100));
                    b.style.left = Math.round(left) + 'px';
                    b.style.top = Math.round(top) + 'px';
                    b.style.display = 'block';
                } catch (e) {
                    hideBubble();
                }
            }

            document.addEventListener('mouseup', function() { setTimeout(showBubble, 10); });
            document.addEventListener('keyup', function(ev) {
                if (ev.key === 'Shift') setTimeout(showBubble, 10);
            });
            document.addEventListener('mousedown', function(ev) {
                try { if (bubble && ev.target !== bubble) hideBubble(); } catch (e) {}
            }, true);
            document.addEventListener('scroll', hideBubble, true);
            document.addEventListener('keydown', function(ev) {
                if (ev.key === 'Escape') hideBubble();
            });
            window.addEventListener('resize', hideBubble);
            addStyle();
        } catch (e) {}
    })();
    """


def ensure_text_highlight_script(profile, enabled: bool, base_dir=None) -> None:
    """Install or remove the per-profile "highlight text to copy" script.

    Profile-scoped (like forced dark) so it applies to every page in the
    profile from the first render — main browser tabs AND embedded previews
    that share the profile (Personal Hub → Sites) get the feature together.
    """
    try:
        scripts = profile.scripts()
    except Exception:
        return
    if base_dir:
        try:
            from litebrowser.core import prefs
            enabled = prefs.get_text_highlight_enabled(base_dir) if enabled is None else enabled
        except Exception:
            pass
    existing = None
    if hasattr(scripts, "findScript"):
        try:
            existing = scripts.findScript(_TEXT_HIGHLIGHT_SCRIPT_NAME)
        except Exception:
            existing = None
    if existing is None or (hasattr(existing, "isNull") and existing.isNull()):
        try:
            for s in scripts.toList():
                if s.name() == _TEXT_HIGHLIGHT_SCRIPT_NAME:
                    existing = s
                    break
        except Exception:
            pass
    if not enabled:
        if existing is not None and not (hasattr(existing, "isNull") and existing.isNull()):
            try:
                scripts.remove(existing)
            except Exception:
                pass
        return
    if existing is not None and not (hasattr(existing, "isNull") and existing.isNull()):
        return
    script = QWebEngineScript()
    script.setName(_TEXT_HIGHLIGHT_SCRIPT_NAME)
    script.setSourceCode(build_text_highlight_js(True))
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(False)
    scripts.insert(script)


def ensure_chrome_compat_script(profile, base_dir=None) -> None:
    """Uninstall the legacy Chrome-shape script from a profile.

    Mei <= 1.0.1 installed a DocumentCreation script on every profile that
    deleted ``navigator.webdriver``, replaced ``navigator.plugins``, invented
    ``deviceMemory`` and rewrote WebGL's unmasked vendor/renderer strings. That
    is fingerprint spoofing, not compatibility: it ran on every page and every
    subframe, contradicted the engine's native values, and existed to make
    anti-bot systems believe this was desktop Chrome.

    The script is no longer installed anywhere. This function is kept as an
    explicit *uninstall hook* (call sites in the main window and the personal
    hub still invoke it) so a profile that was created earlier in the same
    process cannot keep a stale script object alive. It never installs anything.
    """
    try:
        scripts = profile.scripts()
    except Exception:
        return
    try:
        legacy = scripts.findScript(_CHROME_COMPAT_SCRIPT_NAME)
    except Exception:
        legacy = None
    if legacy is not None and not (hasattr(legacy, "isNull") and legacy.isNull()):
        try:
            scripts.remove(legacy)
        except Exception:
            pass


class BrowserPage(QWebEnginePage):
    #: Emitted when a ``file://`` document outside the trusted roots was refused.
    localContentBlocked = pyqtSignal(str)

    def __init__(self, profile, parent, base_dir=None, host=None):
        super().__init__(profile, parent)
        # The page is owned by its QWebEngineView so discarding a hibernated
        # tab actually releases the Chromium renderer.  Keep the app window as
        # a separate interaction host for popups, permissions, and new tabs.
        self._host = host or parent
        self._base_dir = base_dir or (getattr(self._host, "base_dir", None) if self._host else None)
        # Uninstall the legacy Chrome-shape script if a profile created by an
        # older build still carries it. Nothing is installed: the engine now
        # reports its real identity (browser/engine_identity.py).
        ensure_chrome_compat_script(profile, self._base_dir)
        if self._base_dir:
            try:
                from litebrowser.core import prefs as _prefs
                ensure_forced_dark_script(profile, _prefs.effective_force_dark_web(self._base_dir), self._base_dir)
                ensure_webgl_disable_script(profile, _prefs.get_disable_webgl(self._base_dir))
            except Exception:
                pass
        self.featurePermissionRequested.connect(self._on_permission_requested)
        # A refused local document is the user's to resolve, so tell the host
        # window instead of letting the navigation fail with no explanation.
        try:
            handler = getattr(self._host, "on_local_content_blocked", None)
            if callable(handler):
                self.localContentBlocked.connect(handler)
        except Exception:
            pass
        # Seamless proxy authentication: Chromium asks the page for proxy
        # credentials at connection time; answer from the saved VPN config
        # instead of failing every request silently (v6.5 gap — SOCKS/HTTP
        # proxies with auth were unusable).
        self.proxyAuthenticationRequired.connect(self._on_proxy_auth_required)

    def _on_proxy_auth_required(self, url, authenticator, _proxy_host):
        cfg = {}
        try:
            from litebrowser.core import prefs as _prefs

            cfg = _prefs.get_proxy_config(self._base_dir) if self._base_dir else {}
        except Exception:
            cfg = {}
        user = str(cfg.get("user") or "")
        password = str(cfg.get("password") or "")
        if user:
            authenticator.setUser(user)
            authenticator.setPassword(password)

    def createWindow(self, _window_type):
        host = self._host
        if hasattr(host, "tab_manager"):
            browser = host.tab_manager.add_tab(QUrl("about:blank"), "New Tab", is_active=True)
            if browser is not None:
                return browser.page()
        return super().createWindow(_window_type)

    def _on_permission_requested(self, origin, feature):
        # Deny-by-default: a feature this build does not have a name for is not
        # one the user can meaningfully consent to. The old code prompted for
        # anything (including "feature_9"), which trains users to click Yes.
        known = self._known_feature(feature)
        if known is None:
            self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionDeniedByUser)
            return
        if not self._base_dir or not origin.isValid():
            self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionDeniedByUser)
            return
        origin_str = origin.toString()
        feature_name = known
        # Private browsing never inherits or persists a site permission. Ask
        # per session, and never write the answer to the persistent profile.
        try:
            incognito = bool(self.profile().isOffTheRecord())
        except Exception:
            incognito = False
        # Private browsing does not read the persistent profile's answers either:
        # a site the user once allowed the microphone in the normal profile must
        # be asked again here. Reading it was how a private tab inherited a grant
        # the user never made in this session, contradicting the comment above.
        saved = None if incognito else prefs.get_permission(self._base_dir, origin_str, feature_name)
        if saved == "allow":
            self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionGrantedByUser)
            return
        if saved == "deny":
            self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionDeniedByUser)
            return
        # Non-modal prompt: an app-modal exec_() inside this callback froze the
        # renderer IPC for the whole window until the user answered (v6.4).
        # The permission stays pending until we call setFeaturePermission, so
        # answering asynchronously is safe.
        msg = QMessageBox(self._host)
        msg.setWindowTitle("Permission request")
        msg.setText("Site %s requests permission: %s.\nAllow?" % (origin_str, feature_name))
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.NoToAll)
        msg.setDefaultButton(QMessageBox.No)

        def _decide(what, remember):
            if what == "allow":
                self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionGrantedByUser)
            else:
                self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionDeniedByUser)
            if remember and not incognito:
                try:
                    prefs.set_permission(self._base_dir, origin_str, feature_name, what)
                except Exception:
                    pass
            msg.deleteLater()

        msg.button(QMessageBox.Yes).clicked.connect(lambda: _decide("allow", True))
        msg.button(QMessageBox.NoToAll).clicked.connect(lambda: _decide("deny", True))
        msg.button(QMessageBox.No).clicked.connect(lambda: _decide("deny", False))
        msg.setModal(False)
        msg.show()

    def _trusted_local_roots(self):
        """Folders whose ``file://`` pages Mei ships or owns.

        A host that owns extra roots can expose them as ``trusted_local_roots``;
        a host without that attribute contributes none.
        """
        try:
            extra = tuple(getattr(self._host, "trusted_local_roots", None) or ())
        except (TypeError, AttributeError):
            extra = ()
        cache = getattr(self, "_local_roots_cache", None)
        if cache is not None and cache[0] == extra:
            return cache[1]
        from litebrowser.browser import local_content_policy as policy

        try:
            roots = policy.trusted_local_roots(self._base_dir, extra)
        except Exception:  # noqa: BLE001 - no roots means nothing is trusted
            roots = ()
        self._local_roots_cache = (extra, roots)
        return roots

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        """Refuse untrusted ``file://`` documents before they can load.

        The profile keeps ``LocalContentCanAccessRemoteUrls`` on because the
        bundled chain apps are real local pages calling their deployed APIs, and
        Qt cannot scope that switch to one origin. The gate is therefore here:
        a local document outside Mei's own folders never runs, so a downloaded
        ``.html`` cannot use the switch at all. Other schemes are untouched.

        Every frame is judged, not just the main one: an untrusted document in
        an iframe runs in the same renderer and reaches the same switch. The
        decision also fails closed — a ``file:`` document whose policy cannot be
        evaluated is refused, because the alternative is an unreviewed local page
        running with that switch in reach. A redirect's target arrives here as
        its own navigation request, so each hop is judged like the first.
        """
        try:
            scheme = str(url.scheme() if hasattr(url, "scheme") else "").lower()
        except Exception:  # noqa: BLE001 - an unreadable URL is not a file: document
            scheme = ""
        if scheme != "file":
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)

        try:
            target = url.toString() if hasattr(url, "toString") else str(url)
        except Exception:  # noqa: BLE001
            target = ""

        allowed = False
        try:
            from litebrowser.browser import local_content_policy as policy

            allow_untrusted = bool(
                self._base_dir and prefs.get_allow_untrusted_local_files(self._base_dir)
            )
            allowed = (
                policy.navigation_decision(target, self._trusted_local_roots(), allow_untrusted)
                == policy.ALLOW
            )
        except Exception:  # noqa: BLE001 - a gate that cannot judge must refuse
            allowed = False
        if allowed:
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)
        try:
            self.localContentBlocked.emit(target)
        except Exception:  # noqa: BLE001 - a host without the signal still gets the block
            pass
        return False

    def _feature_name(self, feature):
        """Backwards-compatible name lookup; unknown features get a slug."""
        known = self._known_feature(feature)
        return known if known is not None else "feature_%s" % int(feature)

    def _known_feature(self, feature):
        """Name of a permission Mei can explain, or None (deny by default)."""
        names = {
            QWebEnginePage.Geolocation: "geolocation",
            QWebEnginePage.MediaAudioCapture: "microphone",
            QWebEnginePage.MediaVideoCapture: "camera",
            QWebEnginePage.MediaAudioVideoCapture: "microphone_camera",
            QWebEnginePage.DesktopAudioVideoCapture: "desktop_capture",
            QWebEnginePage.Notifications: "notifications",
        }
        return names.get(feature)

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        lowered = (message or "").lower()
        noisy_fragments = (
            "mixed content:",
            "unrecognized feature:",
            "samesite",
            "chromestatus.com/feature",
            "requested an insecure image",
        )
        if any(fragment in lowered for fragment in noisy_fragments):
            return
        if os.environ.get("LITEBROWSER_DEBUG_JS"):
            print(f"js[{int(level)}] {source_id}:{line_number}: {message}")

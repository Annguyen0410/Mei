# Mei - Custom QWebEnginePage for permissions (notifications, geolocation)
import os

from PyQt5.QtCore import QUrl
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

_CHROME_STUB_JS = r"""
(function(){
    'use strict';
    /* ----------------------------------------------------------------
       Mei Chrome-compat shim.
       Goal: make Qt WebEngine (Chromium 122) look enough like real
       desktop Chrome that Google Gaia ("accounts.google.com"),
       Cloudflare bot-checks, and similar fingerprint scripts do not
       refuse sign-in with "This browser or app may not be secure".
       Runs at DocumentCreation in MainWorld so it executes BEFORE
       any page script reads navigator.* / window.chrome.
       ---------------------------------------------------------------- */

    /* Defining a non-configurable native property throws TypeError; wrap in try.
       Returns true when the override stuck, false otherwise — callers can fall back. */
    function tryDefine(obj, prop, descriptor) {
        try {
            var existing = Object.getOwnPropertyDescriptor(obj, prop);
            if (existing && existing.configurable === false) return false;
            Object.defineProperty(obj, prop, descriptor);
            return true;
        } catch (e) { return false; }
    }

    /* Make spoofed function look native to Function.prototype.toString fingerprinting.
       Real Chrome getters serialize to "function get foo() { [native code] }". Without
       this, anti-bot scripts can call e.g. navigator.__lookupGetter__('webdriver').toString()
       and immediately see our patched function source. */
    function makeNative(fn, name) {
        try {
            var label = 'function ' + (name || fn.name || '') + '() { [native code] }';
            Object.defineProperty(fn, 'toString', {
                value: function toString() { return label; },
                configurable: true,
                writable: true
            });
            Object.defineProperty(fn.toString, 'toString', {
                value: function toString() { return 'function toString() { [native code] }'; },
                configurable: true,
                writable: true
            });
        } catch (e) {}
        return fn;
    }

    /* 1. navigator.webdriver — Gaia explicitly checks this and refuses sign-in
          when it is true. Qt WebEngine returns false (real Chrome returns
          undefined when not under automation). Force undefined. */
    try { delete navigator.webdriver; } catch (e) {}
    try { delete Object.getPrototypeOf(navigator).webdriver; } catch (e) {}
    var webdriverGetter = makeNative(function() { return undefined; }, 'get webdriver');
    tryDefine(navigator, 'webdriver', {
        get: webdriverGetter, configurable: true, enumerable: true
    });
    tryDefine(Object.getPrototypeOf(navigator), 'webdriver', {
        get: webdriverGetter, configurable: true, enumerable: true
    });

    var host = (location.hostname || '').toLowerCase();
    var sensitiveHosts = [
        'accounts.google.com',
        'google.com',
        'googleusercontent.com',
        'gstatic.com',
        'youtube.com',
        'googleapis.com',
        'gemini.google.com',
        'openai.com',
        'chatgpt.com',
        'oaistatic.com',
        'oaiusercontent.com',
        'anthropic.com',
        'claude.ai',
        'microsoft.com',
        'bing.com',
        'copilot.microsoft.com',
        'perplexity.ai'
    ];
    var isSensitive = sensitiveHosts.some(function(d){ return host === d || host.endsWith('.' + d); });

    /* 2. window.chrome.* — Chromium 122 ships an empty stub `window.chrome`,
          but Gaia probes for chrome.app, chrome.csi(), chrome.loadTimes(), and
          chrome.runtime. Missing any of those is read as "embedded WebView".
          Real Chrome on a normal page exposes ALL of them. */
    function ensureChromeShape() {
        try {
            if (!window.chrome || typeof window.chrome !== 'object') window.chrome = {};
            var c = window.chrome;
            if (!c.app) {
                c.app = {
                    isInstalled: false,
                    InstallState: {DISABLED:'disabled', INSTALLED:'installed', NOT_INSTALLED:'not_installed'},
                    RunningState: {CANNOT_RUN:'cannot_run', READY_TO_RUN:'ready_to_run', RUNNING:'running'},
                    getDetails: function(){ return null; },
                    getIsInstalled: function(){ return false; },
                    runningState: function(){ return 'cannot_run'; }
                };
            }
            if (typeof c.csi !== 'function') {
                c.csi = makeNative(function csi(){
                    return { startE: Date.now(), onloadT: Date.now(), pageT: 0, tran: 15 };
                }, 'csi');
            }
            if (typeof c.loadTimes !== 'function') {
                c.loadTimes = makeNative(function loadTimes(){
                    var now = Date.now() / 1000;
                    return {
                        requestTime: now, startLoadTime: now, commitLoadTime: now,
                        finishDocumentLoadTime: now, finishLoadTime: now,
                        firstPaintTime: 0, firstPaintAfterLoadTime: 0,
                        navigationType: 'Other',
                        wasFetchedViaSpdy: true, wasNpnNegotiated: true,
                        npnNegotiatedProtocol: 'h2',
                        wasAlternateProtocolAvailable: false, connectionInfo: 'h2'
                    };
                }, 'loadTimes');
            }
            /* chrome.runtime: Chromium 122 already provides an empty {} on most
               regular pages; only fill in the enums Gaia inspects. Do NOT add
               .id (real Chrome leaves it undefined on non-extension contexts). */
            if (!c.runtime || typeof c.runtime !== 'object') c.runtime = {};
            var rt = c.runtime;
            if (!rt.OnInstalledReason)         rt.OnInstalledReason         = {INSTALL:'install',UPDATE:'update',CHROME_UPDATE:'chrome_update',SHARED_MODULE_UPDATE:'shared_module_update'};
            if (!rt.OnRestartRequiredReason)   rt.OnRestartRequiredReason   = {APP_UPDATE:'app_update',OS_UPDATE:'os_update',PERIODIC:'periodic'};
            if (!rt.PlatformOs)                rt.PlatformOs                = {MAC:'mac',WIN:'win',ANDROID:'android',CROS:'cros',LINUX:'linux',OPENBSD:'openbsd'};
            if (!rt.PlatformArch)              rt.PlatformArch              = {ARM:'arm',X86_32:'x86-32',X86_64:'x86-64',MIPS:'mips',MIPS64:'mips64'};
            if (!rt.PlatformNaclArch)          rt.PlatformNaclArch          = {ARM:'arm',X86_32:'x86-32',X86_64:'x86-64',MIPS:'mips',MIPS64:'mips64'};
            if (!rt.RequestUpdateCheckStatus)  rt.RequestUpdateCheckStatus  = {THROTTLED:'throttled',NO_UPDATE:'no_update',UPDATE_AVAILABLE:'update_available'};
            if (!c.webstore) {
                c.webstore = {
                    onInstallStageChanged: {addListener: function(){}, removeListener: function(){}},
                    onDownloadProgress: {addListener: function(){}, removeListener: function(){}},
                    install: function(url, onSuccess, onFailure){ (onFailure || function(){})('In-app store is not supported in Mei', 'INTERNAL_ERROR'); },
                    setStoreLoginState: function(){}
                };
            }
        } catch (e) {}
    }

    /* 3. navigator.plugins — non-empty PDF list mirrors real Chrome on Windows. */
    function ensurePlugins() {
        if (navigator.plugins && navigator.plugins.length > 0) return;
        var fakePlugins = [
            { name: 'PDF Viewer',              filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer',       filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chromium PDF Viewer',     filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'WebKit built-in PDF',     filename: 'internal-pdf-viewer', description: 'Portable Document Format' }
        ];
        tryDefine(navigator, 'plugins', {
            get: makeNative(function(){ return fakePlugins; }, 'get plugins'),
            configurable: true
        });
    }

    /* 4. navigator.languages — empty array reads as headless. */
    function ensureLanguages() {
        if (navigator.languages && navigator.languages.length > 0) return;
        tryDefine(navigator, 'languages', {
            get: makeNative(function(){ return ['en-US','en']; }, 'get languages'),
            configurable: true
        });
    }

    /* 5. navigator.userAgentData — JS side of Client Hints.
          Chromium 122 in Qt provides a userAgentData but its `brands` may miss
          the "Google Chrome" brand that Gaia keys on. We patch ONLY when the
          existing object is missing brands or platform; never blindly redefine. */
    function ensureUserAgentData() {
        var current = navigator.userAgentData;
        var hasGoodBrands = current && Array.isArray(current.brands) && current.brands.length >= 2 &&
            current.brands.some(function(b){ return /chrome/i.test(b.brand || ''); });
        var hasGoodPlatform = current && typeof current.platform === 'string' && current.platform;
        if (hasGoodBrands && hasGoodPlatform) return;

        var uaMatch = /Chrome\/(\d+)(?:\.(\d+)\.(\d+)\.(\d+))?/.exec(navigator.userAgent || '');
        var chromeMajor = uaMatch ? uaMatch[1] : '122';
        var fullVer = uaMatch && uaMatch[2] ? (uaMatch[1]+'.'+uaMatch[2]+'.'+uaMatch[3]+'.'+uaMatch[4]) : (chromeMajor + '.0.0.0');
        var brands = [
            { brand: 'Chromium',      version: chromeMajor },
            { brand: 'Not(A:Brand',   version: '24'       },
            { brand: 'Google Chrome', version: chromeMajor }
        ];
        var fullVersionList = [
            { brand: 'Chromium',      version: fullVer    },
            { brand: 'Not(A:Brand',   version: '24.0.0.0' },
            { brand: 'Google Chrome', version: fullVer    }
        ];
        var uad = {
            brands: brands,
            mobile: false,
            platform: 'Windows',
            getHighEntropyValues: makeNative(function(hints){
                var out = {
                    brands: brands, mobile: false, platform: 'Windows',
                    platformVersion: '15.0.0', architecture: 'x86', bitness: '64',
                    model: '', uaFullVersion: fullVer,
                    fullVersionList: fullVersionList, wow64: false
                };
                var result = {};
                (hints || []).forEach(function(h){ if (h in out) result[h] = out[h]; });
                return Promise.resolve(result);
            }, 'getHighEntropyValues'),
            toJSON: function(){ return { brands: brands, mobile: false, platform: 'Windows' }; }
        };
        tryDefine(navigator, 'userAgentData', {
            get: makeNative(function(){ return uad; }, 'get userAgentData'),
            configurable: true
        });
    }

    /* 6. navigator.permissions.query — Notifications API quirk.
          Real Chrome returns the actual Notification.permission state for the
          'notifications' query; some builds of Qt WebEngine return 'denied'
          which scripts read as "embedded view". Patch on every host. */
    function patchPermissions() {
        try {
            if (!navigator.permissions || typeof navigator.permissions.query !== 'function') return;
            var origQuery = navigator.permissions.query.bind(navigator.permissions);
            navigator.permissions.query = makeNative(function(params){
                if (params && params.name === 'notifications') {
                    try { return Promise.resolve({ state: Notification.permission, onchange: null }); } catch (eN) {}
                }
                return origQuery(params);
            }, 'query');
        } catch (e) {}
    }

    /* 7. navigator hardware signals — headless / embedded Chromium builds
          sometimes omit or zero these. A missing deviceMemory or a 0
          hardwareConcurrency is a classic bot/WebView tell. Only patch when
          the real value is missing; never clobber real hardware info. */
    function ensureDeviceSignals() {
        if (typeof navigator.deviceMemory === 'undefined') {
            tryDefine(navigator, 'deviceMemory', { get: makeNative(function(){ return 8; }, 'get deviceMemory'), configurable: true });
        }
        if (!navigator.hardwareConcurrency) {
            tryDefine(navigator, 'hardwareConcurrency', { get: makeNative(function(){ return 8; }, 'get hardwareConcurrency'), configurable: true });
        }
        if (!navigator.vendor) {
            tryDefine(navigator, 'vendor', { get: makeNative(function(){ return 'Google Inc.'; }, 'get vendor'), configurable: true });
        }
        if (typeof navigator.maxTouchPoints === 'undefined') {
            tryDefine(navigator, 'maxTouchPoints', { get: makeNative(function(){ return 0; }, 'get maxTouchPoints'), configurable: true });
        }
        if (typeof navigator.onLine === 'undefined') {
            tryDefine(navigator, 'onLine', { get: makeNative(function(){ return true; }, 'get onLine'), configurable: true });
        }
    }

    /* 8. WebGL unmasked renderer/vendor — anti-bot scripts call
          gl.getParameter(UNMASKED_VENDOR_WEBGL / UNMASKED_RENDERER_WEBGL) to
          read the GPU string. Some embedded builds return '' or a software
          renderer (SwiftShader/llvmpipe) that real desktop Chrome wouldn't.
          We only rewrite when the value looks wrong; real GPU strings pass
          through untouched so WebGL sites are unaffected. */
    function patchWebGL() {
        var VENDOR = 37445, RENDERER = 37446;  // UNMASKED_VENDOR_WEBGL, UNMASKED_RENDERER_WEBGL
        var cleanVendor = 'Google Inc.';
        var cleanRenderer = 'ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)';
        var bad = /Qt|WebKit|SwiftShader|llvmpipe|softpipe|software|Mesa|llvm/i;
        function wrap(proto) {
            if (!proto || typeof proto.getParameter !== 'function') return;
            var orig = proto.getParameter;
            proto.getParameter = function(p) {
                var val = orig.apply(this, arguments);
                if (p === VENDOR && (!val || bad.test(String(val)))) return cleanVendor;
                if (p === RENDERER && (!val || bad.test(String(val)))) return cleanRenderer;
                return val;
            };
        }
        var glCtx = (typeof WebGLRenderingContext !== 'undefined') ? WebGLRenderingContext : (window.WebGLRenderingContext || null);
        var gl2Ctx = (typeof WebGL2RenderingContext !== 'undefined') ? WebGL2RenderingContext : (window.WebGL2RenderingContext || null);
        try { wrap(glCtx && glCtx.prototype); } catch (e) {}
        try { wrap(gl2Ctx && gl2Ctx.prototype); } catch (e) {}
    }

    /* Run on every page (sensitive or not): minimal hardening. */
    ensureChromeShape();
    ensurePlugins();
    ensureLanguages();
    ensureUserAgentData();
    patchPermissions();
    ensureDeviceSignals();
    patchWebGL();
})();
"""


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
    if not base_dir:
        try:
            from litebrowser.core import prefs
            enabled = prefs.get_force_dark_web(base_dir) if enabled is None else enabled
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
    """Install or remove the Chrome-shape JS shim on a QWebEngineProfile based on user pref."""
    try:
        scripts = profile.scripts()
    except Exception:
        return
    if base_dir:
        try:
            from litebrowser.core import prefs
            enabled = prefs.get_chrome_compat_shim(base_dir)
        except Exception:
            enabled = True
    else:
        enabled = True
    existing = None
    if hasattr(scripts, "findScript"):
        try:
            existing = scripts.findScript(_CHROME_COMPAT_SCRIPT_NAME)
        except Exception:
            existing = None
    if existing is None or (hasattr(existing, "isNull") and existing.isNull()):
        try:
            iter_scripts = scripts.toList()
        except Exception:
            iter_scripts = []
        for s in iter_scripts:
            try:
                if s.name() == _CHROME_COMPAT_SCRIPT_NAME:
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
    script.setName(_CHROME_COMPAT_SCRIPT_NAME)
    script.setSourceCode(_CHROME_STUB_JS)
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(True)
    scripts.insert(script)


class BrowserPage(QWebEnginePage):
    def __init__(self, profile, parent, base_dir=None, host=None):
        super().__init__(profile, parent)
        # The page is owned by its QWebEngineView so discarding a hibernated
        # tab actually releases the Chromium renderer.  Keep the app window as
        # a separate interaction host for popups, permissions, and new tabs.
        self._host = host or parent
        self._base_dir = base_dir or (getattr(self._host, "base_dir", None) if self._host else None)
        # Install the chrome-compat shim on the *profile* once. Page-level
        # script collections in Qt WebEngine are bound to the renderer only
        # after the page <-> renderer wiring settles, which can race with the
        # very first navigation issued during tab construction; profile-level
        # scripts are bound at renderer process start and run reliably from
        # the first DocumentCreation event onward (verified vs Chromium 122).
        ensure_chrome_compat_script(profile, self._base_dir)
        if self._base_dir:
            try:
                from litebrowser.core import prefs as _prefs
                ensure_forced_dark_script(profile, _prefs.get_force_dark_web(self._base_dir), self._base_dir)
            except Exception:
                pass
        self.featurePermissionRequested.connect(self._on_permission_requested)

    def createWindow(self, _window_type):
        host = self._host
        if hasattr(host, "tab_manager"):
            browser = host.tab_manager.add_tab(QUrl("about:blank"), "New Tab", is_active=True)
            if browser is not None:
                return browser.page()
        return super().createWindow(_window_type)

    def _on_permission_requested(self, origin, feature):
        if not self._base_dir:
            self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionDeniedByUser)
            return
        origin_str = origin.toString()
        feature_name = self._feature_name(feature)
        saved = prefs.get_permission(self._base_dir, origin_str, feature_name)
        if saved == "allow":
            self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionGrantedByUser)
            return
        if saved == "deny":
            self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionDeniedByUser)
            return
        msg = QMessageBox(self._host)
        msg.setWindowTitle("Permission request")
        msg.setText("Site %s requests permission: %s.\nAllow?" % (origin_str, feature_name))
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.NoToAll)
        msg.setDefaultButton(QMessageBox.No)
        ret = msg.exec_()
        if ret == QMessageBox.Yes:
            self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionGrantedByUser)
            prefs.set_permission(self._base_dir, origin_str, feature_name, "allow")
        elif ret == QMessageBox.NoToAll:
            self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionDeniedByUser)
            prefs.set_permission(self._base_dir, origin_str, feature_name, "deny")
        else:
            self.setFeaturePermission(origin, feature, QWebEnginePage.PermissionDeniedByUser)

    def _feature_name(self, feature):
        names = {
            QWebEnginePage.Geolocation: "geolocation",
            QWebEnginePage.MediaAudioCapture: "microphone",
            QWebEnginePage.MediaVideoCapture: "camera",
            QWebEnginePage.MediaAudioVideoCapture: "microphone_camera",
            QWebEnginePage.DesktopAudioVideoCapture: "desktop_capture",
            QWebEnginePage.Notifications: "notifications",
        }
        return names.get(feature, "feature_%s" % int(feature))

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

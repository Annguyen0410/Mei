"""One-click VPN / proxy hub: quick presets + optional public proxy list (use at your own risk)."""
from __future__ import annotations

import json
import os
import re
import socket
import struct
import time
import urllib.error
import urllib.request
from typing import Any

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtNetwork import QNetworkProxy
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from litebrowser.core import prefs
from litebrowser.ui.dialogs import sessions as sessions_dialog
from litebrowser.ui.dialogs.common import _stylesheet


def _test_proxy_connection(host: str, port: int, kind: str, timeout: float = 6.0) -> tuple[bool, str]:
    """Real proxy reachability test.

    Returns (ok, message). Tries a CONNECT to example.com:443 for HTTP proxies
    and a SOCKS5 greeting + CONNECT for SOCKS5 proxies. Pure stdlib so no extra
    dependency, and works even if QtWebEngine has not been restarted yet.
    """
    sock = None
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        if kind == "http":
            req = (
                "CONNECT example.com:443 HTTP/1.1\r\n"
                "Host: example.com:443\r\n"
                "User-Agent: Mei-VPN-Test/1\r\n"
                "Proxy-Connection: Keep-Alive\r\n\r\n"
            ).encode("ascii")
            sock.sendall(req)
            sock.settimeout(timeout)
            data = sock.recv(256) or b""
            head = data.split(b"\r\n", 1)[0].decode("ascii", "ignore")
            if " 200 " in head or head.endswith(" 200"):
                return True, "OK · " + head
            return False, "Proxy refused the CONNECT: " + head
        if kind == "socks5":
            sock.sendall(b"\x05\x01\x00")
            resp = sock.recv(2)
            if not resp or len(resp) < 2 or resp[0] != 0x05:
                return False, "Not a SOCKS5 proxy (bad greeting)"
            if resp[1] == 0xFF:
                return False, "SOCKS5 requires authentication — this preset doesn't support user/pass"
            target = b"example.com"
            packet = b"\x05\x01\x00\x03" + bytes([len(target)]) + target + struct.pack(">H", 443)
            sock.sendall(packet)
            reply = sock.recv(10)
            if not reply or len(reply) < 2 or reply[0] != 0x05:
                return False, "SOCKS5 proxy sent a malformed reply"
            if reply[1] != 0x00:
                codes = {
                    0x01: "general failure", 0x02: "connection not allowed",
                    0x03: "network unreachable", 0x04: "host unreachable",
                    0x05: "connection refused", 0x06: "TTL expired",
                    0x07: "command not supported", 0x08: "address type not supported",
                }
                return False, "SOCKS5 error: " + codes.get(reply[1], "code=%d" % reply[1])
            return True, "OK · SOCKS5 CONNECT succeeded"
        return False, "Proxy type does not support testing: " + kind
    except (TimeoutError, ConnectionRefusedError, ConnectionResetError) as exc:
        return False, "Could not connect: " + str(exc)
    except OSError as exc:
        return False, "Network error: " + str(exc)
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


# Curated quick presets (no keys; user still picks from list). Tor ports are common defaults.
_BUILTIN_PRESETS: list[dict[str, Any]] = [
    {"name": "Tor Browser (SOCKS5)", "host": "127.0.0.1", "port": 9150, "type": "socks5", "note": "While Tor Browser is running"},
    {"name": "Tor (port 9050)", "host": "127.0.0.1", "port": 9050, "type": "socks5", "note": "tor.exe default"},
    {"name": "Manual configuration (form)", "host": "", "port": 0, "type": "manual", "note": "Enter your own host/port"},
]


def _user_presets_path(base_dir: str) -> str:
    return os.path.join(base_dir, "vpn_quick_presets.json")


def _load_user_presets(base_dir: str) -> list[dict[str, Any]]:
    path = _user_presets_path(base_dir)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _fetch_public_https_proxies(max_lines: int = 30) -> list[str]:
    """Fetch plaintext host:port lines from a public API (quality varies; HTTPS only)."""
    url = (
        "https://api.proxyscrape.com/v2/?request=displayproxies"
        "&protocol=https&timeout=10000&country=all&ssl=all&anonymity=all"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mei/3 VPN-hub"})
    with urllib.request.urlopen(req, timeout=18) as resp:
        text = resp.read().decode("utf-8", errors="ignore")
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if re.match(r"^[\w.-]+:\d{1,5}$", line):
            out.append(line)
        if len(out) >= max_lines:
            break
    return out


def _fetch_ip_info(timeout: float = 8.0) -> dict:
    """Free IP intelligence (no key): ipleak.net JSON — ip, country, isp."""
    req = urllib.request.Request("https://ipleak.net/json/", headers={"User-Agent": "Mei/6 VPN-hub"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="ignore"))
    if not isinstance(data, dict):
        return {}
    return {
        "ip": str(data.get("ip") or ""),
        "country": str(data.get("country_name") or ""),
        "isp": str(data.get("isp") or data.get("as_number") or ""),
    }


def run_leak_test(parent, base_dir) -> None:
    """DNS-leak style audit, free: the visible IP is fetched via the OS
    resolver; a WebEngine tab (Chromium path) fetches it again. If the two
    differ, DNS/traffic is partially bypassing the proxy."""
    QApplication.setOverrideCursor(Qt.WaitCursor)
    os_ip, browser_ip, errors = "", "", []
    try:
        os_ip = _fetch_ip_info().get("ip", "")
    except Exception as exc:
        errors.append(f"OS path: {exc}")
    browser_path_ip = {"v": ""}

    def _finish():
        QApplication.restoreOverrideCursor()
        protected = bool(prefs.get_proxy_config(base_dir).get("enabled"))
        if errors and not browser_ip:
            body = ("Could not complete the leak test:\n" + "\n".join(errors[:2]) +
                    "\n\n(Check your connection and try again.)")
            QMessageBox.warning(parent, "VPN leak test", body)
            return
        if protected and browser_ip and os_ip and browser_ip == os_ip:
            verdict = ("⚠ <b>Possible leak:</b> the browser's visible IP matches the direct path while a proxy is enabled. "
                       "The proxy may not be covering all traffic.")
        elif protected and browser_ip:
            verdict = f"🛡 <b>No obvious leak.</b> Browser exits via {browser_ip}; direct path was {os_ip or 'unknown'}."
        else:
            verdict = f"ℹ No proxy enabled. Browser IP: <b>{browser_ip or '?'}</b> · direct: {os_ip or '?'}"
        box = QMessageBox(parent)
        box.setWindowTitle("VPN leak test")
        box.setTextFormat(Qt.RichText)
        box.setText(verdict)
        box.exec_()

    from litebrowser.browser import new_tab_page  # noqa: F401  (ensures WebEngine import)

    probe_view = QWebEngineView(parent)

    def _on_load(ok):
        if not ok:
            errors.append("browser path: page load failed")
            _finish()
            return

        def _grab(text):
            m = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", text or "")
            browser_path_ip["v"] = m.group(1) if m else ""
            probe_view.deleteLater()
            _finish()

        probe_view.page().toPlainText(_grab)

    probe_view.loadFinished.connect(_on_load)
    probe_view.load(QUrl("https://ipv4.ipleak.net/json/"))


def show_vpn_hub(parent) -> None:
    base_dir = parent.base_dir
    dlg = QDialog(parent)
    dlg.setWindowTitle("VPN / Proxy — Mei Shield")
    dlg.resize(560, 640)
    dlg.setStyleSheet(_stylesheet(parent))
    layout = QVBoxLayout(dlg)

    # --- Status card: are we protected right now, and what does the world see? ---
    cfg_now = prefs.get_proxy_config(base_dir)
    active = bool(cfg_now.get("enabled"))
    status_card = QLabel()
    status_card.setObjectName("SectionCard")
    status_card.setWordWrap(True)
    status_card.setTextFormat(Qt.RichText)
    status_card.setContentsMargins(14, 10, 14, 10)
    layout.addWidget(status_card)

    def _paint_status(ip_info: dict | None = None, err: str = ""):
        if active:
            route = "%s:%s (%s)" % (cfg_now.get("host"), cfg_now.get("port"), str(cfg_now.get("type") or "").upper())
            head = f"🛡 <b>Protected</b> — routing via {route}"
        else:
            head = "⚪ <b>Unprotected</b> — direct connection"
        if ip_info:
            tail = f"Visible IP: <b>{ip_info.get('ip', '?')}</b> · {ip_info.get('country', '?')} · {ip_info.get('isp', '?')}"
        elif err:
            tail = f"Visible IP: <i>lookup failed ({err})</i>"
        else:
            tail = "<i>Looking up your visible IP…</i>"
        status_card.setText(head + "<br>" + tail)

    _paint_status()
    layout.addWidget(QLabel(
        "Free public proxies are usually <b>slow / unreliable</b> and may read your HTTP traffic. "
        "For testing only; real VPNs (WireGuard/OpenVPN) need separate software."
    ))
    warn = QLabel("")
    warn.hide()
    # (kept label variable name for layout clarity below)
    layout.addWidget(warn)
    warn.hide()

    from PyQt5.QtCore import QThread, pyqtSignal as _sig

    class _IpProbe(QThread):
        done = _sig(dict)
        failed = _sig(str)

        def run(self):
            try:
                self.done.emit(_fetch_ip_info())
            except Exception as exc:
                self.failed.emit(str(exc))

    probe = _IpProbe(dlg)
    probe.done.connect(lambda info: _paint_status(info))
    probe.failed.connect(lambda err: _paint_status(None, err[:80]))
    probe.start()

    list_w = QListWidget()
    list_w.setMinimumHeight(220)

    def add_preset_row(label: str, meta: dict[str, Any]) -> None:
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, meta)
        list_w.addItem(item)

    for p in _BUILTIN_PRESETS:
        note = p.get("note") or ""
        add_preset_row(f"{p['name']}  —  {note}", dict(p))

    for p in _load_user_presets(base_dir):
        if not isinstance(p, dict):
            continue
        name = (p.get("name") or "Custom").strip()
        host = (p.get("host") or "").strip()
        port = int(p.get("port") or 0)
        typ = (p.get("type") or "http").lower()
        if not host or port <= 0:
            continue
        add_preset_row(f"{name}  ({typ})  {host}:{port}", {"name": name, "host": host, "port": port, "type": typ, "note": ""})

    layout.addWidget(list_w)

    fetch_row = QHBoxLayout()
    chk_risk = QCheckBox("I understand the risks and want to load a public HTTPS proxy list")
    fetch_btn = QPushButton("Load free proxies (HTTPS)")
    fetch_row.addWidget(chk_risk, 1)
    fetch_row.addWidget(fetch_btn)
    layout.addLayout(fetch_row)

    chk_auto = QCheckBox("Auto-connect this proxy every time Mei starts")
    chk_auto.setChecked(prefs.get_auto_connect_vpn(base_dir))
    layout.addWidget(chk_auto)

    def _persist_auto():
        prefs.set_auto_connect_vpn(base_dir, chk_auto.isChecked())

    seen_public: set[str] = set()

    def on_fetch():
        if not chk_risk.isChecked():
            QMessageBox.warning(dlg, "VPN hub", "Tick the risk acknowledgment before loading the list.")
            return
        try:
            lines = _fetch_public_https_proxies(40)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            QMessageBox.warning(dlg, "VPN hub", f"Could not load the list: {e}")
            return
        if not lines:
            QMessageBox.information(dlg, "VPN hub", "The API returned no valid lines. Try again later.")
            return
        added = 0
        for line in lines:
            if line in seen_public:
                continue
            seen_public.add(line)
            host, _, port_s = line.partition(":")
            meta = {"name": f"Public HTTPS {host}", "host": host, "port": int(port_s), "type": "http", "note": "public"}
            item = QListWidgetItem(f"{meta['name']}:{port_s}  (HTTP CONNECT → HTTPS)")
            item.setData(Qt.UserRole, meta)
            list_w.addItem(item)
            added += 1
        QMessageBox.information(dlg, "VPN hub", f"Added {added} new proxies. Select one line, then click Connect.")

    fetch_btn.clicked.connect(on_fetch)

    btn_row = QHBoxLayout()
    btn_test = QPushButton("Test connection")
    btn_leak = QPushButton("Run leak test")
    btn_connect = QPushButton("Connect (select 1 line)")
    btn_disconnect = QPushButton("Disconnect proxy")
    btn_manual = QPushButton("Detailed form…")
    btn_close = QPushButton("Close")
    btn_row.addWidget(btn_test)
    btn_row.addWidget(btn_leak)
    btn_row.addWidget(btn_connect)
    btn_row.addWidget(btn_disconnect)
    btn_row.addWidget(btn_manual)
    btn_row.addStretch()
    btn_row.addWidget(btn_close)
    layout.addLayout(btn_row)

    def _selected_meta() -> dict[str, Any] | None:
        item = list_w.currentItem()
        if not item:
            return None
        meta = item.data(Qt.UserRole) or {}
        if not isinstance(meta, dict):
            return None
        return meta

    def on_test():
        meta = _selected_meta()
        if not meta or meta.get("type") == "manual":
            QMessageBox.information(dlg, "VPN hub", "Select a specific preset (not 'Manual configuration').")
            return
        host = (meta.get("host") or "").strip()
        port = int(meta.get("port") or 0)
        if not host or port <= 0:
            QMessageBox.warning(dlg, "VPN hub", "Invalid preset.")
            return
        kind = "socks5" if (meta.get("type") or "").lower().startswith("socks") else "http"
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            t0 = time.monotonic()
            ok, msg = _test_proxy_connection(host, port, kind, timeout=6.0)
            dt = (time.monotonic() - t0) * 1000.0
        finally:
            QApplication.restoreOverrideCursor()
        title = "VPN hub — proxy OK" if ok else "VPN hub — proxy NOT working"
        body = "%s:%d (%s)\n\n%s\n(%.0f ms)" % (host, port, kind.upper(), msg, dt)
        if ok:
            QMessageBox.information(dlg, title, body)
        else:
            QMessageBox.warning(dlg, title, body)

    btn_test.clicked.connect(on_test)
    btn_leak.clicked.connect(lambda: run_leak_test(parent, base_dir))

    def apply_cfg(cfg: dict[str, Any]) -> None:
        prefs.set_proxy_config(base_dir, cfg)
        if cfg.get("enabled"):
            prefs.set_last_vpn_proxy(base_dir, cfg)
        parent._set_proxy_from_config(cfg)

    def on_connect():
        item = list_w.currentItem()
        if not item:
            QMessageBox.information(dlg, "VPN hub", "Select a preset or proxy from the list.")
            return
        meta = item.data(Qt.UserRole) or {}
        if meta.get("type") == "manual":
            dlg.accept()
            sessions_dialog.show_vpn_dialog(parent)
            return
        host = (meta.get("host") or "").strip()
        port = int(meta.get("port") or 0)
        if not host or port < 1 or port > 65535:
            QMessageBox.warning(dlg, "VPN hub", "Invalid preset.")
            return
        typ = (meta.get("type") or "http").lower()
        norm = "socks5" if typ.startswith("socks") else "http"

        # 1) Verify the proxy actually answers before we commit the user to it.
        kind = "socks5" if norm == "socks5" else "http"
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, detail = _test_proxy_connection(host, port, kind, timeout=8.0)
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            retry = QMessageBox.question(
                dlg,
                "VPN hub — proxy not responding",
                f"{host}:{port} ({norm.upper()}) did not pass the check:\n{detail}\n\n"
                "Enable this proxy anyway? (pages may fail to load)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if retry != QMessageBox.Yes:
                return

        cfg = {
            "enabled": True,
            "type": norm,
            "host": host,
            "port": port,
            "user": None,
            "password": None,
        }
        apply_cfg(cfg)
        _persist_auto()
        # Smart restart: session was already saved by the launcher; relaunching
        # applies the Chromium flag with tabs intact (~2 s, no manual steps).
        relaunch = getattr(parent, "smart_restart", None)
        dlg.accept()
        if relaunch is not None:
            relaunch(reason=f"VPN connected: {host}:{port}")
        else:
            QMessageBox.information(
                dlg,
                "VPN hub",
                f"Proxy enabled: {host}:{port} ({norm.upper()})\n\nRestart Mei to route all tabs through it.",
            )

    def on_disconnect():
        prefs.set_proxy_config(base_dir, {"enabled": False})
        prefs.set_auto_connect_vpn(base_dir, False)
        QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.NoProxy))
        existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(
            tok for tok in existing.split() if not tok.startswith("--proxy-server=")
        ).strip()
        relaunch = getattr(parent, "smart_restart", None)
        dlg.accept()
        if relaunch is not None:
            relaunch(reason="VPN disconnected")
        else:
            QMessageBox.information(
                dlg,
                "VPN hub",
                "Proxy disabled.\nRestart Mei so web tabs no longer route through the proxy.",
            )

    btn_connect.clicked.connect(on_connect)
    btn_disconnect.clicked.connect(on_disconnect)
    def _open_manual():
        dlg.accept()
        sessions_dialog.show_vpn_dialog(parent)

    btn_manual.clicked.connect(_open_manual)
    btn_close.clicked.connect(dlg.reject)

    presets_hint = QLabel(
        "Custom presets (JSON): add a vpn_quick_presets.json file in the profile with an array "
        '[{"name":"...","host":"...","port":8080,"type":"http"}, ...]'
    )
    presets_hint.setWordWrap(True)
    presets_hint.setObjectName("MutedLabel")
    layout.addWidget(presets_hint)

    dlg.exec_()

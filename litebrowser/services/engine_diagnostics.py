"""Facts about the browser engine, for Settings → Browser Diagnostics.

A browser's engine is its most important product fact and it used to be visible
only inside an exported zip. This module turns the engine facts into a readable
report. It imports no Qt: the GUI passes what only a running application can
know (binding, Qt version, Chromium build, UA, GPU flags), exactly like
``services/diagnostics.py`` does, so this stays importable in tests.

Every field that cannot be determined honestly says ``Unknown``. The report is
what Mei *knows*, not what it would like to claim — a fabricated value here
would hide exactly the version skew this page exists to expose.
"""

from __future__ import annotations

import os
import platform
import sys

from litebrowser.core import engine_security, product

UNKNOWN = "Unknown"

#: Below this, the engine is old enough that modern sites refuse it. Qt 5.15 is
#: Chromium 87; Qt 6.11 is 140.
MIN_SUPPORTED_CHROMIUM = 120

ENV_SANDBOX_OFF = "QTWEBENGINE_DISABLE_SANDBOX"
ENV_CHROMIUM_FLAGS = "QTWEBENGINE_CHROMIUM_FLAGS"


def _clean(value) -> str:
    text = str(value or "").strip()
    return text or UNKNOWN


def chromium_major(chromium: str) -> int:
    try:
        return int(str(chromium or "").split(".")[0])
    except (TypeError, ValueError):
        return 0


def sandbox_status(environ=None) -> str:
    """Best-effort sandbox state, or Unknown when it cannot be proven.

    There is no reliable Qt API that reports the Chromium sandbox state at
    runtime on Windows, so this reports only what can be seen: an explicit
    opt-out in the environment, or Unknown. It never claims "enabled" without
    evidence.
    """
    env = os.environ if environ is None else environ
    value = str(env.get(ENV_SANDBOX_OFF, "") or "").strip().lower()
    if value in ("1", "true", "yes", "on"):
        return "Disabled by QTWEBENGINE_DISABLE_SANDBOX (insecure)"
    return UNKNOWN


def hardware_acceleration_status(environ=None) -> str:
    env = os.environ if environ is None else environ
    flags = str(env.get(ENV_CHROMIUM_FLAGS, "") or "").lower()
    if "--disable-gpu" in flags:
        return "Disabled by QTWEBENGINE_CHROMIUM_FLAGS"
    if "--disable-software-rasterizer" in flags:
        return "Software rasterizer disabled by environment"
    return UNKNOWN


def collect(ui: dict | None = None, environ=None) -> dict:
    """Assemble the report from caller-provided facts plus the process.

    ``ui`` keys: ``binding``, ``qt``, ``qtwebengine``, ``chromium``,
    ``gpu_backend``, ``profile``, ``user_agent``.
    """
    facts = dict(ui or {})
    chromium = _clean(facts.get("chromium"))
    major = chromium_major(chromium)
    # The Chromium base is not the patch level: Qt ships 6.11.0 with security
    # version 146 and 6.11.3 with 155, both on base 140 (core/engine_security.py).
    webengine = _clean(facts.get("qtwebengine"))
    security = engine_security.security_version_for(webengine)
    version = product.APP_VERSION
    report = {
        "Mei version": version,
        "Python": platform.python_version() + f" ({platform.python_implementation()})",
        "Executable": "frozen .exe" if getattr(sys, "frozen", False) else "source checkout",
        "Platform": platform.platform(),
        "PyQt binding": _clean(facts.get("binding")),
        "Qt": _clean(facts.get("qt")),
        "QtWebEngine": _clean(facts.get("qtwebengine")),
        "Chromium": chromium,
        "Chromium major": str(major) if major else UNKNOWN,
        "Chromium security patch": chromium if major and chromium.count(".") >= 3 else UNKNOWN,
        "Chromium security version": str(security) if security else UNKNOWN,
        "GPU backend": _clean(facts.get("gpu_backend")),
        "Hardware acceleration": hardware_acceleration_status(environ),
        "Sandbox": sandbox_status(environ),
        "Active profile": _clean(facts.get("profile")),
        "User-Agent": _clean(facts.get("user_agent")),
    }
    warnings: list[str] = []
    if not major:
        warnings.append(
            "The Chromium version could not be read. Treat this build as unverified "
            "for web compatibility."
        )
    elif major < MIN_SUPPORTED_CHROMIUM:
        warnings.append(
            f"Chromium {major} is below the supported floor ({MIN_SUPPORTED_CHROMIUM}). "
            "Modern sign-in, WebAuthn and many JavaScript APIs will refuse it. "
            "Install PyQt6-WebEngine 6.11 (Chromium 140)."
        )
    if str(report["PyQt binding"]).startswith("PyQt6"):
        if security is None:
            warnings.append(
                f"The security patch level of QtWebEngine {webengine} is unknown. "
                "Add it to core/engine_security.py before treating this build as patched."
            )
        elif not engine_security.meets_floor(security):
            warnings.append(
                f"This engine carries security version {security}, below the required "
                f"floor ({engine_security.MIN_SECURITY_VERSION}). Update the WebEngine pin."
            )
    if str(report["PyQt binding"]).startswith("PyQt5"):
        warnings.append(
            "This is the LEGACY PyQt5 engine path (Qt 5.15 / Chromium 87). It is not "
            "the production engine and must not be shipped in a release."
        )
    if "Disabled" in str(report["Sandbox"]):
        warnings.append("The browser sandbox is disabled; do not browse untrusted sites.")
    report["Warnings"] = warnings
    return report


def format_report(report: dict | None = None) -> str:
    data = dict(report or {})
    if not data:
        return "No engine facts available."
    lines = []
    for key, value in data.items():
        if key == "Warnings":
            continue
        lines.append(f"{key}: {value}")
    warnings = data.get("Warnings") or []
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"• {warn}" for warn in warnings)
    else:
        lines.append("")
        lines.append("Warnings: none")
    return "\n".join(lines)


__all__ = [
    "MIN_SUPPORTED_CHROMIUM",
    "UNKNOWN",
    "chromium_major",
    "collect",
    "format_report",
    "hardware_acceleration_status",
    "sandbox_status",
]

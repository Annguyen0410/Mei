"""Single Qt import surface.

The app runs on PyQt5 or PyQt6: ``qt_compat`` redirects the PyQt5 module names to
PyQt6 when it is installed, and every module used to ``from PyQt5... import ...``
and rely on that rewrite. It works, but it means the binding is decided by an
import side effect and a Qt upgrade touches every file.

New code imports from here instead:

    from litebrowser.qt import QtCore, QtWidgets

``tests/test_qt_facade.py`` keeps the list of modules still importing PyQt5
directly, and only lets it shrink, so the binding swap stays a one-file change.

Importing this module goes through ``litebrowser/__init__``, so the shim is
always active first.
"""
from PyQt5 import (  # noqa: F401
    QtCore,
    QtGui,
    QtNetwork,
    QtPrintSupport,
    QtWidgets,
)

try:  # QtWebEngineCore/QtWebEngineWidgets ship with PyQt*WebEngine
    from PyQt5 import QtWebEngineCore, QtWebEngineWidgets  # noqa: F401
except ImportError:  # pragma: no cover - only when WebEngine is absent
    QtWebEngineCore = None  # type: ignore[assignment]
    QtWebEngineWidgets = None  # type: ignore[assignment]

try:  # WebChannel is optional (panels work without it)
    from PyQt5 import QtWebChannel  # noqa: F401
except ImportError:  # pragma: no cover - optional dependency
    QtWebChannel = None  # type: ignore[assignment]

# QShortcut moved from QtWidgets to QtGui in PyQt6; expose whichever exists so
# callers do not have to care which binding is active.
QShortcut = getattr(QtGui, "QShortcut", None) or getattr(QtWidgets, "QShortcut", None)

__all__ = [
    "QtCore",
    "QtGui",
    "QtNetwork",
    "QtPrintSupport",
    "QtWebChannel",
    "QtWebEngineCore",
    "QtWebEngineWidgets",
    "QtWidgets",
    "QShortcut",
]

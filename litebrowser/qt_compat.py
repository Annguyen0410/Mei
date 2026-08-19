"""PyQt5 -> PyQt6 compatibility shim.

Import this module BEFORE any PyQt5 imports (via litebrowser/__init__.py).
It redirects PyQt5 module names to PyQt6 through sys.modules and
monkey-patches enum / API differences so existing PyQt5-style code
works unchanged.

When PyQt6 is not installed the module is a harmless no-op and the
original PyQt5 packages are used as-is.
"""
import os
import sys
import types

PYQT6 = False

try:
    import PyQt6.QtCore
    import PyQt6.QtGui
    import PyQt6.QtNetwork
    import PyQt6.QtPrintSupport
    import PyQt6.QtWebEngineCore
    import PyQt6.QtWebEngineWidgets
    import PyQt6.QtWidgets
    PYQT6 = True
except ImportError:
    pass

if PYQT6:
    # ------------------------------------------------------------------
    # 1. Redirect all "from PyQt5.X import ..." to PyQt6 equivalents
    # ------------------------------------------------------------------
    # We use plain assignment (not setdefault) so this wins even if the
    # PyInstaller frozen loader pre-populated a bogus PyQt5 entry. This shim
    # module itself is imported from ``litebrowser/__init__.py`` before any
    # `from PyQt5.*` import in the package runs.
    import PyQt6
    try:
        import PyQt6.QtWebChannel
        _qt_webchannel = PyQt6.QtWebChannel
    except ImportError:  # PyQt6-WebChannel not installed – not fatal
        _qt_webchannel = None

    _aliases = [
        ("PyQt5", PyQt6),
        ("PyQt5.QtCore", PyQt6.QtCore),
        ("PyQt5.QtWidgets", PyQt6.QtWidgets),
        ("PyQt5.QtGui", PyQt6.QtGui),
        ("PyQt5.QtNetwork", PyQt6.QtNetwork),
        ("PyQt5.QtPrintSupport", PyQt6.QtPrintSupport),
        ("PyQt5.QtWebEngineCore", PyQt6.QtWebEngineCore),
    ]
    if _qt_webchannel is not None:
        _aliases.append(("PyQt5.QtWebChannel", _qt_webchannel))
    for alias, real in _aliases:
        sys.modules[alias] = real

    # QShortcut moved from QtWidgets -> QtGui in PyQt6; re-export so old imports work
    from PyQt6.QtGui import QShortcut as _QShortcut
    if not hasattr(PyQt6.QtWidgets, "QShortcut"):
        PyQt6.QtWidgets.QShortcut = _QShortcut

    # WebEngine: several classes moved from QtWebEngineWidgets -> QtWebEngineCore
    _wew = types.ModuleType("PyQt5.QtWebEngineWidgets")
    _wew.__package__ = "PyQt5"
    from PyQt6.QtWebEngineCore import (
        QWebEnginePage,
        QWebEngineProfile,
        QWebEngineScript,
        QWebEngineSettings,
        QWebEngineUrlRequestInterceptor,
    )
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    _wew.QWebEngineView = QWebEngineView
    _wew.QWebEngineProfile = QWebEngineProfile
    _wew.QWebEngineSettings = QWebEngineSettings
    _wew.QWebEnginePage = QWebEnginePage
    _wew.QWebEngineUrlRequestInterceptor = QWebEngineUrlRequestInterceptor
    # In PyQt5 layout QWebEngineScript lives in QtWebEngineWidgets, so re-export it
    # on the shim so existing "from PyQt5.QtWebEngineWidgets import QWebEngineScript"
    # keeps working when we are actually running on PyQt6.
    _wew.QWebEngineScript = QWebEngineScript
    sys.modules["PyQt5.QtWebEngineWidgets"] = _wew

    # ------------------------------------------------------------------
    # 2. Monkey-patch old-style enum access onto Qt classes
    # ------------------------------------------------------------------
    from PyQt6.QtCore import Qt

    def _patch(cls, mapping):
        for old, new in mapping.items():
            if not hasattr(cls, old):
                setattr(cls, old, new)

    _patch(Qt, {
        # Orientation
        "Horizontal": Qt.Orientation.Horizontal,
        "Vertical": Qt.Orientation.Vertical,
        # AlignmentFlag
        "AlignCenter": Qt.AlignmentFlag.AlignCenter,
        "AlignLeft": Qt.AlignmentFlag.AlignLeft,
        "AlignRight": Qt.AlignmentFlag.AlignRight,
        "AlignTop": Qt.AlignmentFlag.AlignTop,
        "AlignBottom": Qt.AlignmentFlag.AlignBottom,
        "AlignHCenter": Qt.AlignmentFlag.AlignHCenter,
        "AlignVCenter": Qt.AlignmentFlag.AlignVCenter,
        # MouseButton
        "LeftButton": Qt.MouseButton.LeftButton,
        "RightButton": Qt.MouseButton.RightButton,
        "NoButton": Qt.MouseButton.NoButton,
        "MiddleButton": Qt.MouseButton.MiddleButton,
        # CursorShape
        "PointingHandCursor": Qt.CursorShape.PointingHandCursor,
        "CrossCursor": Qt.CursorShape.CrossCursor,
        "OpenHandCursor": Qt.CursorShape.OpenHandCursor,
        "ArrowCursor": Qt.CursorShape.ArrowCursor,
        # Key
        "Key_Return": Qt.Key.Key_Return,
        "Key_Enter": Qt.Key.Key_Enter,
        "Key_Escape": Qt.Key.Key_Escape,
        # ItemDataRole
        "UserRole": Qt.ItemDataRole.UserRole,
        # ContextMenuPolicy
        "CustomContextMenu": Qt.ContextMenuPolicy.CustomContextMenu,
        # ScrollBarPolicy
        "ScrollBarAlwaysOff": Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        # AspectRatioMode
        "KeepAspectRatio": Qt.AspectRatioMode.KeepAspectRatio,
        # TransformationMode
        "SmoothTransformation": Qt.TransformationMode.SmoothTransformation,
        # GlobalColor
        "white": Qt.GlobalColor.white,
        "black": Qt.GlobalColor.black,
        # PenStyle / PenCapStyle / PenJoinStyle
        "NoPen": Qt.PenStyle.NoPen,
        "SolidLine": Qt.PenStyle.SolidLine,
        "RoundCap": Qt.PenCapStyle.RoundCap,
        "RoundJoin": Qt.PenJoinStyle.RoundJoin,
        # CheckState
        "Checked": Qt.CheckState.Checked,
        "Unchecked": Qt.CheckState.Unchecked,
        # ItemFlag
        "ItemIsUserCheckable": Qt.ItemFlag.ItemIsUserCheckable,
        "NoItemFlags": Qt.ItemFlag(0),
        # WidgetAttribute
        "WA_Hover": Qt.WidgetAttribute.WA_Hover,
    })

    # EasingCurve
    from PyQt6.QtCore import QEasingCurve
    if hasattr(QEasingCurve, "Type"):
        for name in ("Linear", "InQuad", "OutQuad", "InOutQuad", "OutCubic", "InCubic", "InOutCubic"):
            val = getattr(QEasingCurve.Type, name, None)
            if val is not None:
                _patch(QEasingCurve, {name: val})

    # QAbstractAnimation
    from PyQt6.QtCore import QAbstractAnimation
    if hasattr(QAbstractAnimation, "State"):
        for name in ("Stopped", "Paused", "Running"):
            val = getattr(QAbstractAnimation.State, name, None)
            if val is not None:
                _patch(QAbstractAnimation, {name: val})

    # QFrame
    from PyQt6.QtWidgets import QFrame
    if hasattr(QFrame, "Shape"):
        _patch(QFrame, {"NoFrame": QFrame.Shape.NoFrame})

    # TextInteractionFlags
    if hasattr(Qt, "TextInteractionFlag"):
        _patch(Qt, {"TextSelectableByMouse": Qt.TextInteractionFlag.TextSelectableByMouse})

    # TextFormat (Qt.RichText / Qt.PlainText / Qt.AutoText / Qt.MarkdownText)
    if hasattr(Qt, "TextFormat"):
        for _name in ("RichText", "PlainText", "AutoText", "MarkdownText"):
            _val = getattr(Qt.TextFormat, _name, None)
            if _val is not None:
                _patch(Qt, {_name: _val})

    # --- Flatten-every-remaining-enum safety net ---------------------------
    # PyQt6 moved most Qt.* scoped enums into nested enum classes (e.g.
    # Qt.TextFormat.RichText replaces Qt.RichText). Any value we forget to
    # patch above raises AttributeError at first use and, in a windowed EXE,
    # the whole app silently exits. To make that failure mode *impossible*
    # we sweep every nested enum on Qt and re-export its members at the top
    # level when the name isn't already taken. This is idempotent and only
    # adds attributes; it never overrides real ones.
    try:
        import enum as _enum
        for _attr_name in dir(Qt):
            _attr = getattr(Qt, _attr_name, None)
            if not isinstance(_attr, type):
                continue
            if not issubclass(_attr, _enum.Enum):
                continue
            for _member in _attr:
                if not hasattr(Qt, _member.name):
                    try:
                        setattr(Qt, _member.name, _member)
                    except (AttributeError, TypeError):
                        pass
    except Exception:
        pass

    # ApplicationAttribute – may not exist in all Qt6 builds
    if hasattr(Qt, "ApplicationAttribute"):
        for name in ("AA_UseSoftwareOpenGL", "AA_ShareOpenGLContexts",
                      "AA_UseDesktopOpenGL", "AA_UseOpenGLES"):
            val = getattr(Qt.ApplicationAttribute, name, None)
            if val is not None and not hasattr(Qt, name):
                setattr(Qt, name, val)

    # --- QStyle ---
    from PyQt6.QtWidgets import QStyle
    if hasattr(QStyle, "StandardPixmap"):
        for name in ("SP_ArrowBack", "SP_ArrowForward", "SP_BrowserReload",
                      "SP_DirHomeIcon", "SP_DialogCloseButton",
                      "SP_FileDialogContentsView", "SP_MessageBoxInformation",
                      "SP_MessageBoxWarning", "SP_ComputerIcon"):
            val = getattr(QStyle.StandardPixmap, name, None)
            if val is not None:
                _patch(QStyle, {name: val})

    # --- QLineEdit ---
    from PyQt6.QtWidgets import QLineEdit
    _patch(QLineEdit, {
        "Password": QLineEdit.EchoMode.Password,
        "Normal": QLineEdit.EchoMode.Normal,
    })
    if hasattr(QLineEdit, "ActionPosition"):
        _patch(QLineEdit, {"LeadingPosition": QLineEdit.ActionPosition.LeadingPosition,
                           "TrailingPosition": QLineEdit.ActionPosition.TrailingPosition})

    # --- QToolButton ---
    from PyQt6.QtWidgets import QToolButton
    if hasattr(QToolButton, "ToolButtonPopupMode"):
        _patch(QToolButton, {"InstantPopup": QToolButton.ToolButtonPopupMode.InstantPopup})

    # --- QSizePolicy ---
    from PyQt6.QtWidgets import QSizePolicy
    _patch(QSizePolicy, {
        "Expanding": QSizePolicy.Policy.Expanding,
        "Preferred": QSizePolicy.Policy.Preferred,
        "Fixed": QSizePolicy.Policy.Fixed,
        "Minimum": QSizePolicy.Policy.Minimum,
        "Maximum": QSizePolicy.Policy.Maximum,
        "MinimumExpanding": QSizePolicy.Policy.MinimumExpanding,
    })

    # --- QMessageBox ---
    from PyQt6.QtWidgets import QMessageBox
    _patch(QMessageBox, {
        "Yes": QMessageBox.StandardButton.Yes,
        "No": QMessageBox.StandardButton.No,
        "NoToAll": QMessageBox.StandardButton.NoToAll,
    })
    if hasattr(QMessageBox, "Icon"):
        _patch(QMessageBox, {
            "Warning": QMessageBox.Icon.Warning,
            "Information": QMessageBox.Icon.Information,
        })

    # --- QDialog ---
    from PyQt6.QtWidgets import QDialog
    _patch(QDialog, {
        "Accepted": QDialog.DialogCode.Accepted,
        "Rejected": QDialog.DialogCode.Rejected,
    })

    # --- QFont ---
    from PyQt6.QtGui import QFont
    _patch(QFont, {
        "Bold": QFont.Weight.Bold,
        "DemiBold": QFont.Weight.DemiBold,
    })
    if hasattr(QFont, "StyleStrategy"):
        _patch(QFont, {"PreferAntialias": QFont.StyleStrategy.PreferAntialias})

    # --- QPainter ---
    from PyQt6.QtGui import QPainter
    if hasattr(QPainter, "RenderHint"):
        _patch(QPainter, {"Antialiasing": QPainter.RenderHint.Antialiasing})

    # --- QCalendarWidget ---
    from PyQt6.QtWidgets import QCalendarWidget
    if hasattr(QCalendarWidget, "VerticalHeaderFormat"):
        _patch(QCalendarWidget, {
            "NoVerticalHeader": QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader,
        })

    # --- QGraphicsView ---
    from PyQt6.QtWidgets import QGraphicsView
    _patch(QGraphicsView, {
        "NoDrag": QGraphicsView.DragMode.NoDrag,
        "ScrollHandDrag": QGraphicsView.DragMode.ScrollHandDrag,
    })
    if hasattr(QGraphicsView, "ViewportAnchor"):
        _patch(QGraphicsView, {"AnchorUnderMouse": QGraphicsView.ViewportAnchor.AnchorUnderMouse})
    if hasattr(QGraphicsView, "ViewportUpdateMode"):
        _patch(QGraphicsView, {"FullViewportUpdate": QGraphicsView.ViewportUpdateMode.FullViewportUpdate})

    # --- QGraphicsItem / QGraphicsRectItem ---
    from PyQt6.QtWidgets import QGraphicsItem, QGraphicsRectItem
    if hasattr(QGraphicsItem, "GraphicsItemFlag"):
        for name in ("ItemIsMovable", "ItemIsSelectable", "ItemSendsGeometryChanges"):
            val = getattr(QGraphicsItem.GraphicsItemFlag, name, None)
            if val is not None:
                _patch(QGraphicsItem, {name: val})
                _patch(QGraphicsRectItem, {name: val})

    # --- QNetworkProxy ---
    from PyQt6.QtNetwork import QNetworkProxy
    if hasattr(QNetworkProxy, "ProxyType"):
        for name in ("NoProxy", "DefaultProxy", "Socks5Proxy", "HttpProxy",
                      "HttpCachingProxy", "FtpCachingProxy"):
            val = getattr(QNetworkProxy.ProxyType, name, None)
            if val is not None:
                _patch(QNetworkProxy, {name: val})

    # --- QPrinter ---
    from PyQt6.QtPrintSupport import QPrinter
    if hasattr(QPrinter, "PrinterMode"):
        for name in ("HighResolution", "ScreenResolution"):
            val = getattr(QPrinter.PrinterMode, name, None)
            if val is not None:
                _patch(QPrinter, {name: val})

    # ------------------------------------------------------------------
    # 3. WebEngine API compat
    # ------------------------------------------------------------------

    # QWebEngineSettings – attribute enums
    if hasattr(QWebEngineSettings, "WebAttribute"):
        for name in dir(QWebEngineSettings.WebAttribute):
            if name.startswith("_"):
                continue
            _patch(QWebEngineSettings, {name: getattr(QWebEngineSettings.WebAttribute, name)})

    # QWebEngineProfile – cookie / cache enums
    if hasattr(QWebEngineProfile, "PersistentCookiesPolicy"):
        for name in ("NoPersistentCookies", "ForcePersistentCookies", "AllowPersistentCookies"):
            val = getattr(QWebEngineProfile.PersistentCookiesPolicy, name, None)
            if val is not None:
                _patch(QWebEngineProfile, {name: val})
    if hasattr(QWebEngineProfile, "HttpCacheType"):
        for name in ("MemoryHttpCache", "DiskHttpCache", "NoCache"):
            val = getattr(QWebEngineProfile.HttpCacheType, name, None)
            if val is not None:
                _patch(QWebEngineProfile, {name: val})

    # QWebEngineProfile.defaultProfile() – removed in Qt6
    if not hasattr(QWebEngineProfile, "defaultProfile"):
        _compat_dp = [None]
        def _default_profile():
            if _compat_dp[0] is None:
                _compat_dp[0] = QWebEngineProfile()
            return _compat_dp[0]
        QWebEngineProfile.defaultProfile = _default_profile

    # QWebEnginePage – permission enums (deprecated but present in Qt 6.8)
    if hasattr(QWebEnginePage, "PermissionPolicy"):
        for name in ("PermissionGrantedByUser", "PermissionDeniedByUser", "PermissionUnknown"):
            val = getattr(QWebEnginePage.PermissionPolicy, name, None)
            if val is not None:
                _patch(QWebEnginePage, {name: val})
    if hasattr(QWebEnginePage, "Feature"):
        for name in ("Geolocation", "MediaAudioCapture", "MediaVideoCapture",
                      "MediaAudioVideoCapture", "DesktopAudioVideoCapture",
                      "DesktopVideoCapture", "Notifications"):
            val = getattr(QWebEnginePage.Feature, name, None)
            if val is not None:
                _patch(QWebEnginePage, {name: val})

    # QWebEngineDownloadRequest (was QWebEngineDownloadItem in Qt5)
    try:
        from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest
        if hasattr(QWebEngineDownloadRequest, "DownloadState"):
            for name in ("DownloadCompleted", "DownloadCancelled", "DownloadInterrupted",
                          "DownloadRequested", "DownloadInProgress"):
                val = getattr(QWebEngineDownloadRequest.DownloadState, name, None)
                if val is not None:
                    _patch(QWebEngineDownloadRequest, {name: val})
        if not hasattr(QWebEngineDownloadRequest, "setPath"):
            def _set_download_path(self, path):
                self.setDownloadDirectory(os.path.dirname(os.path.abspath(path)))
                self.setDownloadFileName(os.path.basename(path))
            QWebEngineDownloadRequest.setPath = _set_download_path
    except ImportError:
        pass

    # ------------------------------------------------------------------
    # 4. exec_() compat – PyQt6 only has exec(); add exec_() alias
    # ------------------------------------------------------------------
    # Do NOT assign QDialog.exec_ = QDialog.exec — SIP treats exec specially
    # and dlg.exec_() raises: TypeError: exec(self): first argument of unbound
    # method must have type 'QDialog'. Wrappers call .exec() on the instance.
    from PyQt6.QtWidgets import QApplication
    if not hasattr(QApplication, "exec_"):
        def _qapp_exec_(self):
            return self.exec()

        QApplication.exec_ = _qapp_exec_

    if not hasattr(QDialog, "exec_"):
        def _qdialog_exec_(self):
            return self.exec()

        QDialog.exec_ = _qdialog_exec_

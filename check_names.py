"""Static NameError checker for every module: bare names used but never
imported/assigned/builtin would raise NameError at runtime."""
import ast
import builtins
import os
import sys

B = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__", "__spec__", "__builtins__", "__debug__"}
MODULE_HINTS = {
    "prefs", "app_paths", "app_version", "theme", "dialogs", "components", "vault_ui",
    "win_titlebar", "tab_manager", "adblock", "browser_page", "new_tab_page",
    "extension_patterns", "extension_bridge", "workspace_manager", "life_service",
    "personal_service", "history_service", "password_manager", "focus_service",
    "download_mgr", "tab_sets", "sync_service", "ai_service", "retriever",
    "security", "google_auth", "open_request", "agent_actions", "brief_service",
    "android_bridge_service", "update_service", "personal_window", "ai_window",
    "flashcard_service", "page_monitor", "routines_service", "rss_service",
    "export_service", "ics_service", "note_templates", "profile_lock",
    "storage_utils", "time_utils", "app_models", "commands", "tray", "onboarding",
    "focus_heatmap", "QApplication", "QTimer", "QUrl", "Qt", "QEvent", "QColor",
    "QPainter", "QPen", "QPixmap", "QFont", "QIcon", "QKeySequence", "QDesktopServices",
    "QMessageBox", "QDialog", "QMenu", "QLabel", "QLineEdit", "QPushButton",
    "QVBoxLayout", "QHBoxLayout", "QGridLayout", "QSplitter", "QStackedWidget",
    "QListWidget", "QListWidgetItem", "QTreeWidget", "QTreeWidgetItem", "QComboBox",
    "QCheckBox", "QSpinBox", "QPlainTextEdit", "QTextEdit", "QToolButton",
    "QFrame", "QWidget", "QMainWindow", "QScrollArea", "QCalendarWidget",
    "QGraphicsView", "QGraphicsScene", "QGraphicsRectItem", "QGraphicsPathItem",
    "QGraphicsTextItem", "QGraphicsOpacityEffect", "QPropertyAnimation",
    "QVariantAnimation", "QEasingCurve", "QAbstractAnimation", "QCompleter",
    "QStringListModel", "QSyntaxHighlighter", "QTextCharFormat", "QTextCursor",
    "QDate", "QDateTime", "QFileSystemWatcher", "QPointF", "QRect", "QSize",
    "QSizePolicy", "QStyle", "QShortcut", "QFileDialog", "QInputDialog",
    "QButtonGroup", "QNetworkProxy", "QPrinter", "QPrintDialog", "QProgressBar",
    "QSystemTrayIcon", "QWebEngineView", "QWebEnginePage", "QWebEngineProfile",
    "QWebEngineSettings", "QWebEngineScript", "pyqtSignal", "QObject",
    "QThread", "QProcess", "QSettings", "QStandardPaths", "QGuiApplication",
    "QSignalBlocker", "QSignalSpy", "QImage", "QBrush", "QPainterPath",
    "QNetworkAccessManager", "QNetworkRequest", "QNetworkReply",
    "QWebChannel", "QWebEngineDownloadItem", "QWebEngineDownloadRequest",
    "QDialogButtonBox", "QTabWidget", "QTableView", "QTreeView", "QHeaderView",
    "QGroupBox", "QRadioButton", "QSlider", "QDial", "QTimeEdit", "QDateEdit",
    "QDateTimeEdit", "QFontDialog", "QColorDialog", "QFontMetrics", "QCursor",
    "QClipboard", "QMimeData", "QDrag", "QDropEvent", "QDragEnterEvent",
    "QDragMoveEvent", "QPaintEvent", "QMouseEvent", "QKeyEvent", "QWheelEvent",
    "QResizeEvent", "QCloseEvent", "QShowEvent", "QHideEvent", "QTimerEvent",
    "QEvent", "QEventLoop", "QCoreApplication", "QTranslator", "QLocale",
    "QCollator", "QVersionNumber", "QVersion", "os", "sys", "re", "json",
    "time", "uuid", "html", "zipfile", "socket", "struct", "hashlib", "secrets",
    "shutil", "tempfile", "subprocess", "threading", "traceback", "typing",
    "dataclasses", "asdict", "field", "contextlib", "contextmanager",
    "Iterator", "Any", "Optional", "Union", "List", "Dict", "Tuple", "Callable",
    "Iterable", "Sequence", "Mapping", "MutableMapping", "Counter", "deque",
    "defaultdict", "OrderedDict", "namedtuple", "dataclass", "Enum", "IntEnum",
    "Flag", "IntFlag", "Path", "PurePath", "datetime", "timedelta", "timezone",
    "date", "time_module", "urllib", "urlopen", "Request", "HTTPError",
    "URLError", "urlencode", "urlparse", "quote", "quote_plus", "unquote",
    "unquote_plus", "parse_qs", "urljoin", "base64", "binascii", "zlib",
    "gzip", "bz2", "lzma", "tarfile", "csv", "configparser", "argparse",
    "unittest", "pytest", "logging", "warnings", "atexit", "signal", "stat",
    "errno", "glob", "fnmatch", "linecache", "locale", "gettext", "textwrap",
    "difflib", "pprint", "reprlib", "copy", "copyreg", "weakref", "types",
    "inspect", "importlib", "pkgutil", "module", "builtins", "gc", "queue",
    "select", "selectors", "mmap", "ctypes", "platform", "errno", "grp",
    "pwd", "spwd", "crypt", "termios", "tty", "pty", "fcntl", "msvcrt",
    "winreg", "winsound", "winsound", "site", "code", "codeop", "ast",
    "dis", "token", "tokenize", "keyword", "symbol", "codeop", "compileall",
    "getopt", "shlex", "fileinput", "filecmp", "difflib", "plistlib",
    "smtpd", "smtp", "poplib", "imaplib", "nntplib", "smtplib", "telnetlib",
    "ssl", "select", "asyncio", "socketserver", "http", "ftplib", "xmlrpc",
    "ipaddress", "mailcap", "mimetypes", "quopri", "uu", "email", "mailbox",
    "mimetypes", "cgi", "cgitb", "wsgiref", "urllib2", "urlparse", "BaseHTTPServer",
    "SimpleHTTPServer", "CGIHTTPServer", "SocketServer", "DocXMLRPCServer",
    "SimpleXMLRPCServer", "xmlrpclib", "cookielib", "Cookie", "commands",
    "exceptions", "dummy_thread", "dummy_threading", "thread", "string",
    "StringIO", "cStringIO", "md5", "sha", "sets", "whichdb", "anydbm",
    "dbhash", "dumbdbm", "gdbm", "dbm", "bsddb", "whichdb", "UserDict",
    "UserList", "UserString", "UserList", "UserDict", "UserString",
    "new", "types", "operator", "collections", "itertools", "functools",
    "random", "whrandom", "bisect", "heapq", "array", "deque", "defaultdict",
    "namedtuple", "OrderedDict", "Counter", "ChainMap", "abc", "atexit",
    "trace", "cgitb", "doctest", "unittest", "test", "2to3", "lib2to3",
    "pickle", "cPickle", "shelve", "marshal", "dbm", "gzip", "bz2", "zipfile",
    "tarfile", "zipimport", "zlib", "sysconfig", "distutils", "setuptools",
    "pkg_resources", "pip", "wheel", "pyproject", "toml", "tomllib",
    "csv", "posixpath", "ntpath", "genericpath", "pathlib", "fileinput",
    "stat", "filecmp", "tempfile", "fnmatch", "glob", "os", "io", "abc",
    "aifc", "audioop", "chunk", "colorsys", "imageop", "imghdr", "mailcap",
    "mmap", "nis", "ossaudiodev", "pipes", "sndhdr", "sunau", "telnetlib",
    "uu", "wave", "xdrlib", "ossaudiodev", "spwd", "crypt", "nis",
    "xml", "xml.etree", "ElementTree", "Element", "SubElement", "tostring",
    "fromstring", "parse", "iterparse", "XMLParser", "XMLTreeBuilder",
    "XMLParseError", "ParseError", "ET", "etree",
}


def check(path):
    src = open(path, encoding="utf-8-sig").read()
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [f"SYNTAX {exc}"]
    imported, assigned, used = set(), set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                imported.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                imported.add(a.asname or a.name)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assigned.add(n.name)
        elif isinstance(n, ast.arg):
            assigned.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            assigned.add(n.name)
        elif isinstance(n, ast.Name):
            used.add(n.id)
        elif isinstance(n, (ast.For, ast.comprehension)):
            target = n.target
            for x in ast.walk(target):
                if isinstance(x, ast.Name):
                    assigned.add(x.id)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                for x in ast.walk(t):
                    if isinstance(x, ast.Name):
                        assigned.add(x.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            assigned.add(n.target.id)
        elif isinstance(n, (ast.withitem,)):
            if n.optional_vars is not None:
                for x in ast.walk(n.optional_vars):
                    if isinstance(x, ast.Name):
                        assigned.add(x.id)
    known = imported | assigned | B
    suspects = sorted(
        x for x in used - known
        if x in MODULE_HINTS or (x[0].isupper() and len(x) > 3 and not x.startswith("_"))
    )
    return suspects


total = 0
for root, _dirs, files in os.walk("litebrowser"):
    for name in sorted(files):
        if name.endswith(".py"):
            path = os.path.join(root, name)
            suspects = check(path)
            if suspects:
                total += len(suspects)
                print(f"{path}: {suspects}")
print("TOTAL suspicious unresolved names:", total)

"""AST-verified extraction: menu builders -> MenusMixin.

Cut list (by fresh AST spans, not stale line numbers):
- show_tab_context_menu
- show_extension_import_center
- _import_extension_batches_as_workspaces
- _build_options_menu

Safety: both output files must ast.parse before anything is written.
"""
import ast
import io

PATH = "litebrowser/ui/main_window/window.py"
src = io.open(PATH, encoding="utf-8-sig").read()
tree = ast.parse(src)

cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SearchWindow")
wanted = {"show_tab_context_menu", "show_extension_import_center", "_import_extension_batches_as_workspaces", "_build_options_menu"}
spans = sorted(
    [(n.lineno - 1, n.end_lineno, n.name) for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
)
print("cutting:", [(n, s + 1, e) for s, e, n in spans])

# Extract method text (keep original indentation; class-level context is fine
# inside a Mixin class as long as 'self' usage stays).
lines = src.splitlines(keepends=True)
chunks = []
cut_spans = []
for s, e, name in spans:
    # include immediately-preceding comment lines attached to the method
    start = s
    j = s - 1
    while j >= 0 and lines[j].strip().startswith("#") and not lines[j].strip().startswith("# ---"):
        start = j
        j -= 1
    chunks.append("".join(lines[start:e]))
    cut_spans.append((start, e))

# Build mixin text
header = (
    "# Mei - window mixins: context menus and the extension import center.\n"
    "#\n"
    "# Extracted from window.py (AST-verified cut) so menu logic is reviewable\n"
    "# separately from browser state. Methods only touch SearchWindow-owned\n"
    "# attributes (tab_list, base_dir, tab_manager, ...).\n"
    "\n"
    "from PyQt5.QtCore import Qt, QUrl\n"
    "from PyQt5.QtWidgets import (\n"
    "    QDialog,\n"
    "    QFileDialog,\n"
    "    QHBoxLayout,\n"
    "    QInputDialog,\n"
    "    QLabel,\n"
    "    QListWidget,\n"
    "    QListWidgetItem,\n"
    "    QMenu,\n"
    "    QMessageBox,\n"
    "    QPushButton,\n"
    "    QTreeWidget,\n"
    "    QTreeWidgetItem,\n"
    "    QVBoxLayout,\n"
    ")\n"
    "\n"
    "from litebrowser.core import prefs\n"
    "from litebrowser.services import extension_bridge, workspace_manager\n"
    "\n"
    "\n"
    "class MenusMixin:\n"
    '    """Tab/bookmark context menus, options menu, extension import center."""\n'
    "\n"
)
mixin_text = header + "\n".join(chunk.rstrip() + "\n" for chunk in chunks)

new_window_text = "".join(
    line for i, line in enumerate(lines) if not any(s <= i < e for s, e in cut_spans)
)

# Verify BEFORE writing
ast.parse(mixin_text)
ast.parse(new_window_text)
print("both parse OK")

io.open("litebrowser/ui/main_window/window_menus.py", "w", encoding="utf-8").write(mixin_text)
io.open(PATH, "w", encoding="utf-8").write(new_window_text)
print("window.py now", new_window_text.count("\n"), "lines")

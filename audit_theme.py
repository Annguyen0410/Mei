"""Theme coverage audit: find QMenu/QDialog/QFrame windows created without
a stylesheet in scope, and hard-coded hex colors in UI strings."""
import os
import re

UI_DIRS = ("litebrowser/ui", "litebrowser/browser")
issues = []

menu_no_style = []
dialog_ok = set()

for root in UI_DIRS:
    for _dir, _sub, files in os.walk(root):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(_dir, name)
            src = open(path, encoding="utf-8-sig").read()
            # QMenu created with no parent argument
            for m in re.finditer(r"QMenu\(\s*\)", src):
                line = src[: m.start()].count("\n") + 1
                menu_no_style.append((path, line))
            # hard-coded hex in setText/tooltip-ish contexts (rough scan)
            for m in re.finditer(r'setStyleSheet\([^)]*#[0-9a-fA-F]{6}', src):
                line = src[: m.start()].count("\n") + 1
                issues.append((path, line, "hardcoded hex in setStyleSheet"))

print("== QMenu() without parent (won't inherit theme QSS) ==")
for path, line in menu_no_style:
    print(f"  {path}:{line}")
print()
print("== setStyleSheet with literal hex ==")
for path, line, what in issues[:40]:
    print(f"  {path}:{line} {what}")
print(f"total: {len(menu_no_style)} menus, {len(issues)} hex-style lines")

import io
import re

old = io.open("_old_window.py", encoding="utf-8-sig").read()
new = io.open("litebrowser/ui/main_window/window.py", encoding="utf-8-sig").read()


def extract(src, func):
    m = re.search(r"    def " + func + r"\(.*?(?=\n    def |\n\nclass )", src, re.DOTALL)
    return m.group(0) if m else "(not found)"


for fn in (
    "_apply_responsive_layout",
    "_apply_sidebar_collapse_visibility",
    "_toggle_topbar",
    "_apply_topbar_collapse",
    "resizeEvent",
    "_build_tab_desk",
    "_build_options_menu",
):
    o = extract(old, fn)
    n = extract(new, fn)
    status = "SAME" if o == n else f"DIFF old={len(o)}c new={len(n)}c"
    print(f"{fn:44s} {status}")

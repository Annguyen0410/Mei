import io
import re

SUSPECT = "\u00c2\u00e2\u00c3\u00e2\u2013\u00e2\u2020\u00e2\u2030\u00e2\u2122\u00e2\u25ba"
for path in [
    "litebrowser/main.py",
    "litebrowser/browser/adblock.py",
    "litebrowser/browser/browser_page.py",
    "litebrowser/browser/new_tab_page.py",
    "litebrowser/browser/tab_manager.py",
    "litebrowser/ui/shell/pages.py",
    "litebrowser/ui/components.py",
    "litebrowser/ui/dialogs/navigation.py",
    "litebrowser/ui/dialogs/sessions.py",
    "litebrowser/ui/dialogs/profiles_privacy.py",
    "litebrowser/ui/dialogs/vpn_hub.py",
    "litebrowser/ui/dialogs/help_hub.py",
    "litebrowser/ui/dialogs/common.py",
    "litebrowser/ui/vault_ui.py",
    "litebrowser/ui/win_titlebar.py",
]:
    try:
        src = io.open(path, encoding="utf-8-sig", errors="replace").read()
    except OSError:
        continue
    hits = []
    for m in re.finditer(r'"([^"\n]*)"', src):
        s = m.group(1)
        if any(ch in s for ch in "\u00c2\u00e2\u00c3"):
            line = src[: m.start()].count("\n") + 1
            hits.append((line, s[:70]))
    for line, s in hits[:6]:
        print(path, line, repr(s))
    if hits:
        print(path, "hits:", len(hits))
print("scan done")

"""Export center: bundle SafeVault notes for sharing or backup.

Two free formats from one dialog:
- Markdown bundle (zip): notes/ tree with categories as folders + an index.md
- Static HTML mini-site: index + one page per note, styled with the active
  theme palette; works offline, opens in any browser.
"""
from __future__ import annotations

import html
import os
import re
import time
import zipfile

from litebrowser.core import prefs
from litebrowser.services import personal_service


def _safe_name(title: str) -> str:
    raw = re.sub(r'[\\/:*?"<>|]', "-", (title or "").strip())[:60]
    return raw or "note"


def _render_html_page(title: str, content: str, theme_tokens: dict) -> str:
    """Minimal markdown-ish → HTML (headings, bold, lists, wiki-link hints,
    code, paragraphs). Enough for notes; never claims to be full CommonMark."""
    p = theme_tokens

    def inline(text: str) -> str:
        text = html.escape(text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
        text = re.sub(r"\[\[([^\]]+)\]\]", r'<span class="wl">\1</span>', text)
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
        return text

    body_lines = []
    in_list = False
    in_code = False
    code_buf = []
    for line in content.splitlines():
        if line.strip().startswith("```"):
            if in_code:
                body_lines.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")
                code_buf = []
            in_code = not in_code
            continue
        if in_code:
            code_buf.append(line)
            continue
        if re.match(r"^\s*[-*] ", line):
            if not in_list:
                body_lines.append("<ul>")
                in_list = True
            body_lines.append("<li>" + inline(re.sub(r"^\s*[-*] ", "", line)) + "</li>")
            continue
        if in_list:
            body_lines.append("</ul>")
            in_list = False
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            body_lines.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            continue
        if line.strip() == "---":
            body_lines.append("<hr>")
            continue
        if line.strip():
            body_lines.append(f"<p>{inline(line)}</p>")
    if in_list:
        body_lines.append("</ul>")
    if in_code and code_buf:
        body_lines.append("<pre><code>" + html.escape("\n".join(code_buf)) + "</code></pre>")

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{html.escape(title)}</title><style>
body {{ background:{p['MAIN_BG']}; color:{p['TEXT']}; font-family:'Segoe UI',sans-serif;
       max-width:820px; margin:0 auto; padding:34px 22px; line-height:1.65; }}
h1,h2,h3 {{ color:{p['ACCENT_HOVER']}; font-family:Georgia,serif; }}
a {{ color:{p['ACCENT']}; }}
.wl {{ color:{p['ACCENT_HOVER']}; border-bottom:1px dotted {p['ACCENT']}; }}
pre {{ background:{p['MAIN_BG_ALT']}; padding:12px; border-radius:8px; overflow:auto; }}
code {{ background:{p['MAIN_BG_ALT']}; padding:1px 5px; border-radius:4px; }}
hr {{ border:none; border-top:1px solid {p['BORDER_SOFT']}; margin:18px 0; }}
footer {{ color:{p['TEXT_MUTED']}; font-size:12px; margin-top:34px; }}
</style></head><body>
{chr(10).join(body_lines)}
<footer>Exported from Mei · {html.escape(time.strftime('%Y-%m-%d %H:%M'))}</footer>
</body></html>"""


def export_notes_html(base_dir: str, out_path: str) -> int:
    """Static mini-site: index.html + note pages under notes/. Returns count."""
    mode = prefs.get_shell_theme(base_dir)
    from litebrowser.ui import theme

    tokens = theme._palette(mode, prefs.get_accent(base_dir))
    notes = personal_service.list_notes(base_dir)
    if not notes:
        return 0
    root = os.path.join(os.path.dirname(out_path), "mei_site")
    os.makedirs(os.path.join(root, "notes"), exist_ok=True)
    pages = []
    for note in notes:
        slug = _safe_name(note["title"]) + "-" + note["id"][-6:] + ".html"
        body = _render_html_page(note["title"], note["content"], tokens)
        with open(os.path.join(root, "notes", slug), "w", encoding="utf-8") as fh:
            fh.write(body)
        pages.append((note["title"], note.get("category", "General"), "notes/" + slug))
    # Build the whole index body first so the list lands INSIDE the document
    # (appending after _render_html_page put it past </html>).
    index_body = f"# Mei Notes\n\n{len(pages)} notes\n\n## All notes\n\n" + "\n".join(
        f"- [{title}]({rel}) · {cat}" for title, cat, rel in pages
    )
    with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(_render_html_page("Mei Notes", index_body, tokens))
    # zip it
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                full = os.path.join(dirpath, name)
                zf.write(full, os.path.relpath(full, root))
    return len(pages)


def export_notes_md_zip(base_dir: str, out_path: str) -> int:
    """Markdown bundle preserving categories as folders."""
    notes = personal_service.list_notes(base_dir)
    used = set()
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        index = ["# Mei notes index", ""]
        for note in notes:
            rel = os.path.join(note.get("category", "General").replace("/", "-"), _safe_name(note["title"]) + ".md")
            rel = rel.replace("\\", "/")
            if rel in used:
                rel = rel[:-3] + f"-{note['id'][-4:]}.md"
            used.add(rel)
            zf.writestr(rel, note["content"])
            index.append(f"- [{note['title']}]({rel}) · {note.get('category', 'General')}")
        zf.writestr("index.md", "\n".join(index) + "\n")
    return len(notes)

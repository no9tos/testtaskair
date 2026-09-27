"""Render docs/SOLUTION.md + appendices (full prompt, full filter list) to one HTML file.

Uploading it to Google Drive as text/html converts it into a native Google Doc
(headings, lists, tables and bold become real Docs formatting).
Run:  pip install markdown && python docs/build_gdoc_html.py [filter-sheet-url]
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "WinWin_AI_Assistant.html"
MD = ["tables", "fenced_code", "sane_lists"]


def md(text: str, shift: int = 0) -> str:
    out = markdown.markdown(text, extensions=MD)
    for level in range(6, 0, -1):  # demote headings of embedded documents
        new = min(level + shift, 6)
        out = out.replace(f"<h{level}>", f"<h{new}>").replace(f"</h{level}>", f"</h{new}>")
    # Docs import keeps <pre>; make code blocks small monospace
    return out.replace("<pre>", '<pre style="font-family:Consolas,monospace;font-size:8pt">')


def filter_tables() -> str:
    catalog = json.loads((ROOT / "filters" / "catalog.json").read_text())
    by_cat: dict[str, list[dict]] = {}
    for f in catalog["filters"]:
        by_cat.setdefault(f["category"], []).append(f)
    parts = [f"<h1>Appendix B: full filter list ({catalog['count']} filters)</h1>",
             "<p>Also in <code>filters/catalog.csv</code> with synonyms and conflict metadata. "
             "Range filters show their unit and bounds.</p>"]
    for cat, items in by_cat.items():
        parts.append(f"<h3>{html.escape(cat)} ({len(items)})</h3>")
        rows = ['<table border="1" style="border-collapse:collapse;font-size:8pt">'
                "<tr><th>id</th><th>label</th><th>type</th></tr>"]
        for f in items:
            t = f["type"]
            if t == "range":
                t = f"range {f['min']}–{f['max']} {f['unit']}"
            elif t == "enum":
                t = "enum: " + ", ".join(f["options"][:6]) + ("…" if len(f["options"]) > 6 else "")
            rows.append(f"<tr><td>{html.escape(f['id'])}</td><td>{html.escape(f['label'])}</td>"
                        f"<td>{html.escape(t)}</td></tr>")
        rows.append("</table>")
        parts.append("".join(rows))
    return "\n".join(parts)


def main() -> None:
    import sys
    sheet_url = sys.argv[1] if len(sys.argv) > 1 else None
    appendix_b = filter_tables() if not sheet_url else (
        "<h1>Appendix B: full filter list (1,021 filters)</h1>"
        f'<p>The complete list, one filter per row with its type, unit and bounds, is in the '
        f'<a href="{sheet_url}">filter catalog spreadsheet</a>. The version with synonyms and conflict '
        "metadata is <code>filters/catalog.csv</code> in the repository.</p>")
    body = [
        md((ROOT / "docs" / "SOLUTION.md").read_text()),
        '<p style="page-break-before:always"></p><h1>Appendix A: full system prompt</h1>',
        md((ROOT / "assistant" / "system_prompt.md").read_text(), shift=1),
        '<p style="page-break-before:always"></p>',
        appendix_b,
    ]
    OUT.write_text('<!doctype html><html><head><meta charset="utf-8"><title>WinWin AI Assistant</title></head>'
                   '<body style="font-family:Arial;font-size:10.5pt">' + "\n".join(body) + "</body></html>")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()

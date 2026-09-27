"""Render docs/SOLUTION.md (+ appendices: full prompt, full filter list) to docs/WinWin_AI_Assistant.docx.

The .docx is meant for upload to Google Drive -> "Open with Google Docs".
Run:  pip install python-docx && python docs/build_docx.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "WinWin_AI_Assistant.docx"
INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)")


def add_inline(par, text: str) -> None:
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            par.add_run(part[2:-2].replace("`", "")).bold = True
        elif part.startswith("`") and part.endswith("`"):
            run = par.add_run(part[1:-1])
            run.font.name = "Consolas"
            run.font.color.rgb = RGBColor(0xB0, 0x30, 0x60)
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            par.add_run(part[1:-1]).italic = True
        else:
            par.add_run(part)


def add_code(doc, lines: list[str]) -> None:
    par = doc.add_paragraph()
    par.paragraph_format.space_after = Pt(6)
    run = par.add_run("\n".join(lines))
    run.font.name = "Consolas"
    run.font.size = Pt(8)


def add_table(doc, rows: list[list[str]]) -> None:
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Light Grid Accent 1"
    for r, cells in enumerate(rows):
        for c, text in enumerate(cells):
            cell = table.cell(r, c)
            cell.text = ""
            add_inline(cell.paragraphs[0], text.strip())
            for run in cell.paragraphs[0].runs:
                run.font.size = Pt(8.5)
                if r == 0:
                    run.bold = True
    doc.add_paragraph()


def render_markdown(doc, md: str, heading_offset: int = 0) -> None:
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            add_code(doc, block)
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.match(r"^\|[\s:\-|]+\|$", lines[i]):
                    rows.append(lines[i].strip("|").split("|"))
                i += 1
            add_table(doc, rows)
            continue
        elif m := re.match(r"^(#{1,4})\s+(.*)", line):
            level = min(len(m.group(1)) + heading_offset, 4)
            if level == 1:
                h = doc.add_heading(m.group(2), 0)
                h.alignment = WD_ALIGN_PARAGRAPH.LEFT
            else:
                doc.add_heading(m.group(2), level - 1)
        elif m := re.match(r"^(\s*)[*-]\s+(.*)", line):
            text = m.group(2)
            while i + 1 < len(lines) and re.match(r"^\s{2,}\S", lines[i + 1]) and not re.match(r"^\s*[*-]\s", lines[i + 1]):
                i += 1
                text += " " + lines[i].strip()
            add_inline(doc.add_paragraph(style="List Bullet 2" if m.group(1) else "List Bullet"), text)
        elif m := re.match(r"^(\d+)\.\s+(.*)", line):
            # manual numbers: Word's "List Number" style would continue numbering across sections
            text = f"{m.group(1)}. {m.group(2)}"
            while i + 1 < len(lines) and re.match(r"^\s{2,}\S", lines[i + 1]):
                i += 1
                text += " " + lines[i].strip()
            par = doc.add_paragraph()
            par.paragraph_format.left_indent = Pt(18)
            par.paragraph_format.first_line_indent = Pt(-12)
            add_inline(par, text)
        elif line.strip() == "---":
            pass
        elif line.strip():
            text = line
            while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r"^(#|\||```|\s*[*-]\s|\d+\.\s|---)", lines[i + 1]):
                i += 1
                text += " " + lines[i].strip()
            add_inline(doc.add_paragraph(), text)
        i += 1


def main() -> None:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)

    render_markdown(doc, (ROOT / "docs" / "SOLUTION.md").read_text())

    doc.add_page_break()
    doc.add_heading("Appendix A — Full system prompt (assistant/system_prompt.md)", 1)
    render_markdown(doc, (ROOT / "assistant" / "system_prompt.md").read_text(), heading_offset=1)

    doc.add_page_break()
    catalog = json.loads((ROOT / "filters" / "catalog.json").read_text())
    doc.add_heading(f"Appendix B — Full filter list ({catalog['count']} filters)", 1)
    add_inline(doc.add_paragraph(), "Also available as `filters/catalog.csv` with synonyms and conflict metadata. "
                                    "Range filters show unit and bounds; ⚔ = has hard conflicts, ⇒ = implies other filters.")
    by_cat: dict[str, list[dict]] = {}
    for f in catalog["filters"]:
        by_cat.setdefault(f["category"], []).append(f)
    for cat, items in by_cat.items():
        doc.add_heading(f"{cat} ({len(items)})", 3)
        rows = [["id", "label", "type"]]
        for f in items:
            t = f["type"]
            if t == "range":
                t = f"range {f['min']}–{f['max']} {f['unit']}"
            elif t == "enum":
                t = "enum: " + ", ".join(f["options"][:6]) + ("…" if len(f["options"]) > 6 else "")
            marks = (" ⚔" if f.get("conflicts_with") or f.get("exclusive_group") else "") + (" ⇒" if f.get("implies") else "")
            rows.append([f"`{f['id']}`", f["label"] + marks, t])
        add_table(doc, rows)

    doc.save(OUT)
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

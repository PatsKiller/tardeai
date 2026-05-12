# DOCX Update Protocol

## The Problem

Direct XML editing of the Reference Architecture DOCX breaks the file. Word stores text split across multiple `<w:r>` runs unpredictably. Regex replacements on DOCX XML have caused:
- `</w:t>` becoming `w:t>` after text swaps
- Orphaned `<w:pPr>` blocks outside `<w:p>` after section deletions
- Corrupted files that don't open in Word

## The Protocol: JSON Patch Approach

### Step 1 — Claude Code gathers live data (queries only, no doc editing)

Claude Code runs the data-gathering queries:
- PostgreSQL: table counts, schema changes, new tables since last backup
- Crontab: `crontab -l` for current job list
- File counts: `find scripts/ -name "*.py" | wc -l`, skill counts, etc.
- OpenClaw: read `~/.openclaw/openclaw.json`, count workspaces/skills
- Backup: latest backup size, date, success status

Claude Code writes results to a flat JSON file:

```
docs/project/docx_patch_YYYYMMDD.json
```

Format:
```json
{
  "patch_date": "2026-05-03",
  "sections": {
    "db_tables": {"count": 143, "new_since_last": ["table_name"]},
    "crontab_entries": {"count": 52, "new": ["0 7 * * * iris library-audit"]},
    "scripts_count": 87,
    "skills_count": 15,
    "backup_latest": {"file": "trade_ai_backup_20260503.zip", "size_mb": 42.8}
  }
}
```

### Step 2 — Apply patch to DOCX using python-docx (safe operations only)

Use `python-docx` library with these constraints:

**ALLOWED:**
- `doc.add_paragraph()` — append new content at end
- `doc.add_table()` — append new tables
- `table.add_row()` — add rows to existing tables
- `paragraph.add_run()` — add text with formatting
- Set `run.bold`, `run.font.name`, `run.font.size`
- Set `paragraph.style` using style objects from existing paragraphs
- Apply table borders via `tblPr` XML append (safe — adds to existing element)
- `shutil.copytree` for backup before any edit

**BANNED — these break the file:**
- `python-docx` paragraph deletion or reordering
- `xml.etree.ElementTree` on the raw .docx XML
- String `.replace()` on XML content
- Direct `lxml` manipulation of paragraph elements
- Removing or moving existing `<w:p>` elements
- Any regex on the XML part files

### Step 3 — Verify

After any DOCX edit:
```python
from docx import Document
doc = Document('path/to/file.docx')
print(f"Paragraphs: {len(doc.paragraphs)}")
print(f"Tables: {len(doc.tables)}")
# Spot-check new content exists
```

## Quick Reference: When to Update What

| Trigger | What to update in DOCX |
|---------|----------------------|
| New DB table created | Appendix D backup table (auto-captured by pg_dump — just note it) |
| New cron job added | Section 12 Operational Runbook (if significant) |
| New OpenClaw skill installed | Appendix C skills table |
| New Python script added | Section 13 Key Files (if core), backup auto-captures |
| New .env variable added | Appendix B .env reference |
| New channel/integration | Appendix B channels + Appendix C channels table |
| Backup scope changed | Appendix D backup components table |

## Table Styling

All tables must have grid borders. After creating tables, apply:

```python
from docx.oxml.ns import nsdecls
from docx.oxml import parse_xml

border_xml = f'<w:tblBorders {nsdecls("w")}>' \
    '<w:top w:val="single" w:sz="4" w:space="0" w:color="000000"/>' \
    '<w:left w:val="single" w:sz="4" w:space="0" w:color="000000"/>' \
    '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000"/>' \
    '<w:right w:val="single" w:sz="4" w:space="0" w:color="000000"/>' \
    '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/>' \
    '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000"/>' \
    '</w:tblBorders>'

for table in doc.tables:
    tblPr = table._tbl.tblPr
    if tblPr is None:
        tblPr = parse_xml(f'<w:tblPr {nsdecls("w")}/>')
        table._tbl.insert(0, tblPr)
    existing = tblPr.find(qn('w:tblBorders'))
    if existing is not None:
        tblPr.remove(existing)
    tblPr.append(parse_xml(border_xml))
```

## Heading Styles

This document has duplicate style names. To get heading styles safely:

```python
h1_style = None
h2_style = None
for p in doc.paragraphs:
    if p.style and p.style.name == 'Heading 1' and h1_style is None:
        h1_style = p.style
    if p.style and p.style.name == 'Heading 2' and h2_style is None:
        h2_style = p.style
    if h1_style and h2_style:
        break
```

Do NOT use `doc.styles['Heading 1']` — it throws KeyError due to duplicate names.

## Before Any DOCX Edit

1. Back up the file: `cp docs/project/Trade_AI_v12_Reference_Architecture.docx docs/project/Trade_AI_v12_Reference_Architecture.docx.bak`
2. Verify backup can open: load it with python-docx and count paragraphs
3. Make edits (append only)
4. Verify result: load and check paragraph/table counts
5. Remove backup only after verification passes

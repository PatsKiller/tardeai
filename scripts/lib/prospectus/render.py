"""Render a Prospectus@v1 document to HTML (self-contained, dark + light), PDF (WeasyPrint) and DOCX (python-docx).

No network: fonts are system stacks, charts are inline SVG (HTML) or embedded PNG (PDF, DOCX), and every library is
already pinned in requirements.txt (matplotlib, python-docx, weasyprint). A missing renderer skips that one format
and says so in the result; it never fails the other formats.
"""
from __future__ import annotations

import base64
from html import escape
import io
import re
from typing import Any

from . import charts as ch
from . import tables as tb
from .stops import stop_plan_table

CITE_RE = re.compile(r"\[(F\d+(?:\s*,\s*F\d+)*)\]")


def _inline(text: str) -> str:
    s = escape(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", s)
    s = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<em>\1</em>", s)
    return CITE_RE.sub(lambda m: "".join(f'<sup class="pc-cite"><a href="#{i.strip()}">{i.strip()}</a></sup>'
                                         for i in m.group(1).split(",")), s)


def md_to_html(md: str) -> str:
    """Small, escaping markdown subset: paragraphs, bullet/numbered lists, bold, italics, citation markers."""
    out, items, kind = [], [], None

    def flush():
        nonlocal items, kind
        if items:
            out.append(f"<{kind}>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + f"</{kind}>")
        items, kind = [], None

    para: list[str] = []
    for line in str(md or "").splitlines() + [""]:
        bullet = re.match(r"^\s*[-*]\s+(.*)$", line)
        number = re.match(r"^\s*\d{1,2}[.)]\s+(.*)$", line)
        if bullet or number:
            if para:
                out.append(f"<p>{_inline(' '.join(para))}</p>")
                para = []
            want = "ul" if bullet else "ol"
            if kind and kind != want:
                flush()
            kind = want
            items.append((bullet or number).group(1))
        elif not line.strip():
            flush()
            if para:
                out.append(f"<p>{_inline(' '.join(para))}</p>")
                para = []
        else:
            flush()
            para.append(re.sub(r"^#+\s*", "", line.strip()))
    return "".join(out)


CSS = """
:root{--bg:%(lbg)s;--surface:%(lsurface)s;--surface2:%(lsurface2)s;--border:%(lborder)s;--text:%(ltext)s;--text2:%(ltext2)s;
--muted:%(lmuted)s;--success:%(lsuccess)s;--warning:%(lwarning)s;--danger:%(ldanger)s;--info:%(linfo)s;--ai:%(lai)s;%(lchart)s}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:%(dbg)s;--surface:%(dsurface)s;--surface2:%(dsurface2)s;
--border:%(dborder)s;--text:%(dtext)s;--text2:%(dtext2)s;--muted:%(dmuted)s;--success:%(dsuccess)s;--warning:%(dwarning)s;
--danger:%(ddanger)s;--info:%(dinfo)s;--ai:%(dai)s;%(dchart)s}}
:root[data-theme="dark"]{--bg:%(dbg)s;--surface:%(dsurface)s;--surface2:%(dsurface2)s;--border:%(dborder)s;--text:%(dtext)s;
--text2:%(dtext2)s;--muted:%(dmuted)s;--success:%(dsuccess)s;--warning:%(dwarning)s;--danger:%(ddanger)s;--info:%(dinfo)s;
--ai:%(dai)s;%(dchart)s}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}
header.pc-head{border-bottom:2px solid var(--info);padding-bottom:12px;margin-bottom:16px}
h1{font-size:26px;margin:0}h1 small{color:var(--muted);font-weight:500;font-size:16px}
.pc-verdict{font-size:17px;color:var(--text2);margin:8px 0 0}
.pc-meta{color:var(--muted);font-size:12px;margin-top:6px;display:flex;flex-wrap:wrap;gap:6px 14px}
.pc-badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;background:var(--surface2);color:var(--text2)}
.pc-badge.holding{color:var(--success)}.pc-badge.watch{color:var(--info)}
section{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;margin:14px 0}
section h2{font-size:18px;margin:0 0 6px;color:var(--text)}
.pc-cite a{color:var(--info);text-decoration:none;font-size:11px;margin-left:1px}
.pc-sources{font-size:12px;color:var(--muted);margin-top:8px}
figure{margin:14px 0;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px}
figcaption{font-size:13px;color:var(--text2);margin-bottom:4px}
.pc-chart{width:100%%;height:auto}.pc-grid{stroke:var(--border);stroke-width:1}.pc-range{stroke:var(--border);stroke-width:3}
.pc-axis,.pc-val,.pc-ann{fill:var(--muted);font-size:11px;font-family:system-ui,sans-serif}.pc-val{fill:var(--text2)}
.pc-charts{display:grid;grid-template-columns:1fr;gap:4px}
@media(min-width:900px){.pc-charts{grid-template-columns:1fr 1fr}}
table.pc-facts{width:100%%;border-collapse:collapse;font-size:12px}
table.pc-facts td{border-top:1px solid var(--border);padding:4px 6px;vertical-align:top;word-break:break-word}
table.pc-facts td:first-child{color:var(--info);white-space:nowrap}
.pc-foot{color:var(--muted);font-size:12px;margin:18px 0 30px}
.pc-tw{overflow-x:auto}table.pc-table{width:100%%;border-collapse:collapse;font-size:13px}
table.pc-table th{text-align:left;color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;padding:4px 6px}
table.pc-table td{border-top:1px solid var(--border);padding:5px 6px;vertical-align:top}
tr.pc-hl td{background:var(--surface2);font-weight:600}
.pc-kpis{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}.pc-kpi{background:var(--surface2);border-radius:8px;padding:6px 10px}
.pc-kpi span{display:block;font-size:11px;color:var(--muted)}.pc-kpi b{font-size:14px}
.pc-note{font-size:12px;color:var(--muted);margin:6px 0 0}
.pc-partial{background:var(--surface2);border-left:3px solid var(--warning);padding:8px 10px;color:var(--text2)}
.pc-st{padding:1px 7px;border-radius:999px;font-size:11px;background:var(--surface2)}
.pc-st-used{color:var(--success)}.pc-st-stale,.pc-st-empty{color:var(--warning)}.pc-st-failed{color:var(--danger)}
.pc-st-not_applicable{color:var(--muted)}
@media print{body{background:#fff}section,figure{break-inside:avoid}}
"""


def css() -> str:
    vals: dict[str, Any] = {}
    for theme, p in (("dark", "d"), ("light", "l")):
        tok = ch.TOKENS[theme]
        for key in ("bg", "surface", "surface2", "border", "text", "text2", "muted", "success", "warning", "danger", "info", "ai"):
            vals[p + key] = tok[key]
        vals[p + "chart"] = "".join(f"--chart-{i + 1}:{c};" for i, c in enumerate(tok["chart"]))
    return CSS % vals


def _money(v: Any) -> str:
    try:
        return f"${float(v):.2f}"
    except (TypeError, ValueError):
        return "n/a"


def html(doc: dict, *, png_charts: dict[str, bytes] | None = None, theme: str | None = None) -> str:
    """Self-contained HTML. With ``png_charts`` the figures embed PNGs (for PDF); otherwise inline SVG."""
    sym, name = escape(doc.get("symbol", "")), escape(doc.get("name", ""))
    scope = doc.get("scope", "watch")
    parts = [f'<!doctype html><html lang="en"{f" data-theme={theme!r}" if theme else ""}><head><meta charset="utf-8">'
             f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{sym} prospectus</title>'
             f"<style>{css()}</style></head><body><main>",
             f'<header class="pc-head"><h1>{sym} <small>{name}</small></h1>'
             f'<p class="pc-verdict">{escape(doc.get("verdict_line", ""))}</p><div class="pc-meta">'
             f'<span class="pc-badge {scope}">{"Holding" if scope == "holding" else "Watch list"}</span>'
             f'<span>Version {escape(str(doc.get("version", "")))}</span><span>Generated {escape(str(doc.get("generated_at", ""))[:16])} UTC</span>'
             f'<span>Model {escape(str(doc.get("model") or "n/a"))}</span><span>Cost {_money(doc.get("cost_usd"))}</span>'
             f"</div></header>"]
    figs: dict[str, str] = {}
    for chart in doc.get("charts") or []:
        if png_charts is not None:
            data = png_charts.get(chart["id"])
            body = (f'<img alt="{escape(chart.get("title", ""))}" style="width:100%" '
                    f'src="data:image/png;base64,{base64.b64encode(data).decode()}">') if data else ""
        else:
            body = ch.svg(chart)
        if body:
            figs[chart["id"]] = (f'<figure id="chart-{chart["id"]}"><figcaption>{escape(chart.get("title", ""))}'
                                 f"</figcaption>{body}</figure>")
    status = doc.get("status") or "ready"
    if status == "partial":
        parts.append('<p class="pc-partial">Partial: ' + escape("; ".join(doc.get("partial_gaps") or [])) + "</p>")
    sections = doc.get("sections") or []

    def section_html(sec: dict) -> str:
        cites = ", ".join(f'<span id="{escape(c["id"])}-ref">{escape(c["id"])}: {escape(c.get("label", ""))}</span>'
                          for c in sec.get("citations") or [])
        return (f'<section id="{escape(sec["id"])}"><h2>{escape(sec.get("title", ""))}</h2>{md_to_html(sec.get("body_md", ""))}'
                + (f'<div class="pc-sources">Sources: {cites}</div>' if cites else "") + "</section>")

    def table_html(t: dict) -> str:
        head = "".join(f"<th>{escape(c)}</th>" for c in t["columns"])
        body = []
        for i, row in enumerate(t["rows"]):
            cls = ' class="pc-hl"' if t.get("highlight") == i else ""
            cells = []
            for k, cell in enumerate(row):
                text = escape(str(cell))
                if k == t.get("status_col"):
                    text = f'<span class="pc-st pc-st-{escape(str(cell))}">{text}</span>'
                elif str(cell).startswith("https://"):
                    text = f'<a href="{escape(str(cell))}">EDGAR</a>'
                cells.append(f"<td>{text}</td>")
            body.append(f"<tr{cls}>" + "".join(cells) + "</tr>")
        kpis = "".join(f'<div class="pc-kpi"><span>{escape(k)}</span><b>{escape(str(v))}</b></div>' for k, v in t.get("kpis") or [])
        return (f'<section id="block-{t["id"]}"><h2>{escape(t["title"])}</h2>' + (figs.pop(t["chart"], "") if t.get("chart") else "")
                + (f'<div class="pc-kpis">{kpis}</div>' if kpis else "")
                + f'<div class="pc-tw"><table class="pc-table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
                + (f'<p class="pc-note">{escape(t["note"])}</p>' if t.get("note") else "") + "</section>")

    if sections:
        parts.append(section_html(sections[0]))
    parts.append('<div class="pc-charts">' + "".join(figs.pop(k) for k in ("price_1y", "analyst_targets", "position_pl")
                                                       if k in figs) + "</div>")
    for t in tb.top_tables(doc) + stop_plan_table(doc):
        parts.append(table_html(t))
    for sec in sections[1:]:
        parts.append(section_html(sec))
        if sec["id"] == "valuation_vs_peers":
            parts.append("".join(figs.pop(k) for k in ("valuation_vs_peers", "revenue_eps_trend") if k in figs))
    for t in tb.bottom_tables(doc):
        parts.append(table_html(t))
    if figs:
        parts.append('<div class="pc-charts">' + "".join(figs.values()) + "</div>")
    rows = "".join(
        f'<tr><td id="{escape(f["id"])}">{escape(f["id"])}</td><td>{escape(f.get("label", ""))}</td>'
        f'<td>{escape(str(f.get("value", f.get("text", ""))))}{escape(" " + f["unit"]) if f.get("unit") and "value" in f else ""}</td>'
        f'<td>{escape(f.get("source", ""))}</td><td>{escape(str(f.get("as_of") or "")[:10])}</td></tr>'
        for f in doc.get("facts") or [])
    parts.append(f'<section id="facts"><h2>Sources and facts</h2><table class="pc-facts">{rows}</table></section>')
    gaps = "; ".join(escape(g) for g in doc.get("gaps") or [])
    parts.append(f'<p class="pc-foot">{escape(doc.get("advisory", ""))}'
                 + (f"<br>Data gaps: {gaps}" if gaps else "") + "</p></main></body></html>")
    return "".join(parts)


def chart_pngs(doc: dict) -> dict[str, bytes]:
    out = {}
    for chart in doc.get("charts") or []:
        data = ch.png(chart, theme="light")
        if data:
            out[chart["id"]] = data
    return out


def pdf(doc: dict, pngs: dict[str, bytes]) -> bytes | None:
    try:
        import weasyprint  # noqa: PLC0415
    except (ImportError, OSError):
        return None
    return weasyprint.HTML(string=html(doc, png_charts=pngs, theme="light")).write_pdf()


def docx(doc: dict, pngs: dict[str, bytes]) -> bytes | None:
    try:
        from docx import Document  # noqa: PLC0415
        from docx.shared import Inches, Pt, RGBColor  # noqa: PLC0415
    except ImportError:
        return None
    light = ch.TOKENS["light"]

    def rgb(hexstr: str):
        return RGBColor.from_string(hexstr.lstrip("#").upper())

    d = Document()
    style = d.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    title = d.add_heading(f"{doc.get('symbol', '')} — {doc.get('name', '')}", level=0)
    for run in title.runs:
        run.font.color.rgb = rgb(light["info"])
    p = d.add_paragraph()
    run = p.add_run(doc.get("verdict_line", ""))
    run.bold = True
    meta = d.add_paragraph(f"{'Holding' if doc.get('scope') == 'holding' else 'Watch list'} · version {doc.get('version')} · "
                           f"generated {str(doc.get('generated_at', ''))[:16]} UTC · model {doc.get('model') or 'n/a'}")
    for run in meta.runs:
        run.font.color.rgb = rgb(light["muted"])
        run.font.size = Pt(8.5)
    for i, sec in enumerate(doc.get("sections") or []):
        h = d.add_heading(sec.get("title", ""), level=1)
        for run in h.runs:
            run.font.color.rgb = rgb(light["text"])
        for block in str(sec.get("body_md", "")).split("\n"):
            text = block.strip()
            if not text:
                continue
            bullet = re.match(r"^[-*]\s+(.*)$", text) or re.match(r"^\d{1,2}[.)]\s+(.*)$", text)
            para = d.add_paragraph(style="List Bullet" if bullet else None)
            body = bullet.group(1) if bullet else re.sub(r"^#+\s*", "", text)
            for chunk in re.split(r"(\*\*.+?\*\*|\[F\d+(?:\s*,\s*F\d+)*\])", body):
                if not chunk:
                    continue
                r = para.add_run(chunk.strip("*") if chunk.startswith("**") else chunk)
                if chunk.startswith("**"):
                    r.bold = True
                elif chunk.startswith("[F"):
                    r.font.superscript = True
                    r.font.color.rgb = rgb(light["info"])
        if sec.get("citations"):
            src = d.add_paragraph("Sources: " + "; ".join(f"{c['id']} {c.get('label', '')}" for c in sec["citations"]))
            for run in src.runs:
                run.font.size = Pt(8)
                run.font.color.rgb = rgb(light["muted"])
        if i == 0:
            for chart in doc.get("charts") or []:
                data = pngs.get(chart["id"])
                if data and chart["id"] not in ("relative_performance", "eps_surprise"):
                    d.add_picture(io.BytesIO(data), width=Inches(6.2))
    def add_table(t: dict) -> None:
        d.add_heading(t["title"], level=1)
        if t.get("chart") and pngs.get(t["chart"]):
            d.add_picture(io.BytesIO(pngs[t["chart"]]), width=Inches(6.2))
        for k, v in t.get("kpis") or []:
            kp = d.add_paragraph(f"{k}: {v}")
            for run in kp.runs:
                run.font.size = Pt(9)
        tbl = d.add_table(rows=1, cols=len(t["columns"]))
        tbl.style = "Light Grid Accent 1"
        for cell, label in zip(tbl.rows[0].cells, t["columns"]):
            cell.text = str(label)
        for i, row in enumerate(t["rows"]):
            cells = tbl.add_row().cells
            for cell, val in zip(cells, row):
                cell.text = str(val)
                if t.get("highlight") == i:
                    for para in cell.paragraphs:
                        for run in para.runs:
                            run.bold = True
        if t.get("note"):
            np_ = d.add_paragraph(t["note"])
            for run in np_.runs:
                run.font.size = Pt(8)
                run.font.color.rgb = rgb(light["muted"])

    for t in tb.top_tables(doc) + stop_plan_table(doc) + tb.bottom_tables(doc):
        add_table(t)
    d.add_heading("Sources and facts", level=1)
    facts = doc.get("facts") or []
    table = d.add_table(rows=1, cols=4)
    table.style = "Light List Accent 1"
    for cell, label in zip(table.rows[0].cells, ("Id", "Fact", "Value", "Source / as of")):
        cell.text = label
    for f in facts:
        cells = table.add_row().cells
        cells[0].text = f["id"]
        cells[1].text = f.get("label", "")
        cells[2].text = str(f.get("value", f.get("text", "")))
        cells[3].text = f"{f.get('source', '')} · {str(f.get('as_of') or '')[:10]}"
    foot = d.add_paragraph(doc.get("advisory", ""))
    for run in foot.runs:
        run.font.size = Pt(8)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def render_all(doc: dict) -> dict[str, bytes]:
    """{relative path: bytes} for one version directory (missing renderers are simply absent)."""
    pngs = chart_pngs(doc)
    files = {"prospectus.html": html(doc).encode("utf-8")}
    for cid, data in pngs.items():
        files[f"charts/{cid}.png"] = data
    pdf_bytes = pdf(doc, pngs)
    if pdf_bytes:
        files["prospectus.pdf"] = pdf_bytes
    docx_bytes = docx(doc, pngs)
    if docx_bytes:
        files["prospectus.docx"] = docx_bytes
    return files

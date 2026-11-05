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
from . import extensions as ext
from . import presentation as pr
from . import tables as tb
from .stops import stop_plan_table

CITE_RE = pr.GROUP_RE  # kept for callers; matches "[F7]" and "[F7, F8]"
_CITE_ID = re.compile(r"^[FW]\d+$")  # internal fact (F7) and web-fact (W2) ids; never shown to the reader
NA_CELL_RE = re.compile(r"^[\s·/|,()—-]*(?:(?:n/a|none|not available(?: yet)?|—|-|unknown)[\s·/|,()—-]*)*$", re.IGNORECASE)


def _cites(s: str, notes: dict[str, dict] | None) -> str:
    """Remove citation groups from already-escaped text (operator 2026-10-27: no visible citations). The fact ids stay
    in a hidden ``data-fact-id`` marker for the gate, the layer-3 check and the accuracy auditor."""
    known = set(notes or {})

    def rep(m: re.Match) -> str:
        ids = pr.split_ids(m.group(1))
        if not all(_CITE_ID.match(i) or i in known for i in ids):
            return m.group(0)
        return f'<span class="pc-cite" data-fact-id="{escape(" ".join(ids))}" hidden></span>'

    out = pr.GROUP_RE.sub(rep, s)
    return re.sub(r"\s+(<span class=\"pc-cite\")", r"\1", out)


def _inline(text: str, notes: dict[str, dict] | None = None) -> str:
    s = escape(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<em>\1</em>", s)
    s = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<em>\1</em>", s)
    s = pr.UNRELIABLE_RE.sub(lambda m: f'<span class="pc-mute">{m.group(0)}</span>', s)
    return _cites(s, notes)


def cell_html(text: Any, notes: dict[str, dict] | None = None) -> str:
    return _inline(pr.clean_prose(text), notes)


def md_to_html(md: str, notes: dict[str, dict] | None = None) -> str:
    """Small, escaping markdown subset: paragraphs, bullet/numbered lists, bold, italics, footnote numbers."""
    out, items, kind = [], [], None

    def flush():
        nonlocal items, kind
        if items:
            out.append(f"<{kind}>" + "".join(f"<li>{_inline(i, notes)}</li>" for i in items) + f"</{kind}>")
        items, kind = [], None

    para: list[str] = []
    for seg, line in pr.md_segments(pr.clean_prose(md)) + [("text", "")]:
        if seg == "table":
            flush()
            if para:
                out.append(f"<p>{_inline(' '.join(para), notes)}</p>")
                para = []
            head = "".join(f"<th>{_inline(c, notes)}</th>" for c in line["head"])
            body = "".join("<tr>" + "".join(f"<td>{_inline(c, notes)}</td>" for c in r) + "</tr>" for r in line["rows"])
            out.append(f'<div class="pc-tw"><table class="pc-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
            continue
        bullet = re.match(r"^\s*[-*•]\s+(.*)$", line)
        number = re.match(r"^\s*\d{1,2}[.)]\s+(.*)$", line)
        if bullet or number:
            if para:
                out.append(f"<p>{_inline(' '.join(para), notes)}</p>")
                para = []
            want = "ul" if bullet else "ol"
            if kind and kind != want:
                flush()
            kind = want
            if (bullet or number).group(1).strip():
                items.append((bullet or number).group(1))
        elif not line.strip():
            flush()
            if para:
                out.append(f"<p>{_inline(' '.join(para), notes)}</p>")
                para = []
        else:
            flush()
            para.append(re.sub(r"^#+\s*", "", line.strip()))
    return "".join(out)


def _is_na(v: Any) -> bool:
    return bool(NA_CELL_RE.match(str(v if v is not None else "")))


def polish_tables(doc: dict, tables: list[dict], pres: dict | None = None) -> list[dict]:
    """Fund-aware, gap-compact tables: blocks that do not apply to a fund are dropped (the fund structure takes the
    ownership slot); rows whose every value is missing collapse into one "Not in our data: …" note per table."""
    pres = pres or pr.present(doc)
    fund = bool(pres.get("is_fund"))
    out: list[dict] = []
    for t in tables:
        tid = t.get("id")
        if tid == "source_coverage":
            continue  # rendered from the presentation coverage (relevant domains only)
        if fund and tid in pr.FUND_HIDDEN_BLOCKS:
            if tid == "ownership_flows" and pres.get("fund_structure"):
                out.append(fund_structure_table(pres["fund_structure"]))
            continue
        t = dict(t)
        if t.get("columns") and t["columns"][0] in ("Measure", "Topic", "Series") and len(t["columns"]) >= 2:
            keep, absent = [], []
            for row in t.get("rows") or []:
                (absent if all(_is_na(c) for c in row[1:]) else keep).append(row)
            t["rows"] = keep
            if absent:
                lead = "Not in our data: " + ", ".join(str(r[0]) for r in absent) + "."
                t["note"] = lead + (" " + t["note"] if t.get("note") else "")
        out.append(t)
    if fund and pres.get("fund_structure") and not any(t.get("id") == "fund_structure" for t in out):
        if any(t.get("id") in ("relative_performance", "peer_comparison", "risk_technicals") for t in tables):
            idx = next((i for i, t in enumerate(out) if t.get("id") == "risk_technicals"), len(out))
            out.insert(idx, fund_structure_table(pres["fund_structure"]))
    return out


def fund_structure_table(fs: dict) -> dict:
    rows = [[r["label"], r["value"] + "".join(f" [{c}]" for c in r.get("cites") or [])] for r in fs.get("rows") or []]
    top = fs.get("top_holdings") or []
    if top:
        rows.append(["Top holdings", "; ".join(f"{h.get('symbol') or h['name']} {h['weight_pct']:.1f}%" if h.get("weight_pct") is not None
                                              else str(h.get("symbol") or h["name"]) for h in top)])
    if fs.get("sectors"):
        rows.append(["Sector weights", "; ".join(f"{x['name']} {x['weight_pct']:.1f}%" for x in fs["sectors"])])
    if fs.get("countries"):
        rows.append(["Country weights", "; ".join(f"{x['name']} {x['weight_pct']:.1f}%" for x in fs["countries"])])
    note = ("Not in our data: " + ", ".join(fs["missing"]) + ".") if fs.get("missing") else ""
    if fs.get("as_of"):
        note += f" Holdings as of {fs['as_of']}."
    return {"id": "fund_structure", "title": "Fund structure & holdings", "columns": ["Measure", "Value"], "rows": rows,
            "note": note.strip()}


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
.pc-mute{color:var(--muted);font-style:italic}
details>summary{cursor:pointer;list-style:none}details>summary::-webkit-details-marker{display:none}
details>summary h2{display:inline}details>summary::before{content:"\\25B8  ";color:var(--muted)}details[open]>summary::before{content:"\\25BE  "}
section h2 small{color:var(--muted);font-weight:500;font-size:13px}
.pc-cov{margin:6px 0;font-size:12px;line-height:2}.pc-cov b{color:var(--text2);margin-right:4px}
:target{scroll-margin-top:16px}li:target{background:var(--surface2)}
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
.pc-valid{margin:8px 0 0;font-size:12px;color:var(--text2)}.pc-valid summary{cursor:pointer;min-height:32px;padding:6px 0}
.pc-valid-ok summary,p.pc-valid-ok{color:var(--success)}.pc-valid-warn summary,p.pc-valid-warn{color:var(--warning)}
ul.pc-vlist{margin:2px 0 6px;padding-left:18px;font-size:12px;color:var(--text2)}
@media print{body{background:#fff}section,figure{break-inside:avoid}}
"""


def drawable(chart: dict) -> bool:
    """False for a chart too thin to draw honestly: an EPS-surprise chart of fewer than 3 quarters (one quarter drew a
    page-wide bar). Stored reports are filtered at render time; the estimates table still lists every quarter."""
    if chart.get("id") == "eps_surprise":
        pts = [p for s in chart.get("series") or [] for p in (s.get("points") or []) if len(p) > 1 and p[1] is not None]
        return len(pts) >= 3
    return True


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


def _when(v: Any) -> str:
    return str(v or "")[:10]


def html(doc: dict, *, png_charts: dict[str, bytes] | None = None, theme: str | None = None,
         print_mode: bool | None = None) -> str:
    """Self-contained HTML. With ``png_charts`` the figures embed PNGs (for PDF); otherwise inline SVG.
    ``print_mode`` (default: when PNGs are given) uses plain lists instead of collapsible disclosures."""
    printing = png_charts is not None if print_mode is None else print_mode
    pres = pr.present(doc)
    notes_list = pres.get("footnotes") or []
    notes = {e["id"]: e for e in notes_list}
    sym = escape(doc.get("symbol", ""))
    shown_name = pres.get("display_name") or doc.get("name") or ""
    name = escape(shown_name) if str(shown_name).upper() != str(doc.get("symbol", "")).upper() else ""
    scope = doc.get("scope", "watch")
    parts = [f'<!doctype html><html lang="en"{f" data-theme={theme!r}" if theme else ""}><head><meta charset="utf-8">'
             f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{sym} prospectus</title>'
             f"<style>{css()}</style></head><body><main>",
             f'<header class="pc-head"><h1>{sym}{f" <small>{name}</small>" if name else ""}</h1>'
             f'<p class="pc-verdict">{_inline(pr.clean_prose(doc.get("verdict_line", "")), notes)}</p><div class="pc-meta">'
             f'<span class="pc-badge {scope}">{"Holding" if scope == "holding" else "Watch list"}</span>'
             f'<span>Version {escape(str(doc.get("version", "")))}</span><span>Generated {escape(str(doc.get("generated_at", ""))[:16])} UTC</span>'
             f'<span>Model {escape(str(doc.get("model") or "n/a"))}</span><span>Cost {_money(doc.get("cost_usd"))}</span>'
             f"</div>{validation_html(pres.get('validation') or {}, printing)}</header>"]
    figs: dict[str, str] = {}
    for chart in doc.get("charts") or []:
        if not drawable(chart):
            continue
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
    sections = pr.ordered_sections(doc)

    def section_html(sec: dict) -> str:
        return (f'<section id="{escape(sec["id"])}"><h2>{escape(sec.get("title", ""))}</h2>'
                f'{md_to_html(sec.get("body_md", ""), notes)}</section>')

    def table_html(t: dict) -> str:
        head = "".join(f"<th>{escape(c)}</th>" for c in t["columns"])
        body = []
        for i, row in enumerate(t["rows"]):
            cls = ' class="pc-hl"' if t.get("highlight") == i else ""
            cells = []
            for k, cell in enumerate(row):
                if k == t.get("status_col"):
                    text = f'<span class="pc-st pc-st-{escape(str(cell))}">{escape(str(cell))}</span>'
                elif str(cell).startswith("https://"):
                    text = f'<a href="{escape(str(cell))}">{"EDGAR" if "sec.gov" in str(cell) else "link"}</a>'
                else:
                    text = cell_html(cell, notes)
                cells.append(f"<td>{text}</td>")
            body.append(f"<tr{cls}>" + "".join(cells) + "</tr>")
        kpis = "".join(f'<div class="pc-kpi"><span>{escape(k)}</span><b>{escape(str(v))}</b></div>' for k, v in t.get("kpis") or []
                       if not _is_na(v))
        table = (f'<div class="pc-tw"><table class="pc-table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
                 if body else "")
        return (f'<section id="block-{t["id"]}"><h2>{escape(t["title"])}</h2>' + (figs.pop(t["chart"], "") if t.get("chart") else "")
                + (f'<div class="pc-kpis">{kpis}</div>' if kpis else "") + table
                + (f'<p class="pc-note">{cell_html(t["note"], notes)}</p>' if t.get("note") else "") + "</section>")

    for t in polish_tables(doc, ext.top_tables(doc), pres):
        parts.append(table_html(t))
    if sections:
        parts.append(section_html(sections[0]))
    parts.append('<div class="pc-charts">' + "".join(figs.pop(k) for k in ("price_1y", "analyst_targets", "position_pl")
                                                       if k in figs) + "</div>")
    for t in polish_tables(doc, tb.top_tables(doc) + stop_plan_table(doc), pres):
        parts.append(table_html(t))
    for sec in sections[1:]:
        parts.append(section_html(sec))
        if sec["id"] == "valuation_vs_peers":
            parts.append("".join(figs.pop(k) for k in ("valuation_vs_peers", "revenue_eps_trend") if k in figs))
    for t in polish_tables(doc, tb.bottom_tables(doc) + ext.bottom_tables(doc), pres):
        parts.append(table_html(t))
    if figs:
        parts.append('<div class="pc-charts">' + "".join(figs.values()) + "</div>")
    parts.append(coverage_html(pres.get("coverage") or {}, printing))
    gaps = "; ".join(escape(g) for g in doc.get("gaps") or [])
    parts.append(f'<p class="pc-foot">{escape(doc.get("advisory", ""))}'
                 + (f"<br>Data gaps: {gaps}" if gaps else "") + "</p></main></body></html>")
    return "".join(parts)


def validation_html(v: dict, printing: bool) -> str:
    """ONE validation statement under the header; on screen it opens a compact summary (counts by source type and
    any unreliable fields) — never a citation list."""
    if not v or not v.get("line"):
        return ""
    cls = {"validated": "ok", "partial": "warn"}.get(str(v.get("status")), "info")
    line = escape(str(v["line"]))
    if printing:
        return f'<p class="pc-valid pc-valid-{cls}" data-validation="{escape(str(v.get("status")))}">{line}</p>'
    rows = "".join(f"<li>{escape(k)} <b>{int(n)}</b></li>" for k, n in (v.get("by_source") or {}).items())
    bad = "".join(f"<li>{escape(u['label'])} — {escape(u['reason'])}</li>" for u in v.get("unreliable") or [])
    reasons = "".join(f"<li>{escape(r)}</li>" for r in v.get("reasons") or [])
    body = (f'<p class="pc-note">Figures checked by source type</p><ul class="pc-vlist">{rows}</ul>'
            + (f'<p class="pc-note">Not validated</p><ul class="pc-vlist">{bad}{reasons}</ul>' if (bad or reasons) else ""))
    return (f'<details class="pc-valid pc-valid-{cls}" data-validation="{escape(str(v.get("status")))}">'
            f"<summary>{line}</summary>{body}</details>")


def coverage_html(cov: dict, printing: bool) -> str:
    groups, counts = cov.get("groups") or {}, cov.get("counts") or {}
    if not any(counts.values()):
        return ""
    summary = " · ".join(f"{counts[g]} {lab.lower()}" for g, lab in pr.COVERAGE_GROUPS if counts.get(g))
    rows = []
    for g, lab in pr.COVERAGE_GROUPS:
        if groups.get(g):
            chips = "".join(f'<span class="pc-st pc-st-{escape(g)}" title="{escape(str(d.get("reason") or ""))}">{escape(d["label"])}'
                            + (f' · {escape(_when(d.get("as_of")))}' if g == "stale" and d.get("as_of") else "") + "</span> "
                            for d in groups[g])
            rows.append(f'<p class="pc-cov"><b>{lab}</b> {chips}</p>')
    key = (f'<p class="pc-note">Partial: {escape("; ".join(cov["key_gaps"]))}</p>' if cov.get("key_gaps") else "")
    body = "".join(rows) + key
    if printing:
        return f'<section id="block-source_coverage"><h2>Source coverage <small>{escape(summary)}</small></h2>{body}</section>'
    return (f'<section id="block-source_coverage"><details><summary><h2>Source coverage <small>{escape(summary)}</small></h2>'
            f"</summary>{body}</details></section>")


def chart_pngs(doc: dict) -> dict[str, bytes]:
    out = {}
    for chart in doc.get("charts") or []:
        if not drawable(chart):
            continue
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


def _runs(para: Any, text: str, notes: dict[str, dict], rgb: Any, light: dict, *, size: Any = None) -> None:
    """Add ``text`` to a python-docx paragraph: **bold** runs, citation groups removed (kept in the JSON),
    "not reliable (…)" notes muted and italic."""
    text = pr.clean_prose(text)
    known = set(notes)
    pos = 0
    pieces: list[tuple[str, str]] = []
    for m in pr.GROUP_RE.finditer(text):
        ids = pr.split_ids(m.group(1))
        if not all(_CITE_ID.match(i) or i in known for i in ids):
            continue
        pieces.append(("t", text[pos:m.start()].rstrip(" ")))
        pieces.append(("n", ",".join(str(notes[i]["n"]) for i in ids if i in notes)))
        pos = m.end()
    pieces.append(("t", text[pos:]))
    for kind, chunk in pieces:
        if not chunk:
            continue
        if kind == "n":  # citations are not shown (operator 2026-10-27); they stay in the JSON
            continue
        for sub in re.split(r"(\*\*.+?\*\*)", chunk):
            if not sub:
                continue
            bold = sub.startswith("**") and sub.endswith("**")
            body = sub[2:-2] if bold else sub
            last = 0
            for mm in pr.UNRELIABLE_RE.finditer(body):
                if mm.start() > last:
                    r = para.add_run(body[last:mm.start()])
                    r.bold = bold or None
                    if size:
                        r.font.size = size
                r = para.add_run(mm.group(0))
                r.italic = True
                r.font.color.rgb = rgb(light["muted"])
                if size:
                    r.font.size = size
                last = mm.end()
            if last < len(body):
                r = para.add_run(body[last:])
                r.bold = bold or None
                if size:
                    r.font.size = size


def docx(doc: dict, pngs: dict[str, bytes]) -> bytes | None:
    try:
        from docx import Document  # noqa: PLC0415
        from docx.shared import Inches, Pt, RGBColor  # noqa: PLC0415
    except ImportError:
        return None
    light = ch.TOKENS["light"]
    pres = pr.present(doc)
    notes_list = pres.get("footnotes") or []
    notes = {e["id"]: e for e in notes_list}

    def rgb(hexstr: str):
        return RGBColor.from_string(hexstr.lstrip("#").upper())

    d = Document()
    style = d.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    name = pres.get("display_name") or doc.get("name") or ""
    sym = str(doc.get("symbol", ""))
    title = d.add_heading(sym + (f" — {name}" if name and name.upper() != sym.upper() else ""), level=0)
    for run in title.runs:
        run.font.color.rgb = rgb(light["info"])
    p = d.add_paragraph()
    _runs(p, doc.get("verdict_line", ""), notes, rgb, light)
    for run in p.runs:
        if not run.font.superscript:
            run.bold = True
    meta = d.add_paragraph(f"{'Holding' if doc.get('scope') == 'holding' else 'Watch list'} · version {doc.get('version')} · "
                           f"generated {str(doc.get('generated_at', ''))[:16]} UTC · model {doc.get('model') or 'n/a'}")
    for run in meta.runs:
        run.font.color.rgb = rgb(light["muted"])
        run.font.size = Pt(8.5)
    val = pres.get("validation") or {}
    if val.get("line"):
        vp = d.add_paragraph(str(val["line"]))
        for run in vp.runs:
            run.font.size = Pt(9)
            run.font.color.rgb = rgb(light["success"] if val.get("status") == "validated" else light["warning"]
                                     if val.get("status") == "partial" else light["muted"])

    def add_table(t: dict) -> None:
        d.add_heading(t["title"], level=1)
        if t.get("chart") and pngs.get(t["chart"]):
            d.add_picture(io.BytesIO(pngs[t["chart"]]), width=Inches(6.2))
        for k, v in t.get("kpis") or []:
            if _is_na(v):
                continue
            kp = d.add_paragraph(f"{k}: {v}")
            for run in kp.runs:
                run.font.size = Pt(9)
        if t["rows"]:
            tbl = d.add_table(rows=1, cols=len(t["columns"]))
            tbl.style = "Light Grid Accent 1"
            for cell, label in zip(tbl.rows[0].cells, t["columns"]):
                cell.text = str(label)
            for i, row in enumerate(t["rows"]):
                cells = tbl.add_row().cells
                for cell, val in zip(cells, row):
                    _runs(cell.paragraphs[0], str(val), notes, rgb, light)
                    if t.get("highlight") == i:
                        for run in cell.paragraphs[0].runs:
                            run.bold = True
        if t.get("note"):
            np_ = d.add_paragraph()
            _runs(np_, t["note"], notes, rgb, light, size=Pt(8))
            for run in np_.runs:
                if not run.font.superscript:
                    run.font.color.rgb = rgb(light["muted"])

    for t in polish_tables(doc, ext.top_tables(doc), pres):
        add_table(t)
    for i, sec in enumerate(pr.ordered_sections(doc)):
        h = d.add_heading(sec.get("title", ""), level=1)
        for run in h.runs:
            run.font.color.rgb = rgb(light["text"])
        for seg, block in pr.md_segments(pr.clean_prose(sec.get("body_md", ""))):
            if seg == "table":
                tbl = d.add_table(rows=1, cols=len(block["head"]))
                tbl.style = "Light Grid Accent 1"
                for cell, label in zip(tbl.rows[0].cells, block["head"]):
                    _runs(cell.paragraphs[0], label, notes, rgb, light)
                for r in block["rows"]:
                    for cell, val in zip(tbl.add_row().cells, r):
                        _runs(cell.paragraphs[0], val, notes, rgb, light)
                continue
            text = block.strip()
            if not text:
                continue
            bullet = re.match(r"^[-*•]\s+(.*)$", text) or re.match(r"^\d{1,2}[.)]\s+(.*)$", text)
            para = d.add_paragraph(style="List Bullet" if bullet else None)
            _runs(para, bullet.group(1) if bullet else re.sub(r"^#+\s*", "", text), notes, rgb, light)
        if i == 0:
            for chart in doc.get("charts") or []:
                data = pngs.get(chart["id"])
                if data and chart["id"] not in ("relative_performance", "eps_surprise"):
                    d.add_picture(io.BytesIO(data), width=Inches(6.2))

    for t in polish_tables(doc, tb.top_tables(doc) + stop_plan_table(doc) + tb.bottom_tables(doc) + ext.bottom_tables(doc), pres):
        add_table(t)
    cov = pres.get("coverage") or {}
    if any((cov.get("counts") or {}).values()):
        d.add_heading("Source coverage", level=1)
        for g, lab in pr.COVERAGE_GROUPS:
            items = (cov.get("groups") or {}).get(g) or []
            if items:
                cp = d.add_paragraph()
                r = cp.add_run(f"{lab} ({len(items)}): ")
                r.bold = True
                r.font.size = Pt(8.5)
                r2 = cp.add_run(", ".join(x["label"] for x in items))
                r2.font.size = Pt(8.5)
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
    # PDF / Word downloads: Chromium print + LibreOffice from the same HTML (print_render); each format falls back
    # to the WeasyPrint / python-docx renderer below with a logged reason.
    from . import print_render  # noqa: PLC0415
    files.update(print_render.render_print(doc, pngs, fallback_pdf=pdf, fallback_docx=docx))
    return files

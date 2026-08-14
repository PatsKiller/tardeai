"""cio_report_render.py — Phase 4 multi-format renderers over one report view.

Consumes only `build_report_view(model)` output (or a full model that will be
projected). Never recalculates financial arithmetic.

Formats:
  * HTML  — self-contained, print-friendly
  * DOCX  — python-docx when available
  * PDF   — Chromium/Chrome headless or weasyprint/wkhtmltopdf when available
  * JSON  — model + view + parity manifest

READ_ONLY_ADVISORY. No broker / Telegram.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_report_view import (
    REPORT_ARCHITECTURE_VERSION,
    build_report_view,
    section_by_id,
)


def _e(v: Any) -> str:
    return (
        str(v if v is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _ensure_view(model_or_view: dict[str, Any]) -> dict[str, Any]:
    if model_or_view.get("architecture_version") and model_or_view.get("sections"):
        return model_or_view
    if model_or_view.get("view") and isinstance(model_or_view["view"], dict):
        return model_or_view["view"]
    return build_report_view(model_or_view)


# ─────────────────────────────────────────────────────────────────────────────
# HTML
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
@page { size:letter; margin:1.6cm 1.4cm;
  @bottom-center {
    content:"Trade AI — Institutional Report v2  ·  page " counter(page) " of " counter(pages);
    font-size:8pt; color:#555;
  }
}
:root { --ink:#111; --muted:#666; --line:#ddd; --bg:#fff; --hi:#f7f7f5; }
* { box-sizing:border-box; }
body { font-family: 'Segoe UI', Calibri, system-ui, sans-serif; color:var(--ink);
       margin:0; padding:24px 32px; background:var(--bg); line-height:1.45; }
h1 { font-size:1.6rem; margin:0 0 .25rem; }
h2 { font-size:1.2rem; margin:1.6rem 0 .5rem; border-bottom:1px solid var(--line); padding-bottom:.25rem; }
h3 { font-size:1.05rem; margin:1rem 0 .4rem; }
.lede { color:var(--muted); font-size:.92rem; margin-bottom:.75rem; }
.meta { display:flex; flex-wrap:wrap; gap:.75rem 1.25rem; color:var(--muted); font-size:.8rem; margin-bottom:1rem; }
.meta span { white-space:nowrap; }
.section { margin-bottom:1.25rem; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:.5rem; }
.box { background:var(--hi); border:1px solid var(--line); border-radius:6px; padding:.55rem .7rem; }
.box .k { font-size:.7rem; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }
.box .v { font-size:1.05rem; font-weight:600; margin-top:.15rem; }
table { width:100%; border-collapse:collapse; font-size:.88rem; margin:.4rem 0 .8rem; }
th, td { border:1px solid var(--line); padding:.35rem .5rem; text-align:left; vertical-align:top; }
th { background:var(--hi); font-weight:600; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
.pos { color:#0a7a2f; }
.neg { color:#a11; }
.badge.flag { background:#fde8e8; color:#a11; font-size:.72rem; padding:.1rem .35rem; border-radius:3px; }
.footnote { font-size:.78rem; color:var(--muted); margin-top:.25rem; }
ul { margin:.25rem 0 .6rem 1.1rem; padding:0; }
@media print {
  body { padding:12mm; }
  h2 { break-after:avoid; }
  table { break-inside:avoid; }
}
"""

def render_html_from_view(view: dict[str, Any]) -> str:
    """Render the full institutional report HTML from a shared view."""
    view = _ensure_view(view)
    sections_html: list[str] = []

    cover = section_by_id(view, "cover") or {}
    meta = cover.get("meta") or {}
    sections_html.append(f"<h1>{_e(cover.get('title') or 'Trade AI — Institutional Report v2')}</h1>")
    sections_html.append(
        "<div class='lede'>Private investment office · CIO advisory · "
        "READ_ONLY_ADVISORY — no execution authority · "
        f"arch {_e(meta.get('architecture') or REPORT_ARCHITECTURE_VERSION)}</div>"
    )
    sections_html.append(
        f"<div class='meta'><span>as_of {_e(meta.get('as_of'))}</span>"
        f"<span>source SHA {_e(meta.get('source_sha') or '—')}</span>"
        f"<span>manifest {_e(meta.get('manifest_hash_short') or '—')}…</span>"
        f"<span>traceability {_e(meta.get('traceability_pct'))}%</span>"
        f"<span>facts {_e(str(view.get('facts_fingerprint') or '')[:12])}</span></div>"
    )

    sections_html.append("<h2>Part A — CIO Investment Committee</h2>")

    letter = section_by_id(view, "cio_letter") or {}
    sections_html.append(f"<div class='section'><h3>{_e(letter.get('title'))}</h3>")
    if letter.get("thesis_summary"):
        sections_html.append(f"<p>{_e(letter['thesis_summary'])}</p>")
    if letter.get("stance"):
        sections_html.append(f"<p><strong>Stance:</strong> {_e(letter['stance'])}</p>")
    if letter.get("priorities"):
        sections_html.append("<p><strong>Priorities:</strong></p><ul>")
        for p in letter["priorities"]:
            sections_html.append(f"<li>{_e(p)}</li>")
        sections_html.append("</ul>")
    if letter.get("what_not_to_do"):
        sections_html.append("<p><strong>What not to do:</strong></p><ul>")
        for p in letter["what_not_to_do"]:
            sections_html.append(f"<li>{_e(p)}</li>")
        sections_html.append("</ul>")
    sections_html.append("</div>")

    for sid in ("decisions_now", "capital_plan", "portfolio_posture"):
        sec = section_by_id(view, sid)
        if not sec:
            continue
        sections_html.append(f"<div class='section'><h3>{_e(sec.get('title'))}</h3>")
        if sec.get("kind") == "table":
            rows = sec.get("rows") or []
            if rows:
                headers = sec.get("headers") or []
                sections_html.append("<table><thead><tr>")
                for i, h in enumerate(headers):
                    cls = " class='num'" if i >= 2 and i <= 4 else ""
                    sections_html.append(f"<th{cls}>{_e(h)}</th>")
                sections_html.append("</tr></thead><tbody>")
                for row in rows:
                    sections_html.append("<tr>")
                    for i, cell in enumerate(row):
                        cls = " class='num'" if i >= 2 and i <= 4 else ""
                        sections_html.append(f"<td{cls}>{_e(cell)}</td>")
                    sections_html.append("</tr>")
                sections_html.append("</tbody></table>")
            else:
                sections_html.append(f"<p class='lede'>{_e(sec.get('empty_message') or '—')}</p>")
        elif sec.get("kind") == "kv":
            sections_html.append("<div class='grid'>")
            for k, v in sec.get("rows") or []:
                sections_html.append(
                    f"<div class='box'><div class='k'>{_e(k)}</div>"
                    f"<div class='v' style='font-size:.95rem'>{_e(v)}</div></div>"
                )
            sections_html.append("</div>")
            st = sec.get("sector_table")
            if st and st.get("rows"):
                sections_html.append("<table><thead><tr>")
                for h in st.get("headers") or []:
                    sections_html.append(f"<th>{_e(h)}</th>")
                sections_html.append("</tr></thead><tbody>")
                for row in st["rows"]:
                    sections_html.append("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>")
                sections_html.append("</tbody></table>")
        sections_html.append("</div>")

    funnel = section_by_id(view, "opportunity_funnel") or {}
    sections_html.append(f"<div class='section'><h3>{_e(funnel.get('title'))}</h3>")
    for key, title in (
        ("sector_opportunities", "Sector opportunities"),
        ("watch_additions", "Watch additions"),
        ("reentry_candidates", "Re-entry candidates"),
        ("research_gaps", "Research gaps"),
    ):
        items = funnel.get(key) or []
        if not items:
            continue
        sections_html.append(f"<p><strong>{_e(title)}:</strong></p><ul>")
        for it in items[:8]:
            if isinstance(it, dict):
                label = (
                    f"{it.get('sector') or it.get('symbol') or '—'} "
                    f"({it.get('state') or it.get('verdict') or '—'}): "
                    f"{it.get('recommendation') or it.get('label') or ''}"
                )
            else:
                label = str(it)
            sections_html.append(f"<li>{_e(label.strip())}</li>")
        sections_html.append("</ul>")
    sections_html.append("</div>")

    ct = section_by_id(view, "counter_thesis") or {}
    sections_html.append(f"<div class='section'><h3>{_e(ct.get('title'))}</h3>")
    if ct.get("highest_impact_unknowns"):
        sections_html.append("<p><strong>Highest-impact unknowns:</strong></p><ul>")
        for u in ct["highest_impact_unknowns"]:
            sections_html.append(f"<li>{_e(u)}</li>")
        sections_html.append("</ul>")
    sections_html.append("</div>")

    sections_html.append("<h2>Part B — Institutional Portfolio Book</h2>")
    for sid in (
        "portfolio_book", "accounts", "allocation", "performance", "coverage",
        "field_coverage_matrix", "known_gap_resolutions", "quality_flags",
    ):
        sec = section_by_id(view, sid)
        if not sec:
            continue
        sections_html.append(f"<div class='section'><h3>{_e(sec.get('title'))}</h3>")
        if sec.get("kind") == "table":
            headers = sec.get("headers") or []
            rows = sec.get("rows") or []
            sections_html.append("<table><thead><tr>")
            for h in headers:
                sections_html.append(f"<th>{_e(h)}</th>")
            sections_html.append("</tr></thead><tbody>")
            for row in rows:
                cells = []
                for c in row:
                    cs = str(c if c is not None else "—")
                    if "account-aggregated" in cs or cs == "flagged":
                        cells.append(
                            f"<td>{_e(cs)} <span class='badge flag'>flagged</span></td>"
                        )
                    else:
                        cells.append(f"<td>{_e(cs)}</td>")
                sections_html.append("<tr>" + "".join(cells) + "</tr>")
            sections_html.append("</tbody></table>")
        elif sec.get("kind") == "kv":
            sections_html.append("<div class='grid'>")
            for k, v in sec.get("rows") or []:
                sections_html.append(
                    f"<div class='box'><div class='k'>{_e(k)}</div>"
                    f"<div class='v' style='font-size:.95rem'>{_e(v)}</div></div>"
                )
            sections_html.append("</div>")
            if sec.get("unavailable"):
                sections_html.append("<p class='footnote'><strong>Unavailable fields:</strong> "
                                     + _e(", ".join(str(x) for x in sec["unavailable"][:20])) + "</p>")
        elif sec.get("kind") == "list":
            items = sec.get("items") or sec.get("highest_impact_unknowns") or []
            if items:
                sections_html.append("<ul>")
                for u in items:
                    us = str(u)
                    flag = " <span class='badge flag'>flagged</span>" if (
                        "account-aggregated" in us or "flagged" in us
                    ) else ""
                    sections_html.append(f"<li>{_e(us)}{flag}</li>")
                sections_html.append("</ul>")
        sections_html.append("</div>")

    disc = section_by_id(view, "disclosure") or {}
    sections_html.append(
        f"<div class='section'><h3>{_e(disc.get('title') or 'Disclosure')}</h3>"
        f"<p class='lede'>{_e(disc.get('text') or '')}</p></div>"
    )
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{_e(cover.get('title') or 'Institutional Report v2')}</title>"
        f"<style>{_CSS}</style></head><body>"
        + "\n".join(sections_html)
        + "</body></html>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# DOCX
# ─────────────────────────────────────────────────────────────────────────────

def render_docx_from_view(view: dict[str, Any], out: Path) -> Path:
    """Write DOCX from the shared view. Requires python-docx."""
    try:
        import docx
        from docx.shared import Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError as exc:
        raise RuntimeError("python-docx is not installed") from exc

    view = _ensure_view(view)
    document = docx.Document()
    document.core_properties.title = "Trade AI Institutional Report v2"
    document.core_properties.author = "Trade AI Investment Office (Alex, CIO)"
    styles = document.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"].font.size = Pt(10.5)

    def _table(headers: list[str], rows: list[list[Any]]) -> None:
        table = document.add_table(rows=1, cols=len(headers))
        table.style = "Light Grid Accent 1"
        for i, h in enumerate(headers):
            table.rows[0].cells[i].text = str(h)
        for row in rows:
            cells = table.add_row().cells
            for i, val in enumerate(row):
                cells[i].text = str(val if val is not None else "—")

    cover = section_by_id(view, "cover") or {}
    meta = cover.get("meta") or {}
    t = document.add_heading(str(cover.get("title") or "Trade AI — Institutional Report"), level=0)
    sub = document.add_paragraph()
    r = sub.add_run(
        f"{view.get('report_version') or ''}  ·  {view.get('authority') or ''}  ·  "
        f"as-of {view.get('as_of') or ''}  ·  arch {meta.get('architecture') or REPORT_ARCHITECTURE_VERSION}"
    )
    r.italic = True
    r.font.size = Pt(9)
    r.font.color.rgb = RGBColor(0x60, 0x60, 0x60)
    if meta.get("source_sha"):
        p = document.add_paragraph()
        pr = p.add_run(
            f"Source SHA: {meta['source_sha']}  ·  facts {str(view.get('facts_fingerprint') or '')[:16]}"
        )
        pr.font.size = Pt(8)
        pr.font.color.rgb = RGBColor(0x90, 0x90, 0x90)

    document.add_heading("Part A — CIO Investment Committee", level=1)

    letter = section_by_id(view, "cio_letter") or {}
    document.add_heading(str(letter.get("title") or "CIO Letter"), level=2)
    if letter.get("stance"):
        document.add_paragraph(f"Stance: {letter['stance']}")
    if letter.get("risk_posture"):
        document.add_paragraph(f"Risk posture: {letter['risk_posture']}")
    if letter.get("priorities"):
        document.add_paragraph("Priorities:").runs[0].bold = True
        for item in letter["priorities"]:
            document.add_paragraph(str(item), style="List Bullet")
    if letter.get("what_not_to_do"):
        document.add_paragraph("Guardrails (what not to do):").runs[0].bold = True
        for item in letter["what_not_to_do"]:
            document.add_paragraph(str(item), style="List Bullet")

    for sid in (
        "decisions_now", "capital_plan", "portfolio_posture",
        "opportunity_funnel", "counter_thesis",
        "portfolio_book", "accounts", "allocation", "performance", "coverage",
        "disclosure",
    ):
        sec = section_by_id(view, sid)
        if not sec:
            continue
        if sid == "portfolio_book":
            document.add_heading("Part B — Portfolio Book", level=1)
        document.add_heading(str(sec.get("title") or sid), level=2)
        kind = sec.get("kind")
        if kind == "table":
            rows = sec.get("rows") or []
            if rows:
                _table(list(sec.get("headers") or []), rows)
            else:
                document.add_paragraph(str(sec.get("empty_message") or "—"))
        elif kind == "kv":
            _table(["Metric", "Value"], list(sec.get("rows") or []))
            st = sec.get("sector_table")
            if st and st.get("rows"):
                document.add_paragraph("Sector posture:").runs[0].bold = True
                _table(list(st.get("headers") or []), st["rows"])
            if sec.get("unavailable"):
                document.add_paragraph("Unavailable fields:").runs[0].bold = True
                for f in sec["unavailable"][:20]:
                    document.add_paragraph(str(f), style="List Bullet")
        elif kind == "funnel":
            for key, title in (
                ("sector_opportunities", "Sector opportunities"),
                ("research_gaps", "Research gaps"),
            ):
                items = sec.get(key) or []
                if not items:
                    continue
                document.add_paragraph(f"{title}:").runs[0].bold = True
                for it in items[:8]:
                    if isinstance(it, dict):
                        text = (
                            f"{it.get('sector') or it.get('symbol') or '—'} "
                            f"({it.get('state') or '—'}): {it.get('recommendation') or ''}"
                        )
                    else:
                        text = str(it)
                    document.add_paragraph(text.strip(), style="List Bullet")
        elif kind == "list":
            if sec.get("highest_impact_unknowns"):
                document.add_paragraph("Highest-impact unknowns:").runs[0].bold = True
                for u in sec["highest_impact_unknowns"]:
                    document.add_paragraph(str(u), style="List Bullet")
        elif kind == "prose":
            document.add_paragraph(str(sec.get("text") or ""))

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(out))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# PDF
# ─────────────────────────────────────────────────────────────────────────────

def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def has_pdf_renderer() -> bool:
    for cmd in ("weasyprint", "wkhtmltopdf", "chromium", "chromium-browser", "google-chrome"):
        if _which(cmd):
            return True
    return False


def render_pdf_from_html(html: str, out: Path) -> Path:
    """Render HTML to PDF via the first available engine."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    html_path = out.with_suffix(".print.html")
    html_path.write_text(html, encoding="utf-8")

    # 1) weasyprint CLI
    if _which("weasyprint"):
        r = subprocess.run(
            ["weasyprint", str(html_path), str(out)],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return out

    # 2) wkhtmltopdf
    if _which("wkhtmltopdf"):
        r = subprocess.run(
            ["wkhtmltopdf", "--quiet", str(html_path), str(out)],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return out

    # 3) Chromium / Chrome headless
    for browser in ("chromium", "chromium-browser", "google-chrome"):
        bin_path = _which(browser)
        if not bin_path:
            continue
        r = subprocess.run(
            [
                bin_path, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                f"--print-to-pdf={out}", str(html_path),
            ],
            capture_output=True, text=True, timeout=120,
        )
        if out.exists() and out.stat().st_size > 0:
            return out

    raise RuntimeError("No PDF renderer available (weasyprint/wkhtmltopdf/chromium)")


# ─────────────────────────────────────────────────────────────────────────────
# Bundle export (one snapshot → all formats)
# ─────────────────────────────────────────────────────────────────────────────

def export_report_formats(
    model: dict[str, Any],
    out_dir: Path | str,
    *,
    basename: str = "cio_institutional_report_v2",
    write_docx: bool = True,
    write_pdf: bool = True,
) -> dict[str, Any]:
    """Export HTML + DOCX + PDF + JSON from a single model snapshot.

    Returns paths, facts_fingerprint, and per-format status. Formats that cannot
    be produced are recorded with errors; they never invent alternate facts.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Strip heavy embedded HTML before projecting view (rebuilt from view)
    model_core = {k: v for k, v in (model or {}).items() if k != "html"}
    view = build_report_view(model_core)
    html = render_html_from_view(view)

    # Attach presentation artifacts back onto a clean model copy
    model_out = dict(model_core)
    model_out["view"] = view
    model_out["html"] = html
    model_out["architecture_version"] = REPORT_ARCHITECTURE_VERSION
    model_out["facts_fingerprint"] = view["facts_fingerprint"]
    # Normalize allocation onto part_b for any downstream consumer
    pb = dict(model_out.get("part_b") or {})
    pb["allocation"] = view["facts"].get("allocation_usd") or pb.get("allocation") or {}
    pb["allocation_weight_pct"] = view["facts"].get("allocation_weight_pct") or {}
    model_out["part_b"] = pb

    paths: dict[str, Optional[str]] = {}
    errors: dict[str, str] = {}

    model_path = out_dir / f"{basename}.model.json"
    model_path.write_text(json.dumps(model_out, indent=2, default=str), encoding="utf-8")
    paths["model_json"] = str(model_path)

    view_path = out_dir / f"{basename}.view.json"
    view_path.write_text(json.dumps(view, indent=2, default=str), encoding="utf-8")
    paths["view_json"] = str(view_path)

    html_path = out_dir / f"{basename}.html"
    html_path.write_text(html, encoding="utf-8")
    paths["html"] = str(html_path)

    if write_docx:
        docx_path = out_dir / f"{basename}.docx"
        try:
            render_docx_from_view(view, docx_path)
            paths["docx"] = str(docx_path)
        except Exception as exc:
            errors["docx"] = str(exc)[:200]
            paths["docx"] = None

    if write_pdf:
        pdf_path = out_dir / f"{basename}.pdf"
        try:
            render_pdf_from_html(html, pdf_path)
            paths["pdf"] = str(pdf_path)
        except Exception as exc:
            errors["pdf"] = str(exc)[:200]
            paths["pdf"] = None

    parity = {
        "architecture_version": REPORT_ARCHITECTURE_VERSION,
        "facts_fingerprint": view["facts_fingerprint"],
        "section_ids": view.get("section_ids"),
        "formats": {k: bool(v) for k, v in paths.items()},
        "errors": errors,
        "unit_guards": {
            "allocation_weights_le_100": all(
                abs(float(v)) <= 100.01
                for v in (view["facts"].get("allocation_weight_pct") or {}).values()
                if v is not None
            ),
            "decision_count": len(view["facts"].get("decisions") or []),
            "decision_symbols_unique": len(view["facts"].get("decisions") or [])
                == len({d.get("symbol") for d in (view["facts"].get("decisions") or [])}),
        },
    }
    parity_path = out_dir / f"{basename}.parity.json"
    parity_path.write_text(json.dumps(parity, indent=2), encoding="utf-8")
    paths["parity_json"] = str(parity_path)

    return {
        "ok": not errors.get("docx") or paths.get("html"),  # html is required minimum
        "out_dir": str(out_dir),
        "paths": paths,
        "errors": errors,
        "facts_fingerprint": view["facts_fingerprint"],
        "architecture_version": REPORT_ARCHITECTURE_VERSION,
        "parity": parity,
        "view": view,
        "model": model_out,
    }

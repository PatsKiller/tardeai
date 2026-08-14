# PHASE 4 CLOSEOUT — One Reporting Architecture

**UTC:** 2026-08-14  
**Branch:** `wt/cio-phase1-notify`  
**Versions:** `report_v2_1.1.0` · `report_arch_1.0.0`  
**Authority:** `READ_ONLY_ADVISORY` unchanged  

## Goal

> Eliminate the parallel simplistic DOCX implementation. One canonical report
> model feeds one shared visualization/data layer, then HTML, PDF, DOCX and
> Command Center. No format gets a different set of facts or calculations.

## Architecture

```
build_report_v2()                 # canonical model (facts)
        │
build_report_view(model)          # shared presentation view
        │                         #  - normalize allocation USD + weight %
        │                         #  - sections[] for every surface
        │                         #  - facts_fingerprint
        │
   ┌────┴──────┬──────────┬────────────────┐
 HTML        DOCX       PDF         Command Center slice
 (render_html_from_view / render_docx_from_view / render_pdf_from_html)
```

| Layer | Module | Role |
| --- | --- | --- |
| Model | `scripts/lib/cio_report_v2.py` | Part A/B, coverage, manifest, checkpoint |
| View | `scripts/lib/cio_report_view.py` | **NEW** — single fact surface + sections |
| Render | `scripts/lib/cio_report_render.py` | **NEW** — HTML/DOCX/PDF + `export_report_formats` |
| CLI | `scripts/render_cio_report_files.py` | Thin exporter (all formats from one snapshot) |

## Guarantees

1. **One fingerprint** — `facts_fingerprint` hashes numeric/operator facts; HTML embeds the short form; parity JSON records it.
2. **No $ as %** — allocation always carries `allocation_usd` + `allocation_weight_pct` on the model and view.
3. **No format-local math** — DOCX no longer re-derives tables from raw part_a/part_b with divergent formatters.
4. **CC slice** — `view.command_center` exposes the same decisions + capital dollars.
5. **Phase 2/3 preserved** — earmark fields on capital plan; professional stances; pseudo-sectors filtered.

## Export

```bash
python scripts/render_cio_report_files.py /tmp/cio_report_v2_model.json exports/
```

Produces (when tools available):

| Artifact | Notes |
| --- | --- |
| `*.model.json` | Full model + view + html |
| `*.view.json` | Shared presentation view |
| `*.html` | Always |
| `*.docx` | When `python-docx` installed |
| `*.pdf` | When chromium/weasyprint/wkhtmltopdf present |
| `*.parity.json` | Fingerprint + unit guards |

## Tests

```
tests/test_cio_report_architecture.py   8 passed
tests/test_cio_report_v2.py             (compat) passed
related suite                           100 passed
```

## Non-goals (later)

- Phase 5 institutional visual polish / full chart suite  
- Phase 6 analytical completeness  
- Phase 7 production pipeline stamping / immutable retention  

## Safety

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## SECRETS PRINTED: 0  
## FINANCIAL AUTHORITY CHANGED: NO  

## Next phase allowed

Phase 5 — restore institutional visual quality (cover, pagination, charts).

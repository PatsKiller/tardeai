# PHASES 8–9 — Live report path + plan/report decision parity

**UTC:** 2026-08-14  
**Branch:** `wt/cio-v4-phases-3-21`  
**Authority:** `READ_ONLY_ADVISORY` unchanged  
**Version:** `live_report_1.0.0`

## Goal

1. Live report generation uses the **live** capital plan / holdings, not a
   synthetic $100k book.
2. HTML is required. PDF and DOCX are required for *production* acceptance.
   Renderer detection is honest: missing weasyprint / chromium / wkhtmltopdf
   is a clear FAIL (`pdf=missing`), never a faked PASS.
3. Decision identity on the capital plan and the report model must match:
   `decision_id`, `symbol`, `recommended_delta_usd`, `stance`.

## Why

CIO Acceptance v4 gates G10–G12 fail a synthetic/toy report even when HTML
exists. A dry path that silently built a $100k book (or claimed PDF `ok`
without a renderer) would launder a FAIL into a PASS. Phases 8–9 close that
gap without changing `run_cio_acceptance.py` scoring.

## Live source order

1. `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state/holdings.json`
   if present
2. Else this repo's `data/portfolios/state/holdings.json`
3. Else **refuse** — no $100k fallback

A document is *holdings-shaped* when it carries a `holdings` (or `positions`)
list of rows with `symbol` / `is_cash` plus a value field, or
`portfolio_totals.total_value` plus a `holdings` list. Shape, not dollar
amount, decides `synthetic`. Explicit `synthetic` / `toy` markers win.

## Pipeline

```
live holdings.json
        │
build_capital_plan_from_sources   # live book dollars
        │
build_report_v2                   # Part A/B + coverage + manifest
        │
detect_renderers()                # honest
        │
   ┌────┴─────────┬──────────────┐
 HTML (always)   DOCX            PDF
                 if python-docx  if weasyprint / chromium / wkhtmltopdf
```

| Status | Meaning |
| --- | --- |
| `ok` | File written, size > 0 |
| `missing` | Engine/library not present — **not** `ok=true` |
| `error` | Engine present but write failed (DOCX must not do this when python-docx is installed) |
| `refused` | Input was a synthetic/toy book |

Playwright's cached Chromium is **not** counted. That would fake production PDF
readiness.

## CLI

```bash
python scripts/render_cio_live_report.py
python scripts/render_cio_live_report.py --out data/audit/cio_live_report_dry/
python scripts/render_cio_live_report.py --no-db
```

Prints JSON:

```json
{
  "html": ".../cio_live_report.html",
  "pdf": null,
  "docx": ".../cio_live_report.docx",
  "source_sha": "<git HEAD>",
  "synthetic": false,
  "live": true
}
```

Evidence lands in `data/audit/cio_live_report_dry/` (HTML, DOCX when
python-docx is present, PDF only when a renderer exists, plus
`*.model.json`, `*.capital_plan.json`, `*.render_status.json`).

`--source live` on `scripts/render_cio_report_files.py` now uses the same
live builder (`assemble_live_model` → `build_report_from_live_sources`).

## Decision parity

`compare_plan_report_decisions(capital_plan, report_model)` compares every
published report decision against `capital_plan.position_decisions` on:

- `decision_id`
- `symbol`
- `recommended_delta_usd` (tolerance $0.02)
- `stance` / `stance_code`

Matching surfaces → `ok: true`. A delta mismatch → `ok: false`. Immaterial
plan-only HOLD rows that the report omits are not mismatches.

## Tests

`tests/test_cio_live_report_parity.py` (dry, no network):

| Case | Expect |
| --- | --- |
| Holdings-shaped fixture passed to `render_live_report` | `synthetic is False` |
| Missing PDF renderer | `formats.pdf.status == "missing"` and `ok is not True` |
| python-docx present | DOCX file created, `status == "ok"` |
| Matching plan / report surfaces | parity `ok` |
| Delta mismatch | parity fails |
| Bare `{portfolio_value: 100000}` | refused, `synthetic is True` |

Wired into `scripts/run_cio_hardening_ci.py` as `live_report_parity`.

## Acceptance scoring (unchanged)

`scripts/run_cio_acceptance.py` / `eval_g10_g12_report_formats` still **FAIL**
G11 when PDF is missing and G12 when DOCX is missing. This phase does **not**
award PDF PASS because a dry HTML path exists.

## Files

| File | Role |
| --- | --- |
| `scripts/lib/cio_live_report.py` | Live loaders, renderer, parity helper |
| `scripts/lib/cio_report_v2.py` | `build_report_from_live_sources` wrapper |
| `scripts/lib/cio_report_render.py` | `detect_renderers`, `has_docx_library`, honest PDF probe |
| `scripts/lib/cio_report_view.py` | `decision_id` on view facts |
| `scripts/render_cio_live_report.py` | Dry/live CLI + evidence writer |
| `scripts/render_cio_report_files.py` | `--source live` uses live builder |
| `tests/test_cio_live_report_parity.py` | Dry tests |

## Host truth (this environment)

Recorded when the dry path was run on this host
(`source_sha` `9783faf1c1e8ef89a52d5e1e6d4e676669a776af`,
`portfolio_value_usd` **1,282,826.92**, `synthetic: false`,
`plan_report_parity: true`, `production_formats_ok: false`):

| Engine | Present? |
| --- | --- |
| weasyprint CLI | no |
| weasyprint Python | no |
| wkhtmltopdf | no |
| chromium / google-chrome on PATH | no |
| python-docx (project venv) | yes (1.2.0) |
| Playwright cached Chromium | present under `~/.cache/ms-playwright` — **not used**, not a production renderer |

**PDF is not generable on this host** via the accepted engines. The dry path
must report `pdf=missing` / `pdf: null`. DOCX is generable when tests/CLI run
under the project venv.

## Safety

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## SECRETS PRINTED: 0  
## FINANCIAL AUTHORITY CHANGED: NO  

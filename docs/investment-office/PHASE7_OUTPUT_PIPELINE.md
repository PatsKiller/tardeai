# PHASE 7 CLOSEOUT — Output Pipeline (HTML / PDF / DOCX + Immutable Manifest)

**UTC:** 2026-08-14  
**Branch:** `wt/cio-phase1-notify`  
**Versions:** `report_v2_1.4.0` · `pipeline_1.0.0`  
**Authority:** `READ_ONLY_ADVISORY` unchanged  

## Goal

Make report generation **reproducible and truthful**: one model snapshot, shared
view, multi-format render, immutable instance manifest, and cross-format key
value parity.

## Canonical CLI

```bash
python scripts/render_cio_report_files.py \
  --source live \
  --formats html,pdf,docx \
  --out exports/

python scripts/render_cio_report_files.py \
  --source file \
  --model /tmp/cio_report_v2_model.json \
  --formats html,docx \
  --out /tmp/report_out \
  --basename cio_institutional_report_v2
```

Legacy positional still works: `python scripts/render_cio_report_files.py [model.json] [out_dir]`

| Flag | Meaning |
| --- | --- |
| `--source live\|file` | Assemble from holdings/DB or load model JSON |
| `--formats` | `html,pdf,docx` (any subset) |
| `--out` | Output directory |
| `--basename` | File prefix |
| `--report-id` | Optional fixed instance id |

## Artifacts per run

| File | Role |
| --- | --- |
| `*.html` | Primary print surface (charts as SVG) |
| `*.pdf` | HTML → Chromium/weasyprint/wkhtmltopdf when available |
| `*.docx` | Same view; charts embedded as PNG when converter present |
| `*.model.json` | Full model + view + charts + instance |
| `*.view.json` | Shared presentation view |
| `*.parity.json` | Key-value parity + unit guards |
| `*.instance_manifest.json` | **Immutable** report instance record |
| `*.claims.json` | Files created + sha256 (CLI claims == disk) |
| `*_charts/*.svg` | Chart suite files |

## Instance manifest fields

`report_id`, `report_version`, `generated_at`, `as_of`, `source_sha`,
`input_hashes`, `facts_fingerprint`, `capital_plan_digest`, `decision_ids`,
`chart_dataset_hashes`, `output_files`, `output_sha256`, `page_counts`,
`source_traceability_pct`, `quality_flags`, `key_values`, `instance_hash`,
`immutable: true`.

## Cross-format parity keys

portfolio total · cash · cash % · recommended deploy · post-plan cash ·  
top position · top decisions · YTD · CAGR · benchmark · max drawdown ·  
facts fingerprint  

Canonical source = shared **view facts**. HTML/DOCX are checked against it.

## Exit gate

| Gate | Meaning |
| --- | --- |
| CLI_CLAIMS_EQ_FILES_CREATED | claims.json paths exist on disk |
| HTML_PDF_DOCX_KEY_VALUE_PARITY | hard mismatches = 0 vs view |
| MANIFEST_HASHES | instance hash + file sha256 present |
| PDF_PAGE_COUNT_GT_0 | when PDF produced |
| DOCX_PAGE_COUNT_GT_0 | when DOCX produced |
| CHARTS_EMBEDDED_IN_PDF | PDF path uses HTML (SVG charts) |
| CHARTS_EMBEDDED_IN_DOCX | images and/or chart inventory present |

PDF/DOCX may be environment-optional; HTML + parity are required for CLI success.

## Modules

| File | Role |
| --- | --- |
| `scripts/lib/cio_report_pipeline.py` | **NEW** parity extractors, instance manifest, exit gate |
| `scripts/lib/cio_report_render.py` | `export_report_formats` emits manifest/claims |
| `scripts/render_cio_report_files.py` | Canonical CLI + live assemble |
| `tests/test_cio_report_pipeline.py` | **NEW** |

## Tests

```
tests/test_cio_report_pipeline.py   7 passed
with analytics/charts/architecture/v2 suite
```

## Safety

## REAL TELEGRAM SENDS: 0  
## BROKER CALLS: 0  
## SECRETS PRINTED: 0  
## FINANCIAL AUTHORITY CHANGED: NO  

## Next phase allowed

Phase 8 — Alex / Command Center / report consistency.

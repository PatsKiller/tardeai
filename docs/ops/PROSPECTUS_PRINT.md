# Ticker Prospectus — PDF and Word that look like the HTML report

Operator 2026-10-27: "the HTML prospectus looks great. The PDF and the Word document doesn't. … add whatever plugins …
so the Word document and the PDF look identical." Code: `scripts/lib/prospectus/print_render.py` (renders, fallbacks,
DOCX post-processing), `print_worker.py` (the headless Chromium process), hook in `render.render_all`; check
`scripts/prospectus_print_fidelity.py`; tests `tests/test_prospectus_print_render_20261027.py` (CI gate
`prospectus_print_20261027`); settings `config/prospectus_print.json` (own file, so it never collides with `config/prospectus.json` edits).

No new dependency: Playwright (`requirements.txt`, its Chromium under `~/.cache/ms-playwright`), LibreOffice
(`soffice`), python-docx, and for the check only `pdftoppm` (poppler) and Pillow.

## One report, three formats

All three come from `render.html(doc)`, the same presentation model and order the reader sees. The downloads print no
citations: footnote numbers, `[F7]` fact ids, `data-fact-id` attributes, per-section "Sources" and the Sources
appendix are stripped (`print_render.strip_citations`), so a later change that removes citations from the HTML
composes with this one.

| Format | How | Look |
|---|---|---|
| HTML | `render.html` (unchanged) | dark + light, inline SVG charts |
| PDF | Chromium prints the light-theme HTML with `PRINT_CSS` | Letter (or A4), same cards, colours, SVG charts; no split charts / KPI rows / table rows; table headers repeat on each page; headings never end a page; running header (symbol · name, "Prospectus · version YYYY-MM-DD") and footer (scope, generated time, "advisory only", page x / y) |
| DOCX | `word_html` (same HTML, LibreOffice-shaped: literal light-theme colours, sections as shaded one-cell tables, KPI chips as a shaded table, charts as PNGs that Chromium rasterised from the same SVGs at 2x, embedded as data URIs) → `soffice --headless --infilter="HTML (StarWriter)" --convert-to docx` → `postprocess_docx` | editable Word: real headings, tables and pictures; margins and paper match the PDF; header/footer with PAGE / NUMPAGES fields; repeated table header rows, rows that do not split, headings and chart captions kept with the next paragraph; one font (Calibri, flagged as a sans face so LibreOffice and phone viewers substitute a sans, not a serif) |

## Safety and performance

* Build job only: `pipeline.persist_doc` → `render.render_all`. The API serves the stored files and never renders.
* One render at a time on the host (`flock` on `$TMPDIR/prospectus_print.lock`, wait `lock_wait_s`, then fallback).
* Chromium runs in its own process (`print_worker.py`) and process group, killed at `chromium_timeout_s`; LibreOffice
  likewise at `soffice_timeout_s`, with a throwaway profile (`-env:UserInstallation`) and `HOME` inside the temp dir.
* The print page has JavaScript disabled, the context is offline and every request is aborted (`route("**/*")`):
  the page is self-contained (inline CSS, inline SVG, data: images). Playwright launches its bundled headless shell
  without the setuid sandbox; only our own static HTML is ever parsed.
* A redirected `HOME` (sandboxed lane, pytest) still finds the browsers: `browser_env()` points
  `PLAYWRIGHT_BROWSERS_PATH` at the account's real cache.
* Measured on ms01 (2026-10-27): ~4 s per report for PDF + chart PNGs + DOCX.

## Fallbacks

Each format falls back on its own and the reason is logged (`prospectus.print` logger, warning):

| Reason | PDF | DOCX |
|---|---|---|
| `print.enabled` false, lock busy, python playwright missing, Chromium error or timeout | WeasyPrint (`render.pdf`) | python-docx (`render.docx`) |
| Chromium ok, no `soffice`, LibreOffice error/timeout, DOCX without its chart images | Chromium | python-docx |

A fallback never fails the stored report; a missing renderer leaves that one format out, as before.

## Fidelity check

```
TMPDIR=$HOME/.cache/agent-tmp/prospectus-print \
  .venv/bin/python scripts/prospectus_print_fidelity.py --out OUT_DIR [REPORT.json ...]
```

Without arguments it uses the public synthetic fixture. For each report it renders the HTML (full-page screenshot), the
PDF and the DOCX (→ PDF via LibreOffice) and the previous renderers as "before", then scores the colour palette of
HTML vs each format and PDF page i vs DOCX page i (blurred, downscaled grayscale), threshold 0.85, and writes
`<SYM>-overview.png` (HTML | PDF before | PDF after | Word before | Word after), `<SYM>-pages.png` (PDF page | Word
page) and `fidelity.json`. Real reports: copy `prospectus.json` into a temp dir and write the images to the private
state root only (the repository is public).

Proof 2026-10-27 (one stock, one fund, temp copies; images in persistent-state
`coordination/handoffs/prospectus-20261026/shots/print/`):

| Report | Palette HTML vs PDF (before → after) | HTML vs Word (before → after) | PDF vs Word pages (mean / min) |
|---|---|---|---|
| stock | 0.843 → 0.910 | 0.664 → 0.885 | 0.968 / 0.919 |
| fund | 0.877 → 0.911 | 0.522 → 0.884 | 0.952 / 0.911 |
| synthetic fixture | 0.900 → 0.902 | 0.528 → 0.887 | 0.972 / 0.966 |

Known limit: markdown pipe tables inside section prose print as text in all three formats (the HTML renderer does
not parse them); that is an HTML change, out of scope here.

READ_ONLY_ADVISORY: rendering only; nothing here sizes, orders, stops or weights (MBI_BEHAVIOR=0).

# Reporting & Prospectus Generation Module

Status:      ACTIVE
as_of:       2026-06-24T12:44:46-04:00
Measured at: efcc51365 / not measured

Trade AI v12 produces analyst-firm quality reports from synthesized intelligence (Layer 4, Hermes, news, ensemble validation, portfolio state, health agent, journal).

## Architecture

```
analyst_report_builder.py   # Compose report JSON from data sources
report_synthesis.py         # v3 actionable sections (intelligence_view, narrative callouts)
report_narrative.py         # Executive callouts, agent synthesis helpers
report_visuals.py           # Chart generation (Plotly → PNG)
report_export.py            # Premium DOCX + PDF (KPI strip, callouts, 3-col agent table)
report_lineage.py           # History archive, canonical latest paths, continuity deltas
reporting_engine.py         # Orchestration, registry, eligibility, batch, Grok editorial
```

Symbol holding/watchlist reports use **schema v3.0** (`meta.version: "3.0"`). Legacy section ids (`recommendation`, `fundamental_news`, `agent_synthesis`, etc.) still work as aliases.

**Output:** `data/portfolios/reports/analyst/`
**Registry:** `data/portfolios/reports/analyst/registry.json`
**Prospectus batch logs:** `data/portfolios/reports/analyst/prospectus/batch_*.json`

### Canonical living-doc paths

| Report type | Stable files |
|-------------|--------------|
| `symbol_holding` | `prospectus_{SYMBOL}_latest.{json,docx,pdf}` |
| `symbol_watchlist` | `watchlist_{SYMBOL}_latest.{json,docx,pdf}` |

Held symbols prefer **holding** links in the UI; watchlist-only names use **watchlist** paths.

## Report Types

| Type | Builder | Use case |
|------|---------|----------|
| `symbol_holding` | `build_symbol_report` | Portfolio holding prospectus |
| `symbol_watchlist` | `build_symbol_report` | Watchlist item prospectus |
| `symbol_custom` | `build_symbol_report` | Custom instrument |
| `sector_theme` | `build_sector_report` | Sector / theme deep dive |
| `daily_digest` | `build_daily_digest` | Daily intelligence + Action Queue |
| `weekly_review` | `build_weekly_review` | Weekly performance + Action Queue |
| `intelligence_deep` | `build_intelligence_deep` | Topic deep dive |
| `event_driven` | `build_event_driven` | Stop hits, thesis invalidations |

Blank symbol/sector filters produce **aggregate ALL** reports (`meta.scope: "all"`).

## Report Link Eligibility (Portfolio + Watchlist UI)

Command Center v3 shows inline **PROSPECTUS / PDF / Word** links only when a verified file exists on disk (no phantom URLs).

### Holdings — all non-cash positions

Every portfolio holding above `$0` market value gets report links. Generate-on-demand fallback: **📄 Generate report →** opens `/v3/reports`.

Backend: `eligible_holding_symbols()`, `holdingReportEligible()` (frontend).

### Watchlist — manual OR buy-side CIO view

Report links when **any** of:

| Rule | Sources / fields |
|------|------------------|
| **Manually added** | `source` ∈ `{operator, personal_watchlist}` OR `origin_system = operator` |
| **Buy-side CIO** | BUY, STRONG BUY, ADD, ACCUMULATE, WAIT FOR PULLBACK in `latest_recommendation`, `holdings_llm_action`, `synthesis_recommendation`, `grok_recommendation`, or `chatgpt_recommendation` |

Symbols already held in portfolio are excluded from watchlist eligibility (they use holding prospectus instead).

Backend: `watchlist_report_eligible()`, `eligible_watchlist_symbols()` — manual rows prioritized first, then buy-side (default limit 120–200).

### Verified links API

`report_links_map()` and `verified_export_urls()` return DOCX/PDF only when files exist. Holding registry row preferred over watchlist for the same symbol.

## Ad-hoc Generation

### CLI

```bash
# Single holding prospectus with Grok polish
.venv/bin/python scripts/reporting_engine.py generate --symbol RKLB --type symbol_holding --grok

# Batch all portfolio holdings (skips unchanged fingerprints)
.venv/bin/python scripts/reporting_engine.py batch-holdings --grok

# Batch manual + buy-side watchlist names (not held)
.venv/bin/python scripts/reporting_engine.py batch-watchlist --grok --limit 200

# Force full refresh
.venv/bin/python scripts/reporting_engine.py batch-holdings --force --grok
.venv/bin/python scripts/reporting_engine.py batch-watchlist --force --grok

# Autonomous holdings + watchlist in one pass
.venv/bin/python scripts/reporting_engine.py autonomous --mode weekly

# Registry manifest
.venv/bin/python scripts/reporting_engine.py registry --type symbol_holding
.venv/bin/python scripts/reporting_engine.py registry --type symbol_watchlist
```

### API (Command Center v3)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v2/reports/analyst/preview` | GET | Live preview JSON |
| `/api/v2/reports/analyst/export` | POST | Export preview to DOCX/PDF |
| `/api/v2/reports/analyst/generate` | POST | Build + export + register |
| `/api/v2/reports/analyst/registry` | GET | Generated document manifest |
| `/api/v2/reports/analyst/eligible` | GET | Holdings + watchlist due for refresh |
| `/api/v2/reports/analyst/links` | GET | Verified symbol → DOCX/PDF map |
| `/api/v2/reports/analyst/validate` | GET | Coverage: eligible vs on-disk links |

**Batch holdings body:**
```json
{ "mode": "batch_holdings", "grok_edit": true, "force": false, "limit": 120 }
```

**Batch watchlist body:**
```json
{ "mode": "batch_watchlist", "grok_edit": true, "force": false, "limit": 200 }
```

**Single prospectus body:**
```json
{ "type": "symbol_holding", "symbol": "RKLB", "grok_edit": true }
```

**Validate coverage (example response):**
```json
{
  "holdings_eligible": 33,
  "holdings_with_links": 33,
  "holdings_missing": [],
  "watchlist_eligible": 200,
  "watchlist_with_links": 200,
  "watchlist_missing": []
}
```

## Automation (Cron) — Autonomous Lineage Pipeline

| Schedule | Script | Mode | Behavior |
|----------|--------|------|----------|
| Mon–Fri 7:30 AM | `generate_analyst_daily_digest.py` | — | Daily digest DOCX |
| Mon–Fri 7:35 AM | `generate_analyst_reports_autonomous.py` | `daily` | Holdings + watchlist when **fingerprint** changes |
| Sun 21:15 | `generate_analyst_reports_autonomous.py` | `weekly` | Same fingerprint gate (no age-only refresh) |
| Sun 21:00 | `generate_analyst_weekly_review.py` | — | Weekly review DOCX/PDF |

`run_autonomous_cycle()` runs **both** `generate_holding_prospectus_batch` and `generate_watchlist_prospectus_batch` (default `--limit 200` each).

### Refresh triggers (`prospectus_needs_refresh`)

| Reason | When |
|--------|------|
| `never_generated` | New holding or eligible watchlist name — first report auto-created on next cron run |
| `fingerprint_changed` | Price, synthesis, ensemble, technicals, P&L, or proposal context changed |
| `stale_Nd` | Optional age gate when `stale_days` set (batch-holdings CLI only) |
| `forced` / `full` | Manual `--force` or `--mode full` |

Fingerprint hash inputs: recommendation, price, day change, synthesis timestamp, portfolio %, RSI, ensemble score/decision, proposal status (`symbol_fingerprint()` in `reporting_engine.py`).

If fingerprint matches, batch **skips** — no new document, no Grok re-run.

```bash
# Dry-run — see which symbols would refresh
.venv/bin/python scripts/generate_analyst_reports_autonomous.py --mode daily --dry-run

# Manual autonomous runs
.venv/bin/python scripts/generate_analyst_reports_autonomous.py --mode weekly
.venv/bin/python scripts/reporting_engine.py autonomous --mode full --force
```

### Building on prior reports

`report_lineage.py` archives every generation under `data/portfolios/reports/analyst/history/{SYMBOL}/` and maintains `history/index.json`.

Each update (only when fingerprint changes):

1. Snapshots the current `prospectus_{SYMBOL}_latest.json` (or `watchlist_*`) to `history/{SYMBOL}/snapshot_*.json`.
2. Loads that living file as prior context for continuity synthesis (`report_continuity` section).
3. **Overwrites in place** `*_latest.{json,docx,pdf}` — same paths, not new files every run.
4. Upserts one registry row per symbol (`id: prospectus_{SYMBOL}` or `watchlist_{SYMBOL}`).

Registry dedupes on load; API `/registry?type=symbol_holding` returns canonical rows only.

## Grok OAuth Editorial

`apply_grok_editorial()` in `reporting_engine.py` calls `llm_lane` (Grok OAuth, free lane) to polish:

- Executive summary (2–4 sentences, institutional analyst tone)
- Action plan / recommendation stance
- Preserves executive callouts meaning

Facts are preserved; no invented data. Sections gain `grok_edited: true` and `meta.grok_editorial` records the pass.

## Claude Cloud Oversight (`report_oversight.py`)

Advisory, read-only senior-review pass that runs **after the report JSON is assembled, before export**.
Never a broker action. Pipeline:

1. **Free dual-lane sanity** — Grok (`:8645`) + ChatGPT (`:8646`) OAuth proxies each critique the
   assembled prose against a live **data packet** (ground-truth KPIs, agent panel, targets, peers,
   technicals, Hermes notes). Each returns `{fabrications, stale_or_contradictory, unsupported_claims,
   missing_required, section_grades}`. These run on **every** symbol report.
2. **Claude arbiter** (metered Anthropic lane) — receives the report + data packet + both free critiques
   and returns `{verdict: PUBLISH | PUBLISH_WITH_FIXES | BLOCK, fixes[], analyst_note, confidence_check}`.
   Model resolved from config: `REPORT_CLAUDE_MODEL` → `CLAUDE_ESCALATION_MODEL` → lane default
   (**never hardcoded**).
3. **Deterministic fix application** — the safe subset is applied: senior `analyst_note` overlay injected
   into the executive summary, per-section `oversight_flags`, and a prominent **HOLD FOR REVIEW** callout
   on `BLOCK`. The builder still governs all numeric data; the model never silently rewrites numbers.
   Result is stamped at `meta.claude_oversight = {verdict, model, ts, fixes_applied, claude_ran,
   claude_gate_reason, free_lanes[], confidence_check}`.

**Cost gate (hard).** Free lanes always run. The metered Claude lane runs only when:
- `--claude-oversight` is passed (operator / single-symbol), **or**
- `REPORT_CLAUDE_OVERSIGHT=1` **and** a trigger fires (a free lane flagged a fabrication/contradiction,
  or a monthly-cadence `BUY`/`ADD` holding).

Default **OFF** for batch (`REPORT_CLAUDE_OVERSIGHT=0`) so daily/weekly runs never meter Claude. If the
Claude lane is down it degrades to the dual free-lane verdict (`model: free_lanes_only`,
`skipped: lane_down(claude)`) and **never blocks** the report.

```
# Operator single-symbol with Claude arbiter
.venv/bin/python scripts/reporting_engine.py generate --symbol V --type symbol_holding --grok --claude-oversight
# Re-run oversight on an existing living prospectus (no rebuild)
.venv/bin/python scripts/reporting_engine.py oversight-only --symbol V --claude-oversight
```

Env: `REPORT_CLAUDE_OVERSIGHT` (default 0), `REPORT_CLAUDE_MODEL` (blank → escalation model),
`AGENT_FRESHNESS_DAYS` (default 30). Monthly Claude cron (operator adds; not auto-installed):

```
30 21 1 * * cd $PROJ && flock -n /tmp/analyst_reports_monthly_oversight.lock \
  env REPORT_CLAUDE_OVERSIGHT=1 .venv/bin/python scripts/generate_analyst_reports_autonomous.py --mode full \
  >> logs/analyst_reports_autonomous.log 2>&1
```

## RC1 — Coverage, Card Links & Refresh Cadence

**Batch tiers.** `generate_report(..., oversight=bool, engine=...)` and the holding/watchlist batches
(`generate_holding_prospectus_batch` / `generate_watchlist_prospectus_batch`) take `engine` + `oversight`
so a bulk run mixes quality: holdings render with Grok + free dual-lane oversight; watchlist can render
fast (`oversight=False`, `grok_edit=False`) with on-the-fly full generation per symbol from the card / Reports.

**Card icon-links.** `HoldingReportLinks` (Portfolio + Watchlist hubs) renders 📕 PDF · 📘 Word · ↻
regenerate icon-links + an oversight-verdict dot, with a multi-line hover tooltip (date created + relative
age, generation #, stance, cloud-oversight verdict, Grok status). Populated from `report_links_map`, which
carries `generation` / `grok_edited` / `oversight_verdict` per symbol (also stamped on the registry entry).

**Refresh cadence (cron):**

| When | Job | Behaviour |
|------|-----|-----------|
| Weekday 07:35 | `analyst_urgent_refresh.py` | Regenerates ONLY holdings whose recommendation bucket flipped vs the last report; emails operator the updated PDFs (attached). Silent otherwise. |
| Sun 20:30 / 21:15 | `generate_analyst_reports_autonomous.py --mode weekly` | Baseline full refresh — **Grok + ChatGPT free dual-lane oversight** (batch defaults; Claude gated off). |
| Day-1 21:30 | `... --mode full` (`REPORT_CLAUDE_OVERSIGHT=1`) | Monthly full refresh with the metered Claude arbiter. |
| `*/15` 06–17 wkdays | `eligible_report_payload(use_cache=False)` | Pre-warm the `/eligible` disk cache out of the request path (R0). |

`ai_oversight_audit` table logs every oversight pass (surface/symbol/verdict/model/free_lanes/payload).

## v4 Rendering Stack (sell-side design)

One section model (the `analyst_report_builder` JSON) → two renderers in `scripts/report_render.py`:

- `render_html(report)` — Jinja2 `templates/analyst_report.html.j2` + `assets/analyst_report.css`
  (cover KPI band, two-column TOC, prose-first sections with one compact KPI table, charts inlined as
  base64 data URIs, `break-inside: avoid` so a figure never splits a page).
- `render_pdf(report, path)` — **headless Chromium via Playwright** (`page.pdf`, CSS Paged Media,
  `displayHeaderFooter` running header + footer with `pageNumber`/`totalPages`).
- `render_docx(report, path)` — styled **python-docx** from the same model.

**Stack note / flag-back:** WeasyPrint and Pandoc require system libs (`libpango`, `libcairo`) installed
via `sudo apt`, which is not available passwordless in this environment. The active stack is therefore
Playwright (PDF) + python-docx (DOCX) + mplfinance (charts) — all pip/already-installed, no sudo. To use
WeasyPrint/Pandoc instead, run:

```
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 pandoc fonts-inter
.venv/bin/pip install weasyprint mplfinance jinja2
```

CLI: `generate --engine playwright|weasyprint|legacy` (default `playwright`). `legacy` = the old
python-docx hand-placement export. Real TA charts: `report_visuals.chart_technical` (mplfinance
candlestick + volume + RSI + MACD + Bollinger + SMA20/50/200 with drawn entry/stop/target/support lines).

**Oversight enforcement (v4):** `report_oversight.enforce_integrity` runs deterministically before
critique — dedupes the agent panel to one row per (agent, recommendation) and reconciles the peer-median
PE to the listed peers. After fixes are applied, `_unresolved_after_apply` re-validates; if a flagged
issue survives, the verdict is downgraded to BLOCK (a report never ships contradicting its own overlay).
`meta.claude_oversight` gains `integrity_normalizations` and `unresolved`.

## v3 Section Schema (Holdings & Watchlist)

Default prospectus sections (`PROSPECTUS_SECTIONS`):

```
header_context, executive_summary, personal_performance, report_continuity,
news_catalysts, technical_analysis, fundamental_valuation, analyst_predictions,
intelligence_view, risk_assessment, action_plan
```

Symbol reports also append `peer_comparison` and `hermes_research` when data exists.

| Section id | Purpose | Key fields |
|------------|---------|------------|
| `header_context` | Symbol, sector, personal P&L | `metrics` (entry, cost basis, accounts) |
| `executive_summary` | Actionable synthesis (+ Claude overlay) | `callouts[]`, `metrics.what_to_do_now` |
| `personal_performance` | User-specific performance | `content`, `metrics.entry_quality` |
| `report_continuity` | Delta vs last archived report; same-day/unchanged-fingerprint builds are flagged as intraday refreshes (no fabricated +0.00%) | `metrics.price_delta_pct`, `prior_call_assessment` |
| `news_catalysts` | 30–90d catalysts, entity-relevance gated | `bullets` with sentiment tags |
| `technical_analysis` | RSI, MAs, momentum | `metrics`, charts in `visuals` |
| `fundamental_valuation` | PE + **professional** rating only (never the Finviz recom) | `metrics` (street_rating, target_mean); ETF-honest YTD/yield |
| `analyst_predictions` | Wall-Street consensus: low/mean/high targets, upside, Buy/Hold/Sell split | `metrics`, `rating_distribution`, target + rating-split charts |
| `intelligence_view` | Calibration-weighted agent synthesis + Layer-4 + dual-lane (Grok/ChatGPT) consensus with the disagreement ×0.8 rule | `agents[]` (with `accuracy_pct`), narrative |
| `risk_assessment` | Thesis-validity band (computed from support/stop/target for holdings) + **realized** volatility (never the Finviz weekly-range field) | `bullets`, thesis validity chart |
| `action_plan` | Recommendation + concrete add-zone/do-not-chase/stop levels; concentration reconciled with ADD | `bullets` (sizing, stops, catalyst dates) |
| `hermes_research` | Hermes graded research; labeled web-grounded only when sources are attached | `bullets`, `metrics` |

## Extending Report Templates

### 1. Add a section

For symbol reports, prefer extending `report_synthesis.py`:

1. Add section id to `HOLDING_REPORT_SECTIONS` and implement block in `compose_symbol_sections()`.
2. Add id to `SECTION_IDS` in `analyst_report_builder.py` (for API `sections` filter).
3. Add to `PROSPECTUS_SECTIONS` if included in batch prospectus.
4. Add checkbox in `AnalystReportsPanel.tsx` `SECTION_OPTS` if user-selectable.
5. If section has `agents[]` or special tables, extend `report_export.py` DOCX/PDF renderers.

### 2. Add a visualization

In `report_visuals.py`:

1. Implement `chart_foo(symbol, ctx) -> dict` returning `{ "chart_path": "/data/...", "caption": "..." }`.
2. Append to `report["visuals"]` in the relevant builder.
3. `report_export.py` auto-embeds any visual with `chart_path` resolving under `data/portfolios/reports/analyst/charts/`.

Supported chart types today: price + technical levels, thesis validity range, sector allocation, score distribution, digest action severity, peer comparison.

### 3. Add a new report type

1. Add builder function `build_foo_report()` returning `{ meta, sections, visuals, action_items? }`.
2. Register in `build_report()` and `list_report_types()`.
3. Add API preview branch in `api_v2.py` `_reports_analyst_preview` if special query params needed.
4. Add UI tab in `AnalystReportsPanel.tsx` `REPORT_TYPES`.
5. Optional: wire `reporting_engine.generate_scheduled("foo")` for cron.

### 4. Prospectus document class

Symbol reports with `report_type.startswith("symbol_")` get `meta.document_class = "summary_prospectus"` and default sections from `PROSPECTUS_SECTIONS` in `reporting_engine.py`.

## Export Quality

- **DOCX:** KPI strip, executive callouts, 3-column agent table, embedded PNG charts, visual summary appendix.
- **PDF:** ReportLab with chart images; fallback message if chart missing.
- Charts generated at 2× DPI for print clarity.

## UI

Command Center v3:

| Surface | Component | Behavior |
|---------|-----------|----------|
| **Portfolio** | `HoldingReportLinks` on `PortfolioHub`, `DetailDrawer` | All non-cash holdings |
| **Watchlist** | `HoldingReportLinks` on `WatchlistHub` | Manual + buy-side eligible rows |
| **Reports** | `AnalystReportsPanel`, `AnalystReportViewer` | Preview, generate, batch, Grok toggle |
| **Links map** | `useAnalystReportMap` → `/api/v2/reports/analyst/links?limit=500` | Disk-verified URLs |

Hard-reload if stale bundle: `/v3/reports?_cc_reload=1`

## Tests

```bash
.venv/bin/python -m pytest tests/test_report_links.py tests/test_reporting_engine.py \
  tests/test_report_lineage.py tests/test_report_synthesis.py tests/test_analyst_report_builder.py -q
```

Coverage checks: eligibility rules, verified URL map, holdings == book count, operator-priority watchlist ordering.
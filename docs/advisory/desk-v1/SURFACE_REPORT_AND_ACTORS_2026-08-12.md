# Advisory Desk → Operators: Wiring, Telegram, and the MS-Style Report

**Date:** 2026-08-12 · **Authority:** READ_ONLY_ADVISORY · **Flag:** `ADVISORY_DESK_V1`

This document answers three operator-facing questions and records what was shipped
to close them:

1. **Where is the desk output actually used** by the CIO, wealth officer, and advisor?
2. **How do Telegram notifications go out**, and what do they tell the operator?
3. **The Morgan Stanley–style portfolio report** — what it is, what it shows, and how
   it is delivered.

---

## 1. Who consumes the Advisory Desk

The desk is a **read-only display + notification surface**. It is consumed at four seams:

| Consumer | Seam | What they get |
|---|---|---|
| **Operator (you)** | Command Center `/v3/advisory` + Telegram `/advisory` | Full verdict table, banners, synthesis, analytics, performance |
| **CIO actor (Alex)** | `scripts/lib/cio_advisory_bridge.py` → `cio_desk_synthesis.py` memo | Compact desk context: top actionable rows + analytics + performance + thesis |
| **Wealth advisor (Steph) / advisor (Morgan)** | same bridge, same memo | The same read-only verdict table surfaced inside the desk note |
| **Event-driven CIO brief** | `scripts/cio_event_brief.py` | Dollars-first push of *material* changes (verdicts, concentration, re-entry, theme gaps) |

### The bridge (`scripts/lib/cio_advisory_bridge.py`)

A deterministic, read-only module — the single seam where the desk meets the CIO
actor family:

- `advisory_desk_context()` → `ok`, `as_of`, `row_count`, `verdict_counts`, `by_class`,
  `top_actionable` (ranked actionable-first then by market value), `portfolio_analytics`,
  `performance`, `banners`, `synthesis`.
- `living_thesis_context()` → the current `desk@vN` governing thesis (stance, summary,
  risk posture, principles, linked symbols).

**Rules:** never writes to disk, never mutates state, never calls an LLM. All values are
read from the desk cache / state JSON, or labeled `DATA_UNAVAILABLE`.

### The memo wiring (`scripts/lib/cio_desk_synthesis.py`)

`collect_desk_inputs()` now includes an `advisory_desk` block, and `render_desk_note()`
emits a deterministic **"Desk verdicts (read-only)"** section listing the top actionable
rows (e.g. `SCHD TRIM`, `V TRIM`, `SPCX TRIM`, `DXCM TRIM`) alongside the existing cash,
concentration, and drawdown analysis. This is a *deterministic* addition — **no LLM
behavior was changed.**

---

## 2. Telegram notification map

All pushes are READ_ONLY. None place orders, none set stops. Two classes:

### Operator-pull (reply on command)
| Command | Effect |
|---|---|
| `/advisory` | Full desk verdict table + banners |
| `/cio` | The desk note (memo) |
| `/v3/cio` | The `desk@vN` governing thesis |
| `watch` / `promote` | Watchlist + promotion state |

### Scheduled pushes
| Producer | Schedule | What it conveys |
|---|---|---|
| `recovery_watch_daily.py` | daily 07:30 | Stopped-out detection + analyst re-entry review (recovery escalations) |
| `rotation_rebalance_digest.py` | Sunday 18:00 | Advisory-only "rotate out of X" digest + research-gap seeding |
| `cio_event_brief.py` | **new**, weekdays 07:50 | Material-change CIO brief (below) |
| `portfolio_report_ms.py` | **new**, month-day-1 07:35 | Monthly report PDF (`sendDocument`) + email summary |

### The CIO event brief (`scripts/cio_event_brief.py`)

The piece that was missing: a **single autonomous, thesis-grounded "here's what to look
at" push**. It aggregates *material* events only:

1. **Actionable desk rows** (TRIM/EXIT/ADD/RE_ENTER above the materiality floor) — dollars first.
2. **Look-through concentration breaches** (single-name above guideline).
3. **Re-entry watch** (desk RE_ENTER / closed-position recovery).
4. **Theme deployment gaps** (dry-powder candidates — research, not deploy).

**Dedupe:** a content fingerprint is persisted at `data/runtime/cio_event_brief_last.json`;
the brief is sent **only when the material content changed** (or `--force`). No LLM, no
broker action. `--dry-run` prints without sending; `--no-send` builds + fingerprints.

---

## 3. The Morgan Stanley–style report (`scripts/portfolio_report_ms.py`)

Reproduces the structure and graphics of the operator's Morgan Stanley Wealth Management
report, driven entirely by canonical Data Broker state — **no LLM narrative is invented.**

### Sections (mirrors the MS report)
1. **Cover** — brand, as-of date, governing thesis, position/account counts.
2. **Contents + Governing Thesis** + quality flags.
3. **Accounts Included** — per-account market value, weight, day change, total gain %.
4. **Investment Summary** — KPIs (total value, cash, inception, YTD, weighted P/E) + charts.
5. **Performance** — period returns with source labels, risk/attribution (CAGR, alpha,
   Sharpe, Sortino, max drawdown), benchmark, rolling alpha.
6. **Portfolio X-Ray** — weighted valuation (P/E, P/B, P/S, P/CF, coverage), sector
   look-through, top underlying holdings, concentration advisories.
7. **Change in Portfolio Value** — YTD and since-inception, beginning/ending/change.
8. **Unrealized Gain / Loss Detail** — per symbol:account from `tax_lots.json` (per-lot
   cost basis, LT/ST term), top 25 by |G/L|.
9. **Disclosures** — provenance + documented gaps (TWR, account-aggregated periods).

### Data provenance (every figure traced)
| Figure | Source |
|---|---|
| Holdings, accounts, totals, cash | `data/portfolios/state/holdings.json` |
| Per-lot cost basis + term | `data/portfolios/state/tax_lots.json` |
| Valuation multiples + sector | `data/portfolios/state/ticker_enrichment_cache.json` |
| Period returns | `data/portfolios/state/performance_history.json` |
| CAGR / alpha / Sharpe / drawdown | `data/portfolios/state/performance_attribution.json` |
| Sector/theme look-through | `config/fund_lookthrough.json` + `fund_lookthrough.py` |
| Look-through themes + advisories | `data/portfolios/state/lookthrough_themes.json` |
| Governing thesis | `data/cio/cio_theses_projection.json` (`desk@vN`) |

Where a figure is unavailable it is labeled `DATA_UNAVAILABLE` and never estimated.

### Graphics (matplotlib, MS print theme — navy/green/burgundy, white)
- Asset allocation donut
- Sector allocation (look-through) bar
- Top 10 holdings (aggregated by security) bar
- Portfolio vs benchmark (CAGR) scatter
- Period returns bar (green/red)
- **Rolling alpha vs benchmark** (advanced)
- **Theme exposure (look-through)** (advanced)

### Delivery
- **PDF** — landscape Letter via Playwright (headless Chromium).
- **Telegram** — `sendDocument` with the PDF + a caption.
- **Email** — plain-text summary + PDF path + dashboard link (via `gog gmail send`).

### CLI
```
python scripts/portfolio_report_ms.py [--ad-hoc] [--dry-run] [--no-send]
                                      [--out DIR] [--no-pdf] [--no-charts]
```

---

## 4. Scheduling (systemd user units)

| Unit | Schedule | Persistent |
|---|---|---|
| `tradeai-cio-event-brief.{timer,service}` | Mon–Fri 07:50 | yes |
| `tradeai-portfolio-report-ms.{timer,service}` | month day-1 07:35 | yes |

Both are `oneshot`, `Nice=10`, log to `logs/`, and read secrets from the same
`EnvironmentFile` drop-ins as the existing shadow session.

---

## 5. Known gaps (unchanged, surfaced in report disclosures)

- True time-weighted return (TWR) not yet tracked — CAGR is money-weighted.
- `3M`/`1Y` returns are account-aggregated and may include transfers/ACATS step-changes.
- Valuation multiples + style are direct-equity only (funds/ETFs ≈ 79% of book).

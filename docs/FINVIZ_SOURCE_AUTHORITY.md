# Finviz Source Authority & Phase 0 Reconciliation

**Status:** Phase 0 complete · 2026-07-20 · commit `cc8abd6b`
**Scope:** reconciliation and truth-correction only. No screener was added, no
screener was run, no order was submitted, no execution control was changed.

Regenerate the live state at any time:

```bash
.venv/bin/python scripts/finviz_registry_reconcile.py            # human table
.venv/bin/python scripts/finviz_registry_reconcile.py --json     # artifact
```

---

## 1. The executor of record

**`scripts/finviz_screener_runner.py` reads the `finviz_screeners` DATABASE
TABLE** (`finviz_screener_runner.py:196-198`). It does not read
`assets/screeners.yaml`.

This inverts the assumption the expansion plan was written against. The plan
treated the checked-in 18-screen YAML as the live system and
`config/candidate_sources.yaml` as drifted. The measured reality is the
opposite:

| Declaration site | Count | Actually runs? |
|---|---|---|
| `assets/screeners.yaml` | 18 definitions | **No** — 0 membership rows, ever |
| `config/candidate_sources.yaml` | 40 referenced ids | mapping layer only |
| `finviz_screeners` (DB) | 29 rows | **Yes** — all 29 have membership |

All 27 registry references that appear "orphaned" against the YAML in fact
resolve against the DB. The registry was closer to the truth than the YAML.

`assets/screeners.yaml`'s only production reader is `scripts/finviz_ingestion.py`,
which is on **no cron**. A screen added to the YAML alone is dead on arrival.
A banner now states this at the top of the file.

### Current state distribution

| State | n | Meaning |
|---|---|---|
| `ACTIVE` | 26 | in DB, mapped, running, capturing members |
| `ORPHANED` | 18 | all YAML-only definitions — never execute |
| `SHADOW` | 2 | running but unmapped (`fib_retracement_targeted`, `swing_breakout_targeted`) — no strategy consumes them |
| `BROKEN` | 1 | `speculative_catalyst` — last run 2026-07-17, stale |

---

## 2. Source hierarchy (authoritative)

### Finviz — discovery and context ONLY

Underlying universe discovery; descriptive/fundamental/technical filters;
sector and industry groups; ETF holdings; correlations; news and alert
triggers; human presets, flags, portfolios and charts.

**Finviz never makes a proposal trade-eligible.** It supplies no options-chain
data anywhere in this project today.

### Schwab — authoritative for every contract fact

Contracts, expirations, strikes, bid/ask/mid, greeks, open interest and
contract volume at the decision timestamp; contract validation; ticket
construction; position reconciliation.

Verified live during Phase 0: `options_lifecycle_engine.quote_leg()` returned an
exact-match SPY contract quote. The registry previously claimed
`provider: NOT_CONFIGURED` / `status: BLOCKED_PROVIDER_MISSING` — stale since
the Schwab chain went live. **Corrected.**

A Finviz chain must never silently substitute for a failed Schwab chain, and
quotes from different providers or timestamps must never be blended or averaged.

### Portfolio / account — internal records

Holdings, lots, committed shares, account option tiers, cash, tax state, open
option positions.

### Events — see §3, currently BROKEN

### Analyst ratings — not Finviz

The repo already guards this correctly and those guards must stay:
`report_narrative.py:357` — *"Finviz 'recom' is a technical screen, NOT an
analyst rating — never present it as 'Street rates'"*; `broker_proposal_intel.py:134`
rejects invalid Finviz recom outright. Yahoo/`analyst_consensus_history`
remains the rating of record.

### Implied volatility — no proxies

True IV rank requires an option-IV history series. `options_iv_history` holds
**230 rows / 68 symbols / 12 days** (2026-07-05 → 07-17) — far short of the
~252 sessions a percentile needs. IV rank must therefore be reported
`UNAVAILABLE`. Any realized-volatility stand-in must be labeled
`UNDERLYING VOLATILITY PROXY — NOT IV RANK`.

`covered_call_candidates` previously advertised *"Established holdings with
elevated IV rank"*. Its actual filters are `cap_midover, sh_opt_optionshort,
sh_avgvol_o1000` — no IV field, and the Finviz **stock** screener has none to
offer. **Corrected.**

---

## 3. P0 — the earnings event gate was failing OPEN

The most consequential Phase 0 finding, and a live safety defect rather than a
documentation issue.

**Chain of failure:**

1. FMP's `v3/earning_calendar` now returns **HTTP 403** — *"Legacy Endpoint ...
   only available for legacy users with valid subscriptions prior August 31,
   2025."* `FMP_API_KEY` is set (32 chars) but is not a legacy key.
2. `portfolio_options._get_earnings_dates` swallowed it: `if not resp.ok:
   return {}`, plus a bare `except: pass`.
3. `options_desk_enterprise.earnings_calendar` therefore returned `""` for
   every symbol.
4. `earnings_blackout_check` treated `""` as *no scheduled earnings* and
   returned `in_blackout: False`.

**Effect:** the earnings blackout cleared **every** symbol for
`covered_call`, `cash_secured_put`, `credit_spread` and `long_call` — the four
`BLOCKING_STRATEGIES`. The gate is wired into the live path at
`options_desk_enterprise.py:140` and `:584`, and proposals for three of those
four strategies were generated during this very session.

**Fix (same day):**

- `_get_earnings_dates` raises `EarningsProviderError` on missing key, non-OK
  HTTP, or unparseable body. It returns `{}` **only** when the provider
  answered successfully and no requested ticker reports.
- `earnings_calendar` returns an `EARNINGS_UNKNOWN` sentinel, deliberately
  distinct from `""`.
- `earnings_blackout_check` **fails closed** on `EARNINGS_UNKNOWN`, with
  `refusal_code: EARNINGS_TIMESTAMP_UNKNOWN` and `data_blocked: true`.

**Consequence — intended, not a regression:** those four strategies are
event-blocked until a working earnings provider is restored. `deep_itm_call` is
outside `BLOCKING_STRATEGIES`, so the armed paper canary is unaffected
(verified explicitly).

**Operator action required:** restore an earnings source (FMP stable tier,
Nasdaq, or Yahoo) before earnings-sensitive options strategies resume. Until
then the desk is correctly refusing rather than silently guessing.

---

## 4. Throttle coverage gap (open finding, not yet fixed)

`scripts/finviz_throttle.py` is the cross-process rate limiter that exists
because of the 2026-06-22 Finviz 429 storm, which collapsed the screener
universe and zeroed the GO tier.

**Seven** callers use it: `finviz_screener_runner`, `finviz_ingestion`,
`finviz_enrichment`, `finviz_news`, `finviz_sector_research`,
`finviz_industry_groups`, `finviz_market_movers`.

**Thirteen** bypass it entirely, including `symbol_enrichment.py`,
`portfolio_technical.py`, `catalyst_enrichment.py`, `market_context.py`,
`social_scalp_scanner.py` and `api_v2.py:26428`.
`external_market_data_ingest.py:180` additionally scrapes **non-elite**
`finviz.com` HTML.

Most are low-volume or on-demand, which is likely why no storm has recurred —
but the exposure is real and predates this work. Recommend routing all of them
through `finviz_throttle.acquire()` before adding any new Finviz load.

---

## 5. Orphaned configuration

`config/screener_schedule.yaml` is read by **no production script** — only by
`tests/test_screener_arch5_schedule_stale_remediation.py`. The run-window
definitions inside `assets/screeners.yaml` are likewise inert, since that file
never reaches the executor.

---

## 6. Status language

```
FINVIZ CAPABILITY AUDITED:              YES
FINVIZ SOURCE REGISTRY RECONCILED:      YES
CURATED OPTIONS LIST LIBRARY:           NO   (Phase 1 — not started)
CURATED DEFENSE LIST LIBRARY:           NO   (Phase 1 — not started)
FINVIZ-TO-PORTFOLIO ROUTING VERIFIED:   NO   (Phase 2)
FINVIZ-TO-CHAIN ROUTING VERIFIED:       NO   (Phase 2)
NEW OPTION STRUCTURES OPERATIONALLY VERIFIED: NO  (none built)
NEW OPTION STRUCTURES OUTCOME VALIDATED:      NO
LIVE EXECUTION ELIGIBLE:                YES  (platform-level, unchanged)
NEW FINVIZ LIST EXECUTION AUTHORITY:    NO
AUTONOMOUS BROKER SUBMISSION:           NO
EARNINGS EVENT GATE:                    FAIL-CLOSED (provider dead — operator action required)
```

---

## 7. Why Phase 1 has not started

Phase 1 would add `OPT-CC-QUALITY-OVERWRITE` and the rest of the curated
library. Two Phase 0 findings change its design and make starting it
prematurely a mistake:

1. **New lists must be registered in the `finviz_screeners` DB table**, not
   only in `assets/screeners.yaml`. Writing them to the YAML — which is what
   the plan's Layer A implies — would produce 14 more `ORPHANED` rows that
   never run and silently generate nothing.
2. **The covered-call families the library targets are exactly the four
   strategies now event-blocked.** `OPT-CC-QUALITY-OVERWRITE`,
   `OPT-CC-RICH-PREMIUM`, `OPT-CSP-QUALITY-PULLBACK` and the bull-put list all
   route into `BLOCKING_STRATEGIES`. Until an earnings provider is restored,
   every candidate they produce would correctly refuse with
   `EARNINGS_TIMESTAMP_UNKNOWN` — six weeks of shadow captures would accrue
   zero chain-qualified observations, and the activation standard could never
   be met.

The ordering that follows from the evidence: restore the earnings provider,
then build Phase 1 against the DB-backed canonical definition system.

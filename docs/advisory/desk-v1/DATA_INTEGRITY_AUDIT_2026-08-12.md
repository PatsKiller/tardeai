# Advisory Desk & CIO Desk — Data Integrity Audit (2026-08-12)

**Trigger:** an operator found that the Command Center v3 advisory page showed a
`watchlist` row with a confident directional verdict (`ADD @ 0.50`, `AVOID @ 0.45`)
sitting on top of an *empty* expand card — no lots, no price action, no analyst,
no instrument identity. A "buy" recommendation with nothing behind it.

**Scope:** audit every deterministic fact and confidence number on the Advisory
Desk, then the CIO Desk, for the same class of failure: a confident output that
is not backed by symbol-specific evidence.

---

## Root cause — the "deep hallucination" failure mode

The watchlist bug is not an LLM bug. The LLM is downstream of a **deterministic
layer that fabricated verdicts and confidence from operator *intent labels***
rather than evidence. Five distinct defects compound into it:

### F1 — Confidence is fabricated for every non-holding row class

`confidence` is evidence-derived only for `holding` rows (via `_compute_confidence`).
For every other class it is a hardcoded constant:

| row class | hardcoded confidence |
|---|---|
| watchlist (intent → ADD/AVOID) | `0.45` / `0.50` / `0.40` |
| closed (RE_ENTER / WAIT) | `0.55` / `0.30` / `0.25` |
| allocation (any) | `0.75` |
| allocation per-account cash | `0.70` |

### F2 — Inverted confidence for `INSUFFICIENT_DATA`

`ALLOC:fixed_income` and the five per-account cash rows carried `INSUFFICIENT_DATA`
at `0.70–0.75` — high confidence in *having no data*. Logically inverted.

### F3 — Watchlist verdicts derived from intent labels

`_derive_watchlist_opinion` mapped `target_intent` straight into verdicts:
`long_term_hold`/`income`/`etf_broad` → `ADD`, `growth_speculative` → `AVOID`.
So `HTGC → ADD @ 0.50` was produced from a human-entered label with **zero**
symbol-specific market data. Operator intent was masquerading as analysis.

### F4 — Evidence count inflated by portfolio-aggregate items

`rotation`, `sector_context`, and `investment_policy` are portfolio-level and
were appended to *every* row unconditionally, then counted toward `evidence_count`.
A watchlist row with no symbol-specific data still showed `ev 3` and
`sufficient=True`. (HTGC showed `ev 3` where all 3 items were aggregate.)

### F5 — A2 sufficiency gate only applied to `holding`

The "≥3 evidence items for an actionable verdict" gate was guarded by
`if rcls == "holding"`, so watchlist/allocation/closed rows bypassed it entirely.

### F6 — No evidence-basis guard on deterministic rows

The CIO specialist advisory already carries a `confidence_basis` enum
(`FULL_EVIDENCE` / `PARTIAL_EVIDENCE` / `UNKNOWN`) plus `validate_specialist_advisory`.
The advisory desk's deterministic layer had no such guard.

---

## Fixes applied

### 1. `_build_evidence_bundle` — honest evidence accounting
- The three portfolio-level items (`rotation`, `sector_context`, `investment_policy`)
  are now tagged `"aggregate": True`.
- `evidence_count` now counts **symbol-specific** items only; aggregate items are
  reported separately as `aggregate_evidence_count`.
- `sufficient` is derived from the symbol-specific count.
- `row_class` is surfaced in the bundle for the LLM validator gate.
- Gap tracking (`evidence_gaps`) now applies to `watchlist` rows too (for the
  entry-relevant domains: catalysts, earnings, technicals, agent opinions,
  instrument identity, price action, analyst context). Position-specific gaps
  (hermes health, risk stops, lot basis) remain `holding`-only — a watchlist
  instrument has no lots or stops.

### 2. `_derive_watchlist_opinion` — no more intent → verdict
A watchlist entry is an *intent*, not a position. The desk now returns:
- `WAIT` (confidence `0.25–0.35`) when there is an intent and/or thesis —
  "on watchlist, awaiting entry signal". Intent and thesis are surfaced as
  rationale signals, never as a verdict.
- `INSUFFICIENT_DATA` (confidence `0.20`) when there is neither intent nor thesis.

### 3. `_derive_allocation_rows` — confidence agrees with verdict
- `INSUFFICIENT_DATA` (fixed-income CUSIP gap, per-account cash) → `0.20`.
- `HOLD` → `0.55`.
- `ADD` / `TRIM` (deterministic drift arithmetic) → `0.65`.

### 4. A2 sufficiency gate extended to `watchlist`
`if rcls in ("holding", "watchlist")`. Allocation rows stay exempt — their
evidence is the target/actual drift arithmetic in the row fields, not the
security evidence bundle.

### 5. LLM validator oversight gate (second line of defense)
`validate_opinion_output` now hard-rejects a model that returns an actionable
verdict (`ADD`/`TRIM`/`EXIT`/`RE_ENTER`) with fewer than 3 symbol-specific
evidence items, unless the row is `allocation`. This is the oversight the
operator asked about: the model may disagree with the deterministic verdict,
but only with evidence.

### 6. System prompt guidance (yaml + in-code fallback)
Added: a `watchlist` row is NOT a held position — with no symbol-specific
evidence the correct verdict is `WAIT`/`INSUFFICIENT_DATA`, never `ADD`/`TRIM`/`EXIT`.
An `allocation` row's evidence is its drift arithmetic, not security research.

### 7. `api_v3_advisory.py` — evidence_count no longer coalesces to aggregate
`evidence_count` falls back to `len(items)` only when the bundle value is `None`
(previously `0 or len(items)` let a symbol-specific count of `0` re-inflate to
the aggregate total).

---

## CIO Desk finding (fixed)

The CIO snapshot reported `watch` and `watch_intelligence` as `DATA_UNAVAILABLE`
while the advisory desk simultaneously listed 12 watchlist items. Root cause: a
**stale path** — `cio_portfolio.py` read `data/watchlist/state/watchlist.json`,
which does not exist; the canonical watchlist lives at
`data/portfolios/state/watchlist.json` (the same file the advisory desk reads).

`WATCHLIST_PATH` now points at `STATE_DIR / "watchlist.json"`. The CIO snapshot
is back to 14/15 domains available, with `watch`/`watch_intelligence` consistent
with the advisory desk.

**Remaining honest gap:** `reconciliation` remains `DATA_UNAVAILABLE` because no
producer writes `data/reconciliation/state/latest.json`. This is reported
honestly (not fabricated) and is a separate wiring task, out of scope here.

---

## Verification

- `tests/test_advisory_desk_phase{1..7}.py` + `test_gate_d_advisory_contract.py`
  + `test_advisory_bridge_routing.py`: **93 passed**.
- `test_gate_b_suite.py` + `test_cio_health_boundary.py` +
  `test_gate_b1_final_verification.py`: **95 passed** (two stale assertions
  synced to include the `advisory_desk` caller in `CALLER_PROCESS_MAP` /
  `CALLER_TASK_POLICY_MAP`).
- Live desk rebuild: watchlist rows are now `WAIT @ 0.30` with honest
  `ev` (0–8) and populated gap lists; allocation `INSUFFICIENT_DATA` rows at
  `0.20`; holdings unchanged and still well above the actionable threshold
  (mean symbol-specific evidence 9.4).
- Validator gate unit-checked across three cases: watchlist `ADD` on thin
  evidence → rejected; allocation `TRIM` → allowed; holding `ADD` with 5 items
  → allowed.

## Result for the operator

A watchlist entry now reads as what it is — *on watch, awaiting an entry signal* —
at low confidence, with its missing data explicitly listed. It can no longer
present as a confident "buy/avoid" recommendation. The desk's confidence numbers
now always agree with the evidence basis behind them.

---

## Follow-up (2026-08-12, evening): watchlist expand cards now populated

After the verdict/confidence fixes landed, the operator reported the watchlist
rows *still* rendered hollow — the filter worked, but every expand card still
showed "No price-action data", "No analyst coverage", "No instrument identity",
and triplicated `agent_opinion · watchlist_agent_results` lines. Three defects:

### F7 — External data loaders scoped to held positions only
`build_advisory_desk` computed `listing_dates`, `instrument_data`, `analyst_data`,
and `price_actions` from `holdings_symbols` alone. Watchlist and closed-journal
symbols (MSFT, NVDA, GD, PLTR, …) were never passed to the loaders, so their
rows had no symbol-specific evidence *at all* — even though the underlying data
(Finviz quotes, `ticker_enrichment_cache`, `yahoo_analyst_targets_history`) was
already present for those tickers.

**Fix:** introduce `research_symbols = holdings ∪ watchlist ∪ closed` and scope
all four loaders to it. `_load_instrument_identity` now iterates the full symbol
set (not just positions). Price action is computed for non-held symbols too
(OHLCV or Finviz fallback; no cost basis, by design). `price_action` and
`instrument` are attached to watchlist/closed rows.

Result: every watchlist row now carries price action, instrument identity, and
analyst context; `ev` rose (e.g. GD 3 → 5, MSFT 8 → 12) and gaps fell.

### F8 — `analyst_consensus_history` is corrupted; consensus mislabeled
`analyst_rating` was trusted verbatim, but the table stores garbage — GD carried
`recom_score = 160.15` and `analyst_rating = 'Strong Sell'` (a percentage return
mis-stored in the score column). The authoritative 1–5 score lives in
`yahoo_analyst_targets_history.recommendation_mean` (GD = 2.125 → **Buy**).

**Fix:** derive `consensus_rating` from `recommendation_mean` via a 1–5 scale
map (`_recommendation_mean_label`); `analyst_rating` is now fallback-only, and
`consensus_score` is only kept when it is a plausible 1–5 value.

### F9 — `watchlist_agent_results` duplicated per re-run
The agent table accumulates near-identical rows (same symbol + agent, new
`completed_at`), so GD showed three `agent_opinion · maria — HOLD` lines.

**Fix:** `_load_agent_results` uses `DISTINCT ON (upper(symbol), agent) …
ORDER BY completed_at DESC` — one latest row per agent.

Frontend: `EvidenceCard` now renders `agent + recommendation` for
`agent_opinion` items (no more three identical lines), and `OpinionCard`'s
empty state no longer misleadingly claims "ADVISORY_DESK_V1 off".

**Verification:** 33 advisory-desk tests green; live desk `validation_ok` +
`plausibility PASS`; live `/api/v3/advisory` watchlist rows now show real price
action, analyst consensus, instrument identity, and deduplicated agent evidence.

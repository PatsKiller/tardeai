# Advisory Desk & CIO Desk — Data Integrity Audit (2026-08-12)

Status:      HISTORICAL
as_of:       2026-08-12T22:00:58-04:00
Measured at: efcc51365 / not measured


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

---

## Follow-up (2026-08-12, night): market cap unit + price-action gap closure

After the watchlist cards populated, the operator still saw two defects in the
GD expand card: `Market cap $104926140.00M` and empty `1d` / `Off 52w high/low`.

### F10 — `market_cap_b` is in millions, not billions
The enrichment field is named `market_cap_b` but stores **millions** of dollars
(GD = `104,926.14` → $104.9B). `_load_instrument_identity` multiplied by `1e9`,
inflating every market cap 1000× (GD rendered as `$104,926,140M` ≈ $104.9T).

**Fix:** multiply by `1e6`. Frontend `fmtUSD` now emits `B`/`T` suffixes, so the
value reads `$104.93B`.

### F11 — 1d and 52-week distance were left empty in the Finviz fallback
For symbols without OHLCV, the Finviz fallback hardcoded `price_change_pct_1d`,
`pct_off_52w_high`, and `pct_off_52w_low` to `None` — even though the data was
already cached (`finviz_quote_cache.change_pct` for 1d;
`ticker_enrichment_cache.week52_high_pct` / `week52_low_pct` for 52w distance).

**Fix:** map those three fields in `_load_price_action`'s Finviz fallback.

**Result:** GD now reads `1d +0.6%`, `Off 52w high -3.1%`, `Off 52w low +26.3%`,
`Market cap $104.93B` — no empty fields remain on watchlist rows.

---

## Follow-up (2026-08-12, night): DeepSeek-default + budget sweep across the rest of the site

After the Advisory Desk watchlist was fixed (DeepSeek as sole default lane,
Ollama fallback removed, budget raised), the same audit was applied to every
other operator-facing page: **Proposals (Watch), Defense, Re-Entry, CIO Desk,
Rotation, Reports, Agents, Strategy, Options, Journal, Trading**.

### What was found to be already correct (no change needed)

- **Central lane router** (`llm_lane.py`) is already fail-closed for DeepSeek:
  "No silent fallback to Gemma when DeepSeek is requested" — a DeepSeek failure
  raises, it never falls through to `local`. Unknown lanes raise
  `UNKNOWN_LANE ... refusing silent local-Gemma fallback`.
- **Governed bridge** (`cio_governed_model_bridge.py`) enforces
  `default_failure_behavior: VISIBLE_FAILURE_NO_SILENT_FALLBACK`; the six CIO
  financial agents (`alex`/`maria`/`steph`/`guardian`/`ledger`/`morgan`) route
  through the DeepSeek-only governed gateway (no local/OAuth fallback).
- **Re-Entry Decision Desk** is deterministic by design (`llm_in_path: false`):
  READY/NEAR/BLOCK states come from Data Broker stores, never an LLM.
- **Rockville Watch/CIO model policy** already pins `provider_allowlist: ["deepseek"]`
  and `forbidden_fallback_providers` (gemma/ollama/grok/chatgpt/…) with
  `no_silent_fallback: true`.
- **Watchlist narrative processes** (`watchlist_maria/risk/steph/agent_debate/
  agent_flash_extract`) are already DeepSeek-only with ample caps (0.75–2.0).

The "local/Ollama fallback that silently serves non-DeepSeek opinions" failure
was therefore **specific to `advisory_desk.yaml`'s `lane_preference`**, already
removed earlier. Reflective critics (`sentinel`/`darwin`/`iris`/`reflection`)
were still on local Ollama at the time of this sweep; they have since been
migrated to governed DeepSeek Flash (see F15 below).

### F12 — CIO specialist-agent caps were below a single call's cost

The six CIO agents plus Alex's escalation are DeepSeek-only and route through the
governed bridge, but several `daily_cost_cap_usd` values were **below the
projected cost of one call**, so the bridge rejected every request with
`COST_CAP_EXCEEDED` before any spend — the same class of defect that blocked the
Advisory Desk synthesis.

| process | policy | projected $/call | old cap | effect |
|---|---|---|---|---|
| `steph_allocation_review` | PRO | 0.0242 | 0.01 | **blocked** (0 calls/day) |
| `alex_cio_escalation` | PRO_THINK | 0.0324 | 0.02 | **blocked** (0 calls/day) |
| `guardian_risk_critique` | FAST | 0.0078 | 0.01 | ~1 call/day |
| `ledger_tax_critique` | FAST | 0.0078 | 0.01 | ~1 call/day |
| `morgan_wealth_synthesis` | FAST | 0.0078 | 0.015 | ~1 call/day |
| `maria_research_critique` | FAST | 0.0078 | 0.02 | ~2 calls/day |
| `alex_cio_synthesis` | PRO | 0.0324 | 0.15 | ~4 calls/day |

**Fix:** raise caps in `config/llm_process_registry.json` *and* the Postgres
`llm_process_config` table (the true runtime source of truth):

| process | new cost cap | new soft cap | ≈ calls/day |
|---|---|---|---|
| `guardian_risk_critique` | 0.20 | 60 | 25 |
| `ledger_tax_critique` | 0.20 | 60 | 25 |
| `steph_allocation_review` | 0.30 | 40 | 12 |
| `maria_research_critique` | 0.30 | 80 | 38 |
| `morgan_wealth_synthesis` | 0.20 | 60 | 25 |
| `alex_cio_synthesis` | 0.40 | 100 | 12 |
| `alex_cio_escalation` | 0.15 | 20 | 4 |

The `LLM_GLOBAL_DAILY_USD_CAP` (0.50) remains the hard ceiling, so raising these
per-process caps cannot cause runaway spend. Applied idempotently via
`scripts/sync_cio_process_caps.py`.

### F13 — deploy script hardcoded the old global cap (regression risk)

`scripts/deploy_portfolio_server.sh` writes the portfolio-server drop-in with a
**hardcoded** `Environment=LLM_GLOBAL_DAILY_USD_CAP=0.25`. The live drop-in had
been raised to `0.50`, but the next redeploy would have silently reverted it to
`0.25`, regressing the earlier budget fix.

**Fix:** `deploy_portfolio_server.sh` now writes `0.50`. The source
`config/systemd/user/{cio-governed-bridge,tradeai-advisory-shadow-session,
tradeai-holdings-agent-enqueue}.service` files (still `0.25`) were also raised to
`0.50` to match the live units.

### F14 — CIO dashboard advertised a silent OAuth fallback it does not have

`api_v3_cio.py` reported `"fallback": "deepseek-v4-flash → free-oauth (grok/chatgpt)"`.
That is misleading: the governed bridge fails closed and never falls back to
OAuth/local. Corrected to `"fallback": "none — fail-closed
(VISIBLE_FAILURE_NO_SILENT_FALLBACK)"`.

**Verification:** bridge restarted (global cap 0.50 confirmed in the running
process env); re-ran projected-cost check — no DeepSeek process remains below a
single call's cost (all ≥4 calls/day, most 12–38).

## Follow-up (2026-08-12, night): reflective critics migrated to DeepSeek Flash

The four wave-1 reflective critics were the last non-deterministic agents still
on local Ollama:

| agent | timer cadence | model calls/job | before | after |
|---|---|---|---|---|
| `sentinel` | every 5 min | 3 | `gemma3:12b` (Ollama) | governed DeepSeek Flash |
| `iris` | every 5 min | 3 | `gemma3:12b` (Ollama) | governed DeepSeek Flash |
| `reflection` | Mon–Fri 21:30 | 3 | `gemma3:12b` (Ollama) | governed DeepSeek Flash |
| `darwin` | hourly | **0** | deterministic (no LLM) | unchanged |

Key facts established before migrating:

- **They currently dispatch zero jobs** (`dispatch summary: total: 0` on every
  timer fire). The runner is `PREPARE-ONLY / DEFAULT-DISABLED`; their triggers
  (`WATCH_ARTIFACT_CHANGED`, `CANDIDATE_LESSON`, `CONTRADICTION_EXCEPTION`,
  `NIGHTLY_BATCH`) are event-driven, so real volume is a handful of calls/day,
  not the 288 timer fires/day ceiling.
- **`darwin` is fully deterministic** (`BudgetPolicy.max_model_calls=0`) — it
  never calls an LLM, so there is nothing to migrate there.
- The three LLM-using critics were budgeted at `max_cost_usd=0.0` — a
  free-local-Ollama declaration. Their per-call cost on DeepSeek Flash is
  ~**$0.0015** (≈8K in × 512–1024 out), so even 50 calls/day ≈ **$0.08/day**.

### F15 — Reflective critics wired through the governed Flash path

**Changes:**

1. **Registry** — new process `reflective_critic_flash` in
   `config/llm_process_registry.json`: `deepseek_only`, `FAST`, `automated`,
   `max_input_tokens=8000`, `max_output_tokens=1024`, `daily_cost_cap_usd=0.10`,
   `daily_soft_cap=100`, `tools_allowed=false`, `fallback_allowed=false`,
   `advisory_only=true`. At ~$0.0015/call this cap ≈ 66 calls/day.
2. **Provider** — `scripts/agent_runtime_live_providers.py` gains
   `_build_governed_flash_provider()` (routes `lib.llm_lane.generate` →
   `gate_and_generate`, so calls are cost-governed, circuit-breakered, and
   fail-closed with no silent Ollama/Grok fallback). `sentinel`/`iris`/
   `reflection` share a `_REFLECTIVE_FLASH` factory; `darwin` keeps its unused
   Ollama factory (deterministic, `max_model_calls=0`).
3. **BudgetPolicy** — `max_cost_usd` for `sentinel`/`iris`/`reflection` raised
   `0.0 → 0.01` so the shadow board reflects the new small paid allowance.
   `darwin` unchanged (`0.0`, `max_model_calls=0`).
4. **Env** — `LLM_GLOBAL_DAILY_USD_CAP=0.50` added to the operator drop-in
   `~/.config/systemd/user/tradeai-agent-runtime@.service.d/20-operator-auth.conf`
   (the agent-runtime runner is a separate process from the bridge and needs its
   own global cap for `gate_and_generate`). Source
   `config/systemd/agent_runtime/tradeai-agent-runtime@.service` annotated.
5. **DB** — `scripts/sync_cio_process_caps.py` now UPSERTs (so a brand-new
   process row is created) and includes `reflective_critic_flash`; re-run, DB row
   verified `cost=0.10 soft=100`.
6. **Tests** — `test_gate_b_suite.py` reflective-critic test updated to assert
   `sentinel/iris/reflection` share the governed-Flash factory and `darwin`
   remains on the (unused) Ollama factory.

**Non-goal:** `vigil`, `argus`, and the disabled wave-2 agents (`vega`,
`risk_agent`, `aegis`) are **not** migrated. They fall through to the default
Ollama factory (`gemma3:4b`); `vigil` still uses local Ollama for health-signal
fusion and `argus` is deterministic. Only the three LLM-using reflective critics
were in scope.


### F16 — Stale agent-runtime tests reconciled to the wave-3 fleet

The wave-3 CIO/wealth rollout (alex/steph/ledger/morgan) plus `vigil` landed in
`definitions.py`, but the tests, the canonical roster, and `morgan`'s catalog
entry never caught up. 10 tests were failing (`test_agent_runtime_lane_d_agents.py`
× 4, `test_agent_runtime_monitoring.py` × 6). Root causes and fixes:

1. **`morgan` catalog entry was malformed.** `config/agent_maturity_catalog.json`
   had a partial, handoff-style `morgan` record (missing `objective`, `owner`,
   `maturity_target`, `denied_tools`, `retrieval_policy`, `review_policy`,
   `score_policy`, `disable_control`, `rollback_control`, `acceptance_evidence`,
   `budget.deadline_seconds`, and 6 of 8 `authority` keys). `load_maturity_catalog`
   raised `canonical roster mismatch … extra=['morgan']`. **Fix:** completed the
   entry to the canonical maturity schema, preserving its `DESIGNED` / `enabled:false`
   intent and the readiness fields `cio_agent_readiness` consumes
   (`governed_gateway_process`, `gateway_policy`, `deterministic_sources`, canary
   fields). `morgan` stays `DESIGNED` → `NOT_READY` for handoff (unchanged runtime
   behavior).
2. **`morgan` missing from `CANONICAL_AGENT_IDS`.** `scripts/agent_runtime/monitoring.py`
   listed 16 agents; the catalog had 17. **Fix:** added `morgan`.
3. **Roster partition test** (`test_fleet_roster_matches_wave_partitions`) asserted
   `FLEET == INITIAL | SECOND` and ignored the `THIRD` wave (`steph/ledger/morgan`).
   **Fix:** union all three waves; assert the current wave membership.
4. **Enablement test** (`test_initial_agents_are_enabled_in_shadow`) forced
   `wave == "INITIAL"`, but `INITIAL_SHADOW_AGENT_IDS` now spans wave-1
   (`sentinel/darwin/iris/reflection/argus/vigil`) and wave-3 (`alex/steph/morgan`).
   **Fix:** accept `wave in {INITIAL, THIRD}` for the enabled-SHADOW set.
5. **Authority test false-positive.** A bare substring check (`"broker" in tool`)
   flagged `data_broker.read` (a read-only Data Broker tool) as broker authority.
   **Fix:** prefix-match against `FORBIDDEN_TOOL_PREFIXES` (`broker.`, `order.`, …),
   matching the contracts deny surface exactly.
6. **Budget invariant** asserted `max_cost_usd == 0.0` ("SHADOW spend is zero"), but
   wave-3 advisors and the migrated reflective critics now carry a small paid
   allowance (`0.01`–`0.05`). **Fix:** assert `max_cost_usd >= 0.0`.
7. **Monitoring counts** were stale (`agent_count == 16`, `SHADOW == 5`). `alex` was
   already `SHADOW` in the catalog. **Fix:** `agent_count == 17`, `SHADOW == 6`
   (`{sentinel,darwin,iris,reflection,argus,alex}`), `DESIGNED == 11`.

**Out of scope (pre-existing, documented for a later pass):**
- `tax_agent` (catalog) vs `ledger` (definitions) naming, and `vigil`/`ledger`
  absent from the catalog — the catalog is a parallel maturity board with its own
  stable IDs; renaming would ripple into `cio_agent_handoff_queue` (`_HANDOFF_TO_CATALOG_ID`)
  and the frontend.
- `steph` is `SHADOW` in `definitions.py` but `DESIGNED` in the catalog (handoff
  queue deliberately treats steph as `NOT_READY`).
- `tests/test_llm_content_quality.py` has a committed `SyntaxError` (unterminated
  string at line 33) and blocks whole-suite collection.
- 22 `tests/test_cio_agent_handoff_queue.py` failures (e.g. `BLOCKED -> CLAIMED`)
  are pre-existing: the lazy `AGENT_REGISTRY` derives readiness from the catalog
  (maria/steph `DESIGNED` → `NOT_READY`), which predates this work. Verified by
  stashing this change set and reproducing the same failures.

**Verification:** `test_agent_runtime_lane_d_agents.py`,
`test_agent_runtime_monitoring.py`, `test_gate_b_suite.py`,
`test_gate_b1_final_verification.py`, `test_gate_b2_closure.py` → **107 passed**.
`AgentReadinessRegistry.load()` parses the completed catalog (17 agents) cleanly.

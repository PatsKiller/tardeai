# Scalp Fire Integrity — Gate Persistence, Stop Floor, and Canonical Setup Identity

Status:      HISTORICAL
as_of:       2026-07-28T11:51:51-04:00
Measured at: efcc51365 / not measured

Date: 2026-07-28
Branch: `agent/scalp-fire-integrity-v1`
Scope: three defects in the momentum-scalp fire path (detector → shadow logger → ActiveTrader
projection/UI), plus the directly-associated queue dedup/order correction. SHADOW / MANUAL-PAPER only.
No schedules, services, flags, accounts, credentials, broker authority, or order path were changed.
The stale convergence-pin refresh and `scripts/alpaca_live_read_sync.py` are explicitly OUT OF SCOPE.

---

## Defect 1 — Persist and honor the universal execution gate

### Root cause
`scalp_setup_detectors.detect_setups()` computes `execution_gate_result = PASS|FAIL` and stores the full
evidence under `setup_evidence["_execution_gate"]`, but the shadow logger discarded it:

- Ordinary setup rows inserted a **hard-coded `gate_result = NULL`**.
- FSM lane=TRIGGER rows inserted a **hard-coded `gate_result = 'PASS'`** — a DB row could claim PASS even
  though no successful gate evaluation existed for that fire bar.

The ActiveTrader projection then had no trustworthy gate to honor, and the frontend mapped a missing gate
to an implicit **PASS** (fail-open).

### Fix — exact gate persistence semantics
One PURE normalization helper, `scalp_setup_detectors.normalize_gate_result()`:

| detector `execution_gate_result` | persisted / projected `gate_result` |
|----------------------------------|-------------------------------------|
| `PASS`                           | `PASS`                              |
| `FAIL`                           | `VETO`                              |
| missing / unreadable             | `NULL` → `NOT_EVALUATED` (DEFER)    |

- **Ordinary rows** (`scalp_shadow_logger`): persist the normalized taxonomy gate result, plus a
  structured `gate_reasons` JSON (`execution_gate_result`, reason labels, and the stop-validation block).
- **FSM lane-trigger rows**: the hard-coded `'PASS'` is removed. The gate result is computed from the
  **fire-bar taxonomy** (`ftax`); when the taxonomy/gate is unavailable it persists **NO PASS** (`NULL`).
  The stop-validation and execution-gate result are merged into the existing FSM `gate_reasons`.
- A row NEVER says `PASS` unless the detector produced a successful gate evaluation.

### Projection contract (`read_api._map_ignition_row_to_signal`)
Distinct, never-collapsed fields: `lane`, `setupState`, `fsmState`, `gateDecision` ∈ {PASS, VETO, DEFER},
`primarySetupId`, `primarySetupLabel`, `setupIdentityState`, `stopValidation`, `executionEligibility`.
Rules: a NULL/missing gate → **DEFER, never PASS**; `setup_state=FIRED` with DEFER stays VISIBLE as a fire
but is not execution-eligible; ARMED / VETO / missing identity are never eligible.

`executionEligibility = SIMULATION_ELIGIBLE` only when **all** hold: `setupState==FIRED` AND
`gateDecision==PASS` AND `primarySetupId` present AND `registryHash` present AND `stopValidation==PASS`
AND required current-data fields present. Otherwise a typed reason: `SETUP_NOT_FIRED |
GATE_NOT_EVALUATED | GATE_VETO | SETUP_IDENTITY_UNRESOLVED | STOP_INVALID | DATA_INCOMPLETE`.

The **simulation engine's** existing `gate_decision == PASS` refusal (`sim_execution.py` STAGE 5) is
preserved verbatim — not rewritten.

### Frontend (`ActiveTraderPage.tsx`)
- Removed the fail-open `missing gate -> PASS`; a missing gate now renders **`GATE: DEFER / NOT
  EVALUATED`**.
- `canRoute` now requires `setupState==='FIRED'` AND `gateDecision==='PASS'` AND `primarySetupId` present
  AND `stopValidation==='PASS'` AND not reference/sample. **ARMED never prepares a paper route.** The final
  paper-submit button remains absent/disabled (unchanged).

---

## Defect 2 — Deterministic minimum-stop floor

### Root cause
Implausibly tight stop references (e.g. a stop a fraction of a tick below entry) were never rejected
through a deterministic tick/spread/volatility floor; they could flow through as if actionable.

### Fix — ONE pure validator, config-driven
`scalp_execution_gate.validate_stop_reference()` — a single pure function reused by (1) ordinary
named-setup rows, (2) FSM lane-trigger rows (both via the universal gate in `detect_setups`), and (3) the
simulation event validation (`sim_execution.py` STAGE 6). No duplication across the three modules.

Formula (long entry):
```
actual_stop_distance = entry_ref - stop_ref
tick_floor           = min_stop_ticks        * price_increment
spread_floor         = min_stop_spread_multiple * spread_dollars   (spread_dollars = spread_bps/1e4 * price)
volatility_floor     = min_stop_atr_multiple  * atr_1m
required_stop_distance = max(available floors)
```
Only floors whose inputs are available contribute. It **VETOes** when `actual_stop_distance` is below any
available floor, and **fails CLOSED** (`STOP_FLOOR_INPUT_UNAVAILABLE`) when no defensible floor can be
established. It **NEVER silently widens** a stop — it returns PASS or a typed VETO.

Outputs: `stop_validation` (PASS|VETO), `actual_stop_distance`, `required_stop_distance`, `tick_floor`,
`spread_floor`, `volatility_floor`, `stop_distance_bps`, `price_increment`, `reason_codes`.
Reason codes: `STOP_REFERENCE_MISSING`, `STOP_DIRECTION_INVALID`, `STOP_DISTANCE_BELOW_TICK_FLOOR`,
`STOP_DISTANCE_BELOW_SPREAD_FLOOR`, `STOP_DISTANCE_BELOW_VOLATILITY_FLOOR`, `STOP_FLOOR_INPUT_UNAVAILABLE`,
`STOP_VALIDATION_PASS`.

### Config (versioned, NOT in code) — `config/scalp_confirmations.yaml` → `gate.stop_floor`
```yaml
version: "scalp-stop-floor-v1"
min_stop_ticks: 2
min_stop_spread_multiple: 1.5
min_stop_atr_multiple: 0.25
us_equity_fallback: { ge_1: 0.01, lt_1: 0.0001 }   # price>=1 -> 0.01, price<1 -> 0.0001
```
Explicit provider/broker `price_increment` is preferred; the US-equity fallback is used only when it is
unavailable. The validator carries these same numbers as a defensive code fallback ONLY when no config is
supplied (config is authoritative).

> **These defaults are a CONFIGURABLE ENGINE ADAPTATION, not a validated trading edge.**

### Regression fixtures (all covered by tests)
- ATAI-like entry 7.18 / stop 7.1764 (~0.0036, ~5bp) → **VETO** (below tick floor).
- NUAI-like entry 4.36 / stop 4.3229 (~0.0371, ~85bp) → **PASS** (clears tick/spread/vol floors).
- stop ≥ entry → `STOP_DIRECTION_INVALID`; missing ATR / missing spread still validate on remaining
  floors; sub-dollar increment (0.0001); wide spread raising the floor; ordinary valid stop; and proof the
  validator never modifies the supplied entry/stop.

The gate includes stop validation but keeps it a **separate eligibility dimension**: a FIRED setup with
`stop_validation != PASS` stays visible but is not execution-eligible, and the liquidity gate's PASS/FAIL
is unaffected.

---

## Defect 3 — Canonical setup identity

### Root cause
The projection fabricated a named canonical setup from a bare lane event:
`label = primary_setup_label or ("IGNITION BREAKOUT" if lane == "TRIGGER" else lane)`. A `lane=TRIGGER`
row with no `primary_setup_id` was displayed as **IGNITION BREAKOUT** — inventing a setup identity.

### Fix — bare-trigger vs canonical-setup semantics
A canonical named setup REQUIRES `primary_setup_id` **and** `primary_setup_label` present (and the ID
resolves in `config/scalp_setup_registry.yaml`). A bare lane trigger is projected as:
`primarySetupId=absent`, `matchedSetupIds` absent, `matchedSetupLabels=[]`,
`setupIdentityState=UNRESOLVED`, `displayEventLabel="IGN TRIGGER — SETUP UNCLASSIFIED"`,
`executionEligibility=SETUP_NOT_FIRED`. **IGNITION BREAKOUT** is shown only when the canonical ID is
`SCALP_IGNITION_BREAKOUT_V1` and its registry label resolves. Lane and setup remain SEPARATE taxonomies.

The `tests/test_active_trader_permission_queue.py::test_signal_projection_trigger_row` test that asserted
`primarySetupLabel == 'IGNITION BREAKOUT'` (which encoded the bug) was reversed, and tests were added
proving: bare TRIGGER stays a lane event; canonical IGNITION BREAKOUT requires its setup ID; canonical
VWAP PULLBACK stays itself; scanner-style rows never acquire setup IDs/labels; matched arrays empty for an
unresolved bare trigger; and an unresolved identity cannot prepare a paper route.

### Query ordering correction (`_ign_trigger_today`)
`DISTINCT ON (symbol)` forces `ORDER BY symbol …`, so the `LIMIT` was applied **alphabetically before
recency ordering**. Fixed with a CTE so the LIMIT applies AFTER dedup and the final result is ordered by
recency/priority:
```sql
WITH latest_per_symbol AS (
    SELECT DISTINCT ON (symbol) …
    FROM scalp_ignition_events
    WHERE session_date = %s AND (lane = 'TRIGGER' OR setup_state = 'FIRED')
    ORDER BY symbol, fired_at DESC, id DESC)
SELECT * FROM latest_per_symbol
ORDER BY fired_at DESC, ign_score DESC, symbol LIMIT %s
```
Inclusion (`lane='TRIGGER' OR setup_state='FIRED'`) and one-latest-row-per-symbol are preserved.

Additive response counts on the permission queue: `lane_trigger_count`, `canonical_setup_fire_count`,
`unclassified_lane_trigger_count`, `deduped_fire_count`. The historical last-fire/reference query
(`_permission_queue_signals`) now recognizes `lane='TRIGGER' OR setup_state='FIRED'` WITHOUT treating a
bare lane trigger as a named setup.

---

## Compatibility behavior
- **Database**: purely additive at the value level — no schema migration authored, no DDL run, no rows
  written. Both INSERTs already targeted existing `gate_result` / `gate_reasons` columns; the ordinary
  INSERT now populates `gate_reasons` (previously left to its default). Column/placeholder counts verified
  (35/35 columns, 33 & 32 placeholders).
- **API**: existing response fields preserved as compatibility aliases (`ign_trigger_count` kept; new
  counts are additive). New projection fields (`gateDecision`, `setupIdentityState`, `displayEventLabel`,
  `stopValidation`, `executionEligibility`) are additive and optional.
- **Frontend**: all new `ScalpSignal` fields are optional; existing chips/behavior unchanged except the
  fail-open gate default and the tightened `canRoute`.

## Tests
- `tests/test_scalp_confirmations_gate.py` — added the stop-floor validator matrix + gate integration.
- `tests/test_active_trader_permission_queue.py` — reversed the IGNITION-BREAKOUT bug test; added canonical
  identity, DEFER-not-PASS, and scanner-row tests.
- `tests/test_active_trader_sim_execution.py` — added the stop-inside-noise-floor refusal.
- Full scope suite green: `test_scalp_confirmations_gate`, `test_scalp_setup_detectors`,
  `test_scalp_trigger_engine`, `test_active_trader_permission_queue`, `test_active_trader_session_http`,
  `test_active_trader_sim_execution`, `test_scalp_engine_isolation` (+ adjacent active_trader/scalp tests).
- Frontend: `tsc --noEmit` clean; `scripts/check_design_tokens.sh` pass.

## Remaining risks
- The stop-floor defaults are engine adaptations, not a proven edge — they must be tuned against real fill
  data before any promotion beyond SHADOW.
- Stop-validation is persisted inside `gate_reasons` JSON (no dedicated column) to avoid a migration; a
  future migration could promote it to a first-class column for indexed querying.
- Playwright ActiveTrader E2E was not executed here (no browser binaries in this environment); assertions
  were reviewed manually and the affected chips still render (`GATE:` label preserved).

## Rollback
Revert the branch `agent/scalp-fire-integrity-v1` (or the four commits). No data migration, no service or
schedule change, and no deployment occurred, so revert is a pure code rollback. Historical rows are
unaffected because nothing was written to the database.

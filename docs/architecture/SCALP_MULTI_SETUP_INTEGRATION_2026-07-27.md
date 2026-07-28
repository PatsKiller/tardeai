# Scalp Multi-Setup Taxonomy — Integration Architecture (2026-07-27)

How the named-setup taxonomy extends the existing `momentum_scalp_intraday` engine. Additive, SHADOW,
deterministic. No parallel scalping system was built.

## Modules

| Layer | Module | Role |
|---|---|---|
| Registry | `config/scalp_setup_registry.yaml`, `scripts/scalp_setup_registry.py` | canonical 7 setups; stable hash; deterministic primary selection; read-only public view |
| Session | `scripts/scalp_session.py` (+ `scalp_signal_engine.yaml → session`) | PREMARKET/REGULAR/POST_CUTOFF/CLOSED clock; configurable active start; noon cutoff; per-setup eligibility |
| A Detectors | `scripts/scalp_setup_detectors.py` | 7 pure detectors + `detect_setups` orchestrator |
| B Overlays | `scripts/scalp_confirmations.py` (+ `scalp_confirmations.yaml`) | 9 confirmation labels, direction-aware |
| C Gate | `scripts/scalp_execution_gate.py` | universal veto gate, canonical outputs, never auto-markets |
| Wiring | `scripts/scalp_shadow_logger.py` | computes taxonomy per symbol / per fire; writes additive columns |
| API | `scripts/active_trader/read_api.py` + `read_http.py` | GET setups + setup-events (read-only, zero-authority) |
| UI | `apps/command-center-v3/src/components/ScalpStrategyModal.tsx`, `ScalpSetupsPanel.tsx` | modal + panel on Trading→Scalp |
| Alerts | `scripts/scalp_alert_emitter.py` | alert names the setup + MANUAL PAPER ONLY |

## FSM reuse (no duplication)

MICRO PULLBACK and IGNITION BREAKOUT **reuse** `scalp_trigger_engine.run_trigger_engine` (the existing
impulse→pullback→ARMED→TRIGGERED machine). MICRO PULLBACK maps a TRIGGERED fire to the setup; IGNITION
BREAKOUT additionally requires the IGN notification lane. No second state machine exists — enforced by
`tests/test_scalp_engine_isolation.py` (AST guard) covering all new modules.

## Data flow (per symbol, per minute — SHADOW)

```
bars + IGN + FSM state + T0 micro (existing)
   └─> taxonomy_for_symbol()
         ├─ detect_setups(): run 7 detectors → session/window gate → execution-gate veto → primary
         ├─ confirmations (Layer B) → confirmation_labels
         └─ execution gate (Layer C) → veto + gate labels
   └─> scalp_shadow_logger writes additive columns on scalp_ignition_events
```

Fail-safe: a taxonomy exception never breaks the existing IGN/TRIGGER logging (wrapped; columns default).

## Event contract (additive migration `2026-07-28_scalp_setup_taxonomy.sql`)

Preserved: `lane` (IGN_60/IGN_ACCEL/TRIGGER — a lane is not a setup). Added (all `IF NOT EXISTS`):
`primary_setup_id, primary_setup_label, matched_setup_ids (jsonb), matched_setup_labels (jsonb),
setup_state, setup_version, setup_fired_at, market_session, confirmation_labels (jsonb),
setup_evidence (jsonb), setup_fail_reasons (jsonb), registry_hash`. `setup_state ∈ SCANNING/ARMED/FIRED/
INVALIDATED/EXPIRED/DATA_UNAVAILABLE/OUTSIDE_WINDOW`.

## API contract

`GET /api/v3/active-trader/scalp/setups` → `{setup_registry:{setups[],registry_hash,...}, read_only, authority:false…}`.
`GET /api/v3/active-trader/scalp/setup-events?limit=&session_date=&setup=` → `{events[], count, source}`.
Both GET-only, zero-authority, backward compatible, fail-closed (empty when the DB/columns are absent).

## UI integration

`ScalpSetupsPanel` renders on the Trading hub Scalp tab (one-line insertion in `TradingHub.tsx`),
consuming the API. `ScalpStrategyModal` is registry-driven (no hard-coded rules), a11y (role=dialog,
aria-modal, focus trap + return, Escape), responsive (scroll body, wide tables scroll, sticky header),
strictly read-only. Signal rows show setup chips + MULTI-SETUP; a chip opens the modal preselected.

## Rollout (gated)

Additive migration (`IF NOT EXISTS`), then build the exact merged ref and deploy the static UI via the
canonical convergence installer, then update only the approved shadow-logger schedule/window. Restart only
services that strictly require it. See the closeout for the exact plan. No paper/live order during rollout.

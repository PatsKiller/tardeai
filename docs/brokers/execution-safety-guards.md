# Execution Safety Guards (ADR-B3)

**Status:** ACCEPTED — the safety contract of the whole program. Schwab has NO paper environment, so these
guards ARE the environment separation.

## Execution modes (`BrokerExecutionMode`)
| Mode | Meaning | I/O allowed | Who uses it |
|---|---|---|---|
| `SIMULATION` | internal sim only, no broker calls | none | tests, what-ifs |
| `PAPER_TRAINING` | Alpaca paper pipeline (training) | Alpaca paper API | the EXISTING pipeline, unchanged |
| `BROKER_DRY_RUN` | translate + validate + audit, **zero order-endpoint HTTP** (operator decision 2026-06-11) | none on order surface | Schwab previews |
| `BROKER_DISABLED` | adapter registered, everything blocked | none | **Schwab default this phase** |
| `LIVE_ENABLED_FUTURE` | reserved; cannot be reached by config alone | n/a | nobody |

## Guard rules (fail-closed, tested)
0. **HARDCODED CANARY GATE (Stage 2a Part D, 2026-06-12)** — `scripts/brokers/canary_gate.py` runs IN
   FRONT of the mode logic for every mutating action (submit/replace) on every non-alpaca broker:
   symbol ∈ committed allowlist (ships EMPTY; committed by git at session time) · price ≤ $4 ·
   qty ≤ 10 sh · notional ≤ $40 · US equities · long-only — anything else ⇒ BLOCKED before any
   present-or-future allow branch is even consulted. The module is pure (no env/DB/config reads —
   commit-only by construction); UI/config can never widen it. Unit-tested in isolation incl. the
   hypothetical where BROKER_DISABLED is lifted and 2FA approved (tests/test_canary_gate.py 22/22).
1. Missing/unknown config → `BROKER_DISABLED`. Unknown broker → BLOCKED.
2. `LIVE_ENABLED_FUTURE` additionally requires ALL of: env flag `BROKER_LIVE_ENABLED=true` AND a DB
   `system_controls` row AND a signed operator approval record — none exist; checks fail closed; and even
   then this phase's Schwab adapter raises `ExecutionBlocked` unconditionally in `submit()`.
3. Every authorize() decision (grant or block) emits an `intent_state_events` audit row with reason +
   correlation_id.
4. The existing fences are UNTOUCHED and remain authoritative beneath this layer: schwab_transport
   NotProvenWrite (validate_schwab_no_writes 17/17 as of 2026-06-12), ALPACA paper-only init checks,
   LIVE_TRADING_ENABLED, live_trading_gate. The guard layer sits ABOVE them; defense in depth, not
   replacement.
5. `scripts/brokers/` imports neither schwab-py nor transport write methods — verified by the no-writes
   validator continuing to pass (boundary rule) and by test_no_write_imports.
6. **Two-channel anti-fat-finger approval (Part E, 2026-06-12)** — a future submission requires BOTH:
   Telegram ✅ in the proposals chat (one-time code; message carries the Tailscale deep-link
   `https://<TAILSCALE_HOSTNAME>/v3/trading?tab=Broker+Orders&intent=<id>`) AND a web popup where the
   operator must TYPE the ticker exactly (a click alone never confirms). Single-use, TTL 10 min,
   ONE order at a time (a second intent cannot request approval while one holds the slot). Fully
   exercisable today; execution still ends BLOCKED (tests/test_two_channel_approval.py 11/11).

## Stage 2a dormant surfaces (2026-06-12) — read-only by construction
- **ToS-desktop-style Active Trader panel** (v3 Trading → Broker Orders): every control builds/edits a
  DRAFT canonical intent → `/api/v2/broker-orders/preview` (validate+translate+guard audit). Qty
  presets are canary-scaled (2/5/10). No auto-send; no submit endpoint exists (validator-checked).
- **All-accounts monitor** (v3 Trading → Schwab Accounts): live positions/open orders for all 3
  accounts via `/api/v2/schwab/accounts-live` (fenced reads, 30s cache). "Edit" = DRAFT modification
  only — never an API modify.
- **Shadow-reconciliation harness** `scripts/schwab_shadow_recon.py` (~30s reads; diffs Schwab's
  actual order JSON vs the translator prediction; ∅ = pass modulo documented renames; mismatch =
  session ABORT) and **activity capture** `scripts/schwab_activity_capture.py` (poll-based
  fill/status payloads → `schwab_activity_log`). Both read-only — validator-checked.
- **Canary analytics exclusion**: `schwab_round_trips.canary` (sticky tag at ingest from the gate
  allowlist) excluded from stats/journal/backtester/strategy consumers — proven zero aggregate
  movement (tests/test_canary_exclusion.py 9/9).
- **AI help** on the order panel is advisory-only (local model default; Claude only on explicit
  escalation; never auto-cloud; explains mechanics, never picks, cannot submit/approve).

## Non-conflation guarantee
`PAPER_TRAINING` (Alpaca) and Schwab modes are disjoint enum values with disjoint adapters; no registry or
flag flip can re-point the training pipeline at Schwab. The training submitter never consults the Schwab
adapter; the Broker-Orders surface never consults the Alpaca training path.

## Release gating checklist (future live enablement — OUT OF SCOPE now)
operator-signed approval record · 30+ reconciled dry-run translations reviewed · order-event streaming or
≤1-min polling proven · replace/cancel semantics verified on dev account · rate-limit confirmation ·
kill-switch drill · rollback plan · validator extended with live-path assertions BEFORE any unfencing.

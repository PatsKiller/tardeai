# Stage 2c — Protective Stops on Holdings (spec)

**Status: DESIGN. Policy lock `brokers/protective_stop_policy.py` committed with `ENABLED=False` —
nothing can place a stop on a holding until that flips by commit AND the operator arms it.**
**Prereq: Stage 2b canary write test (docs/brokers/stage2b-write-pilot-spec.md) must PASS first.**

Operator decisions (2026-06-14): build the buttons now but gated OFF; headline shows the concrete
advised stop; full monitoring (alert near stop + warn-to-modify + read-only broker recon).

## The lifecycle

```
engine advises stop  →  [Queue stop] (Open Trades card)  →  preflight (policy + structure + quote)
   →  per-order 2FA (web typed-ticker + Telegram)  →  submit via schwab_transport (the SAME fenced
       pilot path as the canary)  →  stop LIVE at broker  →  monitor loop:
         • alert when price within ~1 ATR of the active stop
         • warn (with [Modify]) when the stop should trail up / is mis-sized vs new structure
         • reconcile (read-only) that the stop still EXISTS at Schwab; flag if missing/cancelled
   →  [Modify] → 2FA → cancel + re-place (no in-place replace, per the canary's cancel+new rule)
```

## What's built NOW (gated off)

- **Headline fix** — the Open Trades card replaces "Needs protection review" with the engine's
  concrete action: `▸ ADVISED: SELL STOP $25.18 GTC · then trail 8%`.
- **`brokers/protective_stop_policy.py`** — commit-only envelope, `ENABLED=False`:
  SELL-to-close existing longs only · STOP/STOP_LIMIT GTC · taxable only · placed stop within ±5% of
  the advised stop AND below price · qty ≤ held shares · ≤$250K/order. Fails closed; default blocks.
- **Locked buttons** on each card: `🔒 Queue stop` / `🔒 Queue stop-limit` / `🔒 Modify` (disabled,
  tooltip explains Stage 2c). Visible so the workflow is clear; inert until armed.

## What's built NEXT (after spec review)

1. **Endpoints** — `pilot/protective-preflight` (build the SELL STOP intent from the held position +
   advised stop; run policy + canary-style structure/quote checks + save draft) → existing
   request-approval/approve (2FA) → `pilot/protective-execute` (sole transport caller). Reuses the
   Stage 2b 2FA + transport; adds the protective-stop policy as an extra gate IN FRONT.
2. **Transport** — `place_order` already exists (Stage 2b). The protective path passes the
   protective_stop_policy gate + the existing execution_guard stack. STOP/STOP_LIMIT specs already
   exist (`make_battery_spec`); generalize to arbitrary qty/price within the envelope.
3. **Monitor** — extend `unified_stop_supervisor` (or a sibling cron) to, for each REAL holding with a
   placed protective stop: (a) alert at ≤1 ATR distance, (b) re-run the family engine and warn if the
   advised stop moved materially (trail-up / re-size), (c) reconcile via the read-only Schwab recon
   that the stop order still exists; Telegram + card surfacing. Advisory; [Modify] is operator-gated.
4. **Arm/disarm** — `schwab_pilot_arm.py`-style typed-phrase to flip the session + a commit to set
   `ENABLED=True`. Two surfaces (commit + arm), same as Stage 2b.
5. **Validator** — extend `validate_schwab_write_policy.py`: protective stops only via the policy gate
   (default-off proven), taxable-only, qty≤held, drift≤5%, fails-closed; tamper-evidence covers the
   new module.

## Safety invariants (unchanged from Stage 2b, restated)

- Real orders ONLY through `schwab_transport` behind: protective_stop_policy → execution_guard
  (canary/locks) → per-order 2FA. A button click alone places nothing — Telegram on your phone is
  the second surface.
- SELL-to-close only: the policy refuses qty > held shares, so it can never open a short.
- `ENABLED=False` at rest; any restart / disarm returns to blocked; commit-only widening.
- Paper/canary untouched. Schwab IRAs excluded.

## Open questions for review

1. **Qty:** full position per stop, or allow partial (e.g. stop only the unrealized-gain tranche)?
   Default proposed: full held qty.
2. **STOP vs STOP_LIMIT default:** market-stop (guaranteed exit, slippage risk) vs stop-limit
   (price floor, gap risk of no fill). Proposed: STOP for liquid names, STOP_LIMIT offered as the
   variant button.
3. **Trail execution:** Schwab supports native TRAILING_STOP — place the trail directly, or place a
   fixed STOP and let the monitor walk it up via [Modify]? Proposed: native trailing where the family
   says trail, fixed STOP otherwise.
4. **Envelope scope:** taxable-only first (proposed), or include the IRAs once proven?

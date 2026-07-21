# Stage 2c — Protective Stops on Holdings (spec)

> **✅ SHIPPED 2026-06-15 — this is the original DESIGN spec (historical). For the as-built production
> architecture (all taxable + IRAs live, standing no-ARM, modify, lifecycle/health/Hermes/Grok monitoring,
> Alpaca auto-management) see → [`stop-management-architecture.md`](stop-management-architecture.md).**

**Status: DESIGN (historical). Policy lock `brokers/protective_stop_policy.py` was committed with
`ENABLED=False` — nothing could place a stop until that flipped by commit AND the operator armed it.**
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

## Design decisions (operator, 2026-06-14 — RESOLVED)

1. **Qty = FULL position** — each protective stop covers all held shares (e.g. SELL 301 V STOP).
   `[Queue stop]` defaults qty = held shares; policy already refuses qty > held (no shorts).
2. **Default order type = STOP** (market-on-trigger; guaranteed exit, accepts small slippage).
   `[Queue stop-limit]` is the explicit variant button for a price floor (gap-risk acknowledged).
3. **Trail = native Schwab TRAILING_STOP** — when the family engine says trail (unrealized ≥ +10% &
   price > 50d SMA, e.g. V/FCNTX at 8%), place a real `TRAILING_STOP` that the broker auto-walks up.
   Fixed STOP only when the engine says no-trail (income / underwater). No manual walk-up needed.
4. **Envelope = taxable only first** (IRAs excluded until proven), matching the canary pilot.

> **2026-07-21 (commit 06cc5349):** a 4th Schwab type — **`TRAILING_STOP_LIMIT`** (trail offset + limit
> offset, `limit_offset ≥ trail_pct`) — is now in the policy allowlist and UI. Trades market-on-trigger
> slippage for non-fill/gap-through risk. Schwab only; Fidelity/SnapTrade advisory/manual. See
> `docs/STOP_METHODOLOGY.md` → "Trailing STOP-LIMIT".

These are wired into `protective_stop_policy.py` semantics: SELL-to-close · STOP/STOP_LIMIT/TRAILING_STOP/TRAILING_STOP_LIMIT
· taxable · qty≤held · within ±5% of advised · ≤$250K/order. Build the execute endpoints + monitor
NEXT, after the Stage 2b canary test passes and this spec is approved.

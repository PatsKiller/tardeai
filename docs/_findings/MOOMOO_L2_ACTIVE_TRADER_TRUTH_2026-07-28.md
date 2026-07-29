# Moomoo L2 · ActiveTrader Live Truth — findings (2026-07-28)

Branch: `agent/moomoo-l2-active-trader-live-truth-v1` · Base: `596d4efe` (PR #246 merged).
Scope: **market-data / read-plane ONLY**. No live session, no trade unlock, no order path,
no schedule/deploy/service-restart changes. `live_session_enabled=false` preserved.

## What was actually wrong (the 10 defects)

1. **L2 entitlement existed but ActiveTrader consumed no L2.** There was no consumer path
   from the OpenD L2 entitlement into the ActiveTrader read surface.
2. **`moomoo_t2.default_provider()` supplied `book_fetcher=None`** — fixed in the base for the
   scan path; the real single-owner consumer path did not exist.
3. **`default_provider()` swallowed a `MoomooClient` construction failure** — fixed in the base
   (narrowed + logged); superseded here by the gateway.
4. **`ArmedSubscriptionManager` only mutated a local dict**, never issuing OpenD
   subscribe/unsubscribe. The new `SubscriptionManager` issues real
   `subscribe`/`unsubscribe`/`query_subscription` through the single gateway.
5. **`read_api._arming_status` inferred L2 connectivity from a file.** The L2 block now derives
   `connected`/`entitlement`/`quota`/lifecycle from the LIVE gateway; a state file NEVER implies
   connected/subscribed/fresh/T2. Distinct `l2_arm_intent` / `l2_subscription_state` /
   `l2_data_state` / `l2_confirmation_state` are surfaced.
6. **`scalp_shadow_logger` hardcoded `data_tier='T0'`** for every ignition/trigger row and the
   detector. Replaced with `effective_data_tier(cfg)`: defaults T0, promotes to T2 ONLY on an
   explicit operator config act (`data_tiers.active_tier==T2` or `t2.feeds_scoring`), fails closed
   to T0 when the dcf/slippage ladder lacks the tier. A live feed NEVER promotes on its own.
7. **UI polled 5s and rendered `last==entry_ref`, `changePct=0`.** The queue metadata still polls
   5s, but the live ticker (current mark, L2 truth, fire-performance) polls 1.5–2s over the
   visible set. Fire price / time are immutable; current mark, change, MFE/MAE, current-R are
   server-computed.
8. **Scanner prices were scan-time snapshots.** The live-mark resolver serves current marks with
   explicit source priority (Moomoo-subscribed → gateway; else approved provider), never blended.
9. **Current-session fires stayed in the queue with no TTL / resolved lifecycle.** Fires now carry
   a lifecycle (FIRED_FRESH → ACTIVE_OBSERVATION → STOP/TARGET → EXPIRED → OUTCOME_RESOLVED /
   DATA_STALE); only FIRED_FRESH + ACTIVE_OBSERVATION show in the active queue; older fires move to
   TODAY'S FIRE HISTORY.
10. **Fire time / current price / delta / MFE / MAE / outcome were not projected.** All computed
    server-side in `fire_performance.py` and shipped via `/api/v3/active-trader/fire-performance`.

## Entitlement vs subscription vs freshness vs confirmation (T2)

These are FOUR different things and must never collapse:

| Concept        | Truth source                          | "yes" means                                        |
|----------------|---------------------------------------|----------------------------------------------------|
| Entitlement    | `gateway.entitlement_ok()` (ping)     | OpenD is logged in and serving quotes              |
| Subscription   | `SubscriptionManager.confirmed_*`     | OpenD accepted a real ORDER_BOOK/TICKER subscribe  |
| Freshness      | lifecycle FSM tick (book/tape age)    | a book/tape arrived within the stale threshold     |
| Confirmation=T2| `L2FeatureService.evaluate_t2`        | connected+entitled+confirmed+fresh+seq-ok+uncrossed|

**T2 requires ALL of them.** ARM_INTENT, a state file, or "armed" are none of these.

## New surfaces

- `GET /api/v3/active-trader/l2-status` and `/l2-status/{symbol}` — provider/entitlement/quota/
  per-symbol lifecycle/confirmed-subs/freshness/sequence/feature + `source_commit`, `read_only`,
  `write:false`, `order_path:false`.
- `GET /api/v3/active-trader/fire-performance` — active vs today's-history split with immutable
  fire facts + live marks + MFE/MAE/current-R.

## Remaining risks / not-done

- **No live OpenD integration proof in this environment.** All lifecycle/gate/feature logic is
  proven deterministically with a mock transport (`MockTransport`). The real futu adapter
  (`real_gateway_transport.py`) is fail-closed and reports "not connected" until a logged-in OpenD
  is present. **The consumer path is NOT claimed live** until an integration probe shows
  book+tape+quota round-trip. Do that on the host, out of band, before flipping any promotion.
- The read process's gateway is the read-plane owner. The scan-side arm-on-demand
  (`scalp_shadow_logger` → `moomoo_t2`) remains short-lived per cron. If both are made long-lived
  simultaneously, reconcile to ONE subscription owner first.
- `replenishment` / `cancellation_pressure` features require multi-snapshot delta history and are
  reported honestly as absent (never fabricated).

## Rollback

Pure additive + one honest tier change. To revert: `git revert` the four commits, or disable the
UI panels by not polling the new endpoints. The tier change defaults to byte-identical T0 while
promotion is off, so reverting it changes nothing at rest. No DB migration, no schedule, no deploy.

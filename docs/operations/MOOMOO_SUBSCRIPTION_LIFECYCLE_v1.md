# Moomoo / OpenD L2 Subscription Lifecycle — operations v1

Read-plane only. No order path, no trade unlock, no schedule change. Config:
`config/moomoo_l2_lifecycle.example.yaml` (schema `moomoo-l2-lifecycle-v1`).

## Single owner

Exactly one process-wide `QuoteGateway` owns exactly one `OpenQuoteContext`. The context is
constructed only in `scripts/moomoo/client.py:FutuTransport`; the gateway composes it via
`RealGatewayTransport`. No request handler, logger, test, script, or React component may open an
independent production `OpenQuoteContext`. Tests inject `MockTransport`.

Layers:
- `quote_gateway.py` — the owner. Bounded in-memory book/tape/quote buffers, PUSH-preferred
  ingest (`on_book_push`/`on_tape_push`/`on_quote_push`), pull fallback (`poll_book`). Nothing is
  written per-event to PostgreSQL.
- `subscription_manager.py` — the decision layer: quota truth + per-symbol FSM + dwell + reconnect.
- `l2_feature_service.py` — feature snapshot + the T2 admission gate.

## Quota semantics (SIMULTANEOUS, not daily calls)

`query_subscription(is_all_conn=True)` at startup/reconnect. The ledger tracks `total_quota`,
`total_used`, `remain`, `own_used`, `subscriptions_by_type`, `other_connection_usage`,
`last_queried_at`, `reserved_units`.

**Per-subtype accounting.** One L2 arm consumes one unit PER requested subtype. The example config
requests `QUOTE + ORDER_BOOK + TICKER` = **3 units/symbol**. So 8 L2 symbols is **24 units**, not 8 —
and 8 symbols × (ORDER_BOOK+TICKER) alone is 16 units. `max_concurrent_l2_symbols` (8) caps distinct
symbols; the quota caps units.

**Reservations.** `quota_reservations` carves out capacity (held positions / operator-selected /
active fires / reconnect recovery / emergency) BEFORE discretionary pre-fire arming. If a P1/P2
request would dip into the reserve, it becomes `QUOTA_DEFERRED` with the exact `required_units` +
`available_units` — never a silent eviction. P0 (open position, active fire, operator-selected)
bypasses the reserve carve-out.

## Per-symbol lifecycle (FSM)

`NOT_REQUESTED → ARM_INTENT → {QUOTA_DEFERRED | SUBSCRIBE_REQUESTED → SUBSCRIBED →
WAITING_FIRST_BOOK → (WAITING_FIRST_TAPE) → FRESH ⇄ STALE}` with failure branches
`SEQUENCE_GAP`, `CROSSED_BOOK`, `ENTITLEMENT_MISSING`, `PROVIDER_DISCONNECTED`, `FAILED`, and
release branches `POST_FIRE_RETENTION → UNSUBSCRIBE_PENDING → UNSUBSCRIBED`.

Per symbol we store: symbol, reason, priority, requested/confirmed subtypes, armed/subscribed/
first-book/first-tape/last-book/last-tape timestamps, provider_at, received_at, sequence_id,
reconnect_epoch, book_age_ms, tape_age_ms, quota_units, expires_at, error_code, error_detail.

**A state file may restore DESIRED intent after restart (ARM_INTENT), but file existence NEVER
implies connected/subscribed/fresh/T2/entitled.**

## Arm policy (pre-fire)

L2 is requested BEFORE the terminal FSM ARMED (the FSM cadence is multi-minute). Eligible pre-arm:
`setup_state==ARMED`, `fsm_state ∈ {PULLBACK, ARMED}`, `lane ∈ {IGN_45/60/75/ACCEL}`,
operator-selected, or an active fire retained for post-fire tracking. Priority P0 (open pos /
active fire / operator) > P1 (fsm ARMED / setup ARMED / IGN_ACCEL / IGN_75) > P2 (PULLBACK /
IGN_60 / IGN_45). Never subscribe: stale symbol, invalidated/expired setup, outside window, halted
without policy, no entitlement, or an arbitrary full scanner universe.

`L2_MOMENTUM` may NOT fire without fresh entitled ORDER_BOOK + TICKER. Other setups may use L2 as
confirmation, but its absence stays visible and is never fabricated.

## Dwell + post-fire retention + reconnect

- **Min dwell** (`min_subscription_dwell_seconds`, 60): a release within the dwell becomes
  `UNSUBSCRIBE_PENDING`; the real `unsubscribe` fires only once dwell elapses (via `tick`).
- **Post-fire retention** (`default_post_fire_retention_seconds`, 120): a fired symbol is held
  subscribed through the fire + retention window, then released.
- **Arm TTL** (`default_arm_ttl_seconds`, 180): a non-fire arm expires and releases.
- **Reconnect**: `on_reconnect` bumps `reconnect_epoch`, re-subscribes the DESIRED set exactly once
  each (no duplication), and resets per-symbol stream state so a post-reconnect lower sequence is
  NOT a false gap. The T2 gate rejects an epoch mismatch.

## Source / freshness contract (T2)

`evaluate_t2` returns T2 ONLY when: provider connected AND entitled AND ORDER_BOOK confirmed
(AND TICKER confirmed when tape required) AND healthy sequence AND matching reconnect epoch AND a
FRESH book AND a FRESH tape when required AND a non-crossed book. Otherwise a typed reason
(`STALE_BOOK`, `SEQUENCE_GAP`, `CROSSED_BOOK`, `WAITING_FIRST_DATA`, `TAPE_REQUIRED_MISSING`,
`ENTITLEMENT_MISSING`, `PROVIDER_DISCONNECTED`, …). `data_tier` is NEVER T2 merely because a
symbol is requested/armed.

## Live-mark contract

`LiveMarkResolver` resolves a current mark with EXPLICIT source priority
(`moomoo_subscribed` → gateway QUOTE/TICKER/top-of-book; else `approved_current_quote_provider`).
No averaging across sources. Every mark carries `source` + provider timestamp. A symbol with no
available source returns `available=false` — never a fabricated price.

## Promotion (data_tier)

`scalp_shadow_logger.effective_data_tier(cfg)` defaults T0. Promotion to T2 is an explicit
operator config act (`data_tiers.active_tier==T2` or `t2.feeds_scoring`). **Do not promote until an
integration probe proves live per-symbol book+tape+quota round-trip.** Promotion moves dcf 0.4→1.0
and assumed slippage 40→8 bps, which makes signals fire/size more — an operator decision.

## Rollback

Additive endpoints + UI; the tier change is byte-identical at rest while promotion is off. Revert
the branch commits or stop polling the new endpoints. No DB migration, no schedule, no deploy.

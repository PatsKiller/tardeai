# Alert Policy Diff

Source policy changed:

- `paper_proposal`, paper approval/lifecycle, blocked/rebuild/watch/expired/revalidated proposal states: Telegram OFF; Command Center or digest only.
- `APPROVALS_ONLY` is allowlist-only and requires explicit live authorization/order/session reference.
- `CRITICAL_OPERATIONS` handles live protection/auth/flatten/kill/outage incidents only when time-sensitive operator action is required.
- `P1_DIGEST` no longer means immediate send. The compatibility router returns `False` for `should_send_telegram()` on P1 and queues through the outbox.
- Scalp containment defaults:
  - `scalp_realtime_enabled: false`
  - `scalp_realtime_min_score: 45`
  - `scalp_send_on_critic_downgrade: false`
  - `scalp_send_on_critic_block: false`
  - `scalp_score_jump_telegram: false`
- Runtime activation flag added under `telegram_normalization.runtime_enabled: false`.

Preserved:

- No financial guardrail changes.
- No broker write path changes.
- Existing `/v3` Reports/System routes preserved.
- Existing proposal and broker-order deep links preserved.

Added:

- Canonical alert link: `https://ms01-openclaw.tail163d14.ts.net/v3/go/alert/<alert_id>`
- URL/message sanitizer for internal IPs, localhost, `:7777`, `/v2/`, raw OAuth URLs/state, filesystem paths, and shell commands.

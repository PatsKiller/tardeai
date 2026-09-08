# Lane I — Inbound normalization and consumption

Campaign `m2-canary-20260907`. Lease: `LEASE_MANIFEST_G_I_T.json` owner `I`.

## Path

```
Telegram callback/reply
  → inbound_event_normalizer.normalize_inbound_update
  → CommunicationEvent@v2 (stable event GUID; provider update/message ids preserved)
  → dedupe (checkpoint + provider key)
  → outbound/thread/subject/commitment correlation when available
  → sender allowlist + CANARY chat scope
  → inbound_consumption.process_inbound_update
  → AgentConsumptionReceipt@v2 (source_kind=comm_event, source_id=event_id)
```

## Honesty rules

- Default `effect_kind='none'`.
- `effect_kind='none'` **never** counts as behavioral consumption.
- Non-`none` effects require a resolvable `effect_ref`.
- No financial or broker action from this path.
- Fail closed on missing allowlist, identity, or persistence.

## Composition (not redefinition)

Lane I **imports** Lane B modules (`scripts.lib.comms.inbound`,
`scripts.lib.comms.agent_contracts`, client/delivery). It does not edit them.
Identifier minting remains in the frozen CampaignInterfaces / Lane B contracts.

## Configuration (tests / canary only)

| Env | Role |
|---|---|
| `COMMS_INBOUND_SENDER_ALLOWLIST` | Required sender ids (fail-closed if empty) |
| `COMMS_GATEWAY_CANARY_CHATS` | Required when mode=CANARY |
| `COMMS_GATEWAY_MODE` | OFF default; CANARY scopes chats |
| `COMMS_INBOUND_STATE_DIR` | Durable checkpoint dir (tmp in tests) |

## Runtime entry (poller hook)

Canonical feed for the approved Telegram long-poll daemon
(`scripts/run_telegram_` + `callback` + `_poller.py`):

```python
from scripts.lib import inbound_consumption
result = inbound_consumption.feed_telegram_update(update)  # never contacts Telegram
```

Reachability (integration-owner `tests/test_runtime_reachability.py` @ e0e943f9):
requires a BFS import/call chain from that daemon to `normalize_inbound_update`.
Lane-local `assert_inbound_runtime_reachability()` additionally requires the
daemon text to import `inbound_consumption` and call `feed_telegram_update`.

Dark-contract guard (`scripts/check_dark_contracts.py --fail-on-new`):
`InboundConsumption@v1` is NEW and fails until the daemon imports this module.

## Shared File Requests

- **SFR-I-RUNTIME-001** — wire the approved long-poll daemon to
  `from scripts.lib import inbound_consumption` and
  `inbound_consumption.feed_telegram_update(update)` (exact fragment in handoff).
  Do not create a second getUpdates consumer.
- Extend `LANE_HANDOFF_SCHEMA.json` / `LANE_EVIDENCE_SCHEMA.json` lane enum to include `I`.
- Extend `validate_leases.py` known owners to include `G`,`I`,`R`,`T`.
- Optional: claim-registry + prompt seal for Lane I (integration owner).

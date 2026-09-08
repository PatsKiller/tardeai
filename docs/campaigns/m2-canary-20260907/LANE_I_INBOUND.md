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

## Shared File Requests

- Extend `LANE_HANDOFF_SCHEMA.json` / `LANE_EVIDENCE_SCHEMA.json` lane enum to include `I`.
- Extend `validate_leases.py` known owners to include `G`,`I`,`R`,`T`.
- Optional: claim-registry + prompt seal for Lane I (integration owner).

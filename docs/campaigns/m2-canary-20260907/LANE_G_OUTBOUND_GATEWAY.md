# Lane G — Outbound CANARY gateway path

Campaign `m2-canary-20260907`. Baseline `54639ff5aaae0e3f56e6e0a327a7c99c06c5d466`.

## Path

```
agent output
  → CommunicationEvent@v2 (GUID, subject_guid, thread_id, correlation_id)
  → ownership decision (gateway | legacy)
  → channel formatting (Telegram)
  → durable ChannelDelivery RESERVED
  → injected Telegram transport
  → provider acknowledgement (provider_message_id)
  → SETTLED
```

## Modules (leased)

| Path | Role |
|---|---|
| `scripts/lib/agent_gateway_adapter.py` | Build event + ownership + CC link |
| `scripts/lib/gateway_settlement.py` | Reserve → transport → settle |
| `tests/test_agent_gateway_adapter.py` | Adapter proofs |
| `tests/test_gateway_settlement.py` | Settlement + idempotency proofs |

## Contracts consumed (not edited)

Lane B `scripts/lib/comms/**`: `CommunicationEvent`, `publish_communication`,
`reserve_delivery`, `settle_delivery`, `render_for_channel`,
`telegram_class_allowed`, `validate_link`, `COMMS_GATEWAY_MODE` /
`COMMS_GATEWAY_CANARY_CLASSES` / `COMMS_GATEWAY_CANARY_CHATS`.

## Ownership

- **Gateway** only when `COMMS_GATEWAY_MODE=CANARY` (or ACTIVE) **and** the
  message class is on the explicit allowlist (`COMMS_GATEWAY_CANARY_CLASSES`).
- When `COMMS_GATEWAY_CANARY_CHATS` is set, requested chat ids must intersect
  that allowlist or delivery fails closed (`delivery_blocked_canary_chats`)
  **after** RESERVED and **before** transport.
- Otherwise **legacy**, with a recorded reason (`canary_allowlist_empty`,
  `class_not_in_canary_allowlist`, `mode_off_not_delivery_owner`, …).
- Unexplained legacy fallback is a defect; every legacy path carries `reason`.
- CANARY configuration alone is never evidence of delivery ownership.

## Fail-closed

Missing `subject_guid`, authoritative sources, body, CC `/v3/` link contract,
persistence failure, missing injected transport when `deliver=True`, or missing
`provider_message_id` after ack → refuse / FAILED. No credentials in source,
fixtures, logs, or evidence.

## Transport isolation

`deliver_agent_outbound(..., deliver=True)` **requires** an injected `transport`
callable. This lane never opens a network socket and never reads bot tokens.
Live wiring of the approved Telegram adapter is an integration Shared File
Request (wake / telegram_alert call site), not a Lane G lease edit.

## Idempotency

Retry of the same agent outbound (same event identity after publish collide, or
cached SETTLED index) does not invoke transport again and does not mint a second
provider settlement.

## Runtime reachability (follow-up)

Canonical factory: `build_wake_outbound_handler` in `gateway_settlement.py`.

Signature for `WakeEngine._outbound` (already present after SFR-G-002):

```python
handler(wake=wake, receipts=receipts) -> dict
```

Gates:
1. `PERSISTENT_WAKE_GATEWAY_OUTBOUND=1`
2. `COMMS_GATEWAY_MODE` in `{CANARY, ACTIVE}`
3. explicit `deliver=True` (or `PERSISTENT_WAKE_GATEWAY_DELIVER=1`)
4. valid wake provenance → `AgentOutboundRequest`
5. transport = injected fake (tests) or `sanctioned_telegram_transport` (reuses
   `telegram_alert._raw_send_telegram_result`; requires `ENABLE_TELEGRAM` + token)
6. class/chat allowlists + provider acknowledgement

`SFR-G-003` injects the factory from `run_persistent_wake.py`. Without that SFR
the hook stays `None` and soak `gateway_settlements` remains 0.

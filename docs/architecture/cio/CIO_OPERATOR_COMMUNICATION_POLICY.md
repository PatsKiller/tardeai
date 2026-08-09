# CIO Operator Communication Policy

**Document ID:** CIO-COMM-001  
**Version:** 1.0.0  
**Owner:** Trade AI CIO Agent  
**Date:** 2026-08-08

## 1. Core Principle

ALL messages to the operator originate from durable CIO state (the notification outbox). No raw LLM output is ever sent directly to the operator. Every message has a deterministic, hash-verified provenance chain.

## 2. Message Classes

| Class | Trigger | Severity | Dedupe Window |
|-------|---------|----------|--------------|
| `advisory` | CIO run produces action | P2 | 24h per action |
| `alert` | Health boundary detects critical issue | P0-P1 | 1h |
| `status` | Scheduled check-in | INFO | Per slot |
| `checkin` | Daily/weekly summary | INFO | Per slot |
| `confirmation_request` | Material action needs operator approval | P1 | Per action ID |
| `data_quality_block` | Health boundary blocks advisory | P0 | Per decision ID |
| `data_quality_recovered` | Health boundary clears | P1 | Per decision ID |
| `followup_due` | Deferred action follow-up | P2 | Per action ID |
| `specialist_complete` | Handoff to specialist completed | P2 | Per handoff ID |
| `system_notice` | System-level notification | INFO | Per event |

## 3. Material Recommendation Format (8-point checklist)

Every material CIO recommendation sent to the operator MUST include:

1. **CIO run ID** — unique run identifier
2. **Snapshot reference** — canonical evidence snapshot ID + hash
3. **Domain** — relevant CIO domain(s)
4. **Recommendation** — clear, specific recommended action
5. **Rationale** — evidence-based reasoning
6. **Confidence** — 0.0-1.0 from synthesis
7. **Operator action needed** — explicit yes/no/optional
8. **Deadline** — when action is needed (if applicable)

## 4. Deduplication Rules

- Messages deduplicated by `dedupe_key` (computed from content hash)
- Window: 24 hours for advisory, 1 hour for alerts
- Same action ID + same content = suppress
- Different action ID = always send

## 5. Expiry

- Advisory: 24 hours (shadow mode), 72 hours pending live
- Alerts: 1 hour
- All others: 24 hours
- Expired notifications are not delivered

## 6. Quiet Hours / Digest Policy

- No financial advisory messages between 22:00-06:00 ET
- Alerts (P0/P1) bypass quiet hours
- Daily digest at 06:00 ET for batched updates

## 7. Sensitive Content Rules

- Never send: account numbers, SSNs, passwords, 2FA codes, API keys
- Never send: exact order instructions (messages are advisory only)
- Rich text via Telegram HTML parse mode

## 8. Inbound Operator Request Handling

- Inbound messages are routed through Alex → CIO handoff
- Never auto-execute from inbound messages
- Inbound text is captured, hashed, and stored in handoff queue
- Responses go through the CIO synthesis pipeline (not direct reply)

## 9. Delivery Channels

| Channel | Status | Authorization Required |
|---------|--------|----------------------|
| Telegram (shadow) | Built, tested | AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY |
| Telegram (live) | Built, not activated | AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY |
| Command Center | Future | N/A |

## 10. Forbidden Message Types

The following are NEVER sent through the notification system:
- Execute trade instructions
- Order submissions
- Risk overrides
- 2FA codes
- Credential requests
- Secret deliveries

# Rejection Classifier Spec — Stage 3

**Version:** stage3-v1.0 · Code: `scripts/active_trader/rejections.py`

## Input (redacted before entering the dataclass)
`RawBrokerEvent`: broker · account_label · masked_account_id (re-masked defensively) ·
symbol · order_intent_id · raw_status · raw_code · raw_message · http_status ·
order_state · filled_quantity · remaining_quantity · observed_at · adapter_version ·
provenance (CAPTURED_REDACTED | SYNTHETIC | SYNTHETIC_FUTURE_ADAPTER).
Redaction: bearer/authorization/api-key/token values always; 8+ digit runs in free-text
messages only (structured broker codes survive for exact-rule matching).

## Output
`Classification`: normalized_code · retryable · requires_operator ·
requires_broker_call · affected_capability · scope (symbol/account/account+symbol/
session/none) · confidence (EXACT_CODE/MESSAGE_PATTERN/STRUCTURAL/FALLBACK) ·
matched_rule_id · classifier_version · reason · retry_backoff_seconds (RATE_LIMITED only).

## Rule pipeline (ordered by specificity; deterministic; fixture-covered)
1. **EXACT_CODE** (broker-scoped): AL-EX-001..003, SW-EX-001, MM-EX-001..002
2. **MESSAGE_PATTERN** (broker-scoped, narrow needles): SW-PT-001..007, AL-PT-001..008,
   MM-PT-001..002, cross-broker XB-PT-001..002 (halted, wash-trade)
3. **STRUCTURAL** (cross-broker): 401/403→AUTHENTICATION_EXPIRED · 429→RATE_LIMITED
   (backoff 30 s) · order_state STALE→STALE_ACCOUNT_STATE (backoff 10 s)
4. **FALLBACK**: XB-FB-000 → UNKNOWN_BROKER_REJECTION (never retryable, operator-required)

Invariants (constructor-enforced, tested):
- UNKNOWN_BROKER_REJECTION can never be retryable.
- RATE_LIMITED may be retryable only with bounded backoff metadata; automatic broker
  failover on RATE_LIMITED is false by default (not in any policy allowlist by default).
- AUTHENTICATION_EXPIRED is never retried in the order path (managed reauth owns it).
- Exact code beats message pattern; broker patterns never cross brokers; case/spacing
  normalized without overmatching ("brokerage account statement" stays UNKNOWN).
- No raw-message substring causes any action by itself — the classifier only labels;
  actions live in the separately-tested fallback evaluator and notification policy.

## Capability impact projection
A classification with `affected_capability` may emit a `CapabilityEvidenceProposal`:
RESTRICTED-only (a rejection can never grant), explicit scope (one symbol's rejection
restricts that symbol+account only; one account never restricts another), idempotency
key over (broker,account,capability,scope,symbol,source-event), review expiry, and an
auditable link (`capability_evidence_ref`) on the persisted rejection row. It never
mutates the capability registry directly, and accepted higher-confidence evidence is
never silently overwritten (proposals are additive rows for later adjudication).

## Persistence (lab only)
`persist_rejection` upserts on the raw-event idempotency key: replay increments
`occurrence_count` on the single row (no duplicates), stores redacted raw fields,
normalized result, classifier version, matched rule, confidence, evidence hash,
first/last seen, notification_state, fallback_state, capability_evidence_ref.

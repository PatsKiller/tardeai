# Fallback Policy — Stage 3

Code: `scripts/active_trader/fallback.py` · PURE model/evaluator — submits nothing,
calls no broker, requests no 2FA. Session 2FA and broker submission are later stages.

## Policy model (typed, validated)
`FallbackPolicy`: session_authorization_id · source_account_id · fallback_account_id ·
priority · **allowed_normalized_codes (must be explicit — empty list rejected)** ·
max_fallback_shares/notional/risk (non-negative) · auto_failover ·
requires_operator_confirmation · expires_at · policy_version.

## Evaluator gates (strict order; first failure decides)
1. **Source finality** — the very first gate: SUBMITTED/ACCEPTED/PENDING_REPLACE/
   PENDING_CANCEL/PARTIALLY_FILLED_WITH_UNCONFIRMED_REMAINDER →
   WAIT_FOR_SOURCE_FINALITY; UNKNOWN/STALE/BROKER_UNREACHABLE → BLOCKED;
   unconfirmed fill quantity → BLOCKED. Automatic fallback is possible only from
   REJECTED_WITH_ZERO_FILL / CANCELLED_WITH_CONFIRMED_FILL_QUANTITY /
   EXPIRED_WITH_CONFIRMED_FILL_QUANTITY.
2. **Envelope membership** — account not in signed envelope → REAUTHORIZE_SESSION
   (pause symbol, notify, display alternates, amendment + new 2FA later — projection
   `unapproved_alternate_projection`); not marked FALLBACK → NO_FALLBACK; no policy /
   expired policy → NO_FALLBACK.
3. **Rejection class** — normalized code must be in the policy allowlist.
4. **Eligibility** — fallback capability must be SUPPORTED (UNKNOWN/RESTRICTED fail);
   symbol eligibility must be affirmatively true (None/unknown fails).
5. **Session validity** — time bounds, market thesis, trade count.
6. **Quantity/risk reconciliation** — see DUPLICATE_FILL_PREVENTION.md.
7. **Mode** — auto_failover without operator confirmation → AUTO_FAILOVER_ELIGIBLE;
   otherwise PROMPT_OPERATOR.

Decisions: AUTO_FAILOVER_ELIGIBLE · PROMPT_OPERATOR · REAUTHORIZE_SESSION ·
WAIT_FOR_SOURCE_FINALITY · NO_FALLBACK · BLOCKED — each with deterministic reason
codes and an idempotency key (same inputs → identical result, tested).

## Defaults of record
- RATE_LIMITED and UNKNOWN are not in any default allowlist → automatic broker
  failover on them is impossible without an explicit operator policy change.
- Stage 3 market/risk state is synthetic; the evaluator takes it as typed input only.

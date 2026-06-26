# Order Lifecycle

States: PROPOSED → PREFLIGHTED → OPERATOR_APPROVED → SUBMIT_REQUESTED → BROKER_ACKED →
WORKING → PARTIALLY_FILLED → FILLED (or CANCELLED / REJECTED / EXPIRED / ERROR_RECONCILE_REQUIRED).

No trade is live before broker ack. Idempotency key on intent_id+account+symbol.

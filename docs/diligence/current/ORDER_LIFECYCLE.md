# Order Lifecycle

Status:      ACTIVE
as_of:       2026-06-27T22:07:55-04:00
Measured at: efcc51365 / not measured

_Generated: 2026-06-28T02:06:07.289867+00:00_
_Source: `brokers/order_lifecycle.py + brokers/reconcile_orders.py`_
**Status: PASS**

No trade is live before broker acknowledgement. Internal state never outruns broker truth.

States: PROPOSED → PREFLIGHTED → OPERATOR_APPROVED → SUBMIT_REQUESTED → BROKER_ACKED →
WORKING → PARTIALLY_FILLED → FILLED (or CANCELLED / REJECTED / EXPIRED / ERROR_RECONCILE_REQUIRED).

Broker status taxonomy → lifecycle state: queued/accepted/pending_activation → BROKER_ACKED;
working → WORKING; partially_filled → PARTIALLY_FILLED (preserved); filled → FILLED;
canceled → CANCELLED; rejected → REJECTED; expired → EXPIRED; unknown → ERROR_RECONCILE_REQUIRED.

- FILLED/WORKING/PARTIALLY_FILLED require a broker order id (proof of ack).
- Idempotency key = sha256(intent_id|account|symbol); duplicate active submits are fenced.
- Stale SUBMIT_REQUESTED requires reconcile (GET broker truth) before any retry — never blind-retry.
- Reconciliation report → `data/runtime/reconcile_orders_<date>.json`; result recorded to the audit ledger.

# Durable coordination ledger

Dated 2026-10-07. The served gateway path is still the in-memory store. `durable` on its receipt remains false. A sqlite proof in a unit test is not a served restart and is not a consumer acknowledgment.

## Why this is not the existing outbox

Three stores were considered and not extended:

- `communication_deliveries` is the production send ledger. A coordination nonce there would couple the lab to a live delivery table, and this pass has no db-write grant.
- `scripts/lib/cio_notification_outbox.py` is the operator-notification log. Its channels include telegram. A nonce does not belong there.
- `scripts/lib/cio_action_ledger.py` is the CIO action log. Mixing HMAC replay state into CIO actions would make a lab claim look like an operator action.

`scripts/lib/n8n_coordination_ledger.py` is a separate sqlite file the gateway process does not open unless a later, reviewed install points it there. The default server in `scripts/n8n_coordination_gateway.py` still uses process memory.

## What the file proves

One transaction inserts the nonce, the event, and a single source-side effect, or it rolls back. A crash before commit leaves no nonce and no effect. After the process reopens the file, the same idempotency key with a new nonce is a duplicate and does not add a second effect. The same nonce is `replayed_nonce`. Two connections racing the same nonce leave one effect. The receipt field `durable` is still false, `exactly_once_scope` is `source_side_file_only`, and `external_delivery` is `NOT_CLAIMED`. Retries toward n8n or a provider may be at least once. This ledger does not say otherwise.

The row can store source SHA, served SHA, workflow version, attempts, expiry, a terminal result, a typed refusal, a dead-letter flag, and a consumer id. `CONSUMED` requires a consumer and a receipt id.

Payloads over 65,536 bytes are refused. A caller is limited to 30 accepts in 60 seconds inside this file.

## Authentication

See `docs/architecture/n8n/ADR_COORDINATION_SECRETS.md`. Summary: 127.0.0.1 is a bind constraint. Proxy headers are not identity. The HTTP layer rejects an unknown method, a percent-encoded or `..` path, an oversized body, and invalid UTF-8. During key overlap the server can verify the current key or `TRADEAI_N8N_GATEWAY_HMAC_KEY_PREVIOUS`. The seed is not written to the ledger. A reference token is returned once; only its hash is stored. Redeeming it cannot change lane or project, cannot mint a claim, and does not return the HMAC key.

HMAC material has not been installed in n8n. A workflow that held either the seed or a bearer claim would copy that material into execution data. That install is BLOCKED_POLICY. The five pilots stay fixture-only.

## DOF

No ownership change and no GRANT were applied. The proposed least-privilege shape lives on the DOF policy branch, not as a binding rule. The gateway's forbidden-route list still includes `sql` and `postgres`. There is no DOF production route.

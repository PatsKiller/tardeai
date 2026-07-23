# Broker Discovery Contract — Stage 2

**Run ID:** 20260722-01 · Code: `scripts/active_trader/discovery*.py`, `probe_brokers.py`

## Interfaces (adapter-neutral, READ-ONLY by construction)
Implemented discovery surface per broker: `discover_accounts` (fleet `discover()`),
`read_account`, `read_balances`, `read_positions`, `read_open_orders`,
`read_capabilities` (capability grading), `validate_symbol_read_only` (safe asset /
market-hours lookup), `authentication_health` (auth state per account),
`stream_health` (Schwab: existing stream lane noted; not probed live in Stage 2 —
STREAM_ORDER_EVENTS stays UNKNOWN). **No write method exists anywhere in the
discovery service**; the Schwab test transport proves discovery never requests one.

## Result shape (every adapter)
`DiscoveredAccount`: broker · account_label · masked_account_id (constructor rejects
unmasked digits) · environment (SHADOW/SIMULATION/LIVE, explicit) · account_type ·
status (ACTIVE/INACTIVE/NOT_CONFIGURED/NEEDS_MAPPING/ERROR) · read_state
(OK/PARTIAL/UNAVAILABLE) · authentication_state (OK/NOT_CONFIGURED/EXPIRED/ERROR) ·
capabilities[] (Stage 1 `BrokerCapability`) · evidence{} · observed_at · expires_at ·
credential_slot (names only).

## Capability rules enforced
- States: SUPPORTED/UNSUPPORTED/UNKNOWN/DEGRADED/RESTRICTED (Stage 1 enum).
- Evidence sources: DOCUMENTATION / RUNTIME_READ_PROBE / EXISTING_ADAPTER /
  BROKER_RESPONSE / OPERATOR_OVERRIDE (DB mapping documented in discovery.py).
- Expiry by source: RUNTIME_READ_PROBE = 24 h configurable · EXISTING_ADAPTER =
  version stamp required + 30-day review · DOCUMENTATION = review date required ·
  OPERATOR_OVERRIDE = explicit expiry required. Expired ⇒ effective UNKNOWN, never
  silently SUPPORTED.
- UNKNOWN never becomes SUPPORTED by inference; per-account isolation (no
  cross-account inheritance); paper never implies live; read never implies write;
  adapter-source-existence proves nothing; **a write capability can never be
  evidenced by a read probe** (factory-enforced) and no write endpoint is callable.

## Compatibility with existing registries
`scripts/brokers/capabilities.py`, `capability_gate.py`, `pilot_caps.py`, and the
`broker_capability_checks` table are UNTOUCHED. Stage 2 grades Schwab write
capabilities FROM those fences (RESTRICTED where a built path is deliberately
fail-closed — the Stage 2c protective-stop lane; UNKNOWN otherwise) instead of
replacing them. Conflict policy: none detected this stage; future conflicts are to be
documented in BROKER_CONFIGURATION_DISCREPANCIES.md, never silently resolved.
Persistence goes to the Stage 1 `broker_account_capabilities` table in the LAB
database only (idempotent upsert on the (broker, account, environment, capability)
PK, sha256 evidence_ref, adapter_version='stage2').

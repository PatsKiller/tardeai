# ADR-B1: Broker Abstraction Layer

**Status:** ACCEPTED (2026-06-11, operator-approved phase) · **Decision drivers:** Phase-1 coupling findings;
the Schwab write fence (12/12) must remain untouched; future brokers.

## Decision
Introduce `scripts/brokers/` — a broker-agnostic layer with seven interfaces, extending (not replacing) the
existing `broker_adapter.py` Protocol and `broker_config.py` account resolution:

| Interface | Responsibility | Existing code it wraps |
|---|---|---|
| `BrokerAuthProvider` | token/key acquisition + health | schwab_token_manager / env keys |
| `BrokerAccountService` | account discovery, balances, positions | schwab_transport reads / alpaca adapter |
| `BrokerMarketDataAdapter` | quotes, bars, hours | ohlc_charts tiers / schwab_transport |
| `BrokerOrderTranslator` | canonical OrderIntent → broker payload (PURE, no I/O) | NEW |
| `BrokerOrderAdapter` | submit/replace/cancel/status (I/O) | alpaca adapter; Schwab = BLOCKED stub |
| `BrokerExecutionGuard` | fail-closed mode gating + audit | generalizes dry_run_bracket + live_trading_gate |
| `BrokerCapabilityRegistry` | per-broker feature truth for UI/validation | NEW |

## Rules (non-negotiable)
1. **Translators are pure functions** — they emit payload dicts and never perform I/O. The Schwab translator
   therefore cannot violate the write fence by construction; the no-writes validator stays 12/12 because
   `scripts/brokers/` never imports schwab-py nor calls transport write methods.
2. **The guard wraps every adapter call.** No code path may reach `BrokerOrderAdapter.submit` without
   `BrokerExecutionGuard.authorize()` returning an explicit grant; absence of config = BLOCKED (fail-closed).
3. **Alpaca paper training is its own mode** (`PAPER_TRAINING`), permanently distinct from any Schwab mode —
   the training pipeline is never re-pointed by registry/flag changes.
4. **Capability truth lives in one place** (the registry). UI, validation, and translators all consult it;
   no scattered `if broker == ...` checks.

## Alternatives considered
- Extending alpaca_paper_adapter with broker switches — rejected (deepens the coupling Phase 1 documented).
- Forking a separate Schwab pipeline — rejected (duplicates gates/risk/audit; divergence risk).

## Consequences
- Alpaca behaviors (separate-stop placement, order-anchored promotion, fill tolerances) become adapter
  details behind the interfaces; business logic targets the canonical model only.
- Adding a broker = translator + capabilities + adapter stub + registry entry; no business-logic edits.

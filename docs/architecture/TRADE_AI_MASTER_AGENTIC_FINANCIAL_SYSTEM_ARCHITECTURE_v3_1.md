# TRADE AI MASTER AGENTIC FINANCIAL SYSTEM ARCHITECTURE v3.1
## Canonical v3.1 amendment and artifact index

**Status:** OPERATOR-APPROVED ARCHITECTURE AMENDMENT  
**Date:** 2026-07-22  
**Supersedes:** `TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_0.md` where this amendment conflicts.  
**Full canonical artifact SHA-256:** `db27d6e9d9a48e904cd5d4efda53b176632ba328a457b600c1e6c75c5737d497`  
**Full canonical Drive artifact:** `https://drive.google.com/file/d/1b2tK9CviygPT2PcWPXymflwdNollTLPw/view`

The complete 2,900-line v3.1 master document is stored in the canonical Drive architecture folder. This repository entry records the controlling amendment, artifact identity, and implementation rules so the authorization boundary is auditable in Git.

## Architecture-owner approval

The architecture owner explicitly approves:

1. the Moomoo momentum-scalp live-canary phase;
2. automatic live scalp entries, modifications, broker-native protection, scale-outs, deterministic exits, and reconciliation;
3. one operator 2FA ceremony at the start of a bounded live scalp session instead of per-order 2FA for each scalp order;
4. deterministic enforcement of the signed session authorization envelope on every order;
5. immediate session revocation and kill-switch authority.

No future financial guardrail change is authorized without explicit architecture-owner approval in a versioned amendment.

## Controlling live authorization rule

Per-order 2FA remains the default for non-simulation trading. The approved exception is:

```text
MOMENTUM_SCALP_LIVE_SESSION
```

One successful operator 2FA ceremony activates a signed session. While that session is valid, the deterministic momentum-scalp engine may auto-trade without additional per-order 2FA.

Every order must bind to:

```yaml
session_authorization_id:
strategy: MOMENTUM_SCALP
broker:
account_ids: []
allowed_symbols: []
candidate_rule_version:
ticket_policy_version:
session_start:
session_entry_cutoff:
session_expiry:
max_trades:
max_concurrent_positions:
max_gross_notional:
max_notional_per_trade:
max_risk_per_trade:
max_daily_loss:
max_chase_bps:
max_order_ttl_seconds:
allowed_order_types: []
required_protection:
live_arm_token_hash:
operator_id:
2fa_verification_ref:
authorization_hash:
status:
```

The allowed universe may be an explicit symbol list or a deterministic dynamic-universe rule whose version, limits, and maximum symbol count are included in the signed envelope.

Inside the envelope, the engine may automatically:

- select and arm qualifying momentum candidates;
- compile and independently validate tickets;
- submit live entries;
- manage partial fills and bounded limit repricing;
- install broker-native or independently survivable protection;
- scale out;
- execute deterministic thesis, risk, emergency, and session-close exits;
- cancel or replace orders required by the approved strategy;
- reconcile broker orders and positions.

The session does not authorize:

- another strategy, broker, or account;
- symbols outside the signed universe;
- positions or losses above the signed limits;
- entries after the entry cutoff;
- changed strategy, candidate, ticket, risk, or chase-policy versions;
- weakened protection;
- LLM-originated orders;
- unrelated discretionary trading.

A material envelope change requires revocation and a new 2FA ceremony.

When the entry window closes, no new positions may open. Existing session-authorized positions remain protected and may be managed automatically until flat. Every live scalp order must carry the session ID and authorization hash. An order without a valid matching authorization is rejected before the adapter.

## Approved live-canary state machine

```text
SESSION_2FA_PENDING
  → SESSION_AUTHORIZED
  → CANDIDATE
  → ARMED
  → FIRED
  → LIVE_STAGED
  → SESSION_POLICY_CHECK
  → WORKING
  → FILLED
  → PROTECTED
  → MANAGING
  → EXITING
  → FLAT
```

No per-order 2FA occurs after `SESSION_AUTHORIZED` while the envelope remains valid.

## Live-canary readiness gate

Architecture approval is granted. Activation requires recorded proof of:

- production-ready Moomoo live adapter;
- operator-present Moomoo trade-unlock ceremony where required;
- session-scoped 2FA and authorization-hash enforcement;
- broker-native or equivalent survivable protection;
- account and PDT/day-trade review;
- UPS, network, clock, and reconnect health;
- positive shadow and simulation evidence;
- fill/slippage review;
- idempotent order submission;
- order and position reconciliation;
- hard daily-loss, notional, trade-count, concurrent-position, and chase limits;
- operator-visible arm, status, revocation, and kill switch;
- smallest live symbol/universe and notional canary;
- automated post-session closeout.

## Acceptance invariants

```text
LIVE ORDERS OUTSIDE VALID PER-ORDER OR SESSION AUTHORIZATION: 0
SESSION-AUTHORIZED ORDERS WITHOUT MATCHING SESSION HASH: 0
ORDERS AFTER SESSION ENTRY CUTOFF: 0
SESSION LIMIT BREACHES REACHING ADAPTER: 0
REFLECTIVE AGENT BROKER CALLS: 0
LIVE SCALP WITHOUT BROKER PROTECTION: 0
```

## Unchanged constitutional boundaries

- Deterministic validation, risk, broker reconciliation, and execution services remain authoritative.
- No LLM runs in the tick, fire, stop, broker-write, kill-switch, or protective path.
- Bitwarden Secrets Manager remains the only credential store.
- The implementation still proceeds through Moomoo data capture, replay, shadow, and simulation before the live canary readiness gate.
- The architecture owner controls financial guardrail changes.

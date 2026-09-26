# TradingSessionGrant@v1 — contract and enforcement point

```
Contract:     TradingSessionGrant@v1 (+ TradingMutationRequest@v1, TradingAuthorizationDecision@v1)
Status:       PROPOSED with AGENTS.md 1.3.0 — verifier built and tested, NOT wired
Owner:        operator (limits, entry points, contract changes are §17)
Implementer:  scripts/lib/trading_session_grant.py (pure; no broker import, no I/O)
Envelope:     scripts/active_trader/session_control.py (build_envelope, compute_authorization_hash)
Tests:        tests/test_trading_session_grant_20260925.py
Base-SHA:     1c60ecb4264ba4dcc6a38106e76fae0d96a26787
```

Architecture v3.3 §1.2 requires that "an order that cannot prove current authorization is
rejected before the adapter." The P3 session-control plane builds and hashes the envelope, but no
code checked an individual broker mutation against it. This contract defines that check and where
it must run.

## 1. What a live session binds

The envelope fields and their hash are **session_control's**, unchanged — one hash definition. The
grant adds the authorization facts that describe the ceremony, not the trading bounds.

| group | fields | source |
|---|---|---|
| identity | `session_id`, `operator_identity`, `twofa_verification_ref` (a reference to the 2FA ceremony record, never a code) | grant |
| broker scope | `brokers[]`, `account_ids[]` | envelope (hashed) |
| strategy | `strategy`, `setup_ids[]`, `setup_versions[]`, `registry_hash` | envelope (hashed) |
| symbols | `symbol_list_or_universe_rule` — `symbols:A,B` (explicit) or `universe:<rule>` (versioned by `candidate_policy_version`; each request must carry `universe_membership_ref`) | envelope (hashed) |
| time | `session_start`, `entry_cutoff`, `expiry`, `allowed_sessions[]` | envelope (hashed) |
| limits | `max_trades`, `max_concurrent_positions`, `max_gross_notional`, `max_notional_per_trade`, `max_risk_per_trade`, `max_daily_loss`, `max_chase_bps`, `max_order_ttl_sec` | envelope (hashed) |
| order policy | `allowed_order_types[]`, `required_protection[]` | envelope (hashed) |
| policy versions | `candidate_policy_version`, `risk_policy_version` | envelope (hashed) |
| integrity | `authorization_hash` (recomputed, must equal the signed `authorized_hash`) | envelope + grant |
| revocation | `state` (session_control lifecycle), `revoked_at`, `kill_switch_exit_only` | grant |

**Gap versus v3.3 §1.2, recorded rather than silently filled:** v3.3 also lists
`ticket_policy_version`, `model_review_policy` and `live_arm_token_hash`, which session_control's
`ENVELOPE_FIELDS` does not hash yet. Adding them changes the hash contract, so it is a follow-up
change to session_control, reviewed on its own.

## 2. Mutation classes and the rules

| class | allowed when | refused when |
|---|---|---|
| `ENTRY`, `MODIFY` (can add exposure) | state `ACTIVE`, `session_start ≤ now < entry_cutoff < expiry`, symbol in scope, order type allowed, every limit set and not exceeded | any check fails; any limit unset → `OPERATOR_DECISION_REQUIRED` |
| `CANCEL`, `PROTECTION`, `EXIT` (reduce or protect) | state `ACTIVE`, `ENTRY_CUTOFF`, `DRAINING`, `PAUSED`, `REVOKED` or `KILLED`, on a position **this session opened**; `EXIT` qty ≤ held; no added notional or risk | position not the session's; exposure would grow; envelope altered |

Every class must also pass:
- **Caller:** the entry point is in `DETERMINISTIC_ENTRY_POINTS` (today only
  `deterministic_execution_path`), and the origin is not `llm`.
- **Replay:** the `request_id` hasn't been seen before.
- **Session:** session id matches, a 2FA reference is present, and the envelope recomputes to the
  signed hash, which the request also carries.
- **Scope:** broker, account, strategy and policy versions match.

**Why exits survive a stopped session:** v3.3 §1.4 — "Session revocation never removes protection
from an open position." **Why a tampered envelope blocks exits too:** a hash mismatch proves
nothing about the session. Those exits fall back to the normal per-order authority.

## 3. Enforcement point (where it gets wired after ratification)

Under the ACTIVE AGENTS.md (§0 rule 2), broker code may not be modified yet, so none of these call
sites was edited. Line numbers are at `1c60ecb42`.

| layer | call site | action today | wiring after 1.3.0 |
|---|---|---|---|
| **chokepoint** | `scripts/brokers/execution_guard.py:304` `require(intent, action)` | canary/protective gates → standing locks → caps → 2FA | if `intent` carries `session_authorization_id`: build the `MutationRequest` from the intent and refuse unless `verify_mutation(...)` allows. Per-order-2FA intents keep today's path. |
| Schwab submit | `scripts/schwab_transport.py:101` `place_order` → `require(intent,"submit")` at `:137` | pilot stack | covered by the chokepoint |
| Schwab cancel | `scripts/schwab_transport.py:437` `cancel_order` → `require(intent,"cancel")` at `:493` | pilot stack | covered by the chokepoint (class `CANCEL`) |
| Schwab replace | `scripts/schwab_transport.py:525` `replace_order` | raises `NotProvenWrite` | stays refused until a proven replace exists, then class `MODIFY` |
| SnapTrade submit | `scripts/brokers/snaptrade_transport.py:31` → `require` at `:34` | 2FA + envelope | covered by the chokepoint |
| SnapTrade protective | `scripts/brokers/snaptrade_protective_stop_pilot.py:77-78` | `require` | covered (class `PROTECTION`) |
| Moomoo | `scripts/moomoo/client.py:420` `place_order` | raises (Stage 0) | wired when Moomoo reaches its trade stage (v3.3 §1.5) |
| adapter stubs | `scripts/brokers/schwab_order_adapter.py:18-20` | raise `ExecutionBlocked` | unchanged |
| simulation | `scripts/active_trader/sim_execution.py` | simulated fills | **wire here first** (A2), so the negative matrix runs end to end on `SIM_BROKER` before any live adapter changes |

The contract of the wiring: the verifier runs **inside the process that performs the mutation**,
immediately before the adapter call. A terminal hook, an API route or a UI can never stand in for
it, because each of those can be bypassed by calling the adapter directly (review finding 6).

## 4. Values the operator must decide (the verifier never defaults them)

Each is `OPERATOR_DECISION_REQUIRED`. An envelope missing any of them refuses every entry.

| decision | notes |
|---|---|
| live broker(s) and account id(s) for the canary | v3.3 suggests the smallest approved taxable account |
| symbol scope | explicit list, or a named universe rule and its version |
| `session_start`, `entry_cutoff`, `expiry`, `allowed_sessions` | per session |
| `max_trades`, `max_concurrent_positions` | |
| `max_gross_notional`, `max_notional_per_trade` | |
| `max_risk_per_trade`, `max_daily_loss` | |
| `max_chase_bps`, `max_order_ttl_sec` | |
| `allowed_order_types`, `required_protection` | |
| `DETERMINISTIC_ENTRY_POINTS` | only `deterministic_execution_path` today; widening is §17 |
| how `usage` counters are sourced (broker reconciliation vs journal) | must come from reconciled broker state, not an agent |

## 5. Proven by tests (`tests/test_trading_session_grant_20260925.py`, 26 cases)

**Refused:**
- the session is expired, revoked, past its entry cutoff, or in exit-only kill
- wrong broker, account, symbol or order type
- a missing universe membership proof
- over a limit: per-trade notional, trade count, gross notional or daily loss
- an altered envelope, a request hash mismatch, or a policy-version mismatch
- a duplicate `request_id`
- an alternate entry point: manual CLI, API route, Telegram command, or LLM tool call
- LLM origin, a missing 2FA reference, or no session at all
- an unset limit, which comes back as `OPERATOR_DECISION_REQUIRED`

**Allowed:**
- exit, protection and cancel after cutoff, expiry, revocation and kill
- the exit cap holds even then: an exit can't exceed the held quantity or add exposure
- a position the session didn't open is refused

**Module guard:** the module imports no broker, network, DB or secret library.

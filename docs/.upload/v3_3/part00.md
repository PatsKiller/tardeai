# TRADE AI MASTER AGENTIC FINANCIAL SYSTEM ARCHITECTURE v3.3
## Canonical Architecture for Trade AI v12, OpenClaw, Hermes, Moomoo OpenD, Watch Decision Integrity, and Momentum Scalp

**Status:** CANONICAL MASTER ARCHITECTURE — implementation blueprint; no execution authorization  
**Architecture owner:** Lead Architect  
**Date:** 2026-07-22  
**Target production host:** `ms01-openclaw`  
**Canonical repository path:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild` — verify before each implementation session  
**Primary database:** PostgreSQL `trade_ai` — live schema inventory, not a historical table count, is authoritative  
**Primary operator surfaces:** Command Center v3 (`/v3`) and quasi-parallel Active Trader Next (`/v3-next`) during migration  
**Security posture:** deterministic safety core, explicit human authority, per-order authorization by default, operator-approved session-scoped 2FA for live momentum scalp, Bitwarden Secrets Manager only  
**Supersedes as controlling architecture:**

- `AGENTIC_MATURITY_ARCHITECTURE_v1_0.md`
- `AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v2_0.md`
- `MOOMOO_REFERENCE_ARCHITECTURE_v2_2.md`
- `MOMENTUM_SCALP_ARCHITECTURE_V1.3.md`
- `TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_0.md`
- `TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_1.md`
- `TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_2.md`

The superseded documents remain historical evidence. Their conflicting requirements are resolved in §1. No implementation may select a superseded rule when this document provides a controlling rule.

## v3.1 operator-approved amendment

The architecture owner has explicitly authorized:

1. an approved live-canary phase for Moomoo momentum scalping;
2. automatic live scalp entries, modifications, protective management, scale-outs, and exits while a bounded live scalp session is active;
3. one operator 2FA ceremony at the start of that session instead of per-order 2FA for each scalp order;
4. deterministic enforcement of the signed session authorization envelope;
5. immediate session revocation and kill-switch authority.

This amendment changes only the momentum-scalp authorization boundary. It does not authorize an LLM to execute, remove deterministic validation, remove risk limits, weaken broker reconciliation, expose credentials, or permit orders outside the signed session.

**Architecture guardrails may not be changed again without explicit architecture-owner approval recorded in a versioned architecture amendment.**

## v3.3 operator-approved multi-broker and autonomous-build amendment

The architecture owner additionally authorizes the design and staged implementation of:

1. API-enabled account discovery and trading across all eligible Alpaca, Moomoo, and Schwab accounts;
2. broker capability discovery and normalized broker-rejection handling;
3. pre-authorized primary and fallback broker accounts;
4. automatic failover only among accounts already bound into the signed session envelope;
5. operator notification and session-amendment workflow when an unapproved alternate account is required;
6. complete pre-trade, working-order, in-trade, and post-trade ticket views;
7. configurable quick-add controls, including 100, 200, 500, and 1,000-unit presets;
8. single-order cancel, protected cancel-all, flatten, and intelligent-sell actions;
9. broker-specific exit translation and fallback behavior;
10. a server-side feature-control modal for staged testing without changing the current live dashboard;
11. a read-only second-architect litmus review that cannot modify source, configuration, or architecture;
12. a resumable sequential Codex night-run controller that commits each green stage, pushes to GitHub, syncs artifacts to Google Drive, and emails the operator;
13. Bitwarden credential-requirement scaffolding and an operator completion to-do list.

This amendment preserves v3.2's session-scoped authorization boundary. A broker, account, quantity, symbol, strategy, or risk limit not already present in the signed session envelope cannot be introduced through automatic failover, a quick-add button, a flatten action, or a feature flag.

The unattended implementation workflow may build and test through non-live stages. It may not merge to the production branch, deploy to production, enable a live feature flag, request real 2FA, unlock live trading, or submit a real order without a separate operator start instruction for that exact stage.

## v3.2 operator-approved Active Trader amendment

The architecture owner additionally authorizes the design and staged implementation of:

1. a new Active Trader workspace on the Trade AI operator surface;
2. a quasi-parallel `/v3-next` dashboard that can be switched against the existing `/v3` dashboard without replacing it;
3. operator-configurable share quantities and account selection;
4. saveable session drafts and one session-scoped 2FA ceremony;
5. automatic live momentum-scalp execution after session activation;
6. Level 2 and time-and-sales-informed limit management;
7. deterministic in-trade management that distinguishes ordinary pullbacks, resilient continuation, supply/resistance, runner promotion, and exit conditions;
8. complete event-sourced journaling and learning feedback;
9. staged Codex implementation with explicit stop points and acceptance evidence.

This amendment does not authorize the implementation agent to reinterpret or weaken the v3.1 session envelope. The architecture owner remains the sole authority for changing financial guardrails.

---

# 0. EXECUTIVE CHARTER

Trade AI is not being redesigned as an autonomous trading bot.

It is being designed as an **agentic financial operating system** in which:

1. market and account observations are acquired with provenance;
2. deterministic services establish facts, arithmetic, eligibility, and risk;
3. reflective agents retrieve institutional memory and challenge decisions;
4. a deterministic reconciler releases or quarantines artifacts;
5. humans retain financial authority;
6. every live order is covered by either per-order 2FA or an active operator-signed momentum-scalp session authorization;
7. outcomes become cases, lessons, hypotheses, and scored improvements;
8. no learned change reaches production without evidence, adjudication, versioning, and rollback.

The architectural maxim is:

> **Machines observe broadly. Deterministic systems establish truth. Agents challenge and learn. Evidence earns promotion. Humans retain financial authority.**

## 0.1 Two loops, one constitution

```text
FAST REFLECTIVE LOOP
observations
  → normalized facts
  → candidate decision/ticket
  → independent deterministic validation
  → Sentinel integrity kernel
  → retrieval-grounded reflective critique
  → deterministic release or quarantine
  → operator presentation

SLOW LEARNING LOOP
artifact and outcome
  → immutable case
  → nightly reflection
  → candidate lesson or preregistered hypothesis
  → deterministic evaluation / shadow / walk-forward
  → Darwin adjudication evidence
  → human promotion decision
  → versioned config or code
  → reversible deployment
  → new outcomes
```

The fast loop prevents obvious nonsense today.  
The slow loop reduces recurrence and improves the system over time.

## 0.2 The core architectural decision

The execution and protection layers remain deliberately non-agentic.

The reflective and learning layers become agentic.

An LLM is never the authority for:

- price truth;
- position truth;
- account truth;
- order status;
- arithmetic;
- eligibility;
- stop enforcement;
- risk limits;
- broker routing;
- approval state;
- 2FA;
- live execution.

---

# 1. SUPERSESSION AND CONFLICT RESOLUTION

This section is controlling when prior documents disagree.

## 1.1 Credentials

**Bitwarden Secrets Manager is the only credential store.**

- Broker, provider, OAuth service, TOTP, RSA/private-key, and API credentials are stored in Bitwarden Secrets Manager.
- Production secret set: `trade-ai-prod`.
- Laboratory secret set: `trade-ai-lab`; it must not contain live broker credentials.
- Secrets are rendered at service start into a dedicated tmpfs path under `/run`.
- No broker credential, trade password, TOTP secret, or private key is stored in `.env`.
- No agent may read raw secrets.
- The only permanent secret material allowed on disk is the minimum Bitwarden machine-token material already approved by the secrets migration.
- `credential_slot` is a logical reference to a Bitwarden secret set, not a path and not a credential value.

Any older statement that places a Moomoo trade password or TOTP secret in `.env` is void.

## 1.2 Live authorization modes

Per-order 2FA remains the default for non-simulation trading.

The architecture owner has approved one explicit exception:

```text
MOMENTUM_SCALP_LIVE_SESSION
```

A live momentum-scalp session is activated by one operator 2FA ceremony. After activation, the deterministic scalp engine may automatically submit and manage live scalp orders that remain inside the signed session authorization envelope.

The session envelope must bind at minimum:

```yaml
session_authorization_id:
strategy: MOMENTUM_SCALP
broker:
account_ids: []
allowed_symbols: []
candidate_rule_version:
ticket_policy_version:
model_review_policy:
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
allowed_sessions: []
required_protection:
live_arm_token_hash:
operator_id:
2fa_verification_ref:
authorization_hash:
status:
```

The allowed symbol set may be:

- an explicit operator-approved list; or
- a deterministic dynamic universe rule whose version, filters, and maximum symbol count are included in the signed envelope.

One-time session 2FA authorizes, within those bounds:

- live entries;
- partial-fill management;
- bounded limit repricing;
- broker-native protective orders;
- authorized scale-outs;
- deterministic thesis exits;
- session-close exits;
- emergency exits;
- order cancellation or replacement required by the approved strategy.

It does not authorize:

- another strategy;
- another broker or account;
- a larger position or risk budget;
- a symbol outside the signed universe;
- an order after the entry cutoff;
- a changed strategy, candidate, risk, or chase-policy version;
- removal or weakening of required protection;
- an LLM-originated order;
- manual discretionary orders unrelated to the scalp engine.

Any material envelope change requires revocation and a new 2FA ceremony.

When the entry window expires:

- no new positions may be opened;
- already-open positions remain under the original authorization until flat;
- protective management and exits continue automatically;
- the session closes after all positions and working orders are reconciled.

All live scalp orders must carry `session_authorization_id` and `authorization_hash`. An order that cannot prove current authorization is rejected before the adapter.

### Composite per-order envelope

For non-scalp live trading, one 2FA ceremony may still authorize an immutable composite order envelope when every child is shown and hash-bound. Any later material change requires new authorization.

## 1.3 Momentum scalp live auto-execute

The permitted operating modes are:

```text
IGNORE
ELIGIBLE_WATCH
AUTO_STAGE_ON_FIRE
AUTO_EXECUTE_LIVE_SESSION
```

`AUTO_EXECUTE_LIVE_SESSION` is valid only while a signed `MOMENTUM_SCALP_LIVE_SESSION` is active.

The mode may automatically:

- select a candidate under the signed deterministic universe rule;
- arm and fire;
- compile and validate the ticket;
- submit the bounded live entry;
- install broker-native protection;
- manage the position;
- scale out;
- exit;
- reconcile the broker state.

No per-order 2FA is required inside the valid session envelope.

## 1.4 Exit-only kill switch

Exit-only mode means:

- the live scalp session is immediately closed to new entries;
- no adds are permitted;
- working entry orders are cancelled where safe;
- broker-resident protective orders remain active;
- existing session-authorized scalp positions continue deterministic protective management and may exit automatically;
- non-scalp discretionary live exits remain on their normal authorization policy;
- simulation exits may remain autonomous;
- the operator is alerted and the revocation is audited.

Session revocation never removes protection from an open position.

## 1.5 Moomoo authority

Moomoo enters in three separate capability stages:

```text
DATA_ONLY
SIMULATION_TRADE
LIVE_TRADE
```

The implementation sequence still begins with `DATA_ONLY`, then `SIMULATION_TRADE`.

`LIVE_TRADE` and the smallest momentum-scalp live canary are now architecture-owner approved, but may activate only after the P11 readiness gate proves the adapter, protection, account, authorization-session, reconciliation, and operational prerequisites.

Approval of the phase is not evidence that those prerequisites are already implemented.

## 1.6 Broker inventory and SnapTrade

The canonical broker plane currently names:

- Schwab;
- Alpaca;
- Moomoo, data-only initially.

The earlier v2.0 diagram mentioned SnapTrade without evidence in the reviewed repository context. SnapTrade is excluded from the canonical plane until a live inventory proves:

- an installed connector;
- an account registry entry;
- a source-of-truth contract;
- capability rows;
- tests;
- an owner.

## 1.7 Dashboard and paths

- Command Center v3 is the canonical operator surface.
- New scalp UI belongs under `/v3/scalp`, not a new legacy `/v2/scalp` product.
- APIs belong under the current v3 service boundary.
- Historical paths such as `/home/john/trade-ai-v12-rebuild/` are not assumed valid.
- Every implementation session begins by resolving the actual repository, service, and bundle paths.

## 1.8 Raw market-data storage

The momentum v1.3 proposal to write all ticks and order-book updates into PostgreSQL is superseded by the following rule:

> PostgreSQL is the control and feature store. High-frequency raw events use an append-only replay store. The main OLTP database does not ingest every book mutation.

PostgreSQL may retain sampled or bounded partitions only after a throughput benchmark proves the value.

## 1.9 Agent names and operator continuity

Existing stable IDs remain compatible:

```text
maria
steph
risk_agent
tax_agent
alex
aegis
iris
hermes
```

Institutional display roles may be added without breaking IDs:

```text
risk_agent → Guardian Risk
tax_agent  → Ledger Tax
```

New agent IDs are introduced only for missing functions.

---

# 2. HONEST MATURITY ASSESSMENT

The platform is stronger in deterministic engineering than in agentic operation.

| Capability | Current maturity | Target |
|---|---:|---:|
| Deterministic execution and safety | 8.5/10 | 9.0 |
| Scheduled automation and operations | 7.2/10 | 8.5 |
| Data breadth | 7.0/10 | 8.5 |
| Provenance and cross-source truth | 5.5/10 | 8.5 |
| Decision compilation | 6.0/10 | 8.0 |
| Universal decision integrity | 5.5/10 | 8.5 |
| Durable agent runtime | 3.0/10 | 8.0 |
| Machine-readable institutional memory | 3.2/10 | 8.0 |
| Outcome learning | 4.5/10 | 7.5 |
| Hypothesis-to-promotion science | 3.8/10 | 8.0 |
| Model orchestration and independence | 5.0/10 | 8.0 |
| Market microstructure intelligence | 2.0/10 | 8.0 |
| Operator agent experience | 4.5/10 | 8.0 |

**Current agentic-financial-system maturity: approximately 4.3/10.**

The deterministic core could remain technologically conservative forever. That is not a weakness. The underdeveloped capability is the circulation between evidence, memory, critique, evaluation, and promotion.

---

# 3. CONSTITUTIONAL LAWS

1. **The deterministic core never learns in place.**
2. **Learning proposes; evaluation tests; adjudication promotes; deployment versions; outcomes judge.**
3. **No LLM is a source of arithmetic, market, broker, account, position, eligibility, or execution truth.**
4. **No LLM runs in tick, fire, stop, broker-write, kill-switch, or protective paths.**
5. **Every reflective agent retrieves before reasoning.**
6. **Every agent artifact is immutable and scored.**
7. **Every material prediction is frozen before its outcome window.**
8. **Every promoted change has a one-step rollback.**
9. **Agents write only to staging, review, case, lesson-candidate, hypothesis, and exception surfaces.**
10. **No model or model ensemble can override a deterministic failure.**
11. **Abstention is a valid high-quality output.**
12. **Cron/systemd may trigger an agent; a cron job is not automatically an agent.**
13. **A personality name is not an agent.**
14. **An agent may not validate or score its own artifact.**
15. **No production agent survives without measurable utility.**
16. **No live order is representable without a valid per-order authorization or active signed session authorization.**
17. **Production secrets never enter an agent prompt, model context, replay file, or KB.**
18. **Research availability and financial authorization are separate concerns.**
19. **The operator surface may degrade; protective truth may not.**
20. **No architecture phase may require a rewrite of the existing data estate before delivering value.**
21. **Only the architecture owner may approve a financial guardrail change; every approval is versioned, attributable, and auditable.**
22. **Operator-entered account, quantity, and session intent is immutable after 2FA except through explicit revocation and reauthorization.**
23. **Level 2 is evidence, not truth by itself; book signals require persistence, tape confirmation, sequence integrity, and price-context agreement.**
24. **A winning scalp may become an intraday runner only through a deterministic state transition recorded in the session policy and journal.**

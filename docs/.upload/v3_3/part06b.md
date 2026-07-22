- account-level Moomoo request-rate governor;
- complete journal and replay references;
- resilience/resistance and runner policy versions;
- all enabled Alpaca, Moomoo, and Schwab account capabilities probed;
- broker-assisted rejection and alternate-account workflow tested;
- cancel, cancel-all, flatten, and smart-sell broker translations tested;
- quick-add envelope enforcement tested;
- feature-control rollback tested;
- read-only architecture litmus review PASS or operator-accepted conditional findings;
- smallest-symbol/universe and notional canary;
- automated post-session closeout.

Required canary sequence:

```text
1. operator reviews the complete session envelope
2. operator completes one 2FA ceremony
3. session enters AUTHORIZED
4. deterministic engine may auto-trade qualifying scalps within the envelope
5. every order is tagged and audited against the session hash
6. any envelope breach is rejected
7. entry cutoff disables new positions
8. open positions are protected and managed to flat
9. session closes and produces a reconciliation report
```

Architecture approval is granted. Production activation remains conditional on recorded proof that every prerequisite and acceptance gate is complete.

---

# 23. TEST STRATEGY

## 23.1 Contract tests

- canonical views;
- provenance envelope;
- ticket hash binding;
- Sentinel outputs;
- KB retrieval;
- model registry;
- order intent;
- per-order and session-authorization binding;
- Moomoo entitlement and sequence state.

## 23.2 Replay tests

- known Watch failures;
- stale data;
- missed pullback;
- distant breakout;
- blocked event;
- held starter-plan suppression;
- local model unavailable;
- OAuth split;
- Moomoo disconnect;
- sequence gap;
- crossed book;
- scalp fire and reversal;
- restart during simulated chase;
- stale authorized draft hash;
- duplicate browser activation;
- multi-account partial failure;
- place/modify rate-budget exhaustion;
- static book wall without tape confirmation;
- resilient pullback held correctly;
- resistance-dominant winner scaled/exited;
- runner promotion and demotion;
- entry cutoff with open position;
- `/v3` and `/v3-next` parity mismatch;
- journal/replay reconstruction;
- Schwab electronic-entry/broker-assistance rejection;
- authorized fallback broker succeeds after source rejection;
- unauthorized alternate broker requires new 2FA;
- source broker late fill after rejection/cancel ambiguity;
- multi-account partial fill and one-account rejection;
- quick-add 100/200/500/1000 shares and dollars;
- quick-add exceeds session envelope;
- cancel all preserves protective orders;
- native flatten partial multi-status;
- Moomoo opposite-side close;
- Schwab marketable-limit close fallback;
- smart-sell deadline escalates to flatten;
- feature modal toggles shadow only;
- reviewer write capability denied;
- interrupted night run resumes from checkpoint;
- Drive sync retry is idempotent;
- operator email contains no secrets;
- Bitwarden sentinel placeholder rejected by runtime.

## 23.3 Fault injection

- PostgreSQL unavailable;
- OpenD unavailable;
- model timeout;
- Bitwarden render failure;
- clock drift;
- network partition;
- duplicate event;
- stale authorization;
- package rollback;
- corrupted replay segment.

## 23.4 Evaluation fixtures

Every severe incident becomes a permanent regression case.

---

# 24. ACCEPTANCE GATES

## Agentic

```text
DURABLE MVL RUNS: VERIFIED
RETRIEVAL BEFORE REASONING: >=95%
AGENT TOOL CALLS AUDITED: 100%
AGENT OUTPUTS SCORED: >=95%
UNSCORED OPERATIONAL AGENTS: 0
CANCELLATION: VERIFIED
RESUME/CHECKPOINT: VERIFIED WHERE IMPLEMENTED
MODEL OVERRIDES DETERMINISTIC FAILURE: 0
DIRECT AGENT PRODUCTION WRITES: 0
```

## Decision integrity

```text
MECHANICS WITHOUT VERIFIED TICKET: 0
HEADER/TILE/POLICY CONTRADICTIONS: 0
BLOCKED WITH CURRENT MECHANICS: 0
NO-TRADE-PREFERRED WITH CURRENT MECHANICS: 0
MISSED ENTRY WITH CURRENT MECHANICS: 0
LEGACY PACKET WITHOUT WARNING: 0
```

## Knowledge

```text
LESSONS WITH PROVENANCE: 100%
RATIFIED LESSONS WITH COUNTEREVIDENCE SEARCH: 100%
UNVERSIONED EMBEDDINGS: 0
SECRET-BEARING CHUNKS: 0
```

## Learning

```text
PROMOTED CHANGES PREREGISTERED: 100%
PROMOTED CHANGES WITH OOS/SHADOW EVIDENCE: 100%
PROMOTED CHANGES WITH ROLLBACK: 100%
AGENT SELF-PROMOTIONS: 0
```

## Upgrade lab

```text
IN-PLACE FIRST UPGRADE: 0
PROD SECRETS IN LAB: 0
CANDIDATE ON PROD PATH BEFORE APPROVAL: 0
ROLLBACK TESTED: 100%
```

## Moomoo

```text
OPEND HEALTH: VERIFIED
ENTITLEMENTS DISPLAYED: VERIFIED
QUOTA GOVERNED: VERIFIED
SEQUENCE GAPS DETECTED: VERIFIED
REPLAY DETERMINISTIC: VERIFIED
LLM IN TICK PATH: NO
LIVE TRADE AUTHORITY IN DATA PHASE: NO
```

## Active Trader

```text
OLD DASHBOARD AVAILABLE: YES
NEW DASHBOARD AVAILABLE: YES
SWITCH VERIFIED: YES
SERVER-SIDE SESSION STATE: VERIFIED
ACCOUNT CHECKBOX VALIDATION: VERIFIED
PER-ACCOUNT QUANTITY VALIDATION: VERIFIED
DRAFT/AUTHORIZATION HASH MATCH: VERIFIED
ONE-TIME SESSION 2FA: VERIFIED
MOO MOO PLACE RATE LIMIT EXCEEDED: 0
MOO MOO MODIFY RATE LIMIT EXCEEDED: 0
BOOK-ONLY UNCONFIRMED ENTRY/EXIT ACTIONS: 0
JOURNAL EVENT COMPLETENESS: 100%
REPLAY REFERENCES PRESENT: 100%
PARITY MISMATCH DURING LIVE ACTIVATION: 0
BROKER CAPABILITIES UNKNOWN FOR ENABLED ACTION: 0
REJECTION EVENTS WITHOUT OPERATOR NOTIFICATION: 0
AUTOMATIC FAILOVER TO UNAUTHORIZED ACCOUNT: 0
QUICK ADD OUTSIDE AUTHORIZED ENVELOPE: 0
CANCEL ALL REMOVING PROTECTION WITHOUT REPLACEMENT/FLATTEN: 0
FLATTEN REPORTED COMPLETE BEFORE BROKER PARITY: 0
SMART SELL WITHOUT DEADLINE/FALLBACK: 0
FEATURE FLAGS CHANGING /V3 BEHAVIOR: 0
```

## Documentation and unattended implementation

```text
ONE GREEN STAGE PER COMMIT: VERIFIED
GITHUB PUSH AFTER EACH GREEN STAGE: VERIFIED
DRIVE SYNC AFTER EACH GREEN STAGE: VERIFIED
LOCAL/GITHUB/DRIVE HASH PARITY: VERIFIED
CHECKPOINT RESUME: VERIFIED
FAILURE STOP: VERIFIED
FINAL OPERATOR EMAIL: VERIFIED
OPERATOR TODO ATTACHED/LINKED: VERIFIED
BITWARDEN LAB PLACEHOLDERS CREATED OR EXPLICITLY WAIVED: VERIFIED
PRODUCTION SECRET VALUES CREATED BY CODEX: 0
READ-ONLY ARCHITECT WRITES: 0
AUTOMATIC MERGE TO MAIN: 0
AUTOMATIC PRODUCTION DEPLOY: 0
```

## Execution

```text
LIVE ORDERS OUTSIDE VALID PER-ORDER OR SESSION AUTHORIZATION: 0
SESSION-AUTHORIZED ORDERS WITHOUT MATCHING SESSION HASH: 0
ORDERS AFTER SESSION ENTRY CUTOFF: 0
SESSION LIMIT BREACHES REACHING ADAPTER: 0
REFLECTIVE AGENT BROKER CALLS: 0
LIVE SCALP WITHOUT BROKER PROTECTION: 0
```

---

# 25. ARCHITECTURE DECISIONS

- **ADR-001:** Deterministic core remains sovereign — ACCEPTED.
- **ADR-002:** MVL precedes general runtime — ACCEPTED.
- **ADR-003:** Sentinel kernel synchronous; reflective review class-dependent — ACCEPTED.
- **ADR-004:** Research display may fail open visibly; proposal eligibility fails closed — ACCEPTED.
- **ADR-005:** Wrap existing tables; do not re-platform as prerequisite — ACCEPTED.
- **ADR-006:** PostgreSQL is control/feature store; raw microstructure uses replay storage — ACCEPTED.
- **ADR-007:** Moomoo enters data-only — ACCEPTED.
- **ADR-008:** The smallest Moomoo momentum-scalp live canary is architecture-owner approved after P11 readiness proof — ACCEPTED.
- **ADR-009:** Bitwarden Secrets Manager only — ACCEPTED.
- **ADR-010:** Per-order 2FA is default; live momentum scalp may auto-trade under one bounded session-scoped 2FA authorization — ACCEPTED.
- **ADR-011:** OpenClaw is operator/runtime gateway, not financial authority — ACCEPTED.
- **ADR-012:** Hermes is hypothesis/discovery, not execution or promotion authority — ACCEPTED.
- **ADR-013:** OpenAI Agents SDK is optional laboratory technology — ACCEPTED.
- **ADR-014:** Product upgrades are side-by-side candidates with atomic promotion — ACCEPTED.
- **ADR-015:** Client-only live scalp stops are prohibited — ACCEPTED.
- **ADR-016:** SnapTrade is excluded pending evidence — ACCEPTED.
- **ADR-017:** Existing agent IDs remain stable; institutional display roles may be aliases — ACCEPTED.
- **ADR-018:** Active Trader Next is deployed quasi-parallel at `/v3-next`; `/v3` remains available until explicit retirement — ACCEPTED.
- **ADR-019:** Session drafts, account allocations, and quantities are server-side and hash-bound before 2FA — ACCEPTED.
- **ADR-020:** Moomoo order requests are governed by account-level token buckets with emergency reserve — ACCEPTED.
- **ADR-021:** Level 2 actions require persistence, tape confirmation, and sequence integrity — ACCEPTED.
- **ADR-022:** Resilience and resistance are separate deterministic scores; runner conversion is an explicit state transition — ACCEPTED.
- **ADR-023:** All Active Trader events feed the journal, replay, Darwin, and the governed learning loop — ACCEPTED.
- **ADR-024:** All API-enabled Alpaca, Moomoo, and Schwab accounts are discovered, but only eligible and session-authorized accounts may trade — ACCEPTED.
- **ADR-025:** Broker actions are translated through a runtime capability registry — ACCEPTED.

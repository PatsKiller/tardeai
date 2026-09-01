# Trade AI Agentic MVL Backlog — 2026-07-23

Status:      HISTORICAL
as_of:       2026-07-23T21:44:03-04:00
Measured at: efcc51365 / not measured

**Controlling sequence:** prove the Minimum Viable Loop before general orchestration.
**Hard exclusions:** no Active Trader Session 1 branch/timer/marker changes; no broker/order/2FA/config-promotion authority.

## P0 — Required before any shadow activation

### Runtime and host baseline

- verify deployed Git SHA and dirty state;
- inventory OpenClaw, Hermes, OpenAI SDK, Node, npm, Ollama and pgvector versions;
- inventory OpenClaw/Hermes homes, services, ports, channels and inherited environment;
- inventory agent-related cron/systemd entries;
- inventory active prompts, tools, output schemas, owners and score methods;
- resolve documented model and embedding drift;
- document production and shadow database roles.

### Security and permissions

- create dedicated `trade_ai_shadow_ro` canonical-view reader;
- create separate lab/staging writer for `agentic_runtime` only;
- prove denied production schema writes;
- prove no production Bitwarden machine token or broker secret enters shadow;
- add prompt-injection and tool-confusion fixtures;
- add explicit local-lane no-cloud-fallback test;
- make every denied tool call auditable, not silently swallowed.

### Schema proof

- apply the paired MVL migration only to an isolated lab database;
- run up/down/up migration proof;
- verify append-only evidence triggers;
- verify producer/reviewer and producer/scorer checks;
- verify retention, backup and replay of agent runs;
- benchmark expected run/artifact volume.

## P1 — Minimum Viable Loop

### Sentinel integrity integration

- define canonical Watch artifact envelope;
- bind existing deterministic validator output and hashes;
- build at least 20 known-bad regression fixtures;
- enforce no mechanics for blocked/no-trade/stale/invalid tickets;
- create quarantine and review-required states without editing the ticket;
- measure synchronous kernel latency.

### Sentinel reflective critic

- build temporal/provenance-filtered retrieval facade;
- retrieve ratified/disputed lessons, analogous cases and source notices;
- bind local, Grok OAuth and ChatGPT OAuth results independently;
- implement release-class deadlines and fail-open/fail-closed semantics;
- preserve disagreement instead of majority voting;
- expose abstention and insufficient evidence as valid outputs.

### Knowledge base

- audit current corpus and embedding provenance;
- select one canonical embedding model/version only after live verification;
- create dual-index migration plan if the live model changes;
- seed findings, incidents, handoffs, tickets and outcomes as cases;
- implement `kb.search`, `kb.get_lesson`, `kb.get_case`, `kb.find_contradictions`;
- implement temporal validity and counterevidence links;
- build Iris review workflow for candidate/ratified/disputed/retired lessons.

### Darwin

- join immutable artifacts to operator disposition and later outcomes;
- define grounding, integrity, utility, calibration, latency and cost dimensions;
- score abstentions and false alarms explicitly;
- prevent direct rule/config promotion;
- replace legacy calibration auto-write behavior with staged evidence;
- publish agent scorecards and retirement thresholds.

### Nightly Reflection

- consume only new closed cases/exceptions;
- create candidate lessons, contradictions and preregistered hypotheses;
- never ratify or promote its own output;
- checkpoint and resume through model/tool failures;
- enforce cost, time and case-count budgets;
- deliver an operator summary without changing production behavior.

## P2 — Governed operator experience

### OpenClaw Concierge

- isolated shadow home and test channel;
- list/status/explain/cancel/resume/replay commands;
- explicit cost and provider visibility;
- artifact and source links;
- no unrestricted production shell;
- no production secret inheritance;
- operator adjudication workflow for lesson/hypothesis candidates.

### Command Center agent run UI

- current and recent run list;
- status, checkpoint, elapsed time and budget;
- retrieval refs and provenance;
- model/tool call ledger;
- artifact, review, disagreement and score panels;
- cancellation and replay controls;
- clear LAB/SHADOW/OPERATIONAL state;
- tool-denial and exception audit.

## P3 — Hermes hypothesis flywheel

Only after KB and Darwin evidence:

- isolate candidate Hermes home/profile;
- disable auto-graft and production config access;
- preregister hypothesis, inputs, metrics, outcome window and rollback;
- run backtest, walk-forward and shadow evaluation;
- have Darwin produce adjudication evidence;
- require human promotion decision;
- generate versioned config/code PR rather than direct mutation;
- observe promoted changes and automatically recommend rollback, never execute it autonomously.

## P4 — Expansion agents

Activate only when the MVL proves value:

- Argus population integrity scan;
- Maria durable fundamental/catalyst research;
- Vega technical lifecycle;
- Steph portfolio/account allocation critique;
- Guardian Risk and Ledger Tax durable critics;
- Aegis incident investigation;
- Alex unresolved trade-off synthesis;
- Pulse only after the Moomoo feature plane is empirically accepted;
- Atlas deferred until multiple durable workflows require generalized orchestration.

## Acceptance gates

### MVL evidence target

- 100 reviewed Watch artifacts;
- at least 20 known-bad regression fixtures;
- retrieval recorded on at least 95% of eligible Sentinel reviews;
- tool decisions audited on 100% of calls;
- scoring complete on at least 95% of artifacts;
- zero deterministic failures released;
- checkpoint/resume and cancellation verified;
- false-positive rate, latency and cost measured;
- zero direct production-config writes;
- zero broker calls from reflective agents.

### Knowledge integrity

- every ratified lesson has provenance and counterevidence search;
- every retrieval applies temporal validity;
- every embedding row has provider/model/version;
- every promoted change has preregistration, out-of-sample/shadow evidence and one-step rollback.

## Parallel project boundaries

- Re-Entry and Watch UI/data work continues on `main`-based branches.
- Active Trader Next UI remains on the sibling PR #162 and must not be merged before Session 1 terminal evidence.
- Session 2 is not armed until Session 1 legitimately counts.
- Agentic MVL work stays independent of Active Trader observation state.

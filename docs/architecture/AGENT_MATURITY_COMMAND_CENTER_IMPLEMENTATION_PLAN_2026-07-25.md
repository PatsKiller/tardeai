# Agent Maturity and Command Center Implementation Plan — 2026-07-25

## Status

- Branch: `agent/agent-maturity-command-center-v1`
- Exact starting point: `28645f8b9fa8031c42771da19511a97fa464d915`
- Parent program: PR #163, governed agentic MVL foundation
- Deployment state: `DESIGNED / SHADOW ONLY`
- Production activation: not authorized

This plan makes agent documentation, maturity, observability, operator control, scoring, and retirement evidence first-class deliverables. An agent is not considered mature merely because a script, prompt, schedule, or personality name exists.

## Constitutional boundaries

The implementation must preserve these rules:

1. deterministic market, account, position, risk, eligibility, and execution truth remains sovereign;
2. reflective agents cannot override deterministic failure;
3. agents retrieve before reasoning;
4. material artifacts are immutable and independently reviewed/scored;
5. no agent validates or scores its own artifact;
6. agents write only to governed run, artifact, review, score, case, lesson-candidate, hypothesis, and exception surfaces;
7. no raw secrets, broker credentials, approval tokens, or 2FA material enter prompts, artifacts, replay, logs, or the knowledge base;
8. broker, order, approval, 2FA, service-control, config-promotion, and production-database authority remain absent;
9. a scheduler may trigger an agent, but a scheduler is not itself an agent;
10. every operational agent has a disable/rollback control and measurable utility.

## Canonical roster

| Stable ID | Display name | Primary role | Initial maturity target |
|---|---|---|---|
| `sentinel` | Sentinel | Decision integrity and contradiction review | MVL operational shadow |
| `darwin` | Darwin | Outcome joins, scoring, calibration evidence | MVL operational shadow |
| `iris` | Iris | Knowledge curation and lesson lifecycle | MVL support |
| `reflection` | Nightly Reflection | Case-to-lesson and hypothesis generation | MVL shadow |
| `argus` | Argus | Population-wide integrity scan | Phase 2 shadow |
| `maria` | Maria | Fundamental and catalyst research | Durable integration later |
| `vega` | Vega | Technical structure and setup lifecycle | After technical artifacts stabilize |
| `pulse` | Pulse | Moomoo microstructure interpretation | After the Moomoo feature plane is proven |
| `steph` | Steph | Portfolio and account allocation | Durable integration later |
| `risk_agent` | Guardian Risk | Portfolio and ticket risk critic | Existing ID retained |
| `tax_agent` | Ledger Tax | Tax, wash-sale, and account constraints | Existing ID retained |
| `hermes` | Hermes | Hypothesis discovery and experiment design | After KB and Darwin |
| `aegis` | Aegis | Incident and reliability investigation | After the case pipeline |
| `alex` | Alex | CIO synthesis for unresolved trade-offs | After lower layers are reliable |
| `concierge` | Concierge | Governed operator interface | After governed tools |
| `atlas` | Atlas | General durable-workflow orchestration | Deferred until MVL evidence |

## Required agent definition contract

Every agent definition must expose, in machine-readable form:

```yaml
agent_id:
agent_version:
display_name:
objective:
owner:
allowed_job_types:
allowed_tools:
denied_tools:
retrieval_policy:
artifact_schema:
review_policy:
score_policy:
budget:
deadline:
stop_conditions:
deployment_state:
disable_control:
rollback_control:
current_limitations:
```

The registry must reject missing owners, undefined artifact schemas, absent stop conditions, or deployment states outside:

```text
DESIGNED
SHADOW
OPERATIONAL
RESTRICTED
RETOOL
RETIRED
```

## Documentation deliverables

### 1. Agent handbook

Create one canonical handbook page that explains:

- what each agent does;
- what triggers it;
- what it reads;
- what tools it may use;
- what it is forbidden to do;
- what artifact it produces;
- who reviews and scores it;
- its budget and deadline;
- its current maturity and known limitations;
- its disable/rollback procedure;
- its acceptance evidence.

### 2. Agent-specific runbooks

Each agent that reaches `SHADOW` requires a focused runbook covering:

- inputs and canonical source contracts;
- retrieval requirements;
- failure and abstention semantics;
- tool-call lifecycle;
- output schema;
- review/scoring separation;
- alerting and operator actions;
- replay and incident evidence;
- promotion and retirement gates.

### 3. Permission matrix

Maintain a current matrix of:

- allowed tools;
- denied tools;
- database read/write scope;
- network/provider scope;
- operator commands;
- production reachability;
- secret exposure risk;
- evidence owner.

## Read-only monitoring API

Implement additive read models behind a production-inactive contract. Initial routes may be mounted under `/api/v2/agent-runtime` after review:

```text
GET /agents
GET /agents/{agent_id}
GET /runs
GET /runs/{run_id}
GET /runs/{run_id}/timeline
GET /artifacts
GET /reviews
GET /scores
GET /cases
GET /lessons
GET /health
```

The API must:

- be read-only;
- expose source/as-of/contract versions;
- paginate large collections;
- support agent, state, date, symbol/entity, and outcome filters;
- mask internal identifiers where appropriate;
- never return raw prompts containing secrets;
- distinguish `UNAVAILABLE`, `NOT_RUN`, `BLOCKED`, `FAILED`, `CANCELLED`, and `STALE` from success;
- expose whether evidence is fixture, LAB, SHADOW, or production-derived;
- expose deadlines, budgets, tool-call counts, provider/model identity, latency, cost, reviews, scores, and operator disposition when available;
- provide deterministic status summaries rather than model-written health labels.

The first UI tranche may use fixtures and an interface-compatible read adapter while the Codex persistence lane implements the authoritative Postgres adapter. No duplicate persistence layer may be created on this branch.

## Command Center v3 monitoring surface

Add a first-class `/v3/agents` workspace and contextual agent panels on relevant pages.

### Global Agents workspace

The main page must provide:

1. **Fleet summary**
   - counts by lifecycle state;
   - running, blocked, failed, stale, cancelled, and deadline-exceeded runs;
   - unreviewed and unscored artifacts;
   - current tool/provider availability;
   - last successful reflection and scoring cycles.

2. **Agent catalog**
   - display/stable name;
   - objective;
   - owner;
   - deployment state;
   - current version;
   - last run and next eligible trigger;
   - success, abstention, failure, and false-positive metrics;
   - current limitations;
   - documentation link.

3. **Run queue and timeline**
   - run ID and trigger;
   - subject/symbol/entity;
   - current checkpoint;
   - deadline and budget utilization;
   - retrieval, tool-call, artifact, review, and score stages;
   - explicit blocker or stop reason;
   - operator status/explain/cancel/replay controls only where governed APIs exist.

4. **Artifact review desk**
   - immutable artifact hash;
   - producer;
   - independent reviewer and scorer;
   - deterministic gate result;
   - contradictions and abstentions;
   - operator disposition;
   - eventual outcome and Darwin score.

5. **Knowledge and learning**
   - cases and lessons;
   - candidate, ratified, rejected, stale, and superseded lesson states;
   - contradiction links;
   - Nightly Reflection outputs;
   - Iris/operator adjudication evidence;
   - no automatic production promotion.

6. **Authority and safety**
   - visible denied capabilities;
   - production reachability state;
   - last authority scan;
   - secret-rejection state;
   - rollback/disable status;
   - zero broker/order/approval/2FA authority indicator.

### Contextual page integration

Add bounded, read-only panels rather than duplicating the whole fleet UI:

- **Watch:** Sentinel integrity, reflective review, Argus population findings, Darwin outcome score, relevant case/lesson links.
- **Defense/Sectors:** Steph allocation evidence, Guardian Risk critique, sector/industry diligence agents, model critique clearly separated from deterministic math.
- **Portfolio/Re-Entry/Redeploy:** Steph, Guardian Risk, Ledger Tax, Darwin outcome/calibration evidence.
- **Journal/TradeInView:** case creation, replay links, Darwin scoring, Iris lesson candidates, Aegis incident links.
- **Active Trader Next:** later separate redesign; do not imply its current frontend meets the final operator specification.

Contextual panels must never change the sovereign page decision or authorize an action.

## Maturity scorecard

Track evidence-backed maturity by capability, not by visual completeness:

| Dimension | Required evidence |
|---|---|
| Definition | versioned contract, objective, owner, allowed/denied tools |
| Durability | persisted run, checkpoint, artifact, review, and score lifecycle |
| Retrieval | recorded retrieval for eligible runs and contradiction search |
| Reliability | deadlines, retries, cancellation, resume, terminal-state correctness |
| Independence | producer/reviewer/scorer separation |
| Safety | authority scan, secret rejection, zero forbidden calls |
| Quality | regression fixtures, false-positive/abstention/outcome metrics |
| Learning | candidate lesson creation and adjudication without auto-promotion |
| Operator experience | status, explain, evidence, replay, cancel, and documentation |
| Rollback | tested disable/rollback path |

A display badge may summarize maturity only when every underlying dimension is visible.

## Minimum Viable Loop acceptance

The first promotion gate remains:

```text
100 reviewed Watch artifacts
>= 20 known-bad regression fixtures
retrieval recorded on >= 95% of eligible Sentinel reviews
0 deterministic failures released
Sentinel false-positive rate measured
Darwin scoring complete for >= 95% of artifacts
Nightly Reflection creates candidate lessons
Iris or operator can ratify/reject lessons
0 production config mutations
0 broker calls
0 authority violations
```

## Implementation phases

### Phase A — registry and documentation

- enrich the agent registry contract;
- add validation tests;
- publish handbook and permission matrix;
- define maturity and health read models.

### Phase B — fixture-backed monitoring UI

- add `/v3/agents` route and navigation;
- render catalog, runs, artifacts, reviews, scores, cases, lessons, safety, and limitations;
- add contextual read-only panels to Watch first;
- prove desktop/narrow layout, accessibility, honest empty/error/stale states, and no forbidden action.

### Phase C — authoritative persistence integration

- rebase/integrate after the Codex persistence PR is reviewed;
- replace fixtures with the approved Postgres read adapter;
- preserve the same API/UI contracts;
- verify pagination and realistic run volumes.

### Phase D — MVL population and scorecards

- execute 100-artifact Watch population;
- include at least 20 known-bad cases;
- produce false-positive, abstention, latency, cost, retrieval, review, and scoring reports;
- create Nightly Reflection candidates and Iris/operator dispositions.

### Phase E — controlled promotion

- promote only individually proven agents;
- retain Atlas, Pulse, Hermes activation, and other later roles behind their prerequisites;
- keep every disable/rollback control tested and operator-visible.

## Non-overlap with Codex lane

The Codex branch `codex/agent-runtime-persistence-v1` owns:

- LAB DB proof;
- Postgres persistence adapters;
- concurrency-safe journal semantics;
- deterministic export/replay;
- persistence-focused tests.

This branch must not edit those files until the Codex draft PR is reviewed. Initial UI/read-model work must remain interface- or fixture-backed.

## Hard exclusions

- no production database migration or write;
- no service or scheduler activation;
- no model/provider activation;
- no OpenClaw/Hermes installation or upgrade;
- no broker/account/position/order/approval/2FA action;
- no Active Trader execution-path work;
- no automatic lesson, hypothesis, model, threshold, config, or code promotion;
- no claim that an agent is operational without acceptance evidence.

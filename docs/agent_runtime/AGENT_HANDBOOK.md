# Trade AI Agent Handbook

Status:      ACTIVE
as_of:       2026-07-25T18:22:00-04:00
Measured at: efcc51365 / not measured

**Contract:** `agent-runtime-monitoring-v1`  
**Catalog:** `config/agent_maturity_catalog.json`  
**Environment:** LAB / SHADOW only  
**Production activation:** not authorized

This handbook describes governed agent roles, permissions, maturity, monitoring,
and rollback. It does not turn a script, scheduled task, model call, or
personality label into an operational agent.

The controlling architecture remains
`docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md`.
The implementation plan is
`docs/architecture/AGENT_MATURITY_COMMAND_CENTER_IMPLEMENTATION_PLAN_2026-07-25.md`.

## Constitutional authority

Deterministic services remain sovereign for market, account, position,
arithmetic, eligibility, risk, release, broker routing, approval, 2FA, and live
execution truth.

Every cataloged agent has these authorities explicitly denied:

- broker and order authority;
- approval and 2FA authority;
- production database writes;
- production configuration promotion;
- production secret access;
- service control.

Agents may critique, retrieve, create governed evidence, and stage bounded
candidates only where their individual contract permits it. A model result
cannot override a deterministic failure.

## Lifecycle

| State | Meaning |
|---|---|
| `DESIGNED` | Contract exists; durable runtime evidence is incomplete. |
| `SHADOW` | Runs may execute in LAB/SHADOW with no production authority. |
| `OPERATIONAL` | Individually accepted production role; none are represented this way in this tranche. |
| `RESTRICTED` | Temporarily narrowed after a defect, incident, or evidence regression. |
| `RETOOL` | Utility or reliability is inadequate; redesign is required. |
| `RETIRED` | Disabled permanently while history remains auditable. |

No visual badge can promote an agent. Promotion requires its artifact schema,
fixtures, independent review/scoring, owner, disable/rollback controls, and
measurable acceptance evidence.

## Canonical fleet

| Stable ID | Display name | Purpose | Current state | Target |
|---|---|---|---|---|
| `sentinel` | Sentinel | Decision-integrity contradiction review | SHADOW | MVL operational shadow |
| `darwin` | Darwin | Outcome joins and deterministic scoring | SHADOW | MVL operational shadow |
| `iris` | Iris | Knowledge quality and lesson review | SHADOW | MVL support shadow |
| `reflection` | Nightly Reflection | Cases to candidate lessons/hypotheses | SHADOW | MVL operational shadow |
| `argus` | Argus | Population-wide contradiction scans | DESIGNED | Phase 2 shadow |
| `maria` | Maria | Fundamental and catalyst research | DESIGNED | Durable integration later |
| `vega` | Vega | Technical structure and setup lifecycle | DESIGNED | After technical artifacts stabilize |
| `pulse` | Pulse | Microstructure feature interpretation | DESIGNED | After Moomoo feature-plane proof |
| `steph` | Steph | Portfolio and account-allocation critique | DESIGNED | Durable integration later |
| `risk_agent` | Guardian Risk | Portfolio and ticket risk critique | DESIGNED | Durable integration later |
| `tax_agent` | Ledger Tax | Tax and account-constraint review | DESIGNED | Durable integration later |
| `hermes` | Hermes | Hypothesis discovery and experiment design | DESIGNED | After KB and Darwin |
| `aegis` | Aegis | Incident and reliability investigation | DESIGNED | After the case pipeline |
| `alex` | Alex | CIO synthesis of unresolved trade-offs | DESIGNED | After lower layers are reliable |
| `concierge` | Concierge | Governed operator status/explain controls | DESIGNED | After governed tools |
| `atlas` | Atlas | General durable-workflow orchestration | DESIGNED | Deferred until MVL evidence |

## Minimum Viable Loop agents

### Sentinel

**Objective:** Review immutable Watch and decision artifacts for contradictions
after deterministic validation.

**Triggers:** Watch ticket review, decision-integrity review, or known-bad
regression.

**Reads:** Validated tickets, deterministic validation, applicable lessons,
analogous cases, and contradiction evidence.

**Allowed tools:** `kb.search`, `kb.get_lesson`, `kb.get_case`, `ticket.read`,
`validator.read`, governed artifact writing, and quarantine staging.

**Forbidden:** Ticket edits, lesson ratification, scoring its own artifacts,
hypothesis promotion, proposal release, broker/order/approval/2FA actions.

**Artifact:** `sentinel-review-v1`.

**Review and score:** Independent review is required. Darwin scores eventual
outcomes and false-positive/abstention behavior.

**Budget:** Up to 3 model calls, 12 tool calls, $0.00 paid cost, 360-second
deadline.

**Stops:** Deterministic failure, deadline, budget exhaustion, missing required
retrieval, or operator cancellation.

**Current limitations:** SHADOW only; cannot edit a ticket or grant proposal
authority; 100-artifact population acceptance remains incomplete.

**Disable / rollback:** Disable the definition while preserving artifacts.
Restore the prior versioned definition and replay known-bad fixtures.

### Darwin

**Objective:** Join immutable artifacts to outcomes and write deterministic,
versioned scores.

**Triggers:** Artifact scoring, outcome joins, and calibration evidence.

**Reads:** Artifacts, outcomes, and cases.

**Allowed tools:** Read artifact/outcome/case evidence and write scores.

**Forbidden:** Producing the artifact it scores, config promotion, lesson
ratification, broker/order/approval/2FA actions.

**Artifact:** `darwin-score-v1`.

**Review and score:** Producer and scorer must differ. Score-policy changes
require separate human review.

**Budget:** No model calls, up to 12 tool calls, $0.00 paid cost, 600-second
deadline.

**Stops:** Missing outcome contract, deadline, budget exhaustion, or operator
cancellation.

**Current limitations:** SHADOW only; no rule promotion; real outcome population
is incomplete.

**Disable / rollback:** Disable scoring jobs while retaining prior scores.
Restore the prior score-policy version and recompute only in LAB/SHADOW.

### Iris

**Objective:** Review lesson quality, provenance, duplication, temporal scope,
and counterevidence.

**Triggers:** Lesson review, knowledge-quality review, and retrieval audit.

**Reads:** Lessons, cases, retrieval evidence, and contradictions.

**Allowed tools:** KB reads, lesson-review writing, and contradiction writing.

**Forbidden:** Ratifying a lesson, promoting hypotheses/config, scoring its own
artifact, production writes, broker/order/approval/2FA actions.

**Artifact:** `iris-lesson-review-v1`.

**Review and score:** Human or operator ratification remains required.
Knowledge-quality metrics are scored independently.

**Budget:** Up to 2 model calls, 20 tool calls, $0.00 paid cost, 900-second
deadline.

**Stops:** Missing provenance, missing counterevidence search, deadline, or
operator cancellation.

**Current limitations:** SHADOW only; authoritative KB write adapter is pending;
Iris cannot ratify lessons.

**Disable / rollback:** Disable Iris review jobs without mutating candidates.
Restore the prior curation policy; change an index pointer only after separate
validation.

### Nightly Reflection

**Objective:** Convert bounded new cases and exceptions into candidate lessons
and preregistered hypotheses.

**Triggers:** Nightly reflection or exception reflection.

**Reads:** New cases, exceptions, applicable lessons, and unresolved
contradictions.

**Allowed tools:** KB search, case/exception reads, candidate-lesson writing,
and hypothesis registration.

**Forbidden:** Lesson ratification, hypothesis/config promotion, production
mutation, broker/order/approval/2FA actions.

**Artifact:** `nightly-reflection-v1`.

**Review and score:** Iris or the operator reviews candidates; quality is scored
independently.

**Budget:** Up to 3 model calls, 20 tool calls, $0.00 paid cost, 1,200-second
deadline.

**Stops:** No new cases, deadline, budget exhaustion, or operator cancellation.

**Current limitations:** SHADOW only; no scheduler activation is authorized; no
candidate can promote itself.

**Disable / rollback:** Disable the reflection trigger and preserve candidate
outputs. Restore the previous prompt/policy and replay the bounded case window.

## Designed roles

The remaining agents are cataloged so their intended permissions, evidence,
limitations, and rollback are explicit before implementation.

- **Argus** opens population-integrity exceptions; it never repairs packets.
- **Maria** produces fundamental/catalyst research; it never creates execution
  mechanics.
- **Vega** reviews deterministic technical facts; it cannot invent prices or
  treat unclosed bars as confirmed.
- **Pulse** interprets deterministic microstructure features; no LLM runs in the
  tick, fire, stop, broker-write, or kill-switch path.
- **Steph** critiques allocation and account fit; it cannot write accounts,
  positions, or rebalances.
- **Guardian Risk** challenges risk evidence; it cannot override the central
  deterministic risk gate.
- **Ledger Tax** reviews canonical lot/account evidence; it cannot fabricate
  basis or execute tax trades.
- **Hermes** registers hypotheses and experiment plans; it cannot promote its
  own work or change production configuration.
- **Aegis** investigates incidents; it cannot execute shell/service controls or
  apply unrestricted fixes.
- **Alex** synthesizes unresolved evidence; it cannot release a ticket or
  override lower deterministic layers.
- **Concierge** exposes governed status, explain, cancel, resume, and replay
  requests; it is not a shell or execution authority.
- **Atlas** remains deferred. A general orchestrator is not justified until the
  direct MVL demonstrates measurable value.

Exact per-agent tools, budgets, stop conditions, limitations, disable controls,
rollback controls, and acceptance evidence are machine-readable in the catalog.

## Read-only monitoring contract

`scripts/agent_runtime/monitoring.py` validates the complete roster and exposes
deterministic read models:

- catalog projection;
- fleet lifecycle summary;
- explicit run-state counts;
- unreviewed/unscored artifact counts;
- fixture-backed snapshot with `source_kind=FIXTURE`;
- Watch contextual panel for Sentinel, Argus, Darwin, Reflection, and Iris.

Fixture data is labeled `NOT_RUN` and cannot be presented as live runtime
activity. The Watch panel is read-only, contains no action controls, and cannot
change quality admission, the sovereign ticket state, or proposal eligibility.

The authoritative Postgres read adapter remains a later integration after the
persistence PR is reviewed. This tranche creates no duplicate persistence
layer.

## Minimum Viable Loop acceptance

No MVL agent becomes operational until evidence proves:

- 100 reviewed Watch artifacts;
- at least 20 known-bad regression fixtures;
- retrieval recorded on at least 95% of eligible Sentinel reviews;
- zero deterministic failures released;
- Sentinel false-positive rate measured;
- Darwin scoring complete for at least 95% of artifacts;
- Nightly Reflection creates candidate lessons;
- Iris or the operator can ratify or reject candidates;
- zero production configuration mutations;
- zero broker calls;
- zero authority violations.

## Operator interpretation

`DESIGNED` and `SHADOW` are evidence states, not marketing labels. Missing,
blocked, failed, cancelled, stale, deadline-exceeded, unreviewed, and unscored
states must remain visible. An unavailable agent must never hide deterministic
truth or weaken protective behavior.

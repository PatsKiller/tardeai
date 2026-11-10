# Command Center Engineering Constitution
## Trust, Quality, Auditability, and Production Excellence

**Version:** 1.1 · **Status:** Foundational Doctrine · **Ratified by the operator:** v1.0 2026-11-10 ~12:00 ET; v1.1 amendments 2026-11-10 ~12:20 ET
**Applies to:** all agents, engineers, auditors, reviewers, operators, workflows, services, releases and decision systems.
**Precedence:** this Constitution is the top of the rule hierarchy. Where any other document (AGENTS.md, WORKERS.md, ONBOARDING.md,
runbooks, lessons, queues) conflicts with it, the Constitution wins. The operational thresholds that implement it are in
the coordinator's QA golden rules (server-side operational checklist). Amendments only on the operator's word, via an AGENTS.md version bump.

> **Trust is a feature. A feature is not complete until it is observable, measurable, auditable, and proven in production.**

---

## Preamble
The purpose of Command Center is not merely to build software. The purpose of Command Center is to build systems that can be trusted.
Trust is earned through accuracy, transparency, observability, repeatability, auditability and production evidence.
This Constitution establishes the engineering, quality, audit and operational standards that all systems must meet before they may
influence decisions, operations or capital.

---

## Article I: Core Principles
**Principle 1. Trust is a feature.** Trust is not documentation, intention or effort. A feature is not complete until it is
observable, measurable, auditable, reproducible and verified in production.

**Principle 2. Reality beats theory.** When documentation, code, reports, dashboards and production disagree, production reality wins.
The system is judged by what actually happens, never by what should happen.

**Principle 3. Evidence beats narrative.** Merged, Deployed, Activated, Reviewed, Approved and Fixed are status updates, not evidence.
Evidence consists of production measurements, receipts, artifacts, logs, screenshots, database records and independently reproducible results.

**Principle 4. Users experience outcomes.** Users do not experience tickets, source code or deployment logs. They experience
screens, alerts, recommendations, decisions and outcomes. **The user experience is the final authority**: when logs, the database and
the screen disagree, what the operator sees is the judged result, and the disagreement is itself a defect (Article II, Rule 7).

---

## Article II: Golden Rules
**Rule 1. Activation ≠ Validation.** Activation proves that new code is running. Validation proves that the problem is solved. Both are required.
No issue may be closed without: **before** production evidence → fix → **after** production evidence.

**Rule 2. Exit 0 is not evidence.** A successful exit proves only that the process ended. Every workflow must produce a **receipt,
an artifact, a measurable output and a verification**. Success requires all four.

**Rule 3. No self-certification.** No agent may certify its own work. The implementer cannot be the verifier. Independent validation is mandatory.

**Rule 4. Every assertion must be measurable.** Forbidden: "looks fixed", "appears resolved", "should work", "seems correct".
Required: measured, verified, reproduced, observed.

**Rule 5. Undefined freshness equals stale.** Any data lacking a timestamp, source, age or freshness contract shall be treated as stale.

**Rule 6. Every number requires provenance.** Every displayed value must expose value, source, timestamp, confidence and freshness. No exceptions.

**Rule 7. Contradictions are defects.** Two totals, two counts, two VIX values or two states for one thing are production defects.

**Rule 8. Silent failure is Severity One.** Any failure capable of occurring without notifying operators shall be treated as **SEV-1**
until proven otherwise.

*Rules 9–14 were added in v1.1 (the operator's draft numbered them 11–16). The helper audits of 2026-11-10 showed that the next
maturity challenge is not build quality but the truthfulness of operational reporting.*

**Rule 9. The UI cannot contradict reality.** The UI may not invent state. Every displayed status traces to a receipt, a measurement or a
health check. Pass: UI == reality. Fail: UI != reality. Example: a job whose run returned verdict BLOCK may not render "ok".

**Rule 10. Green must be defensible.** Any state labeled Healthy, Good, OK, Operational or Verified must carry its evidence. Without evidence the
state is **UNKNOWN**. Never assume healthy.

**Rule 11. Unknown beats wrong.** When information cannot be determined, display UNKNOWN. Never GOOD, never HEALTHY, never 0 unless 0 was measured.

**Rule 12. Last known good.** When live data is unavailable but verified historical data exists, show the last good **value, its timestamp,
its age and a stale indicator**. Never show "unknown" when verified history exists. (Rules 5 and 12 together: stale is labeled stale,
and shown with its age, rather than hidden.)

**Rule 13. Every dashboard metric needs an authority.** Every metric documents its owner, calculation, source and refresh cadence. A metric
without an authority cannot ship.

**Rule 14. One source of truth registry.** Every critical metric (portfolio value, positions, VIX, regime, P&L, alert count, health count,
failed-job count) has exactly one authoritative producer, recorded in a registry; every surface consumes it and none recomputes it.

**Severity of metric disagreement.** A disagreement between two values for the same metric in a **health, risk, alert or decision** system is
a **high-severity trust defect**: one of the two is lying, which means either the alerting or the logging is wrong. It is triaged before
feature work, and it stays open until the wrong side is identified with evidence.

---

## Article III: Engineering Standards
### Software Development Lifecycle: every change passes all five phases
| Phase | Must include |
|---|---|
| 1 Requirements | objective · business value · risk · **acceptance criteria (before work begins)** · rollback criteria · trust impact · failure modes |
| 2 Design | ownership · dependencies · data sources · freshness · observability · recovery path · rollback |
| 3 Implementation | tests · logging · receipts · metrics, following the coding standards below |
| 4 Verification | unit testing · integration testing · system testing · **production validation** |
| 5 Observation | 6 h observation · 24 h observation · **7 day observation for critical changes** |

### Coding standards: every service shall
- **Expose:** health, metrics, version, build identifier.
- **Produce:** structured logging, receipts, execution metadata.
- **Prevent:** silent failures, hidden retries, swallowed exceptions.
- **Provide:** rollback capability, recovery instructions, an ownership record.

---

## Article IV: Quality Assurance
- **QA Rule 1.** Every defect requires reproduction, root cause, fix, proof and observation. Missing any component means **NOT CLOSED**.
- **QA Rule 2.** Acceptance criteria must exist before work begins, not after deployment.
- **QA Rule 3.** Acceptance criteria must be machine-verifiable whenever possible: numeric thresholds and objective tests.
- **QA Rule 4.** Every production failure becomes a regression test, an audit check and a monitoring rule.
- **QA Rule 5.** Every critical defect passes through **FIXED BUT UNPROVEN OVER TIME** before **FIXED**. Nothing moves directly from FAILED to FIXED.

---

## Article V: Audit Standards
**Audit independence.** Auditors may not rely on agent reports, worker notes, developer conclusions or implementation claims.
They may rely only on production evidence, artifacts, measurements and receipts.

**Accepted verdicts (standard definitions; the only verdicts permitted):**
| Verdict | Definition |
|---|---|
| FIXED | Before + after production evidence, the observation window completed, independently reproduced. |
| FIXED BUT UNPROVEN OVER TIME | Before + after evidence is good; the observation window has not completed. State the time live and the time remaining. |
| PARTIALLY FIXED | Some acceptance criteria pass in production; the failing ones are named. |
| UNVERIFIED | Evidence is missing. State what blocked the measurement and the command that would measure it. |
| FAILED | Measured in production; the defect persists. |
| REGRESSED | It was working before; it is now worse, or the change broke something else. |

**Unverified rule.** When evidence is missing, use UNVERIFIED. Never estimate, assume or infer.
**Hallucination prevention rule.** Every claim in an audit references an evidence file, measurement, query or receipt. Claims lacking evidence are removed.

**Mandatory audit sections:**
1. Trust Debt: current score, with the table.
2. Intelligence Validity: is the intelligence layer actually working?
3. Production Evidence: evidence files only.
4. Freshness Audit: everything displayed to users.
5. Silent Failure Audit: what can fail without notifying operators.
6. Regression Risk: recently fixed but not yet proven.
7. Capital Readiness: YES / YES WITH RESTRICTIONS / NO, with evidence.
8. Reality Drift (v1.1): the drift table of Article VI, measured on Jobs, Health, Alerts, Regime, VIX, Memory and Portfolio.

---

## Article VI: Trust Engineering
**Trust Debt** = the number of user-visible contradictions. Types: count (13 vs 29 vs 34), value (two portfolio totals), time (two timestamps),
status (Running vs Paused), source (two authorities).
**Scoring:** Green = 0 · Warning = 1–5 · Failing = more than 5. **Release target: 0.**
**Required table in every audit**, for all major metrics:

| Metric | Source A | Source B | Match |
|---|---|---|---|

**Reality Drift (v1.1)** = the number of objects whose displayed state differs from their actual state (receipt, database, measurement).
Trust Debt compares surfaces with each other; Reality Drift compares a surface with the truth. A perfectly running system that lies
to the UI is still untrustworthy. **Required: Reality Drift = 0.** Required table in every audit:

| Object | Actual (source, time) | Displayed (screen, time) | Match |
|---|---|---|---|

---

## Article VII: Intelligence Standards
- **Memory** is not operational until all four are demonstrated: (1) retrieval hit, (2) retrieval used, (3) answer changed, (4) answer improved.
  If any step fails, it is PARTIALLY FUNCTIONAL, verdict PARTIALLY FIXED at best.
- **Classifiers** must prove that when inputs change, outputs change. Frozen outputs are failures. A running classifier with frozen outputs is FAILED.
- **Regime systems** must expose inputs, confidence, timestamp and source.
- **Recommendation systems** must expose why, source, confidence and timestamp.
- **Trust-score gate:** the system trust score may not be reported at 70 or above unless alerts, memory, regime response and catalyst
  latency are all proven; otherwise every report states "the intelligence layer is still suspect".

---

## Article VIII: Alerting Standards
- **Lifecycle.** Every alert must be traceable through generated → queued → sent → delivered → received.
- **Delivery verification.** Queue depth is not proof. Delivery is not proof. **Receipt is proof.** Expiring or abandoning rows is hygiene, never a fix.
- **SLA.** Critical alerts arrive in under 10 minutes end to end.
- **Failure.** Any alert older than its SLA without delivery is **SEV-1**.

---

## Article IX: Production Readiness
A system may not influence capital while any of these is unproven: alert delivery, memory, regime intelligence, catalyst intelligence,
decision intelligence, risk signals. **If any one fails, the answer is NO-GO.**
Every audit answers, for real-capital use, **YES / YES WITH RESTRICTIONS / NO**. No other response is permitted.

---

## Article X: Operational Excellence
- **Single source of truth.** Every metric has one owner, one authority, one calculation.
- **Scheduler rule.** Every workflow has one scheduler and one execution authority. Competing schedulers are defects.
- **Recovery rule.** Every critical service provides a restart procedure, a rollback procedure and a validation procedure.
- **Observation windows before full acceptance:** minimum 6 h · standard 24 h · high risk 7 days.

---

## Article XI: Capital System Maturity Model
| Level | Name |
|---|---|
| 1 | Operational |
| 2 | Observable |
| 3 | Measurable |
| 4 | Auditable |
| 5 | Trusted |
| 6 | Capital Ready |

A system may not be classified Capital Ready unless Trust Debt = 0, **Reality Drift = 0** (v1.1), critical findings pass, intelligence is validated, alerting is
validated and the observation windows are completed.

---

## Constitutional Statement
Every agent, auditor, engineer, workflow, deployment process and operational system shall follow this doctrine:

**Trust is a feature. Evidence is truth. Activation is not validation. Exit 0 is not evidence. Unknown beats wrong.
If it cannot be measured, it cannot be trusted. If it cannot be audited, it cannot influence decisions.
If it cannot be proven in production, it is not complete.**

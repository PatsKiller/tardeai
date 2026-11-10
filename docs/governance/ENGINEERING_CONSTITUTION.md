# Command Center Engineering Constitution
## Trust, Quality, Auditability, and Production Excellence

**Version:** 1.5 · **Status:** Foundational Doctrine · **Ratified by the operator:** v1.0 2026-11-10 ~12:00 ET; v1.1 amendments 2026-11-10 ~12:20 ET; v1.2 (Rule 15) 2026-11-10 ~12:30 ET; v1.3 (Principle 5, Rule 16, Documentation Drift, reference cases) 2026-11-10 ~12:32 ET; v1.4 (Principle 6, Article VI-A Documentation Drift, Reference Case B, audit cover page) 2026-11-10 ~12:41 ET; v1.5 (Principle 7 Drift Must Be Measured, six canonical drift classes, trust maturity ladder, cover page risks) 2026-11-10 ~12:55 ET
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

**Principle 5 (v1.3). Health and verdicts are computed, never declared.** Every health state (Rule 15) and every verdict (Rule 16) is a
function of measurable evidence. A person, agent, report, ledger row or ticket may supply evidence; none may supply the state.

**Principle 6 (v1.4). Registration is not execution.** The existence of a workflow, scheduler, receipt, registration record,
database row, queue entry, deployment artifact, or status flag does not prove execution, completion, success, delivery, or
correctness. A queue row is not delivery. An embedding table is not working memory. A receipt is not useful output. A registered
workflow is not a running one. A healthy flag is not health. A completed deployment is not a fixed issue. Only the measured
outcome counts (Article II Rules 2, 15, 16; Reference Case B).

**Principle 7 (v1.5). Drift must be measured.** Any difference between intended state, documented state, deployed state,
executing state, displayed state, or observed state shall be measured as drift. Unmeasured drift is treated as unknown risk.
Measured drift becomes a tracked defect. The six canonical drift classes are defined in Article VI-A.

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

**Rule 15 (v1.2). Every health state must be computed.** Health, OK, VERIFIED and FIXED are never stored by hand: no worker, report, ledger row
or ticket may set `healthy=true` or `VERIFIED`. Every such state is `health = f(evidence)`, computed from measurable inputs (for example:
10 successful runs, 0 failures, 24-hour window complete, acceptance criteria passed), and the computation and its inputs are shown with it.
A state whose evidence cannot be computed is UNKNOWN (Rule 11).

**Rule 16 (v1.3). Computed verdict.** A verdict is not an opinion; it is a computed result derived from evidence. No FIXED, VERIFIED,
HEALTHY, PASS or READY state may exist without measurable inputs that reproduce that determination: acceptance criteria passed, observation
window complete, independent validation complete, trust-debt impact assessed. If any input changes, the verdict is recomputed automatically
(a regression flips FIXED back without anyone deciding to). A stored verdict with no reproducible inputs is UNVERIFIED.

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
9. Documentation Drift (v1.3): agent runtime rules version (session hook), agent documentation version (AGENTS.md the agents open),
   live release version, canonical checkout version, and the code each production service actually executes. Pass: all synchronized.
   Fail: any mismatch. Rules that are not in the checkout are eventually forgotten; code that runs outside a release is an unreviewed deploy.
   Measured by the six canonical drift classes of Article VI-A (v1.5).

**Audit cover page (v1.4).** Every audit opens with four computed lines, each backed by the sections below it:
System Status (capital readiness, item 7) · Audit Status (is the audit process itself working) · Governance Status (IMPROVING /
STABLE / DEGRADING, from the trend of Trust Debt, Reality Drift and Documentation Drift) · Primary Risk (the largest open category). v1.5 adds Secondary Risk (the next largest) and Most Important Achievement.
2026-11-10 cover page: **System Status: NOT CAPITAL READY · Audit Status: WORKING AS INTENDED · Governance Status: IMPROVING ·
Primary Risk: Reality Drift between reported state and actual state.**
Updated 2026-11-10 ~12:55 ET (operator, v1.5): **System Status: NOT CAPITAL READY · Audit Status: WORKING AS INTENDED · Governance
Status: SIGNIFICANTLY IMPROVED · Primary Risk: Reality Drift (6 of 12, LQ-1813) · Secondary Risk: Runtime Drift (4 processes on old
code in memory) · Most Important Achievement: drift is now measured, classified, audited, and assigned ownership.**

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

## Article VI-A: Drift, the six canonical classes (v1.4 Documentation Drift; v1.5 six classes)
Trust Debt (surface vs surface) and Reality Drift (surface vs truth) have a third sibling: **Documentation Drift**, where the
authorities that govern and run the system disagree with each other. It is measured in every audit (Article V item 9).
v1.5 (Principle 7): drift is one family with **six canonical classes**, all measured in every audit:

| Type | Definition | Measured by |
|---|---|---|
| Rule Drift | the Constitution version differs between its copies (coordinator file, session hook, repo, agent docs) | version line of each copy |
| Documentation Drift | the AGENTS.md version differs between the checkout agents open, the live release and main | `Policy-Version` of each |
| Runtime Drift | services execute different code from the release (old checkout, or old code held in memory since before a sync) | each process's cwd + start time vs the sync/activation time |
| Release Drift | release metadata (deployment log, BUILD_SHA, ledger "LIVE") differs from what is actually running | BUILD_SHA + process cwd vs the log |
| Reality Drift | a surface's displayed state differs from the actual state (Article VI) | the Article VI Reality Drift table |
| Source-of-Truth Drift | different authorities give different answers to the same question | the Article VI tables |

**Required: all six = 0.** Any non-zero type is a finding with an owner. Reference: 2026-11-10 12:3x ET, four versions at once
(main 30.0.1, canonical 31.0.0, live 32.0.0, fold 32.1.0); canonical synced to the fold at 12:39 ET.

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
Trust maturity ladder (v1.5, operator; replaces the v1.0 table):

| Level | Name | Meaning |
|---|---|---|
| 0 | Unknown | no measurements |
| 1 | Observable | problems are visible |
| 2 | Measurable | problems are quantified |
| 3 | Governed | acceptance criteria exist |
| 4 | Auditable | independent verification exists |
| 5 | Trustworthy | Trust Debt = 0 and Reality Drift = 0 |
| 6 | Capital Ready | all critical systems proven |

Rating 2026-11-10 ~12:55 ET (operator): audit program Level 4 (Auditable); platform Level 2 to 3 (Measurable / Governed); capital readiness not achieved.

A system may not be classified Capital Ready unless Trust Debt = 0, **Reality Drift = 0** (v1.1), critical findings pass, intelligence is validated, alerting is
validated and the observation windows are completed.

---

## Appendix A: Reference cases (v1.3, extended v1.4; used to train every auditor)
**Reference Case A (canonical): contradiction.** **Reference Case B (v1.4): Outcome Substitution:** the system measures existence,
registration or freshness and mistakes it for successful completion (Principle 6).

| Case | What the system said | What was true | Rules violated |
|---|---|---|---|
| **source-litmus-vs-yahoo (canonical case)** | `status=ok`, `outcome=ok` in the same file as `summary.verdict=BLOCK` (2026-11-10 07:46 ET) | the check blocked | 9, 10, 11, 15, 16 |
| Alert queue "clean" | queue depth 0; scorecard row passed | 655 rows abandoned in one update at 10:51:01 ET; 0 ever sent or delivered | 2, Art. VIII |
| DeepSeek 79.8% vs 0 failures | route `deepseek_only`; records say `deepseek-flash`; usage log says 0 failures | the calls ran on Anthropic and 219 of 262 failed in 24 h (provider identity drift) | 7, 14, Reality Drift |
| **Reference Case B: the scorecard (Outcome Substitution)** | scorecard rows PASS | per the operator's review of the 11-10 re-audit, 12 of 16 passes check only age or registration, not outcome. LQ-1811 (cc-opus-1, 12:51 ET on 631cef93b) reports 16 of 16 passes measure existence, registration, freshness or a count, and all 4 outcome checks fail; lead reproduction pending | Principle 6, 15, 16 |
| CIO memory | memory lanes running | `intelligence.embedding` = 0 rows; 0 decisions changed | Art. VII |

---

## Constitutional Statement
Every agent, auditor, engineer, workflow, deployment process and operational system shall follow this doctrine:

**Trust is a feature. Evidence is truth. Activation is not validation. Exit 0 is not evidence. Unknown beats wrong. Health and verdicts are computed, never declared. Registration is not execution. Drift is measured, never assumed.
If it cannot be measured, it cannot be trusted. If it cannot be audited, it cannot influence decisions.
If it cannot be proven in production, it is not complete.**

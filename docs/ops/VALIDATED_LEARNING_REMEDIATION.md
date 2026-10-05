# Validated learning remediation: release and operations

Status:      ACTIVE (operating procedure; deployment status requires the release receipt)
as_of:       2026-10-05T15:58:00Z
Measured at: implementation 61840b2add2c495d44f2c06e5ce0ca3da0fa2005; baseline served 60363378d-main-exact-phase2-20261005-093147
Owner:       platform / CIO advisory lifecycle

The implementation closes evidence and consumption gaps without granting broker authority,
enabling disabled agents, changing memory influence, or manufacturing learning outcomes.
This document describes the implemented contracts and release procedure. It does not certify
that a particular release is live or that an unattended cycle has exercised every path.

## Implemented behavior [CODE-ONLY until verified on the served release]

| Area | Behavior and owner |
|---|---|
| Promotion | `release_grant_preflight.py --ci-only --sha <full-sha>` requires completed successful push-to-main workflow runs for the exact candidate. Missing, pending, cancelled, failed, wrong-SHA and unavailable evidence refuse activation. The canonical deploy receipt retains workflow/run IDs and conclusions. Grant binding and rollback remain in force. |
| Topic session gate | `non_trading_hours_gate.sh` uses configured `PY`, then `VENV_PYTHON`, then the canonical interpreter. Regular/premarket sessions skip successfully; missing interpreter, failed check and unknown session return distinct failures. `data/health/non_trading_hours_gate.json` records the latest health state. |
| Operational truth | `check_expected_services.py` records exit status, signals, restart evidence and cgroup OOM counters in its durable receipt and transition journal. `check_worker_pins.py` distinguishes CURRENT-bound units, separate immutable deployments and ordinary working directories. No service is repinned by an inventory read. |
| Historical maturity | The existing current-evidence maturity route remains authoritative. The historical rubric and diligence export identify installation coverage as superseded; they do not claim demonstrated learning. |
| Research evaluation | The shared `cio_product_reassessment.research_impact` evaluator reports changed advisory judgment, review required, no change or blocked. It retains before/after state, evidence identities, thesis/retrieval/decision references and notification IDs. Freshness, subject and request identity are checked. A negative model label alone does not publish a thesis or force notification. |
| Replays and retries | Duplicate completion reports no new transition. Retries retain the original sources and timestamps and do not rerun paid research. Plan-store failure produces a blocked completion receipt. |
| Operator consumption | `persistent_agent_wake` consumes the actual operator turn for the subject. Answered turns and approval callbacks do not trigger new work. The research object that selected the wake gets a processing receipt even when another branch wins; processing is distinct from judgment influence. |
| Reuse | Retrieval receipts distinguish available, retrieved, used, rejected and judgment-changing evidence, including explicitly traversed graph references. Unknown reported references cannot be promoted to observed use. |
| Questions and gaps | Existing owners reconcile explicit originating question/gap identities, cited answers, partial answers, unresolved work and recorded expiry. Legacy question joins require a unique exact subject/question match. Routing uses bounded priority plus age fairness; unknown completion does not authorize another paid attempt. |
| Outcomes | Known review-only observations and vacuous falsifiers are rejected before commitment minting. Confirmed/refuted outcomes require joined observed evidence at the horizon. Price scoring requires an explicit metric, comparator and threshold; generic bullish/bearish prose is not a price forecast. |
| Checkpoints | Missing due dates may be derived only from recorded creation and an explicit parseable elapsed horizon. Otherwise the proposal requires migration review. Original records are retained. |
| Lessons and agents | Valid outcomes produce unratified review candidates with shadow defaults. Advisory use is separate from broker behavior. Registry/runtime disagreements are health findings, not activation instructions. |

## Local validation [OBSERVED, ISOLATED]

`PATH=.venv/bin:$PATH bash scripts/ai_local_acceptance.sh` exited zero for implementation
commit `61840b2add2c495d44f2c06e5ce0ca3da0fa2005`. Its final report marked targeted,
regression, release-equivalent and authority checks green. The 79 new regression tests are
registered in `scripts/run_cio_hardening_ci.py`:

- `tests/test_learning_operational_remediation.py`: promotion refusal, scheduling skip/failure,
  exit evidence and separate deployment contracts.
- `tests/test_learning_operator_remediation.py`: turn consumption, selection receipts and fairness.
- `tests/test_learning_research_remediation.py`: conflict/invalidation, unchanged/blocked evidence,
  expiry, subject/request mismatch, duplicates, retry lineage, reuse and question lifecycles.
- `tests/test_learning_outcome_governance.py`: honest scoring, conservative migration and preserved authority.

These are fixtures, not organic learning. The integrated release candidate must pass acceptance
again after merging a newer main. Remote CI must pass on the exact PR head and merged SHA.

## Baseline corrections [OBSERVED, READ-ONLY]

The audit at `2026-10-05T15:24:04Z` read persistent ledgers and aggregate database queries;
it wrote no production state and made no paid research calls. Its local evidence bundle is
`/home/johnclaw/tradeai-remediation-evidence-20261005/production-readonly-audit.json`.

- All 883 historical commitment outcomes remain `INSUFFICIENT_EVIDENCE`.
- 10,137 scheduled checkpoints have no due date. None had sufficient recorded elapsed-horizon
  information for automatic derivation. No migration was applied.
- The watch-decision queue was completing work: 274 completions in the prior 24 hours,
  1,329 queued and two running with current heartbeats. The older total-stall finding was stale.
- Twenty historical Hermes ledger requests were absent from the active projection. A local
  snapshot dry run of the existing bounded restoration routine found zero eligible recoveries.
  No retries were dispatched.
- 1,798 unambiguous legacy question-answer joins were available; live reconciliation was not applied.
- 204,901 contradiction candidates had no recorded verdict. Ownership and budgets must be
  checked before any recovery; this count is not authorization to adjudicate the backlog.
- CIO, held and research views returned the same declared Visa subject, thesis and research/result
  identities with zero paid calls. This does not establish decision-time influence.
- The canonical promotion ledger retained 633 archived records. No lesson was ratified or promoted.
- Current core-service cgroup counters did not establish an OOM cause for historical exits.

## Governed release and acceptance

Follow [the canonical release runbook](FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md), with the additional
exact-SHA post-merge CI gate in `cio_phase2_exact_main_deploy.sh`. Use a matching operator grant;
another campaign's `release-write` grant cannot authorize this release. Capture the immediately
preceding CURRENT release for rollback and obtain a deployment/production coordination lease.

1. Commit the candidate and documentation, run local acceptance, and push under the matching grant.
2. Require green CI on the exact PR head, merge the authorized PR and capture the full merge SHA.
3. Wait for completed successful push-to-main CI on that merge SHA. Prepare and promote only
   through the canonical deploy mechanism with grant binding enforced.
4. Verify CURRENT, BUILD_SHA/SOURCE_COMMIT, persistent-state links, API health and the cwd of
   every CURRENT-bound process. Preserve explicitly separate service deployments.
5. Observe natural scheduled receipts after activation: the topic gate's session decision,
   research evaluation dispositions and identities, consumed-turn suppression and question
   lifecycle transitions. Record time, source release and receipt IDs. Do not replay fixtures
   into production or manufacture a changed recommendation to satisfy acceptance.

The deployment receipt is `~/.local/state/cio-phase2-exact-main/deploy_receipt.json` and its
CI evidence is `post_merge_ci.json` beside it. Archive both with the exact candidate's acceptance
log. A passing promotion alone does not prove that all learning paths have run.

The existing due-diligence owner adds `expires_at`, `lifecycle_checked_at` and `lifecycle_events`
idempotently on its authorized apply path. An explicit production schema operation requires its
own matching `db-write` grant. Do not run a paid question-generation batch as a migration shortcut.

For checkpoint migration, `scripts/resolve_due_checkpoints.py --migrate-missing-deadlines`
previews proposals. `--apply` appends through the existing checkpoint owner and requires the
appropriate production-state authority. Retain unresolved migration-review cases and all
historical outcome records. No deadline, outcome, lesson promotion or agent activation may be
invented to make a metric improve.

On a failed required live acceptance check, use the canonical rollback command and verify the
restored process pins and health. Revoke only this task's unused grants at closeout.

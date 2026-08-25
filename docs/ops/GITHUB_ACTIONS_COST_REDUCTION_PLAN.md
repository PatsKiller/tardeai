# GitHub Actions cost-reduction plan

**Status:** analysis only. This tranche does **not** rewrite workflows.  
**Date:** 2026-08-25  
**Authority:** engineering cost control; does not change Trade AI safety or required release evidence.

Inventory of `.github/workflows/` (14 files). Only `watch-quality-governance-ci.yml` has `concurrency` / `cancel-in-progress`.

## Inventory

| Workflow | Every PR? | Feature push? | Path filter | Dup risk | setup-python | artifacts | Required-ish | Notes |
|---|---|---|---|---|---|---|---|---|
| cio-production-hardening-ci | **yes (no PR paths)** | main/wt/hardening/feat + paths | push only | overlapping CIO pytest | 1 | yes | **required `cio-hardening`** | Comment admits it runs on every PR so the required check is never Pending |
| release-readiness | yes | main + hardening/** | no | schwab/no-broker also in provider-cost | 1 | yes | often required | Local equivalent: `run_release_ci_equivalent.py --source-only` |
| provider-cost-ci | yes | main + one old feature branch | no | schwab/no-broker overlap | 1 | no | used as a check | pytest `tests/provider_cost` + scripts |
| aif-financial-senses-integration-ci | yes | main + feature/** + fix/** | no | **pytest `tests/financial_senses` also in financial-senses-ci** | 1 | no | used as a check | push on all `feature/**` is expensive |
| financial-senses-ci | PR path-filtered | main + one old feature branch | PR yes | overlaps AIF integration | **2 jobs** | no | not a branch gate | two ubuntu jobs, two setup-python |
| options-lifecycle-ci | PR + push paths | path-filtered push | yes | backend+frontend pair | py+node | yes | historically required | postgres service for some jobs |
| research-governance-ci | PR + push | path-filtered | yes | | 1 | no | | |
| watch-quality-governance-ci | PR + push | path-filtered | yes | | 1 | no | | **only workflow with cancel-in-progress** |
| agent-intelligence-foundation-ci | PR + push | path-filtered | yes | | 1 | no | | |
| agentic-mvl-ci | PR path-filtered | no push | PR yes | | 1 | yes | | |
| defense-sectors-ci | PR + push | path-filtered | yes | two jobs py+node | 2 runners | yes | | |
| reentry-watch-operator-ci | PR path-filtered | no | yes | | py+node | no | | |
| active-trader-policy-ci | PR path-filtered | no | yes | | 1 | yes | | |
| active-trader-live-motion-ui-validation | PR path-filtered | no | yes | | node | yes | | |

## What actually burns minutes

1. **Required check without PR path filter.** `cio-hardening` runs the full CIO suite on *docs-only* PRs (R16.2 evidence, this policy pack, etc.). That is the largest avoidable cost.
2. **Duplicate financial-senses pytest** on every PR: `aif-financial-senses-integration-ci` (no path filter) *and* `financial-senses-ci` (path filter). Unrelated PRs still pay for the integration job.
3. **`aif-financial-senses-integration-ci` push on `feature/**` and `fix/**`** — feature-branch pushes duplicate the PR run.
4. **Repeated `setup-python` + pip** on every workflow; almost no shared cache.
5. **No concurrency cancel** except watch-quality — superseded pushes keep running.
6. **provider-cost-ci and release-readiness** both run Schwab/no-broker validators on every PR.

## Phased repair (do not implement in this tranche)

### PHASE A — concurrency cancel (trivially safe)

Add to expensive workflows (cio-hardening, release-readiness, provider-cost, aif-financial-senses, options-lifecycle, defense-sectors, financial-senses):

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

Does not weaken evidence: the surviving run is the head SHA.

### PHASE B — stop duplicate feature-branch pushes

Where a `pull_request` job already validates the head:

- drop `push: branches: ['feature/**', 'fix/**']` from AIF integration;
- keep `push: main` if post-merge proof is wanted.

PR validation remains. Push-to-feature-branch CI is the waste.

### PHASE C — path-aware expensive jobs

Keep **required** checks from going Pending by introducing a **lightweight coordinator** (Phase D) rather than running the heavy suite on every path.

Until D exists, do **not** add a path filter to `cio-hardening` `pull_request:` — that is exactly why it currently runs everywhere.

Path-filter *non-required* duplicates (AIF integration, provider-cost) immediately.

### PHASE D — one lightweight aggregate required gate

Replace “run every expensive suite so the required check has a green box” with:

1. A 30-second `tradeai-required-gate` workflow that:
   - always reports success/failure;
   - runs the heavy suite **only** when changed paths match;
   - otherwise reports `skipped_irrelevant_paths` as success for the required context.
2. Point branch protection at that one context.

This is the correct fix for the “path filter makes required checks Pending” problem. It must be designed so a missed path still fails closed on merge-to-main (run full suite on `push: main`).

### PHASE E — self-hosted runner (optional)

A Trade AI self-hosted runner would cut billed `ubuntu-latest` minutes. Separate ops work: isolation, secrets, no broker credentials on the runner, queue fairness. Not a substitute for A–D.

## Estimated reduction (order of magnitude)

| Move | Typical saving |
|---|---|
| A cancel-in-progress | wasted minutes on superseded pushes |
| B drop feature/** push | ~50% of AIF/integration runs |
| C path-filter non-required jobs | most docs/policy PRs skip AIF + provider-cost |
| D aggregate required gate | **cio-hardening no longer runs on docs-only PRs** (largest) |
| pip cache | smaller, additive |

Do **not** weaken merge-to-main release evidence. Full CIO + release-readiness must still run on `main`.

## Local equivalent (already exists)

Agents should use these **before** requesting GitHub:

```
python3 scripts/run_release_ci_equivalent.py --source-only
python3 scripts/run_cio_hardening_ci.py
python3 scripts/run_cio_adversarial_suite.py
bash scripts/ai_local_acceptance.sh
```

GitHub CI is the independent check of an already-green candidate.

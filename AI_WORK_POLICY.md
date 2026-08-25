# Trade AI — AI Engineering & Remote-Cost Policy

Status: MANDATORY
Scope: ALL human and AI development tools working in this repository.

This policy applies regardless of client or model, including but not limited to:

- OpenAI Codex
- ChatGPT coding agents
- Grok Code
- Grok Build
- Claude Code
- Cursor
- GitHub Copilot
- VS Code agents
- terminal agents
- future coding agents

If a tool-specific instruction conflicts with this file, the safer and
more restrictive rule wins.

The environment flag that unlocks a single remote synchronization event is:

    TRADEAI_REMOTE_PUSH_AUTHORIZED=1

That is the namespaced form of `REMOTE_PUSH_AUTHORIZED`. A general instruction
to continue, implement, test, mature, or finish does **not** set this flag.

---

# 1. CORE DEVELOPMENT MODEL

GitHub is a RELEASE AND INDEPENDENT VERIFICATION BOUNDARY.

GitHub is NOT the normal development/test loop.

The default lifecycle is:

LOCAL WORK
→ LOCAL COMMIT
→ LOCAL TEST
→ LOCAL ITERATION
→ LOCAL COMMIT
→ LOCAL REGRESSION
→ LOCAL RELEASE-EQUIVALENT
→ ONE REMOTE PUSH
→ ONE GITHUB CI
→ MERGE
→ DEPLOY

Do NOT use:

edit
→ push
→ wait for CI
→ edit
→ push
→ wait for CI

as the normal development process.

---

# 2. LOCAL COMMITS ARE THE CHECKPOINT MECHANISM

A development checkpoint means:

    git commit

It does NOT mean:

    git push

Agents may create as many useful LOCAL commits as necessary.

Examples:

- implementation checkpoint
- test checkpoint
- refactor checkpoint
- evidence checkpoint
- documentation checkpoint
- fault-test checkpoint

These commits remain local until the tranche is ready for remote verification.

---

# 3. REMOTE PUSH BUDGET

Default budget per coherent development tranche:

    target pushes: 1
    target GitHub CI cycles: 1
    maximum pushes without explicit operator approval: 2

The second push exists only for a failure that could not reasonably have been
caught in the local acceptance process.

A third push requires explicit operator authorization.

The following are NOT valid reasons to push:

- "see whether CI passes"
- save a checkpoint
- show progress
- update a test count
- update evidence
- update closeout wording
- let another agent inspect the branch
- poll a partially finished implementation
- obtain a GitHub SHA
- verify code that can be verified locally

---

# 4. NO INTERMEDIATE REMOTE CHECKPOINTS

Do NOT:

- push after every feature
- push after every bug fix
- push after every test addition
- create remote checkpoint commits
- create evidence-only PRs during active implementation
- repeatedly amend/open/update a PR while development is unfinished
- poll GitHub CI as a substitute for local testing

Accumulate the completed tranche locally.

---

# 5. REQUIRED LOCAL GATES BEFORE FIRST PUSH

Before the first remote push of a tranche, all applicable gates must be true:

    LOCAL_TARGETED_GREEN=true
    LOCAL_REGRESSION_GREEN=true
    LOCAL_RELEASE_EQUIVALENT_GREEN=true
    LOCAL_AUTHORITY_AUDIT_GREEN=true
    LOCAL_DIFF_REVIEWED=true

At minimum use repository-native local validation.

Examples where applicable:

    python3 scripts/run_release_ci_equivalent.py --source-only

    python3 scripts/run_cio_hardening_ci.py

    python3 scripts/run_cio_adversarial_suite.py

plus relevant:

    pytest
    frontend/type checks
    builds
    schema tests
    authority tests
    security tests

Do not push unfinished code merely to outsource validation to GitHub Actions.

The wrapper `scripts/ai_local_acceptance.sh` is the default command. It may skip
heavy suites when the tranche diff is policy/docs/hooks only.

---

# 6. TEST-FIRST / LOCAL-FIRST ITERATION

During development:

1. identify the smallest relevant subsystem;
2. add or strengthen the test;
3. run targeted local tests;
4. implement;
5. rerun targeted tests;
6. commit locally;
7. proceed to next local iteration.

Do NOT rerun the entire repository after every small edit.

Use:

targeted tests during iteration

then:

full relevant regression near tranche completion.

---

# 7. GITHUB CI IS THE FINAL INDEPENDENT CHECK

GitHub CI should validate an already locally-green candidate.

Expected sequence:

LOCAL ACCEPTANCE GREEN
→ PUSH
→ CI
→ MERGE

If GitHub CI fails:

1. identify the remote/local difference;
2. reproduce the issue locally;
3. fix all known related failures locally;
4. rerun complete local acceptance;
5. create local commit(s);
6. make ONE corrective push.

Do not perform trial-and-error through remote pushes.

---

# 8. NATURAL / LIVE EVIDENCE STAYS LOCAL UNTIL MILESTONE

Natural timer evidence, soak evidence and live operational receipts do NOT
need to be pushed individually.

Examples:

- material-scan receipts
- free-first receipts
- natural event observations
- checkpoint outcomes
- model-performance observations
- longitudinal results
- service restart evidence
- watcher results
- natural no-change cycles

Keep them locally during the observation window.

Commit/push them when they form a meaningful milestone or closeout.

---

# 9. WATCHERS MUST NOT DRIVE REMOTE ACTIVITY

A watcher may:

- observe timers
- inspect local state
- inspect CURRENT
- collect receipts
- append local evidence

A watcher must NOT automatically:

- push commits
- update PRs
- trigger CI
- create evidence-only PRs
- merge
- deploy

unless the operator has explicitly requested that action.

---

# 10. EVIDENCE BATCHING

During a tranche, accumulate locally:

    tests
    JSON evidence
    receipts
    markdown closeouts
    maturity matrices
    fault results
    screenshots/metadata
    manifests

Push the completed evidence set together with the tranche.

Avoid:

implementation push
→ evidence push
→ closeout push
→ typo push
→ maturity push

Prefer one coherent remote candidate.

---

# 11. PR POLICY

Do not open a PR merely because development started.

Preferred:

local branch
→ complete work
→ local acceptance
→ push
→ open PR

Once the PR exists:

avoid further pushes unless CI identifies a genuine unresolved problem.

PR descriptions may summarize the complete local validation result.

---

# 12. DOCS-ONLY WORK

Documentation/evidence-only changes should normally be batched.

Do not run an expensive code CI fleet repeatedly for documentation iteration.

When workflow design permits, docs-only changes should use lightweight checks.

---

# 13. REMOTE-COST AWARENESS

Before any push, ask:

    Is there useful validation that can still be performed locally?

If yes:

DO NOT PUSH YET.

Also ask:

    Does the remote repository need this state right now?

If no:

DO NOT PUSH YET.

---

# 14. AGENT HANDOFFS ARE LOCAL

Switching from:

Codex → Claude Code
Grok → Cursor
Cursor → Codex
Claude → Grok

does NOT require a GitHub push.

Agents should inspect the same local repository/worktree.

Use local:

git log
git status
git diff
commits
evidence

for handoffs.

GitHub is not an inter-agent message bus.

---

# 15. BRANCH / COMMIT BEHAVIOR

Agents may create coherent local commits freely.

Do not rewrite protected main.

Do not force-push protected branches.

Do not push directly to main unless the repository's explicit release policy
allows it.

Before remote synchronization:

    git status
    git diff origin/main...HEAD
    git log origin/main..HEAD

must be reviewed.

---

# 16. REMOTE PUSH AUTHORIZATION

Automated agents should treat remote pushes as a gated operation.

Default:

    REMOTE_PUSH_AUTHORIZED=false
    TRADEAI_REMOTE_PUSH_AUTHORIZED unset or not equal to 1

An explicit operator instruction such as:

    "push this tranche"
    "sync the branch"
    "open the PR"
    "run GitHub CI"

authorizes that remote synchronization event.

A general instruction to "continue", "implement", "test", "mature", or "finish"
does NOT by itself authorize repeated remote pushes.

The git pre-push hook enforces this independently of which agent wrote the code:

    TRADEAI_REMOTE_PUSH_AUTHORIZED=1 git push ...

Do not set that flag merely to bypass this policy.

---

# 17. MAXIMUM TWO-PUSH RULE

Per development tranche:

Push 1:
    final locally-green candidate

Push 2:
    one corrective candidate if remote CI reveals a genuine issue

After Push 2:

STOP before another push and request operator approval.

Exception:

an explicit operator instruction overrides this limit.

---

# 18. CI WORKFLOW DESIGN POLICY

GitHub workflows should themselves minimize billed runner time.

Prefer:

- path-aware execution
- one aggregate required gate
- conditional expensive jobs
- concurrency cancellation
- local CI-equivalent scripts
- caching where safe
- avoiding duplicate test suites across jobs
- avoiding repeated dependency installation
- docs-only fast paths
- self-hosted runners where appropriate and separately configured

Expensive jobs should not run merely to report a required status if a lightweight
coordinator can safely report the aggregate result.

This file does not itself rewrite GitHub workflows. That is a separate tranche.

---

# 19. CONCURRENCY

Expensive GitHub Actions workflows should use an equivalent of:

    concurrency:
      group: ${{ github.workflow }}-${{ github.ref }}
      cancel-in-progress: true

when doing so does not compromise required release evidence.

New pushes should not leave superseded expensive runs executing unnecessarily.

---

# 20. TRADE AI SAFETY BOUNDARIES

This cost-control policy never weakens Trade AI's existing safety controls.

Continue to preserve all applicable authority constraints, including:

    READ_ONLY_ADVISORY
    MEMORY_BEHAVIOR_INFLUENCE=0

unless a separately governed change explicitly says otherwise.

Do not infer financial authority from permission to develop software.

---

# 21. DEPLOYMENT IS DISTINCT FROM PUSH

A git push does not imply deployment authorization.

A merged PR does not imply deployment authorization.

Deployment follows the repository's canonical release process and its own
authorization boundary.

---

# 22. TOOL-SPECIFIC RULE

Every coding assistant must read this file before making changes.

If the assistant cannot automatically discover this file, its adapter instruction
must direct it here.

If an assistant cannot comply with these rules, it must stop rather than silently
falling back to repeated remote experimentation.

---

# 23. DEFAULT STATUS REPORT

At the end of a local development session report:

    local_branch:
    local_commits_ahead:
    targeted_tests:
    regression_tests:
    release_equivalent:
    remote_pushes_this_tranche:
    github_ci_cycles_this_tranche:
    ready_to_sync:
    remaining_local_work:

Do not push merely to produce this report.

---

# 24. GOLDEN RULE

LOCAL COMPUTE IS THE DEVELOPMENT LOOP.

GITHUB COMPUTE IS THE FINAL INDEPENDENT VERIFICATION LOOP.

Never push merely to ask GitHub whether unfinished code works.

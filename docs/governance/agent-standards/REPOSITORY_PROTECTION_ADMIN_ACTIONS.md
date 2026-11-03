# Repository protection — actions only a repository administrator can take

```
Measured:  2026-09-25 via `gh api repos/PatsKiller/tardeai/branches/main/protection` (read-only)
Base-SHA:  1c60ecb4264ba4dcc6a38106e76fae0d96a26787
Class:     AGENTS.md §17 — branch-protection or required-context changes are operator-only
```

A workflow file existing is not enforcement. Only the branch-protection settings below decide what
can merge. **Actions 1 and 3 were applied on 2026-09-25 by the operator's decision** (re-measured
below). The review-related actions are deferred. This PR adds files (CODEOWNERS, PR template) that do
nothing until an administrator turns the matching settings on.

## Measured on `main`, 2026-09-25 after the operator's change (read back via the API)

| setting | value | meaning |
|---|---|---|
| protected | true | |
| required status checks | `cio-hardening` **and** `agent-governance`, `strict: true` | both must be green on an up-to-date head |
| required approving reviews | **0** | no human or independent review is required |
| require code-owner reviews | **false** | CODEOWNERS (added here) is advisory until this is on |
| dismiss stale reviews | true | |
| enforce admins | **true** | administrators can no longer merge past the required checks |
| require last-push approval | false | |
| required signatures | false | |
| conversation resolution | false | |
| force pushes / deletions | disabled / disabled | |
| rulesets | none (`[]`) | |

## Proposed administrator actions (operator decides each)

1. ~~Add **`agent-governance`** to the required status checks~~ **DONE 2026-09-25** (operator decision; read back: `['cio-hardening','agent-governance']`, strict).
2. Set **required approving reviews ≥ 1** and **require code-owner reviews**, so the sensitive
   paths in `.github/CODEOWNERS` need a reviewer who is not the author.
   **Constraint:** PRs here are authored by the operator's own account, and GitHub never counts an
   author's approval. So independent review needs a **separate reviewer account or a review bot**.
   Decide which before turning this on, or every PR will be unmergeable. **Deferred 2026-09-25** by
   operator decision until a second reviewer account or bot exists (the only collaborator is the PR author).
3. ~~Turn on **enforce admins**~~ **DONE 2026-09-25** (operator decision; read back `enforce_admins: true`).
4. Require **last-push approval**, so a review can't be satisfied by a push made after it. **Deferred** with item 2.
5. Consider **required conversation resolution** for authority PRs.
6. Decide whether path-conditional jobs (e.g. `active-trader-policy-ci`, `bitemporal-memory-correctness-ci`)
   should become required for the paths they cover (a ruleset can scope this).
7. Decide whether merge is a separate grant. **Today it isn't enforced:** with 0 required reviews,
   anyone with write access, or any agent holding a push grant whose reason happens to mention
   merging, can merge a green PR. Items 2 and 4 are what would make merge authority real (item 3 is now on).
8. Turn on GitHub **secret scanning push protection**, as a server-side layer behind
   `scripts/check_no_secrets.py`.
9. ~~Enable the GitHub **merge queue on `main`**~~ **NOT AVAILABLE for user-owned repositories**
   (measured 2026-10-09: `owner.type: "User"`). AGENTS.md 4.1.0 §23.13 no longer depends on it: the
   standing merge approval rests on Agent A's board review verdict, the three required checks green on
   the exact head, and main CI green on the merged SHA before any promote. The section below is kept
   as the record and applies only if the repository is ever transferred to an organization (an
   operator decision).

## Action 9 — enable the merge queue on `main` (operator) — NOT AVAILABLE (user-owned repository)

Preconditions found 2026-10-09 (read-only `gh api repos/PatsKiller/tardeai` and `.../rulesets`):

- The repository is owned by a **User** account (`owner.type: "User"`), public, with no rulesets.
  GitHub documents the merge queue for repositories owned by an **organization** (public, or private
  on Enterprise Cloud). If the "Require merge queue" option is not offered, the queue cannot be
  enabled here without transferring the repository to an organization — itself an operator decision.
  In that case the §23.13 standing approval does not apply and merges stay operator-approved.
- No workflow under `.github/workflows/` triggers on `merge_group`. A queued merge waits for its
  required checks on the `merge_group` event; without that trigger it never completes. Adding
  `merge_group:` to the `on:` block of the workflows that produce `agent-governance`,
  `cio-hardening` and `release-readiness` is a separate PR (workflow files are governed).
- Required checks measured 2026-11-02
  (`gh api repos/PatsKiller/tardeai/branches/main/protection/required_status_checks`):
  `cio-hardening`, `agent-governance`, `release-readiness`, `ci-gate` — `strict: false`.
  The 2026-10-09 measurement above named three; `ci-gate` has since been added. **`secret-scan` is
  not required**, which is how PR #2465 merged on 2026-11-01 with `secret-scan` red on four heads
  (main red at `f96c6399f`, deploy blocked). Proposal to make it required: see
  "Proposed: make `secret-scan` required" below.

Steps (UI): Settings → Rules → Rulesets → New branch ruleset → name `main-merge-queue`, enforcement
**Active**, target `main` (Include default branch) → enable **Require merge queue** (merge method
squash or merge, as today; build concurrency 1; "Only merge non-failing pull requests" on) and
**Require status checks to pass** with `agent-governance`, `cio-hardening`, `release-readiness`
→ Create. (Where the classic branch-protection page offers "Require merge queue" instead, tick it
there; the three checks are already required.)

Steps (gh, equivalent):

```
gh api -X POST repos/PatsKiller/tardeai/rulesets --input - <<'JSON'
{
  "name": "main-merge-queue",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "merge_queue", "parameters": {
      "merge_method": "MERGE", "grouping_strategy": "ALLGREEN",
      "max_entries_to_build": 1, "min_entries_to_merge": 1, "max_entries_to_merge": 1,
      "min_entries_to_merge_wait_minutes": 0, "check_response_timeout_minutes": 60}},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": false,
      "required_status_checks": [
        {"context": "agent-governance"}, {"context": "cio-hardening"}, {"context": "release-readiness"}]}}
  ]
}
JSON
```

Verify (read back; the setting is not enforced until the API says so):

```
gh api repos/PatsKiller/tardeai/rulesets --jq '.[] | {id, name, enforcement}'
gh api repos/PatsKiller/tardeai/rules/branches/main --jq '[.[].type]'   # must include "merge_queue"
```

## Proposed: make `secret-scan` required (operator-only, AGENTS.md §17)

**Why.** Branch protection requires four checks. `secret-scan` is not one of them, so a PR can be
green on every required check while secret scanning is red — and one did: PR #2465 merged on
2026-11-01 with `secret-scan` failing on four heads (`6f21e6d6a`, `1f6715af0`, and two more). Main
went red at `f96c6399f` and the deploy poller refused to promote until a human re-ran the job.

**Confirmed before proposing** (measured 2026-11-02):

- The workflow `.github/workflows/secret-scan.yml` runs on `pull_request` with types
  `[opened, synchronize, reopened, ready_for_review]` — that is every non-draft PR head and every new
  push to one. Drafts are skipped deliberately (push policy v2, `draft-quick-check` covers them).
- It reports **one stable check name, `secret-scan`**, verified against PR #2465's head:
  `gh api repos/PatsKiller/tardeai/commits/<head>/check-runs` returned exactly one matching run,
  `{"name": "secret-scan", "conclusion": "failure", "status": "completed"}`.
- Adding it does not create a draft deadlock: drafts are exempt from required checks until they are
  marked ready, which is exactly when `ready_for_review` fires the scan.

**The command (operator runs this; no agent may).** Two traps, both verified 2026-11-02:

* the PATCH **replaces** the whole set, so the current checks must be carried into it;
* the legacy `contexts` form **drops the `app_id` binding** on every check it sends. All four live
  checks are bound to app `15368` (GitHub Actions); re-sending them as bare contexts would leave
  them unbound, which is a weaker protection than the one being extended. Use the `checks` form,
  built from the live list rather than typed out here.

```bash
# 1. Read the live set, including each check's app binding.
gh api repos/PatsKiller/tardeai/branches/main/protection/required_status_checks \
  --jq '{strict, checks: [.checks[] | {context, app_id}]}'

# 2. Build the new set from the live one plus secret-scan on the same app (15368), then PATCH it.
gh api repos/PatsKiller/tardeai/branches/main/protection/required_status_checks \
  --jq '{strict, checks: ([.checks[] | {context, app_id}] | . + [{"context":"secret-scan","app_id":15368}] | unique_by(.context))}' \
  > /tmp/required_checks.json
cat /tmp/required_checks.json   # confirm five entries, all with an app_id

gh api -X PATCH repos/PatsKiller/tardeai/branches/main/protection/required_status_checks \
  --input /tmp/required_checks.json

# 3. Read back: every entry must still carry its app_id.
gh api repos/PatsKiller/tardeai/branches/main/protection/required_status_checks \
  --jq '[.checks[] | "\(.context)@\(.app_id)"]'
```

**Do not add `secret-scan` to the merge-queue ruleset.** Two independent reasons, both measured:

1. A `PUT /rulesets/<id>` replaces the **whole** `rules` array — a payload carrying only the status
   checks deletes the `merge_queue` rule, silently disabling the queue.
2. `.github/workflows/secret-scan.yml` has **no `merge_group` trigger**. A queued merge is judged on
   the `merge_group` event, so a required check that never runs there would wait until
   `check_response_timeout_minutes` (60) and then fail every queued merge.

If the merge-queue ruleset is ever put in force, adding `merge_group:` to `secret-scan.yml` is the
precondition, and that is a `.github/**` change (held). Until then, classic branch protection is the
only place `secret-scan` becomes required.

**Known gap (not fixed here, `.github/**` is held).** `secret-scan.yml:52` skips on `mergify/*`
speculative branches. Mergify runs the required suites there so a batch does not fail for lack of
checks; the secret scan does not, so a batch's speculative head is not secret-scanned. The real PR
head still is, and the gate above reads the real head — so this is a coverage note for the batch
window, not a hole in the requirement.

**Risk and fallback.** Making a check required only ever blocks a merge that is already red; it
cannot block a green one. The fallback is the reverse PATCH without `secret-scan`. Until the
operator runs it, the code-side gate (`scripts/lib/pr_all_checks_green.py`) refuses merges from the
work-pipeline applier on any red check, so the hole is narrowed but not closed for merges that
happen outside it (Mergify, the operator's own `gh pr merge`).

Then open a trivial PR, add it to the queue (`gh pr merge <n> --auto` routes through the queue once
it is required) and confirm the three checks run on a `merge_group` ref before it lands. Record the
values in the "Measured" table above.

Rollback: `gh api -X DELETE repos/PatsKiller/tardeai/rulesets/<id>` (or set `"enforcement":
"disabled"` with `gh api -X PUT repos/PatsKiller/tardeai/rulesets/<id> ...`), or untick the option in
the UI. Classic branch protection is untouched by the ruleset, so the existing required checks and
enforce-admins stay in force after a rollback. With the queue off, the §23.13 standing approval no
longer applies.

After each change, re-run the measurement above and record the new values here. The setting is
not enforced until the API says so.

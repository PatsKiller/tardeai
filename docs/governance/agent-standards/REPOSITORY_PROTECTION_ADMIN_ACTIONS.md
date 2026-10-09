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
- Required checks measured 2026-10-09 (`gh api repos/:owner/:repo/branches/main/protection/required_status_checks`):
  `cio-hardening`, `agent-governance`, `release-readiness` — the three §23.13 condition (b) names.
  The 2026-09-25 measurement above predates `release-readiness` becoming required, and `strict` now
  reads `false` (the operator turned strict up-to-date protection off on 2026-10-09); the ruleset below
  keeps it off.

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

# Repository protection — actions only a repository administrator can take

```
Measured:  2026-09-25 via `gh api repos/PatsKiller/tardeai/branches/main/protection` (read-only)
Base-SHA:  1c60ecb4264ba4dcc6a38106e76fae0d96a26787
Class:     AGENTS.md §17 — branch-protection or required-context changes are operator-only
```

A workflow file existing is not enforcement. Only the branch-protection settings below decide what
can merge. **None of the proposed changes has been made.** This PR adds files (CODEOWNERS, PR
template) that do nothing until an administrator turns the matching settings on.

## Measured today (`main`)

| setting | value | meaning |
|---|---|---|
| protected | true | |
| required status checks | `cio-hardening` only, `strict: true` | `agent-governance` runs on every PR but **cannot block a merge** |
| required approving reviews | **0** | no human or independent review is required |
| require code-owner reviews | **false** | CODEOWNERS (added here) is advisory until this is on |
| dismiss stale reviews | true | |
| enforce admins | **false** | an administrator can merge past every check |
| require last-push approval | false | |
| required signatures | false | |
| conversation resolution | false | |
| force pushes / deletions | disabled / disabled | |
| rulesets | none (`[]`) | |

## Proposed administrator actions (operator decides each)

1. Add **`agent-governance`** to the required status checks (keeps `cio-hardening`).
2. Set **required approving reviews ≥ 1** and **require code-owner reviews**, so the sensitive
   paths in `.github/CODEOWNERS` need a reviewer who is not the author.
3. Turn on **enforce admins**, or record in writing why administrator bypass stays open.
4. Require **last-push approval**, so a review can't be satisfied by a push made after it.
5. Consider **required conversation resolution** for authority PRs.
6. Decide whether path-conditional jobs (e.g. `active-trader-policy-ci`, `bitemporal-memory-correctness-ci`)
   should become required for the paths they cover (a ruleset can scope this).
7. Decide whether merge is a separate grant. **Today it isn't enforced:** with 0 required reviews,
   anyone with write access, or any agent holding a push grant whose reason happens to mention
   merging, can merge a green PR. Items 2–4 are what would make merge authority real.
8. Turn on GitHub **secret scanning push protection**, as a server-side layer behind
   `scripts/check_no_secrets.py`.

After each change, re-run the measurement above and record the new values here. The setting is
not enforced until the API says so.

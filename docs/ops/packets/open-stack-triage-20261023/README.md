# WP-33 item 5: open stack triage evidence

Status: REVIEW — six superseded source PRs closed; nine remain open with blockers
as_of: 2026-10-24T03:41:43Z
Measured at: main `325ff34f2b3b272090b78d5210a2847c8c30bd2a`; session `codex-wp33-triage-20261023`

This packet records a source/PR audit. It makes no deployment, workflow activation, contract-review or runtime-acceptance decision. No source/config/protected file was changed. Closing a duplicate PR preserved its branch.

- `snapshot.json`: exact heads, source/main ancestry, changed-path comparisons, required checks and initial/latest mergeability for all eighteen scoped PRs.
- `closures.json`: post-close readback for #1599, #1628 and #1804–#1807, with exact unchanged heads and reasons.
- `closure-proof.json`, `replacement-ancestry.json`, `integration-delta-comparison.json`: original-to-accepted-integration comparisons and main ancestry.
- `1804-allowlist-state-proof.json`: the only first-batch LLM integration delta not matching by zero-context patch ID; both planner entries and the RI blocked reason equal current main exactly.
- `patch-equivalence.txt`: the four remaining LLM commits are patch-equivalent to main; first-batch differences are addressed by the separate semantic-record proof.
- `llm-process-summary.json`: all twenty-five incremental process records already match main exactly.
- `1599-exact-head-functions.json`: all five original relay-env functions equal current main structurally. The renderer and secret-name classifier also match by full blob.
- `1628-current-tests.json`: all twenty-three original test functions remain structurally identical on main. The integration harness only adapted the release_venv fixture source path.
- `f09-lanes.csv`: all forty-one staged lanes, with name-only comparison to the closed read set. Five script names match; this is not exact-argv, capability-audit or runtime admission proof.
- `desk-row-summary.json`: three proposed shadow monitors and two inert/staged targets from #1940; corresponding reviewed contracts are absent from current main.
- `claims.selected.json`: captured active/retained claim ownership; WP-21 holds registry/allowlist/contracts and related tests. Older stale claims are recorded separately from live ownership by their `state` field.

The source-required checks at capture were `cio-hardening`, `agent-governance`, `release-readiness` and `ci-gate` (`strict:false`). Historical green checks belong to the captured old heads; they do not prove an integration with current main.

Reproduction uses read-only Git/GitHub operations. Examples:

```bash
git merge-base --is-ancestor aa0b9b8d912bbc3fb0d440f1bcc5d3a6ee25b9f3 325ff34f2b3b272090b78d5210a2847c8c30bd2a
git cherry -v 325ff34f2b3b272090b78d5210a2847c8c30bd2a cb6dd1064e78ba5e755b50356635aba5a15a8ea1
gh pr view 1940 --json state,headRefOid,mergeable,mergeStateStatus,statusCheckRollup
gh pr checks 1940 --required
```

The full original GitHub bodies, failure-log responses and raw source comparisons remain in the worker's private cache at `/home/johnclaw/.cache/rtc/codex-wp33-triage-20261023/`; they are not copied into this packet. No credential or account-number value was collected or published. Two requested failed-log reads returned empty output, so #1940's specific failing test cause remains NOT_MEASURED.

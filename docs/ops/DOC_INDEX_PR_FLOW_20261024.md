# WP-02 documentation-index conflict correction and proposed PR flow

Status: PROPOSED replacement; comment correction implemented locally
as_of: 2026-10-24
Owner: Coordinator and operator for approval/integration; codex-doc-index-pr-flow-20261024 for this packet
Design-Task: DSN-20261024-doc-index-pr-flow-P1-T1
Source base: 8b24e113740cda70c25e4823c16c46ea3b63cf7f

GitHub mergeability cannot be inferred from a local `merge=union` success. The repository
comments made that claim for both `docs/INDEX.md` and the append-only wave ledger. Both
comments are corrected; the actual merge attributes remain byte-identical. Real source
conflicts still require review. Existing generated-index requirements remain active.

The coordinator reported sibling index conflicts and absent CI on #2052–#2059. This package
does not claim to have re-run their GitHub checks or remotely updated those PRs. Instead it
reproduces the mechanism in isolated Git repositories: adjacent per-PR index insertions
conflict with an ordinary text merge; source-only PRs merge and yield a complete index after
one batch regeneration. Local merge behavior is measured; real post-rollout GitHub acceptance
is NOT_MEASURED.

The [registered design](../designs/DSN-20261024-doc-index-pr-flow.md) and
[review packet](packets/doc-index-pr-flow-20261024/REVIEW.md) propose a complete transition:

1. PR CI validates an exact committed-tree index projection without changing the checkout.
2. Artifacts bind full base/head/tree identities, source and index digests, complete markdown
   coverage and missing-header debt. The existing generator/checker supplies titles and syntax.
3. The coordinator regenerates and commits the index once on the integrated batch, before full
   exact-head CI. Main/batch committed-index checks remain strict.

The [executable prototype](packets/doc-index-pr-flow-20261024/project_index.py) is offline and
proposal-only. It is not registered as an active gate, never accepts an activation environment
variable, and never stages, commits or pushes. It rejects invalid baseline coverage, altered
artifacts, identity drift, untracked docs, dirty source, per-PR index edits and symlink markdown.
It reads the generator and documents from committed Git blobs, with no filesystem-listing
fallback. An emitted receipt is evidence of the projection, not an approval or authority token.

Changed regression tests stay in the existing `generated_file_merge` CI gate. They demonstrate
the real sibling merges and batch check, plus missing/stale/mistitled/duplicate/malformed and
preamble failures, source and receipt tampering, SHA/ancestry, clean-tree and output boundaries.
`psycopg2` import refusal is explicitly verified with the required nopg shim before these tests.
No production DB, service, live-server request, broker, credential or remote write is involved.

Validation: 61 tests passed in 6.15 seconds across the existing generated-file merge,
CI-registry/index integrity and overnight index suites with `psycopg2` hidden. Ruff, current
committed-index validation, test coverage (zero new unlisted files), host-path guard (zero new
violations) and staged whitespace checks passed. No required GitHub check has been run for
this unpublished branch.

Source integrity evidence and test receipts are retained at
`/home/johnclaw/.cache/rtc/docs-index-pr-flow-20261024-evidence/`. The integrity receipt proves
that protected policy, hooks, guard, current CI workflow/tail, index generator and gate registry
files are unchanged, and that all noncomment attribute entries match the base exactly.

The review packet gives exact proposed policy replacements and a source-backed consumer matrix.
P2 must change the runner tail, both workflow checks, committed-tree tests, contributor rules,
claim guidance and coordinator batch step together. A one-step skip or uncommitted CI rewrite
would weaken coverage and is explicitly excluded. P3 requires real sibling PR/check receipts.

This delivery prepares a reviewable correction and replacement proposal. It does not activate
the new process, close conflicting PRs, prove required GitHub checks, or claim a served release.
Publication remains queued to the coordinator; the source claim is retained.

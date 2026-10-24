# Proposed documentation-index PR flow

Status: PROPOSED
as_of: 2026-10-24
Authority: Offline package; no active gate or policy changes
Design-Task: DSN-20261024-doc-index-pr-flow-P1-T1

The problem is a shared generated file in every docs PR. `.gitattributes` union helps
local Git; GitHub's server-side mergeability does not honor that merge driver. A local
union-merge test proves local behavior only. The correction leaves attributes intact.

The proposed replacement has two explicit contracts:

| Context | Required artifact and check | Writer |
|---|---|---|
| Agent PR | Docs source changes, no `docs/INDEX.md` diff; generate `INDEX.md` plus `receipt.json` from exact committed Git blobs; validate base index and candidate coverage/title/syntax; publish them as CI artifacts bound to full base/head/tree and content digests | CI writes only the job artifact directory |
| Coordinator integration batch / main | Regenerate and commit `docs/INDEX.md` once after source integration, then run the existing committed-index checker plus full required checks on the resulting exact head | Coordinator under existing branch/merge authority |

No schedule, release, train capability, remote-write permission or new index store is added.
The generated index remains a single committed map on main. The PR artifact is a preview of
the candidate tree; it must not be described as the committed map or approved documentation.

`project_index.py` is a proposal-only prototype for the PR artifact contract. It:

- Requires full base/head SHAs, exact current HEAD, ancestry, clean tracked files and no untracked docs.
- Refuses a PR diff to the committed index. This requires policy approval before use on real PRs.
- Reads tracked markdown through `git ls-tree` and batch blob reads, with no filesystem fallback; symlinks are refused.
- Reuses `extract_title`, header detection, rendering and `index_problems` from the existing generator.
- Validates the base index against the base tree before tolerating index drift caused by new PR docs.
- Emits exact markdown coverage, original missing-header debt, full head tree, source digest and index digest.
- Recomputes the full receipt/body to reject altered rows, stale identities and forged ACTIVE/authority labels.
- Writes only a new, explicitly selected artifact directory outside the checkout. It never stages, commits or pushes.

The receipt is not a signature or deployment capability. CI must take base/head identity from
its trusted event/job context, not user-supplied environment assertions, and must upload the
artifact with its exact run identity. Missing proof is a failure; generation is not a substitute
for document content review. A title match does not prove a document's factual claims.

## Integration changes required together after approval

| Current consumer | Proposed reviewed change | Integrity retained |
|---|---|---|
| `AGENTS.md` §14.1 and generated-files contributor paragraph | Apply the exact replacement clauses below through the policy process | One generator, complete tree coverage, header debt and main/batch drift enforcement |
| Plan A2/B0 contributor directions | Coordinator changes branch-index instruction only after the new contract is active | Agents cannot silently choose an unapproved mode |
| `scripts/run_cio_hardening_ci.py` `docs_index_drift` tail | Explicit trusted PR context selects projection; batch/main keeps committed checker | Same required job names, failures still propagate |
| `.github/workflows/cio-production-hardening-ci.yml` and `cio-full-suite-sharded.yml` Docs index drift steps | PR projection with required uploaded receipt; batch/main committed checker | Do not leave an old independent tail red or broadly skip docs validation |
| `tests/test_overnight_g3_docs_index.py` committed-tree tests | Separate fixture-tested PR-artifact contract from batch/main committed-tree contract | Missing/stale/duplicate/mistitled/malformed rows still fail; header debt remains visible |
| `tests/test_ci_gates_registry_20261021.py` local merge proof | Keep its local-only scope; add approved plain-text source-only sibling proof | Local proof never presented as GitHub proof |
| `scripts/regenerate_generated_files.sh` and coordinator batch construction | Keep explicit tracked-doc staging and no implicit staging; run generation once on integrated tree before exact-head CI | Batch cannot pass with stale committed index |
| `config/agent_claim_shared_paths.json` and claim-board documentation | Update guidance from per-PR row edits to approved projection/batch ownership | Source claims remain exclusive; generated map has one integration writer |

Do not activate projection in one workflow while the test gate or runner tail still demands
per-PR committed-index parity. Do not use `--write-index` inside PR CI and then call the old
checker green: that would hide an uncommitted mutation rather than prove the new contract.

## Proposed policy replacements, not applied

In `AGENTS.md` §14.1, replace the paragraph beginning `When it is built: a generator walks`
through `documentation debt.` with:

> `scripts/report_docs_inventory.py` is the sole documentation-index generator. The committed
> `docs/INDEX.md` on main and every coordinator integration batch lists every tracked markdown
> document by path and title; CI fails on a missing, stale, duplicate or mistitled row, an altered
> preamble or malformed table content. Row order may differ, and canonical regeneration sorts it.
> Agent PRs change documentation source, without editing this generated map. Their CI generates
> and validates an index projection from the exact committed candidate tree, publishes the full
> base/head/tree identities and source/index digests, and reports `MISSING HEADER` debt without
> dropping those documents. The coordinator regenerates and commits the map once after source
> integration, before all required checks run on the final batch head. Neither a recently generated
> artifact nor local merge-driver success proves GitHub mergeability or document approval.

In the generated-files contributor paragraph beginning `After merging main into a branch`, replace
the index instructions with:

> After merging main into a branch, validate the approved PR index projection from the clean exact
> tree and retain its receipt; agent PRs do not edit `docs/INDEX.md`. On the coordinator integration
> branch, stage new docs by exact name, run `python3 scripts/report_docs_inventory.py --write-index`,
> commit the generated map, and require `--check-index` on that final batch head. Generation stages
> nothing. Until the reviewed CI and batch transition is active, the existing per-PR committed-index
> rules continue to apply.

These replace stale instructions; they add no authority. Protected policy is deliberately
unchanged in this delivery. The operator chooses the amendment/version process before apply.

## Reproducible offline review

From the package's worktree, these commands are safe as written and perform no remote write:

```bash
cd /home/johnclaw/wt-codex-doc-index-pr-flow-20261024
PYTHONPATH=/home/johnclaw/.cache/rtc/nopg PYTHONDONTWRITEBYTECODE=1 TRADE_AI_CI=1 /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python -m pytest -q tests/test_generated_file_merge_driver.py tests/test_ci_gates_registry_20261021.py tests/test_overnight_g3_docs_index.py
python3 scripts/report_docs_inventory.py --check-index
git diff --check
```

The fixture test invokes the prototype's CLI with real exact SHAs in its own disposable Git
repositories and requires output outside them; no placeholder command needs a real host state.
An apply command is intentionally absent: this is an unapproved replacement contract, not an
already reviewed executable policy patch. After approval, P2 must build one exact-base package
covering the consumer matrix and policy clauses, then prove it in a throwaway clone before apply.

## Proof and remaining acceptance

The plain-text negative control reproduces a same-gap index conflict. The source-only positive
control merges both real fixture branches with `merge=text`, then regenerates and passes the
unchanged committed-index checker. Invalid baseline rows, missing/extra/mistitled/duplicated rows,
changed preamble, junk, artifact tampering, forged receipt fields, wrong or short SHAs, nonancestor
base, dirty files, untracked docs, index edits, symlink markdown and checkout-output writes fail.
No production service, DB, GitHub merge or real PR CI is exercised by those proofs.

P2/P3 remain PROPOSED. Real GitHub sibling mergeability and four required checks are NOT_MEASURED
until the reviewed complete transition is applied. Existing conflicting PRs need coordinator
regeneration/integration; this package does not remotely update or merge them.

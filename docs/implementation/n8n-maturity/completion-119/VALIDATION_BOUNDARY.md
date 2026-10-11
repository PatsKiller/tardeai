# Completion119 validation boundary

Status: BLOCKED. Evidence: TEST_ONLY for the rejected run; SOURCE_ONLY for caller attribution. Runtime/CURRENT are NOT_MEASURED. This packet authorizes nothing.

## Refused action

The latest native PR-profile attempt ran on source head `53bafd4e529c866ef3d66648d29e9a276f3639d2`, with observed origin/main `c15b7b98caa3909665ac5abb878f02eb558d6ff6`:

```sh
cd /home/johnclaw/worktrees/refactor-completion-119
python3 run-isolated-completion.py final-pr-profile-declarations .venv/bin/python scripts/run_cio_hardening_ci.py --profile pr --base origin/main
```

Its receipt is `reassess-gates/final-pr-profile-declarations.json`: `STOPPED_ON_REFUSAL`, exit -15, 38.519 seconds, PID 756, refusal detail `host command crontab`, `reaped_to_empty: true`. The corresponding `.log` and `.audit.jsonl` are retained. No acceptance is derived from this attempt, and it is not retried.

The external isolation guard in `reassess-safety/barriers.py:123` rejects a command whose executable basename is `crontab`, without recording its complete argv. Therefore the receipt does not distinguish a real host binary from a scratch executable with the same name. A host-crontab read is NOT_MEASURED, not OBSERVED_HOST.

## Bounded source attribution

Both source reviews agree on the strongest explanation:

1. `tests/test_tranche_b_readiness_20261008.py:119` creates a text-file scheduler adapter at `tmp_path/crontab`.
2. Its `_env` helper explicitly injects that absolute path through `CRONTAB_CMD`.
3. The first cutover test launches `scripts/pipelines/cutover/cutover_after_close_close-capture.sh`, which executes `_cutover.py`.
4. `scripts/pipelines/cutover/_cutover.py:103` launches the injected command to read the scratch table.
5. The unchanged isolation guard rejects the adapter's basename.

The read-only reconstructed plan, `reassess-gates/static-native-unit-plan.log`, matches the rejected attempt's selection metrics. In initial unit `n8n_parallel_20261007`, the two child launches preceding PID 756 match the preceding test file's two Bash syntax checks, followed by the first tranche-B cutover test. Exact argv and executed caller identity remain uncaptured; this fit supports SOURCE_ONLY attribution, not definitive observed attribution.

The malformed-registry, source-report and repricer-discovery fixture corrections are independently tested isolation improvements. They are not proven causes of the final crontab refusal: the reconstructed initial units did not yet include the registry gate. Earlier rejected receipts are preserved rather than relabeled.

## Operator decision and bounded next step

The refactor playbook at `/home/johnclaw/n8n-maturity-verification/refactor/CODEX_REFACTOR_PLAYBOOK.md` §1 says: “If a permission prompt, hook or classifier refuses something, stop that lane, write why in your report, and continue with the next lane. Do not find another way.” §1A includes a hook/guard/classifier block as a refusal. This action is stopped under those instructions.

No fixture rename, guard edit, test deselection, exemption, budget change or unconstrained retry is applied. No valid existing grant for overriding this classification has been established. The operator must adjudicate the scratch-fixture classification and authorize a concrete isolation correction or an independent approved validation environment before further native-profile validation.

A candidate source correction for operator review only is a distinct basename for this explicitly injected scratch text-file adapter, with negative controls proving the path is absolute, within the test's scratch directory, passed only through `CRONTAB_CMD`, and never resolved from PATH. Every existing dry-run/no-write, missing-line refusal, backup, single-write, repeat-apply refusal and byte-for-byte rollback assertion must remain. The real host command must remain blocked. This candidate is not implemented because applying it after the refusal could route around the classifier without an operator decision.

After an approved correction is committed, validate its new exact head under an unchanged production/secret/DB/network/host-command boundary, then run the same native PR profile with a new evidence tag. Stop again on any actual refusal. The acceptance requirement remains exit 0, no capability refusals, unchanged native selection/gates, and all owned children reaped. A targeted pass alone does not satisfy it.

This is a validation decision only. It grants no push, PR, remote merge, deployment, workflow import, contract review, model/provider selection or scheduler cutover. No push or release grant is requested while required validation is blocked.

## Retained source results

All 119 scoped lanes are accounted for: 84 source-corrected including partial repairs, four prior preparations retained, and 31 unchanged owner/authority boundaries. None is newly operationally admitted. The three operational configuration files and their reviewers remain unchanged from audited source `65337da5366b469c8478b198187201bd37671bc2`. The combined targeted suite passed 421 tests; source-only standalone gates and static integrity receipts are separate evidence, never runtime acceptance.

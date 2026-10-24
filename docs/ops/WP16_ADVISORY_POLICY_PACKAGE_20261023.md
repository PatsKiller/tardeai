# WP-16 advisory-policy package delivery

Status: DRAFT — tested proposal artifacts; operator publication, application and ratification pending
as_of: 2026-10-24T02:33:00Z
Measured at: `4acb33ada3eed278c5f7652fcdcd6cbda15e68e5`, AGENTS 20.1.0 ACTIVE
Design-Task: DSN-20261023-handoff-v3-P4-T16

The stale 20.0.0-based advisory-sizing package has been rebuilt on current main. The deliverable is the reviewable [operator package](packets/agents-21-20261023-wp16/README.md), not an activated policy or runtime feature. Actual AGENTS.md, adapters, behavior rails, Ask-CIO wiring and live state are unchanged. The old external `handoffs/scratchpad-20261023/agents-21/` remains historical; use this rebuilt package's commands below.

The proposal preserves the operator's option-B formula, the three explicitly scoped ratifying clauses and the existing unconditional behavior rail. Its pure stdlib library returns no size until actual 21.0.0 ACTIVE with §29 present. Existing position exposure is required rather than silently defaulted to zero; only the policy's risk-budget default is retained. Model-written behavior fields are stripped. The importer regression examines Python import nodes and permits only the eventual Ask-CIO contract importer.

## Verification and limitations

| Isolated export | Policy-state check | Policy suite and section-zero parity |
|---|---|---|
| Unchanged | 20.1.0 ACTIVE | 711 passed, 5 skipped |
| Proposed | 21.0.0 PROPOSED | 782 passed, 5 skipped |
| Synthetic ratified fixture | 21.0.0 ACTIVE | 782 passed, 5 skipped |

The synthetic approval token/PR in the last stage is a test fixture and confers no authorization. The unchanged baseline also has five skips. The two proposal stages retain one warning from an existing parsed source's invalid escape; there are no test failures. The package also adds the new policy test's canonical CI gate using `scripts.lib.ci_gates.render`. The CI-gate registry suite passes separately on both the final proposed export and synthetic ratified export (25 tests each). Older policy hashes remain pinned: normalizers remove only the new 21.0.0 amendment before checking their original content.

Evidence retained on this host:

- Three-stage receipt: `/home/johnclaw/.cache/rtc/codex-wp16-20261023/acceptance-x16_s1oy/result.json` and each referenced `tests.log`.
- Final aggregate output: `/home/johnclaw/.cache/rtc/codex-wp16-20261023/verify-final.log`.
- Patch normalization proof: `/home/johnclaw/.cache/rtc/codex-wp16-20261023/normalized-patch-parity-72i_4l64/parity.json`; all 31 produced/base files remain byte-identical to the tested proposed export. Only exact empty context lines in patch artifacts were normalized for Git whitespace checks.
- Operator read-only preview: `/home/johnclaw/.cache/rtc/codex-wp16-20261023/operator-preview.log`; exact source pins matched and no claim/worktree/policy was changed.
- Negative control against an older base refused test-file drift. A later WP-15 20.2.0 policy also requires rebuilding this package before application.

Helper Python lint/format, shell syntax and byte compilation pass. Package integrity is checked before testing or operator application. These fixture results do not establish GitHub required-check status, actual policy ratification, deployed feature acceptance or Ask-CIO consumer behavior.

## Pinned artifacts

| Artifact | SHA-256 |
|---|---|
| `BASE_MANIFEST.json` | `8aa2a1f248df4b3183978bd5dc886e958b0662d2afdbd42da5d2113555bb7342` |
| `agents-21.0.0-proposed.patch` | `1e7630ad76aa1e0123c4eb533e6ef8c184c158de676e3abe03040b6c8f278cc2` |
| `code-tests-21.0.0.patch` | `a74b86e70b6a44403dba194affc8033191449467b161b7f50aea6566296e4f18` |
| `SHA256SUMS` | `5b96c81c69d2782689635a051c94920727afad473623a06e3378c3e88f03a096` |

The manifest binds the raw current policy, all four adapters, the protected behavior-rail module and every existing file the generated patch changes. Preview compares current remote main with local `origin/main`, refuses stale refs and refuses relevant source drift. It does not silently replace a 20.2.0 policy with 20.1.0.

## Operator application and ratification

Publication of this artifact-only branch is tracked separately by its `PUSH_NEEDED` progress event. After review, the operator can preview the proposal against freshly fetched main, then apply it in a separate operator worktree:

```bash
cd /home/johnclaw/wt-codex-wp16-20261023
git fetch origin
bash docs/ops/packets/agents-21-20261023-wp16/apply21-operator.sh --preview
bash docs/ops/packets/agents-21-20261023-wp16/apply21-operator.sh --apply
```

Apply creates `/home/johnclaw/wt-agents-21-0-0-wp16-apply` on `ops/agents-21-0-0-wp16-20261023`, claims its exact paths and runs the policy checks. It prints the real review/commit/push/PR commands, and executes none of those publication steps. After the operator publishes that proposal PR, request its exact real token command:

```bash
cd /home/johnclaw/wt-codex-wp16-20261023
bash docs/ops/packets/agents-21-20261023-wp16/ratify21-operator.sh --preview
```

After the operator posts the printed approval comment, verify and apply that exact PR/head-bound ratification:

```bash
bash /home/johnclaw/wt-codex-wp16-20261023/docs/ops/packets/agents-21-20261023-wp16/ratify21-operator.sh --apply
```

Paste back preview/apply summaries, policy test summaries, the real proposal PR URL/full SHA, and the actual approval-comment reference. Do not paste secrets. Helpers require a clean proposal worktree, matching branch/head/PR and an exact operator-owned token before ratifying. The coordinator owns merges and releases after required checks are green.

WP-16 remains open for actual operator ratification/merge and the later, separately claimed `size_suggestion` integration in `scripts/lib/cio_ask_contract.py` after #2011. No current answer or prospect receives sizing from this delivery. WP-15 currently ships only another inert package; if it lands first as actual 20.2.0 policy, rebuild and re-verify this package before operator application.

# Disabled disk hygiene: CI follow-up

Status: source preparation in progress. Original `01a3563915dbb15eee0536140e0350279b1092f6`
was removed from batch 21 after CI and is not accepted main. Its branch, source
and historical proof remain unchanged. This follow-up starts from accepted
PR #2072 main `e148e2a65303d8aa6e6c9437784ae83f9e2bebe8`; it uses a content
port, with no stale-feature merge or rebase.

The original package changes 23 paths. Nineteen independently owned paths were
ported byte-for-byte after verifying they had no intervening accepted-main
change. Existing accepted main and C1 proposals are preserved. The two normally
handed-off health/allowlist files were merged by named disk fields: unrelated
rows and the operative reviewed contract are unchanged.

The actual CI defects are:

| Defect | Finding / action |
| --- | --- |
| Whole tmp-hygiene test still expected two env names | The shared reader closure also declares three path-only names: `CANONICAL_SOURCE`, `TRADEAI_AGENT_CLAIMS_REPO`, `TRADEAI_RELEASES_BASE`. Keep enforce mode and the exact closed set of five; keep plan-only argv and all existing guards. The **whole 29-test file passes with psycopg2 hidden**. |
| Registry serialization | Original 01a adds one escaped arrow among 147 literal arrows. Preserve the canonical literal UTF8 serializer; do not weaken `load_registry_exact` or its W1 test. Registry is still held by the active C1 worker and is unmodified in this branch. |
| Source-pinned activation packet | Recompute all source-config pins, their reviewed-input digest, and rules/draft pins after final registry bytes and accepted/C1 integration. Current copied pins are historical and are not ready for publication. |

The full all-registered psycopg2-hidden/native profile is waiting for C1's
current full run to finish, per the integrator's capacity instruction. The
prior 420 scoped tests, the 29 tmp tests and syntax checks are not full-project
CI. No ready/PUSH_NEEDED assertion is made for this partial checkpoint.

The standing configuration remains disabled with approval pending. No cleanup,
worktree removal, host schedule, unit, release, broker, order, stop, credential
or provider operation has been performed. The source packet remains operator
reviewed/applied; no approver identity is invented here.

Current task: `DSN-20261024-disk-standing-ci-fix-P1-T1`, claim
`20261024T212136Z-codex-36b3d3c4`. Evidence is under
`/home/johnclaw/.cache/rtc/codex-disk-standing-ci-fix-20261024/`:
`scope-preflight.json`, `unique-source-port.json`, `free-config-field-port.json`
and `tmp-whole.xml`. Next: normal registry handoff, literal UTF8 field merge,
exact repinning, whole requested suites/checks, then one updated follow-up
publication request. Original 01a must not be published.

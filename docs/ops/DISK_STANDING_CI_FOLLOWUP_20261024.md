# Disabled disk hygiene: CI follow-up

Status: reported source defects fixed; full-project validation blocked. Original `01a3563915dbb15eee0536140e0350279b1092f6`
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
| Registry serialization | Original 01a adds one escaped arrow among 147 literal arrows. The normal C1 ownership handoff completed before this branch edited the file. The canonical literal UTF8 serializer now passes `load_registry_exact`; its W1 assertion is unchanged. The exact frozen C1 NEVER_SCHEDULED/kind-none proposal row remains at manual-prefix index482. All accepted lane objects and order remain unchanged. |
| Source-pinned activation packet | All five source-config byte hashes, their reviewed-input document digest, and rules/draft pins were regenerated after the final registry union. Review remains `PENDING_OPERATOR_REVIEW`, with null approver and approval time. Source metadata preservation does not import C1 feature ancestry or activate a lane. |

The full all-registered psycopg2-hidden profile has not been run on this head.
C1's completed broad run records genuine Hermes write and canonical-runtime
mkdir refusals in unrelated legacy fixtures. Repeating those known production
state attempts is outside this worker's authority; their barriers remain intact.
The complete affected/native execution passed **578 tests in 142.35s**, with zero failures/errors/skips: 11 whole files and both requested real-tree nodes. Twelve read-only validators returned zero; all configuration hashes stayed unchanged during CHECK. Neither
the prior 420 scoped tests nor the 29 tmp tests is full-project CI. Full-project
acceptance remains blocked pending legitimate fixture isolation and a fresh run;
no ready/PUSH_NEEDED assertion is made for this partial checkpoint.

The standing configuration remains disabled with approval pending. No cleanup,
worktree removal, host schedule, unit, release, broker, order, stop, credential
or provider operation has been performed. The source packet still requires operator
review and application; no approver identity is invented here.

Current task: `DSN-20261024-disk-standing-ci-fix-P1-T1`, claim
`20261024T212136Z-codex-36b3d3c4`. Evidence is under
`/home/johnclaw/.cache/rtc/codex-disk-standing-ci-fix-20261024/`:
`scope-preflight.json`, `unique-source-port.json`, `free-config-field-port.json`,
`format-preserving-port.json`, `literal-utf8-fixture-proof.json`,
`registry-union-repin.json` and `tmp-whole.xml`. The staged docs-index check also passes. Next: retain the full-project blocker and obtain the
coordinator's disposition before an updated publication request. Original 01a
must not be published.

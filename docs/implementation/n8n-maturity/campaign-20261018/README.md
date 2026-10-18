# n8n operational maturity campaign — 2026-10-18

Status: IN PROGRESS; production mutations held pending the recorded gates  
Owner: Codex integrator; Agent A remains Chief Architect  
as_of: 2026-10-18T19:42:00Z  
Measured at: source `3af0a8bdd659e02bf6f493c071800c6a227ae292`; initial served `a2aef7b4d2de17e737526337a2ffc37848deda4f`

The operator's 2026-10-18 execution mandate authorizes scoped implementation,
reviewed exact-head merges, canonical release, reversible activation/cutover and
rollback. It issues no guard grant and ratifies no policy amendment. This record
does not authorize deletion, trading-policy changes, broker operations, destructive
retention, credentials or changes to the guard ledger.

## Baseline and immutable identities

- Physical primary repository: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`.
- Integrator worktree: `/home/johnclaw/tradeai-wt-n8n-maturity-campaign-20261018`;
  branch `wt/n8n-maturity-campaign-20261018`.
- Refreshed main: `3af0a8bdd659e02bf6f493c071800c6a227ae292`.
- Initial CURRENT: `a2aef7b4d-main-exact-phase2-20261018-103647`.
- Active source policy: AGENTS.md 14.0.0. Proposed disk-hygiene 15.0.0 is outside
  this campaign. The historical standing merge window has expired; this campaign
  uses the current operator authorization and still requires independent review.
- #1851 refreshed head: `865a9a0b127a37454438389abdaddd1962b079d1`.
- #1853 refreshed head: `0baddc47481f3ec1673fabf23e37e7b044a54dca`.
- No campaign push, merge, deployment, activation or scheduler change has occurred.
  These heads are review inputs, not approved mutation targets.

Initial host observations: portfolio-server, coordination gateway, relay and run
executor were active. Loopback `/api/health` returned 200. Loopback `/v3/` returned
200; this is the trusted local listener and proves no remote authentication claim.
Tailscale Serve maps the tailnet CC origin to the Unix auth proxy. The tailnet
hostname failed DNS resolution from this execution context even outside the
sandbox. This is an access limitation; it does not establish a CC outage.
Resolving the same TLS hostname to the verified tailnet IP subsequently returned
302 from `/` to `/v3/` and 200 from `/v3/`. That is reachable UI evidence, not a
login redirect or proof of an authenticated session. The current CC configuration
reports authentication rather than enforcing it globally; real MFA/session and
SPCX threat-model acceptance remain open. No public exposure was added.
Authenticated-session and real MFA acceptance remain UNPROVEN.

The 19:41Z service refresh confirmed the same served SHA and all five queried
application services active, with the independent n8n watchdog, breach detector
and health-tick timers waiting. Exact unit names have the `tradeai-` prefix.
Queries of similarly named unloaded units are not service-outage evidence.

Two host read-only workflow snapshots found all 19 active graphs matching;
[the latest snapshot](baseline/workflow-drift-host.json) is a point observation,
not continuous coverage. The existing cutover report found 338 active cron lines
and mapped all 338. Its historical `MIGRATED_PROVEN` category does not establish
this campaign's stricter business-output or consumption acceptance. The direct
Communications SQL read was unavailable; its counts remain unmeasured.

[Hermes receipt reconciliation](baseline/hermes-receipts.json) finds existing live
receipts for five of six stages: grader, tag engine, outcome learning, config
governor and tune. Feedback has none. The first four still report
`declared_not_enforced`. Tune's two October 17 receipts explicitly report valid
`empty_allowed` work at 12:00/17:00 ET using source `7b07774ad8af3db523d7e297eae6192a8c25e024`.
These receipts are preserved without rerunning learning. Exact consumed input
versions and downstream consumption remain unproven.

[All 46 active lanes without output signals](baseline/no-output-signals.json)
are individually classified: 11 scheduled-output gaps, four reminder/event
acknowledgement gaps and 31 retained systemd assets. None receives a blanket
no-work exemption or an invented output count.

## Work ownership

| Workstream | Owner | Write scope |
|---|---|---|
| Integration, generated files, documentation, CI registration | root Codex | this campaign directory; further files explicitly leased before editing |
| Shared output verdict, gateway inputs and CI integration | root integrator, reusing reviewed agent commits | isolated contracts-enforcement worktree |
| Host evidence attestation and activation verification | contracts_routes agent | isolated attestation owner, framework validator and fixed read-only producer |
| Repair acceptance, deadlines and cost truth | independent_review agent (implementation author) | isolated fixer/evaluator worktree; integration-owned versioned check policy |
| Communications generations, delivery and recovery wording | retirement_collector agent | isolated consumer/fan-in/notifier/host-sender worktree |
| Independent review of final candidates | a nonauthor agent, assigned after implementation | read-only candidate inspection and hermetic tests |

Agent A's false-green, registry-truth, output-proof and fixer worktrees are retained.
No peer branch, production store or shared crontab is edited concurrently. F07 and
registry_systemd assets remain unchanged. Nightly mutation and Claude fixer stay
disarmed; their current grants explicitly preserve that hold.

## Review dispositions

| PR | Result at recorded head | Disposition |
|---|---|---|
| #1851 | Required exact-head CI green; independent 81-test subset green. Additional expected-assertion regressions show missing tune c2 admission and malformed/symlink grant-ledger acceptance. | HOLD; fix canonical validation and every mutation boundary before reliance. |
| #1853 | Safe data-quality subset: 24 passed. Required contexts absent at initial review. Also changes ATR stop/target and execution readiness; packet uses a nonempty token and records ownership before scheduler mutation. | HOLD whole PR. Reuse only reviewed, separately scoped nonfinancial data-quality changes. |
| #1852 | Proposed policy amendment for automated disk deletion. | OUT OF SCOPE; no ratification or deletion authorized here. |

Locally committed follow-ups remain **implemented, not pushed/merged/deployed**:
output truth `2475379fc0b2b7b4f68300cc1ffa42cddd19d612`, closed gateway input
`3ef2fb5c07ac84c67be88035ebae0f56b0941c20`, authentic grant admission and held
unsafe packet mutations `b14bfc542d481499d7bf1efcc4b8147de6332628`, eligibility
collector `76d4ee0a65cfb6f84ff686abd3ca55338d0e6d09`, and atomic restart budgeting /
budget-independent critical enrollment `afab1a474dfa52509d57ebd9e9b7923ee2d14352`.
The first combined enforcement branch is
`wt/n8n-contract-enforcement-20261018` at
`2333c8e1b00f4be3b5fab653bf67d9a42fdcd399`. Required local checks and independent
review are in progress. There is no matching new campaign branch/head push grant;
the pre-existing Agent A grants are not consumed for these branches.

Retirement remains held pending trusted host attestation and a fully proven
transactional rollback. The collector's current CLI fails closed; its pure
eligibility projection is code-only and cannot establish production eligibility.
No new qualifying soak has started, so a next eligibility timestamp cannot yet
be computed. Re-evaluate at collector installation/first qualifying natural slot;
then use 48 actual continuous hours and the lane's required natural cycles.

The independent review artifacts are initially under
`/tmp/n8n-campaign-20261018/review/`; sanitized evidence is integrated with the
implementation, never used to claim a deployment or live effect.

## Acceptance thresholds fixed before evaluation

| Measure | Required threshold and window |
|---|---|
| Useful-output truth | Every applicable live terminal success in the observed cohort has fresh same-lane/run/attempt, effective-live output satisfying its reviewed rule and downstream proof; missing evidence is unavailable. |
| False recovery / duplicate effects or deliveries | Zero in the complete observation window; any occurrence holds affected cutover/soak. |
| Critical enrollment | Every distinct qualifying critical episode enrolls at P1 even with diagnosis budgets exhausted; repeats deduplicate by episode/generation. |
| Repair acceptance | Nonempty versioned mandatory checks all SUCCESS at the exact full SHA; identical assertion red/green, conservative unknown costs, absolute deadline; deployment alone cannot close. |
| Retirement | At least 48 continuous qualifying hours AND two natural cycles AND all stronger active rules. Missing coverage, interruptions, ambiguous effects or changed identity hold/reset observation. |
| Sustained maturity | One actual full trading week with explicit measured denominators; elapsed time is never simulated or compressed. |

Lane-specific freshness, queue age, timeout and natural-slot thresholds come from
reviewed health contracts. An absent or contradictory threshold is a blocker, not
a zero or an implicit exemption. Provisional operational maturity remains 2.5/5.

## Checkpoints

| Checkpoint | Current outcome | Next action / uncertainty |
|---|---|---|
| C0 | IN PROGRESS: source/policy/PR/pin/service baseline captured; regression findings reproduced. | Finish sanitized host/output, threat and contract matrices; validate existing Hermes evidence stage by stage. |
| C1 | IN PROGRESS: output, grant and retirement contract implementations assigned. | Integrate producer/consumer tests and host evidence reports; unavailable cannot be healthy. |
| C2 | NOT COMPLETE | Same named behavioral tests must fail on baseline and pass on exact candidate; independent review and exact-head CI required. |
| C3 | HELD | Safe automatic trigger/error/incident/outbox/business recovery drill after eligible release and authority. |
| C4 | HELD | Fixer disarmed; acceptance gaps and unattended policy bar unresolved. A manual repair cannot prove unattended operation. |
| C5 | HELD | No transactional cohort approved yet; exact evidence/grant/controller identities required. |
| C6 | NOT STARTED | Install reviewed collector under scoped authority; publish actual coverage/next evaluation; retain all legacy comments. |

All retirement output is eligibility only. `deletion_execution_enabled` remains
false and no legacy entries, scripts, workflow definitions or rollback records are
deleted by this campaign.

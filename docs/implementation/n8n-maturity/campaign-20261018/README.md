# n8n operational maturity campaign — 2026-10-18

Status: IN PROGRESS; production mutations held pending the recorded gates  
Owner: Codex integrator; Agent A remains Chief Architect  
as_of: 2026-10-18T17:11:26Z  
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
Authenticated-session and real MFA acceptance remain UNPROVEN.

## Work ownership

| Workstream | Owner | Write scope |
|---|---|---|
| Integration, generated files, documentation, CI registration | root Codex | this campaign directory; further files explicitly leased before editing |
| Shared output verdict and executor enforcement | contracts_routes agent | isolated output worktree; shared output validator, executor and focused test |
| Authentic grant and packet mutation admission | independent_review agent (now implementation author) | isolated follow-up to #1851; fabric grant and three existing packet scripts/tests |
| Eligibility-only retirement collector | retirement_collector agent | existing nightly cutover owner/controller and focused test |
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

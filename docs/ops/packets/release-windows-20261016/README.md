# Release windows, 12:00 and 17:30 America/New_York

```
Status:      PROPOSED (disarmed; nothing here is executed by merging it)
as_of:       2026-10-16T17:14:00Z
Measured at: branch release/window-runner-20261016 on origin/main 5f0ea5b8c; served CURRENT = b120849ed
```

Owner: platform. Operator decision, verbatim: "Adopt daily release windows at 12:00 and 17:30 America/New_York, with valid
authorization covering preparation, promotion, verification and rollback. Preserve the existing emergency
process for urgent fixes."

Code: `scripts/release_window.py`. Tests: `tests/test_release_window_20261016.py`, registered as the
`release_windows_20261016` stage of `scripts/run_cio_hardening_ci.py`. Registry row: `release-window` in
`config/lane_registry.json` (kind `none`, `NEVER_SCHEDULED`, so it is disarmed).

---

## 1. Where the 2026-10-16 refusal happened

The refusal came from the `prepare` phase, at `scripts/cio_phase2_exact_main_deploy.sh:76`. The message says
"refuse hybrid promote", but the check that produced it belongs to `prepare`.

| Time (UTC)       | Event | Evidence |
|---|---|---|
| 02:21:46 | Overnight run starts. CURRENT is `11b469ffe`. | `overnight_20261016/run.log` line 1 |
| ~02:23 | Step 2: #1808 merged, #1809 not mergeable (conflict), then #1810–#1813 merged. Main is `a7fc2175b` (#1813, committed 22:22:57 ET). | run.log, step 2 |
| ~02:24 | Step 4 picks `M=a7fc2175b` and polls main CI for that SHA (up to 90 × 60 s). | `operator_overnight_20261016.sh` step 4 |
| 02:55:53 | #1809 is merged after its rebase. Main moves to `94ee3770a` while the script is still waiting on CI for `a7fc2175b`. | `git log a7fc2175b..94ee3770a` |
| ~03:11 | CI on `a7fc2175b` finishes green (7 of 7 workflows). The script runs `git checkout --detach a7fc2175b` in `~/tradeai-exact-main-20260827`, then `prepare`. | run.log, step 4 |
| ~03:11 | `cmd_prepare` (line 652) → `require_head_is_origin_main` (line 62) fetches `origin main`. HEAD `a7fc2175b` ≠ origin/main `94ee3770a`, so `die` at **line 76**: `ERROR: ROOT HEAD a7fc2175b… != origin/main 94ee3770a… — refuse hybrid promote.` | run.log, step 4 |
| ~03:11 | Promote never ran, because the steps were chained with `&&`. CURRENT stayed `11b469ffe` and health stayed 200. | run.log |

This confirms how the deploy script works, as the operator described it:
- **`prepare` requires the latest main.** `require_head_is_origin_main` (lines 62–81) compares the checkout HEAD
  with a freshly fetched `origin/main`.
- **`promote` checks only the exact prepared candidate.** It does not compare against main.
  `cmd_promote` reads `<dir>/BUILD_SHA` (line 731), runs the release grant preflight for that SHA (line 735),
  then re-reads exact-SHA push/main CI (line 740).

**Root cause:** the run waited ~45 minutes on CI between choosing the SHA and preparing it. Any merge in that
interval guarantees a refusal.

**What the window runner changes:** it never waits on CI. It chooses the main head only if CI is *already*
green on that exact SHA, and it calls `prepare` within seconds. A merge after that point waits for the next
window. If main moves in those few seconds, the outcome is `STOP_MAIN_MOVED`; this case is replayed by
`test_replay_20261016_main_moved_between_selection_and_prepare`.

## 2. What one window does

```
open window (12:00–12:45 or 17:30–18:15 ET; off-window = REFUSED_OFF_WINDOW)
  ├─ refuse if a STOP latch exists, a bypass variable is set, or another run holds the lock
  ├─ M = origin/main head (git ls-remote); base = CURRENT/BUILD_SHA; M == base → NO_CHANGE
  ├─ PR list base...M (gh compare); grant verdict; exact-SHA push/main CI evidence
  │     no window grant        → DISARMED (exit 2, nothing written but last.json)
  │     CI in flight / missing → STOP_CI_PENDING   (exit 3, grant revoked)
  │     CI failed / unknown    → STOP_CI_NOT_GREEN (exit 3, grant revoked)
  ├─ receipt: candidate SHA, PR list, CI evidence, grant id
  ├─ release checkout: fetch + checkout --detach M; deploy `prepare`
  │     HEAD != origin/main    → STOP_MAIN_MOVED (exit 3); other failure → STOP_PREPARE_FAILED
  │     prepared BUILD_SHA must equal M
  ├─ deploy `promote <prepared dir>`   (promote re-checks exact-SHA CI for that BUILD_SHA)
  ├─ verify: promote exit 0 · CURRENT → prepared dir · BUILD_SHA == M · units that were active stay active ·
  │          /api/health 200 · scripts/check_served_copy_split.py exit 0
  │     all pass → RELEASED (exit 0), window grant revoked
  └─ any fail → deploy `rollback <previous release>` → health 200 → ROLLED_BACK (exit 4)
                (rollback fails → ROLLBACK_FAILED, exit 5)
                both write STOP.json: later windows refuse until the operator runs clear-stop
```

- **Receipts:** `$TRADEAI_STATE_ROOT/data/runtime/release_window/windows/<YYYYMMDD-HHMM>.json` and `last.json`.
  They follow the `ReleaseWindowReceipt@v1` schema.
- **One run per window:** a terminal receipt makes a second run in the same window `ALREADY_RAN`.
- **The deploy's environment is cleaned before every call.** Each `GUARDED_ENV` name is removed.
  The runner refuses to start at all if one is set to a weakening value: `TRADEAI_EMERGENCY_RELEASE_SHA`,
  `TRADEAI_RELEASE_GRANT_BINDING=warn`, `TRADEAI_CONFORMANCE_GATE_OVERRIDE`, `TRADEAI_RELEASE_PIN_MODE≠apply`,
  `TRADEAI_RELEASE_VENV_MODE≠link`, `TRADEAI_TREE_ATTESTED_PROMOTE=1`, `CIO_DEPLOY_FF_DEV_TREE=0`,
  `TRADEAI_GUARD_CONSUME=0`.
- **The runner itself writes nothing to the guard ledger.** Its only ledger action is `guard revoke release-write`,
  which tightens authority. It revokes only when the ledger's release-write `grant_id` is still the window's
  grant.

## 3. Authorization: the existing guard grant, one per window

The runner adds no new mechanism.
- **The deploy's authority check is unchanged.** `release_grant_preflight.py` →
  `ReleaseGrantBinding@v1` matches the grant by **campaign id**. The runner exports
  `TRADEAI_RELEASE_CAMPAIGN=release-window-<YYYYMMDD>-<HHMM>`, and `TRADEAI_RELEASE_PR` set to the newest PR in
  the window's range.
- **The runner also checks the grant before it prepares.** It requires all of the following:
  - the `RELEASE_WINDOW` token and the window's campaign id;
  - the three stop conditions;
  - at least 2 uses (prepare and promote each consume one);
  - at least 15 minutes left before expiry;
  - and the same grant authorizing prepare, promote and rollback.

**Token format (grant reason):**

```
RELEASE_WINDOW release-window-<YYYYMMDD>-<HHMM> actions=prepare,promote,verify,rollback stop=verify_failed,rolled_back,ci_not_green <free text scope>
```

**Arming command (operator, at the keyboard; the agent never types APPROVE).** Example for today's 17:30
window:

```bash
GUARD=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/bin/guard
"$GUARD" grant release-write --for 90m --uses 3 --reason "RELEASE_WINDOW release-window-20261016-1730 actions=prepare,promote,verify,rollback stop=verify_failed,rolled_back,ci_not_green scope: scripts/release_window.py releases the origin/main head only if exact-SHA push/main CI is green; no emergency/warn/bypass"
"$GUARD" show      # strip ANSI before grepping: sed 's/\x1b\[[0-9;]*m//g'
```

**The four controls:**
- **Scope:** one window. That means one candidate SHA, chosen at the window, with prepare, promote,
  verification and rollback.
- **Expiry:** `--for` must cover the window and its 45-minute grace. Issue it shortly before the window.
- **Revocation:** the runner revokes the grant when the window ends (released, nothing new, or stopped).
  The operator can revoke at any time with `guard revoke release-write`.
- **Stop conditions:**
  - CI not green: the grant is revoked and no release happens.
  - Failed verification: the runner rolls back, latches STOP and revokes the grant.
  - A rollback: the runner latches STOP and revokes the grant.

**Caveat: the ledger holds one row per tier.** A window grant **replaces** any other active `release-write`
grant, and the runner's revoke ends that row. Do not arm a window while another release grant is in use.

**Current policy:** one grant per window is one grant per release, so it already complies with AGENTS §24.8.
A grant naming both of a day's windows, or a standing multi-day grant, does **not** comply. The runner refuses
such a grant (`MULTI_WINDOW_GRANT_STATUS = "PROPOSED"`) until amendment A below is ratified.

**Dry run (read-only, writes nothing):**
`.venv/bin/python scripts/release_window.py plan --window 1730`. Output on 2026-10-16 at 13:14 ET:
- outcome `DISARMED`: the active grant, "Operator 2026-10-16: merge + release PR #1775 …", names no window;
- candidate `5f0ea5b8c` (#1814), base `b120849ed`;
- CI `STOP_CI_PENDING`: `cio-production-hardening-ci` was in progress and the other six workflows were green.

**Status and clear:**
- `scripts/release_window.py status` shows the latch and the last receipt.
- `scripts/release_window.py clear-stop --reason "<review note>"` is for the operator. It archives the latch,
  renamed and never deleted.

## 4. Scheduling

**What ships:** a registered host lane, `release-window` (`NEVER_SCHEDULED`). No cron line, no unit and no
allowlist entry are created by this PR. The lane is **disarmed twice over**:
1. nothing schedules it;
2. without a window grant it exits `DISARMED` before it touches anything.

**Why n8n cannot trigger it today:** two blockers.
1. **AGENTS §23.3** forbids `release-deploy` commands in `config/n8n_run_allowlist.json`. The test
   `tests/test_n8n_run_allowlist_20261008.py` enforces this: its `NEVER` list includes `deploy`, `promote` and
   `cio_phase2_exact_main_deploy`, and the gateway's `FORBIDDEN_ROUTE_TOKENS` include `promote`, `rollback`
   and `grant`. The command `scripts/release_window.py run` contains none of those tokens. Admitting it without
   an amendment would therefore be a silent widening, so this PR does not add it.
2. **A run cannot be a child of the executor.** `promote` restarts `tradeai-n8n-run-executor`,
   `tradeai-n8n-coordination-gateway` and `tradeai-n8n-run-relay` (`restart_root_frozen_units`, line 857).
   A run launched by the executor would be killed in the middle of its own promote.

**Options, both operator acts:**
- **Host timer (operator installs; scheduler mutation is operator-only).** The proposed text is below. It is
  *not* installed:
  ```ini
  # ~/.config/systemd/user/tradeai-release-window.timer
  [Timer]
  OnCalendar=*-*-* 12:00:00 America/New_York
  OnCalendar=*-*-* 17:30:00 America/New_York
  Persistent=false
  # ~/.config/systemd/user/tradeai-release-window.service
  [Service]
  Type=oneshot
  WorkingDirectory=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
  ExecStart=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python scripts/release_window.py run
  TimeoutStartSec=5400
  ```
- **n8n trigger, after amendment B.** n8n posts a run request for a `release-window` *request* lane. The host
  starts the oneshot unit above, outside the executor's cgroup, so the promote restarts cannot kill the run.

## 5. Unchanged processes

- **Urgent fixes outside a window:** the existing process.
  1. The operator grants `release-write` naming the PR or SHA (§24.8).
  2. Run `TRADEAI_RELEASE_PR=<n> bash scripts/cio_phase2_exact_main_deploy.sh prepare`, then `promote`, from
     `~/tradeai-exact-main-20260827`, checked out at origin/main.
  3. Roll back with `cio_phase2_exact_main_deploy.sh rollback <prev>`.
- **CI-provider outage emergency (2026-10-05):** `TRADEAI_EMERGENCY_RELEASE_SHA=<sha>` together with
  `scripts/ci_outage_emergency_release.py check|request-grant|reconcile`. It needs all of:
  - a live Actions incident;
  - local replay evidence bound to the commit's tree;
  - a separate `release-emergency` grant naming the SHA and the incident;
  - reconciliation after GitHub recovers.
- **The window runner never uses either path.** It refuses to start when `TRADEAI_EMERGENCY_RELEASE_SHA` is
  set. Neither path's code is touched by this PR.

## 6. Policy amendments needed (proposed text; operator ratification per §20)

**A. §24.8 window clause.** Needed only if one grant should cover more than one window. Add after the §24.8
bullet:

> - **Release-window exception (PROPOSED).** A `release-write` grant may name release windows instead of a SHA
>   or PR. Its reason carries `RELEASE_WINDOW release-window-<YYYYMMDD>-<HHMM>` once per window, plus
>   `actions=prepare,promote,verify,rollback` and `stop=verify_failed,rolled_back,ci_not_green`. It authorizes
>   only `scripts/release_window.py`, which:
>   - releases the origin/main head at that window only when exact-SHA push/main CI is green;
>   - uses no emergency, warn or bypass setting;
>   - revokes the grant on any stop condition.
>
>   At most the windows of one New York calendar day may be named, at most 4 uses per window.
>   `scripts/release_window.py` `MULTI_WINDOW_GRANT_STATUS` reads `ACTIVE`.

**B. §23.3 release-window trigger.** Needed only for an n8n trigger. Add as an exception bullet:

> - **Exception (PROPOSED) — release-window request only.** The allowlist may contain one lane,
>   `release-window-request`, whose command writes a window request and nothing else. It does not prepare,
>   promote or roll back, and it starts no deploy. The host's oneshot `tradeai-release-window.service` performs
>   the release outside the executor's cgroup, under the per-window `release-write` grant. A release still
>   needs that grant: n8n holds no release authority, and an unarmed window exits `DISARMED`.

Neither amendment is needed for the compliant form, where the operator arms each window with its own grant
and runs the runner or a host timer.

## 7. Known limits

- **A merge in the ~45 minutes before a window usually means no release.** CI on the new head is still running
  (`STOP_CI_PENDING`), and the runner does not wait or fall back to an older SHA. That matches the operator's
  rule, and the merge ships at the next window.
- **The gap between choosing the SHA and `prepare` is only seconds.** A merge inside it gives
  `STOP_MAIN_MOVED`. The deploy script's latest-main rule is deliberately left unchanged.

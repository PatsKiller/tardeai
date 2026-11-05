# Release train: merge when green, release main in the 12:00 and 17:30 windows

```
Status:      DRAFT (code in this branch; nothing scheduled, granted, released or changed on GitHub)
Phase 3:     §11 train controller (BUILD_ONLY), branch feat/release-train-controller-20261021
as_of:       2026-10-21T19:56:00Z
Measured at: origin/main 7faa8cddf (#1906); served CURRENT 7faa8cddf (7faa8cddf-main-exact-phase2-20261021-154546)
```

Owner: platform. The operator approved the process plan on 2026-10-21. Goal: merge green PRs to main as they are
ready, release main's newest green commit in the scheduled windows (operator 2026-10-16: 12:00 and 17:30
America/New_York), and keep an expedited path for urgent fixes. The cost it removes: on 2026-10-21 each PR waited
for PR CI and then main CI, and was released on its own. That made seven releases, hours of waiting and exhausted
grants.

Builds on `docs/ops/packets/release-windows-20261016/README.md`. That packet's §2 window flow and §5
unchanged-process notes still hold. This packet changes the runner's selection, verification and alerting, plus
two deploy-path defects.

---

## 1. Findings

### 1.1 Why `release_window.py` was not used on 2026-10-21 `[VERIFIED]`

1. **It has never run, because nothing schedules it.**
   - `crontab -l | grep -c release_window` returns `0`.
   - `systemctl --user list-timers --all | grep -ci release` returns `0`.
   - `config/n8n_run_allowlist.json` has 0 matches.
   - `config/lane_registry.json` row `release-window` is `scheduler.kind = none`, state `NEVER_SCHEDULED`.
   - The state directory `~/trade-ai-releases/persistent-state/data/runtime/release_window` does not exist, so
     no receipt was ever written.
2. **Even run by hand, it would have exited `DISARMED`.**
   - It requires a `release-write` grant whose reason carries `RELEASE_WINDOW release-window-<date>-<HHMM>` and
     the three stop names.
   - Every grant on 2026-10-21 named a PR or SHA (§24.8 "one grant per release"). Those grants authorize the
     manual `prepare`/`promote` path and never a window.
   - A grant covering both of a day's windows is refused while `MULTI_WINDOW_GRANT_STATUS = "PROPOSED"`.
3. **Armed, it would still have released less than the operator expected.**
   - It released only the exact head and never fell back. A merge in the ~30 minutes before a window
     (push/main `cio-hardening` takes 29–32 min, see §6) meant `STOP_CI_PENDING`, so nothing shipped.
   - It counted only 2 of the 3 required contexts. `release_grant_preflight.REQUIRED_PUSH_WORKFLOWS` names
     `cio-production-hardening-ci.yml` and `agent-governance.yml`. Branch protection on main
     (`gh api repos/PatsKiller/tardeai/branches/main/protection`) also requires `release-readiness`.
   - An evidence `ok: true` with `release-readiness` missing or still running therefore read as green. This is the
     same weak-verdict class the 2026-10-21 watcher had to be fixed for. The fix is
     `tests/test_release_train_20261021.py::test_evidence_ok_without_release_readiness_is_not_green`.

### 1.2 Approving a new release-write grant REPLACES the active one `[VERIFIED]` (not fixed here; proposal §4)

The cause is in `.cursor/hooks/guard_ledger.py`:
- `ledger_create_grant` writes `doc[tier] = {...}`. The ledger is one object keyed by tier, so it holds one row per
  tier.
- A second `release-write` approval silently overwrites the first one's uses, expiry and reason.
- `ledger_consume_grant(tier)` and `guard revoke release-write` also act on the tier, not on a `grant_id`.

The consequences:
- An expedited per-PR grant approved during the day disarms a window grant, and the reverse.
- The window runner's revoke is careful: it revokes only when the ledger's `grant_id` is still the window's.
  Even so, the ledger cannot hold both grants at once.
- The 2026-10-16 packet records this as a caveat ("Do not arm a window while another release grant is in use").
  Today that caveat cost grants.

### 1.3 A promote refused by exact-SHA CI consumed a release-write use `[VERIFIED]` (fixed here)

The cause is in `scripts/cio_phase2_exact_main_deploy.sh` `cmd_promote`. It ran `release_grant_preflight promote`
**first**. That call decides and then calls `consume_release_grant()`. Only after that did it run
`conformance_gate` and the exact-SHA CI re-query (`release_grant_preflight.py --ci-only`). A CI refusal then
`die`d with the use already spent.

The evidence is `~/.local/state/cio-phase2-exact-main/deploy_receipt.json`:
- `mode: promote`, `extra: post_merge_ci_refused`;
- `attempted_target.sha 71df62accb03…`;
- `post_merge_ci.errors: ["not_successful:.github/workflows/cio-production-hardening-ci.yml"]`;
- checked `2026-10-21T18:43:14Z`.

`prepare` has the same shape: it consumes at its start, so a failed build also costs a use. That is noted, and
not changed here (§4.3).

## 2. What this branch builds

| Change | File | Test |
|---|---|---|
| Head only if all **three** required checks are literally `success` on that exact SHA (`train_ci_verdict`; neutral, skipped, cancelled, null, unavailable and a red optional workflow are all not green; in-flight or missing is `STOP_CI_PENDING`) | `scripts/release_window.py` | `test_evidence_ok_without_release_readiness_is_not_green`, `test_anything_but_literal_success…` (9 cases) |
| Otherwise the **newest green first-parent main commit since the served release** (`selected_by: fallback_newest_green`, at most 15 SHAs queried, read from the GitHub commits API; no fetch, no ref moved) | `scripts/release_window.py` `Host.first_parent_chain` | `test_pending_head_falls_back…`, `test_nothing_green…`, `test_no_fallback_when…` |
| The deploy prepares a fallback SHA under `TRADEAI_RELEASE_TRAIN_SHA`. It is accepted only if HEAD is that SHA, the tree is clean, it is on a freshly fetched origin/main's first-parent chain (500 deep), and its exact-SHA CI is green now. It is refused together with the emergency SHA. The window runner refuses to start if the variable is set in its own environment (`GUARDED_ENV`). | `scripts/cio_phase2_exact_main_deploy.sh` | `test_prepare_accepts_a_train_sha_only_on_the_first_parent_chain` (tmp git repo: c2 ok, side-branch commit refused, head ok), `test_prepare_refuses_a_train_sha_whose_ci_is_not_green`, `test_prepare_refuses_train_and_emergency_together`, `test_a_train_sha_set_from_outside_is_a_bypass` |
| **Grant-use fix.** `cmd_promote` runs `release_grant_preflight promote --no-consume` (binding verdict only), then conformance, then the CI re-query, then `release_grant_preflight promote` (re-decide + consume) immediately before `activate_release` | `scripts/cio_phase2_exact_main_deploy.sh`, `scripts/release_grant_preflight.py` (`--no-consume`) | `test_promote_refused_by_ci_consumes_no_grant_use`, `test_promote_consumes_only_after_ci_passes_and_before_activation` (order `no-consume → ci → consume`), `test_preflight_no_consume_never_touches_the_ledger` |
| Verification adds Command Center pages (`/v3/ /v3/system /v3/cio`) 200, `/api/v2/system/platform-health` 200 and not `UNAVAILABLE`, and `/api/v2/needs-action` 200 and parseable. Each is fetched through `scripts/cc_curl.sh`, so the runner never handles the token. Any failure rolls back. | `scripts/release_window.py` `_verify_surfaces` | `test_each_new_verification_fails_the_window_and_rolls_back` (5 cases) |
| A failed window leaves one receipt, a **Needs-action item** and **one notification intent**. The item comes from the new `release_window` source, which reads `STOP.json` and `last.json`. The intent is sent through `telegram_alert.send_telegram(priority=…, dedupe_minutes=0, producer="release_window")`: P1 on rollback or prepare failure, P2 on CI red or main moved. A routine `STOP_CI_PENDING` pages nobody. | `scripts/release_window.py` `_alert`, `scripts/lib/needs_action.py` `rule_release_window`, `scripts/api_v2.py` probe | `test_rollback_sends_one_p1_intent…`, `test_ci_pending_window_does_not_page`, `test_ci_red_window_is_a_p2_intent`, `test_needs_action_rule_is_quiet…` |
| **Per-window campaign grant.** The binding accepts `RELEASE_WINDOW <date> <window>` (`20261021 1200` or `2026-10-21 12:00`) as well as `release-window-20261021-1200`. It binds only when the action runs under that campaign (`TRADEAI_RELEASE_CAMPAIGN`, exported only by the runner). | `scripts/lib/release_grant_binding.py` `window_campaigns` | `test_binding_accepts_a_release_window_campaign_grant` (3 spellings), `test_window_token_for_another_window_does_not_bind` |

All of these tests run in CI as stage `release_train_20261021` (ANCHOR `RELEASE_TRAIN_20261021`,
`scripts/run_cio_hardening_ci.py`).

**Red, then green** (`.venv/bin/python -m pytest tests/test_release_train_20261021.py`):
- before the code: `38 failed, 3 passed`;
- after: `tests/test_release_train_20261021.py tests/test_release_window_20261016.py
  tests/test_release_grant_binding_20260925.py tests/test_cc_needs_action_20261021.py` gave `110 passed`;
  with the deploy, release, n8n-allowlist, notification-intent and SOP-evidence suites added, `332 passed`.

The 2026-10-16 tests changed in only three ways:
- their `green()` fixture now carries `release-readiness`;
- their fake host answers `first_parent_chain`, `http_get` and `notify`.

## 3. Dry run (read-only, quoted)

`.venv/bin/python scripts/release_window.py plan --window 1730` at 2026-10-21 15:51 ET returned exit 0 with
`outcome NO_CHANGE`. Main's head `7faa8cddf` is already served (`CURRENT` → `7faa8cddf-…-154546`). **Right now it
would release nothing.**

A counterfactual on real GitHub data ran the same `plan` code with the served release pretended to be `a6ac0ebbe`
(scratch script; read-only; no state written):

- **head `7faa8cddf`:**
  - `head_verdict GREEN`, `picked 7faa8cddf head_green`, PRs `[1900, 1904, 1905, 1906]`;
  - grant: `DISARMED`, "no release-write grant names this PR/SHA/campaign". No window grant is active.
- **head pretended `71df62acc` (today's CI-red head):**
  - `tried [('71df62acc', 'STOP_CI_NOT_GREEN'), ('17b071470', 'GREEN')]`, so it picked
    `17b071470 fallback_newest_green`, PRs `[1900]`.

  The 18:43Z refused promote would instead have released #1900, the newest green commit, in the window.

## 4. Grant fixes

### 4.1 No use consumed on a refused activation: built (§2)

Per promote, the deploy now consumes exactly one use, and only when every gate passed. The window still needs 2
uses (prepare and promote). A refused promote leaves its use for the next window.

### 4.2 The ledger holds one grant per tier: proposed, not built

The guard ledger is the operator's control. Its schema and its CLI semantics belong in their own reviewed change.
Proposed patch to `.cursor/hooks/guard_ledger.py` and `bin/guard`:
- `ledger_create_grant` refuses when an active, unexpired row of the same tier exists, unless `--replace` is given.
  The refusal message prints the active row's reason and uses.
- Alternatively, store rows as `doc[tier] = [row, …]` keyed by `grant_id`. `load_grants` in
  `release_grant_binding.py` already reads a list per tier.
- `ledger_consume_grant(tier, grant_id=None)` decrements the row the binding matched.
  `release_grant_preflight.consume_release_grant` passes `v.grant_id`, and refuses to consume a different row.
- `guard revoke release-write --grant-id <id>` lets the window runner end only its own grant.

With this patch in place, an expedited per-PR grant and the day's train grant can coexist.

### 4.3 `prepare` consumes at its start: proposed

`cmd_prepare` can follow the same pattern: decide with `--no-consume` at the start, then consume after
`PREPARE OK`. This is not done here, because the operator asked for the promote case. The pattern and its test
are ready to copy.

### 4.4 A standing per-day "campaign" grant: needs a §24.8 amendment (proposed text)

What works today, inside §24.8: **one grant per window**, approved once per window. Either spelling binds:

```bash
GUARD=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/bin/guard
"$GUARD" grant release-write --for 75m --uses 3 --reason "RELEASE_WINDOW 2026-10-22 12:00 actions=prepare,promote,verify,rollback stop=verify_failed,rolled_back,ci_not_green scope: scripts/release_window.py releases main's newest exact-SHA-green first-parent commit"
```

Approving the train **once per day** needs `MULTI_WINDOW_GRANT_STATUS = "ACTIVE"`, which an operator-ratified
amendment must set. Proposed text: an `AGENTS.md` patch, **not applied**, under §20, to be added after the §24.8
bullet:

> - **Release-window campaign (PROPOSED).** A `release-write` grant may name release windows instead of a SHA or
>   PR. Its reason names each window once, as `RELEASE_WINDOW <YYYY-MM-DD> <HH:MM>` or
>   `release-window-<YYYYMMDD>-<HHMM>`. It also carries `actions=prepare,promote,verify,rollback` and
>   `stop=verify_failed,rolled_back,ci_not_green`. It binds only to `scripts/release_window.py`, the only caller
>   that exports the window campaign. That runner:
>   - releases main's head, or the newest first-parent main commit whose three required checks are `success` on
>     that exact SHA;
>   - uses no emergency, warn or bypass variable;
>   - verifies and rolls back;
>   - revokes the grant on any stop condition and after the last window it names.
>
>   A grant may name at most the windows of one New York calendar day, with at most 3 uses per window and an
>   expiry no later than the last window's close. `MULTI_WINDOW_GRANT_STATUS` in `scripts/release_window.py` reads
>   `ACTIVE`. Expedited releases keep the per-SHA/PR grant. Until §4.2 lands, approving one replaces the day grant,
>   so re-arm the train afterwards.

The day grant is then (example):
`--for 6h30m --uses 6 --reason "RELEASE_WINDOW 2026-10-22 12:00 RELEASE_WINDOW 2026-10-22 17:30 actions=… stop=…"`,
issued at about 11:50 ET. Classification: it widens what one grant authorizes, so it is MAJOR by the version policy
unless the operator rules otherwise.

## 5. Scheduling (proposed; operator installs; not installed)

> **SUPERSEDED 2026-10-21 (release-train arming finding 7).** Do not install this 12:00/17:30 timer. Release Train v2
> runs in the 18:00, 00:00, 06:00 and 08:00 windows through the claimer units, which step D of
> `docs/ops/packets/release-train-arming-20261021/README.md` installs. Both together would be two release paths.
> `install_release_window_timer.sh --apply` now refuses (`SUPERSEDED`), and step D refuses to install the claimer
> while a `tradeai-release-window.timer` is present (`--disable` archives it). The text below is kept as history.

**Use a host systemd timer, not n8n.**
- §23.3, the allowlist `never` entries and `tests/test_n8n_run_allowlist_20261008.py` forbid release-deploy
  commands (`deploy`, `promote`, `cio_phase2_exact_main_deploy`) on the dispatcher.
- §17 makes any new production systemd entry an operator decision.
- `promote` restarts the n8n executor, gateway and relay, so an executor child would kill itself mid-promote.

`install_release_window_timer.sh` (this directory) defaults to a **dry run**. It prints the two units, the commands
`--apply` would run, a read-only preflight and a `plan`. `--apply` and `--disable` require
`TRADEAI_OPERATOR_INSTALL=1`; `--disable` archives the units and never deletes them.

The units:
- `OnCalendar` is set to 12:00:00 and 17:30:00 `America/New_York`, with `Persistent=false`.
- `ExecStart` is `<canonical>/.venv/bin/python <release checkout>/scripts/release_window.py run`. The release
  checkout is `${TRADEAI_RELEASE_CHECKOUT:-~/trade-ai-releases/train-checkout}` (2026-10-22). Before that it was
  `~/tradeai-exact-main-20260827`, a dated path that no longer exists.
  The runner is read from the release checkout (reviewed main code with a git remote), never the dev tree.
- `SuccessExitStatus=2 3`: disarmed and stopped windows are receipts. Exit codes 4 and 5 (rolled back, rollback
  failed) leave a failed `tradeai-*` unit, which Needs-action also shows.

Dry-run output on 2026-10-21 15:55 ET:

```
PREFLIGHT: /home/johnclaw/tradeai-exact-main-20260827/scripts/release_window.py predates the release train (merge + release the release-train PR first)
PREFLIGHT: the release checkout's deploy script predates the release train
"outcome": "NO_CHANGE"   (candidate 7faa8cddf == served 7faa8cddf)
```

`~/.config/systemd/user` has 0 `release-window` units, both before and after the dry run.

## 6. GitHub: merge-when-green, merge queue and CI split

**The merge queue is probably unavailable on this repository.**
- `gh api repos/PatsKiller/tardeai` returns `owner_type: User`, `visibility: public`, `allow_auto_merge: true`.
- GitHub documents merge queues for organization-owned repositories `[DOC-CLAIM]`. This was not verified by
  running the command, because the operator runs it.

The command to enable it on main with the three required checks (operator; requires `merge_group` triggers first,
see below):

```bash
gh api -X POST repos/PatsKiller/tardeai/rulesets --input docs/ops/packets/release-train-20261021/merge-queue-ruleset.json
```

**What works today, for merge-when-green: GitHub auto-merge, which is already enabled on the repo.**
- Command: `gh pr merge <N> --auto --merge`.
- Required checks are `strict: false`, so a PR merges as soon as `cio-hardening`, `agent-governance` and
  `release-readiness` are green on its head. No rebase is required.

This is a remote write, so it falls under `AI_WORK_POLICY.md`: the operator or an authorized session runs it, and
the §23.13 standing merge approval applies where it exists.

**`merge_group` triggers are proposed, not applied.** See `ci-merge-group.proposed.diff`.
- The diff adds `merge_group:` to the three required workflows. Without it a queue stalls, because the required
  contexts never report.
- It was applied and then reverted in this branch: `agent-governance.yml` is hash-pinned by the SOP evidence
  (`tests/test_sop_evidence_integrity.py::test_in_repo_evidence_validator_on_repo` failed with
  `WORKFLOW_BLOB_HASH_MISMATCH`, `WORKFLOW_LINE_COUNT_MISMATCH`).
- It needs a governance-evidence refresh in its own PR. It is useful only once a queue exists.

**Fast PR checks vs the full suite on the train: proposed, not applied.** See `ci-train-profile.proposed.diff`.

Measured on 2026-10-21 (`gh run list`, runs created that day):

| Workflow / event | n | avg | max |
|---|---|---|---|
| `cio-production-hardening-ci` push | 4 | 29 min | 32 min |
| `cio-production-hardening-ci` pull_request (already the affected-tests PR profile) | 10 | 9 min | 16 min |
| `cio-full-suite-sharded` pull_request (EVERY registered test, 8 shards + serial + pg) | 10 | 6 min | 7 min |

So the 30-minute wait on main comes from the single-job FAST profile, while the same suite already runs sharded in
about 7 minutes. The proposal:
- run the sharded suite on push/main and `merge_group` instead of every PR;
- leave PRs with the affected-only `cio-hardening`;
- reduce `cio-hardening` on push to its rails;
- make release evidence (`REQUIRED_PUSH_WORKFLOWS`, `REQUIRED_TRAIN_WORKFLOWS`) require the sharded workflow.

This is not implemented, because it changes the required context (`cio-hardening` → `ci-gate`) and the release
evidence, and both are operator decisions (§17). Expected main CI: about 7 min instead of 30.

## 7. The routine

1. **Merge when green.** Each PR gets `gh pr merge <N> --auto --merge` once it is reviewed, and merges when its
   three required checks pass. Nothing is released at merge.
2. **Release in the windows.**
   - The operator arms the day's windows (§4.4; one grant per window until the amendment).
   - At 12:00 and 17:30 ET the runner releases main's head if it is green on all three checks. Otherwise it
     releases the newest green first-parent commit since the served release.
   - It verifies (health, units, served copy, pages, platform-health, needs-action) and rolls back on failure.
   - It writes `release_window/windows/<YYYYMMDD-HHMM>.json`.
   - A failure adds a Needs-action item and one P1/P2 intent; a rollback latches STOP until
     `scripts/release_window.py clear-stop --reason …`.
3. **Expedited path, unchanged and explicit.**
   - The operator grants `release-write` naming the PR and SHA (§24.8).
   - Then run `TRADEAI_RELEASE_PR=<n> bash scripts/cio_phase2_exact_main_deploy.sh prepare` and `promote <dir>` from
     the release checkout at origin/main.
   - A promote refused by CI no longer costs the use.
   - Until §4.2 lands, the expedited grant replaces the train grant, so re-arm the next window.
4. **CI-outage emergency** stays as it is: `TRADEAI_EMERGENCY_RELEASE_SHA` plus a `release-emergency` grant. The
   runner refuses to start while that variable is set, and the deploy refuses it together with a train SHA.

## 8. Operator steps, in order

1. Review and merge this PR (it changes the deploy script, so it is per-PR, not §23.13 standing).
2. Release it once by the expedited path, so the release checkout carries the train code. The installer preflight
   checks this.
3. **SUPERSEDED** (arming finding 7): do not install the 12:00/17:30 timer. Install the train claimer by
   `docs/ops/packets/release-train-arming-20261021/README.md` step D instead. (`install_release_window_timer.sh
   --apply` refuses.)
4. Arm windows per §4.4. Optionally ratify the §4.4 amendment and the §4.2 ledger change.
5. Use `gh pr merge --auto --merge` for green PRs. Optionally apply the CI split (§6), then switch the required
   context.

## 9. Phase 0 rules (Release Train v2, approved 2026-10-21)

### 9.1 The STOP latch fails closed

- If `release_window/STOP.json` is **missing**, there is no STOP.
- If it is **present but unreadable**, that is a STOP. Unreadable covers:
  - corrupt JSON;
  - a non-object value;
  - permission denied;
  - a directory in its place.

`State.read_latch()` returns `ABSENT`, `SET` or `UNREADABLE`.
- `run` and `plan` refuse with `REFUSED_STOP_UNREADABLE`, exit 2. Nothing is prepared, promoted or sent.
- `status` reports `latch_state: UNREADABLE` with the read error.
- Needs-action shows a P1 item, "Release windows halted: STOP latch unreadable".
- `clear-stop` archives whatever is at the path, by rename; it never deletes.

Before this change, `State.read` returned `None` for a damaged latch, so it read as "no STOP".

Tests: `test_unreadable_stop_latch_refuses_every_mutating_path` (corrupt, non_object, unreadable mode 000,
directory), `test_missing_latch_is_no_stop_and_readable_latch_is_stop`,
`test_clear_stop_archives_an_unreadable_latch`. Against `58bf60cf3`: 6 failed. After this change: 54 passed.

### 9.2 `TRADEAI_RELEASE_TRAIN_SHA` identifies a commit; it never authorizes one

The variable only says which already-qualified commit `prepare` stamps. Setting it never skips the release-write
grant binding, the exact-SHA CI check or the conformance gate. It never widens the set of commits that can be
released.

**Audit (`58bf60cf3`).**

`scripts/cio_phase2_exact_main_deploy.sh` reads the variable in exactly two functions:
- `git_sha` uses it to choose the SHA.
- `require_head_is_origin_main` only **adds** refusals. It refuses unless all of these hold:
  - the value is 40 hex characters;
  - HEAD is that SHA;
  - the tree is clean;
  - the SHA is on a freshly fetched origin/main's first-parent chain;
  - its exact-SHA CI is green;
  - the emergency SHA is not also set.

`cmd_prepare` then still runs the release-write binding on that SHA.

`cmd_promote` never reads the variable. Its sequence is the same with or without it:
1. it reads `BUILD_SHA`;
2. it runs the binding with `--no-consume`;
3. it runs conformance;
4. it re-queries exact-SHA CI;
5. it runs the consuming binding.

`scripts/release_window.py` handles it in two places only:
- `GUARDED_ENV` refuses to start when the variable is set from outside.
- `deploy_env` sets it only for a fallback candidate the runner already qualified, with all three required checks
  `success` on that exact SHA.

**Tests.** Each runs the real `release_grant_preflight.py` binding against a tmp grant ledger and a tmp git repo:

| Test | What it proves |
|---|---|
| `test_train_sha_with_no_grant_is_refused_at_prepare` | A qualified, green, first-parent commit with **no grant** is refused. |
| `test_train_sha_with_a_grant_for_another_release_is_refused` | A grant naming another PR or SHA does not cover the train SHA. |
| `test_train_sha_with_a_valid_grant_still_needs_green_ci_and_first_parent` | **CI red** is refused, and so is a **side-branch commit** not on main's first-parent chain. Both are refused before the binding is consulted. |
| `test_train_sha_in_the_environment_does_not_relax_promote` | promote with the variable set is refused for no grant, and for CI red. |
| `test_train_sha_is_read_only_by_git_sha_and_require_head` | Static audit: no other deploy function reads the variable, and `release_window.py` names it exactly twice. |

The audit found no gap, so no code change was needed for 9.2. All of these tests also pass against `58bf60cf3`.

## 10. Not done, deliberately

No push, release, grant, promote, crontab, systemd, n8n or GitHub-setting change (§11 adds only proposed unit files). No `AGENTS.md` or adapter edit;
the policy text is in §4.4 only. The `lane_registry.json` row stays `NEVER_SCHEDULED` until the timer is installed.

## 11. Release Train v2 Phase 3: the train controller (branch `feat/release-train-controller-20261021`)

```
Status:      BUILD_ONLY (TRAIN_CONTROLLER_STATUS; --live refused; GitHub writer refuses while GITHUB_WRITES_STATUS != ACTIVE)
as_of:       2026-10-21T23:30:00-04:00
Measured at: base origin/main 7faa8cddf + ops 9dde41745 + authority 8c5d5bc22 + Phase 1 queue 72d62fddc (origin/main
             has since moved to 8fd1500fc; not rebased)
```

`scripts/release_window.py` stays the one deployer and the one entry point. Its new `train-*` commands call
`scripts/lib/release_train_controller.py`. Every production effect goes through `release_window.Host`, and so
through `cio_phase2_exact_main_deploy.sh` `prepare` / `promote` / `rollback`. Every release is verified by
`release_window.Runner._verify`. The commands `plan`, `run`, `status` and `clear-stop` are unchanged. They remain the
operator's fallback, together with a grant and the deploy script.

### 11.1 Pipeline

| step | what happens | fails closed when |
|---|---|---|
| select | `QueueSource`. The source is the Phase 1 store (`release_train_queue.read_queue`), or the PR-hygiene receipt + `gh pr list` (read-only) when the store reads NOT_MIGRATED or is unreachable. Each PR is classified by the Phase 1 classifier (`release_train_classify.classify_change` + `config/release_train_policy.json`). Live runs classify from git `base...head`; a dry run uses the gh file list (approximate). | the snapshot is incomplete (no receipt, stale > 36 h, gh failure, possible truncation); the classifier cannot load (then `HoldAllClassifier`); a PR is not `eligible`; a PR touches `PROTECTED_SURFACES` |
| freeze | Builds a `TrainCandidate@v1` (validated): base main SHA, full head SHAs in dependency order, policy version, classifier version, the four-check manifest and the window id (`YYYY-MM-DDTHH:MM±HH:MM`). Written once to `trains/<id>/manifest.json`. | main or a head moved since select |
| integrate | Runs in a scratch worktree under `$TRADEAI_RELEASE_TRAIN_SCRATCH` (default `~/.cache/rtc`). Each PR is merged `git merge --no-ff` in order, then the generated files are regenerated once (`scripts/regenerate_generated_files.sh`, plus a GATES registry check). The candidate's own hooks never run: the trusted `core.hooksPath` of the release checkout is pinned, and the environment comes from an allowlist. | a conflict or a protected path ejects that PR and its dependents, with a reason; the final diff `base..candidate` touches a protected path |
| local test | Runs `run_cio_hardening_ci.py --profile pr --base <base>` with an environment built from an allowlist (PATH, LANG, LC_ALL, TZ, TERM, plus fixed CI flags). HOME and TMPDIR are scratch, and no `.env`, `DB_*`, token or key is passed. RLIMIT_CPU is set. On failure it bisects over prefixes, bounded by `test_attempts` (6) and `test_budget_s` (2700). | the culprit is attributed and ejected; the uncertain remainder is marked `pending_investigation` (a `ready` event; still queued, not ejected); a red base blames nobody |
| wait for window | Integration and local test may start `lead_min` (90) before the window opens. Every GitHub write happens inside the window. | the window closes (no catch-up) |
| qualify | A build/publish capability is issued per action. It can only push `refs/heads/train/<id>` and open/update the batch PR. Qualification waits until cio-hardening, agent-governance, release-readiness and ci-gate all read exactly `success` on the candidate SHA: the latest run, from app `github-actions`. There is no tree-equivalence fallback. | a check is red, neutral, skipped or cancelled (RED); a check is missing or still running at the timeout (PENDING); forged-app or wrong-SHA runs are ignored |
| merge | Re-reads the checks, then issues a merge capability bound to: expected base, ordered PR heads, candidate, manifest digest, evidence digest and rollback target. STOP, control epoch, delegation epoch and digest, `main == base` and the PR heads are re-checked immediately before the merge. The merge goes through `merge_method=merge` with `sha=<candidate>`. | main or a head moved; STOP/revoke/epoch; the resulting commit's parents are not `[base, candidate]` (STOP latched, `MERGED_NOT_LIVE`) |
| promote | Waits for the exact-SHA push/main checks on the merge commit, then runs `prepare` under a prepare capability. A promote capability then binds the prepared artifact's digest, services, rollback target (= CURRENT) and the batch evidence. CURRENT, the latest start, STOP and epoch are re-checked at activation, then `promote` runs. | main moved after the merge; CURRENT moved; the artifact or merge commit is quarantined; STOP before activation |
| verify | `release_window` verification: promote exit, CURRENT, BUILD_SHA, units, /api/health, served copy, CC pages, platform-health, needs-action. | any check fails: roll back to the bound target, latch STOP, quarantine the artifact and its lineage, send a P1 through the host notifier |
| outcome | Writes a `TrainOutcome@v1` (validated); `control.train_terminal`. | |

**Windows** (America/New_York). 18:00 and 00:00 are general windows. 06:00 needs a proven drain: the production
controller wires `release_train_drain.ReadOnlyDrainProbe` (Phase 7 prerequisites, 2026-10-22; read-only, fail
closed: measured restart impact, market hours, critical-lane schedule, running `pipeline_runs`, held `flock` locks; see
the arming packet §J.2). 08:00 has a latest activation start of 09:00 minus the measured promote, verify and
rollback times (`release_train_timing.DurationHistory`: the worst of the last 10 samples from `train_measurements.jsonl`
and the deploy receipt history), minus a 10-minute buffer, capped by the delegation's `latest_start_et`. It is checked
at the start, before the merge and at activation, and the window is skipped until each of the three has 3 samples.
08:00 is also skipped on an 08:30 macro-release day, or when the calendar is missing or stale.

**Macro calendar (updated in release 3).** The controller now reads `scripts/lib/macro_calendar.py`
(`MacroCalendar@v1` at `<state root>/data/runtime/macro_calendar.json`, from the n8n lane `macro-calendar-refresh`;
72 h). The earlier `~/.config/tradeai/release_train/macro_calendar.json` reader (`MacroReleaseCalendar@v1`) is gone.
While the file is absent, 08:00 is always skipped (fail closed).

A window can be claimed only from `start - 90 min` until `start + 15 min`. The claim is
`claims/<YYYYMMDD>-<slot>.json`, created O_EXCL, so a repeated local hour cannot activate twice. Window starts use
`fold=0`, and a non-existent local time is skipped.

### 11.2 Durability, locks, restart

- **Events.** Every step is a `TrainEvent@v1` (validated against the Phase 1 contract). It is written through
  `release_train_queue.append_event` when the store probes OK. When the store reads NOT_MIGRATED or
  DB_UNAVAILABLE, or an append fails, the row goes to `train_events.jsonl` (append-only, fsync, seq). The
  projection is rebuilt at the end of a run when the store is OK.
- **Intents** are written to `train_intents.jsonl` and `trains/<id>/state.json` before the capability is reserved
  and before every side effect.
- **Locks.** `train.lock` means one train at a time. The window claim means one train per window.
  `control.claim_train` covers the control state. `.lock` is the one global release lock that a manual
  `release_window.py run` also holds, so a manual release and a train mutation exclude each other. A busy lock is
  a refusal that consumes nothing.
- **Restart.** A non-terminal train makes the next run refuse with `REFUSED_RECONCILE_FIRST`.
  `train-reconcile` reads GitHub main, CURRENT and the units and decides each pending intent: ABSENT, APPLIED,
  APPLIED_UNVERIFIED (STOP latched) or AMBIGUOUS (STOP latched, train left open). It reconciles the capability
  ledger, including an orphan reservation left by a crash between intent and reserve.
- **Quarantine.** `quarantine.jsonl` is append-only. While an unresolved quarantined SHA is in main's lineage, every
  train refuses (`REFUSED_QUARANTINED_LINEAGE`), until `train-quarantine-resolve` records how main was reconciled.

### 11.3 Commands (dry run is the default everywhere)

```bash
python3 scripts/release_window.py train-plan [--now ISO] [--json]          # read-only
python3 scripts/release_window.py train-run [--integrate [--local-test]] [--simulate-classifier allow] [--json]
python3 scripts/release_window.py train-run --live                          # REFUSED_BUILD_ONLY today
python3 scripts/release_window.py train-status
python3 scripts/release_window.py train-reconcile [--live]
python3 scripts/release_window.py train-quarantine-resolve --sha S --reason R --evidence E [--live]
python3 scripts/release_window.py train-claim [--apply]                     # n8n requests; lists unless --apply
```

`--integrate` really fetches PR refs into the release checkout (`refs/train-scratch/pr-N`) and adds a scratch
worktree there. It is opt-in, and the only dry-run flag that writes anything outside stdout.

### 11.4 Dry run on this host, 2026-10-21 (quoted; read-only: `gh pr list`, `git ls-remote`, a store probe)

```
$ TMPDIR=~/.cache/rtc python scripts/release_window.py train-plan --now 2026-10-21T17:00
release train DRY RUN at 2026-10-21T17:00:00-04:00
LIVE WOULD REFUSE: control CONTROL_UNARMED
LIVE WOULD REFUSE: delegation MISSING: /home/johnclaw/.config/tradeai/release_train/delegation.json does not exist (never armed)
preconditions: latch ABSENT, control UNARMED epoch None, delegation MISSING
window 2026-10-21T18:00-04:00 slot 1800 (canary) lead; enabled=False
LIVE WOULD REFUSE: window 1800 is disabled in the delegation
WOULD claim window 2026-10-21T18:00-04:00 (claim key 20261021-1800, O_EXCL) and train rt-20261021-1800-9445f1
window rules: pass
select: pr-hygiene-receipt+gh-pr-list (fallback: phase1:release_queue store:not_migrated): 29 open, complete=False ['no_receipt:/home/johnclaw/trade-ai-releases/persistent-state/data/runtime/pr-hygiene-audit_last.json']
=> NO_OP (QUEUE_INCOMPLETE: no_receipt:...pr-hygiene-audit_last.json)
outcome: NO_OP reason: QUEUE_INCOMPLETE exit: 0
```

The real host stops at select: the PR-hygiene lane has not written a receipt, and the store is not migrated.

The full pipeline below comes from the test fixture world: a temp git repo, a fake GitHub and deploy host, and an
armed temp control and delegation. Three PRs are queued; #1904 edits `scripts/release_window.py`:

```
release train DRY RUN at 2026-10-21T18:05:00-04:00
preconditions: latch ABSENT, control RUNNING epoch 1, delegation AUTHORIZED
window 2026-10-21T18:00-04:00 slot 1800 (canary) open; enabled=True
WOULD claim window 2026-10-21T18:00-04:00 (claim key 20261021-1800, O_EXCL) and train rt-20261021-1800-9033d1
window rules: pass
select: test-queue: 3 open, complete=True 
select: 2 eligible [1901, 1903]; 1 not riding
freeze: base 11d15a11d5b4, members #1901@d87bf0637, #1903@c82398be7; checks ['cio-hardening', 'agent-governance', 'release-readiness', 'ci-gate']; manifest sha256:e05405195954
WOULD merge --no-ff #1901 d87bf0637230 in a scratch worktree (conflict ejects it and its dependents)
WOULD merge --no-ff #1903 c82398be7b50 in a scratch worktree (conflict ejects it and its dependents)
WOULD regenerate once: noop
WOULD run local tests: /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python -c import os,sys; sys.exit(1 if os.path.exists('FAIL_MARKER') else 0) (worker env from allowlist ['PATH', 'LANG', 'LC_ALL', 'TZ', 'TERM']; bisect budget 6 runs / 2700s)
WOULD issue build_publish capabilities (push_train_ref, open_batch_pr) bound to base 11d15a11d5b4, 2 PR heads, output ref refs/heads/train/rt-20261021-1800-9033d1
WOULD push <candidate> -> refs/heads/train/rt-20261021-1800-9033d1 (the only ref the build capability allows)
WOULD open/update batch PR head=train/rt-20261021-1800-9033d1 base=main title='Release train rt-20261021-1800-9033d1 (2 PRs)'
WOULD wait <= 600s for ['cio-hardening', 'agent-governance', 'release-readiness', 'ci-gate'] to read exactly 'success' (latest run, app github-actions) on <candidate>; neutral/skipped/cancelled/missing never pass; no tree-equivalence fallback
WOULD re-read the 4 checks on the candidate, then issue a merge capability (expected base 11d15a11d5b4, candidate, artifact sha256:e05405195954, evidence digest, rollback target main_ref 11d15a11d5b4)
WOULD re-check STOP / control epoch / delegation epoch+digest / main == base / PR heads immediately before the merge
WOULD merge batch PR (merge_method=merge, sha=<candidate> so a moved head is refused)
WOULD record the resulting main SHA and require parents == [base, candidate]
WOULD wait <= 600s for exact-SHA push/main checks ['cio-hardening', 'agent-governance', 'release-readiness'] on the merge commit
WOULD refuse if the merge commit or its prepared artifact is quarantined, or CURRENT moved
WOULD git -C <tmp>/checkout fetch + checkout --detach <merge commit>; then bash <tmp>/deploy.sh prepare (TRADEAI_RELEASE_CAMPAIGN=release-train-rt-20261021-1800-9033d1, TRADEAI_RELEASE_PR=<batch PR>) under a prepare capability
WOULD issue a promote capability: artifact digest of the prepared dir, services ['portfolio-server.service', 'cio-governed-bridge.service', 'tradeai-n8n-coordination-gateway.service', 'tradeai-n8n-run-relay.service', 'tradeai-n8n-run-executor.service'], rollback target = CURRENT (<tmp>/releases/prev), batch evidence bound
WOULD re-check STOP + epoch at activation, then bash cio_phase2_exact_main_deploy.sh promote <prepared dir>
WOULD verify: promote exit, CURRENT, BUILD_SHA, units, /api/health, served copy, CC pages ['/v3/', '/v3/system', '/v3/cio'], platform-health, needs-action
WOULD on failure: rollback <bound target>, latch STOP, quarantine the artifact
=> DRY_RUN_COMPLETE (DRY_RUN_COMPLETE: nothing was claimed, issued, pushed or written)
outcome: DRY_RUN_COMPLETE reason: DRY_RUN_COMPLETE exit: 0
```

### 11.5 Capability library changes (`scripts/lib/release_capability.py`)

- `TRAIN_RE` now also accepts the Phase 1 id `rt-YYYYMMDD-HHMM-<4..12>`. This is the id used by the store, the view
  and the contracts. `train-…` ids still validate.
- `issue_promote(..., batch_candidate_sha, batch_evidence)` adds qualification v1. `ci-gate` is a
  pull_request-only workflow, so it never runs on the merge commit. The batch evidence must carry all four checks on
  the batch PR head, and the main evidence must carry the other three on the merge commit. Both digests are bound.
  Each SHA is qualified by runs on exactly that SHA, so this is not a tree-equivalence fallback.

### 11.6 n8n window requests (contract `docs/ops/RELEASE_TRAIN_N8N_CONTRACT.md` rev 1 `5a230186a` when built; now rev 3)

`train-claim` is the controller half of C1–C11:

- **C1–C2.** Strict validation (unknown keys are invalid, so a request that names a SHA, PR, train id or command is
  refused). The claim is `os.rename(pending -> claimed)`, processed in `requested_at` order under
  `.claimer.lock`.
- **C3.** Shadow runs a dry run only: simulated writer, no capability, no window claim, no STOP or epoch write. An
  off-window shadow request is evaluated as at its window start.
- **C4.** A live request is re-validated on the host. While BUILD_ONLY it is refused with `CONTROLLER_BUILD_ONLY`.
- **C5.** An ACKNOWLEDGED receipt is written before the run.
- **C6–C8.** Expiry, duplicate window and terminal-receipt immutability are enforced.
- **C9.** The closed refusal set is used.

The proposed units (`tradeai-release-train-claim.{path,timer,service}.proposed`) are in this packet and are not
installed (operator item O7).

**Contract gaps (reported, not diverged from):**

- **(a) C9 codes — RESOLVED (contract revision 3; controller updated 2026-10-21, branch
  `fix/release-train-arming-blockers-20261021`, arming finding 9).** The controller's `REFUSAL_CODES` now equal the
  receipt schema's closed set. A reconcile-first refusal is `RECONCILE_REQUIRED`, a quarantined lineage is
  `QUARANTINED_LINEAGE`, a corrupt control state or an unreadable main is `CONTROLLER_ERROR` and a controller
  exception is `CONTROLLER_FAILED` (both with `state: FAILED`); a busy lock stays `LOCK_HELD`, a bypass environment
  `NOT_ARMED`. The precise reason still travels in `refusal.detail`.
- **(b) Schema and validator — RESOLVED.** Release 2 ships `config/schemas/release_train/train_window_{request,receipt}.v1.schema.json`
  and `scripts/lib/release_train_window_view.py`. The controller's temporary §5 validator is gone: `train-claim` uses
  `validate_request` (plus the host rule that the file is named `<request_id>.json`) and validates every receipt
  with `validate_receipt` before writing it (a valid request whose receipt fails the contract gets a FAILED
  `CONTROLLER_ERROR` receipt instead).
- **(c) Simulated outcomes.** A simulate run that got through every step reports `NO_OP` plus `simulated_effects`,
  per §7 ("never a release").
- **(d) Receipt file mode.** Receipts are written 0600 by `_atomic_write_json`. The relay must read them as the same
  uid; if it does not, the mode is a decision for O5.

### 11.7 What still needs Phase 1, Phase 4 or the operator

**Phase 1**

- Apply `migrations/2026_10_21_release_queue.sql` (operator). Until then, events go to JSONL and the queue is the
  receipt + gh.
- The submission path: something must append `submitted` events, or the store queue stays empty.
- A PR-hygiene receipt on the host (the lane is at SHADOW and writes none).
- TrainEvent@v1 has no intent/effect type. Intents live in `train_intents.jsonl`. Propose `intent_recorded` /
  `effect_recorded` if they should be in the store.
- Ride approvals for `needs_operator` are not consumed (those PRs never ride in v1).

**Phase 4**

- The request lane, the schema files and the relay view (§11.6 gaps).
- Install and activate the n8n workflow (O5).

**Operator**

- Write the delegation record (`~/.config/tradeai/release_train/delegation.json`) and the capability key (mode 600).
- `release_control_cli.py arm`.
- Enable windows in the order 18:00, 00:00, 06:00, 08:00.
- An 08:30 macro calendar.
- A proven 06:00 drain.
- The GitHub App and token minting (D2). `GITHUB_WRITES_STATUS` stays PROPOSED until D2 and the AGENTS 17.0.0
  amendment are in force.
- `ci-gate` as a required context (D4).
- Flip `TRAIN_CONTROLLER_STATUS` by reviewed PR.
- Install the claimer units (O7).
- **The deploy script's release-grant binding.** `cio_phase2_exact_main_deploy.sh` still requires a guard
  `release-write` grant naming the PR, SHA or campaign. The train passes campaign `release-train-<id>` and the batch
  PR. A standing-delegation release therefore needs either a reviewed change so that `release_grant_preflight.py`
  accepts a capability reservation (that file is a protected surface), or an operator grant per train. It is not
  changed here.
- **Test-worker isolation is environment-level only.** A separate uid or cgroup (`systemd-run --user --scope`) is
  the stronger boundary the design asks for (§2).
- Scratch worktrees are never removed by the controller (§0 rule 6). Each is a full checkout of the repo, so
  retention under `~/.cache/rtc` needs an archive-with-tripwire rule.

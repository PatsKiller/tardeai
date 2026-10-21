# Release train: merge when green, release main in the 12:00 and 17:30 windows

```
Status:      DRAFT (code in this branch; nothing scheduled, granted, released or changed on GitHub)
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
- `ExecStart` is `<canonical>/.venv/bin/python ~/tradeai-exact-main-20260827/scripts/release_window.py run`.
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
3. `bash docs/ops/packets/release-train-20261021/install_release_window_timer.sh` (dry run), then
   `TRADEAI_OPERATOR_INSTALL=1 … --apply`.
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

No push, release, grant, promote, crontab, systemd, n8n or GitHub-setting change. No `AGENTS.md` or adapter edit;
the policy text is in §4.4 only. The `lane_registry.json` row stays `NEVER_SCHEDULED` until the timer is installed.

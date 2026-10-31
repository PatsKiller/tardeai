# Self-heal train monitor and fixer

Status: BUILT, SHADOW. Revised 2026-10-31 after an independent review: AGENTS.md §24.5 binds — "The §28.14 fixer stops at a local fix branch". Neither the fixer nor the train monitor's regenerate rules ever push or open a PR; a person pushes the local branch they leave (fix.patch and the PR body sit beside it). A live attempt arms only on an operator `git-push` guard grant naming `self-heal-fixer` (`arm_on: guard_grant`); the header Status never arms. Before the hand-off the fix commit must pass check_no_pii and a secret scan, and the Claude credentials file is bound read-only into the sandbox.

Operator, 2026-10-25 (verbatim, voice-typed): "Arm the fixer and also a logger that tracks what was fixed, but this
train should be no different than submitting in [to GitHub]. Somebody needs to monitor it, if there's little errors
they need to correct it as long as they're adhering to our agents.md."

## 1. The binding text: AGENTS.md 21.0.0 §28.14 (PR #2128)

The rule is §28.14 in AGENTS.md. This document does not restate it. It maps each item of the section to the code
that enforces it.

| §28.14 item | Where it is enforced |
|---|---|
| Arming is this section ACTIVE; no separate guard grant; shadow until then | Monitor: `self_heal_train_intake.policy_gate` needs Policy-Version >= 21.0.0, ACTIVE, and a heading starting `## 28.14 Self-heal monitor and fixer` with ACTIVE on it. Fixer: `config/self_heal_fixer.json` `arming.arm_on: policy_section`, so `arming_verdict` arms on `policy_verdict` alone (the 24.11 or 28.14 heading ACTIVE at origin/main). A grant never arms. Kill switches: `data/self_heal/MONITOR_DISABLED` stops both lanes; `data/self_heal/FIXER_DISABLED` stops the fixer. |
| 1 A host monitor independent of n8n | `config/systemd/user/tradeai-self-heal-train-monitor.{service,timer}`, every 5 min. It is installed by the release's staged-units step (`config/staged_user_units.json`, PR #2134). Missed runs are caught by the cron outage watchdog through the lane row's heartbeat `ok_at`. |
| 2 Four deterministic remediations, each once per incident | `config/self_heal_train_monitor.json` `deterministic[]`:<br>- the infrastructure-flake CI rerun;<br>- regenerating a canonical generated file with its own generator (`ci_gates_canonical`, `docs_index_regen`);<br>- the disk-packet re-pin;<br>- the stale-train reconcile.<br>`rules_done` makes each rule run once per episode. A second failure goes to the fixer. |
| 3 Every other fix is an ordinary PR | The fixer pushes ONE branch with `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` (never the override) and opens ONE `self-heal-fix` PR. It never merges, releases or deploys. Each push is one `fixer_push` row in the fix log. |
| 4 Refused scopes go to a person | `refused_scopes`: `broker_active_trader`, `guard_policy`, `train_self`, `credentials`, plus `self_heal_self`, which is stricter than the section. A refused failure gets a P1 and a coordinator task, and no fix attempt. |
| 5 Every action is logged; the log is append-only | `data/self_heal/fix_log.jsonl` (SelfHealFixLog@v1). Both lanes only append to it. It is shown on Releases & schedules → Fixes (PR #2133). |
| 6 Escalation P1 once per incident | After `max_attempts_per_signature` (2) or on a refused scope, the monitor sends P1 through `telegram_alert.send_telegram` and marks it `paged_at`, so it is sent once. When `scripts/delivery_failure_alerts.py` (PR #2106, the §28.12 step 10 path) is on the release, the email and SMS channels come from it. |

Budgets are read from config and never widened by model output. Per fixer job, reserved before launch: 4 iterations,
90 minutes, USD 12. Per ET day: 3 jobs and USD 24; 1 job per cycle; diff at most 8 files and 600 lines. Per monitor
day: 3 hand-offs, 8 deterministic actions, 4 CI reruns, 10 coordinator tasks, 12 P1 alerts. Per signature: 2 attempts,
and a 12 h cooldown after a failed model attempt.

## 2. How a failure flows

| Source | What is read | Becomes |
|---|---|---|
| CI | `gh run list --branch main --event push` (GET), latest run per workflow of main HEAD; failed job names (`gh run view --json jobs`) and `--log-failed` tail | one finding per red workflow; signature = workflow + failed jobs + first failing tests (never the SHA) |
| train | `trains/<id>/outcome.json` with FAILED_PRE_MERGE / MERGED_NOT_LIVE / ROLLED_BACK / ROLLBACK_FAILED; `trains/<id>/state.json` with no outcome for longer than 240 min; live window receipts in state FAILED or with `needs_action` TRAIN_STALLED (shadow and simulate receipts are ignored) | coordinator task (+ P1 for MERGED_NOT_LIVE / ROLLED_BACK / ROLLBACK_FAILED); a stale train runs `train-reconcile` |
| tester | `post_release_tester/last_api.json`, `last_light.json` with status FAILED (PR #2106) | the Claude Code fixer |
| sweep | `post_release_tester/last_nightly.json` broken findings, one per route and kind | the Claude Code fixer |

The fixer hand-off is one `N8nCodeDefect@v1` record in `data/self_heal/fixer_defects.jsonl`. This is the same
contract the fixer already consumes from the n8n diagnoser. Each record carries the failing log tail as its receipt.
Its lane is `train-monitor-<source>`. The fixer reads this store read-only (`train_incidents` in
`scripts/self_heal_fixer.py`). The job is recovered when the monitor has written a `fixed-released` row with
`verified_at` for it.

## 3. Deterministic remediations

| id | trigger | action |
|---|---|---|
| `ci_infra_flake_rerun` | every failed job is the Postgres shard (`shard pg`, `hardening shard pg`), the log shows a pull or runner failure (`toomanyrequests`, `failed to pull`, `Error response from daemon`, TLS or i/o timeout, runner shutdown), and the run is on attempt 1 | `gh run rerun <id> --failed`, once; if it is still red, the fixer takes it |
| `ci_gates_canonical` | log names `config/ci_gates` / `not canonical` / `GateRegistryError` | re-render each gate through `lib.ci_gates.validate` + `render`; a malformed gate is refused (a human decides); a regenerate PR |
| `docs_index_regen` | log names `docs/INDEX.md` / `--check-index` | `scripts/report_docs_inventory.py --write-index`; a regenerate PR |
| `disk_packet_repin` | log shows `source_config_changed` / `review_source_pins_mismatch` | re-derive `activation-input-sha256.json` from the config bytes and `review.required.json` `source_config_pins_sha256` from the pins file (precedents 583512363, dcbdd0d08); no other field is touched; a regenerate PR |
| `train_stale_reconcile` | a non-terminal train older than 240 min | `release_window.py train-reconcile` dry run; `--live` only when the dry run exits 0 with no AMBIGUOUS disposition; otherwise P1 + coordinator |

A regenerate PR is built in a throwaway worktree off `origin/main` under `$TMPDIR`. It commits only the rule's
`allowed_paths`; any other changed path refuses the fix. It pushes one branch `self-heal-regen/<rule>-<ts>` and opens
one PR labelled `self-heal-fix`. If the generator changes nothing, the failure was not this one, and the next tick
hands it to the fixer.

## 4. Outcomes

`detected` → (`shadow-proposed` in shadow) → `remediating` (re-run or reconcile issued) / `fixer-queued` /
`fix-PR-open` → `fixed-released-pending` (the merge is in CURRENT) → `fixed-released` (the signature is absent on a
later tick) or `fixed-no-release` (a re-run or reconcile cleared it). Exits: `escalated` (refused or coordinator),
`gave-up` (attempts exhausted), `cleared` (it went away by itself). A CI-sourced fix is judged absent only when main
CI is settled (GREEN or RED); pending or unreadable CI proves nothing. An outcome is never judged in the same tick as
the action that produced it. A signature that recurs after `fixed-*` or `cleared` starts a new episode with a fresh
attempt budget.

## 5. Running it

```
python3 scripts/self_heal_train_monitor.py            # dry run: prints decisions, writes nothing
python3 scripts/self_heal_train_monitor.py --apply    # a tick (shadow until 21.0.0 §28.14 ACTIVE)
python3 scripts/self_heal_train_monitor.py --status   # projected fix log + last heartbeat
```

Writes: `data/self_heal/fix_log.jsonl` (append-only), `data/self_heal/train_monitor_state.json`,
`data/self_heal/fixer_defects.jsonl` (live only) and `data/runtime/self-heal-train-monitor_last.json` (the
heartbeat, `ok` + `ok_at`, measured by the cron outage watchdog). Paths are relative to `TRADEAI_STATE_ROOT`.

The fixer's worktrees live under `~/.shw` (the operator's home, expanded at run time). That path is on disk, never `/tmp`, and it is short: the
egress bridge binds a unix socket at `<worktree_root>/<job_id>-eg/s`, and AF_UNIX paths cap at 107 bytes.

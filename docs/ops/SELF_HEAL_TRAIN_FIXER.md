# Self-heal train monitor and fixer

Status: BUILT, SHADOW. It turns LIVE only when AGENTS.md 20.4.0 is ACTIVE and carries section 28.14 (below) marked ACTIVE.
Owner: platform. Code: `scripts/self_heal_train_monitor.py`, `scripts/lib/self_heal_train_intake.py`,
`scripts/self_heal_fixer.py` (the existing Claude Code fixer). Config: `config/self_heal_train_monitor.json`.

Operator, 2026-10-25 (verbatim, voice-typed): "Arm the fixer and also a logger that tracks what was fixed, but this
train should be no different than submitting in [to GitHub]. Somebody needs to monitor it, if there's little errors
they need to correct it as long as they're adhering to our agents.md."

## 1. Proposed AGENTS.md text: section 28.14

This text goes into the 20.4.0 amendment (branch `docs/agents-20-4-0-hands-off-20261025`). The code reads the
heading line exactly. It must begin with `## 28.14 Self-heal monitor and fixer` and carry `ACTIVE` on the same line.

```markdown
## 28.14 Self-heal monitor and fixer (20.4.0, ACTIVE; extends §0 rules 3, 4, 7, §17, §24.5)

**What it is.** The host lane `self-heal-train-monitor` (systemd user timer, every 5 minutes, independent of n8n)
reads main CI of main HEAD, release-train outcomes and window receipts, the post-release tester and the nightly sweep.
It turns each failure into one fix per failure signature. The lane `self-heal-fixer` is the existing headless Claude
Code fixer. Under this section both may open pull requests from a scheduled job. This is the exception to §24.5 for
these two lanes only.

**Fix PRs are ordinary PRs.** A fix is a branch and a pull request. It runs normal CI and is classified by the release
train like any other PR. Neither lane merges, deploys, promotes, rolls back, re-runs a train window, edits
crontab/systemd, writes the production DB or calls a broker. The train merges a fix PR only when it is eligible. A
fix PR that is not eligible goes to the coordinator queue (`scripts/agent_claim.py task add --kind fix`).

**Order of remediation.** The monitor tries a deterministic remediation first. These run without a model and come
from the reviewed list in `config/self_heal_train_monitor.json` `deterministic[]`:
- re-run a CI job once for a known infrastructure flake;
- regenerate the canonical `config/ci_gates` JSON;
- regenerate `docs/INDEX.md`;
- re-pin the disk-standing packet when only pinned config bytes changed;
- `release_window.py train-reconcile` for a stale train (dry run first; `--live` only when nothing is AMBIGUOUS).

Anything else goes to the Claude Code fixer. The fixer works in an isolated worktree and sandbox, with a reserved
budget, the diff guard and protected paths. It never deletes, skips or weakens a test, and section 0 is quoted in its
prompt.

**Refused scopes.** Broker, Active Trader and MBI code; guard and policy (AGENTS.md, AI_WORK_POLICY.md, the adapters,
hooks, `bin/`, `.github/`); the train's own files; the self-heal lanes' own code and config; credentials and auth.
The monitor never fixes a failure in these scopes. It sends a P1 alert and opens a coordinator task. Train outcomes
caused by the release machinery (MERGED_NOT_LIVE, ROLLED_BACK, ROLLBACK_FAILED, stalls) are coordinator work, never a
model fix.

**Budgets and limits** are read from config and are never widened by model output:
- per fixer job, reserved before launch: 4 iterations, 90 minutes, USD 12;
- per ET day: 3 fixer jobs and USD 24;
- 1 job per cycle;
- per monitor day: 3 fixer hand-offs, 8 deterministic actions, 4 CI re-runs, 10 coordinator tasks, 12 P1 alerts;
- per signature: 2 attempts and a 12 h cooldown after a failed model attempt;
- each deterministic rule runs at most once per episode;
- the fixer's diff is at most 8 files and 600 changed lines.

**Logging.** Every change of a fix is one row in the append-only `data/self_heal/fix_log.jsonl` (SelfHealFixLog@v1).
A row records:
- `detected_at`, `source`, failure signature, evidence refs;
- remediation kind, attempts, model cost;
- PR number and head;
- outcome: one of `fixed-released`, `fixed-no-release`, `fix-PR-open`, `escalated`, `gave-up`, `cleared`, or
  `shadow-proposed`;
- released SHA and `verified_at`.

A fix is `fixed-released` only when its merge commit is in the served release AND the failure signature is no longer
observed after that release. A merged fix is not a heal. The Command Center shows the log (Ops → Releases &
schedules → Fixes). The digest carries one daily line, and each fix released gets one short note.

**Escalation.** These are P1 at once through the existing failure-alert path (the Telegram chokepoint): a refused
scope, attempts exhausted (`gave-up`), an ambiguous reconcile, or a release-machinery outcome rated P1. Each also opens
one coordinator task. An escalation is sent once per fix, never repeated per tick.

**Arming and shadow.** Until this section is ACTIVE the monitor runs in SHADOW (§0 rule 7, the dry-run phase). It
detects and logs `shadow-proposed` rows, and it executes, launches and sends nothing. The fixer additionally needs its
operator guard grant (`git-push`, reason naming `self-heal-fixer`). The kill switch
`<state>/data/self_heal/MONITOR_DISABLED` stops all action. A missed monitor run is caught by the cron outage
watchdog.
```

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
python3 scripts/self_heal_train_monitor.py --apply    # a tick (shadow until 28.14 ACTIVE)
python3 scripts/self_heal_train_monitor.py --status   # projected fix log + last heartbeat
```

Writes: `data/self_heal/fix_log.jsonl` (append-only), `data/self_heal/train_monitor_state.json`,
`data/self_heal/fixer_defects.jsonl` (live only) and `data/runtime/self-heal-train-monitor_last.json` (the
heartbeat, `ok` + `ok_at`, measured by the cron outage watchdog). Paths are relative to `TRADEAI_STATE_ROOT`.

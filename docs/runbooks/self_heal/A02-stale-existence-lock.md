# A02-stale-existence-lock — stale existence lock (pidfile) whose recorded owner is dead and whose age exceeds the lane timeout

Generated from `config/self_heal_runbook_catalog.json` v2026-11-08.2 (priority 110); **do not edit this page** — run `python3 scripts/gen_self_heal_runbook_docs.py --write`. Category A · Locks & concurrency.

| | |
| --- | --- |
| Tier | `auto_notify` |
| Action | `release_stale_flock` |
| Attempts | 2 · cooldown 60 min |
| Verify | `lock_absent_or_free` |
| Replay | 0 failures in the window |

## 1. What fires it

The engine selects this entry when **any** of these holds. A `failure_class` is a lowercased set membership; a reason pattern is searched in `reason`/`failure_kind`/`detail`; an exception pattern is searched in the wider text — reason, failure kind, exception, detail, title, error and the last 4 000 characters of stderr/stdout:

- failure class `stale_lock`
- reason text matches `/\bstale[_ -]?lock\b/`
- reason text matches `/\bstale[_ -]?pidfile\b/`

It is selected by explicit priority **110** (lowest matching priority wins; ids break ties). Should it not match, the next entry above it is `A03-sqlite-database-locked` (priority 120).

## 2. Evidence to collect

Collect these before planning. The plan is only as good as the evidence it is evaluated on, and a missing fact is a refusal, never an assumption.

| field | why it is read |
| --- | --- |
| `lane` | the incident's lane; the engine refuses without it |
| `signature` | the stable signature text the fixer keys the idempotency hash on |
| `failure_class` | the class the caller derived (the matcher's first input) |
| `reason / failure_kind / detail` | the matcher's reason text |
| `exception / stderr_tail / stdout_tail` | the wider text the `exception_regex` patterns read |
| `attempts` | how many times this entry already acted for this incident |
| `entry_last_attempt_at` | the entry's cooldown anchor |
| `lane_last_action_at` | the lane's hourly rate-limit anchor |
| `lock_path` | precondition lock_path_recorded: the lock's path is known, so the action can name what it would archive. |
| `owner_pid` | precondition owner_pid_recorded: the lock records an owner pid, so liveness can be decided instead of guessed. |
| `pid_alive` | precondition owner_pid_dead: the recorded owner is dead, so the lock is orphaned rather than held. |
| `lock_age_s` | precondition lock_age_recorded: the lock's age is known, so 'older than the lane's own timeout' can be decided. |
| `lane_timeout_s (or the contract's baseline.timeout_s)` | precondition lock_age_gt_lane_timeout: the lock has outlived the lane's timeout, i.e. it cannot be a run still inside its budget. |
| `lock_kind` | precondition lock_kind_existence: the lock is existence-based (a pidfile/marker), not a kernel flock. A flock is released by the kernel when its holder dies and a holder-less flock file blocks nothing, so there is nothing to archive. |

## 3. Diagnosis

The engine evaluates these checks in this order; the first `ok: false` is the refusal and the plan's `reason` names it:

- `entry_match` — one entry matched (lowest explicit priority wins, ids break ties)
- `unambiguous_match` — no other entry shares the winner's priority
- `attempt_budget` — `attempts < max_attempts`; at the cap the action becomes `escalate_finding`
- `entry_cooldown` — the entry has not acted within `cooldown_min`
- `lane_rate_limit` — no mutating action on this lane in the last hour
- `not_execution_lane` — the lane is not an execution lane (a global rail: no entry can opt out)

Then this entry's own preconditions, in the catalog's order:

- **`lane_present`** proves the incident names a lane. Without one the engine refuses — an unattributed failure has no owner. Collect: the lane id from the receipt's file name (`d:<lane>:<mode>:<stamp>.json`) or the dead letter's `lane_id`.
- **`not_execution_lane`** proves the lane is not an execution lane. No runbook action may touch one; a failure there is escalated. Collect: the lane id, checked against the engine's execution-lane refusals.
- **`lock_path_recorded`** proves the lock's path is known, so the action can name what it would archive. Collect: the absolute path the lane's lock wrapper printed in its stderr or reason.
- **`owner_pid_recorded`** proves the lock records an owner pid, so liveness can be decided instead of guessed. Collect: the pidfile's contents (or the lock's log line).
- **`owner_pid_dead`** proves the recorded owner is dead, so the lock is orphaned rather than held. Collect: collect `pid_alive` yourself (`kill -0 <pid>` / `ps -p <pid>`) and put it in the evidence. When the field is absent the engine probes `kill(pid, 0)`; a probe it cannot make is a refusal.
- **`lock_age_recorded`** proves the lock's age is known, so 'older than the lane's own timeout' can be decided. Collect: `stat -c %Y <lock_path>` against `date +%s`.
- **`lock_age_gt_lane_timeout`** proves the lock has outlived the lane's timeout, i.e. it cannot be a run still inside its budget. Collect: the recorded age, and the lane's timeout from its health contract.
- **`lock_kind_existence`** proves the lock is existence-based (a pidfile/marker), not a kernel flock. A flock is released by the kernel when its holder dies and a holder-less flock file blocks nothing, so there is nothing to archive. Collect: how the lane acquires the lock: `safe_flock.sh` (flock) or a pidfile/marker (existence).

To replay this entry: `python3 -m pytest tests/test_self_heal_runbooks_lq1231_20261108.py -k 'A02-stale-existence-lock' -q` plans a synthetic incident into it; `tests/fixtures/self_heal_runbooks/` is the replay corpus for the signatures seen in real receipts.

## 4. The only action it may take

`release_stale_flock`

**the only action that writes to the host.** With `--apply`, and only after the plan's preconditions held, it re-probes the lock non-blockingly and re-checks the path against the never-touch list; if the lock is still free it renames the file to `<name>.stale-<UTC stamp>`. The archive is why nothing is deleted.

**Parameters.** `lock_path`, `lock_kind` (from the evidence; the plan carries them in its `_apply` block).

**It does not:** never removes a file (`os.replace` to an archive name), never touches a lock a live process holds, never acts on a kernel flock (a holder-less flock file blocks nothing), never touches a path inside the never-touch list.

**Tier.** `auto_notify` — the fixer applies the action and posts a FINDING, so an operator sees the failure even when the action works. Use this tier when the *occurrence* is information: a timeout, a refused route, an unverifiable output.

## 5. Verification

`verify.kind = lock_absent_or_free`, window 300 s. Verified means: the lock file is gone, or nothing holds it.

```bash
ls -l <lock_path> 2>&1
fuser -v <lock_path> 2>&1
ps -o pid,lstart,cmd -p <owner_pid> 2>&1
```

**Expected:** `No such file or directory`, or the file listed with `fuser` printing nothing (no holder) and `ps` answering `no such process`. Any pid named by `fuser` means a live holder: the lock is doing its job, do not touch it.

## 6. Rollback

`mv <lock_path>.stale-<stamp> <lock_path>` — the archived name is the rollback.

## 7. Budget and cooldown

- **Attempts:** 2. At the cap the engine switches the action to `escalate_finding` with `reason: max_attempts_reached`; it does not keep trying.
- **Cooldown:** 60 min between this entry's actions on one lane.
- **Lane rate limit:** one mutating action per lane per hour. The observing actions (`noop_wait_recheck`, `escalate_finding`, `mark_weekend_expected`, `release_stale_sqlite_wal_lock`) are not rate-limited.
- **Idempotency:** the plan's key hashes the entry, lane, signature and attempt. It is stable across a day and across a restart, so applying the same plan twice is the same act.

## 8. When to escalate, and what to send

Escalate when any of these is true:

- the attempt budget is spent (2 attempts);
- a precondition refuses (`reason: precondition_failed:<check>`) — the action is not safe;
- verification still fails at the end of its window (§5);
- the tier is `human_only`: the engine escalates on the first plan by design.

The FINDING title, rendered from the catalog with the plan's values:

```text
stale lock on <lane> did not pass its sanity checks
```

Send it with the receipt it was rendered from: the plan's `lane`, `signature`, `entry`, `reason`, `attempts: n/max`, `checks[]`, `idempotency_key` and the receipt path — plus what §5's command printed. A FINDING without the receipt path cannot be audited.

## 9. Human steps

1. the lock is archived (renamed .stale-<utc>), never deleted; a kernel flock is never touched because the kernel releases it when the holder exits

## 10. Tests

The catalog declares these test labels (the plan requires at least three per entry: a match, a refusal on a failed precondition, and a repeat):

- `fx-stale-lock-match`
- `fx-stale-lock-refuse-live-pid`
- `fx-stale-lock-repeat`

The mechanical evidence that they hold:

- `tests/test_self_heal_runbooks_lq1231_20261108.py` — schema, action whitelist, priorities, per-entry match, precondition refusal, repeat determinism, rate limit, dry-run default.
- no corpus fixture asserts this entry yet: the corpus covers signatures seen in receipts, and this one has not been seen in the window (its evidence is the taxonomy, not a live receipt).

```bash
python3 -m pytest tests/test_self_heal_runbooks_lq1231_20261108.py tests/test_self_heal_runbook_coverage_20261108.py -q
```

---

[Workbook index](INDEX.md) · [14-day coverage](COVERAGE.md) · [rulings behind the cells](RULINGS.md)

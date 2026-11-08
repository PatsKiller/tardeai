# A03-sqlite-database-locked — sqlite 'database is locked': report the lock, never remove a WAL/SHM file

Generated from `config/self_heal_runbook_catalog.json` v2026-11-08.2 (priority 120); **do not edit this page** — run `python3 scripts/gen_self_heal_runbook_docs.py --write`. Category A · Locks & concurrency.

| | |
| --- | --- |
| Tier | `auto_notify` |
| Action | `release_stale_sqlite_wal_lock` |
| Attempts | 1 · cooldown 60 min |
| Verify | `next_run_opens_db` |
| Replay | 9 failure(s) on 1 lane(s) |

## 1. What fires it

The engine selects this entry when **any** of these holds. A `failure_class` is a lowercased set membership; a reason pattern is searched in `reason`/`failure_kind`/`detail`; an exception pattern is searched in the wider text — reason, failure kind, exception, detail, title, error and the last 4 000 characters of stderr/stdout:

- reason text matches `/(?i)database is locked/`
- reason text matches `/\bSQLITE_BUSY\b/`
- exception or tail text matches `/\bOperationalError\b.*database is locked/`

It is selected by explicit priority **120** (lowest matching priority wins; ids break ties). Should it not match, the next entry above it is `A04-pg-lock-not-available` (priority 130).

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

To replay this entry: `python3 -m pytest tests/test_self_heal_runbooks_lq1231_20261108.py -k 'A03-sqlite-database-locked' -q` plans a synthetic incident into it; `tests/fixtures/self_heal_runbooks/` is the replay corpus for the signatures seen in real receipts.

## 4. The only action it may take

`release_stale_sqlite_wal_lock`

reports only: it records `sqlite_lock_reported` and names the risk in the human steps. It never removes a `-wal` or `-shm` file.

**Parameters.** none.

**It does not:** does not remove, truncate or checkpoint a SQLite side file.

**Tier.** `auto_notify` — the fixer applies the action and posts a FINDING, so an operator sees the failure even when the action works. Use this tier when the *occurrence* is information: a timeout, a refused route, an unverifiable output.

## 5. Verification

`verify.kind = next_run_opens_db`. Verified means: the next run of the lane opened the same database without hitting `SQLITE_BUSY`.

```bash
STATE="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"
newest=$(ls -t "$STATE"/data/runtime/n8n_runs/d:<lane>:*.json 2>/dev/null | head -1)
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("state"), "|", d.get("reason"))' "$newest"
```

**Expected:** a receipt newer than the plan's `at` whose state is `RUN_DONE` and whose `reason`/stderr mention no `database is locked`/`SQLITE_BUSY`. Nothing is removed to make this true: a WAL/SHM file is never deleted.

## 6. Rollback

none — nothing was written.

## 7. Budget and cooldown

- **Attempts:** 1. At the cap the engine switches the action to `escalate_finding` with `reason: max_attempts_reached`; it does not keep trying.
- **Cooldown:** 60 min between this entry's actions on one lane.
- **Lane rate limit:** one mutating action per lane per hour. The observing actions (`noop_wait_recheck`, `escalate_finding`, `mark_weekend_expected`, `release_stale_sqlite_wal_lock`) are not rate-limited.
- **Idempotency:** the plan's key hashes the entry, lane, signature and attempt. It is stable across a day and across a restart, so applying the same plan twice is the same act.

## 8. When to escalate, and what to send

Escalate when any of these is true:

- the attempt budget is spent (1 attempts);
- a precondition refuses (`reason: precondition_failed:<check>`) — the action is not safe;
- verification still fails at the end of its window (§5);
- the tier is `human_only`: the engine escalates on the first plan by design.

The FINDING title, rendered from the catalog with the plan's values:

```text
sqlite lock persisted on <lane>
```

Send it with the receipt it was rendered from: the plan's `lane`, `signature`, `entry`, `reason`, `attempts: n/max`, `checks[]`, `idempotency_key` and the receipt path — plus what §5's command printed. A FINDING without the receipt path cannot be audited.

## 9. Human steps

1. find the writer: lsof <db path> (read-only)
2. do not delete -wal/-shm files; that is how a database is corrupted

## 10. Tests

The catalog declares these test labels (the plan requires at least three per entry: a match, a refusal on a failed precondition, and a repeat):

- `fx-sqlite-locked-match`
- `fx-sqlite-locked-refuse`
- `fx-sqlite-locked-repeat`

The mechanical evidence that they hold:

- `tests/test_self_heal_runbooks_lq1231_20261108.py` — schema, action whitelist, priorities, per-entry match, precondition refusal, repeat determinism, rate limit, dry-run default.
- no corpus fixture asserts this entry yet: the corpus covers signatures seen in receipts, and this one has not been seen in the window (its evidence is the taxonomy, not a live receipt).

```bash
python3 -m pytest tests/test_self_heal_runbooks_lq1231_20261108.py tests/test_self_heal_runbook_coverage_20261108.py -q
```

---

[Workbook index](INDEX.md) · [14-day coverage](COVERAGE.md) · [rulings behind the cells](RULINGS.md)

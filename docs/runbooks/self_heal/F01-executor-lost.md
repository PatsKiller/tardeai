# F01-executor-lost — executor_lost: the existing reaper owns the orphan; do not duplicate the effect

Generated from `config/self_heal_runbook_catalog.json` v2026-11-08.2 (priority 490); **do not edit this page** — run `python3 scripts/gen_self_heal_runbook_docs.py --write`. Category F · Scheduler / n8n plane.

| | |
| --- | --- |
| Tier | `auto` |
| Action | `noop_wait_recheck` |
| Attempts | 2 · cooldown 30 min |
| Verify | `orphan_reaped` |
| Replay | 106 failure(s) on 18 lane(s) |

## 1. What fires it

The engine selects this entry when **any** of these holds. A `failure_class` is a lowercased set membership; a reason pattern is searched in `reason`/`failure_kind`/`detail`; an exception pattern is searched in the wider text — reason, failure kind, exception, detail, title, error and the last 4 000 characters of stderr/stdout:

- failure class `executor_lost`
- reason text matches `/\bexecutor_lost\b/`
- reason text matches `/(?i)executor (was )?lost/`
- reason text matches `/(?i)lost its executor/`

It is selected by explicit priority **490** (lowest matching priority wins; ids break ties). Should it not match, the next entry above it is `E01-run-timeout-124` (priority 500).

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

To replay this entry: `python3 -m pytest tests/test_self_heal_runbooks_lq1231_20261108.py -k 'F01-executor-lost' -q` plans a synthetic incident into it; `tests/fixtures/self_heal_runbooks/` is the replay corpus for the signatures seen in real receipts.

## 4. The only action it may take

`noop_wait_recheck`

records the plan and schedules the next look at `now + wait_s`. It changes nothing on the host: no file, no lock, no process, no row. It is the action for a condition that is expected to clear itself.

**Parameters.** `wait_s` — seconds until the next re-check (default 300).

| param | value |
| --- | --- |
| `wait_s` | `600` |

**It does not:** does not re-run the lane, does not touch the lock, does not acknowledge the failure to anyone.

**Tier.** `auto` — the fixer applies the action and posts nothing while the entry still has attempts. Silence is the point: these signatures are the normal path (a held lock, a lost executor), and a message per occurrence is noise. When the attempt budget is spent the engine itself switches the action to `escalate_finding` (`reason: max_attempts_reached`), so the silence is bounded.

## 5. Verification

`verify.kind = orphan_reaped`, window 1200 s. Verified means: the orphaned run left the `RUNNING` state and its slot was re-armed or is free.

```bash
STATE="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"
sqlite3 "file:$STATE/data/governance/n8n_coordination_ledger.sqlite?mode=ro" \
  "select slot_key, state, last_reason from runs where slot_key like '%<lane>%' order by rowid desc limit 5"
```

**Expected:** the newest row is not `RUNNING`, and no row still names the orphaned run as the holder.

## 6. Rollback

none — nothing was written. The plan's receipt is the only artifact.

## 7. Budget and cooldown

- **Attempts:** 2. At the cap the engine switches the action to `escalate_finding` with `reason: max_attempts_reached`; it does not keep trying.
- **Cooldown:** 30 min between this entry's actions on one lane.
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
orphan run stayed unreaped for <lane>
```

Send it with the receipt it was rendered from: the plan's `lane`, `signature`, `entry`, `reason`, `attempts: n/max`, `checks[]`, `idempotency_key` and the receipt path — plus what §5's command printed. A FINDING without the receipt path cannot be audited.

## 9. Human steps

1. inspect the run row's state; never mark it done by hand

## 10. Tests

The catalog declares these test labels (the plan requires at least three per entry: a match, a refusal on a failed precondition, and a repeat):

- `fx-executor-lost-match`
- `fx-executor-lost-refuse`
- `fx-executor-lost-repeat`

The mechanical evidence that they hold:

- `tests/test_self_heal_runbooks_lq1231_20261108.py` — schema, action whitelist, priorities, per-entry match, precondition refusal, repeat determinism, rate limit, dry-run default.
- the replay corpus fixture(s) that assert this entry resolve here: `executor-lost.json`.

```bash
python3 -m pytest tests/test_self_heal_runbooks_lq1231_20261108.py tests/test_self_heal_runbook_coverage_20261108.py -q
```

---

[Workbook index](INDEX.md) · [14-day coverage](COVERAGE.md) · [rulings behind the cells](RULINGS.md)

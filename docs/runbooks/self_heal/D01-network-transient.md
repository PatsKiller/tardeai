# D01-network-transient — network / dependency transient: defer with jitter and retry

Generated from `config/self_heal_runbook_catalog.json` v2026-11-08.2 (priority 400); **do not edit this page** — run `python3 scripts/gen_self_heal_runbook_docs.py --write`. Category D · Network / transient.

| | |
| --- | --- |
| Tier | `auto_notify` |
| Action | `defer_until` |
| Attempts | 3 · cooldown 15 min |
| Verify | `next_attempt_succeeds` |
| Replay | 0 failures in the window |

## 1. What fires it

The engine selects this entry when **any** of these holds. A `failure_class` is a lowercased set membership; a reason pattern is searched in `reason`/`failure_kind`/`detail`; an exception pattern is searched in the wider text — reason, failure kind, exception, detail, title, error and the last 4 000 characters of stderr/stdout:

- failure class `network`
- failure class `transient`
- failure class `dependency_unavailable`
- failure class `dependency`
- reason text matches `/(?i)name resolution/`
- reason text matches `/\bgaierror\b/`
- reason text matches `/\bEAI_AGAIN\b/`
- reason text matches `/(?i)network is unreachable/`
- reason text matches `/(?i)connection reset/`
- exception or tail text matches `/\bgaierror\b/`
- exception or tail text matches `/\bConnectionResetError\b/`

It is selected by explicit priority **400** (lowest matching priority wins; ids break ties). Should it not match, the next entry above it is `D02-provider-5xx` (priority 410).

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
| `retries_today (or deferrals_today / attempts_today)` | precondition retries_under_budget: the lane has retries left today. A missing count is a refusal — 0 is a value, missing is not. |

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
- **`retries_under_budget`** proves the lane has retries left today. A missing count is a refusal — 0 is a value, missing is not. Collect: the deferral/retry count for the lane's current ET day.

To replay this entry: `python3 -m pytest tests/test_self_heal_runbooks_lq1231_20261108.py -k 'D01-network-transient' -q` plans a synthetic incident into it; `tests/fixtures/self_heal_runbooks/` is the replay corpus for the signatures seen in real receipts.

## 4. The only action it may take

`defer_until`

records `deferred` with `next_attempt_at = now + delay_s + deterministic jitter` (bounded by `jitter_s`). The jitter spreads a rate-limited fleet so the retries do not collide on the next window.

**Parameters.** `delay_s` (default 300), `jitter_s` (default 60), `max_retries` (default 3, the daily budget).

| param | value |
| --- | --- |
| `delay_s` | `120` |
| `jitter_s` | `120` |
| `max_retries` | `3` |

**It does not:** does not change the provider's quota, the budget governor or the clock.

**Tier.** `auto_notify` — the fixer applies the action and posts a FINDING, so an operator sees the failure even when the action works. Use this tier when the *occurrence* is information: a timeout, a refused route, an unverifiable output.

## 5. Verification

`verify.kind = next_attempt_succeeds`, window 900 s. Verified means: the re-run or the next scheduled slot completed, and no dead letter is left for the lane.

```bash
STATE="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"
python3 scripts/n8n_dlq.py list --lane <lane> --json
newest=$(ls -t "$STATE"/data/runtime/n8n_runs/d:<lane>:*.json 2>/dev/null | head -1)
echo "$newest"
```

**Expected:** `[]` from the dead-letter listing (nothing unreleased for the lane) and a receipt newer than `at`.

## 6. Rollback

none — nothing was written.

## 7. Budget and cooldown

- **Attempts:** 3. At the cap the engine switches the action to `escalate_finding` with `reason: max_attempts_reached`; it does not keep trying.
- **Cooldown:** 15 min between this entry's actions on one lane.
- **Lane rate limit:** one mutating action per lane per hour. The observing actions (`noop_wait_recheck`, `escalate_finding`, `mark_weekend_expected`, `release_stale_sqlite_wal_lock`) are not rate-limited.
- **Idempotency:** the plan's key hashes the entry, lane, signature and attempt. It is stable across a day and across a restart, so applying the same plan twice is the same act.

## 8. When to escalate, and what to send

Escalate when any of these is true:

- the attempt budget is spent (3 attempts);
- a precondition refuses (`reason: precondition_failed:<check>`) — the action is not safe;
- verification still fails at the end of its window (§5);
- the tier is `human_only`: the engine escalates on the first plan by design.

The FINDING title, rendered from the catalog with the plan's values:

```text
network dependency did not recover for <lane>
```

Send it with the receipt it was rendered from: the plan's `lane`, `signature`, `entry`, `reason`, `attempts: n/max`, `checks[]`, `idempotency_key` and the receipt path — plus what §5's command printed. A FINDING without the receipt path cannot be audited.

## 9. Human steps

1. resolve DNS/host reachability outside the lane; never edit /etc/hosts or a proxy env from a runbook

## 10. Tests

The catalog declares these test labels (the plan requires at least three per entry: a match, a refusal on a failed precondition, and a repeat):

- `fx-network-match`
- `fx-network-refuse`
- `fx-network-repeat`

The mechanical evidence that they hold:

- `tests/test_self_heal_runbooks_lq1231_20261108.py` — schema, action whitelist, priorities, per-entry match, precondition refusal, repeat determinism, rate limit, dry-run default.
- no corpus fixture asserts this entry yet: the corpus covers signatures seen in receipts, and this one has not been seen in the window (its evidence is the taxonomy, not a live receipt).

```bash
python3 -m pytest tests/test_self_heal_runbooks_lq1231_20261108.py tests/test_self_heal_runbook_coverage_20261108.py -q
```

---

[Workbook index](INDEX.md) · [14-day coverage](COVERAGE.md) · [rulings behind the cells](RULINGS.md)

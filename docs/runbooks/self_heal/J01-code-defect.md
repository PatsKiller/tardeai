# J01-code-defect — code defect: route to the LLM fixer with a repro; never a runbook action

Generated from `config/self_heal_runbook_catalog.json` v2026-11-08.2 (priority 1000); **do not edit this page** — run `python3 scripts/gen_self_heal_runbook_docs.py --write`. Category J · Code and data defects.

| | |
| --- | --- |
| Tier | `auto_notify` |
| Action | `escalate_finding` |
| Attempts | 1 · cooldown 0 min |
| Verify | `repro_exists` |
| Replay | 148 failure(s) on 26 lane(s) |

## 1. What fires it

The engine selects this entry when **any** of these holds. A `failure_class` is a lowercased set membership; a reason pattern is searched in `reason`/`failure_kind`/`detail`; an exception pattern is searched in the wider text — reason, failure kind, exception, detail, title, error and the last 4 000 characters of stderr/stdout:

- failure class `code_error`
- failure class `code_defect`
- reason text matches `/\bCODE_ERROR\b/`
- reason text matches `/\bAssertionError\b/`
- exception or tail text matches `/\bTraceback \(most recent call last\)\b/`
- exception or tail text matches `/\bAssertionError\b/`

It is selected by explicit priority **1000** (lowest matching priority wins; ids break ties). Should it not match, the next entry above it is `J02-test-failure` (priority 1010).

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

To replay this entry: `python3 -m pytest tests/test_self_heal_runbooks_lq1231_20261108.py -k 'J01-code-defect' -q` plans a synthetic incident into it; `tests/fixtures/self_heal_runbooks/` is the replay corpus for the signatures seen in real receipts.

## 4. The only action it may take

`escalate_finding`

renders a deterministic FINDING (`_finding_text`) from the entry's `on_fail.title`, the plan and the human steps, and records `escalation_rendered` with the text in the receipt. This is always available: it survives a spent budget, a failed precondition and any lane.

**Parameters.** none.

**It does not:** does not attempt the failure again, does not page anyone, does not write outside the receipt.

**Tier.** `auto_notify` — the fixer applies the action and posts a FINDING, so an operator sees the failure even when the action works. Use this tier when the *occurrence* is information: a timeout, a refused route, an unverifiable output.

## 5. Verification

`verify.kind = repro_exists`. Verified means: the failure is reproducible: a run after the plan failed the same way.

```bash
STATE="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"
ls -t "$STATE"/data/runtime/n8n_runs/d:<lane>:*.json 2>/dev/null | head -3
```

**Expected:** a receipt newer than the plan's `at` with the same failure state — evidence for the escalation.

## 6. Rollback

none — the FINDING is information, not a mutation.

## 7. Budget and cooldown

- **Attempts:** 1. At the cap the engine switches the action to `escalate_finding` with `reason: max_attempts_reached`; it does not keep trying.
- **Cooldown:** 0 min between this entry's actions on one lane.
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
code defect in <lane>
```

Send it with the receipt it was rendered from: the plan's `lane`, `signature`, `entry`, `reason`, `attempts: n/max`, `checks[]`, `idempotency_key` and the receipt path — plus what §5's command printed. A FINDING without the receipt path cannot be audited.

## 9. Human steps

1. run the failing command 3 times on base before believing it is code

## 10. Tests

The catalog declares these test labels (the plan requires at least three per entry: a match, a refusal on a failed precondition, and a repeat):

- `fx-code-match`
- `fx-code-refuse`
- `fx-code-repeat`

The mechanical evidence that they hold:

- `tests/test_self_heal_runbooks_lq1231_20261108.py` — schema, action whitelist, priorities, per-entry match, precondition refusal, repeat determinism, rate limit, dry-run default.
- the replay corpus fixture(s) that assert this entry resolve here: `exit-nonzero.json`.

```bash
python3 -m pytest tests/test_self_heal_runbooks_lq1231_20261108.py tests/test_self_heal_runbook_coverage_20261108.py -q
```

---

[Workbook index](INDEX.md) · [14-day coverage](COVERAGE.md) · [rulings behind the cells](RULINGS.md)

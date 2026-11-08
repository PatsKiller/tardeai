# J03-data-defect-in-input — data defect in the lane's input: escalate to the producer's owner, never patch the input

Generated from `config/self_heal_runbook_catalog.json` v2026-11-08.2 (priority 1020); **do not edit this page** — run `python3 scripts/gen_self_heal_runbook_docs.py --write`. Category J · Code and data defects.

| | |
| --- | --- |
| Tier | `auto_notify` |
| Action | `escalate_finding` |
| Attempts | 1 · cooldown 0 min |
| Verify | `human_verified` |
| Replay | 5 failure(s) on 3 lane(s) |

## 1. What fires it

The engine selects this entry when **any** of these holds. A `failure_class` is a lowercased set membership; a reason pattern is searched in `reason`/`failure_kind`/`detail`; an exception pattern is searched in the wider text — reason, failure kind, exception, detail, title, error and the last 4 000 characters of stderr/stdout:

- failure class `data_defect`
- reason text matches `/(?i)dependency_unavailable/`
- reason text matches `/(?i)label normalizes to empty/`
- reason text matches `/\bDiscoveryInboxError\b/`
- reason text matches `/(?i)no (?:source|producer)\b.*rows/`

It is selected by explicit priority **1020** (lowest matching priority wins; ids break ties). Should it not match, the next entry above it is `K01-credential-problem` (priority 1100).

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

This entry declares **no preconditions**: it fires on the signature alone. That is only safe because its action observes (or escalates) and writes nothing.

To replay this entry: `python3 -m pytest tests/test_self_heal_runbooks_lq1231_20261108.py -k 'J03-data-defect-in-input' -q` plans a synthetic incident into it; `tests/fixtures/self_heal_runbooks/` is the replay corpus for the signatures seen in real receipts.

## 4. The only action it may take

`escalate_finding`

renders a deterministic FINDING (`_finding_text`) from the entry's `on_fail.title`, the plan and the human steps, and records `escalation_rendered` with the text in the receipt. This is always available: it survives a spent budget, a failed precondition and any lane.

**Parameters.** none.

**It does not:** does not attempt the failure again, does not page anyone, does not write outside the receipt.

**Tier.** `auto_notify` — the fixer applies the action and posts a FINDING, so an operator sees the failure even when the action works. Use this tier when the *occurrence* is information: a timeout, a refused route, an unverifiable output.

## 5. Verification

`verify.kind = human_verified`. Verified means: a person confirms the condition against the evidence named in the human steps. There is no command that decides it; this is where the workbook hands over rather than pretending to verify.

```bash
(no command: the check is the human step itself)
```

**Expected:** the finding carries what the person concluded **and** the independent source they checked it against. An escalation without that pair is UNPROVEN by the audit standard, not verified.

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
the input defect for <lane> is unresolved
```

Send it with the receipt it was rendered from: the plan's `lane`, `signature`, `entry`, `reason`, `attempts: n/max`, `checks[]`, `idempotency_key` and the receipt path — plus what §5's command printed. A FINDING without the receipt path cannot be audited.

## 9. Human steps

1. the lane's input is missing, empty-keyed or too old: name the producing lane from the receipt and escalate to its owner; a runbook must never write or repair the producer's rows
2. if the producer was retired, the consuming lane needs a retirement proposal, not a data patch

## 10. Tests

The catalog declares these test labels (the plan requires at least three per entry: a match, a refusal on a failed precondition, and a repeat):

- `fx-discovery-empty-key-match`
- `fx-dependency-unavailable-match`
- `fx-data-defect-refuse`
- `fx-data-defect-repeat`

The mechanical evidence that they hold:

- `tests/test_self_heal_runbooks_lq1231_20261108.py` — schema, action whitelist, priorities, per-entry match, precondition refusal, repeat determinism, rate limit, dry-run default.
- the replay corpus fixture(s) that assert this entry resolve here: `discovery-empty-key.json`.

```bash
python3 -m pytest tests/test_self_heal_runbooks_lq1231_20261108.py tests/test_self_heal_runbook_coverage_20261108.py -q
```

---

[Workbook index](INDEX.md) · [14-day coverage](COVERAGE.md) · [rulings behind the cells](RULINGS.md)

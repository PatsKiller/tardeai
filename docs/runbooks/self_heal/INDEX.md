# Self-heal runbook workbook

Generated from `config/self_heal_runbook_catalog.json` v2026-11-08.2 and the replay snapshot `COVERAGE.json`. **Do not edit any page in this directory except `README.md`, `RULINGS.md` and `COVERAGE.json`** — regenerate with `python3 scripts/gen_self_heal_runbook_docs.py --write`.

## How to use this workbook

1. Find the signature in [COVERAGE.md](COVERAGE.md) — every failure seen in the last 14 days is a row, with the entry it plans to and its hit count.
2. Open that entry's page. It states the trigger, the evidence, the diagnosis order, the one action the fixer may take, and the command that proves the outcome.
3. If the entry is `human_only`, the page's action is **yours to run**, never the fixer's: the engine replaces it with an escalation.
4. If a signature is not in COVERAGE.md, do not improvise: it falls to `K05-unclassified-catch-all` and needs an entry of its own, or a written reason in the replay's `GATE_REASONS`.
5. [RULINGS.md](RULINGS.md) records why each disputed cell (action, tier) is what it is, so a reviewer can re-open one decision without re-reading the whole catalog.

**Window:** 2026-10-25T22:45:00+00:00 .. 2026-11-08T22:45:00+00:00 (14 days). **1028 failures** · **24 signatures** · **17 entries hit** · catch-all **0**.

## Entries by category

| Cat | Name | Entries | auto | auto_notify | human_only | 14-day hits |
| --- | --- | --- | --- | --- | --- | --- |
| **A** | Locks & concurrency | 6 | 2 | 4 | 0 | 579 |
| **B** | Quota / rate limit / LLM provider | 4 | 0 | 1 | 3 | 0 |
| **C** | Upstream data | 7 | 1 | 6 | 0 | 65 |
| **D** | Network / transient | 3 | 0 | 3 | 0 | 1 |
| **E** | Time / wall | 2 | 0 | 2 | 0 | 54 |
| **F** | Scheduler / n8n plane | 6 | 1 | 4 | 1 | 157 |
| **G** | Resources | 3 | 0 | 0 | 3 | 0 |
| **H** | Database | 5 | 1 | 2 | 2 | 7 |
| **I** | Config / registry drift | 6 | 0 | 1 | 5 | 12 |
| **J** | Code and data defects | 3 | 0 | 3 | 0 | 153 |
| **K** | Human-only | 5 | 0 | 1 | 4 | 0 |

## Every entry

| Entry | Category | Tier | Action | Attempts | Cooldown | 14-day hits | Lanes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [A01-flock-held](A01-flock-held.md) | A | `auto` | `noop_wait_recheck` | 3 | 60 min | 565 | 12 |
| [A02-stale-existence-lock](A02-stale-existence-lock.md) | A | `auto_notify` | `release_stale_flock` | 2 | 60 min | 0 | 0 |
| [A03-sqlite-database-locked](A03-sqlite-database-locked.md) | A | `auto_notify` | `release_stale_sqlite_wal_lock` | 1 | 60 min | 9 | 1 |
| [A04-pg-lock-not-available](A04-pg-lock-not-available.md) | A | `auto_notify` | `noop_wait_recheck` | 3 | 15 min | 2 | 2 |
| [A05-overlapping-schedule](A05-overlapping-schedule.md) | A | `auto_notify` | `noop_wait_recheck` | 2 | 60 min | 0 | 0 |
| [A06-effect-already-claimed](A06-effect-already-claimed.md) | A | `auto` | `noop_wait_recheck` | 2 | 60 min | 3 | 2 |
| [B01-rate-limited-429](B01-rate-limited-429.md) | B | `auto_notify` | `defer_until` | 3 | 30 min | 0 | 0 |
| [B02-oauth-expired](B02-oauth-expired.md) | B | `human_only` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [B03-budget-governor-refusal](B03-budget-governor-refusal.md) | B | `human_only` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [B04-provider-credit-exhausted](B04-provider-credit-exhausted.md) | B | `human_only` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [C01-late-data](C01-late-data.md) | C | `auto_notify` | `rerun_once_via_gateway` | 2 | 120 min | 0 | 0 |
| [C02-empty-output](C02-empty-output.md) | C | `auto` | `rerun_once_via_gateway` | 1 | 60 min | 27 | 2 |
| [C03-weekend-expected](C03-weekend-expected.md) | C | `auto_notify` | `mark_weekend_expected` | 1 | 0 min | 0 | 0 |
| [C04-no-briefs](C04-no-briefs.md) | C | `auto_notify` | `rerun_once_via_gateway` | 1 | 60 min | 0 | 0 |
| [C05-stale-source](C05-stale-source.md) | C | `auto_notify` | `noop_wait_recheck` | 2 | 60 min | 0 | 0 |
| [C06-output-unverifiable](C06-output-unverifiable.md) | C | `auto_notify` | `escalate_finding` | 1 | 0 min | 38 | 5 |
| [C07-upstream-verification-failed](C07-upstream-verification-failed.md) | C | `auto_notify` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [D01-network-transient](D01-network-transient.md) | D | `auto_notify` | `defer_until` | 3 | 15 min | 0 | 0 |
| [D02-provider-5xx](D02-provider-5xx.md) | D | `auto_notify` | `defer_until` | 3 | 15 min | 1 | 1 |
| [D03-connection-refused](D03-connection-refused.md) | D | `auto_notify` | `defer_until` | 3 | 15 min | 0 | 0 |
| [E01-run-timeout-124](E01-run-timeout-124.md) | E | `auto_notify` | `noop_wait_recheck` | 2 | 30 min | 54 | 6 |
| [E02-slow-gateway](E02-slow-gateway.md) | E | `auto_notify` | `noop_wait_recheck` | 2 | 30 min | 0 | 0 |
| [F01-executor-lost](F01-executor-lost.md) | F | `auto` | `noop_wait_recheck` | 2 | 30 min | 106 | 18 |
| [F02-bridge-route-refused](F02-bridge-route-refused.md) | F | `auto_notify` | `escalate_finding` | 1 | 0 min | 9 | 1 |
| [F03-breaker-open](F03-breaker-open.md) | F | `auto_notify` | `open_breaker_cooldown` | 1 | 15 min | 0 | 0 |
| [F04-dead-letter](F04-dead-letter.md) | F | `human_only` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [F05-restart-killed-child](F05-restart-killed-child.md) | F | `auto_notify` | `rerun_once_via_gateway` | 1 | 60 min | 0 | 0 |
| [F06-effect-no-owner](F06-effect-no-owner.md) | F | `auto_notify` | `escalate_finding` | 1 | 0 min | 42 | 9 |
| [G02-tmp-enospc](G02-tmp-enospc.md) | G | `human_only` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [G01-disk-floor](G01-disk-floor.md) | G | `human_only` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [G03-memory-pressure](G03-memory-pressure.md) | G | `human_only` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [H01-db-unreachable](H01-db-unreachable.md) | H | `auto_notify` | `defer_until` | 2 | 30 min | 0 | 0 |
| [H02-db-read-only-txn](H02-db-read-only-txn.md) | H | `human_only` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [H03-schema-missing](H03-schema-missing.md) | H | `human_only` | `escalate_finding` | 1 | 0 min | 4 | 1 |
| [H04-db-error-while-updating](H04-db-error-while-updating.md) | H | `auto_notify` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [H05-db-connection-closed](H05-db-connection-closed.md) | H | `auto` | `noop_wait_recheck` | 2 | 30 min | 3 | 2 |
| [I01-duplicate-registry-row](I01-duplicate-registry-row.md) | I | `human_only` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [I02-lane-missing-from-registry](I02-lane-missing-from-registry.md) | I | `human_only` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [I03-contract-missing](I03-contract-missing.md) | I | `human_only` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [I05-env-names-missing](I05-env-names-missing.md) | I | `human_only` | `escalate_finding` | 1 | 0 min | 6 | 1 |
| [I04-invalid-config-json](I04-invalid-config-json.md) | I | `human_only` | `escalate_finding` | 1 | 0 min | 6 | 2 |
| [I06-log-path-not-a-directory](I06-log-path-not-a-directory.md) | I | `auto_notify` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [J01-code-defect](J01-code-defect.md) | J | `auto_notify` | `escalate_finding` | 1 | 0 min | 148 | 26 |
| [J02-test-failure](J02-test-failure.md) | J | `auto_notify` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [J03-data-defect-in-input](J03-data-defect-in-input.md) | J | `auto_notify` | `escalate_finding` | 1 | 0 min | 5 | 3 |
| [K01-credential-problem](K01-credential-problem.md) | K | `human_only` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [K02-broker-orders](K02-broker-orders.md) | K | `human_only` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [K03-data-correction](K03-data-correction.md) | K | `human_only` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [K04-audit-block](K04-audit-block.md) | K | `human_only` | `escalate_finding` | 1 | 0 min | 0 | 0 |
| [K05-unclassified-catch-all](K05-unclassified-catch-all.md) | K | `auto_notify` | `escalate_finding` | 1 | 0 min | 0 | 0 |

## The action whitelist

No other action is executable by the fixer, and mutating actions are refused on execution lanes before the catalog is consulted.

- `defer_until` — records `deferred` with `next_attempt_at = now + delay_s + deterministic jitter` (bounded by `jitter_s`).
- `escalate_finding` — renders a deterministic FINDING (`_finding_text`) from the entry's `on_fail.title`, the plan and the human steps, and records `escalation_rendered` with the text in the receipt.
- `mark_weekend_expected` — records `expected_window_marked`: the receipt says the window is expected (weekend / market holiday / closed calendar), so a later reader does not count it as an unexplained failure.
- `noop_wait_recheck` — records the plan and schedules the next look at `now + wait_s`.
- `open_breaker_cooldown` — records `cooldown` with `next_attempt_at = now + cooldown_s`, so the lane is not re-attempted while the breaker is open.
- `release_stale_flock` — **the only action that writes to the host.** With `--apply`, and only after the plan's preconditions held, it re-probes the lock non-blockingly and re-checks the path against the never-touch list; if the lock is still free it renames the file to `<name>.stale-<UTC stamp>`.
- `release_stale_sqlite_wal_lock` — reports only: it records `sqlite_lock_reported` and names the risk in the human steps.
- `rerun_once_via_gateway` — records `rerun_requested` with `via: coordination_gateway` and `next_attempt_at = now + delay_s`.

## Regenerating

```bash
python3 scripts/ops/self_heal_runbook_replay.py --as-of <UTC instant> --window-days 14 \
    --out docs/runbooks/self_heal/COVERAGE.json --check-gate
python3 scripts/gen_self_heal_runbook_docs.py --write
python3 -m pytest tests/test_self_heal_runbook_docs_20261108.py -q
```

The replay is dry: it calls no action, writes no receipt and touches no lane.

# Self-heal runbook replay corpus (SYNTHETIC)

One JSON file per mined failure signature with `count_30d >= 2` (22 at 2026-11-08): `<signature_id>.json`.
Every value is synthetic. This repo is public: no real tickers, holdings, hosts, personal paths, accounts or tokens.
Taxonomy text is sanitized (`<SYM>`, `/example/...`, `synthetic_*`) before it goes in `taxonomy_signature`.

Source of the rows: SELFHEAL-FAILURE-TAXONOMY-20261108.json (LQ-1237, 35 rows; 22 at count_30d >= 2).
Categories and actions: SELFHEAL-BEST-PRACTICE-PLAN-20261108.md, RUNBOOK CATALOG.

## Schema (enforced by `tests/test_self_heal_runbook_coverage_20261108.py`)

| key | type | meaning |
|---|---|---|
| `fixture_id` | str | equals the file stem |
| `signature_id` | str | kebab slug, unique per fixture |
| `taxonomy_signature` | str | sanitized copy of the taxonomy row's signature |
| `count_30d` | int | the taxonomy row's count; must be >= 2 |
| `category` | str | one of A..K |
| `synthetic` | bool | must be `true` |
| `receipt` | object | receipt-shaped input: `lane_id`, `exit_code`, `status`, `reason`, `exception`, `failure_class`, `ts_et` |
| `expect.classified` | bool | must be `true` |
| `expect.category` | str | equals `category` |
| `expect.entry_id` | str | `<category letter>-<kebab slug>` (the catalog id the engine must return) |
| `expect.action` | str | one of the whitelist: noop_wait_recheck, rerun_once_via_gateway, defer_until, release_stale_flock, release_stale_sqlite_wal_lock, open_breaker_cooldown, mark_weekend_expected, escalate_finding |
| `expect.tier` | str | auto, auto_notify or human_only |

## Expected catalog entries (for LQ-1231 to match)

| entry_id | action | tier | fixtures |
|---|---|---|---|
| A-flock-held-wait-recheck | noop_wait_recheck | auto | flock-held-skip, flock-skipped-pid-running |
| A-effect-already-claimed | noop_wait_recheck | auto | effect-already-claimed |
| C-empty-output-recheck | noop_wait_recheck | auto | empty-output |
| C-output-unverifiable | escalate_finding | auto_notify | output-unverifiable |
| C-upstream-verification-failed | escalate_finding | auto_notify | upstream-verification-failed |
| E-run-timeout | escalate_finding | auto_notify | timeout-exit-124, setup-step-timeout |
| F-executor-lost-after-restart | escalate_finding | auto_notify | executor-lost |
| F-effect-no-owner | escalate_finding | auto_notify | effect-no-owner |
| F-bridge-route-refused | rerun_once_via_gateway | auto | bridge-route-refused-a, bridge-route-refused-b |
| G-disk-full-lock-file | escalate_finding | human_only | lock-file-no-space, lock-file-dryrun-no-space |
| H-schema-missing-migration | escalate_finding | human_only | schema-table-missing |
| H-db-error-escalate | escalate_finding | auto_notify | db-error-while-updating |
| H-db-connection-closed-recheck | noop_wait_recheck | auto | rollback-connection-closed |
| I-log-path-not-a-directory | escalate_finding | auto_notify | log-path-not-a-directory |
| I-env-names-missing | escalate_finding | human_only | env-names-missing |
| J-code-defect-to-fixer | escalate_finding | auto_notify | exit-nonzero, json-decode-error, discovery-empty-key |

Mapping notes:
- The taxonomy proposes `A` for `safe_flock: log path component is not a real directory`. It is a config path
  defect, so the corpus uses `I`.
- The plan puts `BRIDGE_ROUTE_REFUSED` under `F` (scheduler/n8n plane), not `B`, so both bridge fixtures use `F`.
- `J` rows are code defects: the action is an escalation that routes to the LLM fixer, never a runbook action.

## Replay

`tests/test_self_heal_runbook_coverage_20261108.py` replays every fixture through `plan_runbook()` in
`scripts/lib/self_heal_runbooks.py` with, per fixture, three inputs built by the harness:

- `evidence` -- the fixture's `receipt`, plus `lane` (= `receipt.lane_id`) and `signature` (= `signature_id`);
- `contract` -- a synthetic lane contract: `timeout_s 1800`, `freshness_failed_after_h 26`;
- `now` -- a **fixed clock** (2026-11-08T17:00Z). The plan's deferral, jitter, cooldown and idempotency key all
  depend on it, so a replay that read the wall clock would prove something different every hour.

The replay reads no taxonomy and no live coordination store; the corpus is self-contained (the schema test checks
`count_30d >= 2` on every fixture).

It resolves all 22 fixtures to a definite plan in the catalog and prints each fixture's `expect` beside the engine's
answer. The two are **reported**, not reconciled here: the `entry_id` column above was written before the catalog
landed and uses `<letter>-<slug>`, while the catalog ids are `<letter><NN>-<slug>`; a few `action`/`tier` cells also
disagree with the catalog's choice. Each disagreement is listed per fixture in
`DONE-LQ-20261107-1256-cc-deepseek-8.md` and belongs to the catalog owner (LQ-1231) or to a reviewed corpus change,
never to a silent edit on one side.

Signatures the catalog cannot classify yet fall to the catch-all; they are pinned as a ceiling
(`CATALOG_GAPS_20261108`) that a new unclassified signature fails and a closed gap may shrink.

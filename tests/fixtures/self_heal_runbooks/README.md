# Self-heal runbook replay corpus (SYNTHETIC)

One JSON file per mined failure signature with `count_30d >= 2` (22 at 2026-11-08): `<signature_id>.json`.
Every value is synthetic. This repo is public: no real tickers, holdings, hosts, personal paths, accounts or tokens.
Taxonomy text is sanitized (`<SYM>`, `/example/...`, `synthetic_*`) before it goes in `taxonomy_signature`.

Source of the rows: SELFHEAL-FAILURE-TAXONOMY-20261108.json (LQ-1237, 35 rows; 22 at count_30d >= 2).
Categories and actions: SELFHEAL-BEST-PRACTICE-PLAN-20261108.md, RUNBOOK CATALOG.
Catalog ids, actions and tiers: `config/self_heal_runbook_catalog.json` v2026-11-08.2, with the
reviewed decisions in `docs/runbooks/self_heal/RULINGS.md`.

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
| `expect.entry_id` | str | `<category letter><NN>-<kebab slug>` — the catalog id the engine must return |
| `expect.action` | str | one of the whitelist: noop_wait_recheck, rerun_once_via_gateway, defer_until, release_stale_flock, release_stale_sqlite_wal_lock, open_breaker_cooldown, mark_weekend_expected, escalate_finding |
| `expect.tier` | str | auto, auto_notify or human_only |

## Expected catalog entries

Every cell below is the **catalog's** answer as of v2026-11-08.2, and the replay asserts it
(`test_replay_resolves_every_fixture_to_a_definite_plan`). A disagreement is a test failure, not a printed note.

| entry_id | action | tier | fixtures |
|---|---|---|---|
| A01-flock-held | noop_wait_recheck | auto | flock-held-skip, flock-skipped-pid-running |
| A06-effect-already-claimed | noop_wait_recheck | auto | effect-already-claimed |
| C02-empty-output | rerun_once_via_gateway | auto | empty-output |
| C06-output-unverifiable | escalate_finding | auto_notify | output-unverifiable |
| C07-upstream-verification-failed | escalate_finding | auto_notify | upstream-verification-failed |
| E01-run-timeout-124 | noop_wait_recheck | auto_notify | timeout-exit-124, setup-step-timeout |
| F01-executor-lost | noop_wait_recheck | auto | executor-lost |
| F02-bridge-route-refused | escalate_finding | auto_notify | bridge-route-refused-a, bridge-route-refused-b |
| F06-effect-no-owner | escalate_finding | auto_notify | effect-no-owner |
| G01-disk-floor | escalate_finding | human_only | lock-file-no-space, lock-file-dryrun-no-space |
| H03-schema-missing | escalate_finding | human_only | schema-table-missing |
| H04-db-error-while-updating | escalate_finding | auto_notify | db-error-while-updating |
| H05-db-connection-closed | noop_wait_recheck | auto | rollback-connection-closed |
| I04-invalid-config-json | escalate_finding | human_only | json-decode-error |
| I05-env-names-missing | escalate_finding | human_only | env-names-missing |
| I06-log-path-not-a-directory | escalate_finding | auto_notify | log-path-not-a-directory |
| J01-code-defect | escalate_finding | auto_notify | exit-nonzero |
| J03-data-defect-in-input | escalate_finding | auto_notify | discovery-empty-key |

Mapping notes:
- The taxonomy proposes `A` for `safe_flock: log path component is not a real directory`. It is a config path
  defect, so the corpus uses `I` and the catalog entry is `I06`.
- The plan puts `BRIDGE_ROUTE_REFUSED` under `F` (scheduler/n8n plane), not `B`, so both bridge fixtures use `F`.
- `J` rows are code defects: the action is an escalation that routes to the LLM fixer, never a runbook action.
- `json-decode-error` moved from `J` to `I` with its entry (`I04`): invalid config JSON is a config defect a human
  fixes. Fixture `category` and `expect.category` are both `I`. See RULINGS.md R5.
- `empty-output` now re-runs once through the gateway (`auto`) instead of escalating; `executor-lost` and
  `flock-held-skip` are `auto` (a normal skip/loss must not notify). See RULINGS.md R1–R3.

## Replay

`tests/test_self_heal_runbook_coverage_20261108.py` replays every fixture through `plan_runbook()` in
`scripts/lib/self_heal_runbooks.py` with, per fixture, three inputs built by the harness:

- `evidence` -- the fixture's `receipt`, plus `lane` (= `receipt.lane_id`) and `signature` (= `signature_id`);
- `contract` -- a synthetic lane contract: `timeout_s 1800`, `freshness_failed_after_h 26`;
- `now` -- a **fixed clock** (2026-11-08T17:00Z). The plan's deferral, jitter, cooldown and idempotency key all
  depend on it, so a replay that read the wall clock would prove something different every hour.

The replay reads no taxonomy and no live coordination store; the corpus is self-contained (the schema test checks
`count_30d >= 2` on every fixture).

It resolves all 22 fixtures to a definite plan and **asserts** each fixture's expectation against the engine's
answer: 22/22 resolve, 22/22 match. The expectation is the corpus's specification — the reviewed rulings that put
these cells where they are live in `docs/runbooks/self_heal/RULINGS.md`.

`CATALOG_GAPS_20261108` is **empty**: no fixture reaches `K05-unclassified-catch-all`. It stays a ceiling, not an
allowance — a new unclassified signature fails the test, and closing a gap is the only direction it may move.

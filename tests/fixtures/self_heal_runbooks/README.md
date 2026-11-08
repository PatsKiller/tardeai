# Self-heal runbook replay corpus (SYNTHETIC)

One JSON file per mined failure signature: `<signature_id>.json`. Every value is synthetic. This repo is public:
no real tickers, holdings, hosts, paths outside the repo, accounts or tokens.

Schema (enforced by `tests/test_self_heal_runbook_coverage_20261108.py`):

| key | type | meaning |
|---|---|---|
| `fixture_id` | str | equals the file stem |
| `signature_id` | str | the id in SELFHEAL-FAILURE-TAXONOMY-20261108.json (count >= 2) |
| `category` | str | one of A..K (SELFHEAL-BEST-PRACTICE-PLAN-20261108.md, RUNBOOK CATALOG) |
| `synthetic` | bool | must be `true` |
| `receipt` | object | receipt-shaped input: `lane_id`, `exit_code` (int), `status`, `reason`, `exception` (str or null), `failure_class`, `ts_et` (`YYYY-MM-DDTHH:MM`) |
| `expect` | object | `classified` (bool, must be true), `entry_id` (str or null; null until the catalog names it), `tier` (null, `auto`, `auto_notify`, `human_only`) |

The file is filled once LQ-1237 (mining, taxonomy) and LQ-1231 (catalog, engine) land. Until then only the schema
exists and the coverage test skips with the reason shown.

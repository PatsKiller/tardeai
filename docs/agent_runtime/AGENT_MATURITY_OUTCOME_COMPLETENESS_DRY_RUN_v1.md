# Agent Maturity Outcome Completeness Dry Run v1

Status: OPERATOR_DATA_REQUIRED for production datasets.

The dry-run analyzer is implemented in `scripts/agent_runtime/outcome_completeness_dry_run.py` and `scripts/agent_runtime/maturity_observability.py`.

It reports:

- source dataset;
- time range;
- record count;
- records with outcome;
- records missing outcome;
- records missing immutable source ID;
- records missing decision timestamp;
- records missing outcome timestamp;
- records missing agent/model provenance;
- records missing prompt/version/hash;
- excluded records and reasons;
- candidate derived records;
- conflicts or duplicates;
- estimated sample-size impact.

Every candidate derived record carries:

- source IDs;
- original timestamps;
- derivation version;
- `dry_run: true`;
- `write_attempted: false`.

No historical backfill is implemented by this task. No production table mutation is allowed by the analyzer.

## Fixture Result

With no sanitized input records, the analyzer reports `source_dataset: NOT_AVAILABLE`, `record_count: 0`, and an `OPERATOR_DATA_REQUIRED` exclusion. This is the expected clone-safe behavior.

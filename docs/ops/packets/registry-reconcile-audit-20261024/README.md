# Registry reconciliation evidence packet

Status: DRAFT — read-only evidence; live-input explanation and source action remain BLOCKED
as_of: 2026-10-24T04:18:00Z
Design-Task: DSN-20261024-registry-reconcile-P1-T31

This packet accompanies [the audit](../../REGISTRY_RECONCILE_SEMANTIC_AUDIT_20261024.md). It contains observations of frozen source trees, not a proposed registry patch or an authority change.

| File | Meaning |
|---|---|
| `main8b24-replay.json` | Explicit committed-Oct09-snapshot replay on fresh main;676 rows,0 semantic or byte changes |
| `batch14-replay.json` | Same replay on batch14@3693b3d2;677 rows,0 semantic or byte changes |
| `canonical-replay.json` | Same replay on canonical d0c8b70d8;676 rows,0 semantic or byte changes |
| `canonical-replay-tests.txt` | Existing fixture replay suite,33 tests passing with psycopg2 hidden |
| `OPERATOR_CAPTURE.md` | Exact four-hour read-only grant/capture packet for missing default-host inputs; not executed |
| `SHA256SUMS` | Frozen file digests; excludes itself |

Each replay receipt records source/input hashes, original and candidate registry hashes, complete changed-lane/top-level lists, ID additions/removals, order equality, text diff counts and problem lists. All three changed sets are empty and hashes match. The historical snapshot's446 cron lines and140 units are historical inputs, not newly measured host counts. Capture times in that snapshot are not current observations.

Reproduction from an immutable checkout uses the existing source-only interface, not the default live census:

```bash
PYTHONPATH=/home/johnclaw/.cache/rtc/nopg \
  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python \
  scripts/reconcile_lane_registry.py --dry-run --json \
  --snapshot-in docs/implementation/n8n-maturity/data/scheduler_snapshot_20261009.json

PYTHONPATH=/home/johnclaw/.cache/rtc/nopg \
  /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python \
  -m pytest -q tests/test_n8n_maturity_registry_reconcile_20261009.py
```

The receipt-generation probe was held in `/home/johnclaw/.cache/rtc/codex-registry-audit-20261024/case.py`; it called `reconcile()` in memory, compared all per-lane/top-level fields and dumped bytes, and blocked census/subprocess/socket-create-connection calls. It did not invoke `--write` or mutate any input. No new application/fixture test file was introduced.

The report's approximately70+/96- live-input diff remains NOT_MEASURED until its exact original inputs or an authorized newly named capture are supplied. These receipts must not be cited as evidence that the live drift was fixed.

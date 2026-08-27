# Workflow Acceptance Harness

This harness is local, deterministic, and side-effect free. It exercises the
append-only lineage projection with a sanitized workflow and does not invoke a
provider, scheduler, broker, Telegram, or production store.

The assertions cover:

- event/entity/materiality/research/specialist/CIO/notification/checkpoint IDs;
- reconstruction after creating a new reader instance;
- 100 identical semantic replays with no new records;
- a material change receiving a distinct product identity;
- timestamp cutoffs excluding future nodes;
- explicit `UNRESOLVED_LINK`/`PARTIAL` records instead of phantom edges;
- `READ_ONLY_ADVISORY` authority on every persisted row.

Run with:

```bash
python -m pytest -q tests/test_r20_r24_workflow_acceptance_harness.py
```

Evidence class is `DRY_RUN`; these tests are not production or natural-current
evidence.

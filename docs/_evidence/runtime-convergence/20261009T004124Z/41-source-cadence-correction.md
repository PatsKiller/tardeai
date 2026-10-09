# N1 scheduler intent and cadence source correction

Status: SOURCE_ONLY correction; production acceptance remains NO_GO.
as_of: 2026-10-09T02:25:00Z. Source base after latest-main integration: f8749580b (PR1541).

Independent host receipts, workflow census and crontab observations in 38-runtime-independent-inspection.json prove that a peer retired four legacy cron entries around 02:01Z. Served CURRENT 4673f135f still declares those four entries as cron. Peer PR1542 head a9b8bb8546430d28bf412f111cf714c854d75903 declares n8n ownership, but three supplied cadence values contain approximately 5.2KB / 337 fields and control characters from shell expansion. A peer merged it at 2026-10-09T02:22:23Z as 4d7753c121a0fd9824406397488294687d40388d after existing CI passed. Parent did not perform that merge or consume the peer's grants; the malformed registry is an observed main-source defect until the correction is merged.

The source registry is reconciled directly against measured workflow IDs and original schedules:

| Lane | Observed active workflow | Original / corrected cadence |
|---|---|---|
| crontab-snapshot-for-health-agent | c0d4c7845e5c4fcc | */20 * * * * |
| n8n-pilot-dispatch | 078e8fcbea0c5020 | */15 * * * * |
| n8n-incident-fanin | 722fac0e043ea5c4 | */5 * * * * |
| n8n-research-intake-consumer | 21fd15d5f8a4c4da | */15 * * * * |

This records actual scheduler ownership, not approval or proof of the cutover. Registry state_reason explicitly retains **N1 NO_GO**. Consumer descriptions point to existing host reader paths; they do not assert a consumed receipt. Existing owner, output signals, expected freshness, match and financial authority remain unchanged. Malformed immutable CutoverReceipt files remain intact; this document is superseding correction evidence, not a rewritten receipt.

Two source guards prevent recurrence: the cutover CLI refuses invalid or altered cadence before mutation, and lane registry validation checks a supplied n8n cadence. Registered negative tests cover malformed values and cadence fidelity. Registry validation prior-defect command `.venv/bin/python -m pytest tests/test_lane_registry_n8n_kind_20261008.py -k 'provided_cadence or valid_recurring or omit_scheduler' -q --tb=no` failed 13 malformed cases while 7 valid/compatibility cases passed (13 deselected, 0.37s). The combined five-file registry/cutover/drift/W1 suite then passed 123 checks in 9.56s. These are the independent source reviewer's TEST_ONLY tool receipts. Existing source formatter debt is unchanged; edited tests are formatted, lint and compilation passed. Final test logs, source SHA and exact-current rollout receipts are recorded by the parent when complete.

Runtime acceptance gaps remain: insufficient two natural post-final-fix shadow fires; incident's only pre-cutover current live canary skipped the lock; snapshot's original legacy line had no shared lock; weekly maturity canary remains outstanding. No new host scheduler cutover is authorized by this source correction. Restore a previous approved immutable release through canonical rollback if deployment validation fails; do not reactivate legacy cron while live n8n ownership remains enabled.

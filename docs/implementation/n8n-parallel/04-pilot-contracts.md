# Five muted pilot contracts

Dated 2026-10-07. No n8n workflow was created. No live send was made. Cron and systemd still own the lanes.

`scripts/lib/n8n_pilot_contracts.py` still refuses a send, a provider charge, a syslog line as a morning-brief receipt, a holdings ledger whose mode is not holdings, an unmuted material digest, a non-numeric LLM amount, and an approval signal that is only the package-ledger mtime. The served-schema fixtures in the test use those same refusals with synthetic ids. They are not copies of live rows.

`scripts/lib/n8n_pilot_compare.py` labels one event, one artifact, and one consumer. A green execution with no artifact is `UNCONSUMED` and is not a receipt. Missing cost, latency math, and natural opportunities are `NOT_MEASURED`. An expected-silent artifact is `EXPECTED_SILENT`. Two natural fires per lane were not observed, because the shadow workflows are not installed and this commit is not served.

| Pilot | Contract result in tests | Natural fire | Consumer |
| --- | --- | --- | --- |
| morning-brief-0730 | syslog line is not a receipt; send blocked | NOT_MEASURED | NOT_MEASURED |
| research-scheduler-holdings | wrong mode refused; holdings without a run or a typed refusal refused | NOT_MEASURED | NOT_MEASURED |
| material-change-digest | unmuted notifier refused | NOT_MEASURED | NOT_MEASURED |
| llm-spend-report-daily | provider charge refused | NOT_MEASURED | NOT_MEASURED |
| approval-package-reminder | ledger mtime refused; run receipt without a consumer is `ARTIFACT_WRITTEN` | NOT_YET_DUE on the served tree | DELIVERY_UNMEASURED |

Shadow workflows stay BLOCKED_POLICY until the secret ADR is accepted and a workflow can run without retaining a seed or a bearer claim. A green canvas with no artifact would still be `ARTIFACT_WRITTEN` or `UNCONSUMED`, not ownership transfer.

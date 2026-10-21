# Change and release log — 2026-10-21

**Status:** PR #1887 OPEN / CLEAN (mergeable) at exact head 641e3a23; all required and non-skipped hosted checks passed. No merge/deployment.
**Updated:** 2026-10-21 03:48 UTC

| Change | Reason / expected impact | Validation | Release status |
|---|---|---|---|
| Communications ready-three candidate, merge 641e3a23c7eb1fea6df2615450657af02415949a (parents ee7bd4f… and ef085ce…). | Reconcile communications health truth and stuck-delivery reporting. | Local backend 31/31; frontend projection 21/21; frontend build/guards passed; independent static reconciliation approved. All required and non-skipped exact-head hosted checks passed as listed in TEST_RESULTS.md. | Pushed exact PR head, OPEN / CLEAN (mergeable); not merged/deployed/live. Current docs edits are not in pushed SHA. |
| Production main #1888 identity ef085ce76be4512da71a58e65ef4feb25d156206. | Current released baseline observed during this review. | Build metadata GET and aggregate communications GET; see [live validation](LIVE_VALIDATION.md). | Live baseline; does not include ready-three behavior. |
| Indicator non-finite JSON remediation, separate branch fix/indicator-json-nonfinite-20261021 at 0b5ff40692b739bd6135c4776eae11e8dcab2ae0 (parent 3828695f). | Normalize NaN/Infinity to strict JSON null in both indicator database writers. | Author suite 45 related tests in 11.31s; independent review 9/9 including np.longdouble edge and Fraction/NumPy serialization; Ruff, format, py_compile, diff, secret scan passed. | Pushed as separate PR #1889; hosted exact-head checks, including isolated PG shard, running as of 03:45 UTC. No local DB/runtime integration or host DB access; not merged/deployed and not part of PR #1887. |
| Dated operational evidence dossier. | Preserve verifiable status, incomplete tests, risks, and release gates without rewriting historical evidence. | Markdown review, SOP evidence integrity, and generated docs index checks passed. | Documentation candidate only. |

## Pending evidence and release events

- Exact-head hosted CI for 641e3a23: all required and non-skipped checks passed, including cio-hardening (10m56s); cio-hardening-full and main-red-alert skipped by PR-event rules. See TEST_RESULTS.md.
- PR remains OPEN / CLEAN (mergeable); no merge or deployment. Any release requires separate exact-SHA authority and deployment/production lease.
- Merge of ready-three candidate: not evidenced.
- Authorized deployment and post-deployment verification: not evidenced.
- Rollback: not invoked.
- C3 runtime wiring: incomplete; C3 rows remain PAUSED/off.

Historical CI and release manifests remain historical records. This log does not replace or retroactively amend them.


## Follow-up evidence — 2026-10-21 03:47 UTC

PR #1889 hosted run 39540242917 remained in progress; integrity rails failed due to a newly added test missing from `GATES`, while inherited unlisted baseline 921 was unchanged. The isolated PostgreSQL shard passed. Local fix `8d14cb07f1b161ad2509a34e7d7d8e98ce6b49bf` adds coverage guard `NEW=0`; focused tests: 7 passed, 2 skipped. At this first follow-up observation the fix was unpushed pending exact guard validation; the 03:47:45 UTC entry below supersedes that status. The hosted run applies to prior SHA `0b5ff406…`, not the correction. No production change, merge, or deployment occurred. Live state has not been freshly audited since 03:42:26 UTC.


### Superseding status — 2026-10-21 03:47:45 UTC

Coverage correction `8d14cb07f1b161ad2509a34e7d7d8e98ce6b49bf` was pushed to PR #1889 after exact push grant activation/consumption. Hosted CI restarted on exact SHA 8d14cb07 at 03:47:45 UTC and is pending. Prior run 39540242917 on 0b5ff406 remains the coverage failure RCA (new test omitted from `GATES`; PG shard passed). No merge, deployment, or production change.

# WP-33 item 3: receipt-window fix and lane revalidation

Status: DRAFT — timestamp fix verified locally; exact-head CI, deployment and new natural acceptance pending
as_of: 2026-10-24T03:15:32Z
Measured at: main `325ff34f2b3b272090b78d5210a2847c8c30bd2a`
Design-Task: DSN-20261023-handoff-v3-P7-T333

The registry lane's latest producer success does **not** establish host acceptance. Its matching immutable receipt and coordination row reproduce the reported `output_unverifiable` failure. Enrichment's latest matching run is accepted, although four historical non-successes remain. This review fixes the registry producer's execution timestamp; it changes no admission, stage, contract review, schedule or output-verification tolerance.

## Exact run correlation

The coordination SQLite database was opened using URI `mode=ro` and `PRAGMA query_only=ON` (read back as `1`). Only the two lanes' selected rows and sanitized receipt fields were collected. No credential-based database, live script, crontab, Docker, workflow API or host-service request was used. The sanitized snapshot is `/home/johnclaw/.cache/rtc/codex-wp33i3-20261023/runtime-correlation.json`.

| Lane | Exact run | Producer | Matching host acceptance |
|---|---|---|---|
| registry-runtime-truth | `d:registry-runtime-truth:live:20261023T0720` | `ok`, produced 1, exit 0 | **RUN_FAILED**, `output_unverifiable`; `receipt_outside_attempt_window` |
| watchlist-enrichment-sweep | `d:watchlist-enrichment-sweep:live:20261023T1630` | `ok`, attempted/produced 158, exit 0 | **RUN_DONE**, verdict `produced`; 220.870 s |

The mutable last files use `LaneRunReceipt@v1` with `output_fields=LaneRunReceipt@v2`; their immutable attempt files are actual `LaneRunReceipt@v2` documents. The output consumer reads the immutable attempt, not the mutable last file's status alone.

Source identities correlate without assuming current main was deployed:

- Registry receipt/host SHA: `f7c1e96cbcab399082de186e6367fa834df48e1c`. Its producer file is byte-identical to the audit base before this fix (SHA-256 `e970c90b755959b7392a150eb24539196dd0796c28d4afc95873939fa448f257`).
- Enrichment receipt/host SHA: `c04a09498d7d42554a0c3fa4681f874712c7326a`. Its producer file is byte-identical to the audit base (SHA-256 `b51e0f01f2fe9acd985f282cf74458a2f47e81b43e7b68b83927609675eaeef8`).
- Registry immutable receipt SHA-256: `da42de5083b62590e9c9e134108d09aafbfa7a5ffa54a80e62db210e5cd79e96`.
- Enrichment immutable receipt SHA-256: `be277687639a27f3b5f6f7b937dcd36cbab00124a5c35a4fd395a499a518bd5b`.

## Registry root cause and fix

The matching registry host attempt starts at `11:20:04.215703Z`. The producer records `started_at=11:20:04Z` after rounding its report observation clock down to a whole second; it finishes at `11:20:04.474448Z`, within the host's completion boundary of `11:20:04.533648Z`. The consumer correctly rejects the rounded start because it precedes the independently recorded attempt.

The producer now captures the real aware execution start, including microseconds, at entry to `main`. Receipt timing uses that value. The report's rounded/injected observation clock, fingerprint behavior and contradiction semantics remain unchanged. This also keeps a fixture `--now` value from becoming a fabricated execution start. The strict consumer's time, attempt, mode, run and full-SHA checks remain intact.

The new regression runs the producer against isolated fixture repo/ledger/receipt paths, then calls the real post-spawn `apply_output_verdict` with an independent fractional host window and matching run/SHA. It fails on the old source, passes after the fix, and deliberately reinstates the rounded start to prove the consumer still rejects it. Existing tests keep the wrong-SHA/stale/future/mode/attempt and fatal-skip boundaries.

`tests/test_registry_runtime_truth_20261018.py`, `tests/test_n8n_output_contract_truth_20261018.py` and `tests/test_lane_useful_output_proof_20261016.py` pass **117 tests**. The modified regression remains covered by its existing canonical `registry_runtime_truth_20261018` CI gate; no configuration edit was required. Receipts: `before.xml`/`.log` and `after.xml`/`.log` under the snapshot directory. Lint, whitespace and generated INDEX checks pass.

The seven-day retained registry population contains three live rows, all RUN_FAILED. Their history is preserved; this source change does not turn them into accepted runs. A fresh natural run after deployment must establish the new start time, exact deployed SHA, matching immutable receipt, RUN_DONE and produced verdict.

## Enrichment and unresolved findings

The retained seven-day enrichment population is **76 RUN_DONE and 4 RUN_TIMEOUT**. The latest accepted run's 220.870 s is below the configured 900 s timeout. Existing source already has a 600 s loop budget and typed `deadline_deferred` output; fixtures verify its budget propagation and completed-batch behavior. No new enrichment fix is justified by the latest accepted run alone.

| Historical request (UTC) | Duration | Recorded reason |
|---|---:|---|
| 2026-10-22 13:00:05 | 900.163 s | `timeout_exit_124` |
| 2026-10-22 15:00:05 | 780.886 s | `executor_lost` |
| 2026-10-23 13:30:06 | 806.287 s | `executor_lost` |
| 2026-10-23 16:00:06 | 422.986 s | `executor_lost` |

Those rows remain an operational gap. This review does not establish why an executor was lost or why the one actual 900 s overrun occurred; no host/service probes or producer run was authorized here. Per-request counts are retained-request accounting, not an expected-fire SLO or independent proof of all 158 business records. The n8n execution database and downstream business consumers were not independently queried.

The registry's completed report itself contains **51 contradictions**: 4 `ACTIVE_CRON_LINE_ABSENT`, 29 `CONTRACT_STAGE_MISMATCH`, 13 `DECLARED_OFF_CRON_LINE_ACTIVE` and 5 `LIVE_LIST_REGISTRY_NOT_LIVE`. Its receipt says a DIGEST intent was queued (`ci-d6fab7c2cd0bc1e73df18372`); delivery was not independently established. Produced count 1 means the report completed, not that registry/runtime state is clean.

The coordinator should retain the registry failure item until new deployed acceptance, qualify the enrichment item with its accepted latest run and four unresolved historical failures, and track the 51 contradictions separately. No promotion or historical acceptance is inferred. Exactly one `PUSH_NEEDED` event supplies the source-fix publication command; the worker retains its claim and the coordinator owns merge/release.

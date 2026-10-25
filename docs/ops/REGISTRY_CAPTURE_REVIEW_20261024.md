# Registry reconciliation: actual-capture review proposals

Status: PROPOSED — review packet only; operative registry unchanged by this task
as_of: 2026-10-24T04:53:19Z
Design-Task: DSN-20261024-registry-reconcile-P2-T1

The operator-supplied cron capture now explains the previously unmeasured drift. Its SHA-256 is `b2097df25a62e6824b6e7046d55a3f279b9b058e76b1bcd09c2da89b5a748626`, verified before use. A read-only in-memory replay against frozen registry `0764cad27840f7e3de2af7e77f2d921d256925d2` produces **77 added / 103 removed lines, affecting 13 IDs and 177 JSON leaves**. This is the newly measured proposal, not a claim that an earlier unretained70/96 diff had identical inputs.

The replay holds the committed October9 **unit** snapshot fixed. No current unit capture was supplied, so this is a cron-input comparison with historical unit evidence, not a fresh complete host census. The coordinator captured the1077-line cron file at `2026-10-24T04:35:03Z` under read-only grant `7cf078bf`;348 uncommented job entries are discovered. This worker made no crontab, systemctl, database, broker, network or live-server calls to collect it. The prior sandbox spool read refusal remains in force; using the explicitly supplied input is not a new host read.

The [packet](packets/registry-capture-review-20261024/README.md) separates three review artifacts. None was applied to an operative file.

| Proposal | Exact diff | Review disposition | Source validation |
|---|---:|---|---|
| `restriction-only.PROPOSED.patch` |14 added /4 removed | Two catalyst rows gain existing broker-word heuristic markers; requires review. Keeps RETIRED state, no dispatch, all schedules and other fields unchanged. | Structurally valid; committed-Oct09 fixed-point replay passes |
| `provenance-only.HELD.patch` |1 added /1 removed | `market-regime-collector` F reference L199→L213 matches its active5:16 schedule; HELD because existing canonical replay rewrites it toL199 | Structurally valid; canonical fixed-point intentionally fails, so this is not merge-ready alone |
| `mechanical.REJECTED.patch` |77 added /103 removed | Rejected as an operative proposal: six provenance/owner/class downgrades and two identity/output regressions | Structural gate reports no problem, demonstrating why structural success alone is insufficient |

No lifecycle status, scheduler authority, dispatch/live flag, ownership, contract or output-evidence field changes in either narrow proposal. The restriction-only proposal changes admission metadata; it is not an approval or authority to run, retire, restore or enable anything. The parent retains the operative registry claim through WP37. A separate source claim on another branch was refused even for that existing owner; this task owns only its new report/packet/tests/gate/index and does not bypass that boundary. Historical audit `6dd068f6b` merged via PR2063 remains unchanged.

## Every affected ID and cause

[semantic-fields.json](packets/registry-capture-review-20261024/semantic-fields.json) and [CSV](packets/registry-capture-review-20261024/semantic-fields.csv) contain every changed JSON pointer, before/after presence and value, classification, causal explanation and captured line/hash reference. Nine existing IDs change; two existing IDs would be removed and two replacements added. Common IDs retain their relative order. The row population remains677, which conceals the identity substitution if only totals are checked.

| Affected ID | Captured line | Explanation / disposition |
|---|---:|---|
| `catalyst-momentum-engine-premarket` |381 | Actual command includes `env ALPACA_MODE=paper`; existing whole-command broker-word heuristic finds `alpaca`, adds a broker_order stay marker and forces top-level KEEP_ON_CRON. Review restriction metadata; no broker invocation is proven by a token match. |
| `catalyst-momentum-engine-market` |382 | Same token cause and review restriction. Existing P07 rationalization is retained. |
| `market-regime-collector` |215 | Exact current5:16 schedule joins F:L213; oldL199 describes6:30. All other F fields/verdicts are equal. Provenance-only proposal held for the old fixed-point conflict. |
| `compute-intraday-vwap` |614 | F:L608 retains13–21 cadence while recorded current cadence is9–16. The line moved, so positional retiming fallback fails, and exact(schedule,name) fallback cannot match the old cadence. Reject default platform/UNCLASSIFIED/MIGRATE_N8N and loss of the existing drift block. |
| `hermes-cross-source-synthesizer` |836 | F:L823 retains06:20 while current schedule is18:20. Line movement breaks the retiming fallback; reject loss of research ownership, Technical Debt/P10 and recorded schedule drift. |
| `run-scalp-shadow-logger` |817 | F:L804 retains6–11 while current schedule is6–15. Line movement breaks the fallback; reject loss of scalp ownership, Business Critical/P02 and existing drift evidence. |
| `reporting-engine` |575 | F:L573 names an inline job. After line movement, fallback requires literal `inline`, which is absent. Reject loss of portfolio ownership, Technical Debt and R0 evidence. |
| `set-purge-dates` |158 | F:L156 inline monthly job shifts two lines; positional join fails and generic name cannot match. Reject loss of research/P16 retention evidence and replacement with generic migration defaults. No retention/data-write action is authorized. |
| `start-trade-ai-lab-moomoo-opend` |819 | Shifted inline @reboot join loses F:L806. Reject class/evidence loss. Existing KEEP_ON_CRON and moomoo stay marker remain unchanged. |
| `prewarm-finviz-strip-map` → `cc-curl-finviz` |576 | Generated identity changes because `cc_curl.sh` becomes the primary script. The endpoint, cadence and existing declaration still identify the same process. Reject replacing its ID and losing explicit NO_DURABLE_OUTPUT evidence. |
| `prewarm-trade-ai` → `cc-curl-accept` |766 | Wrapper/header-derived identity replaces the existing endpoint ID for the same process. Reject identity churn and substitution of redirect-log mtime for its explicit no-output declaration. |

The two replacement pairs account for four IDs. Their added/deleted fields are all enumerated individually in the ledger. A command using `curl -o /dev/null` can leave its redirect log silent; the new generic log-mtime declaration is not equivalent output proof. Its generated ACTIVE default is not a newly approved lifecycle decision. Stable lane/evidence identities must be retained when wrapper text changes.

## Authority and trust findings

Both catalyst rows are **RETIRED with no dispatch block** in frozen0764, but their captured cron entries at381/382 are uncommented. That is a source/host lifecycle contradiction. This packet records it and preserves the lifecycle fields; neither adding a restriction nor accepting the packet resolves the actual scheduler authority. The existing marker heuristic does not independently prove a broker operation. Its effects on future admission remain subject to reviewed policy, contracts and ownership.

The generator's rationalization join first depends on historical line positions; retimed named jobs can recover only while that original line still aligns. Inline jobs have no reliable name fallback. Rebuilding generated rows also makes their IDs depend on wrapper/argument text, severing key-based output declarations. These are concrete causes of the rejected proposal. Do not repair them by dropping existing reviewed metadata, lowering tests, changing scheduler authority or treating a successful serializer/structural gate as acceptance.

The correct current-capture F:L213 correction conflicts with the historical replay's first matching6:30 declaration. A later source fix can make the generator choose the explicitly declared schedule before a broad script match, with regression fixtures for duplicate scheduled scripts. That source change is not part of this packet, and the one-line config proposal remains held meanwhile.

## Verification and handoff

**84 focused tests pass with psycopg2 hidden**:26 new packet cases,33 existing reconciliation cases and25 CI-registry cases. Host-path and test-coverage ratchets both report zero new violations.

The focused packet fixtures apply the exact narrow patches to a temporary copy of a hash-bound frozen registry. They verify all177 full-diff leaves independently, restrict narrow previews to their exact metadata whitelist, preserve every state/scheduler/dispatch/watch/owner/output field, refuse tampered bindings/context and refuse the full mechanical proposal through the preview API. The helper returns bytes and has no host or file-write API. Refusing census/subprocess/network barriers surround the relevant tests. Canonical replay explicitly proves restriction fixed-point success and provenance fixed-point failure; no gate is weakened.

Raw private cron commands are not committed. The packet records their operator-provided hash and selected line/hash references; the actual input remains in the private coordinator capture. The compressed fixture is the already-committed0764 registry, bound to SHA-256 `f5af4203e3329053194a6113117d2992c31be0ded9c86963e8d1238e5d8db6e1`, rather than a production state copy.

The parent can review the restriction-only patch and ledger now. Actual shared-config application requires the proper operative claim and a subsequent reviewed source change; provenance correction and mechanical regeneration remain held/rejected as specified. Publication is queued separately under this new task. No source merge, deployment, scheduler mutation, live activation or runtime acceptance is asserted by this report.

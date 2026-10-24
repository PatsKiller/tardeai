# C1 company-facts population: source delivery and production-copy proof

**Status:** Source proposal tested locally; publication/release/backfill/native activation pending coordinator/operator.
**Owner:** CIO; source worker codex-c1-populate-20261024.
**Task:** DSN-20261024-c1-company-populate-P1-T1. Accepted base: `8b6cd3be6d9776d3051ea24fbbcfc65248431c45`.

The production defect was structural: the original company-facts writer only merged existing records, so the104 Watch
names without records could never receive facts. This follow-up creates minimal **FACTS_ONLY InstrumentRecord** rows for
confirmed security GUIDs using the existing `apply_prospect` / `upsert_prospect` facade. Company evidence is stored in
`research.company_facts`; Watch, CIO cognition, Ask and specialist consumers read the same saved GUID record. No request-time
provider, Watch-only store, judgment, conviction, stance, stage or prospect promotion is introduced. This package changes no Watch UI source.

## Exact copy measurements

The operator-authorized SELECT-only capture was run by the coordinator, not the worker. Capture SHA256:
`492e92efe00a6395041b80070f5747f7a9e926a15dd1b82cc62f2f22f8a15d1a`, captured2026-10-24T20:00:49.398467+00:00.
Membership:104 MyWatchlist,24 held,118 formerly-held,212 distinct targets;198 stored profiles. Formerly-held uses all available
SELL ledger history, with date bounds recorded in the private capture. Queries are separate read-only transactions with
original per-query observation clocks, **not** a claimed consistent database snapshot. No broker/provider/HTTP calls were used.

The worker applied only to its private COPY, using the same facade with the existing PG flag off:

| Population | Before all four fields | After all four fields |
|---|---:|---:|
| MyWatchlist |0/104|99/104 (95.19%)|
| Held |0/24|20/24 (83.33%)|
| Formerly-held |0/118|104/118 (88.14%)|

203 fact-only records were created;0 existing-record updates,0 judgments,0 promotions. A second identical plan reports203
unchanged,0 creates,0 updates. This measures company/description/sector/industry coverage, **not** current catalyst coverage
or production backfill. Watch field totals are101 company,101 description,103 sector,103 industry. Exact conflicts retain
source/value/ref/original publication/observation clocks; only identical retained evidence dictionaries are deduplicated.

Remaining Watch gaps:

| Symbol | Missing fields | Reason |
|---|---|---|
| CXMT | company, description, sector, industry | company_fields_not_on_cio_record |
| HOOD | company | company_fields_not_on_cio_record |
| HTGC | description | company_fields_not_on_cio_record |
| INTC | company | company_fields_not_on_cio_record |
| PPC | description | company_fields_not_on_cio_record |

Nine target identities lack confirmed security identity:12507E201,44984F807,543354104,628518102,73017P409,824430300,CASH,CXMT,EKSO.
They are explicit skips, never minted. Thirteen confirmed security identities lack issuer GUIDs:ARKG,ARKQ,ATAI,BJDX,CACI,ELAB,
FCNTX,JEPQ,JTAI,LGPS,NEE,PEW,XCUR. Those facts can be saved keyed by security GUID with an explicit issuer gap. In particular,
JEPQ/XCUR are **not** falsely classified as unresolved security. The immutable source capture's older combined22 identity
annotations are preserved as source diagnostics; the evaluator separates9 security gaps from13 issuer gaps. Every group
field gap and original source gap is in [COPY_PROOF.json](packets/c1-company-population-20261024/COPY_PROOF.json).

## Persistence and authority

Fact mode accepts identity and company research only and rejects even null judgment keys. Existing judged rows retain all
judgments, sibling research and identity. The facade re-reads current canonical tips under its shared append lock, so a CIO
judgment published after preview survives. Multiple GUID records, subject collisions, changed identity and malformed canonical
rows fail closed. Ordinary writers reject a stale last-observed tip under the same lock and must explicitly re-read/reapply their owned patch; a stale judgment writer cannot erase newer facts or sibling research. The real symbol/GUID wake loader, Ask source adapter and CIO/Telegram cognition readers consume newly created SECURITY records without judgments. Exact same evidence is a no-op; genuine conflicting sources or clocks remain visible.

The default judged-prospect validator remains strict. Fact-only PG rows need the proposed migration on the **existing**
`cio_prospect` table; no second table/store is created. Its explicit record-kind check allows null judgment fields only for
fact-only records carrying same-GUID company facts; judged rows still require issuer,stage,stance,conviction,evidence andexpiry.
The normal prospect projection excludes fact-only rows. The existing canonical JSONL remains the P1 store of record.

PG flag-off makes no connection and reports `NOT_REQUESTED_FLAG_OFF`. Requested PG writes require existing registry/flag/table
admission and the fact-only schema capability before canonical append. A subsequent PG error is an explicit partial failure;
replay cannot report success from JSONL alone. Unchanged evidence requires same-GUID PG equality; divergence is owner-held,
not auto-repaired. Native failed/malformed input writes a sanitized failed v2 receipt; missing receipt writes remain visible.

## Native source package and remaining operator work

[Operator runbook](packets/c1-company-population-20261024/RUNBOOK.md) gives exact backfill commands and grant scopes. The generated
workflow is inactive and has native weekday06:35/15:35 America/New_York triggers, live/apply mode, one attempt, sharedlock600s.
It uses existing RunLane, durable receipts and fabric-error routing. No host cron/systemd schedule is created or changed.

The operative registry declaration is **NEVER_SCHEDULED / kind none**, with proposed native source metadata. The new contract
is DRAFT **outside** the operative catalogue; no review/grandfathering was invented. Source structural validation passes;
authority still requires actual contract review, config/relay admission, schema grant if PG enabled, framework readiness,
inactive import and exact-workflow activation. 15:35 follows the nominal15:25 Hermes fire, but completion ordering is not
proven. Conservative72/96h freshness bounds cover the63h weekend scheduled gap; weekday expected-fire and notification
acceptance remain unmeasured. This source release alone does not make n8n population live.

Latest report/receipt are bounded overwrite files. Existing CIO current/events retention is KEEP_FOREVER; canonical JSONL
history is append-only. No retention deletion or identity/PG divergence repair is authorized by this package.

## Evidence and limits

Private evidence root: `/home/johnclaw/.cache/rtc/codex-c1-populate-20261024/`. The initial source-file manifest was captured
2026-10-24T19:58:58.415960+00:00 with source/copy hashes and stable-at-copy checks. Later observations found independent changes
in live `cio_instrument_records.jsonl` and `trade_ai_cache.json`; the final timed bracket also finds changes in
`ticker_research_graph.jsonl` and `ticker_enrichment_cache.json`. All four changes are drift and were **not repaired**. Proof
continues against the immutable captured inputs/original hash-verified prefix. No worker write targeted production state.
This report makes no claim about Fidelity mapping absence or current account mappings.

`COPY_PROOF.json` contains source hashes, captured clocks, every gap and bracketed drift hashes. Actual public FATN/ANET facts
in `apps/command-center-v3/e2e/fixtures/c1CompanyPopulation.fixture.json` come from the copy's canonical GUID record projection:
Fatpipe Inc / Technology / Software - Infrastructure; Arista Networks Inc / Technology / Computer Hardware. Their descriptions,
source refs and original clocks are retained; no current catalyst is invented. Two browser cases render the actual accepted
WatchCompanyFacts component at1440/412 with all traffic intercepted to a synthetic origin, no live server. They assert facts,
source tooltips, two-line descriptions and no horizontal overflow.

Native hidden-PG affected tests, exact real-tree completeness tests, captured registry/reconciliation/health/retention gates,
host-path and coverage ratchets, docs index and npm build are recorded in `VALIDATION.json`. Effective psycopg2 refusal is
verified. The scheduler reconciliation uses the **historical2026-10-09 snapshot** and pinned coordinator discovery, never a fresh
host census. The CLI reconstructs195 existing generated suffix rows; those events are not195 newly admitted lane IDs. Pure keyed comparison reports0new/0removed/0field-changed lanes; the follow-up corrects only C1 row ordering. This is historical planning output, not a current host census. Before/after file hashes prove CHECK did not rewrite source/config/captures. Required GitHub CI and exact-CURRENT
runtime/consumer/alert acceptance remain pending publication and operator work.

## PR2074 CI follow-up

b81 local203-test validation did not cover two CI guards. This follow-up centralizes explicit state-root path selection inside
`portfolio_positions.store_path(root)` and uses its approved `load_store`, without a reader exemption. The lane and planned
activation row now say CORRELATED with admission/runtime coverage **not proven**, rather than inventing ESTABLISHED evidence.
The full registered profile also caught C1 being appended after generated rows. Only that row moves677→482 before the suffix;
every row object, other row order and top-level field is conserved. A dedicated admission-order regression now protects it.

The complete registered native fast profile (same coverage as serial full, jobs2,1403unique files/1438refs/675gates) finished
exit1 after2117s:686pass/26fail **execution units** out of712, spanning25failed gate names. Case execution summaries, including
35duplicate file references:25420passed,167failed,57errors,287skipped,2xfailed. These are not unique-test counts. Complete unique
failed nodeids remain NOT_MEASURED because the native runner truncates failure output. All seven frozen source hashes matched
at completion. This run was b81 plus the accessor/confidence working-tree fixes **before** the ordering correction; it is not
a full-green receipt for the final commit.

After the ordering fix, all four requested entire files pass124tests; the whole affected gate union passes234tests in14files.
Actual CIO reader/copy/race tests pass202 with2existing PG skips. Canonical Ruff PATH and the exact hash-pinned pure classifier
fixture rerun pass67tests; root's normally reviewed five ephemeral/forkserver nodes pass. Original full failures are retained.
Remaining socket/dependency/command-fixture failures and blocked genuine production-state attempts remain explicit. In particular,
private-PG telegram-turn tests all skip under hidden psycopg2 and their gate correctly refuses an all-skipped run; no guard or
tolerance is weakened. Late immutable-fixture tests fail at socket creation, while git shows the tracked fixture tree clean.

[CI_FOLLOWUP_VALIDATION.json](packets/c1-company-population-20261024/CI_FOLLOWUP_VALIDATION.json) records the distinctions and
raw receipt hashes. Native admission remains inactive/DRAFT and production acceptance is unmeasured. The coordinator updates
the existing PR branch; no new PR or agent push is requested. A committed-head affected-gate receipt will be saved outside
the commit so it can name the actual final SHA without a self-referential file hash.

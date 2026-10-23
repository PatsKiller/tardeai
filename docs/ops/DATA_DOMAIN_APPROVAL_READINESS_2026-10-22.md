# Data-domain approval readiness — 2026-10-22

```
Status:      ACTIVE (read-only report; proposes, approves nothing)
as_of:       2026-10-23T02:15:25Z (2026-10-22 22:15 ET)
Measured at: branch feat/ops-controls-data-approvals-20261022 on base 4f26fe6da (stacked on #1964); live repo scan
             + read-only DB probe: `python scripts/lib/data_domain_readiness.py --json` (scan DONE, 24.2 s)
Owner:       platform / CIO data foundation
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0
Policy:      AGENTS.md §7A, §17, §26.2, §26.6 (18.0.0 ACTIVE)
```

Operator feedback 2026-10-22 on Ops → Controls → **Data approvals**: the tab listed 17 domains, all "proposed",
with nothing else — *"This is not a dashboard."* The tab now shows each domain's store, writer, readers, live checker
findings, freshness and approval, with a verdict. This report is the same scan, written down, plus a proposed
approval list. **Nothing here approves or promotes a row.** A grant is the operator's decision (§17). It is applied
later by a reviewed PR that calls `scripts/lib/data_dictionary.promote` with the operator's approval record.

## 1. What the verdict means

The verdict uses only checks that already exist; none was invented for this report. The scan
(`scripts/lib/data_domain_readiness.py`) promotes each proposed row **in memory**, with the ceilings measured now.
Those are the same ceilings `promote` would record. It then runs the real gate functions against the promoted row:

| Criterion | Gate (called, not shelled out) | Finding that would fail CI once the row is binding |
|---|---|---|
| Row is well-formed | `data_dictionary.validate()` | `DICTIONARY_INVALID` |
| Writer exists, or UNCONSOLIDATED + target | `check_data_source_authority.check_domains()` | `WRITER_MISSING`, `WRITER_UNDECLARED` |
| Read projection is registered | `check_domains()` | `PROJECTION_MISSING` |
| Ceilings hold once binding | `data_dictionary.promote()` + `evaluate()` | `DICTIONARY_SECOND_WRITER`, `NON_AUTHORITATIVE_READ` |
| Gated-store readers are approved | `check_readers()` | `UNAPPROVED_READER`, `READER_GRANT_INVALID` |
| A named single writer is the only writer | AGENTS.md §26.2 (the `extra` set in `evaluate()`) | — (a false claim in the row) |

**READY_TO_APPROVE** means every criterion holds. **NOT_READY** lists each failing criterion, with the gate's own
finding. **APPROVED** means the row is in `domains[]` with a dictionary block. Freshness, live warnings and reader
counts are shown as evidence; no code makes them a criterion, so they are not one here.

Granting a row moves it into `domains[]`. From then on CI **fails** on the checks above instead of warning, against
ceilings that may only fall. For `cio_prospect`, the grant is also one of three runtime conditions for the Postgres
dual-write (`prospect_store_status()` in `scripts/lib/cio_instrument_record.py`); the other two are the flag and the
table. Granting creates no table, moves no reader and changes no page (§26.6).

## 2. Verdict per domain `[VERIFIED]` (scan above)

Summary: **approved 0 · ready to approve 16 · not ready 1 · live findings 31** (all warnings: no row is granted yet).

| # | Domain | Verdict | Store | Writer (writer files today) | Live findings (warnings today) | Freshness |
|---|---|---|---|---|---|---|
| 1 | `cio_prospect` | READY_TO_APPROVE — **operator approval E given (2026-10-22, approve-all); promotion pending its own PR** | table `cio_prospect` | `scripts/lib/cio_instrument_record.py` (1) | 4× NON_AUTHORITATIVE_READ: `api_v3_opportunities.py` → opportunity projection; `api_v3_cio.py` → investment brief; `api_v2.py` → watchlist_research_cards, advisor_recommendations | table does not exist yet (the migration follows the grant) |
| 2 | `security_identity` | READY_TO_APPROVE | file `runtime/identity_registry.json` | `scripts/lib/identity_registry.py` (0 seen — scan blind spot) | none | updated 16.4 h ago (SLA 24 h) |
| 3 | `positions_store` | READY_TO_APPROVE (extends the granted §7A domain) | table `positions_current` | `scripts/positions_sync.py` (1) | 1× NON_AUTHORITATIVE_READ: 5 surface files read `holdings.json` | no time column declared (table has `as_of`) |
| 4 | `transactions` | READY_TO_APPROVE | table `trade_transactions` | UNCONSOLIDATED → `schwab_transaction_ingest.py` (3) | SECOND_WRITER 3; 2× NON_AUTHORITATIVE_READ (`tax_lots.json`, `cost_basis_anchors`) | no time column declared |
| 5 | `broker_stops` | READY_TO_APPROVE | table `stop_lifecycle` | `scripts/stop_lifecycle_monitor.py` (1) | none | declared `observed_at` is **not a column** (table has `snapshot_at`) |
| 6 | `watchlist_membership` | READY_TO_APPROVE | table `watchlist_items` | UNCONSOLIDATED → `lib/writers/watchlist_items_writer.py` (to build) (25) | SECOND_WRITER 25; 3× NON_AUTHORITATIVE_READ | no time column declared |
| 7 | `scanner_results` | READY_TO_APPROVE | table `trade_ai_scans` | UNCONSOLIDATED → `lib/writers/trade_ai_scans_writer.py` (to build) (6) | SECOND_WRITER 6; 2× NON_AUTHORITATIVE_READ | no time column declared |
| 8 | `catalyst_events` | READY_TO_APPROVE | table `catalyst_events` | UNCONSOLIDATED → `news_to_catalyst.py` (3) | SECOND_WRITER 3; 1× NON_AUTHORITATIVE_READ | no time column declared |
| 9 | `fused_signals` | READY_TO_APPROVE | table `fused_signals` | `scripts/signal_fusion.py` (1) | none | declared `as_of` is **not a column** (table has `created_at`) |
| 10 | `cio_decisions` | READY_TO_APPROVE | table `cio_decisions` | UNCONSOLIDATED → `cio_instrument_record.py` (5) | SECOND_WRITER 5 | declared `decided_at` is **not a column** (table has `created_at`) |
| 11 | `cio_theses` | READY_TO_APPROVE | file `cio/cio_theses.jsonl` | `scripts/lib/cio_theses.py` (0 seen — scan blind spot) | 1× NON_AUTHORITATIVE_READ: 2 files read `cio_theses_projection.json` | updated 8.6 h ago (SLA 24 h) |
| 12 | `options_ideas` | READY_TO_APPROVE | table `options_approval_queue` | UNCONSOLIDATED → `options_desk_enterprise.py` (4) | SECOND_WRITER 4; 2× NON_AUTHORITATIVE_READ | no time column declared |
| 13 | `paper_proposals` | READY_TO_APPROVE | table `paper_trade_proposals` | UNCONSOLIDATED → `lib/proposal_lifecycle.py` (to build) (51) | SECOND_WRITER 51; 1× NON_AUTHORITATIVE_READ | no time column declared |
| 14 | `paper_trades` | READY_TO_APPROVE | table `paper_trades` | UNCONSOLIDATED → `paper_execution_sweep.py` (32) | SECOND_WRITER 32 | no time column declared |
| 15 | `alert_events` | READY_TO_APPROVE | table `alert_events` | UNCONSOLIDATED → `alert_event_writer.py` (17) | SECOND_WRITER 17; 2× NON_AUTHORITATIVE_READ | declared `fired_at` is **not a column** (table has `created_at`) |
| 16 | `comms_intents` | READY_TO_APPROVE | table `communication_events` | UNCONSOLIDATED → `lib/comms/client.py` (7) | SECOND_WRITER 7; 2× NON_AUTHORITATIVE_READ | no time column declared |
| 17 | `operator_settings` | **NOT_READY** | table `operator_settings` | UNCONSOLIDATED → `scripts/ops/operator_controls_applier.py` (to build) (1) | none today | no time column declared |

**Why `operator_settings` is not ready.** Both items are findings from the gates:

1. `PROJECTION_MISSING`: the row declares projection `operator_settings`, but `scripts/lib/data_broker/catalog.py`
   has no projection by that id.
2. `DICTIONARY_SECOND_WRITER` once binding: `scripts/lib/ops_controls_store.py` writes `operator_settings` today.
   The row names no single writer (UNCONSOLIDATED, target `operator_controls_applier.py`), so promotion would record
   a ceiling of 1 with no allowed writer, and the one real writer would fail CI.

The fix is a registry edit, which an agent proposes and the operator decides (§17). Either name the real writer, or
move the write behind the applier; and either register the projection or set `projection: null` with a
`projection_status`.

**Not criteria, but worth fixing before the grant PR.** Each of these is a registry or proposal edit, not done here:

- **Declared time columns that do not exist.** Four rows' `data_dictionary.facts` name a column the table does not
  have: `broker_stops`/`observed_at`, `fused_signals`/`as_of`, `cio_decisions`/`decided_at` and
  `alert_events`/`fired_at`. Freshness cannot be measured for them until the fact names the real column.
  `positions_store` declares no time column, although its table has `as_of`.
- **Scan blind spots.** For `security_identity` and `cio_theses` the dictionary scan sees 0 writers, because the file
  path is assembled rather than spelled (see `data_dictionary`'s docstring). Promotion would record a ceiling of 1.
  That is correct, but it is not evidence that the declared writer is the only one.
- **Surface-read ceilings freeze today's debt.** For example, `positions_store` would record 5 page/API reads of
  `holdings.json` as its ceiling. That matches §26.6 ("ceilings measured at the grant"; readers move in batches).
  It is stated here so the number is a choice, not a surprise.

## 3. Proposed approval list (for the operator — not applied)

Reply with the batch letters or rows you grant (or narrow). Each grant is then recorded in one reviewed PR. That PR
calls `data_dictionary.promote(auth, <domain>, {approved_by: "operator", approved_on, reference: <your reply
verbatim>, scope}, measured)`, re-renders `docs/architecture/DATA_DICTIONARY.md` and `docs/SOURCE_OF_TRUTH.md`, and
runs `scripts/check_data_source_authority.py`. The ceilings shown are what `promote` records today; the PR re-measures
them at grant time.

**Batch A — already approved, promotion PR pending**

- [x] `cio_prospect`: *Grant cio_prospect as the single per-security store: a Postgres table keyed by security_guid,
  written only by InstrumentRecordStore; opportunity_assessment becomes its export (superseded, not removed).*
  The operator approved this in approval E (2026-10-22, approve-all). That approval is recorded in
  `config/data_domain_approval_notes.json` for display only. It binds when its own promotion PR merges. Writer
  ceiling 1. Surface-read ceilings: opportunity projection 1, investment brief 1, watchlist_research_cards 1,
  advisor_recommendations 1, others 0.

**Batch B — one named writer, ready**

- [ ] `security_identity`: identity registry file, writer `identity_registry.py`. Ceiling 1; memory_identity reads 0.
- [ ] `positions_store`: adds the dictionary block to the granted §7A domain; supersedes `holdings_accounts`
  (marked, not removed). Writer ceiling 1; `holdings.json` surface reads 5; `schwab_positions_live` 0.
- [ ] `broker_stops`: observed stops, read-only. Writer ceiling 1. Grants no stop or order authority (§0 rules 1–2).
  Suggested fix first: change the fact's `observed_at` to `snapshot_at`.
- [ ] `fused_signals`: writer `signal_fusion.py`, ceiling 1. Suggested fix first: change the fact's `as_of` to
  `created_at`.
- [ ] `cio_theses`: writer `cio_theses.py`, ceiling 1; `cio_theses_projection.json` surface reads 2.

**Batch C — UNCONSOLIDATED, with a ceiling that only falls (§26.2), ready**

- [ ] `transactions`: ceiling 3 (target `schwab_transaction_ingest.py`).
- [ ] `catalyst_events`: ceiling 3 (target `news_to_catalyst.py`).
- [ ] `cio_decisions`: ceiling 5 (target the CIO writer). Suggested fix first: change `decided_at` to `created_at`.
- [ ] `options_ideas`: ceiling 4 (target `options_desk_enterprise.py`, host only).
- [ ] `scanner_results`: ceiling 6 (target writer module to build).
- [ ] `comms_intents`: ceiling 7 (target `lib/comms/client.py`).
- [ ] `alert_events`: ceiling 17 (target `alert_event_writer.py`). Suggested fix first: change `fired_at` to
  `created_at`.
- [ ] `watchlist_membership`: ceiling 25; supersedes `watch_discovery` (marked, not removed).

**Batch D — UNCONSOLIDATED, paper path (consolidation needs an execution-engineering grant; the row grant itself
records only the ceiling)**

- [ ] `paper_proposals`: ceiling 51 (target `lib/proposal_lifecycle.py`, to build).
- [ ] `paper_trades`: ceiling 32 (target `paper_execution_sweep.py`).

**Not proposed — fix first**

- `operator_settings`: NOT_READY (section 2). Re-propose after the registry row names its real writer and its
  projection status.

## 4. Reproduce

```
python scripts/lib/data_domain_readiness.py            # table: verdict, store, writer, freshness, missing items
python scripts/lib/data_domain_readiness.py --json     # the payload Ops → Controls serves
python scripts/lib/data_domain_readiness.py --no-db    # skip the table probe
```

The API serves the same view in `GET /api/v2/ops/controls/state` → `data_approvals`. One background scan runs at
most every ~60 s (about 25 s each on this host); a request never waits for it.

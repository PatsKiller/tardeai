# Production bill — what “READY” means for Cross-Asset Decision Intelligence

Status: ACTIVE
Owner: Agent A (release coordination); John (operator authorization)
as_of: 2026-10-09T11:42:14-04:00
Measured at: local CADI-01 fixtures on base `3b5c248569908adfad9a60ca895e0fa9b2aa2c49`; no current release verification
Current ticket: **CADI-01 SOURCE REGISTRATIONS APPROVED; FINAL ACCEPTANCE PENDING**
Full cross-asset recommendation: **NOT READY**
Current test results: **121 combined PASS; 80 core PASS (overlap); 15 adversarial PASS**; full acceptance not green

### Latest authority checkpoint

John approved the two named CADI-01 registrations with sole writer
`scripts/lib/cross_asset/decision_store.py`, explicitly without production activation.
Both DSA rows reference the
[approval archive manifest](governance/CADI01_SOURCE_APPROVAL_ARCHIVE_MANIFEST_20261009.md#cadi01-source-approval-20261009).
The pending-source descriptions and failed test counts below are retained before-state records.
Post-approval native authority/full acceptance, an exact-SHA push grant and Agent A review/merge
remain required. This is neither a release grant nor a READY recommendation.

## Current bill and authority boundaries — 2026-10-09

This approved engineering revision replaces the sequencing/activation instructions in the
historical bill preserved below. Existing shared-research transparency is useful but does not
prove complete cross-asset EV routing or historical superiority. Code merged or served, five
Drive files present, and a sent status email are distinct facts; none completes the requested
engine without functional evidence. This local foundation makes no new runtime/delivery claim.

### Bill 1 — CADI-01 alone: canonical contract and store authority

Land CADI-01's v2 schema and both v1 adapters before any downstream ticket branches. Preserve
immutable history, protect idempotency/concurrent writes, and rebuild views through one declared
writer. An unknown action must yield a visible error receipt for that symbol including raw value,
source and event reference; other rows continue, and batch status reports partial failure honestly.

Register **every** new authoritative history/projection store in `config/data_source_authority.json`
with its single writer **in the same PR** (§7A), and classify every new output schema, including
error/projection receipts, in `config/cio_surface_classification.json`. Actual operator approval
is distinct from supervisor review and plan approval. Missing approval means blocked source/
writer activation and an honest gate finding, not an invented approval record.

Agent A reviews the PR and controls its merge. Required local acceptance/normal pre-push and
exact-SHA push authorization are not waived. No author self-merge or deployment. CADI-01 now
implements the contract, adapters and explicit-path fixture writer, registers both proposed
stores and classifies four schemas. Source approvals are pending; the authority gate remains red.
Local targeted proof is 84 PASS and release-equivalent source checks are 17/17 PASS; this does not
complete Bill 1 until actual approval, final acceptance and Agent A review/merge. No PR or push yet.

The full run exited 1 for missing source approvals and missing audit-read edges. The latter was
repaired with a bounded, read-only adapter to the existing operator-artifacts audit panel;
focused completeness and a combined 111-test run passed. This is not CADI-07's comparison UI,
not production activation, and not a second store writer. Production read needs both approved
registry records and an independent activation flag, currently off. A final scoped result is
recorded at checkpoint; full acceptance must rerun after actual source approval.

### Bill 2 — Source linking, economics and frozen model

Only after CADI-01 merges, CADI-02/03/04 may branch in parallel with disjoint declared ownership.
Read approved stores through existing readers; do not create private research or a second
positions writer. Missing quantities remain unknown; covered-call cover is per account.

Compare expressions with executable quotes, common horizon/capital basis, costs, dividends,
financing and assignment limits. The forecast model is **Parfit-owned**, **Halley-reviewed
independently**, versioned and frozen before held-out validation and per release. Only John may
promote an exact artifact hash/supported scope after validation. No automatic model promotion,
runtime retraining or silent replacement. `NO_PROVEN_WINNER` remains the default until validated
probabilities, constraints and positive incremental net-EV confidence evidence clear it.

### Bill 3 — Named retention and pgvector decisions, before CADI-06

**No CADI-06 start without `CADI_OPTIONS_ARCHIVE_RETENTION`.** The CADI agent produces a PR'd
read-only live-store packet with measured snapshot bytes, capture frequency, symbol/contract
counts, actual compression, index/TOAST overhead and peak migration space, plus sample bounds,
pinned root/as_of, current policy and storage/headroom forecasts. Agent A reviews and presents
choices; John records approved retention/budget/floor. Proposed 365 days is not approval.

The packet also supplies the measured **pgvector reserved-space figure** and configured floor
on the shared filesystem. `PGVECTOR_DISK_FLOOR` is a separate pending named John decision;
preserve existing floors, and do not activate/migrate pgvector implicitly. Missing measurements
stay NOT MEASURED, not guessed numbers. Existing retention writers/pruners stay unchanged until
the authorized change. This sidecar performed none of these measurements or decisions.

### Bill 4 — CADI-05 n8n lane and CADI-06 real replay

After required Stage 2 contracts, build CADI-05; CADI-06 additionally waits for Bill 3.
The five-minute worker is an **n8n lane under AGENTS.md §23**, never a new cron or systemd timer.
One PR adds both its `kind="n8n"` registry row and allowlist entry with fixed argv, genuine
non-mutating `--dry-run`, dedicated `safe_flock`, classified output and durable receipt.
The expression stays a placeholder until Agent A generates the workflow and the operator imports
it under a named grant. Its expected temporary **ORPHANED** state before the first scheduler-shadow
receipt must be in the PR body. No fabricated workflow id, hidden failure or forbidden-writer bypass.

Use relay → coordination gateway → executor only. Agent A generates; operator imports/activates.
Prove **scheduler-shadow → canary → live** with host `RunReceipt@v1`, output and lock evidence.
Quote every cadence/cron string; never split a bare `*` through the shell. Nothing here grants
workflow changes, model authority, broker reach or trading permission.

**scheduler-shadow** is n8n `dry_run`; **decision-shadow** is organic advisory evaluations persisted
without financial action. Keep these separate in receipt fields, board, monitor and docs.
Scheduler-shadow/fixtures/manual fires cannot satisfy the fourteen-day decision-shadow requirement.

Replay real 30/60/90 cohorts using then-available sources. Report reconstructed/priced/excluded/
pending/matured counts and denominators; never use current quotes, later research, revised dates
or synthetic premiums as historical evidence. Distinguish missing proposals, correctly blocked
alternatives and demonstrated economic misses. Retention/pruning follows John's approved budget.

### Bill 5 — UI, continuous QA and full readiness

CADI-07 follows stable Stage 3 projections; CADI-08 validates throughout. Cached read-only CIO
pages show timestamps, lineage, evidence class, queue age/priority, model version and blockers.
Page loads must not launch research, fitting or replay. Verify desktop/mobile and source agreement.

Full readiness requires passing actual targeted/regression/authority/full acceptance and exact-SHA
CI, independent review, real historical proof, an operator-promoted frozen model, and at least
**fourteen consecutive organic decision-shadow days with >=99% eligible-event receipt coverage**.
No untested high/critical defects. Receipt coverage does not itself prove usable economics.
Missing any gate keeps **NOT READY**. Transparency readiness, source deployment and decision-EV
readiness must never be conflated, even if code lands within a week.

### Bill 6 — Governed release, proof and delivery

Agent A coordinates exact-SHA merge/release grants, normal prepare/promote and tested rollback;
John authorizes applicable operator-only steps. Independently verify served source, process cwd,
API/UI projection and natural receipts. No financial action or broker/trade authority is part of
this bill. A push grant is not a merge/deployment or source/writer/model approval.

Update all five docs with exact commits, files, commands/results, hashes, before/after state and
residual risks. Announce serialized-file PRs on `~/N8N_PROGRAM_BOARD.md` before opening and append
`time, CADI agent, ticket, PR, head SHA` for each PR. Budget two pushes; never bypass a hook.
The coordinator regenerates INDEX/derived authority docs after sidecar handback.

For delivery, verify content parity of **all five** Drive mirrors and actual status/package email
attachment/link receipts. Do not equate the historical sent status email with delivery of a new
completed package, or mirror existence with current readiness. No Drive write or email was sent
by this sidecar.

### Current billing evidence

| Checkpoint | State at documentation handback |
|---|---|
| Source base | `3b5c248569908adfad9a60ca895e0fa9b2aa2c49` |
| CADI-01 | **IN PROGRESS**; documentation revised, no sidecar code/test claim |
| Tests / release-equivalent / authority | **NOT RUN** |
| CADI-02..07 branches | **NONE started here**; wait for required merges/decisions |
| Retention / pgvector packet | **PENDING / NOT MEASURED** |
| Model approval / n8n import / activation | **NONE performed here** |
| Commit / push / PR / merge / deployment | **NONE performed here** |
| Full readiness | **NOT READY** |

---

## Historical production bill — 2026-09-29 (preserved, not current authorizations)

as_of: 2026-09-29  
Authority: Operator requirement — one security, one research spine, all silos transparent  

## Shared security research — methodology (binding)

See **AGENTS.md → “Shared security research — NO SILOS (CRITICAL PATH, CIO-owned)”**.

That section is the house rule: CIO owns `SecurityResearchSpine@v1`; options / holdings /
watchlists / re-entry **read** via `view_for_silo`; they must not invent private thesis stores.
This production bill only sequences *how* that methodology reaches live (A→E).

| Approval | Meaning |
|---|---|
| **git-push** (#1360) | Code + docs onto GitHub / PR only |
| **Not yet** | Merge, promote to CURRENT, enable spine in live, go-live trading |

Push ≠ production. Production requires the checklist below.

## Your product requirement (acceptance)

> Research must not live in silos. Options, holdings, watchlists, and re-entry must all see the **same** CIO-owned research for a security, persisted in shared memory.

That is `SecurityResearchSpine@v1` (`scripts/lib/cross_asset/security_research_spine.py`):
- **Owner:** `cio`
- **Consumers:** options_desk, watchlist, reentry, holdings, hermes, cross_asset, aegis
- **Write path:** Hermes complete → `upsert_from_hermes` (flag `CROSS_ASSET_SPINE=1`)
- **Read path:** `view_for_silo(symbol, silo)` — same thesis for every silo

## Bill to production — approve these in order

### Bill A — Merge PR #1360 (code on main)
**Grant:** git-push (merge)  
**Does:** lands scaffold on `main`  
**Does not:** change live behavior  

### Bill B — Promote to CURRENT
**Grant:** `release-write` reason must include `prepare and promote #1360` (or merge SHA ≥9 hex)  
**Does:** server runs new modules  
**Does not:** write spines yet (flags still off)

### Bill C — Enable shared spine (this is the transparency bill)
**Grant:** `config-write` (or service restart after env)  
**Set:** `CROSS_ASSET_SPINE=1` on portfolio-server + CIO telegram  
**Wire:** Hermes research COMPLETE → `upsert_from_hermes` via
`scripts/lib/cross_asset/hooks.notify_hermes_result_completed` from
`cio_hermes_research._persist_stamped_result` (**CADI-011 landed**).  
**Read:** `thesis_fields_for_symbol` overlays spine; options `_research_universe_rows`
merges `spine_rows_for_root` first; reentry overlays spine summary (**CADI-012 landed**).  
**Prove:** for NFLX (or any symbol), `view_for_silo` returns identical thesis for options/watch/reentry/holdings  

**Pass criteria for Bill C:**
1. One Hermes result creates one spine row.  
2. Options universe merge includes `cio_research` lane from spine (tested).  
3. Watch / reentry / holdings callers prefer spine via `thesis_fields_for_symbol` overlay + options universe merge (CADI-012).  
4. No silo invents a private thesis when spine is POPULATED.  

**Honesty:** hermetic PASS ≠ OBSERVED. Organic “research once, every desk sees it”
requires promote of the CADI-011/012 PR + `CROSS_ASSET_SPINE=1` on live services +
one completed Hermes result that appends the spine ledger.
### Bill D — Shadow expression ranking (optional same week)
**Set:** `CROSS_ASSET_SHADOW=1`  
**Prove:** SymbolDecisionObject ledger grows; no broker calls  

### Bill E — READY for production recommendation
Only when **all** true:
1. Bill C live ≥7 days with spine coverage metrics (symbols researched → spine present %).  
2. Options + watch + reentry + holdings all call `view_for_silo` (grep gate in CI).  
3. Hermetic + one OBSERVED live canary (operator ask → spine → all silos).  
4. Historical/EV still may be CONDITIONAL — transparency can go live **before** EV ranking.  

**Important:** You can bill **transparency (shared research)** to production before EV/options superiority is READY. Those are different bars:
- **Transparency READY** = Bill C + E.1–E.3  
- **Expression EV READY** = still NOT READY until chain pricing + 30/60/90 metrics  

## Gaps still blocking full EV go-live (not blocking shared research)

- Chain-priced expected value  
- Continuous shadow timer  
- Archive replay superiority rates  
- Collar family  
- UI  

## Immediate next engineering tickets

| ID | Work | Status |
|---|---|---|
| CADI-011 | Hook Hermes complete → `upsert_from_hermes` when `CROSS_ASSET_SPINE=1` | **DONE** (hooks + `_persist_stamped_result`) — hermetic; OBSERVED after promote |
| CADI-012 | Options/watch/reentry/holdings prefer spine (`overlay` / `spine_rows_for_root`) | **DONE** — hermetic; OBSERVED after promote |
| CADI-013 | Coverage metric: % of researched symbols with spine | open |
| CADI-014 | CC API `GET /api/v2/research/spine/{symbol}` | open |

---

When you say “I need this to be production,” approve **Bill A → B → C** for transparency. Say if you want EV ranking in the same bill or as a follow-on.

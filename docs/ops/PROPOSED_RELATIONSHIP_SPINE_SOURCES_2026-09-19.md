# DEFERRED — operator continue-park (AGENTS.md §17 / §7A)

```
Status: DEFERRED
Effective-Date: 2026-09-20
as_of: 2026-09-20T14:45:00-04:00
Last-amended: 2026-09-20T16:15:00-04:00 (merge origin/main draft-row prose; Status remains DEFERRED)
Measured at: AEC four-spine INTEGRATED; relationship domain data ABSENT by design until granted
Canonical repo path: docs/ops/PROPOSED_RELATIONSHIP_SPINE_SOURCES_2026-09-19.md
Authority: propose-and-stop — adding a data source or writer of an authoritative store is operator-only
Subject: Relationship memory spine — first granted sources (no call sites until approved)
See also: ledger PARTIAL-relationship-spine-data; config/data_source_authority.json (§7A);
  sibling parks: docs/ops/PROPOSED_RETIRE_HERMES_ADVISORY_EVENT_ENQUEUE_2026-09-19.md;
  docs/ops/PROPOSED_BITTEMPORAL_PROD_5432_2026-09-20-1051.md
Operator-decision: DEFER (continue-park; spine stays empty; no data_source_authority edit)
decided_on: 2026-09-20T14:45:00-04:00
decision_reference: Grok session plan approve — triple-DEFER maturity gap closeout
```
## Finding

AEC four-spine memory (`strategic` / `operational` / `relationship` / `learning`) is live.
Strategic and learning are fed by the AEC cycle; operational gains `cio_cycle_status` via #1106.
**Relationship remains empty by design** until sources carry an operator `approval` in
`config/data_source_authority.json` (§7A). Ledger row: `PARTIAL-relationship-spine-data`.

Spine **slot** = INTEGRATED (wake loads all four keys). Domain **data** = ABSENT
(`relationship: count=0`). Closing PARTIAL requires a granted registry row — not a feeder
invented by an agent.

## Exact operator decision ask

Reply with one of:

1. **APPROVE_RELATIONSHIP_SOURCE_<N>** — grant candidate **1**, **2**, and/or **3** below
   (name which). Agent then opens a PR that lands **only** the registry row(s) with a
   complete `approval` block — **no call sites** until `UNAPPROVED_SOURCE` would pass.
2. **APPROVE_RELATIONSHIP_MANUAL_ONLY** — candidate **3** only (operator-curated store).
3. **DEFER** — leave relationship spine empty; keep PARTIAL parked.
4. **REJECT** — relationship spine stays intentionally unfed; close PARTIAL as won't-fix
   with reason recorded here.

Agents must **not** edit `config/data_source_authority.json` until one of (1)/(2) is granted.

## Sibling §17 parks (cite — do not rebuild)

| park | propose | recommended token |
|---|---|---|
| hermes advisory enqueue | `docs/ops/PROPOSED_RETIRE_HERMES_ADVISORY_EVENT_ENQUEUE_2026-09-19.md` | `APPROVE_RETIRE_HERMES_ADVISORY_EVENT_ENQUEUE` (or `DEFER`) |
| bitemporal prod `:5432` | `docs/ops/PROPOSED_BITTEMPORAL_PROD_5432_2026-09-20-1051.md` | **`DEFER`** — keep shadow `:55432` only |
| relationship (this file) | here | `DEFER` / `APPROVE_RELATIONSHIP_*` / `REJECT` |

Packet: store `plans/s17-continue-park-or-settle-20260920.md`. Agents invent none of these tokens.

## Proposal (do not apply without operator grant)

Candidate **same-question** sources for relationship facts (counterparty / broker-house /
analyst-firm / peer-set links that are **not** security identity and **not** macro):

1. **Schwab instrument `description` peer clusters** — already on disk via
   `lib/schwab_instrument_evidence` (4,997 instruments). Scope: issuer peer labels only;
   never mint CUSIP/identity; never size.
2. **Existing `document_mentions` with `role=mentioned`** — already tagged; relationship
   edge = "document about A mentions firm B as source". Writer would project mentions →
   relationship spine facts; no new provider host.
3. **Operator-curated counterparties** — manual store (like `private_company_proxies`):
   `writer: operator`, `no_coverage: refuse_up_front`.

**Not proposed:** scraping new social/graph APIs, inventing ticker→firm maps, or giving
macro series an issuer.

## Required grant shape (DataSourceAuthority@v2)

For whichever candidate is accepted, the PR that lands **only** the registry row must carry:

- `approval.approved_by: operator`
- `approved_on`, `reference` (this note / Telegram / PR)
- `scope` one-liner of what the source may supply
- single writer module, cadence, `no_coverage`, backup (same question only)

**No call site** until that row is granted (`UNAPPROVED_SOURCE` fails the build).

## Path choice — why this file, not `config/data_source_authority.json` yet

`[VERIFIED]` 2026-09-20: `scripts/check_data_source_authority.py` `check_approvals` treats any
non-blank `approved_by` / `approved_on` / `reference` / `scope` as complete. Putting
`approved_by: "PENDING"` (or similar) into the live registry would **pass** `UNAPPROVED_SOURCE`
while inventing a grant — that weakens the gate. Leaving fields blank fails the build and
cannot merge.

**Therefore the valid propose-and-stop path without weakening the gate is docs+ledger:** keep
the draft row here until the operator types `APPROVE_RELATIONSHIP_*`; only then land it in
`config/data_source_authority.json` with `approved_by: operator`. Prior propose PR #1107
already parked this file on main; this amendment adds the exact draft JSON only.

**No production call sites. No registry mutation in this propose wave.**

### Draft registry row — candidate 3 (`APPROVE_RELATIONSHIP_MANUAL_ONLY`)

Shape mirrors granted `private_company` (manual / `refuse_up_front`). **Do not copy into
`config/` until granted.**

```json
{
  "domain": "relationship_memory",
  "class": "manual",
  "approval": {
    "approved_by": "operator",
    "approved_on": "<OPERATOR_GRANT_DATE>",
    "reference": "docs/ops/PROPOSED_RELATIONSHIP_SPINE_SOURCES_2026-09-19.md + operator token APPROVE_RELATIONSHIP_MANUAL_ONLY (or APPROVE_RELATIONSHIP_SOURCE_3)",
    "scope": "advisory relationship memory only — operator-curated counterparty / broker-house / analyst-firm / peer-set facts for the AEC relationship spine; never sizes, orders, stops, weights, or broker writes (MBI_BEHAVIOR=0); never mints security identity"
  },
  "store": {
    "table": "relationship_memory_facts"
  },
  "writer": "operator",
  "cadence": null,
  "stale_after_hours": null,
  "projection": null,
  "primary_provider": "none",
  "backup": [],
  "retired": [],
  "no_coverage": "refuse_up_front",
  "on_gap": []
}
```

Candidates 1–2, if granted later, get their own rows with a declared single writer module and
the same cognition-only scope — still **no call sites** in the grant PR.

## Why not auto-close

§7A / §17 — agents propose and stop. This file is the proposal (amended 2026-09-20 with draft
row + path choice from main). **No** `data_source_authority.json` mutation. **No** invented
`approved_by=operator`.

---

## Operator decision (recorded)

```
token: DEFER
decided_on: 2026-09-20T14:45:00-04:00
reference: Grok Build session — plan approve (triple-DEFER maturity gap closeout)
effect: continue-park for goal accounting; no production mutation; no build started
```

Prior propose text above is retained for history. A later `APPROVE_*` may reopen this park.


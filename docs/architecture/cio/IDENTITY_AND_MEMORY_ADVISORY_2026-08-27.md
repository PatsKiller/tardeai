# Identity, GUIDs and the memory layer — advisory

**Date:** 2026-08-27
**Asked:** build a system of unique, immutable GUIDs and persistent metadata tags spanning every entity's lifecycle — securities, purchases, events, catalysts — supporting chronological and multidimensional traversal, as an agent's long-term memory. Allocate ~25% of architecture to it.
**Advice:** **do not build it.** It is already designed, to a standard most teams never reach, and it is switched off. The work is promotion and cutover, not construction.

---

## The finding

```
live lineage envelopes ........... 315
carrying a subject_guid .......... 0
entity_type = UNRESOLVED ......... 94 / 94  (100%)
```

Meanwhile, in the same tree:

| Component | What it is | Consumers |
|---|---|---|
| `scripts/lib/security_identity.py` | **The GUID spine.** `issuer_guid` → `security_guid` → `listing_guid` → `ticker_alias_guid`. UUIDv5. *"Ticker is an alias, not the permanent spine."* | 10 |
| `scripts/lib/memory_fact.py` | `MemoryIdentity@v1` + **bitemporal** `MemoryFact@v2`, closed-open intervals, `valid_from`/`valid_to` business time, `tx_from` assigned by the store | 4 — **all of them other memory modules** |
| `scripts/lib/event_identity.py` | `SecurityEvent@v1` catalyst lifecycle: `event_guid(issuer_guid, event_type, period)`, states SCHEDULED / OCCURRED / POST_EVENT / SUPERSEDED / CANCELLED. *"Earnings is not a timeless catalyst."* | **0** |
| `CatalystBinding@v1`, `CatalystRelation@v1`, `CatalystTrace@v1` | The graph edges | 1 file each |
| `ticker_knowledge_graph.py`, `contradiction_graph.py`, `cio_intelligence_fabric.py` | Graph traversal | 11 / 1 / 5 |
| `cio_identity_resolver.py`, `cio_disposition_identity.py` | Alias resolution, immutable decision disposition | **0 / 0** |
| `ADR_DURABLE_STATE_EVENT_SOURCING.md` | **FROZEN 2026-08-08.** Append-only streams, event log authoritative, projections derived and rebuildable, hash-chain integrity, atomicity, crash tests, prohibited patterns | — |

Every property in the request maps to something that exists:

- *unique GUID at creation, immutable for its existence* → `security_identity.py`, UUIDv5, four levels, ticker demoted to alias
- *associated with catalysts — earnings, ratings, news, corporate actions* → `event_identity.py` + the three `Catalyst*@v1` contracts
- *not dynamically recreated on demand; durable with historical continuity* → the FROZEN event-sourcing ADR
- *linear chronological AND multidimensional traversal, backward and forward in time* → bitemporal `MemoryFact@v2` (business time and transaction time are separate axes — this is exactly what lets you ask both "what was true then" and "what did we believe then")
- *unified data graph* → `ticker_knowledge_graph`, `contradiction_graph`, `cio_intelligence_fabric`

**The design is not the gap. The production write path is.** `memory_fact.py` says so in its own docstring: *"SHADOW in-memory store. Production writers are not cut over."*

## Why this keeps happening

This is the fourth instance of one pattern found today alone:

| Component | State |
|---|---|
| `position_truth` hallucination gate (audit C2) | built, tested, never called from live code |
| `complete_to_checkpoint` | computed on every write, read by nothing, false 94/94 |
| `production_root_map.map_all()` | classifies 29 stores, reports `source_tree_coupled_n: 3`, consumed by nothing |
| `security_identity` / `memory_fact` / `event_identity` | specified carefully, 0 production writers |

The failure mode is not poor design. It is **building the contract and never wiring the caller** — and because each artifact passes its own tests, nothing reports a problem. Adding a new subsystem on top would produce a fifth instance.

## Recommendation

### Do not allocate 25% to new construction

The constraint is not build capacity. It is that build capacity already spent is **dark**. Spending more on new persistence architecture before switching on the existing spine compounds the exact problem — you would be adding a second GUID model beside an unconsumed first one.

A standing ~25% allocation to persistence, memory integrity and lifecycle tracking is sound as an *operating* policy. Point it at promotion, cutover, consumer-wiring and the tests that keep them wired — not at new contracts.

### Sequence

**A. Mint at the edge (unblocks everything else).**
Every symbol entering the system resolves once through `subject_from_security(symbol, cik, company, exchange)`; persist the result to the `identity.registry` store (declared in `CanonicalStoreRegistry@v1`, absent from disk until today); stamp `subject_guid` on lineage envelopes. `entity_type` moves `UNRESOLVED → SECURITY` and the 0/315 becomes a real number. **Nothing downstream can be graph-traversed until this exists**, because there is no durable node id to traverse.

**B. Promote `memory_fact` from shadow to authoritative.**
PR #505 (*"non-authoritative Postgres/pgvector production memory shadow"*) is the vehicle and is already open. The storage decision is made — POSTGRES_PGVECTOR, `tstzrange`, FORCE RLS, `AdjudicationReceipt@v1` — from the M2 benchmark. Bitemporality is what delivers the "move forward and backward through the lifecycle" requirement; it is written and unused.

**C. Wire the catalyst graph.**
`event_identity.py` already models exactly the lifecycle asked for, and earnings/ratings/news already flow through the research lane. Connect the producers to `CatalystBinding@v1` / `CatalystRelation@v1` / `CatalystTrace@v1` rather than defining new edges.

**D. Consolidate identity, and fix what I added.**
There are **29** identity/memory/lineage/graph modules; three have zero consumers. Retire or merge them.

That includes my own work from today. `cio_canonical_identity.py` (PR #548) is wired into both lineage arcs and does close the join it was built for — but it derives **80-bit truncated SHA-256 digests** when a **UUIDv5 spine already existed one directory away**. It should be refactored to derive its `event_id` from `security_identity`'s GUIDs rather than from a symbol string. I did not find `security_identity.py` before writing it; that is the same failure this document is about, committed while documenting it.

### What to measure

The signal that this is working is not a dashboard, it is the number already being reported:

```
python scripts/cio_lineage_completion_report.py
    entity_types    {'UNRESOLVED': 94}     ← today
                    {'SECURITY': n, ...}   ← Phase A landed
    with_event_id   0                      ← today
```

## Sequencing note

This supersedes the ordering in `CIO_PIPELINE_DIAGRAM_VERIFICATION_2026-08-27.md`. The causal-trigger wiring (making research completion enqueue a `HERMES_CHALLENGE_RESOLVED` wake) should carry the **root GUID**, not a truncated digest — so Phase A lands first, and the trigger becomes a consumer of the spine rather than another parallel identity scheme.

---

**Sources:** `scripts/lib/security_identity.py` · `memory_fact.py` · `event_identity.py` · `ADR_DURABLE_STATE_EVENT_SOURCING.md` (FROZEN) · `docs/audits/CIO_PIPELINE_DIAGRAM_VERIFICATION_2026-08-27.md` · PR #505 · live lineage at release `89eb12bc`

# 07 · Enterprise Cognitive Graph — the graph as an execution framework

```
Status:      PROPOSED
as_of:       2026-09-27T18:00:00-04:00
Measured at: 8f2a178d5 (origin/main) / served 8f2a178d5-main-exact-phase2-20260927-171004.
Authority:   READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. Nothing here is built.
Package:     cognitive_transformation_20260927 — read 00 first.
Answers:     operator brief §7 (Knowledge Graph as Operating System).
```

## 1. From data to execution

The 09-27 design adds one Postgres edge table over registry GUIDs and projects it from existing stores
`[DOC-CLAIM: §7]` — the right storage decision (no graph database; recursive CTEs cover the traversals).
But it treats the graph as something to *query*. Here the graph is what *drives work*: a change to a
node is an instruction to traverse, and the traversal result is a work list. Today the catalyst graph
(12,584 nodes, 21,901 traces) is traversed only by health checks `[DOC-CLAIM: §2.1 row 7]` and
`cio_graph_impact.graph_impact_for` does one-hop same-sector neighbours `[CODE]` — a graph nobody
executes.

## 2. Node and edge vocabulary

**Nodes** = the GIR entities (02 §3 namespaces). The operator's list maps directly:

| Node | Namespace | Source |
|---|---|---|
| companies | `SEC:` `ISS:` | identity registry |
| events, catalysts | `EVENT:` | catalyst graph, `catalyst_events`, 8-K/10-Q feed (new, 09-27 Wave 2) |
| research | `THESIS:` `EVID:` `Q:` | theses, deltas, research objects |
| decisions | `DEC:` `WAKE:` `COMMIT:` | ledger, wake store, commitments |
| lessons | `LESSON:` `PROC:` | promotion queue (04) |
| agents | `AGENT:` `BELIEF:` `CKPT:` | registry, beliefs, checkpoints |
| workflows, workers | `LANE:` `RUN:` | lane registry, supervisor (06) |
| risks | `RISK:` `CONTRA:` | invalidations, contradictions |
| positions | `POS:` (a relation instance `HOLDS` with attributes) | holdings |
| outcomes | `OUT:` | commitment sweep, `decision_outcomes`, options outcomes |

**Edges** (`gir_edge.relation`), extending the 09-27 set:

```
company:  COMPETES_WITH · SUPPLIES · IN_INDUSTRY · IN_THEME · REGULATED_BY
research: HAS_BULL · HAS_BEAR · HAS_RISK · SUPPORTED_BY · CONTRADICTS · CITES · SUPERSEDES · ANSWERS
market:   AFFECTED_BY · TRIGGERED
decision: DECIDED_ON · USED (evidence/fact/lesson) · PRODUCED (action/commitment) · CAUSED_BY (event/wake) · RESULTED_IN (outcome)
agent:    BELIEVES · CHECKPOINTED · RAN (lane) · ASSIGNED_TO
ops:      SCHEDULES · DEPENDS_ON (lane→lane, lane→store) · BREACHED · RECOVERED_BY
learning: LEARNED_FROM (outcome→lesson) · APPLIES_TO (lesson→subject/class) · APPLIED_IN (decision)
holding:  HOLDS (account→security, with lots ref)
```

Every edge carries `valid_period` (bitemporal) and `source_ref` (the record that asserts it), so a
traversal can be run *as of* any time and every hop is attributable.

## 3. Graph-native by construction

An artifact is graph-native when it cannot be written without its edges. The façade (01) enforces this:

| Write | Edges emitted automatically |
|---|---|
| `commit` of a research delta | `THESIS —SUPPORTED_BY→ EVID`, `EVID —CITES→ url`, `THESIS —SUPERSEDES→ prior`, `Q —ANSWERS→` |
| `create_cio_action` / wake decision | `DEC —DECIDED_ON→ SEC`, `DEC —USED→ {facts, evidence, lessons}` (from the context), `DEC —CAUSED_BY→ {EVENT, WAKE}`, `DEC —PRODUCED→ {COMMIT, ACTION}` |
| outcome settled | `OUT —RESULTED_IN←DEC`, `BELIEF` updated with `LEARNED_FROM` |
| checkpoint (04) | `AGENT —CHECKPOINTED→ CKPT`, `CKPT —USED→ context facts` |
| heartbeat / breach (06) | `LANE —RAN→ RUN`, `RUN —BREACHED→ BREACH`, `BREACH —RECOVERED_BY→ RUN` |
| contradiction adjudicated | `CONTRA` closed with `valid_to`; the losing `EVID` gets `CONTRADICTS` with `valid_to` |
| lesson promoted | `LESSON —LEARNED_FROM→ OUT*`, `—APPLIES_TO→ subjects/classes` |

The memory `USED` edges are the provenance the 09-25 tranche found empty (`evidence_refs` lists 0/82
`[DOC-CLAIM: cio-cognition-tranche3]`); here they cannot be empty because the context is the only
source of facts a decision can cite.

## 4. The graph as execution framework — traversals that produce work

| Trigger (node change) | Traversal | Work produced | Consumer |
|---|---|---|---|
| `THESIS` changed (`thesis.changed`) | `SEC ←HOLDS← accounts`, `SEC ←DECIDED_ON← open DEC`, `SEC —COMPETES_WITH→`, `SEC ←AFFECTED_BY← open EVENT` | holdings review, re-entry re-validation, options review, watchlist refresh, risk review (the 09-27 fan-out, derived from edges instead of a hard-coded list) | wake requests with `subject` set |
| `EVENT` ingested (8-K, catalyst, material change) | `EVENT —AFFECTED_BY→ SEC*` → theses whose `HAS_RISK`/invalidation mentions the event class | research requests, `RESEARCH_REQUESTED` (03 ladder first) | Hermes CIO worker |
| `CONTRA` opened | both `EVID` → the `DEC`s that `USED` them | decision re-check; adjudication item | contradiction queue (03 §6) |
| `OUT` settled | `OUT ←RESULTED_IN← DEC —USED→ {LESSON, BELIEF}` | belief update; lesson confirm/refute; calibration | belief writer; promotion queue |
| `LESSON` promoted | `—APPLIES_TO→ subjects/classes` → open contexts on those | inject into `MemoryContext.lessons` on next open | façade |
| `BREACH` on `LANE` | `LANE —DEPENDS_ON→`, `←DEPENDS_ON←` | which lanes are starved downstream; which store is at risk; ladder level choice | supervisor (06) |
| operator turn on `SEC` | `SEC ←DECIDED_ON← DEC`, open `COMMIT` | disposition update; M3 proof path | wake |

Each traversal is a bounded recursive CTE (depth ≤ 3, `valid_period @> now()`), run by the bus consumer
that already handles the 15 event types `[DOC-CLAIM: 09-27 §4]`. The traversal result is idempotent
work (uuid5 keys, like wakes).

## 5. Projection and queries

- **Projector** `intelligence.gir_edge` is rebuilt from the sources listed in 09-27 §7 plus decisions,
  outcomes, lanes and breaches; incremental via `memory.delta` events. Idempotency and `source_sha`
  per the M2 projector pattern.
- **Queries** (through the façade, never raw SQL from silos):
  `neighbors(guid, relation, depth, as_of)`, `impact(guid, kinds)`, `provenance(guid)` (walk `USED`/
  `SUPPORTED_BY`/`CITES` to leaves), `dependents(lane_id)`, `path(a, b, max_depth)`.
- **Performance envelope:** tens of thousands of nodes, low millions of edges; indexed on
  `(from_guid, relation)`, `(to_guid, relation)`, GiST on `valid_period`. Well inside Postgres on this
  host; no new engine.

## 6. What the graph refuses to be

- Not a source of authority: an edge asserts what a record said; the record is canonical.
- Not a broker path: no traversal produces an order, size, stop or weight (MBI_BEHAVIOR = 0).
- Not a similarity index: "similar" is a retrieval result (03 step 7), never an edge (08-24 model rule
  `[DOC-CLAIM]`).

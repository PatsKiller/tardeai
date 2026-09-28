# 02 · Global Intelligence Record — one envelope for every kind of intelligence

```
Status:      PROPOSED
as_of:       2026-09-27T18:00:00-04:00
Measured at: 8f2a178d5 (origin/main) / served 8f2a178d5-main-exact-phase2-20260927-171004.
Authority:   READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. Nothing here is built.
Package:     cognitive_transformation_20260927 — read 00 first.
Answers:     operator brief §2 (Global Intelligence Record instead of a Company Intelligence Record).
```

## 1. Why a company record is insufficient

The 09-27 Company Intelligence Record composes thesis, risks, catalysts, earnings, prior decisions,
contradictions, analyst opinions, position state and per-field freshness for one `security_guid`
`[DOC-CLAIM: 09-27 §11]`. That covers the *company* class. It leaves outside the record exactly the
things a cognitive platform learns from: what it **decided** (71,847 `cio_decisions`, 64,332 of them
`routine` `[DOC-CLAIM: 09-27 §2.1 row 16]`), what its **agents** believe and how well they are calibrated
(31,106 calibration events, disjoint from commitments `[DOC-CLAIM: 09-07 truth report row 18]`), what it
**learned** (586 lesson candidates, 0 promoted `[DOC-CLAIM: 09-27 §2.1 row 12]`), what it **risks**, what
**happened operationally** (467 crons, 90 timers, 5 queue styles `[DOC-CLAIM: 09-27 §5]`), and what the
**market** did. A company record with no decision record cannot answer "what did we do last time this
thesis weakened, and was it right?"

## 2. The eight intelligence classes and where each one already lives `[CODE]`/`[DOC-CLAIM]`

| Class | Entity kinds | Existing sources (no new stores) | Owner (one writer) |
|---|---|---|---|
| **Company** | ISSUER, SECURITY, LISTING, OPTION_CONTRACT | identity registry, `cio_theses`, catalyst graph, holdings | `accept_research_result` for theses; `mint_identity_registry` for identity |
| **Research** | THESIS, EVIDENCE, RESEARCH_OBJECT, CITATION, QUESTION | `research_thesis_deltas`, `research_objects`, Hermes requests/results, `hermes_external_research`, `ticker_research_graph` | `accept_research_result` (all seven producers route here — 09-27 Wave 2) |
| **Decision** | DECISION, WAKE, COMMITMENT, OUTCOME, ACTION | `cio_decisions`, `cio_wake_jobs`, persistent-wake commitments/outcomes, `cio_action_ledger`, `decision_outcomes`, options decisions in M2 | `cio_action_ledger` / wake store |
| **Agent** | AGENT, BELIEF, CALIBRATION, CHECKPOINT (04) | `agent_maturity_catalog`, `instrument_belief_latest`, `agent_calibration_events`, AEC spines | belief writer; runtime registry (one, after 09-27 Wave 4) |
| **Operational** | LANE, WORKER, RUN, HEARTBEAT, BREACH, RELEASE | `lane_registry`, `agent_heartbeat`, health JSON, release manifests, LLM consumption log | supervisory layer (06) |
| **Lessons** | LESSON_CANDIDATE, LESSON, PROCEDURE | `outcome_to_lesson` candidates, advisory KB, DB lesson tables | lesson promotion queue (one store, 09-27 §10 row 6) |
| **Risk** | RISK, INVALIDATION, EXPOSURE, CONTRADICTION | thesis `invalidation_conditions`, `risk_agent`, contradiction candidates, IPS | risk lane + adjudication queue |
| **Market** | EVENT, CATALYST, MACRO_SERIES, REGIME | `catalyst_events` (126,750), catalyst graph, news/8-K (to be added), macro (no issuer — AGENTS.md §7) | material-change detector (the one kept, 09-27 §10 row 7) |

Macro data never receives an issuer GUID (AGENTS.md "Macro data has NO issuer") — MACRO entities live in
their own namespace.

## 3. One subject key, with namespaces

Registry GUIDs (`security_identity.resolve_identity_spine`, `identity_registry`) are the only company
keys — the 09-27 Wave 1 item, promoted here to a **precondition**: the façade (01) refuses a ticker
string. Non-company entities get UUIDv5 GUIDs in explicit namespaces so that "one key" does not
collapse into "one table":

```
SEC:<security_guid>     ISS:<issuer_guid>     OPT:<contract_guid>
THESIS:<thesis_guid>    EVID:<research_id>    Q:<question_guid>
DEC:<decision_guid>     WAKE:<wake_id>        COMMIT:<commitment_id>   OUT:<outcome_id>
AGENT:<agent_id>        BELIEF:<belief_id>    CKPT:<checkpoint_id>
LANE:<lane_id>          RUN:<run_id>          BREACH:<breach_id>
LESSON:<lesson_id>      PROC:<procedure_id>
RISK:<risk_id>          CONTRA:<contradiction_id>
EVENT:<event_hash>      MACRO:<series_id>     REGIME:<regime_id>
```

The existing `HELD:<tkr>` / `EXIT:` / `WATCH:` keys of `cio_instrument_record.subject_key` `[CODE]` stay
as **views** of `SEC:` (a holding is a relation, not an identity); the beliefs keyed `HELD:<tkr>` are
re-keyed by the 09-27 Wave 1 job, with the old key kept as an alias.

## 4. The entity envelope — the eight fields every entity carries

```yaml
IntelligenceEnvelope@v1:
  guid: namespaced key (§3)
  class: COMPANY|RESEARCH|DECISION|AGENT|OPERATIONAL|LESSON|RISK|MARKET
  kind: entity kind within the class
  memory:        {current_value_ref, fact_ids: [...], m2_version_ref}            # what is believed now
  history:       {versions: n, first_seen, last_changed, supersedes: [...]}      # bitemporal chain (M2 SUPERSEDES)
  contradictions:{open: n, ids: [...], last_adjudicated, state: NONE|OPEN|ADJUDICATED}
  confidence:    {score: 0..1, basis: CALIBRATED|EVIDENCE_COUNT|DECLARED, n_outcomes, calibration_error}
  lineage:       {produced_by: lane_id, release_sha, evidence_refs: [...], derived_from: [guid]}
  ownership:     {writer: lane_id, registry_row, approval_ref}                    # DataSourceAuthority@v2 approval
  freshness:     {as_of, next_due, sla_class, state: CURRENT|THIN|STALE|CONFLICTED|UNKNOWN}
  dependencies:  {depends_on: [guid], depended_on_by: [guid]}                    # edges (07), read at decision time
```

Every field has a rule about absence: `UNKNOWN` is a legal value and its count is a measurement
(AGENTS.md §14). No field is manufactured to look complete.

**Freshness per class** (extends the only staleness mechanism that exists today, the 30-day symbol
thesis SLA `[DOC-CLAIM: 09-27 §2.5]`): COMPANY thesis 30 d; RESEARCH evidence 72 h (matches
`hermes_web_research.reused_objects` window `[CODE]`); DECISION never stale (historical), OUTCOME due
at its checkpoint; AGENT belief until next outcome; OPERATIONAL heartbeat per lane SLA (06); LESSON
until refuted; RISK per invalidation condition; MARKET event immutable, REGIME daily.

**Confidence** is calibrated where outcomes exist (belief writer, `n<5 → unqualified` rule already in
force `[CODE: cio_belief_writer]`), evidence-counted where they do not, and DECLARED (by an LLM or a
person) only with that label.

## 5. Storage: composed read model, one new schema, no new products

```mermaid
erDiagram
  GIR_ENTITY ||--o{ GIR_EDGE : from
  GIR_ENTITY ||--o{ GIR_EDGE : to
  GIR_ENTITY ||--|| GIR_ENVELOPE : has
  GIR_ENTITY {
    text guid PK
    text class
    text kind
    text source_store
    text source_ref
    timestamptz first_seen
  }
  GIR_ENVELOPE {
    text guid PK
    jsonb memory
    jsonb history
    jsonb contradictions
    jsonb confidence
    jsonb lineage
    jsonb ownership
    jsonb freshness
    timestamptz projected_at
    text projection_version
    text idempotency_key
  }
  GIR_EDGE {
    text from_guid
    text to_guid
    text relation
    tstzrange valid_period
    text source_ref
  }
```

- **Projected, not authored.** The three tables are projections from the canonical stores, built by
  the same idempotent pattern as the options M2 projector and the M2 shadow migration design
  (`source_event_id`, `source_sha`, `projection_version`, `idempotency_key` `[DOC-CLAIM: M2_PRODUCTION_SHADOW_MIGRATION_DESIGN_2026-08-24]`).
  The canonical stores keep their single writers; the projection has zero authority.
- **Where.** One new schema `intelligence` on the production Postgres 17 (766 tables; pgvector 0.8.6
  present `[VERIFIED: read-only `SELECT extname, extversion FROM pg_extension` on :5432, 2026-09-27]`).
  A new schema is an infrastructure approval (11, 12). No graph database, no document store, no cache
  layer: 07 shows recursive CTEs over `gir_edge` cover every traversal the platform needs.
- **Bitemporal.** `history` and `as_of` reads delegate to M2 (`memory_m2_v2.query_now` `[CODE]`), which
  moves from the :55432 shadow to production under the existing `memory_prod_cutover.apply` `[CODE]`
  — an operator/infra approval already known to be blocked on role creation `[DOC-CLAIM: memory 09-19]`.
- **Cost of the projection.** The stores involved total under 2 GB of JSONL and a few million
  Postgres rows `[DOC-CLAIM: 09-27 §2.1]`; a full rebuild is a batch job, incremental is a bus consumer.

## 6. Read API (served by the façade, 01)

```python
get_intelligence(guid, *, classes=None, as_of=None, depth=0)  -> {envelope, facts_by_class, edges[:depth]}
what_changed(guid, since)                                      -> [MemoryDelta@v1]
find(class, kind, filters, as_of=None)                         -> [guid]
contradictions(guid)                                           -> [Contradiction@v1]
lineage(guid)                                                  -> provenance chain to evidence
```

Every surface listed in the 09-27 V/Visa test as "reads its own raw store" (holdings advisory, CIO
decision engine, analyst, portfolio review, risk `[DOC-CLAIM: 09-27 §3]`) migrates to `get_intelligence`
in the 09-27 Wave 1–2 sequence; Ring 1 (01) makes the migration irreversible.

## 7. Write API — one door per class

| Class | Write function (existing or adapter) | Precondition |
|---|---|---|
| Company/Research | `accept_research_result` (+ adapters for the six other producers, 09-27 Wave 2) | `RetrievalReceipt@v1` (03) |
| Decision | `cio_action_ledger.create_cio_action`, wake store | `context_id` (01 Ring 2) |
| Agent | `cio_belief_writer.apply_belief` only (AGENTS.md §13.4) | outcome settled |
| Operational | supervisory layer (06) | heartbeat row |
| Lessons | promotion queue → `Procedure@v1` (04) | operator promotion |
| Risk | risk lane; contradiction adjudication (03 §6) | judge receipt |
| Market | material-change detector (one) | identity resolved or `UNRESOLVABLE` (AGENTS.md §17A) |

Adding a writer to an authoritative store is operator-only (AGENTS.md §17, `DataSourceAuthority@v2`
approval row) — each adapter is an item in 11.

## 8. How this unifies rather than adds

A 4.7 system does not have a company record and a decision log and a lessons KB and a health JSON that
happen to share a host. It has one envelope, one key discipline, one door in (01), one door out (§6),
one graph over all of it (07), and one supervisor that reads the OPERATIONAL class the same way the
CIO reads the COMPANY class (06). The seven-plane taxonomy of the 08-24 memory architecture
`[DOC-CLAIM]` is preserved: the planes are *how memory is layered*; the classes are *what it is about*.

# CIO Completeness Measurement

`scripts/cio_completeness_measurement.py` emits
`CIOCompletenessMeasurement@v2`. With `--write`, it also writes
`docs/_evidence/cio_completion/completeness_20261002.json`.

Spec step 13 asks for `produced_not_surfaced = 0` for operator-relevant CIO
capabilities. The 2026-10-02 result below does **not** reach zero: 13
operator-relevant schemas are still not surfaced. They are named at the end of
this page, each with the reason it is still missing.

## Definitions (enumerated, not labelled by hand)

- **produced** is the union of three sets:
  - `route:` every CIO-family backend GET route that the API census parsed,
    with alias spellings collapsed into one route;
  - `capability:` every capability-coverage row in the operator evidence;
  - `schema:` every `Name@vN` contract defined in `scripts/lib/cio_*.py`.
    A definition is any `*SCHEMA*` constant, including a bare `SCHEMA = ...`,
    or a `schema` / `schema_version` / `contract` key. Literals inside the rows
    of a module-level producer catalog name another module's contract. They
    are reported as `catalog_references` and are not counted as definitions.
- **operator_visible** depends on the item type:
  - A **route** counts in two cases. The first is when a component in the
    routed pages' import closure fetches it and does not discard the result.
    The second is when the route handler's output (its envelope, or one key
    below it) is embedded in a consumed payload at a key path that the
    consumer reads. That case is reported as `EMBEDDED_IN_CONSUMED_PAYLOAD`.
  - A **capability** row counts when `/api/v3/cio/operator-evidence` is
    consumed by a component that renders capability rows.
  - A **schema** counts when its own block lands at a key path that the
    consumer reads, segment by segment. `scripts/cio_payload_flow.py` follows
    the payload flow transitively (handler → api getter → lib builder) and
    keeps the key path at each step. A schema that is fetched but never read
    is listed under `fetched_but_ignored`, not as visible. The consumer is the
    fetching file plus any local JSX child it hands the fetched value to as a
    prop.
  - A **record schema** is stamped by a writer into a store and read back by a
    reader that never names it. It counts only through a `record_edge` in the
    classification file. The measurement checks every link of that edge (see
    below) and reports the result as `RECORD_EDGE_VERIFIED`.
- **produced_not_surfaced** is the difference between the two sets, listed by
  name. Each of these items must have an entry in
  `config/cio_surface_classification.json`:
  - `NOT_OPERATOR_RELEVANT`, with a specific reason;
  - `RETIRE_CANDIDATE`, with a specific reason;
  - `SURFACE`, which marks it operator-relevant.

  An item that is unclassified, or classified `SURFACE` but not yet visible,
  counts in **produced_not_surfaced_operator_relevant**, which has a target of
  0. Each reason must be at least 60 characters and unique. Entries that are
  stale (no longer produced, or already surfaced) fail the gate.
- **surfaced_not_runtime_proven** lists the surfaced capability rows whose
  runtime state is not `LIVE`. The `ui_label` is the state that the
  CoverageRow renders. The list also includes research artifacts that are not
  `USED_IN_JUDGMENT`. **surfaced_runtime_unmeasured** lists the surfaced
  routes and schemas. This measurement has no runtime capture for them, so
  they are never counted as `LIVE`. In the UI, the new panels show each
  block's own `state` / `status` / `truth_quality` / `evidence_class` and its
  `source_as_of` / `composition_as_of` verbatim. A missing label is shown as
  `NOT_IN_PAYLOAD`.

### Record-edge checks

For each `record_edge`, all of the following must hold:

1. The route is consumed.
2. The reader function lands at a prefix of `path` in that route's payload.
3. The consumer reads every segment of `path`.
4. The writer function names the schema, as a literal or a module constant.
5. The store-file literal appears both on the reader or route side and on the
   writer side, or in a module that calls the writer.

## Result (2026-10-02, prod `data/cio` read-only)

| Kind | Produced | Operator visible | Produced, not surfaced | …of which operator-relevant |
|---|---|---|---|---|
| Routes | 48 | 44 | 4 | 0 |
| Capabilities | 23 | 23 | 0 | 0 |
| Schemas | 196 | 71 | 125 | 13 |
| **Total** | **267** | **138** | **129** | **13** |

The 129 items that are produced but not surfaced break down as follows:

| Classification | Count |
|---|---|
| `NOT_OPERATOR_RELEVANT` | 72 |
| `RETIRE_CANDIDATE` | 44 |
| `SURFACE` (operator-relevant, not yet surfaced) | 13 |
| Unclassified | 0 |

Visible items by visibility method:

| Method | Items |
|---|---|
| Direct fetch or payload flow | 123 |
| `EMBEDDED_IN_CONSUMED_PAYLOAD` | 12 |
| `RECORD_EDGE_VERIFIED` | 3 |

The 12 embedded routes are `/api/v2/cio/capital-plan` and the 11 brain
sub-routes that `/api/v3/cio/brain` embeds and CioBrainPanel reads. The 3
record edges are `CIOWeeklyLearningReview@v1`, `CIOTelegramSendReceipt@v1` and
`ResearchImpact@v1`. There are 117 surfaced items that are not runtime-proven:
13 capabilities labelled `PARTIAL`, 2 labelled `DARK`, and 102 research
artifacts labelled `UNKNOWN`. Each is shown with its label.

### What changed against the earlier figures

| | Produced | Operator visible | Produced, not surfaced |
|---|---|---|---|
| Earlier | 204 | 62 | 142 |
| Now | 267 | 138 | 129 |

The earlier count had both false negatives and false positives:

- **Produced was undercounted by 65 schemas.** The definition regex missed a
  bare `SCHEMA = "X@v1"` constant, and three catalog-row references counted as
  definitions.
- **Visible was overcounted.** One delegation level credited every schema in
  a delegated builder to the whole response. That included 13 home and product
  blocks that no component read, such as `CIONotificationBlock@v1`,
  `CashSleeveLetter@v1` and `CIOIdentityCoverage@v1`.
- **Brain sub-projections were undercounted.** The `brain/*` sub-projections
  sit two or more calls deep, so they were reported as not surfaced even
  though CioBrainPanel renders them.

## Surfaced in this change (all read-only)

| Where | What it renders | Source |
|---|---|---|
| CIO › Evidence & Comms › Full brain › Brain projections | Data health and store inventory, model-task performance, envelope provider status, office situation scan, intelligence coverage matrix, producer inventory, latest weekly learning review | Brain payload. The situation scan, coverage matrix and inventory blocks were already computed in `get_cio_brain_v1` / `get_intelligence_lifecycle_v1` and are now returned. |
| Same tab › Maturity contract & policy provenance | Maturity contract, policy provenance, and the `OperatorPolicyRegistry@v1` block behind the provenance view | `/brain/maturity-contract`, `/brain/policy-provenance` (the registry is now returned) |
| CIO › Decisions › Office home projections | Operator product view, record narrative coverage, graph impact (S6 plus items), notification block with `NotificationPolicy@v1` decisions, strategy and research context, cash-sleeve letter | Already in `/api/v3/cio/home` |
| CIO › Research › Investment books › Product health & learning | Identity coverage, holdings data quality, Surface-A, checkpoint lineage, research verdict counts, failure histogram, provisional lessons (`LessonCandidate@v2`), thesis changes today, thesis decision gate, held-instrument ids | Already in `/api/v3/cio/investment-product` |
| CIO › Research › Thesis & delegation | Desk thesis, desk note, open actions, open plans (router-relative plan links), delegation and Hermes challenges, data-broker snapshot, sector opportunities | `/thesis`, `/desk-note`, `/actions`, `/plans`, `/delegation`, `/snapshot`, `/api/v2/cio/sector-opportunities` |
| CIO › Research › Universe theses › Thesis research context | Ask-thesis, thesis-research-context, RI pipeline (dry), research proposal | Loaded only when the operator presses Load. Never polled. |
| CIO › Evidence & Comms › Learning cockpit › CIO record ledgers | Outcome checkpoints and observations, lesson binds, thesis revisions and change cards, held-book thesis coverage, instrument records and beliefs, belief-writer receipt, reassessments, linked feedback and feedback ingests, goal predicates and verdicts, operator-product envelope, stance-hold summary, CIO reconciliation | New `GET /api/v3/cio/records` (`scripts/lib/cio_record_ledgers.py`: bounded 512 KB tail reads, rows filtered by each contract's own schema, `PRESENT` / `EMPTY` / `MISSING`) and `/api/v3/intelligence/reconciliation` |
| Agents › Maturity › Learning | `CIOOutcomeMaturity@v1` disposition outcomes | Already in `/api/v3/maturity/learning` |

Every new panel follows the same rules:

- It is closed by default and fetches only while open.
- It polls no faster than every 300 s.
- It shows `Loading…`, `UNAVAILABLE — <error>` or `NO PAYLOAD` instead of an
  endless spinner.

## Not operator-relevant (72) and retire candidates (44)

The per-item reasons are in `config/cio_surface_classification.json` and in
the JSON artifact (`not_operator_relevant`, `retire_candidates`).

- **Not operator-relevant.** These fall into a few groups:
  - transport and dedupe receipts;
  - retry and provider journals;
  - identity and lineage plumbing;
  - plan-hygiene and migration job receipts;
  - research-gate and wake internals;
  - agent context packs;
  - P2 diligence census output;
  - the Cursor fabric map (`/api/v3/cio/r71-fabric-map`).

  Where an operator-facing projection exists, the reason names it.
- **Retire candidates.** Each of these is one of three things:
  - a builder with no production caller (grep of `scripts/`, tests excluded);
  - a module imported only by `check_dark_contracts.py` or by a one-off wave
    report;
  - a duplicate route: `/api/v2/cio`, `/api/v3/cio` (composite), and the GET
    `/api/v3/cio/decision/{key}` that ignores `{key}`.

  Nothing was deleted (AGENTS rule 6).

## Still operator-relevant and not surfaced (13)

| Schema | Why it is still missing |
|---|---|
| `CIOAgentBrief@v1` | No prod store carries it. Built transiently for Telegram; it needs persistence and a route first. |
| `CIOAttentionAnswer@v1` | Same: no prod store, built transiently for Telegram. |
| `CIOAdvisoryMessage@v1` | Same: no prod store, built transiently for Telegram. |
| `CIOAdvisorySynthesis@v1` | Same: no prod store, built transiently for Telegram. |
| `CioComposedNarrative@v1` | Same: no prod store, built transiently for Telegram. |
| `CioModelNarration@v1` | Same: no prod store, built transiently for Telegram. |
| `CioWakeComposition@v1` | Same: no prod store, built transiently for Telegram. |
| `CIOWhatChanged@v1` | Same: no prod store, built transiently for Telegram. |
| `GrokCritique@v1` | Same: no prod store, built transiently for Telegram. |
| `InvestmentDecision@v1` | Same: no prod store, built transiently for Telegram. |
| `AlertQuality@v1` | Same: no prod store, built transiently for Telegram. |
| `InvestmentIntelligenceCard@v1` | Only in older notification-outbox rows. |
| `BuyReadyInstitutionalPacket@v2` | Shown on Re-Entry › Entry alerts, which is outside the five measured CIO pages. |

## Run

```bash
TRADEAI_CIO_DIR=<cio data dir> python3 scripts/cio_completeness_measurement.py --write
```

The gate is `tests/test_cio_payload_flow_20261002.py`. It fails when a new
produced item is unclassified, when a classification is blanket, duplicated or
stale, or when a record edge stops verifying.

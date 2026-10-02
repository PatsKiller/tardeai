# CIO Completeness Measurement

`scripts/cio_completeness_measurement.py` emits
`CIOCompletenessMeasurement@v2`. With `--write`, it also writes
`docs/_evidence/cio_completion/completeness_20261002.json`.

## Definitions (enumerated, not labelled by hand)

- **produced** is the union of three sets:
  - `route:` every CIO-family backend GET route that the API census parsed,
    with alias spellings collapsed;
  - `capability:` every capability-coverage row in the operator evidence;
  - `schema:` every `Name@vN` contract literal defined in `scripts/lib/cio_*.py`.
- **operator_visible** depends on the item type:
  - a route counts when a component in the routed pages' import closure
    consumes it (from the census consumer mapping);
  - a capability row counts when `/api/v3/cio/operator-evidence` is consumed
    by a component that renders capability rows;
  - a schema counts when the handler of a consumed route, or its first
    delegated lib function, emits it.
- **produced_not_surfaced** is the difference, listed by name. It is not tuned.
- **surfaced_not_runtime_proven** lists surfaced capability rows whose runtime
  state is not `LIVE`. The `ui_label` is the state the CoverageRow renders.
  The list also includes research artifacts that are not `USED_IN_JUDGMENT`.
- **surfaced_runtime_unmeasured** lists surfaced routes and schemas. This
  measurement has no runtime capture for them, and they are never counted as
  `LIVE`.

## Result (2026-10-02)

Evidence was read from the prod `data/cio` (read-only). Counts:

| Kind | Produced | Operator visible | Produced, not surfaced |
|---|---|---|---|
| Routes | 46 | 17 | 29 |
| Capabilities | 23 | 23 | 0 |
| Schemas | 134 | 21 | 113 |
| **Total** | **203** | **61** | **142** |

There are 189 surfaced items that are not runtime-proven:

- 22 capabilities labelled `PARTIAL`;
- 1 capability labelled `DARK`;
- 166 research artifacts labelled `RETRIEVED`.

The 29 routes that are produced but not surfaced:

- `/api/v2/cio`, `/api/v2/cio/capital-plan`, `/api/v2/cio/sector-opportunities`
- `/api/v3/cio`, `actions`, `ask-thesis/*`, `delegation`, `desk-note`, `plans`,
  `r71-fabric-map`, `snapshot`, `thesis`, `thesis-research-context/*`,
  `thesis-research-proposal`, `thesis-ri-pipeline/*`
- `decision/*` (the GET dispositions branch)
- 13 `brain/*` sub-projections: capital-plan, data-health,
  intelligence-lifecycle, learning-cockpit, learning-review, market-context,
  maturity-contract, methodology, model-performance, policy-provenance,
  portfolio-state, portfolio-thesis, seasonality

The schema list is in the JSON artifact. It over-reports schemas that are
nested more than one delegation level deep inside a consumed payload, such as
the `brain/*` sub-states inside `CIOBrainSnapshot@v1`.

Run:

```bash
TRADEAI_CIO_DIR=<cio data dir> python3 scripts/cio_completeness_measurement.py --write
```

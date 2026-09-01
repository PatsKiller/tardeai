# CIO Research Live Wire

Status:      ACTIVE
as_of:       2026-08-15T08:58:06-04:00
Measured at: efcc51365 / not measured

Live hook: `retrieve_research_context` now attaches a governed Almanac
decision-use audit (`governed_audit` + `governed_almanac`) before the
capital-plan / strategy-context envelope is composed.

- Authority remains `READ_ONLY_ADVISORY`
- Fail-soft if the governance package or fixture is missing
- Never creates TRIM / standalone sell
- Influence cap ≤10%
- Does **not** rewrite `rag_retrieval`, Hermes, or `kb_lessons`
- Does **not** flip `STOCK_ALMANAC_INTEGRATION` or
  `RESEARCH_GOVERNANCE_ACCEPTANCE` to PASS (honesty: this is a live hook,
  not a claim that FULL research is production-accepted)

Exact-main deploy overlays `tests/fixtures/us_equity_monthly_sample.csv`
and `config/cio_research_source_catalog.json` so the live release can
reproduce Almanac layers.

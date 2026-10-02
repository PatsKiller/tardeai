# CIO / Hermes / Research Intelligence links

The investment-office CIO surface and the engineering-oriented Control Plane
remain separate products. Their evidence is connected by explicit links.

## Operator paths

- A CIO decision with a symbol links to its direct `decision_id` lineage and to
  Research Intelligence filtered to that symbol.
- Research Intelligence accepts `symbol`/`q` query context and links back to
  CIO Research. Hermes-originated items also link to Hermes Provenance.
- Hermes exposes CIO Research and Research Intelligence entry points from its
  operator header.

All links are router-relative under the `/v3` basename. No page claims that a
link proves the underlying artifact was used in judgment; provenance state is
rendered by the CIO evidence contract.

## Hermes research ↔ CIO decisions (HermesResearchLinks@v1)

`GET /api/v3/hermes/research-links?limit=&result_id=&decision_id=&symbol=` is a
read-only reverse index (`scripts/lib/cio_cross_surface_links.py`). It answers
four questions:

- **Hermes result → CIO decisions that consumed it.** The sources are:
  - `cio_research_impacts.jsonl` (`ResearchImpact@v1`: `result_id` →
    `new_product_id`, written by `cio_product_reassessment` when a completed
    result re-composes the CIO product);
  - `intelligence_lineages.json` (`research_result_ids` → `decision_id`,
    `advisory_use.product_id`);
  - the current `cio_investment_brief.json`
    (`research_cases[].hermes_result_id`).

  The producer already records consumption at this point, so no new write
  field was needed.
- **Result → thesis.** The lineage `thesis_id` and the current product's
  book/verdict `thesis.source_refs` → `symbol_thesis_version`.
- **Result → symbol.** The result row's `symbol`.
- **Result → workflow.** A prefiltered, bounded tail scan of
  `cio_workflow_lineage.jsonl` research nodes.

A link is `RECORDED` only when a store row names both ids. Otherwise it is
`NOT_RECORDED`, and nothing is inferred from symbol or time. Large stores are
read through bounded tail windows. The response reports each window and
whether it was `complete`.

These pages render the links:

- **Hermes › Provenance**, filterable by `?symbol=` / `?result_id=`.
  `/hermes?tab=Provenance` deep links now select the tab.
- **Hermes › Research**, which shows the latest results.
- **Research Intelligence**, when it is opened with `?symbol=` or
  `?decision=`.

The links go to `/cio?tab=evidence-comms&sub=decision-lineage&decision=<id>`,
`/research-intelligence?symbol=` and `/research-intelligence?q=<thesis>`. All
of them are router-relative.

At composition on 2026-10-02, 198 of the latest 200 results carried a recorded
decision link, and 15 carried a recorded thesis link.

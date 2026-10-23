# Ask the CIO — Phase 9: the research pipeline

```
Status:      DRAFT (code merged-ready; lane at SHADOW in a stacked PR, its health contract DRAFT awaiting owner review)
as_of:       2026-10-23T14:05:00Z
Measured at: origin/main 53aa1b619 + branch feat/ask-cio-phase9-research-20261023
```

Operator approval: 2026-10-23 ("Ask the CIO", Phases 8–11 come after release-train phases 0–7). This
document covers Phase 9 only. Another agent builds Phase 8 (the ask bar and the questions page), Phase 10
(auto-tracking) and Phase 11 (re-answer on material change). That agent also owns the shared contract,
`scripts/lib/cio_ask_contract.py` (`AskRequest@v1` / `AskAnswer@v1`).

## What it does

One `AskRequest@v1` produces one `AskAnswer@v1` prospectus per security. Each prospectus has:

- 3m / 6m / 12m bear / base / bull scenarios
- the street target range
- dated catalysts
- risks
- what would change the view
- sizing context, only for quantities the operator named
- sources with `as_of`
- confidence
- model dissent

| Piece | Where |
|---|---|
| Contract entry point (the deep path) | `scripts/lib/cio_ask_research.py` → `run_deep_research(AskResearchContext) -> AskAnswer@v1` (`DEEP_RESEARCH_ENTRYPOINT`) |
| Library core (lane and tests) | `run_research(request, …)` → the internal research result; `to_contract_answer` maps it |
| Host executor (the n8n lane `cio-ask-research`) | `scripts/cio_ask_research.py` (`--dry-run` = shadow) |
| Tests (hermetic) | `tests/test_cio_ask_research.py`; CI gate `config/ci_gates/cio_ask_research_phase9_20261023.json` |

### Pipeline

1. **Entity resolution.**
   - A symbol resolves through `cio_subject_guid.lookup_identity_envelope` to a `security_guid`.
   - A name goes through `company_name_index.resolve_name` first. That index is built from the stored broker
     instrument feed, and it never guesses.
   - If the name does not resolve, the company is a **private / unlisted tracked entity**. Its key is the
     contract's deterministic `private_entity_guid(name)` (`ent_…`), with `symbol = None`. No ticker is invented.
     Its status is `TRACKED_PRIVATE_UNREGISTERED`, because registering it in the identity table is a store write
     (§26.6, operator).
   - An unresolved symbol gets "identity unresolved" and no record.
2. **Parallel gather.** Every (entity × source) pair runs in a thread pool under its own timeout.
   - A timeout, an exception, or a fact without `as_of` or a citation becomes a named gap (`TIMEOUT`, `SOURCE_ERROR`,
     `FACT_REJECTED`, `NO_DATA`, `NOT_APPLICABLE_PRIVATE_ENTITY`). Nothing is dropped silently.
   - A hung source does not hold the answer, because the pool is abandoned on return.
3. **LLM panel.**
   - One prompt goes to every member, and it is the same for all of them; the `prompt_sha` per member proves it.
   - `local_only` facts (holdings, trades) are excluded from the prompt (§2A), and the prompt passes
     `sanitise_for_external`, whose redacted copy is always used.
   - Each member returns a closed JSON shape. Disagreement is kept: `dissent[]` holds stance dissent and
     per-horizon anchor dissent.
4. **Synthesis.**
   - Every scenario price is a *fact's value*, and the anchor is cited with its `as_of`. Anchors come from:
     - a panel majority, where the anchor must be a fact_id that carries a number;
     - for 12m, the street low / mean / high.
   - A horizon with no sourced anchor says `NO_SOURCED_ANCHOR (no number invented)`.
   - Model sentences carrying a number that matches no fact are dropped (`ungrounded_log`). Numbers printed in a
     sourced claim count as sourced.
   - When two street sources disagree, both are shown in `conflicts[]` (§26.5).
5. **MBI guard.**
   - Model output keys in `BEHAVIOR_FIELDS` (and sizing synonyms) are removed.
   - Sentences that size, order, stop or weight are removed: a sizing regex plus `execution_language.find_imperative`.
   - Every removal is logged in `mbi_strip_log`.
6. **Sizing.**
   - `sizing_context` is arithmetic (notional, and scenario P/L per horizon) on quantities the operator named, for
     example "100 or 1,000 TSLA". It is `egress: local_only`.
   - The CIO never picks a quantity.
   - `risk_budget_inputs` collects the sourced inputs a later risk-budget calculation would need: portfolio value,
     stop reference, concentration limit, held flag. It **does not compute one**.
   - `size_suggestion` is always `None` with policy text, until AGENTS >= 21.0.0 is ACTIVE (operator decision
     pending, 2026-10-23).
7. **CIO memory (no silos).**
   - Every gathered fact and the final answer are appended through `CIOEnvelopeIntegrator.integrate_envelope`.
   - They are keyed by `security_guid`, or by `entity_guid` for a private tracked entity.
   - Predicates are the contract's memory kinds `ask.source` (one per fact) and `ask.answer_version`. On the deep
     path the core (`cio_ask_core`) appends `ask.answer_version` itself, so Phase 9 appends only `ask.source`.
   - Writes go through the integrator in dry-run mode unless `CIO_ASK_MEMORY_APPLY=1` (deep path) or
     `--apply-memory` (lane) is set. A dry run records nothing in the idempotency ledger.
   - Appends are idempotent: a deterministic `event_key` per event, plus a local ledger. A refused envelope is
     reported in `memory_receipt.refused` and never retried blindly.
   - Sizing never enters memory.
   - On the n8n path (`origin = n8n`) model-derived text is not written to memory (§23.4); only the sourced
     skeleton is.

### Sources wired (all read-only; existing readers only)

| Family | Source | Reader |
|---|---|---|
| internal | CIO prospect record | `data_broker.cio_prospect.get_prospect` (empty until the cio_prospect migration is granted) |
| internal | held flag (no qty, no $) | `data_broker.watch_domains.held_positions(surface="cio_ask")` — `local_only` |
| internal | thesis | `symbol_thesis_attach.thesis_fields_for_symbol` |
| internal | catalysts | `data_broker.catalyst_record.get_symbol_catalysts` (`catalyst_events`) |
| internal | Hermes research | `data_broker.subject_research.get_subject_research` |
| internal | past alerts | `alert_events` (id, type, severity, created_at) |
| internal | past fills | `trade_transactions` (action, date only; no account, qty or price) — `local_only` |
| market | reference price | `data_broker.market_quote.get_price_batch(skip_live=True)` |
| street | targets low / mean / high / count | `data_broker.analyst_detail.get_analyst_targets` + `data_broker.analyst_rollup` (pro_analyst) |
| sec | 8-K disclosures | `sec_filing_documents.load_primary_disclosures` |
| sec | XBRL fundamentals | `fundamentals_feed.card_block` |
| news | stored articles | `data_broker.catalyst_record.get_symbol_news` (`news_articles`) |
| web | governed search | `search_router.route_query(caller="web_research")`: class `operator`, existing cache / free tiers / Brave budget |
| LLM | DeepSeek (flash), Grok OAuth, ChatGPT OAuth | `governed_cloud_generation.generate_cloud(process_id="cio_ask_deep_research", lanes=(lane,))`; through the bridge when `TRADEAI_LLM_VIA_BRIDGE` is on |
| LLM | Claude oversight | **NOT AVAILABLE**: no governed Claude process exists for this path (bridge and registry have none). Recorded, not improvised. |

### Read-only evidence `[VERIFIED]` 2026-10-23

The full pipeline ran against live stores, with the web source and the panel off (no spend):

```
partial True refusals [{'member': 'deepseek', 'reason': 'PROCESS_NOT_REGISTERED'}, {'member': 'grok', ...}, {'member': 'chatgpt', ...}]
street [128.11, 600.0] 12m {'bear': 128.11, 'base': 392.42, 'bull': 600.0}
sizing [(100.0, 37043.5), (1000.0, 370435.0)]
cited problems []
conf medium 0.617
risk_budget missing ['concentration_limit', 'portfolio_value', 'stop_reference']
```

The sources produced these counts: sec.filings 7, sec.fundamentals 6, internal.catalysts 5, hermes_research 5,
trades 5, street 4, news 4, quote 1, holdings 1. The gaps were `cio_prospect` (NO_DATA: the migration is not
applied), alerts (NO_DATA) and thesis (NO_DATA). The answer JSON is at `~/.cache/rtc/ask_p9_tsla_answer.json`.

## Cost

- **Per question:** `CIO_ASK_RESEARCH_PER_QUESTION_USD`, default **$0.30**, estimated per member before each call.
- **Per day:** `llm_consumption.check_cost_cap(process_id, projected_usd, global_cap)`. This is the process
  `daily_cost_cap_usd` plus the global cap (`LLM_GLOBAL_DAILY_USD_CAP`, $2.00 today) minus lane floors. The
  in-process call reserves and settles the real spend (`gate_and_generate`).
- **Fail closed:** an unregistered process (`PROCESS_NOT_REGISTERED`) or a ledger error (`BUDGET_UNAVAILABLE`)
  refuses. A refused member makes the answer `partial` and names the reason. The sourced part is still answered.

## Operator approvals needed (§17)

1. **Spend cap and process registration.** Register `cio_ask_deep_research` (the contract's
   `ResearchBudget.process_id`) in `config/llm_process_registry.json`,
   plus `governed_process_routes` and the bridge map if it goes through the bridge. The proposed row is
   `lane_policy: ensemble`, `allowed_lanes: [deepseek-flash, grok, chatgpt]` and `daily_cost_cap_usd`.
   The proposed research cap was $5/day, but **the global cap is $2.00/day** (§12). A $5 process cap cannot be
   reached without a §12 global-cap decision. The operator picks the number. Until then every panel call is refused.
2. **Lane contract review.** The `cio-ask-research` health contract is DRAFT (stacked PR). An agent cannot mark
   it REVIEWED (§23.19), and `check_n8n_health_contracts` reports `DRAFT_NOT_GRANDFATHERED` until the owner does.
3. **Holdings reader.** Add `cio_ask` to `positions_store.approved_readers` in `config/data_source_authority.json`
   (§26.2). Until then `held_positions` serves the held flag from its fallback.
4. **Questions/answers store row** (Phase 8, §26). The executor writes answers only to the `--out-dir` it is given,
   and it creates no store.
5. **Memory apply.** The executor uses the integrator in dry-run mode unless `--apply-memory` is set. Live memory
   writes start when the lane leaves shadow.

## Contract reconciliation

The shared contract landed on `feat/ask-cio-phase8-11-20261023` (commits 3eed4d4bc and 50fbd7059). It is not on
`main` yet. The module imports it lazily:

- `run_deep_research(ctx)` returns a contract `AskAnswer`, and that answer passes `validate_answer` (tested).
- Without the contract, `run_deep_research` raises `ImportError`. The core then treats the deep path as
  `deep_pending`.
- The two adapter tests `importorskip` the contract, so they start running when it merges.

These items are aligned with the contract:

- the process id `cio_ask_deep_research`
- `private_entity_guid`
- the memory kinds
- the `quick`/`deep` depths
- `EntityRef` inputs (pre-resolved entities are trusted)
- `NamedQuantity{amount, unit}`, including `usd`
- the MBI guard: the contract's patterns run inside this module's strip as well

**`sizing_context` is left empty in the contract answer.** The core computes it on the host. Phase 9 hands over
`provenance.reference_prices` with each value's `as_of` and `fact_id`.

**Contract gaps for the contract owner:**

1. `StreetTarget` has `median`, but the sources publish a **mean**. `median` is left `None`, and the mean is in
   `provenance.street_mean`. Proposal: add `mean` to `StreetTarget`.
2. `Scenario` has no citation field. The anchor and its `as_of` are written into the narrative, and the full
   facts are in `provenance.facts`.

## Findings

- **§23.4 versus no-silos.** §23.4 forbids writing model output from an n8n path to a memory store. The operator's
  no-silos rule wants every answer in CIO memory. This pipeline takes the restrictive reading: on the n8n path
  only sourced facts and the answer skeleton go to memory. The in-process deep path writes the full answer.
- **There is no prose MBI scanner at the bridge.** Step 9b scans keys only, and only for `n8n_*` processes. This
  module strips prose itself.

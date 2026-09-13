# Gap Resolution — when the answer is stale or missing, go find out

```
Status:      ACTIVE
as_of:       2026-09-13T18:00:00-04:00
Measured at: e8a173e7d (origin/main, PR #994 merge) / live pin not measured
```

**Status:** SHIPPED 2026-09-13 (One Source of Truth, Phase 7; integrated in `fee3e7737`, merged in
PR #993/#994) · **Authority:** READ_ONLY_ADVISORY
**Code:** `scripts/lib/gap_resolver.py` · desk wiring `scripts/lib/cio_operator_desk_loop.py` ·
projection hook `scripts/lib/data_broker/gap_hook.py` · monitor `scripts/check_gap_resolution.py`
**Registry:** `config/data_source_authority.json` → `domains[].on_gap` (rendered in
`docs/SOURCE_OF_TRUTH.md`; governed by `AGENTS.md` §7A)

**Corrections kept in (AGENTS.md §14).** The first version of this document said the registry "is owned
by a parallel agent and is not edited here" and that the per-domain chains lived only in
`docs/implementation/sot/phase7_registry_patch.json`. That was true in the Phase 7 worktree and stopped
being true at `fee3e7737` (integration): every domain's `on_gap` is now in the registry itself, the
patch file is the historical proposal, and the monitor's lane and timer are declared (not installed —
see below). The text below reflects the merged state.

## The operator's question

> "what happens when the information is stale or it doesn't meet the operator's need — how does it
> find out through multiple different vectors: one for Hermes research, two for like DeepSeek
> curation, etc."

Before Phase 7: it mostly didn't. A desk or projection that met stale or missing data served the old
value, opened a pending that might never close, or said "no coverage". The pieces existed
(`gather_tradeai_evidence`, `_enqueue_hermes_research`, `brave_router`, `deepseek_offpeak`,
`retired_providers`) but nothing ran them as a sequence, budgeted them, or wrote down what was tried.

## The vectors, in the only order they may run

| # | vector | cost | what it does | what it may NOT do | typical ETA |
|---|---|---|---|---|---|
| 1 | `refresh_producer` | free | re-runs the domain's **declared writer** (`writer` / `writer_target` in the registry), then re-reads the store | invent a new producer; count exit 0 as an answer | 2 min |
| 2 | `backup_provider` | free | walks the domain's registry `backup` list — **same question, different provider** | cross-domain substitution; a retired slot (refused up front, `retired_skipped`) | 30 s |
| 3 | `governed_search` | metered | `brave_router.search()` — the router owns budget, cache and the SearXNG spill | touch a search host directly | 20 s |
| 4 | `hermes_research` | metered | `_enqueue_hermes_research` — slow; returns `queued` + ETA | answer synchronously | 30 min |
| 5 | `llm_curation` | metered | DeepSeek (`FAST` policy) inside the off-peak/bulk window, Ollama otherwise — **curates evidence already gathered** | run with no evidence; be stored as a fact; go unlabelled (`source: "llm_curation"`, model id) | 1 min |
| 6 | `operator_ask` | free | **one** question to the operator with an ETA; opens/rides the Phase-2 pending | run before the others | 2 h |

Rules enforced in code, not left to the caller (`normalise_chain`, `resolve`):

* **free → metered → paid**, stable within a class; a registry chain that disagrees is re-sorted. A `paid`
  slot additionally needs `GAP_RESOLVER_PAID_AUTHORIZED=1` or `free_first_refresh.reject_paid_transition`
  refuses it (`budget_denied`, the rail's own words in the receipt).
* **A retired provider is never a vector.** `retired_providers.is_retired` refuses it before anything is
  spent; the refusal is a receipt (`retired_skipped`), never a silent fall-through.
* **Budget is per vector per UTC day**, counted from the receipts file — so it survives restarts.
  Refusals (`budget_denied`, `retired_skipped`) do not consume budget.
* **A fast answer stops the chain.** `partial` (search hits, curation) is evidence, not an answer; the
  chain continues. `queued` records an ETA and the cheaper remaining vectors still run.
* **Side effects are armed, not assumed.** Without `GAP_RESOLVER_LIVE=1` every side-effecting vector
  records what it *would* have done (`dry_run: would run scripts/pro_analyst_fetch.py`). Tests never set it.

## Where the chain is declared

`config/data_source_authority.json` → `domains[].on_gap` (ordered list of
`{vector, cost_class, max_per_day, expected_seconds}`). `gap_resolver.load_on_gap(domain)` reads it and
falls back to `DEFAULT_ON_GAP` when a domain has none. All 24 domains declare a chain (measured
2026-09-13 against `e8a173e7d`: `python3 -c "import json; a=json.load(open('config/data_source_authority.json')); print(sum('on_gap' in d for d in a['domains']))"` → `24`).
The historical proposal is `docs/implementation/sot/phase7_registry_patch.json`; the registry is
authoritative. Highlights (verified against the registry, same measurement):

| domain | chain |
|---|---|
| quote_price | refresh(24) → backup(24) → operator_ask — a price comes from a price provider or not at all |
| analyst_opinion | refresh → backup(yfinance_on_demand) → search(6) → curation(4) → operator_ask |
| catalyst_news | refresh → backup → search(20) → curation(6) → operator_ask — search IS a same-question backup here |
| research_thesis | refresh → backup → search(8) → **hermes(6)** → curation(6) → operator_ask |
| technicals / holdings_accounts | refresh(12) → backup(12) → operator_ask — nothing to search for |
| watch_discovery | operator_ask only — dead feed, no producer |
| private_company | **empty** — `refuse_up_front`; `is_answerable` refuses before the resolver is reached |

## Receipts

Every attempt appends one row to `data/cio/gap_resolution_receipts.jsonl` (`GapResolutionReceipt@v1`;
`data/cio` is a served, linked dir so it lands in persistent-state):

```
gap_id · domain · subject · question · why · requester · vector · cost_class · provider · model
outcome ∈ answered | partial | queued | no_answer | budget_denied | retired_skipped | error
started · finished · as_of (of the answer) · eta_seconds · detail
```

The `Resolution` returned to the caller carries `answer`, `as_of`, `age_hours`, `source`
(`"<vector>:<provider>"` or `"llm_curation:<model>"`), the `vector` that answered, `eta_seconds` when a
slow vector was queued, `operator_question`, `no_coverage_behaviour` (from the registry) and every attempt.

## What the operator sees

| situation | before Phase 7 | now |
|---|---|---|
| unanswerable (no instrument) | refused up front | unchanged — refused before any vector runs |
| a fast vector answers | pending, silence | answer now: `*WMT* analyst opinion — via backup_provider:yfinance_on_demand · as of 2026-09-13T17:00, 1h old` |
| the refresh makes the store complete | pending | the normal curated desk reply, from the store |
| only a slow vector queued | "I'll reply when it lands" | pending opened **with the ETA**: "≈ 30 min until it lands · Pending opr_…" |
| every vector denied / exhausted | pending that expires in 2 h | "no coverage through any declared source — tried refresh_producer=no_answer, governed_search=budget_denied …; declared behaviour `say_so`". **No pending.** |
| curation ran | — | text labelled "_curated by deepseek-v4-flash from gathered evidence — not a fact source_" |

Switch: `CIO_GAP_RESOLVER=0` restores the pre-Phase-7 path (the negative-control test proves the old
behaviour returns: a pending with no ETA).

## The projection hook

`scripts/lib/data_broker/gap_hook.enqueue_gap(domain, subject, question, why=…, stale_age_hours=…)`
appends to `data/cio/gap_queue.jsonl` and returns. It never blocks a page load and never resolves
anything. A queued gap with no receipt after 2 h is what the monitor reports — today nothing drains
the queue (the resolver runs from the operator desk only); a drain lane is the next wiring step.

## The monitor

`scripts/check_gap_resolution.py` (read-only; receipt `data/runtime/gap_resolution_last_run.json` every
run; alert state `~/.local/state/tradeai/gap_resolution_last_alert.json`; fires on change only; sentinel
`[DATA_INTEGRITY]` → `P0_INTERRUPT`):

* `OPEN_NO_ATTEMPT` — a gap in `gap_queue.jsonl` or `research_gaps.jsonl` (OPEN) older than 2 h with no receipt
* `VECTOR_FAILING` — a vector with ≥ 3 `error` receipts today
* `RETIRED_RAN` — a receipt whose provider is retired and whose outcome is not `retired_skipped`. **Must be 0.**

Schedule **declared, not installed**: `config/systemd/user/tradeai-gap-resolution.{service,timer}` (every
30 min at :07/:37, `Persistent=true`, `SuccessExitStatus=0 1`), lane `gap-resolution-audit` in
`config/lane_registry.json` (receipt `output_signal` = `data/runtime/gap_resolution_last_run.json`) and
unit `tradeai-gap-resolution.timer` in `config/expected_services.json` so that the timer being OFF is
itself a finding. Installing is operator-only (AGENTS.md §9.3, §17); whether it is installed is measured
by `check_expected_services.py` on the host, never asserted by a document.

## How to add a vector — registry first, grant first

1. **If the vector introduces a new provider or a new writer, stop: that is an operator-only decision**
   (AGENTS.md §7A "Ownership and the grant", §17). Propose the provider row with an `approval` record
   in a PR; the operator grants it; `check_data_source_authority.py` fails `UNAPPROVED_SOURCE` until then.
2. Add the vector name to the `on_gap` chains that may use it in `config/data_source_authority.json`,
   with `cost_class`, `max_per_day`, `expected_seconds`; re-render with `scripts/render_source_of_truth.py`.
3. Add the name to `gap_resolver.VECTORS` and an implementation to `DEFAULT_VECTORS`. It must: be
   fail-soft, return a `VectorResult`, refuse retired providers, do nothing without `ctx.is_live()`,
   and label any model output with `source` and model id.
4. Add a row to the table above and a test that injects the vector's I/O and asserts the receipt.
5. A vector that is not in the registry does not run: `normalise_chain` drops unknown names.

## Tests

`tests/test_gap_resolver_20260913.py` (chain order, retired skip, budget, fast-stop, ETA, no_coverage,
receipts, curation labelling, arm flag, desk wiring, negative control, hook) ·
`tests/test_gap_resolution_monitor_20260913.py` (findings, alarm firing with `COVERS`, units, lane).

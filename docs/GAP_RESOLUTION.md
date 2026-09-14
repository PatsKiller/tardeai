# Gap Resolution — when the answer is stale or missing, go find out

```
Status:      ACTIVE
as_of:       2026-09-13T23:59:00-04:00
Measured at: a8a62217e (origin/main, PR #1001 merge) / timers observed on the host 2026-09-13 23:54 ET
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
see below). The text below reflects the merged state. **Second correction (PR #998, 2026-09-13 night):**
this document described only the registry resolver. The operator desk also writes the separate
`data_gap_registry` queue, and "resolved" there used to mean "a job was queued" — see "The data gap queue"
below. The registry now declares 26 domains, and the monitor timer has since been installed.

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
falls back to `DEFAULT_ON_GAP` when a domain has none. All 26 domains declare a chain (measured
2026-09-13 against `a8a62217e`: `python3 -c "import json; a=json.load(open('config/data_source_authority.json')); print(len(a['domains']), sum('on_gap' in d for d in a['domains']))"` → `26 26`;
it was 24 at `e8a173e7d`, before `data_gaps` (PR #998) and `operator_conversation` (PR #1001), both `operator_ask` only).
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
| only a slow vector queued | "I'll reply when it lands" | pending opened **with the ETA**: "≈ 30 min until it lands · Pending opr_…"; it stays open until ETA + `CIO_OPERATOR_PENDING_ETA_GRACE_HOURS` (default 1 h), not a flat 2 h (PR #998) |
| a pending is closed unanswered | "did not arrive within 2h" | the question and when it was asked, how long it was open, why it closed, what was missing, and retry advice from the deterministic subject resolver (PR #1000) |
| every vector denied / exhausted | pending that expires in 2 h | "no coverage through any declared source — tried refresh_producer=no_answer, governed_search=budget_denied …; declared behaviour `say_so`". **No pending.** |
| curation ran | — | text labelled "_curated by deepseek-v4-flash from gathered evidence — not a fact source_" |

Switch: `CIO_GAP_RESOLVER=0` restores the pre-Phase-7 path (the negative-control test proves the old
behaviour returns: a pending with no ETA).

## Measured 2026-09-14 — what the chain actually does for an operator question

The walk is correct as coded (88 resolver/router tests pass); what limits it is which switches the calling process
has. The CIO bot process has **none** of `GAP_RESOLVER_LIVE`, `BRAVE_ROUTER_ENABLED`, `BRAVE_ROUTER_LIVE`.

| Step | Effect in the bot today |
|---|---|
| refresh_producer | dry run ("would run <writer>") |
| backup_provider | nothing — research/news backups have no adapter; analyst backup is dry run |
| governed_search | skipped — `router_disabled` |
| hermes_research | **real** — enqueues regardless of `GAP_RESOLVER_LIVE`; one DeepSeek Flash call over house evidence, no web |
| llm_curation | nothing — curates only gathered evidence |
| operator_ask | no message — embedded in the desk reply; 1/day across domains |

Real receipts, HPE ask 09:12 ET: refresh dry-run → backup no_adapter → Brave router_disabled → **Hermes queued** →
curation nothing → operator_ask embedded. Hermes completed 09:16; delivered 10:36 after PR #1006.

Brave IS live for scheduled lanes (hourly `run_governed_research_producer.py` with `BRAVE_ROUTER_LIVE`; `web_research`)
and never for the desk. SearXNG takes a Brave search only on `DAILY_EXHAUSTED` / `MONTHLY_EXHAUSTED` / `HTTP_429`.
Nothing escalates on insufficient results. Full picture, due-diligence test and the approved target design (the
Research Escalation Circle): `docs/architecture/RESEARCH_ESCALATION_2026-09-14.md`.

## The data gap queue — `data_gap_registry` (PR #998)

A second, older mechanism with a similar name: `scripts/data_gap_resolver.py` (cron `0 10-16 * * 1-5`,
`--pre-overnight` 18:00 weekdays, `--weekly-audit` Sunday 08:00) works a PostgreSQL queue of per-symbol
gaps (`missing_catalyst`, `missing_sector`, `missing_thesis`, …) by refreshing enrichment or dispatching a
Maria research job. Registry domain `data_gaps`; history in `docs/MASTER_SYSTEM_DOCUMENTATION.md` §5.5.

* **One writer.** `scripts/lib/writers/data_gap_registry_writer.py` holds the INSERT, the one dedup rule
  (a symbol + gap_type already `open` or `enriching` is not inserted again; its id comes back as
  `existing_ids`) and every status transition. Callers: the resolver, the operator desk, and the retired
  overnight lane. It rejects a non-tradable symbol (never `BOOK`), a gap type the resolver has no action
  for, and an unknown severity — on the receipt, with a reason.
* **The desk queues for real.** For a gap the resolver can act on, the desk writes it through the module and
  the reply names the gap rows and the resolver's next run, **read from the crontab**
  (`_gap_resolver_schedule`, cached 10 min). An unreadable crontab yields no time, and the reply then
  promises no follow-up. Before PR #998 the desk imported a bridge module that never reached main and
  registered 0 gaps on every call; the table had no new row since 2026-05-24.
* **Resolved means proven.** A dispatched job leaves the gap `enriching` with the job id.
  `verify_dispatched()` marks it `resolved` only when the job is `completed` **and** wrote a result row that
  was not demoted for `UNGROUNDED_NUMBERS` (rule G0, `agent_number_grounding`); the proof is recorded. A
  failed, expired or missing job — or a completed one without a result row — reopens the gap with the reason;
  `DATA_GAP_MAX_DISPATCH_ATTEMPTS` (default 3) failures abandon it. Weekly audit abandons gaps open > 30 days.
* **Not the same as a registry receipt.** `data/cio/gap_resolution_receipts.jsonl` records the declared vectors
  above; `data_gap_registry` records per-symbol gaps for the hourly worker. A desk question can touch both.

Stale text, kept visible: the registry's `data_gaps._note` still says "'resolved' means the resolver dispatched
its action … not that the data landed". That described the pre-#998 behaviour; the writer module and resolver
code above are current. The note lives in operator-granted config and is not rendered into
`docs/SOURCE_OF_TRUTH.md`.

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

Schedule **declared** (and, as a dated observation, installed: `systemctl --user list-timers` showed it scheduled at 2026-09-13 23:54 ET with a run at 23:37): `config/systemd/user/tradeai-gap-resolution.{service,timer}` (every
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
`tests/test_gap_resolution_monitor_20260913.py` (findings, alarm firing with `COVERS`, units, lane) ·
`tests/test_data_gap_registry_writer_20260913.py` (dedup, rails, transitions, resolved-only-on-proof) ·
`tests/test_desk_gap_queue_reconnect_20260913.py` (desk writes through the module, crontab-derived next run) ·
`tests/test_pending_expiry_unanswerable_20260913.py` · `tests/test_pending_close_wording_20260913.py`.

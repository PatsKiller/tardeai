# Research escalation — who researches what, and when one step hands off to the next

**Status:** measured on 2026-09-14, on main `32897e80a`, by reading the code, the flags each process actually has, the live receipts and the Brave budget ledger, and by a dry run of the resolver. It describes what IS wired, not what was designed.

**Operator question that prompted this (2026-09-14):**
> "When does the agent say Brave's answers weren't enough, so we put it out to the LLM, or vice versa? Web searches are not enough, so we go to Brave? Hermes did not get enough, so we go to Brave?"

## The short answer

- **There is no quality-based escalation anywhere.**
  - No step judges another step's answer as "not enough" and hands off.
  - Hermes never escalates to Brave, and Brave never escalates to an AI model.
- **What exists is three separate mechanisms.** Each has its own trigger and its own stop rule:
  1. **The operator desk gap resolver.** It walks a fixed per-domain list and stops at the first step that returns the outcome code `answered`.
  2. **The Brave router spill.** It moves a web search from Brave to SearXNG only when Brave's quota is exhausted or rate-limited, never because Brave's results were thin.
  3. **The CIO research need gate.** It climbs `skip → reuse → corpus_hit → flash → pro → residual → grok_critique` for scheduled research. This is a separate path from the operator desk.
- **For an operator question on 2026-09-14, the only step that did real work was Hermes.**
  - Hermes is ONE DeepSeek Flash call over the house evidence packet. It does no web search.
  - Brave is live, but only for scheduled research lanes. The CIO bot process does not have the switch on.

## 1. Operator desk questions — `gap_resolver.resolve()`

**When it runs.** The desk (`cio_operator_desk_loop.handle_operator_desk_question`) finds blocking gaps in the house evidence:
- a research ask with no promoted research on the subject;
- a re-entry ask with no desk row.

For each gap it walks that domain's `on_gap` list from `config/data_source_authority.json`.

**Stop rules** (`scripts/lib/gap_resolver.py::resolve`):

| Outcome a step returns | What the resolver does next |
|---|---|
| `answered` | **stops**; the desk answers from it |
| `partial` (search hits, curated text) | keeps walking; the evidence is carried forward to later steps |
| `queued` (Hermes, operator ask) | remembers the ETA, keeps walking the cheaper remaining steps; `operator_ask` is always last |
| `no_answer`, `error`, `retired_skipped` | keeps walking |
| `budget_denied` | that step's daily attempts are spent (counted from the receipts ledger); keeps walking |

**Limits on the walk:**
- A `paid` step needs `GAP_RESOLVER_PAID_AUTHORIZED`. Without it the free-first rail denies the step.
- Every attempt writes one row to `data/cio/gap_resolution_receipts.jsonl`.

**"Not enough" in this path means only the outcome code.**
- No step scores whether Brave's hits or Hermes' answer were sufficient.
- `llm_curation` only rewrites evidence already gathered: "never invents".

### The chains (registry, 2026-09-14)

| Domain | Steps, in order |
|---|---|
| research_thesis | refresh_producer → backup_provider → governed_search (Brave) → hermes_research → llm_curation → operator_ask |
| analyst_opinion | refresh_producer → backup_provider (yfinance on demand) → governed_search → llm_curation → operator_ask |
| catalyst_news | refresh_producer → backup_provider → governed_search → llm_curation → operator_ask |
| symbol_identity | refresh_producer → backup_provider → governed_search → … → operator_ask |
| earnings_date | refresh_producer → governed_search → llm_curation → operator_ask |
| web_search | governed_search → operator_ask |
| quote_price, technicals, holdings, sector, regime | refresh_producer → backup_provider → operator_ask (nothing to search for) |

### What each step actually does today

| Step | Switch it needs | State in the CIO bot process | Real effect today |
|---|---|---|---|
| refresh_producer | `GAP_RESOLVER_LIVE=1` | unset | **dry run** — "would run <writer>" |
| backup_provider | `GAP_RESOLVER_LIVE=1` + an adapter | unset; research/news have no adapter | **nothing** — "no_adapter" |
| governed_search (Brave → SearXNG spill) | `BRAVE_ROUTER_ENABLED` (+ `BRAVE_ROUTER_LIVE`) | unset | **skipped** — "router_disabled" |
| hermes_research | none (enqueues regardless of `GAP_RESOLVER_LIVE`) | — | **real**: one Hermes request → one DeepSeek Flash call over house evidence; ~4 min to result |
| llm_curation | `GAP_RESOLVER_LIVE=1` + evidence to curate | unset; nothing gathered | **nothing** |
| operator_ask | live + a send function | not live; desk passes none | **no message**; the question is embedded in the desk reply; 1 per day |

**After Hermes lands.** Since PR #1006, `try_fulfill_pending_replies` joins the Hermes result to the operator's pending question by id and sends a follow-up. First delivery: HPE, 2026-09-14 10:36 ET. Nothing in this path escalates from Hermes to anything else. The Hermes critic verdict (VALID / INVALID) does not trigger a further step.

### Due-diligence test, 2026-09-14

**Real receipts: the operator's HPE question at 09:12 ET.** research_thesis, in order:
- refresh `dry_run` · backup `no_adapter` · Brave `router_disabled` · hermes `queued` · curation `no_evidence_to_curate` · operator_ask `queued (embedded)`.
- Hermes completed at 09:16. The answer reached the operator automatically at 10:36, once #1006 was deployed.

**Dry run** (`scripts` on main, all switches unset, Hermes enqueue faked, temp receipts):

| Gap | Outcome | Where it stopped |
|---|---|---|
| research_thesis HPE | queued | hermes_research (ETA 1800 s) |
| analyst_opinion SPCX | no_coverage | all steps no_answer; operator_ask budget_denied (1/1 today) |
| catalyst_news ELMT | no_coverage | backup "yahoo/brave/searxng: no_adapter"; Brave router_disabled |
| web_search | no_coverage | Brave router_disabled |

**Tests:** `test_gap_resolver_20260913`, `test_gap_resolution_monitor_20260913`, `test_brave_router*`, `test_searxng_engine_pool`: 88 passed, 2 xfailed. The walk logic is correct as coded; what limits it is which switches are on.

> **Evidence hygiene note.** The first attempt at this dry run passed the receipts path under the wrong keyword and appended 6 labelled rows to the live ledger (`gap_id=dd-research_thesis`, 2026-09-14T16:12:48Z). They count once against today's per-step budgets. They are left in place because the ledger is append-only.

## 2. Brave, and when a web search moves to SearXNG — `scripts/lib/brave_router.py`

**Who calls Brave.** From the budget ledger `data/runtime/search_budget.json`:
- **September:** `governed_research_producer` 113 calls, `web_research` 75.
- **August:** also `aegis_social_sentiment` and `aegis_transcript_discovery`.
- **Schedule:** the governed research producer runs hourly at :45 with `BRAVE_ROUTER_LIVE` set on its crontab line.
- **The operator desk never calls Brave.**

**Limits.** Operator-owned local cost policy, not a Brave plan ceiling:
- 120 calls a day and 1,500 a month;
- per-caller daily caps: default 25, catalyst_intelligence 10, portfolio_news 10, topic_ingestion 5, web_news_fetcher 5.
- **2026-09-14:** 25 used, 30 refused with `CALLER_DAILY_CAP`.

**When Brave hands off to SearXNG.**
- Only when the refusal reason is `DAILY_EXHAUSTED`, `MONTHLY_EXHAUSTED` or `HTTP_429`.
- `CALLER_DAILY_CAP` is deliberately **not** a spill reason (operator decision, 2026-09-13): a caller over its own cap gets nothing.
- Zero or poor results are **not** a spill reason either.
- Tavily is declared in the registry but has no client, so it is never called.

## 3. Scheduled CIO research — the research need gate

`ResearchNeedDecision@v2` climbs `skip → reuse → corpus_hit → flash → pro → residual → grok_critique`:
- `residual` is the ChatGPT/OpenAI rung, run by `scripts/lib/cio_residual_web.py`, which also reads SearXNG directly.
- Each rung runs only when the gate routes a subject to it. The gate decides from coverage and freshness of the corpus, not from a score of the previous rung's answer.
- This path serves plans and wakes, not the operator desk.

The model lanes follow the separate LLM escalation policy (`AGENTS.md`, "LLM lane escalation"):
1. free OAuth: Grok, then ChatGPT;
2. DeepSeek Flash, the one paid lane allowed automatically;
3. notify and stop;
4. any further paid lane only on an explicit operator re-run.

## 4. What the operator expected vs what exists

| Expectation | Today |
|---|---|
| "If Hermes did not get enough, go to Brave" | Not wired. Hermes' result is delivered as-is; its "Still unknown" and "Limits" lines say what it could not find. |
| "If Brave's answers weren't enough, go to the LLM" | Not wired as a quality test. For the desk, Brave is off; `llm_curation` would only summarise Brave hits (partial) if both were on. |
| "If web searches are not enough, go to Brave" | Reversed. Brave is the first web step; SearXNG is only the quota/rate-limit spill. |
| Research on "push for more" | "Do more research on X" is classified `research` and triggers the chain above. There is no separate "dig deeper" intent. |

## 5. Operator directive and the target design — the Research Escalation Circle (approved, not yet built)

Operator, 2026-09-14: *"We need to utilize everything — SearXNG, Brave, Hermes, DeepSeek, everything — and it
should be an escalation ladder or escalation circle with some intelligence around it. Also Yahoo Finance and all
the other channels."* This is the build target. Nothing below is live until its phase ships and is verified.

**The circle — one question, laps until the answer is sufficient or the bounds are reached:**

```
            ┌─────────────────────────────────────────────────────────────────────────┐
  question  │ LAP n                                                                   │
  (subject  │ 1. HOUSE      Trade-AI stores (dossier, desk, research, thesis, memory)    │
   GUID,    │ 2. PROVIDERS  free, in parallel: Yahoo Finance (yfinance), Finviz, SEC     │
   needs)   │               EDGAR, FRED, Alpaca/Schwab market data, catalyst & news      │
            │ 3. WEB-FREE   SearXNG (self-hosted)                                        │
            │ 4. WEB-PAID   Brave — only if SearXNG evidence is insufficient             │
            │ 5. SYNTHESIS  Hermes: DeepSeek Flash over house + provider + web evidence  │
            │ 6. CRITIC     free lane (Grok, then ChatGPT OAuth): sufficient? contradicted?│
            │               names the missing facts                                     │
            │ 7. JUDGMENT   DeepSeek Pro — only when the critic finds contradiction or   │
            │               a material open question on a held/decision-relevant name    │
            └───────────────┬─────────────────────────────────────────────────────────┘
                            │ sufficiency test fails AND critic named specific missing facts
                            └──► LAP n+1: targeted queries for exactly those facts (steps 2–6)
  stop: sufficient · lap limit (2) · budget · time limit → answer with what is known, say what is not,
        ask the operator only for what no channel can supply
```

**The intelligence — "enough" becomes a measured decision, not an outcome code:**

| Evidence | Sufficient when |
|---|---|
| Price / levels / volume | a fresh value (inside the domain's stale window) from the store or a provider, cross-checked against a second source within tolerance |
| Analysts / earnings / fundamentals | a dated value from Yahoo or the house store; stale values are labelled and trigger a provider refresh |
| News / catalysts | ≥ 2 independent sources dated inside the window, relevant to the subject GUID (not just the ticker string) |
| Research question | every operator sub-question has an answer citing evidence ids; critic verdict VALID; no unresolved contradiction |

- Each step records **what it added** (new facts, new sources, contradictions); a step that adds nothing is not repeated.
- Cost order is fixed: free before metered before paid; Brave and DeepSeek Pro are entered only when the free
  evidence fails the test, and every entry is receipted with the reason.
- Bounds per question: 2 laps, Brave ≤ 3 queries, DeepSeek Pro ≤ 1 call, wall clock ≤ the ETA the operator is told;
  global caps stay the registry's (`providers.brave.budget`, LLM daily spend cap).
- Every line of the answer carries its pill: 🟢 Trade-AI data · 🔵 Looked up outside Trade-AI (named source) ·
  🟣 AI model (which model, which role).
- The answer joins back to the pending question by id (PR #1006) with an ETA stated up front; progress messages only
  when a lap completes, never per step.

**Phases (each one PR, tested, dry-run on real questions, then armed):**
1. Cost-class arming (`GAP_RESOLVER_LIVE_CLASSES`) and FREE steps live for the desk: refresh producers,
   Yahoo/Finviz/EDGAR/FRED backups, SearXNG as its own vector; the sufficiency module with the table above.
2. Brave for the desk behind the sufficiency test (desk caller cap in the Brave cost policy); web hits flow into the
   Hermes evidence packet.
3. Critic step (free lanes) and DeepSeek Pro judgment under the rules above; the lap loop with targeted re-queries.
4. "Push for more" intent ("dig deeper", "research X", "what else") starts a lap on the existing subject instead of a
   fresh question; a monitor for questions that stopped on a bound rather than on sufficiency.

## Where to look

- **Code:** `scripts/lib/gap_resolver.py`, `scripts/lib/brave_router.py`, `scripts/lib/cio_operator_desk_loop.py`, `scripts/lib/cio_hermes_research.py`, `scripts/lib/hermes_bridge_backend.py`, `scripts/lib/cio_residual_web.py`.
- **Registry:** `config/data_source_authority.json` — `domains[*].on_gap`, `providers.brave.budget`, `domains.web_search.backup` / `spill_on`.
- **Receipts:** `data/cio/gap_resolution_receipts.jsonl`, `data/runtime/search_budget.json`, `data/runtime/brave_router_health.json`.
- **Related docs:** `docs/GAP_RESOLUTION.md`, `docs/OPERATOR_REPLY_ROUTING.md`, `docs/architecture/DOCUMENT_MENTIONS_AND_LLM_ESCALATION.md`.

# Ask the CIO: open questions with persistent CIO memory (Phases 8–11)

```
Status:      DRAFT (branch feat/ask-cio-phase8-11-20261023; shipped with the research cap PROPOSED, so deep answers
             and re-answers are inert, and the re-answer lane is not scheduled)
as_of:       2026-10-23T14:30:00-04:00
Measured at: not measured live. Hermetic tests only (tests/test_cio_ask_20261023.py, tests/test_cio_ask_contract_20261023.py,
             apps/command-center-v3/src/lib/askCioModel.test.ts, apps/command-center-v3/e2e/ask-cio.spec.ts). Base: origin/main 53aa1b619
Owner:       cio
Authority:   READ_ONLY_ADVISORY · MBI_BEHAVIOR = 0 · operator-only API
Contract:    scripts/lib/cio_ask_contract.py (AskRequest@v1, AskAnswer@v1, AskProspectus@v1, AskSizingContext@v1,
             AskSizeSuggestion@v1 [gated], AskResearchContext@v1)
```

On 2026-10-23 the operator approved building "Ask the CIO" as Phases 8 to 11, after release-train phases 0 to 7. The
operator's words: "the key is the persistent memory. Across the CIO system." A clarification came the same day:
"we don't need the hard code sizes. I could just ask the question without sizes. It can suggest sizes, or I can say
sizes."

## 1. What the operator gets

**Phase 8: one brain, two channels.**
- An **Ask the CIO** bar sits under the header on every Command Center page. ⌘K or Ctrl-K focuses it.
- **My questions** (`/v3/cio/questions`) lists every thread from the Command Center and Telegram. Each thread shows its
  status (quick, deep pending, deep, re-answered, capped), every answer version, sources, what it is tracking, and a
  follow-up box.
- Telegram questions use the same path. A question asked in the Command Center is mirrored to the CIO Telegram chat.
  - Replying in Telegram to any message in a thread adds a follow-up to that thread.
  - So does any message that names the thread id (`thr_…`).
  - A follow-up typed in the Command Center lands in the same thread.

**Persistent memory: the core requirement.**
- These items are appended to CIO memory:
  - every question and follow-up
  - every entity resolution
  - every answer version
  - every source
  - every tracking change and re-answer trigger
- Memory is the CIO-owned `SecurityResearchSpine`, as `silo="cio"` contributions tagged `ask_the_cio`, keyed by the
  registry `security_guid`.
- When a later question names the same security, the answer opens with **"Earlier on TSLA (CIO memory):"**. This works
  on either channel and in any thread.
- Every other silo that reads the spine through `view_for_silo` (options, re-entry, holdings, Hermes) sees the same
  contributions. Nothing here is a private thesis cache.

**Phase 10: auto-tracking.** For each entity in an answered question, the existing write paths are used:
- **My Watchlist.** The entry goes into `data/portfolios/state/watchlist.json`, in the shape `/api/watchlist/write`
  writes. The question becomes the thesis.
  - An entry the operator already had is never overwritten. The thread id is added to `ask_threads` instead.
- **CIO record.** `InstrumentRecordStore` cognition sets `next_research_question` to the question and records the
  operator turn.
  - Stage, conviction and stance stay with the CIO prospect builder. A question never invents a conviction.
- **Catalyst watch directive.** It goes through `watch_directives_writer`, created by the operator, with a 90-day TTL.
  - A listed security gets a `ticker` directive carrying the question's keywords.
  - A private entity gets a `trend` directive on its name.
- **Untrack** on the thread removes only what the question added: the watchlist entry it created, if no other tracked
  thread holds it, and the directive it created. The CIO record keeps its history.
  - A later follow-up does not re-track an untracked entity.

**Phase 11: re-answer on material change.**
- Tracked securities are subscribed to `sec_filing_events` (the SEC feed) and Postgres `material_changes`. Both are
  keyed by `subject_guid` = `security_guid`.
- When an event fires, the CIO answers the thread's question again through the same path. The new version is posted in
  the same thread, in the Command Center and on Telegram, under "What changed" and with a pointer to the previous
  version.
- Guards:
  - one re-answer per thread per event, ever
  - at most one per thread per 6 hours
  - at most 10 per day
  - the cost cap
  - `mode: shadow` by default: candidates are recorded, and nothing is spent or sent

**Unknown and private entities.**
- A pre-IPO company becomes a `private_entity` with an `entity_guid` (`ent_…`, a uuid5 of the name).
- It is **never given a ticker**: no watchlist row, and a trend directive on its name.
- Its memory is the ask ledger, keyed by `entity_guid`. The spine requires a listed security.

## 2. MBI_BEHAVIOR = 0: sizes

- Quantities are **optional**. Nothing in the UI, in Telegram parsing or in the contract asks for one.
- When the operator names quantities ("100 or 1,000 TSLA?"), **sizing context** shows each one:
  - dollar exposure
  - % of portfolio
  - % combined with what is already held
  - the concentration limit (`config/investment_policy_statement.json` `constraints.max_single_position_pct`, 12%)
  - loss at a reference stop: the operator's stop if the question names one, otherwise an illustrative 8% below the
    price, configurable as `sizing.reference_stop_pct`
- Sizing context never recommends a quantity.
- **`size_suggestion`** is designed in the contract (`AskSizeSuggestion@v1`: advisory, risk-budget based, reasoning
  shown, `actionable: false`). It is **always omitted** unless AGENTS.md has an ACTIVE version-history row at or above
  **21.0.0**. The check is `size_suggestion_allowed()`, which uses `ops_controls_core.policy_state(..., or_later=True)`
  once PR #1970 lands and an equivalent fail-closed check until then.
  - The 21.0.0 amendment is the operator's option and is not proposed by this change.
  - The MBI rail code (`cio_instrument_record.BEHAVIOR_FIELDS`, `BehaviorWriteRefused`) is untouched.
- The **MBI guard** (`mbi_guard_text`, `mbi_guard_payload`) strips any model sentence or key that proposes a quantity,
  order, stop, limit or weight.
  - The strip is recorded on the answer (`mbi_guard.stripped`) and shown ("sizing advice removed"). It is never silent.
- §2A: `sizing_context` is computed on the host and is never part of a prompt. `research_context_for_model` removes
  position dollars and account detail before the Phase 9 pipeline sees anything.

## 3. Flow

```
CC  POST /api/v2/cio/ask ─┐                                  ┌─ Telegram (cio_telegram_bot → cio_telegram_converse)
                          ▼                                  ▼
        cio_converse_core.process_operator_message(channel=…, ask_options=…)
             begin_turn   thread (explicit / thr_ id / reply), entities (operator_subject_resolver),
                          operator-named quantities, CIO-memory recall          — writes nothing
             desk loop    handle_operator_desk_question (unchanged)
             compose      MBI guard → recall → sizing context → auto-track → footer
             _prepare_reply → send
             finish_turn  ledger events + CIO memory + channel link             — skipped on dry_run
```

- The quick path is the existing desk loop, with its own registered caps.
- The deep path calls `request_deep`. It goes through the cost gate, then
  `DEEP_RESEARCH_ENTRYPOINT = scripts.lib.cio_ask_research:run_deep_research`, which is Phase 9, built on
  `feat/ask-cio-phase9-research-20261023`.
- Until that module exists, the thread shows `deep_pending`. While the cap awaits approval, it shows `capped` with the
  reason.

## 4. API (`scripts/lib/cio_ask_api.py`, dispatched from `api_v2.handle`)

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/api/v2/cio/ask` | `{question, thread_id?, depth?: quick\|deep, client_request_id?}` | `client_request_id` makes the ask idempotent |
| GET | `/api/v2/cio/asks?limit=` | | thread summaries, newest first |
| GET | `/api/v2/cio/asks/tracked` | | tracked entities (for Watch / Home flags) |
| GET | `/api/v2/cio/asks/<thr_…\|ask_…>` | | one thread |
| POST | `/api/v2/cio/asks/<thr_…>/deep` | `{ask_id?}` | request the deep answer |
| POST | `/api/v2/cio/asks/<thr_…>/untrack` | `{entity_key}` | |

- Every route answers only the operator's tailnet identity on `serve_proxy`, following the Ops Controls convention.
  Requests through the service token (agents, n8n) get `403 AGENT_CALLER_REFUSED`.
- POSTs re-check same-origin CSRF (`cc_auth.command_csrf_check`) and are a `csrf.hard_routes` entry
  (`cio_ask_command`).

## 5. Stores

- **Asks ledger.** File `data/cio/cio_ask_events.jsonl` (`CioAskEvent@v1`).
  - Append-only, fcntl-locked, fsync'd. Idempotent through a deterministic `event_id`.
  - Event kinds: `ask.asked`, `ask.entity_resolved`, `ask.answer_version`, `ask.tracking_changed`,
    `ask.reanswer_triggered`, `ask.reanswer_skipped`, `ask.channel_link`, `ask.cost`.
  - "My questions" reads its thread projection (`AskEventStore.threads()`).
  - It is a **projection, not a silo**: every security-level event also lands in CIO memory.
  - Data-dictionary row `cio_asks` is **PROPOSED** (`config/data_source_authority.json` `proposed_domains`) and awaits
    the operator's grant (§7A, §26.6).
  - Postgres-portable shape for the move (§24.9):
    `cio_ask_events(event_id text primary key, kind text, thread_id text, ask_id text, at timestamptz, payload jsonb)`.
- **CIO memory.** `data/cio/security_research_spine.jsonl`, through `upsert_research_memory`.
  - An optional second copy goes to M2 (`CIOEnvelopeIntegrator`, predicate `ask_cio_exchange`) when
    `CIO_ASK_M2_APPLY=1`. M2 production writes are separately authorised.
- **Config.** `config/cio_ask.json`: caps, mirror, auto-track steps, re-answer mode and guards, reference stop.

## 6. Cost

- Quick answers spend under the desk loop's existing operator-reply caps.
- Deep answers and re-answers go through `CostGate`. It fails closed, and its checks run in this order:
  1. the cap's `approval.status` must be `APPROVED`
  2. per-question cap, $0.50
  3. daily cap, **$5.00 proposed**, summed from `ask.cost` events
  4. the governed global cap, `llm_consumption.check_cost_cap("cio_ask_deep_research", …)`
- The cap ships as **PROPOSED**, so the deep path and re-answers spend $0 until the operator approves ("inert above
  cap").
- `cio_ask_deep_research` also needs its `config/llm_process_registry.json` row and bridge registration (§9.2). That
  is a Phase 9 deliverable, approved with the cap.

## 7. Operator approvals needed (propose and stop: §17)

1. **Data-dictionary row `cio_asks`.** Grant the asks ledger as a store, with `cio_ask_store.py` as its single writer.
   The row is PROPOSED; CI only warns.
2. **Research spend cap.** $5.00/day and $0.50 per question for deep answers and re-answers. Approve by setting
   `config/cio_ask.json` `cost.approval.status: APPROVED` with `approved_by`, `approved_on` and `reference`.
3. **Re-answer lane.** `cio-ask-reanswer` (`scripts/cio_ask_reanswer.py --once`) as an n8n lane at **shadow**. It is
   not in cron (cron freeze 2026-10-09; n8n-first). `mode: live` additionally needs approval 2.
4. **Optional, the operator's choice: AGENTS.md 21.0.0.** It would let `size_suggestion` appear (advisory, risk-budget
   based, never actionable). Until then it is always omitted.
5. **Mirroring CC answers to Telegram** (`mirror_cc_to_telegram: true`) is on, because cross-channel follow-up depends
   on it. Turn it off in config if not wanted.

## 8. Run and verify

```
.venv/bin/python -m pytest -q tests/test_cio_ask_20261023.py tests/test_cio_ask_contract_20261023.py
cd apps/command-center-v3 && npm run build        # includes src/lib/askCioModel.test.ts
.venv/bin/python scripts/cio_ask_reanswer.py --once --dry-run   # rule 7: before any live run
```

Under pytest, the ask path refuses default (production) dependencies unless a test injects fakes
(`cio_ask_core.set_deps` or `ask_options["deps"]`). Existing converse tests therefore never write the live ledger
(§24.6).

## 9. Known limits (honest)

- **Gate 4 alert threads.** A re-answer is posted to Telegram as a new message naming the thread. It does not reply to
  a Gate 4 unified-alert thread root: those are keyed by `day:SYM:event_key` in `unified_momentum_alerts.jsonl`, and
  no Command Center thread surface exists for them yet.
- **Telegram replies.** `send_cio_message` fans out to the allowlist without `reply_to`, so Telegram replies chain by
  the thread id in the footer and by recorded outbound message ids.
- **"Flagged on Watch / Home."**
  - The ask bar in the header shows a chip for each tracked name on every page, Home and Watch included
    (`GET /api/v2/cio/asks/tracked`). Each chip links to its thread.
  - Watch also shows the entry in My Watchlist, with the question as thesis.
  - A per-row flag inside the Watch tables is left to the Watch IA branch (`feat/watch-my-watchlist-suggests-20261023`,
    PR #2008), which owns those files today. A per-card flag on Home is left out to avoid colliding with PR #1975.
- **Re-answer sources.** Re-answers subscribe to SEC filings and `material_changes`. The CIO event bus
  (`thesis.changed`, `portfolio.material_change`) is not yet a source.
- **Pending desk follow-ups** for a Command Center ask (the desk loop's deferred "I'll get back to you") are delivered
  by the Telegram loop, because Command Center asks share the operator's CIO chat id.

# Operator reply routing — every path from a free-text message to a sent reply

```
Status:      ACTIVE
as_of:       2026-09-13T23:59:00-04:00
Measured at: 034ff2c90 (file:line references in the map) · a8a62217e (section "What PRs #1000 and #1001 added")
```

`READ_ONLY_ADVISORY` · MBI_BEHAVIOR = 0 · written 2026-09-13 · branch `feat/route-a-every-reply-cites-sources` (merged in PR #998)

**Line numbers are pinned, symbols are the anchor.** The `file:line` references in the map were measured at
`034ff2c90`. Later commits in PRs #998–#1001 grew `cio_operator_desk_loop.py` to 3,679 lines, so its line numbers
have moved — at `a8a62217e`: `gather_tradeai_evidence` 898 → 1552, `handle_operator_desk_question`
1729 → 3114, `try_fulfill_pending_replies` 2047 → 3597. Search by function name. The converse-core chokepoint
has not moved (`_prepare_reply` `cio_converse_core.py:373`, `finalize_operator_reply` call `:378`).

## Why this exists

The operator, verbatim, 2026-09-13 18:58 and 19:05:

> "it needs to quote the source ... whatever elements it returns it needs to give the elements like
> you're saying that it couldn't find it local so it went to DeepSeek — but it should have been able
> to find it local"
>
> "the routing should be internal Command Center first and when it has to go out for other stuff it
> needs to let us know; this needs to be wired and fixed tight"

Two live replies that day said nothing about where their content came from: "get back into schg"
got the whole re-entry book, and a sector question was answered from DeepSeek's general knowledge
while calling cash and holdings empty. The base fix (`ffc795f3c`) added a `Sources:` footer to one
branch of the desk loop. This document maps **every** branch, and states which of them sent a reply
with no Sources line before this change.

## The contract

A reply to the operator is never sent without:

1. **`Sources:`** — the Command Center stores it read, with the store's `as_of` / computed time when
   known, and — when a model wrote prose — the model id and its role: `wording only`,
   `general knowledge where labelled`, or `intent classification only`. A path that read nothing says
   `none — no Command Center store was read for this reply`; it never omits the line.
2. **`Went outside:`** — present **only** when the answer needed something outside the Command
   Center: a gap-resolver vector (governed search, backup provider, LLM curation), the Hermes research
   queue, or a model call. Each entry is `<what> — <why>`.
3. **The authority tail**, exactly once, last.

**One chokepoint.** `cio_converse_core.process_operator_message` builds every operator reply with
`_prepare_reply` (`scripts/lib/cio_converse_core.py:373`), which calls
`reply_provenance.finalize_operator_reply` (`scripts/lib/reply_provenance.py:356`) — the only call of
that function in the core (`cio_converse_core.py:378`). Every `_send(...)` on an operator-reply branch
sends `final_reply`; only the slash and ack command branches send `cmd_reply`. A static test asserts
this (`tests/test_operator_reply_routing_sources_20260913.py::test_every_send_in_the_converse_core_goes_through_the_chokepoint`).
The pending follow-up and retraction sends do not pass through the core; they call the same
`finalize_operator_reply` (`scripts/lib/cio_operator_desk_loop.py:2028`, `:2082`, `:2102`).

The desk loop's evidence-aware footer is `reply_provenance.with_sources_footer`
(`reply_provenance.py:198`), re-exported as `cio_operator_desk_loop._with_sources_footer`
(`cio_operator_desk_loop.py:1442`). The chokepoint keeps a Sources line the desk already wrote and
merges its store labels into the receipt; it never adds a second one. Store labels are deduplicated on
**store identity** (`reply_provenance.py:127`), and a trailing authority line is split off whole
(`reply_provenance.py:218`).

**The receipt.** `ReplyProvenance@v1` (`reply_provenance.py:85`) is written as `reply_provenance` on
the processor result for every operator-reply branch and on the per-turn `operator.message` event
payload (`cio_converse_core.py:578`). Field names are a contract with the answer-quality monitor:
`stores_read`, `went_outside`, `model`, `sources_line_present` (plus `kind`, `model_role`,
`authority_tail_present`, `schema`).

## Command Center first — the order the stores are tried

Each path reads house stores before anything else, and says so:

| tier | what | examples on these paths |
|---|---|---|
| 1 — Command Center stores | files and projections the house writes | `reentry_decision_desk_latest.json`, CIO snapshot (`get_cio_snapshot`: portfolio, cash, sectors, investment policy, holdings detail, risk), `holdings.json`, `hermes_research_intelligence`, `yahoo_analyst_targets_history`, decision catalog + dispositions, capital plan (CC API), `config/cio_llm_policy.yaml`, pending ledger, rate ledger |
| 2 — declared gap vectors | `gap_resolver.resolve` (`scripts/lib/gap_resolver.py:674`) over the domain's `on_gap` chain (`gap_resolver.py:101`); dry run unless `GAP_RESOLVER_LIVE=1` (`gap_resolver.py:73`) | refresh_producer, backup_provider, governed_search, hermes_research, llm_curation, operator_ask |
| 3 — models | governed bridge, DeepSeek Flash | intent classification (facts never), wording polish of a desk card, freeform prose with general knowledge labelled |

Tiers 2 and 3 are what `Went outside:` reports.

## Entry points (how a message reaches the router)

| # | entry | path |
|---|---|---|
| E1 | Live Telegram poller (runs the `CURRENT` release) | launcher `~/.config/tradeai/bin/run_telegram_callback_poller_current.sh:11` → `scripts/run_telegram_callback_poller.py:310` (`if not handled:`) → `scripts/lib/cio_poller_reply.py:147` `maybe_answer` (flag `CIO_REPLY_ENABLED`; `should_answer` `:81`) → `:203` `process_operator_message` |
| E2 | Dedicated CIO bot loop | `scripts/cio_telegram_bot.py:101` → `scripts/lib/cio_telegram_converse.py:1448` `process_telegram_message` → `:1499` `process_operator_message` |
| E3 | WhatsApp | `scripts/lib/cio_whatsapp_ingress.py:144` → `:170` `process_operator_message` |
| E4 | Pending follow-ups (no inbound message) | `scripts/cio_telegram_bot.py:130` → `scripts/lib/cio_operator_desk_loop.py:2047` `try_fulfill_pending_replies` |

All three inbound entries converge on `process_operator_message` (`cio_converse_core.py:289`).

## Out of contract — command traffic, not answers

These never reach the desk and are command output, not an answer drawn from stores: poller commands
`/pt*` (`run_telegram_callback_poller.py:242`), `/stop*` (`:250`), `/atm` (`:265`), `/caps` (`:279`),
`/approve` `/deny` (`:285`), the Schwab `code=` paste (`:292`), the ATM `YES` confirmation (`:722`);
and inside the core the `/cio` slash (`cio_converse_core.py:386`) and `ack` (`:401`) branches, which
send `cmd_reply` from `handle_cio_slash` (`cio_telegram_converse.py:1186`).

## The map — one row per operator-reply path

"Before" is `ffc795f3c` (the base fix). Every row now carries Sources + tail; each has a test in
`tests/test_operator_reply_routing_sources_20260913.py`.

| # | path (kind) | trigger | stores read (tier 1 first) | model — role | went outside | Sources before | now |
|---|---|---|---|---|---|---|---|
| R1 | **attention** | `looks_like_attention_query` — `cio_converse_core.py:438` | office situation scan, `cio_operator_attention.py:51`; the scan runs on `office or {}` (`:60`) and the core passes no office, so it scans an **empty** office (`same_brain` is False at `:107`, the core reports True) | none | nothing | **NO** — base `cio_converse_core.py:374` | `_attention_provenance` `cio_converse_core.py:248`; send `:442`; the line states "no office state loaded" |
| R2 | **reentry_facts** (book interceptor) | `looks_like_reentry_purchase_query` (`cio_telegram_converse.py:1521`) and no named symbol (`cio_converse_core.py:460`, `:463`) | `reentry_decision_desk_latest.json` + `computed_at` via `load_reentry_desk_rows` `cio_telegram_converse.py:1604` | DeepSeek Flash — wording only, when `CIO_REENTRY_FLASH` (`curate_reentry_reply_with_flash` `:1914`) | the model, when it polished | **NO** — base `cio_converse_core.py:400` | `_reentry_facts_provenance` `cio_converse_core.py:258`; send `:467` |
| R3 | **rate_limited** fail-soft | `rate_limit_ok` false — `cio_converse_core.py:480` | converse wake rate ledger | none | nothing | **NO** — base `cio_converse_core.py:414` | inline provenance `:480`–`:485` |
| R4 | **decision_thread** | a `dec_…` id in the text or quoted card — `cio_converse_core.py:508` | decision catalog + operator dispositions (`cio_telegram_converse.py:391`, `:406`); capital plan via CC API `/api/v2/cio/capital-plan` (`:428` → `cio_office_state.py:74`) | none | nothing | **NO** — base `cio_converse_core.py:446` | `_decision_thread_provenance` `cio_converse_core.py:273`; send `:514` |
| R5 | **operator_desk** → `handle_operator_desk_question` | everything else — `cio_converse_core.py:535` → `cio_operator_desk_loop.py:1729` | per sub-row | intent: DeepSeek Flash — intent classification only, when `CIO_OPERATOR_INTENT_FLASH` (`cio_operator_desk_loop.py:267`, `:473`) | the intent model, when used | per sub-row | `provenance_for_desk` `reply_provenance.py:404`; `_prepare_reply` `cio_converse_core.py:544`–`:553`; send `:606` |
| R5a | desk · attention | intent `attention` — `cio_operator_desk_loop.py:1749` | office situation scan (as R1) | none | nothing | **NO** | via R5 |
| R5b | desk · meta_system | runtime / LLM questions — `gather_tradeai_evidence` `cio_operator_desk_loop.py:898` | `config/cio_llm_policy.yaml` | none (`runtime_meta` `:1464`) | nothing | yes (policy path) — base `cio_operator_desk_loop.py:1945` | via R5 |
| R5c | desk · unclear clarifier | nothing mapped — `cio_operator_desk_loop.py:1477` | none (canned clarifier) | none | nothing | **NO** (footer silent: no sources) | "none" declared |
| R5d | desk · freeform | thematic / general — `gather_freeform_context` `cio_operator_desk_loop.py:519`; research status `:500` | CIO snapshot: portfolio, cash, sectors, investment policy, holdings detail; subject research | DeepSeek Flash — general knowledge where labelled (`answer_freeform_with_flash` `:790`, source `freeform_flash` `:885`) | the model; the gap resolver when thematic research was queued | line present but **the model was never named**: the base footer tested `source == "deepseek_flash"` (base `cio_operator_desk_loop.py:1473`) and freeform returns `freeform_flash` (base `:885`) — the 18:56 sector reply | `labels_from_evidence` `reply_provenance.py:154` recognises `freeform_flash` |
| R5e | desk · re-entry answer (symbol card or book) | `reentry_ready` / `reentry_levels` — `gather_tradeai_evidence` `:898`; `_curate_from_evidence` `:1455` | re-entry desk rows + `computed_at`; CIO snapshot (cash, portfolio, risk) when asked; `hermes_research_intelligence`; `yahoo_analyst_targets_history` | book card only: DeepSeek Flash — wording only (`:1540`); symbol cards are never polished (`:1558`) | the model, when it polished | yes — base `cio_operator_desk_loop.py:1945`, **with two defects**: tail duplicated ("No orders/stops from chat ·" orphan) and desk label doubled (base `:1483`) | fixed at `reply_provenance.py:218` and `:127` |
| R5f | desk · empty evidence | no facts — `cio_operator_desk_loop.py:1533` | none | none | nothing | **NO** | "none" declared |
| R5g | desk · unanswerable | market need with no resolvable instrument — `cio_operator_desk_loop.py:1785` | none | none | nothing | **NO — and the refusal was not sent**: it lives in `reply_preview`; the base core read only `text` (base `cio_converse_core.py:473`) and sent "Queued a pull if needed" (base `:476`) | core reads `reply_preview` (`cio_converse_core.py:544`–`:547`) |
| R5h | desk · answered by a gap-resolver vector | resolver answered, store still incomplete — `cio_operator_desk_loop.py:1831`; text `:1680` | the stores the evidence pass read | `llm_curation:<model>` when that vector answered | the vector (`<vector> — <domain> for <subject> had no house coverage (answered)`) | **NO** — base `cio_operator_desk_loop.py:1866` | via R5 |
| R5i | desk · no_coverage | every vector denied or empty — `cio_operator_desk_loop.py:1849`; text `:1710` | the stores the evidence pass read | none | "gap resolver — every declared vector denied or empty; nothing answered" | **NO** — base `cio_operator_desk_loop.py:1884` | via R5 |
| R5j | desk · deferred (pending opened) | blocking gap — `cio_operator_desk_loop.py:1893` | the stores the evidence pass read | none | Hermes research queue (`_enqueue_hermes_research` `:1368`, recorded `:1867`) or the resolver's queued vector with ETA | **NO** — base `cio_operator_desk_loop.py:1925` | via R5 |
| R5k | desk · freeform soft research queue | named symbol with no research — `cio_operator_desk_loop.py:1917` | as R5d | as R5d | Hermes research queue (recorded `:1935`) | line present; the Hermes enqueue was **not** declared | via R5 |
| R6 | **failsoft_empty** | desk returned no text — `cio_operator_desk_loop` result, `cio_converse_core.py:547` | none | none | nothing | **NO**, and it claimed "Queued a pull if needed" (base `cio_converse_core.py:476`) | "none" declared; false claim removed |
| R7 | **pending_fulfilled** follow-up | re-check found the facts — `cio_operator_desk_loop.py:2102` | `cio_operator_pending_replies.jsonl` (opened time) + the evidence gathered | as R5e / R5d | the model, when it wrote | **NO** — base `cio_operator_desk_loop.py:2112` | `_pending_reply_provenance` `:2028` |
| R8 | **pending_expired** retraction | unanswerable or past `PENDING_EXPIRY_HOURS` — `cio_operator_desk_loop.py:2082` | `cio_operator_pending_replies.jsonl` (opened time) | none | nothing | **NO** — base `cio_operator_desk_loop.py:2093` | `_pending_reply_provenance` `:2028` |

**Count.** 18 operator-reply rows (R1–R4, R5a–R5k, R6–R8; R5 itself is the dispatcher). Before this
change **14 sent no Sources line at all** (R1, R2, R3, R4, R5a, R5c, R5f, R5g, R5h, R5i, R5j, R6, R7,
R8) — and R5g did not even send its refusal. **3 sent a wrong one**: R5d never named the model, R5k
never declared the Hermes enqueue, R5e duplicated its tail and its desk label. **1 was correct** (R5b).

## What PRs #1000 and #1001 added (measured at `a8a62217e`)

The contract above is unchanged; these change what the desk rows put in front of it.

- **Subject brief for a named stock (R5e, #1000).** `format_subject_brief` renders, per named symbol: last
  close and 30-day change from the broker `daily_bars` projection (`subject_price_facts`); levels from that
  symbol's re-entry desk row (`_subject_levels`); analysts with as-of date and age (`subject_analyst_view`,
  "may be out of date" past `ANALYST_STALE_DAYS`); research — the newest `SUBJECT_RESEARCH_PER_TYPE` (3) rows
  of each type (`SUBJECT_RESEARCH_SQL`), near-duplicates merged, operational stop/protection notes only when
  the question is about stops (`select_subject_research`); and "What this means" with a next step. The
  Sources line names only what the reply shows.
- **Checked Flash summary.** `curate_subject_reply_with_flash` may reword the brief. `_subject_flash_problems`
  rejects the summary unless every number is in the brief (`agent_number_grounding`, zero unsupported), the
  symbol, close, mean target and as-of survive, and no order language appears; the brief is sent otherwise.
  `CIO_SUBJECT_FLASH=0` disables.
- **Memory recall (#1001).** `subject_memory()` reads up to 3 earlier operator questions per subject GUID in the
  same chat within `CIO_SUBJECT_MEMORY_DAYS` (30) from `operator_conversation_turns`, pairs each with the reply
  by `reply_to_message_id`, and excludes the question being answered. `format_subject_memory` appends
  "Earlier on V" (what was asked, what was answered or "No reply to it is on record", and the close move since)
  to the subject brief and to single-symbol re-entry cards. Old Sources and authority lines are stripped from
  excerpts. The Sources line then names `conversation memory (operator_conversation_turns)`
  (`reply_provenance.py:179`, `:245`). `CIO_SUBJECT_MEMORY=0` disables. Not the comms-gateway
  `scripts/lib/comms/subject_memory.py`.
- **Deferred (R5j) and closing (R8) replies (#998, #1000).** A deferred reply names the `data_gap_registry` rows
  it queued and the gap resolver's next run from the crontab (`_gap_queue_note`), or promises nothing. Expiry is
  `_pending_expiry_hours`: ETA + `CIO_OPERATOR_PENDING_ETA_GRACE_HOURS` when the pending has an ETA, else
  `PENDING_EXPIRY_HOURS` (2). `_closing_message` states the question and when it was asked, how long it was
  open, why it closed and what was missing; `_retry_advice` comes from the deterministic subject resolver, with
  no model call.
- **Before any of this: house facts and the subject (#998).** `operator_subject_resolver` binds the question to
  instruments; `operator_evidence_contract` (`config/operator_evidence_contract.json`) reports facts the store
  had but the evidence did not carry (`MISSING_FACT`, `FALSE_EMPTY_CLAIM`) as soft `contract` gaps.

## What PRs #1006 and #1007 added (2026-09-14)

- **Research answers come back.** A pending opened for missing research is joined to its Hermes result by pending id
  (`cio_operator_gap_requests.jsonl` → `hermes_research_projection.json` → `hermes_research_results.jsonl`) in
  `try_fulfill_pending_replies`; the follow-up quotes the question and carries Hermes' answer, findings (by severity),
  open questions and limits, every line `🟣 AI model:`. A failed Hermes run closes the pending at once with the
  reason. Monitor rule `RESEARCH_LANDED_UNSENT` flags research that landed > 10 min ago without a follow-up.
- **Answer now.** A research-only ask replies immediately with the house facts plus "Deeper research queued: Hermes
  … Pending `opr_…`" (`CIO_OPERATOR_RESEARCH_ANSWER_NOW`, default on); the follow-up omits the dossier.
- **Hermes is asked the operator's question**, split to its 220-character limit, plus the thesis check.
- **Pills are spelled out.** Every reply opens with `Key: 🟢 green = Trade-AI's own stored data · 🔵 blue = looked up
  outside Trade-AI for this reply · 🟣 purple = written by an AI model (DeepSeek), check before acting`; labels are
  defined once in `reply_provenance` (`PILL_HOUSE`, `PILL_OUTSIDE`, `PILL_MODEL`, `LEGEND`).
- First live delivery: HPE research, asked 09:12 ET, delivered automatically 10:36 ET.

## Known limits — named, not closed

- **Attention scans an empty office on the converse path** (R1, R5a). The Sources line now says so, but
  the answer text still reads "Nothing material changed in verified portfolio truth". Wiring the office
  state into `answer_attention_query` is the attention lane's change, not this one.
- **Only desk turns (R5, R6) persist `reply_provenance` durably**, on the `operator.message` event. R1–R4
  carry it on the processor result only. No new event was added for them: `operator.message` wakes
  consumers, and emitting it on branches that do not emit it today would change what runs. The sent
  body — including its Sources and Went outside lines — is also captured as the agent turn in
  `operator_conversation_turns` on E1 (`cio_poller_reply.py:100`) and E2
  (`cio_telegram_converse.py:1448`), which a monitor can parse.
- **R7 / R8 receipts are not persisted**; the ledger row records status, not provenance.
- **The answer-quality monitor does not know about ETAs.** `check_operator_answer_quality.py`
  `pending_never_closed` flags any pending still open after `PENDING_OPEN_HOURS` (2 h), while the desk keeps a
  pending with an ETA open to ETA + grace. A long-ETA pending is reported before it is due.

## Tests

Also: `tests/test_operator_answers_use_house_facts_20260913.py`, `tests/test_operator_evidence_contract_20260913.py`,
`tests/test_operator_intent_resolution_20260913.py`, `tests/test_subject_answer_completeness_20260913.py`,
`tests/test_subject_memory_recall_20260913.py`, `tests/test_pending_close_wording_20260913.py`,
`tests/test_desk_gap_queue_reconnect_20260913.py`, `tests/test_operator_answer_quality_20260913.py`.

`tests/test_operator_reply_routing_sources_20260913.py` — offline: injected send, replaced event bus
and wake store, fixture desk rows / snapshot / pending ledger, every model patched, patches applied
under both `scripts.lib.*` and `lib.*` module spellings. One test per row above, plus a negative
control that replaces the chokepoint with identity and shows the attention reply leaves without a
Sources line (then restores it), the same control for the pending retraction, the static
single-chokepoint test, the interceptor test (steps aside for a named symbol, still fires for "what's
ready to buy back"), the receipt field-name test, and exact-string tests for the SCHG footer.

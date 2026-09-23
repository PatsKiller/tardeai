---
cursor:
  subagentId: "bc-dfa11c90-4661-528e-8ff1-454f6c73a742"
---

# Plan: Why `S` got a hollow DeepSeek answer instead of research-then-answer

```
Status:      PLAN (not implementation)
as_of:       2026-09-22T14:50:00-04:00
Measured at: worktree HEAD 2b4b14e1b (docs branch) · fix branch
             cursor/fix-single-letter-ticker-s-667c @ ed957509d (PR #1187) ·
             served pin ~466c781d0 (main, no fix) — [DOC-CLAIM] from audit + operator paste
Authority:   AGENTS.md §7 operator replies / RESEARCH_ESCALATION ·
             docs/OPERATOR_REPLY_ROUTING.md · docs/architecture/RESEARCH_ESCALATION_2026-09-14.md
Repo:        /home/johnclaw/tradeai-wt-cc-lean-docs-20260915
```

Operator paste (failure signature): DeepSeek summary restating Trade-AI facts (price $19.84 close Sep 04, 30d −10.8%, no levels / analyst / house research) → “Next — say `research S`…” → full-picture dossier (not held, no specialist in 2 months, empty stores) → TROW footer bleed beside S · receipt `4f5054b0` · `S:84601d7d` `TROW:69403c08`.

---

## 1. Verdict

The desk answered from **house stores that were already empty/thin**, then let DeepSeek Flash **reword only those facts** (`CIO_SUBJECT_FLASH` + `agent_number_grounding`). Missing house research is **not a quality trigger to research first** — on the served pin it became an **operator prompt** (“say `research S`”), not an auto-enqueue; even the HPE “answer now + Hermes later” path still sends a first hollow reply. Hollow in → hollow out was by design; researching *before* any answer is not wired.

---

## 2. Causal chain (ordered, with cites)

### Step 1 — Inbound lands on the desk converse path

Telegram / CIO bot → `process_operator_message` → desk `handle_operator_desk_question` (`scripts/lib/cio_operator_desk_loop.py` around the `handle_operator_desk_question` entry; map in `docs/OPERATOR_REPLY_ROUTING.md` R5 / E1–E2). Every reply then exits through `reply_provenance.finalize_operator_reply` (`cio_converse_core` `_prepare_reply`). `[CODE]`

Receipt GUIDs prove **S did resolve** as a subject (`S:84601d7d`); TROW in the same receipt proves **link chrome / identity bleed**, not that the question was about TROW. `[DOC-CLAIM]` operator paste; bleed family documented in `docs/audits/SINGLE_LETTER_TICKER_S_FIX_2026-09-22.md` and `docs/OPERATOR_REPLY_ROUTING.md` (PR #1187 section).

### Step 2 — Intent: house facts first, optional `research` / `analyst_view` needs

`analyze_operator_intent` heuristics add `research` only when the text matches research/hermes/thesis/deep-dive language (`cio_operator_desk_loop.py:447-453`); valuation / “a buy” → `analyst_view` (`:459-468`). “How is X doing” can add `reentry_levels` (`:412-417`). Intent Flash may refine needs but does not invent coverage. `[CODE]`

An investment question about `S` can therefore open the **subject brief** path (`research` or `analyst_view` in needs, and `not want_reentry` → `subject_symbols` at `:1881-1884`) **without** ever making missing Hermes a **blocking** gap (blocking requires `"research" in needs` **and** no `hermes_research` **and** no `reentry_card` — `:1905-1907`). `[CODE]`

### Step 3 — Evidence gather: thin stores still count as “complete enough to answer”

- Price: `subject_price_facts` → broker projection `daily_bars.get_daily_bars` over `ticker_prices` (`:2234-2273`, `scripts/lib/data_broker/daily_bars.py:59-79`). No single-letter filter here. `[CODE]`
- Levels: re-entry desk row or “not on desk” (`format_subject_brief` `:2401-2402`).
- Analyst / Hermes: only when those needs were declared (`:1835-1876`); empty → gap rows, often **soft**.
- `complete = not blocking and bool(available)` (`:1916`) — a stale close alone makes `available` non-empty, so the turn is **not deferred**. `[CODE]`
- Dossier always attaches for named symbols (`_attach_subject_dossier` `:3474-3521`, `gather_tradeai_evidence` `:3524-3531`) and reports empty sections + “no specialist … two months” (`subject_dossier.py` takeaway ~`:404`). `[CODE]`

### Step 4 — Curate: DeepSeek may only reword the deterministic brief

`_curate_from_evidence_core` builds `format_subject_brief`, then optionally `curate_subject_reply_with_flash` (`:3173-3192`). Flash system prompt: “Use only the FACTS… Every number… must appear in the FACTS” (`:2495-2502`). `_subject_flash_problems` rejects unsupported numbers via `agent_number_grounding` (`:2460-2483`). **Hollow FACTS → accepted hollow summary.** `[CODE]` · matches AGENTS.md §7 “Checked Flash summary” / `CIO_SUBJECT_FLASH`.

`_curate_from_evidence` then **appends the dossier** under a “DeepSeek wrote the summary from Trade-AI facts” header (`:3534-3575`) — matching the operator’s “DeepSeek summary” + “Full picture” paste. `[CODE]`

### Step 5 — “Say `research S`” is intentional UX on served code, not auto-research

Emitted in at least three places on **main / served** (not yet replaced by #1187):

| location | when | cite |
|---|---|---|
| `_subject_takeaway` | no substantive research and/or no/stale analyst | `cio_operator_desk_loop.py:2358-2359` — exact “Next: say 'research {sym}'…” |
| Soft-gap footer | soft gaps present; registry did not claim “queued” | `:3882-3894` — “not refreshed automatically; say 'research \<ticker\>'…” |
| `subject_dossier.format_dossier` | always ends outside pill with queue prompt | `subject_dossier.py:427-428` |

Freeform / thematic “nothing queued” copy is the same family (`_thematic_research_status` `:880-881`). `[CODE]`

**What does auto-enqueue today (served)?** Only when a gap is **blocking** (or freeform soft research with `CIO_OPERATOR_FREEFORM_QUEUE`) — `_enqueue_hermes_research` (`:2845+`) and freeform soft queue (`:3829-3868`). Subject-brief investment asks with soft/missing research **prompt the operator instead**. `[CODE]`

### Step 6 — Research escalation policy: emptiness does not escalate

`docs/architecture/RESEARCH_ESCALATION_2026-09-14.md` § short answer (still true 2026-09-16): **no quality-based escalation**; desk gap resolver stops at first `answered`; Brave spill is quota/429 only; `CALLER_DAILY_CAP` refusal → free search (PR #1045) is a **refusal** rescue, not thin-answer escalation. AGENTS.md §7 / §12 same. `[DOC-CLAIM]` + `[CODE]` gap_resolver stop rules.

So “no house research on S” never triggers “go research, then answer” *before* the first send unless the gap is classified **blocking** and the Hermes path runs — and even then `CIO_OPERATOR_RESEARCH_ANSWER_NOW` (default on) **answers immediately** with house facts and queues Hermes for a **follow-up** (`:3771-3797`). That is “answer then research,” not “research then answer.” `[CODE]`

### Step 7 — TROW footer bleed proves served pin ≠ #1187

Served build still extracts secondary symbols into outbound Command Center / Finviz / Yahoo chrome (`comms_editor` / `telegram_rich` behavior documented in audit). Operator paste with TROW links beside S matches **PR_ONLY** lifecycle: fix SHA `ed957509d` on draft PR #1187, main/served `~466c781d0`. `[DOC-CLAIM]` `docs/audits/SINGLE_LETTER_TICKER_S_FIX_2026-09-22.md`.

### Step 8 — Quote staleness (Sep 04 vs Sep 22): producer coverage, not letter-length filter

`subject_price_facts` / `daily_bars` read whatever is in `ticker_prices` — no `len(symbol)==1` skip (`daily_bars.py`). Writers sync from holdings / watchlist / market_quotes paths (`ticker_prices_writer.py` header; repricer / `watchlist_enrichment_sweep`). **S not held** (dossier) ⇒ likely **off the daily producer universe**, so last close sits at Sep 04 (~18 days) while domain `technicals` `stale_after_hours` is 26h (`config/data_source_authority.json`). Brief prints the date (`:2376`) but does not loudly label multi-day STALE. Single-letter extraction bugs are orthogonal to this stale bar. `[CODE]` / `[DOC-CLAIM]` for live DB contents (not queried in this plan pass).

---

## 3. What #1187 already fixes vs still open

**PR #1187** (`ed957509d`, branch `cursor/fix-single-letter-ticker-s-667c`) — `[CODE]` via `git show` on that branch; **not** on served pin.

| Already on #1187 | Still open after merge+promote |
|---|---|
| Link chrome scoped to turn `primary_symbols` (stops TROW bleed) — `telegram_rich`, `comms_editor`, `telegram_transport`, `cio_converse_core` | Does **not** make the first reply wait for Hermes |
| Single-letter extract / bind (`SINGLE_LETTER_TICKERS`, resolver + `extract_symbols`) | `subject_dossier.py:428` **still** says “say 'research X' to queue a fresh pull” (unchanged on the PR branch) |
| `enqueue_research_gap` deduped helper; freeform + **soft** researchish gaps auto-queue Hermes; takeaway no longer prompts “say research X” | Soft-gap auto-enqueue path **acks + enqueues** but does **not** open a `PENDING_PATH` row (unlike freeform / blocking) → `try_fulfill_pending_replies` may never send a research follow-up |
| Tests in `tests/test_single_letter_tickers.py` (link isolation, extract, enqueue once) | Stale Sep 04 `ticker_prices` for off-universe `S` |
| | Intent may still omit `research` need → hollow brief still possible until soft enqueue fires |
| | True “research THEN answer” (block until Hermes) is **not** in the PR; existing design is answer-now (`CIO_OPERATOR_RESEARCH_ANSWER_NOW`) + async fulfill |

**Merge+promote #1187 is sufficient for:** stop TROW bleed; reliable `S` bind; **auto-queue** instead of “type `research S`” on soft/freeform/takeaway paths covered by the PR.

**Merge+promote #1187 is not sufficient for:** “do research, then send the only answer”; dossier prompt cleanup; pending follow-up on soft enqueue; fresh quote for names outside holdings/watchlist.

---

## 4. Proposed fix plan (phased; smallest correct change first)

**Pre-build search (§13.5):** Do **not** invent a new research subsystem. Extend existing: `enqueue_research_gap` / `_enqueue_hermes_research`, `try_fulfill_pending_replies` + `hermes_result_for_pending`, `CIO_OPERATOR_RESEARCH_ANSWER_NOW`, `format_subject_brief` / `subject_dossier`, `daily_bars` / `ticker_prices` writers. Ruled out: new `@v1` type, second Hermes queue, synchronous model web search in the desk curate path.

### Phase 0 — Lifecycle (no code)

1. Land PR #1187 (ready → merge) when CI green.
2. Promote **exact merge SHA**; restart desk/Telegram units whose cwd still pin an older release (audit already shows telegram bot cwd lagging portfolio-server).
3. Re-ask `S` on **served** pin; confirm primary-only links + enqueue ack (not “say research S” in takeaway).

### Phase 1 — Close #1187 remainder (small, same modules)

1. **`subject_dossier.format_dossier`**: replace the hard-coded “say 'research …'” outside line with either silence (desk owns enqueue) or the same ack string `enqueue_research_gap` returns — one UX. `[CODE]` target `subject_dossier.py:427-428`.
2. **Soft-gap path**: when `enqueue_research_gap` succeeds, **open the same `PENDING_PATH` + gap-request join** used by freeform/blocking so `try_fulfill_pending_replies` can deliver Hermes (mirror `:3850-3868`). Without this, auto-queue is fire-and-forget.
3. Optional: surface `subject_price.stale` / age in the brief when `price_date` is older than `technicals.stale_after_hours` so Sep 04 cannot read as “today.”

### Phase 2 — “Research then answer” product choice (wire existing async; do not invent sync wait by default)

| Option | Behavior | Fit |
|---|---|---|
| **A (recommended default)** | Keep answer-now + auto-enqueue + **guaranteed pending follow-up** when house research missing on a named symbol (extend soft path + dossier). Matches HPE pattern already proven (`CIO_OPERATOR_RESEARCH_ANSWER_NOW`, join-back #1006). | Telegram latency; AGENTS “promise only what is queued” |
| **B** | Treat empty house research on investment/subject asks as **blocking** even without the word “research” (widen `:1905-1907` / needs inference). Still answer-now if flag on. | Stronger enqueue; still not sync |
| **C** | Block-and-wait on Hermes inside the desk turn | Operator-only if desired; conflicts with desk latency / bridge caps; not in #1187 |

**Do not** implement quality-based web→LLM escalation here — still unbuilt per RESEARCH_ESCALATION; out of scope unless operator expands §17.

### Phase 3 — Quote freshness for asked symbols (separate finding)

On ask for a named symbol with `ticker_prices` age ≫ stale window: either (a) declare gap + soft refresh via existing gap registry / producer, or (b) explicit on-demand bar refresh if a granted path exists — **propose registry/producer change, do not invent a second writer** (§7A / §17). Measure whether `S` is absent from watchlist/holdings universe before blaming single-letter logic.

---

## 5. Operator decisions (§17 / product)

| # | Decision | Why it is operator-facing |
|---|---|---|
| 1 | Merge + promote #1187 (and whether telegram unit restart is authorized with the promote) | Deploy / release-write |
| 2 | Confirm product intent: **A** answer-now + follow-up vs **C** block-until-research | Changes operator UX and spend timing; not a silent default flip to sync wait |
| 3 | If Phase 3 adds a new on-demand quote producer or writer for off-universe symbols | §7A / §17 data-source grant |
| 4 | Whether empty `house_research` on any named-symbol investment ask should be **blocking** by policy (Option B) | Widens when Hermes spends money |

No broker / MBI / credential decisions in scope.

---

## 6. Verification (live `S` query after promote)

Prove from the **served** release (resolve `CURRENT` → concrete pin; quote SHA). Suggested sequence:

1. **Dry-run desk** (same code path, no send): invoke `handle_operator_desk_question("is S a good investment?", chat_id=…)` under `--dry-run` / test harness if available; quote returned `kind`, `research_queued`, text (must **not** contain “say 'research S'” after Phase 0/1), and absence of TROW URLs when `primary_symbols=['S']`.
2. **Live ask** on Telegram for `S` after promote: capture message; confirm footer links are S-only; confirm ack that research is queued + `Pending opr_…` when research missing.
3. **Durable artifacts**: row in `data/cio/cio_operator_gap_requests.jsonl` for that `pending_id`; Hermes result in `hermes_research_results.jsonl`; open then fulfilled row in `cio_operator_pending_replies.jsonl` when worker lands.
4. **Follow-up**: `try_fulfill_pending_replies` (bot loop) delivers Hermes section; quote command + message id.
5. **Quote check**: `daily_bars` / SQL last `price_date` for `S` — if still Sep 04, Phase 3 is still open; say so explicitly.
6. **Negative**: ask a multi-letter name with thin research to ensure auto-enqueue is not S-only.

Do **not** treat hermetic `tests/test_single_letter_tickers.py` PASS as OBSERVED_LIVE.

---

## Evidence index (this plan)

| claim | tag | where |
|---|---|---|
| Hollow flash = reword-only | `[CODE]` | `curate_subject_reply_with_flash` / `_subject_flash_problems` |
| “say research S” intentional on served | `[CODE]` | `_subject_takeaway:2359`, soft footer `:3894`, `subject_dossier:428` |
| No quality escalation | `[DOC-CLAIM]` | `RESEARCH_ESCALATION_2026-09-14.md`; AGENTS §7 |
| Blocking vs soft research | `[CODE]` | `:1905-1907`, `:3771-3797`, `:3829+` |
| #1187 scope / remaining | `[CODE]` | branch `ed957509d` vs `subject_dossier` untouched; soft pending gap |
| Served ≠ fix | `[DOC-CLAIM]` | audit + operator TROW bleed |
| Sep 04 quote | `[CODE]` reader path; live why = measure after | `daily_bars` / universe producers |

**Out of scope for this document:** implementation, push, promote, live Telegram send.

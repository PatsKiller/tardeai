---
cursor:
  subagentId: "bc-3bcb8834-4de9-54b8-b7d8-61057d39b996"
---

# Audit: SentinelOne (S) — memory vs research, GUIDs, persistence

```
Status: ACTIVE
as_of: 2026-09-23T08:45:00-04:00
Measured at: hub persistent CIO stores + Postgres watch_directives/watchlist_items +
             Maria OpenClaw session jsonl + gateway cron log (/tmp/openclaw/…)
Authority: AGENTS.md §4 / §7 operator replies · operator paste ~08:21–08:29 ET
Surface under audit: Maria Telegram (OpenClaw gateway), chat 8797974247 —
                     display “John OpenClaw” — NOT tradeai_bigjohn718_bot / cio-telegram desk
Also measured: CIO desk turn same morning ~07:44 ET on chat 6993102664 (separate bot)
```

Class tags used below:

| tag | meaning |
|---|---|
| MEMORY | prior conversation / agent memory note, not a fresh store read |
| HOUSE_RESEARCH | Trade-AI durable store / API / Hermes / risk / portfolio |
| LIVE_LOOKUP | live web_search / web_fetch / external page |
| MODEL_GENERAL | model prose not bound to a cited Trade-AI fact with Sources/LEGEND |
| UNKNOWN | cannot prove origin from measured artifacts |

Evidence tags follow AGENTS.md §4: `[VERIFIED]` command/output, `[CODE]` source read.

---

## 0 · Two surfaces, same morning

| when (ET) | surface | chat_id | session / ids |
|---|---|---|---|
| **07:44** | CIO Telegram desk (`tradeai-cio-telegram`) | `6993102664` | turn `operator_conversation_turns.id=393` · `opr_ab7192d3b009` · `plan_e2cdd9c8c1a8` · `res_c3a661c21740` · receipt `14a76d62-e505-5134-9753-a535c383899e` |
| **08:21–08:31** | **Maria / OpenClaw** (“John OpenClaw”) | `8797974247` | session `2e04fc8a-fe5d-454d-a09e-e7542fed5bc3` · watch_directive **id=1278** · cron job ids `a9c337e0-…` / `729e2b82-…` |

Operator paste in the task matches the **Maria** window. Telegram service cwd at measure was still `…/857931d41-main-exact-phase2-20260922-170257` (not the later promote pin) — `[VERIFIED]` earlier this session via `systemctl --user show` + `/proc/…/cwd`.

---

## 1 · Message-by-message classification (Maria thread)

Source of truth for turns:  
`~/.openclaw/agents/maria/sessions/2e04fc8a-fe5d-454d-a09e-e7542fed5bc3.jsonl` `[VERIFIED]` Grep/Read.

| # | UTC | ET | who | text (abbrev) | class | GUID / ids | evidence |
|---|---|---|---|---|---|---|---|
| 1 | 12:21:33Z | 08:21 | operator | “give me perspective on sentinel one” | — | **none** stamped into Trade-AI inbound for this chat | Session L5. **No** matching `inbound_operator_questions` / `operator_conversation_turns` row for chat `8797974247` at this time `[VERIFIED]` SQL |
| 2 | 12:21:59Z | 08:21 | tool | `ticker S` → `🔎 S` only | HOUSE_RESEARCH (thin fail) | none | Skill exec; empty/minimal CC ticker payload |
| 3 | 12:22:10Z | 08:22 | tool | `ask` → Grok “Investment Perspective on SentinelOne…” | MODEL_GENERAL | none | ToolResult “🤖 (grok): …” — free OAuth lane, not Hermes / not dossier |
| 4 | 12:22:20Z | 08:22 | tool | `web_search` searxng “SentinelOne latest quarterly…” | LIVE_LOOKUP | none | SearXNG results, marked EXTERNAL_UNTRUSTED |
| 5 | 12:22:44Z | 08:22 | Maria | “Here's my read on **SentinelOne (NYSE: S)**…” narrative | **MODEL_GENERAL** (primary) + LIVE_LOOKUP scraps | **no** `S:84601d7d`, **no** receipt, **no** Sources/LEGEND | Delivery-mirrored assistant text L14. No `finalize_operator_reply` path |
| 6 | 12:24:19Z | 08:24 | operator | “yes add to watchlist, yes for iris and cio” | — | — | L15 |
| 7 | 12:24:40Z | 08:24 | tool | `tradeai_watchlist.py add S` → ✅ Added… | HOUSE_RESEARCH (mutation) | **directive_id=1278** (DB); **no subject_guid on row** | Skill POSTs `/api/v2/watch/directives`. SQL: `watch_directives.id=1278` active, `spec={"symbol":"S"}`, `rationale` “added via OpenClaw…”, `created_at=2026-09-23 08:24:26-04` `[VERIFIED]`. API `GET /api/v2/watch-directives` shows S with `hit_symbols:["S"]` |
| 8 | 12:25–12:26 | 08:25–08:26 | Maria | “Iris / Alex CIO take” synthesized | HOUSE_RESEARCH (partial) + MODEL_GENERAL | none | `hermes-hub` / `risk-hub` / `portfolio` via tradeai-readonly. **Iris/Alex sessions not called** — session tool: `agentToAgent` forbidden; Maria role-played specialists |
| 9 | 12:26:09Z | 08:26 | Maria | “Done on all three…” incl. Hermes “0 recent findings”, Dec 8 earnings, book fit | HOUSE_RESEARCH (0 Hermes findings) + MODEL_GENERAL (Purple AI / external catalysts) | none | L34. Claim “queued” is directive `hermes_enabled=true`, not a new `res_*` from this session |
| 10 | 12:28:02Z | 08:28 | tool | cron create “SentinelOne (S) earnings reminder” | MEMORY/scheduler | cron id **`a9c337e0-7a4d-4a83-8089-5aa3bf5f5059`**, `at=2026-12-07T13:00:00Z` (08:00 ET) | ToolResult L37. Gateway log `/tmp/openclaw/openclaw-2026-09-23.log` `cron: job added` `[VERIFIED]`. **Live `~/.openclaw/cron/jobs.json` ABSENT** (only `.migrated` / `.bak`) — persistence gap |
| 11 | 12:28:09Z | 08:28 | Maria | “Both set…” Dec 7 reminder + profile later | MEMORY (promise) | cron id only | L38–39 |
| 12 | 12:28:52Z | 08:28 | operator | “yes monitor support resistance volume for entry” | — | — | L40 |
| 13 | 12:29:22Z | 08:29 | tool | `web_fetch` stockanalysis.com/stocks/s/ | LIVE_LOOKUP | none | L45 |
| 14 | 12:30:43Z | 08:30 | tool | cron “SentinelOne (S) entry monitor” `5 16 * * 1-5` ET | scheduler | cron id **`729e2b82-7ace-4a13-8456-c469cb1072e9`** | L47 + gateway log. Same **jobs.json absent** gap |
| 15 | 12:30:55Z | 08:30 | Maria | “Monitoring set…” S/R levels, Bernstein downgrade | LIVE_LOOKUP + MODEL_GENERAL | none | L49–50. Levels from web page, not Trade-AI technicals projection. Bernstein claim not house-grounded |
| 16 | 12:31:52Z | 08:31 | Maria | “Got it — I'll watch both…” | MEMORY (intent) | none | L53 |

Maria daily memory note (post-facto MEMORY for later wakes):  
`~/.openclaw/workspace-maria/memory/2026-09-23.md` — documents watchlist + entry monitor + Dec 7 reminder + Bernstein note `[VERIFIED]` Read.

---

## 2 · GUID / subject / pending / receipt persistence per turn

### Maria / OpenClaw thread (08:21–08:31)

| artifact | present? | cite |
|---|---|---|
| `subject_guid` `84601d7d-ae35-5dc7-b664-1b77ad8ea57e` on outbound | **MISSING** | No reply_provenance / guid_footer on Maria replies |
| `issuer_guid` | **MISSING** | — |
| `opr_*` pending | **MISSING** | OpenClaw path does not open desk pendings |
| Comms editor receipt | **MISSING** | No new `comms_editor_receipts` row for this thread in the 08:21–08:31 window (CIO receipt at 11:45Z is the other bot) |
| Session message ids | YES (OpenClaw-local) | jsonl `id` / telegram delivery-mirror metadata |
| Watch directive id | YES | **1278** in Postgres + API |
| Cron job ids | YES in session + gateway log; **file store unverified** | `a9c337e0-…`, `729e2b82-…`; `jobs.json` not on disk |

### CIO desk turn (07:44 ET) — same ticker, different surface

| artifact | present? | cite |
|---|---|---|
| Operator turn row | YES but **identity null** | `operator_conversation_turns.id=393`, chat `6993102664`, text about SentinelOne; **`symbol=NULL`, `subject_guid=NULL`, `issuer_guid=NULL`** `[VERIFIED]` SQL — tagging gap |
| `opr_ab7192d3b009` | YES (gap request) | `cio_operator_gap_requests.jsonl` ts `2026-09-23T11:44:46Z` / hermes forced `11:44:59Z` |
| Pending reply ledger | **not in** `cio_operator_pending_replies.jsonl` for this id (file mtime still 2026-09-22) | Gap vs gap_requests — pending open/fulfill not recorded there |
| Hermes | YES completed | `res_c3a661c21740` → `rr_abb8acb2f962`, `completed_ts=2026-09-23T11:46:01Z`, provider `governed_bridge` / `deepseek-flash` |
| Request `subject_guid` | **null** on HERMES_RESEARCH_REQUESTED row | jsonl; lineage envelope **does** carry `subject_guid=84601d7d-…` |
| Comms receipt | YES | `comms_editor_receipts.jsonl` ts `2026-09-23T11:45:05Z`, subjects `[{symbol:S, guid:84601d7d-…}]`, changes include `primary_symbols_scoped`, `guid_footer` |

---

## 3 · Persistence check (claimed actions → durable artifacts)

| claim | durable? | path / location | timestamp |
|---|---|---|---|
| Add S to watchlist | **YES** (directive + watchlist_items link) | Postgres `watch_directives.id=1278` active; `watchlist_items` rows for `S` carry `directive_id=1278`, `last_hit` / thesis `directive:Watchlist`, `updated_at≈08:37 ET` | created `2026-09-23 08:24:26-04` |
| Visible on `/api/v2/watchlist` top list | **NO** at measure | `/api/v2/watchlist` returned 13 symbols, **S absent** (PLTR…PPC) `[VERIFIED]` | as_of audit |
| Visible on `/api/v2/watch-directives` | **YES** | S row with `hermes_enabled`, `trade_ai_enabled`, rationale OpenClaw | same |
| Iris / Hermes queue from Maria | **PARTIAL** | Directive enables Hermes; **no new** `hermes_research_requests` row timed to 08:24 from OpenClaw. Morning Hermes completion is from **CIO desk** `res_c3a661c21740` (07:44). Maria reported “0 recent findings” while that result already existed ~40 min earlier — surface split | Hermes completed 07:46 ET |
| “Alex CIO take” | **NO separate specialist row** | Role-play after `agentToAgent` deny; risk/portfolio reads only | session L22–L34 |
| Dec 7 earnings reminder | **CLAIMED + logged; store file missing** | Gateway: job `a9c337e0-…` added to `…/cron/jobs.json`; **directory has only** `jobs.json.migrated` / `.bak*` — **no live `jobs.json`** `[VERIFIED]` Glob | cron create 08:28:02 ET |
| S/R entry monitor (4:05 ET weekdays) | **same** | Job `729e2b82-…`, expr `5 16 * * 1-5` America/New_York; same missing `jobs.json` | create 08:30:42 ET |
| Maria memory note | YES | `~/.openclaw/workspace-maria/memory/2026-09-23.md` | written same day |
| Hermes research product for S | YES (from CIO desk, not Maria) | `data/cio/hermes_research_results.jsonl` `res_c3a661c21740`; findings: uptrend technicals, **INSUFFICIENT_DATA** thesis, off-symbol RAG, null analyst, empty catalysts | completed 11:46Z |
| Data gaps | YES open/enriching | `data_gap_registry` id **77** `missing_market_data` S (quote stale path from desk); id **76** `stale_news`/research from prior day | 07:44 / prior |

---

## 4 · Verdict vs prior hollow S reply

**Improved**

1. **Operator got action, not only a hollow brief** — watch directive 1278 landed in Postgres with Hermes/Trade-AI flags on; watchlist_items linked to it.
2. **Morning CIO desk path (07:44) did research-first plumbing** — gap → Hermes enqueue → completed result with lineage `subject_guid`, scoped receipt with `guid_footer` (vs Sep 22 hollow quote-only / TROW bleed family).
3. **Maria session is fully reconstructable** from session jsonl + memory note (intent trail clear).

**Still broken / integrity gaps**

1. **Maria’s main “perspective” is MODEL_GENERAL + LIVE_LOOKUP** with **no Trade-AI Sources/LEGEND**, no `S:84601d7d`, and a useless `ticker S` house call — same class of ungrounded narrative the hollow-S work was trying to stop, on a **different bot**.
2. **Iris/CIO “takes” were not real specialist wakes** — cross-agent disabled; prose labeled Iris/Alex without Iris/Alex sessions.
3. **Cron reminder + entry monitor: gateway says written; `jobs.json` not on disk** — restart risk; cannot re-read jobs from the declared store path.
4. **Identity tagging failed on the CIO desk turn** that *did* name SentinelOne — `operator_conversation_turns` row has null symbol/GUIDs.
5. **Hermes request rows still omit `subject_guid`** even when lineage later stamps `84601d7d`.
6. **S not in the short `/watchlist` API list** operators/skills treat as “the watchlist” — directive exists, list UX can still look empty of S.
7. **Two bots, two truths** — Maria said Hermes had 0 findings while desk Hermes had just completed an INSUFFICIENT_DATA packet on the same symbol.

---

## 5 · Recommended fixes (no grants invented; propose only)

1. **Route ticker “perspective / buy / research” intents on Maria to the CIO desk converse path** (or call the same evidence + `finalize_operator_reply` stack) so Sources/LEGEND + subject GUID footer are mandatory.
2. **Refuse specialist labels unless the named agent session actually runs**; if `agentToAgent` is off, say so up front (Maria partially did) and do not invent “Iris found…”.
3. **Prove cron durability** — after create, read back `jobs.json` (or fix the store so the file the gateway logs actually exists); alert if `storePath` missing.
4. **Stamp `subject_guid`/`issuer_guid` on** Hermes REQUESTED rows, watch_directives, and OpenClaw→Trade-AI writes; fix inbound tagging so company-name “SentinelOne” sets GUIDs (desk turn 393 is the positive-control failure).
5. **Reconcile watchlist surfaces** — either promote directive 1278 into the `/watchlist` ranking the skill prints, or have `add` print directive id + “not yet in ranked watchlist” honestly.
6. **Single subject timeline** — when Maria mutates S, attach `opr_` / plan / res ids from the desk Hermes if one is already open, so “0 findings” cannot be claimed beside a completed `res_*`.

---

## Appendix A · Prior hollow-S contrast (Sep 22)

Prior failure (desk): thin house facts + Flash reword + “say research S” + TROW chrome bleed · receipt `4f5054b0` · `S:84601d7d`. Plans in store `docs/plan-s-hollow-research-then-answer.md`.

This morning’s **desk** path is closer to research-then-answer (Hermes completed). This morning’s **Maria** path is richer prose but **weaker grounding labels** than even the hollow desk reply (which at least carried subject GUID chrome).

## Appendix B · Key paths

```
~/.openclaw/agents/maria/sessions/2e04fc8a-fe5d-454d-a09e-e7542fed5bc3.jsonl
~/.openclaw/workspace-maria/memory/2026-09-23.md
~/.openclaw/cron/          # jobs.json MISSING; .migrated/.bak only
/tmp/openclaw/openclaw-2026-09-23.log
…/data/cio/hermes_research_requests.jsonl   # res_c3a661c21740
…/data/cio/hermes_research_results.jsonl
…/data/cio/cio_operator_gap_requests.jsonl  # opr_ab7192d3b009
…/data/runtime/comms_editor_receipts.jsonl  # 14a76d62-…
Postgres: watch_directives id=1278; watchlist_items symbol=S; operator_conversation_turns id=393
```

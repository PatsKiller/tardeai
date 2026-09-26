---
cursor:
  subagentId: "bc-1a01e422-d866-536c-a006-dafc25ca729c"
---

# Plan: OpenClaw internal-first integrity (Maria → Trade-AI / Hermes before MODEL_GENERAL)

```
Status:      LIVE · PARITY LOCKED (Stages 1–3 + 5 on served pin)
as_of:       2026-09-23T12:20:00-04:00
Measured at: LIVE pin b51a866dd-main-exact-phase2-20260923-121555
             (SOURCE_COMMIT b51a866ddb02ab3229ae2916b6cf9a8d9ae4cd5e);
             remasure /tmp/remeasure-s-b51a866dd.out from CURRENT
Authority:   AGENTS.md §4 / §7 operator replies · §17 operator-only ·
             docs/OPERATOR_REPLY_ROUTING.md · docs/ops/telegram_channel_diligence_20260916/
Inputs:      docs/audit-s-sentinelone-memory-vs-research-20260923.md ·
             docs/hermes-s-backlog-20260923.md · operator STAGE 1–5 + decision
             "we need both to have same capabilities" (CIO desk ∧ Maria/OpenClaw)
Repo / host: tradeai worktree + OpenClaw under ~/.openclaw
Closeout:    internal/live-openclaw-parity-20260923.md
```

**LIVE on served pin** (prepare+promote 2026-09-23). Merged PRs on tip: #1193 join/chokepoint, #1194 ban fake specialists, #1195 watchlist honesty (+ #1196 directive union). Residual: `tradeai-cio-telegram` still on stale pin until `service` keyboard grant; organic Maria Telegram session remasure needs gateway grant (shared Maria API remasured from pin).

---

## 1 · Verdict / product intent

**Operator lock (2026-09-23):** CIO desk **and** Maria/OpenClaw must have the **same capabilities**. OpenClaw-only shortcuts that leave Maria weaker (or desk-only improvements that Maria never reaches) are **out of product scope**.

**Product intent:** On either conversational surface, for ticker perspective / buy / research / specialist take:

1. **Trade-AI house stores + CIO Hermes desk products first** (join `opr_` / `res_` / results before Hub empties).
2. **Mandatory** Sources / LEGEND / subject GUID chrome via the **shared** `finalize_operator_reply` path (or a thin wrapper that calls it — no second dialect).
3. **No fake specialists** — Iris/Alex/CIO labels only when a real specialist run happened (or the shared desk synthesis path); if OpenClaw `agentToAgent` is off, say so and do not roleplay.
4. **Watchlist honesty** — directive vs ranked `/watchlist` truth on both surfaces.
5. **Cron durability where applicable** — OpenClaw gateway cron is residual host infra (Stage 4); converse parity does not wait on it, but Maria reminders must not claim durable schedule without `jobs.json`.

Only after house+Hermes join may either surface use MODEL_GENERAL or LIVE_LOOKUP — labeled Went outside, never as house research.

**Failure this morning (Maria / OpenClaw, S):** perspective = Grok `ask` + SearXNG/stockanalysis; Iris/Alex roleplay after `agentToAgent` deny; Hermes “0 findings” while desk `res_c3a661c21740` completed ~40 min earlier; cron ids logged but `jobs.json` absent; directive **1278** real but ranked watchlist omitted S. Desk the same morning was closer (Hermes completed + receipt) but still had null GUIDs on turn 393. `[DOC-CLAIM]` audits.

**Success criterion (parity):** Remeasure ticker **S** (and one held control) on **both** Maria and CIO desk with the **same** pass table: LEGEND + Sources, joined Hermes honesty, GUID chrome or explicit unresolved, no fake specialists, watchlist honesty. Parity is fail if either surface passes and the other fails.

---

## 2 · AS-IS root causes → real files (verified / do not invent)

There is **no** Trade-AI `openclaw/reply_handler.py`. Maria’s Telegram path is the **OpenClaw gateway** + skills; CIO desk is a **separate** Python converse stack. Mixing those names is how prior plans cite ghosts.

### 2.1 Two conversational stacks (root of “two truths”)

| Surface | Bot / service | Ingress | Reply chokepoint today |
|---|---|---|---|
| **Maria / OpenClaw** (“John OpenClaw”) | `@bigjohn_openclaw_bot` · `openclaw-gateway.service` | OpenClaw bindings → agent `maria` | **None equivalent to desk** — skills + model tools; no `finalize_operator_reply` |
| **CIO desk** | dedicated CIO bot · `tradeai-cio-telegram.service` | `cio_telegram_converse` → `process_operator_message` | **Yes** — `_prepare_reply` → `finalize_operator_reply` |

`[CODE]` desk chain:

- `scripts/lib/cio_telegram_converse.py` → `process_operator_message`
- `scripts/lib/cio_converse_core.py:289` `process_operator_message`; `:373–382` `_prepare_reply` (documented “THE chokepoint”)
- `scripts/lib/reply_provenance.py:126` `ReplyProvenance`; `:408` `finalize_operator_reply`; LEGEND / pills `:79–82`
- `scripts/lib/cio_operator_desk_loop.py:3797` `handle_operator_desk_question`
- WhatsApp (CIO ingress, separate from OpenClaw WA): `scripts/lib/cio_whatsapp_ingress.py` also calls `process_operator_message` (`docs/OPERATOR_REPLY_ROUTING.md` E3)

`[DOC-CLAIM]` OpenClaw stack (from `docs/project/project_openclaw.md` + channel map; live remasure of `~/.openclaw` needs **openclaw** grant — blocked in this plan session):

- Config / gateway: `~/.openclaw/openclaw.json`, `openclaw-gateway.service` :18789
- Maria session evidence: `~/.openclaw/agents/maria/sessions/<uuid>.jsonl`
- Skills (paths referenced from Trade-AI too):  
  `~/.openclaw/skills/tradeai-readonly/scripts/tradeai_readonly.py`  
  `~/.openclaw/skills/tradeai-watchlist/scripts/tradeai_watchlist.py`  
  (+ `tradeai_query.py` NL router per project doc)
- Trade-AI bridge reference: `scripts/telegram_command_handler.py:109` `_WL_SKILL = ~/.openclaw/skills/tradeai-watchlist/scripts/tradeai_watchlist.py`

### 2.2 Cause → mechanism map

| # | Observed defect | Mechanism | Code / store that exists |
|---|---|---|---|
| A | Perspective is MODEL_GENERAL + LIVE_LOOKUP | Maria tools prefer `ask` (Grok) / `web_search` / `web_fetch` before dossier | OpenClaw skill/tool order + SOUL; **not** desk `gather_tradeai_evidence` |
| B | No Sources / LEGEND / GUID footer | Maria never calls `finalize_operator_reply` | Desk-only chokepoint above; Maria delivery is gateway Telegram mirror |
| C | “Iris / Alex CIO take” roleplay | `agentToAgent` forbidden; model invents specialist voice | OpenClaw tool policy; no Iris/Alex session rows |
| D | “0 recent Hermes findings” beside completed desk research | Hub/intelligence ≠ CIO desk results | Hub: `hermes_research_intelligence` via `_hermes_research_backlog` `scripts/api_v2.py:31200` (`LIMIT 500`); desk: `data/cio/hermes_research_results.jsonl` (`res_c3a661c21740`); Maria/Hub APIs `symbol-journey` / `self-learning/drilldown` read Hub |
| E | “Backlog 500 deep → S queued” | API page ceiling misread as FIFO depth | `api_v2.py:31223` `LIMIT 500`; `total = len(items)` — audit: 2 staged / 498 rejected; S not in list |
| F | Watch add real, ranked watchlist omits S | Directives vs combined watchlist | Writer `scripts/lib/writers/watch_directives_writer.py:450` `write_watch_directives` (identity helpers `:260+`); `POST /api/v2/watch/directives`; list `GET /api/v2/watch-directives` `:35795`; ranked/combined `watchlist_combined` `:4837` → `/api/v2/watchlist` |
| G | Cron “added” but not durable | Gateway logs write to `jobs.json`; file missing | `~/.openclaw/cron/` — audit: only `.migrated` / `.bak*`; ids `a9c337e0-…`, `729e2b82-…` in session + `/tmp/openclaw/openclaw-*.log` |
| H | Desk turn named SentinelOne but null GUIDs | Inbound tagger miss on company name | `scripts/lib/inbound_identity_tagger.py:250` `tag_inbound`; `:365` `persist_turn`; turn `operator_conversation_turns.id=393` |
| I | Hermes REQUESTED rows omit `subject_guid` | Stamp gap on enqueue | Desk lineage later carries `84601d7d-…`; request jsonl null — audit |

---

## 3 · Phased fix plan (operator STAGE 1–5, refined)

Ship **smallest correct path that delivers parity** — both consumers of one shared internal-first path. Prefer extending desk contracts; **forbid** a Maria-only LEGEND/footer that desk does not use.

**Mandatory scope (operator lock):** Stages **1 + 3** are a **shared chokepoint / shared internal-first path** consumed by CIO desk **and** Maria. Stage 2 honesty rules apply on both. Stage 5 is API-wide (both). Stage 4 is residual OpenClaw host infra (does not unblock converse parity).

### STAGE 1 — Shared reply chokepoint (desk + Maria)

**Intent:** Perspective / buy / research intents on **either** surface cannot leave without the same honesty contract.

**Design (mandatory — no OpenClaw-only interim dialect):**

1. One Trade-AI entry (library + optional HTTP skill bridge): subject resolve → house evidence → Hermes join (Stage 3) → body → **`finalize_operator_reply`** (`scripts/lib/reply_provenance.py`).
2. **CIO desk:** keep `_prepare_reply` in `cio_converse_core` as the Telegram/WA caller of that same function; close gaps (inbound GUID, Hermes request stamp) so desk meets the matrix target.
3. **Maria:** skill/SOUL **must call that entry** for those intents — not a parallel footer. Fixed order:
   1. Resolve subject (ticker or company name → identity)
   2. House reads + **join desk Hermes**
   3. Queue desk Hermes if missing (reuse desk enqueue — no second queue)
   4. `finalize_operator_reply`
   5. LIVE_LOOKUP / MODEL_GENERAL only as labeled Went outside
4. Refuse Grok `ask` as primary “perspective” when the shared path is available — on Maria **and** any desk freeform escape that would skip house join.

**Files to touch (implement wave):** OpenClaw Maria SOUL / skill entrypoints under `~/.openclaw/skills/tradeai-*` (grant required); possibly new thin bridge in Trade-AI `scripts/` that reuses `reply_provenance` + desk gather — **not** a new `@v1` type.

### STAGE 2 — Ban pseudo Iris / Alex / CIO roleplay (both surfaces)

**Intent:** Specialist labels require a real specialist run — **same rule on desk and Maria**.

- OpenClaw: if `agentToAgent` is off, say so once, then house + Hermes join only — no “Iris found…” / “Alex CIO take…”.
- Desk: “CIO take” / specialist wording must bind to real desk synthesis or named agent-job rows — never invented attribution.
- If A2A unlocked later (§17): stamp session/job id or refuse the label.
- Tests: fixtures for A2A-deny (Maria) and desk synthesis without specialist row → no fake attribution on either.

### STAGE 3 — Shared Hermes join before “0 findings” (both surfaces)

**Intent:** One subject timeline — **same join order** for desk and Maria.

Before claiming Hermes empty, **both** must join:

1. `cio_operator_gap_requests` / pending (`opr_*`)
2. `hermes_research_requests` / projection (`res_*`)
3. `hermes_research_results.jsonl` completed rows
4. Only then Hub `hermes_research_intelligence` / symbol-journey

Vocabulary (both): **analyzed-thin** (`INSUFFICIENT_DATA`) ≠ **queued** ≠ **Hub promoted 0**. Never report backlog `total: 500` as FIFO depth (`api_v2.py:31200–31223`). Hub promotion of desk results remains §17 propose-only.

### STAGE 4 — OpenClaw cron `jobs.json` (residual host infra)

**Intent:** Gateway “job added” ⇒ durable `jobs.json`. **Not** on the shared converse critical path; does **not** gate Stages 1–3–5 parity.

- Read-back after create; recover `.bak`/`.migrated`/log ids only with operator pick (§0.5).
- Needs **openclaw** grant. Desk has no equivalent store.

### STAGE 5 — Watchlist API vs `watch_directives` (shared / both)

**Intent:** Same honesty whether add came from Maria skill or desk/command.

- Print **directive id** + ranked `/api/v2/watchlist` vs directives-only truth.
- Pick promote-into-ranked **or** honest split copy (one PR policy).
- Stamp `subject_guid` via `watch_directives_writer` helpers.

### Cross-cutting (parity-critical)

- Stamp `subject_guid` / `issuer_guid` on Hermes REQUESTED rows (desk enqueue Maria also uses).
- Fix inbound company-name tagging (“SentinelOne” → GUID) for **desk turns and** any Maria path that persists turns — `inbound_identity_tagger.py`; turn 393 is the desk positive-control failure.

---

## 4 · Capability parity (operator lock) — both surfaces, same targets

### 4.1 Shared capability matrix

Same rows; **Target** is identical for CIO desk and Maria. Parity fails if only one column reaches Target.

| Capability | CIO desk **today** | Maria / OpenClaw **today** | **Target (both)** |
|---|---|---|---|
| Internal-first (house before MODEL_GENERAL / LIVE_LOOKUP) | Partial — desk gathers house; can still answer thin / Flash-reword | Fail — Grok `ask` + web first on S | **Pass** — shared path order |
| Hermes join (`opr_` / `res_` / results before “0 findings”) | Partial — can enqueue/complete; does not always join Hub vs desk; pending ledger gaps | Fail — Hub 0 while desk `res_*` done | **Pass** — shared join helper |
| Sources / LEGEND via `finalize_operator_reply` | Pass (chokepoint exists) | Fail — no chokepoint | **Pass** — same function |
| Subject GUID chrome (or explicit unresolved) | Partial — receipt can carry GUID; turn 393 null on company name | Fail — none | **Pass** — resolve + stamp |
| No fake Iris / Alex / specialist labels | Partial — different model; must not invent specialists | Fail — roleplay after A2A deny | **Pass** — real run or refuse |
| Watchlist honesty (directive id vs ranked list) | Partial — API split; desk may not spell it | Fail — “added” while `/watchlist` omits S | **Pass** — same API contract copy |
| Cron / reminder durability | N/A (not OpenClaw cron) | Fail — `jobs.json` missing | Desk: N/A · Maria: **Pass** Stage 4 (residual; see §4.3) |
| Single subject timeline across bots | Partial | Fail | **Pass** — both read same join |

### 4.2 Surfaces in scope for parity vs residual

| Surface | Parity scope |
|---|---|
| **CIO desk Telegram** + **CIO WhatsApp** (`process_operator_message`) | **In** — shared converse path |
| **Maria / OpenClaw Telegram** (and OpenClaw WA if it stays Maria-bound) | **In** — must call same path |
| Trade AI DM / Proposal Decisions | **Out** — alert/proposal bus, not perspective Q&A |
| Command Center UI | Consumes Stage 5 APIs; not a Telegram converse twin |

Source map: `docs/ops/telegram_channel_diligence_20260916/01_CHANNEL_INVENTORY_SOURCE_MAP.md`.

### 4.3 Recommendation (updated) — shared path is mandatory default

| Option | Verdict under operator lock |
|---|---|
| OpenClaw-only / Maria-SOUL-first | **Rejected** — leaves desk/Maria asymmetric; third provenance dialect risk |
| Desk-only harden, Maria later | **Rejected** — violates “same capabilities” |
| **Shared chokepoint + shared Hermes join as default mandatory scope** | **Required** — Stages 1+3 land as one library; **wire both consumers before claiming done**; Stage 5 API-wide; Stage 2 on both; Stage 4 residual OpenClaw-only |

**Residual OpenClaw-only infra:** gateway cron store (`~/.openclaw/cron/jobs.json`), OpenClaw `agentToAgent` unlock, Maria SOUL/bindings. These do not replace the shared converse path. Converse parity can ship while Stage 4 is still open **only if** Maria does not claim durable cron without read-back — otherwise Stage 4 is required before “reminders work” claims.

**Do not claim parity** until **both** Maria and CIO desk remasure S against §4.1 Target column.

### 4.4 What “agents work” means under parity

| Phrase | Shared meaning (both surfaces) |
|---|---|
| **Hermes research** | Joined desk `opr_`/`res_`/results; Hub alone is insufficient to say “0” or “queued” |
| **CIO take** | Desk synthesis / real specialist job — never invented prose on Maria |
| **Iris / Alex** | Real OpenClaw A2A session **or** refuse; desk uses Trade-AI agents/jobs, not fake A2A |
| **Watchlist add** | Same directive + ranked-list honesty |

**Naming trap:** OpenClaw agent **Maria** ≠ watchlist job lane **maria**.

---

## 5 · Operator decisions (§17) — propose and stop

| Decision | Status |
|---|---|
| **CIO desk ∧ Maria same capabilities** | **LOCKED** (operator 2026-09-23) — not optional; shared path mandatory |
| Unlock OpenClaw `agentToAgent` | Still propose — default off; Stage 2 honesty without unlock |
| Promote desk Hermes → Hub intelligence | Still propose — join-at-read until grant |
| Auto-merge divergent OpenClaw cron stores | Still propose — report both; operator picks |
| Scheduler / gateway changes for cron | Propose unit/config only |
| Route Trade AI DM into desk converse | Out of scope |

No grant invented. Implement waves needing `openclaw` / `git-push` / `release-write` request them explicitly.

---

## 6 · Test plan + verification (ticker **S** remasure)

### 6.1 Automated (Trade-AI worktree)

- Extend / add tests that **fail closed** when:
  - A Maria-bridge / shared helper returns perspective text **without** LEGEND / Sources when stores were read.
  - Join helper sees completed `res_*` for S but output claims “0 findings” / “queued not analyzed”.
  - Pseudo-specialist strings appear when A2A disabled (fixture).
  - Watchlist `add` response distinguishes directive vs ranked list (contract test against API shapes).
- Keep using existing desk pins: `tests/test_operator_reply_routing_sources_20260913.py`, inbound tagger tests (SentinelOne → GUID positive control).
- Do **not** assert Hub backlog `total == 500` as queue depth.

### 6.2 Hermetic / dry-run

- Dry-run shared helper on S with fixtures: completed `res_c3a661c21740`-shaped result → must cite analyzed-thin / INSUFFICIENT_DATA.
- Mutation: remove result fixture → must not claim desk completion; may say Hub 0 + offer enqueue.

### 6.3 Live remasure (acceptance) — both surfaces, same table

Ask **the same** question on **Maria** and **CIO desk**: “perspective on SentinelOne / S” (after Stages 1–3 + 5 wired to both).

| Check | Pass on **both** |
|---|---|
| Internal first | House / desk Hermes before web/`ask` |
| Provenance | LEGEND + Sources; Went outside only if live lookup used |
| GUID | `S:84601d7d-…` or explicit unresolved |
| Hermes honesty | Cites `res_*` or “Hub promoted 0 / desk INSUFFICIENT_DATA” — never “500 deep queued” |
| Specialists | No Iris/Alex / fake CIO labels unless real run |
| Watch | If add: directive id + ranked-list truth |
| Cron (Maria only) | If reminders claimed: `jobs.json` read-back (Stage 4) |

**Parity gate:** one surface green + the other red = **not done**.

Record: both session/turn ids, shared `opr_`/`res_` citations, receipts, watch API snapshots, as_of + pin.

---

## 7 · Out of scope / risks

**Out of scope**

- Broker / MBI_BEHAVIOR / order routes
- Replacing OpenClaw with CIO bot (parity means shared path, not one bot)
- **Maria-only or desk-only “good enough” ship** (rejected by operator lock)
- Full Hub promotion pipeline (unless §17 grant)
- Alert-bus redesign for Trade AI DM / Proposals
- Re-enabling taxonomy_tagger or unrelated research lanes

**Risks**

- **Third provenance dialect** if Maria gets a hand-rolled footer (forbidden under parity lock)
- **False parity** if only one surface remasures green
- **Cron recovery** auto-picking divergent copies (report, don’t merge)
- **agentToAgent unlock** without spend/allowlist controls
- **Name collision** OpenClaw Maria vs watchlist agent maria
- Remasure blocked without `openclaw` grant for Stage 4 / Maria live session inspect

---

## 8 · Ordered build for parity (smallest correct — Maria not left weaker)

Goal: each step raises **both** surfaces toward §4.1 Target; never ship a Maria-only dialect.

1. **Shared Hermes join library** (Stage 3) + unit tests — desk and Maria will both import; no OpenClaw grant yet.
2. **Shared internal-first entry** that ends in `finalize_operator_reply` (Stage 1) — single module/API; tests for LEGEND/Sources.
3. **Wire CIO desk** through that entry (close GUID stamp + Hermes REQUESTED guid + company-name tagger for turn-393 class) so desk Target column is honest, not “assumed already fine.”
4. **Wire Maria skill/SOUL** to the **same** entry (Stage 1+3 consumer #2) — Grok-first perspective banned; no interim fake footer.
5. **Stage 2** refuse fake specialists on **both** (A2A-deny fixture + desk attribution fixture).
6. **Stage 5** watchlist/directive honesty API-wide — both consumers inherit.
7. **Dual remasure on S** (Maria ∧ desk) against §6.3 — parity gate.
8. **Request openclaw grant** → Stage 4 cron durability + reminder honesty (residual; after converse parity or blocking only if Maria claims schedules).
9. **§17 propose** only for A2A unlock and/or Hub promotion — not required for converse parity.

---

## 9 · See also

- `docs/audit-s-sentinelone-memory-vs-research-20260923.md`
- `docs/hermes-s-backlog-20260923.md`
- `docs/plan-s-hollow-research-then-answer.md` (desk hollow path — complementary, not duplicate)
- `docs/OPERATOR_REPLY_ROUTING.md`
- `docs/ops/telegram_channel_diligence_20260916/01_CHANNEL_INVENTORY_SOURCE_MAP.md`
- `docs/project/project_openclaw.md`

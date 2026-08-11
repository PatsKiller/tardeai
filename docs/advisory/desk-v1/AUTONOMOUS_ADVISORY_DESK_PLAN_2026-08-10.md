# Plan: Autonomous Advisory Desk (CIO + Wealth Advisors)

**Branch:** `feature/advisory-desk-v1`  
**Authority:** `READ_ONLY_ADVISORY` only — no broker, order, stop, approval, or 2FA authority  
**Model order:** DeepSeek **Flash first** (per-row opinions) → DeepSeek **Pro** (desk synthesis / CIO)  
**Date:** 2026-08-10  
**Doc location:** `docs/advisory/desk-v1/`  
**P0 outcome:** [P0_BRIDGE_OUTCOME_2026-08-11.md](./P0_BRIDGE_OUTCOME_2026-08-11.md) (bridge path + live cap refuse — closed 2026-08-11)  
**Phase 1 outcome:** [PHASE1_DATA_TRUTH_OUTCOME_2026-08-11.md](./PHASE1_DATA_TRUTH_OUTCOME_2026-08-11.md) (lots, validation, Risk/Tax holdings — closed 2026-08-11)  
**Phase 2 outcome:** [PHASE2_QUALITY_CACHE_OUTCOME_2026-08-11.md](./PHASE2_QUALITY_CACHE_OUTCOME_2026-08-11.md) (evidence, cache, Pro synthesis — closed 2026-08-11)  
**Phase 3 outcome:** [PHASE3_MEMORY_OUTCOME_2026-08-11.md](./PHASE3_MEMORY_OUTCOME_2026-08-11.md) (history, feedback, thrash, outcomes — closed 2026-08-11)  
**Phase 4 outcome:** [PHASE4_SURFACE_DELIVERY_OUTCOME_2026-08-11.md](./PHASE4_SURFACE_DELIVERY_OUTCOME_2026-08-11.md) (API, UI, Telegram — closed 2026-08-11)  
**Phase 5 outcome:** [PHASE5_SHADOW_OUTCOME_2026-08-11.md](./PHASE5_SHADOW_OUTCOME_2026-08-11.md) (shadow sessions + Guardian/Ledger — closed 2026-08-11)  
**Phase 6 outcome:** [PHASE6_LESSONS_BROKER_OUTCOME_2026-08-11.md](./PHASE6_LESSONS_BROKER_OUTCOME_2026-08-11.md) (lessons KB + notif broker — closed 2026-08-11)  
**Phase 7 outcome:** [PHASE7_PROMOTION_OUTCOME_2026-08-11.md](./PHASE7_PROMOTION_OUTCOME_2026-08-11.md) (30-session promotion gate — closed 2026-08-11)  
**Autonomy / scheduling truth:** [AUTONOMY_AND_SCHEDULING_TRUTH_2026-08-11.md](./AUTONOMY_AND_SCHEDULING_TRUTH_2026-08-11.md) (brains vs timers — 2026-08-11)

---

## 0. What “100% autonomous” means here

| Allowed (target) | Forbidden (by design) |
|---|---|
| Unattended **deterministic** desk rebuild every morning | Any agent placing/modifying orders or stops |
| Unattended **Flash** opinions on changed/actionable rows | Agents holding broker credentials or 2FA |
| One **Pro** synthesis → “three things today” | Silent budget override / cap bypass |
| Memory, feedback, calibration, lessons | Config promote / risk-limit mutation |
| Telegram/email brief + `/advisory` ack/rate/snooze | “Yes, deploy $15k” executing without existing proposal+2FA path |
| CIO (Alex) + Steph/Morgan wealth **shadow advisory** loops | Production activation without P2 auth gates |

**Honest product target:** a fully autonomous **advisory factory** that observes, reasons, remembers, and surfaces decisions for a human — not an autonomous trader.

### Scheduling honesty (do not skip)

| Reality | Detail |
|---|---|
| **Not free-running agents** | Desk and fleet jobs are **systemd timer → oneshot**. Agents cannot self-reschedule. |
| **Brains = LLM on the job** | Flash/Pro run when a scheduled (or manual) job hits the bridge under cap — not a continuous “always thinking” process. |
| **Fleet today** | `agent_runtime@*` is SHADOW/prepare-only; on host 2026-08-11 many units **fail** (queue module misconfig). Desk does not depend on them for promotion. |
| **Promotion** | Never automatic. 30 consecutive green sessions + operator `promote --confirm`. |

Full table of timers and host truth: [AUTONOMY_AND_SCHEDULING_TRUTH_2026-08-11.md](./AUTONOMY_AND_SCHEDULING_TRUTH_2026-08-11.md).

---

## 1. Ground-truth scorecard (code + runtime, not the design doc alone)

Verified on host / `feature/advisory-desk-v1` as of 2026-08-10/11.

| Layer | Design claim | Actual state | Evidence |
|---|---|---|---|
| **P0 Governed bridge** | Must be in path | **BROKEN** — DeepSeek hard-bypasses to `api.deepseek.com`; port **8766 not listening**; caps not enforced | `advisory_opinion_engine._call_bridge` lines 92–113; `ss` empty on 8766 |
| **L0 Data truth** | Lots, OHLCV, identity | **Mostly built.** 29 holdings `lot_data_status=VERIFIED` in latest snapshot; S6: 19/25 txn-rebuilt, 2 UNTRUSTED historically; rebuild is **one-shot** (`_s6_rebuild_lots.py`), not scheduled | `advisory_desk_latest.json`; `S6_REPORT.md` |
| **L1 Deterministic rows** | 50 rows / 4 classes | **Working.** 52 rows (29 hold / 12 watch / 9 alloc / 2 closed); underweight→EXIT fixed (materiality floor) | snapshot metadata |
| **L2 Validation** | invariants + plausibility | **Built.** External invariants applied in build; `validate_advisory_output` exists but **not auto-invoked** after build | `advisory_desk.py` |
| **L3 Evidence** | 10 sources | **13 types wired.** Mean **11.86** items/holding. Gaps: catalysts/technicals/earnings/analyst still common | evidence_items histogram |
| **L4 Memory** | history/feedback/outcomes/lessons | **Missing** for this desk. No `advisory_rows.jsonl`; no rate codes; no desk calibration. (Separate: dual-opinion / `wire_advisory_lessons` / CIO Darwin JSONL — not this product) | filesystem + code search |
| **L5 Opinion (Flash)** | Flash per row + cache | **Partial.** Engine + `advisory_opinion_cache.json` (39 keys). Latest desk snapshot `llm_in_path=False` (deterministic-only refresh). Direct DeepSeek bypass. Prompt is **volatile full dump** (no stable-prefix cache design) | opinion engine + cache |
| **L6 Synthesis (Pro)** | One Pro “three things” | **Function exists** (`generate_desk_synthesis`) but **always uses lane[0]=flash**; Pro lane unused | engine line ~408; S6: 10/10 flash |
| **L7 Delivery** | `/v3/advisory` + Telegram | **Not started** (S6 Tracks C/D) | S6_REPORT |
| **Agent opinions** | Maria/Risk/Tax | **Maria only on holdings** (22/22 last S6; 176 maria / 0 risk / 0 tax in 7d on holdings). risk_agent has 390 rows fleet-wide but not mapped to held symbols | DB query |
| **CIO / wealth fleet** | Autonomous agents | **Shadow infrastructure built; production fleet not truly autonomous.** Heartbeat GATE_A contained; agent_runtime timers prepare-only / opt-in; Steph OpenClaw digests live but Wave-3 wealth durable path incomplete; Guardian/Ledger DESIGNED | roster + systemd + crontab backup |

### Critical bugs (must fix before trusting cost or quality metrics)

1. **Bridge bypass** — config says `127.0.0.1:8766`, runtime ignores it for `provider=="deepseek"`.
2. **No systemd unit** for `cio_governed_model_bridge.py` (only `scripts/_s6_start_bridge.sh`).
3. **Synthesis wrong lane** — Pro configured for synthesis, Flash always selected.
4. **Catalyst cache hardcode** — `catalyst_cache_2026-08-10.json` (stales daily).
5. **Plausibility validator not on the build path.**
6. **Lot rebuild not productionized** (one-shot script).
7. **Risk/Tax never enqueued for holdings** (Maria-only evidence).
8. **Doc/registry drift** — maturity catalog vs `definitions.py` vs AGENT_ROSTER disagree on Steph/Morgan/Ledger enablement.

---

## 2. Architecture (target — aligned with design doc)

```
L7  DELIVERY      Telegram brief · /advisory commands · /v3/advisory page
L6  SYNTHESIS     ONE DeepSeek Pro call — "three things today" (dollars-first)
L5  OPINION       DeepSeek Flash per changed/actionable row · local hash cache
L4  MEMORY        prior verdicts · feedback reason codes · outcomes · lessons
L3  EVIDENCE      13 sources, staleness + gaps reported
L2  VALIDATION    external invariants · plausibility · numeric integrity
L1  DETERMINISTIC row universe + verdicts — zero LLM
L0  DATA TRUTH    holdings · lots · OHLCV · analyst · instrument identity
        ▲
   GOVERNED BRIDGE (8766) — only paid LLM egress
        ▲
   Bitwarden SM → /run/user/1000/tradeai/env → deepseek_tradeai
```

**Standing fences**

- L0→L1 trust: UNTRUSTED data suppresses derived signals (already partially done for lots/`long_held`).
- L1→L5 determinism: model never invents numbers; validator rejects numeric/citation freelancing.
- L4 is evidence-only: memory never overrides current evidence silently.
- L5 Flash / L6 Pro only via bridge; desk sub-budget + `LLM_GLOBAL_DAILY_USD_CAP` enforced.
- No path from opinion → order without existing proposal queue + human approval + per-order 2FA.

### Model policy (explicit)

| Workload | Model | Process / task_type |
|---|---|---|
| Per-row opinion | **deepseek-v4-flash** | `advisory_opinion` / FAST |
| Desk synthesis (“three things”) | **deepseek-v4-pro** | `advisory_synthesis` / PRO |
| Alex CIO material synthesis (later) | Pro (+ PRO_THINK on disagreement) | `alex_cio_synthesis` |
| Steph routine narratives | Flash | `watchlist_steph_flash_narrative` |
| Steph allocation review | Pro default | `steph_allocation_review` |
| Morgan wealth | Flash | `morgan_wealth_synthesis` |
| Tax lane Roth/IRMAA/SSDI | **Claude-only** (operator decision #5 — do not creep to DeepSeek) | existing tax policy |

`never_escalate_to`: pro-think / pro-max for routine desk rows.

### Cache cost model (Phase 2B)

1. **Local opinion cache** (already exists): material-field hash only (price 0.5%, weight 0.1pp, P&L 0.5pp).
2. **Provider prefix cache**: rewrite prompts stable-first / volatile-last (no timestamp/run-id/symbol in system prefix).
3. Telemetry required every run: `input_tokens`, `cached_tokens`, `cache_hit_rate`, `cost_usd`, `rows_called`, `rows_cache_hit`. Target ≥70% provider hit after warmup; second identical run = 0 model calls.

---

## 3. Agent roles in the autonomous advisory desk

| Agent | Role in desk | Today | Target autonomy |
|---|---|---|---|
| **Deterministic desk** | L0–L3 factory | Built | Daily unattended |
| **Maria** | Research opinion into evidence | Holdings coverage LIVE | Keep Flash; ensure holdings queue |
| **Risk / Guardian** | Risk critique on holdings + concentration | Watchlist only / DESIGNED durable | Flash opinions on holdings; Guardian shadow artifacts |
| **Tax / Ledger** | Tax/lot context on holdings; Roth ladder later | Almost empty on holdings; Ledger DESIGNED | Flash tax critique; Claude for Roth/IRMAA; no execution |
| **Steph** | Wealth / allocation advisor | OpenClaw digests LIVE; Wave-3 incomplete | Morning cash/allocation narrative feeds synthesis |
| **Morgan** | Multi-account wealth synthesis | Scaffold | Shadow wealth brief |
| **Alex (CIO)** | Final “three things” owner + specialist handoffs | Shadow state exists; heartbeat contained | Consumes desk synthesis; no broker authority |
| **Darwin** | Outcome scoring / calibration | CIO scorecards exist; desk not wired | Score desk verdicts 30/60/90d |
| **Iris** | Lesson ratification | Taxonomy only | Ratify `kb_lessons` for desk |
| **Sentinel** | Reviewer on specialist artifacts | Partial | Review Guardian/Ledger shadow artifacts |

**Do not build trading autonomy.** Build **unattended advisory loops** that always stop at human decision.

---

## 4. Phased implementation plan

Phases are **gates**. Flash path must work under the bridge before Pro synthesis spend, surface work, or agent-fleet expansion.

### Phase 0 — P0 Cost governance (BLOCKING)

**Goal:** Every DeepSeek call from the desk goes through port 8766; cap exhaustion refuses.

| # | Work item | Files / ops |
|---|---|---|
| 0.1 | Remove DeepSeek direct override in `_call_bridge`; always hit bridge endpoint + headers | `scripts/lib/advisory/advisory_opinion_engine.py` |
| 0.2 | Ensure process registry entries for `advisory_desk_opinion` / `advisory_synthesis` with daily USD caps | `config/llm_process_registry.json`, bridge caller map |
| 0.3 | Install **user systemd unit** for bridge: `CIO_BRIDGE_MODE=canary`, port 8766, `EnvironmentFile=-%t/tradeai/env` (or source `deepseek_tradeai`), `After=tradeai-sm-render.service` | `~/.config/systemd/user/cio-governed-bridge.service` (+ timer optional); reuse `_s6_start_bridge.sh` pattern |
| 0.4 | Wire `ADVISORY_DESK_V1` flag (default OFF) for enrichment path | `config/advisory_desk.yaml` + callers |
| 0.5 | Forced-exhaustion test: set temp micro-cap → next call **refused** → log proves refusal | test under `tests/` + ops evidence JSON |

**Pass (design 1.1):** Bridge listening; live row call shows bridge headers/process settlement; refuse-at-cap proof.

**Stop rule:** No further paid desk runs until 0.5 is green. Treat all cost figures as unenforced until then.

---

### Phase 1 — Data truth & multi-agent evidence (Flash path only)

**Goal:** Trustworthy facts + Maria/Risk/Tax on holdings; Flash opinions only when data is trusted.

| # | Work item | Notes |
|---|---|---|
| 1.1 | Productionize lot rebuild after holdings sync | Promote `_s6_rebuild_lots.py` → scheduled job; mark UNTRUSTED when share mismatch >5%; never invent lots |
| 1.2 | Resolve/document CUSIP + AMANX/V UNTRUSTED cases | Manual CUSIP ID; AMANX basis anomaly |
| 1.3 | Fix catalyst cache path (latest / glob, not hardcoded date) | `advisory_desk.py` |
| 1.4 | Auto-run `validate_advisory_output` after build; surface failures in metadata | Soft-fail flag + hard-fail for delivery |
| 1.5 | Enqueue **risk_agent + tax_agent** jobs for current holdings symbols (not watchlist-only) | `process_watchlist_agent_jobs.py` or holdings-targeted scheduler |
| 1.6 | Flash enrichment only via bridge; respect `max_model_rows_per_run` + materiality | Opinion engine |
| 1.7 | Document conviction rule (thesis confidence ≠ size); same-instrument account basis may differ deterministically | Already partially in YAML; add unit fixtures |

**Pass:** design 1.1–1.7 (bridge, lots, UNTRUSTED suppression, 0 invariant violations, OHLCV coverage, agent opinions ≥25/29 with multi-agent mix, conviction fixtures).

**Model:** Flash only. No Pro synthesis spend yet.

---

### Phase 2 — Quality + cache (Flash mature; Pro synthesis introduced)

#### 2A Evidence quality

- Close top gaps (catalysts, technicals, analyst) where data exists.
- Rank actionable rows by **dollars at stake** for model coverage.
- Require model coverage on 100% of actionable rows above materiality floor.

#### 2B Cache & telemetry

- Split prompt: stable system (taxonomy, IPS, schema, examples) → semi-stable universe → volatile evidence+memory+ask.
- Material-field `advisory_row_hash` buckets.
- Log cache hit rate; investigate if &lt;70% after warmup.
- Prove second identical run = **0** model calls (local cache).

#### 2C First Pro call (only after 2B warmup)

- Fix `generate_desk_synthesis` to `prefer_lane="deepseek-pro"` + task_type `advisory_synthesis`.
- **One** Pro call per desk run. Never parallel second synthesizer (standing rule #11).
- Synthesis must lead with largest dollar item (cash concentration / SCHD-class issues).

**Pass:** design 2.1–2.6.

---

### Phase 3 — Memory (what makes it an advisor)

| Track | Deliverable |
|---|---|
| **3A Verdict history** | Append-only `data/runtime/advisory_rows.jsonl` (or Postgres); inject prior verdict/conviction/key_risk/thrash count into memory block; thrash penalty on conviction |
| **3B Feedback** | `/advisory rate <row_id> notuseful <REASON_CODE>` with fixed codes; store per-symbol + pattern; `DISAGREE_THESIS` surfaces next run |
| **3C Outcomes** | Darwin-style deterministic scorer at 30/60/90d on desk verdicts; calibration table; **no model self-assess** |

Memory enters prompts as evidence only (design §5.5).

**Pass:** design 3.1–3.6.

---

### Phase 4 — Surface & delivery

| Track | Deliverable |
|---|---|
| **4A** | `/api/v3/advisory` + CC v3 page: classes, expand (lots, price action, analyst, memory), data-quality column, 5 banner states |
| **4B** | Telegram section to both chat IDs (≤+5 lines on brief); `/advisory` ack/rate/snooze → ledger; **prove every pre-existing alert still fires** |

Flag `ADVISORY_DESK_V1` remains operator-only until Phase 5.

**Pass:** design 4.1–4.6.

---

### Phase 5 — Shadow autonomy for desk + missing specialists

Run **20 sessions** flag ON for operator only:

- No invariant violations; no plausibility failures reaching operator.
- Spend within budget every session.
- Operator useful-rate ≥60% on actionable rows; zero indefensible verdicts.
- Document median changed-rows/day (cost model truth).

In parallel (specialist shadow — design “Guardian & Ledger”):

| Specialist | First mandate | Gate |
|---|---|---|
| **Guardian** | Cash concentration / IPS breach | SHADOW, Sentinel review, Darwin score ≥20 artifacts, 0 contradictions |
| **Ledger** | Roth conversion ladder → Golden Window (Claude-only tax numbers) | Same; no DeepSeek tax-lane creep |
| **Steph** | Capital deployment narrative on idle cash (operator decision #3) | Feeds desk synthesis; no rebalance.execute |
| **Alex** | Owns one synthesis; delegates; no second competing summary | Wake path uses `cio_wake_dispatch_entrypoint` not legacy inline worker |

**Optional fleet enablement** (operator gates, not automatic):

- Un-contain `cio_heartbeat` only after P0+Phase1 green.
- Enable agent_runtime timers only with `/etc/tradeai/agent_runtime_enabled` + `AGENT_RUNTIME_OPERATOR_AUTH` + provider module proven.
- Do **not** set `production_activation_authorized` until final promotion gate.

---

### Phase 6 — Lessons + notification broker

- `kb_lessons` + pgvector (`qwen3-embedding:8b`); Iris ratifies; auto-retire &lt;40% hit rate over 20+ apps.
- Nightly reflection proposes candidates; max 5 lessons injected per row.
- Notification broker: ingest Telegram producers at Tier D chokepoint; **egress cutover only after zero material drops**.

**Pass:** design 6.x + broker compression ratio proof.

---

### Phase 7 — Final promotion (desk as default morning path)

All must hold for **30 consecutive sessions**:

- Zero indefensible verdicts  
- ≥60% useful rate  
- Spend within budget  
- Invariants + plausibility green  
- Every existing alert intact  
- Authority fence unchanged (no broker credentials on any agent)

---

## 5. PR / workstream breakdown (implementation order)

| PR | Title | Depends on | Scope |
|---|---|---|---|
| **PR-0a** | Route advisory opinions through governed bridge | — | `advisory_opinion_engine.py` remove bypass; bridge headers; process IDs |
| **PR-0b** | systemd `cio-governed-bridge` + sm-render order | PR-0a | unit files, env from `%t/tradeai/env` |
| **PR-0c** | Cap-exhaustion proof test + ops evidence | PR-0b | tests + evidence artifact |
| **PR-1a** | Lot rebuild production job + UNTRUSTED labels | PR-0c | promote rebuild script; schedule after holdings |
| **PR-1b** | Evidence hygiene (catalyst path, plausibility on build) | PR-0c | `advisory_desk.py` |
| **PR-1c** | Holdings jobs for risk_agent + tax_agent | PR-1b | processor / scheduler |
| **PR-1d** | Flash enrichment under flag + materiality selection | PR-0c, 1b | dry_run=False path gated by `ADVISORY_DESK_V1` |
| **PR-2a** | Stable-prefix prompts + material hash + telemetry | PR-1d | opinion engine + yaml |
| **PR-2b** | Pro synthesis lane fix (one call) | PR-2a | `generate_desk_synthesis` |
| **PR-3a** | `advisory_rows.jsonl` + history injection + thrash | PR-2b | memory L4-A |
| **PR-3b** | Feedback reason codes + storage API | PR-3a | L4-B |
| **PR-3c** | Outcome scorer + calibration | PR-3a | Darwin desk path |
| **PR-4a** | `/api/v3/advisory` + CC v3 page | PR-3a min | surface |
| **PR-4b** | Telegram brief + `/advisory` commands | PR-4a | delivery; alert regression proof |
| **PR-5** | Shadow 20 sessions + Guardian/Ledger first mandates | PR-4b | ops + specialist |
| **PR-6** | kb_lessons + Iris + notification broker | PR-5 data | learning + egress |

Each PR must include: tests, ops evidence path, and **explicit unmet criteria** (standing rule #7 — no self-certify with explanation).

---

## 6. Explicit non-goals (until separate gates)

- Live order / stop / rebalance execution by any agent  
- Natural-language “yes, deploy $X” that skips proposal queue + 2FA  
- DeepSeek on Roth/IRMAA/SSDI tax-lane (Claude-only until operator reopens)  
- Raising global LLM cap without a measured week of bridge telemetry  
- OpenClaw dual-key spend outside Trade AI consumption ledger  
- Enabling full agent_runtime fleet without provider + auth gates  

---

## 7. Operator decisions needed (block or shape later phases)

From design §10 — recommend defaults for planning:

| # | Decision | Recommended default |
|---|---|---|
| 1 | November 15 scope | Keep date; **narrow** to Phases 0–4 + shadow start if slip |
| 2 | Ledger vs Guardian first | **Guardian first for cash concentration** (largest current risk visible in S6 synthesis); Ledger next for Golden Window clock |
| 3 | $533K / ~$514K idle cash | Operator must declare **deliberate vs drift** before Steph capital-deployment narrative is “actionable” |
| 4 | Global LLM cap $0.25/day | Keep until Phase 2B telemetry; then size from observed changed-rows × Flash + 1 Pro |
| 5 | Tax-lane Claude-only | **Hold** — do not let desk Flash/Pro absorb Roth math |
| 6 | CUSIP resolution | Manual identify 3 unknowns to unlock allocation row |
| 7 | Steph unblocking | Enable wealth narrative into desk synthesis after P0+1; still no rebalance.execute |

---

## 8. Success definition (product)

Every morning, without human prompt:

1. SM env rendered → bridge up → desk rebuilds deterministic rows.  
2. Flash opinions only for material/changed rows under cap.  
3. One Pro synthesis: three things, each with verdict, reason, strongest counter-argument.  
4. Memory: prior stance + operator disagreement + outcome trust rate.  
5. Delivery: one short Telegram + full page; existing alerts unchanged.  
6. Human still owns every order.

---

## 9. Immediate next actions (when leaving plan mode)

1. **PR-0a/0b/0c** only — fix bridge path and prove cap refuse.  
2. Re-run a 5–10 row Flash opinion under bridge; attach consumption ledger lines.  
3. Then PR-1c (Risk/Tax on holdings) — highest quality lever for free once Flash is governed.  
4. Do **not** start CC v3 or Telegram until Phase 0 pass is evidenced.

---

## 10. Key file index

| Area | Path |
|---|---|
| Deterministic desk | `scripts/lib/data_broker/advisory_desk.py` |
| Opinion / synthesis | `scripts/lib/advisory/advisory_opinion_engine.py` |
| Routing config | `config/advisory_desk.yaml` |
| Governed bridge | `scripts/lib/cio_governed_model_bridge.py` |
| Bridge starter | `scripts/_s6_start_bridge.sh` |
| Lot rebuild (one-shot) | `scripts/_s6_rebuild_lots.py` |
| Agent job processor | `scripts/process_watchlist_agent_jobs.py` |
| Model / process registries | `config/llm_model_registry.json`, `config/llm_process_registry.json` |
| Agent defs / maturity | `scripts/agent_runtime/agents/definitions.py`, `config/agent_maturity_catalog.json` |
| Steph wealth docs | `docs/wealth-advisor/STEPH_WEALTH_ADVISOR.md` |
| CIO durable state | `data/cio/` |
| Live artifacts | `data/runtime/advisory_desk_latest.json`, `data/runtime/advisory_opinion_cache.json` |
| Diagnostics | `S1_DIAGNOSIS_2026-08-10.md`, `S6_REPORT.md` |
| SM env | `/run/user/1000/tradeai/env` ← `tradeai-sm-render` ← Bitwarden `trade-ai-prod` / `deepseek_tradeai` |

---

## 11. Risk register

| Risk | Mitigation |
|---|---|
| Cap too low → silent dry-run culture returns | Bridge refuse is loud; dry_run default stays True until flag ON |
| Pro synthesis doubles cost | One call; Flash-only until Phase 2C |
| Agent opinions swamp context | Cap 3 agents × short narrative; prefer holdings materiality |
| Memory overrides evidence | Prompt + validator: conflict must be stated |
| Enabling agent_runtime fleet thrash | Keep prepare-only until desk Phase 5 green |
| Operator confuses advisory with execution | Banner + fence tests; no credentials on agents |

---

*Advisory only. Live trading remains behind existing approval, per-order 2FA, and shadow requirements. No component of this plan grants broker credentials or order endpoints to agents.*

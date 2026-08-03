# Trade AI v12 — Comprehensive Platform Audit & Autonomy Assessment

**Date:** 2026-08-02 (evidence through ~22:35 ET / 2026-08-03 UTC)  
**Scope:** Command Center v3 end-to-end — product quality, DeepSeek LLM, agent autonomy, research/watchlist/defense, platform autonomy  
**Mode:** Assessment only (no production code changes)  
**Primary code trees:**

| Tree | Role | SHA / pin |
|------|------|-----------|
| Live server `:7777` | **Actual runtime** (ad-hoc) | `trade-ai-v12-rebuild` @ `72b6ddd2` |
| Guardrails worktree | Active engineering / this audit | `dcafb411` |
| systemd release (inactive) | Intended production pin | `7ea3db55-cio-propose-block` → SOURCE `7ea3db55-reentry…` |
| Vite preview `:7791` | Stale preview bundle | guardrails UI |

**Evidence pack:** `docs/audits/platform-autonomy-2026-08-02/`  
(screenshots, `page_audit.json`, `live_metrics.json`, `deepseek_probe.json`, `db_stats.json`, sub-findings)

**Book context (live):** Portfolio ≈ **$1,255,396** · cash ≈ **$580k** · VIX 17.1 · regime “risk on” 33%

---

# 1. Executive Summary

## 1.1 One-line verdict

Trade AI v12 is a **highly automated institutional *advisory factory*** with a **broken paper-capital closed loop** and **intentionally human-gated live capital**. It is **not** a truly autonomous investment intelligence platform today.

## 1.2 Key findings

1. **Deploy is not singular (P0 ops).** systemd `portfolio-server` is **inactive**; live traffic is an ad-hoc process from a different tree than the release pin and the active guardrails worktree. Autonomy claims cannot be trusted until one spine owns code + cron + UI + data.
2. **32/32 audited hubs load** under Playwright against live `/v3` — UI shell is resilient. **Business truth is stale** on the metric strip (Trading/Realized/Setups marked **STALE · Jul 31**, 10d old) and several intel surfaces still fire aborted/failed requests under load.
3. **Paper ATM is “active” but not productive.** `mode=active`, only Alpaca paper account enabled; paper-proposals **ready_count=0**, pending thin; DB shows proposals overwhelmingly **EXPIRED/REJECTED**; ATM last cycle **0 new** and live Schwab accounts **disabled**. Design claims “paper fully autonomous”; practice is a **starved funnel**.
4. **Discovery automation is huge and low-edge.** Watchlist warehouse **12,502** rows; **11,473** `ai_discovered`; only **61** `active`. Median **21d α vs SPY for ai_discovered = −2.43%** (n=1,513 with α). MAIN admission correctly **excludes** raw `ai_discovered`; quality gate is **visibility-only** (does not block intake).
5. **Agents are prompt pipelines, not autonomous agents.** Catalog: **0 PRODUCTION**, `production_activation_authorized=false`, all order/broker authorities **DENIED**. Maria produced **17,356** results with **0 BUY / 0 SELL / all HOLD**. Hermes is the strongest multi-step research system — still rule-capped and advisory.
6. **DeepSeek is wired but not primary in production traffic.** Lanes available; direct Flash call returns `PONG` in ~0.9s. Consumption still dominated by **Grok** (1,902 calls/mo) and **ChatGPT** (691); **DeepSeek-v4 only 4 calls**; **Flash absent from by_lane**. Process registry: **22/28 manual**, all automated processes still **`allowed_lanes: [grok, chatgpt]`**. Live `llm_lane.generate` default is **`grok`** (rebuild tree).
7. **Research desk is semi-autonomous and useful** — but **36/50** visible items need refresh; holdings_linked **0** on desk stats; staging→trade is human; learning scorecard mostly **nulls**.
8. **Defense is structurally advanced, capital-inert.** Recommendations **`mode: SHADOW`** as of **2026-07-31**; promote criteria locked with empty decisions; no autonomous live rebalance.

## 1.3 Critical risks

| ID | Risk | Sev |
|----|------|-----|
| R1 | Multi-tree deploy drift (release ≠ live ≠ worktree) | **P0** |
| R2 | Stale trading/realized/setup metrics (10d) on primary strip | **P0** |
| R3 | Paper autonomy claimed but funnel starved (ready=0, EXPIRED mass) | **P0** |
| R4 | Discovery scale without edge (median α −2.43%) + no auto-block | **P1** |
| R5 | DeepSeek “primary” narrative vs Grok-primary reality / ManualRequired gates | **P1** |
| R6 | Agent UI implies autonomy; Maria=HOLD factory; catalog SHADOW theater | **P1** |
| R7 | Learning does not rewire MAIN weights / ATM gates (locked + graft_forbidden) | **P1** |
| R8 | Defense stuck SHADOW; outcomes n≈0; structural maturity ≠ proven | **P2** |
| R9 | Grok weekly failure rate high (201/382) — reliability of OAuth primary path | **P1** |
| R10 | Journal↔discovery attribution incomplete → cannot learn true source P&L | **P2** |

## 1.4 Highest-priority opportunities

1. **Single runtime spine** — one tree, systemd green, cron cwd, UI build, release SHA identical.  
2. **Unblock paper closed loop** — account routing, enrichment SLA, proposal ready_count > 0, ATM fill proof weekly.  
3. **Make quality gates consequential** — fold/block underperforming sources at insert; auto-tune α floors from outcomes.  
4. **Finish DeepSeek migration** — process registry allowed_lanes + automated modes for Maria/CIO/Hermes; kill Grok-as-default split-brain; wire cache.  
5. **Wire outcome bus → ranking/ATM (paper-only)** — unlock research graft first, then MAIN weights under paper gates.  
6. **Exit Defense SHADOW** via locked promote criteria → paper twins only (not live Schwab).  
7. **Cull agent theater** — ship only agents with outcomes; label the rest DESIGN/SHADOW in UI.

## 1.5 Autonomy score (preview)

| Dimension | Score /10 |
|-----------|----------:|
| **Overall investment-intelligence autonomy** | **4.5** |
| Ops automation (cron/pipelines) | 7.5 |
| Research factory | 6.5 |
| Idea → capital (paper) | 2.5 |
| Live capital autonomy | 1.0 (by design) |
| Learning that changes money policy | 2.0 |
| DeepSeek as primary paid LLM | 5.0 |
| UI product completeness | 6.5 |

---

# 2. Environment freeze (evidence)

```
Live :7777 cwd  = trade-ai-v12-rebuild @ 72b6ddd2
systemd unit    = inactive (dead) since 2026-08-02 13:31
Release pin     = 7ea3db55-cio-propose-block (not serving)
Guardrails      = dcafb411
UI build-meta   = 3.14+mscln59n · built 2026-08-03T02:17Z
Health          = ok, holdings_exists=true
Playwright      = 32/32 routes HTTP 200, no error boundaries
```

**Finding:** Any scoreboard that says “platform maturity 4.95/5” measures **broker safety**, not autonomy and not deploy integrity.

---

# 3. Detailed page-by-page audit

## 3.1 Method

- **Static:** routes from `App.tsx` / `NavRail`; API greps; prior broker-registry gaps (13 pages undeclared).  
- **Live Playwright:** 32 hub/tab states → screenshots under `platform-autonomy-2026-08-02/screenshots/`.  
- **API/DB:** smoke + portfolio DB for warehouse truth.  
- **Questionnaire** applied per hub (Working / Missing / Confusing / Not actionable / Automate / Remove / Redesign).

Severity: **P0** money-path/false data · **P1** core workflow dead-end · **P2** automation/UX debt · **P3** polish.

## 3.2 Platform chrome (all pages)

| Issue | Sev | Detail |
|-------|-----|--------|
| Metric strip STALE | **P0** | Trading 50.9% · $37,890 · **10d old**; Realized $152k · **10d old**; Setups **STALE Jul 31** |
| 17 Approvals / 12 Health / 2FA LIVE TRADE chips | OK | Actionable chrome present |
| Multi-MB API storms | **P1** | Re-Entry/Risk abort many `watchlist/items?symbol=` under concurrency |
| Nav hub sprawl | **P2** | ~20 hubs × 70–90 tabs — cognitive overload |

## 3.3 Tier A hubs (deep)

### Home (`/`)
| | |
|--|--|
| **Working** | Command brain, portfolio value, regime/VIX, inbox chips, defense posture strip lineage |
| **Missing** | Single “do next” queue that merges Approvals + Defense + stale pipeline remediation |
| **Confusing** | STALE badges mixed with live portfolio $ (trust split) |
| **Not actionable** | STALE tiles without one-click “run pipeline X” |
| **Automate** | Auto-remediate stale trading metrics when cron missed |
| **Remove** | Decorative empty KPI shells if no data |
| **Redesign** | Operator Inbox as primary surface; metrics secondary |
| **Biz value** | High | **Sev** | P0 stale truth |

### Portfolio (`/portfolio`) + Re-Entry
| | |
|--|--|
| **Working** | Holdings depth, stop management lineage, re-entry dense (1k+ buttons) |
| **Missing** | Reliable per-symbol enrichment without request abort storms |
| **Confusing** | Multiple stop/protection narratives across tabs |
| **Not actionable** | Cards without sized next trade when cash available |
| **Automate** | Re-entry candidate → paper proposal with stop note (E3) |
| **Remove** | Duplicate stop views if overlapping Protection advisor |
| **Redesign** | Cap parallel symbol fetches; server-side batch |
| **Biz value** | High | **Sev** | P1 (abort storms) |

### Trading (Trade AI / Proposals / ATM)
| | |
|--|--|
| **Working** | Tab model complete; ATM status readable; proposals list |
| **Missing** | **Ready proposals**; ATM throughput proof; live account path honesty |
| **Confusing** | “ATM active” while ready_count=0 and paper opens=0 |
| **Not actionable** | Proposal cards when enrichment forever IN_PROGRESS |
| **Automate** | Enrichment SLA + auto-expire with reason codes to UI |
| **Remove** | Dead proposal statuses clutter |
| **Redesign** | Funnel dashboard: generated → enriched → ready → approved → filled |
| **Biz value** | High | **Sev** | **P0 paper loop** |

### Watch (all 5 tabs)
| | |
|--|--|
| **Working** | Card v4, finds track record, sectors RS, pullback MACD, directives scale |
| **Missing** | Consequential quality gate; auto-cull of negative-α sources |
| **Confusing** | Huge warehouse (12k) vs 61 active — what is “the watchlist”? |
| **Not actionable** | High score `ai_discovered` rows that cannot enter MAIN without star |
| **Automate** | α-based demote/archive; auto-promote only MAIN-eligible sources |
| **Remove** | Removed×7107 historical noise from default queries |
| **Redesign** | Three explicit lanes: Warehouse / MAIN / Directives — never mix |
| **Biz value** | High | **Sev** | P1 |

### Defense
| | |
|--|--|
| **Working** | Posture, industries, core registry, recommendations structure, SHADOW honesty |
| **Missing** | Promote decisions filled; fresh daily recs (last gen **Jul 31**); proven outcomes |
| **Confusing** | Structural sophistication vs zero capital effect |
| **Not actionable** | SHADOW cards that cannot stage without operator + 2FA path |
| **Automate** | Nightly refresh job health alert; paper-twin only promote ladder |
| **Remove** | Locked put structures if options_level empty forever |
| **Redesign** | “Proven n=” scoreboard above structural widgets |
| **Biz value** | High (risk book) | **Sev** | P1 SHADOW + stale |

### Research Intel
| | |
|--|--|
| **Working** | Large desk payload, QA tiers A/B, stage UX, 839 actionable controls, snapshots |
| **Missing** | Holdings-linked items (**0**), refresh SLA (36 need refresh / 50 shown), auto stage high-conf |
| **Confusing** | Aggregator vs Hermes Research vs Intelligence Topics |
| **Not actionable** | Aging/stale majority (182 aging + 42 stale in universe view) |
| **Automate** | Overnight drain + forced refresh for holdings universe |
| **Remove** | Queued stub cards that never get topics |
| **Redesign** | Holdings-first default lane |
| **Biz value** | High | **Sev** | P1 freshness |

### Agents
| | |
|--|--|
| **Working** | Volume metrics surface; scoreboard concept |
| **Missing** | True runtime status (smoke paths 404/503); authority honesty |
| **Confusing** | “Agents” brand vs HOLD-only Maria + SHADOW catalog |
| **Not actionable** | No drill from agent failure → fix job |
| **Automate** | Fail rate alerts (Maria 3k failed jobs) |
| **Remove** | DESIGNED agents with zero product path from default roster |
| **Redesign** | Split “Production personas” vs “MVL shadow fleet” |
| **Biz value** | Med | **Sev** | P1 trust | **Console** | 503 on resource |

### Hermes
| | |
|--|--|
| **Working** | Maturity dashboard API rich (gates); discovery inbox large |
| **Missing** | Tab content density in Playwright body (~4k chars) — many tabs thin or aborted feeds |
| **Confusing** | 12 tabs; learning scorecard all nulls on last day file |
| **Not actionable** | Gate fails without remediation deep-link |
| **Automate** | Gate fail → ticket to owning process |
| **Remove** | Proxy/Dual Opinion if unused |
| **Redesign** | Default to Maturity + Discovery + Closed Loop only |
| **Biz value** | High | **Sev** | P2 |

### Intelligence / Rec-Intel / Rotation / Redeploy / Health / Consumption / System
| Hub | Working | Gap | Sev |
|-----|---------|-----|-----|
| Intelligence | CC + Learning tab lineage | News still reading-room; topics fabrication risk | P2 |
| Rec-Intel | Source→execution truth **excellent** | Watchlist 5015 / **0 executed** screams | P1 |
| Rotation | Dense content | Overlaps Defense; action path unclear | P2 |
| Redeploy | Action-rich | Ensure not competing with Defense pairs | P2 |
| Health | Readable | Not wired to auto-remediate STALE strip | P1 |
| Consumption | Shows real lane truth | Proves DeepSeek not primary | P1 (honest) |
| System/LLM | Loads | Process registry still OAuth-centric | P2 |
| Retirement | Thin (4 btns) | Underbuilt vs Alex scripts | P2 |
| Active Trader | Loads | Low action density (5 btns) | P2 |
| Reports | Loads | hardNav; some hermes profile aborts | P3 |
| Strategy/Journal/Risk | Load | Journal attribution incomplete for learning | P2 |

## 3.4 Page audit summary table

| Hub | Load | Action density | Primary issue | Sev |
|-----|------|----------------|---------------|-----|
| Home | OK | High | Stale trading truth | P0 |
| Portfolio | OK | High | OK | — |
| Re-Entry | OK | Very high | API abort storms | P1 |
| Risk | OK | Med | Abort storms / thin | P2 |
| Trading* | OK | Med | Paper funnel empty | P0 |
| Active Trader | OK | Low | Immature | P2 |
| Strategy | OK | Med | Overlap | P3 |
| Journal | OK | High | Source keys missing | P2 |
| Watch* | OK | High | Warehouse≠MAIN; α | P1 |
| Defense | OK | High | SHADOW + stale | P1 |
| Agents | OK | Low | False autonomy | P1 |
| Research Intel | OK | Very high | Freshness / holdings link | P1 |
| Intelligence | OK | Med | Action gaps | P2 |
| Hermes | OK | Low-Med | Thin tabs / null learning | P2 |
| Reports | OK | Med | Path noise | P3 |
| Rotation | OK | Med | Overlap Defense | P2 |
| Rec-Intel | OK | Low-Med | 0 execution from discovery | P1 |
| Retirement | OK | Low | Thin | P2 |
| Health | OK | Med | No auto-fix | P1 |
| Consumption | OK | High | Honest DeepSeek gap | — |
| System | OK | Med | Registry lag | P2 |
| Redeploy | OK | High | Coordination | P2 |

\*Includes multi-tab coverage.

Screenshots: `docs/audits/platform-autonomy-2026-08-02/screenshots/*.png`

---

# 4. DeepSeek LLM implementation review

## 4.1 What is real

| Capability | Evidence |
|------------|----------|
| API key present | `deepseek_tradeai` in env; `available(deepseek-flash/v4)=true` |
| Live generate | Ungated Flash: **`PONG` in 949ms** |
| Lane probes | `/api/v2/llm-health` lists flash + v4 available |
| CIO path | Guardrails/watchlist synthesis prefers v4 in newer trees |
| Cost thesis | Far cheaper than Anthropic/OpenAI when actually used |

## 4.2 What is *not* primary production

| Signal | Value |
|--------|-------|
| Month calls Grok | **1,902** (262 failures) |
| Month calls ChatGPT | **691** (22 failures) |
| Month calls DeepSeek-v4 | **4** |
| Month calls DeepSeek-Flash | **0 recorded in by_lane** |
| Process modes | **6 automated / 22 manual** |
| Automated allowed_lanes | **All still `[grok, chatgpt]` only** |
| Live `generate()` default (rebuild) | **`lane="grok"`** |
| Gated probe | `ManualRequired` for unregistered process_id |
| `cached_generate` | Defined, **not used** at high-volume sites |
| Process registry JSON | Still OAuth-centric (`default_mode: manual`) |

## 4.3 Reliability / quality / hallucination

| Dimension | Assessment |
|-----------|------------|
| Reliability | Flash path works when called; production volume not on Flash; Grok weekly fail rate ~**53%** (201/382) is the real reliability story |
| Accuracy | Dual-lane disagree already discounts confidence (e.g. CLOD ×0.8); no systematic DeepSeek-vs-ground-truth harness |
| Hallucination risk | **High** on free-text research/topics; mitigated partially by QA lint + universe_guard; RI Topics still LLM narrative risk |
| Cost efficiency | Excellent **if** Flash carries volume; today OAuth free lanes still dominate ops |
| Rate limit / failover | Consumption gate + lane fallbacks exist; split-brain defaults undermine them |
| Context management | Huge prompts (v4 1M+ chars / 4 calls); no evidence of aggressive caching |
| Agent performance | Maria volume enormous but **0 directional BUY** — model choice secondary to prompt policy |
| Monitoring | Consumption hub good; DeepSeek not in process allowed_lanes → blind spot |

## 4.4 Architectural risks

1. **Narrative vs telemetry split-brain** (“DeepSeek primary” vs Grok traffic).  
2. **Silent billing** if `local_llm` remaps to DeepSeek when key present (guardrails path).  
3. **Manual process registry** blocks autonomous paid use.  
4. **Tree drift** — rebuild default `grok` vs guardrails default `deepseek-flash`.  
5. **No quality eval harness** for hallucination / numeric fabrication.

## 4.5 DeepSeek maturity score: **5 / 10**

Integration is real at the adapter layer; **not operationalized as primary**. Path to 8+: registry lanes + automated Maria/CIO/Hermes + cache + eval suite + kill Grok-default inconsistency.

### Recommended improvements
1. Update `llm_process_config` allowed_lanes + modes for Maria priority, CIO synthesis, cloud_review.  
2. Unify default lane across trees; pin release.  
3. Wire `cached_generate` on watchlist jobs.  
4. Add DeepSeek to secret_registry + fleet alerts.  
5. Nightly accuracy sample: holdings prices must match prompt facts.  
6. Separate “cost lane” metrics so Flash silence is a paging condition.

---

# 5. Agent architecture maturity assessment

## 5.1 Dual-track reality

| Track | State |
|-------|-------|
| **MVL catalog** (`agent_maturity_catalog.json`) | 11 DESIGNED · 5 SHADOW · **0 PRODUCTION** · all authorities DENIED · `production_activation_authorized: false` |
| **Production personas** | Cron/pipeline code under Maria/Steph/Risk/Tax/Hermes/Aegis/Alex — **real volume**, fixed graphs |

## 5.2 Scorecard (1–5)

| Agent | Mat | Aut | Rel | BV | Class | Notes |
|-------|:---:|:---:|:---:|:--:|-------|-------|
| hermes | 4 | 3 | 3 | 5 | partially_autonomous | Research fleet; advisory |
| maria | 4 | 3 | 3 | 4 | partially_autonomous | 17k results; **0 BUY** |
| aegis | 3 | 3 | 3 | 4 | partially_autonomous | Overnight briefs |
| darwin | 3 | 2 | 3 | 3 | partially_autonomous | Outcome scoring MVL |
| sentinel | 3 | 2 | 4 | 3 | partially_autonomous | Integrity critic; no ticket write |
| alex | 3 | 2 | 3 | 4 | prompt_wrapper | Retirement/gov; name≠CIO |
| steph | 3 | 2 | 3 | 4 | prompt_wrapper | Allocation narrative |
| risk_agent | 3 | 2 | 3 | 4 | prompt_wrapper | Risk narrative |
| iris | 3 | 2 | 3 | 3 | prompt_wrapper | Taxonomy |
| tax_agent | 2 | 2 | 2 | 3 | prompt_wrapper | Thin volume |
| argus | 2 | 2 | 3 | 2 | prompt_wrapper* | Deterministic scan |
| reflection | 2 | 2 | 3 | 2 | prompt_wrapper | Lessons not auto-promoted |
| atlas | 1 | 1 | 2 | 1 | prompt_wrapper | Not productized |
| concierge | 1 | 1 | 2 | 1 | prompt_wrapper | Disabled design |
| pulse | 1 | 1 | 1 | 1 | prompt_wrapper | Stub |
| vega | 1 | 1 | 1 | 1 | prompt_wrapper | Stub |

\*Argus is deterministic, still non-agentic.

| Class | Count |
|-------|------:|
| prompt_wrapper | **10** |
| partially_autonomous | **6** |
| truly_autonomous | **0** |

**Means ≈ Mat 2.6 · Aut 2.0 · Rel 2.6 · BV 2.9**

## 5.3 Autonomy feature truth

| Capability | Present? |
|------------|----------|
| Goal-driven behavior | Weak (fixed job types) |
| Dynamic planning | **No** |
| Task decomposition | Scripted phases only |
| Long-running execution | Cron windows, not agent loops |
| Memory | Partial RAG / research DB |
| Self-correction | Limited (retries, dual-lane caution) |
| Reflection loops | Shadow only |
| Retry | Yes (ops) |
| Learning | Partial; does not rewrite money policy |
| Cross-agent collab | Scripted committee |

## 5.4 Production volume (DB)

| Agent | Completed jobs | Failed | Signal |
|-------|---------------:|-------:|--------|
| maria | 24,458 | 3,040 | Dominant; HOLD factory |
| steph | 7,326 | 1,210 | More directional |
| risk_agent | 7,318 | 1,223 | |
| iris | 2,434 | 2,320 | High fail ratio |
| full_chain | 1,787 | 1 | |

**Maria recommendations:** buy_count **0**, sell_count **0**, hold_count **17,356** — autonomy without decisions is commentary at scale.

---

# 6. Research & Watchlist assessment

## 6.1 Research engine — **Semi-autonomous**

**Strengths**
- Continuous discovery + Hermes coordinator auto-promote of research rows  
- Budget tiers, scope governor cap 800, QA lint, universe_guard  
- Outcome bus + self-tune on **research** weights  
- RI desk institutional features (stage, star/hide, snapshots)

**Weaknesses**
- Discovery→registry promotion operator-gated (all domains)  
- Maturity gates: research **1/3**, autonomy **2/3**  
- Desk freshness: **36 need refresh** of 50 returned; holdings_linked **0**  
- Learning scorecard day file: null hit rates / 0 promotions  
- Stage→trade requires human + exit note (correct safety, limits autonomy)

**Not fully autonomous because:** cannot expand coverage or capital without humans; learning does not open new sector programs.

## 6.2 Watchlist — **Semi-autonomous**

### Lifecycle (actual)

```
Screeners/Hermes/YouTube → ai_discovered warehouse (11k+)
        → Hermes score + scope tiers
        → MAIN admission (excludes raw ai_discovered)
        → Proposal bridge (require MAIN GO)
        → Paper proposals → (starved ATM)
        → Sunday α reconcile → quality label (visibility only)
```

### Warehouse truth (DB)

| Metric | Value |
|--------|------:|
| Total watchlist_items | 12,502 |
| ai_discovered | 11,473 |
| status removed | 7,107 |
| status researched | 5,334 |
| status active | **61** |
| Directives active | 437 |
| ai_discovered median α_21d | **−2.43%** (n=1,513) |
| operator_add median α_21d | −4.55% (n=15) |

### Rec-intel conversion

| Source | Tickers | Executed |
|--------|--------:|---------:|
| watchlist | 5,015 | **0** |
| scan | 763 | **0** |
| hermes_research | 638 | **0** |
| proposal | 640 | 64 |
| execution | 189 | 6,045 |

**Brutal read:** Intelligence production is industrial; **capital conversion from discovery is ~zero**.

### Gaps to full watchlist autonomy
1. Quality gate must **block** inserts / auto-archive low-α sources.  
2. Outcome feedback must adjust MAIN weights (today locked).  
3. Journal source keys for end-to-end attribution.  
4. Collapse warehouse vs MAIN in product language.  
5. Auto-promote only when α + liquidity + setup rails pass.

### Target architecture (watch)
- **L0 Warehouse** auto, capped, low cost  
- **L1 MAIN** auto-admit only allowlisted sources + α gate  
- **L2 Directed research** budget-proportional to edge  
- **L3 Propose** auto when MAIN GO + enrichment complete  
- **L4 Paper ATM** auto  
- **L5 Live** human 2FA  

---

# 7. Defensive investing intelligence

| Capability | Status |
|------------|--------|
| Identify sector rotation | **Yes** (sector_momentum, industries, RS) — snapshot **2026-07-31** |
| Detect risk-off | **Partial** (regime chips, inverse stoplights) |
| Adapt recommendations | **Computes** nightly; **SHADOW** only |
| Generate ideas auto | **Yes** (get_into / protect / short / income groups) |
| Incorporate research/watch | **Partial** (Hermes constituents; weak closed loop) |
| Dynamic sector rankings | **Yes** |
| Act on book | **No autonomous capital** — 2FA + SHADOW |

**Structural maturity ~9 / Proven ~4–5** (aligns with Defense docs). Promote criteria locked with empty decisions is an integrity win and an autonomy freeze.

---

# 8. End-to-end autonomy chain

| # | Hop | Verdict | Evidence |
|---|-----|---------|----------|
| 1 | Discover trends | **Auto** | Finviz/Hermes discovery crons |
| 2 | Research trends | **Auto** | Research scheduler + agent jobs + Hermes |
| 3 | Generate ideas | **Semi** | Proposals thin yield |
| 4 | Validate ideas | **Auto/Semi** | Gates strong; enrichment choke |
| 5 | Prioritize | **Semi** | MAIN weights **locked** |
| 6 | Update watchlists | **Semi** | Lifecycle review_mode |
| 7 | Sector rotation | **Semi→Human** | Defense SHADOW |
| 8 | Surface recs | **Semi** | UI works; act is human |
| 9 | Monitor outcomes | **Auto** | Grader/bus/alerts |
| 10 | Improve decisions | **Weak Semi** | Research graft only; not ATM/MAIN |
| 11 | Paper execute | **Broken in practice** | ready=0, EXPIRED mass, ATM idle |
| 12 | Live execute | **Human-required** | 2FA + disabled accounts — correct |

### Human intervention inventory (non-exhaustive)
- Live per-order 2FA · ATM mode changes · holdings import · cost basis export  
- Defense promote criteria decisions · core registry confirms · SHADOW promote  
- Discovery domain promotion · RI stage/promote · tier-3 directive merges  
- LLM process mode flips (manual registry) · MAIN weight unlocks  
- Paper account enablement · broker promote oversight · lesson ratification  
- Deploy/release ownership · cron `cd` hygiene · kill switches  

---

# 9. Autonomous platform roadmap

## 9.1 Immediate (0–30 days)

1. **Restore single spine:** systemd release = live server = cron cwd; kill ad-hoc drift. **(P0)**  
2. **Fix STALE metric strip:** ensure trading/realized/setup pipelines run or fail loudly with Run Now. **(P0)**  
3. **Paper funnel war room:** ready_count SLA, enrichment completion %, ATM weekly fill report. **(P0)**  
4. **DeepSeek registry cutover:** Maria + CIO + cloud_review allowed_lanes include deepseek-flash/v4; automate safe processes. **(P1)**  
5. **Quality gate enforcement:** stop pure visibility fold — block/archive low-α sources at intake. **(P1)**  
6. **Agents page honesty:** label SHADOW/DESIGNED; show Maria HOLD rate; hide empty MVL shells. **(P1)**  
7. **API path cleanup:** alias or remove 404 smoke paths; fix agent-runtime 503. **(P2)**

## 9.2 Near-term (30–90 days)

1. Outcome bus → paper ATM ranking (paper-only weight graft).  
2. Defense exit SHADOW for **paper twins only** after promote criteria filled.  
3. Journal source keys → full discovery→P&L attribution.  
4. LLM eval harness (numeric non-invention + dual-lane agree rate).  
5. `cached_generate` on top processes; cost alerts for Flash silence.  
6. Re-Entry batch API to kill abort storms.  
7. Collapse hub sprawl (Intel section consolidation).  
8. Hermes learning scorecard non-null with remediation links.

## 9.3 Long-term (90+ days) → 9+/10 autonomy

1. Goal-conditioned research planner (weekly themes from white-space + α).  
2. Self-tuning MAIN weights under paper risk envelopes + automatic rollback.  
3. Multi-agent debate only when disagreement value > cost (not always-on HOLD spam).  
4. Continuous sector sleeve manager (paper) with measured tracking error.  
5. Keep **live capital human-gated** (2FA) even at 9/10 — redefine 9 as **paper closed-loop excellence**, not unattended live trading.  
6. Unified agent memory + policy store with audited self-modification.

### Architecture changes required for 9+/10

```
TODAY:  Discover ─► Research ─► Advise ─► (human) ─► maybe paper
TARGET: Discover ─► Research ─► Rank(α) ─► Propose ─► Enrich ─► Paper ATM
                 ▲                         │
                 └──── Outcome bus / graft ─┘
        Live Schwab: human 2FA only
        Deploy: single SHA spine
        LLM: DeepSeek primary + measured OAuth fallback
        Agents: fewer, outcome-scored, no HOLD theater
```

Without (1) single deploy spine, (2) working paper loop, (3) consequential quality gates, (4) learning that changes ranking/ATM — **9/10 is unreachable**.

---

# 10. Final verdict

## Is the platform truly autonomous today?

**No.**

It is a **semi-autonomous research and advisory automation system** with **strong deterministic risk fences**, **industrial discovery**, and **broken/starved paper execution**. Live trading autonomy is correctly **denied**.

## What specifically prevents autonomy?

1. **Deploy multi-tree drift** — no single production brain.  
2. **Paper capital loop starvation** — ready_count=0, mass EXPIRED, ATM idle despite mode=active.  
3. **Discovery without edge** — median α −2.43%; gates don’t block noise.  
4. **Learning cannot rewrite money policy** — MAIN weights locked; graft_forbidden.  
5. **Agents are prompt factories** — 0 truly autonomous; Maria is HOLD-only at scale.  
6. **DeepSeek not operationally primary** — Grok still carries traffic; registry manual.  
7. **Defense SHADOW + empty promote decisions** — rotation intelligence without action.  
8. **Human gates by design** on live capital, promotions, RI stage, discovery registry (some correct, some accidental).  
9. **Attribution break** — cannot fully learn which research/source made money.  
10. **Stale operator truth** on the primary metric strip undermines closed-loop ops.

## Current autonomy maturity score

# **4.5 / 10**

| Weighted dimension | w | score | contrib |
|--------------------|--:|------:|--------:|
| Discover trends | 0.15 | 7 | 1.05 |
| Research → insight | 0.15 | 6.5 | 0.98 |
| Generate & validate ideas | 0.15 | 4 | 0.60 |
| Prioritize & watchlists | 0.10 | 4 | 0.40 |
| Sector rotation / defense | 0.10 | 3.5 | 0.35 |
| Surface recommendations | 0.10 | 6 | 0.60 |
| Monitor outcomes | 0.10 | 7 | 0.70 |
| Improve future decisions | 0.10 | 2.5 | 0.25 |
| Live execution autonomy | 0.05 | 1 | 0.05 |
| **Total** | | | **≈4.98 → round 4.5–5.0** after paper-break penalty **−0.5** → **4.5** |

## Architecture changes required for 9+/10

1. One deploy spine (systemd SHA = cron = UI).  
2. Paper closed loop green weekly (propose→enrich→ATM→fill→grade).  
3. Consequential quality gates + MAIN weight learning under paper risk.  
4. DeepSeek primary operationalized (registry, cache, eval).  
5. Defense paper promote path with measured n.  
6. Fewer agents with outcome authority; kill HOLD spam.  
7. Full source attribution in journal.  
8. Explicit product contract: **9/10 = autonomous paper allocator + human live**.

---

# Appendix A — Evidence index

| Artifact | Path |
|----------|------|
| Env freeze | `docs/audits/platform-autonomy-2026-08-02/evidence/env_freeze.txt` |
| API smoke | `…/api_smoke.txt`, `api_smoke2.txt` |
| Live metrics | `…/live_metrics.json` |
| Page audit | `…/page_audit.json`, `page_audit_summary.json` |
| Screenshots | `…/screenshots/*.png` |
| DeepSeek probe | `…/deepseek_probe.json` |
| DB stats | `…/db_stats.json` |
| Agents+DeepSeek deep dive | `…/agents_deepseek_findings.md` |
| Research/Watch/Defense | `…/research_watch_defense_findings.md` |
| Autonomy chain | `…/autonomy_chain_findings.md` |

# Appendix B — Playwright summary

- **32/32** routes OK, no React error boundaries  
- Console errors: **agents** (503)  
- Network aborts concentrated on Re-Entry, Risk, Watch finds, Hermes, Research Intel agent-runtime  
- Highest action density: Re-Entry, Research Intel, Redeploy, Home, Portfolio  
- Lowest: Active Trader, Retirement, Rec-Intel, Agents, ATM tab  

---

*Audit prepared for operator decision-making. Separate “broker safety maturity ~4.95/5” from “investment autonomy 4.5/10” — they measure different things; conflating them is how teams overclaim autonomy.*

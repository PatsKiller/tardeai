# Platform Autonomy Audit — Agents + DeepSeek LLM
**Date:** 2026-08-02  
**Tree:** `/home/johnclaw/tradeai-wt-cursor-guardrails`  
**Mode:** READ-ONLY  
**Primary sources:** `config/agent_maturity_catalog.json`, `config/agents.json`, `scripts/agent_runtime/**`, `scripts/process_watchlist_agent_jobs.py`, `scripts/llm_lane.py`, `scripts/local_llm.py`, `scripts/llm_router.py`, `config/llm_process_registry.json`, `config/premium_review_providers.yaml`, `docs/DEEPSEEK_INTEGRATION_PLAN_2026_08_01.md`, live evidence under this audit folder.

---

## 0. Executive verdict (brutal honesty)

Trade AI v12 has **two parallel agent systems** that share names but not maturity:

| Track | What it is | Reality |
|-------|------------|---------|
| **A. Catalog / MVL SHADOW fleet** | `config/agent_maturity_catalog.json` + `scripts/agent_runtime/` | Governed, fail-closed, **no production activation** (`production_activation_authorized: false`). Most “agents” are **definitions + deterministic pipelines + optional critic LLM**. |
| **B. Production operational personas** | Watchlist jobs, Hermes research fleet, Aegis overnight, Alex retirement, agent_router | **Real cron/pipeline code** producing operator-facing narratives, jobs, alerts. Almost all are **prompt wrappers / fixed pipelines**, not goal-driven agents. |

**No agent is truly autonomous** in the sense of open-ended goal pursuit, dynamic multi-step planning with tool choice under a budget, and closed-loop self-correction that changes production behavior without a human. Hermes is the closest operational system (scheduled research + outcome feedback), still heavily rule/threshold gated.

DeepSeek integration is **structurally half-done but directionally real**: `llm_lane` default is `deepseek-flash`, CIO path prefers `deepseek-v4`, and both lanes are **available live**. But consumption logging shows **almost no Flash volume**, many CLI defaults still hardcode `grok`, process registry is still OAuth-centric, secret registry has **no DeepSeek entry**, and `cached_generate` is **defined but not wired into high-volume callers**.

---

## 1. Scoring rubric

Scores are **1–5** for operational reality (not aspirational catalog copy):

| Score | Maturity | Autonomy | Reliability | Business value |
|------:|----------|----------|-------------|----------------|
| 1 | Design / stub | Manual only | Untested / silent fail | Negligible |
| 2 | Partial scripts | Fixed prompt, single shot | Fragile | Nice-to-have |
| 3 | Cron/pipeline live | Multi-step scripted | Some gates | Useful advisory |
| 4 | Durable ops + metrics | Adaptive within rails | Proven fail-closed | Core operator path |
| 5 | Production authority + measured outcomes | Goal-driven planning | Hardened + monitored | P&L-critical closed loop |

**Classification:**
- `prompt_wrapper` — fixed prompt → LLM → parse/store; no planning loop
- `partially_autonomous` — scheduled multi-step pipelines, queues, retries, feedback **within fixed graphs**
- `truly_autonomous` — open goals + dynamic planning + self-modification of behavior (none achieved)

**Dual-track scoring note:** Catalog `deployment_state` is cited; **scores reflect the stronger of (catalog pipeline | production persona)** where names collide, with explicit dual-track notes.

---

## 2. Agent scorecard (16 catalog agents)

| Agent | Catalog state | Real implementation | Mat | Aut | Rel | BV | Class | Goal | Dyn plan | Memory | Self-corr | Reflect | Retry | Learn | Cross-agent |
|-------|---------------|---------------------|:---:|:---:|:---:|:--:|-------|:----:|:--------:|:------:|:---------:|:-------:|:-----:|:-----:|:-----------:|
| **aegis** | DESIGNED (“not implemented”) | **Prod:** `aegis_overnight.py`, `aegis_synthesis.py`, `aegis_surveillance.py`, `aegis_nightly_ingestion.py`, morning brief delivery. **Shadow:** `synthesis_critics_pipeline.py` incident critic (deterministic + optional LLM). | 3 | 3 | 3 | 4 | partially_autonomous | partial (overnight phases) | no | ledger/DB | limited | synthesis | phase re-run | weak | feeds Steph/Alex |
| **alex** | DESIGNED (“not implemented”) | **Prod:** `alex_retirement_advisor.py`, `alex_gov_research.py`, CIO synthesis in `process_watchlist_agent_jobs.py` (Alex-as-CIO narrative is synthesis, not this catalog agent). **agents.json** `alex` = retirement/disability (not CIO). **Shadow:** synthesis critic stub. | 3 | 2 | 3 | 4 | prompt_wrapper / partial | no | no | gov cache | no | advisor scans | manual | weak | yes (escalation) |
| **argus** | SHADOW | `argus_pipeline.py` + definitions — deterministic population scan, 0 model calls. Not a durable production population auditor outside MVL. | 2 | 2 | 3 | 2 | prompt_wrapper* | no | no | no | no | no | no | no | no |
| **atlas** | DESIGNED (deferred) | Shadow def + `synthesis_critics_pipeline` stuck-run scan. **No real durable orchestrator.** Production orchestration is `agent_router` / pipeline controller, not Atlas. | 1 | 1 | 2 | 1 | prompt_wrapper | no | no | no | no | no | no | no | design only |
| **concierge** | DESIGNED (disabled) | Shadow OPENCLAW operator surface (status/cancel/explain tools denied shell). **Not production operator gateway.** | 1 | 1 | 2 | 1 | prompt_wrapper | no | no | no | no | no | no | no | no |
| **darwin** | SHADOW | `darwin_pipeline.py` deterministic artifact scoring in MVL. **Separate** `agent_outcome_scorer.py` scores watchlist agents vs closed trades (production learning loop). Catalog Darwin ≠ production scorer fully unified. | 3 | 2 | 3 | 3 | partially_autonomous | no | no | outcomes DB | no | nightly score | no | **yes** (calib) | scores others |
| **hermes** | DESIGNED (catalog hypothesis agent “disabled”) | **Massive production research fleet** (100+ `hermes_*.py`, maturity YAML, outcome bus, budget guards, discovery). Catalog Hermes ≠ Hermes research system. | 4 | 3 | 3 | 5 | partially_autonomous | partial (domains) | limited | research DB | thresholds | outcome feedback | yes | **yes** (maturity) | feeds watch/CIO |
| **iris** | SHADOW | **Prod:** `iris_taxonomy_agent.py` (weekly taxonomy/hygiene). **Shadow:** `iris_critic_pipeline.py` lesson reviews. Cannot ratify lessons. | 3 | 2 | 3 | 3 | prompt_wrapper | no | no | KB candidates | no | review only | no | weak | feeds specialists |
| **maria** | DESIGNED (“not durable”) | **Prod workhorse:** `process_watchlist_agent_jobs.py` maria prompts + RAG + peer notes + OAuth priority; `maria_oauth_priority`. Shadow research critic also defined. | 4 | 3 | 3 | 5 | partially_autonomous | no | no | RAG + peer + calib | synthesis retry | no agent-level | **yes** (outcome scorer) | committee |
| **pulse** | DESIGNED (“not implemented”) | Shadow microstructure critic shell; production options/microstructure elsewhere, **not this agent**. | 1 | 1 | 1 | 1 | prompt_wrapper | no | no | no | no | no | no | no | no |
| **reflection** | SHADOW | `reflection_pipeline.py` — candidate lessons only; LLM optional behind `AGENT_RUNTIME_CRITIC_LANES`. Scheduler “not authorized” per catalog. | 2 | 2 | 3 | 2 | prompt_wrapper | no | no | candidate lessons | no | **yes** (nightly) | no | no auto-promote | iris reviews |
| **risk_agent** | DESIGNED | **Prod:** watchlist risk/stop narratives; stops/risk JSON context. Deterministic risk gates elsewhere (not this agent). Shadow risk critic: concentration/unprotected heuristics. | 3 | 2 | 3 | 4 | prompt_wrapper | no | no | risk JSON | no | no | job requeue | weak | committee |
| **sentinel** | SHADOW | `sentinel_pipeline.py` + `sentinel.py` — post-validation integrity critic, **cannot change tickets**. Lab provider exists. Not production Watch gate authority. | 3 | 2 | 4 | 3 | partially_autonomous | no | no | KB retrieve | no | review | budget stops | no | iris/darwin |
| **steph** | DESIGNED | **Prod:** allocation/account-fit narratives in watchlist jobs; rebalance planners exist separately. Shadow allocation critic: income-sleeve heuristics. | 3 | 2 | 3 | 4 | prompt_wrapper | no | no | holdings | no | no | job requeue | weak | committee |
| **tax_agent** | DESIGNED | **Prod:** tax/location narrative in watchlist jobs; wash-sale truth still partial (catalog: lot truth pending). | 2 | 2 | 2 | 3 | prompt_wrapper | no | no | situation JSON | no | no | job requeue | weak | committee |
| **vega** | DESIGNED (“not implemented”) | Shadow technical critic definition + trigger wiring; **no durable technical agent product**. Indicators/screens are deterministic engines, not Vega. | 1 | 1 | 1 | 1 | prompt_wrapper | no | no | no | no | no | no | no | no |

\*Argus is deterministic scan, not an LLM wrapper — still not goal-driven autonomy.

### Score means (catalog 16)

| Metric | Mean (approx) |
|--------|---------------|
| Maturity | **2.6** |
| Autonomy | **2.0** |
| Reliability | **2.6** |
| Business value | **2.9** |

**Human-facing production value concentrates in: Hermes, Maria, Aegis, Alex (retirement), Steph/Risk narratives, CIO synthesis.** Catalog “agents” as a governed MVL fleet are mostly **shadow theater with good safety rails**.

---

## 3. Classification summary counts

| Class | Count | Agents |
|-------|------:|--------|
| **prompt_wrapper** | **10** | alex*, argus*, atlas, concierge, iris, pulse, reflection, risk_agent, steph, tax_agent, vega (argus deterministic variant still non-agentic) |
| **partially_autonomous** | **6** | aegis, darwin, hermes, maria, sentinel, (+ hermes-scale research system) |
| **truly_autonomous** | **0** | — |

\*Alex production is multi-script advisory but still fixed-scan, not open-goal.

**Catalog deployment_state counts (authoritative for MVL):**
- DESIGNED: **11** (aegis, alex, atlas, concierge, hermes, maria, pulse, risk_agent, steph, tax_agent, vega)
- SHADOW: **5** (argus, darwin, iris, reflection, sentinel)
- PRODUCTION: **0**
- `production_activation_authorized`: **false**
- Global authority: **all DENIED** (orders, broker, config promote, secrets, 2FA, service control)

---

## 4. Per-agent implementation evidence (file map)

### 4.1 Catalog / runtime
| Path | Role |
|------|------|
| `/home/johnclaw/tradeai-wt-cursor-guardrails/config/agent_maturity_catalog.json` | 16-agent contracts, budgets, denied tools |
| `/home/johnclaw/tradeai-wt-cursor-guardrails/scripts/agent_runtime/agents/definitions.py` | Shadow fleet specs (all enabled=True in code, still SHADOW) |
| `/home/johnclaw/tradeai-wt-cursor-guardrails/scripts/agent_runtime/agents/run_once.py` | **Prepare-only** runner; requires `AGENT_RUNTIME_OPERATOR_AUTH=1` + queue module |
| `/home/johnclaw/tradeai-wt-cursor-guardrails/scripts/agent_runtime/critic_llm.py` | Critic LLM; **default OFF** (`AGENT_RUNTIME_CRITIC_LANES`); DeepSeek flash first when on |
| Pipelines: `sentinel_pipeline.py`, `darwin_pipeline.py`, `iris_critic_pipeline.py`, `reflection_pipeline.py`, `argus_pipeline.py`, `domain_critics_pipeline.py`, `synthesis_critics_pipeline.py`, `hermes_pipeline.py` | Bounded shadow processing |

### 4.2 Production personas (name collisions)
| Agent name | Primary production code |
|------------|-------------------------|
| maria / steph / risk / tax | `scripts/process_watchlist_agent_jobs.py` (cron ~15m) |
| CIO synthesis (often called Alex/CIO in UI) | same file: `_synthesis_lanes` / `_synthesis_llm` |
| hermes (research) | `scripts/hermes_*.py`, `config/hermes_*.yaml` |
| aegis | `scripts/aegis_overnight.py` + siblings |
| alex (retirement) | `scripts/alex_retirement_advisor.py`, `alex_gov_research.py` |
| iris (taxonomy) | `scripts/iris_taxonomy_agent.py` |
| routing | `scripts/agent_router.py` + `config/agents.json` |
| learning | `scripts/agent_outcome_scorer.py`, `agent_calibration_engine.py`, `agent_collab.py` |

### 4.3 agents.json named agents (router config)
Present under `config/agents.json`:
- `orchestrator`, `maria_research`, `steph_allocation`, `risk_agent`, `tax_agent`, `alex`, `iris`, `aegis_core`, `social_scalp`
- Keyword routing + freshness + high-impact multi-reviewer rules
- **Not** goal-driven agents — **intent classifier + handoff config**
- Stale model overrides still list `claude-sonnet-4-6` for alex/iris (DeepSeek migration incomplete at config layer)

---

## 5. Autonomy feature matrix (cross-cutting)

| Capability | Present? | Where / honesty |
|------------|----------|-----------------|
| Goal-driven objectives | **Weak** | Catalog has `objective` strings; runtime uses fixed `job_type`. No free-form goal interpreter. |
| Dynamic planning | **No** | Fixed phase graphs (Aegis overnight, Hermes dispatch, watchlist committee). |
| Memory | **Partial** | RAG, peer agent notes, John’s past decisions, Hermes research DB, lesson candidates. Not unified agent memory. |
| Self-correction | **Limited** | CIO dual-consensus caution rule; synthesis_retry job; LLM refusal skip. No agent rewrites its own policy. |
| Reflection | **Shadow only** | `reflection` pipeline → candidate lessons; human/Iris ratification required. |
| Retry | **Yes (ops)** | Watchlist synthesis retry enqueue; Hermes circuit breakers; LLM lane fallbacks. |
| Learning | **Partial** | Outcome scorer + calibration context injected into prompts; Hermes maturity score; **no auto threshold promote** without human. |
| Cross-agent | **Yes (scripted)** | Committee (maria/steph/risk/tax → synthesis); agent_router reviewers; Hermes → watch; Aegis → Steph. Not a multi-agent marketplace. |

---

## 6. Human intervention points (by agent)

| Agent | What still requires a human |
|-------|-----------------------------|
| **All catalog agents** | Any production mutation: orders, config promote, lesson ratify, hypothesis promote, service control — **globally DENIED**. |
| **maria/steph/risk/tax** | Interpreting narratives; acting on BUY/TRIM/SELL; high-impact paths need multi-reviewer (agents.json). |
| **CIO synthesis** | Trust bundle / degraded local fallback; dual-consensus disagreements; final trade execution. |
| **hermes** | Promotion of candidates, research budget exceptions, Auto-Promote policy (explicitly non-Flash in plan), outcome adjudication. |
| **aegis** | Acting on morning brief escalations; overnight findings are advisory. |
| **alex** | Roth/SSDI/Medicaid decisions; gov data is research not legal advice. |
| **iris** | Accept/reject taxonomy proposals. |
| **sentinel/darwin/reflection/argus** | All shadow outputs; operator review; no ticket edit authority. |
| **atlas/concierge/pulse/vega** | Essentially not productized — human does the work those names promise. |
| **agent_router writes** | `approval_required_for_writes: true`. |
| **LLM consumption** | Process registry **default_mode: manual** — many cloud calls need operator mode flip / manual_trigger. |
| **Premium review** | DeepSeek enabled in YAML but still operator-gated product surface. |

---

## 7. DeepSeek implementation assessment

### 7.1 Core implementation (`scripts/llm_lane.py`)

| Aspect | Status | Evidence |
|--------|--------|----------|
| Default lane | **deepseek-flash** | `generate(..., lane="deepseek-flash")` default |
| Models | Flash=`deepseek-v4-flash`, v4=`deepseek-v4-pro` | Lines 23–24 (plan text still says `deepseek-chat` / `deepseek-reasoner` — **docs drift**) |
| API key env | **`deepseek_tradeai`** (Bitwarden-style name as env var) | Line 21; plan also mentions `DEEPSEEK_API_KEY` / tmpfs — **naming inconsistency** |
| Failover Flash | no key / error → **local** | Lines 104–108, 133–137 |
| Failover v4 | no key / error → **grok** | Lines 141–144, 170–174 |
| OAuth fallback | grok / chatgpt proxies | :8645 / :8646 |
| Consumption logging | optional `process_id` | log_call on success |
| Cache wrapper | `cached_generate()` exists | **No production call sites found** wrapping high-volume paths |

### 7.2 `local_llm.py` chain
PRIMARY DeepSeek Flash → local Ollama gemma → (paid OpenAI/Anthropic only if `ALLOW_PAID_FALLBACK=true`). This means **many “local” callers silently become DeepSeek-billed** when the key is present — high leverage, also a cost/monitoring risk if operators assume “local = free”.

### 7.3 `llm_router.py`
Task routing tables prefer DeepSeek Flash/v4; legacy docstring still describes Grok-primary “May 2026 GPU testing”. `_call_anthropic` / `_call_openai` **remapped to deepseek-v4 / deepseek-flash**. Specialist watchlist agents go through this router when not on Maria OAuth path.

### 7.4 CIO / watchlist agents
- Maria OAuth path: `deepseek-flash → grok → chatgpt` (`process_watchlist_agent_jobs.py` ~294)
- Specialist `_llm`: `llm_router.get_llm_response` (DeepSeek-first tables)
- `_synthesis_llm`: deepseek-flash then local
- `_synthesis_lanes`: **deepseek-v4 primary**, dual grok+chatgpt fallback

### 7.5 Critic / SHADOW fleet
`critic_llm.generate_for_critic`: deepseek-flash → grok → chatgpt → local — **but only when `AGENT_RUNTIME_CRITIC_LANES` enabled** (default off → deterministic empty).

### 7.6 Config alignment gaps

| Config | Finding |
|--------|---------|
| `config/premium_review_providers.yaml` | DeepSeek **enabled: true**, model `deepseek-v4-pro`, credentials `deepseek_tradeai` |
| `config/llm_process_registry.json` | **Still OAuth-centric** (grok_only / either / ensemble). **No** `deepseek_flash_*` process IDs from the plan |
| `config/secret_registry.yaml` | **No DeepSeek entry** (plan step incomplete) |
| `config/inference_layers.yaml` | Still documents free OAuth + local (grep evidence) |
| `config/hermes_research_budget.yaml` | Plan asked for Flash caps; not verified as complete in this pass |
| Plan frontmatter todos | Still marked **`status: pending`** despite code partially shipped |

### 7.7 Remaining Grok/ChatGPT hardcodes (sample, not exhaustive)

| File | Issue |
|------|-------|
| `holding_protection_advisor.py` | `run()` default `deepseek-flash` but **CLI `--lane default=grok`** and choices exclude deepseek |
| `grok_stop_review.py`, `grok_execution_review.py`, `grok_daily_execution_digest.py` | CLI default `grok` |
| `journal_review_builder.py`, `schwab_journal_classifier.py` | CLI default `grok` |
| `paper_trade_advisory.py` | default lanes `grok,chatgpt` |
| `hermes_top20_external_intel.py` | default `chatgpt,grok` |
| `hermes_subject_enhance.py` | default `grok` |
| `hermes_external_researcher.py` | **DEFAULT_MODEL still `claude-sonnet-4-6`**; lanes claude/chatgpt/grok only — plan item to switch to DeepSeek **not done** |
| `api_v2.py` | Many inline grok second-opinion paths |
| `llm_process_registry.json` | Soft caps and policies for OAuth, not DeepSeek spend |

### 7.8 Caching
- Implemented: `scripts/lib/llm_cache.py` (SQLite curated messages)
- Wrappers: `llm_lane.cached_generate`, `local_llm.cached_generate`, `critic_llm.cached_critic_generate`
- **Call-site adoption: ~0** outside definitions (grep found only definitions, not production wraps of agent jobs / entry planner / catalysts)
- Model key drift: cache examples use `deepseek-chat`; runtime uses `deepseek-v4-flash` / `deepseek-v4-pro`

### 7.9 Rate limits & monitoring

| Control | Status |
|---------|--------|
| OAuth consumption gate (`lib/llm_consumption.py`) | Mature for grok/chatgpt; process modes + soft caps |
| DeepSeek daily budget | **Not first-class** in process registry; premium YAML has $0.20/day for ticket review only |
| Lane health | `llm_health_check.py` includes deepseek-flash/v4; live_metrics show both **available: true** |
| Consumption reality (live_metrics) | **deepseek-v4:** 4 calls today/week/month; **deepseek-flash: absent from by_lane** — Flash is “primary” in code but **not yet the observed workhorse** |
| Grok failure rate | Week: 201 failures / 382 calls — OAuth still dominant and noisy |
| Fail-closed manual mode | Audit probe hit `ManualRequired` for process_id `audit_probe` |

### 7.10 Live probe evidence
File: `docs/audits/platform-autonomy-2026-08-02/evidence/deepseek_probe.json`

```json
"deepseek_key_present": true,
"available": { "deepseek-flash": true, "deepseek-v4": true, "grok": true, "chatgpt": true, "local": true },
"deepseek-flash": { "ok": false, "error": "ManualRequired(... audit_probe ...)" },
"deepseek-v4": { "ok": false, "error": "ManualRequired(... audit_probe ...)" }
```

Interpretation:
- Key present; liveness OK.
- Generate path used a gated `process_id` → blocked by consumption **manual mode** (good safety, bad for naive probes).
- Direct `generate(..., process_id=None)` should bypass gate for DeepSeek (DeepSeek branch does not require `gate_and_generate` unless routed via consumption helpers).
- Note: probe also reported `available("deepseek") == false` while flash/v4 true — alias/health quirk worth fixing later.

### 7.11 DeepSeek maturity score: **5 / 10**

| Justification (+/−) | Points |
|---------------------|--------|
| Unified lane API with Flash default + v4 CIO path | +2 |
| local_llm + llm_router remapped; multi-script migration underway | +1.5 |
| Live key + availability true | +1 |
| Failover chains exist | +0.5 |
| Process registry / secret registry / plan todos incomplete | −1 |
| High-volume call sites still default grok; Flash not in consumption by_lane | −1.5 |
| Cache not adopted; model ID doc drift; hermes_external still Claude | −1 |
| No DeepSeek-specific rate/budget enforcement at fleet scale | −0.5 |

**5/10 = “plumbing exists; production gravity still OAuth; metered primary not proven under load.”**

---

## 8. Top risks

1. **Dual naming / dual systems** — Operators and audits confuse Catalog Hermes/Maria (shadow critics) with production Hermes/Maria (cron pipelines). Overstates autonomy maturity if catalog is taken at face value; understates production value if only catalog is read.
2. **Silent DeepSeek billing via `local_llm.generate`** — Callers expecting free local may hit paid Flash first; weak cost attribution if process_id omitted.
3. **Incomplete migration** — Code defaults say DeepSeek; CLI crons and process registry still OAuth. Split-brain routing → unpredictable quality and spend.
4. **Cache dead code** — Metered API without call-site caching risks duplicate spend on 15-min agent loops.
5. **SHADOW fleet looks “enabled” in definitions but is prepare-only** — `run_once` refuses without operator auth + queue module; critic lanes default off. False sense of multi-agent autonomy.
6. **Zero truly autonomous agents** — All business-critical actions still human or deterministic gates; LLM agents are narrative/advisory. Risk is **false confidence**, not rogue trading (authority is correctly denied).
7. **Grok OAuth high failure rate** still on critical path as fallback / default for many scripts.
8. **Hermes external researcher still Claude-primary** — highest-stakes research path not on DeepSeek plan target.
9. **Tax/lot truth incomplete** — tax_agent narratives may overclaim wash-sale certainty.
10. **Monitoring gap on Flash volume** — if Flash is primary, absence from consumption overview means either no process_id logging or traffic not actually using Flash.

---

## 9. Monitoring gaps

| Gap | Impact |
|-----|--------|
| No dedicated DeepSeek process IDs / soft caps in `llm_process_registry.json` | Cannot gate or budget Flash/v4 like OAuth |
| Flash missing from consumption `by_lane` | Blind to primary-lane spend |
| Plan todos still pending in doc frontmatter | Planning system not closed-loop with implementation |
| Secret registry missing DeepSeek | Rotation/ownership unclear |
| Critic fleet provenance when lanes off is “deterministic” empty — easy to misread as “agent ran smartly” | False maturity in UI boards |
| Outcome learning not wired to auto-adjust model routing | Calibration is prompt injection, not control loop |
| No end-to-end SLI: “% agent jobs that used deepseek-flash successfully” | Migration success unmeasured |
| Model ID inconsistency (`deepseek-chat` vs `deepseek-v4-flash`) | Cache misses + confusing dashboards |

---

## 10. Human intervention map (ops checklist)

1. **Trade execution / broker** — always human (or separate ATM with its own gates), never agent authority.
2. **Enable any SHADOW agent run** — `AGENT_RUNTIME_OPERATOR_AUTH=1`, queue backend, critic lanes env.
3. **Flip LLM process modes** — registry default manual → automated for each process_id.
4. **Approve premium / DeepSeek ticket review** — credentials + budget already small.
5. **Ratify Iris/Reflection lessons** — no auto-ratify.
6. **Hermes promote / threshold change** — human + Darwin/outcome evidence.
7. **Re-auth OAuth** when grok/chatgpt fail (still common).
8. **Interpret CIO synthesis under degraded local fallback** — trust bundle.
9. **High-impact portfolio actions** — multi-agent reviewers per agents.json, then human.
10. **Secret rotation for `deepseek_tradeai`** — manual until secret_registry entry exists.

---

## 11. agents.json / named-agent notes

| Named agent | Class | Notes |
|-------------|-------|-------|
| `orchestrator` | routing only | Default agent; no LLM body |
| `maria_research` | production persona config | Maps to watchlist Maria jobs |
| `steph_allocation` | production persona config | write_allowed true (router policy), not free broker write |
| `risk_agent` | production persona | stop/honor language |
| `tax_agent` | production persona | Roth/tax placement |
| `alex` | retirement advisor + escalation | model_override claude still listed |
| `iris` | taxonomy | model_override claude still listed |
| `aegis_core` | overnight window 20:00–06:00 | write_allowed true for evidence/briefs |
| `social_scalp` | rules-based | model_override: rules-based |

---

## 12. Bottom line

**Agent autonomy maturity:** overall **~2.5/5**. Production value is real for Hermes research + watchlist committee + Aegis overnight, but architecture is **pipelines-with-personas**, not autonomous agents. Catalog MVL is a **safety-first SHADOW design** with honest denied authorities — good governance, low autonomy.

**DeepSeek maturity: 5/10.** The integration spine is in place (`llm_lane`, `local_llm`, router, CIO v4 path, premium provider enabled, live key). It is **not yet the measured production center of gravity**; OAuth and incomplete call-site migration still dominate observed traffic and many entrypoints.

**Nothing in this audit authorizes production activation of the catalog fleet or removal of human gates on trading.**

---

## 13. Evidence index

| Artifact | Path |
|----------|------|
| Catalog | `config/agent_maturity_catalog.json` |
| Router agents | `config/agents.json` |
| LLM lane | `scripts/llm_lane.py` |
| Local LLM | `scripts/local_llm.py` |
| Router | `scripts/llm_router.py` |
| Watchlist agents | `scripts/process_watchlist_agent_jobs.py` |
| Critic LLM | `scripts/agent_runtime/critic_llm.py` |
| Process registry | `config/llm_process_registry.json` |
| Premium providers | `config/premium_review_providers.yaml` |
| Plan (todos pending) | `docs/DEEPSEEK_INTEGRATION_PLAN_2026_08_01.md` |
| Cache | `scripts/lib/llm_cache.py` |
| Live probe | `docs/audits/platform-autonomy-2026-08-02/evidence/deepseek_probe.json` |
| Live metrics | `docs/audits/platform-autonomy-2026-08-02/evidence/live_metrics.json` |
| Env freeze | `docs/audits/platform-autonomy-2026-08-02/evidence/env_freeze.txt` |

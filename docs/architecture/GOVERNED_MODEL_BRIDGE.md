# The governed model bridge — caps, callers, and how it fails

**Status:** documented 2026-09-06 after a full-day outage of the paid lane
**Service:** `cio-governed-bridge.service` (systemd **user** unit) on `127.0.0.1:8766`
**Code:** `scripts/lib/cio_governed_model_bridge.py`
**Updated:** 2026-10-14 — §0 (AI and LLM governance as served at `3e9dc5e14`) added; §1–§9 are the 2026-09 record

---

## 0. AI and LLM governance — as served 2026-10-14

Measured 2026-10-14 at served `3e9dc5e14` (origin/main `a1b1c5c93`). AGENTS.md §12 (model lanes), §9.2 (model calls)
and §23.4 (n8n model calls) are canonical; this section records what the code does and labels each control
(LIVE / MERGED-NOT-SERVED / PR-OPEN / BRANCH-ONLY / PLANNED / POLICY-ONLY). §4 "projections ~17×" below predates the
calibrated projection (`calibrated_projected_usd`, p90 × 1.5) the bridge now uses.

### 0.1 The pipeline (LIVE) — `execute_governed_call`

The bridge serves `POST /v1/chat/completions` and `GET /health` on 127.0.0.1:8766 (`CIO_BRIDGE_MODE=canary`,
`CIO_BRIDGE_MAX_INFLIGHT` default 4, watchdog `scripts/cio_bridge_watchdog.py`). In order: circuit breaker →
process registration (`llm_process_config` row, else 404 `PROCESS_NOT_REGISTERED`) → server-side policy and lane
(`select_governed_lane`, health gate) → legacy-model rejection and per-process policy allowlist → transport
(canary: non-DeepSeek providers 503 `provider_not_configured`) → step 4b agent preconditions
(`scripts/lib/bridge_agent_preconditions.py`) → step 5 caps (429 `COST_CAP_EXCEEDED`) → 5b routing-policy cost
ceiling → 6 reservation → 6b egress sanitiser → 7 provider call → 8 model-mismatch check → 9 settlement → 9b output
schema and behaviour-field scan → 10 `_tradeai` provenance and `ProviderRequestJournal@v1`.

### 0.2 The six governance areas (§23.24, PROPOSED 11.0.0)

| Area | Control | Status | Evidence |
|---|---|---|---|
| Prompt management | versioned prompts with an `active.json` pin, `vN_system.md` / `vN_user_template.md`, CHANGELOG (`prompts/cio_alex_enrich/` pin v2, `prompts/cio_judge/`); loader `scripts/lib/cio_prompt_loader.py` with last-known-good fallback; eval `cio_prompt_eval.py`, judge `cio_prompt_judge.py` | LIVE | no review/approval field in prompt files; most other prompts are inline in scripts |
| | n8n templates `config/n8n_prompt_templates.json` (3: material_digest_draft.v1, ops_summary_draft.v1, lane_failure_diagnosis.v1), checked host-side in `scripts/lib/n8n_model_job.py` | LIVE | the bridge itself does not check templates |
| Model selection and fallback | caller names a process, never a model: `CALLER_PROCESS_MAP` + `X-TradeAI-Agent`; `config/llm_model_registry.json` (FAST … PRO_MAX, fails closed on unknown/legacy ids); `config/llm_process_registry.json` (75 processes); `config/llm_routing_policy.json` (chains deepseek→grok→chatgpt 37, deepseek-only 28, grok→chatgpt→deepseek 10; concurrency deepseek 6 / grok 2 / chatgpt 2) | LIVE | live bridge transport is DeepSeek only ("no fallback"); OAuth grok/chatgpt transports **PR-OPEN #1738**, OFF unless `CIO_BRIDGE_OAUTH_TRANSPORTS` is set |
| | escalation free → one paid → ask: `scripts/lib/llm_escalation.py` (grok → chatgpt → deepseek-flash → Telegram → stop); `scripts/lib/llm_fallback.py` `NEVER_CHAIN={local,gemma,ollama}` | LIVE | ~143 scripts still mention gemma/ollama; generative local models are policy-barred (`llm_task_policy.py`) |
| Cost and token monitoring | per-process `daily_cost_cap_usd` / `daily_soft_cap` / max tokens; `/caps` (`scripts/lib/llm_cap_admin.py`); ledgers `llm_consumption_log` (reasoning and cache tokens), `llm_cost_reservations`; `ProviderCostEvent@v1`; `scripts/llm_spend_report.py`; global ruled ceiling $2.00/day | LIVE | the global cap is not universally enforced (~78 of 84 lanes, AGENTS.md §12) |
| Response validation | closed schemas `config/schemas/n8n_model_job_outputs.json` + behaviour-field scan (step 9b) | LIVE for `n8n_*` processes only | `llm_output_schemas.py` / `llm_json_contract.py` imported only by tests |
| Hallucination controls | number grounding `scripts/lib/agent_number_grounding.py` (`enforce`, demotes to RESEARCH_MORE), SLO `config/agent_number_grounding_slo.json` RATIFIED 2026-09-30, report `scripts/report_agent_number_grounding.py --check-slo` | LIVE for the watchlist agent jobs | host re-check of an LLM-recommended action (§23.23) PLANNED |
| Output guardrails | `BehaviorWriteRefused` (`cio_instrument_record.py`); router write-gate `_TRADE_WRITE_RE` → `pending_approval`; PI guard `agent_model_pi_guard.scan_model_output` in 3 callers; egress sanitiser `scripts/lib/cio_egress_sanitiser.py` | LIVE (sanitiser in **report** mode) | PI guard not at the bridge; `sanitise_for_external()` single egress point POLICY-ONLY (§2A) |
| HITL escalation | router write-gate forces reviewers; operator-action messages are P1 intents with dedupe off (§9.1) | LIVE | n8n approval Wait + host record (§23.23) PLANNED; `tradeai-approval-router` inactive; an LLM agent can write an operator-attributed approval (WS7-07) |

### 0.3 Controls documented in AGENTS.md that the code does not enforce

| Statement | Reality | Label |
|---|---|---|
| §23.4: caller identity bound to the credential | `TRADEAI_BRIDGE_CALLER_AUTH` defaults to `report`; the header is self-asserted | POLICY-ONLY |
| §23.4: a refused call is queued by `llm_deferral` | the bridge has no deferral code; deferral is in `llm_consumption.gate_and_generate` and armed only where `LLM_DEFER_OFFPEAK=1` | POLICY-ONLY at the bridge |
| §2A: one sanitising egress point | sanitiser runs in report mode; messages leave unchanged | POLICY-ONLY |
| §23.23: `/v1/llm_step`, closed schema, `LlmStepAudit@v1` joined by `run_id` ↔ `execution_id` | PR-OPEN #1738 (head `3c67b55d0`), OFF by default | PR-OPEN |
| §23.23: AI Agent node only with the bridge-backed credential | `N8N_DISABLED_MODULES` includes `agents`; AI nodes excluded | PLANNED |

### 0.4 n8n and LLMs today

No n8n workflow contains an LLM step (0 AI nodes; `NODES_EXCLUDE` and `N8N_DISABLED_MODULES`). LLM work fired by the
dispatcher is a host lane whose model calls go through this bridge; the failure diagnoser (`n8n_failure_diagnosis`)
is a host lane with caps $0.05 per call and $0.10 per day and a 0.7 confidence floor
(`docs/implementation/n8n-maturity/N8N_MONITORING_AND_REMEDIATION_STANDARD.md` §5).

---

## 1. What it is

Every paid model call goes through this one process. It resolves policy, reserves budget, enforces
caps, settles actual cost, and runs a circuit breaker. It is the chokepoint that makes
`LLM_GLOBAL_DAILY_USD_CAP` mean anything.

It is **one Python process**. Restarting it is:

```bash
systemctl --user restart cio-governed-bridge     # scope: service. NOT sudo, NOT a reboot.
```

`:8766` is unavailable for a few seconds. Nothing else is touched.

**Pin rule.** The unit's `WorkingDirectory` is `…/portfolio-server/CURRENT`, but the process
resolves that symlink once at start. After every promote, its `/proc/<pid>/cwd` must equal the
resolved CURRENT (and portfolio-server's cwd). `promote` restarts it via
`TRADEAI_CURRENT_BOUND_UNITS` (default includes `cio-governed-bridge.service` since 2026-09-18).
One-shot align and verification: `docs/ops/BRIDGE_PIN_ALIGNMENT.md`.

## 2. Caller identity is server-side and is NEVER taken from the caller

```
client sends   X-TradeAI-Agent: advisory_desk        (HERMES_BRIDGE_AGENT, default advisory_desk)
bridge maps    CALLER_PROCESS_MAP[advisory_desk] -> advisory_desk_opinion
```

**A caller-supplied `process_id` or `model_id` is never trusted.** That is deliberate: if a script
could name its own budget it could name one with no cap. The consequence is that **you cannot give
a job its own budget by relabelling it** — the mapping is code, and code changes need a restart.

## 3. There are FOUR caps, and they are not all about money

Enforced in `llm_consumption.reserve_projected_cost`:

| cap | source | failure |
|---|---|---|
| process dollar | `llm_process_config.daily_cost_cap_usd` | `COST_CAP_EXCEEDED: process cap` |
| global dollar | `LLM_GLOBAL_DAILY_USD_CAP` (env, `.env`) | `COST_CAP_EXCEEDED: global cap` |
| **process REQUEST COUNT** | `llm_process_config.daily_soft_cap` | `COST_CAP_EXCEEDED: daily request cap` |
| circuit breaker | in-process | breaker open |

**The request-count cap is the one that surprises you.** On 2026-09-06 the usefulness backfill
stopped dead after exactly 200 calls having spent **$0.0742 of a $0.30 budget** — 25% of the money,
100% of the count. Every caller saw `HTTP 500`, which reads like a broken provider and is not.

**Read the error body before diagnosing.** The status is 500; the cause is in the JSON:

```json
{"error": {"code": "RESERVATION_FAILED",
           "message": "COST_CAP_EXCEEDED: daily request cap", "status": 500}}
```

The bridge's own log records only `"POST /v1/chat/completions HTTP/1.1" 500 -` with no reason, so
the log will not tell you. Nor will a `curl` without `X-TradeAI-Agent` — that returns 401 and looks
like an auth problem instead.

## 4. Projections are ~17× actual, so a dollar cap bites ~17× early

`ledger_paid_usd_today` counts `projected_usd` for **reserved** holds and `actual_usd` for
**settled** ones. Measured on 2026-09-06:

```
200 reservations   projected $1.2639   actual $0.0742   ->  17x over-estimate
```

The cause is `HERMES_CLOUD_MAX_TOKENS` (default **4096**) reserving for a response that is a
one-sentence JSON of roughly **60 tokens**. A caller with a small, known response should pass a
realistic value:

```bash
HERMES_CLOUD_MAX_TOKENS=256 python3 scripts/hermes_external_feedback_loop.py --apply
```

**Fixing the estimate is worth more than raising the cap.** At a true rate of ~$0.00006 per call,
`$0.50/day` buys about 8,000 calls; against a 17× projection it buys about 470.

## 5. Reservations that never settle hold budget for ever

Policy in `ledger_paid_usd_today`: `reserved` counts projected, `settled` counts actual, `released`
counts zero. A hold that is never settled therefore consumes budget permanently.
`recover_stale_reservations(max_age_minutes=30)` runs on each reserve, which is what stops that
becoming a slow leak. The docstring records a real incident: sixteen `test_*` rows carrying
synthetic amounts were 99% of one day's apparent $2.72 spend against $0.0141 of real production
cost, and two never settled and blocked a live hop.

## 6. Operational facts that cost time on 2026-09-06

- **It had been running 10 days**, from the release of 2026-08-27, and logs into *that* release's
  `logs/` directory — not the current one. A bridge code change is not live until it is restarted,
  and `journalctl` shows almost nothing because output is redirected.
- **`GET /health` returned 501 until 2026-09-14.** It now returns JSON: `ok`, `circuit_open`, `inflight`, `oldest_inflight_s`, `upstream_deadline_s` (§8).
- **`curl` without `X-TradeAI-Agent` returns 401**, and with an unmapped agent returns
  `Unknown caller … not in server-side mapping`. Neither is the bug you are chasing.

## 7. Changing a cap

Dollar and request caps are **rows**, read per request — no restart needed:

```sql
SELECT process_id, mode, daily_soft_cap, daily_cost_cap_usd
  FROM llm_process_config WHERE process_id = 'advisory_desk_opinion';

UPDATE llm_process_config
   SET daily_soft_cap = 30000            -- 2026-09-06: was 200, raised on operator direction
 WHERE process_id = 'advisory_desk_opinion';
```

**Record the previous values in the change.** `advisory_desk_opinion` was `200 / $0.30` before
2026-09-06.

Adding a *new* process, by contrast, needs a code change to `CALLER_PROCESS_MAP` or `CALLER_TASK_PROCESS_MAP`
**and** a restart, because caller identity is server-side. That is the price of not letting callers name their
own budget, and it is the right trade. §9 lists everything a new caller needs.

## 8. One held call must not wedge it (2026-09-14)

**What happened.** From 15:15 ET, DeepSeek held non-streaming calls about 906 s each.
- It trickled keep-alive bytes, so the 90 s per-read timeout never fired.
- It then returned a 50-character body with no usage, logged as a $0 success.
- The bridge was a single-threaded `HTTPServer`, so every caller queued behind each held call: CIO Hermes
  research (every job failed), desk answers and advisory.
- A restart at 16:15 re-wedged within seconds, because a restart does not shorten a provider's queue.

**What holds now:**

| Control | Setting | Effect |
|---|---|---|
| Wall-clock upstream deadline | `CIO_BRIDGE_UPSTREAM_DEADLINE_S` = 150 | Body streamed, deadline checked per chunk; a hit is a TIMEOUT provider error, so the circuit counts it |
| Threaded server | `ThreadingHTTPServer`, daemon threads | `/health` answers while calls are in flight |
| In-flight slots | `CIO_BRIDGE_MAX_INFLIGHT` = 4 | A full bridge answers 503 `BRIDGE_BUSY` at once; research treats it as retryable |
| `GET /health` | JSON | In-flight count and oldest age, circuit state, last error, deadline |
| Watchdog | `scripts/cio_bridge_watchdog.py`, cron every 5 min, lane `cio-bridge-watchdog` | Restarts after 2 unanswered probes (30 min cooldown); alerts on state change; never restarts for a provider-side problem |
| Memory | `MemoryMax=768M` | The threaded bridge hit 256M 40,579 times in its first hour |

**Diagnose in this order:** `curl /health`; the accept queue (`ss -ltn`, port 8766); in-flight age;
`ss -tinp` `lastsnd`/`lastrcv` on the :443 socket (bytes still arriving means the provider is holding the
request); `pg_stat_activity` for lock waits.

## 9. Callers name themselves (2026-09-14)

The `advisory_desk` caller maps each task type to its own process id:

| Task type | Process id | Mode | Sent by |
|---|---|---|---|
| `advisory_opinion` (and any unknown task) | `advisory_desk_opinion` | automated | advisory opinion engine |
| `advisory_synthesis` | `advisory_desk_synthesis` | automated | advisory Pro synthesis |
| `operator_reply` | `cio_operator_reply` | **manual** | Telegram converse, operator desk loop |
| `plan_enrichment` | `cio_plan_enrichment` | automated | plan enrichment (default for `call_governed_llm`) |
| `prompt_judge` | `cio_prompt_judge` | automated | CIO prompt judge |
| `research_circle` | `research_circle_analyzer` | **manual** | Research Escalation Circle |
| `hermes_cloud_json` | `hermes_cloud_json` | automated | `hermes_llm_failover.chat_json` default |
| `usefulness_score` | `hermes_usefulness_score` | automated | `hermes_external_feedback_loop.py` |
| `hermes_research_job` | `cio_hermes_research` | automated | CIO Hermes queue worker |
| `golden_judge` | `hermes_golden_judge` | automated | Hermes golden judge |

A process registered `manual` is logged with `trigger_mode="manual"`, so the spend report shows it as ad hoc
and the scheduled-work window never applies to it.

**A new caller needs, in the same change:**
- the map entry and a `resolve_model_policy` entry;
- a `config/llm_process_registry.json` row with caps and `default_mode`;
- `sync_cio_process_caps.py`;
- a bridge restart.

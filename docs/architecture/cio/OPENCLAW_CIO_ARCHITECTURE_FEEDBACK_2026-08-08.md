# OpenClaw + Hermes CIO Architecture — Audit Feedback

**Date:** 2026-08-08 03:48 UTC  
**Source:** Live runtime inspection of OpenClaw v2026.6.11 on `ms01-openclaw`  
**Based on:** The v2.0 architecture prompt (32 sections)  

---

## Summary

The CIOrity prompt is architecturally correct in direction. However, the actual runtime state of OpenClaw is orders of magnitude less mature than the prompt assumes. Alex is currently a skill-wrapper agent with no autonomous capabilities. The prompt designs a Ferrari for a platform that currently has a go-kart engine. This feedback identifies the specific gaps, backed by live evidence.

---

## Gate 0: OpenClaw Autonomous Runtime — What Actually Works

### What exists (verified live)

| Capability | State | Evidence |
|-----------|-------|----------|
| OpenClaw gateway | Running | `systemctl --user status openclaw-gateway.service` — active since 13:37, v2026.4.11 service, v2026.6.11 CLI |
| Agent workspaces | 11 exist | maria, steph, aegis, alex, darwin, iris, risk_agent, sentinel, concierge, tradeai-health-inspector, main |
| Cron jobs | 3 enabled | aegis-evening-surveillance, steph-weekly-allocation-review, steph-income-progress |
| Telegram | Connected but degraded | `[telegram] UND_ERR_CONNECT_TIMEOUT` every ~10 min in systemd journal — intermittent connectivity |
| DeepSeek routing | Partially configured | Agent defaults use `deepseek/deepseek-v4-pro` primary, but provider config is ollama-based with gemma3:12b |
| Agent-to-agent delegation | Maria-to-specialists only | `openclaw agent --agent alex --deliver` is the mechanism |
| Skills | 11 installed | tradeai-readonly, tradeai-watchlist, tradeai-health-inspect, wealth, steph-wealth-advisor, scalp-signal-approve, email-calendar, light-research, personal-productivity, operations, integrations |
| Memory/HEARTBEAT | Disabled everywhere | All HEARTBEAT.md files are comments-only: "Keep this file empty to skip heartbeat API calls" |

### What does NOT exist (contrary to prompt assumptions)

| Capability | State | Evidence |
|-----------|-------|----------|
| Alex autonomous heartbeat | DISABLED | `workspace-alex/HEARTBEAT.md` — "Keep this file empty to skip heartbeat API calls" |
| Alex autonomous cron | NONE | Zero Alex cron jobs in `~/.openclaw/workspace/backups/openclaw/jobs.json` |
| Alex agent-to-agent delegation | NONE | Alex can receive delegation from Maria, but cannot initiate delegation to other agents |
| Alex CIO action ledger | NONE | No `cio_action` table. The existing tables are `cio_decisions` (deterministic), `alex_hygiene_log`, `cio_decision_responses` |
| Alex Data Broker access | PARTIAL | Alex's SOUL references `tradeai-readonly` skill but only performance/risk/intelligence/research — not the full CIO matrix in Section 15 |
| Alex financial tool ownership | NONE | `workspace-alex/TOOLS.md` is a template with TTS/camera/SSH examples. No financial tools defined. |
| Guardian/Ledger/Vega/Iris/Darwin agents | SKELETONS | Workspaces exist but SOUL files are generic or undefined. No operational roles. |
| Hermes-to-OpenClaw bridge | NONE | Hermes has 16,152 research rows (last: today 21:26) but no channel from Hermes to OpenClaw Alex |
| Model governance gateway | NONE | OpenClaw calls providers directly via its config. No integration with Trade AI's `llm_router.py` or governed process registry |
| CIO action ledger DB | NONE | No `cio_action_id`, `cio_action` table, or `followup_condition` column exists |
| OpenAI secondary review path | CONFIGURED BUT UNTESTED | `chatgpt/gpt-5.4` is listed as a fallback but the OpenAI provider config was not found active |
| Memory search | DISABLED | Heartbeat/MEMORY files are comments-only across all agents |

---

## Section-by-Section Gaps

### Section 5 (Known OpenClaw Findings)

The prompt lists 22 items to verify (`openclaw_version`, `openclaw_gateway_state`, etc.). Here are the actual answers:

```
openclaw_version:          2026.6.11 (e085fa1)
openclaw_gateway_state:    active (running), service v2026.4.11
openclaw_agent_roster:     11 agents (maria, steph, aegis, alex, darwin, iris, risk_agent, sentinel, concierge, tradeai-health-inspector, main)
openclaw_agent_models:     defaults: deepseek-v4-pro → v4-flash → deepseek-chat → gpt-5.4 → qwen3:8b
openclaw_fallback_chains:  5-deep chain configured but untested end-to-end
openclaw_skills:           11 skills
openclaw_mcp_servers:      NOT FOUND in skill manifests
openclaw_memory_capabilities:  DISABLED (all HEARTBEAT.md are comments-only)
openclaw_heartbeat_capabilities:  DISABLED
openclaw_cron_jobs:        3 jobs (all non-Alex)
openclaw_disabled_jobs:    Unknown — no disabled_jobs.json found
openclaw_telegram_route:   Maria is front door; connectivity degraded (timeouts in journal)
openclaw_exec_permissions:  Maria executes python3 scripts via skills; exec permission via shell tool
openclaw_tradeai_readonly_tools:  tradeai-readonly skill (CLI-based, not API-based)
openclaw_tradeai_write_tools:  tradeai-watchlist skill (watchlist adds, save-knowledge)
openclaw_agent_delegation_support:  Maria→specialist only (one-directional)
openclaw_agent_to_agent_handoff_support:  NONE — no handoff_id, no artifact tracking
openclaw_session_persistence:  Node.js process, no durable session store visible
openclaw_failure_recovery:  systemd restart only — no agent-level recovery
openclaw_audit_tracing:  NONE — no immutable audit log for agent actions
```

### Section 8 (Repository Audit): Missing from the checklist

The prompt's audit list omits the existing auto-remediation infrastructure that was built and matured in the current session (Aug 7, 2026):

- `scripts/claude_escalation_handler.py` — processes health findings, executes allowlisted retry commands, dispatches to AI coders. Currently runs every 10 min 24/7 with `--tier1-only` (no LLM hangs)
- `scripts/health_agent.py` — scores all 6 health categories (data_quality, execution_health, intelligence_quality, risk_protection, retirement_planning, pipeline_freshness), detects trends, enqueues findings into `claude_escalation_queue.json`. Runs every 15 min 24/7
- `scripts/lib/live_project_root.py` — resolves the live deployment directory via CURRENT symlink → RuntimeAwareness → dev fallback. Critical because all cron jobs run from the dev directory but the live API reads from the release directory
- `scripts/lib/runtime_awareness.py` — discovers the live server PID, directory, and cache paths via `ss -tlnp`
- `config/claude_escalation_allowlist.yaml` — governs which retry commands the handler can execute automatically
- `config/health_agent_policy.json` — contains the `remediation_map` mapping finding types to allowlisted retry commands. Currently covers 50+ finding types
- `scripts/coder_dispatch.py` — receives code-fix escalations, creates git worktrees, dispatches AI coders

**The prompt should explicitly address whether Alex absorbs or replaces the escalation handler and health agent, or delegates to them as specialists.**

### Section 10 (Design A Real OpenClaw CIO Agent)

The current Alex is NOT a CIO. Evidence:

1. **No autonomous heartbeat.** `workspace-alex/HEARTBEAT.md`:
   ```
   # Keep this file empty (or with only comments) to skip heartbeat API calls.
   ```
   Alex cannot wake autonomously. The entire OBSERVE-ORIENT-PLAN-DELEGATE-CHALLENGE-SYNTHESIZE-COMMUNICATE-FOLLOWUP-LEARN-ABSTAIN loop is impossible without heartbeat.

2. **Alex is a prompt responder, not an autonomous manager.** His SOUL.md defines:
   - "Live delegation: Maria may forward CIO/strategy/retirement questions"
   - "Scheduled digests: OpenClaw cron Alex Monthly Retirement Check-in"
   - No mention of autonomous monitoring, event-driven wake, or self-directed delegation

3. **No financial tools defined.** `workspace-alex/TOOLS.md` is a generic template with TTS voice preferences and camera names. The prompt's financial responsibility matrix (Section 16) requires 30+ data sources; Alex has zero defined.

4. **No agent catalog entry.** `config/agent_maturity_catalog.json` has zero entries matching "alex" or "cio".

5. **Existing CIO tables are legacy, not agent-driven.** `cio_decisions` (deterministic decision engine output), `alex_hygiene_log`, `cio_decision_responses` — none of these have the `cio_action_id`, `followup_condition`, or `next_check_at` fields the prompt defines in Section 17.

### Section 11 (OpenClaw Agent Team)

The prompt proposes 9 specialist agents (Alex, Maria, Steph, Guardian, Ledger, Vega, Aegis, Iris, Concierge). Current state:

| Agent | Exists | Has SOUL | Has HEARTBEAT | Has TOOLS | Operational |
|-------|--------|----------|---------------|-----------|-------------|
| Maria | Yes | Detailed | No file found | No file found | YES — active Telegram front door |
| Steph | Yes | Detailed | Has file | Has file | YES — weekly cron + delegation |
| Aegis | Yes | Detailed | Has file | Has file | YES — evening cron + delegation |
| Alex | Yes | Partial (watchlist/CIO lite) | Disabled | Template (TTS/cameras) | NO — delegation-only, no autonomy |
| Guardian/Risk | risk_agent workspace only | Template-like | No evidence | No evidence | NO |
| Ledger/Tax | NO WORKSPACE | Does not exist | Does not exist | Does not exist | NO |
| Vega | NO WORKSPACE | Does not exist | Does not exist | Does not exist | NO |
| Iris | Exists | Generic | Has file | Has file | UNKNOWN — no evidence of runs |
| Darwin | Exists | Minimal | No evidence | No evidence | UNKNOWN |
| Sentinel | Exists | Minimal | No evidence | No evidence | UNKNOWN |
| Concierge | Exists | Minimal | No evidence | No evidence | UNKNOWN |
| tradeai-health-inspector | Exists | Detailed (built Aug 7) | Has file | Has file | PARTIAL — daemon running but DeepSeek auth unverified |

**Gap:** The prompt assumes 9 operational specialists. Only 3 are operational (Maria, Steph, Aegis). Guardian, Ledger, Vega, Iris, Darwin, Sentinel, and Concierge are either non-existent or skeletal.

### Section 12 (Hermes as Autonomous Research Challenger)

Good news: Hermes IS operational.

```
hermes_research_intelligence rows:  16,152
hermes_research last entry:         2026-08-07 21:26:16 ET
```

Bad news: There is no channel from Hermes to OpenClaw.

- Hermes writes to `hermes_research_intelligence` table in PostgreSQL
- OpenClaw agents read via the `tradeai-readonly` skill (CLI wrapper)
- No push mechanism from Hermes to Alex
- No `hermes_challenge_id` schema in the DB
- No `Alex requests Hermes challenger` contract exists

The prompt's coordination contract (Section 13) requires a `handoff_id` with `from_agent`, `to_agent`, `input_snapshot_id`, `deadline`, and `budget`. None of these fields exist in any current table.

### Section 14 (Model Routing — DeepSeek First)

The prompt is correct in direction but needs correction for reality:

1. **OpenClaw provider config is ollama-based, not DeepSeek-native.** The `openclaw.json` provider config uses `ollama` with `gemma3:12b` as the base. Agent defaults say `deepseek/deepseek-v4-pro` but this has not been proven to work end-to-end.

2. **DeepSeek auth was broken in this session.** Previous attempts to use DeepSeek via OpenClaw failed because auth required an interactive TTY (`openclaw models auth login --provider deepseek --force`). This is a blocking issue for the entire architecture.

3. **No Trade AI LLM router integration.** The prompt says "Preferred: centralized governed router." The Trade AI `llm_router.py` and `llm_process_registry.json` exist but OpenClaw does not use them. OpenClaw calls providers directly.

4. **LLM cost cap is $0.25/day.** `LLM_GLOBAL_DAILY_USD_CAP=0.25` in the systemd drop-in. Running DeepSeek Pro for every CIO synthesis would likely exceed this. The prompt has no cost budget question in Section 7.

### Section 15 (Data Broker First)

The prompt's Data Broker matrix is comprehensive but the runtime reality is:

- The `tradeai-readonly` skill is CLI-based (`python3 tradeai_readonly.py <command>`), not API-based
- OpenClaw agents shell-exec to get data, they don't call canonical APIs
- The matrix's 30+ CIO requirements don't all have Data Broker projections yet — sections like "retirement models," "goals/IPS," and "operator action ledger" have no Data Broker domain
- The current system reads from HTML pages in some cases (`portfolio-today` parses JSON from API but others may not)

### Section 18 (OpenClaw Memory)

Critical finding: **Memory is disabled across all OpenClaw agents.**

Every HEARTBEAT.md and MEMORY.md file found contains:
```
# Keep this file empty (or with only comments) to skip heartbeat API calls.
```

This means:
- No agent remembers previous conversations between sessions
- No agent stores operator preferences durably
- No agent tracks follow-up deadlines autonomously
- The entire "follow up on unresolved actions" capability in Section 10 is impossible without memory

The prompt correctly separates financial memory (Trade AI) from conversational memory (OpenClaw), but **neither exists today in usable form for Alex.**

### Section 19 (Autonomous Cadence)

The prompt defines heartbeats, premarket, intraday, close, MWF research, weekly letters, monthly reviews, and quarterly IPS reviews. Current cron:

```
aegis-evening-surveillance:   0 20 * * 1-5    (weeknights at 8pm)
steph-weekly-allocation-review: 0 9 * * 0     (Sundays at 9am)
steph-income-progress:         0 9 1 * *      (1st of month at 9am)
```

**Zero of the prompt's proposed cadences exist.** No morning briefs. No intraday event triggers. No close summaries. No MWF research refreshes. No weekly CIO letters.

### Section 20 (Telegram)

Maria IS the Telegram front door. The prompt correctly questions whether this should remain. The evidence:

- All DMs route to Maria
- Maria delegates to specialists via `openclaw agent --agent <name> --deliver`
- Telegram has intermittent connectivity issues (timeouts in journal every ~10 min)
- No `/cio` commands exist. No `/hermes` commands exist.
- The prompt's recommended command set (`/cio today`, `/cio actions`, etc.) would require significant implementation

### Section 17 (CIO Action Ledger)

The prompt's `cio_action` schema is well-designed but:

- **No table exists.** The closest are `cio_decisions` (deterministic engine output) and `cio_decision_responses` (operator responses)
- **No `followup_condition` field** in any existing table
- **No `next_check_at` field** in any existing table
- **No agent artifact references** — the existing system doesn't link specialist outputs to CIO actions

### Section 27 (Implementation Phases)

The prompt proposes 16 phases starting with "Phase 0 — Live truth reconciliation." There should be a **Phase -1: OpenClaw platform hardening** before any Alex design:

1. Enable and test OpenClaw heartbeat across all agents
2. Enable and test OpenClaw memory/retrieval
3. Prove DeepSeek auth works end-to-end for autonomous calls (not requiring TTY)
4. Add Alex cron jobs (at least a no-model idle heartbeat)
5. Establish OpenClaw-to-Trade-ai LLM router integration
6. Verify Telegram reliability (current timeouts)
7. Deploy Guardian, Ledger, Vega, Iris, Darwin, Sentinel workspaces with operational SOULs
8. Build Hermes-to-OpenClaw push channel

---

## Architecture Decision Corrections

### ADR 1 — Where does Alex live?

The prompt asks to choose between OpenClaw-native, Trade AI durable runtime, hybrid, or Hermes-owned.

**Live evidence demands the hybrid pattern.** OpenClaw provides identity and delegation (Maria already does this) but has no durable state, heartbeat, or memory. Trade AI has the financial truth, DB persistence, and the health/escalation infrastructure. Alex needs both.

### ADR 3 — Memory ownership

The prompt correctly separates financial memory (Trade AI) from conversational memory (OpenClaw). But **both are currently broken** — OpenClaw memory is disabled and Trade AI has no CIO-specific durable memory table. Both need to be built before the separation matters.

### ADR 5 — Model gateway

The prompt prefers the governed Trade AI LLM router. **Correct.** OpenClaw currently calls providers directly. The migration path is: build the gateway integration → migrate one agent → migrate all → deprecate direct calls.

### ADR 6 — Scheduler ownership

The prompt warns against duplicate cron + systemd timer + Trade AI scheduler. **The current system already has this problem.** The escalation handler runs from system cron (`*/10 * * * *`), the health agent runs from system cron (`*/15 * * * *`), and OpenClaw has its own cron (`0 20 * * 1-5` for Aegis). Three schedulers for three different subsystems. The prompt's recommendation to "choose one owner per trigger" is correct but the current state makes this a migration, not a greenfield decision.

---

## Top 10 Gaps (prioritized by blocking impact)

1. **DeepSeek auth does not work for autonomous calls.** The entire architecture assumes DeepSeek-first model routing. This must be proven before designing anything else.

2. **Alex has no heartbeat, memory, or cron.** The OBSERVE-ORIENT-PLAN loop cannot function without these OpenClaw platform capabilities.

3. **Guardian, Ledger, Vega, Iris, Darwin, Sentinel, Concierge are skeletons or non-existent.** The prompt's 9-agent team has 3 operational members.

4. **No Hermes-to-OpenClaw channel.** Hermes actively produces research (16,152 rows, today's data) but has no push mechanism to Alex.

5. **No CIO action ledger table.** The prompt's primary product (Section 17) has no database schema, no API, no CRUD operations.

6. **No agent-to-agent delegation beyond Maria→specialist.** Alex cannot delegate to Maria, Guardian, or Hermes autonomously.

7. **Telegram connectivity is degraded.** Timeouts every ~10 min. The primary operator channel is unreliable.

8. **LLM cost cap ($0.25/day) may not support CIO workload.** DeepSeek Pro for weekly CIO letters + daily briefs could exceed the cap.

9. **No Data Broker integration with OpenClaw.** Agents use CLI wrappers, not governed API projections.

10. **The escalation handler and health agent auto-remediation system is not mentioned in the prompt.** These are the closest existing components to "autonomous monitoring" — the prompt should address whether Alex replaces, absorbs, or delegates to them.

---

## Recommended Prompt Additions

### Add to Section 5 (Known OpenClaw Findings)

```
- Can OpenClaw autonomously call DeepSeek without TTY? (PROVE THIS FIRST)
- Does the OpenClaw provider config match the agent defaults, or is there a conflict?
- What is the current OpenClaw-to-Trade-AI path? (CLI skills calling python3 scripts)
- Are heartbeat and memory intentionally disabled, or is this a configuration issue?
- What is the current Telegram reliability? (check systemd journal for timeout frequency)
```

### Add to Section 7 (Required Live Baseline)

```
# Health system baseline (NEW)
curl http://localhost:7777/api/v2/health | jq '.data.overall_score, .data.category_scores'
curl http://localhost:7777/api/v2/health/remediation | jq '.data.items | length'
python3 scripts/health_agent.py --json | jq '.data_quality, .execution_health'

# Escalation queue baseline (NEW)
cat logs/claude_escalation_queue.json | jq 'length'
cat logs/claude_escalation_retry_cmd.jsonl | tail -5

# Cost baseline (NEW)
grep LLM_GLOBAL_DAILY_USD_CAP .config/systemd/user/portfolio-server.service.d/*
# Estimate: how many DeepSeek Pro calls does Alex need daily? At what cost?

# Telegram reliability baseline (NEW)
journalctl --user -u openclaw-gateway.service --since "24 hours ago" | grep -c "timeout\|unhealthy\|UND_ERR"
```

### Add to Section 8 (Required Repository Audit)

```
Escalation / health infrastructure (NEW)
----------------------------------------
scripts/claude_escalation_handler.py
scripts/health_agent.py
scripts/lib/live_project_root.py
scripts/lib/runtime_awareness.py
config/claude_escalation_allowlist.yaml
config/health_agent_policy.json
scripts/coder_dispatch.py
```

### Add a Gate 0 before Phase 0

```
Gate 0 — Prove OpenClaw platform readiness
------------------------------------------
1. Run openclaw agent --agent alex --message "What is the current portfolio value?"
   via the DeepSeek provider chain. Must complete without TTY.
2. Enable heartbeat on alex workspace. Verify it persists between sessions.
3. Run one cron job for Alex. Verify it executes without operator intervention.
4. Verify Telegram delivery from an autonomous Alex turn.
If any of these fail, the platform is not ready for CIO agent design.
```

---

## Final Answer to Section 30 (Required Final Architecture Decision)

```yaml
cio_agent_id: alex
cio_display_name: Alex
cio_platform: OPENCLAW  # correct choice, but platform needs hardening first
openclaw_role: AUTONOMOUS_ADVISORY  # requires enabled heartbeat + memory + cron
trade_ai_role: CANONICAL_TRUTH + DURABLE_STATE + COST_GOVERNANCE
hermes_role: INDEPENDENT_RESEARCH_CHALLENGER  # already operational
durable_run_state_owner: TRADE_AI  # cio_action table + cio_decision_responses
scheduler_owner: TRADE_AI_SYSTEM_CRON  # already runs health agent + escalation handler
operator_gateway: OPENCLAW_TELEGRAM  # Maria is current front door
telegram_front_door: MARIA_WITH_CIO_ROUTING  # keep Maria, add /cio commands
financial_memory_owner: TRADE_AI  # PostgreSQL, not MEMORY.md
conversational_memory_owner: OPENCLAW  # must be enabled first
data_source: TRADE_AI_DATA_BROKER  # canonical API projections, not CLI wrappers
primary_routine_provider: DEEPSEEK
primary_routine_model: V4_FLASH_FAST
primary_cio_provider: DEEPSEEK
primary_cio_model: V4_PRO
primary_cio_policy: THINKING_OFF_EXCEPT_MATERIAL_ESCALATION
complex_escalation_policy: PRO_THINK_WITH_DETERMINISTIC_REASON
secondary_provider: OPENAI
secondary_model: GPT_5_4
secondary_trigger_policy: EXPLICIT_OPERATOR_OR_MATERIAL_CONFLICT_ONLY
codex_role: ENGINEERING_AGENT  # not live CIO model
fundamental_researcher: MARIA  # operational
portfolio_allocation_critic: STEPH  # operational
risk_critic: GUARDIAN  # DOES NOT EXIST — must be built
tax_critic: LEDGER  # DOES NOT EXIST — must be built
technical_critic: VEGA  # DOES NOT EXIST — must be built
research_challenger: HERMES  # operational, no bridge to OpenClaw
outcome_scorer: DARWIN  # skeletal
knowledge_curator: IRIS  # skeletal
action_ledger_owner: TRADE_AI_POSTGRESQL  # table must be created
learning_policy: OPERATOR_APPROVED_ONLY  # Section 22 is correct
financial_authority: READ_ONLY_ADVISORY  # Section 26 is correct
```

---

## Conclusion

The prompt is architecturally sound and its direction is correct. The issue is that it designs against an idealized OpenClaw that doesn't match the runtime reality.

The first deliverable should be a **Platform Readiness Report** answering the Gate 0 questions. Until heartbeat, memory, DeepSeek auth, and agent-to-agent delegation are proven, designing a 16-phase implementation plan is premature.

The second deliverable should be a **gap list** against the runtime evidence above: 5 of 9 specialist agents don't exist, Hermes has no OpenClaw bridge, the CIO action ledger has no table, and the Data Broker has no governed API tools for OpenClaw.

The prompt is a strong architecture document. It just needs a Phase -1 for platform hardening and an honest accounting of what exists versus what needs to be built.

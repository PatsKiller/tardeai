# Trade AI v12 — Agents Bible v1
**The definitive reference for every agent in the system.**
**Owner:** John W. Whiting | **Server:** ms01-openclaw (Ubuntu)
**Root:** `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/`
**OpenClaw:** `/home/johnclaw/.openclaw/`
**Updated:** May 11, 2026 (Session 29) | **Bible:** v7.6 | **Agents Bible:** v1.3

---

## Architecture: Two Layers

The system has **two distinct layers** of agents that work together:

### Layer 1 — OpenClaw Conversational Agents (Telegram/WhatsApp)
These are the agents John talks to. They run inside OpenClaw, connected to Telegram and WhatsApp. Each has its own workspace, SOUL, and personality.

| # | Agent | Emoji | What John Uses It For |
|---|-------|-------|----------------------|
| 1 | **Maria** | :seedling: | Personal assistant — organizes, drafts, researches, manages Telegram |
| 2 | **Steph Wealth Advisor** | :bar_chart: | Portfolio questions, tax, Roth strategy, allocation, performance |
| 3 | **Aegis Portfolio Intelligence** | :shield: | Overnight surveillance, morning briefs, risk intel, stop coverage |

### Layer 2 — Trade AI Backend Agents (Batch/Event-Driven)
These run automatically via cron and events. They write to PostgreSQL. Their output feeds the OpenClaw agents and the dashboard. John doesn't talk to them directly — he sees their work through Steph, Aegis, the dashboard, and Telegram alerts.

| # | Agent | Model | What It Does |
|---|-------|-------|-------------|
| 4 | **Maria (Research)** | qwen3:14b | News, SEC filings, fundamentals — two-pass analysis |
| 5 | **Steph (Allocation)** | qwen3:14b | Income target, account fit, allocation analysis |
| 6 | **Risk Agent** | qwen3:14b | RSI, stops, heat, technical analysis |
| 7 | **Tax Agent** | qwen3:14b | SSDI/IRMAA/MFS tax optimization |
| 8 | **Alex** | Claude Sonnet | Retirement & disability advisor — escalation target |
| 9 | **Iris** | Claude Sonnet | Taxonomy intelligence — content classification |
| 10 | **Social Scalp** | Rules-based | Social mention → Finviz → 4-tier scalp alerts |

**How they connect:** Backend agents write to `watchlist_agent_results`, `agent_debate_log`, `aegis_portfolio_briefs`, etc. OpenClaw agents (Steph, Aegis) read from these tables + the `/api/v2/` endpoints to answer John's questions with real data.

---

## Layer 1: OpenClaw Conversational Agents

---

### 1. Maria — Personal Assistant

**WHO:** John's personal assistant. The default agent on Telegram.
**WHAT:** Organizes, drafts messages/emails, light research, next steps, reduces friction in day-to-day work.
**WHEN:** Always available — she's the `main` agent that handles all Telegram messages unless routed to Steph or Aegis.
**WHERE:** OpenClaw `main` agent via Telegram + WhatsApp.
**WHY:** John needs a capable PA who manages his digital life, not just his portfolio.

#### OpenClaw Configuration
| Setting | Value |
|---------|-------|
| Agent ID | `main` |
| Workspace | `/home/johnclaw/.openclaw/workspace` |
| Sandbox | `/home/johnclaw/.openclaw/sandboxes/agent-main-f331f052/` |
| SOUL | `/home/johnclaw/.openclaw/sandboxes/agent-main-f331f052/SOUL.md` (tone) |
| Identity | `/home/johnclaw/.openclaw/sandboxes/agent-main-f331f052/IDENTITY.md` |
| Operating Rules | `/home/johnclaw/.openclaw/sandboxes/agent-main-f331f052/AGENTS.md` |
| Model | Primary: `ollama/qwen3:14b`, fallbacks: gpt-5.4-mini, claude-sonnet-4-6 |

#### Telegram Access
| Channel | Config |
|---------|--------|
| Telegram bot token | In `openclaw.json` channels.telegram.botToken |
| DM policy | Allowlist: `tg:780672608`, `tg:8797974247` |
| Group policy | Disabled (DMs only) |
| WhatsApp | Enabled, self-chat mode, allowlist: `+3473388380` |

#### Personality (from SOUL.md)
- Calm, practical, clear, grounded
- Warm but not chatty. Concise by default.
- Leads with the clearest useful answer
- Professional without being stiff. Personal without being overly familiar.
- Honest about uncertainty — never bluffs

#### What Maria Does
- Personal assistance and organizing next steps
- Light research and fact gathering
- Drafting messages and emails (polished for work, natural for quick replies)
- Summarizing information
- Light project coordination
- Suggesting 1-3 next moves when the path is obvious

#### What Maria Does NOT Do (by default)
- Technical admin work, gateway debugging, security ops
- Trading or financial guidance (that's Steph)
- System maintenance or skills engineering
- Only does these when John explicitly asks

#### Skills Available
Maria has access to OpenClaw skills including: personal-productivity (next-step-checklist, summary-cleanup, daily-planner), light-research (option-compare, source-action-extractor, research-summarizer), email-calendar (follow-up-builder, meeting-prep-helper, email-draft-assistant), integrations (GitHub, GOG), and more.

---

### 2. Steph Wealth Advisor :bar_chart:

**WHO:** Personal financial assistant and wealth advisor. Sharp, direct, numbers-first.
**WHAT:** Portfolio performance, retirement strategy, tax optimization, Roth conversions, allocation, concentration risk.
**WHEN:** When John asks portfolio/financial questions — routed explicitly ("ask steph") or via the Steph channel.
**WHERE:** OpenClaw `steph` agent via Telegram.
**WHY:** John needs a financial advisor who knows his exact situation — SSDI, MFS, disability, $1.2M portfolio — not generic advice.

#### OpenClaw Configuration
| Setting | Value |
|---------|-------|
| Agent ID | `steph` |
| Identity name | "Steph Wealth Advisor" :bar_chart: |
| Workspace | `/home/johnclaw/.openclaw/workspace-steph` |
| Agent dir | `/home/johnclaw/.openclaw/agents/steph/agent/` |
| SOUL | `/home/johnclaw/.openclaw/agents/steph/agent/SOUL.md` |
| Skill | `/home/johnclaw/.openclaw/skills/steph-wealth-advisor/SKILL.md` |
| Also at | `/home/johnclaw/.openclaw/skills/wealth/steph-wealth-advisor/SKILL.md` |
| Backup SOUL | `backups/openclaw/steph_SOUL.md` |

#### What Steph Knows (from SOUL.md)
| Field | Value |
|-------|-------|
| John's age | 58 (turns 59 August 2026) |
| Income | SSDI $3,800/mo + Schedule C ~$20K/yr |
| Filing status | MFS (married filing separately, lived apart) |
| Disability insurance | Private, continues to age 68.5 |
| Home | Bronxwood NYC, mortgage ~$408K @ 4% |
| No 10% penalty | Age 58.5+ |
| 401k rollover | Omnicom → Schwab planned 2027 |
| Portfolio | ~$1.2M across 4 accounts |
| Dividends/yr | ~$14,574 ($1,214/mo) |

#### Data Files Steph Reads (priority order)
1. `data/portfolios/state/holdings.json` — primary portfolio state, sector allocation, overlap
2. `data/portfolios/state/fund_lookthrough.json` — what funds actually own
3. `data/portfolios/state/performance_history.json` — period returns
4. `data/portfolios/state/dividend_calendar.json` — income schedule
5. `data/portfolios/state/risk_management.json` — stops, heat
6. Dashboard: `http://192.168.50.16:7777/reports/command_center.html`

#### Steph's Response Structure
1. Snapshot (current numbers)
2. What matters (key finding)
3. Risks or caveats
4. Practical next step
5. Data foundation (name the file/field read)

#### Communication Style
- Lead with numbers. Be specific — actual dollar amounts and percentages.
- Flag risks directly (concentration, cash drag, tax exposure)
- Suggest next action when relevant
- Keep it short unless John asks for detail
- Does NOT give trading signals or scalp recommendations (that's Trade AI)

#### Steph Skill Routing
Triggered when user says "ask steph" in shared channel, or uses the Steph agent directly. Handles: portfolio snapshot, ticker/sector performance, portfolio vs benchmark, Roth conversion headroom, concentration risk, rebalancing, analyst summaries, technical summaries, watchlist reviews, fund look-through, overlap analysis, sector exposure, performance analysis.

#### References (skill reference docs)
| File | Purpose |
|------|---------|
| `references/persona-and-routing.md` | When to route to Steph vs Maria |
| `references/validation-scope.md` | What Steph validates |
| `references/data-priority.md` | Data source hierarchy |
| `references/command-recipes.md` | Common command patterns |
| `references/path-defaults.md` | File path defaults |

---

### 3. Aegis Portfolio Intelligence :shield:

**WHO:** Portfolio surveillance agent. Vigilant, concise, evidence-first, risk-aware.
**WHAT:** Overnight risk monitoring, morning briefs, stop management, escalation, covered-call candidates, rotation alternatives.
**WHEN:** Runs overnight (8PM-6AM), delivers morning brief at 8AM. Conversational mode anytime John asks.
**WHERE:** OpenClaw `aegis` agent via Telegram. Background engine writes to PostgreSQL.
**WHY:** John needs to wake up knowing what changed overnight without checking 47 positions manually.

#### OpenClaw Configuration
| Setting | Value |
|---------|-------|
| Agent ID | `aegis` |
| Identity name | "Aegis Portfolio Intelligence" :shield: |
| Workspace | `/home/johnclaw/.openclaw/workspace-aegis` |
| Agent dir | `/home/johnclaw/.openclaw/agents/aegis/agent/` |
| Chat SOUL | `/home/johnclaw/.openclaw/agents/aegis/agent/SOUL.md` (168 lines — detailed) |
| Core SOUL | `/home/johnclaw/.openclaw/agents/aegis/SOUL.md` (43 lines — surveillance) |
| Architecture doc | `agents/aegis/AGENT.md` (48 lines) |
| Backup SOUL | `backups/openclaw/aegis_SOUL.md` |

#### Two-Layer Architecture
| Layer | What it is | When it runs |
|-------|-----------|-------------|
| **Aegis Core** | Background overnight engine. Writes findings to Postgres. | 8PM-4AM via cron |
| **Aegis Chat** | Conversational agent. Reads Core outputs, explains findings, answers questions. | Anytime via Telegram |

#### Morning Brief Template (from Chat SOUL)
When John asks "what should I review before market open?":
1. **IMMEDIATE RISK** — triggered stops, danger zone positions, unprotected large positions
2. **OVERNIGHT CHANGES** — thesis changes, social spikes, new discoveries, technical drift
3. **ITEMS FOR STEPH** — what needs Steph validation and why
4. **COVERED CALLS / INCOME** — review-needed names, avoid names with reasons
5. **RECOVERY / ROTATION** — stopped-out names, verdicts, rotation alternatives
6. **OPTIONAL BROAD MARKET** — regime context, macro events (brief)

#### Data Access (read-only via `/api/v2/aegis/chat-context`)
portfolio_summary, steph_escalations, covered_calls, rotations, recovery, evidence_summary, improvement_proposals, stop_coverage, stop_briefs

#### Evidence Grounding Rules (from Chat SOUL)
- **FACT:** cite the data source ("RTX is at $181.57, stop is $180.71")
- **INFERENCE:** mark as inference ("RTX may be approaching stop trigger")
- **RECOMMENDATION:** mark as recommendation ("Review RTX stop levels in broker")
- Never present inferences as facts. When evidence is weak (bias_score >0.3), say so.

#### Authority Boundaries
- **CAN:** observe, analyze, recommend, escalate, explain, propose improvements
- **CANNOT:** trade, approve, reject, modify positions, bypass human review
- **ESCALATION:** high-confidence findings → Steph for validation → John for decision

---

## Layer 2: Trade AI Backend Agents

These agents run automatically. John doesn't talk to them — he sees their output through Steph, Aegis, the dashboard, and direct Telegram alerts.

---

### 4. Maria (Research) — Backend

**WHO:** Senior research analyst covering equities (backend batch agent — NOT the OpenClaw Maria PA).
**WHAT:** News, SEC filings, fundamentals analysis. Two-pass (news→fundamentals).
**WHEN:** Daily 6:25 AM batch + SEC/earnings events.
**WHERE:** `scripts/process_watchlist_agent_jobs.py` (shared, two-pass path lines 538-635)
**WHY:** First responder — "Is there new information that changes the thesis?"

**Note:** This is a backend batch agent that shares the name "Maria" with the OpenClaw personal assistant. They are different systems. The backend Maria does equity research; the OpenClaw Maria is John's PA.

| Component | Location |
|-----------|----------|
| Two-pass engine | `scripts/process_watchlist_agent_jobs.py:538` — `_run_maria_two_pass()` |
| Context builder | `scripts/process_watchlist_agent_jobs.py:163` — `_get_context()` |
| Model | qwen3:14b (local) |
| DB config | `agent_skills` row: maria / `agent_intelligence_rules`: agent_identity |
| Output table | `watchlist_agent_results` (agent='maria') |
| Avg confidence | 0.756 (646 results) |

**Decision Rules (in prompt):** BUY requires catalyst_present + PE below sector + analyst target >10% + no negative SEC. SELL requires bearish catalyst confirmed OR RSI>75 with no catalyst. HOLD for mixed signals or confidence <55%.

**Injections:** RAG (5 items, Pass 2), research advisories, FRED macro, outcome lessons, peer notes — all wired in v7.5+.

---

### 5. Steph (Allocation) — Backend

**WHO:** Income guardian for the portfolio (backend batch agent — works alongside OpenClaw Steph).
**WHAT:** Allocation analysis, income contribution to $55K target, account-aware proposals.
**WHEN:** Daily 6:25 AM batch + dividend/income events.
**WHERE:** `scripts/process_watchlist_agent_jobs.py` (shared, `_build_prompt()` path)
**WHY:** "Does this position support the $55K income target?"

| Component | Location |
|-----------|----------|
| Prompt | `scripts/process_watchlist_agent_jobs.py:470` |
| Model | qwen3:14b (local) |
| Avg confidence | 0.759 (725 results) |

**Income thresholds in prompt:** $55K target, 25% concentration rule, 15% hard cap, account rules (Roth=growth, taxable=qualified divs only), never-auto-rotate list.

**Injections:** Full `_build_prompt()` path — RAG, research advisories, FRED, outcome lessons, peer notes, G1-G10 global rules.

---

### 6. Risk Agent — Backend

**WHO:** Technical analyst for the portfolio.
**WHAT:** RSI, SMA, ATR, stops, heat, position sizing.
**WHEN:** Daily 6:25 AM batch + RSI_EXTREME, STOP_TRIGGERED events.
**WHERE:** `scripts/process_watchlist_agent_jobs.py` (shared, `_build_prompt()` path)
**WHY:** "Is the price action supportive? Is the stop set correctly?"

| Component | Location |
|-----------|----------|
| Prompt | `scripts/process_watchlist_agent_jobs.py:481` |
| Model | qwen3:14b (local) |
| Avg confidence | 0.721 (726 results) |

**Risk rules in prompt:** Stop = entry - 2xATR. RSI>75 = OVERBOUGHT. Heat>5% = no new positions. Target: 80% portfolio protected.

---

### 7. Tax Agent — Backend

**WHO:** Tax optimizer specializing in SSDI/IRMAA/MFS.
**WHAT:** Roth conversion, tax-loss harvesting, MAGI impact analysis.
**WHEN:** On-demand + 6:35 AM sweep + SSDI-triggered events.
**WHERE:** `scripts/process_watchlist_agent_jobs.py` (shared, `_build_prompt()` path)
**WHY:** "What is the tax-optimal path? Does this affect SSDI/IRMAA?"

| Component | Location |
|-----------|----------|
| Prompt | `scripts/process_watchlist_agent_jobs.py:497` |
| Tax sweep | `scripts/overnight_batch.py --tax-sweep` (6:35 AM cron) |
| Model | qwen3:14b (local, Claude for Roth) |

**Tax situation in prompt:** MFS, SSDI $45,600/yr, IRMAA threshold $103K, 22% ceiling $94,300, Golden Window 2036-2040, disability exemption (no 10% penalty).

---

### 8. Alex — Retirement & Disability Advisor

**WHO:** Senior retirement planner. The only high-quality reasoner. Gets the hard escalations.
**WHAT:** Disability-optimized retirement planning, Roth strategy, SSDI optimization.
**WHEN:** Daily 5AM scan + weekly Sunday + monthly + debate escalation + on-demand via Telegram `alex <SYMBOL>`.
**WHERE:** `scripts/alex_retirement_advisor.py` (dedicated, 1031 lines)
**WHY:** 48 disability rules, 3-tier decision hygiene, gov data scrapers. Claude-only.

| Component | Location |
|-----------|----------|
| Main script | `scripts/alex_retirement_advisor.py` (1031 lines) |
| Disability rules | `scripts/alex_retirement_advisor.py:31-137` — SSDI_RULES, DUAL_ELIGIBILITY, TRUST_RULES |
| 3-tier hygiene | `scripts/alex_hygiene.py` (290 lines) — Tier 1/2/3 multi-model |
| Gov scrapers | `scripts/alex_gov_research.py` (194 lines) — SSA, IRMAA, Medicaid NY, Roth IRS |
| Daily runner | `scripts/run_alex_daily.py` |
| Model | Claude Sonnet (always — no local fallback) |
| Gov data cache | `agent_intelligence_rules`: ssa_thresholds, irmaa_thresholds, medicaid_ny_rules, roth_ira_rules (all FRESH May 1) |

**Telegram access:** Direct — `alex <SYMBOL>`, `roth ladder`, `monthly report` (via `telegram_command_handler.py`)

**Injections (v7.6):** RAG (5 items), peer notes (Maria/Steph/Risk/Tax 30d), FRED macro, outcome lessons, cross-agent context via `agent_collab.get_agent_context()`.

#### Alex OpenClaw SOUL Summary
Full SOUL at `/home/johnclaw/.openclaw/agents/alex/agent/SOUL.md` (189 lines)

**Identity question:** "What is the retirement and disability-optimal path?"
**Non-negotiables:** IRMAA never breach ($103K), Medicaid lookback (>$50K dist), MFS implications, disability exemption, CPA disclaimer, income floor, 401k loan awareness.
**Golden Window mission:** Ages 68.5-73 (2036-2040) — every recommendation preserves this.
**Response format:** ~400 words prose. Situation -> retirement impact -> tax/SSDI -> 3-5 recs -> watch-for -> CPA note.
**3-tier hygiene:** Tier 1 (routine ~$0.01) / Tier 2 (Roth/IRMAA ~$0.03) / Tier 3 (critical ~$0.15).

---

### 9. Iris — Taxonomy Intelligence

**WHO:** Content classification agent.
**WHAT:** Manages tagging so the right content reaches the right agents. Gap detection, hygiene, library audit.
**WHEN:** Sunday 6AM (hygiene) + daily 7AM (library audit) + on-demand.
**WHERE:** `scripts/iris_taxonomy_agent.py` (dedicated, 1639 lines)
**WHY:** Without Iris, agents get noise instead of signal.

| Component | Location |
|-----------|----------|
| Main script | `scripts/iris_taxonomy_agent.py` (1639 lines) |
| System prompt | `scripts/iris_taxonomy_agent.py:73` — IRIS_SYSTEM_PROMPT |
| Model | Claude Sonnet |
| DB tables | `iris_taxonomy_proposals`, `iris_run_log`, `iris_hygiene_log`, `iris_hygiene_pending` |

**Telegram access:** Direct — `iris status`, `iris approve <id>`, `iris reject <id>`, `iris run`, `iris library` (via `telegram_command_handler.py`)

---

### 10. Social Scalp Scanner — Rules-Based

**WHO:** Rules-based scalp pipeline (no LLM).
**WHAT:** Social mentions → Finviz enrichment → 6-pillar scoring → tiered Telegram alerts.
**WHEN:** Pre-market every 30m (6-9:30 AM) + market hourly (10AM-4PM) M-F.
**WHERE:** `scripts/social_scalp_scanner.py` (dedicated)
**WHY:** Catch social momentum plays before market open.

| Grade | Score | Telegram Action |
|-------|-------|----------------|
| A+ | >=48 | Alert + Sonnet trade plan |
| GO | >=40 | Alert |
| WAIT | 30-39 | Soft notification ("watching, not acting") |
| AVOID | <30 | Stored only — dashboard visible, no alert |

**Sends alerts directly** via `send_telegram()` — no OpenClaw routing.

---

## Agent Interaction Map

### How the Two Layers Connect

```
OpenClaw (Telegram)                    Trade AI Backend
=====================                 ==================
Maria (PA)                            
  - manages Telegram                  
  - routes to Steph/Aegis             
                                      
Steph (Wealth Advisor) ←── reads ──── Steph (Allocation) backend agent
  - answers portfolio Qs              Maria (Research) backend agent
  - reads agent results               Risk Agent backend agent
  - reads holdings/performance        Tax Agent backend agent
                                      
Aegis (Intel) ←── reads ──────────── Aegis Core (overnight engine)
  - morning briefs                      aegis_portfolio_briefs
  - explains overnight findings         aegis_covered_call_candidates
  - escalates to Steph                  aegis_steph_escalations
                                      
                                      Alex (Retirement) ← escalation target
                                      Iris (Taxonomy) → feeds content routing
                                      Social Scalp → direct Telegram alerts
```

### Backend Agent Interaction (Escalation Ladder)

```
Event (SEC/RSI/FRED/Dividend)
  ↓
event_detector.py → agent_event_queue
  ↓
agent_event_router.py → watchlist_agent_jobs
  ↓
Maria (Research) + Risk Agent (parallel)
  ↓
If conflict → 3-agent debate (Maria + Steph + Risk)
  ↓ [agent_watchlist_engine.py:run_agent_debate()]
If consensus >=50% → auto-queue Alex
  ↓
Alex (Claude) → disability-aware allocation review
  ↓
watchlist_proposals → John approval (Telegram)
```

### Review Chain
```
Aegis Core findings → Steph (validation) → John (decision)
```

---

## Telegram Commands (via telegram_command_handler.py)

### Agent-Direct Commands
| Command | Routes To | What It Does |
|---------|-----------|-------------|
| `alex <SYMBOL>` | Alex backend | Full retirement analysis |
| `roth ladder` | Alex backend | 5-year Roth conversion ladder |
| `monthly report` | Alex backend | Monthly retirement report |
| `tax` | Tax backend | Current bracket, Roth room |
| `iris` / `iris status` / `iris approve` | Iris backend | Taxonomy intelligence |

### Cross-Agent Commands
| Command | What It Does |
|---------|-------------|
| `intel <SYMBOL>` | Recent intelligence from all backend agents |
| `conflicts` | Show agent disagreements |
| `status` | Full system: portfolio + income + tax + agents |
| `proposals` | Pending watchlist proposals (from backend agents) |
| `tasks` | Pending `john_decision_queue` tasks |
| `debates` | Recent agent debates |
| `approve/reject proposal <id>` | Act on proposal → `agent_feedback_log` |
| `approve/reject task <id>` | Act on task |

### Research Commands (LLM-routed)
| Command | What It Does |
|---------|-------------|
| `research <topic>` | Research with FRED + Alex intel injection |
| `analyze <symbol>` | Analyze with portfolio context |
| `run screener <name>` | Run named Finviz screener |

### Content Ingestion (Session 36)
| Command | What It Does |
|---------|-------------|
| `add video <URLs>` | Ingest YouTube videos — adds channel to tracking, fetches transcript, scores/tags |
| `add article <URLs>` | Ingest article URLs — fetches page, extracts text, scores/tags |
| (bare YouTube URLs) | Auto-detected → video ingestion |
| (bare article URLs) | Auto-detected → article ingestion |

Works from both Telegram (via `telegram_command_handler.py` poll whitelist) and OpenClaw (via `content-ingestion` skill in `~/.openclaw/skills/integrations/`). If YouTube IP-blocks the server, videos are queued in `youtube_ingest_queue` for automatic retry.

### Direct Telegram Alerts (no command — automatic)
| Source | What Gets Sent |
|--------|---------------|
| Social Scalp Scanner | GO/WAIT/A+ scalp alerts |
| Aegis Morning Brief | `aegis_morning_brief_delivery.py` at 8:05 AM |
| Smart Alerts | Roth reminders, income milestones, stop proximity, Medicare countdown |
| Agent Completion | Summary when 2+ agents finish a symbol |
| CIO Summary | Critical/high decisions needing review |

---

## OpenClaw Configuration

**Config file:** `backups/openclaw/openclaw.json`

| Setting | Value |
|---------|-------|
| Gateway port | 18789 |
| Gateway mode | local |
| Telegram enabled | true |
| Telegram DM policy | allowlist |
| Telegram allowed | `tg:780672608`, `tg:8797974247` |
| WhatsApp enabled | true |
| WhatsApp allowed | `+3473388380` |
| Default model | `ollama/qwen3:14b` |
| Fallback models | gpt-5.4-mini, claude-sonnet-4-6 |
| Memory search | enabled |

### OpenClaw Agent Registry (`openclaw.json` agents.list)
| Agent | ID | Workspace | Has SOUL |
|-------|----|-----------|----------|
| Maria | `main` | `/home/johnclaw/.openclaw/workspace` | Yes — SOUL.md + IDENTITY.md + AGENTS.md |
| Steph | `steph` | `/home/johnclaw/.openclaw/workspace-steph` | Yes — SOUL.md (82 lines) |
| Aegis | `aegis` | `/home/johnclaw/.openclaw/workspace-aegis` | Yes — SOUL.md (168 lines, detailed) |
| Alex | `alex` | `/home/johnclaw/.openclaw/workspace-alex` | Yes — SOUL.md (retirement/disability) |

### Backend Agent Registry (`config/agents.json`)
| Agent | ID | Domains | Routes To |
|-------|----|---------|-----------|
| Orchestrator | `orchestrator` | Ambiguous routing, multi-agent synthesis | (routes to all) |
| Maria Research | `maria_research` | ETF comparison, analyst ratings, news, sentiment | steph_allocation, tax_agent, risk_agent |
| Steph Allocation | `steph_allocation` | Allocation, account placement, position sizing | maria_research, tax_agent, risk_agent |
| Risk Agent | `risk_agent` | Stops, drawdowns, heat, technical damage | maria, steph, tax_agent |
| Tax Agent | `tax_agent` | Roth, tax drag, capital gains, asset location | maria, steph, risk_agent |
| Alex | `alex` | Retirement, SSDI, IRMAA, Golden Window, escalation | steph, tax_agent, risk_agent, maria |
| Iris | `iris` | Taxonomy, content gaps, hygiene, RAG QA | (feeds all agents) |
| Aegis Core | `aegis_core` | Overnight surveillance, stops, covered calls, rotation | steph, alex |
| Social Scalp | `social_scalp` | Social mentions, scalp scoring, pre-market momentum | steph |

### Agent Chain Definitions (`config/agent_runtime.json`)
| Chain | Agents | When Used |
|-------|--------|-----------|
| `portfolio_allocation` | maria_research → steph_allocation → risk → tax | Full allocation decision |
| `market_research` | maria_research | Research-only query |
| `stop_decision` | risk → maria_research | Stop honor/override |
| `tax_or_roth` | tax → steph_allocation | Tax/Roth question |
| `retirement_disability` | alex | SSDI/IRMAA/Medicare question |
| `roth_conversion` | tax → alex → steph_allocation | Roth conversion decision |
| `escalation` | maria_research → risk → steph_allocation → alex | Conflict resolution |
| `full_pipeline` | maria_research → steph_allocation → risk → tax → alex | Complete analysis |
| `taxonomy_intelligence` | iris | Content classification |
| `portfolio_surveillance` | aegis_core → steph_allocation | Overnight findings |
| `scalp_discovery` | social_scalp | Social momentum scan |

### High-Impact Rules (`config/agents.json`)
| Rule | Trigger | Reviewers |
|------|---------|-----------|
| `large_add` | add/buy ≥$10K | steph, maria, risk |
| `trim_core_position` | trim/sell V, SCHD, JEPI, FCNTX, SCHG | steph, tax, risk |
| `honor_or_override_stop` | stop decision | risk, maria |
| `roth_conversion` | any Roth convert/rollover | alex, tax, steph |
| `ssdi_irmaa_impact` | SSDI/IRMAA/MAGI/Medicaid action | alex, tax |
| `income_asset_sell` | sell/trim income strategy positions | steph, alex, risk |

### Escalation Rules (`config/agent_runtime.json`)
| Trigger | Chain | Escalates To |
|---------|-------|-------------|
| Agent conflict (BUY vs SELL 48h) | escalation | Alex (after 3-agent debate) |
| Roth conversion recommendation | roth_conversion | Human approval required |
| TRIM/SELL on income-critical | escalation | Alex with INCOME_CRITICAL flag |
| MAGI >$103K or distribution >$50K | retirement_disability | Human approval required |

---

## Cron Schedule (Agent-Related)

### Pre-Market (5:00-9:30 AM M-F)
| Time | Script | Purpose |
|------|--------|---------|
| 5:00 | `run_alex_daily.py --daily` | Alex daily scan |
| 5:30 | `overnight_batch.py --outcomes` | Outcome evaluation (learning loop) |
| 6:00-9:30 | `social_scalp_scanner.py` (30m) | Social scalp scanner |
| 6:15 | `agent_router_cron.sh full` | Full agent context refresh |
| 6:25 | `agent_intelligence_cron.sh daily` | Agent intelligence discovery |
| 6:35 | `overnight_batch.py --tax-sweep` | Tax agent sweep |
| 8:05 | `aegis_morning_brief_delivery.py` | Aegis morning brief → Telegram |

### Market Hours (10AM-7PM M-F)
| Time | Script | Purpose |
|------|--------|---------|
| Every 15m | `process_watchlist_agent_jobs.py --limit 10` | Process backend agent jobs |
| Every 15m | `event_detector.py` → `agent_event_router.py` | Event detection → agent routing |
| Hourly 10-4 | `social_scalp_scanner.py` | Social scalp (market hours) |
| 19:00 | `agent_watchlist_engine.py --daily` | Daily discovery + proposals |

### Evening (8PM-11PM M-F)
| Time | Script | Purpose |
|------|--------|---------|
| 20:00 | `overnight_batch.py --telegram` | Aegis Core overnight batch |
| Every 5m | `process_watchlist_agent_jobs.py --limit 25` | Clear job backlog |

### Weekend
| Time | Script | Purpose |
|------|--------|---------|
| Sun 6:00 | `iris_taxonomy_agent.py --hygiene` | Iris hygiene |
| Sun 8:00 | `run_alex_daily.py --weekly` | Alex weekly report |

---

## Database Tables (Agent-Related, 53 tables)

**Core:** `agent_skills`, `agent_intelligence_rules`, `agent_event_queue`, `agent_feedback_log`, `agent_handoffs`, `agent_debate_log`, `agent_performance_history`

**Watchlist:** `watchlist_agent_jobs`, `watchlist_agent_results`, `watchlist_analysis_maturity`, `watchlist_final_synthesis`, `watchlist_proposals`, `watchlist_escalation_policies`

**Aegis:** `aegis_portfolio_briefs`, `aegis_covered_call_candidates`, `aegis_rotation_candidates`, `aegis_steph_escalations`, `aegis_steph_resolution_history`, `aegis_symbol_snapshot_nightly`, `aegis_outcome_tracking`, `aegis_evidence_ledger`

**Iris:** `iris_taxonomy_proposals`, `iris_run_log`, `iris_hygiene_log`, `iris_hygiene_pending`

**Decision:** `john_decision_queue`, `john_decision_history`, `cio_decisions`, `decision_outcomes`

**Scalp:** `scalp_scan_results`

---

## API Endpoints (Agent Data)

| Endpoint | What |
|----------|------|
| `GET /api/v2/agents/summary` | Cross-agent activity |
| `GET /api/v2/agent-health` | Per-agent health |
| `GET /api/v2/agent-pipeline` | Live job pipeline |
| `GET /api/v2/alex/recent` | Alex analyses |
| `GET /api/v2/iris/status` | Iris coverage |
| `GET /api/v2/aegis/chat-context` | Unified Aegis context (for OpenClaw Aegis Chat) |
| `GET /api/v2/aegis/briefs` | Portfolio briefs |
| `GET /api/v2/aegis/covered-calls` | Covered-call candidates |
| `GET /api/v2/aegis/steph-escalations` | Steph escalation queue |
| `GET /api/v2/aegis/outcomes` | Outcome tracking |

---

*Agents Bible v1.2 — Backend agents renamed: maria_research, steph_allocation (eliminates OpenClaw naming collision). run_alex_daily.py verified (3 crons). agent_collab.py verified (3 functions). Alex SOUL.md written (189 lines — Golden Window, 7 non-negotiables, decision framework, 3-tier hygiene). Alex IDENTITY.md created. 4 OpenClaw agents + 9 backend agents registered. 11 chains, 6 high-impact rules, 4 escalation rules.*

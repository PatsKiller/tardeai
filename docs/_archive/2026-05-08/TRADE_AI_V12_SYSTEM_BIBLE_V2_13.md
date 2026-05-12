# Trade AI v12 System Bible v2.13

**April 28, 2026 | ms01-openclaw | v2.13 — Full Audit with Grok Active**

---

## Changes in v2.13

| Change | Status |
|--------|--------|
| Grok API activated and verified | **DONE** — all 4 LLM providers operational |
| Full system audit with live data | **DONE** |
| OpenClaw gateway documented | **DONE** |
| All agents assessed | **DONE** |

---

## LLM Router — All 4 Providers Active

| Provider | Status | Role | Cost/call |
|----------|--------|------|-----------|
| Local Ollama (qwen3:1.7b) | Available | Primary for routine tasks | $0.00 |
| **Grok (xAI)** | **AVAILABLE** | Preferred fallback for agent narratives | ~$0.0002 |
| Claude Sonnet | Available | High-impact CIO synthesis | ~$0.0013 |
| OpenAI GPT-4o | Available | Last resort | ~$0.0005 |

**Daily budget:** $0.08 spent of $2.00 cap. All providers tested and working.

---

## OpenClaw Setup

| Component | Status |
|-----------|--------|
| Gateway | **RUNNING** on port 18789 |
| Profiles | anthropic:default, openai:default, ollama:default, **xai:default** |
| Agent SOULs | Aegis (167 lines), Steph (81 lines) |
| Credential management | openclaw.json with 4 provider profiles |
| Integration with Trade AI | Agents route through OpenClaw gateway → Ollama/API |

**Trust: FUNCTIONAL** — gateway runs, profiles configured, but most agent work goes through the direct `llm_router.py` path rather than OpenClaw gateway.

---

## All Agents — Maturity Assessment

| Agent | Symbols | Results | LLM | Trust |
|-------|---------|---------|-----|-------|
| Maria (Research) | 19 | 19 | qwen3:1.7b | **FUNCTIONAL** — fundamentals/catalyst analysis, limited by 1.7B |
| Steph (Allocation) | 36 | 38 | qwen3:1.7b | **FUNCTIONAL** — account fit/income, most active agent |
| Risk (Technical) | 41 | 41 | qwen3:1.7b | **FUNCTIONAL** — covers all portfolio symbols |
| Tax | 1 | 1 | qwen3:1.7b | **MINIMAL** — only RTX analyzed |
| Full Chain | 0 real | 0 | — | **NOT USED** on real symbols |
| **Alex (Retirement)** | All portfolio | On-demand | **Claude** (high-impact) | **FUNCTIONAL** — tax-aware, IRMAA, Roth ladder, account-specific |
| Aegis (Overnight) | Portfolio | Briefs | qwen3:1.7b | **FUNCTIONAL** — morning briefs, stop monitoring |

### Agent Routing
```
Telegram command → telegram_command_handler.py
  "alex V" → Alex (Claude for high-impact)
  "research X" → LLM router (local → Grok → Claude)
  "roth ladder" → Alex Roth analysis (Claude)

Watchlist submit → watchlist_agent_jobs queue
  → process_watchlist_agent_jobs.py (every 15 min)
  → Routes to Maria/Steph/Risk/Tax based on escalation policy
  → When all required complete → auto-synthesis (Claude for CIO)
  → Safety engine → Decision QA → persist

Price alert fires → alert_event_writer.py
  → Creates agent jobs by strategy type
  → Alex can analyze via --scan-portfolio
```

---

## Telegram Integration

| Capability | Status |
|-----------|--------|
| **Output** (alerts → Telegram) | **VERIFIED** — 20+ send points, stop alerts, health, CIO summary |
| **Input** (commands from Telegram) | **FUNCTIONAL** — poll-based via telegram_command_handler.py |
| Commands | help, status, topics, research, find, analyze, alex, roth ladder, run screener |
| Persistent topics | **WORKING** — 6 active, daily iteration at 8 AM |
| Alex via Telegram | **WORKING** — `alex V` returns full retirement analysis |
| **WhatsApp** | **NOT INTEGRATED** — no WhatsApp bot exists |

---

## System URLs Master List

### Command Center Pages (27 routes, all 200)

| URL | Page |
|-----|------|
| /v2/ | Overview |
| /v2/hub | System Hub (master index) |
| /v2/portfolio | Holdings |
| /v2/watchlist | Watchlist Workbench |
| /v2/cio | CIO Dashboard |
| /v2/system-health | System Health + Screeners |
| /v2/risk | Risk Management |
| /v2/retirement | Retirement |
| /v2/dividends | Dividends |
| /v2/tax | Tax & Lots |
| /v2/returns | Returns |
| /v2/technical | Technical |
| /v2/research | Research |
| /v2/ai-analyst | AI Analyst |
| /v2/attribution | Attribution |
| /v2/correlation | Correlation |
| /v2/forecast | Forecast |
| /v2/rebalance | Rebalance |
| /v2/reports | Reports |
| /v2/actions | Action Center |
| /v2/approvals | Approvals |
| /v2/alerts | Alerts |
| /v2/ops | Ops |
| /v2/recovery | Recovery Watch |
| /v2/journal | Trade Journal |
| /v2/journal-analytics | Journal Analytics |
| /v2/morning-brief | Morning Brief |

### Key API Endpoints (30+)

| URL | Purpose |
|-----|---------|
| /api/v2/system-health | System status |
| /api/v2/llm/health | LLM router + budget |
| /api/v2/cost-dashboard | Spend tracking |
| /api/v2/finviz-screeners | 20 screeners |
| /api/v2/research-topics | 6 active topics |
| /api/v2/cio-dashboard | CIO summary |
| /api/v2/cio-decisions | All decisions |
| /api/v2/classifications | 55 classifications |
| /api/v2/income-dashboard | Income goals |
| /api/v2/signals/fused | Signal intelligence |
| /api/v2/watchlist/symbols | Deduped symbols |
| /api/v2/watchlist/research-card/{sym} | Full research card |
| /api/v2/strategy-rules/{sym} | Rule evaluation |
| /api/v2/portfolio-level-qa/latest | Portfolio QA |
| /api/v2/rebalance-plans/latest | Rebalance plan |
| /api/v2/marl/shadow-diagnostics | MARL status |

### Telegram Commands

| Command | Action |
|---------|--------|
| `alex V` | Retirement analysis for V |
| `roth ladder` | 5-year IRMAA-aware conversion projection |
| `research <topic>` | Save topic + LLM research |
| `find <what>` | Discovery + persist |
| `analyze <symbol>` | Symbol analysis |
| `run screener <name>` | Show Finviz screener URL |
| `topics` | List active research interests |
| `status` | System status |
| `help` | Command list |

---

## Maturity Assessment: 6.2 / 10

| Component | Score | Notes |
|-----------|-------|-------|
| Portfolio tracking | 9 | Real data, 4 accounts, 135K prices |
| Classification engine | 8 | 55 symbols, DB-backed |
| Strategy cards | 8 | Real market data |
| Income gap detection | 8 | FMP API dividends (29 symbols) |
| **Alex retirement advisor** | **7** | IRMAA, Roth ladder, tax-aware, Claude-powered |
| LLM router | 7 | 4 providers active, budget caps, logging |
| Agent analysis | 5 | 41 symbols but 1.7B quality for Maria/Steph/Risk |
| Synthesis | 5 | 22 actionable, safety gates work |
| CIO decisions | 5 | 16 non-routine, Claude for synthesis |
| Research topics | 5 | 6 active, daily iteration |
| Screener system | 5 | 20 screeners, runner built |
| Telegram | 5 | 9 commands, poll-based, output verified |
| Signal pipeline | 4 | Single batch, keyword catalyst/sentiment |
| OpenClaw | 4 | Gateway running, 4 profiles, limited direct use |
| Decision outcomes | 2 | 99% synthetic |
| MARL | 1 | Shadow only |
| Social | 0 | No data |
| WhatsApp | 0 | Not integrated |

---

## What Should John Trust Right Now?

| Category | Trust? | Why |
|----------|--------|-----|
| Portfolio value $1.2M | **Yes** | Real broker data |
| Income gap $40,658 | **Yes** | FMP API dividends |
| "Alex says trim 800 shares of SCHD from IRA" | **Read carefully** | Claude-powered, tax-aware, but verify with your CPA |
| "Roth ladder: convert $75K/yr" | **Directional trust** | IRMAA math is real, but verify thresholds with tax advisor |
| Safety blocks (SCHD, CSWC, PFLT) | **Yes** | Blocking logic is sound |
| 22 actionable recommendations | **With caution** | Pipeline works, LLM quality is the limit |
| Decision outcomes | **Ignore** | 99% synthetic |
| MARL | **Ignore** | Empty |

---

## Immediate Action Plan

1. **Grok key:** DONE (verified working, all 4 providers active)
2. **Verify cron tomorrow:** `ls -la logs/ | grep "Apr 29"` + `tail -20 logs/watchlist_agent_jobs.log`
3. **Try Alex:** `python3 scripts/alex_retirement_advisor.py --roth-ladder` or Telegram `alex V`
4. **Wait 3-7 days** for real decision outcomes
5. **GPU upgrade** when Arc Pro B50 arrives: `ollama pull qwen3:14b`

---

**v2.13 — Full audit with Grok active. 4 LLM providers, 6 agents, 27 UI pages, 30+ APIs, 9 Telegram commands, 20 screeners, IRMAA-aware Roth planning. Maturity: 6.2/10. Next jump: GPU + time.**

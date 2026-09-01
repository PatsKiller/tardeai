# Hermes Sidecar Strategy for Trade AI - Version 4

Status:      ACTIVE
as_of:       2026-05-29T22:39:06-04:00
Measured at: efcc51365 / not measured

**Document purpose:** Strategic design guide for integrating Hermes as a near-24/7 research, memory, and challenge layer for Trade AI.

**Design status:** Planning and architecture document. This is not an implementation approval and does not authorize trading, database mutation, broker activity, or model-routing changes.

**Core decision:** Trade AI remains the system of record and execution authority. Hermes becomes the research desk, second brain, durable memory layer, challenge reviewer, and strategy-learning system.

---

## 1. Executive Summary

Hermes should not be installed as the standalone Railway trading worker described in the original onboarding prompt. That pattern is useful for a new isolated trading bot, but Trade AI already has the proposal lifecycle, backtesting, journal, Command Center, ATM safety gates, local model routing, self-healing, and Drive-synced documentation.

Hermes should instead be integrated as a sidecar intelligence system:

```text
Trade AI = source of truth, proposal engine, execution governance, journal, backtesting, safety.
Hermes = research desk, second brain, challenge layer, long-term memory, experiment recommender.
Claude Code = implementation mechanic under explicit operator-approved prompts.
John = final approval authority for strategy, execution, DB changes, cron changes, and broker behavior.
```

Hermes should operate close to 24/7, but not by running heavy models continuously. It should use lightweight polling and routing during market hours, normal local analysis for daily work, and off-hours deep review for large research or monthly synthesis.

The v4 design expands Hermes from a trade-review agent into a full research organization that covers:

- Tickers
- News
- Related news
- YouTube transcripts
- Earnings transcripts
- Incubator and percolator ideas
- Proposals and missed opportunities
- All trades, paper and real
- Portfolio holdings and rotation
- Retirement accounts
- Tax lots and tax-loss watchlists
- Rebalance planning
- Internal tickets and system issues
- Dashboard truth and UI comprehension
- Data freshness and source credibility
- Strategy experiments and long-term lessons

Hermes must learn from history by recording every recommendation, every operator decision, and every later outcome.

---

## 2. Strategic Positioning

### 2.1 What Hermes Is

Hermes is the always-learning second brain for Trade AI. It reads, researches, remembers, challenges, and recommends.

Hermes should behave like a small analyst team that never forgets:

- A ticker analyst
- A news analyst
- A transcript analyst
- A proposal challenger
- A trade postmortem reviewer
- A portfolio rotation researcher
- A retirement and tax research assistant
- A systems analyst
- A memory librarian
- A chief coordinator

### 2.2 What Hermes Is Not

Hermes is not:

- A broker
- A trading bot
- A replacement for Trade AI
- An approval engine
- A proposal mutation engine
- A cron editor
- A database writer for core trading tables
- A second execution path
- A system allowed to bypass safety gates

### 2.3 Core Rule

Hermes may recommend. Trade AI and John decide.

---

## 3. Source Grounding and Current Trade AI Baseline

The current Trade AI platform already includes:

- 23 strategy definitions and a strategy playbook
- Agent capabilities and OpenClaw integration
- Research pages: Research Intelligence, Topic Monitor, Ticker Research, Intelligence Hub, Overnight Brief
- AI Analyst and CIO Dashboard
- Tax & Lots, Rebalance, and Retirement pages
- Proposal lifecycle inspector
- Execution-readiness endpoint
- Backtesting with source-aware run types
- LLM Review Coverage label clarity
- Complete backtest classification coverage
- ATM audit showing automated trading is working correctly but blocked when appropriate
- Human-in-the-loop execution and fail-closed safety principles

Hermes should use those existing capabilities, not duplicate them.

---

## 4. Operating Model

### 4.1 Trade AI Owns

- Proposal creation
- Proposal enrichment
- Proposal lifecycle state
- ATM approval logic
- Execution-readiness checks
- Broker and paper-trade adapters
- Journal records
- Backtesting database
- Trade LLM review records
- Stop management
- Risk gates
- Automated-trading safety
- Command Center UI
- System health monitoring
- Model routing policy
- Google Drive sync pipeline

### 4.2 Hermes Owns

- Research synthesis
- Ticker dossiers
- News and transcript reframing
- Incubator research
- Trade reflection
- Proposal challenge memos
- Missed-opportunity analysis
- Portfolio rotation research
- Retirement research
- Tax and lot research packets
- Strategy hypothesis generation
- Long-term memory and lessons
- Recommendation queue
- Daily/weekly/monthly advisory briefs

### 4.3 Claude Code Owns

- Code implementation
- Documentation updates
- Schema or config changes when approved
- Controlled validation
- Commits and Drive sync
- Rollback documentation

---

## 5. Hermes Safety Boundary

Hermes must never:

- Place orders
- Call broker submit endpoints
- Approve proposals
- Reject proposals
- Expire proposals
- Modify paper_trades
- Modify real trade records
- Modify journal rows
- Modify proposal lifecycle status
- Change `.env`
- Change cron
- Change model routing
- Change production strategy config directly
- Run arbitrary shell commands against production
- Create a second trading worker

Hermes may:

- Read from approved APIs, exports, docs, and snapshots
- Write advisory JSONL memory
- Write Markdown reports
- Write recommendation queue items
- Draft Claude Code implementation plans
- Flag missing evidence
- Ask for operator review
- Summarize and research

---

## 6. The Six Hermes Pods

The full v4 design groups Hermes into six pods. Pods make the system easier to operate than a flat list of agents.

| Pod | Purpose | Main Outputs |
|---|---|---|
| Research Intelligence Pod | Research tickers, news, transcripts, articles, and external narratives | Ticker dossiers, news scores, transcript briefs |
| Trade Lifecycle Pod | Review trades, proposals, open positions, missed opportunities, and thesis decay | Reflections, challenge memos, missed-opportunity reports |
| Portfolio Planning Pod | Research holdings, rotation, retirement, taxes, dividends, ETFs, and rebalancing | Rotation memos, tax-lot watchlists, retirement packets |
| Strategy and Experiment Pod | Turn lessons into scientific one-variable strategy experiments | Hypotheses, experiment backlog, regime reports |
| Operations and Governance Pod | Research internal issues, tickets, dashboards, freshness, and documentation gaps | Issue digests, freshness warnings, UI truth audits |
| Coordinator and Memory Pod | Orchestrate agents, schedule work, maintain memory, score recommendations | Daily brief, weekly review, memory index, outcome scoring |

---

## 7. Hermes Agent Roster v4

The target design is 24 logical Hermes agents. They can start as workflows in one sidecar and later split into scheduled services.

### 7.1 Agent 1 - Chief Hermes Coordinator

**Purpose:** Coordinate all Hermes agents and produce the operator-facing picture.

**Jobs:**

- Decide which agents run and when
- Prevent duplicate work
- Maintain daily/weekly/monthly schedules
- Route tasks to the right model tier
- Summarize agent findings
- Escalate urgent items
- Maintain the Hermes operating state

**Outputs:** Daily Hermes Brief, weekly review, monthly review, coordinator log, priority queue.

### 7.2 Agent 2 - Ticker Research Agent

**Purpose:** Build living ticker dossiers.

**Researches:** Fundamentals, technicals, analyst ratings, price targets, sector context, news, prior Trade AI history, prior rejected proposals, backtest evidence, current setup readiness.

**Outputs:** Ticker dossier, bull/bear case, catalyst score, risk score, missing evidence, next action.

### 7.3 Agent 3 - News Research Agent

**Purpose:** Classify and prioritize news.

**Researches:** News articles, related news, article age, source quality, repeated stories, ticker linkage, catalyst relevance.

**Outputs:** Actionable news, noise list, thesis-change alerts, ticker-linked summaries.

### 7.4 Agent 4 - YouTube and Transcript Research Agent

**Purpose:** Convert long-form video and transcripts into trade intelligence.

**Researches:** YouTube search results, YouTube transcripts, earnings transcripts, interviews, investor days, conference transcripts.

**Outputs:** Transcript brief, ticker implications, management tone, catalyst/risk extraction, follow-up questions.

### 7.5 Agent 5 - Research Reframer Agent

**Purpose:** Translate raw research into trade implications.

**Researches:** Articles, transcripts, analyst notes, tickets, internal notes.

**Outputs:** Why-this-matters summary, bull case, bear case, timing relevance, confidence score.

### 7.6 Agent 6 - Source Credibility Agent

**Purpose:** Score whether research can be trusted.

**Researches:** Source type, original reporting, recency, repeated content, source history, relevance to ticker.

**Outputs:** Source credibility score, stale-source warnings, duplicate-story warnings, confidence adjustment.

### 7.7 Agent 7 - Incubator Research Agent

**Purpose:** Review pre-trade ideas in the incubator and percolator.

**Researches:** Incubator names, percolator candidates, watchlists, topics, news, transcript findings, catalyst status, sector context.

**Outputs:** Promote / hold / drop / needs evidence, research completeness score, missing-data checklist.

### 7.8 Agent 8 - Proposal Challenge Agent

**Purpose:** Independently challenge Trade AI proposals before action.

**Researches:** Proposal enrichment, lifecycle inspector, ticker dossier, news, backtests, similar trades, risk state.

**Outputs:** support / wait / challenge / needs evidence / reject recommendation / operator review required.

### 7.9 Agent 9 - All-Trade Reflection Agent

**Purpose:** Review all trades across paper and real modes.

**Researches:** Closed trades, open-to-close lifecycle, journal, original proposal, news around entry/exit, stop behavior, MFE/MAE.

**Outputs:** setup score, exit score, stop score, mistake category, learning note, one-variable experiment candidate.

### 7.10 Agent 10 - Open Trade Watch Agent

**Purpose:** Monitor open positions for thesis deterioration or opportunity.

**Researches:** Holdings, open trades, stop alerts, latest news, analyst changes, sector movement, portfolio heat.

**Outputs:** hold / review / reduce / exit-watch recommendation, evidence summary, alert priority.

### 7.11 Agent 11 - Missed Opportunity Agent

**Purpose:** Learn from what Trade AI did not take.

**Researches:** Rejected proposals, expired proposals, missed proposals, incubator names not promoted, later price movement, later news.

**Outputs:** false-negative score, block reason, whether the block was correct, suggested gate test.

### 7.12 Agent 12 - Thesis Decay Agent

**Purpose:** Detect when an original thesis is weakening.

**Researches:** Original catalyst, latest news, analyst downgrades, sector weakness, price action, expired catalysts, negative articles.

**Outputs:** thesis intact / weakened / broken, evidence, recommended review urgency.

### 7.13 Agent 13 - Strategy Hypothesis Agent

**Purpose:** Generate scientific one-variable strategy experiments.

**Researches:** Trade reflections, missed opportunities, backtests, journal, strategy performance, prior experiments.

**Outputs:** current variable, proposed variable, evidence, expected impact, test plan, rollback criteria.

### 7.14 Agent 14 - Backtest and Journal Consistency Agent

**Purpose:** Check whether learning data is clean.

**Researches:** Backtest rows, trade LLM reviews, journal records, trade_transactions, proposal links, run_type labels.

**Outputs:** data-quality report, source mismatch report, review coverage warnings.

### 7.15 Agent 15 - Market Regime and Macro Research Agent

**Purpose:** Contextualize trades and ideas by regime.

**Researches:** indexes, VIX, sector ETFs, breadth, rates, macro calendar, risk regime, portfolio heat.

**Outputs:** regime label, strategy compatibility, macro warning, sector pressure report.

### 7.16 Agent 16 - Portfolio Rotation Research Agent

**Purpose:** Research holdings and possible rotation opportunities.

**Researches:** holdings, attribution, returns, dividends, analyst changes, sector rotation, correlation, forecast.

**Outputs:** rotation watchlist, hold/review/reduce notes, replacement candidates.

### 7.17 Agent 17 - Dividend and Income Research Agent

**Purpose:** Research dividend sustainability and income quality.

**Researches:** dividends, payout trends, ETF/fund income, AGNC-like income positions, dividend cuts, income gaps.

**Outputs:** dividend concern notes, income-quality score, replacement research list.

### 7.18 Agent 18 - Retirement Research Agent

**Purpose:** Research retirement-account holdings and long-term suitability.

**Researches:** IRA/401k holdings, ETFs, funds, long-term allocation, sector exposure, risk, income, retirement roadmap.

**Outputs:** retirement review, ETF/fund replacement candidates, risk concentration notes, long-term suitability questions.

### 7.19 Agent 19 - Tax and Lots Research Agent

**Purpose:** Prepare tax-lot and tax-planning research for operator/CPA review.

**Researches:** tax lots, realized/unrealized gains, holding periods, wash-sale indicators if available, dividends, account type.

**Outputs:** tax-loss watchlist, holding-period alerts, CPA question list, rebalance/tax impact notes.

**Important:** Hermes produces research only. It does not provide final tax advice.

### 7.20 Agent 20 - Rebalance Research Agent

**Purpose:** Research rebalancing opportunities and risks.

**Researches:** current allocation, target allocation, concentration, sector drift, tax impact, retirement suitability, portfolio heat.

**Outputs:** rebalance candidates, risk notes, income impact, tax-aware considerations.

### 7.21 Agent 21 - Internal Ticket and Issue Research Agent

**Purpose:** Research internal operational issues and tickets.

**Researches:** tickets, Telegram alerts, Claude Code reports, health-agent findings, failed jobs, unresolved TODOs.

**Outputs:** issue digest, recurring failure report, priority list, next-session task list.

### 7.22 Agent 22 - Data Freshness Critic

**Purpose:** Prevent stale data from driving bad conclusions.

**Researches:** freshness registry, pipeline timestamps, last successful runs, stale dashboards, missing enrichment.

**Outputs:** stale-data warnings, confidence downgrades, remediation suggestions.

### 7.23 Agent 23 - Dashboard Truth Auditor

**Purpose:** Review UI screenshots and labels for operator misunderstanding.

**Researches:** screenshots, Playwright crawls, page payloads, labels, warnings, counts.

**Outputs:** misleading-label warnings, UI comprehension issues, recommended clarity fixes.

### 7.24 Agent 24 - System Memory and Lessons Agent

**Purpose:** Maintain durable memory and outcome scoring.

**Researches:** all Hermes outputs, operator decisions, outcomes, Claude Code reports, session summaries, lessons learned.

**Outputs:** memory index, recommendation outcomes, do-not-repeat list, next-session memory notes.

---

## 8. Research Objects Hermes Should Maintain

### 8.1 Living Ticker Dossier

Each important ticker should have a persistent dossier:

```yaml
ticker: XYZ
last_updated: timestamp
current_status: incubator | proposal | open_trade | closed_trade | avoid | watch
thesis: text
bull_case: text
bear_case: text
latest_news: []
latest_transcripts: []
analyst_context: {}
sector_context: {}
trade_ai_history: []
proposal_history: []
backtest_context: []
open_questions: []
next_action: text
confidence: 0.0
```

### 8.2 Research Debt Record

Hermes should track what is missing:

- no recent news
- no transcript
- no analyst data
- no sector comparison
- no backtest sample
- no historical Trade AI history
- contradictory sources unresolved
- stale data
- weak catalyst

### 8.3 Reason-We-Did-Not-Trade Record

For promising ideas not traded:

- no catalyst
- stale quote
- bad market regime
- poor risk/reward
- missing enrichment
- operator skipped
- too late
- earnings risk
- portfolio heat

Hermes should later check whether that reason was correct.

### 8.4 Operator Decision Memory

Hermes should remember John’s decisions:

- approved
- rejected
- deferred
- requested more evidence
- overrode Hermes
- agreed with Hermes
- ignored recommendation

Later, Hermes checks outcomes and adapts.

### 8.5 Recommendation Queue

File-first implementation:

```text
data/hermes_memory/recommendation_queue.jsonl
```

Future DB table:

```text
hermes_recommendation_queue
```

Fields:

- recommendation_id
- agent_name
- symbol
- strategy
- source_type
- source_ids
- recommendation_type
- summary
- evidence
- confidence
- risk_level
- required_operator_action
- suggested_next_step
- expiration_time
- status
- outcome

---

## 9. Near-24/7 Operating Schedule

### 9.1 Lightweight Always-On Loop

Cadence: every 15-30 minutes.

Jobs:

- Check new news/articles/transcripts
- Check incubator changes
- Check proposal changes
- Check open trade alerts
- Check system alerts
- Update memory index
- Queue deeper research

Model: gemma3:4b for light summaries, gemma3:12b for moderate analysis.

### 9.2 Market Hours Loop

Jobs:

- Open trade watch
- Proposal challenge review
- News catalyst updates
- Ticker risk check
- Intraday issue detection
- Thesis decay detection

Model: gemma3:12b, fallback gemma3:4b.

### 9.3 After-Close Loop

Jobs:

- All-trade reflection
- Proposal outcome review
- Missed opportunity review
- Journal/backtest comparison
- Daily Hermes Brief

Model: gemma3:12b.

### 9.4 Overnight Deep Loop

Jobs:

- YouTube transcript analysis
- Long article synthesis
- Incubator deep review
- Retirement/portfolio research
- Tax-lot watchlist generation
- Strategy hypothesis generation

Model: Gemma4 31B via llama.cpp for selected batches; fallback to gemma3:12b.

### 9.5 Weekly Loop

Jobs:

- Portfolio rotation review
- Retirement review
- Tax/rebalance watchlist
- Strategy lessons
- Missed opportunity review
- Top research findings

### 9.6 Monthly Loop

Jobs:

- CIO-style review
- Strategy promotion/demotion
- Research pipeline review
- Tax and lot planning watchlist
- Retirement suitability review
- Model performance review
- Hermes recommendation outcome review

---

## 10. Model Routing Strategy

Hermes should be model-router aware. It should request an analysis tier; the Trade AI model policy should decide the actual engine.

| Workload | Preferred Model |
|---|---|
| short summaries | gemma3:4b |
| normal ticker research | gemma3:12b |
| proposal challenge | gemma3:12b |
| trade reflection | gemma3:12b |
| incubator research | gemma3:12b |
| transcript synthesis | gemma3:12b or Gemma4 31B off-hours |
| weekly/monthly deep review | Gemma4 31B via llama.cpp |
| external narrative challenge | optional xAI/Grok later |

Disabled / not production:

- qwen3:14b
- Gemma4 e2b/e4b
- gemma3:27b GPU

### 10.1 Grok / xAI Position

Grok/xAI should not be the default Hermes brain.

It can be added later as an External Challenger Agent for:

- broad market narrative
- social/X-aware sentiment
- outside-view macro review
- high-value ticker challenge
- weekly/monthly alternative perspective

Controls:

- secrets in vault or `.env`
- no hardcoded keys
- cost limits
- rate limits
- sanitized prompts
- no broker credentials
- no account numbers
- advisory output only

---

## 11. Command Center Integration

Hermes should eventually be visible in:

- AI Analyst
- CIO Dashboard
- Research Intelligence
- Topic Monitor
- Ticker Research
- Intelligence Hub
- Incubator
- Strategy Desk
- Proposal Lifecycle Inspector
- Journal Reports
- Backtesting
- Tax & Lots
- Rebalance
- Retirement
- System Health
- Agent Pipeline

Suggested UI cards:

- Hermes Daily Brief
- Hermes Research Queue
- Hermes Ticker Dossiers
- Hermes Incubator Watch
- Hermes News Reframes
- Hermes Transcript Findings
- Hermes Trade Lessons
- Hermes Missed Opportunities
- Hermes Strategy Hypotheses
- Hermes Portfolio Rotation
- Hermes Retirement Watch
- Hermes Tax/Lot Watch
- Hermes Internal Issues
- Hermes Memory Outcomes

---

## 12. First Build Target

The first build should be read-only and research-first.

### 12.1 Phase 1 Agents

Start with five:

1. Chief Hermes Coordinator
2. Ticker Research Agent
3. News Research Agent
4. Incubator Research Agent
5. All-Trade Reflection Agent

### 12.2 Phase 1 Inputs

- latest 25 closed trades across all modes
- current open trades
- current incubator items
- latest 50 news articles
- latest related news
- latest YouTube transcripts if available
- latest rejected/expired proposals
- latest missed proposals
- latest portfolio holdings
- latest retirement holdings
- latest tax/rebalance watchlist
- latest internal tickets

### 12.3 Phase 1 Outputs

- Daily Hermes Research Brief
- Top ticker risks/opportunities
- Top incubator promotion/drop candidates
- Top trade lessons
- Top missed opportunities
- One one-variable strategy hypothesis
- Research debt list
- Memory files written
- No DB writes
- No proposal mutations
- No execution actions

---

## 13. Execution Plan Preview

### Step 1 - Hermes Compatibility Audit

Before installation:

- Verify whether Hermes is already installed
- Determine how Hermes stores memory
- Determine whether Hermes can use local models
- Determine whether Hermes calls external APIs by default
- Determine whether Hermes can run project-scoped
- Determine whether Hermes can be sandboxed
- Determine whether Hermes supports multiple agents/workflows
- Determine whether it conflicts with Claude Code
- Determine install/rollback behavior

No install without approval.

### Step 2 - Sidecar Directory Skeleton

Create:

```text
docs/hermes/
data/hermes_memory/
logs/hermes/
config/hermes/
```

### Step 3 - Read-Only Connectors

Build exports or read-only API pulls for:

- trades
- proposals
- incubator
- research
- news
- transcripts
- backtests
- journal
- risk
- portfolio
- tax lots
- retirement
- system tickets

### Step 4 - First Manual Hermes Run

Run the five Phase 1 agents manually.

### Step 5 - Operator Review

Review:

- source accuracy
- hallucinations
- usefulness
- missing context
- actionability
- memory quality

### Step 6 - Add Schedule

Only after useful output:

- 15-30 minute lightweight polling
- after-close daily report
- overnight deep research
- weekly/monthly reports

### Step 7 - Add Command Center Cards

Expose outputs in UI.

### Step 8 - Add External Challenger

Add xAI/Grok only after local Hermes memory loop is proven.

---

## 14. Success Metrics

Hermes is successful if it:

- Finds missed risks before they damage trades
- Finds missed opportunities Trade AI skipped
- Produces useful ticker dossiers
- Improves incubator research quality
- Reduces repeated mistakes
- Produces measurable strategy hypotheses
- Tracks whether its own recommendations worked
- Avoids hallucinated source IDs
- Does not mutate trading state
- Does not create duplicate execution paths
- Improves John’s decision speed and confidence

---

## 15. Final v4 Recommendation

Build Hermes as a near-24/7 research, memory, and challenge sidecar for Trade AI.

Use the six-pod structure and 24 logical agents as the target design.

Start with five agents and file-based memory.

Use local LLMs first.

Use Gemma4 31B only for off-hours deep research.

Add Grok/xAI later only as an external challenger.

Keep Trade AI as the only execution authority.

Make Hermes self-learning by recording every recommendation, John’s decision, and the later outcome.

The first real implementation task should be a Hermes compatibility audit and sidecar install plan, not installation.

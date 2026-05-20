# ATP-1B — Target Scheduler Design

## Current vs Target

### Currently Installed (sufficient)

| Time ET | Script | Session | Proposal? |
|---------|--------|---------|-----------|
| 07:00-17:00 hourly | incubator_proposal_promoter.py | market | Yes |
| 07:00,08:00,10:00,12:00,14:00,16:00,18:00 | finviz_screener_runner.py | all-day | No |
| 12:00,14:00,16:00 | trade_ai_orchestrator.py | market | Yes (auto_proposals) |
| 17:30 | trade_ai_orchestrator.py --allow-underfilled | after_close | No (narrow) |
| 17:30 | afterhours_candidate_preparation.sh | after_close | No (snapshot) |
| 09:00-15:00 every 5m | quote_refresh | market | No |
| 09:00-16:00 every 5m | paper_execution_sweep.py | market | Executes approved |
| 16:30 | closed_trade_digest | after_close | No |
| 20:00 | overnight_batch.py | overnight | No |
| 23:00 | deep_overnight_llm_window.sh | overnight | No |

### Gaps Identified (future phases)

| Time ET | Missing Job | Purpose | Phase |
|---------|-------------|---------|-------|
| 16:15 | EOD price/volume snapshot | Capture close data | ATP-2 |
| 20:00 | strategy-fit + route audit refresh | Re-evaluate after full close data | ATP-2 |
| 22:00 | technical/Fib/ORB context enrichment | Prepare candidate list | ATP-2 |
| 00:30 | watchpool aging/TTL check | Remove expired | ATP-2 |
| 02:00 | news/catalyst delta scan | Overnight catalyst changes | ATP-2 |
| 04:00 | premarket gap/volume scan | Early movers | ATP-2 |
| 09:20 | pre-open readiness check | Final readiness validation | ATP-2 |
| Every 30m market hours | proposal revalidation | Quote drift, R:R, spread | ATP-2 |

### Current Coverage Assessment

**Adequate for paper-trading phase:**
- 7 FinViz screener runs/day cover full universe
- Hourly promoter evaluates incubator candidates
- After-hours readiness snapshot covers 1,311 symbols
- Quote refresh runs every 5 minutes during market hours
- Deep overnight LLM processing handles research backlog

**Not yet needed until live-trading approach:**
- 30-minute proposal revalidation
- Pre-open readiness gate
- Dedicated premarket gap scanner
- EOD technical context enrichment

## Data Provider Rules

| Provider | Research mode | Execution mode |
|----------|-------------|----------------|
| FinViz | Yes - any time | No |
| yfinance | Yes - any time | No |
| News/RSS | Yes - any time | No |
| Alpaca | Yes - market hours | Yes - required for approval |
| Polygon | Yes - any time | Yes - required for approval |

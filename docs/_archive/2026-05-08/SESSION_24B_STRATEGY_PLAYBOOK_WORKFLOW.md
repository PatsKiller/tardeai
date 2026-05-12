# Session 24B: Strategy Playbook Workflow

## Architecture

```
docs/project/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md   <- Human doctrine
config/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md          <- Prompt reference copy
config/strategies/*.yaml (20 files)                <- Machine-readable rules
config/strategies/shared_risk_rules.yaml           <- Global risk policy
config/strategies/strategy_schema.yaml             <- Validation schema
    |
    v
scripts/strategy_config_loader.py                  <- YAML loader + validator + DB syncer
    |
    v
strategy_config_versions (DB)                      <- Immutable version history
strategy_registry (DB)                             <- Live state + config_hash
strategy_prompt_context_cache (DB)                 <- Cached LLM prompt blocks
    |
    v
scripts/multi_setup_router.py                      <- Evaluate symbol against all 20 strategies
    |
    v
strategy_setup_matches (DB)                        <- Per-symbol multi-strategy match history
    |
    v
paper_trade_proposals.setup_stack                  <- Primary + secondary strategies on proposal
paper_trade_proposals.primary_strategy_id
paper_trade_proposals.secondary_strategy_ids
    |
    v
Agent prompts (Maria/Risk/Steph)                   <- Strategy context injected
qwen3:14b proposal analysis                        <- Strategy criteria in LLM prompt
```

## Daily Workflow

### Morning (6:00-7:00 AM ET)
1. Trade AI orchestrator runs scans
2. `auto_proposal_generator.py` creates proposals with strategy-aware expiry
3. `proposal_enrichment_loop.py` enriches proposals
4. `multi_setup_router.py --pending-proposals --apply` evaluates setup stacks
5. Agent jobs queued with strategy context from YAML

### Market Hours (9:30 AM - 4:00 PM ET)
1. `proposal_monitor.py` checks lifecycle (entry zone, price drift)
2. `proposal_execution_readiness.py` checks quote/spread/volume
3. User reviews proposals on `/v2/paper-proposals` with:
   - Lifecycle bar (ENTRY_ZONE_VALID / ENTRY_MISSED)
   - Strategy tab (setup stack, criteria met/failed)
   - Execution tab (quote provider, bracket dry-run)

### After-Hours (4:30 PM - 6:30 AM ET)
1. `proposal_monitor.py` checks overnight proposals (4:30 PM, 6 PM, 6 AM, 6:30 AM)
2. `alpaca_paper_reconciler.py` reconciles positions (4:15 PM)
3. `paper_execution_quality_analyzer.py` analyzes fills (4:30 PM)
4. `paper_performance_governance.py` calculates governance (1st of month)

### Monthly
1. Governance calculator aggregates per-strategy performance
2. Live Governance page shows validation gate progress
3. Human reviews governance dashboard

## YAML-to-DB Sync

```bash
# Validate all 20 strategy YAMLs
.venv/bin/python scripts/strategy_config_loader.py --validate

# Sync to DB (updates strategy_config_versions + strategy_registry + prompt_context_cache)
.venv/bin/python scripts/strategy_config_loader.py --sync-db

# View prompt context for a strategy
.venv/bin/python scripts/strategy_config_loader.py --strategy swing_breakout --print-prompt-context

# Route a symbol through all strategies
.venv/bin/python scripts/multi_setup_router.py --symbol SMX --dry-run

# Route all pending proposals
.venv/bin/python scripts/multi_setup_router.py --pending-proposals --apply
```

## UI Pages

| Page | Route | Purpose |
|------|-------|---------|
| Paper Proposals | `/v2/paper-proposals` | Proposal cards with lifecycle bar, setup stack tab |
| Strategy Admin | `/v2/strategy-admin` | All 20 strategies with config viewer, validate/sync controls |
| Live Governance | `/v2/live-governance` | Governance dashboard with validation gates checklist |
| Execution Quality | `/v2/execution-quality` | TCA dashboard with fill quality analysis |
| Broker Reconciliation | `/v2/broker-reconciliation` | Alpaca position/order reconciliation |
| Paper Outcomes | `/v2/paper-outcomes` | Thesis outcomes, lifecycle events, governance by strategy |

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/v2/strategy-configs` | All 20 strategy configs with metadata |
| GET | `/api/v2/strategy-configs/<id>` | Full config + prompt context for one strategy |
| GET | `/api/v2/strategy-setup-matches` | Multi-setup match history |
| POST | `/api/v2/strategy-configs/validate` | Validate all YAMLs |
| POST | `/api/v2/strategy-configs/sync-db` | Sync YAML to DB |

## Rules Hierarchy

```
YAML files = source of truth for thresholds and criteria
    Thresholds, entry criteria, disqualifiers, risk limits, expiry windows
    Version-controlled in Git, diffable, auditable

Database = live operational state
    Strategy status (enabled/paused/killed)
    Validation state (paper trades, win rate, PF)
    Config hash (tracks which YAML version is active)
    Setup match history

Code = deterministic enforcement
    risk_gate.py enforces hard blocks
    proposal_lifecycle.py enforces expiry
    execution readiness enforces quote/spread/volume

LLM = explanation and critique only
    qwen3:14b sees strategy context in prompt
    Agents see YAML rules + their specific role
    LLMs cannot override risk gates, thresholds, or live trading controls
```

## Live Trading Path

Live trading remains DISABLED. The path to enablement requires:

1. 30+ closed paper trades per strategy
2. 55%+ win rate
3. Profit factor >= 1.3
4. Max drawdown < 25%
5. 6 calendar months of paper data
6. Agent calibration >= 60%
7. Broker reconciliation clean
8. TCA slippage acceptable
9. Human governance review and approval

Current status: PAPER_ONLY for all 20 strategies.

## Session 24C: Execution Gate Enforcement

### Gap Fixed
Pre-24C, RSI/ATR/EMA/VWAP/Fib/R:R were display-only. The system would submit a paper order
for a proposal with RSI 95, bearish EMA, and 1:1 R:R if the quote was fresh.

### New Hard Blocks (6 added, total now 16)
- BLOCKED_BEARISH_EMA: bearish/long-term overhead blocks long entries
- BLOCKED_RSI_OVERBOUGHT: RSI above strategy threshold (85 scalp, 90 swing, 95 position)
- BLOCKED_EXTENDED_ABOVE_VWAP: VWAP above strategy threshold (10% scalp, 15% swing, 25% position)
- BLOCKED_ORB_FAILED: failed opening range breakout blocks momentum_scalp
- BLOCKED_TARGET_UNREALISTIC: target > 3x ATR
- BLOCKED_RR_TOO_LOW: R:R < 1.5

### Strategy-Aware Thresholds
| Threshold | Intraday | Short Swing | Medium Swing | Position |
|-----------|----------|-------------|-------------|----------|
| Max price drift | 2% | 5% | 8% | 12% |
| Max spread | 1% | 3% | 3% | 5% |
| Max quote age | 300s | 24h | 24h | 24h |
| RSI block above | 85 | 90 | 90 | 95 |
| VWAP block above | 10% | 15% | 20% | 25% |
| Min volume | 100K | 50K | 50K | 25K |

### R:R Calculation Fix
Target multiplier changed from 1.5x ATR to 2.0x ATR. All proposals updated to 2:1 minimum.

### Data Trace Documentation
See: `docs/project/TRADE_AI_EXECUTION_GATE_ARCHITECTURE.md`
Complete signal-to-decision trace with every field mapped to enforcement tier.

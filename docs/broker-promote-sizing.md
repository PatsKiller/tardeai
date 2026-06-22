# Broker Promote: Sizing + AI Oversight (paper → Schwab/Fidelity)

**Status:** LIVE as of 2026-06-22.

## Problem

Paper proposals are sized against `alpaca_paper` policy (e.g. 5% risk / 20% position on ~$100k equity). Promoting to Schwab copied those shares without re-running sizing for the destination account — producing 10× oversized live trades. There was also no Grok/ChatGPT or agent-review gate on broker save.

## Solution (two layers)

### 1. Deterministic sizing (`broker_promote_sizing.py`)

1. **Re-size** via `account_policy.compute_sizing()` for the **destination** account
2. **Clamp** with strategy `live_trade_rules` (`max_position_size`, `max_dollar_risk`)
3. **Cash-based sizing (live)** — Schwab/Fidelity risk% and position% apply to **cash**, not equity
4. **Cash cap** — notional cannot exceed available `cash` or `buying_power`
5. **Daily activity** — open trades + new today vs `max_new_positions_per_day` / `max_concurrent_positions`
6. **Market validation** — `validate_paper_proposal_live_market()` → PASS / WARN / BLOCK
7. **Hard block** on save if any gate fails

### 2. AI oversight (`broker_promote_oversight.py`)

Before broker save, merged into the same PASS / WARN / BLOCK status:

| Check | BLOCK | WARN |
|-------|-------|------|
| Maria / Risk / Steph agent reviews | Still **pending** | Agent **REJECT** / **CAUTIOUS** / **WAIT_FOR_DATA** |
| Agent vote | **BLOCK** | — |
| Grok + ChatGPT cloud review (`cloud_review.py`) | Consensus **DISAGREE** | **CAUTION** or not run (lanes available) |
| Local LLM decision packet (`paper_proposal_analysis`) | — | Missing or still **queued** |

**Models involved:**

- **Local agents + narrative:** Ollama `gemma3:4b` via `proposal_agent_review.py`, `proposal_intelligence_analyzer.py`, `process_watchlist_agent_jobs.py`
- **Cloud second opinion:** Grok (`:8645`) + ChatGPT (`:8646`) OAuth proxies via `llm_lane` / `cloud_review.py` — advisory lanes that **can block** when consensus is DISAGREE

Cloud review is cached 24h in `llm_feedback_observations` (`workflow=broker_cloud_oversight`).

**Env toggles:**

| Variable | Default | Effect |
|----------|---------|--------|
| `BROKER_REQUIRE_CLOUD_OVERSIGHT` | `0` | `1` = BLOCK if Grok+ChatGPT not run |
| `BROKER_CLOUD_OVERSIGHT_CACHE_HOURS` | `24` | Reuse cached cloud verdict |

## Account policies

| Account | Risk/trade | Max position | Daily pause |
|---------|------------|--------------|-------------|
| `alpaca_paper` | 5% equity | 20% equity | 2.5% |
| `schwab_*` (seeded) | 0.5% **cash** | 3% **cash** | 2% |
| Fallback (no policy) | $150 | $2,000 | — |

Seed live policies:

```bash
python scripts/migrate_schwab_live_policies.py
```

Tune per account in **ATM Controls** (v3 admin modal).

## Strategy live rules (`momentum_scalp`)

| Cap | Value |
|-----|-------|
| `max_position_size` | $2,000 |
| `max_dollar_risk` | $200 |

These are absolute ceilings applied on top of account policy.

## Execution tolerance

From `validate_paper_proposal_live_market()`:

| Check | WARN | BLOCK |
|-------|------|-------|
| Entry drift | >1.5% | >3.0% |
| Spread | — | >1.5% |
| R:R at live price | — | <1.2:1 |
| Quote age | — | >15 min |

Example: CRMT proposed $3.01, fill $3.06 → **WARN** (1.66% drift), R:R 1.25:1 — allowed. Above ~$3.08 ask → **BLOCK** (R:R < 1.2).

## API

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v2/broker-proposals/prepare-promote` | Load modal; sizing + intel + oversight |
| `POST /api/v2/broker-proposals/evaluate-promote` | Live re-check (sizing + market + oversight) |
| `POST /api/v2/broker-proposals/oversight` | AI oversight snapshot only |
| `POST /api/v2/broker-proposals/queue-oversight` | Queue local agents + gemma LLM for proposal |
| `POST /api/v2/broker-proposals/run-cloud-oversight` | Run Grok+ChatGPT second opinion (~2 min) |
| `POST /api/v2/broker-proposals/promote-from-paper` | Save — blocked server-side if any gate fails |

### evaluate-promote body

```json
{
  "proposal_id": 282,
  "account": "schwab_taxable",
  "shares": 664,
  "entry": 3.01,
  "stop": 2.86,
  "target": 3.31
}
```

Response `data.status`: `PASS` | `WARN` | `BLOCK` (worst of sizing + oversight).

Response `data.oversight`: agent reviews, local LLM status, cloud verdict, violations/warnings.

## Decision context (intel)

`broker_proposal_intel.get_intel_packet()` attaches to prepare-promote and broker queue cards:

- Company description, sector, catalyst (+ critic verdict)
- Technicals (RSI, RVOL, gap, ATR, confluence)
- Analyst consensus (Yahoo targets)
- Why purchase (approve case / strategy purpose)
- Agent reviews with model name
- AI oversight status + cloud consensus

UI: `BrokerIntelPanel.tsx` (queue cards + promote modal).

## Account selection (modal)

When you pick a destination account the modal shows:

| Field | Source |
|-------|--------|
| Cash (sizing base) | Schwab `cashBalance` / buying power |
| Equity | Account liquidation value |
| Open trades | `paper_trades` status=open for account |
| New today | Trades opened today + proposals queued today vs max/day |

Shares **auto-resize** to the cash-based cap when the account changes (unless you manually edit shares).

## UI

**Broker Promote Modal** (`BrokerPromoteModal.tsx`):

- Decision context + **AI oversight** panel
- **Queue local reviews** / **Run Grok+ChatGPT** buttons
- Account dropdown shows cash + `X/Y today` per account
- PASS/WARN/BLOCK badge + separate **AI** badge
- Max shares + binding cap (risk / position / cash)
- Paper original vs broker-resized warning
- Save disabled on BLOCK (sizing or oversight)
- **Apply max shares** one-click cap

## Unblocking a proposal (example CRMT #282)

1. Paper tab → **AI Review** (or modal → **Queue local reviews**)
2. Wait for Maria / Risk / Steph to complete (`proposal_agent_reviews.status=reviewed`)
3. Modal → **Run Grok+ChatGPT**
4. Re-open modal — oversight should be PASS or WARN (not BLOCK)

## CRMT corrected trade

| Field | Wrong (paper) | Correct (broker) |
|-------|---------------|------------------|
| Shares | 6,760 | **664** |
| Investment | ~$20,347 | **~$1,999** |
| Max risk | ~$1,014 | **~$100** |

## Files

| File | Role |
|------|------|
| `scripts/broker_promote_sizing.py` | Sizing + market evaluation |
| `scripts/broker_promote_oversight.py` | Agent + cloud AI gates |
| `scripts/broker_proposal_intel.py` | Decision context packet |
| `scripts/account_policy.py` | `cash_for_account()`, cash cap in `compute_sizing()` |
| `scripts/paper_trade_logger.py` | `promote_proposal_to_broker()` enforcement |
| `scripts/cloud_review.py` | Grok+ChatGPT second opinion (shared) |
| `scripts/api_v2.py` | prepare / evaluate / oversight / promote endpoints |
| `scripts/migrate_schwab_live_policies.py` | DB seed for Schwab policies |
| `apps/.../BrokerPromoteModal.tsx` | Send-to-broker modal |
| `apps/.../BrokerIntelPanel.tsx` | Intel + oversight UI |
| `tests/test_broker_promote_sizing.py` | Sizing unit tests |
| `tests/test_broker_promote_oversight.py` | Oversight unit tests |
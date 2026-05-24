# TRADE AI v12 — STRATEGY PLAYBOOK v1.0
# Complete documentation of all 20 strategies, rules, risk, co-enablement
# and agent/LLM visibility
# John W. Whiting | May 2026
#
# ═══════════════════════════════════════════════════════════════════════
# HOW TO USE THIS DOCUMENT
# ═══════════════════════════════════════════════════════════════════════
#
# This is the canonical strategy reference for Trade AI v12.
# Every agent (Maria, Steph, Risk, Alex, Aegis) and every LLM call
# should reference this document when making decisions.
#
# To save this to the system and ensure agents can see it:
#   cp TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md \
#      /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/docs/project/
#   cp TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md \
#      /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/
#
# Then update agent prompts to reference:
#   config/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md
# ═══════════════════════════════════════════════════════════════════════

---

## SECTION 1: THE 20 STRATEGIES AT A GLANCE

| # | Strategy | Timeframe | Accounts | Status | Risk/Trade | Avg Hold | R:R Target |
|---|---|---|---|---|---|---|---|
| 1 | Momentum Scalp | Intraday | Taxable only | TESTING | $150–$200 | <4 hours | 2:1 min |
| 2 | Gap and Go | Intraday | Taxable only | UNVALIDATED | $150–$200 | <3 hours | 2:1 min |
| 3 | Earnings Catalyst | 1–5 days | Taxable, IRA | UNVALIDATED | $200–$300 | 2–3 days | 2.5:1 |
| 4 | Swing Breakout | 3–21 days | Taxable, IRA | UNVALIDATED | $200–$300 | 5–10 days | 2:1 |
| 5 | Swing Trade | 3–21 days | Taxable, IRA | UNVALIDATED | $200–$300 | 7–14 days | 2:1 |
| 6 | Speculative Growth | 3–21 days | Taxable, Roth | UNVALIDATED | $150–$250 | 5–15 days | 3:1 |
| 7 | Sector Rotation | 2–8 weeks | All accounts | UNVALIDATED | $300–$500 | 2–4 weeks | 2:1 |
| 8 | Income Position Add | Position long | IRA, Roth, Taxable | TESTING | $300–$500 | Months–Years | Income yield |
| 9 | Core Growth Compounder | Position long | All accounts | UNVALIDATED | $300–$500 | Years | 3:1+ long-term |
| 10 | Core Index Fund | Position long | All accounts | UNVALIDATED | $300–$500 | Years | Market return |
| 11 | Covered Call Income | Position long | IRA, Taxable | UNVALIDATED | $200–$400 | Ongoing | Monthly premium |
| 12 | Defense / Aerospace Thesis | Position long | All accounts | UNVALIDATED | $300–$500 | 6–24 months | 2:1 |
| 13 | Dividend Growth Compounder | Position long | IRA, Roth, Taxable | UNVALIDATED | $300–$500 | Years | Yield + growth |
| 14 | High Yield Income (BDC) | Position long | IRA only | UNVALIDATED | $200–$400 | Ongoing | 10–15% yield |
| 15 | International Dividend | Position long | IRA, Roth | UNVALIDATED | $200–$400 | Years | Yield + FX |
| 16 | Recovery Watch | Position long | All accounts | UNVALIDATED | $150–$300 | 3–12 months | 3:1 |
| 17 | REIT Income | Position long | IRA, Roth | UNVALIDATED | $200–$400 | Years | 5–8% yield |
| 18 | Bond Income | Position long | IRA, Roth | UNVALIDATED | $200–$400 | Ongoing | 4–6% yield |
| 19 | Tax Loss Harvest | 1–7 days | Taxable only | UNVALIDATED | $150–$300 | 1–7 days | Tax offset |
| 20 | Cash / Stable | Position long | All accounts | UNVALIDATED | N/A | Ongoing | Capital preservation |

**Validation gate:** 30 paper trades + ≥55% win rate + Profit Factor ≥1.3 before any live trading.
**Live trading status:** DISABLED for all strategies. LIVE_TRADING_ENABLED=false.

---

## SECTION 2: DETAILED STRATEGY PLAYBOOKS

---

### STRATEGY 1 — MOMENTUM SCALP
**Status:** TESTING | **Account:** Taxable only (Fidelity cash)

**The Edge:**
Micro-cap stocks with catalysts and float compression can move 10–40% in a single session.
Institutional players cannot trade these without moving the market. Retail can enter and exit quickly
before the move fades. The edge is speed + catalyst verification.

**Universe:**
- Price: $1–$25
- Float: ≤100M shares
- RVOL: ≥5x (minimum), prefer 8x+
- Gap: ≥5% (minimum at open)
- Market cap: typically $50M–$500M

**Entry Criteria (ALL required):**
1. Catalyst verified (earnings beat, FDA approval, contract win, M&A) — not social-only
2. RVOL ≥5x confirmed by 9:45am
3. Price above VWAP at entry
4. EMA alignment: EMA8 > EMA21 (bullish short-term)
5. Float ≤100M (price can move on sustained buying)
6. Score ≥40 from Trade AI scorer

**Auto-Disqualifiers (any one blocks entry):**
- Social-only catalyst (StockTwits/Reddit buzz without verifiable news) → MAX: WAIT
- Reverse split in last 30 days → BLOCK
- RVOL <3x at entry → BLOCK
- Price >$25 or <$1 → BLOCK
- Float >100M → reassign to gap_and_go
- No stop definable within 8% of entry → BLOCK

**Exit Rules:**
- Target 1: +2R from entry (take 50% of position)
- Target 2: +3R or trailing stop on remainder
- Hard stop: price below gap-low of morning candle
- Time stop: MUST exit by 3:45pm ET — no overnight holds
- VWAP reclaim failure: if price drops below VWAP twice → exit

**Risk Parameters:**
- Risk per trade: $150–$200
- Max position size: $2,000
- Max daily trades: 3 scalp trades per day
- Stop placement: below gap-low or ATR stop (whichever is tighter)
- Stop width maximum: 8% of entry price

**Scoring Profile:**
- Catalyst: 15pts | RVOL: 12pts | Price Action: 10pts | Float: 8pts | Price Range: 5pts | Sector: 5pts
- A+: ≥48 → Sonnet trade plan + Telegram alert
- GO: ≥40 → Telegram alert, eligible for paper trading
- WAIT: 30–39 → monitor only
- AVOID: <30 → do not trade

**Agent Responsibilities:**
- Maria: Catalyst verification — is it company-specific? Is the news real? Source quality check
- Risk: RVOL validation, entry timing, first-candle analysis, stop below gap-low
- Steph: Position sizing vs portfolio, confirm taxable account only
- Alex: N/A for scalps (intraday, no IRA impact)

**Co-enables:**
- Often identifies stocks that become Swing Breakout candidates if they hold gains multiple days
- Feeds incubator — scalp symbols with sustained RVOL get promoted to swing watch
- Social scalp scanner runs parallel pipeline for same universe

**Notes:**
- SSDI income gate: scalp profits are Schedule C income → count toward $20K annual gross
- Execute in Fidelity cash account (taxable) or Alpaca paper. Never IRA.
- SMX and MNKD are current open paper trades from this strategy.

---

### STRATEGY 2 — GAP AND GO
**Status:** UNVALIDATED | **Account:** Taxable only

**The Edge:**
Pre-market gaps with real catalysts cause institutional FOMO at open.
Early entry on first-candle confirmation captures the gap continuation move.
Exit when gap fills OR at 2R. Never hold overnight.

**Universe:**
- Price: $2–$50
- Float: ≤200M shares (wider than scalp)
- Gap: ≥5% (key criterion)
- RVOL: ≥3x
- Exclude: ETFs, warrants, preferred shares

**Entry Criteria:**
1. Gap ≥5% confirmed in pre-market
2. Catalyst present (can be sector catalyst, not just company)
3. First 5-min candle closes above pre-market high
4. Entry must be placed before 9:50 AM ET (no late gap trades)
5. Pre-market volume confirms institutional interest

**Auto-Disqualifiers:**
- No catalyst at all → BLOCK (gap without reason = reversal risk)
- Entry after 9:50 AM → BLOCK
- First candle immediately fails (dumps below open) → BLOCK
- Reverse split in 30 days → BLOCK
- Gap >100% → data error, skip

**Exit Rules:**
- Target: gap measured move (+gap% × 0.618 Fibonacci extension)
- Stop: below gap-low (the low of the gap candle)
- Time stop: exit by 11:30 AM ET (gap plays typically resolve by midday)
- If gap fills (price returns to prior close) → exit immediately, no recovery wait

**Risk Parameters:**
- Risk per trade: $150–$200
- Stop width: gap-low to entry (typically 5–10%)
- Hold max: 3 hours from entry

**Proposal Lifecycle:** 10-hour expiry (intraday only, no overnight)

**Differences from Momentum Scalp:**
- Wider float tolerance (200M vs 100M)
- Lower RVOL minimum (3x vs 5x)
- Driven by gap size, not float compression
- Earlier exit (gap-fill or 11:30 AM vs 3:45 PM)

---

### STRATEGY 3 — EARNINGS CATALYST
**Status:** UNVALIDATED | **Account:** Taxable, Rollover IRA, Roth IRA

**The Edge:**
Two-phase: pre-earnings buildup 3–5 days before announcement, OR post-earnings momentum
on confirmed beats. The options market consistently underestimates magnitude of strong beats
in growth stocks. Post-earnings momentum persists 1–5 days.

**Universe:**
- Price: $5–$150
- Float: ≤500M (medium cap included)
- Earnings date: within 5 days (pre) OR earnings reported <2 days ago (post)

**Entry Criteria (POST-earnings phase — primary):**
1. EPS beat by ≥10% of consensus
2. Revenue beat OR raised guidance
3. Stock up ≥5% on earnings day
4. RVOL ≥3x day of earnings
5. Sector not in bear trend

**Entry Criteria (PRE-earnings buildup — secondary):**
1. Strong fundamental trend (3 consecutive beats)
2. IV rank <50 (options not pricing large move)
3. 3–5 days before earnings
4. Stock above 50-day SMA

**Exit Rules:**
- Target 1: 2.5R
- Target 2: prior resistance level
- Hard stop: below earnings-day low (post) or below entry -6% (pre)
- Time stop: 5 trading days maximum
- If earnings miss on next quarterly → exit immediately

**Risk Parameters:**
- Risk per trade: $200–$300
- Max hold: 5 trading days
- Account sizing: max 5% of IRA per position

**Proposal Lifecycle:** 72-hour expiry (3 calendar days — catalyst window)

**Agent Responsibilities:**
- Maria: EPS/revenue beat quality, guidance language, analyst reaction
- Risk: Chart setup, volume confirmation, stop placement
- Steph: IRA eligibility, position sizing vs income concentration
- Alex: SSDI/IRMAA impact if IRA trade

---

### STRATEGY 4 — SWING BREAKOUT
**Status:** UNVALIDATED | **Account:** Taxable, Rollover IRA, Roth IRA

**The Edge:**
Institutional accumulation during a multi-week consolidation base creates coiled energy.
When the base breaks on volume expansion, institutional momentum carries the move for days.
The edge: you enter early in the breakout, with a defined stop below the base.

**Universe:**
- Price: $5–$150
- Float: ≤500M
- Base duration: ≥15 trading days of consolidation
- Breakout volume: ≥1.5x average volume

**Entry Criteria:**
1. Base formed: ≥15 days of price consolidation (<20% range)
2. Volume dried up during base (3+ days below 30-day avg)
3. Breakout candle closes above base high
4. Breakout volume ≥1.5x 30-day average
5. Sector ETF in top 3 performing sectors
6. Entry within 3% of breakout level (no chasing)

**Auto-Disqualifiers:**
- Earnings within 7 days → BLOCK (binary event risk)
- Entry extended >5% from breakout → BLOCK (too late)
- Base >90 days → dead money, not a valid base
- Sector rank >7 → BLOCK
- Reverse split in 60 days → BLOCK

**Exit Rules:**
- Stop: below base-low (the low of the entire consolidation)
- Target 1: 2R (take 50%)
- Target 2: measured move from base (base height × 1.0 above breakout)
- Time stop: 21 calendar days (don't hold dead money)
- If price reclaims below breakout level for 2+ days → exit

**Risk Parameters:**
- Risk per trade: $200–$300
- Stop width: base-low to entry (varies 5–15%)
- Max hold: 21 calendar days

**Proposal Lifecycle:** 120-hour expiry (5 calendar days)

**Co-enables:**
- Incubator feeds this strategy: symbols consolidating ≥15 days surface as swing_breakout candidates
- Graduated from Momentum Scalp: a scalp that held for days and formed a mini-base
- Often becomes position trade: if breakout extends with fundamental catalyst, may graduate to Core Growth

---

### STRATEGY 5 — SWING TRADE
**Status:** UNVALIDATED | **Account:** Taxable, Rollover IRA, Roth IRA

Similar to Swing Breakout but entry can be on pullbacks within a trend,
not only on base breakouts. Wider universe, more flexible entry.

**Key differences from Swing Breakout:**
- No strict base formation required (trend pullbacks qualify)
- Hold: 3–21 days
- Entry: pullbacks to support within an established uptrend
- RVOL: ≥2x on entry day (lower bar, trend already established)

**Risk Parameters:**
- Risk per trade: $200–$300
- Proposal lifecycle: 168-hour expiry (7 calendar days)

---

### STRATEGY 6 — SPECULATIVE GROWTH
**Status:** UNVALIDATED | **Account:** Taxable, Roth IRA

High-risk, high-reward. Early-stage companies with transformational catalysts.
Position sizing is reduced (Roth max 3% per position). Hold 3–21 days.

**Universe:**
- Small/mid cap: $100M–$2B market cap
- Strong revenue growth: ≥40% YoY
- Catalyst: clinical trial, product launch, regulatory milestone

**Risk Parameters:**
- Risk per trade: $150–$250 (lower dollar risk, higher potential %)
- Roth only above $25 stocks (taxable for sub-$25)
- Proposal lifecycle: 168-hour expiry (7 calendar days)

---

### STRATEGY 7 — SECTOR ROTATION
**Status:** UNVALIDATED | **Account:** All accounts (ETFs available in 401k)

**The Edge:**
Sector cycles are persistent and institutional rebalancing creates momentum that lasts weeks.
Trade leading sector ETFs based on relative performance, momentum, breadth, and macro alignment.

**ETF Universe:**
XLK (Tech), XLF (Financials), XLV (Healthcare), XLE (Energy), XLI (Industrials),
XLC (Communication), XLP (Consumer Staples), XLU (Utilities), XLB (Materials), XLRE (Real Estate)

**Rotation Entry Rules:**
- Buy when sector rank ≤3 (top 3 performers)
- Outperforms SPY by ≥2% over 5 days
- Breadth: ≥50% of sector stocks above 50-day SMA
- Momentum improving (not decelerating)

**Rotation Exit Rules:**
- Sector rank drops to >5
- Underperforms SPY by ≥1% over 5 days
- Breadth deteriorates

**Macro Alignment (FRED data feeds this):**
| Regime | Prefer | Avoid |
|---|---|---|
| High inflation | XLE, XLB, XLI | XLRE, XLU, XLP |
| Rising rates | XLF, XLE | XLRE, XLU |
| Recession risk | XLP, XLU, XLV | XLK, XLF, XLE |
| Risk-on | XLK, XLF, XLI | XLU, XLP |

**Risk Parameters:**
- Risk per trade: $300–$500 (larger positions — ETFs are more stable)
- Rebalance: weekly
- Proposal lifecycle: 336-hour expiry (14 calendar days)

**Co-enables:**
- Momentum Scalp: sector ETF momentum confirms individual stock direction
- Swing Breakout: sector top 3 is a required criterion for swing setups
- Defense Thesis: sector rotation into XLI/XLF with geopolitical catalyst

---

### STRATEGY 8 — INCOME POSITION ADD
**Status:** TESTING | **Account:** Rollover IRA, Roth IRA, Taxable

Adding to or initiating income-generating positions. Triggered by:
- Pullbacks to support in dividend/income stocks
- Ex-dividend opportunities
- Rebalancing when income weight drops below target

**Universe:**
- Yield: ≥3% (preferred ≥5%)
- SCHD, VYM, DGRO, O, MAIN, JEPI, JEPQ and similar
- Dividend growth rate: ≥3% annually (income should grow)

**Entry Criteria:**
1. Price at or below 50-day SMA (pullback entry, not chasing)
2. Dividend not at risk (payout ratio <80% for most sectors)
3. No ex-dividend within 5 days (buying before ex-div for income)
4. Portfolio income weight below target

**Risk Parameters:**
- Risk per trade: $300–$500
- Position sizing: Steph calculates based on income contribution target ($55K/yr goal)
- Non-negotiable: never sell income-critical positions (>$11K/yr income contribution) without John approval
- Proposal lifecycle: 240-hour expiry (10 calendar days)

**Income Protection Rule (G2 — Non-Negotiable):**
NEVER auto-rotate, trim, or exit income-critical positions.
This rule cannot be overridden by any agent or LLM.

---

### STRATEGIES 9–10 — CORE GROWTH COMPOUNDER / CORE INDEX
**Status:** UNVALIDATED | **Account:** All accounts

Long-term buy-and-hold for wealth compounding. Not active trading strategies.
Core Growth: large-cap quality compounders (10%+ earnings growth, wide moat)
Core Index: SPY/QQQ/VTI for passive market exposure.

**Entry:** On meaningful pullbacks only (≥8% from recent high)
**Exit:** Only on fundamental thesis change (not price movements)
**Risk:** No hard stop (position trades — size controlled by allocation %)
**Proposal lifecycle:** 720-hour expiry (30 calendar days)

---

### STRATEGY 11 — COVERED CALL INCOME
**Status:** UNVALIDATED | **Account:** IRA, Taxable (must own underlying)

Monthly income generation from JEPI/JEPQ or writing calls on existing positions.
Requires existing position in the underlying.

**Target yield:** 8–12% annually from premium
**Roll rules:** Roll 21 DTE (days to expiration) to avoid assignment
**Assignment rules:** If assigned, treat as planned exit at strike price
**Proposal lifecycle:** 720-hour expiry (30 calendar days)

---

### STRATEGY 12 — DEFENSE / AEROSPACE THESIS
**Status:** UNVALIDATED | **Account:** All accounts

Concentrated thesis trade: geopolitical uncertainty, NATO spending, AI in defense.
Core holdings: LMT, RTX, NOC, KTOS, HII, TDG.
3–18 month thesis horizon. Size by conviction (max 3% per position in IRA).
**Proposal lifecycle:** 720-hour expiry (30 calendar days)

---

### STRATEGIES 13–18 — INCOME & POSITION STRATEGIES

| Strategy | Target Yield | Universe | Key Rule | Lifecycle |
|---|---|---|---|---|
| Dividend Growth Compounder | Yield + 3%+ growth | SCHD, VZ, KO, PEP | DGR ≥3%/yr | 720hr |
| High Yield Income (BDC) | 10–15% | MAIN, ARCC, HTGC, PSEC | IRA only (ordinary income) | 720hr |
| International Dividend | 4–6% yield + FX | VEA, VXUS, EEM | Diversification hedge | 720hr |
| Recovery Watch | Capital appreciation | Deep value, 52-wk lows | Thesis must include catalyst | 336hr |
| REIT Income | 5–8% yield | O, STAG, PLD | IRA only (avoids ordinary income tax) | 720hr |
| Bond Income | 4–6% yield | BND, AGG, TLT | Duration matches rate outlook | 720hr |

---

### STRATEGY 19 — TAX LOSS HARVEST
**Status:** UNVALIDATED | **Account:** Taxable only

**Purpose:** Realize losses to offset capital gains. Harvest in Q4 or after large market moves.
**Rules:**
- Wash sale: 30-day rule — cannot repurchase same or substantially identical security
- Replacement: use correlated ETF (sell NVDA → buy SMH) to maintain exposure
- Window: 7-day maximum to find replacement (narrow tax window)
- Coordinate with Steph on total tax impact before executing

**Proposal lifecycle:** 168-hour expiry (7 calendar days — harvest window is narrow)

---

### STRATEGY 20 — CASH / STABLE
**Status:** UNVALIDATED | **Account:** All accounts

Parking capital in money market, T-bills, or stable funds during:
- Market uncertainty / high VIX environments
- Between active positions (capital waiting to be deployed)
- SSDI income floor protection (maintain cash buffer)

**Target:** 3–5% yield (T-bills or money market)
**Exit trigger:** Market regime improves, deploy into active strategies
**Proposal lifecycle:** 720-hour expiry (30 calendar days)

---

## SECTION 3: GLOBAL RISK RULES

These rules apply to ALL strategies, ALL accounts. No exceptions.

### Hard Blocks (BLOCK = no trade under any circumstances)
| Rule | Description |
|---|---|
| NO_STOP_DEFINED | Stop loss must be set before entry. No stop = no trade. |
| REVERSE_SPLIT_30D | Reverse split in last 30 days. Stock is manipulated. |
| TRADING_HALT | Symbol currently halted. |
| DATA_STALE | Price data >24 hours old. |
| DAILY_LOSS_LIMIT | Daily loss ≥4× risk-per-trade. Stop trading for the day. |
| WEEKLY_LOSS_LIMIT | Weekly loss ≥8× risk-per-trade. Stop trading for the week. |
| STRATEGY_KILLED | Strategy has been terminated. |
| LIVE_TRADING_DISABLED | Global kill switch active. Paper only. |
| SOCIAL_ONLY_CATALYST | No news, only social media buzz. Max = WAIT for scalp. |
| IRA_SCALP_ATTEMPT | Momentum scalp or gap_and_go → IRA account. Hard block. |
| MAX_POSITIONS_EXCEEDED | >3 taxable simultaneous, >5 IRA simultaneous. |

### Paper-Only Blocks (PAPER_ONLY = no live trading yet)
| Rule | Description |
|---|---|
| STRATEGY_UNVALIDATED | Strategy has <30 paper trades or <55% win rate. |
| STRATEGY_QUARANTINED | Under performance review after drawdown. |
| LIVE_TRADING_DISABLED | LIVE_TRADING_ENABLED=false in .env |

### Portfolio Risk Limits
| Limit | Value |
|---|---|
| Max simultaneous positions (taxable) | 3 |
| Max simultaneous positions (IRA) | 5 |
| Max simultaneous total | 8 |
| Max same-sector positions | 1 |
| Max single position (IRA %) | 5% of account |
| Daily loss limit | 4× risk-per-trade |
| Weekly loss limit | 8× risk-per-trade |

### Market Regime Rules (from FRED macro data)
| VIX Level | Action |
|---|---|
| <15 | Normal operation, all strategies active |
| 15–20 | Normal, prefer swing over intraday |
| 20–25 | Reduce scalp size 25%, prefer sector rotation |
| 25–35 | Scalp/gap paused, income/defensive only |
| >35 | All active strategies paused, cash/stable only |

### Catalyst Source Quality
| Source | Max Signal | Quality Score |
|---|---|---|
| SEC 8-K (earnings, M&A, FDA) | A+ / GO | 1.00 |
| Press release + multiple news outlets | GO | 0.85 |
| Single news outlet, verified | GO | 0.75 |
| Social media + news confirmation | WAIT | 0.60 |
| StockTwits only | WAIT (no GO) | 0.35–0.55 |
| Reddit only | WAIT (no GO) | 0.35 |
| No source found | AVOID | 0.00 |

---

## SECTION 4: AVERAGE RISK BY STRATEGY

| Strategy | Risk/Trade | Avg Trades/Mo | Avg Monthly Risk | Annual Risk Budget |
|---|---|---|---|---|
| Momentum Scalp | $150–$200 | 10–20 | $1,500–$4,000 | $18,000–$48,000 |
| Gap and Go | $150–$200 | 5–10 | $750–$2,000 | $9,000–$24,000 |
| Earnings Catalyst | $200–$300 | 3–6 | $600–$1,800 | $7,200–$21,600 |
| Swing Breakout | $200–$300 | 4–8 | $800–$2,400 | $9,600–$28,800 |
| Swing Trade | $200–$300 | 3–6 | $600–$1,800 | $7,200–$21,600 |
| Speculative Growth | $150–$250 | 1–3 | $150–$750 | $1,800–$9,000 |
| Sector Rotation | $300–$500 | 2–4 | $600–$2,000 | $7,200–$24,000 |
| Income Position Add | $300–$500 | 1–3 | $300–$1,500 | $3,600–$18,000 |
| Position Strategies | $300–$500 | 0–2 | $0–$1,000 | $0–$12,000 |

**Current paper trading:** MNKD + SMX open. 2 trades in system.
**Live trading:** DISABLED until 6-month paper validation complete.

---

## SECTION 5: HOW STRATEGIES CO-ENABLE

This is the system intelligence — how finding a signal in one strategy
often strengthens signals in another.

```
DISCOVERY LAYER
  ├── 22 Finviz screeners → 385 symbols daily
  ├── Social scanners → StockTwits + Reddit discovery
  └── 44 YouTube channels → macro + sector intelligence

INCUBATOR (144 symbols)
  ├── Symbols tracked for 7+ days
  ├── Score improving → promoted to strategy signal
  └── Score degrading → rolled off (keeps universe clean)
  
SIGNAL ROUTING (from GO tickers)
  ├── Float ≤100M + RVOL ≥5x + Gap ≥5% + Price $1-$25
  │   └── MOMENTUM_SCALP
  ├── Gap ≥5% + RVOL ≥3x + Pre-market volume
  │   └── GAP_AND_GO
  ├── Earnings catalyst + Post-beat momentum
  │   └── EARNINGS_CATALYST
  ├── Base ≥15d + Breakout volume
  │   └── SWING_BREAKOUT → may become CORE_GROWTH
  └── Sector ETF in top 3 + Macro alignment
      └── SECTOR_ROTATION

CO-ENABLEMENT FLOWS:

1. Scalp → Incubator → Swing:
   SMX was a scalp. Held 3+ days with sustained volume.
   Now in incubator. If score continues to improve →
   becomes swing_breakout candidate with existing position context.

2. Sector Rotation → All Strategies:
   Sector ETF confirms the wind is at your back.
   Swing breakout in XLV sector stock + XLV in top 3 sectors
   = higher conviction entry. Same stock in bottom sector = wait.

3. Earnings Catalyst → Swing Breakout:
   Post-earnings beat creates the base catalyst.
   If stock consolidates for 15+ days after earnings pop →
   becomes a swing_breakout setup with the earnings as background catalyst.

4. Income Position Add → Covered Call Income:
   Once an income position is established (via income_add),
   writing covered calls generates monthly premium.
   The two strategies work as a unit: income via dividend + income via premium.

5. Tax Loss Harvest → Income Position Add:
   Harvest NVDA loss → buy SMH (correlated, avoids wash sale) →
   when harvest window passes → rotate back to NVDA →
   OR deploy harvest proceeds into income_add for yield.

6. Recovery Watch → Core Growth Compounder:
   Identify beaten-down quality companies (recovery_watch).
   When thesis inflects (management change, spin-off, product cycle) →
   initiate position → becomes core_growth_compounder as thesis plays out.

7. Momentum Scalp → Strategy Intelligence:
   A scalp that works tells you the sector is HOT.
   If 3 scalps in biotech win in the same week →
   Sector Rotation model should consider XLV.
   Maria calibration tracks this — "4 biotech GO signals this week,
   2 won, 1 hit time stop, 1 stopped. Catalyst quality: earnings beats."
```

---

## SECTION 6: AGENT + LLM VISIBILITY — ARE THEY SEEING THE STRATEGIES?

### What agents currently receive (injected automatically):
1. **Portfolio context** — holdings, income gap, tax bracket
2. **FRED macro context** — 7 series (rates, inflation, employment, VIX)
3. **Qualified intel** — news + YouTube key points + SEC Form 4
4. **Outcome lessons** — last 7 correct/wrong decisions from calibration
5. **SSDI rules** — Medicaid lookback, IRMAA thresholds, MFS ceiling
6. **Cross-agent views** — prior results from other agents on same symbol
7. **Scan intelligence** — trade_ai_scans data for GO tickers
8. **RAG context** — relevant prior intelligence from embeddings
9. **Calibration context** — accuracy stats or "accumulating" message
10. **Scalp instructions** — for price<$100, float<200M GO tickers only

### What agents do NOT currently receive:
❌ The full strategy playbook (this document)
❌ Clear explanation of which strategy a proposal belongs to and WHY
❌ Co-enablement context ("this scalp signal is from the same sector as your swing candidate")
❌ Risk budget context ("you've taken 3 scalps this week, daily loss limit awareness")

### To fix agent visibility — add to strategy_prompt_injection:

```python
# Add to scripts/intel_query.py or agent prompt builder
def get_strategy_context_for_prompt(strategy_id: str, proposal: dict) -> str:
    """
    Returns a clear plain-English strategy context block for agent prompts.
    Tells the agent exactly what this strategy requires and how this
    specific proposal measures up.
    """
    from scripts.proposal_lifecycle import get_expiry_hours, is_overnight

    playbook = STRATEGY_PLAYBOOK.get(strategy_id, {})

    lines = [
        f"STRATEGY: {playbook.get('display_name', strategy_id)}",
        f"Purpose: {playbook.get('purpose', 'See strategy YAML')}",
        f"Account: {playbook.get('account_fit', 'See YAML')}",
        f"Hold period: {playbook.get('hold_period', 'See YAML')}",
        f"Risk/trade: ${playbook.get('risk_per_trade', '150-300')}",
        f"Proposal expires: {get_expiry_hours(strategy_id)}hr from creation",
        f"Overnight eligible: {is_overnight(strategy_id)}",
        "",
        "KEY CRITERIA FOR THIS STRATEGY:",
    ]

    criteria = playbook.get('entry_criteria', [])
    for c in criteria:
        lines.append(f"  ✓ {c}")

    disqualifiers = playbook.get('auto_disqualifiers', [])
    if disqualifiers:
        lines.append("")
        lines.append("AUTO-DISQUALIFIERS (any one blocks the trade):")
        for d in disqualifiers:
            lines.append(f"  ✗ {d}")

    lines.append("")
    lines.append(
        f"YOUR TASK: Evaluate whether {proposal.get('symbol')} meets "
        f"the {strategy_id} criteria above. Be specific about which "
        f"criteria it meets and which it fails. Do not fabricate data."
    )

    return "\n".join(lines)
```

### To verify agents can see strategies — run this:

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# 1. Check what's in the agent prompt for a pending proposal
psql -h 127.0.0.1 -U trade_ai -d trade_ai -c "
SELECT proposal_id, symbol, model_used,
       LEFT(narrative, 400) as narrative,
       LEFT(approve_case, 200) as approve_case
FROM paper_proposal_analysis
ORDER BY created_at DESC LIMIT 3;" | cat

# 2. Check if strategy context is in the prompt
# The narrative should mention the strategy name, criteria, and specific data
# NOT just: "XMTR is a swing_breakout proposal. RVOL 6.7x. Catalyst verified."

# 3. Check agent reviews mention strategy criteria
psql -h 127.0.0.1 -U trade_ai -d trade_ai -c "
SELECT agent_name, verdict, LEFT(narrative, 300) as narrative
FROM watchlist_agent_results
WHERE created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC LIMIT 6;" | cat

# 4. Check YAML files actually exist on disk
ls config/strategies/*.yaml 2>/dev/null || echo 'YAML FILES MISSING'

# If missing, the prompts don't have strategy context.
# This document + Claude Code should create all YAML files.
```

### YAML Files to Create (if not present):

```bash
ls /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/strategies/
```

**If any are missing, use Claude Code with this prompt:**

```
Create/update the strategy YAML files in config/strategies/ 
using the TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md as the source of truth.

Each YAML must include:
  strategy_id, display_name, version, purpose, eligible_accounts,
  timeframe, universe (price/float/rvol/gap ranges), 
  entry_criteria (list), auto_disqualifiers (list),
  exit_rules (list), risk_per_trade, target_rr, stop_method,
  max_hold_days, proposal_expiry_hours,
  agent_responsibilities (maria/risk/steph/alex roles),
  co_enables (which other strategies this feeds)

Files needed:
  momentum_scalp.yaml, gap_and_go.yaml, earnings_catalyst.yaml,
  swing_breakout.yaml, swing_trade.yaml, speculative_growth.yaml,
  sector_rotation.yaml, income_add.yaml, core_growth_compounder.yaml,
  core_index.yaml, covered_call_income.yaml, defense_thesis.yaml,
  dividend_growth_compounder.yaml, high_yield_income_bdc.yaml,
  international_dividend.yaml, recovery_watch.yaml, reit_income.yaml,
  bond_income.yaml, tax_loss_harvest.yaml, cash_or_stable.yaml,
  shared_risk_rules.yaml (global rules)

After creating YAMLs, update proposal_intelligence_analyzer.py to:
1. Load the relevant YAML before building the LLM prompt
2. Inject strategy criteria into the prompt so qwen3:14b
   evaluates the proposal against actual strategy rules
3. The narrative should cite specific criteria met/failed,
   not just "RVOL 6.7x verified"

Verify with:
  ls config/strategies/*.yaml | wc -l  # should be 21
  cat config/strategies/momentum_scalp.yaml | head -30
  cat config/strategies/shared_risk_rules.yaml | head -20
```

---

## SECTION 7: VALIDATION GATE — PATH TO LIVE TRADING

Each strategy must pass this gate before live trading is enabled.

### Gate Requirements (per strategy):
1. **30 paper trades completed** (not just proposed — approved + closed)
2. **Win rate ≥55%** (not just the 30, but consistent over time)
3. **Profit Factor ≥1.3** (gross wins / gross losses)
4. **Max drawdown <25%** on paper trading capital
5. **6 calendar months** of paper trading data
6. **Agent calibration ≥60%** accuracy on that strategy type
7. **Human review** — John approves strategy graduation

### Current Status:
| Strategy | Paper Trades | Win Rate | PF | Status |
|---|---|---|---|---|
| Momentum Scalp | 2 open | N/A | N/A | Accumulating |
| All others | 0 | N/A | N/A | Not started |

### Graduation Process:
1. Automated check: `paper_performance_governance.py` runs monthly
2. If gate is met: Telegram alert to John + Aegis brief
3. John reviews: `/v2/paper-journal` + strategy analytics
4. John approves: `STRATEGY_LIVE_ENABLED=momentum_scalp` in system_controls
5. Alpaca executes: `LIVE_TRADING_ENABLED=true` (global flag)
6. First live trade: single unit, manual monitoring

---

## SECTION 8: WHERE THIS DOCUMENT LIVES

### Save to system:
```bash
# Primary location (Claude Code reads this)
cp TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md \
   /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/docs/project/

# Config location (agent prompts reference this)
cp TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md \
   /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/

# Verify
ls -la /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md
ls -la /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/docs/project/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md
```

### Reference in agent prompts:
```python
# In intel_query.py or process_watchlist_agent_jobs.py
STRATEGY_PLAYBOOK_PATH = 'config/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md'

def get_strategy_rules(strategy_id: str) -> str:
    """Read the playbook and extract the relevant strategy section."""
    try:
        with open(STRATEGY_PLAYBOOK_PATH) as f:
            content = f.read()
        # Extract the section for this strategy
        marker = f'### STRATEGY'
        # Find the relevant section...
        return content[...]  # see full implementation in session prompt
    except Exception:
        return f"Strategy: {strategy_id} — see config/strategies/{strategy_id}.yaml"
```

### Commit:
```bash
git add docs/project/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md
git add config/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md
git commit -m "Add Strategy Playbook v1.0: all 20 strategies, rules, risk, co-enablement, agent visibility"
```

---

## CHANGELOG

| Version | Date | Changes |
|---|---|---|
| v1.0 | May 7, 2026 | Initial — all 20 strategies documented from live system data |

*This document should be updated whenever strategy rules change.
The strategy_registry table in PostgreSQL is the live record.
This document is the human-readable reference and agent training material.*

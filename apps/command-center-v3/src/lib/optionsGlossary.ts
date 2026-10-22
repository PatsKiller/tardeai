/** Options desk glossary (2026-10-22, operator: "options is the most complicated page; accurate
 *  tooltips and help files all over the page").
 *
 *  One definitions module for every number and term the Options desk renders. Each entry says:
 *    plain    — what it is, in plain English
 *    formula  — how it is calculated, when it is calculated (text)
 *    computedBy — the server function that computes it (file:function), cited so the text can be
 *                 checked against the code; the TS mirrors below follow the same arithmetic
 *    source   — the served field(s) the page reads
 *    forYou   — what it means for you
 *
 *  Rules for this file:
 *    - Never describe a number the server does not compute. If a field is absent the page shows
 *      "—" with NOT_SERVED, never a fabricated value.
 *    - The formula mirrors below are display/check helpers only. The page shows SERVED values;
 *      src/lib/optionsGlossary.test.ts proves the mirrors reproduce the served values on a fixture
 *      captured from the live API, so the text cannot drift from the code silently.
 */

export type GlossaryEntry = {
  term: string
  plain: string
  formula?: string
  computedBy?: string
  source?: string
  forYou: string
}

/** Shown when a field the page wants is absent from the payload. */
export const NOT_SERVED = 'Not provided by this server version. The page shows "—" rather than estimate it.'

// ── Formula mirrors (each cites the server function it mirrors) ──────────────────────────────────

const fin = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const r2 = (v: number) => Math.round(v * 100) / 100

/** Mid price. Mirrors scripts/lib/options_intent/ranking.py:mid — (bid + ask) / 2 when both sides exist. */
export function midPrice(bid: number | null | undefined, ask: number | null | undefined): number | null {
  if (!fin(bid) || !fin(ask) || ask <= 0) return null
  return (bid + ask) / 2
}

/** Bid/ask spread as % of mid. Mirrors scripts/options_desk_enterprise.py:liquidity_gate:
 *  100 × (ask − bid) / mid, where mid is the chain's own mid when it supplies one, else (bid + ask) / 2.
 *  The desk gate fails above 12%. Unknown when there is no positive mid or ask < bid. */
export function spreadPct(bid: number | null | undefined, ask: number | null | undefined, chainMid?: number | null): number | null {
  if (!fin(bid) || !fin(ask) || ask < bid) return null
  const m = fin(chainMid) && chainMid > 0 ? chainMid : (bid > 0 && ask > 0 ? (bid + ask) / 2 : 0)
  return m > 0 ? (100 * (ask - bid)) / m : null
}

/** Cash paid or received for the whole order. Mirrors scripts/lib/options_economics.py:economics
 *  (option_cost_total / credit_total) — premium × 100 × contracts. */
export function premiumTotal(premium: number, contracts: number, multiplier = 100): number {
  return r2(premium * multiplier * contracts)
}

/** Cash a cash-secured put reserves. Mirrors scripts/lib/options_economics.py:economics
 *  (cash_committed) and ranking.py:rank_csp (collateral_per_contract) — strike × 100 × contracts. */
export function cspCollateral(strike: number, contracts = 1, multiplier = 100): number {
  return r2(strike * multiplier * contracts)
}

/** Premium as a % of the cash held. Mirrors scripts/lib/options_intent/ranking.py:rank_csp
 *  (return_pct = mid / strike × 100). Uses the per-share premium and strike. */
export function premiumOverCollateralPct(premium: number, strike: number): number | null {
  if (!fin(premium) || !fin(strike) || strike <= 0) return null
  return Math.round((premium / strike) * 100 * 1000) / 1000
}

/** Simple (not compounded, not repeatable) annualized %. Mirrors ranking.py:rank_csp / rank_covered_calls
 *  (annualized_pct = return × 365 / dte × 100, dte floored at 1). */
export function simpleAnnualizedPct(returnFraction: number, dte: number): number | null {
  if (!fin(returnFraction) || !fin(dte)) return null
  return Math.round(((returnFraction * 365) / Math.max(Math.trunc(dte), 1)) * 100 * 10) / 10
}

/** Covered-call premium yield, annualized on the shares' value. Mirrors scripts/options_engine.py:_cc_yield_ann_pct
 *  ((premium / spot) × (365 / max(dte, 1)) × 100). */
export function coveredCallYieldAnnPct(premium: number, spot: number, dte: number): number {
  if (!(premium > 0) || !(spot > 0)) return 0
  return (premium / spot) * (365 / Math.max(Math.trunc(dte || 0), 1)) * 100
}

/** Breakeven at expiry, per share. Mirrors scripts/lib/options_economics.py:economics:
 *   cash_secured_put  → strike − premium   (net_cost_if_assigned_per_share)
 *   protective_put / long_put → strike − premium (put_breakeven)
 *   long_call         → strike + premium
 *   covered_call      → strike + premium is the called-away price (called_away_price_per_share), not a breakeven
 *   credit_spread     → short strike − credit (breakeven) */
export function breakevenPerShare(strategy: string, strike: number, premium: number, shortStrike?: number | null): number | null {
  if (!fin(strike) || !fin(premium)) return null
  if (strategy === 'cash_secured_put' || strategy === 'protective_put' || strategy === 'long_put') return r2(strike - premium)
  if (strategy === 'long_call') return r2(strike + premium)
  if (strategy === 'credit_spread') return r2((fin(shortStrike) ? shortStrike : strike) - premium)
  return null
}

/** Protective-put floor: the least the insured shares are worth at expiry, after the premium.
 *  Mirrors scripts/lib/options_economics.py:economics (floor_value_after_premium = (strike − premium) × insured shares). */
export function protectivePutFloor(strike: number, premium: number, insuredShares: number): number {
  return r2((strike - premium) * insuredShares)
}

/** Most the hedged shares can lose from today's mark, premium included.
 *  Mirrors economics (hedged_max_loss_from_mark = max(0, spot − (strike − premium)) × insured). */
export function hedgedMaxLossFromMark(spot: number, strike: number, premium: number, insuredShares: number): number {
  return r2(Math.max(0, spot - (strike - premium)) * insuredShares)
}

/** Desk tier from edge. Mirrors scripts/options_desk_enterprise.py:desk_tier (A ≥ 72, B ≥ 62, else C; config may override). */
export function deskTier(edge: number, aMin = 72, bMin = 62): 'A' | 'B' | 'C' {
  if (edge >= aMin) return 'A'
  if (edge >= bMin) return 'B'
  return 'C'
}

// ── Entries ──────────────────────────────────────────────────────────────────────────────────────

export const GLOSSARY: Record<string, GlossaryEntry> = {
  // Contract basics
  'term.strike': {
    term: 'Strike',
    plain: 'The fixed price in the option contract: the price you may buy (call) or sell (put) the shares at.',
    source: 'proposal.strike',
    forYou: 'Compare it with today\'s stock price. A put strike below spot means the insurance starts only after a drop.',
  },
  'term.expiry': {
    term: 'Expiry',
    plain: 'The last day the contract exists. After it, the option is exercised, assigned or worthless.',
    source: 'proposal.expiration',
    forYou: 'Anything the trade protects or earns ends on this date.',
  },
  'term.dte': {
    term: 'DTE (days to expiry)',
    plain: 'Calendar days from the quote date to expiry.',
    formula: 'expiration date − quote date, in calendar days',
    computedBy: 'scripts/options_engine.py (contract dte from the Schwab chain)',
    source: 'proposal.dte',
    forYou: 'Longer gives a thesis time; shorter decays faster. Annualized numbers divide by this.',
  },
  'term.contracts': {
    term: 'Contracts',
    plain: 'How many option contracts. One standard contract covers 100 shares.',
    source: 'proposal.contracts',
    forYou: 'Shares covered = contracts × 100. Merged rows add the contracts of each account.',
  },
  'term.spot': {
    term: 'Spot (stock price)',
    plain: 'The stock price the desk used, with the time it was read.',
    source: 'proposal.underlying_price, proposal.price_source.as_of',
    forYou: 'Every quote has its own time. A ⚠ means it is older than the cap or from outside the regular session.',
  },
  'term.bid': {
    term: 'Bid',
    plain: 'The highest price a buyer is currently offering for the contract.',
    source: 'proposal.bid',
    forYou: 'If you sell, you are likely to be filled near the bid, not the mid.',
  },
  'term.ask': {
    term: 'Ask',
    plain: 'The lowest price a seller is currently asking for the contract.',
    source: 'proposal.ask',
    forYou: 'If you buy, expect to pay near the ask. Protective-put costs here are priced at the ask.',
  },
  'term.mid': {
    term: 'Mid',
    plain: 'Halfway between bid and ask. A reference price, not a fill.',
    formula: '(bid + ask) / 2',
    computedBy: 'scripts/lib/options_intent/ranking.py:mid',
    source: 'proposal.premium_midpoint, plan match .mid',
    forYou: 'A wide quote makes the mid unreliable; a limit order at mid may not fill.',
  },
  'term.spread_pct': {
    term: 'Spread %',
    plain: 'How wide the bid/ask quote is, as a percent of the mid.',
    formula: '100 × (ask − bid) / mid (the chain\'s own mid when it supplies one, else (bid + ask) / 2)',
    computedBy: 'scripts/options_desk_enterprise.py:liquidity_gate',
    source: 'proposal.bid_ask_spread_pct, enterprise.liquidity.bid_ask_spread_pct',
    forYou: 'The desk cap is 12%. Above it the price is not trustworthy and the idea is held for a re-quote.',
  },
  'term.oi': {
    term: 'OI (open interest)',
    plain: 'How many of these contracts are open right now.',
    source: 'proposal.oi',
    forYou: 'The desk wants at least 50. Low OI means few counterparties and a costly exit.',
  },
  'term.volume': {
    term: 'Volume',
    plain: 'Contracts traded today.',
    source: 'proposal.volume',
    forYou: 'The desk wants at least 5. Zero early in the day is normal; zero with low OI is a warning.',
  },
  'term.iv': {
    term: 'IV (implied volatility)',
    plain: 'The yearly volatility the option price implies. Higher IV means richer premiums.',
    source: 'proposal.iv_used (fraction) or plan match .iv (percent)',
    forYou: 'Sellers like high IV; buyers pay more for it.',
  },
  'term.iv_rank': {
    term: 'IV rank',
    plain: 'Where today\'s implied volatility sits in its recent range, 0–100.',
    computedBy: 'scripts/options_engine.py:_iv_rank_from_history (or _iv_rank_proxy when history is short)',
    source: 'proposal.iv_rank, proposal.iv_rank_basis',
    forYou: 'Check the basis: a "proxy blend" is not true historical IV rank.',
  },
  'term.delta': {
    term: 'Delta (Δ)',
    plain: 'How much the option price moves for a $1 move in the stock. Puts are negative.',
    source: 'proposal.delta, plan match .delta',
    forYou: 'It is price sensitivity, not the probability of assignment.',
  },
  'term.premium': {
    term: 'Premium',
    plain: 'The price of one option, per share. Multiply by 100 per contract.',
    source: 'proposal.premium, proposal.premium_basis (ask, bid or mid)',
    forYou: 'Check the basis: an ask price is what a buyer pays; a mid is not a fill.',
  },
  'term.total_cost': {
    term: 'Total cost / credit',
    plain: 'Cash paid (debit) or received (credit) today for every contract in the idea.',
    formula: 'premium × 100 × contracts (summed across merged accounts)',
    computedBy: 'scripts/lib/options_economics.py:economics (option_cost_total / credit_total)',
    source: 'proposal.premium_total',
    forYou: 'A debit is the most a bought option can lose. A credit is the most a sold option can make.',
  },
  'term.collateral': {
    term: 'Collateral (cash held)',
    plain: 'Cash the broker sets aside so you can buy the shares if a sold put is assigned.',
    formula: 'strike × 100 × contracts',
    computedBy: 'scripts/lib/options_economics.py:economics (cash_committed); ranking.py:rank_csp (collateral_per_contract)',
    source: 'economics.cash_committed, plan match .collateral_per_contract',
    forYou: 'That cash cannot be used for anything else until the put expires or is closed.',
  },
  'term.premium_over_collateral': {
    term: 'Premium / collateral',
    plain: 'The premium as a percent of the cash held for a cash-secured put.',
    formula: 'premium ÷ strike × 100 (the premium is the bid, what a seller receives, when the server sends premium_basis "bid"; older servers used the mid)',
    computedBy: 'scripts/lib/options_intent/ranking.py:rank_csp (return_pct); premium_over_collateral_pct when served',
    source: 'premium_over_collateral_pct, plan match .premium_over_collateral_pct or .return_pct',
    forYou: 'This is what the desk shows for a cash-secured put instead of reward/risk.',
  },
  'term.simple_annualized': {
    term: 'Simple annualized',
    plain: 'The one-trade return scaled to a year without compounding.',
    formula: 'return × 365 ÷ DTE × 100 (DTE at least 1)',
    computedBy: 'scripts/lib/options_intent/ranking.py:rank_csp / rank_covered_calls (annualized_pct); simple_annualized_yield_pct when served',
    source: 'simple_annualized_yield_pct, yield_basis, plan match .annualized_pct',
    forYou: 'Not repeatable: it assumes the same premium every period, which rarely happens. Use it to compare, not to forecast.',
  },
  'term.breakeven': {
    term: 'Breakeven',
    plain: 'The stock price at expiry where the trade neither makes nor loses money, per share.',
    formula: 'cash-secured put and put: strike − premium · long call: strike + premium · credit spread: short strike − credit',
    computedBy: 'scripts/lib/options_economics.py:economics (net_cost_if_assigned_per_share, put_breakeven, breakeven)',
    source: 'proposal.put_breakeven, proposal.breakeven, plan match .breakeven',
    forYou: 'For a cash-secured put it is your effective purchase price if assigned.',
  },
  'term.floor': {
    term: 'Floor',
    plain: 'The least the insured shares are worth at expiry once the premium is paid.',
    formula: '(strike − premium) × insured shares',
    computedBy: 'scripts/lib/options_economics.py:economics (floor_value_after_premium)',
    source: 'proposal.floor_value, economics.floor_value_after_premium',
    forYou: 'However far the stock falls before expiry, the insured shares plus the puts are worth at least this.',
  },
  'term.hedged_max_loss': {
    term: 'Most you can lose (hedged)',
    plain: 'The insured shares\' largest loss from today\'s price to the floor, premium included.',
    formula: 'max(0, spot − (strike − premium)) × insured shares',
    computedBy: 'scripts/lib/options_economics.py:economics (hedged_max_loss_from_mark)',
    source: 'economics.hedged_max_loss_from_mark',
    forYou: 'It is measured from today\'s price, not from what you paid for the shares.',
  },
  'term.time_value_pct': {
    term: 'Time value %',
    plain: 'The part of a LEAP\'s price that is not intrinsic value, as a percent of the stock price.',
    computedBy: 'scripts/lib/options_intent/ranking.py:rank_leaps (time_value_pct)',
    source: 'plan match .time_value_pct',
    forYou: 'This is the cost of holding the call instead of the shares; it decays to zero by expiry.',
  },
  'term.pop': {
    term: 'POP (probability of profit)',
    plain: 'A model estimate of the chance the trade ends profitable at expiry.',
    formula: 'lognormal terminal price at the stated IV, zero drift',
    computedBy: 'scripts/lib/options_economics.py:payoff_metrics (probability_of_profit_pct)',
    source: 'proposal.pop_pct, proposal.pop_basis',
    forYou: 'Not calibrated against real outcomes. Withheld when quotes are not validated. Not shown for insurance.',
  },
  'term.edge': {
    term: 'Edge',
    plain: 'The desk\'s 0–100 composite score of POP, IV rank, premium yield, catalyst and conviction.',
    formula: '0.35 × POP + 0.20 × IV rank + premium-yield points (≤ 20) + catalyst (≤ 15) + conviction (≤ 10)',
    computedBy: 'scripts/options_engine.py:_edge_score',
    source: 'proposal.edge_score, edge_status, edge_withheld_reason, edge_liquidity_penalty, edge_inputs.conviction_basis',
    forYou: 'A heuristic, not an expected return. Hidden when the contract fails the liquidity gate (edge_status WITHHELD_LIQUIDITY), because the inputs are not tradeable. Newer servers subtract a liquidity penalty: min(15, 0.75 × spread %), +3 if OI is under twice the floor, +2 if volume is 0. For protective puts the conviction input is a fixed placeholder.',
  },
  'term.tier': {
    term: 'Tier',
    plain: 'A grade from the edge score: A at 72 or more, B at 62 or more, otherwise C.',
    formula: 'edge ≥ 72 → A · edge ≥ 62 → B · else C',
    computedBy: 'scripts/options_desk_enterprise.py:desk_tier',
    source: 'proposal.desk_tier',
    forYou: 'Tier sorts ideas; it does not approve them.',
  },
  'term.sleeve': {
    term: 'Sleeve',
    plain: 'Where the idea came from: portfolio (shares you hold) or conviction (watchlist names).',
    source: 'proposal.sleeve, filter_facets.by_sleeve',
    forYou: 'Portfolio ideas use your shares; conviction ideas start new exposure.',
  },
  'term.assignment': {
    term: 'Assignment',
    plain: 'When the option buyer exercises: a sold put makes you buy 100 shares per contract at the strike; a sold call makes you sell them.',
    forYou: 'It can happen before expiry. Make sure the cash or shares are in the same account.',
  },

  // Strategies
  'strategy.covered_call': {
    term: 'Covered call',
    plain: 'Sell a call on shares you own. You collect premium and agree to sell at the strike.',
    formula: 'credit = premium × 100 × contracts · called-away price = strike + premium',
    computedBy: 'scripts/lib/options_economics.py:economics (credit_total, called_away_price_per_share)',
    forYou: 'Upside above the strike is given up; most of the downside stays with you.',
  },
  'strategy.cash_secured_put': {
    term: 'Cash-secured put',
    plain: 'Sell a put and hold the cash to buy 100 shares per contract at the strike if assigned.',
    formula: 'credit = premium × 100 × contracts · cash held = strike × 100 × contracts · effective price if assigned = strike − premium',
    computedBy: 'scripts/lib/options_economics.py:economics; scripts/lib/options_intent/ranking.py:rank_csp',
    forYou: 'Shown as premium/collateral and simple annualized, not reward/risk. The stock can fall far below your purchase price.',
  },
  'strategy.protective_put': {
    term: 'Protective put',
    plain: 'Buy a put on shares you own: insurance that pays below the strike until expiry.',
    formula: 'cost = premium × 100 × contracts · floor = (strike − premium) × insured shares',
    computedBy: 'scripts/lib/options_economics.py:economics',
    forYou: 'Negative expected value is normal for insurance; it is the price of the floor.',
  },
  'strategy.long_call': {
    term: 'Long call',
    plain: 'Buy the right to buy shares at the strike until expiry.',
    formula: 'cost = premium × 100 × contracts · breakeven = strike + premium',
    computedBy: 'scripts/lib/options_economics.py:_payoff',
    forYou: 'You can lose the whole premium.',
  },
  'strategy.long_put': {
    term: 'Long put',
    plain: 'Buy the right to sell shares at the strike until expiry, without owning them.',
    formula: 'cost = premium × 100 × contracts · breakeven = strike − premium',
    computedBy: 'scripts/lib/options_economics.py:_payoff',
    forYou: 'A bet on a fall. You can lose the whole premium.',
  },
  'strategy.leap_call': {
    term: 'LEAP',
    plain: 'A long-dated call (often more than a year) used as a stock substitute.',
    computedBy: 'scripts/lib/options_intent/ranking.py:rank_leaps',
    forYou: 'Controls 100 shares for less cash. No dividends or votes, and it can expire worthless.',
  },
  'strategy.pmcc': {
    term: 'PMCC (poor man\'s covered call)',
    plain: 'Sell short-dated calls against a LEAP instead of shares.',
    forYou: 'The LEAP must be approved by your broker as cover; a LEAP alone does not authorize a short call.',
  },
  'strategy.credit_spread': {
    term: 'Credit spread',
    plain: 'Sell one option and buy a further-out one; you collect a credit and the loss is capped.',
    formula: 'collateral = (short strike − long strike) × 100 × contracts · max loss = (width − credit) × 100 × contracts · breakeven = short strike − credit',
    computedBy: 'scripts/lib/options_economics.py:economics (credit_spread)',
    forYou: 'Credit is priced short leg at bid and long leg at ask when executable; a mid credit is not a fill. Floor: reward/risk at least 0.25.',
  },
  'strategy.debit_spread': {
    term: 'Debit spread',
    plain: 'Buy one option and sell a further-out one to lower the cost; gain and loss are both capped.',
    forYou: 'Advisory only on this desk.',
  },
  'strategy.collar': {
    term: 'Collar',
    plain: 'Own shares, buy a put and sell a call: a floor paid for by giving up upside.',
    forYou: 'Advisory only on this desk.',
  },

  // Workflow concepts
  'concept.thesis': {
    term: 'Thesis',
    plain: 'The written case for the idea: purpose, catalyst, exit criteria and what would make it wrong.',
    source: 'proposal.options_thesis (missing_required, pending_operator), proposal.thesis_state',
    forYou: 'An idea cannot be approved with required thesis fields missing.',
  },
  'concept.cio_decision': {
    term: 'CIO decision',
    plain: 'A recorded investment decision with its own Decision ID, for this strategy and account.',
    source: 'proposal.review_workflow.decision_guid, proposal.lifecycle.timeline',
    forYou: 'A model score is never a CIO decision. "Review failed" means the CIO step errored and must be re-run.',
  },
  'concept.aegis_review': {
    term: 'Aegis model review',
    plain: 'Several language models review the idea and vote. It is advice.',
    source: 'proposal.aegis_verdict, proposal.ensemble_verdict, options_decision_packet.model',
    forYou: 'A model vote is advice, not a decision. It never approves or places anything.',
  },
  'concept.standing_plan': {
    term: 'Standing plan',
    plain: 'Your saved plan for a ticker (for example: accumulate with cash-secured puts below a price). The matcher finds contracts that fit it.',
    source: '/api/v2/options/intents',
    forYou: 'A match is not staged: you still pick the account and size before it becomes an idea.',
  },
  'concept.plan_conflict': {
    term: 'Plan conflict',
    plain: 'The desk proposes something that works against your plan, such as insuring shares your plan says to accumulate.',
    source: 'intent_conflicts / intents[].conflicts when served (HEDGE_VS_ACCUMULATE, ACCUMULATE_VS_HEDGE); earnings_dates.conflict (dates more than 3 days apart)',
    forYou: 'Decide which one you mean. Both can be valid; the page will not choose for you.',
  },
  'concept.watch_only': {
    term: 'Not held · watch only',
    plain: 'You hold no shares of this ticker in any synced account.',
    source: 'intents[].watch_only, shares_held_total; else matches.shares_by_account',
    forYou: 'Covered calls are impossible without shares; only cash-backed or bought options apply.',
  },
  'concept.merged': {
    term: 'Accounts merged',
    plain: 'Ideas for the same contract in several accounts are shown as one row; contracts and cost are summed.',
    formula: 'group key = symbol · strategy · option type · strike · expiry',
    forYou: 'Each account is still decided and placed on its own.',
  },
  'concept.scenario': {
    term: 'If the stock falls',
    plain: 'Profit or loss at expiry if the stock moves by the shown percent: shares alone, shares with this trade, and the difference.',
    computedBy: 'scripts/lib/options_exposure.py (combined_exposure.scenarios) or economics.protection_scenarios',
    source: 'proposal.combined_exposure.scenarios, economics.protection_scenarios',
    forYou: 'Shares are marked from today\'s price, not your cost basis. Fees and slippage are excluded.',
  },
  'concept.checklist': {
    term: 'Checklist to place it',
    plain: 'Every condition that must be true before this idea can be placed. ✓ done · ✗ failing · ○ not yet.',
    forYou: 'The last two steps are always yours: your decision, then a fresh preflight and per-order 2FA.',
  },
  'concept.desk_path_b': {
    term: 'Desk Path B paper ledger',
    plain: 'A lab ledger of paper trades per strategy (target 30 closed trades each).',
    source: '/api/v2/options/validation desk_path_b_strategies',
    forYou: 'Paper results never unlock live trading.',
  },
  'concept.manual_log': {
    term: 'Manual execution log',
    plain: 'A record of option trades you placed yourself at the broker.',
    forYou: 'Record them so open positions and P/L stay accurate.',
  },

  // Lifecycle steps
  'lifecycle.found': {
    term: 'Found',
    plain: 'Names in the desk\'s inventory (holdings, watchlist, re-entry, research). Being found is not being evaluated.',
    source: 'proposals.coverage.inventory_count',
    forYou: 'Only a few are evaluated per scan; see Scan coverage.',
  },
  'lifecycle.research': {
    term: 'Needs research',
    plain: 'The idea\'s thesis is missing required fields.',
    source: 'review_workflow.state = NEEDS_RESEARCH',
    forYou: 'Owner: Research / CIO. Nothing for you to do until the thesis is complete.',
  },
  'lifecycle.data': {
    term: 'Needs data',
    plain: 'The quote is stale, too wide or illiquid, so the numbers cannot be trusted yet.',
    source: 'review_workflow.state = NEEDS_DATA or APPROVED_AWAITING_QUOTES',
    forYou: 'Re-quote during the regular session or pick another strike.',
  },
  'lifecycle.plan': {
    term: 'Not staged',
    plain: 'Contracts matching your standing plans that are not yet ideas for a specific account and size.',
    source: 'intents.unstaged_count',
    forYou: 'Stage one to pick the account and size; nothing is placed.',
  },
  'lifecycle.you': {
    term: 'Your decision',
    plain: 'Ideas waiting on a decision by you or the CIO, including ones held by a recorded policy block.',
    source: 'review_workflow.state = READY_FOR_REVIEW or BLOCKED',
    forYou: 'Open it, read the checklist, then decide.',
  },
  'lifecycle.place': {
    term: 'Ready to place',
    plain: 'Approved ideas ready for a fresh preflight and your per-order 2FA.',
    source: 'review_workflow.state = READY_FOR_PREFLIGHT',
    forYou: 'You place each order yourself. The page never submits one.',
  },
  'lifecycle.open': {
    term: 'Open',
    plain: 'Option positions currently held at the broker.',
    source: '/api/v2/options/open-positions position_count',
    forYou: 'Manage them in the Lifecycle view; close or roll at the broker and record it in the manual log.',
  },

  // Freshness chips
  'fresh.market': {
    term: 'Market session',
    plain: 'The trading session the server reports: regular, pre-market, after hours or closed.',
    source: 'proposals.market_session, market_session_as_of, snapshot (generated_at, age_s, next_scheduled_refresh, refresh_paused)',
    forYou: 'The page says "closed" only when the server says so. Outside the regular session quotes are not executable. The ideas themselves come from a snapshot that may be older; its time is in this tooltip.',
  },
  'fresh.stock_quotes': {
    term: 'Stock quotes',
    plain: 'The time each idea\'s stock price was read. The chip shows the oldest.',
    source: 'underlying_price_time (underlying_price_time_basis), else price_source.as_of',
    forYou: 'Each idea shows its own quote time in the detail panel. "Fetch time" means the provider\'s own time was not recorded, so the real age may be larger.',
  },
  'fresh.option_chain': {
    term: 'Option chains',
    plain: 'How old the option chain behind each idea is. The chip shows the oldest.',
    formula: 'chain_age_seconds = now − chain fetched_at',
    computedBy: 'scripts/options_desk_enterprise.py:evaluate_hard_risk_blocks (cap 300 s by default)',
    source: 'chain_age_s (served at request time) or chain_age_seconds, chain_fetched_at',
    forYou: 'Older than the cap blocks the idea until it is re-quoted.',
  },
  'fresh.holdings': {
    term: 'Holdings',
    plain: 'When your share holdings were last synced from the broker.',
    source: 'proposals.coverage.source_receipts.holdings (or a served holdings-freshness field)',
    forYou: 'If a stop filled or you traded today, the share counts here can be wrong until the next sync.',
  },
  'fresh.scan_coverage': {
    term: 'Scan coverage',
    plain: 'How many inventory names have actually been evaluated for options.',
    source: 'coverage.status_counts.EVALUATED, coverage.inventory_count, coverage.not_scanned, coverage.pending_evaluation_count, scan_status',
    forYou: 'A short list of ideas usually means few names were scanned, not that the market has nothing.',
  },
  'exec.state': {
    term: 'Execution state',
    plain: 'Whether the broker route for options is open, and whether any idea is eligible.',
    source: 'proposals.execution_state_text (when served) or /api/v2/options/execution/status',
    forYou: 'Even with the route open, nothing is placed without your decision, a fresh preflight and per-order 2FA.',
  },

  // Blocker reasons
  'blocker.awaiting_cio_decision': { term: 'Awaiting CIO decision', plain: 'No CIO decision has been issued for this strategy and account.', source: 'enterprise.blocks[].code', forYou: 'The CIO review must run and record a decision first.' },
  'blocker.cio_review_failed': { term: 'CIO review failed', plain: 'The CIO review step ran and errored (for example POLICY_NOT_ALLOWED). After the failure cap (REVIEW_FAILURE_CAP) it stops retrying.', source: 'review_failures, review_failure_reason, lifecycle_stage; else lifecycle.timeline', forYou: 'It is a failure, not a rejection. Below the cap it retries; at the cap an operator must reopen it.' },
  'blocker.quote_stale': { term: 'Quote stale', plain: 'The contract quote is older than the cap (120 s by default).', computedBy: 'scripts/options_desk_enterprise.py:evaluate_hard_risk_blocks', source: 'proposal.quote_age_seconds', forYou: 'Re-quote during the regular session.' },
  'blocker.option_chain_stale': { term: 'Chain stale', plain: 'The option chain is older than the cap (300 s by default).', computedBy: 'scripts/options_desk_enterprise.py:evaluate_hard_risk_blocks', source: 'proposal.chain_age_seconds', forYou: 'Re-quote during the regular session.' },
  'blocker.quote_age_unknown': { term: 'Quote age unknown', plain: 'The contract has no quote time, so its age cannot be checked.', forYou: 'Treated as stale until re-quoted.' },
  'blocker.chain_age_unknown': { term: 'Chain age unknown', plain: 'The chain has no fetch time, so its age cannot be checked.', forYou: 'Treated as stale until re-quoted.' },
  'blocker.market_session_unknown': { term: 'Session unknown', plain: 'The proposal carries no market session.', forYou: 'Re-quote so the session is recorded.' },
  'blocker.market_closed': { term: 'Market closed', plain: 'The server reports the market is not in the regular session.', forYou: 'Quotes are not executable until the open.' },
  'blocker.wide_spread': { term: 'Quote too wide', plain: 'The bid/ask spread is above the 12% desk cap.', computedBy: 'scripts/options_desk_enterprise.py:liquidity_gate', source: 'enterprise.liquidity.issues', forYou: 'Re-quote; if it stays wide, choose another strike or expiry.' },
  'blocker.low_open_interest': { term: 'Low open interest', plain: 'Fewer than 50 contracts open.', computedBy: 'scripts/options_desk_enterprise.py:liquidity_gate', source: 'enterprise.liquidity.issues', forYou: 'Choose a more traded strike or expiry.' },
  'blocker.low_volume': { term: 'Low volume', plain: 'Fewer than 5 contracts traded today; checked only when open interest is under 100.', computedBy: 'scripts/options_desk_enterprise.py:liquidity_gate', source: 'enterprise.liquidity.issues', forYou: 'Check again later in the session.' },
  'blocker.liquidity_unknown': { term: 'Liquidity unknown', plain: 'The desk could not read OI, volume or spread.', forYou: 'Re-quote.' },
  'blocker.thesis_missing': { term: 'Thesis incomplete', plain: 'A required thesis field (such as exit criteria) is missing.', source: 'options_thesis.missing_required', forYou: 'Research must complete it before approval.' },
  'blocker.thesis_required': { term: 'Thesis required', plain: 'No options thesis is on file.', forYou: 'Research must write one.' },
  'blocker.earnings_blackout': { term: 'Earnings blackout', plain: 'Expiry falls inside the earnings blackout window (14 days by default).', source: 'enterprise.earnings', forYou: 'Pick an expiry before earnings or accept the event risk.' },
  'blocker.portfolio_risk': { term: 'Portfolio risk limit', plain: 'The idea would breach a desk risk limit (net delta, symbol notional, per-strategy notional or contracts per order).', forYou: 'Size down or pick a different idea.' },
  'blocker.buying_power': { term: 'Buying power', plain: 'Buying power is unknown or below the minimum.', forYou: 'Check the account cash before staging.' },
  'blocker.no_resolved_occ': { term: 'Contract unresolved', plain: 'The exact listed contract (OCC symbol) could not be resolved.', forYou: 'Re-quote or pick another strike.' },
  'blocker.holdings_unverified': { term: 'Holdings unverified', plain: 'Today\'s share count may not match the broker (for example after a stop filled).', forYou: 'Wait for the next holdings sync before deciding.' },
  'blocker.not_staged': { term: 'Not staged', plain: 'A plan match without an account and size.', forYou: 'Stage it to pick both.' },
  'blocker.other': { term: 'Other block', plain: 'A recorded block the page has no plain-English label for yet. Its raw reason is shown.', forYou: 'Open the idea for the full reason.' },
}

/** Every key the desk renders must resolve. Unknown keys fall back to `blocker.other`. */
export function glossary(key: string): GlossaryEntry {
  return GLOSSARY[key] || GLOSSARY['blocker.other']
}

export function hasGlossary(key: string): boolean {
  return Object.prototype.hasOwnProperty.call(GLOSSARY, key)
}

/** Plain-text tooltip body (used for aria descriptions and native fallbacks). */
export function glossaryText(key: string): string {
  const g = glossary(key)
  return [g.plain, g.formula ? `How: ${g.formula}.` : '', g.forYou].filter(Boolean).join(' ')
}

/** The "How this page works" help panel copy. */
export const HOW_THIS_PAGE_WORKS = {
  lifecycle: [
    'Every options idea moves left to right through seven steps, from Found to Open.',
    'The scanner finds names; research and the CIO write the thesis; quote validation makes the numbers trustworthy.',
    'Plan matches wait in Not staged until you pick an account and size.',
    'An idea reaches Your decision when only a human decision is left, and Ready to place once it is approved.',
    'You place each order yourself, after a fresh preflight and per-order 2FA; then it shows as Open.',
  ],
  readIdea: 'Each row is one idea: one contract, with accounts merged. "What it does" says the effect in plain English, "Cost" is the cash paid (or + credit received), and "Stuck on" names the first thing blocking it. Click the row for the full picture.',
  checklist: '✓ means the condition is met, ✗ means it is failing and says what to do, ○ means it has not happened yet. The last two items are always yours.',
  never: 'The system never sizes, orders, stops, rolls or closes an option on its own. It never treats a model vote as a decision, and it never places an order without your per-order 2FA.',
}

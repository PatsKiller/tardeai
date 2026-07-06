/**
 * Novice-friendly options education — advisory copy only; no execution paths.
 */
import { fmt$ } from './format'
import { cashflowIsCredit, executionRouteBadge, isPaperModelRow, optionCashflowLabel } from './optionsCardSemantics'

export type EducationCard = {
  strategy: string
  symbol: string
  underlying?: string
  strike?: number
  expiration?: string
  dte?: number
  premium?: number
  premium_total?: number
  contracts?: number
  breakeven?: number
  max_profit?: number | string
  max_loss?: number | string
  option_type?: string
  side?: string
  underlying_price?: number
  delta?: number
  educational_paper_model?: boolean
  alpaca_paper_enabled?: boolean
  broker?: string
  execution_route_kind?: string
  enterprise?: { live_eligible?: boolean }
  short_strike?: number
  long_strike?: number
  execution_route?: string
  execution_route_badge?: string
  advice_label?: string
  entry_fill_price?: number
  mark?: number
  unrealized_pnl?: number
  entry_iv?: number
  iv?: number
  paper_only?: boolean
  position_source?: string
}

export type OptionEducation = {
  title: string
  oneLineSummary: string
  tradeType: string
  legs: string
  direction: string
  cashflow: string
  goal: string
  maxGain: string
  maxLoss: string
  breakeven: string
  whatNeedsToHappen: string
  whatCanGoWrong: string[]
  whatToMonitor: string[]
  warningSigns: string[]
  noviceGlossary: { term: string; def: string }[]
  paperOrLiveExplanation: string
  beginnerSummary: string
  stockMoveScenarios: { heading: string; bullets: string[] }[]
  monitorChecklist: string[]
  sections: {
    tradeType: string
    buyingSelling: string
    whyUse: string
    howMakeMoney: string
    howLoseMoney: string
    whatToMonitor: string
    numbersMean: string
    paperLive: string
  }
}

export const NOVICE_GLOSSARY: { term: string; def: string }[] = [
  { term: 'Call', def: 'Right to buy 100 shares at the strike before expiration.' },
  { term: 'Put', def: 'Right to sell 100 shares at the strike before expiration.' },
  { term: 'Strike', def: 'The price where the option contract is anchored.' },
  { term: 'Expiration', def: 'The date the option ends.' },
  { term: 'Premium', def: 'The price per share of the option (one contract = 100 shares).' },
  { term: 'Total debit', def: 'Cash paid to enter the trade.' },
  { term: 'Total credit', def: 'Cash collected to enter the trade.' },
  { term: 'Breakeven', def: 'Price where the trade starts to make money at expiration.' },
  { term: 'Delta', def: 'How much the option tends to move when the stock moves $1. Higher delta means more stock-like.' },
  { term: 'Theta', def: 'Estimated daily time decay. This usually hurts option buyers.' },
  { term: 'IV', def: 'Implied volatility. Higher IV usually means more expensive options.' },
  { term: 'DTE', def: 'Days until expiration.' },
  { term: 'OI', def: 'Open interest. Low OI can mean the contract is hard to trade.' },
  { term: 'Bid/ask spread', def: 'The gap between buyers and sellers. Wide spreads can make entry/exit expensive.' },
  { term: 'Assignment', def: 'When an option seller is required to buy or sell shares.' },
  { term: 'ITM / OTM', def: 'In-the-money = profitable to exercise now. Out-of-the-money = not profitable to exercise.' },
]

type StratEdu = {
  title: string
  tradeType: string
  legs: string
  direction: string
  cashflowKind: 'debit' | 'credit'
  goal: string
  maxGainHint: string
  maxLossHint: string
  needs: string
  wrong: string[]
  monitor: string[]
  warnings: string[]
  whyUse: string
  howWin: string
  howLose: string
  beginnerTemplate: string
  stockMoves: { rise: string[]; flat: string[]; fall: string[]; catalyst?: string[] }
  monitorChecklist: string[]
}

const STRATEGY_EDU: Record<string, StratEdu> = {
  deep_itm_call: {
    title: 'Deep ITM Call — stock replacement paper model',
    tradeType: 'Buy call (deep in-the-money)',
    legs: '1 long call contract',
    direction: 'Buy call',
    cashflowKind: 'debit',
    goal: 'Stock-like upside exposure while using less cash than buying 100 shares.',
    maxGainHint: 'Uncapped upside above breakeven (minus spread and time decay).',
    maxLossHint: 'Maximum loss is the debit paid for the option.',
    needs: 'The underlying needs to stay above breakeven by expiration, or the option needs to gain value before you close it.',
    wrong: [
      'The stock can fall and the option can lose value.',
      'Time decay can reduce the option’s value even if the stock is flat.',
      'Wide bid/ask spreads can make exits expensive.',
      'Earnings or catalysts before expiration can cause sharp moves.',
      'If the option expires below breakeven, the paper trade may lose money.',
      'The entire debit can be lost.',
    ],
    monitor: [
      'Stock price vs entry price',
      'Option mark / current value',
      'Unrealized P/L',
      'Delta — how stock-like the option still is',
      'Theta — daily time decay',
      'IV — whether volatility is rising or falling',
      'Bid/ask spread — whether the contract is still tradable',
      'DTE — days left until expiration',
      'Earnings date',
      'Breakeven price',
      'Lifecycle monitor advice label (after fill)',
    ],
    warnings: [
      'Delta falls — option becomes less stock-like',
      'Wide spread or stale quote',
      'Advisory label moves to WATCH or CONSIDER CLOSE',
      'Earnings before expiration',
    ],
    whyUse: 'Review this when you want stock-like upside with less capital than buying 100 shares outright.',
    howWin: 'The stock rises or the option mark increases enough to overcome the debit paid.',
    howLose: 'The stock falls, time decay erodes value, or you exit into a wide spread.',
    beginnerTemplate: 'Buy {n} call, pay {cash}, get stock-like upside exposure, max option loss {cash}',
    stockMoves: {
      rise: [
        'The option should usually gain value.',
        'Higher delta means it may move somewhat like the stock.',
        'You still need to watch bid/ask spread and time decay.',
      ],
      flat: [
        'Time decay may slowly hurt the position.',
        'The option can still lose value even if the stock does not move much.',
      ],
      fall: [
        'The option loses value.',
        'Loss is limited to the debit paid in the paper model.',
        'If delta falls, it becomes less stock-like.',
      ],
      catalyst: [
        'Price may gap sharply around the event.',
        'IV may change quickly.',
        'After fill, the paper monitor watches P/L, IV, spread, and advisory labels.',
      ],
    },
    monitorChecklist: [
      'Current option value',
      'Unrealized P/L',
      'Stock price vs entry',
      'Breakeven',
      'Delta',
      'Theta',
      'IV',
      'Bid/ask spread',
      'DTE',
      'Earnings / catalyst date',
      'Lifecycle monitor advice label',
    ],
  },
  atm_call: {
    title: 'ATM Call — bullish directional',
    tradeType: 'Buy call (at-the-money)',
    legs: '1 long call contract',
    direction: 'Buy call',
    cashflowKind: 'debit',
    goal: 'Profit if the stock rises enough before expiration.',
    maxGainHint: 'Uncapped upside above breakeven.',
    maxLossHint: 'Can lose the entire premium paid.',
    needs: 'The stock must rise above breakeven before time decay dominates.',
    wrong: ['Stock stays flat or falls.', 'Theta decay accelerates near expiration.', 'IV crush after events can hurt call value.'],
    monitor: ['Stock move vs breakeven', 'Theta decay', 'IV crush', 'Breakeven', 'DTE', 'Bid/ask spread'],
    warnings: ['DTE under 14', 'IV falling vs entry', 'Wide spread'],
    whyUse: 'Review for a defined-risk bullish directional paper test.',
    howWin: 'Stock rises materially above strike + premium before expiry.',
    howLose: 'Stock does not rise enough; premium decays to zero.',
    beginnerTemplate: 'Buy {n} call, pay {cash}, profit only if the stock rises enough before time decay hurts',
    stockMoves: {
      rise: ['Call gains if move exceeds breakeven.', 'Gamma can accelerate near the strike.'],
      flat: ['Theta usually hurts buyers.', 'Value can drift lower even without a big stock drop.'],
      fall: ['Premium can decay toward zero.', 'Max loss is the debit paid.'],
    },
    monitorChecklist: ['Stock move', 'Breakeven distance', 'Theta', 'IV', 'DTE', 'Spread', 'P/L'],
  },
  atm_put: {
    title: 'ATM Put — bearish directional or hedge review',
    tradeType: 'Buy put (at-the-money)',
    legs: '1 long put contract',
    direction: 'Buy put',
    cashflowKind: 'debit',
    goal: 'Profit if the stock falls enough before expiration, or hedge review on existing shares.',
    maxGainHint: 'Large downside move can increase put value substantially.',
    maxLossHint: 'Can lose the entire premium paid.',
    needs: 'The stock must fall below breakeven before time decay dominates.',
    wrong: ['Stock rises or stays flat.', 'Theta decay.', 'IV changes can hurt or help unpredictably.'],
    monitor: ['Stock move lower', 'Theta decay', 'IV', 'Breakeven', 'DTE'],
    warnings: ['Short DTE', 'IV crush after events', 'Stale quotes'],
    whyUse: 'Review for bearish directional exposure or downside hedge context.',
    howWin: 'Stock falls below breakeven; put value rises.',
    howLose: 'Stock does not cooperate; premium decays.',
    beginnerTemplate: 'Buy {n} put, pay {cash}, profit if the stock falls enough before expiration',
    stockMoves: {
      rise: ['Put usually loses value.', 'Max loss is premium paid.'],
      flat: ['Time decay hurts long puts.', 'Watch DTE closely.'],
      fall: ['Put can gain if move is large enough.', 'Spread width matters on exit.'],
    },
    monitorChecklist: ['Stock move', 'Put value', 'Theta', 'IV', 'Breakeven', 'DTE', 'P/L'],
  },
  covered_call: {
    title: 'Covered Call — income on shares owned',
    tradeType: 'Sell call against shares owned',
    legs: 'Long stock + short call',
    direction: 'Sell call',
    cashflowKind: 'credit',
    goal: 'Collect income; accept capped upside on shares you already own.',
    maxGainHint: 'Premium collected plus any stock gain up to the strike if assigned.',
    maxLossHint: 'Stock can still fall; upside is capped at the strike.',
    needs: 'Stock stays at or below the strike through expiration, or you buy back the call profitably.',
    wrong: ['Stock rallies above strike — upside capped or shares called away.', 'Stock falls — premium only partially offsets loss.'],
    monitor: ['Stock price vs strike', 'Assignment risk', 'Ex-dividend date', 'DTE', 'Remaining credit'],
    warnings: ['Call goes in-the-money', 'Ex-dividend before expiry', 'Wide spread on buyback'],
    whyUse: 'Review when you own shares and want to consider income with capped upside.',
    howWin: 'Collect credit; stock stays below strike or you manage the call.',
    howLose: 'Stock drops more than premium collected; or rally caps upside.',
    beginnerTemplate: 'Sell calls against shares you own, collect {cash}, but cap upside',
    stockMoves: {
      rise: ['Call may go in-the-money — assignment risk rises.', 'Upside above strike may be forgone.'],
      flat: ['Often favorable for short-call income strategies.', 'Watch time decay helping the short call.'],
      fall: ['Stock loss can exceed premium collected.', 'Review whether hedge is needed.'],
    },
    monitorChecklist: ['Stock vs strike', 'Assignment risk', 'Remaining credit', 'DTE', 'Ex-dividend', 'Liquidity'],
  },
  cash_secured_put: {
    title: 'Cash-Secured Put — income or buy lower',
    tradeType: 'Sell put with cash reserved',
    legs: 'Short put (cash secured)',
    direction: 'Sell put',
    cashflowKind: 'credit',
    goal: 'Collect income, or potentially buy stock at the strike if assigned.',
    maxGainHint: 'Keep the credit if the put expires worthless.',
    maxLossHint: 'May be assigned shares; stock can fall below breakeven.',
    needs: 'Stock stays above the strike, or you are willing to own shares at the strike.',
    wrong: ['Assignment if stock falls through strike.', 'Stock can fall far below strike after assignment.'],
    monitor: ['Stock vs strike', 'Buying power / cash reserved', 'Assignment risk', 'DTE'],
    warnings: ['Put in-the-money', 'Earnings gap risk', 'Low liquidity'],
    whyUse: 'Review when you might want income or to buy stock lower — only on names you would own.',
    howWin: 'Keep credit; put expires OTM.',
    howLose: 'Assigned at strike into a falling stock.',
    beginnerTemplate: 'Sell a put, collect {cash}, but you may have to buy shares if the stock falls',
    stockMoves: {
      rise: ['Put usually loses value — credit working.', 'Assignment risk falls.'],
      flat: ['Time decay helps short premium.', 'Watch distance to strike.'],
      fall: ['Assignment risk rises.', 'May need to buy stock at strike.'],
    },
    monitorChecklist: ['Stock vs strike', 'Assignment risk', 'Remaining credit', 'DTE', 'Liquidity', 'Cash reserved'],
  },
  protective_put: {
    title: 'Protective Put — downside hedge',
    tradeType: 'Buy put as hedge',
    legs: 'Long stock + long put (hedge leg on card)',
    direction: 'Buy put',
    cashflowKind: 'debit',
    goal: 'Offset some stock losses if price falls.',
    maxGainHint: 'Put value can rise if stock falls sharply.',
    maxLossHint: 'Hedge premium can decay to zero; stock can still fall.',
    needs: 'Stock drawdown large enough that put gains offset hedge cost.',
    wrong: ['Premium decays if stock rises or stays flat.', 'Hedge may not fully cover gap risk.'],
    monitor: ['Hedge effectiveness', 'Underlying drawdown', 'Put value', 'Theta', 'DTE', 'IV'],
    warnings: ['Put OTM with short DTE', 'IV crush', 'Stock gaps through strike'],
    whyUse: 'Review as insurance on shares you hold — costs money but may offset losses.',
    howWin: 'Stock falls; put value rises enough to offset hedge cost.',
    howLose: 'Premium decays while stock does not fall enough.',
    beginnerTemplate: 'Buy a put as insurance. It costs {cash} but can offset stock losses',
    stockMoves: {
      rise: ['Put usually loses value.', 'You paid for protection you may not use.'],
      flat: ['Theta erodes hedge value.', 'Review if protection is still worth cost.'],
      fall: ['Put may offset some stock loss.', 'Check effective hedge vs premium paid.'],
    },
    monitorChecklist: ['Hedge effectiveness', 'Underlying drawdown', 'Put value', 'Theta', 'IV', 'DTE', 'Breakeven'],
  },
  credit_spread: {
    title: 'Credit Spread — defined-risk income',
    tradeType: 'Sell one option, buy farther option',
    legs: 'Short leg + long leg (same expiry)',
    direction: 'Net short premium',
    cashflowKind: 'credit',
    goal: 'Collect net credit with capped max loss.',
    maxGainHint: 'Keep net credit if price stays away from short strike.',
    maxLossHint: 'Max loss if price moves through the spread width.',
    needs: 'Price stays on the profitable side of the short strike through expiration.',
    wrong: ['Price moves through short strike.', 'Assignment risk on short leg.', 'Gap risk on credit structures.'],
    monitor: ['Short strike distance', 'Long strike protection', 'Spread mark', 'Max gain / max loss', 'DTE'],
    warnings: ['Short strike threatened', 'Wide spread marks', 'Assignment risk'],
    whyUse: 'Review for defined-risk income with known max loss.',
    howWin: 'Spread expires worthless or is closed for less than credit received.',
    howLose: 'Price moves against short strike toward max loss.',
    beginnerTemplate: 'Collect {cash} with capped risk — want price to stay away from the short strike',
    stockMoves: {
      rise: ['Effect depends on call vs put spread — review short strike side.'],
      flat: ['Often helps short premium spreads.', 'Watch spread mark and DTE.'],
      fall: ['Put credit spreads face assignment/gap risk.', 'Monitor short strike distance.'],
    },
    monitorChecklist: ['Short strike distance', 'Spread mark', 'Max gain / max loss', 'Assignment risk', 'DTE', 'Liquidity'],
  },
  debit_spread: {
    title: 'Debit Spread — directional with capped risk',
    tradeType: 'Buy one option, sell farther option',
    legs: 'Long leg + short leg (same expiry)',
    direction: 'Net long premium',
    cashflowKind: 'debit',
    goal: 'Directional move with capped loss and capped profit.',
    maxGainHint: 'Capped at spread width minus debit.',
    maxLossHint: 'Max loss is the net debit paid.',
    needs: 'Price moves toward breakeven before expiration.',
    wrong: ['Wrong direction.', 'Time decay on debit spreads.', 'IV changes hurt or help.'],
    monitor: ['Price vs breakeven', 'Spread value', 'DTE', 'IV'],
    warnings: ['Short DTE', 'Spread mark diverges from model', 'Stale quotes'],
    whyUse: 'Review for directional exposure with known max loss and max gain.',
    howWin: 'Spread value expands toward max profit.',
    howLose: 'Debit lost if spread expires worthless.',
    beginnerTemplate: 'Pay {cash} for a directional bet with capped loss and capped gain',
    stockMoves: {
      rise: ['Bullish debit spreads benefit if call-side.', 'Watch breakeven vs spot.'],
      flat: ['Time decay hurts net debit positions.', 'Review DTE.'],
      fall: ['Bearish put debit spreads may benefit.', 'Max loss still capped at debit.'],
    },
    monitorChecklist: ['Breakeven', 'Spread mark', 'Max gain / max loss', 'DTE', 'IV', 'P/L'],
  },
  earnings_put_debit_spread: {
    title: 'Earnings Put Debit Spread — defined-risk event downside',
    tradeType: 'Bearish put debit spread around earnings',
    legs: 'Long put + short lower put',
    direction: 'Buy put spread (net debit)',
    cashflowKind: 'debit',
    goal: 'Defined-risk downside move into or after earnings.',
    maxGainHint: 'Capped profit if stock falls through the spread.',
    maxLossHint: 'Lose net debit if the expected move does not happen.',
    needs: 'A downside move large enough to overcome debit; watch IV crush after event.',
    wrong: ['No move or wrong-way move.', 'IV crush after earnings.', 'Wide quotes into the event.'],
    monitor: ['Earnings date', 'Implied move vs historical', 'IV crush', 'Stock gap', 'Breakeven'],
    warnings: ['Event tonight/tomorrow', 'IV rich pay-up', 'Thin history on move stats'],
    whyUse: 'Review only as a paper/event-risk model — not a live recommendation.',
    howWin: 'Stock gaps down enough that spread reaches max profit zone.',
    howLose: 'Flat or up move; IV crush erodes spread value.',
    beginnerTemplate: 'Pay {cash} for a defined-risk earnings downside paper model',
    stockMoves: {
      rise: ['Usually hurts bearish put debit spread.', 'Max loss capped at debit.'],
      flat: ['IV crush after earnings can hurt.', 'Review implied vs realized move.'],
      fall: ['May benefit if move exceeds breakeven.', 'Watch spread mark into close.'],
      catalyst: ['Earnings is the main catalyst.', 'Gap and IV change dominate P/L.'],
    },
    monitorChecklist: ['Earnings date', 'Implied move', 'IV crush', 'Gap vs breakeven', 'Spread mark', 'DTE'],
  },
  earnings_put_credit_spread: {
    title: 'Earnings Put Credit Spread — neutral/bullish event income',
    tradeType: 'Put credit spread around earnings',
    legs: 'Short put + long lower put',
    direction: 'Sell put spread (net credit)',
    cashflowKind: 'credit',
    goal: 'Collect credit; want stock to stay above short put through event.',
    maxGainHint: 'Keep net credit if spread expires OTM.',
    maxLossHint: 'Gap risk and assignment risk if stock falls through short strike.',
    needs: 'Stock stays above short strike; manage gap risk around earnings.',
    wrong: ['Gap below short strike.', 'Assignment on short leg.', 'IV and liquidity around event.'],
    monitor: ['Short strike distance', 'Earnings gap', 'IV crush', 'Assignment risk'],
    warnings: ['Credit lane not enabled for auto paper in all configs', 'Gap risk disclosure', 'Assignment risk'],
    whyUse: 'Review as event-income paper model with explicit gap/assignment disclosures.',
    howWin: 'Stock holds above short strike; keep credit.',
    howLose: 'Gap through short strike toward max loss.',
    beginnerTemplate: 'Collect {cash}; want stock to stay above short put through earnings',
    stockMoves: {
      rise: ['Generally helps short put spreads.', 'Still watch gap risk into print.'],
      flat: ['May keep credit if above short strike.', 'IV crush affects mark.'],
      fall: ['Gap risk through short strike.', 'Assignment risk rises.'],
      catalyst: ['Earnings gap is primary risk.', 'Review distance to short strike pre-event.'],
    },
    monitorChecklist: ['Short strike distance', 'Earnings gap', 'IV crush', 'Assignment risk', 'Spread mark', 'DTE'],
  },
  long_call: {
    title: 'Long Call — bullish directional',
    tradeType: 'Buy call',
    legs: '1 long call contract',
    direction: 'Buy call',
    cashflowKind: 'debit',
    goal: 'Profit if stock rises before expiration.',
    maxGainHint: 'Uncapped above breakeven.',
    maxLossHint: 'Entire premium paid.',
    needs: 'Stock rises above breakeven in time.',
    wrong: ['Time decay.', 'Stock flat or down.', 'Wide spreads.'],
    monitor: ['Stock vs breakeven', 'Theta', 'DTE', 'IV', 'P/L'],
    warnings: ['Short DTE', 'Stale quote'],
    whyUse: 'Review bullish directional exposure with defined max loss.',
    howWin: 'Stock rises above breakeven.',
    howLose: 'Premium decays.',
    beginnerTemplate: 'Buy {n} call, pay {cash}, bullish directional paper review',
    stockMoves: {
      rise: ['Call value may rise if above breakeven.'],
      flat: ['Theta hurts buyers.'],
      fall: ['Max loss is premium paid.'],
    },
    monitorChecklist: ['Stock move', 'Breakeven', 'Theta', 'IV', 'DTE', 'P/L'],
  },
}

function fmtCash(total?: number, per?: number, contracts = 1): string {
  if (total != null) return fmt$(total, total < 10000 ? 0 : 0)
  if (per != null) return fmt$(per * 100 * contracts, 0)
  return 'a premium'
}

function paperLiveExplanation(card: EducationCard): string {
  const ext = card as EducationCard & Record<string, unknown>
  const route = executionRouteBadge(ext as any)
  if (isPaperModelRow(ext as any) || card.educational_paper_model || card.paper_only) {
    if (card.alpaca_paper_enabled || route.kind === 'alpaca_paper' || card.broker === 'alpaca') {
      return 'This is Alpaca paper only. It is a simulated 1-contract limit order path for review. It does not place a live broker order. Validation credit starts only after fill, close, and outcome reconciliation.'
    }
    return 'This is a paper model row for education and review. No live broker order path. Use View Chain and paper testing workflows only.'
  }
  if (route.kind === 'fidelity_manual') {
    return 'Fidelity manual ticket only — you would enter the trade yourself in the broker. This desk does not auto-submit.'
  }
  if (route.kind === 'schwab_live' && card.enterprise?.live_eligible) {
    return 'Schwab live path may be available only after operator review, 2FA, and broker preview/read-back. Nothing auto-submits from this card.'
  }
  return 'Review only on this card — no automatic live order path. Use View Chain before any manual action.'
}

function deepItmPlainEnglish(card: EducationCard, sym: string, strike?: number): string {
  const lines = [
    `This is a call option. A call gives you the right, but not the obligation, to buy 100 shares of ${sym} at the strike price before expiration.`,
    strike != null
      ? `This specific trade is a deep in-the-money call. The strike ($${strike}) is below the current stock price, so the option already behaves somewhat like owning the stock. That is why this strategy is called “stock replacement.”`
      : 'This is a deep in-the-money call — it behaves somewhat like owning the stock with less capital.',
    `You are buying ${card.contracts ?? 1} call contract(s). You pay a debit upfront. That debit is the most the option itself can lose in this paper model.`,
  ]
  return lines.join('\n\n')
}

export function buildBeginnerSummary(card: EducationCard): string {
  const s = (card.strategy || '').toLowerCase()
  const edu = STRATEGY_EDU[s] || STRATEGY_EDU.long_call
  const n = card.contracts ?? 1
  const cash = fmtCash(card.premium_total, card.premium, n)
  let text = edu.beginnerTemplate.replace('{n}', String(n)).replace('{cash}', cash)
  if (isPaperModelRow(card as any) || card.educational_paper_model || card.paper_only) {
    text += ', paper only'
  }
  return `Beginner view: ${text}.`
}

export function buildStockMoveScenarios(strategy: string, symbol: string): { heading: string; bullets: string[] }[] {
  const edu = STRATEGY_EDU[strategy] || STRATEGY_EDU.long_call
  const out: { heading: string; bullets: string[] }[] = [
    { heading: `If ${symbol} rises`, bullets: edu.stockMoves.rise },
    { heading: `If ${symbol} stays flat`, bullets: edu.stockMoves.flat },
    { heading: `If ${symbol} falls`, bullets: edu.stockMoves.fall },
  ]
  if (edu.stockMoves.catalyst?.length) {
    out.push({ heading: 'If earnings or a catalyst happens', bullets: edu.stockMoves.catalyst })
  }
  return out
}

export function buildMonitorChecklist(strategy: string): string[] {
  return STRATEGY_EDU[strategy]?.monitorChecklist || STRATEGY_EDU.long_call.monitorChecklist
}

export function explainAdviceLabel(label?: string): string {
  const l = String(label || '').toUpperCase()
  const map: Record<string, string> = {
    HOLD_PAPER: 'Within monitor thresholds — continue watching; no advisory change suggested.',
    WATCH_PAPER: 'Something needs attention (spread, DTE, IV, etc.) — review before acting.',
    CONSIDER_CLOSE_PAPER: 'Profit target or risk threshold reached on paper — consider closing for review, not an auto-order.',
    CONSIDER_ROLL_PAPER: 'DTE or thesis suggests a roll may be worth reviewing — operator decision only.',
    OUTCOME_READY: 'Broker shows closed — record outcome in desk when ready.',
    DATA_STALE: 'Quote unavailable — do not rely on marks until chain is fresh.',
    QUOTE_UNTRADABLE: 'Missing bid/ask — treat marks as unreliable.',
  }
  return map[l] || 'Lifecycle monitor label — advisory only, no auto-submit.'
}

export function buildOptionEducation(card: EducationCard): OptionEducation {
  const s = (card.strategy || 'long_call').toLowerCase()
  const edu = STRATEGY_EDU[s] || STRATEGY_EDU.long_call
  const sym = card.symbol || card.underlying || 'the stock'
  const cfLabel = optionCashflowLabel(card.strategy, card.side)
  const isCredit = cashflowIsCredit(card.strategy, card.side)
  const cash = fmtCash(card.premium_total, card.premium, card.contracts ?? 1)
  const be = card.breakeven != null ? `$${card.breakeven.toFixed(2)}` : 'see Breakeven on card'
  const optType = (card.option_type || (s.includes('put') ? 'put' : 'call')).toLowerCase()

  const tradeTypeDetail = s === 'deep_itm_call'
    ? deepItmPlainEnglish(card, sym, card.strike)
    : `${edu.tradeType}. Option type: ${optType}. ${edu.legs}.`

  const numbersMean = [
    `Premium: price per share of the option (×100 per contract).`,
    `${cfLabel}: ${cash} for ${card.contracts ?? 1} contract(s).`,
    `Breakeven: ${be} — where the modeled trade crosses zero at expiration.`,
    card.delta != null ? `Delta ${card.delta.toFixed(2)}: approximate $ move per $1 stock move.` : 'Delta: stock sensitivity (higher = more stock-like).',
    card.dte != null ? `DTE ${card.dte}: days until expiration.` : 'DTE: days until expiration.',
  ].join(' ')

  return {
    title: edu.title,
    oneLineSummary: buildBeginnerSummary(card),
    tradeType: edu.tradeType,
    legs: edu.legs,
    direction: edu.direction,
    cashflow: isCredit ? `Collect ${cfLabel.toLowerCase()} (${cash})` : `Pay ${cfLabel.toLowerCase()} (${cash})`,
    goal: edu.goal,
    maxGain: card.max_profit != null ? String(card.max_profit) : edu.maxGainHint,
    maxLoss: card.max_loss != null ? String(card.max_loss) : edu.maxLossHint,
    breakeven: be,
    whatNeedsToHappen: edu.needs,
    whatCanGoWrong: edu.wrong,
    whatToMonitor: edu.monitor,
    warningSigns: edu.warnings,
    noviceGlossary: NOVICE_GLOSSARY,
    paperOrLiveExplanation: paperLiveExplanation(card),
    beginnerSummary: buildBeginnerSummary(card),
    stockMoveScenarios: buildStockMoveScenarios(s, sym),
    monitorChecklist: buildMonitorChecklist(s),
    sections: {
      tradeType: tradeTypeDetail,
      buyingSelling: `${edu.direction}. ${isCredit ? 'You collect premium (credit).' : 'You pay premium (debit).'} ${edu.legs}.`,
      whyUse: edu.whyUse,
      howMakeMoney: edu.howWin,
      howLoseMoney: edu.howLose,
      whatToMonitor: edu.monitor.join(' · '),
      numbersMean,
      paperLive: paperLiveExplanation(card),
    },
  }
}

export const OPEN_OPTIONS_INTRO =
  'Open paper options are monitored after fill. The monitor watches option value, stock price, Greeks, IV, spread, P/L, DTE, and advisory labels. It does not place live orders. It only tells you whether the paper position is HOLD, WATCH, CONSIDER CLOSE, CONSIDER ROLL, DATA STALE, or QUOTE UNTRADABLE.'
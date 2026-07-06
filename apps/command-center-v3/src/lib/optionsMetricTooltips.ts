/** Novice tooltips for compact options metric chips — UI/copy only. */

export type OptionsMetricKey =
  | 'dte_bucket'
  | 'strike'
  | 'delta'
  | 'delta_proxy'
  | 'breakeven'
  | 'breakeven_move_pct'
  | 'share_capital_pct'
  | 'premium'
  | 'total_debit'
  | 'total_credit'
  | 'max_loss'
  | 'max_profit'
  | 'max_gain'
  | 'iv_rank'
  | 'iv_history_building'
  | 'iv'
  | 'oi'
  | 'volume'
  | 'spread_pct'
  | 'pop'
  | 'ev'
  | 'edge'
  | 'rr'
  | 'dte'
  | 'earnings_before_expiry'
  | 'thesis'
  | 'conviction'
  | 'paper_validation'
  | 'live_eligible_false'
  | 'no_live_path'
  | 'alpaca_paper_only'
  | 'net_debit'
  | 'net_credit'
  | 'pkg_slippage'
  | 'implied_move'
  | 'historical_move'
  | 'event_confidence'
  | 'earnings_date'
  | 'dte_to_expiry'
  | 'spot'
  | 'contracts'

export type OptionsMetricTooltip = {
  short: string
  more: string
  watch?: string
  warning?: string
}

export type OptionsMetricContext = {
  symbol?: string
  strategy?: string
  option_type?: 'call' | 'put'
  strike?: number
  spot?: number
  delta?: number
  breakeven?: number
  breakeven_move_pct?: number
  capital_ratio_pct?: number
  dte_bucket?: number
  dte?: number
  is_delta_proxy?: boolean
  iv_rank?: number
  iv_days?: number
  iv_required_days?: number
  premium?: number
  contracts?: number
  validation_label?: string
  validation_message?: string
  blocks?: string[]
}

function inferOptionType(ctx: OptionsMetricContext): 'call' | 'put' {
  if (ctx.option_type) return ctx.option_type
  const s = (ctx.strategy || '').toLowerCase()
  if (s.includes('put') && !s.includes('spread')) return 'put'
  if (s.includes('put')) return 'put'
  return 'call'
}

function sym(ctx: OptionsMetricContext): string {
  return ctx.symbol || 'the stock'
}

function fmtStrike(n?: number): string {
  if (n == null) return 'the strike'
  return `$${n < 50 ? n.toFixed(2) : Math.round(n)}`
}

function fmtPct(n?: number): string {
  if (n == null) return ''
  const sign = n > 0 ? '+' : ''
  return `${sign}${Number(n).toFixed(1)}%`
}

function fmtBe(n?: number): string {
  if (n == null) return 'the breakeven price'
  return `$${Number(n).toFixed(2)}`
}

const BASE: Record<OptionsMetricKey, (ctx: OptionsMetricContext) => OptionsMetricTooltip> = {
  dte_bucket: ctx => {
    const days = ctx.dte_bucket ?? ctx.dte
    const bucket = days != null ? `${Math.round(days)}d` : 'this'
    return {
      short: days != null
        ? `This option expires in the longer-term bucket, around ${Math.round(days)} days.`
        : 'This shows which time bucket the scanner grouped this expiration into.',
      more: `The scanner groups expirations into buckets like 60d, 90d, and 180d so you can compare short-term vs longer-term versions of the same idea. A ${bucket} option gives the trade more time to work, but it may cost more and still loses value as time passes.`,
      watch: 'Watch DTE, theta decay, liquidity, and whether the original thesis is still valid.',
    }
  },

  strike: ctx => {
    const ot = inferOptionType(ctx)
    const strike = fmtStrike(ctx.strike)
    const above = ctx.spot != null && ctx.strike != null && ctx.spot > ctx.strike
    const below = ctx.spot != null && ctx.strike != null && ctx.spot < ctx.strike
    if (ot === 'call') {
      return {
        short: 'The strike is the price where the option contract is anchored.',
        more: above && ctx.symbol
          ? `For a call option, the strike is the price where the contract gives you the right to buy 100 shares. Here, a ${strike} call is deep in-the-money because ${sym(ctx)} is trading above ${fmtStrike(ctx.strike)}. That is why it behaves more like stock than a far-out-of-the-money lottery ticket.`
          : `For a call option, the strike is the price where the contract gives you the right to buy 100 shares at expiration. Compare the strike to the current stock price to see how far in- or out-of-the-money the contract is.`,
        watch: 'Compare the strike to spot price, breakeven, delta, and liquidity.',
      }
    }
    return {
      short: 'The strike is the price where the option contract is anchored.',
      more: below && ctx.symbol
        ? `For a put option, the strike is the price where the contract gives you the right to sell 100 shares. Here, a ${strike} put is in-the-money because ${sym(ctx)} is trading below that level.`
        : `For a put option, the strike is the price where the contract gives you the right to sell 100 shares at expiration. Compare the strike to the current stock price to see how protective or speculative the contract is.`,
      watch: 'Compare the strike to spot price, breakeven, delta, and liquidity.',
    }
  },

  delta: ctx => {
    const d = ctx.delta != null ? Number(ctx.delta).toFixed(2) : '0.50'
    return {
      short: 'Delta estimates how stock-like the option is.',
      more: `A delta of ${d} means the option may move about $${d} for each $1 move in the stock, before other factors change. Higher delta usually means the option behaves more like owning shares. Deep in-the-money calls often have higher delta.`,
      watch: 'If delta drops, the option may become less stock-like and more speculative.',
    }
  },

  delta_proxy: () => ({
    short: 'Delta is estimated from moneyness because the chain had no greeks.',
    more: 'When the option chain does not carry live greeks, the desk uses a proxy based on how far in- or out-of-the-money the strike is. Treat this as a rough stock-likeness estimate — confirm on the chain before sizing.',
    watch: 'Open the chain for a live delta quote before paper or manual review.',
  }),

  breakeven: ctx => {
    const move = ctx.breakeven_move_pct
    const moveTxt = move != null ? ` The ${fmtPct(move)} means the stock needs to ${move >= 0 ? 'rise' : 'fall'} about ${Math.abs(move).toFixed(1)}% from the current reference price by expiration.` : ''
    const ot = inferOptionType(ctx)
    const be = fmtBe(ctx.breakeven)
    return {
      short: 'Breakeven is the stock price needed at expiration to break even.',
      more: ot === 'call'
        ? `For a long call, breakeven is strike plus premium paid. Here, ${sym(ctx)} would need to be around ${be} at expiration for the option to break even.${moveTxt}`
        : `For a long put, breakeven is strike minus premium paid. At expiration, ${sym(ctx)} would need to be around ${be} for the option to break even.${moveTxt}`,
      watch: 'Compare breakeven to current price, earnings risk, time left, and your thesis.',
    }
  },

  breakeven_move_pct: ctx => ({
    short: 'Percent move the stock needs by expiration to reach breakeven.',
    more: `The ${fmtPct(ctx.breakeven_move_pct) || 'shown'} figure compares breakeven to a reference spot price. It answers: how much does the stock still need to move by expiration just to get back to even on the trade?`,
    watch: 'Compare this move to typical volatility, earnings gaps, and your thesis timeline.',
  }),

  share_capital_pct: ctx => {
    const pct = ctx.capital_ratio_pct != null ? Math.round(ctx.capital_ratio_pct) : null
    return {
      short: 'This compares option cost to buying 100 shares.',
      more: pct != null
        ? `Buying 100 shares of ${sym(ctx)} would require much more cash. This option controls roughly 100 shares but uses about ${pct}% of the cash needed to buy those shares outright. That is the stock-replacement idea.`
        : `This ratio compares the option debit to the cash required to buy 100 shares outright — the stock-replacement framing used on deep in-the-money calls.`,
      watch: 'Lower capital use does not mean lower risk. The option can still lose 100% of the debit paid.',
    }
  },

  premium: () => ({
    short: 'Premium is the quoted price for one option contract.',
    more: 'Premium is usually shown per share; one contract covers 100 shares, so multiply by 100 for total cash. For debits you pay premium; for credits you collect it. Confirm the live bid/ask on the chain before sizing.',
    watch: 'Watch bid/ask width, mid vs last, and whether the quote is stale.',
  }),

  total_debit: () => ({
    short: 'Total cash you would pay if the trade fills.',
    more: 'Total debit = premium per share × 100 × number of contracts. This is the maximum you can lose on many long-option trades (excluding fees). Review before any paper or manual ticket.',
    watch: 'Confirm contracts, limit price, and account cash available.',
  }),

  total_credit: () => ({
    short: 'Total cash you would collect if the trade fills.',
    more: 'Total credit = premium per share × 100 × number of contracts. Credit strategies keep this if the trade works, but assignment or defense can change the outcome. Review max loss and margin requirements.',
    watch: 'Watch assignment risk, margin, and whether credit matches your risk budget.',
  }),

  max_loss: () => ({
    short: 'Worst-case loss if the trade goes against you.',
    more: 'For defined-risk spreads, max loss is usually the net debit or spread width minus credit. For long options, max loss is often the premium paid. For covered calls, stock downside can exceed the credit collected.',
    watch: 'Compare max loss to portfolio risk limits and thesis conviction.',
  }),

  max_profit: () => ({
    short: 'Best-case profit if the trade works as modeled.',
    more: 'Max profit is the ceiling under the desk model — spreads cap gains at the long leg; short premium keeps credit if options expire worthless. Actual fills and early closes can differ.',
    watch: 'Do not assume max profit is likely — review POP and breakeven instead.',
  }),

  max_gain: ctx => BASE.max_profit(ctx),

  iv_rank: ctx => ({
    short: 'IV rank shows where current implied volatility sits vs its 52-week range.',
    more: ctx.iv_rank != null
      ? `IV rank ${Math.round(ctx.iv_rank)}% means ATM implied vol is higher than ${Math.round(ctx.iv_rank)}% of the past year's readings. Higher rank often means richer option prices (you pay more for calls / collect more for credits).`
      : 'IV rank places current implied volatility in its 52-week range. The desk uses it to compare whether options look cheap or rich — advisory only.',
    watch: 'Rich IV can mean pay-up risk; cheap IV can mean less premium cushion.',
  }),

  iv_history_building: ctx => ({
    short: 'IV rank is not ready yet — history is still accumulating.',
    more: ctx.iv_days != null
      ? `IV rank needs enough daily ATM-IV snapshots (about ${ctx.iv_required_days ?? 20} days). Only ${ctx.iv_days} days are stored so far, so the desk reports honestly instead of guessing.`
      : 'IV rank needs a rolling history of ATM implied volatility. Until enough days are stored, the card shows building status rather than a percentile.',
    watch: 'Treat IV context as unavailable until history completes — rely on chain quotes.',
  }),

  iv: () => ({
    short: 'Implied volatility (IV) is the market’s estimate of future price swings.',
    more: 'Higher IV usually means options cost more. IV on the card may come from the chain mid or a desk snapshot — compare to historical range when IV rank is available.',
    watch: 'Watch IV into earnings and whether you are paying up for event risk.',
  }),

  oi: () => ({
    short: 'Open interest counts outstanding contracts at this strike.',
    more: 'Higher open interest often means more liquidity and tighter markets. Very low OI can mean wider bid/ask spreads and harder fills — especially important before paper or manual tickets.',
    watch: 'Pair OI with volume to see if the strike is actively traded.',
  }),

  volume: () => ({
    short: 'Volume is how many contracts traded today at this strike.',
    more: 'Volume shows near-term activity. A strike with OI but no volume may still be liquid if the market is open — but zero activity can mean stale quotes.',
    watch: 'Compare volume to OI and check live bid/ask on the chain.',
  }),

  spread_pct: () => ({
    short: 'Bid/ask spread as a percent of the mid price.',
    more: 'A wide spread means the quoted mid may not be what you actually fill at. The desk flags wide spreads because slippage can eat edge on entry and exit.',
    watch: 'Review live quotes before sizing — wide spreads deserve smaller size or limits.',
  }),

  pop: () => ({
    short: 'Probability of profit at expiration under the desk model.',
    more: 'POP estimates how often the trade finishes profitable if held to expiration. It is a model output, not a guarantee — thesis, earnings, and early management can change outcomes.',
    watch: 'Compare POP to breakeven distance, max loss, and your hold plan.',
  }),

  ev: () => ({
    short: 'Expected value is a probability-weighted P/L estimate.',
    more: 'EV blends win rate, credit/debit, and modeled payoffs into one number. Positive EV suggests statistical edge in backtests — not a promise for any single trade.',
    watch: 'Use EV with POP and max loss — one lucky fill does not validate the model.',
  }),

  edge: () => ({
    short: 'Composite quality score from POP, IV, R:R, and conviction.',
    more: 'Edge ranks proposals on the desk. Standard gate is about 62; income sleeve names may use a lower floor. Higher edge means the idea passed more quality checks — still review before action.',
    watch: 'Edge does not replace chain review, thesis check, or risk limits.',
  }),

  rr: () => ({
    short: 'Reward-to-risk ratio: max gain divided by max loss.',
    more: 'R:R compares upside to downside on defined-risk trades. Higher is generally better, but a high R:R with low POP may still be a low-quality idea. Spreads and credits use package economics.',
    watch: 'Read R:R together with POP, breakeven, and liquidity.',
  }),

  dte: ctx => ({
    short: 'Days to expiration — time left before the contract expires.',
    more: ctx.dte != null
      ? `${ctx.dte} days remain until expiration. Theta (time decay) often accelerates in the final two weeks, which matters for long calls and debits.`
      : 'Days to expiration counts calendar days until the option expires. Less time usually means faster time decay for long premium.',
    watch: 'Watch theta, earnings dates, and whether your thesis needs more time.',
  }),

  earnings_before_expiry: () => ({
    short: 'An earnings report is scheduled before this option expires.',
    more: 'Earnings can cause large overnight gaps that bypass breakeven math. The desk flags this so you can review event risk explicitly — it is disclosed, not hidden.',
    watch: 'Compare implied move, historical gaps, and whether you want event exposure.',
    warning: 'Earnings gaps can exceed modeled breakeven moves.',
  }),

  thesis: () => ({
    short: 'Where the underlying idea came from on the desk.',
    more: 'Thesis source links the option idea to watchlist conviction, holdings, or scanner context. It explains why this symbol surfaced — not whether the trade is guaranteed to work.',
    watch: 'Re-check thesis if price action, news, or earnings change the story.',
  }),

  conviction: () => ({
    short: 'Desk conviction score for the underlying idea.',
    more: 'Conviction summarizes how strongly research or watchlist signals support the symbol. Higher conviction can lift edge ranking — it is advisory input, not order permission.',
    watch: 'Conviction can change when new research or price action arrives.',
  }),

  paper_validation: ctx => ({
    short: 'Progress toward the paper-outcomes validation gate.',
    more: ctx.validation_message
      ? ctx.validation_message
      : 'Paper strategies must accumulate closed outcomes (about 30 trades, profit factor and win-rate thresholds) before live consideration. This chip tracks recorded paper results — no live path until the gate clears.',
    watch: 'Validation credit applies only after fill, close, and outcome reconciliation.',
  }),

  live_eligible_false: () => ({
    short: 'This row is not eligible for live broker execution.',
    more: 'Paper-model and unvalidated strategies stay off the live path by design. You can still review, paper-test, or log manual research — live submit requires passing enterprise gates and operator approval.',
    watch: 'Do not expect a live submit button on paper-model cards.',
  }),

  no_live_path: ctx => ({
    short: 'No live broker execution path exists for this row.',
    more: ctx.blocks?.length
      ? `Blocked from live broker execution — paper testing remains available. Reasons: ${ctx.blocks.join('; ')}.`
      : 'Blocked from live broker execution — paper testing path remains available. No live order path until the validation gate is met.',
    watch: 'Use paper lane or manual review only until policy changes.',
  }),

  alpaca_paper_only: () => ({
    short: 'This route uses Alpaca simulated paper orders only.',
    more: 'Alpaca paper sends a simulated limit order — no live broker execution. Outcomes feed the validation ledger after fill, close, and reconciliation.',
    watch: 'Confirm paper fill status before treating results as validated.',
  }),

  net_debit: () => ({
    short: 'Net cash paid to open the spread package.',
    more: 'Net debit is long-leg cost minus short-leg credit for multi-leg trades. It is usually close to max loss on defined-risk debit spreads.',
    watch: 'Confirm package mid, slippage, and leg liquidity on the chain.',
  }),

  net_credit: () => ({
    short: 'Net cash collected to open the spread package.',
    more: 'Net credit is short-leg premium minus long-leg cost. You keep it if the spread expires worthless, but assignment or defense can change outcomes.',
    watch: 'Watch short-strike distance, margin, and event gap risk.',
  }),

  pkg_slippage: () => ({
    short: 'Estimated slippage if each leg fills at the ask/bid instead of mid.',
    more: 'Package slippage models worse-than-mid fills on every leg. Real fills may be better or worse — use it as a conservative liquidity warning.',
    watch: 'Wide leg spreads increase slippage — review live quotes.',
  }),

  implied_move: () => ({
    short: 'Market-implied expected move into the event (from ATM straddle).',
    more: 'Implied move comes from the ATM straddle mid at the event expiration when available. It is what options are pricing for earnings — not a forecast.',
    watch: 'Compare implied move to historical earnings gaps and breakeven.',
  }),

  historical_move: () => ({
    short: 'Average absolute post-earnings move from stored history.',
    more: 'Historical move averages past earnings reactions on record. Thin sample counts mean less confidence — the desk reports sample size honestly.',
    watch: 'Few samples or stale events deserve extra caution.',
  }),

  event_confidence: () => ({
    short: 'Confidence in the earnings date and event metadata.',
    more: 'Event confidence reflects how reliable the earnings calendar and stored history are. Low confidence means treat event lines as review-only.',
    watch: 'Verify earnings date on an external calendar before event trades.',
  }),

  earnings_date: () => ({
    short: 'Scheduled earnings report date for the underlying.',
    more: 'Earnings dates can shift. The desk surfaces the best-known date from its event model — confirm before sizing event trades.',
    watch: 'Cross-check date and timing (BMO/AMC) on the chain or calendar.',
  }),

  dte_to_expiry: ctx => BASE.dte(ctx),

  spot: () => ({
    short: 'Current underlying stock price from chain or snapshot.',
    more: 'Spot is the reference price for moneyness, breakeven distance, and delta context. Stale spot can mislead — refresh the chain for live marks.',
    watch: 'Compare spot to strike, breakeven, and recent trend.',
  }),

  contracts: () => ({
    short: 'Number of option contracts in the proposal.',
    more: 'Each contract represents 100 shares. Contract count scales premium, max loss, and margin. Covered calls are often sized to shares held.',
    watch: 'Confirm size matches holdings (covered calls) or risk budget.',
  }),
}

/** Resolve tooltip copy for a compact metric chip. */
export function getOptionsMetricTooltip(
  metricKey: OptionsMetricKey | string,
  context: OptionsMetricContext = {},
): OptionsMetricTooltip {
  const key = (metricKey === 'delta' && context.is_delta_proxy ? 'delta_proxy' : metricKey) as OptionsMetricKey
  const fn = BASE[key]
  if (fn) return fn(context)
  return {
    short: 'Desk metric — hover or tap for context.',
    more: 'This metric is shown for review. Open the chain and Explain this trade panel for full context.',
  }
}

/** Map paper disclosure flag keys to metric tooltip keys. */
export function paperFlagMetricKey(flagKey: string): OptionsMetricKey | null {
  if (flagKey.includes('earnings_before_expiry')) return 'earnings_before_expiry'
  if (flagKey.startsWith('delta_proxy')) return 'delta_proxy'
  if (flagKey === 'iv_rich' || flagKey === 'iv_rich_pay_up_warning') return 'iv_rank'
  return null
}

export type MetricChipItem = { key: OptionsMetricKey | string; label: string }
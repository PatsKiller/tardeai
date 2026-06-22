import { fmt$ } from './format'
import type { OptionProposal } from '../components/OptionProposalCard'
import type { OptionPosition } from '../components/OptionPositionCard'

export const NOVICE_MODE_KEY = 'options_novice_mode'

export function isNoviceMode(): boolean {
  try { return localStorage.getItem(NOVICE_MODE_KEY) !== '0' } catch { return true }
}

export function setNoviceMode(on: boolean) {
  try { localStorage.setItem(NOVICE_MODE_KEY, on ? '1' : '0') } catch { /* ignore */ }
}

const STRAT = {
  covered_call: {
    name: 'Covered Call',
    emoji: '📞',
    oneLiner: 'You already own the stock. You sell someone the right to buy it from you at a set price — and collect cash upfront.',
    win: 'Stock stays at or below the strike → you keep the premium and your shares.',
    lose: 'Stock jumps above the strike → you may have to sell shares at the strike (capped upside) or buy back the call at a loss.',
    watch: 'Assignment near expiration if the call is in-the-money (ITM).',
  },
  cash_secured_put: {
    name: 'Cash-Secured Put',
    emoji: '🛡️',
    oneLiner: 'You promise to buy the stock at the strike if it falls there — cash is set aside, and you collect premium upfront.',
    win: 'Stock stays above the strike → put expires worthless, you keep the premium.',
    lose: 'Stock falls below the strike → you may be assigned and must buy shares at the strike.',
    watch: 'Only sell puts on stocks you are happy to own at the strike price.',
  },
  long_call: {
    name: 'Long Call',
    emoji: '🚀',
    oneLiner: 'You pay premium for the right to buy the stock at the strike — a directional bet that price rises.',
    win: 'Stock rises well above strike + premium paid → profit grows (uncapped).',
    lose: 'Stock stays flat or falls → you can lose the entire premium paid.',
    watch: 'Time decay (theta) eats value every day — especially in the last 2 weeks.',
  },
  credit_spread: {
    name: 'Credit Spread',
    emoji: '📐',
    oneLiner: 'You sell one option and buy a farther one — defined max risk, collect a net credit.',
    win: 'Price stays in the profitable zone → you keep most or all of the credit.',
    lose: 'Price moves against you past the long leg → max loss is capped but real.',
    watch: 'Know your max loss before entering — it is fixed but not zero.',
  },
} as const

export function strategyGuide(strategy: string) {
  return STRAT[strategy as keyof typeof STRAT] || {
    name: strategy.replace(/_/g, ' '),
    emoji: '◎',
    oneLiner: 'Review the metrics and chain before trading.',
    win: 'Trade works as modeled.',
    lose: 'Price moves against the position.',
    watch: 'Confirm live quotes on the chain.',
  }
}

function fmtDate(iso?: string): string {
  if (!iso) return 'expiration'
  try {
    const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  } catch { return iso }
}

export function plainEnglishProposal(p: OptionProposal): string {
  const sym = p.symbol
  const strike = p.strike
  const credit = fmt$(p.premium_total)
  const exp = fmtDate(p.expiration)
  const contracts = p.contracts ?? 1
  const spot = p.underlying_price

  if (p.strategy === 'covered_call') {
    const shares = contracts * 100
    const otm = spot && strike > spot
    const dist = spot ? `${(((strike - spot) / spot) * 100).toFixed(1)}% above spot` : ''
    return `You own ~${shares} shares of ${sym}. Sell ${contracts} call(s) at $${strike} (${exp}, ${p.dte ?? '—'} days) for ~${credit} total. ${otm ? `Strike is ${dist} — ` : ''}If ${sym} stays below $${strike}, you keep the cash. Above $${strike}, shares may be called away at $${strike}.`
  }
  if (p.strategy === 'cash_secured_put') {
    return `Set aside cash to buy ${sym} at $${strike} if assigned. Collect ~${credit} premium for the ${exp} put (${p.dte ?? '—'} days). Keep premium if ${sym} stays above $${strike}; otherwise you may buy ${contracts * 100} shares at $${strike}.`
  }
  if (p.strategy === 'long_call') {
    const cost = fmt$(p.premium != null ? p.premium * 100 * contracts : null)
    return `Pay ~${cost} for ${contracts} call(s) at $${strike} (${exp}). You profit if ${sym} rises above ~$${p.breakeven ?? strike} by expiration. Max loss is the premium paid.`
  }
  if (p.strategy === 'credit_spread') {
    return `Collect ~${credit} net credit on a ${sym} spread expiring ${exp}. Profit if price stays in range; max loss is capped — see Max loss on the card.`
  }
  return `${strategyGuide(p.strategy).oneLiner} ${sym} $${strike}, ${exp}.`
}

export type RiskFlag = { label: string; tip: string; severity: 'info' | 'warn' | 'danger' }

export function proposalRiskFlags(p: OptionProposal): RiskFlag[] {
  const flags: RiskFlag[] = []
  const spot = p.underlying_price
  const strike = p.strike

  if (p.data_source === 'bs_estimate') {
    flags.push({ label: 'Estimate only', tip: 'Premium is modeled, not live chain — open View Chain and verify bid/ask before sizing.', severity: 'warn' })
  }
  if (p.strategy === 'covered_call' && spot && strike <= spot) {
    flags.push({ label: 'Assignment risk', tip: 'Strike is at or below the current price — the call is in-the-money; higher chance of assignment near expiry.', severity: 'danger' })
  } else if (p.strategy === 'covered_call' && spot && strike > spot) {
    const pct = ((strike - spot) / spot) * 100
    if (pct < 2) flags.push({ label: 'Tight strike', tip: `Only ${pct.toFixed(1)}% above spot — small cushion before the call goes ITM.`, severity: 'warn' })
  }
  if (p.dte != null && p.dte <= 14) {
    flags.push({ label: 'Short DTE', tip: 'Under 2 weeks to expiry — time decay is fast; assignment checks matter more.', severity: 'warn' })
  }
  if (p.pop_pct != null && p.pop_pct < 55) {
    flags.push({ label: 'Lower POP', tip: `Only ~${p.pop_pct.toFixed(0)}% modeled chance of profit — not a high-odds income trade.`, severity: 'warn' })
  }
  if (p.risk_reward != null && p.risk_reward < 0.15 && p.strategy === 'covered_call') {
    flags.push({ label: 'Low R:R', tip: 'Premium is small vs downside on the stock — income is thin relative to equity risk.', severity: 'info' })
  }
  if (p.premium_total != null && p.premium_total < 75) {
    flags.push({ label: 'Small credit', tip: `~${fmt$(p.premium_total)} total — commissions and slippage matter more on tiny premiums.`, severity: 'info' })
  }
  return flags
}

export function strikeDistance(p: OptionProposal): { pct: number; label: string; side: 'otm' | 'itm' | 'atm' } | null {
  const spot = p.underlying_price
  if (!spot || !p.strike) return null
  const pct = ((p.strike - spot) / spot) * 100
  const abs = Math.abs(pct)
  if (abs < 0.5) return { pct, label: 'At-the-money', side: 'atm' }
  if (p.strategy === 'covered_call' || p.strategy === 'cash_secured_put') {
    if (p.strategy === 'covered_call') {
      return pct > 0
        ? { pct, label: `${pct.toFixed(1)}% above spot (OTM)`, side: 'otm' }
        : { pct, label: `${Math.abs(pct).toFixed(1)}% below spot (ITM)`, side: 'itm' }
    }
    return pct < 0
      ? { pct, label: `${Math.abs(pct).toFixed(1)}% below spot (OTM)`, side: 'otm' }
      : { pct, label: `${pct.toFixed(1)}% above spot (ITM)`, side: 'itm' }
  }
  return pct > 0
    ? { pct, label: `${pct.toFixed(1)}% above spot`, side: 'otm' }
    : { pct, label: `${Math.abs(pct).toFixed(1)}% below spot`, side: 'itm' }
}

export function preflightChecklist(p: OptionProposal): string[] {
  const g = strategyGuide(p.strategy)
  const lines = [
    `Strategy: ${g.name} on ${p.symbol}`,
    `Order: ${p.contracts ?? 1} contract(s) · strike $${p.strike} · expires ${fmtDate(p.expiration)} (${p.dte ?? '—'} days)`,
    `Estimated credit/cost: ${fmt$(p.premium_total)} (${p.data_source === 'bs_estimate' ? 'modeled — verify on chain' : 'from chain'})`,
    `If it works: ${g.win}`,
    `If it fails: ${g.lose}`,
    `Watch: ${g.watch}`,
    'Live orders require Telegram/email 2FA approval — nothing submits without you.',
  ]
  return lines
}

export function plainEnglishPosition(p: OptionPosition): string {
  const sym = p.underlying
  const strat = (p.strategy || '').replace(/_/g, ' ')
  if (/short_call/.test(p.strategy || '')) {
    return `You sold a call on ${sym} at $${p.strike ?? '—'}. ${p.moneyness === 'ITM' ? 'It is in-the-money — assignment risk is elevated.' : `~${p.pop_otm_pct?.toFixed(0) ?? '—'}% chance it expires worthless (OTM).`} P/L: ${fmt$(p.unrealized_pnl)}.`
  }
  if (/short_put/.test(p.strategy || '')) {
    return `You sold a put on ${sym} at $${p.strike ?? '—'}. ${p.moneyness === 'ITM' ? 'Stock is below strike — assignment to buy shares is possible.' : 'Stock is above strike — position is working.'}`
  }
  return `Monitoring ${strat} on ${sym} — ${p.moneyness ?? '—'}, ${p.dte ?? '—'} days left. Recommended: ${p.recommended_action ?? 'Hold'}.`
}

export const GLOSSARY: { term: string; def: string }[] = [
  { term: 'Strike', def: 'The price where the option contract applies. For a $34 call, the buyer can buy at $34.' },
  { term: 'Premium', def: 'Cash paid (buyer) or received (seller) per contract. One contract = 100 shares.' },
  { term: 'DTE', def: 'Days to expiration — how long until the option expires.' },
  { term: 'ITM / OTM', def: 'In-the-money = profitable to exercise now. Out-of-the-money = not profitable to exercise.' },
  { term: 'Assignment', def: 'Broker makes you fulfill the option (sell shares on a short call, buy on a short put).' },
  { term: 'POP', def: 'Probability of profit — rough odds the trade finishes profitable at expiration.' },
  { term: 'IV rank', def: 'Where current volatility sits vs the past year — higher often means fatter premiums.' },
  { term: 'Theta', def: 'Time decay — options lose value as expiration approaches (faster near the end).' },
  { term: 'Covered call', def: 'Own 100+ shares, sell a call against them to earn income.' },
  { term: 'Cash-secured put', def: 'Sell a put with cash reserved to buy the stock if assigned.' },
]
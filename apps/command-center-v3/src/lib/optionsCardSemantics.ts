import type { OptionProposal } from '../components/OptionProposalCard'

const EXEC_TRADE_ACTIONS = new Set([
  'sell_covered_call', 'sell_put', 'buy_put', 'buy_call', 'sell_credit_spread',
])

const CREDIT_STRATEGIES = new Set([
  'covered_call', 'cash_secured_put', 'credit_spread', 'put_credit_spread', 'call_credit_spread',
])

const DEBIT_STRATEGIES = new Set([
  'deep_itm_call', 'atm_call', 'atm_put', 'protective_put', 'debit_spread',
  'earnings_put_debit_spread', 'long_call',
])

export type PrimeDisplay = {
  label: string
  shortLabel: string
  color: 'muted' | 'red' | 'amber' | 'teal' | 'amber_high'
  verdict?: string
  showScore: boolean
}

export type LiquidityWarning = { code: string; severity: string; message: string }

export function optionCashflowLabel(
  strategy: string,
  side?: string | null,
): string {
  const s = (strategy || '').toLowerCase()
  if (s === 'covered_call' || s === 'cash_secured_put') return 'Total credit'
  if (CREDIT_STRATEGIES.has(s)) return 'Net credit'
  if (s === 'debit_spread' || s === 'earnings_put_debit_spread') return 'Net debit'
  if (DEBIT_STRATEGIES.has(s)) return 'Total debit'
  const sideU = (side || '').toUpperCase()
  if (sideU === 'SELL') return 'Total credit'
  if (sideU === 'BUY') return 'Total debit'
  return 'Total premium'
}

export function cashflowIsCredit(strategy: string, side?: string | null): boolean {
  return optionCashflowLabel(strategy, side).toLowerCase().includes('credit')
}

export function isCardBlocked(p: OptionProposal & Record<string, unknown>): boolean {
  if (p.card_blocked === true) return true
  const status = String(p.status || p.queue_status || '').toLowerCase()
  if (status === 'blocked') return true
  if ((p as any).enterprise_blocked === true) return true
  if ((p.enterprise?.blocks?.length ?? 0) > 0) return true
  const av = String(p.aegis_verdict || '').toUpperCase()
  if (av === 'BLOCK' || av === 'BLOCKED' || av === 'REJECT') return true
  const aegisSt = String((p as any).aegis_status || '').toLowerCase()
  if (aegisSt === 'block' || aegisSt === 'blocked' || aegisSt === 'review_needed' || aegisSt === 'review-needed') return true
  const ens = String((p as any).ensemble_verdict || (p as any).ensemble_status || '').toUpperCase()
  if (ens === 'BLOCK' || ens === 'BLOCKED' || ens === 'REJECT') return true
  return false
}

export function allowsManualLog(p: OptionProposal & Record<string, unknown>): boolean {
  if (isCardBlocked(p)) return false
  if (p.educational_paper_model) return false
  return p.execution_mode === 'manual' || p.broker === 'fidelity' || p.auto_eligible === false
}

export function executionRouteBadge(p: OptionProposal & Record<string, unknown>): { label: string; kind: string } {
  const route = (p as any).execution_route_kind as string | undefined
  const badge = (p as any).execution_route_badge as string | undefined
  if (badge && route) return { label: badge, kind: route }
  if (p.educational_paper_model) {
    if (p.alpaca_paper_enabled || p.meta?.alpaca_paper_enabled) {
      return { label: 'Alpaca paper only', kind: 'alpaca_paper' }
    }
    return { label: 'Paper model only', kind: 'paper_model' }
  }
  if (p.broker === 'fidelity' || p.execution_mode === 'manual') {
    return { label: 'Fidelity manual ticket only', kind: 'fidelity_manual' }
  }
  if (p.broker === 'alpaca') return { label: 'Alpaca paper only', kind: 'alpaca_paper' }
  if (p.enterprise?.live_eligible && p.broker === 'schwab') {
    return { label: 'Schwab live path · 2FA required', kind: 'schwab_live' }
  }
  return { label: 'Review only', kind: 'review_only' }
}

export function primeDisplayLabel(score?: number | null, verdict?: string | null): PrimeDisplay {
  const s = score != null ? Number(score) : null
  const v = String(verdict || '').toUpperCase().replace('PAPER_ONLY', 'PAPER_WATCH')
  if (s == null) return { label: '—', shortLabel: '—', color: 'muted', showScore: false }
  if (s < 50 || v === 'NOT_PRIME') {
    return { label: 'NOT PRIME', shortLabel: `NOT PRIME ${Math.round(s)}`, color: 'red', verdict: 'NOT_PRIME', showScore: true }
  }
  if (s < 65 || v === 'PAPER_WATCH') {
    return { label: 'PAPER WATCH', shortLabel: `PAPER WATCH ${Math.round(s)}`, color: 'amber', verdict: 'PAPER_WATCH', showScore: true }
  }
  if (s < 80 || v === 'PRIME_FOR_PAPER') {
    return { label: 'PRIME FOR PAPER', shortLabel: `PRIME FOR PAPER ${Math.round(s)}`, color: 'teal', verdict: 'PRIME_FOR_PAPER', showScore: true }
  }
  return {
    label: 'LIVE REVIEW ELIGIBLE · OPERATOR ONLY',
    shortLabel: `LIVE REVIEW ${Math.round(s)}`,
    color: 'amber_high',
    verdict: 'READY_FOR_LIVE_REVIEW_OPERATOR_ONLY',
    showScore: true,
  }
}

export function sanitizeActionButtons(p: OptionProposal): { action: string; label: string }[] {
  if (isCardBlocked(p as any)) {
    return [
      { action: 'review_chain', label: 'View Chain' },
      { action: 'review_block_reason', label: 'Review Block Reason' },
      { action: 'rerun_review', label: 'Rerun Review' },
      { action: 'hold', label: 'Pass' },
    ]
  }
  const raw = p.action_buttons || []
  const filtered = raw.filter(b => !EXEC_TRADE_ACTIONS.has(b.action) || !isCardBlocked(p as any))
  return filtered.length ? filtered : [
    { action: 'review_chain', label: 'View Chain' },
    { action: 'hold', label: 'Pass' },
  ]
}

export function liquidityWarnings(p: OptionProposal): LiquidityWarning[] {
  const fromApi = (p as any).liquidity_warnings as LiquidityWarning[] | undefined
  if (fromApi?.length) return fromApi
  const warnings: LiquidityWarning[] = []
  const oi = p.oi
  if (oi != null && Number(oi) === 0) {
    warnings.push({
      code: 'oi_zero',
      severity: 'danger',
      message: 'Illiquid contract — open interest is 0. Do not trade without live chain review.',
    })
  }
  return warnings
}

export function cashflowColor(isCredit: boolean): string {
  return isCredit ? 'var(--price-up, #22c55e)' : 'var(--text-primary, #e2e8f0)'
}

export function primeChipStyle(color: PrimeDisplay['color']): string {
  switch (color) {
    case 'teal': return '#2dd4bf'
    case 'amber':
    case 'amber_high': return '#f5a623'
    case 'red': return '#ef5350'
    default: return 'var(--text3, #94a3b8)'
  }
}

export function plainEnglishHint(strategy: string): string {
  const s = (strategy || '').toLowerCase()
  if (s === 'deep_itm_call') {
    return 'Paper model: this simulates a deep-ITM call as stock replacement. You pay a debit, max loss is the premium paid, and no live order is placed. Use Alpaca Paper only after review.'
  }
  if (s === 'protective_put') {
    return 'Protective put: you pay a debit for downside hedge protection. Max loss on the option is premium paid; the hedge may offset losses in the underlying.'
  }
  if (s === 'covered_call') return 'You collect a credit, but upside is capped and shares may be assigned.'
  if (s === 'cash_secured_put') return 'You collect a credit, but may be assigned shares and must have cash reserved.'
  if (s === 'atm_call' || s === 'atm_put' || s === 'long_call') {
    return 'You pay a debit for directional exposure. Max loss is premium paid unless hedged.'
  }
  if (s === 'debit_spread' || s === 'earnings_put_debit_spread') {
    return 'Net debit spread — you pay premium; max loss is capped at the debit paid.'
  }
  if (s === 'credit_spread' || s === 'put_credit_spread' || s === 'call_credit_spread') {
    return 'Net credit spread — you collect premium; max loss is defined by the long leg.'
  }
  return 'Review the metrics and chain before trading.'
}

export function alpacaPaperButtonLabel(queueStatus?: string | null, confirming?: boolean): string | null {
  const qs = queueStatus || ''
  if (qs === 'ALPACA_PAPER_SUBMITTED') return 'Awaiting Paper Fill'
  if (qs === 'ALPACA_PAPER_FILLED') return 'Paper Filled — Track Outcome'
  if (qs === 'ALPACA_PAPER_CLOSED' || qs === 'OUTCOME_RECORDED') return 'Outcome Recorded'
  if (confirming) return 'Submit 1-Contract Paper Limit Order'
  if (qs === 'READY_FOR_ALPACA_PAPER') return 'Submit 1-Contract Paper Limit Order'
  return 'Mark Ready for Alpaca Paper'
}
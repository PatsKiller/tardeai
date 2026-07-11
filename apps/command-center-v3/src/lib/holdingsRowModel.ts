import type { StopStatusTone } from './holdingsTerminalTokens'

export interface HoldingsRowInput {
  h: any
  pr?: any
  confirmedStop?: any
  monitored?: any
  llmHealth?: string | null
}

export interface HoldingsRowModel {
  key: string
  symbol: string
  account: string
  accountShort: string
  marketValue: number
  dayPct: number | null
  portfolioPct: number | null
  price: number | null
  cost: number | null
  pl$: number | null
  plPct: number | null
  signal: string | null
  shares: number | null
  stopStatus: StopStatusTone
  stopDistPct: number | null
  stopPrice: number | null
  stopLabel: string
  stopAdvisory: string
  primaryAction: { label: string; tone: 'amber' | 'green' | 'red' | 'muted' }
  llmHealth: string | null
  llmAction: string | null
}

export function plMetrics(h: any): { dollars: number | null; pct: number | null } {
  const cb = h.cost_basis
  if (cb == null || cb <= 0) return { dollars: null, pct: null }
  const dollars = h.gain_loss != null
    ? Number(h.gain_loss)
    : (h.market_value != null ? Number(h.market_value) - Number(cb) : null)
  const pct = h.gain_loss_pct != null
    ? Number(h.gain_loss_pct)
    : (dollars != null ? (dollars / Number(cb)) * 100 : null)
  return { dollars, pct }
}

function acctShort(account: string): string {
  const a = (account || 'unknown').replace(/_/g, ' ')
  if (a.includes('schwab taxable')) return 'Schwab Tx'
  if (a.includes('schwab roth')) return 'Schwab Roth'
  if (a.includes('fidelity rollover')) return 'Fid IRA'
  if (a.includes('fidelity')) return 'Fidelity'
  if (a.includes('401')) return '401k'
  const parts = a.split(' ')
  return parts.length > 2 ? `${parts[0]} ${parts[1]}` : a
}

export function buildHoldingsRowModel(input: HoldingsRowInput): HoldingsRowModel {
  const h = input.h
  const pr = input.pr
  const sym = String(h.symbol || '').toUpperCase()
  const acct = String(h.account ?? 'unknown')
  const key = `${sym}:${acct}`
  const { dollars: pl$, pct: plPct } = plMetrics(h)
  const sh = Number(h.shares) || 0
  const cur = h.current_price != null ? Number(h.current_price)
    : sh > 0 && h.market_value != null ? Number(h.market_value) / sh : null
  const buy = sh > 0 && h.cost_basis != null && Number(h.cost_basis) > 0 ? Number(h.cost_basis) / sh : null
  const dayPct = h.day_change_pct != null ? Number(h.day_change_pct) : null

  const stopPrice = pr?.stop_price != null ? Number(pr.stop_price) : null
  const stopDist = pr?.stop_distance_pct != null ? Number(pr.stop_distance_pct) : null
  const health = String(h.llm_health || input.llmHealth || '').toUpperCase()
  const signal = String(h.signal || '').toUpperCase() || null
  const isSchwab = acct.startsWith('schwab')
  const isFidelity = acct.startsWith('fidelity') && acct !== 'fidelity_401k'
  const needsSellAll = isSchwab && sh > 0 && sh < 40
  const hasLive = Boolean(input.confirmedStop?.order_id || input.monitored?.stop_price)

  let stopStatus: StopStatusTone = 'stable'
  if (health === 'CONCERN' || health === 'TRIM' || signal === 'TRIM' || signal === 'SELL' || signal === 'EXIT') {
    stopStatus = 'action'
  } else if (stopDist != null && stopDist < 5) {
    stopStatus = 'concern'
  } else if (!hasLive && stopPrice && isSchwab) {
    stopStatus = 'action'
  } else if (needsSellAll && stopPrice) {
    stopStatus = 'concern'
  }

  let stopAdvisory = ''
  if (stopPrice != null) {
    stopAdvisory = `Tighten to $${stopPrice.toFixed(2)}`
    if (stopDist != null) stopAdvisory = `${stopDist.toFixed(1)}% below · $${stopPrice.toFixed(2)}`
  } else if (pr?.rec) {
    stopAdvisory = String(pr.rec).split('·')[0].trim().slice(0, 42)
  } else if (health === 'CONCERN') {
    stopAdvisory = 'Review allocation'
  } else {
    stopAdvisory = hasLive ? 'Stop in place' : 'No advisory stop'
  }

  let primaryAction: { label: string; tone: 'amber' | 'green' | 'red' | 'muted' } = { label: 'Details', tone: 'muted' }
  if (isFidelity && stopPrice && !hasLive) {
    primaryAction = { label: 'Create Ticket', tone: 'amber' }
  } else if (isSchwab && stopPrice && !hasLive) {
    primaryAction = { label: 'Request 2FA Stop', tone: 'amber' }
  } else if (isSchwab && stopPrice && pr?.advisory_stop_is_tighter_than_existing) {
    primaryAction = { label: 'Tighten Stop', tone: 'amber' }
  } else if (hasLive && isSchwab && stopPrice) {
    primaryAction = { label: 'Replace Stop', tone: 'amber' }
  } else if (health === 'CONCERN' || health === 'TRIM') {
    primaryAction = { label: 'Review', tone: 'amber' }
  } else if (signal === 'TRIM' || signal === 'SELL') {
    primaryAction = { label: 'Review', tone: 'red' }
  } else if (stopStatus === 'stable' && hasLive) {
    primaryAction = { label: 'Stable', tone: 'green' }
  }

  const stopLabel = stopStatus === 'stable' ? 'Stable' : stopStatus === 'concern' ? 'Concern' : 'Action'

  return {
    key,
    symbol: sym,
    account: acct,
    accountShort: acctShort(acct),
    marketValue: Number(h.market_value) || 0,
    dayPct,
    portfolioPct: h.portfolio_pct != null ? Number(h.portfolio_pct) : null,
    price: cur,
    cost: buy,
    pl$,
    plPct,
    signal,
    shares: sh || null,
    stopStatus,
    stopDistPct: stopDist,
    stopPrice,
    stopLabel,
    stopAdvisory,
    primaryAction,
    llmHealth: h.llm_health ?? null,
    llmAction: h.llm_action ?? null,
  }
}
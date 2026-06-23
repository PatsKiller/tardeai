/** Risk visualization math — payoff curves, thesis scores, contribution weights */

import type { ThesisValidity } from './brokerThesis'

export function thesisValidityScore(tv?: ThesisValidity | null): number {
  if (!tv?.ok) return 0
  if (tv.price_stale) return 25
  const zone = String(tv.zone_status || '').toLowerCase()
  const base: Record<string, number> = {
    comfortable: 92,
    approaching: 68,
    at_risk: 38,
    invalid: 8,
    stale_price: 20,
    unknown: 40,
  }
  let score = base[zone] ?? 40
  if (tv.current_rr != null && tv.current_rr < 1.5) score -= 15
  else if (tv.current_rr != null && tv.current_rr >= 2) score += 5
  if (tv.drift_pct != null && Math.abs(tv.drift_pct) > 5) score -= 10
  return Math.max(0, Math.min(100, Math.round(score)))
}

export type PayoffPoint = { price: number; pnl: number }

/** Simplified options P/L at expiry across underlying prices */
export function optionsPayoffCurve(opts: {
  side: 'short' | 'long'
  optionType: 'call' | 'put'
  strike: number
  spot: number
  qty?: number
  avgEntry?: number
  mark?: number
  points?: number
}): PayoffPoint[] {
  const {
    side, optionType, strike, spot,
    qty = 1, avgEntry = 0, mark = 0,
    points = 41,
  } = opts
  const mult = 100 * qty
  const premium = avgEntry || mark || 0
  const lo = Math.max(0.01, spot * 0.75)
  const hi = spot * 1.25
  const step = (hi - lo) / (points - 1)
  const out: PayoffPoint[] = []
  for (let i = 0; i < points; i++) {
    const price = lo + step * i
    let intrinsic = 0
    if (optionType === 'call') intrinsic = Math.max(0, price - strike)
    else intrinsic = Math.max(0, strike - price)
    let pnl: number
    if (side === 'short') {
      pnl = (premium - intrinsic) * mult
    } else {
      pnl = (intrinsic - premium) * mult
    }
    out.push({ price: Math.round(price * 100) / 100, pnl: Math.round(pnl) })
  }
  return out
}

export function riskContributionRows(
  positions: any[],
  opts?: { max?: number; useMaxLoss?: boolean },
): { name: string; value: number; symbol: string; pct: number }[] {
  const max = opts?.max ?? 12
  const useMaxLoss = opts?.useMaxLoss !== false
  const rows = (positions || [])
    .filter(p => !p.risk_excluded)
    .map(p => {
      const v = useMaxLoss
        ? Math.max(0, Number(p.max_loss) || 0)
        : Math.max(0, Number(p.market_value) || 0)
      return { name: p.symbol || '?', symbol: p.symbol || '?', value: v }
    })
    .filter(r => r.value > 0)
    .sort((a, b) => b.value - a.value)
  const total = rows.reduce((s, r) => s + r.value, 0) || 1
  return rows.slice(0, max).map(r => ({
    ...r,
    pct: Math.round((r.value / total) * 1000) / 10,
  }))
}

export function heatColor(value: number, max: number): string {
  const t = Math.min(1, Math.max(0, value / Math.max(max, 0.01)))
  if (t < 0.33) return `rgba(34, 197, 94, ${0.25 + t})`
  if (t < 0.66) return `rgba(245, 158, 11, ${0.35 + t * 0.4})`
  return `rgba(239, 68, 68, ${0.45 + t * 0.35})`
}
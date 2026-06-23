/** Thesis validity / drift gap helpers for broker proposals */

export type ThesisValidity = {
  ok?: boolean
  label?: string
  valid_low?: number
  valid_high?: number
  entry?: number
  stop?: number
  target?: number
  current_price?: number | null
  drift_pct?: number | null
  current_rr?: number | null
  planned_rr?: number | null
  room_up_pct?: number | null
  room_down_pct?: number | null
  zone_status?: string
  zone_color?: string
  reasons?: string[]
  actionable?: boolean
}

const ZONE_COLORS: Record<string, string> = {
  green: '#22c55e',
  yellow: '#f59e0b',
  red: '#ef4444',
  gray: '#94a3b8',
}

export function zoneColor(status?: string, fallback?: string): string {
  if (fallback && ZONE_COLORS[fallback]) return ZONE_COLORS[fallback]
  const s = String(status || '').toLowerCase()
  if (s === 'comfortable') return ZONE_COLORS.green
  if (s === 'approaching') return ZONE_COLORS.yellow
  if (s === 'at_risk' || s === 'invalid') return ZONE_COLORS.red
  return ZONE_COLORS.gray
}

export function brokerOf(accountKey: string): 'Schwab' | 'Fidelity' | '—' {
  const k = (accountKey || '').toLowerCase()
  if (k.startsWith('fidelity')) return 'Fidelity'
  if (k.startsWith('schwab')) return 'Schwab'
  return '—'
}

export function fmtMoney(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}k`
  return `$${Math.round(n)}`
}

export function tradeEconomics(shares: number, entry: number, stop: number, target: number) {
  const sh = Number(shares) || 0
  const en = Number(entry) || 0
  const st = Number(stop) || 0
  const tg = Number(target) || 0
  const riskPs = Math.max(0, en - st)
  const rewardPs = Math.max(0, tg - en)
  return {
    shares: sh,
    investment: sh && en ? sh * en : null,
    max_risk: sh && riskPs ? riskPs * sh : null,
    profit_at_target: sh && rewardPs ? rewardPs * sh : null,
  }
}
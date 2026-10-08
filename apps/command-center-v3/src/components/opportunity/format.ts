/** Shared formatters + labels for the opportunity modal, ranking table and widgets (kept out of the lazily loaded modal). */
import { TOKENS } from '../../lib/designTokens'

export const money = (v: any, d = 2) => (v == null || !Number.isFinite(Number(v)) ? '—' : `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })}`)
export const pct = (v: any, d = 1) => (v == null || !Number.isFinite(Number(v)) ? '—' : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(d)}%`)
export const num = (v: any, d = 2) => (v == null || !Number.isFinite(Number(v)) ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }))
export const big = (v: any) => {
  const n = Number(v)
  if (v == null || !Number.isFinite(n)) return '—'
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`
  return `$${n.toFixed(0)}`
}
export const vol = (v: any) => {
  const n = Number(v)
  if (v == null || !Number.isFinite(n)) return '—'
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(0)}K` : String(n)
}

export function convictionColor(c?: number | null) {
  if (c == null) return TOKENS.neutral
  return c >= 80 ? TOKENS.success : c >= 65 ? TOKENS.info : c >= 50 ? TOKENS.warning : TOKENS.danger
}
export const STANCE_COLOR: Record<string, string> = { ADD: TOKENS.success, RE_ENTER: TOKENS.success, HOLD: TOKENS.info, WATCH: TOKENS.neutral, TRIM: TOKENS.warning, EXIT: TOKENS.danger }
export const TYPE_LABEL: Record<string, string> = { new_position: 'New Position', existing: 'Existing Position', re_entry: 'Re-Entry', add_on: 'Add-On', exit_candidate: 'Exit Candidate', watchlist: 'Watchlist' }
export const COND_LABEL: Record<string, string> = { breaking_out: 'Breaking Out', pullback: 'Pullback', oversold: 'Oversold', overbought: 'Overbought', trend_continuation: 'Trend Continuation', range: 'Range-bound' }
export const typeLabel = (t?: string) => TYPE_LABEL[t || ''] || t || '—'
export const condLabel = (t?: string) => COND_LABEL[t || ''] || t || '—'


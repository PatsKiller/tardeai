/**
 * Stop display vocabulary for the stop desks (board 15 "Stop source", board 3 "Your book", board 14 Protection).
 * Pure display: every category, distance and dollar figure comes from the CIO record (`cio_truth.resolve`
 * positions rows). Nothing here decides protection — `broker_protected` stays the server's rule.
 */
export type StopCategory = 'active' | 'pending_activation' | 'filled' | 'unknown' | 'planned' | 'none'

export const STOP_CATEGORY_LABEL: Record<StopCategory, string> = {
  active: 'Broker resting · active',
  pending_activation: 'Broker resting · pending activation',
  filled: 'Broker stop filled · awaiting holdings sync',
  unknown: 'Broker stop · state not recorded',
  planned: 'Planned level · no resting order',
  none: 'No stop',
}

export const STOP_CATEGORY_TONE: Record<StopCategory, 'good' | 'warn' | 'bad'> = {
  active: 'good', pending_activation: 'warn', filled: 'warn', unknown: 'warn', planned: 'warn', none: 'bad',
}

/** The server publishes `stop_category`; an older record is mapped from stop_state/stop_source the same way. */
export function stopCategory(p: any): StopCategory {
  const c = p?.stop_category
  if (c && c in STOP_CATEGORY_LABEL) return c as StopCategory
  const s = p?.stop_state
  if (s === 'active' || s === 'pending_activation' || s === 'filled' || s === 'unknown') return s
  if (s === 'pending') return 'pending_activation'
  return p?.stop_source === 'planned' && p?.stop_price != null ? 'planned' : 'none'
}

const num = (v: unknown) => typeof v === 'number' && Number.isFinite(v) ? v : null
export const stopDistancePct = (p: any) => num(p?.distance_to_stop_pct) ?? num(p?.resting_stop_distance_pct) ?? num(p?.planned_stop_distance_pct)
export const stopLossUsd = (p: any) => num(p?.loss_at_stop_usd) ?? num(p?.loss_at_resting_stop_usd)

/** "Review protection" on Home opens the Risk position sheet for that account+symbol (item id `protection:<account>:<symbol>`). */
export function protectionHref(item: any): string | null {
  const id = typeof item?.id === 'string' ? item.id : ''
  const m = /^protection:([^:]+):(.+)$/.exec(id)
  if (!m) return null
  const href = typeof item?.href === 'string' ? item.href : typeof item?.action?.where === 'string' ? item.action.where : ''
  if (!/^(\/v3)?\/risk(\?|$)/.test(href)) return null
  const q = new URLSearchParams({ tab: 'exposure', detail: `position:${m[1]}:${m[2]}` })
  return `/risk?${q.toString()}`
}

/** Group symbols for a short label: ["SPCX","V","SPCX"] → "SPCX ×2, V". */
export function symbolList(rows: { symbol?: string }[]): string {
  const counts = new Map<string, number>()
  for (const r of rows) if (r?.symbol) counts.set(r.symbol, (counts.get(r.symbol) || 0) + 1)
  return [...counts].map(([s, n]) => n > 1 ? `${s} ×${n}` : s).join(', ')
}

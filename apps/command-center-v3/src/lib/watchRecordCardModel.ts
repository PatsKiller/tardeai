/** Presentation over existing Watch/CIO evidence. No source fetches, writes or readiness decisions. */
import type { ListRow, WatchMarketFacts, WatchMarketField } from './watchListsModel.ts'
import type { RailState } from './watchTokens.ts'

export function positive(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null
}

export function ladderGeometry(support: number | null, resistance: number | null, price: number | null,
  zone: [number | null, number | null]): { price: number | null; zone: [number, number] | null } | null {
  const low = positive(support), high = positive(resistance)
  if (low == null || high == null || high <= low) return null
  const min = low * 0.97, max = high * 1.01
  const at = (value: number) => Math.max(0, Math.min(100, (value - min) / (max - min) * 100))
  const p = positive(price), z0 = positive(zone[0]), z1 = positive(zone[1])
  return { price: p == null ? null : at(p), zone: z0 != null && z1 != null && z1 >= z0 ? [at(z0), at(z1)] : null }
}

export function levelPercent(value: number | null, price: number | null): string {
  if (positive(value) == null || positive(price) == null) return '—'
  const pct = (value! - price!) / price! * 100
  return `${pct > 0 ? '+' : pct < 0 ? '−' : ''}${Math.abs(pct).toFixed(1)}%`
}

export function rowZone(row: ListRow): [number | null, number | null] {
  const ref = (row as ListRow & { levels_ref?: Record<string, unknown> }).levels_ref || {}
  const zone = row.reentry?.entry_zone
  return [positive(zone?.[0] ?? ref.entry_low_ref), positive(zone?.[1] ?? ref.entry_high_ref)]
}

export function blockingReasons(row: ListRow): string[] {
  const ranked = [...row.conflicts].sort((a, b) => (a.kind === 'trade_ai_block' ? 0 : 1) - (b.kind === 'trade_ai_block' ? 0 : 1))
  const reasons = ranked.map(c => c.summary).filter(Boolean)
  const state = String(row.trade_ai_state || '').toUpperCase()
  if (!reasons.length && ['DETERMINISTIC_FAIL', 'BLOCK', 'BLOCKED', 'NOGO', 'NO_GO', 'AVOID'].includes(state)) reasons.push(`Trade AI ${state.replace(/_/g, ' ').toLowerCase()}`)
  if (!reasons.length && row.next_action.kind === 'resolve_conflict') reasons.push(row.next_action.reason)
  return Array.from(new Set(reasons))
}

export function cardRail(row: ListRow): RailState {
  if (row.conflicts.length) return 'breach'
  if (blockingReasons(row).length || ['resolve_conflict', 'review_add', 'decide'].includes(row.next_action.kind)) return 'attention'
  return row.lane === 'actionable' ? 'favorable' : 'neutral'
}

export function cycleHeaderSort(current: string | null, header: 'conviction' | 'setup'): string {
  if (header === 'setup') return current === 'setup' ? '' : 'setup'
  return current === 'conviction_desc' ? 'conviction_asc' : current === 'conviction_asc' ? '' : 'conviction_desc'
}

export function rowMarketFacts(row: ListRow): WatchMarketFacts {
  if (row.market_facts) return row.market_facts
  // Prospects already carry these references. Expose their missing provenance;
  // never replace the MyList canonical artifact or invent a provider/time.
  const ref = (row as ListRow & { levels_ref?: Record<string, unknown> }).levels_ref || {}
  const base: WatchMarketField = { value: null, as_of: null, source: null, source_label: 'Source not exposed by record',
    stale: null, freshness: 'UNKNOWN', reason: 'Original source and level observation time are not exposed by this Watch record.' }
  return { schema: 'WatchMarketFacts@v1', evaluated_at: '',
    price: { ...base, value: positive(row.price), as_of: row.price_as_of || null,
      reason: 'Original quote source and freshness verdict are not exposed by this Watch record.' },
    support: { ...base, value: positive(ref.support_ref) }, resistance: { ...base, value: positive(ref.resistance_ref) } }
}

/** Watch lists — page model for My Watchlist, System Suggests, Full universe and the position filters
 *  (operator 2026-10-23: "where is my traditional watch list ... and where is the automated watch list";
 *  "it should be tracked that formerly held ... if I made money with it or not"; "we should be able to filter on this").
 *
 *  The server owns every judgment and every filter:
 *    GET /api/v3/data-broker/watch-curation  (scripts/lib/data_broker/watch_curation.py)  — My Watchlist + System Suggests
 *    GET /api/v3/data-broker/watch-universe  (scripts/lib/data_broker/watch_universe.py)  — Full universe on Watch
 *    GET /api/v3/data-broker/watch-prospects (scripts/lib/data_broker/watch_prospects.py) — Prospects lanes
 *  Position filters are URL query parameters passed straight through to those endpoints (bookmarkable); the
 *  tooltip of each filter is the server's own description of what it does (``position_filters[key].server``).
 *  This file shapes values for display only. No colour literals (design tokens). */
import type { ProspectRow } from './watchProspectsModel.ts'

export type PositionState = 'held' | 'formerly_held' | 'never_held'
export type RoundTrip = {
  entry_at: string | null; entry_price: number | null; exit_at: string | null; exit_price: number | null
  pnl_usd: number | null; pnl_pct: number | null; result: 'won' | 'lost' | 'breakeven' | null
  r: number | null; r_basis: string | null; exit_cause: string; exit_cause_label: string
  exit_cause_evidence?: string | null; stop_raised?: number | null; stop_initial?: number | null; stop_last?: number | null
  hold_days?: number | null; noise_vs_trend?: string | null; noise_vs_trend_basis?: string | null
}
export type ReentryAdvice = {
  state: string; readiness: 'ready' | 'near' | 'waiting' | 'invalidated'; action?: string | null; reason?: string | null
  distance_pct: number | null; entry_zone: (number | null)[]; reclaim: number | null
  alert_levels: { reference: string; level: number | null; means: string }[]
  conditions: { id: string; text: string; met: boolean | null }[]
}
export type PositionFacts = {
  position_state?: PositionState; position_label?: string; last_sell_at?: string | null
  last_round_trip?: RoundTrip | null; reentry?: ReentryAdvice | null
}
export type Membership = { kind: string; label: string; at: string | null; ref: unknown }
export type ListRow = ProspectRow & PositionFacts & {
  mine?: boolean; starred?: boolean; membership?: Membership[]
  expiry_suggestion?: { reason: string; suggest: string } | null
  universe_rank?: number | null
  suggestion?: { symbol: string; universe_rank: number; position: number; status: string; reason: string; top_factor: string | null }
}
export type FilterSpec = { label: string; kind: 'multi' | 'single' | 'number'; options?: string[]; server: string }
export type Facets = Record<string, Record<string, number>>

/** Position filter keys, in display order (mirror of watch_position_facts.FILTERS; the server is the authority). */
export const POSITION_FILTER_KEYS = [
  'position', 'result', 'pnl_usd_min', 'pnl_usd_max', 'pnl_pct_min', 'pnl_pct_max', 'exit_cause', 'exited_within',
  'reentry', 'reentry_dist_min', 'reentry_dist_max', 'r_min', 'r_max',
] as const
export const POSITION_SORTS = ['formerly_held_first', 'exit_date', 'pnl_pct', 'pnl_usd', 'r', 'reentry_distance'] as const
export const OPTION_LABEL: Record<string, string> = {
  held: 'Held', formerly_held: 'Formerly held', never_held: 'Never held',
  won: 'Won', lost: 'Lost', breakeven: 'Breakeven',
  stop: 'Stop hit', trailing: 'Trailing stop', target: 'Target', manual: 'Manual', time: 'Time', unknown: 'Unknown',
  '1d': '≤ 1 day', '1w': '≤ 1 week', '1m': '≤ 1 month', older: 'Older',
  ready: 'Ready', near: 'Near', waiting: 'Waiting', invalidated: 'Invalidated',
  formerly_held_first: 'Formerly held first', exit_date: 'Exit date', pnl_pct: 'P/L %', pnl_usd: 'P/L $', r: 'R multiple',
  reentry_distance: 'Closest to re-entry',
}

/** The position filters present in a URLSearchParams, as a plain object (empty values dropped). */
export function positionQuery(sp: URLSearchParams): Record<string, string> {
  const out: Record<string, string> = {}
  for (const k of POSITION_FILTER_KEYS) {
    const v = (sp.get(k) || '').trim()
    if (v) out[k] = v
  }
  const s = sp.get('psort')
  if (s && (POSITION_SORTS as readonly string[]).includes(s)) out.sort = s
  return out
}

/** Toggle one option of a multi-select filter in a comma list. */
export function toggleOption(current: string | null, opt: string): string {
  const set = new Set((current || '').split(',').map(x => x.trim()).filter(Boolean))
  if (set.has(opt)) set.delete(opt)
  else set.add(opt)
  return [...set].join(',')
}

export function activeCount(sp: URLSearchParams): number {
  return POSITION_FILTER_KEYS.filter(k => (sp.get(k) || '').trim()).length
}

export function withQuery(path: string, q: Record<string, string>): string {
  const qs = new URLSearchParams(q).toString()
  return qs ? `${path}${path.includes('?') ? '&' : '?'}${qs}` : path
}

export function unwrapAny<T = any>(raw: any): T | null {
  if (!raw) return null
  const d = raw?.data && typeof raw.data === 'object' && (raw.data.schema || raw.data.items || raw.data.my_watchlist) ? raw.data : raw
  return d && d.ok !== false ? (d as T) : null
}

// ── display ─────────────────────────────────────────────────────────────────

const sgn = (v: number, d = 2) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(d)}`
export function money(v: number | null | undefined): string {
  return v == null ? '—' : `$${Number(v).toFixed(2)}`
}
export function day(iso: string | null | undefined): string {
  return iso ? String(iso).slice(5, 10).replace('-', '/') : '—'
}

/** "+1.48% · +$189.73 · 0.36R · Trailing stop" — the last round trip in one cell. */
export function roundTripLabel(rt: RoundTrip | null | undefined): string {
  if (!rt) return '—'
  const bits: string[] = []
  if (rt.pnl_pct != null) bits.push(`${sgn(rt.pnl_pct)}%`)
  if (rt.pnl_usd != null) bits.push(`${rt.pnl_usd >= 0 ? '+' : '−'}$${Math.abs(rt.pnl_usd).toFixed(2)}`)
  if (rt.r != null) bits.push(`${rt.r.toFixed(2)}R`)
  bits.push(rt.exit_cause_label)
  return bits.join(' · ')
}

/** Entry → exit with dates: "10/19 $25.64 → 10/22 $26.02 (3 d)". */
export function roundTripPath(rt: RoundTrip | null | undefined): string {
  if (!rt) return '—'
  return `${day(rt.entry_at)} ${money(rt.entry_price)} → ${day(rt.exit_at)} ${money(rt.exit_price)}`
    + (rt.hold_days != null ? ` (${rt.hold_days} d)` : '')
}

export function resultTone(rt: RoundTrip | null | undefined): 'success' | 'danger' | 'neutral' {
  return rt?.result === 'won' ? 'success' : rt?.result === 'lost' ? 'danger' : 'neutral'
}

export function readinessTone(a: ReentryAdvice | null | undefined): 'success' | 'warning' | 'danger' | 'neutral' {
  return a?.readiness === 'ready' ? 'success' : a?.readiness === 'near' ? 'warning' : a?.readiness === 'invalidated' ? 'danger' : 'neutral'
}

/** "Waiting · +3.7% to zone $24.80–$25.10 · or close > $26.02". */
export function reentryLabel(a: ReentryAdvice | null | undefined): string {
  if (!a) return '—'
  const [lo, hi] = a.entry_zone || []
  const bits = [OPTION_LABEL[a.readiness] || a.readiness]
  if (a.distance_pct != null) bits.push(`${sgn(a.distance_pct, 1)}% to zone`)
  if (lo != null && hi != null) bits.push(`${money(lo)}–${money(hi)}`)
  if (a.reclaim != null) bits.push(`or close > ${money(a.reclaim)}`)
  return bits.join(' · ')
}

export function alertLevelsLabel(a: ReentryAdvice | null | undefined): string {
  return (a?.alert_levels || []).filter(x => x.level != null).map(x => Number(x.level).toFixed(3).replace(/0+$/, '').replace(/\.$/, '')).join(' / ') || '—'
}

/** Risk / Reward / R:R in one cell: "−4.2% / +20.2% · 4.8x". */
export function riskRewardCell(rr: { risk_pct?: number | null; reward_pct?: number | null; rr?: number | null } | null | undefined): string {
  if (!rr) return '—'
  const risk = rr.risk_pct != null ? `−${Math.abs(Number(rr.risk_pct)).toFixed(1)}%` : '—'
  const reward = rr.reward_pct != null ? `+${Number(rr.reward_pct).toFixed(1)}%` : '—'
  const ratio = rr.rr != null ? `${Number(rr.rr).toFixed(1)}x` : '—'
  return `${risk} / ${reward} · ${ratio}`
}

export function positionChip(f: PositionFacts): { label: string; tone: 'info' | 'ai' | 'neutral'; tip: string } | null {
  if (f.position_state === 'held') return { label: 'held', tone: 'info', tip: 'Held now, per the broker-synced Watch held reader.' }
  if (f.position_state === 'formerly_held') {
    return { label: `formerly held · sold ${day(f.last_sell_at)}`, tone: 'ai',
      tip: 'Not held now; the broker ledger shows a sell inside the last year. The last round trip and re-entry advice come from the CIO prospect lifecycle.' }
  }
  return null
}

/** Count chips for one filter key from the server facets, in the option order the server declares. */
export function chipsFor(key: string, spec: FilterSpec | undefined, facets: Facets | undefined): { opt: string; label: string; count: number }[] {
  const opts = spec?.options || []
  return opts.map(opt => ({ opt, label: OPTION_LABEL[opt] || opt, count: (facets?.[key] || {})[opt] || 0 }))
}

/** Armed Watch alerts per symbol (active only). */
export function armedBySymbol(rawAlerts: any): Record<string, number> {
  const d = rawAlerts?.data ?? rawAlerts
  const list: any[] = Array.isArray(d?.alerts) ? d.alerts : Array.isArray(d?.items) ? d.items : Array.isArray(d) ? d : []
  const out: Record<string, number> = {}
  for (const a of list) if (a && a.active) { const s = String(a.symbol || '').toUpperCase(); if (s) out[s] = (out[s] || 0) + 1 }
  return out
}

export const HOW_FALLBACK = [
  { id: 'my_watchlist', title: 'My Watchlist', body: 'Your names: starred, your personal watchlist, your watch directives and names you added or proposed. Starred first; never dropped by a cap or expiry.' },
  { id: 'suggests', title: 'System Suggests', body: 'The top 20 (up to 30) of the Full universe ranking, minus what you hold, what is yours and what you dismissed. Each entry and exit has a reason.' },
  { id: 'prospects', title: 'Prospects', body: 'Every Watch name by stage. Your names are always listed.' },
  { id: 'full_universe', title: 'Full universe (research)', body: 'Everything the CIO curator scored, ranked by conviction.' },
  { id: 'proposals', title: 'Trading → Proposals', body: 'Sized trade ideas waiting for your approve / reject. Watching a name never creates one.' },
]

export const TAB_TIPS: Record<string, string> = {
  'my-watchlist': 'Your names — starred, personal watchlist, your directives and adds. Never dropped by caps or expiry.',
  suggests: 'What the system proposes for your list: the top of the Full universe ranking, minus held, yours and dismissed.',
  prospects: 'Every Watch name (yours and the system\'s) by stage: actionable, forming, re-entry, held, expired.',
  opportunities: 'Full universe — everything the CIO curator scored, ranked by conviction. Research, not a to-do list.',
}

/** Queue a CIO symbol review (existing endpoint POST /api/v3/opportunities/{symbol}/review-request). */
export async function askCioReview(symbol: string, note: string): Promise<string> {
  try {
    const res = await fetch(`/api/v3/opportunities/${encodeURIComponent(symbol)}/review-request`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note: note.slice(0, 240) }),
    }).then(x => x.json())
    const d = res?.data ?? res
    return d?.ok ? (d.already_open ? 'A CIO review is already queued for this symbol.' : 'CIO review queued.') : `Could not queue: ${d?.error || 'error'}`
  } catch (e) {
    return `Could not queue: ${String(e).slice(0, 80)}`
  }
}

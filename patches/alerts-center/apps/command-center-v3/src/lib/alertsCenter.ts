/**
 * Alerts Center fan-in (2026-09-29) — pure half of the header ⚑ ALERTS modal.
 *
 * Three honest queues, never collapsed into one fake GO feed:
 *   - Entry:   GET /api/v2/buy-ready/packets (BUY_READY / ENTRY_NEAR …)
 *   - Telegram: GET /api/v2/communications/events?limit=250 (outbound)
 *   - Setups:  GET /api/v2/trade-ai/summary → setup_run_summary (one row)
 *
 * Chrome words ALERT/ENTRY/READY/WATCH are never treated as tickers even when
 * entity_refs claim them. Advisory only — no order controls.
 *
 * No React import so `node src/lib/alertsCenter.test.ts` runs it.
 */
import { renderSetupCounts, type SetupRunSummary } from './setupRunSummary.ts'

/** Title chrome that must never become a dossier / Scalp symbol. */
export const ALERT_CHROME_SYMBOLS = new Set([
  'ALERT', 'ENTRY', 'READY', 'WATCH', 'NEAR', 'SETUP', 'TARGET', 'LIMIT',
  'BUY', 'SELL', 'HOLD', 'GO', 'WAIT', 'NOGO', 'CIO', 'ADVISORY',
])

export type AlertKind = 'entry' | 'telegram' | 'setups'

export type AlertRow = {
  id: string
  kind: AlertKind
  title: string
  subtitle?: string
  when?: string | null
  symbols: string[]
  /** Primary deep link (Scalp for entry; Communications for telegram; Trading Trade AI for setups). */
  href: string
  /** Secondary dossier link for a real instrument, never chrome. */
  dossierHref?: string | null
  state?: string | null
  raw?: unknown
}

export function isChromeSymbol(sym: string | null | undefined): boolean {
  const s = String(sym || '').trim().toUpperCase()
  return !s || ALERT_CHROME_SYMBOLS.has(s)
}

/** Drop chrome + empty; preserve order; de-dupe. */
export function realSymbols(candidates: Iterable<string | null | undefined>): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const c of candidates) {
    const s = String(c || '').trim().toUpperCase()
    if (!s || isChromeSymbol(s) || seen.has(s)) continue
    seen.add(s)
    out.push(s)
  }
  return out
}

/** Primary surface for BUY_READY / ENTRY_NEAR — Scalp tab, never /watch/intelligence/ALERT. */
export function entryPrimaryHref(symbol: string | null | undefined): string {
  const s = realSymbols([symbol])[0]
  if (!s) return '/v3/trading?tab=Scalp'
  return `/v3/trading?tab=Scalp&symbol=${encodeURIComponent(s)}`
}

export function dossierHref(symbol: string | null | undefined): string | null {
  const s = realSymbols([symbol])[0]
  return s ? `/v3/watch/intelligence/${encodeURIComponent(s)}` : null
}

type PacketRow = {
  symbol?: string | null
  state?: string | null
  saved_at?: string | null
  packet_age_h?: number | null
  price?: number | null
  zone?: { position?: string | null; distance_pct?: number | null }
  cio_verdict?: { verdict?: string | null }
  catalyst?: string | null
}

export function rowsFromBuyReadyPackets(payload: any): AlertRow[] {
  const data = payload?.data ?? payload
  const rows: PacketRow[] = Array.isArray(data?.rows) ? data.rows : []
  return rows.map((r, i) => {
    const syms = realSymbols([r.symbol])
    const sym = syms[0] || null
    const state = r.state ? String(r.state) : null
    const zone = r.zone?.position === 'in_zone' ? 'in zone'
      : r.zone?.position === 'above' ? `${r.zone.distance_pct}% above zone`
      : r.zone?.position === 'below' ? `${r.zone.distance_pct}% below zone`
      : null
    const bits = [
      state?.replace(/_/g, ' '),
      zone,
      r.price != null ? `$${Number(r.price).toFixed(2)}` : null,
      r.cio_verdict?.verdict ? `CIO ${String(r.cio_verdict.verdict).replace(/_/g, ' ')}` : null,
    ].filter(Boolean)
    return {
      id: `entry:${sym || i}:${state || 'x'}`,
      kind: 'entry' as const,
      title: sym ? `${sym} — ${state?.replace(/_/g, ' ') || 'entry packet'}` : (state || 'entry packet'),
      subtitle: bits.join(' · ') || (r.catalyst ? String(r.catalyst).slice(0, 120) : undefined),
      when: r.saved_at || null,
      symbols: syms,
      href: entryPrimaryHref(sym),
      dossierHref: dossierHref(sym),
      state,
      raw: r,
    }
  })
}

type CommEvent = {
  event_id?: string | null
  id?: string | null
  direction?: string | null
  subject_key?: string | null
  short_summary?: string | null
  created_at?: string | null
  produced_at?: string | null
  status?: string | null
  entity_refs?: Array<{ symbol?: string | null } | string> | null
  symbols?: string[] | null
  message_class?: string | null
}

function eventSymbols(ev: CommEvent): string[] {
  const fromRefs: string[] = []
  for (const r of ev.entity_refs || []) {
    if (typeof r === 'string') fromRefs.push(r)
    else if (r && typeof r === 'object') fromRefs.push(String(r.symbol || ''))
  }
  return realSymbols([...(ev.symbols || []), ...fromRefs])
}

function humanizeCommTitle(ev: CommEvent): string {
  const summary = (ev.short_summary || '').replace(/\s+/g, ' ').trim()
  if (summary) return summary.slice(0, 140)
  const raw = (ev.subject_key || '').replace(/\s+/g, ' ').trim()
  if (raw.startsWith('telegram:')) {
    const rest = raw.split(':').slice(2).join(':')
    if (rest) return rest.slice(0, 140)
  }
  return raw.slice(0, 140) || 'Telegram event'
}

export function rowsFromCommunicationsEvents(payload: any): AlertRow[] {
  const data = payload?.data ?? payload
  const events: CommEvent[] = Array.isArray(data?.events) ? data.events
    : Array.isArray(data?.rows) ? data.rows
    : Array.isArray(data) ? data
    : []
  const out: AlertRow[] = []
  for (const ev of events) {
    const dir = String(ev.direction || '').toUpperCase()
    if (dir && dir !== 'OUTBOUND' && dir !== 'OUT') continue
    const syms = eventSymbols(ev)
    const id = String(ev.event_id || ev.id || `${ev.created_at || ''}:${humanizeCommTitle(ev)}`)
    out.push({
      id: `telegram:${id}`,
      kind: 'telegram',
      title: humanizeCommTitle(ev),
      subtitle: [
        ev.message_class || null,
        ev.status || null,
        syms.length ? syms.join(', ') : null,
      ].filter(Boolean).join(' · ') || undefined,
      when: ev.created_at || ev.produced_at || null,
      symbols: syms,
      href: '/v3/communications',
      dossierHref: dossierHref(syms[0]),
      state: ev.status || null,
      raw: ev,
    })
  }
  return out
}

/** One honest Setups row from trade-ai/summary — never invents GO cards from Telegram. */
export function rowsFromTradeAiSummary(payload: any): AlertRow[] {
  const data = payload?.data ?? payload
  const s: SetupRunSummary | null = (data?.setup_run_summary || data?.setupRunSummary || null) as SetupRunSummary | null
  if (!s) {
    return [{
      id: 'setups:unavailable',
      kind: 'setups',
      title: 'SETUPS · LATEST RUN — unavailable',
      subtitle: 'No setup_run_summary on /api/v2/trade-ai/summary',
      when: null,
      symbols: [],
      href: '/v3/trading?tab=Trade+AI',
      dossierHref: null,
      state: 'DATA_UNAVAILABLE',
    }]
  }
  const rendered = renderSetupCounts(s)
  const counts = rendered.counts
  const label = s.run_label || s.run_id || 'latest run'
  return [{
    id: `setups:${s.run_id || s.run_timestamp || 'latest'}`,
    kind: 'setups',
    title: `SETUPS · ${label}`,
    subtitle: [
      counts,
      rendered.population || null,
      rendered.healthDegraded && rendered.runHealthStatus ? rendered.runHealthStatus : null,
    ].filter(Boolean).join(' · ') || undefined,
    when: s.run_timestamp || s.run_date || null,
    symbols: [],
    href: '/v3/trading?tab=Trade+AI',
    dossierHref: null,
    state: s.freshness_status || s.count_integrity || null,
    raw: s,
  }]
}

export function fanInAlerts(input: {
  packets?: any
  events?: any
  tradeAiSummary?: any
}): AlertRow[] {
  return [
    ...rowsFromBuyReadyPackets(input.packets),
    ...rowsFromCommunicationsEvents(input.events),
    ...rowsFromTradeAiSummary(input.tradeAiSummary),
  ]
}

export type KindFilter = 'all' | AlertKind

export function filterAlerts(
  rows: AlertRow[],
  opts: { query?: string; kind?: KindFilter } = {},
): AlertRow[] {
  const kind = opts.kind || 'all'
  const q = (opts.query || '').trim().toUpperCase()
  return rows.filter(r => {
    if (kind !== 'all' && r.kind !== kind) return false
    if (!q) return true
    const hay = [r.title, r.subtitle, r.state, ...r.symbols].filter(Boolean).join(' ').toUpperCase()
    return hay.includes(q)
  })
}

export function shortcuts(): Array<{ label: string; href: string }> {
  return [
    { label: 'Communications', href: '/v3/communications' },
    { label: 'Re-Entry · Entry alerts', href: '/v3/portfolio/re-entry' },
    { label: 'Trading · Scalp', href: '/v3/trading?tab=Scalp' },
  ]
}

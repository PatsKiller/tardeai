/**
 * Open Trades desk model (operator-approved Gate 3 design OpenTrades.dc.html, 2026-10-22).
 *
 * Pure: turns /api/v2/open-trades/intelligence into the protect-first strip, the one position table,
 * the filter chips, the detail panel facts and the drawers. Reads only fields the endpoint serves
 * (open_trades_intelligence.py, accuracy fixes 2026-10-22): canonical mark with its own age, P/L =
 * shares × mark − basis, write-offs out of the headline, small positions folded into a drawer.
 * Never derives a stop level, a size or an order — display only.
 */

export type StopState = 'none' | 'near' | 'ok' | 'na'
export type DeskFilter = 'all' | 'unprot' | 'near' | 'loser' | 'paper'

export interface DeskRow {
  id: string
  sym: string
  account: string
  accountLabel: string
  paper: boolean
  shares: number | null
  avgCost: number | null
  mark: number | null
  markAsOf: string | null
  markAgeHours: number | null
  markStale: boolean
  quoteSource: string | null
  value: number | null
  pl: number | null
  plPct: number | null
  todayPct: number | null
  stopState: StopState
  stopText: string
  stopPrice: number | null
  tags: Array<'unprot' | 'near' | 'loser' | 'paper'>
  small: boolean
  writeOff: boolean
  raw: any
}

export interface DeskModel {
  rows: DeskRow[]          // the table: active, not small, not written off
  small: DeskRow[]         // drawer
  writeOffs: DeskRow[]     // drawer, excluded from every headline total
  protect: DeskRow[]       // no working stop, largest dollar exposure first
  accounts: string[]
  headline: {
    positions: number
    accounts: number
    unrealized: number | null
    writeOffCount: number
    writeOffPnl: number | null
    basisPending: number
    unprotectedCount: number
    unprotectedValue: number
  }
}

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

export function money(v: number | null | undefined, opts?: { signed?: boolean; cents?: boolean }): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const abs = Math.abs(v)
  const body = opts?.cents
    ? abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : Math.round(abs).toLocaleString('en-US')
  const sign = v < 0 ? '−' : opts?.signed ? '+' : ''
  return `${sign}$${body}`
}

export function price(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (v > 0 && v < 1) return `$${v.toFixed(4)}`
  return `$${v.toFixed(2)}`
}

export function sharesText(v: number | null | undefined, precise = false): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return Number.isInteger(v)
    ? v.toLocaleString('en-US')
    : v.toLocaleString('en-US', { maximumFractionDigits: precise || v < 1 ? 4 : 2 })
}

/** "12 min" / "3.4 h" / "6 d" — the age of one mark. */
export function ageText(hours: number | null | undefined): string {
  if (hours == null || !Number.isFinite(hours)) return 'age unknown'
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`
  if (hours < 48) return `${hours.toFixed(hours < 10 ? 1 : 0)} h`
  return `${Math.round(hours / 24)} d`
}

function stopOf(p: any): { state: StopState; text: string; price: number | null } {
  const shares = num(p?.shares)
  const stop = num(p?.stop_price)
  const dist = num(p?.stop_distance_pct)
  const protectedNow = p?.protection_state === 'protected' || !!p?.broker_stop
  if (p?.stop_eligible === false || p?.is_unstoppable_fund) {
    return { state: 'na', text: 'fund · stops not available', price: null }
  }
  if (protectedNow) {
    const where = stop != null ? `working ${price(stop)}` : 'working (trailing)'
    const away = dist != null ? ` · ${Math.abs(dist).toFixed(1)}% away` : ''
    return { state: p?.protection?.stop_near ? 'near' : 'ok', text: `${where}${away}`, price: stop }
  }
  if (shares != null && shares < 1) return { state: 'na', text: 'fractional · n/a', price: null }
  return { state: 'none', text: 'none', price: null }
}

export function toDeskRow(p: any, labels?: Record<string, string>): DeskRow {
  const account = String(p?.account ?? '—')
  const paper = p?.environment === 'paper'
  const stop = stopOf(p)
  const pl = num(p?.unrealized_pnl)
  const tags: DeskRow['tags'] = []
  if (stop.state === 'none') tags.push('unprot')
  if (stop.state === 'near') tags.push('near')
  if (pl != null && pl < 0) tags.push('loser')
  if (paper) tags.push('paper')
  return {
    id: `${account}:${p?.symbol}`,
    sym: String(p?.symbol ?? '—'),
    account,
    accountLabel: String(p?.account_label || labels?.[account] || account.replace(/_/g, ' ')),
    paper,
    shares: num(p?.shares),
    avgCost: num(p?.avg_cost ?? p?.entry_price),
    mark: num(p?.current_price),
    markAsOf: p?.mark_as_of ?? p?.price_updated_at ?? null,
    markAgeHours: num(p?.mark_age_hours),
    markStale: p?.mark_stale === true,
    quoteSource: p?.quote_source ?? null,
    value: num(p?.market_value),
    pl,
    plPct: num(p?.unrealized_pnl_pct),
    todayPct: num(p?.today_move_pct),
    stopState: stop.state,
    stopText: stop.text,
    stopPrice: stop.price,
    tags,
    small: p?.small_position === true,
    writeOff: p?.worthless === true,
    raw: p,
  }
}

export function buildDeskModel(data: any): DeskModel {
  const labels: Record<string, string> = data?.summary?.account_labels ?? {}
  const all: DeskRow[] = (data?.positions ?? []).map((p: any) => toDeskRow(p, labels))
  const writeOffs = all.filter((r: DeskRow) => r.writeOff)
  const active = all.filter((r: DeskRow) => !r.writeOff)
  const small = active.filter((r: DeskRow) => r.small)
  const rows = active.filter((r: DeskRow) => !r.small)
  const protect = rows.filter(r => r.stopState === 'none').sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
  const summary = data?.summary ?? {}
  const unrealized = num(summary.total_unrealized_pnl)
    ?? (active.some((r: DeskRow) => r.pl != null) ? active.reduce((s: number, r: DeskRow) => s + (r.pl ?? 0), 0) : null)
  return {
    rows,
    small,
    writeOffs,
    protect,
    accounts: Array.from(new Set(active.map((r: DeskRow) => r.account))) as string[],
    headline: {
      positions: active.length,
      accounts: new Set(active.map((r: DeskRow) => r.account)).size,
      unrealized,
      writeOffCount: writeOffs.length,
      writeOffPnl: num(summary.write_off_unrealized_pnl)
        ?? (writeOffs.length ? writeOffs.reduce((s: number, r: DeskRow) => s + (r.raw?.write_off_pnl ?? r.pl ?? 0), 0) : null),
      basisPending: active.filter((r: DeskRow) => r.pl == null).length,
      unprotectedCount: protect.length,
      unprotectedValue: protect.reduce((s, r) => s + (r.value ?? 0), 0),
    },
  }
}

export const DESK_FILTERS: Array<{ key: DeskFilter; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'unprot', label: 'No working stop' },
  { key: 'near', label: 'Stop near' },
  { key: 'loser', label: 'Losing' },
  { key: 'paper', label: 'Paper' },
]

export function filterRows(rows: DeskRow[], f: DeskFilter, account = 'all'): DeskRow[] {
  return rows.filter(r => (account === 'all' || r.account === account) && (f === 'all' || r.tags.includes(f)))
}

export type SortKey = 'value' | 'pl' | 'sym' | 'stop'
const STOP_RANK: Record<StopState, number> = { none: 3, near: 2, ok: 1, na: 0 }
export function sortRows(rows: DeskRow[], key: SortKey): DeskRow[] {
  const out = [...rows]
  if (key === 'sym') return out.sort((a, b) => a.sym.localeCompare(b.sym))
  if (key === 'pl') return out.sort((a, b) => (a.pl ?? Infinity) - (b.pl ?? Infinity))
  if (key === 'stop') return out.sort((a, b) => STOP_RANK[b.stopState] - STOP_RANK[a.stopState] || (b.value ?? 0) - (a.value ?? 0))
  return out.sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
}

/** Stop history lines for the detail panel — only what the endpoint already carries. */
export function stopHistory(p: any): string[] {
  const out: string[] = []
  const bs = p?.broker_stop
  if (bs) {
    const qty = num(bs.qty)
    const sp = num(bs.stop_price)
    const kind = String(bs.order_type || bs.type || 'STOP').replace(/_/g, ' ').toLowerCase()
    out.push(`Broker ${kind}${sp != null ? ` ${price(sp)}` : ''}${qty != null ? ` × ${sharesText(qty)}` : ''} · ${String(bs.status || 'working').toLowerCase()}`)
    if (bs.coverage === 'partial') out.push(`Covers ${sharesText(qty, true)} of ${sharesText(num(bs.held_qty), true)} shares held`)
    if (bs.coverage === 'oversized') out.push(`Stop quantity ${sharesText(qty, true)} is larger than the ${sharesText(num(bs.held_qty), true)} shares held`)
    if (bs.pilot_placed) out.push('Placed through the protective-stop pilot (2FA)')
  } else if (num(p?.stop_price) != null) {
    out.push(`${p?.environment === 'paper' ? 'Paper ledger' : 'Recorded'} stop ${price(num(p?.stop_price))} · not a working broker order`)
  }
  for (const n of (p?.news ?? [])) {
    if (out.length >= 5) break
    const title = String(n?.title || '')
    if (n?.source === 'hermes' && /stop|trigger|trail/i.test(title)) {
      const when = n?.published_at ? String(n.published_at).slice(5, 16).replace('T', ' ') : ''
      out.push(`${when ? `${when} · ` : ''}${title.length > 120 ? `${title.slice(0, 117)}…` : title}`)
    }
  }
  if (p?.protection?.top_recommendation) out.push(`Advisor: ${String(p.protection.top_recommendation).replace(/_/g, ' ').toLowerCase()}`)
  if (!out.length) out.push('No stop on record')
  return out
}

/** LQ-20261107-1253 — view model for the Home "Since last close" card (GET /api/v2/home/since-close).
 *  Pure: the wire in, what to draw out. The server builds the snapshot overnight; nothing here decides anything. */

export const SINCE_CLOSE_API = '/api/v2/home/since-close'

export interface SinceCloseNews { title: string; source: string; url?: string | null; published_at?: string | null }
export interface SinceCloseMove {
  symbol: string; held: boolean; price: number; change_pct: number; week_pct: number | null
  dollar_impact: number | null; close_tag: string; big_move: boolean; news: SinceCloseNews[]; no_news: boolean
}
export interface SinceCloseWindow { label: string; close_tag: string; session_date: string; session_open: boolean }
export interface SinceCloseFeedItem extends SinceCloseNews {
  kind: 'holding' | 'watch' | 'macro'; exposure: number; so_what: string
  holdings: Array<{ symbol: string; held: boolean; market_value: number | null; change_pct: number }>
}
export interface WeekAheadEvent { date: string; kind: 'macro' | 'fomc' | 'earnings' | 'ex_div'; label: string; time_et: string | null; symbols: string[] }
/** LQ-1257 CIO brief, rendered as written; every field optional because that producer owns the shape. */
export interface CioBriefWire {
  status: 'available' | 'pending'; label?: string; summary?: string; risk_tier?: string
  actions?: Array<{ symbol: string; action: string; reason?: string }>; week_ahead?: string[] | string
  [k: string]: unknown   // LQ-1257 writes data/runtime/cio_overnight_brief/latest.json; aliases are read in cioFrom()
}
export interface SinceCloseUpdated { at: string; at_et: string; reason: string; kind: 'first' | 'news' | 'move'; symbol?: string | null; headline?: string | null }
export interface SinceCloseToday { label: string; basis: string; since: string; moves: SinceCloseMove[]; news: SinceCloseFeedItem[] }
export interface SinceCloseWire {
  feed?: SinceCloseFeedItem[]
  updated?: SinceCloseUpdated | null
  today?: SinceCloseToday | null
  week_ahead?: { events: WeekAheadEvent[]; fed_speakers?: string }
  cio_brief?: CioBriefWire
  status: 'ok' | 'no_snapshot'
  window_now?: SinceCloseWindow
  window?: SinceCloseWindow
  generated_at?: string
  moves?: SinceCloseMove[]
  macro?: { headlines: SinceCloseNews[]; futures: { status: string; label?: string; quotes: Array<Record<string, unknown>> } }
  summary?: { source: 'llm' | 'cache' | 'deterministic'; text: string | null; lines: string[]; reason?: string }
  freshness?: { age_seconds: number | null; stale: boolean; window_current: boolean }
}

export interface SinceCloseModel {
  state: 'none' | 'collapsed' | 'full'
  label: string
  closeTag: string
  stale: boolean
  freshnessText: string
  summaryText: string | null
  summaryLines: string[]
  held: SinceCloseMove[]
  watch: SinceCloseMove[]
  headlines: SinceCloseNews[]
  futuresText: string
  feed: SinceCloseFeedItem[]
  today: SinceCloseToday | null
  updatedText: string | null
  collapsedNote: string | null
  weekAhead: WeekAheadEvent[]
  fedSpeakersText: string
  cio: { pending: boolean; label: string; summary: string | null; tier: string | null; actions: Array<{ symbol: string; text: string }> }
}

const etDay = (iso: string): string => new Date(iso).toLocaleDateString('en-CA', { timeZone: 'America/New_York' })

export const pctText = (n: number | null | undefined): string => (n == null || !Number.isFinite(n) ? '—' : `${n > 0 ? '+' : ''}${n.toFixed(1)}%`)
export const usdText = (n: number | null | undefined): string => {
  if (n == null || !Number.isFinite(n)) return '—'
  const a = Math.abs(Math.round(n)).toLocaleString('en-US')
  return `${n < 0 ? '−' : '+'}$${a}`
}

function ageText(sec: number | null | undefined): string {
  if (sec == null) return 'not built yet'
  if (sec < 90 * 60) return `built ${Math.max(1, Math.round(sec / 60))} min ago`
  return `built ${Math.round(sec / 3600)} h ago`
}

const first = (o: Record<string, unknown>, keys: string[]): unknown => keys.map(k => o[k]).find(v => v !== undefined && v !== null && v !== '')
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null)

/** Read the CIO brief as LQ-1257 writes it. The producer owns the shape, so a few plausible names are accepted for
 *  each field; whatever is absent is simply not drawn (the card never invents a tier or an action). */
export function cioFrom(b: CioBriefWire | null | undefined): SinceCloseModel['cio'] {
  if (!b || b.status !== 'available') return { pending: true, label: b?.label ?? 'CIO brief pending', summary: null, tier: null, actions: [] }
  const rec = b as Record<string, unknown>
  const risk = first(rec, ['risk_tier', 'tier', 'risk_level', 'risk'])
  const tier = str(risk) ?? (risk && typeof risk === 'object' ? str(first(risk as Record<string, unknown>, ['tier', 'level', 'label'])) : null)
  const raw = first(rec, ['actions', 'holding_actions', 'per_holding', 'holdings'])
  const actions = (Array.isArray(raw) ? raw : []).flatMap((x): Array<{ symbol: string; text: string }> => {
    if (!x || typeof x !== 'object') return []
    const o = x as Record<string, unknown>
    const symbol = str(first(o, ['symbol', 'ticker']))
    const action = str(first(o, ['action', 'recommendation', 'advice', 'stance']))
    const reason = str(first(o, ['reason', 'rationale', 'why', 'note']))
    return symbol && action ? [{ symbol, text: reason ? `${action} — ${reason}` : action }] : []
  })
  return { pending: false, label: 'CIO brief', summary: str(first(rec, ['summary', 'overview', 'brief', 'headline'])), tier, actions }
}

export function sinceCloseModel(w: SinceCloseWire | null | undefined, nowMs: number = Date.now()): SinceCloseModel {
  const win = w?.window_now ?? w?.window
  const base = { label: win?.label ?? 'Since last close', closeTag: win?.close_tag ?? 'last close' }
  const empty = { stale: true, freshnessText: 'not built yet', summaryText: null, summaryLines: [], held: [], watch: [], headlines: [], futuresText: 'futures feed pending', feed: [], today: null, updatedText: null, collapsedNote: null, weekAhead: [], fedSpeakersText: 'no feed — not listed', cio: { pending: true, label: 'CIO brief pending', summary: null, tier: null, actions: [] } }
  if (!w || w.status !== 'ok') return { state: 'none', ...base, ...empty }
  const moves = w.moves ?? []
  const fut = w.macro?.futures
  const stale = w.freshness?.stale ?? true
  const lines = w.summary?.lines ?? []
  return {
    // 09:30-16:00 ET on a trading day the card is one line; outside it, the full recap
    state: win?.session_open ? 'collapsed' : 'full',
    ...base,
    stale,
    freshnessText: ageText(w.freshness?.age_seconds) + (w.freshness?.window_current === false ? ' · a newer window is waiting for its first build' : ''),
    summaryText: w.summary?.text ?? null,
    // never an empty card: with no LLM text the deterministic lines stand in
    summaryLines: w.summary?.text ? [] : lines,
    held: moves.filter(m => m.held),
    watch: moves.filter(m => !m.held && (m.big_move || m.news.length > 0)),
    headlines: (w.macro?.headlines ?? []).slice(0, 5),
    feed: w.feed ?? [],
    weekAhead: w.week_ahead?.events ?? [],
    fedSpeakersText: w.week_ahead?.fed_speakers ?? 'no feed — not listed',
    today: w.today ?? null,
    updatedText: w.updated && w.updated.kind !== 'first' ? `updated ${w.updated.at_et} — ${w.updated.reason}` : null,
    // inside the session the one line says what just arrived on a held name, only if it arrived today (ET)
    collapsedNote: w.updated?.kind === 'news' && w.updated.symbol && w.updated.headline && etDay(w.updated.at) === etDay(new Date(nowMs).toISOString())
      ? `New: ${w.updated.symbol} ${w.updated.headline}` : null,
    cio: cioFrom(w.cio_brief),
    futuresText: fut?.status === 'available' && fut.quotes.length
      ? fut.quotes.map(q => `${String(q.symbol ?? q.name ?? '')} ${pctText(Number(q.change_pct))}`).join(' · ')
      : fut?.label ?? 'futures feed pending',
  }
}

/** LQ-20261107-1352 (design v5, operator-approved 2026-11-08) — the Home CIO card and the Market Risk panel.
 *  Wire: GET /api/v2/home/cio-card (schema HomeCioCard@v1, scripts/lib/home_cio_card.py). Every value on the wire
 *  carries source_id + as_of; a value the server could not trace is absent and is drawn as nothing or "—", never
 *  guessed here. This module only formats. Advisory only: nothing here sizes, orders or moves a stop. */
import type { Tone } from './designTokens'

export const CIO_CARD_API = '/api/v2/home/cio-card'

export interface Prov { source_id: string; as_of: string }
export interface Fact<T> extends Prov { value: T }

export interface Held extends Prov { readings_support: string; sessions_recorded: number; sessions_needed: number; held_tier: string }
export interface Driver extends Prov { name: string; state?: string; points?: number; detail?: string }
export interface WeekEvent extends Prov { kind: 'macro' | 'earnings'; date: string; time_et?: string; label: string; symbol?: string; held?: boolean }
export interface StopAction extends Prov {
  symbol: string; account?: string; answer: string; stop_now?: number; stop_qty?: number; held_qty?: number
  suggested_stop?: number; reason?: string; n?: number; of?: number
}
export interface SectorsFact extends Prov { stressed?: string[]; stressed_sectors?: number; measured?: number; down_5d?: number; resilient?: string[] }

export interface CioCard {
  tier?: Fact<string>; score?: Fact<number>; held?: Held; posture?: Fact<string>
  buys_gate?: Fact<string>; buys_until?: Fact<string>; buys_until_short?: Fact<string>; buys_line?: Fact<string>
  stops_total?: Fact<number>; stops_actionable?: Fact<number>
  largest_unprotected?: Prov & { symbol: string; account?: string; shares?: number; price?: number; value?: number }
  book?: Prov & { positions?: number; accounts?: number; cash?: number }
  reentry?: Prov & { ready?: number; near?: number; tracked?: number; line?: string }
  drivers?: Driver[]; score_sum?: Fact<number>
  calm?: Prov & { n: number; of: number; names?: string[]; details?: string[] }
  gaps?: (Prov & { name: string; detail?: string })[]
  sectors?: SectorsFact
  shock?: Fact<string>
  catalyst?: Prov & { event: string; date: string; time_et?: string; label: string }
  this_week?: WeekEvent[]
  do_now?: StopAction
  actions?: StopAction[]
}

export interface HedgeTrigger extends Prov { key: string; label: string; value: number; consider?: number; act?: number; fill?: number }
export interface RotateCandidate extends Prov {
  key: string; symbol: string; label: string; state?: string; leadership?: string; rs20?: number; dd20?: number; qualifies?: boolean
  close?: Fact<number>; avg20?: Fact<number>
  proposed?: { target_pct?: number; target_usd?: number; tranche1_usd?: number | null; shares?: number | null; proposed: true }
}
export interface PositionRow { symbol: string; account_label?: string; value_usd?: number; pct_account?: number; stressed_share?: number; usd_exposed?: number; stop_distance_pct?: number | null; stance?: string; stops_known?: boolean }
export interface StoppedOut extends Prov {
  symbol: string; exit_date?: string; exit_price?: number; exit_basis?: string; account_label?: string; held_elsewhere?: string[]
  last_close?: number; last_date?: string; pct_vs_exit?: number; verdict?: string; headline?: string; invalidation?: number
  stage1_met?: number; stage1_of?: number; waiting_for?: string[]
}
export interface ProtectItem extends Partial<StopAction> {
  kind: 'action' | 'watch'; symbol: string; account_label?: string; stop_distance_pct?: number; stressed_share?: number; value_usd?: number; stance?: string
  source_id: string; as_of: string
}

export interface CioPanel {
  header?: {
    tier?: Fact<string>; score?: Fact<number>; held?: Held; evaluated?: Fact<string>
    confirming?: Prov & { n: number; of: number }
    episode?: Prov & { tier?: string; opened_at?: string; acknowledged_at?: string }
    sectors?: SectorsFact
  }
  exposure?: {
    book_usd?: Fact<number>; cash_usd?: Fact<number>; cash_pct_book?: Fact<number>; stressed_usd?: Fact<number>; stressed_pct_book?: Fact<number>
    largest?: Prov & { symbol: string; account_label?: string; group?: string; share?: number }
  }
  protect?: ProtectItem[]
  hedge?: Prov & {
    verdict?: string; triggers?: HedgeTrigger[]; gap_to_consider_usd?: number; stressed_labels?: string[]; cash_pct_book?: number
    if_triggered?: { symbol: string; stress_led_by?: string[]; others?: string[]; proposed_size_usd?: number | null; proposed: true; staged?: number[]; basis?: string }
  }
  rotate?: Prov & {
    candidates?: RotateCandidate[]
    plan?: { proposed: true; tranche1_usd?: number; tranche1_pct_book?: number; cash_after_pct?: number; tranche2_after?: string; tranche3_when?: string; split?: number[]; rule?: string }
  }
  positions?: Prov & { rows?: PositionRow[]; more_count?: number; more_usd?: number; zero_exposure_symbols?: string[]; stops_known?: boolean }
  stopped_out?: StoppedOut[]
}

export interface CioNote { topic: string; text: string; source_id: string; as_of: string; compared_with?: string }

export interface CioCardWire {
  schema?: string; generated_at?: string; advisory_only?: boolean
  advice?: { ok: boolean; reason?: string | null }
  card?: CioCard; panel?: CioPanel; notes?: CioNote[]
}

/** The value of a provenance-carrying fact, or undefined when the server dropped it. */
export function fv<T>(f: Fact<T> | null | undefined): T | undefined {
  return f && f.source_id && f.as_of ? f.value : undefined
}

/** The card is drawn only from an evaluated market-risk record; otherwise Home keeps its previous cards. */
export function cardVisible(w: CioCardWire | null | undefined): w is CioCardWire & { card: CioCard } {
  return !!(w && w.schema === 'HomeCioCard@v1' && w.card && fv(w.card.tier))
}

/** The panel replaces the Orange/Red banner and the Yellow summary; at GREEN/BLUE Home draws what it drew before. */
export function panelVisible(w: CioCardWire | null | undefined): w is CioCardWire & { panel: CioPanel } {
  const t = String(fv(w?.panel?.header?.tier) ?? '').toUpperCase()
  return !!(w && w.schema === 'HomeCioCard@v1' && (t === 'RED' || t === 'ORANGE' || t === 'YELLOW'))
}

export function tierToneOf(tier: string | undefined): Tone {
  switch (String(tier ?? '').toUpperCase()) {
    case 'RED': return 'danger'
    case 'ORANGE': return 'elevated'
    case 'YELLOW': return 'warning'
    case 'GREEN': return 'success'
    case 'BLUE': return 'info'
    default: return 'neutral'
  }
}

const ET = 'America/New_York'

/** "Sun 9:00 PM ET" for an instant; '' when it is not a time. */
export function etTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('en-US', { timeZone: ET, weekday: 'short', hour: 'numeric', minute: '2-digit' }) + ' ET'
}

/** "Mon 11-02" for an instant, in Eastern. */
export function etDay(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const wd = d.toLocaleDateString('en-US', { timeZone: ET, weekday: 'short' })
  const md = d.toLocaleDateString('en-CA', { timeZone: ET }).slice(5)
  return `${wd} ${md}`
}

/** "Tue 11-10" for a calendar date (YYYY-MM-DD); the weekday is the calendar's, no time zone shift. */
export function calDay(date: string | null | undefined): string {
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return date ?? ''
  const [y, m, d] = date.split('-').map(Number)
  const wd = new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-US', { timeZone: 'UTC', weekday: 'short' })
  return `${wd} ${date.slice(5)}`
}

/** Whole calendar days from today (Eastern) to `date`; null when either side is unreadable. */
export function daysUntil(date: string | null | undefined, nowMs: number): number | null {
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return null
  const today = new Date(nowMs).toLocaleDateString('en-CA', { timeZone: ET })
  const a = Date.parse(`${today}T00:00:00Z`), b = Date.parse(`${date}T00:00:00Z`)
  if (Number.isNaN(a) || Number.isNaN(b)) return null
  return Math.round((b - a) / 86_400_000)
}

export function usd(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—'
  return `${n < 0 ? '−' : ''}$${Math.round(Math.abs(n)).toLocaleString('en-US')}`
}

export function usdShort(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—'
  const a = Math.abs(n), s = n < 0 ? '−' : ''
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(2)}M`
  if (a >= 1e4) return `${s}$${(a / 1e3).toFixed(0)}K`
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(1)}K`
  return `${s}$${a.toFixed(0)}`
}

export function px(n: number | null | undefined): string {
  return n == null || !Number.isFinite(n) ? '—' : `$${n.toFixed(2)}`
}

export function pct(n: number | null | undefined, digits = 1, signed = false): string {
  if (n == null || !Number.isFinite(n)) return '—'
  return `${signed && n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(digits)}%`
}

/** Driver meter: each driver's share of the score, in the order given; the rest of the bar is empty. */
export function meterParts(drivers: Driver[] | undefined, max = 100): { name: string; width: number }[] {
  return (drivers ?? []).filter(d => (d.points ?? 0) > 0).map(d => ({ name: d.name, width: Math.max(0, Math.min(100, ((d.points ?? 0) / max) * 100)) }))
}

/** What the stop action asks for, in plain words. */
export function actionVerb(a: Pick<StopAction, 'answer'>): string {
  switch (String(a.answer).toUpperCase()) {
    case 'RAISE': return 'Raise stop'
    case 'ADD_STOP': return 'Add stop'
    case 'LOWER': return 'Lower stop'
    case 'TIGHTEN': return 'Tighten stop'
    default: return String(a.answer)
  }
}

/** A hedge trigger's bar fill (0..1), from the server's fill or value/act; null when neither is known. */
export function triggerFill(t: HedgeTrigger): number | null {
  if (t.fill != null && Number.isFinite(t.fill)) return Math.max(0, Math.min(1, t.fill))
  if (t.act && Number.isFinite(t.value)) return Math.max(0, Math.min(1, t.value / t.act))
  return null
}

/** Account keys from the stop feed ("schwab_rollover_ira") read as labels ("Schwab Rollover IRA"). */
export function accountText(a: string | undefined): string {
  if (!a) return ''
  return a.split(/[_\s]+/).filter(Boolean).map(w => (/^(ira|hsa|roth)$/i.test(w) ? (w.toLowerCase() === 'roth' ? 'Roth' : w.toUpperCase()) : w === 'moomoo' ? w : w[0].toUpperCase() + w.slice(1))).join(' ')
}

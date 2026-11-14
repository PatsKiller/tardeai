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
  book?: Prov & BookAccounts & { positions?: number; cash?: number }
  reentry?: Prov & { ready?: number; near?: number; tracked?: number; line?: string }
  drivers?: Driver[]; score_sum?: Fact<number>
  calm?: Prov & { n: number; of: number; names?: string[]; details?: string[] }
  gaps?: (Prov & { name: string; detail?: string })[]
  sectors?: SectorsFact
  shock?: Fact<string>
  catalyst?: Prov & { event: string; date: string; time_et?: string; label?: string }
  /** Present when `catalyst` is absent: why there is no event to show (UNKNOWN = could not read, NONE = read and none qualified). */
  catalyst_state?: { state: 'UNKNOWN' | 'NONE'; reason: string; as_of?: string | null }
  this_week?: WeekEvent[]
  do_now?: StopAction
  actions?: StopAction[]
}

/** LQ-20261113-3076 (A07): the book's account counts, each under its own name (scripts/lib/portfolio_total_contract
 *  account_population: ACCOUNTS_DEFINITION, the rule behind the Home contract's by_account `in_book` flag; the Home
 *  table also lists closed and unnamed entries, flagged not in the book). `accounts` is every account in the book,
 *  cash-only ones included; `accounts_with_positions` is the narrower count. A card without `accounts_definition`
 *  was built before the shared definition: its `accounts` meant "with positions" and the all-accounts count is unknown. */
export interface BookAccounts {
  accounts?: number | null; accounts_with_positions?: number | null; cash_only_accounts?: string[] | null
  accounts_unnamed_rows?: number | null; accounts_definition?: string | null
}

/** The Book row's account phrase. Never prints the narrower count as plain "accounts". */
export function bookAccountsText(book: BookAccounts | null | undefined): { text: string | null; title: string | null } {
  if (!book) return { text: null, title: null }
  const legacy = !book.accounts_definition
  const all = legacy ? null : (typeof book.accounts === 'number' ? book.accounts : null)
  const withPos = legacy ? (typeof book.accounts === 'number' ? book.accounts : (book.accounts_with_positions ?? null)) : (book.accounts_with_positions ?? null)
  const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`
  let text: string | null
  if (all != null && withPos != null) text = all === withPos ? plural(all, 'account') : `${plural(all, 'account')} (${withPos} with positions)`
  else if (all != null) text = plural(all, 'account')
  else if (withPos != null) text = `${plural(withPos, 'account')} with positions (all-accounts count unknown)`
  else text = null
  const unnamed = book.accounts_unnamed_rows ?? 0
  if (text && unnamed > 0) text += ` · ${plural(unnamed, 'row')} with no account`
  const cashOnly = book.cash_only_accounts?.length ? `Cash only: ${book.cash_only_accounts.map(a => accountText(a)).join(', ')}` : null
  const title = [book.accounts_definition ?? 'accounts holding a non-cash position (card built before the shared account definition)', cashOnly]
    .filter(Boolean).join('\n')
  return { text, title: text ? title : null }
}

export interface HedgeTrigger extends Prov { key: string; label: string; value: number; consider?: number; act?: number; fill?: number }
/** Whole-share sizing for one tranche (LQ-20261107-1654): floor(usd / live price), and the cash it leaves. */
export interface TrancheRow { tranche: number; usd: number; shares?: number | null; leftover_usd?: number | null }
/** LQ-20261107-1655: one individual stock under a defensive ETF row. `close` and `rs20` are facts (a value the
 *  server could not trace is absent); `held` means the book already owns the name in this sector, and those rows
 *  come first. `compare` is the server's one-line stock-vs-ETF reading — descriptive, never an instruction. */
export interface RotateStock extends Prov {
  symbol: string; held?: boolean; close: Fact<number>; rs20?: Fact<number>; held_value_usd?: Fact<number>
  tranche1_usd?: number; tranche1_shares?: number; proposed?: true; compare?: string
  /** LQ-20261107-1784: a plain reason a HELD name fails a floor ("below $5.00 — review", "no reliable price —
   *  review"). The holding is still listed; the flag replaces a rank it cannot honestly carry. */
  flag?: string
}
export interface RotateCandidate extends Prov {
  key: string; symbol: string; label: string; state?: string; leadership?: string; rs20?: number; dd20?: number; qualifies?: boolean
  close?: Fact<number>; avg20?: Fact<number>
  /** The CURRENT quote the share counts rest on (Finviz ≤30 min, else a fresh broker row). Absent = no share count. */
  price?: Fact<number>
  proposed?: {
    target_pct?: number; target_usd?: number; tranche1_usd?: number | null; shares?: number | null
    tranches?: TrancheRow[]; priced?: boolean; proposed: true
  }
  /** What the book already holds (LQ-20261107-1689). `filled` = at least 90% of the planned tranche-1 shares, so
   *  tranche 1 is a FILL, not an offer. Absent when the group offers no tranche, or the holding cannot be dated. */
  held?: Prov & { shares?: number; avg_cost?: number; pct_of_tranche1?: number; filled?: boolean }
  /** The individual names under this ETF (LQ-20261107-1655), or why none could be drawn. */
  stocks?: RotateStock[]; stocks_gap?: string
  /** LQ-20261107-1784: what the floors dropped, counted, and the price floor the list was drawn under. */
  stocks_note?: string; stocks_min_price?: number | null
  /** The next step after a held tranche (LQ-20261107-1784): tranche 2's size at the CURRENT price and the event
   *  it waits on. Present only when the book already holds the group, so a gated column never sizes tranche 1. */
  next_tranche?: { tranche: number; usd: number; shares?: number | null; after?: string | null }
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
    plan?: { proposed: true; tranche1_usd?: number; tranche1_pct_book?: number; cash_after_pct?: number; tranche2_after?: string; tranche3_when?: string; split?: number[]; rule?: string
             /** LQ-20261107-1689: every offering group's tranche 1 is already in the book. cash_after_pct then excludes
              *  a fill it would otherwise deduct twice. */
             tranche1_filled?: boolean }
    /** The quote time every share count rests on (oldest quote in the batch). Absent = no current price at all. */
    prices_as_of?: string
    prices_sources?: string[]
    /** Qualifying symbols that had no current quote, so the card shows no share count for them. */
    prices_missing?: string[]
    /** LQ-20261107-1784: the CIO's buys line itself (all gates), so the column can state TODAY from the verdict
     *  the operator is being shown — already time-aware at the gate owner. */
    buys?: { gate?: Fact<string>; until?: Fact<string>; until_short?: Fact<string>; line?: Fact<string> } | null
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

/** Dollars with the cents kept: a tranche's leftover cash IS the remainder, so rounding it to $96 hides the point. */
export function usdCents(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—'
  return `${n < 0 ? '−' : ''}$${Math.abs(n).toFixed(2)}`
}

/** The share side of a tranche row (LQ-20261107-1654): floor-share count and the cash it leaves, or an honest
 *  "needs a live price" — the card never prints a count priced off yesterday's close. */
export function trancheShares(t: TrancheRow): string {
  if (t.shares == null) return 'needs a live price'
  return t.leftover_usd == null ? `${t.shares} sh` : `${t.shares} sh + ${usdCents(t.leftover_usd)} cash`
}

export function pct(n: number | null | undefined, digits = 1, signed = false): string {
  if (n == null || !Number.isFinite(n)) return '—'
  return `${signed && n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(digits)}%`
}

/** Driver meter: each driver's share of the score, in the order given; the rest of the bar is empty.
 *  LQ-20261107-1642: each part carries the category's own STATE and the tone it is drawn in, so the segment's
 *  colour explains the reading. Before this the colour was the segment's position in the list
 *  (`cioCard.css` `nth-child(odd)=red / nth-child(even)=amber`), so a RED badge could sit beside an amber bar. */
export function meterParts(drivers: Driver[] | undefined, max = 100): { name: string; state: string; points: number; width: number; tone: Tone }[] {
  // A driver without a number is NOT a zero-point segment: it is absent from the meter entirely. Nothing is
  // drawn for it and no 0 is implied (a missing number is "not reported", never 0).
  return (drivers ?? []).flatMap(d => {
    const pts = d.points
    if (pts == null || !Number.isFinite(pts) || pts <= 0) return []
    return [{
      name: d.name,
      state: String(d.state ?? '').toUpperCase() || 'UNKNOWN',
      points: pts,
      width: Math.max(0, Math.min(100, (pts / max) * 100)),
      tone: driverTone(d.state),
    }]
  })
}

/** A market-risk category state → the tone its segment is drawn in. The vocabulary is the engine's own
 *  (`scripts/lib/market_risk/contract.py` STATES: CALM, IMPROVING, WARN, STRESS, UNKNOWN): STRESS is the danger
 *  colour, WARN the warning colour, IMPROVING the info colour, CALM success. An absent or unrecognised state is
 *  NEUTRAL — never a stress colour for a reading that was not measured. */
export function driverTone(state: string | null | undefined): Tone {
  switch (String(state ?? '').toUpperCase()) {
    case 'STRESS': return 'danger'
    case 'WARN': return 'warning'
    case 'IMPROVING': return 'info'
    case 'CALM': return 'success'
    default: return 'neutral'
  }
}

/** The score at which each market tier starts (config/market_risk_policy.yaml `tiers`: blue 25, yellow 40,
 *  orange 60, red 75; green is the max_score 20 band below blue). Drawn as ticks on the 0-100 meter so the
 *  tier label above it can be read off the scale instead of guessed. */
export const TIER_CUTOFFS = [
  { tier: 'BLUE', score: 25 },
  { tier: 'YELLOW', score: 40 },
  { tier: 'ORANGE', score: 60 },
  { tier: 'RED', score: 75 },
] as const

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

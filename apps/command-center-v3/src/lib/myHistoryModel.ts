/** Prospectus "My history" + fund profile blocks — types and pure display helpers.
 *  Backend: scripts/lib/prospectus/my_history.py (block `my_history`, MyHistory@v1) and etf_profile.py (`fund_profile`).
 *  Every field is optional: an absent block or field renders "not available", never a guess. */

type Num = number | null | undefined

export type HistoryEvent = {
  date?: string | null; kind?: 'catalyst' | 'earnings' | 'big_move' | 'stop_fill' | string; type?: string | null
  headline?: string | null; move_pct?: Num; next_day_pct?: Num; five_day_pct?: Num; fact?: string | null
}
export type OpenLot = {
  account?: string; shares?: Num; avg_cost?: Num; market_value?: Num; unrealized_usd?: Num; unrealized_pct?: Num
  acquired_first?: string | null; holding_days?: Num; term?: string | null; tax_character?: string | null
  lot_dating?: string | null; lot_dating_note?: string | null; fact_ids?: string[]
}
export type RoundTrip = {
  trip: number; account?: string; entry_date?: string | null; entry_price?: Num; exit_date?: string | null; exit_price?: Num
  shares?: Num; hold_days?: Num; realized_usd?: Num; realized_pct?: Num; r_multiple?: Num; origin?: string | null
  sources_before_entry?: string[]; thesis_at_entry?: string | null; setup?: string | null; journaled?: boolean
  journal?: { realized_r?: Num; lesson?: string | null; setup_family?: string | null; exit_type?: string | null } | null
  stopped_out?: boolean; term?: string | null; tax_character?: string | null; entry_vs_52w_range_pct?: Num
  wash_sale?: { flag?: boolean; window?: string[]; replacements?: { account?: string; date?: string; shares?: Num; when?: string }[]; evidence?: string } | null
  while_held?: HistoryEvent[]; fact_ids?: string[]
}
export type LessonStat = { id: string; label: string; value?: Num; unit?: string; n?: Num; note?: string; fact?: string | null }
export type MyHistory = {
  scope?: 'held' | 'previously_traded' | 'never_traded' | 'unavailable' | string
  open_lots?: OpenLot[]; trips?: RoundTrip[]
  current_hold?: { since?: string | null; days?: Num; while_held?: HistoryEvent[] } | null
  totals?: {
    trips?: Num; wins?: Num; losses?: Num; win_rate_pct?: Num; realized_usd?: Num; avg_win_usd?: Num; avg_loss_usd?: Num
    avg_win_pct?: Num; avg_loss_pct?: Num; avg_hold_days?: Num
    best?: { trip?: Num; realized_usd?: Num; realized_pct?: Num }; worst?: { trip?: Num; realized_usd?: Num; realized_pct?: Num }
  } | null
  lessons?: { stats?: LessonStat[]; journal_notes?: { trip: number; lesson: string }[] }
  tax?: { flags?: { trip?: number; kind?: string; sale_date?: string; replacement_dates?: string[] }[]; accounts?: { account: string; character: string }[]
    open_window?: { kind?: string; gated?: boolean; until?: string | null; label?: string | null } | null; note?: string | null }
  origin?: { first_origin?: string | null; sources?: string[] } | null
  writer_note?: { summary?: string | null; lessons?: string | null } | null
  gaps?: string[]
}
export type FundProfile = {
  category?: string | null; category_basis?: string | null; sector?: string | null; sector_etf?: string | null; peers?: string[]
  expense_ratio_pct?: Num; aum_usd?: Num; dividend_yield_pct?: Num; ttm_distribution?: Num; last_distribution?: Num
  last_distribution_date?: string | null; distribution_cadence?: string | null; next_distribution_est?: string | null
  top_holdings?: { name: string; weight_pct?: Num }[]; top10_weight_pct?: Num; dividend_history?: { ex_date: string; amount?: Num }[]
  analyst_look_through_pct?: Num; analyst_basis?: string | null; gaps?: string[]
}

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

export function myHistoryOf(blocks: unknown): MyHistory | null {
  const b = blocks && typeof blocks === 'object' ? (blocks as Record<string, unknown>).my_history : null
  return b && typeof b === 'object' ? (b as MyHistory) : null
}
export function fundProfileOf(blocks: unknown): FundProfile | null {
  const b = blocks && typeof blocks === 'object' ? (blocks as Record<string, unknown>).fund_profile : null
  return b && typeof b === 'object' ? (b as FundProfile) : null
}

export function money(v: Num, signed = false): string {
  if (!isNum(v)) return '—'
  const s = `$${Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  if (!signed) return v < 0 ? `−${s}` : s
  return `${v >= 0 ? '+' : '−'}${s}`
}
export function pctText(v: Num, signed = true, digits = 1): string {
  if (!isNum(v)) return '—'
  return `${signed && v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(digits)}%`
}
export function numText(v: Num, digits = 2): string {
  if (!isNum(v)) return '—'
  return Number.isInteger(v) ? v.toLocaleString('en-US') : v.toLocaleString('en-US', { maximumFractionDigits: digits })
}
export const tone = (v: Num): 'success' | 'danger' | 'neutral' => (!isNum(v) || v === 0 ? 'neutral' : v > 0 ? 'success' : 'danger')

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
/** "2026-03-02" → "Mar 2, 2026" (dates only; no clock time for these rows). */
export function dayText(d?: string | null): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(d ?? ''))
  if (!m) return '—'
  return `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}`
}
export const daysText = (v: Num) => (isNum(v) ? `${Math.round(v)}d` : '—')

const ORIGIN_LABEL: Record<string, string> = {
  watchlist: 'Watch list', directive: 'Your directive', proposal: 'Proposal', scan: 'Screener', screener: 'Screener',
  hermes_research: 'Research', research: 'Research', cio: 'CIO', cio_decision: 'CIO', claude_challenger: 'Challenger review',
}
export const originLabel = (s?: string | null) => (s ? ORIGIN_LABEL[s] ?? s.replace(/_/g, ' ') : 'Direct / manual')

export function whyText(t: RoundTrip): string {
  const src = (t.sources_before_entry ?? []).map(originLabel)
  return src.length ? src.join(' → ') : originLabel(t.origin)
}

export function eventLabel(e: HistoryEvent): string {
  if (e.kind === 'big_move') return `Big day move ${pctText(e.move_pct)}`
  if (e.kind === 'stop_fill') return e.headline || 'Stop filled'
  return e.headline || (e.type ?? 'Event').replace(/_/g, ' ')
}
export function reactionText(e: HistoryEvent): string {
  const a = e.kind === 'big_move' ? 'next session' : 'day-of'
  return `${a} ${pctText(e.next_day_pct)} · 5-session ${pctText(e.five_day_pct)}`
}
export const eventTone = (e: HistoryEvent) => (e.kind === 'stop_fill' ? 'danger' : e.kind === 'earnings' ? 'info' : e.kind === 'big_move' ? 'warning' : 'neutral')

export function lessonValue(s: LessonStat): string {
  if (s.unit === '%') return pctText(s.value, false)
  return numText(s.value)
}

/** Headline numbers for the KPI strip; each entry is omitted when the backend did not supply it. */
export function headline(mh: MyHistory): { k: string; v: string; sub?: string; tone?: string; id: string }[] {
  const out: { k: string; v: string; sub?: string; tone?: string; id: string }[] = []
  const lots = mh.open_lots ?? []
  const shares = lots.reduce((a, l) => a + (isNum(l.shares) ? l.shares : 0), 0)
  const cost = lots.reduce((a, l) => a + (isNum(l.shares) && isNum(l.avg_cost) ? l.shares * l.avg_cost : 0), 0)
  if (lots.length && shares > 0 && cost > 0) {
    out.push({ id: 'avg-cost', k: 'Average cost', v: money(cost / shares), sub: `${numText(shares)} shares · ${lots.length} account${lots.length > 1 ? 's' : ''}` })
  }
  const upl = lots.filter(l => isNum(l.unrealized_usd))
  if (upl.length) {
    const u = upl.reduce((a, l) => a + (l.unrealized_usd as number), 0)
    out.push({ id: 'open-pl', k: 'Open P/L', v: money(u, true), sub: cost > 0 ? pctText((u / cost) * 100) : undefined, tone: tone(u) })
  }
  const t = mh.totals
  if (t) {
    out.push({ id: 'realized', k: 'Lifetime realized', v: money(t.realized_usd, true), sub: `${numText(t.trips)} round trips`, tone: tone(t.realized_usd) })
    out.push({ id: 'winloss', k: 'Won / lost', v: `${numText(t.wins)} / ${numText(t.losses)}`, sub: isNum(t.win_rate_pct) ? `${t.win_rate_pct.toFixed(0)}% win rate` : undefined })
    out.push({ id: 'avg', k: 'Avg win · avg loss', v: `${money(t.avg_win_usd, true)} · ${money(t.avg_loss_usd, true)}`,
      sub: `${pctText(t.avg_win_pct)} · ${pctText(t.avg_loss_pct)}` })
    if (t.best && t.worst) {
      out.push({ id: 'best', k: 'Best · worst trip', v: `${money(t.best.realized_usd, true)} · ${money(t.worst.realized_usd, true)}`,
        sub: `trip ${numText(t.best.trip)} · trip ${numText(t.worst.trip)}` })
    }
  }
  return out
}

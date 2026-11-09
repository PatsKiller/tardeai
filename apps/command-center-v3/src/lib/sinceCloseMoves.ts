/** LQ-20261107-1282 — the "what has moved since the close" view model for the Home card.
 *
 *  Two values per name, not one: what it did in the last regular session (the Friday close) and what it has
 *  printed since — overnight, pre-market, after-hours, or a Sunday futures open. The producer decides which prints
 *  count and whether their reference is THIS close; this file decides only what is drawn, and it never upgrades a
 *  level to a percentage or invents a session label for a print that has none.
 *
 *  Pure: the wire in, what to draw out. Ordering is the producer's (held by |$ moved in the newest print|); the sort
 *  here is a defensive repeat of that contract so a stored snapshot from before LQ-1282 still draws in a stable order.
 */
import type { SinceCloseMove, SinceCloseWire } from './sinceClose.ts'
import { pctText, usdText } from './sinceClose.ts'

export type Arrow = '▲' | '▼' | '–'

/** up / down / flat, from the number the chip shows. NaN and null are flat, never a colour. */
export function arrowFor(pct: number | null | undefined): Arrow {
  if (pct == null || !Number.isFinite(pct) || pct === 0) return '–'
  return pct > 0 ? '▲' : '▼'
}

export interface ExtPrint {
  state: 'print' | 'level_only'
  label: string             // "overnight" / "pre-market" / "after-hours" / "futures open"
  pct: number | null        // null for a level-only print: no percentage is invented
  pctText: string
  arrow: Arrow
  printText: string         // "Sun 6:45 PM ET"
  priceText: string         // "$10.40"
  basisText: string         // "vs Fri close" or "level only (reference Nov 6)"
}

export interface MoveChip {
  symbol: string
  held: boolean
  closePct: number
  closeText: string
  closeArrow: Arrow
  dollars: number | null
  dollarsText: string
  ext: ExtPrint | null
  note: string | null       // "no print since Fri" — the honest answer, grey
  sortDollars: number
}

export interface MarketLevel {
  symbol: string
  label: string
  levelText: string
  pct: number | null
  pctText: string
  arrow: Arrow
  printText: string
  levelOnly: boolean
}

/** An overseas cash index with no feed on this host: the label and when it opens, never a level. */
export interface OverseasRow { label: string; text: string }

export interface MovesModel {
  held: MoveChip[]
  watch: MoveChip[]
  levels: MarketLevel[]       // futures + cash indices, producer order
  levelsStatus: 'available' | 'pending'
  asOfText: string | null
  overseasText: string | null
  overseas: OverseasRow[]
  pendingText: string
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

function priceText(p: number | null): string {
  if (p == null) return '—'
  return `$${p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function extOf(m: SinceCloseMove, closeTag: string): ExtPrint | null {
  const e = m.extended
  if (!e) return null
  const label = e.session_label || e.session || 'extended'
  const pct = e.state === 'print' ? num(e.change_pct) : null
  return {
    state: e.state === 'print' && pct != null ? 'print' : 'level_only',
    label,
    pct,
    pctText: pct == null ? '' : pctText(pct),
    arrow: arrowFor(pct),
    printText: e.printed_text || '',
    priceText: priceText(num(e.price)),
    basisText: pct != null ? `vs ${closeTag}` : `level only${e.reference_date ? ` (reference ${e.reference_date})` : ''}`,
  }
}

function chip(m: SinceCloseMove, closeTag: string, fridayLabel: string): MoveChip {
  const dollars = num(m.dollar_impact_now) ?? num(m.dollar_impact)
  return {
    symbol: m.symbol,
    held: m.held,
    closePct: m.change_pct,
    closeText: pctText(m.change_pct),
    closeArrow: arrowFor(m.change_pct),
    dollars,
    dollarsText: dollars == null ? '—' : usdText(dollars),
    ext: extOf(m, closeTag),
    note: m.extended ? null : `no print since ${fridayLabel}`,
    sortDollars: Math.abs(dollars ?? 0),
  }
}

/** The wire names the close "Fri close"; the chip note says "no print since Fri". */
function fridayOf(closeTag: string): string {
  const m = /^([A-Za-z]{2,3})\b/.exec(closeTag || '')
  return m ? m[1] : 'the close'
}

export function movesModel(w: SinceCloseWire | null | undefined): MovesModel {
  const moves = w?.moves ?? []
  const closeTag = w?.window_now?.close_tag ?? w?.window?.close_tag ?? 'last close'
  const friday = fridayOf(closeTag)
  const held = moves.filter(m => m.held).map(m => chip(m, closeTag, friday))
    .sort((a, b) => b.sortDollars - a.sortDollars)
  const watch = moves.filter(m => !m.held).map(m => chip(m, closeTag, friday))
    .sort((a, b) => Math.abs(b.ext?.pct ?? b.closePct) - Math.abs(a.ext?.pct ?? a.closePct))
  const now = w?.macro?.now
  const rows = now ? [...(now.futures ?? []), ...(now.indices ?? [])] : []
  const levels: MarketLevel[] = rows.map(r => ({
    symbol: r.symbol,
    label: r.label || r.symbol,
    levelText: priceText(num(r.level)),
    pct: num(r.change_pct),
    pctText: r.change_pct == null ? '' : pctText(num(r.change_pct)),
    arrow: arrowFor(num(r.change_pct)),
    printText: r.printed_text || '',
    levelOnly: r.level_only !== false || r.change_pct == null,
  }))
  return {
    held,
    watch,
    levels,
    levelsStatus: now?.status === 'available' || levels.length > 0 ? 'available' : 'pending',
    asOfText: now?.as_of_text || null,
    overseasText: now?.overseas?.label ?? null,
    overseas: (now?.overseas?.rows ?? []).map(r => ({
      label: r.label,
      // "opens Tue 7:00 PM ET" — the exchange's next open. A row with no open text is not drawn with a level.
      text: r.opens_text || 'no feed on this host',
    })),
    pendingText: 'futures feed pending — no print from the extended-hours lane yet',
  }
}

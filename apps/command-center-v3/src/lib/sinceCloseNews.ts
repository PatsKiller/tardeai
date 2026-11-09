/** LQ-20261107-1283 (mockup v3) — the "What to read first" view model: one compact item per story, in the order the CIO
 *  ranks, with the ticker leading the card and a heat-map glow by urgency.
 *
 *  Everything the operator sees is decided by the producer: the rank, the reason, and the glow level (computed from the
 *  thresholds the snapshot stores in `feed_rule.urgency`). A snapshot built before LQ-1283 carries none of it, so the
 *  card falls back to the order it was sent, hides the badge and draws no glow rather than inventing a number.
 */
import type { SinceCloseFeedItem, SinceCloseWire } from './sinceClose.ts'
import { arrowFor, type Arrow } from './sinceCloseMoves.ts'

export type Glow = 'red' | 'amber' | 'green'

export interface NewsCard {
  key: string
  rank: number | null
  badgeText: string         // "#1"
  whyText: string           // the producer's one-line reason, e.g. "$8,524 moved · held SPCX +8.6%"
  glow: Glow | null
  glowText: string | null   // "urgent risk · held BBB -4.4% since the close"
  lead: string              // the ticker that leads the card ("SPCX"), or "Market" for a market-wide story
  leadPct: number | null
  leadText: string          // "+8.62%" / "—"
  leadArrow: Arrow
  basisText: string         // "vs Fri close"
  kind: 'holding' | 'watch' | 'macro'
  isWatch: boolean
  title: string
  url: string | null
  sourcesText: string       // every feed that carried it: "yahoo_rss · google_news:Reuters"
  timeText: string
  symbolsText: string       // kept for the meta line's aria/title: "SPCX ▲ +8.6%"
  dupText: string           // "+2 more on SPCX" when several feeds carried the same story, else ''
  soWhat: string
}

export interface NewsModel {
  items: NewsCard[]
  top: NewsCard[]
  hidden: number
  total: number
  ruleText: string | null   // the producer's glow rule, drawn as the legend's title when present
}

export const NEWS_TOP = 6

export const GLOW_LABEL: Record<Glow, string> = {
  red: 'urgent risk',
  amber: 'watch closely',
  green: 'big gain on a holding',
}

const timeOf = (iso?: string | null): string => {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', minute: '2-digit' }) + ' ET'
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/** Two decimals: the news card's percentage is the precise one the producer computed, not a rounded headline. */
export const pct2 = (n: number | null | undefined): string =>
  n == null || !Number.isFinite(n) ? '—' : `${n > 0 ? '+' : ''}${n.toFixed(2)}%`

/** The number the card leads with, and what it is a move FROM. A newer print since the close is "vs Fri close"; with
 *  no print the only honest number is the close's own move, and then the basis is just the close tag. */
function moveOf(it: SinceCloseFeedItem): { pct: number | null; symbol: string | null; sinceClose: boolean } {
  const h = (it.holdings ?? [])[0]
  if (!h) return { pct: null, symbol: null, sinceClose: false }
  const now = num(h.move_now_pct)
  return now != null
    ? { pct: now, symbol: h.symbol, sinceClose: true }
    : { pct: num(h.change_pct), symbol: h.symbol, sinceClose: false }
}

export function newsCard(it: SinceCloseFeedItem, i: number, closeTag: string): NewsCard {
  const { pct, symbol, sinceClose } = moveOf(it)
  const sources = (it.sources && it.sources.length ? it.sources : [it.source]).filter(Boolean)
  const rank = typeof it.rank === 'number' ? it.rank : null
  const glow = it.urgency === 'red' || it.urgency === 'amber' || it.urgency === 'green' ? it.urgency : null
  const lead = symbol ?? 'Market'
  const dup = sources.length - 1
  return {
    key: `${it.title}|${i}`,
    rank,
    badgeText: rank == null ? '' : `#${rank}`,
    whyText: it.why ?? '',
    glow,
    glowText: glow ? `${GLOW_LABEL[glow]}${it.urgency_why ? ` · ${it.urgency_why}` : ''}` : null,
    lead,
    leadPct: pct,
    leadText: pct2(pct),
    leadArrow: arrowFor(pct),
    basisText: sinceClose ? `vs ${closeTag}` : closeTag,
    kind: it.kind,
    isWatch: it.kind === 'watch',
    title: it.title,
    url: it.url ?? null,
    sourcesText: sources.join(' · '),
    timeText: timeOf(it.published_at),
    symbolsText: symbol ? `${symbol} ${pct == null ? closeTag : `${arrowFor(pct)} ${pct2(pct)}`}` : '',
    dupText: dup > 0 ? `+${dup} more on ${lead}` : '',
    soWhat: it.so_what,
  }
}

export function newsModel(w: SinceCloseWire | null | undefined, top: number = NEWS_TOP): NewsModel {
  const closeTag = w?.window_now?.close_tag ?? w?.window?.close_tag ?? 'last close'
  const raw = w?.feed ?? []
  // the producer ranks; a snapshot without ranks keeps its own order (and shows no badge)
  const ordered = raw.map((it, i) => ({ it, i })).sort((a, b) => (a.it.rank ?? a.i) - (b.it.rank ?? b.i)).map(x => x.it)
  const items = ordered.map((it, i) => newsCard(it, i, closeTag))
  return {
    items,
    top: items.slice(0, top),
    hidden: Math.max(0, items.length - top),
    total: items.length,
    ruleText: w?.feed_rule?.urgency?.red ?? null,
  }
}

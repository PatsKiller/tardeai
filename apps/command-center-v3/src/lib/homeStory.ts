/** LQ-20261107-1314 — the internal story view behind a Home news/feed card.
 *
 *  The operator tapped a card ("SPCX ▲ +8.62%") and the headline anchor took the whole page to the publisher's
 *  site. A feed card is a claim about a symbol the book holds, so the tap must land on the internal view first:
 *  what the CIO's latest brief says about that symbol, and what the story itself says, with the publisher one
 *  deliberate click away at the bottom ("Read source ↗") instead of being the tap target.
 *
 *  This module is only the model — no React, no fetch. `SinceCloseNews` builds one card per story and hands the
 *  card's own fields here; `MajorNewsGrid` hands one guarded headline. Everything drawn comes from the producer;
 *  a story the CIO's brief does not mention says so rather than borrowing another symbol's line.
 */
import type { NewsCard } from './sinceCloseNews.ts'
import { cioFrom } from './sinceClose.ts'
import type { SinceCloseWire } from './sinceClose.ts'

export type CioModel = ReturnType<typeof cioFrom>

export interface StoryCio {
  /** The brief is not available at all (not built, or the read is still pending). */
  pending: boolean
  /** The brief's own pending/ready label, drawn when `pending`. */
  label: string
  /** The brief's risk tier, when it has one. */
  tier: string | null
  /** The brief's overall summary line, when it has one. */
  summary: string | null
  /** This symbol's line in the brief ("HOLD — trim into strength"), or null when the brief has no line for it. */
  action: string | null
}

export interface HomeStory {
  key: string
  /** The symbol the story is about; null for a market-wide story (nothing pretends to be a ticker). */
  sym: string | null
  macro: boolean
  title: string
  /** The producer's one-line "why it matters"; empty when it sent none — never fabricated. */
  summary: string
  /** The producer's one-line reason the card ranks where it does; empty when absent. */
  whyText: string
  sourcesText: string
  timeText: string
  url: string | null
  sourceDomain: string | null
  movePct: number | null
  moveText: string
  basisText: string
  cio: StoryCio
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

const pct2 = (n: number | null): string => (n == null ? '—' : `${n > 0 ? '+' : ''}${n.toFixed(2)}%`)

/** The publisher, for the source badge. A URL that will not parse has no domain — that is not "source unknown". */
export function sourceDomain(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    const host = new URL(url).hostname.replace(/^www\./, '')
    return host || null
  } catch {
    return null
  }
}

/** "3h ago" — the headline feed's own relative clock (the same wording the Major News row shows). */
export function relTime(iso: string | null | undefined, nowMs: number = Date.now()): string {
  if (!iso) return ''
  const ms = nowMs - new Date(iso).getTime()
  if (!Number.isFinite(ms)) return ''
  const h = ms / 3.6e6
  if (h < 1) return `${Math.max(1, Math.round(h * 60))}m ago`
  if (h < 24) return `${Math.round(h)}h ago`
  return `${Math.round(h / 24)}d ago`
}

/** The CIO's line for one symbol, matched case-insensitively. No line is not the same as no brief. */
export function cioFor(cio: CioModel | null | undefined, sym: string | null): StoryCio {
  if (!cio || cio.pending) {
    return { pending: true, label: cio?.label ?? 'CIO brief not loaded', tier: null, summary: null, action: null }
  }
  if (!sym) return { pending: false, label: 'CIO brief', tier: cio.tier, summary: cio.summary, action: null }
  const want = sym.toUpperCase()
  const hit = cio.actions.find(a => a.symbol.toUpperCase() === want)
  return { pending: false, label: 'CIO brief', tier: cio.tier, summary: cio.summary, action: hit?.text ?? null }
}

/** A ranked feed card (SinceCloseNews) as the internal story view. */
export function storyFromCard(c: NewsCard, w: SinceCloseWire | null | undefined): HomeStory {
  const macro = c.kind === 'macro' || c.lead === 'Market'
  const sym = macro ? null : c.lead
  const cio = cioFor(w ? cioFrom(w.cio_brief) : null, sym)
  return {
    key: c.key,
    sym,
    macro,
    title: c.title,
    summary: c.soWhat || '',
    whyText: c.whyText || '',
    sourcesText: c.sourcesText,
    timeText: c.timeText,
    url: c.url,
    sourceDomain: sourceDomain(c.url),
    movePct: c.leadPct,
    moveText: c.leadPct == null ? '—' : `${c.leadArrow} ${pct2(c.leadPct)}`,
    basisText: c.basisText,
    cio,
  }
}

/** One guarded headline from the Major News grid (the API carries no body summary — none is invented). */
export function storyFromHeadline(
  sym: string,
  h: { title?: string | null; source?: string | null; url?: string | null; published_at?: string | null },
  opts: { cio?: CioModel | null; movePct?: number | null; basisText?: string | null } = {},
): HomeStory {
  const title = (h.title ?? '').trim()
  const url = h.url ?? null
  const pct = num(opts.movePct)
  return {
    key: `${sym}|${title}`,
    sym,
    macro: false,
    title: title || `${sym} headline`,
    summary: '',
    whyText: '',
    sourcesText: [sourceDomain(url), h.source].filter(Boolean).join(' · '),
    timeText: relTime(h.published_at),
    url,
    sourceDomain: sourceDomain(url),
    movePct: pct,
    moveText: pct == null ? '—' : pct2(pct),
    basisText: opts.basisText ?? 'today',
    cio: cioFor(opts.cio ?? null, sym),
  }
}

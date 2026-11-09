/** LQ-20261107-1283 (mockup v3) — "What to read first": the same stories, in a multi-column grid instead of one tall
 *  column, each led by its ticker and its move, with a heat-map glow by urgency.
 *
 *  Card anatomy, top to bottom: ticker + arrow/% ("SPCX ▲ +8.62%", "vs Fri close"), rank badge on the right, the
 *  producer's one-line reason, the headline (two lines), one meta line (sources · time), and "+N more on SYM" when
 *  several feeds carried the same story. Six up front, the rest behind "Show all N".
 *
 *  The ORDER and the GLOW are the producer's (rank, urgency, and the rule stored in feed_rule.urgency); this file only
 *  paints them. Mobile first: minmax(320px, 1fr) is one column at 390-412 px and 2-3 at 768-1280.
 */
import { useState, type CSSProperties } from 'react'
import { RADIUS, TOKENS, TYPE, FONT, toneVars } from '../../lib/designTokens'
import { newsModel, GLOW_LABEL, type Glow, type NewsCard } from '../../lib/sinceCloseNews'
import { cioFrom, type SinceCloseWire } from '../../lib/sinceClose'
import { storyFromCard } from '../../lib/homeStory'
import HomeStorySheet from './HomeStorySheet'

const up = toneVars('success')
const dn = toneVars('danger')
const warn = toneVars('warning')
const info = toneVars('info')

const GLOW_TONE: Record<Glow, string> = { red: TOKENS.danger, amber: TOKENS.warning, green: TOKENS.success }
/** border + halo, the mockup's recipe; color-mix keeps it a token, not a hardcoded rgba. */
const glowStyle = (g: Glow): CSSProperties => ({
  borderColor: GLOW_TONE[g],
  boxShadow: `0 0 0 1px ${GLOW_TONE[g]}, 0 0 18px 2px color-mix(in srgb, ${GLOW_TONE[g]} 45%, transparent)`,
})

const S = {
  h3: { margin: 0, fontSize: TYPE.sm, fontWeight: 800, letterSpacing: '.05em', textTransform: 'uppercase',
    color: TOKENS.text[3] } as CSSProperties,
  grid: {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 10, alignItems: 'start',
  } as CSSProperties,
  card: { background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: '10px 12px',
    minWidth: 0, display: 'grid', gap: 5 } as CSSProperties,
  tickerRow: { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', minWidth: 0 } as CSSProperties,
  sym: { fontSize: 22, fontWeight: 800, letterSpacing: '.02em', lineHeight: 1.1, color: TOKENS.text[0] } as CSSProperties,
  pct: { fontSize: 16, fontWeight: 700, fontFamily: FONT.mono, fontVariantNumeric: 'tabular-nums' } as CSSProperties,
  basis: { fontSize: TYPE.base, color: TOKENS.text[3] } as CSSProperties,
  badge: { marginLeft: 'auto', background: TOKENS.primary, color: TOKENS.bg[0], borderRadius: RADIUS.sm, padding: '1px 7px',
    fontSize: 12, fontWeight: 700 } as CSSProperties,
  chipRow: { display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' } as CSSProperties,
  why: { fontSize: 12, color: info.color, background: info.bg, borderRadius: RADIUS.sm, padding: '1px 7px' } as CSSProperties,
  watch: { fontSize: TYPE.sm, color: warn.color, background: warn.bg, borderRadius: RADIUS.sm, padding: '1px 6px' } as CSSProperties,
  title: { color: TOKENS.text[0], textDecoration: 'none', fontWeight: 600, display: '-webkit-box', WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical', overflow: 'hidden', fontSize: 14, lineHeight: 1.35 } as CSSProperties,
  meta: { fontSize: 12, color: TOKENS.text[3], fontFamily: FONT.mono, overflowWrap: 'anywhere', display: 'flex',
    gap: 8, alignItems: 'baseline', flexWrap: 'wrap' } as CSSProperties,
  open: { marginLeft: 'auto', color: info.color, fontWeight: 700 } as CSSProperties,
  dup: { fontSize: 12, color: TOKENS.text[3], display: 'block' } as CSSProperties,
  legend: { display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 12, color: TOKENS.text[3] } as CSSProperties,
  dot: (c: string): CSSProperties => ({ display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
    marginRight: 5, verticalAlign: '-1px', background: c }),
  more: { minHeight: 44, alignSelf: 'flex-start', background: 'none', border: `1px solid ${TOKENS.border}`,
    borderRadius: RADIUS.sm, padding: '6px 10px', color: info.color, fontSize: 14, fontWeight: 600, cursor: 'pointer',
    fontFamily: 'inherit' } as CSSProperties,
}

const tone = (pct: number | null) => (pct == null || pct === 0 ? TOKENS.text[3] : pct > 0 ? up.color : dn.color)

export default function SinceCloseNews({ wire }: { wire: SinceCloseWire | null | undefined }) {
  const [all, setAll] = useState(false)
  // LQ-1314: a card tap opens the internal view; the publisher link lives inside it, not on the card.
  const [story, setStory] = useState<NewsCard | null>(null)
  const m = newsModel(wire)
  if (m.total === 0) {
    return <p style={{ ...S.meta, color: TOKENS.text[3] }} data-testid="since-close-feed-empty">No news on your names since the close.</p>
  }
  const shown = all ? m.items : m.top
  return (
    <div style={{ display: 'grid', gap: 8 }} data-testid="since-close-feed" data-layout="grid"
      data-shown={shown.length} data-total={m.total}>
      <h3 style={S.h3} data-testid="since-close-feed-title">
        What to read first{all ? ` · all ${m.total}` : ` · top ${shown.length} by relevance`}
      </h3>
      <div style={S.legend} data-testid="since-close-feed-legend" title={m.ruleText ?? undefined}>
        {(['red', 'amber', 'green'] as Glow[]).map(g => (
          <span key={g} data-testid={`sc-legend-${g}`}>
            <i style={S.dot(GLOW_TONE[g])} />{GLOW_LABEL[g]}
          </span>
        ))}
        <span>no glow: read when you have time</span>
      </div>
      <div style={S.grid}>
        {shown.map((c, i) => (
          <button key={c.key} type="button" onClick={() => setStory(c)}
            aria-label={`Open the internal view for ${c.lead}: ${c.title}`}
            style={{ ...S.card, ...(c.glow ? glowStyle(c.glow) : null), width: '100%', boxSizing: 'border-box',
              minHeight: 44, textAlign: 'left', font: 'inherit', color: 'inherit', cursor: 'pointer' }}
            data-testid={`sc-news-${c.rank ?? `x${i}`}`} data-kind={c.kind} data-glow={c.glow ?? 'none'}
            title={c.glowText ?? undefined}>
            <span style={S.tickerRow}>
              <span style={S.sym}>{c.lead}</span>
              <span style={{ ...S.pct, color: tone(c.leadPct) }} data-testid="sc-news-move" data-tone={c.leadPct == null || c.leadPct === 0 ? 'flat' : c.leadPct > 0 ? 'up' : 'down'}>
                {c.leadArrow} {c.leadText}
              </span>
              <span style={S.basis}>{c.basisText}</span>
              {c.badgeText && <span style={S.badge} data-testid="sc-news-rank">{c.badgeText}</span>}
            </span>
            {(c.whyText || c.isWatch) && (
              <span style={S.chipRow}>
                {c.whyText && <span style={S.why} data-testid="sc-news-why">{c.whyText}</span>}
                {c.isWatch && <span style={S.watch}>watchlist</span>}
              </span>
            )}
            <span style={S.title} data-testid="sc-news-title">{c.title}</span>
            <span style={S.meta}>
              <span>{[c.sourcesText, c.timeText].filter(Boolean).join(' · ')}</span>
              <span style={S.open} data-testid="sc-news-open">CIO + summary ›</span>
            </span>
            {c.dupText && <span style={S.dup} data-testid="sc-news-dup">{c.dupText}</span>}
          </button>
        ))}
      </div>
      {m.hidden > 0 && (
        <button type="button" style={S.more} onClick={() => setAll(v => !v)} data-testid="since-close-feed-more"
          aria-expanded={all}>
          {all ? `Show top ${m.top.length}` : `Show all ${m.total}`}
        </button>
      )}
      {story && <HomeStorySheet story={storyFromCard(story, wire)} cio={cioFrom(wire?.cio_brief)}
        onClose={() => setStory(null)} />}
    </div>
  )
}

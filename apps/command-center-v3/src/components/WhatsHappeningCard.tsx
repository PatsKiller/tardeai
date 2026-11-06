// The Home "What's happening" card (operator-approved 2026-11-04 14:43Z).
// Tokens only — every colour, radius, type size and space comes from designTokens / tokens.css. No literals.
import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { FONT, RADIUS, TOKENS, TYPE, toneVars } from '../lib/designTokens'
import { columns, counters, STATE_LABEL, STATE_TONE, topRows } from '../lib/whatsHappening'
import { cardFeed, type Census, type FeedRow } from '../lib/whatsHappeningFeed'

const card: CSSProperties = {
  background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg,
  padding: 16, display: 'grid', gap: 12, minWidth: 0,
}
const strip: CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(88px, 1fr))', gap: 8, minWidth: 0 }
const cell: CSSProperties = { display: 'grid', gap: 2, padding: '8px 10px', borderRadius: RADIUS.md, border: `1px solid ${TOKENS.borderSubtle}` }
const rowStyle: CSSProperties = { display: 'grid', gap: 4, padding: '10px 0', borderTop: `1px solid ${TOKENS.borderSubtle}`, minWidth: 0 }

export type WhatsHappeningCardProps = {
  /** the source verdict (inFlightCensus). REQUIRED: there is no bare-list entry point, because a list without a
   *  verdict is exactly how six zeros came to look like a measurement (F1). */
  census: Census
  feed?: FeedRow[] | null
  /** true at 390/412 px: the table DROPS eta / last-update / source rather than squashing them. */
  compact?: boolean
  seeEverythingHref?: string
}

export function WhatsHappeningCard({ census, feed, compact = false,
  seeEverythingHref = '/ops/whats-happening' }: WhatsHappeningCardProps): ReactNode {
  // UNKNOWN IS A FIRST-CLASS OUTCOME and the only fallback: no census, or a census that did not answer, or an
  // answered census with no row list — every one of those renders the reason, never an empty confident card.
  const resolved = cardFeed(census ?? { answered: false, reason: 'no source verdict was supplied' }, feed)
  if (resolved.kind === 'unknown') {
    return (
      <section data-testid="whats-happening" data-state="unknown" style={card}>
        <h2 style={{ margin: 0, fontSize: TYPE.lg, fontWeight: 800, color: TOKENS.text[0] }}>What&rsquo;s happening</h2>
        <p style={{ margin: 0, fontSize: TYPE.base, color: TOKENS.text[1] }}>
          Cannot tell what is happening — {resolved.reason}. That is not the same as nothing happening.
        </p>
        <Link to={seeEverythingHref} style={{ minHeight: 44, display: 'inline-flex', alignItems: 'center', color: TOKENS.primary, fontWeight: 700, fontSize: TYPE.sm }}>
          See everything →
        </Link>
      </section>
    )
  }
  const items = resolved.items
  const cells = counters(items)
  const rows = topRows(items)
  const cols = columns(compact)
  return (
    <section data-testid="whats-happening" data-compact={compact ? 'true' : 'false'} style={card}>
      <h2 style={{ margin: 0, fontSize: TYPE.lg, fontWeight: 800, color: TOKENS.text[0] }}>What&rsquo;s happening</h2>

      <div data-testid="whats-happening-strip" style={strip}>
        {cells.map(c => {
          const tone = toneVars(STATE_TONE[c.state])
          return (
            <div key={c.state} data-testid={`wh-cell-${c.state}`} style={{ ...cell, borderColor: tone.border }}>
              <span style={{ fontSize: TYPE.xl, fontWeight: 800, color: tone.color }}>{c.count}</span>
              <span style={{ fontSize: TYPE.xs, color: TOKENS.text[2] }}>{c.label}</span>
            </div>
          )
        })}
      </div>

      {resolved.unknown > 0 && (
        <p data-testid="wh-unknown-note" style={{ margin: 0, fontSize: TYPE.sm, color: TOKENS.text[1] }}>
          {resolved.unknown} row{resolved.unknown === 1 ? '' : 's'} recorded no state, so {resolved.unknown === 1 ? 'it is' : 'they are'} not counted above.
        </p>
      )}

      <div data-testid="whats-happening-rows">
        {rows.map(item => {
          const tone = toneVars(STATE_TONE[item.state])
          return (
            <div key={item.id} data-testid={`wh-row-${item.id}`} style={rowStyle}>
              <span style={{ fontSize: TYPE.base, fontWeight: 700, color: TOKENS.text[0], overflowWrap: 'anywhere' }}>{item.title}</span>
              <span style={{ fontSize: TYPE.xs, color: TOKENS.text[1], display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <span data-state={item.state} style={{ color: tone.color, fontWeight: 700 }}>{STATE_LABEL[item.state]}</span>
                {cols.includes('owner') && item.owner ? <span>{item.owner}</span> : null}
                {cols.includes('eta') && item.eta ? <span>ETA {item.eta}</span> : null}
                {cols.includes('updated_at') && item.updated_at ? <span style={{ fontFamily: FONT.mono }}>{item.updated_at}</span> : null}
                {cols.includes('source') && item.source ? <span>{item.source}</span> : null}
              </span>
            </div>
          )
        })}
      </div>

      <Link to={seeEverythingHref} data-testid="whats-happening-see-everything"
        style={{ minHeight: 44, display: 'inline-flex', alignItems: 'center', color: TOKENS.primary, fontWeight: 700, fontSize: TYPE.sm }}>
        See everything →
      </Link>
    </section>
  )
}

export default WhatsHappeningCard

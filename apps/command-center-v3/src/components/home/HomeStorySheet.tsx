/** LQ-20261107-1314 — the internal view a Home news/feed card opens.
 *
 *  Operator, 20:12 ET: tapping SPCX in "What to read first" went straight to the publisher and skipped the
 *  Command Center. A card on Home is a claim about one of the book's names, so the tap now opens this view:
 *  the CIO's latest line for that symbol, the story's own summary, and the internal pages for the symbol.
 *  The publisher link is still here, at the bottom, as "Read source ↗" — inside the summary, one deliberate
 *  click away, never the tap target.
 *
 *  Phone (<=820 px): the shared full-screen sheet (MobileDetailSheet — dialog semantics, focus trap, Escape,
 *  body scroll lock). Desktop: a centred dialog over a scrim with the same content. Both close on Escape and on
 *  a click outside; nothing is removed from the card behind them.
 *
 *  CIO data: SinceCloseNews already holds the since-close wire, so it passes `cio`. The Major News grid has no
 *  such wire, so when `cio` is omitted this view reads GET /api/v2/home/since-close once, on open, and says
 *  "CIO brief not loaded" rather than guessing when even that read fails.
 */
import { useEffect, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { useApi } from '../../hooks/useApi'
import { RADIUS, TOKENS, TYPE, FONT, toneVars } from '../../lib/designTokens'
import { SINCE_CLOSE_API, cioFrom, type SinceCloseWire } from '../../lib/sinceClose'
import { cioFor, type CioModel, type HomeStory } from '../../lib/homeStory'
import { MobileDetailSheet } from '../MobileDetailSheet'

const up = toneVars('success')
const dn = toneVars('danger')
const info = toneVars('info')

const S = {
  wrap: { display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 } as CSSProperties,
  head: { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', minWidth: 0 } as CSSProperties,
  sym: { fontSize: 22, fontWeight: 800, letterSpacing: '.02em', lineHeight: 1.1, color: TOKENS.text[0] } as CSSProperties,
  move: { fontSize: 16, fontWeight: 700, fontFamily: FONT.mono, fontVariantNumeric: 'tabular-nums' } as CSSProperties,
  basis: { fontSize: TYPE.base, color: TOKENS.text[3] } as CSSProperties,
  srcBadge: { fontSize: TYPE.xs, fontWeight: 700, color: TOKENS.text[2], border: `1px solid ${TOKENS.border}`,
    borderRadius: RADIUS.sm, padding: '0 6px' } as CSSProperties,
  block: { background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md,
    padding: '10px 12px', display: 'grid', gap: 6, minWidth: 0 } as CSSProperties,
  h3: { margin: 0, fontSize: TYPE.sm, fontWeight: 800, letterSpacing: '.05em', textTransform: 'uppercase',
    color: TOKENS.text[3] } as CSSProperties,
  p: { margin: 0, fontSize: TYPE.md, lineHeight: 1.5, color: TOKENS.text[1], overflowWrap: 'anywhere' } as CSSProperties,
  title: { margin: 0, fontSize: 16, fontWeight: 600, lineHeight: 1.35, color: TOKENS.text[0], overflowWrap: 'anywhere' } as CSSProperties,
  meta: { fontSize: TYPE.base, color: TOKENS.text[3], fontFamily: FONT.mono, overflowWrap: 'anywhere' } as CSSProperties,
  advisory: { fontSize: TYPE.xs, color: TOKENS.text[3] } as CSSProperties,
  why: { justifySelf: 'start', fontSize: TYPE.xs, color: info.color, background: info.bg, borderRadius: RADIUS.sm,
    padding: '1px 7px' } as CSSProperties,
  links: { display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' } as CSSProperties,
  link: { minHeight: 44, display: 'inline-flex', alignItems: 'center', color: info.color, fontSize: TYPE.md,
    fontWeight: 600, textDecoration: 'none' } as CSSProperties,
  linkSubtle: { minHeight: 44, display: 'inline-flex', alignItems: 'center', color: TOKENS.text[2], fontSize: TYPE.md,
    fontWeight: 600, textDecoration: 'none' } as CSSProperties,
  foot: { display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', paddingTop: 2 } as CSSProperties,
  source: { minHeight: 44, display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: TYPE.md, fontWeight: 700,
    color: TOKENS.text[0], background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md,
    padding: '0 12px', textDecoration: 'none' } as CSSProperties,
  close: { minHeight: 44, minWidth: 88, fontSize: TYPE.md, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
    color: TOKENS.text[1], background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md } as CSSProperties,
  overlay: { position: 'fixed', inset: 0, zIndex: 320, background: 'rgba(0,0,0,.6)', display: 'flex',
    alignItems: 'center', justifyContent: 'center', padding: 12 } as CSSProperties,
  panel: { width: 640, maxWidth: '100%', maxHeight: '88vh', overflowY: 'auto', boxSizing: 'border-box',
    background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg, padding: 16 } as CSSProperties,
  panelHd: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 } as CSSProperties,
  panelTitle: { margin: 0, fontSize: TYPE.md, fontWeight: 800, letterSpacing: '.05em', textTransform: 'uppercase',
    color: TOKENS.text[3] } as CSSProperties,
}

const tone = (pct: number | null) => (pct == null || pct === 0 ? TOKENS.text[3] : pct > 0 ? up.color : dn.color)

/** Escape + body-scroll lock for the desktop dialog. Both are handed back on unmount. */
function useDialogDismiss(onClose: () => void, active: boolean) {
  useEffect(() => {
    if (!active) return
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = overflow
      document.removeEventListener('keydown', onKey)
    }
  }, [onClose, active])
}

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia('(max-width: 820px)').matches)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 820px)')
    const on = () => setNarrow(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return narrow
}

/** The view itself. `cio` omitted means "read the since-close wire once" (Major News has no wire of its own). */
export function StoryView({ story, cio, onClose, inlineClose }: {
  story: HomeStory
  cio?: CioModel | null
  onClose: () => void
  inlineClose: boolean
}) {
  const need = cio === undefined
  const { data: wire } = useApi<SinceCloseWire>(need ? SINCE_CLOSE_API : '', 0, { enabled: need })
  // cioFrom reads the BRIEF, not the since-close wire that carries it.
  const c = cioFor(cio ?? (wire ? cioFrom(wire.cio_brief) : null), story.sym)
  const label = story.sym ? `${story.sym} story` : 'Market story'
  return (
    <div data-testid="home-story" data-sym={story.sym ?? 'market'} style={S.wrap} aria-label={label}>
      <div style={S.head}>
        <span data-testid="home-story-sym" style={S.sym}>{story.sym ?? 'Market'}</span>
        {story.sym && (
          <span data-testid="home-story-move" data-tone={story.movePct == null || story.movePct === 0 ? 'flat' : story.movePct > 0 ? 'up' : 'down'}
            style={{ ...S.move, color: tone(story.movePct) }}>{story.moveText}</span>
        )}
        {story.sym && <span style={S.basis}>{story.basisText}</span>}
        <span style={{ flex: 1 }} />
        {story.sourceDomain && <span style={S.srcBadge} data-testid="home-story-domain">{story.sourceDomain}</span>}
      </div>

      <section style={S.block} data-testid="home-story-cio">
        <h3 style={S.h3}>CIO latest{story.sym ? ` · ${story.sym}` : ''}{c.tier ? ` · ${c.tier}` : ''}</h3>
        {c.pending ? (
          <p style={S.p} data-testid="home-story-cio-pending">{c.label}</p>
        ) : (
          <>
            {c.action
              ? <p style={S.p} data-testid="home-story-cio-action"><b>{story.sym}</b> · {c.action} <span style={S.advisory}>advisory</span></p>
              : story.sym && <p style={{ ...S.p, color: TOKENS.text[3] }} data-testid="home-story-cio-none">The latest CIO brief carries no line for {story.sym}.</p>}
            {c.summary && <p style={{ ...S.p, fontSize: TYPE.base }}>{c.summary}</p>}
          </>
        )}
        {story.sym && (
          <div style={S.links}>
            {/* The router is mounted at basename="/v3", so these are app-relative — a "/v3/..." here reads /v3/v3/... */}
            <Link to={`/watch/intelligence/${story.sym}`} data-testid="home-story-open-intel" style={S.link}>
              Open {story.sym} intelligence →
            </Link>
            <Link to={`/portfolio?symbol=${story.sym}`} style={S.linkSubtle}>Security card</Link>
          </div>
        )}
      </section>

      <section style={S.block} data-testid="home-story-body">
        <h3 style={S.h3}>The story</h3>
        {story.whyText && <span style={S.why} data-testid="home-story-why">{story.whyText}</span>}
        <p style={S.title} data-testid="home-story-title">{story.title}</p>
        {story.summary && <p style={S.p} data-testid="home-story-summary">{story.summary}</p>}
        <div style={S.meta} data-testid="home-story-meta">{[story.sourcesText, story.timeText].filter(Boolean).join(' · ')}</div>
      </section>

      <div style={S.foot}>
        {story.url
          ? <a data-testid="home-story-source" href={story.url} target="_blank" rel="noopener noreferrer" style={S.source}>
              Read source ↗{story.sourceDomain ? ` (${story.sourceDomain})` : ''}
            </a>
          : <span style={{ ...S.meta, minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>No publisher link for this item.</span>}
        <span style={{ flex: 1 }} />
        {inlineClose && <button type="button" onClick={onClose} style={S.close} data-testid="home-story-close">Close</button>}
      </div>
    </div>
  )
}

export default function HomeStorySheet({ story, cio, onClose }: {
  story: HomeStory
  cio?: CioModel | null
  onClose: () => void
}) {
  const narrow = useNarrow()
  useDialogDismiss(onClose, !narrow)
  if (narrow) {
    return (
      <MobileDetailSheet title={story.sym ? `${story.sym} story` : 'Market story'} onBack={onClose}>
        <StoryView story={story} cio={cio} onClose={onClose} inlineClose={false} />
      </MobileDetailSheet>
    )
  }
  return createPortal(
    <div style={S.overlay} data-testid="home-story-overlay" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={story.sym ? `${story.sym} story` : 'Market story'}
        data-testid="home-story-dialog" onClick={e => e.stopPropagation()} style={S.panel}>
        <div style={S.panelHd}>
          <h2 style={S.panelTitle}>News · internal view</h2>
          <span style={{ flex: 1 }} />
          <button type="button" onClick={onClose} aria-label="Close" data-testid="home-story-x" autoFocus
            style={{ ...S.close, minWidth: 44 }}>✕</button>
        </div>
        <StoryView story={story} cio={cio} onClose={onClose} inlineClose />
      </div>
    </div>,
    document.body,
  )
}

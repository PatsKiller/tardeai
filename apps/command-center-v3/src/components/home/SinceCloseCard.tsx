/** LQ-20261107-1253 Home "Since last close" card — always on, top of Home. From the last regular close to now it is
 *  the overnight / weekend / holiday recap; 09:30-16:00 ET it shrinks to one line (a link, not removed).
 *  Order: CIO brief (LQ-1257, advisory only) · analysis · held moves + futures/overseas (LQ-1282) · week ahead ·
 *  news ranked by the CIO (LQ-1283, mockup v3).
 *  Reads GET /api/v2/home/since-close (a snapshot n8n refreshes overnight); nothing here orders, sizes or stops.
 *  LIVE (LQ-20261107-1269, operator 18:15 ET "make sure it's not static"): re-fetched every 60 s while the tab is
 *  VISIBLE, and re-read immediately on `visibilitychange` when it becomes visible again — a phone left on Home shows
 *  what the producer has now, not what it had when the page loaded. A hidden tab holds no timer (no background
 *  requests). What is drawn states its own age in the UPDATED/AS OF badge (SinceCloseStamp). */
import { useEffect, useState, type CSSProperties } from 'react'
import { useApi } from '../../hooks/useApi'
import { RADIUS, TOKENS, TYPE, FONT, toneVars } from '../../lib/designTokens'
import SinceCloseStamp, { useNow } from './SinceCloseStamp'
import SinceCloseSynopsis from './SinceCloseSynopsis'
import SinceCloseStops from './SinceCloseStops'
import SinceCloseMoves from './SinceCloseMoves'
import SinceCloseNews from './SinceCloseNews'
import { SINCE_CLOSE_API, pctText, sinceCloseModel, type SinceCloseWire } from '../../lib/sinceClose'
import CioCardV5 from './CioCardV5'
import { cardVisible, type CioCardWire } from '../../lib/cioCard'

/** The operator's target cadence (LQ-1269): one read a minute while the card is being looked at. */
export const SINCE_CLOSE_POLL_MS = 60_000

/** Visible-tab state: the poll interval is 0 while hidden, so `useApi` holds no timer, and the intervalMs change on
 *  becoming visible re-runs its effect — an immediate re-read, not a wait for the next tick. */
export function usePageVisible(): boolean {
  const [visible, setVisible] = useState(() => typeof document === 'undefined' || document.visibilityState !== 'hidden')
  useEffect(() => {
    const onVis = () => setVisible(document.visibilityState !== 'hidden')
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [])
  return visible
}

const info = toneVars('info')
const up = toneVars('success')
const dn = toneVars('danger')
const warn = toneVars('warning')

const S = {
  card: { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderLeft: `4px solid ${info.color}`, borderRadius: RADIUS.lg,
    padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 } as CSSProperties,
  hd: { display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' } as CSSProperties,
  h2: { margin: 0, fontSize: 16, fontWeight: 700, color: TOKENS.text[0] } as CSSProperties,
  meta: { fontSize: TYPE.sm, color: TOKENS.text[3], fontFamily: FONT.mono } as CSSProperties,
  h3: { margin: 0, fontSize: TYPE.sm, fontWeight: 800, letterSpacing: '.05em', textTransform: 'uppercase', color: TOKENS.text[3] } as CSSProperties,
  p: { margin: 0, fontSize: 14, lineHeight: 1.5, color: TOKENS.text[1], overflowWrap: 'anywhere' } as CSSProperties,
  row: { display: 'flex', gap: 8, flexWrap: 'wrap' } as CSSProperties,
  box: { background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: '8px 10px', minWidth: 0 } as CSSProperties,
  link: { minHeight: 44, display: 'inline-flex', alignItems: 'center', background: 'none', border: 'none', color: info.color, fontSize: 14,
    fontWeight: 600, cursor: 'pointer', padding: 0, fontFamily: 'inherit', textAlign: 'left' } as CSSProperties,
}

const tone = (n: number) => (n > 0 ? up.color : n < 0 ? dn.color : TOKENS.text[2])
const timeOf = (iso?: string | null) => {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', minute: '2-digit' }) + ' ET'
}

/** LQ-20261107-1352 (design v5): when Home passes an evaluated HomeCioCard@v1 (`cio5`), the v5 CIO card draws above
 *  this recap and replaces its synopsis; the stop list moves into the card's "Your actions" box unchanged. Without
 *  it (endpoint missing, not evaluated) the recap draws exactly as before. */
export default function SinceCloseCard({ cio5 }: { cio5?: CioCardWire | null } = {}) {
  // LQ-1269: a visible tab re-reads every 60 s; a hidden one is not polled at all and re-reads the moment it is shown.
  const visible = usePageVisible()
  const api = useApi<SinceCloseWire>(SINCE_CLOSE_API, visible ? SINCE_CLOSE_POLL_MS : 0)
  const nowMs = useNow()
  const m = sinceCloseModel(api.data, nowMs)
  const [open, setOpen] = useState(false)
  const v5 = cardVisible(cio5) ? cio5 : null
  const showStops = m.state !== 'none' && (m.stops !== null || m.cio.actions.length === 0)
  const v5Card = v5 ? (
    <CioCardV5 card={v5.card} adviceOk={!!v5.advice?.ok} adviceReason={v5.advice?.reason} nowMs={nowMs}
      actions={showStops ? <SinceCloseStops list={m.stops} stamp={m.stamp} nowMs={nowMs} v5 /> : undefined} />
  ) : null

  if (m.state === 'collapsed' && !open) {
    return (
      <>{v5Card}<div data-testid="since-close-card" data-state="collapsed" style={{ ...S.card, padding: '4px 14px', gap: 0 }}>
        <button type="button" style={S.link} onClick={() => setOpen(true)} aria-expanded={false} data-testid="since-close-expand">
          {m.collapsedNote ? <><b style={{ color: warn.color }}>{m.collapsedNote}</b>{' · '}</> : null}{m.label} · overnight recap
        </button>
      </div></>
    )
  }
  return (
    <>{v5Card}<section data-testid="since-close-card" data-state={m.state} aria-label={m.label} style={S.card}>
      <div style={S.hd}>
        <h2 style={S.h2}>{m.label}</h2>
        <span style={{ ...S.meta, color: m.stale ? warn.color : TOKENS.text[3] }} data-testid="since-close-fresh">{m.freshnessText}</span>
        {m.updatedText && <span style={{ ...S.meta, color: info.color }} data-testid="since-close-updated">{m.updatedText}</span>}
        {m.state === 'collapsed' && (
          <button type="button" style={{ ...S.link, marginLeft: 'auto' }} onClick={() => setOpen(false)} aria-expanded>Collapse</button>
        )}
      </div>

      <SinceCloseStamp stamp={m.stamp} nowMs={nowMs} />

      {m.state === 'none' ? (
        <p style={S.p} data-testid="since-close-none">The recap has not been built yet; it refreshes overnight. Moves and news are on the pages below.</p>
      ) : (
        <>
          {!v5 && <SinceCloseSynopsis s={m.synopsis} stamp={m.stamp} nowMs={nowMs} />}

          {!v5 && showStops && <SinceCloseStops list={m.stops} stamp={m.stamp} nowMs={nowMs} />}

          <SinceCloseStamp stamp={m.stamp} nowMs={nowMs} part="detail" />

          <div data-testid="since-close-cio" style={S.box}>
            <h3 style={S.h3}>CIO brief{m.cio.tier ? ` · ${m.cio.tier}` : ''}</h3>
            {m.cio.pending ? <p style={S.p}>{m.cio.label}</p> : (
              <>
                {m.cio.summary && <p style={S.p}>{m.cio.summary}</p>}
                {m.stops === null && m.cio.actions.map(a => <p key={a.symbol} style={{ ...S.p, fontSize: 13 }}><b>{a.symbol}</b> · {a.text} <span style={S.meta}>advisory</span></p>)}
              </>
            )}
          </div>

          <div data-testid="since-close-analysis">
            <h3 style={S.h3}>Analysis</h3>
            {m.summaryText ? <p style={S.p}>{m.summaryText}</p> : m.summaryLines.map(l => <p key={l} style={S.p}>{l}</p>)}
          </div>

          {m.today && (
            <div data-testid="since-close-today">
              <h3 style={S.h3}>{m.today.label} <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>· {m.today.basis}</span></h3>
              <div style={S.row}>
                {m.today.moves.map(t => (
                  <span key={t.symbol} style={{ ...S.box, fontSize: 13, display: 'inline-flex', gap: 6, alignItems: 'baseline' }}>
                    <b>{t.symbol}</b><span style={{ color: tone(t.change_pct), fontFamily: FONT.mono }}>{pctText(t.change_pct)}</span>
                  </span>
                ))}
              </div>
              {m.today.news.length === 0
                ? <p style={{ ...S.p, fontSize: 13, marginTop: 6 }}>No news on your names since the open.</p>
                : m.today.news.map(n => <p key={n.title} style={{ ...S.p, fontSize: 13, marginTop: 6 }}><b>{n.holdings.map(h => h.symbol).join(', ')}</b> · {n.title} <span style={S.meta}>{n.source} · {timeOf(n.published_at)}</span></p>)}
            </div>
          )}

          {/* LQ-1282 (mockup v3): every chip carries its close move AND its newest print since the close, and the
              futures/overseas row replaces the old one-line "futures feed pending". */}
          <SinceCloseMoves wire={api.data} />

          <div data-testid="since-close-week">
            <h3 style={S.h3}>Week ahead</h3>
            <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 2 }}>
              {m.weekAhead.map((e, i) => (
                <span key={`${e.date}${e.label}${i}`} style={{ ...S.box, fontSize: 12, whiteSpace: 'nowrap', flex: '0 0 auto' }}>
                  <span style={S.meta}>{e.date.slice(5)}{e.time_et ? ` ${e.time_et}` : ''}</span> {e.label}
                </span>
              ))}
              <span style={{ ...S.box, fontSize: 12, whiteSpace: 'nowrap', flex: '0 0 auto', color: TOKENS.text[3] }}>Fed speakers: {m.fedSpeakersText}</span>
            </div>
          </div>

          {/* LQ-1283 (mockup v3): the one tall column becomes a grid, the ticker leads each story, and the glow and
              the order are the producer's (rank, urgency, feed_rule in the snapshot). */}
          <SinceCloseNews wire={api.data} />
        </>
      )}
    </section></>
  )
}

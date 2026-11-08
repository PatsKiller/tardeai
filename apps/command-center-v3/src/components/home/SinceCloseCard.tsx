/** LQ-20261107-1253 Home "Since last close" card — always on, top of Home. From the last regular close to now it is
 *  the overnight / weekend / holiday recap; 09:30-16:00 ET it shrinks to one line (a link, not removed).
 *  Order: CIO brief (LQ-1257, advisory only) · analysis · held moves · futures · week ahead · news feed.
 *  Reads GET /api/v2/home/since-close (a snapshot n8n refreshes overnight); nothing here orders, sizes or stops. */
import { useState, type CSSProperties } from 'react'
import { useApi } from '../../hooks/useApi'
import { RADIUS, TOKENS, TYPE, FONT, toneVars } from '../../lib/designTokens'
import { SINCE_CLOSE_API, pctText, sinceCloseModel, usdText, type SinceCloseWire } from '../../lib/sinceClose'

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

export default function SinceCloseCard() {
  const api = useApi<SinceCloseWire>(SINCE_CLOSE_API, 5 * 60_000)
  const m = sinceCloseModel(api.data)
  const [open, setOpen] = useState(false)

  if (m.state === 'collapsed' && !open) {
    return (
      <div data-testid="since-close-card" data-state="collapsed" style={{ ...S.card, padding: '4px 14px', gap: 0 }}>
        <button type="button" style={S.link} onClick={() => setOpen(true)} aria-expanded={false} data-testid="since-close-expand">
          {m.collapsedNote ? <><b style={{ color: warn.color }}>{m.collapsedNote}</b>{' · '}</> : null}{m.label} · overnight recap
        </button>
      </div>
    )
  }
  return (
    <section data-testid="since-close-card" data-state={m.state} aria-label={m.label} style={S.card}>
      <div style={S.hd}>
        <h2 style={S.h2}>{m.label}</h2>
        <span style={{ ...S.meta, color: m.stale ? warn.color : TOKENS.text[3] }} data-testid="since-close-fresh">{m.freshnessText}</span>
        {m.updatedText && <span style={{ ...S.meta, color: info.color }} data-testid="since-close-updated">{m.updatedText}</span>}
        {m.state === 'collapsed' && (
          <button type="button" style={{ ...S.link, marginLeft: 'auto' }} onClick={() => setOpen(false)} aria-expanded>Collapse</button>
        )}
      </div>

      {m.state === 'none' ? (
        <p style={S.p} data-testid="since-close-none">The recap has not been built yet; it refreshes overnight. Moves and news are on the pages below.</p>
      ) : (
        <>
          <div data-testid="since-close-cio" style={S.box}>
            <h3 style={S.h3}>CIO brief{m.cio.tier ? ` · ${m.cio.tier}` : ''}</h3>
            {m.cio.pending ? <p style={S.p}>{m.cio.label}</p> : (
              <>
                {m.cio.summary && <p style={S.p}>{m.cio.summary}</p>}
                {m.cio.actions.map(a => <p key={a.symbol} style={{ ...S.p, fontSize: 13 }}><b>{a.symbol}</b> · {a.text} <span style={S.meta}>advisory</span></p>)}
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

          <div data-testid="since-close-moves">
            <h3 style={S.h3}>Held · {m.closeTag}</h3>
            <div style={S.row}>
              {m.held.map(h => (
                <span key={h.symbol} style={{ ...S.box, fontSize: 13, display: 'inline-flex', gap: 6, alignItems: 'baseline' }}>
                  <b>{h.symbol}</b><span style={{ color: tone(h.change_pct), fontFamily: FONT.mono }}>{pctText(h.change_pct)}</span>
                  <span style={S.meta}>{usdText(h.dollar_impact)} · wk {pctText(h.week_pct)}</span>
                  {h.no_news && <span style={{ ...S.meta, color: warn.color }}>no news</span>}
                </span>
              ))}
            </div>
            {m.watch.length > 0 && <p style={{ ...S.p, fontSize: 13, marginTop: 6 }}>Watchlist: {m.watch.map(w => `${w.symbol} ${pctText(w.change_pct)}${w.no_news ? ' (no news)' : ''}`).join(' · ')}</p>}
          </div>

          <p style={{ ...S.p, fontSize: 13 }} data-testid="since-close-futures"><b>Futures / overseas:</b> {m.futuresText}</p>

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

          <div data-testid="since-close-feed">
            <h3 style={S.h3}>News since the close</h3>
            {m.feed.length === 0 && <p style={S.p}>No news on your names since the close.</p>}
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {m.feed.map(it => (
                <li key={it.title} style={S.box}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: TOKENS.text[0], overflowWrap: 'anywhere' }}>
                    {it.url ? <a href={it.url} target="_blank" rel="noreferrer" style={{ color: 'inherit' }}>{it.title}</a> : it.title}
                  </div>
                  <div style={S.meta}>{it.source} · {timeOf(it.published_at)}{it.holdings.length > 0 ? ` · ${it.holdings.map(h => h.symbol).join(', ')}` : ''}{it.exposure > 0 ? ` · ${usdText(it.exposure).replace('+', '')} exposed` : ''}</div>
                  <div style={{ ...S.p, fontSize: 13 }}>{it.so_what}</div>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </section>
  )
}

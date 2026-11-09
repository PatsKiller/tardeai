/** LQ-20261107-1253 amendment 4 — "Your actions": the CIO's stop advice (LQ-1257 stop_advice[]) as a numbered list.
 *  Render only: the CIO owns every verdict and nothing here places or edits an order. "Done" is per-viewer state. */
import { useState, type CSSProperties } from 'react'
import { RADIUS, TOKENS, TYPE, FONT, toneVars } from '../../lib/designTokens'
import { type StopList, type StopRow } from '../../lib/stopAdvice'
import type { StampWire } from '../../lib/sinceCloseStamp'
import { AsOfBadge } from './SinceCloseStamp'

const info = toneVars('info')
const warn = toneVars('warning')
const dn = toneVars('danger')
const up = toneVars('success')

const price = (n: number | null | undefined) => (n == null ? '—' : `$${n.toFixed(2)}`)
const KEY = 'tradeai.sinceClose.stopsDone.v1'
/** LQ-1311 (operator 2026-11-08): the action cards sit side by side — three across on a desktop, one column on a phone. */
const GRID: CSSProperties = { margin: 0, padding: 0, display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 300px), 1fr))', gap: 8, alignItems: 'stretch' }

/** A HOLD row says WHY nothing moves: the working stop, its distance under the last price, and the event the CIO weighed. */
function holdLine(r: StopRow): string {
  if (r.kind !== 'HOLD') return 'no action'
  if (r.stopNow == null) return 'hold'
  const room = r.last != null && r.last > 0 ? `, ${(((r.last - r.stopNow) / r.last) * 100).toFixed(1)}% under ${price(r.last)}` : ''
  return `hold · stop ${price(r.stopNow)} already set${room}`
}

function QuietRow({ r }: { r: StopRow }) {
  return (
    <li data-testid="stops-quiet-row" style={{ listStyle: 'none', minWidth: 0, padding: '6px 10px', border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, background: TOKENS.bg[0] }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <b style={{ fontSize: 14, color: TOKENS.text[0] }}>{r.symbol}</b>
        {r.account && <span style={{ fontSize: 11, color: TOKENS.text[3] }}>{r.account}</span>}
        <span style={{ fontSize: 12, color: up.color, fontFamily: FONT.mono }}>{holdLine(r)}</span>
      </div>
      {r.what && <div style={{ fontSize: 12, color: TOKENS.text[1], overflowWrap: 'anywhere' }}>{r.what}</div>}
      {r.reason && <div style={{ fontSize: 12, color: TOKENS.text[3], overflowWrap: 'anywhere' }}>CIO: {r.reason}</div>}
    </li>
  )
}
const dayKey = (r: StopRow) => `${new Date().toLocaleDateString('en-CA', { timeZone: 'America/New_York' })}|${r.symbol}|${r.account ?? ''}|${r.kind}`

function loadDone(): Record<string, boolean> {
  try { return JSON.parse(localStorage.getItem(KEY) ?? '{}') as Record<string, boolean> } catch { return {} }
}

function orderText(r: StopRow): { main: string; sub: string } {
  const o = r.order
  if (!o) return { main: '', sub: '' }
  const gtc = o.gtc ? ' · GTC' : ''
  if (r.kind === 'ADD_STOP') return { main: `${o.qty ?? '—'} sh @ ${price(o.stop)}`, sub: `sell stop · ${o.qty ?? '—'} shares${gtc}` }
  if (r.kind === 'RAISE') return { main: `${o.oldStop != null ? price(o.oldStop) : '—'} → ${price(o.stop)}`, sub: `${o.qty ?? '—'} shares${gtc}` }
  return { main: `${o.qty ?? '—'} sh @ ${price(o.stop ?? o.oldStop)}`, sub: `set quantity to the shares you hold${gtc}` }
}

function Row({ r, done, toggle }: { r: StopRow; done: boolean; toggle: () => void }) {
  const edge = r.urgent ? dn : warn
  const o = orderText(r)
  const tone = r.consequence ? (r.consequence.tone === 'danger' ? dn : r.consequence.tone === 'success' ? up : warn) : null
  return (
    <li data-testid="stop-row" data-kind={r.kind} data-urgent={r.urgent ? 'true' : 'false'} data-done={done ? 'true' : 'false'}
      style={{ listStyle: 'none', display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: '4px 10px', padding: '10px 12px', minWidth: 0, opacity: done ? 0.55 : 1,
        borderLeft: `4px solid ${edge.color}`, background: r.urgent ? dn.bg : TOKENS.bg[0], borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`, borderLeftWidth: 4, borderLeftColor: edge.color } as CSSProperties}>
      <span style={{ fontFamily: FONT.mono, color: TOKENS.text[3], fontSize: 13, paddingTop: 4 }}>{r.n}</span>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <b style={{ fontSize: 20, color: TOKENS.text[0] }}>{r.symbol}</b>
          {r.account && <span style={{ fontSize: 12, color: TOKENS.text[3] }}>{r.account}</span>}
        </div>
        <div style={{ fontSize: 12, fontWeight: 800, letterSpacing: '.06em', color: info.color }}>{r.verb}</div>
        <div style={{ fontFamily: FONT.mono, fontWeight: 800, fontSize: 20, color: warn.color, overflowWrap: 'anywhere' }}>
          {r.kind === 'RAISE' && r.order?.oldStop != null ? <><s style={{ opacity: 0.7 }}>{price(r.order.oldStop)}</s> → {price(r.order.stop)}</> : o.main}
        </div>
        <div style={{ fontSize: 12, color: TOKENS.text[3] }}>{o.sub}</div>
        {r.consequence && tone && <div data-testid="stop-consequence" style={{ fontWeight: 800, fontSize: 15, color: tone.color }}>{r.consequence.text}</div>}
        {r.reason && <div style={{ fontSize: 13, color: TOKENS.text[1], overflowWrap: 'anywhere' }}>{r.reason}</div>}
        {r.worstCase != null && r.worstCase > 0 && <div style={{ fontSize: 12, color: TOKENS.text[3] }}>Worst case if the stop fills: about ${Math.round(r.worstCase).toLocaleString('en-US')} below Friday's close.</div>}
        {r.qa && (
          <details data-testid="stop-qa" style={{ marginTop: 4 }}>
            <summary style={{ cursor: 'pointer', fontSize: 13, color: up.color, minHeight: 28 }}>{r.qa.answer ?? 'Question and answer'}</summary>
            {r.qa.question && <p style={{ margin: '4px 0', fontSize: 13, color: TOKENS.text[1] }}><b>Q:</b> {r.qa.question}</p>}
            {r.qa.correction && <p style={{ margin: '4px 0', fontSize: 13, color: TOKENS.text[1] }}><b>Premise check:</b> {r.qa.correction}</p>}
          </details>
        )}
      </div>
      <label data-testid="stop-done" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minHeight: 44, minWidth: 44, justifyContent: 'flex-end', alignSelf: 'start', fontSize: 13, cursor: 'pointer', color: TOKENS.text[2] }}>
        <input type="checkbox" checked={done} onChange={toggle} style={{ width: 20, height: 20 }} /> Done
      </label>
    </li>
  )
}

export default function SinceCloseStops({ list, stamp, nowMs }: { list: StopList | null; stamp: StampWire | null; nowMs: number }) {
  const [done, setDone] = useState<Record<string, boolean>>(loadDone)
  if (!list) {
    return (
      <div data-testid="since-close-stops" style={{ padding: '8px 10px', border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md }}>
        <h3 style={{ margin: 0, fontSize: TYPE.sm, fontWeight: 800, letterSpacing: '.05em', textTransform: 'uppercase', color: TOKENS.text[3] }}>Your actions</h3>
        <p style={{ margin: '4px 0 0', fontSize: 14, color: TOKENS.text[2] }}>Stop advice is pending — the CIO brief has not published it yet.</p>
      </div>
    )
  }
  const flip = (r: StopRow) => () => {
    const k = dayKey(r)
    const next = { ...done, [k]: !done[k] }
    setDone(next)
    try { localStorage.setItem(KEY, JSON.stringify(next)) } catch { /* private window: the toggle still works for this view */ }
  }
  return (
    <div data-testid="since-close-stops" style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: TOKENS.text[0] }}>{list.header}</h3>
        <AsOfBadge stamp={stamp} nowMs={nowMs} />
      </div>
      {list.actions.length === 0
        ? <p style={{ margin: 0, fontSize: 14, color: up.color }} data-testid="stops-none">Nothing to change at Schwab today.</p>
        : <ol data-testid="stops-grid" style={GRID}>{list.actions.map(r => <Row key={dayKey(r)} r={r} done={!!done[dayKey(r)]} toggle={flip(r)} />)}</ol>}
      {list.quiet.length > 0 && (
        // LQ-1318: a quiet row that carries an event says the event, never a bare "hold" — QuietRow draws r.what,
        // and stopAdvice reads the writer's `event_summary` into it. (LQ-1311's card layout is kept as it is.)
        <div data-testid="stops-quiet" style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
          <span style={{ fontSize: 13, color: TOKENS.text[3] }}>No change needed ({list.quiet.length}):</span>
          <ul style={GRID}>{list.quiet.map(r => <QuietRow key={dayKey(r)} r={r} />)}</ul>
        </div>
      )}
      <p style={{ margin: 0, fontSize: 12, color: TOKENS.text[3] }} data-testid="stops-rule">Rule: {list.rule}</p>
    </div>
  )
}

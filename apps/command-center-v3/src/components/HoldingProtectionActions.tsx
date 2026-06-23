import { useState } from 'react'
import { protectionExplain, resolvedTrailPct } from '../lib/protectionTrail'

const MUTED = '#94a3b8', TEXT0 = '#f8fafc', GREEN = '#22c55e', AMBER = '#f59e0b', BLUE = '#60a5fa', PURPLE = '#a855f7', RED = '#ef4444'
const unwrapApi = (j: any) => (j && typeof j === 'object' && 'data' in j && j.data && typeof j.data === 'object') ? j.data : j
const apiReason = (j: any) => j?.result?.error ?? j?.error ?? j?.reason ?? j?.message ?? 'request failed'

const BROKER_URL: Record<string, string> = {
  fidelity: 'https://digital.fidelity.com/ftgw/digital/portfolio/summary',
  schwab: 'https://www.schwab.com/client-home',
}

export default function HoldingProtectionActions({ h, pr, monitored, confirmedStop, onRefresh }: {
  h: any; pr: any; monitored?: any; confirmedStop?: any; onRefresh?: () => void
}) {
  const acct = String(h.account ?? '')
  const sym = String(h.symbol ?? '').toUpperCase()
  const isSchwab = acct.startsWith('schwab')
  const isFidelity = acct.startsWith('fidelity') && acct !== 'fidelity_401k'
  const stop = Number(pr?.stop_price) || null
  const price = Number(pr?.price) || Number(h.current_price) || null
  const qty = Number(h.shares) || 0
  const trail = resolvedTrailPct(pr)
  const trailPct = trail?.pct ?? null
  const stopDist = trail?.stopDistPct ?? pr?.stop_distance_pct
  const liveStop = confirmedStop?.stop_price != null ? Number(confirmedStop.stop_price)
    : monitored?.status === 'armed' ? Number(monitored.effective_stop ?? monitored.stop_price)
    : null
  const liveDistPct = liveStop != null && price != null && price > 0
    ? ((price - liveStop) / price) * 100 : null

  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [ticket, setTicket] = useState('')

  if (!stop || !qty) return null

  const brokerKey = isFidelity ? 'fidelity' : isSchwab ? 'schwab' : ''
  const brokerUrl = brokerKey ? BROKER_URL[brokerKey] : null
  const preferTrail = Boolean(pr?.trail_recommended || trail?.matchesStopWidth)
  const trailLabel = trailPct != null
    ? (Math.abs(trailPct - Math.round(trailPct)) < 0.15 ? String(Math.round(trailPct)) : trailPct.toFixed(1))
    : ''

  const armStop = async (kind: 'STOP' | 'TRAILING' | 'STOP_LIMIT') => {
    setBusy(true); setMsg(''); setTicket('')
    try {
      const body = {
        symbol: sym, account: acct, qty,
        order_kind: kind,
        stop_price: stop,
        trail_pct: kind === 'TRAILING' ? trailPct : null,
        advised_stop: stop,
        current_price: price,
      }
      const raw = await fetch('/api/v2/holdings/protective-stop', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      }).then(x => x.json())
      const r = unwrapApi(raw)
      if (r?.mode === 'monitored_armed') {
        const t = r?.result?.ticket || r?.order?.ticket || ''
        setTicket(t)
        const kindLbl = kind === 'TRAILING' ? `${trailPct}% trailing` : 'fixed stop'
        setMsg(`✅ Tracking armed — ${kindLbl} @ $${stop.toFixed(2)}`)
        onRefresh?.()
      } else if (r?.mode === 'ticket') {
        setTicket(r.ticket || '')
        setMsg('✅ Ticket ready — place at broker')
      } else if (r?.mode === 'awaiting_approval') {
        setMsg(`Schwab 2FA required — open Trading → Open Trades → ${sym} for live submit`)
      } else if (r?.mode === 'blocked') {
        setMsg(`⛔ ${apiReason(r)}`)
      } else {
        setMsg(`⛔ ${apiReason(r)}`)
      }
    } catch (e: any) {
      setMsg('⛔ ' + String(e.message || e).slice(0, 80))
    } finally {
      setBusy(false)
    }
  }

  const btn = (label: string, kind: 'STOP' | 'TRAILING' | 'STOP_LIMIT', highlight = false) => (
    <button
      onClick={e => { e.stopPropagation(); armStop(kind) }}
      disabled={busy}
      title={kind === 'TRAILING'
        ? `Arm ${trailPct}% trailing — same width as ${stopDist != null ? `${Number(stopDist).toFixed(1)}%` : 'advised'} fixed stop, ratchets up`
        : `Arm fixed stop at $${stop.toFixed(2)} (${stopDist != null ? `${Number(stopDist).toFixed(1)}%` : ''} below) — does not rise`}
      style={{
        fontSize: 9, fontWeight: 800, padding: '4px 8px', borderRadius: 5, cursor: busy ? 'not-allowed' : 'pointer',
        border: `1px solid ${highlight ? AMBER : 'rgba(148,163,184,.35)'}`,
        background: highlight ? 'rgba(245,158,11,.14)' : 'rgba(15,23,42,.5)',
        color: highlight ? AMBER : TEXT0, whiteSpace: 'nowrap',
      }}
    >{busy ? '…' : label}</button>
  )

  return (
    <div onClick={e => e.stopPropagation()} style={{ marginTop: 6, padding: '7px 9px', borderRadius: 8, background: 'rgba(168,85,247,.07)', border: '1px solid rgba(168,85,247,.22)' }}>
      {(confirmedStop?.stop_price != null || monitored?.status === 'armed') && (
        <div style={{ fontSize: 9, color: GREEN, fontWeight: 800, marginBottom: 5 }}
          title={confirmedStop?.note ?? (monitored ? 'Software-monitored stop (not a broker order)' : '')}>
          ✓ {confirmedStop ? 'Stop active' : 'Tracked'} @ ${Number(liveStop).toFixed(2)}
          {confirmedStop ? ' · live @ Fidelity' : monitored?.order_type === 'TRAILING_STOP' && monitored.trail_pct != null ? ` · trail ${monitored.trail_pct}%` : ' · fixed'}
          {liveDistPct != null && (
            <span style={{ color: liveDistPct < 3 ? RED : liveDistPct < 8 ? AMBER : GREEN }}>
              {` · ${liveDistPct >= 0 ? '+' : ''}${liveDistPct.toFixed(1)}% from stop`}
            </span>
          )}
          {monitored?.last_price != null && !confirmedStop ? ` · last $${Number(monitored.last_price).toFixed(2)}` : ''}
        </div>
      )}
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 9, color: MUTED, fontWeight: 700 }}>Protect:</span>
        {btn(`Fixed ${stopDist != null ? `${Number(stopDist).toFixed(0)}%` : ''}`.trim(), 'STOP', !preferTrail)}
        {trailPct != null && btn(`Trail ${trailLabel}% ★`, 'TRAILING', preferTrail)}
        {btn('Stop-limit', 'STOP_LIMIT')}
        {brokerUrl && (
          <a href={brokerUrl} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}
            style={{ fontSize: 9, fontWeight: 800, padding: '4px 8px', borderRadius: 5, border: `1px solid ${isFidelity ? PURPLE : BLUE}`, background: `${isFidelity ? PURPLE : BLUE}18`, color: isFidelity ? PURPLE : BLUE, textDecoration: 'none' }}>
            Execute @ {isFidelity ? 'Fidelity' : 'Schwab'} ↗
          </a>
        )}
        <a href={`/v3/trading?tab=Open%20Trades&symbol=${sym}`} onClick={e => e.stopPropagation()}
          style={{ fontSize: 9, color: BLUE, fontWeight: 700, textDecoration: 'none' }}>Full controls →</a>
      </div>
      {trail && (
        <div style={{ fontSize: 8.5, color: MUTED, marginTop: 5, lineHeight: 1.45 }}>{protectionExplain(pr, trail)}</div>
      )}
      {msg && <div style={{ fontSize: 9, marginTop: 5, color: msg.startsWith('✅') ? GREEN : msg.startsWith('⛔') ? RED : AMBER }}>{msg}</div>}
      {ticket && (
        <div style={{ marginTop: 5, padding: '6px 8px', borderRadius: 6, background: 'rgba(15,23,42,.6)', fontSize: 10, fontFamily: 'monospace', color: TEXT0, lineHeight: 1.4 }}>
          {ticket}
        </div>
      )}
    </div>
  )
}
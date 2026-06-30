import { useEffect, useState } from 'react'
import { protectionExplain, resolvedTrailPct } from '../lib/protectionTrail'

const MUTED = '#94a3b8', TEXT0 = '#f8fafc', GREEN = '#22c55e', AMBER = '#f59e0b', BLUE = '#60a5fa', PURPLE = '#a855f7', RED = '#ef4444'
const SCHWAB_SELL_ALL_MAX_SHARES = 40
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
  const isFractional = isSchwab && qty > 0 && Math.abs(qty - Math.round(qty)) > 1e-9
  const needsSellAll = isSchwab && qty > 0 && qty < SCHWAB_SELL_ALL_MAX_SHARES
  const sellAllTif = isFractional ? 'DAY' : 'GTC'
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
  const [intentId, setIntentId] = useState('')
  const [approveTk, setApproveTk] = useState('')
  const [approveCode, setApproveCode] = useState('')
  const [sellAllDone, setSellAllDone] = useState(false)
  const [tokenHealth, setTokenHealth] = useState<any>(null)

  const needsReauth = isSchwab && tokenHealth?.needs_reauth === true
  useEffect(() => {
    if (!isSchwab || !intentId || tokenHealth) return
    fetch('/api/v2/brokers/schwab/token-health').then(x => x.json()).then(j => setTokenHealth(unwrapApi(j))).catch(() => {})
  }, [isSchwab, intentId, tokenHealth])

  if (!qty) return null
  if (!stop && !needsSellAll) return null

  const brokerKey = isFidelity ? 'fidelity' : isSchwab ? 'schwab' : ''
  const brokerUrl = brokerKey ? BROKER_URL[brokerKey] : null
  const confNote = String(confirmedStop?.note ?? '')
  const confirmedIsTrailing = /trailing|trail\s+\d/i.test(confNote)
    || monitored?.order_type === 'TRAILING_STOP'
  const confirmedIsFixed = Boolean(confirmedStop?.stop_price != null && !confirmedIsTrailing)
  const preferTrail = !confirmedIsFixed && Boolean(pr?.trail_recommended || trail?.matchesStopWidth)
  const trailLabel = trailPct != null
    ? (Math.abs(trailPct - Math.round(trailPct)) < 0.15 ? String(Math.round(trailPct)) : trailPct.toFixed(1))
    : ''

  const resetApprove = () => { setIntentId(''); setApproveTk(''); setApproveCode(''); setSellAllDone(false) }

  const requestOrder = async (kind: 'STOP' | 'TRAILING' | 'STOP_LIMIT' | 'MARKET', opts?: { label?: string }) => {
    setBusy(true); setMsg(''); setTicket(''); resetApprove()
    try {
      const body: Record<string, unknown> = {
        symbol: sym, account: acct, qty,
        order_kind: kind,
        stop_price: kind === 'MARKET' ? null : stop,
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
        const kindLbl = kind === 'TRAILING' ? `${trailPct}% trailing` : kind === 'MARKET' ? `market ${sellAllTif}` : 'fixed stop'
        setMsg(`✅ Tracking armed — ${kindLbl} @ ${kind === 'MARKET' ? 'market' : `$${stop!.toFixed(2)}`}`)
        onRefresh?.()
      } else if (r?.mode === 'ticket') {
        setTicket(r.ticket || r.order?.ticket || '')
        setMsg('✅ Ticket ready — place at broker')
      } else if (r?.mode === 'awaiting_approval') {
        if (!r.intent_id) { setMsg('⛔ Approval request returned no intent_id'); return }
        setIntentId(r.intent_id)
        const short = String(r.intent_id).slice(0, 8)
        const ttl = r.ttl_min ? ` · expires ${r.ttl_min}min` : ''
        setMsg(opts?.label
          ? `${opts.label} — intent ${short}${ttl} · approve below (ticker or 6-digit code)`
          : `Schwab 2FA required — intent ${short}${ttl} · approve below`)
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

  const confirmOrder = async (channel: 'web' | 'telegram') => {
    if (!intentId) { setMsg('⛔ no active intent — request the order first'); return }
    setBusy(true)
    try {
      const code = channel === 'web' ? approveTk.trim().toUpperCase() : approveCode.trim()
      const raw = await fetch('/api/v2/holdings/protective-stop/confirm', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intent_id: intentId, channel, code }),
      }).then(x => x.json())
      const r = unwrapApi(raw)
      const oid = r?.broker_order_id ?? r?.order_id ?? r?.result?.broker_order_id
      const ostatus = r?.status ?? r?.order_status ?? r?.result?.status
      const submitted = ostatus === 'submitted' || ostatus === 'filled' || r?.submitted === true
      if ((r?.stage === 'submit' || submitted || oid) && submitted && r?.ok !== false) {
        setSellAllDone(true)
        setMsg(`✅ LIVE sell placed on Schwab · order #${oid ?? '—'} (${ostatus ?? 'submitted'})`)
        onRefresh?.()
      } else if (r?.stage === 'confirm' && r?.ok && r?.fully_approved === false) {
        setMsg('channel confirmed — waiting on the other factor')
      } else if (r?.stage === 'submit' && (ostatus === 'error' || r?.ok === false)) {
        setMsg(`⛔ approved, but Schwab rejected: ${apiReason(r)}`)
      } else {
        setMsg(`⛔ ${apiReason(r)}`)
      }
    } catch (e: any) {
      setMsg('⛔ ' + String(e.message || e).slice(0, 80))
    } finally {
      setBusy(false)
    }
  }

  const armStop = (kind: 'STOP' | 'TRAILING' | 'STOP_LIMIT') => requestOrder(kind)
  const requestSellAll = () => {
    if (!window.confirm(`Sell ALL ${qty} ${sym} @ MARKET (${sellAllTif}) on ${acct}? Requires 2FA before submit.`)) return
    requestOrder('MARKET', { label: `Sell all ${qty} sh @ MARKET ${sellAllTif}` })
  }

  const tkOk = approveTk.trim().toUpperCase() === sym
  const codeOk = approveCode.trim().length === 6
  const inApprove = !!intentId && !sellAllDone
  const showProtect = stop != null && !(needsSellAll && isFractional && Math.floor(qty) < 1)

  const btn = (label: string, kind: 'STOP' | 'TRAILING' | 'STOP_LIMIT', highlight = false) => (
    <button
      onClick={e => { e.stopPropagation(); armStop(kind) }}
      disabled={busy}
      title={kind === 'TRAILING'
        ? `Arm ${trailPct}% trailing — same width as ${stopDist != null ? `${Number(stopDist).toFixed(1)}%` : 'advised'} fixed stop, ratchets up`
        : `Arm fixed stop at $${stop!.toFixed(2)} (${stopDist != null ? `${Number(stopDist).toFixed(1)}%` : ''} below) — does not rise`}
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
        <div style={{ fontSize: 12.5, color: GREEN, fontWeight: 800, marginBottom: 6, padding: '3px 8px', borderRadius: 5, background: `${GREEN}14`, border: `1px solid ${GREEN}33` }}
          title={confirmedStop?.note ?? (monitored ? 'Software-monitored stop (not a broker order)' : '')}>
          ✓ {confirmedStop ? 'Stop active' : 'Tracked'} @ <b style={{ fontFamily: 'monospace', fontSize: 14 }}>${Number(liveStop).toFixed(2)}</b>
          {confirmedStop
            ? (confirmedIsTrailing ? ' · trailing @ Fidelity' : ' · fixed stop @ Fidelity')
            : monitored?.order_type === 'TRAILING_STOP' && monitored.trail_pct != null ? ` · trail ${monitored.trail_pct}%` : ' · fixed'}
          {liveDistPct != null && (
            <span style={{ color: liveDistPct < 3 ? RED : liveDistPct < 8 ? AMBER : GREEN }}>
              {` · ${liveDistPct >= 0 ? '+' : ''}${liveDistPct.toFixed(1)}% from stop`}
            </span>
          )}
          {monitored?.last_price != null && !confirmedStop ? ` · last $${Number(monitored.last_price).toFixed(2)}` : ''}
        </div>
      )}

      {needsSellAll && (
        <div style={{ marginBottom: showProtect ? 6 : 0, padding: '6px 8px', borderRadius: 6, background: 'rgba(239,68,68,.08)', border: '1px solid rgba(239,68,68,.25)' }}>
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 9, color: MUTED, fontWeight: 700 }}>
              {isFractional ? `Fractional (${qty} sh)` : `Small (${qty} sh)`} — no resting stop for full liquidation
            </span>
            <button
              onClick={e => { e.stopPropagation(); requestSellAll() }}
              disabled={busy || needsReauth || sellAllDone}
              title={needsReauth ? 'Schwab re-auth required' : `Market sell ALL ${qty} sh · ${sellAllTif} · per-order 2FA before live submit`}
              style={{
                fontSize: 9, fontWeight: 900, padding: '4px 10px', borderRadius: 5, cursor: (busy || needsReauth) ? 'not-allowed' : 'pointer',
                border: '1px solid #ef4444', background: sellAllDone ? 'rgba(34,197,94,.14)' : 'rgba(239,68,68,.16)',
                color: sellAllDone ? GREEN : RED, whiteSpace: 'nowrap',
              }}
            >{sellAllDone ? '✓ Submitted' : busy && !intentId ? '…' : `Sell all @ MKT ${sellAllTif}`}</button>
          </div>
          {isFractional && (
            <div style={{ fontSize: 8.5, color: MUTED, marginTop: 4, lineHeight: 1.4 }}>
              Schwab fractional market orders use DAY (not GTC). Whole-share positions under {SCHWAB_SELL_ALL_MAX_SHARES} sh use GTC.
            </div>
          )}
        </div>
      )}

      {showProtect && (
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
      )}

      {inApprove && (
        <div style={{ marginTop: 6, padding: '7px 8px', borderRadius: 6, background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.28)' }}>
          <div style={{ fontSize: 9, color: TEXT0, fontWeight: 800, marginBottom: 5 }}>🔐 Approve to submit LIVE @ Schwab</div>
          {needsReauth && (
            <div style={{ fontSize: 8.5, color: RED, marginBottom: 5 }}>Re-auth needed before submit — refresh Schwab token</div>
          )}
          <div style={{ fontSize: 8.5, color: MUTED, marginBottom: 4 }}>Type ticker <b style={{ color: TEXT0 }}>{sym}</b> or 6-digit code (either channel)</div>
          <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
            <input value={approveTk} onChange={e => setApproveTk(e.target.value.toUpperCase())} placeholder={sym}
              onClick={e => e.stopPropagation()}
              style={{ flex: 1, fontSize: 10, padding: '4px 6px', borderRadius: 4, border: `1px solid ${tkOk ? GREEN : 'rgba(148,163,184,.3)'}`, background: 'rgba(15,23,42,.6)', color: TEXT0 }} />
            <button onClick={e => { e.stopPropagation(); confirmOrder('web') }} disabled={busy || !tkOk}
              style={{ fontSize: 8.5, fontWeight: 800, padding: '4px 8px', borderRadius: 4, border: 'none', cursor: (busy || !tkOk) ? 'not-allowed' : 'pointer', background: tkOk ? AMBER : '#334155', color: tkOk ? '#fff' : MUTED }}>
              approve
            </button>
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            <input value={approveCode} onChange={e => setApproveCode(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="000000" inputMode="numeric"
              onClick={e => e.stopPropagation()}
              style={{ flex: 1, fontSize: 10, padding: '4px 6px', borderRadius: 4, border: `1px solid ${codeOk ? GREEN : 'rgba(148,163,184,.3)'}`, background: 'rgba(15,23,42,.6)', color: TEXT0, letterSpacing: 2, fontFamily: 'monospace' }} />
            <button onClick={e => { e.stopPropagation(); confirmOrder('telegram') }} disabled={busy || !codeOk}
              style={{ fontSize: 8.5, fontWeight: 800, padding: '4px 8px', borderRadius: 4, border: 'none', cursor: (busy || !codeOk) ? 'not-allowed' : 'pointer', background: codeOk ? AMBER : '#334155', color: codeOk ? '#fff' : MUTED }}>
              approve
            </button>
          </div>
        </div>
      )}

      {trail && showProtect && (
        <div style={{ fontSize: 8.5, color: MUTED, marginTop: 5, lineHeight: 1.45 }}>{protectionExplain(pr, trail, { brokerFixedActive: confirmedIsFixed })}</div>
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
import { useEffect, useState } from 'react'
import { protectionExplain, resolvedTrailPct } from '../lib/protectionTrail'
import { buildStopLogic, type StopOrderKind } from '../lib/stopManagement'

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
  const [wholeShareConfirmed, setWholeShareConfirmed] = useState(false)
  const [activeApproval, setActiveApproval] = useState<any>(null)

  const needsReauth = isSchwab && tokenHealth?.needs_reauth === true
  useEffect(() => {
    if (!isSchwab || !intentId || tokenHealth) return
    fetch('/api/v2/brokers/schwab/token-health').then(x => x.json()).then(j => setTokenHealth(unwrapApi(j))).catch(() => {})
  }, [isSchwab, intentId, tokenHealth])

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
  const [selectedKind, setSelectedKind] = useState<StopOrderKind>('STOP')
  const logic = buildStopLogic({
    h,
    pr,
    monitored,
    confirmedStop,
    trailPct,
    orderKind: selectedKind,
    wholeShareConfirmed,
    sourceTimestamp: pr?.source_timestamp ?? pr?.quote_at ?? pr?.at,
  })

  if (!qty) return null
  if (!stop && !needsSellAll && !logic.isFundLike && logic.liveStop == null) return null

  const resetApprove = () => { setIntentId(''); setApproveTk(''); setApproveCode(''); setSellAllDone(false) }

  const requestOrder = async (kind: 'STOP' | 'TRAILING' | 'STOP_LIMIT' | 'MARKET', opts?: { label?: string }) => {
    setSelectedKind(kind)
    const nextLogic = buildStopLogic({
      h, pr, monitored, confirmedStop, trailPct, orderKind: kind, wholeShareConfirmed,
      sourceTimestamp: pr?.source_timestamp ?? pr?.quote_at ?? pr?.at,
    })
    if (kind !== 'MARKET' && !nextLogic.canRequestLive && isSchwab) {
      setMsg(`⛔ ${nextLogic.blockers.map(b => b.message).join(' ')}`)
      return
    }
    setBusy(true); setMsg(''); setTicket(''); resetApprove()
    try {
      const body: Record<string, unknown> = {
        symbol: sym, account: acct, qty,
        order_kind: kind,
        stop_price: kind === 'MARKET' ? null : stop,
        trail_pct: kind === 'TRAILING' ? trailPct : null,
        advised_stop: stop,
        current_price: price,
        source_broker: pr?.source_broker ?? pr?.broker ?? pr?.account ?? pr?.source_account,
        instrument_type: logic.instrumentType,
        quote_at: pr?.source_timestamp ?? pr?.quote_at ?? pr?.at,
        whole_share_confirmed: wholeShareConfirmed,
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
        if (r?.active_approval) setActiveApproval(r.active_approval)
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

  const cancelActiveApproval = async () => {
    const iid = activeApproval?.intent_id || intentId
    if (!iid) { setMsg('⛔ no active approval to cancel'); return }
    setBusy(true)
    try {
      const raw = await fetch('/api/v2/holdings/protective-stop/reject-intent', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intent_id: iid }),
      }).then(x => x.json())
      const r = unwrapApi(raw)
      if (r?.ok) {
        setActiveApproval(null); resetApprove(); setMsg('Approval rejected/canceled.')
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
  const showProtect = stop != null && !logic.isFundLike && !(needsSellAll && isFractional && Math.floor(qty) < 1)
  const liveBlocked = !logic.canRequestLive
  const statusColor = logic.state === 'LIVE BROKER STOP' ? GREEN
    : logic.state === 'MONITORED — SOFTWARE ONLY' ? PURPLE
      : logic.state === 'SOURCE MISMATCH — BLOCKED' || logic.state === 'ACTION REQUIRED' ? RED
        : logic.state === 'NOT APPLICABLE' ? MUTED
          : AMBER

  const btn = (label: string, kind: 'STOP' | 'TRAILING' | 'STOP_LIMIT', highlight = false) => (
    <button
      onClick={e => { e.stopPropagation(); armStop(kind) }}
      disabled={busy || liveBlocked}
      title={kind === 'TRAILING'
        ? `Arm ${trailPct}% trailing — same width as ${stopDist != null ? `${Number(stopDist).toFixed(1)}%` : 'advised'} fixed stop, ratchets up`
        : `Arm fixed stop at $${stop!.toFixed(2)} (${stopDist != null ? `${Number(stopDist).toFixed(1)}%` : ''} below) — does not rise`}
      style={{
        fontSize: 12, fontWeight: 800, minHeight: 34, padding: '7px 10px', borderRadius: 6, cursor: (busy || liveBlocked) ? 'not-allowed' : 'pointer',
        border: `1px solid ${highlight ? AMBER : 'rgba(148,163,184,.35)'}`,
        background: highlight ? 'rgba(245,158,11,.18)' : 'rgba(15,23,42,.66)',
        color: liveBlocked ? MUTED : highlight ? AMBER : TEXT0, whiteSpace: 'nowrap',
      }}
    >{busy ? '…' : label}</button>
  )

  return (
    <div onClick={e => e.stopPropagation()} style={{ marginTop: 10, padding: '12px 13px', borderRadius: 8, background: 'rgba(15,23,42,.74)', border: `1px solid ${statusColor}55`, boxShadow: `inset 3px 0 0 ${statusColor}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 9, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 15, color: statusColor, fontWeight: 900, letterSpacing: 0.2 }}>STOP STATUS: {logic.state}</div>
        <span style={{ fontSize: 12, color: MUTED }}>{logic.nextAction}</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 7, fontSize: 12, lineHeight: 1.35, color: TEXT0 }}>
        <div><span style={{ color: MUTED }}>Current</span><br /><b>{logic.currentPrice != null ? `$${logic.currentPrice.toFixed(2)}` : 'missing'}</b></div>
        <div><span style={{ color: MUTED }}>Account + broker</span><br /><b>{acct}</b> · {logic.broker}</div>
        <div><span style={{ color: MUTED }}>Instrument</span><br /><b>{logic.instrumentType.replace(/_/g, ' ')}</b></div>
        <div><span style={{ color: MUTED }}>Broker live stop</span><br /><b style={{ color: logic.liveStop != null ? GREEN : MUTED }}>{logic.liveStop != null ? `$${logic.liveStop.toFixed(2)}` : 'none'}</b></div>
        <div><span style={{ color: MUTED }}>Suggested fixed stop</span><br /><b style={{ color: AMBER }}>{logic.advisoryStop != null ? `$${logic.advisoryStop.toFixed(2)}` : 'none'}</b>{logic.distancePct != null ? ` (${logic.distancePct.toFixed(1)}% below)` : ''}</div>
        <div><span style={{ color: MUTED }}>Optional trail</span><br /><b>{trailPct != null ? `${trailLabel}%` : 'none'}</b></div>
        <div><span style={{ color: MUTED }}>Family floor/cap</span><br /><b>{pr?.family_floor ?? pr?.floor_label ?? pr?.family ?? 'not provided'}</b></div>
        <div><span style={{ color: MUTED }}>Source timestamp</span><br /><b>{String(pr?.source_timestamp ?? pr?.quote_at ?? pr?.at ?? 'missing').slice(0, 19)}</b></div>
      </div>

      {(pr?.rationale || pr?.reason || pr?.rec) && (
        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text2)', lineHeight: 1.45 }}>
          <b style={{ color: TEXT0 }}>Reason:</b> {pr?.rationale ?? pr?.reason ?? pr?.rec}
        </div>
      )}
      {logic.blockers.length > 0 && (
        <div style={{ marginTop: 8, display: 'grid', gap: 5 }}>
          {logic.blockers.map(b => (
            <div key={b.code} style={{ fontSize: 12, color: b.code === 'fractional_qty' ? AMBER : RED, background: b.code === 'fractional_qty' ? 'rgba(245,158,11,.12)' : 'rgba(239,68,68,.1)', border: `1px solid ${b.code === 'fractional_qty' ? AMBER : RED}44`, borderRadius: 6, padding: '7px 8px' }}>{b.message}</div>
          ))}
        </div>
      )}
      {isSchwab && logic.residualQty > 1e-6 && showProtect && (
        <label style={{ marginTop: 8, display: 'flex', gap: 7, alignItems: 'center', fontSize: 12, color: TEXT0 }}>
          <input type="checkbox" checked={wholeShareConfirmed} onChange={e => setWholeShareConfirmed(e.target.checked)} />
          Confirm whole-share Schwab order: SELL {logic.wholeQty} {sym}; residual {logic.residualQty.toFixed(4)} shares remain monitored.
        </label>
      )}

      {needsSellAll && (
        <div style={{ marginBottom: showProtect ? 6 : 0, padding: '6px 8px', borderRadius: 6, background: 'rgba(239,68,68,.08)', border: '1px solid rgba(239,68,68,.25)' }}>
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 12, color: MUTED, fontWeight: 700 }}>
              {isFractional ? `Fractional (${qty} sh)` : `Small (${qty} sh)`} — no resting stop for full liquidation
            </span>
            <button
              onClick={e => { e.stopPropagation(); requestSellAll() }}
              disabled={busy || needsReauth || sellAllDone}
              title={needsReauth ? 'Schwab re-auth required' : `Market sell ALL ${qty} sh · ${sellAllTif} · per-order 2FA before live submit`}
              style={{
                fontSize: 12, fontWeight: 900, minHeight: 34, padding: '7px 10px', borderRadius: 6, cursor: (busy || needsReauth) ? 'not-allowed' : 'pointer',
                border: '1px solid #ef4444', background: sellAllDone ? 'rgba(34,197,94,.14)' : 'rgba(239,68,68,.16)',
                color: sellAllDone ? GREEN : RED, whiteSpace: 'nowrap',
              }}
            >{sellAllDone ? '✓ Submitted' : busy && !intentId ? '…' : `Sell all @ MKT ${sellAllTif}`}</button>
          </div>
          {isFractional && (
            <div style={{ fontSize: 12, color: MUTED, marginTop: 6, lineHeight: 1.4 }}>
              Schwab fractional market orders use DAY (not GTC). Whole-share positions under {SCHWAB_SELL_ALL_MAX_SHARES} sh use GTC.
            </div>
          )}
        </div>
      )}

      {showProtect && (
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: MUTED, fontWeight: 800 }}>Action:</span>
          {btn(`Fixed ${stopDist != null ? `${Number(stopDist).toFixed(0)}%` : ''}`.trim(), 'STOP', !preferTrail)}
          {trailPct != null && btn(`Trail ${trailLabel}% ★`, 'TRAILING', preferTrail)}
          {btn('Stop-limit', 'STOP_LIMIT')}
          {brokerUrl && (
            <a href={brokerUrl} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}
              style={{ fontSize: 12, fontWeight: 800, minHeight: 34, display: 'inline-flex', alignItems: 'center', padding: '0 10px', borderRadius: 6, border: `1px solid ${isFidelity ? PURPLE : BLUE}`, background: `${isFidelity ? PURPLE : BLUE}18`, color: isFidelity ? PURPLE : BLUE, textDecoration: 'none' }}>
              {isFidelity ? 'Manual Fidelity ticket' : 'Open Schwab'} ↗
            </a>
          )}
          <a href={`/v3/trading?tab=Open%20Trades&symbol=${sym}`} onClick={e => e.stopPropagation()}
            style={{ fontSize: 12, color: BLUE, fontWeight: 800, minHeight: 34, display: 'inline-flex', alignItems: 'center', textDecoration: 'none' }}>Full controls →</a>
        </div>
      )}

      {inApprove && (
        <div style={{ marginTop: 10, padding: '10px 11px', borderRadius: 7, background: 'rgba(245,158,11,.1)', border: '1px solid rgba(245,158,11,.35)' }}>
          <div style={{ fontSize: 14, color: TEXT0, fontWeight: 900, marginBottom: 6 }}>Approve to submit LIVE @ Schwab</div>
          {needsReauth && (
            <div style={{ fontSize: 12, color: RED, marginBottom: 5 }}>Re-auth needed before submit — refresh Schwab token</div>
          )}
          <div style={{ fontSize: 12, color: MUTED, marginBottom: 7 }}>
            Formula: current {logic.currentPrice != null ? `$${logic.currentPrice.toFixed(2)}` : 'missing'} · trail {trailPct != null ? `${trailLabel}%` : 'n/a'} · initial stop {logic.advisoryStop != null ? `$${logic.advisoryStop.toFixed(2)}` : 'n/a'} · qty {isSchwab && logic.residualQty > 1e-6 ? logic.wholeQty : qty} · broker Schwab · account {acct} · 2FA pending
          </div>
          <div style={{ fontSize: 12, color: MUTED, marginBottom: 6 }}>Type ticker <b style={{ color: TEXT0 }}>{sym}</b> or 6-digit code (either channel)</div>
          <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
            <input value={approveTk} onChange={e => setApproveTk(e.target.value.toUpperCase())} placeholder={sym}
              onClick={e => e.stopPropagation()}
              style={{ flex: 1, fontSize: 10, padding: '4px 6px', borderRadius: 4, border: `1px solid ${tkOk ? GREEN : 'rgba(148,163,184,.3)'}`, background: 'rgba(15,23,42,.6)', color: TEXT0 }} />
            <button onClick={e => { e.stopPropagation(); confirmOrder('web') }} disabled={busy || !tkOk}
              style={{ fontSize: 12, fontWeight: 800, minHeight: 34, padding: '4px 10px', borderRadius: 4, border: 'none', cursor: (busy || !tkOk) ? 'not-allowed' : 'pointer', background: tkOk ? AMBER : '#334155', color: tkOk ? '#fff' : MUTED }}>
              approve
            </button>
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            <input value={approveCode} onChange={e => setApproveCode(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="6-digit code" inputMode="numeric"
              onClick={e => e.stopPropagation()}
              style={{ flex: 1, fontSize: 10, padding: '4px 6px', borderRadius: 4, border: `1px solid ${codeOk ? GREEN : 'rgba(148,163,184,.3)'}`, background: 'rgba(15,23,42,.6)', color: TEXT0, letterSpacing: 2, fontFamily: 'monospace' }} />
            <button onClick={e => { e.stopPropagation(); confirmOrder('telegram') }} disabled={busy || !codeOk}
              style={{ fontSize: 12, fontWeight: 800, minHeight: 34, padding: '4px 10px', borderRadius: 4, border: 'none', cursor: (busy || !codeOk) ? 'not-allowed' : 'pointer', background: codeOk ? AMBER : '#334155', color: codeOk ? '#fff' : MUTED }}>
              approve
            </button>
          </div>
          <button onClick={e => { e.stopPropagation(); cancelActiveApproval() }} disabled={busy}
            style={{ marginTop: 7, fontSize: 12, fontWeight: 800, minHeight: 34, padding: '5px 10px', borderRadius: 6, border: `1px solid ${RED}66`, background: 'rgba(239,68,68,.12)', color: RED, cursor: busy ? 'not-allowed' : 'pointer' }}>
            Reject intent / cancel approval
          </button>
        </div>
      )}
      {activeApproval && !inApprove && (
        <div style={{ marginTop: 8, padding: '8px 9px', borderRadius: 6, background: 'rgba(239,68,68,.1)', border: '1px solid rgba(239,68,68,.35)', fontSize: 12, color: RED }}>
          Blocked by active approval: {activeApproval.headline ?? activeApproval.intent_id}, expires {activeApproval.expires_et ?? activeApproval.expires_at ?? 'soon'}
          <button onClick={e => { e.stopPropagation(); cancelActiveApproval() }} disabled={busy}
            style={{ marginLeft: 8, minHeight: 34, padding: '5px 10px', borderRadius: 6, border: `1px solid ${RED}66`, background: 'rgba(239,68,68,.14)', color: RED, fontSize: 12, fontWeight: 800 }}>
            Cancel active approval
          </button>
        </div>
      )}

      {trail && showProtect && (
        <div style={{ fontSize: 12, color: MUTED, marginTop: 8, lineHeight: 1.5 }}>{protectionExplain(pr, trail, { brokerFixedActive: confirmedIsFixed })}</div>
      )}
      {msg && <div style={{ fontSize: 12, marginTop: 7, color: msg.startsWith('✅') ? GREEN : msg.startsWith('⛔') ? RED : AMBER }}>{msg}</div>}
      {ticket && (
        <div style={{ marginTop: 5, padding: '6px 8px', borderRadius: 6, background: 'rgba(15,23,42,.6)', fontSize: 10, fontFamily: 'monospace', color: TEXT0, lineHeight: 1.4 }}>
          {ticket}
        </div>
      )}
    </div>
  )
}

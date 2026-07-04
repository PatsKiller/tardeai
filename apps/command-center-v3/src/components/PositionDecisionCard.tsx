import { useState, useEffect } from 'react'
import { fmt$ } from '../lib/format'
import ProAnalystPill from './ProAnalystPill'
import PreflightChangedPanel from './PreflightChangedPanel'
import { resolvedTrailPct } from '../lib/protectionTrail'
import { runProtectiveStopPreflight, unwrapApi, type PreflightDiff } from '../lib/protectiveStopPreflight'
import { buildStopLogic, type StopOrderKind } from '../lib/stopManagement'
import { formatReviewStamp, stopReviewTooltip } from '../lib/stopReviewTooltip'

const TEXT0 = '#f8fafc'
const TEXT1 = '#dbeafe'
const TEXT2 = '#cbd5e1'
const MUTED = '#94a3b8'
const DIM = '#64748b'
const GREEN = '#22c55e'
const RED = '#ef4444'
const AMBER = '#f59e0b'
const BLUE = '#60a5fa'
const PURPLE = '#a855f7'

const chip = (bg: string, fg: string, strong = false) => ({ fontSize: strong ? 10 : 9, fontWeight: strong ? 850 : 750, padding: strong ? '3px 8px' : '2px 7px', borderRadius: 5, background: bg, color: fg, whiteSpace: 'nowrap' as const, display: 'inline-block', border: `1px solid ${fg}44` })
const metric = { background: 'rgba(2,6,23,.38)', border: '1px solid rgba(148,163,184,.18)', borderRadius: 9, padding: '8px 9px' } as const
const num = (v: any, d = 2) => (v == null || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(d))
const pct = (v: any) => (v == null || Number.isNaN(Number(v)) ? '—' : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(1)}%`)
const PRI: Record<string, string> = { critical: RED, high: AMBER, medium: BLUE, low: GREEN }
const RSI_C = (b: string) => b === 'oversold' ? GREEN : b === 'overbought' ? RED : b === 'missing' ? MUTED : BLUE
const BASIS_C: Record<string, string> = { broker: GREEN, tax_grade: GREEN, verified: BLUE, entry: BLUE, owner_provided: PURPLE, unknown: RED }
const FRESH_C: Record<string, string> = { fresh: GREEN, aging: AMBER, stale: RED, none: MUTED }
const LANE_META: Record<string, { label: string; c: string }> = { local: { label: 'GEMMA', c: '#2dd4bf' }, grok: { label: 'GROK', c: AMBER }, chatgpt: { label: 'GPT', c: '#a3e635' }, claude: { label: 'CLAUDE', c: '#d97757' } }
const SCHWAB_SELL_ALL_MAX_SHARES = 40

// The REAL failure reason is often nested in result.error (e.g. a Schwab transport error like an expired
// refresh token) — dig there first so the operator sees the actual cause, not a generic "failed".
const apiReason = (j: any) => j?.result?.error ?? j?.error ?? j?.reason ?? j?.message ?? j?.hint ?? 'request failed'
const internalBlockMessage = (r: any) => {
  const reason = r?.reason || apiReason(r)
  if (r?.broker_submitted === false && (r?.stage === 'evidence_revalidation' || String(reason).includes('no_evidence_bound_approval'))) {
    return 'Trade AI blocked submit before Schwab: missing evidence-bound approval. No broker order was sent.'
  }
  if (r?.broker_submitted === false) {
    return `Trade AI blocked submit before Schwab: ${reason}. No broker order was sent.`
  }
  return null
}

function Metric({ label, value, color = TEXT0, title }: any) {
  return <div style={metric} title={title}><div style={{ fontSize: 8.5, color: MUTED, textTransform: 'uppercase', fontWeight: 850, letterSpacing: '.05em' }}>{label}</div><div style={{ fontSize: 13, color, fontWeight: 900, marginTop: 3, cursor: title ? 'help' : undefined }}>{value}</div></div>
}

export default function PositionDecisionCard({ p, paMap, expanded, onToggle, onDrill, onAction, llmCov, protectionRec, symCard }: any) {
  const t = p.technical || {}, sr = p.sector_relative || {}
  const priority = p.operator_priority || 'low'
  const border = PRI[priority] || BLUE
  const news: any[] = p.news ?? []
  const lanes: Record<string, any> = {}
  for (const c of (llmCov ?? [])) { const k = LANE_META[c.lane] ? c.lane : 'local'; if (!lanes[k] || c.last_at > lanes[k].last_at) lanes[k] = c }
  const paper = p.environment === 'paper' || String(p.account ?? '').toLowerCase().includes('paper')
  const pnlColor = (p.unrealized_pnl ?? 0) >= 0 ? GREEN : RED
  const basis = p.basis_reliable ? num(p.entry_price) : 'n/a'
  // R-multiple fallback: imported holdings have no tracked R (no strategy entry+stop). When the stored
  // r_multiple is null but we have a reliable basis (entry), a current price, and an advised stop BELOW
  // entry (real downside risk), express current P&L in R units against that advised stop. Marked "~"
  // (advisory). The "Stop" field falls back to the advised stop (marked "*"). Funds (no basis/price) stay '—'.
  const _advStop = protectionRec ? (Number(protectionRec.stop_price) || null) : null
  const _entry = p.basis_reliable ? (Number(p.entry_price) || null) : null
  const _now = Number(p.current_price) || null
  const _rTracked = p.r_multiple != null
  const _rAdvisory = (!_rTracked && _entry && _now && _advStop && (_entry - _advStop) > 0)
    ? (_now - _entry) / (_entry - _advStop) : null
  const _rShow = _rTracked ? Number(p.r_multiple) : _rAdvisory

  // Protective-stop order placement (Stage 2c). Schwab accounts can submit via API; Fidelity = ToS ticket.
  const _acct = String(p.account ?? '')
  const _sym = String(p.symbol ?? '').toUpperCase()
  const _isSchwab = _acct.startsWith('schwab')
  const _isFidelity = _acct.startsWith('fidelity') && _acct !== 'fidelity_401k'
  const [stopOrder, setStopOrder] = useState<any>(null)   // {kind, qty, stop, trailPct, label}
  const [stopTk, setStopTk] = useState('')                // type-the-ticker (web 2FA channel)
  const [stopCode, setStopCode] = useState('')            // telegram/email one-time code (other channel)
  const [stopBusy, setStopBusy] = useState(false)
  const [stopMsg, setStopMsg] = useState('')
  const [stopIntent, setStopIntent] = useState<string>('')   // intent_id once 2FA requested (approve phase)
  const [stopTicket, setStopTicket] = useState<string>('')   // ticket string when account has no API
  const [stopDone, setStopDone] = useState(false)
  const [validating, setValidating] = useState(false)
  const [preflightDiff, setPreflightDiff] = useState<PreflightDiff | null>(null)
  const [pendingAction, setPendingAction] = useState<{ kind: 'request' } | { kind: 'confirm'; channel: 'web' | 'telegram' } | null>(null)
  const [advisoryOverride, setAdvisoryOverride] = useState<any>(null)
  const [liveStopOverride, setLiveStopOverride] = useState<any>(null)
  const effectiveProtectionRec = advisoryOverride ? { ...protectionRec, ...advisoryOverride } : protectionRec
  const _bstop = (p as any).broker_stop as any
  const effectiveBrokerStop = liveStopOverride ?? _bstop
  const _trailRes = resolvedTrailPct(effectiveProtectionRec)
  const _trailPct = _trailRes?.pct ?? null
  const _priceTs = p.price_updated_at ?? effectiveProtectionRec?.source_timestamp ?? effectiveProtectionRec?.at ?? null
  const _effectivePrice = Number(effectiveProtectionRec?.price) || Number(p.current_price) || null
  const computeLogic = (orderKind: StopOrderKind, overrides?: {
    quotePrice?: number | null; quoteTs?: string | null; liveStop?: any; advisorySnap?: any
  }) => {
    const px = overrides?.quotePrice ?? _effectivePrice
    const ts = overrides?.quoteTs ?? _priceTs
    const conf = overrides?.liveStop ?? effectiveBrokerStop
    const snap = overrides?.advisorySnap
    const pr = snap ? { ...effectiveProtectionRec, ...snap, price: px } : { ...effectiveProtectionRec, price: px }
    return buildStopLogic({
      h: { ...p, symbol: _sym, account: _acct, current_price: px, price: px, source_timestamp: ts },
      pr,
      monitored: null,
      confirmedStop: conf,
      trailPct: _trailPct,
      orderKind,
      wholeShareConfirmed: false,
      sourceTimestamp: ts,
    })
  }
  const runClickPreflight = async (orderKind: StopOrderKind) => {
    setValidating(true)
    setPreflightDiff(null)
    setPendingAction(null)
    setStopMsg('⏳ Validating quote + advisory + stop logic…')
    const pf = await runProtectiveStopPreflight({
      sym: _sym, acct: _acct, orderKind, trailPct: _trailPct, isSchwab: _isSchwab, isFidelity: _isFidelity,
      priceTimestamp: _priceTs, effectivePrice: _effectivePrice, effectiveConfirmed: effectiveBrokerStop,
      computeLogic,
    })
    if (pf.advisorySnap) {
      setAdvisoryOverride({ ...pf.advisorySnap, price: pf.quoteSnap?.quote_price ?? pf.advisorySnap.price })
    }
    if (pf.liveSnap && pf.liveSnap !== effectiveBrokerStop) setLiveStopOverride(pf.liveSnap)
    setValidating(false)
    return pf
  }
  // Schwab OAuth token health — surfaced UP FRONT so a dead/expired refresh token shows "re-auth needed"
  // BEFORE an order attempt (the freshness timestamp alone can read healthy while Schwab has revoked it).
  const [tokenHealth, setTokenHealth] = useState<any>(null)
  const _needsReauth = _isSchwab && tokenHealth?.needs_reauth === true
  useEffect(() => {
    if (!_isSchwab || !stopOrder || tokenHealth) return
    fetch('/api/v2/brokers/schwab/token-health').then(x => x.json()).then(j => setTokenHealth(unwrapApi(j))).catch(() => {})
  }, [_isSchwab, stopOrder, tokenHealth])
  const _resetStop = () => {
    setStopOrder(null); setStopTk(''); setStopCode(''); setStopMsg(''); setStopIntent(''); setStopTicket(''); setStopDone(false)
    setValidating(false); setPreflightDiff(null); setPendingAction(null); setAdvisoryOverride(null); setLiveStopOverride(null)
  }
  // "Ignore stop for a week" — operator acknowledgement granting a 7-day grace period. Suppresses the stop
  // ALERT (stop_snooze table); advisory only — does NOT change or cancel the protective stop at the broker.
  const [snoozeBusy, setSnoozeBusy] = useState(false)
  const [snoozeMsg, setSnoozeMsg] = useState('')
  const _snoozeStop = async () => {
    setSnoozeBusy(true); setSnoozeMsg('')
    try {
      const r = await fetch('/api/v2/holdings/stop-snooze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: p.symbol, days: 7 }) }).then(x => x.json())
      setSnoozeMsg(r?.ok ? `✓ Acknowledged — ${p.symbol} stop alert snoozed 1 week (until ${String(r.snoozed_until).slice(0, 10)}); protective stop unchanged` : `failed: ${r?.error ?? '—'}`)
    } catch { setSnoozeMsg('snooze failed — retry') } finally { setSnoozeBusy(false) }
  }
  // Fractional Schwab positions can't hold a resting broker STOP (Schwab rejects fractional stops) — arm a
  // SYNTHETIC stop instead: a monitored level that, on breach, requests a Market-Day sell-all 2FA.
  const _shares = Number(p.shares) || 0
  const _isFractional = _isSchwab && _shares > 0 && Math.abs(_shares - Math.round(_shares)) > 1e-9
  const _needsSellAll = _isSchwab && _shares > 0 && _shares < SCHWAB_SELL_ALL_MAX_SHARES
  const _sellAllTif = _isFractional ? 'DAY' : 'GTC'
  const [synthBusy, setSynthBusy] = useState(false)
  const [synthMsg, setSynthMsg] = useState('')
  const _openSellAll = () => {
    if (!window.confirm(`Sell ALL ${_shares} ${p.symbol} @ MARKET (${_sellAllTif}) on ${_acct}? Requires 2FA before submit.`)) return
    _resetStop()
    setStopOrder({
      kind: 'MARKET', qty: _shares, stop: null, trailPct: null,
      label: `SELL ALL ${_shares} ${p.symbol} @ MARKET ${_sellAllTif}`,
      advised: _advStop, cur: Number(p.current_price) || null,
    })
  }
  const _armSynthetic = async (level: number) => {
    setSynthBusy(true); setSynthMsg('')
    try {
      const r = unwrapApi(await fetch('/api/v2/holdings/synthetic-stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: p.symbol, account: p.account, stop_price: level, qty: _shares, note: 'fractional — arm from card' }) }).then(x => x.json()))
      setSynthMsg(r?.ok ? `✓ Synthetic stop armed @ $${Number(level).toFixed(2)} on full ${_shares} sh — on breach you'll get a Market-Day sell-all 2FA (nothing placed at the broker)` : `⛔ ${apiReason(r)}`)
    } catch (e: any) { setSynthMsg('⛔ ' + e.message) } finally { setSynthBusy(false) }
  }
  const preflightAndRequest = async () => {
    if (!stopOrder) return
    const kind = stopOrder.kind as StopOrderKind
    if (kind === 'MARKET') { _requestStop(); return }
    const pf = await runClickPreflight(kind)
    if (!pf.ok) {
      setStopMsg(`⛔ Validation failed — ${pf.blockers?.join(' · ') || pf.error || 'resolve blockers above'}`)
      return
    }
    if (pf.changed && pf.diffObj) {
      setPreflightDiff(pf.diffObj)
      setPendingAction({ kind: 'request' })
      setStopMsg('⚠️ Logic changed since page load — review below, then confirm to proceed.')
      return
    }
    setStopMsg('✓ Validated — proceeding…')
    await _requestStop(true)
  }
  const preflightAndConfirm = async (channel: 'web' | 'telegram') => {
    if (!stopOrder) return
    const kind = stopOrder.kind as StopOrderKind
    const pf = await runClickPreflight(kind)
    if (!pf.ok) {
      setStopMsg(`⛔ Cannot submit — ${pf.blockers?.join(' · ') || 'validation failed'}`)
      return
    }
    if (pf.changed && pf.diffObj) {
      setPreflightDiff(pf.diffObj)
      setPendingAction({ kind: 'confirm', channel })
      setStopMsg('⚠️ Logic changed — confirm again to submit to Schwab.')
      return
    }
    await _confirmStop(channel, true)
  }
  // STEP 1 — request: builds the order + (Schwab/armed) requests per-order 2FA, or returns a ToS ticket.
  const _requestStop = async (skipPreflight = false) => {
    if (!skipPreflight) { await preflightAndRequest(); return }
    setStopBusy(true); setStopMsg('requesting…')
    try {
      const body = { symbol: p.symbol, account: p.account, qty: stopOrder.qty, order_kind: stopOrder.kind,
                     stop_price: stopOrder.kind === 'MARKET' ? null : stopOrder.stop,
                     trail_pct: stopOrder.trailPct ?? null,
                     advised_stop: stopOrder.advised ?? null, current_price: stopOrder.cur ?? null,
                     replace_order_id: stopOrder.replace_order_id ?? null }
      const raw = await fetch('/api/v2/holdings/protective-stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(x => x.json())
      const r = unwrapApi(raw)
      if (r?.mode === 'awaiting_approval') {
        if (!r.intent_id) { setStopMsg('⛔ Approval request returned no intent_id — cannot confirm. Check backend protective-stop endpoint.'); return }
        setStopIntent(r.intent_id)
        const short = String(r.intent_id).slice(0, 8)
        const ttl = r.ttl_min ? ` · expires ${r.ttl_min}min` : ''
        setStopMsg(`Intent ${short}${ttl} · approve by ticker or 6-digit code · one channel is enough`)
      }
      else if (r?.mode === 'ticket') { setStopTicket(r.ticket); setStopMsg('✅ ToS ticket ready — place it exactly in thinkorswim (no trading API on this account).') }
      else if (r?.mode === 'monitored_armed') {
        const t = r?.result?.ticket || r?.order?.ticket || ''
        if (t) setStopTicket(t)
        setStopDone(true)
        setStopMsg(`✅ Monitored stop armed — tracking ${p.symbol}. On breach: alert + Fidelity Active Trader ticket.`)
      }
      else setStopMsg(`⛔ ${apiReason(r)}`)
    } catch (e: any) { setStopMsg('⛔ ' + e.message) } finally { setStopBusy(false) }
  }
  // STEP 2 — confirm the per-order 2FA (EITHER channel) and submit LIVE.
  const _confirmStop = async (channel: 'web' | 'telegram', skipPreflight = false) => {
    if (!stopIntent) { setStopMsg('⛔ no active stop intent — click REQUEST LIVE STOP first'); return }
    if (!skipPreflight) { await preflightAndConfirm(channel); return }
    setStopBusy(true); setStopMsg(channel === 'web' ? 'confirming by ticker…' : 'confirming by code…')
    try {
      const code = channel === 'web' ? stopTk.trim().toUpperCase() : stopCode.trim()
      const raw = await fetch('/api/v2/holdings/protective-stop/confirm', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ intent_id: stopIntent, channel, code }) }).then(x => x.json())
      const r = unwrapApi(raw)
      const oid = r?.broker_order_id ?? r?.order_id ?? r?.result?.broker_order_id
      const ostatus = r?.status ?? r?.order_status ?? r?.result?.status
      const submitted = ostatus === 'submitted' || ostatus === 'filled' || r?.submitted === true
      // TRUE submit success — a broker order id / submitted|filled status, and ok not explicitly false.
      if ((r?.stage === 'submit' || submitted || oid) && submitted && r?.ok !== false) {
        setStopDone(true)
        setStopMsg(stopOrder?.kind === 'MARKET'
          ? `✅ LIVE sell placed on Schwab · order #${oid ?? '—'} (${ostatus ?? 'submitted'})`
          : `✅ LIVE stop placed on Schwab · order #${oid ?? '—'} (${ostatus ?? 'submitted'})`)
      }
      // 2FA accepted, still waiting on the other channel
      else if (r?.stage === 'confirm' && r?.ok && r?.fully_approved === false) {
        setStopMsg('channel confirmed — waiting on the other factor')
      }
      // approval accepted but the broker submit did NOT confirm (e.g. Schwab token expired) — DO NOT claim
      // success; show the real cause (result.error) so the operator knows exactly what to fix.
      else if (r?.mode === 'blocked' || r?.broker_submitted === false) {
        setStopMsg(`⛔ ${internalBlockMessage(r) ?? apiReason(r)}`)
      }
      else if (r?.stage === 'submit' && (ostatus === 'error' || r?.ok === false)) {
        setStopMsg(`⛔ Schwab rejected the submitted order: ${apiReason(r)}`)
      }
      else if (r?.ok && r?.fully_approved === true && !oid && !submitted) {
        setStopMsg('✅ approval accepted, but submit result was not returned — refresh broker orders / stop monitor to verify before retrying')
      }
      else setStopMsg(`⛔ ${apiReason(r)}`)
    } catch (e: any) { setStopMsg('⛔ ' + e.message) } finally { setStopBusy(false) }
  }
  // FULL STOP MONITORING — the live broker stop now showing on this card, + cancel ("remove") control.
  const _stopReviewTip = stopReviewTooltip({
    advisoryAt: protectionRec?.at, advisoryModel: protectionRec?.model,
    priceAt: p.price_updated_at,
    brokerFetchedAt: effectiveBrokerStop?.fetched_at,
    brokerOrderId: effectiveBrokerStop?.order_id,
  })
  const [cancelBusy, setCancelBusy] = useState(false)
  const [cancelMsg, setCancelMsg] = useState('')
  const _cancelStop = async () => {
    if (!effectiveBrokerStop?.order_id) return
    if (!window.confirm(`Cancel the live ${effectiveBrokerStop.order_type} on ${p.symbol} (#${effectiveBrokerStop.order_id}) at the broker?`)) return
    setCancelBusy(true); setCancelMsg('cancelling…')
    try {
      const r = await fetch('/api/v2/holdings/protective-stop/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account: p.account, broker_order_id: effectiveBrokerStop.order_id, symbol: p.symbol }) }).then(x => x.json())
      if (r?.ok) setCancelMsg(`✅ cancel sent (${r.status}) — refreshing…`)
      else setCancelMsg(`⛔ ${r?.error ?? r?.hint ?? 'cancel failed'}`)
    } catch (e: any) { setCancelMsg('⛔ ' + e.message) } finally { setCancelBusy(false) }
  }
  // MODIFY = cancel the existing stop + place a new one at the current advised level, in one 2FA step.
  const _openModify = () => {
    if (!effectiveBrokerStop) return
    const rec: any = effectiveProtectionRec || {}
    const advStop = Number(rec.stop_price) || (Number(effectiveBrokerStop.stop_price) || null)
    const recPrice = Number(rec.price) || (Number(p.current_price) || null)
    const off = rec.trail_recommended ? Number(rec.trail_offset) : null
    const isTrail = !!rec.trail_recommended || String(effectiveBrokerStop.order_type || '').includes('TRAILING')
    const trailPct = off == null ? null : rec.trail_type === 'PERCENT' ? off : (recPrice ? off / recPrice * 100 : null)
    const kind = isTrail && trailPct != null ? 'TRAILING' : 'STOP'
    const label = kind === 'TRAILING'
      ? `MODIFY → SELL ${p.shares} ${p.symbol} TRAILING STOP ${trailPct?.toFixed(0)}% GTC`
      : `MODIFY → SELL ${p.shares} ${p.symbol} STOP $${(advStop ?? 0).toFixed(2)} GTC`
    _resetStop()
    setStopOrder({ kind, qty: p.shares, stop: advStop, trailPct: kind === 'TRAILING' ? trailPct : null, label, advised: advStop, cur: recPrice, replace_order_id: effectiveBrokerStop.order_id })
  }

  return <div style={{ background: 'linear-gradient(180deg, rgba(30,41,59,.72), rgba(15,23,42,.74))', border: '1px solid rgba(148,163,184,.20)', borderLeft: `5px solid ${border}`, borderRadius: 14, padding: 16, boxShadow: '0 10px 28px rgba(0,0,0,.18)' }}>
    {/* ── Protective-stop confirmation modal: shows the EXACT proposed order + 2FA (type ticker, then
        confirm via Telegram/email/code — any one). Schwab submits via API; Fidelity returns a ToS ticket. ── */}
    {stopOrder && (() => {
      const tkOk = stopTk.trim().toUpperCase() === String(p.symbol).toUpperCase()
      const codeOk = /^\d{6}$/.test(stopCode.trim())
      const acctLbl = String(p.account ?? '').replace(/_/g, ' ').toUpperCase()
      const route = _isSchwab ? 'Submits LIVE to Schwab via API (per-order 2FA)' : 'No API on this account → builds a thinkorswim ticket to place manually'
      const inApprove = !!stopIntent && !stopDone
      const isMarketSell = stopOrder.kind === 'MARKET'
      const orderTif = isMarketSell ? _sellAllTif : 'GTC'
      return <div onClick={() => !stopBusy && _resetStop()} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.72)', zIndex: 80, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 12 }}>
        <div onClick={e => e.stopPropagation()} style={{ background: '#0f172a', border: `1px solid ${isMarketSell ? RED : AMBER}`, borderRadius: 12, padding: 18, width: 'min(440px,94vw)' }}>
          <div style={{ fontSize: 13, fontWeight: 900, color: isMarketSell ? RED : AMBER }}>{inApprove ? '🔐 Approve to place LIVE' : isMarketSell ? '⚠ Confirm market sell-all' : '⚠ Confirm protective stop'}</div>
          <div style={{ marginTop: 10, padding: 11, background: isMarketSell ? 'rgba(239,68,68,.10)' : 'rgba(245,158,11,.10)', border: `1px solid ${isMarketSell ? 'rgba(239,68,68,.3)' : 'rgba(245,158,11,.3)'}`, borderRadius: 8 }}>
            <div style={{ fontSize: 15, fontWeight: 950, color: TEXT0, ...({ fontFamily: 'monospace' } as any) }}>{stopOrder.label}</div>
            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 7, fontSize: 11 }}>
              <span style={{ color: MUTED }}>Qty <b style={{ color: TEXT0 }}>{stopOrder.qty}</b></span>
              <span style={{ color: MUTED }}>Type <b style={{ color: TEXT0 }}>{isMarketSell ? 'MARKET' : stopOrder.kind === 'TRAILING' ? `TRAILING ${stopOrder.trailPct?.toFixed(0)}%` : stopOrder.kind}</b></span>
              {!isMarketSell && stopOrder.stop != null && <span style={{ color: MUTED }}>{stopOrder.kind === 'TRAILING' ? 'Start' : 'Stop'} <b style={{ color: TEXT0 }}>${Number(stopOrder.stop).toFixed(2)}</b></span>}
              <span style={{ color: MUTED }}>TIF <b style={{ color: TEXT0 }}>{orderTif}</b></span>
            </div>
            <div style={{ fontSize: 10, color: MUTED, marginTop: 6 }}>Account <b style={{ color: TEXT1 }}>{acctLbl}</b> · {route}</div>
          </div>

          {/* SCHWAB TOKEN HEALTH — re-auth needed banner (shown UP FRONT, before any order attempt) */}
          {_needsReauth && !stopDone && <div style={{ marginTop: 10, padding: 11, background: 'rgba(239,68,68,.12)', border: `1px solid ${RED}`, borderRadius: 8 }}>
            <div style={{ fontSize: 11.5, fontWeight: 900, color: RED }}>⚠ Schwab re-auth needed — orders will be rejected</div>
            <div style={{ fontSize: 10, color: TEXT2, marginTop: 5, lineHeight: 1.45 }}>{tokenHealth?.message || 'Schwab login expired/revoked.'} The refresh token must be renewed by a manual browser login before any live order can submit. Run:</div>
            <div style={{ marginTop: 6, padding: '6px 8px', borderRadius: 6, background: '#1e293b', color: TEXT0, fontSize: 11, ...({ fontFamily: 'monospace' } as any) }}>{tokenHealth?.reauth_command || 'python3 scripts/schwab_token_manager.py reauth-url schwab_taxable'}</div>
          </div>}

          {/* DONE */}
          {stopDone && <div style={{ fontSize: 12, color: '#22c55e', marginTop: 12, fontWeight: 700 }}>{stopMsg}</div>}

          {/* TICKET MODE (no API on this account) */}
          {!stopDone && stopTicket && <div style={{ marginTop: 11 }}>
            <div style={{ fontSize: 10.5, color: TEXT2 }}>Place this exact order in thinkorswim → Monitor → working orders:</div>
            <div style={{ marginTop: 6, padding: '8px 10px', borderRadius: 6, background: '#1e293b', color: TEXT0, fontSize: 13, ...({ fontFamily: 'monospace' } as any) }}>{stopTicket}</div>
          </div>}

          {/* APPROVE PHASE (Schwab live) — EITHER channel: type ticker OR enter code from Telegram/email */}
          {!stopDone && inApprove && <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 10.5, color: TEXT2 }}>A one-time code was sent to <b style={{ color: TEXT1 }}>Telegram + email</b>. Approve by <b style={{ color: TEXT0 }}>either</b>:</div>
            <div style={{ fontSize: 10, color: MUTED, marginTop: 9 }}>① type the ticker <b style={{ color: TEXT0 }}>{p.symbol}</b></div>
            <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
              <input autoFocus value={stopTk} onChange={e => setStopTk(e.target.value.toUpperCase())} placeholder={`type ${p.symbol}`}
                style={{ flex: 1, fontSize: 14, padding: '8px 10px', borderRadius: 6, border: `1px solid ${tkOk ? '#22c55e' : 'rgba(148,163,184,.3)'}`, background: '#1e293b', color: TEXT0 }} />
              <button onClick={() => _confirmStop('web')} disabled={stopBusy || !tkOk} style={{ fontSize: 11, fontWeight: 800, padding: '7px 12px', borderRadius: 6, border: 'none', cursor: (stopBusy || !tkOk) ? 'not-allowed' : 'pointer', background: tkOk ? '#b45309' : '#334155', color: tkOk ? '#fff' : '#64748b', whiteSpace: 'nowrap' }}>approve + submit</button>
            </div>
            <div style={{ fontSize: 10, color: MUTED, marginTop: 10 }}>② or enter the 6-digit code (Telegram / email)</div>
            <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
              <input value={stopCode} onChange={e => setStopCode(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="6-digit code" inputMode="numeric"
                style={{ flex: 1, fontSize: 14, padding: '8px 10px', borderRadius: 6, border: `1px solid ${codeOk ? '#22c55e' : 'rgba(148,163,184,.3)'}`, background: '#1e293b', color: TEXT0, letterSpacing: 3, ...({ fontFamily: 'monospace' } as any) }} />
              <button onClick={() => _confirmStop('telegram')} disabled={stopBusy || !codeOk} style={{ fontSize: 11, fontWeight: 800, padding: '7px 12px', borderRadius: 6, border: 'none', cursor: (stopBusy || !codeOk) ? 'not-allowed' : 'pointer', background: codeOk ? '#b45309' : '#334155', color: codeOk ? '#fff' : '#64748b', whiteSpace: 'nowrap' }}>approve + submit</button>
            </div>
            <div style={{ fontSize: 9.5, color: DIM, marginTop: 8, fontStyle: 'italic' }}>This still requires this typed ticker or 6-digit code. No agent bypass.</div>
            <div style={{ fontSize: 9.5, color: MUTED, marginTop: 4 }}>You can also tap ✅ Approve in the Telegram message. Any one is enough.</div>
          </div>}

          {/* REVIEW PHASE — request the order (Schwab requests 2FA; no-API accounts return a ticket) */}
          {!stopDone && !inApprove && !stopTicket && <div style={{ fontSize: 10.5, color: TEXT2, marginTop: 11 }}>
            {_isSchwab
              ? (isMarketSell
                ? `Market sell-all of the full ${_shares} sh (fractional OK). Approval goes to Telegram + email; order submits only after you confirm.`
                : 'Requesting will send a one-time approval to Telegram + email; the order is placed only after you confirm (next step).')
              : 'This account has no trading API — you’ll get the exact ToS ticket to place manually.'}
          </div>}

          {pendingAction && preflightDiff && (
            <PreflightChangedPanel
              diff={preflightDiff}
              busy={stopBusy}
              validating={validating}
              onProceed={() => {
                const pa = pendingAction
                setPendingAction(null); setPreflightDiff(null)
                if (pa?.kind === 'request') _requestStop(true)
                else if (pa?.kind === 'confirm') _confirmStop(pa.channel, true)
              }}
              onCancel={() => { setPendingAction(null); setPreflightDiff(null); setStopMsg('') }}
            />
          )}

          <div style={{ display: 'flex', gap: 8, marginTop: 13, justifyContent: 'flex-end', alignItems: 'center' }}>
            {stopMsg && !stopDone && <span style={{ fontSize: 10, flex: 1, color: stopMsg.startsWith('✅') ? '#22c55e' : stopMsg.startsWith('⛔') ? '#ef4444' : MUTED }}>{stopMsg}</span>}
            <button onClick={_resetStop} disabled={stopBusy || validating} style={{ fontSize: 11, padding: '7px 12px', borderRadius: 6, border: '1px solid rgba(148,163,184,.3)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>{stopDone ? 'close' : 'cancel'}</button>
            {!stopDone && !inApprove && !stopTicket && <button onClick={preflightAndRequest} disabled={stopBusy || validating || _needsReauth} title={_needsReauth ? 'Schwab re-auth required before placing a live order' : undefined} style={{ fontSize: 12, fontWeight: 800, padding: '7px 18px', borderRadius: 6, border: 'none', cursor: (stopBusy || validating || _needsReauth) ? 'not-allowed' : 'pointer', background: _needsReauth ? '#334155' : isMarketSell ? RED : '#b45309', color: _needsReauth ? '#64748b' : '#fff' }}>{validating ? 'Validating…' : stopBusy ? '…' : _needsReauth ? 'RE-AUTH NEEDED' : _isSchwab ? (isMarketSell ? 'Request Schwab sell via 2FA' : 'Request Schwab stop via 2FA') : 'Create Fidelity manual ticket'}</button>}
          </div>
        </div>
      </div>
    })()}
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: 20, fontWeight: 950, color: TEXT0 }}>{p.symbol}</span>
          <ProAnalystPill symbol={p.symbol} map={paMap} compact />
          <span style={{ fontSize: 11, color: MUTED }}>{p.shares} sh · {p.hold_duration ?? '—'}</span>
        </div>
        {symCard?.description && <div style={{ fontSize: 11.5, color: TEXT2, marginTop: 5, lineHeight: 1.42 }}>{symCard.description}{symCard.vs_sector_week != null && <span style={{ marginLeft: 6, fontWeight: 850, color: symCard.vs_sector_week >= 0 ? GREEN : RED }}>{symCard.vs_sector_week >= 0 ? '+' : ''}{symCard.vs_sector_week}% vs sector</span>}</div>}
      </div>
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        {p.watchlist_state === 'directive' && <span style={chip('rgba(168,85,247,.20)', PURPLE, true)}>★ directive</span>}
        {p.watchlist_state === 'watchlist' && <span style={chip('rgba(96,165,250,.16)', BLUE, true)}>watchlist</span>}
        <span title={`${p.broker}/${p.environment}`} style={chip(paper ? 'rgba(96,165,250,.18)' : 'rgba(255,167,38,.18)', paper ? BLUE : '#ffa726', true)}>{paper ? 'PAPER' : 'REAL'} · {String(p.account ?? '?').replace(/_/g, ' ').toUpperCase()}</span>
        <span style={chip(`${border}22`, border, true)}>{priority.toUpperCase()}</span>
        <span style={chip(p.protection_state === 'protected' ? 'rgba(34,197,94,.16)' : p.protection_state === 'partial' ? 'rgba(245,158,11,.16)' : 'rgba(239,68,68,.16)', p.protection_state === 'protected' ? GREEN : p.protection_state === 'partial' ? AMBER : RED, true)}>{p.protection_state}</span>
      </div>
    </div>

    <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 10, background: `${border}14`, border: `1px solid ${border}55` }}>
      <div style={{ fontSize: 14, fontWeight: 950, color: border }}>{p.operator_decision ?? 'No action — monitored'}</div>
      <div style={{ fontSize: 11, color: TEXT2, marginTop: 3, lineHeight: 1.45 }}>{p.decision_reason}</div>
      {p.primary_next_review && <div style={{ fontSize: 10, color: MUTED, marginTop: 4 }}>Next: {p.primary_next_review}</div>}
    </div>

    <ScaleControl p={p} />

    {(effectiveBrokerStop || effectiveProtectionRec || Object.keys(lanes).length > 0) && <div style={{ marginTop: 10, padding: '10px 12px', borderRadius: 10, background: 'rgba(168,85,247,.08)', border: '1px solid rgba(168,85,247,.28)' }}>
      {/* FULL STOP MONITORING — a LIVE protective stop is working at the broker (source of truth). */}
      {effectiveBrokerStop && <div title={_stopReviewTip} style={{ marginBottom: effectiveProtectionRec ? 10 : 0, padding: '8px 10px', borderRadius: 8, background: 'rgba(34,197,94,.10)', border: '1px solid rgba(34,197,94,.35)', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', cursor: 'help' }}>
        <span style={{ fontSize: 11, fontWeight: 950, color: '#22c55e' }}>✓ PROTECTED — live stop at broker{effectiveBrokerStop.fetched_at ? ` · read ${formatReviewStamp(effectiveBrokerStop.fetched_at)}` : ''}</span>
        <span style={{ fontSize: 10.5, color: TEXT1, ...({ fontFamily: 'monospace' } as any) }}>SELL {effectiveBrokerStop.qty ?? p.shares} {p.symbol} {String(effectiveBrokerStop.order_type || '').replace('_', ' ')} {effectiveBrokerStop.stop_price != null ? `$${Number(effectiveBrokerStop.stop_price).toFixed(2)}` : effectiveBrokerStop.trail_offset != null ? (effectiveBrokerStop.trail_link === 'PERCENT' ? `${effectiveBrokerStop.trail_offset}%` : `$${effectiveBrokerStop.trail_offset}`) : ''} GTC</span>
        <span style={{ fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 4, background: 'rgba(34,197,94,.18)', color: '#22c55e' }}>{String(effectiveBrokerStop.status || 'working')}</span>
        <span style={{ fontSize: 9, color: MUTED }}>#{effectiveBrokerStop.order_id}</span>
        <span style={{ flex: 1 }} />
        {cancelMsg && <span style={{ fontSize: 9.5, color: cancelMsg.startsWith('✅') ? '#22c55e' : cancelMsg.startsWith('⛔') ? '#ef4444' : MUTED }}>{cancelMsg}</span>}
        <button onClick={_openModify} disabled={cancelBusy} title="Cancel this stop + place a new one at the current advised level — one 2FA. Use after the price moves up." style={{ fontSize: 9.5, fontWeight: 800, padding: '4px 10px', borderRadius: 6, border: `1px solid ${AMBER}`, background: 'rgba(245,158,11,.12)', color: AMBER, cursor: cancelBusy ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>Modify</button>
        <button onClick={_cancelStop} disabled={cancelBusy} title="Cancel this live protective stop at the broker (safe direction; no 2FA)" style={{ fontSize: 9.5, fontWeight: 800, padding: '4px 10px', borderRadius: 6, border: '1px solid #ef4444', background: 'rgba(239,68,68,.12)', color: '#ef4444', cursor: cancelBusy ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>{cancelBusy ? '…' : 'Cancel stop'}</button>
      </div>}
      {/* COVERAGE MISMATCH — a standalone GTC stop does NOT auto-resize when you trim/add. Warn so the
          operator cancels + re-places sized to the shares held now. */}
      {effectiveBrokerStop && effectiveBrokerStop.coverage === 'oversized' && <div style={{ marginBottom: effectiveProtectionRec ? 10 : 0, padding: '6px 9px', borderRadius: 7, background: 'rgba(239,68,68,.12)', border: '1px solid rgba(239,68,68,.4)', fontSize: 10, fontWeight: 800, color: '#f87171' }}>
        ⚠ OVERSIZED — stop covers {effectiveBrokerStop.qty} sh but you hold {effectiveBrokerStop.held_qty}. On trigger it may short the extra {Number(effectiveBrokerStop.qty) - Number(effectiveBrokerStop.held_qty)} (margin) or reject (cash). Cancel & re-place at {effectiveBrokerStop.held_qty} sh.
      </div>}
      {effectiveBrokerStop && effectiveBrokerStop.coverage === 'partial' && <div style={{ marginBottom: effectiveProtectionRec ? 10 : 0, padding: '6px 9px', borderRadius: 7, background: 'rgba(245,158,11,.12)', border: '1px solid rgba(245,158,11,.4)', fontSize: 10, fontWeight: 800, color: AMBER }}>
        ⚠ PARTIAL — stop covers only {effectiveBrokerStop.qty} of {effectiveBrokerStop.held_qty} sh held. {Number(effectiveBrokerStop.held_qty) - Number(effectiveBrokerStop.qty)} sh are unprotected. Re-place at {effectiveBrokerStop.held_qty} sh for full cover.
      </div>}
      {effectiveProtectionRec && (() => {
        const price = Number(effectiveProtectionRec.price) || null, stop = Number(effectiveProtectionRec.stop_price) || null, dist = effectiveProtectionRec.stop_distance_pct
        const off = effectiveProtectionRec.trail_recommended ? Number(effectiveProtectionRec.trail_offset) : null, isPct = effectiveProtectionRec.trail_type === 'PERCENT'
        const trailDollar = off == null ? null : isPct ? (price ? price * off / 100 : null) : off
        const trailPct = off == null ? null : isPct ? off : (price ? off / price * 100 : null)
        const distColor = dist == null ? MUTED : dist < 0 ? RED : dist < 2 ? RED : dist < 5 ? AMBER : GREEN
        const unprotected = p.protection_state !== 'protected'
        const mf = (p as any).is_unstoppable_fund ?? (p as any).is_mutual_fund   // fund (mutual/401k): no exchange stop possible
        const income = (p as any).holding_family === 'income'  // held for yield — protective stop optional
        const lockBtn = { fontSize: 9.5, fontWeight: 800, padding: '4px 9px', borderRadius: 6, border: '1px dashed #64748b', background: 'rgba(100,116,139,.12)', color: MUTED, cursor: 'not-allowed', whiteSpace: 'nowrap' as const }
        const STAGE2C_TIP = 'Protective stops on real holdings (Stage 2c). Schwab taxable submits LIVE via API after per-order 2FA (type the ticker OR a code sent to Telegram + email — either confirms); the pilot must be ARMED. Accounts with no API (IRAs / Fidelity-401k) return an exact thinkorswim ticket to place manually. POC envelope is committed (DRS, taxable, sub-$1k) until the proof passes.'
        return <>
          <div title={`${_stopReviewTip}\n\n${effectiveProtectionRec.rationale ?? ''} · confidence ${effectiveProtectionRec.confidence ?? '—'}`} style={{ display: 'flex', gap: 9, flexWrap: 'wrap', alignItems: 'baseline' }}>
            <span style={{ fontSize: 12, fontWeight: 950, color: '#d8b4fe' }}>Protection advisory</span>
            {effectiveProtectionRec.family && <span style={chip('rgba(96,165,250,.14)', BLUE)}>{effectiveProtectionRec.family}</span>}
            {stop != null && <span style={{ fontSize: 11, fontWeight: 850, color: TEXT1 }}>{mf ? 'ref level' : 'stop'} <b style={{ color: '#d8b4fe' }}>${stop.toFixed(2)}</b></span>}
            {off != null ? <span style={{ fontSize: 11, fontWeight: 850, color: TEXT1 }}>trail <b style={{ color: BLUE }}>{trailDollar != null ? `$${trailDollar.toFixed(2)}` : '—'}</b>{trailPct != null && <span style={{ color: MUTED, fontWeight: 500 }}> ({trailPct.toFixed(1)}%)</span>}</span> : <span style={{ fontSize: 10, color: MUTED }}>no trail yet</span>}
            {dist != null && <span style={{ fontSize: 10, fontWeight: 900, color: distColor }}>{dist < 0 ? 'price BELOW stop' : `price ${dist.toFixed(1)}% above stop`}</span>}
          </div>
          {/* concrete advised action (replaces the vague "review protection") + Stage-2c-locked order buttons.
              Two axes the buttons make explicit: fixed-vs-trailing trigger, and market-vs-limit fill. */}
          {stop != null && unprotected && mf && (
            // Fund holding (mutual fund or 401k/proxy code): an exchange stop order cannot be placed
            // (transacts at NAV / inside the plan). Show the level as REFERENCE only — no order buttons.
            <div style={{ marginTop: 8, padding: '7px 9px', borderRadius: 8, background: 'rgba(100,116,139,.12)', border: '1px solid rgba(100,116,139,.30)' }}>
              <span style={{ fontSize: 10.5, fontWeight: 900, color: MUTED }}>▸ Fund holding — no exchange stop can be placed (trades at NAV / inside the plan). Protect via tax-aware <b style={{ color: TEXT1 }}>trim / rebalance</b>; ${stop.toFixed(2)} is a reference level only.</span>
            </div>
          )}
          {stop != null && unprotected && !mf && (() => {
            const trailRes = resolvedTrailPct(effectiveProtectionRec)
            const effectiveTrailPct = trailRes?.pct ?? ((off != null && trailPct != null) ? trailPct : null)
            const trailReady = effectiveTrailPct != null && stop != null
            const stopTip = `Queue a FIXED sell stop (stop-market) GTC at $${stop.toFixed(2)}. If the price falls to $${stop.toFixed(2)} a MARKET sell fires — it ALWAYS fills, but the fill can slip below $${stop.toFixed(2)} in a fast drop. The trigger does NOT move.\n\n${STAGE2C_TIP}`
            const limitTip = `Queue a FIXED sell stop-limit GTC triggering at $${stop.toFixed(2)}. If the price hits $${stop.toFixed(2)} a LIMIT sell (~$${stop.toFixed(2)}) fires — it avoids a bad fill, but may NOT fill if the price gaps straight through, leaving you unprotected on the way down. The trigger does NOT move.\n\n${STAGE2C_TIP}`
            const trailTip = trailReady ? `Queue a native TRAILING sell stop GTC, trailing ${effectiveTrailPct!.toFixed(0)}%${trailDollar != null ? ` (≈$${trailDollar.toFixed(2)})` : ''}. The stop starts near $${stop.toFixed(2)} and RATCHETS UP as the price rises (never down), locking in profit; if the price then falls ${effectiveTrailPct!.toFixed(0)}% from its high a MARKET sell fires.${off == null ? ' (optional trail — advisor recommended fixed only)' : ''}\n\n${STAGE2C_TIP}` : ''
            const modifyTip = `Modify an ACTIVE stop — change the stop price, the trail %, or switch order type — once a protective order is already working at the broker.\n\n${STAGE2C_TIP}`
            const actBtn = { ...lockBtn, cursor: 'pointer', border: '1px solid #64748b', color: TEXT1 }
            const recBtn = { ...lockBtn, cursor: 'pointer', border: `1px solid ${AMBER}`, background: 'rgba(245,158,11,.18)', color: AMBER }
            // Income holdings are held for yield — frame the level as OPTIONAL, not "ADVISED".
            const headColor = income ? BLUE : AMBER
            const orderTxt = trailReady ? `SELL TRAILING STOP, trail ${effectiveTrailPct!.toFixed(0)}% (starts ~$${stop.toFixed(2)})` : `SELL STOP $${stop.toFixed(2)}`
            const head = income ? `▸ OPTIONAL stop (income hold): ${orderTxt} GTC` : `▸ ADVISED: ${orderTxt} GTC`
            const qty = p.shares
            const open = (kind: string, label: string) => () => { _resetStop(); setStopOrder({ kind, qty, stop, trailPct: kind === 'TRAILING' ? effectiveTrailPct : null, income, label, advised: stop, cur: price ?? (Number(p.current_price) || null) }) }
            return <div style={{ marginTop: 8, padding: '7px 9px', borderRadius: 8, background: income ? 'rgba(96,165,250,.10)' : 'rgba(245,158,11,.10)', border: `1px solid ${income ? 'rgba(96,165,250,.32)' : 'rgba(245,158,11,.32)'}`, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 10.5, fontWeight: 950, color: headColor }}>{head}</span>
              <span style={{ flex: 1 }} />
              <button onClick={open('STOP', `SELL ${qty} ${p.symbol} STOP $${stop.toFixed(2)} GTC`)} title={stopTip} style={trailReady ? actBtn : recBtn}>Queue stop (fixed){trailReady ? '' : ' ★'}</button>
              <button onClick={open('STOP_LIMIT', `SELL ${qty} ${p.symbol} STOP-LIMIT $${stop.toFixed(2)} GTC`)} title={limitTip} style={actBtn}>Queue stop-limit (fixed)</button>
              {trailReady && <button onClick={open('TRAILING', `SELL ${qty} ${p.symbol} TRAILING STOP ${effectiveTrailPct!.toFixed(0)}% GTC`)} title={trailTip} style={recBtn}>Queue trailing stop ★</button>}
              <button onClick={_snoozeStop} disabled={snoozeBusy} title="Acknowledge this stop and grant a 1-week grace period — suppresses the stop ALERT for 7 days. Advisory only: does NOT change or cancel the protective stop at the broker." style={{ fontSize: 10.5, fontWeight: 800, padding: '6px 11px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: MUTED, cursor: snoozeBusy ? 'not-allowed' : 'pointer' }}>{snoozeBusy ? '…' : '⏸ Ignore 1 week'}</button>
            </div>
          })()}
          {/* FRACTIONAL position: a broker STOP covers only whole shares (Schwab rejects fractional stops). Offer a
              synthetic stop that protects the FULL position via a monitored Market-Day sell-all on breach. */}
          {_isFractional && stop != null && unprotected && !mf && (
            <div style={{ marginTop: 8, padding: '7px 9px', borderRadius: 8, background: 'rgba(168,85,247,.10)', border: '1px solid rgba(168,85,247,.32)' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{ fontSize: 10.5, fontWeight: 900, color: '#d8b4fe' }}>▸ Fractional ({_shares} sh) — broker stop covers only {Math.floor(_shares)} whole share{Math.floor(_shares) === 1 ? '' : 's'}. Synthetic stop or market sell-all covers all {_shares}.</span>
                <span style={{ flex: 1 }} />
                {_needsSellAll && (
                  <button onClick={_openSellAll} disabled={stopBusy || _needsReauth || stopDone} title={_needsReauth ? 'Schwab re-auth required' : `Market sell ALL ${_shares} sh · ${_sellAllTif} · per-order 2FA before live submit`}
                    style={{ fontSize: 10.5, fontWeight: 900, padding: '6px 11px', borderRadius: 6, border: '1px solid #ef4444', background: 'rgba(239,68,68,.16)', color: RED, cursor: (stopBusy || _needsReauth) ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>
                    {stopDone ? '✓ Submitted' : `Sell all @ MKT ${_sellAllTif}`}
                  </button>
                )}
                <button onClick={() => _armSynthetic(stop)} disabled={synthBusy} title={`Arm a synthetic stop at $${stop.toFixed(2)} on the FULL ${_shares} sh. The monitor watches the price; on a breach it requests a Market-Day sell-all 2FA (Schwab accepts market sells of fractional qty). Nothing is placed at the broker now.`} style={{ fontSize: 10.5, fontWeight: 800, padding: '6px 11px', borderRadius: 6, border: '1px solid #a855f7', background: 'rgba(168,85,247,.18)', color: '#d8b4fe', cursor: synthBusy ? 'not-allowed' : 'pointer' }}>{synthBusy ? '…' : `Arm synthetic stop @ $${stop.toFixed(2)}`}</button>
              </div>
              {_isFractional && <div style={{ fontSize: 8.5, color: MUTED, marginTop: 5, lineHeight: 1.4 }}>Schwab fractional market orders use DAY (not GTC). Use Sell all @ MKT for immediate exit; use synthetic stop for monitored protection.</div>}
            </div>
          )}
          {synthMsg && <div style={{ fontSize: 10.5, color: synthMsg.startsWith('✓') ? GREEN : '#ef4444', marginTop: 5 }}>{synthMsg}</div>}
          {snoozeMsg && <div style={{ fontSize: 10.5, color: snoozeMsg.startsWith('✓') ? GREEN : AMBER, marginTop: 5 }}>{snoozeMsg}</div>}
        </>
      })()}
      {effectiveProtectionRec?.rationale && <div style={{ fontSize: 10.5, color: TEXT2, marginTop: 5, lineHeight: 1.45 }}>{effectiveProtectionRec.rationale}</div>}
      <div style={{ display: 'flex', gap: 5, marginTop: 6, alignItems: 'center', flexWrap: 'wrap' }}><span style={{ fontSize: 9, color: MUTED }}>reviewed by:</span>{Object.keys(lanes).length === 0 && <span style={{ fontSize: 9, color: MUTED }}>no LLM review in 30d</span>}{Object.entries(lanes).map(([lane, c]: any) => { const m = LANE_META[lane]; return <span key={lane} title={`${c.model} · analyzed ${String(c.last_at).slice(0, 10)} · ${c.n} review${c.n > 1 ? 's' : ''}`} style={{ fontSize: 8.5, fontWeight: 900, padding: '2px 6px', borderRadius: 4, background: m.c + '22', color: m.c, border: `1px solid ${m.c}55` }}>{m.label}</span> })}</div>
    </div>}

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(95px,1fr))', gap: 8, marginTop: 10 }}>
      <Metric label="P&L" value={p.unrealized_pnl != null ? fmt$(p.unrealized_pnl) : fmt$(p.market_value ?? 0)} color={p.unrealized_pnl != null ? pnlColor : TEXT0} />
      <Metric label="P&L %" value={pct(p.unrealized_pnl_pct)} color={(p.unrealized_pnl_pct ?? 0) >= 0 ? GREEN : RED} />
      <Metric label="Today" value={pct(p.today_move_pct)} color={(p.today_move_pct ?? 0) >= 0 ? GREEN : RED} />
      <Metric label="Market Value" value={fmt$(p.market_value ?? 0, 0)} color={TEXT0} />
      <Metric label="Basis" value={basis} color={BASIS_C[p.basis_quality] || TEXT2} />
      <Metric label="Now" value={num(p.current_price)} color={TEXT0} />
      <Metric label="Stop" title={_stopReviewTip || (p.stop_price == null && _advStop != null ? 'Advised stop (no protective stop placed at the broker yet)' : undefined)}
        value={p.stop_price != null ? num(p.stop_price) : _advStop != null ? `${num(_advStop)}*` : '—'}
        color={p.stop_price != null ? RED : _advStop != null ? AMBER : MUTED} />
      <Metric label="R multiple"
        title={_rAdvisory != null ? 'Advisory R: current P&L ÷ risk to the ADVISED stop (this holding has no strategy-tracked entry/stop, so R is computed against the Hermes advised stop)' : _rShow == null ? 'No R — needs a basis (entry) and an advised stop below entry; funds/unverified-basis positions stay blank' : undefined}
        value={_rShow != null ? `${_rAdvisory != null ? '~' : ''}${num(_rShow, 1)}R` : '—'}
        color={_rShow == null ? MUTED : _rShow >= 1 ? GREEN : _rShow >= 0 ? AMBER : RED} />
      {(() => {
        // % from stop — live cushion above the placed (or advised) stop. The monitor field: as it
        // shrinks toward 0% the stop is about to trigger. Uses the placed stop if present, else advised.
        const _s = p.stop_price != null ? Number(p.stop_price) : _advStop
        const _n = Number(p.current_price) || null
        const _d = (_s && _n) ? ((_n - _s) / _n) * 100 : null
        return <Metric label="% from stop"
          title={_d == null ? 'No stop reference yet (no placed/advised stop, or no price)' : `Current price is ${_d.toFixed(1)}% above the ${p.stop_price != null ? 'placed' : 'advised'} stop ($${Number(_s).toFixed(2)}) — your downside cushion. Watch this: <3% means the stop is close to triggering.`}
          value={_d == null ? '—' : `${_d >= 0 ? '+' : ''}${_d.toFixed(1)}%`}
          color={_d == null ? MUTED : _d < 3 ? RED : _d < 8 ? AMBER : GREEN} />
      })()}
    </div>

    <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 10 }}>
      <span style={chip('rgba(15,23,42,.55)', TEXT1)}>{p.strategy ?? 'unclassified'}</span>
      <span style={chip('rgba(15,23,42,.55)', RSI_C(t.rsi_bucket))}>RSI {t.rsi != null ? num(t.rsi, 0) : '—'} {t.rsi_bucket}</span>
      <span style={chip('rgba(15,23,42,.55)', t.trend_label === 'bullish' ? GREEN : t.trend_label === 'bearish' ? RED : TEXT2)}>{t.trend_label}</span>
      {sr.sector && <span style={chip('rgba(15,23,42,.55)', (sr.vs_sector_5d ?? 0) > 1 ? GREEN : (sr.vs_sector_5d ?? 0) < -1 ? RED : TEXT2)}>{sr.sector}{sr.sector_etf ? ` (${sr.sector_etf})` : ''}</span>}
      <span style={chip('rgba(15,23,42,.55)', FRESH_C[p.data_freshness])}>data {p.data_freshness}</span>
      <span style={chip('rgba(15,23,42,.55)', FRESH_C[p.news_freshness])}>news {p.news_freshness}{p.latest_news_age_hours != null ? ` ${Math.round(p.latest_news_age_hours)}h` : ''}</span>
      {(p.risk_flags ?? []).map((r: string) => <span key={r} style={chip('rgba(239,68,68,.14)', RED)}>{r.replace(/_/g, ' ')}</span>)}
      {(p.opportunity_flags ?? []).map((o: string) => <span key={o} style={chip('rgba(34,197,94,.14)', GREEN)}>{o.replace(/_/g, ' ')}</span>)}
    </div>

    {p.analyst && (p.analyst.rating || p.analyst.target_mean != null) && <div style={{ fontSize: 10.5, color: TEXT2, marginTop: 8, lineHeight: 1.45 }}><b style={{ color: TEXT1 }}>Analysts:</b> {p.analyst.rating ? `${String(p.analyst.rating).toUpperCase()}${p.analyst.rating_mean != null ? ` (${Number(p.analyst.rating_mean).toFixed(1)})` : ''}` : 'no consensus'}{p.analyst.opinions != null && ` · ${p.analyst.opinions} opinions`}{p.analyst.target_mean != null && ` · target $${num(p.analyst.target_mean, 2)}`}{p.analyst.target_upside_pct != null && <span style={{ color: p.analyst.target_upside_pct > 0 ? GREEN : RED, fontWeight: 850 }}> ({p.analyst.target_upside_pct > 0 ? '+' : ''}{num(p.analyst.target_upside_pct, 1)}% to target)</span>}</div>}
    {p.earnings_date && (() => { const d = Math.ceil((new Date(String(p.earnings_date)).getTime() - Date.now()) / 86400000); return (
      <div style={{ fontSize: 10.5, color: d >= 0 && d <= 7 ? AMBER : TEXT2, marginTop: 6, fontWeight: d >= 0 && d <= 7 ? 800 : 400 }}>
        <b style={{ color: TEXT1 }}>Earnings:</b> {String(p.earnings_date).slice(0, 10)}{Number.isFinite(d) && d >= 0 ? ` (${d}d)` : ''}
      </div>
    ) })()}
    {p.strategy_rationale && <div style={{ fontSize: 10.5, color: MUTED, marginTop: 7, fontStyle: 'italic', lineHeight: 1.45 }}>Why <b style={{ color: TEXT2 }}>{p.strategy}</b>: {p.strategy_rationale}</div>}

    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 11, alignItems: 'center' }}>{(p.recommended_manual_actions ?? []).slice(0, 4).map((a: string) => <button key={a} onClick={() => onAction?.(a, p)} title="Operator review action only" style={{ fontSize: 10, padding: '4px 10px', borderRadius: 6, border: '1px solid rgba(148,163,184,.25)', background: 'rgba(15,23,42,.55)', color: TEXT2, cursor: 'pointer' }}>{a}</button>)}<span onClick={onToggle} style={{ fontSize: 10, color: MUTED, cursor: 'pointer', textDecoration: 'underline', marginLeft: 'auto' }}>{expanded ? 'less' : 'more'}</span><span onClick={() => onDrill({ title: `${p.symbol} — ${p.account}`, subtitle: `${p.strategy ?? ''} · ${p.broker}/${p.environment}`, endpoint: '/api/v2/open-trades/intelligence', rows: [p], subjectType: 'position', subjectKey: p.symbol })} style={{ fontSize: 10, color: BLUE, cursor: 'pointer', textDecoration: 'underline', fontWeight: 800 }}>drill</span></div>

    {expanded && <div style={{ marginTop: 10, borderTop: '1px solid rgba(148,163,184,.18)', paddingTop: 10 }}><div style={{ fontSize: 11, fontWeight: 900, color: TEXT1, marginBottom: 6 }}>News & catalysts</div>{news.length === 0 && <div style={{ fontSize: 10.5, color: MUTED }}>No recent research surfaced.</div>}{news.map((n: any, i: number) => { const stale = (n.age_hours ?? 0) > 48; return <div key={i} style={{ fontSize: 11, marginBottom: 7, opacity: stale ? 0.7 : 1, lineHeight: 1.45 }}><div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}><span style={chip('rgba(15,23,42,.55)', TEXT2)}>{n.source}</span>{n.age_hours != null && <span style={{ fontSize: 9.5, color: stale ? AMBER : MUTED }}>{Math.round(n.age_hours)}h{stale ? ' stale' : ''}</span>}</div>{n.url ? <a href={n.url} target="_blank" rel="noopener noreferrer" style={{ color: '#bfdbfe', textDecoration: 'none', display: 'block', marginTop: 3, fontWeight: 650 }}>{n.title || ''}</a> : <div style={{ color: TEXT2, marginTop: 3 }}>{n.title || ''}</div>}{n.why_it_matters && <div style={{ fontSize: 10.5, color: MUTED, marginTop: 3 }}><b style={{ color: TEXT2 }}>Why it matters:</b> {n.why_it_matters}</div>}</div> })}<div style={{ fontSize: 10, color: MUTED, marginTop: 6 }}>SMA50 {t.sma50_pct != null ? pct(t.sma50_pct) : '—'} · SMA200 {t.sma200_pct != null ? pct(t.sma200_pct) : '—'} · RVOL {t.rvol ?? '—'}{sr.sector ? ` · ${sr.sector} ${sr.label}` : ''}{p.last_hermes_review_at ? ` · Hermes ${String(p.last_hermes_review_at).slice(0, 10)}` : ''}</div></div>}
  </div>
}

// Mid-trade scale-IN / scale-OUT control (operator 2026-06-19). Web card only; both directions require
// a preview→confirm step. Broker-routed by the API: alpaca_paper = live paper, schwab_* = gated 2FA,
// fidelity_* = record-only. Scale-in is capped server-side at the percent-of-equity position headroom.
function ScaleControl({ p }: any) {
  const [qty, setQty] = useState('')
  const [preview, setPreview] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const held = Number(p.shares) || 0
  const acct = String(p.account ?? '').toLowerCase()
  const broker = acct.includes('alpaca') ? 'alpaca' : acct.startsWith('schwab') ? 'schwab' : acct.startsWith('fidelity') ? 'fidelity' : 'unknown'
  if (held <= 0 || broker === 'unknown') return null
  const brokerNote = broker === 'alpaca' ? 'live paper order' : broker === 'schwab' ? 'Schwab — gated 2FA (no live order yet)' : 'Fidelity — record-only (execute at broker)'

  const send = async (sign: number, confirm: boolean) => {
    const n = Math.abs(parseInt(qty || '0', 10))
    if (!n) { setMsg('enter a share count'); return }
    setBusy(true); setMsg('')
    try {
      const r = await fetch('/api/v2/paper-trades/scale', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account: p.account, symbol: p.symbol, delta_shares: sign * n, confirm })
      }).then(x => x.json())
      const d = r.data ?? r
      if (!confirm) {
        if (d.ok || d.preview || d.gated) setPreview({ ...d, sign, n })
        else { setMsg(d.error || 'preview failed'); setPreview(null) }
      } else {
        if (d.ok) setMsg(`✅ ${d.direction === 'scale_in' ? 'Added' : 'Trimmed'} ${d.applied ?? d.delta} ${p.symbol}${d.new_shares != null ? ` → ${d.new_shares} sh` : ''}${d.realized_pnl != null ? ` · P&L $${d.realized_pnl}` : ''}${d.stop ? ` · ${d.stop}` : ''}`)
        else if (d.gated) setMsg(`🔒 ${d.detail}`)
        else if (d.recorded) setMsg(`📝 ${d.detail}`)
        else setMsg(d.error || 'failed')
        setPreview(null); setQty('')
      }
    } catch (e: any) { setMsg(String(e).slice(0, 90)) } finally { setBusy(false) }
  }

  const inp = { width: 64, fontSize: 11, padding: '4px 7px', borderRadius: 6, border: '1px solid rgba(148,163,184,.3)', background: 'rgba(15,23,42,.55)', color: TEXT0 }
  const btn = (c: string) => ({ fontSize: 10.5, fontWeight: 800, padding: '4px 10px', borderRadius: 6, border: `1px solid ${c}`, background: `${c}1f`, color: c, cursor: busy ? 'not-allowed' as const : 'pointer' as const, whiteSpace: 'nowrap' as const })
  return <div style={{ marginTop: 10, padding: '9px 11px', borderRadius: 10, background: 'rgba(56,189,248,.07)', border: '1px solid rgba(56,189,248,.25)' }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <span style={{ fontSize: 11, fontWeight: 900, color: '#38bdf8' }}>Scale position</span>
      <span style={{ fontSize: 9.5, color: MUTED }}>held {held} sh · {brokerNote}</span>
      <span style={{ flex: 1 }} />
      <input style={inp} value={qty} onChange={e => setQty(e.target.value.replace(/[^0-9]/g, ''))} placeholder="shares" disabled={busy} />
      <button onClick={() => send(1, false)} disabled={busy} title="Add shares (capped at position headroom)" style={btn(GREEN)}>Scale in +</button>
      <button onClick={() => send(-1, false)} disabled={busy} title="Trim shares (partial close)" style={btn(AMBER)}>Scale out −</button>
    </div>
    {preview && <div style={{ marginTop: 9, padding: '8px 10px', borderRadius: 8, background: 'rgba(15,23,42,.6)', border: '1px solid rgba(148,163,184,.25)' }}>
      <div style={{ fontSize: 11, color: TEXT1, fontWeight: 700 }}>
        Confirm {preview.direction === 'scale_in' ? 'scale-IN' : 'scale-OUT'}: {preview.side?.toUpperCase()} {preview.delta_applied ?? preview.delta ?? preview.n} {p.symbol}
        {preview.price ? ` @ ~$${Number(preview.price).toFixed(2)}` : ''}{preview.new_shares != null ? ` → ${preview.new_shares} sh` : ''}
      </div>
      {preview.cap_note && <div style={{ fontSize: 10, color: AMBER, marginTop: 3 }}>⚠ {preview.cap_note}</div>}
      {preview.detail && <div style={{ fontSize: 10, color: MUTED, marginTop: 3 }}>{preview.detail}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <button onClick={() => send(preview.sign, true)} disabled={busy} style={btn(preview.gated ? '#a78bfa' : GREEN)}>{busy ? '…' : preview.gated ? 'Confirm (gated)' : 'Confirm'}</button>
        <button onClick={() => setPreview(null)} disabled={busy} style={btn(MUTED)}>Cancel</button>
      </div>
    </div>}
    {msg && <div style={{ fontSize: 10.5, marginTop: 7, color: msg.startsWith('✅') ? GREEN : msg.startsWith('🔒') || msg.startsWith('📝') ? '#a78bfa' : AMBER }}>{msg}</div>}
  </div>
}

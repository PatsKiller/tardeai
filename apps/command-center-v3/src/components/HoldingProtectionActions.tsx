import { useEffect, useRef, useState } from 'react'
import PreflightChangedPanel from './PreflightChangedPanel'
import { volTierTooltip } from './HoldingsTableView'
import { protectionExplain, resolvedTrailPct } from '../lib/protectionTrail'
import { fmtLiveStop, runProtectiveStopPreflight, unwrapApi, type PreflightDiff } from '../lib/protectiveStopPreflight'
import { buildStopLogic, hasLiveBrokerStopOrder, isTrailingBrokerStop, resolveLiveStop, type StopLogic, type StopOrderKind } from '../lib/stopManagement'
import { formatReviewStamp, stopReviewTooltip } from '../lib/stopReviewTooltip'

const MUTED = '#94a3b8', TEXT0 = '#f8fafc', GREEN = '#22c55e', AMBER = '#f59e0b', BLUE = '#60a5fa', PURPLE = '#a855f7', RED = '#ef4444'
const SCHWAB_SELL_ALL_MAX_SHARES = 40
const resolveSchwabAcct = (a: string) => a === 'schwab_roth' ? 'schwab_roth_ira' : a
const apiReason = (j: any) => j?.result?.error ?? j?.error ?? j?.reason ?? j?.message ?? 'request failed'
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

const BROKER_URL: Record<string, string> = {
  fidelity: 'https://digital.fidelity.com/ftgw/digital/portfolio/summary',
  schwab: 'https://www.schwab.com/client-home',
}

export default function HoldingProtectionActions({ h, pr, monitored, confirmedStop, brokerStopsFetchedAt, brokerStopReadOk, autoStageKind, onRefresh, onPreflightUpdate }: {
  h: any; pr: any; monitored?: any; confirmedStop?: any; brokerStopsFetchedAt?: string | null; brokerStopReadOk?: string[]
  autoStageKind?: 'STOP' | 'TRAILING' | null
  onRefresh?: () => void
  onPreflightUpdate?: (symbol: string, account: string, patch: { holding?: Record<string, unknown>; protection?: Record<string, unknown> }) => void
}) {
  const acct = String(h.account ?? '')
  const sym = String(h.symbol ?? '').toUpperCase()
  const isSchwab = acct.startsWith('schwab')
  const isFidelity = acct.startsWith('fidelity') && acct !== 'fidelity_401k'
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
  const [readiness, setReadiness] = useState<any>(null)
  const [refreshedQuote, setRefreshedQuote] = useState<any>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [validating, setValidating] = useState(false)
  const [preflightDiff, setPreflightDiff] = useState<PreflightDiff | null>(null)
  const [advisoryOverride, setAdvisoryOverride] = useState<any>(null)
  const [pendingAction, setPendingAction] = useState<{ kind: 'request'; orderKind: 'STOP' | 'TRAILING' | 'STOP_LIMIT' | 'MARKET' } | { kind: 'confirm'; channel: 'web' | 'telegram' } | null>(null)
  // Operator overrides for the order parameters (2026-07-14). Empty = advisory value, so the
  // default flow is byte-identical to before. Advisory values are still sent as advised_stop
  // for the audit trail; the tier band is a hint, never a hard clamp — the per-order 2FA +
  // server protective gate remain the actual guards.
  const [ovStop, setOvStop] = useState('')
  const [ovLimit, setOvLimit] = useState('')
  const [ovTrail, setOvTrail] = useState('')
  const numOr = (v: string): number | null => { const n = parseFloat(v); return Number.isFinite(n) && n > 0 ? n : null }
  const [liveStopOverride, setLiveStopOverride] = useState<any>(null)
  const effectivePr = advisoryOverride ? { ...pr, ...advisoryOverride } : pr
  const stop = Number(effectivePr?.stop_price) || null
  const price = Number(effectivePr?.price) || Number(h.current_price) || null
  const qty = Number(h.shares) || 0
  const isFractional = isSchwab && qty > 0 && Math.abs(qty - Math.round(qty)) > 1e-9
  const needsSellAll = isSchwab && qty > 0 && qty < SCHWAB_SELL_ALL_MAX_SHARES
  const sellAllTif = isFractional ? 'DAY' : 'GTC'
  const trail = resolvedTrailPct(effectivePr)
  const trailPct = trail?.pct ?? null
  const stopDist = trail?.stopDistPct ?? effectivePr?.stop_distance_pct

  const needsReauth = isSchwab && tokenHealth?.needs_reauth === true
  useEffect(() => {
    if (!isSchwab || !intentId || tokenHealth) return
    fetch('/api/v2/brokers/schwab/token-health').then(x => x.json()).then(j => setTokenHealth(unwrapApi(j))).catch(() => {})
  }, [isSchwab, intentId, tokenHealth])

  // Telegram bkapprove auto-submits — poll so the card updates without re-typing the ticker here.
  useEffect(() => {
    if (!intentId || sellAllDone) return
    let cancelled = false
    const poll = async () => {
      try {
        const raw = await fetch(`/api/v2/broker-orders/approval-status?intent_id=${encodeURIComponent(intentId)}`).then(x => x.json())
        const s = unwrapApi(raw) ?? raw
        if (cancelled || !s?.submitted) return
        const sub = s.submission ?? {}
        const oid = sub.broker_order_id
        if (!oid) return
        setSellAllDone(true)
        setMsg(`✅ LIVE stop on Schwab · order #${oid} (${sub.status ?? 'submitted'}) — approved via Telegram`)
        onRefresh?.()
      } catch { /* retry on next interval */ }
    }
    void poll()
    const iv = window.setInterval(poll, 5000)
    return () => { cancelled = true; window.clearInterval(iv) }
  }, [intentId, sellAllDone, onRefresh])
  const baseQuoteTs = h?.source_timestamp ?? h?.price_as_of ?? h?.quote_at ?? h?.price_timestamp ?? h?.last_repriced ?? ''
  const quoteTsForReadiness = refreshedQuote?.quote_time_normalized ?? baseQuoteTs

  // Refresh latest quote (read-only; never submits a broker order) and re-evaluate readiness.
  const refreshQuote = async () => {
    setRefreshing(true)
    try {
      const raw = await fetch('/api/v2/holdings/protective-stop/refresh-quote', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: sym, account: acct, order_kind: 'TRAILING_STOP', trail_pct: trailPct }),
      }).then(x => x.json())
      setRefreshedQuote(unwrapApi(raw))
    } catch { /* surfaced via stale state */ }
    setRefreshing(false)
  }

  const brokerKey = isFidelity ? 'fidelity' : isSchwab ? 'schwab' : ''
  const brokerUrl = brokerKey ? BROKER_URL[brokerKey] : null
  const trailLabel = trailPct != null
    ? (Math.abs(trailPct - Math.round(trailPct)) < 0.15 ? String(Math.round(trailPct)) : trailPct.toFixed(1))
    : ''
  const [selectedKind, setSelectedKind] = useState<StopOrderKind>('STOP')
  const priceTimestamp = refreshedQuote?.quote_time_normalized ?? refreshedQuote?.quote_time_raw
    ?? h?.source_timestamp ?? h?.price_as_of ?? h?.quote_at ?? h?.price_timestamp ?? h?.last_repriced ?? null
  const advisoryTimestamp = effectivePr?.source_timestamp ?? effectivePr?.quote_at ?? effectivePr?.at ?? null
  const effectivePrice = refreshedQuote?.quote_price ?? price
  const effectiveConfirmed = liveStopOverride ?? confirmedStop
  const liveResolved = resolveLiveStop(effectiveConfirmed, monitored, effectivePrice)
  const liveStop = liveResolved.price
  // P2 — the existing broker order. Only an app-placed (pilot) order can be API-cancelled for a one-2FA
  // in-app Replace; a manually-placed (ToS) order routes to P3 (cancel in ToS).
  const resolveReplaceParams = (confirmed?: any, kind: StopOrderKind | 'MARKET' = selectedKind) => {
    const conf = confirmed ?? effectiveConfirmed
    const orderId = String(conf?.order_id ?? '').trim() || null
    const isPilot = Boolean(conf?.pilot_placed)
    const canReplace = Boolean(isSchwab && kind !== 'MARKET' && hasLiveBrokerStopOrder(conf, monitored) && isPilot && orderId)
    return { canReplace, orderId, replaceBody: canReplace && orderId ? { replace_order_id: orderId } : {} }
  }
  const replacePreview = resolveReplaceParams()
  const existingOrderId = replacePreview.orderId
  const canReplaceInApp = replacePreview.canReplace
  const replaceReadinessQs = canReplaceInApp && existingOrderId
    ? `&replace_order_id=${encodeURIComponent(existingOrderId)}` : ''
  useEffect(() => {
    if (!isSchwab) return
    fetch(`/api/v2/holdings/stop-readiness?symbol=${encodeURIComponent(sym)}&account=${encodeURIComponent(acct)}&quote_at=${encodeURIComponent(String(quoteTsForReadiness))}${replaceReadinessQs}`)
      .then(x => x.json()).then(j => setReadiness(unwrapApi(j))).catch(() => {})
  }, [isSchwab, sym, acct, quoteTsForReadiness, replaceReadinessQs])
  const confirmedIsTrailing = isTrailingBrokerStop(effectiveConfirmed, monitored)
  const confirmedIsFixed = Boolean(liveResolved.hasLiveBrokerOrder && !confirmedIsTrailing && liveStop != null)
  const preferTrail = !confirmedIsFixed && Boolean(effectivePr?.trail_recommended || trail?.matchesStopWidth)

  const computeLogic = (orderKind: StopOrderKind = selectedKind, overrides?: {
    quotePrice?: number | null; quoteTs?: string | null; liveStop?: any
  }): StopLogic => {
    const px = overrides?.quotePrice ?? effectivePrice
    const ts = overrides?.quoteTs ?? priceTimestamp ?? advisoryTimestamp
    const conf = overrides?.liveStop ?? effectiveConfirmed
    return buildStopLogic({
      h: { ...h, current_price: px, price: px, source_timestamp: ts },
      pr: { ...effectivePr, price: px },
      monitored,
      confirmedStop: conf,
      trailPct,
      orderKind,
      wholeShareConfirmed,
      sourceTimestamp: ts,
    })
  }

  const logic = computeLogic(selectedKind)
  // Schwab orders lane health: if this account's live-stop read did NOT succeed, 'none' is a lie —
  // the state is UNVERIFIABLE (e.g. degraded login token; operator-placed stops invisible to the API).
  const _acctNorm = String(h?.account || '').replace(/_ira$/, '')
  const brokerReadDegraded = String(h?.account || '').startsWith('schwab')
    && Array.isArray(brokerStopReadOk)
    && !brokerStopReadOk.some(a => String(a).replace(/_ira$/, '') === _acctNorm)
    && logic.liveStop == null && !logic.liveStopIsTrailing

  /** Submission + preview use floor-reconciled advisory stop (logic.advisoryStop), not raw pr.stop_price.
   * Operator override fields (ovStop/ovLimit/ovTrail) overlay the advisory when non-empty; the pure
   * advisory is kept alongside so advised_stop in the request stays the advisory for the audit trail. */
  const advisedForKind = (kind: StopOrderKind): { advisoryStop: number | null; trailPct: number | null; limitPrice: number | null; pureAdvisoryStop: number | null } => {
    const lg = computeLogic(kind)
    const pureAdvisoryStop = lg.advisoryStop ?? stop
    const advisoryStop = (kind === 'STOP' || kind === 'STOP_LIMIT') ? (numOr(ovStop) ?? pureAdvisoryStop) : pureAdvisoryStop
    const advTrail = trail?.pct ?? (effectivePr?.suggested_trail_pct != null ? Number(effectivePr.suggested_trail_pct) : null)
    const tr = kind === 'TRAILING' ? (numOr(ovTrail) ?? advTrail) : null
    const limitPrice = kind === 'STOP_LIMIT' ? (numOr(ovLimit) ?? advisoryStop) : null
    return { advisoryStop, trailPct: tr, limitPrice, pureAdvisoryStop }
  }

  const trailLabelFor = (pct: number | null | undefined) => {
    if (pct == null) return ''
    return Math.abs(pct - Math.round(pct)) < 0.15 ? String(Math.round(pct)) : pct.toFixed(1)
  }

  const orderPreviewLine = (kind: StopOrderKind): string => {
    const { advisoryStop: px, trailPct: tr } = advisedForKind(kind)
    if (kind === 'TRAILING' && tr != null) {
      return `SELL ${logic.wholeQty} ${sym} TRAILING_STOP ${trailLabelFor(tr)}% GTC`
    }
    if (px != null && (kind === 'STOP' || kind === 'STOP_LIMIT')) {
      const { limitPrice } = advisedForKind(kind)
      const lim = kind === 'STOP_LIMIT' && limitPrice != null && limitPrice !== px ? ` LIMIT $${limitPrice.toFixed(2)}` : ''
      return `SELL ${logic.wholeQty} ${sym} ${kind === 'STOP_LIMIT' ? 'STOP_LIMIT' : 'STOP'} $${px.toFixed(2)}${lim} GTC`
    }
    return `SELL ${logic.wholeQty} ${sym} ${kind} GTC`
  }

  const runClickPreflight = async (orderKind: StopOrderKind) => {
    setValidating(true)
    setPreflightDiff(null)
    setPendingAction(null)
    setMsg('⏳ Validating quote + advisory + stop logic…')
    const pf = await runProtectiveStopPreflight({
      sym, acct, orderKind, trailPct, isSchwab, isFidelity,
      priceTimestamp, effectivePrice, effectiveConfirmed,
      computeLogic: (kind, overrides) => {
        const px = overrides?.quotePrice ?? effectivePrice
        const ts = overrides?.quoteTs ?? priceTimestamp ?? advisoryTimestamp
        const conf = overrides?.liveStop ?? effectiveConfirmed
        const snap = overrides?.advisorySnap
        const pr = snap ? { ...effectivePr, ...snap, price: px } : { ...effectivePr, price: px }
        return buildStopLogic({
          h: { ...h, current_price: px, price: px, source_timestamp: ts },
          pr,
          monitored,
          confirmedStop: conf,
          trailPct,
          orderKind: kind,
          wholeShareConfirmed,
          sourceTimestamp: ts,
        })
      },
    })
    if (pf.quoteSnap) setRefreshedQuote(pf.quoteSnap)
    if (pf.advisorySnap) {
      const merged = { ...pf.advisorySnap, price: pf.quoteSnap?.quote_price ?? pf.advisorySnap.price }
      setAdvisoryOverride(merged)
    }
    if (pf.readinessSnap) setReadiness(pf.readinessSnap)
    if (pf.liveSnap && pf.liveSnap !== effectiveConfirmed) setLiveStopOverride(pf.liveSnap)
    const qPx = pf.quoteSnap?.quote_price
    const qTs = pf.quoteSnap?.quote_time_normalized ?? pf.quoteSnap?.quote_time_raw ?? priceTimestamp
    if (qPx != null) {
      const holdingPatch: Record<string, unknown> = {
        current_price: qPx,
        source_timestamp: qTs ?? null,
        price_as_of: qTs ?? null,
      }
      if (qty > 0) holdingPatch.market_value = Number(qPx) * qty
      const protPatch = pf.advisorySnap ? { ...pf.advisorySnap, price: qPx } : undefined
      onPreflightUpdate?.(sym, acct, { holding: holdingPatch, protection: protPatch })
    }
    onRefresh?.()
    setValidating(false)
    return pf
  }

  if (!qty) return null
  if (!stop && !needsSellAll && !logic.isFundLike && logic.liveStop == null) return null

  // Lock-in advisory: you hold a LIVE FIXED stop, but a trailing stop at the advised width would sit
  // ABOVE that fixed trigger right now — so switching to trailing locks a HIGHER floor and keeps
  // ratcheting up as price rises. Advisory only; execution routes through the existing Switch action
  // (Schwab = API + 2FA, Fidelity = manual Active Trader ticket).
  const liveFixedStopPx = confirmedIsFixed && liveStop != null ? liveStop : null
  const trailingFloorNow = (trailPct != null && price != null && price > 0) ? price * (1 - trailPct / 100) : null
  const lockInTrail = Boolean(liveFixedStopPx != null && trailingFloorNow != null && trailingFloorNow > liveFixedStopPx + 0.01)
  const lockInGapPct = liveFixedStopPx != null && trailingFloorNow != null
    ? ((trailingFloorNow - liveFixedStopPx) / liveFixedStopPx) * 100 : null

  const resetApprove = () => { setIntentId(''); setApproveTk(''); setApproveCode(''); setSellAllDone(false) }

  const requestOrder = async (kind: 'STOP' | 'TRAILING' | 'STOP_LIMIT' | 'MARKET', opts?: {
    label?: string; skipPreflight?: boolean; liveSnap?: any
  }) => {
    setSelectedKind(kind)
    const nextLogic = computeLogic(kind)
    if (kind !== 'MARKET' && !nextLogic.canRequestLive && isSchwab) {
      setMsg(`⛔ ${nextLogic.blockers.map(b => b.message).join(' ')}`)
      return
    }
    setBusy(true); setMsg(''); setTicket(''); resetApprove()
    const advised = advisedForKind(kind)
    try {
      const body: Record<string, unknown> = {
        symbol: sym, account: acct, qty,
        order_kind: kind,
        stop_price: kind === 'MARKET' ? null : advised.advisoryStop,
        limit_price: advised.limitPrice,
        trail_pct: advised.trailPct,
        advised_stop: advised.pureAdvisoryStop,
        current_price: effectivePrice,
        source_broker: effectivePr?.source_broker ?? effectivePr?.broker ?? effectivePr?.account ?? effectivePr?.source_account,
        instrument_type: nextLogic.instrumentType,
        quote_at: priceTimestamp ?? advisoryTimestamp,
        whole_share_confirmed: wholeShareConfirmed,
        preflight_at: new Date().toISOString(),
        // P2 — replace an existing APP-placed stop: confirm path cancels it, then places the new one, one 2FA.
        // Use the freshest live-stop snap (preflight may have just fetched pilot_placed + order_id).
        ...resolveReplaceParams(opts?.liveSnap ?? effectiveConfirmed, kind).replaceBody,
      }
      const raw = await fetch('/api/v2/holdings/protective-stop', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      }).then(x => x.json())
      const r = unwrapApi(raw)
      if (r?.mode === 'monitored_armed') {
        const t = r?.result?.ticket || r?.order?.ticket || ''
        setTicket(t)
        const kindLbl = kind === 'TRAILING' ? `${advised.trailPct}% trailing` : kind === 'MARKET' ? `market ${sellAllTif}` : 'fixed stop'
        setMsg(`✅ Tracking armed — ${kindLbl} @ ${kind === 'MARKET' ? 'market' : kind === 'TRAILING' ? `${advised.trailPct}%` : `$${advised.advisoryStop!.toFixed(2)}`}`)
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

  type RequestKind = 'STOP' | 'TRAILING' | 'STOP_LIMIT' | 'MARKET'
  const preflightAndRequest = async (kind: RequestKind, opts?: { label?: string }) => {
    if (kind === 'MARKET') { requestOrder(kind, opts); return }
    const pf = await runClickPreflight(kind)
    if (!pf.ok) {
      setMsg(`⛔ Validation failed — ${pf.blockers?.join(' · ') || pf.error || 'resolve blockers above'}`)
      return
    }
    if (pf.changed && pf.diffObj) {
      setPreflightDiff(pf.diffObj)
      setPendingAction({ kind: 'request', orderKind: kind })
      setMsg(`⚠️ Logic changed since page load — review below, then confirm to proceed.`)
      return
    }
    setMsg('✓ Validated — proceeding…')
    await requestOrder(kind, { ...opts, skipPreflight: true, liveSnap: pf.liveSnap })
  }

  // One-click apply: opened via a 🔒 row button (autoStageKind set) on a NAKED position → auto-fire the
  // advised order so the operator lands straight on the 2FA approve step (Schwab) or a manual ticket
  // (Fidelity). Fires ONCE, only when there is no existing stop (existing → manual Replace/ToS) and an
  // advised stop exists. Blockers still surface normally (preflightAndRequest handles them).
  const autoStagedRef = useRef(false)
  useEffect(() => {
    if (autoStagedRef.current || !autoStageKind) return
    if (liveResolved.hasLiveBrokerOrder) return
    if (!stop) return
    if (intentId || pendingAction) return
    autoStagedRef.current = true
    void preflightAndRequest(autoStageKind, { label: 'Applying advised stop' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStageKind, liveResolved.hasLiveBrokerOrder, stop])

  const preflightAndConfirm = async (channel: 'web' | 'telegram') => {
    const pf = await runClickPreflight(selectedKind)
    if (!pf.ok) {
      setMsg(`⛔ Cannot submit — ${pf.blockers?.join(' · ') || 'validation failed'}`)
      return
    }
    if (pf.changed && pf.diffObj) {
      setPreflightDiff(pf.diffObj)
      setPendingAction({ kind: 'confirm', channel })
      setMsg(`⚠️ Logic changed — confirm again to submit to Schwab.`)
      return
    }
    await confirmOrder(channel, true)
  }

  const confirmOrder = async (channel: 'web' | 'telegram', skipPreflight = false) => {
    if (!intentId) { setMsg('⛔ no active intent — request the order first'); return }
    if (!skipPreflight) {
      await preflightAndConfirm(channel)
      return
    }
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
      if (r?.already_submitted || ((r?.stage === 'submit' || submitted || oid) && submitted && r?.ok !== false)) {
        setSellAllDone(true)
        const oid2 = oid ?? r?.broker_order_id ?? r?.result?.broker_order_id
        const st2 = ostatus ?? r?.status ?? r?.result?.status ?? 'submitted'
        setMsg(r?.already_submitted
          ? `✅ Stop already LIVE on Schwab · order #${oid2 ?? '—'} (${st2}) — other 2FA channel already approved`
          : `✅ LIVE sell placed on Schwab · order #${oid2 ?? '—'} (${st2})`)
        onRefresh?.()
      } else if (r?.stage === 'confirm' && r?.ok && r?.fully_approved === false) {
        setMsg('channel confirmed — waiting on the other factor')
      } else if (r?.mode === 'blocked' || r?.broker_submitted === false) {
        setMsg(`⛔ ${internalBlockMessage(r) ?? apiReason(r)}`)
      } else if (r?.stage === 'modify_cancel') {
        setMsg(`⛔ Replace blocked — existing stop was not canceled at Schwab: ${apiReason(r)}. No new stop was placed.`)
      } else if (r?.stage === 'submit' && (ostatus === 'error' || r?.ok === false)) {
        setMsg(`⛔ Schwab rejected the submitted order: ${apiReason(r)}`)
      } else {
        setMsg(`⛔ ${apiReason(r)}`)
      }
    } catch (e: any) {
      setMsg('⛔ ' + String(e.message || e).slice(0, 80))
    } finally {
      setBusy(false)
    }
  }

  const armStop = (kind: 'STOP' | 'TRAILING' | 'STOP_LIMIT') => preflightAndRequest(kind)
  const requestSellAll = () => {
    if (!window.confirm(`Sell ALL ${qty} ${sym} @ MARKET (${sellAllTif}) on ${acct}? Requires 2FA before submit.`)) return
    requestOrder('MARKET', { label: `Sell all ${qty} sh @ MARKET ${sellAllTif}` })
  }

  const tkOk = approveTk.trim().toUpperCase() === sym
  const codeOk = approveCode.trim().length === 6
  const inApprove = !!intentId && !sellAllDone
  const showProtect = stop != null && !logic.isFundLike && !(needsSellAll && isFractional && Math.floor(qty) < 1)
  // Hard backend gates surfaced from the read-only readiness snapshot. These genuinely prevent a safe live
  // request, so they ALSO disable the button (with a clear reason) — not just the data gates in buildStopLogic.
  // Preflight-not-run and active-approval are advisory (shown in the readiness panel), since the per-order 2FA
  // + backend evidence revalidation enforce them at submit; we never silently rely on the frontend for safety.
  const backendHardBlock: string | null = isSchwab && readiness ? (
    readiness.account_api_write_enabled === false ? `${acct} is not armed for live API writes (ticket mode). Set broker_accounts.api_write_enabled=TRUE for ${resolveSchwabAcct(acct)}.`
      : readiness.other_account_canary ? `Another ${sym} canary is already active on ${readiness.other_account_canary}. Only one ${sym} canary may be armed at a time.`
        : readiness.quote_parse_ok === false ? 'Quote timestamp could not be parsed; refresh quote before requesting a live stop.'
          : !readiness.quote_fresh ? 'Quote is stale — refresh the latest price first.'
            : readiness.oco_brackets_schwab_off === false ? 'OCO is ON — must be OFF before any Schwab stop.'
              : (readiness.db_available === false || readiness.evidence_store_available === false) ? 'DB unavailable / evidence store unavailable.'
                : (readiness.execution && readiness.execution.operator_live_via_2fa_allowed === false) ? 'Schwab 2FA live path disabled by execution_state.'
                  : null
  ) : null
  const disabledReasonHuman = logic.disabledReasonHuman ?? backendHardBlock
  const liveBlocked = validating || !logic.canRequestLive || backendHardBlock != null
  const statusColor = logic.state === 'LIVE BROKER STOP' || logic.state === 'FIDELITY STOP VERIFIED' || logic.state === 'FIDELITY STOP RECORDED — MANUAL' ? GREEN
    : logic.state === 'MONITORED — SOFTWARE ONLY' ? PURPLE
      : logic.state === 'SOURCE MISMATCH — BLOCKED' || logic.state === 'ACTION REQUIRED' ? RED
        : logic.state === 'NOT APPLICABLE' ? MUTED
          : AMBER

  // A disabled live-stop button must ALWAYS explain itself: the tooltip carries the primary blocker reason,
  // and an inline reason line is rendered under the button row (see below). Never a silent gray-out.
  const enabledTitle = (kind: 'STOP' | 'TRAILING' | 'STOP_LIMIT') => kind === 'TRAILING'
    ? `Request ${trailPct}% trailing stop via 2FA — operator-approved, whole-share, evidence-bound`
    : `Request fixed stop at $${stop != null ? stop.toFixed(2) : '—'} via 2FA — operator-approved, whole-share, evidence-bound`
  const btn = (label: string, kind: 'STOP' | 'TRAILING' | 'STOP_LIMIT', highlight = false) => (
    <button
      onClick={e => { e.stopPropagation(); armStop(kind) }}
      disabled={busy || validating || liveBlocked}
      title={liveBlocked
        ? `Disabled — ${disabledReasonHuman ?? 'resolve the blockers listed above'}`
        : enabledTitle(kind)}
      style={{
        fontSize: 12, fontWeight: 800, minHeight: 34, padding: '7px 10px', borderRadius: 6, cursor: (busy || liveBlocked) ? 'not-allowed' : 'pointer',
        border: `1px solid ${liveBlocked ? 'rgba(148,163,184,.25)' : highlight ? AMBER : 'rgba(148,163,184,.35)'}`,
        background: liveBlocked ? 'rgba(15,23,42,.5)' : highlight ? 'rgba(245,158,11,.18)' : 'rgba(15,23,42,.66)',
        color: liveBlocked ? MUTED : highlight ? AMBER : TEXT0, whiteSpace: 'nowrap',
      }}
    >{validating ? 'Validating…' : busy ? '…' : label}</button>
  )

  const fidelityTicketLabel = logic.liveStop != null ? 'Create modify ticket' : 'Create Fidelity manual ticket'
  const fidelityReviewDisabled = logic.blockers.some(b => b.code === 'source_mismatch')
  const reviewTip = stopReviewTooltip({
    advisoryAt: effectivePr?.at, advisoryModel: effectivePr?.model,
    priceAt: priceTimestamp ?? advisoryTimestamp,
    brokerFetchedAt: confirmedStop?.fetched_at ?? brokerStopsFetchedAt,
    brokerOrderId: confirmedStop?.order_id,
    confirmedAt: confirmedStop?.confirmed_at,
  })
  const reviewStamp = formatReviewStamp(confirmedStop?.fetched_at ?? brokerStopsFetchedAt ?? effectivePr?.at)

  return (
    <div onClick={e => e.stopPropagation()} style={{ marginTop: 10, padding: '12px 13px', borderRadius: 8, background: 'rgba(15,23,42,.74)', border: `1px solid ${statusColor}55`, boxShadow: `inset 3px 0 0 ${statusColor}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 9, flexWrap: 'wrap' }}>
        <div title={reviewTip} style={{ fontSize: 15, color: statusColor, fontWeight: 900, letterSpacing: 0.2, cursor: 'help' }}>STOP STATUS: {logic.state}</div>
        <span style={{ fontSize: 12, color: MUTED }}>{logic.stop_action_decision.replace(/_/g, ' ')}</span>
        {reviewStamp && <span title={reviewTip} style={{ fontSize: 10, color: MUTED, cursor: 'help' }}>last reviewed {reviewStamp}</span>}
      </div>

      <div style={{ marginBottom: 10, padding: '9px 10px', borderRadius: 7, background: 'rgba(2,6,23,.38)', border: `1px solid ${statusColor}44` }}>
        <div style={{ fontSize: 12, color: MUTED, fontWeight: 800, marginBottom: 3 }}>Recommendation</div>
        <div style={{ fontSize: 15, color: TEXT0, fontWeight: 900, lineHeight: 1.35 }}>{logic.primary_operator_action}</div>
        {logic.secondary_operator_actions.length > 0 && (
          <div style={{ marginTop: 5, display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {logic.secondary_operator_actions.map((a, i) => (
              <span key={`${a}-${i}`} style={{ fontSize: 12, color: MUTED, border: '1px solid rgba(148,163,184,.22)', borderRadius: 999, padding: '3px 7px' }}>{a}</span>
            ))}
          </div>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 7, fontSize: 12, lineHeight: 1.35, color: TEXT0 }}>
        <div><span style={{ color: MUTED }}>Current</span><br /><b>{logic.currentPrice != null ? `$${logic.currentPrice.toFixed(2)}` : 'missing'}</b></div>
        <div><span style={{ color: MUTED }}>Account + broker</span><br /><b>{acct}</b> · {logic.broker}</div>
        <div><span style={{ color: MUTED }}>Instrument</span><br /><b>{logic.instrumentType.replace(/_/g, ' ')}</b></div>
        <div title={brokerReadDegraded ? 'The Schwab open-orders read did not succeed on the last fetch (degraded token lane) — stops you placed directly at Schwab are invisible to the API right now. This is NOT confirmation that no stop exists.' : reviewTip}><span style={{ color: MUTED, fontWeight: 800 }}>CURRENT LIVE BROKER STOP</span><br /><b style={{ color: logic.liveStop != null || logic.liveStopIsTrailing ? GREEN : brokerReadDegraded ? AMBER : MUTED }}>{logic.liveStopIsTrailing && logic.liveTrailPct != null ? `TRAILING ${logic.liveTrailPct}%` : logic.liveStop != null ? `$${logic.liveStop.toFixed(2)}` : brokerReadDegraded ? 'UNVERIFIABLE \u2014 orders feed degraded' : 'none'}</b>{logic.liveStopIsTrailing && logic.liveStop != null ? ` (~$${logic.liveStop.toFixed(2)} now)` : ''}{logic.liveStopDistancePct != null ? ` (${logic.liveStopDistancePct.toFixed(1)}% below)` : ''}</div>
        <div title={reviewTip}><span style={{ color: MUTED, fontWeight: 800 }}>ADVISORY RECOMMENDATION</span><br /><b style={{ color: AMBER }}>{logic.advisoryStop != null ? `$${logic.advisoryStop.toFixed(2)}` : 'none'}</b>{logic.distancePct != null ? ` (${logic.distancePct.toFixed(1)}% below)` : ''}</div>
        <div><span style={{ color: MUTED }}>Optional trail</span><br /><b>{trailPct != null ? `${trailLabel}%` : 'none'}</b>{trailingFloorNow != null ? <span style={{ color: GREEN, fontSize: 11 }}> (≈${trailingFloorNow.toFixed(2)} now)</span> : null}</div>
        <div><span style={{ color: MUTED }}>Family floor/cap</span><br /><b style={{ color: logic.floor_math_consistent ? TEXT0 : RED }}>{logic.familyFloorLabel}</b></div>
        <div title={`${logic.liveStop != null ? `Current stop: $${logic.liveStop.toFixed(2)}${logic.liveStopDistancePct != null ? ` (${logic.liveStopDistancePct.toFixed(1)}% below)` : ''}` : 'Current stop: none'}\nWe advise trailing per ${(logic.volatilityTier ?? 'unclassified').toUpperCase()} tier${logic.regime ? ` + ${logic.regime.replace(/_/g, '-')} regime${logic.regimeAdjustmentPct != null ? ` (${logic.regimeAdjustmentPct > 0 ? 'wider: +' : 'tighter: '}${logic.regimeAdjustmentPct}% cap)` : ''}` : ''}.\nMinimum floor: ${logic.familyFloorPct != null ? logic.familyFloorPct + '%' : 'n/a'} (family/swing-low rule governs final placement).`} style={{ cursor: 'help' }}><span style={{ color: MUTED }}>Vol tier · regime</span><br /><b style={{ color: logic.volatilityTier === 'low' ? GREEN : logic.volatilityTier === 'high' ? RED : logic.volatilityTier === 'medium' ? AMBER : TEXT0 }}>{logic.volatilityTier ?? '—'}</b>{logic.regime ? <span> · {logic.regime.replace(/_/g, '-')}{logic.regimeAdjustmentPct != null ? <span style={{ color: logic.regimeAdjustmentPct > 0 ? GREEN : AMBER, fontSize: 11 }}> ({logic.regimeAdjustmentPct > 0 ? '+' : ''}{logic.regimeAdjustmentPct}% cap)</span> : null}</span> : null}</div>
        <div><span style={{ color: MUTED }}>Price timestamp</span><br /><b>{String(priceTimestamp ?? 'missing').slice(0, 19)}</b></div>
        <div><span style={{ color: MUTED }}>Advisor timestamp</span><br /><b>{String(advisoryTimestamp ?? 'missing').slice(0, 19)}</b></div>
      </div>

      {/* Stop picture — ONE coherent story from the ACTUAL advisory (not the generic band,
          which contradicted the fixed-stop recommendation; operator 2026-07-14). */}
      {(() => {
        const fb = (effectivePr?.family_bounds || {}) as any
        const px = logic.currentPrice
        const basisPs = (Number(h?.shares) > 0 && Number(h?.cost_basis) > 0)
          ? Number(h.cost_basis) / Number(h.shares) : null
        const sh = Number(h?.shares) || 0
        const usd = (v: number) => `${v < 0 ? '\u2212' : '+'}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
        const pct = (v: number) => `${v < 0 ? '\u2212' : '+'}${Math.abs(v).toFixed(1)}%`
        const plNow = basisPs != null && px != null && basisPs > 0 ? (px - basisPs) / basisPs * 100 : null
        const plNowUsd = basisPs != null && px != null && sh > 0 ? (px - basisPs) * sh : null
        // 1 — where you are
        const cur = logic.liveStop != null || logic.liveStopIsTrailing
          ? `Current: ${logic.liveStopIsTrailing && logic.liveTrailPct != null ? `TRAILING ${logic.liveTrailPct}%` : 'FIXED stop'}`
            + (logic.liveStop != null ? ` ${logic.liveStopIsTrailing ? '\u2248' : 'at'} $${logic.liveStop.toFixed(2)}` : '')
            + (logic.liveStopDistancePct != null ? ` (${logic.liveStopDistancePct.toFixed(1)}% below price)` : '')
          : brokerReadDegraded
            ? 'Current: UNVERIFIABLE \u2014 the Schwab orders feed is degraded; a stop you placed at Schwab may exist but is invisible to the API right now'
            : 'Current: NO live stop'
        const curPl = plNow != null ? ` \u00b7 position P/L ${pct(plNow)}${plNowUsd != null ? ` (${usd(plNowUsd)})` : ''}` : ''
        // 2 — what the advisor actually recommends (fixed value + optional/recommended trail)
        const tr = trail?.pct ?? null
        const advParts: string[] = []
        if (logic.advisoryStop != null) {
          advParts.push(`FIXED stop $${logic.advisoryStop.toFixed(2)}${logic.distancePct != null ? ` (${logic.distancePct.toFixed(1)}% below)` : ''}`)
        }
        if (tr != null && px != null) {
          advParts.push(`${effectivePr?.trail_recommended ? 'recommended' : 'optional'} ${tr}% trail (\u2248$${(px * (1 - tr / 100)).toFixed(2)} now)`)
        }
        const advise = advParts.length ? `Advisor: ${advParts.join(' \u00b7 ')}` : 'Advisor: no recommendation yet'
        const advColor = (logic.liveStop == null && !logic.liveStopIsTrailing) ? AMBER
          : logic.advisory_stop_is_tighter_than_existing === false ? AMBER : GREEN
        // 3 — tier context, explicitly labeled so band vs applied floor cannot read as contradiction
        const vt = (effectivePr?.volatility_tier || logic.volatilityTier || '').toUpperCase()
        const ctxBits: string[] = []
        if (vt) ctxBits.push(`${vt} vol tier`)
        if (logic.regime) ctxBits.push(`${logic.regime.replace(/_/g, '-')} regime${logic.regimeAdjustmentPct != null ? ` (${logic.regimeAdjustmentPct > 0 ? '+' : ''}${logic.regimeAdjustmentPct}% cap)` : ''}`)
        if (fb.trail_min_pct != null && fb.trail_max_pct != null) ctxBits.push(`normal trail band ${fb.trail_min_pct}\u2013${fb.trail_max_pct}%`)
        if (logic.familyFloorPct != null) ctxBits.push(`hard floor ${logic.familyFloorPct}% (swing-low anchored)`)
        const context = ctxBits.length ? `Why: ${ctxBits.join(' \u00b7 ')}` : null
        // 4 — consequence if a stop fills. When BOTH a live stop and a (different) advisory
        // exist, show BOTH so the operator can compare what each locks in (operator 2026-07-14).
        const stopLine = (stop: number | null, label: string) => {
          if (stop == null) return null
          const pl = basisPs != null && basisPs > 0 ? (stop - basisPs) / basisPs * 100 : null
          if (pl == null) return null
          const lUsd = sh > 0 && basisPs != null ? (stop - basisPs) * sh : null
          const gb = px != null && px > 0 ? (px - stop) / px * 100 : null
          const gbUsd = px != null && sh > 0 ? (px - stop) * sh : null
          return {
            pl,
            text: `If the ${label} stop fills: you ${pl >= 0 ? 'LOCK IN' : 'take'} ${pct(pl)}${lUsd != null ? ` (${usd(lUsd)})` : ''}`
              + (gb != null ? ` \u00b7 giving back ${gb.toFixed(1)}%${gbUsd != null ? ` (${usd(gbUsd).replace('+', '')})` : ''} from today's price` : ''),
          }
        }
        const hasLive = logic.liveStop != null || logic.liveStopIsTrailing
        const cLive = hasLive ? stopLine(logic.liveStop, 'current') : null
        const advDiffers = logic.advisoryStop != null
          && (!hasLive || logic.liveStop == null || Math.abs(logic.advisoryStop - logic.liveStop) > 0.005)
        const cAdv = advDiffers ? stopLine(logic.advisoryStop, hasLive ? 'ADVISORY' : 'advisory') : null
        const consequence = cLive?.text ?? cAdv?.text ?? null
        const plAtStop = cLive?.pl ?? cAdv?.pl ?? null
        const consequence2 = cLive && cAdv ? cAdv.text : null
        const plAtStop2 = cLive && cAdv ? cAdv.pl : null
        if (!advParts.length && logic.liveStop == null) return null
        return (
          <div style={{ marginTop: 9, padding: '10px 13px', borderRadius: 8, fontSize: 12.5, lineHeight: 1.65,
                        background: 'rgba(148,163,184,.07)', border: `1px solid ${advColor}44` }}>
            <div style={{ color: TEXT0, fontWeight: 700 }}>{cur}{curPl}</div>
            <div style={{ color: advColor, fontWeight: 700 }}>{advise}</div>
            {context && <div style={{ color: MUTED }}>{context}</div>}
            {consequence && <div style={{ color: plAtStop != null && plAtStop < 0 ? RED : GREEN, fontWeight: 700 }}>{consequence}</div>}
            {consequence2 && <div style={{ color: plAtStop2 != null && plAtStop2 < 0 ? RED : AMBER, fontWeight: 700 }}>{consequence2}</div>}
          </div>
        )
      })()}

      <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 5, fontSize: 12 }}>
        {logic.why.map(row => (
          <div key={row.label} style={{ padding: '6px 7px', borderRadius: 6, background: 'rgba(15,23,42,.46)', border: '1px solid rgba(148,163,184,.14)' }}>
            <span style={{ color: MUTED, fontWeight: 800 }}>{row.label}: </span>
            <span style={{ color: TEXT0 }}>{row.value}</span>
          </div>
        ))}
      </div>

      {(effectivePr?.rationale || effectivePr?.reason || effectivePr?.rec) && (
        <div style={{ marginTop: 8, fontSize: 12, color: MUTED, lineHeight: 1.45 }}>
          Analyst note: {String(effectivePr?.rationale ?? effectivePr?.reason ?? effectivePr?.rec).slice(0, 180)}
        </div>
      )}
      {logic.blockers.length > 0 && (
        <div style={{ marginTop: 8, display: 'grid', gap: 5 }}>
          {logic.blockers.map(b => (
            <div key={b.code} style={{ fontSize: 12, color: b.code === 'fractional_qty' ? AMBER : RED, background: b.code === 'fractional_qty' ? 'rgba(245,158,11,.12)' : 'rgba(239,68,68,.1)', border: `1px solid ${b.code === 'fractional_qty' ? AMBER : RED}44`, borderRadius: 6, padding: '7px 8px' }}>{b.message}</div>
          ))}
        </div>
      )}
      {/* P2/P3 — existing live broker stop. App-placed (pilot) → Replace in one 2FA (cancel-then-place).
          Manually-placed (ToS) → can't API-cancel; must modify in ToS. Guard blocks any naked duplicate. */}
      {liveResolved.hasLiveBrokerOrder && canReplaceInApp && (
        <div style={{ fontSize: 11.5, color: GREEN, marginBottom: 6, padding: '7px 9px', borderRadius: 6, background: `${GREEN}12`, border: `1px solid ${GREEN}45`, lineHeight: 1.5 }}>
          <div style={{ fontWeight: 900, marginBottom: 2 }}>🔄 Replace mode — existing app stop {fmtLiveStop(logic)}</div>
          This stop was placed here, so requesting a new one will <b>cancel it and place the replacement in a single 2FA</b> —
          no duplicate. (Order #{existingOrderId})
        </div>
      )}
      {liveResolved.hasLiveBrokerOrder && !canReplaceInApp && (
        <div style={{ fontSize: 11.5, color: AMBER, marginBottom: 6, padding: '7px 9px', borderRadius: 6, background: `${AMBER}12`, border: `1px solid ${AMBER}45`, lineHeight: 1.5 }}>
          <div style={{ fontWeight: 900, marginBottom: 2 }}>⚠️ Existing {existingOrderId ? 'manual ' : ''}broker stop ({fmtLiveStop(logic)}) — modify it {isFidelity ? 'in Fidelity' : 'in ToS'}</div>
          Placing a <b>second</b> stop is blocked (two SELL stops can over-sell). {existingOrderId ? 'This order was not placed here, so Trade AI can’t cancel it via API. ' : ''}
          Cancel or modify the existing order {isFidelity ? 'in Fidelity' : 'in ToS'} first, then place here.
          {!isFidelity && brokerUrl ? <> <a href={brokerUrl} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={{ color: BLUE, fontWeight: 700 }}>Open ToS ↗</a></> : null}
        </div>
      )}
      {/* LOCK-IN PROFITS — fixed stop is live, but trailing now locks a HIGHER floor → advise the switch */}
      {lockInTrail && liveFixedStopPx != null && trailingFloorNow != null && (
        <div style={{ fontSize: 11, color: GREEN, fontWeight: 700, marginBottom: 6, padding: '5px 8px', borderRadius: 6, background: `${GREEN}12`, border: `1px solid ${GREEN}45`, lineHeight: 1.45 }}>
          <div style={{ fontWeight: 900, marginBottom: 2 }}>📈 Lock in profits — switch to {trailLabel}% trailing</div>
          A {trailLabel}% trailing stop now sits at <b style={{ fontFamily: 'monospace' }}>${trailingFloorNow.toFixed(2)}</b>
          {' '}— <b>{lockInGapPct != null ? `${lockInGapPct.toFixed(1)}%` : ''}</b> above your live fixed stop
          {' '}<b style={{ fontFamily: 'monospace' }}>${liveFixedStopPx.toFixed(2)}</b>. It keeps ratcheting up as price rises.
          <div style={{ marginTop: 5, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <button
              onClick={e => { e.stopPropagation(); preflightAndRequest('TRAILING') }}
              disabled={busy || needsReauth}
              title={isFidelity
                ? `Fidelity has no trading API — arms a software-monitored ${trailLabel}% trailing stop + a manual Active Trader ticket to replace the fixed stop`
                : `Submit a ${trailLabel}% trailing stop via the Schwab API (per-order 2FA) to replace the fixed stop`}
              style={{ fontSize: 9.5, fontWeight: 900, padding: '4px 10px', borderRadius: 5, cursor: (busy || needsReauth) ? 'not-allowed' : 'pointer', border: `1px solid ${GREEN}`, background: `${GREEN}1e`, color: GREEN, whiteSpace: 'nowrap' }}
            >{busy && !intentId ? '…' : isFidelity ? `Create Fidelity manual ticket` : `Request Schwab trailing stop via 2FA`}</button>
            {needsReauth && <span style={{ fontSize: 8.5, color: RED, fontWeight: 700 }}>Schwab re-auth required</span>}
          </div>
        </div>
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

      {/* LIVE STOP READINESS — compact gate panel for Schwab protective stops (read-only). */}
      {isSchwab && showProtect && (() => {
        const rd = readiness || {}
        const exec = rd.execution || {}
        const ap = rd.active_approval || {}
        const sv = rd.schwab_validator || {}
        const session: string = rd.quote_session ?? 'unknown'
        const quoteParseOk: boolean = rd.quote_parse_ok !== false
        const quoteFresh: boolean = rd.quote_fresh === true
        const ICON = (s: 'ok' | 'warn' | 'block') => s === 'ok' ? '✅' : s === 'warn' ? '⚠️' : '⛔'
        const quoteStatus: 'ok' | 'warn' | 'block' = !quoteParseOk ? 'block' : !quoteFresh ? 'block' : 'ok'
        const quoteValue = !quoteParseOk ? 'could not be parsed — refresh quote'
          : !quoteFresh ? `stale — refresh price${rd.quote_age_sec != null ? ` (${Math.round(rd.quote_age_sec / 60)}m old)` : ''}` : 'fresh'
        const sessionStatus: 'ok' | 'warn' | 'block' = session === 'regular' ? 'ok' : (session === 'after_hours' || session === 'pre_market' || session === 'closed') ? 'warn' : 'block'
        const rows: { label: string; status: 'ok' | 'warn' | 'block'; value: string }[] = [
          { label: 'Build', status: 'ok', value: rd.build_marker || 'cc-v3 stop-lifecycle-close 2026-07-01' },
          { label: 'Quote', status: quoteStatus, value: quoteValue },
          { label: 'Session', status: sessionStatus, value: session.replace(/_/g, '-') },
          { label: 'Quote raw / normalized', status: quoteParseOk ? 'ok' : 'block', value: `${String(rd.quote_raw ?? '—')} → ${String(rd.quote_normalized ?? 'unparseable')}` },
          { label: 'DB / evidence store', status: (rd.db_available && rd.evidence_store_available) ? 'ok' : 'block', value: rd.db_available == null ? 'checking…' : (rd.db_available && rd.evidence_store_available) ? 'available' : 'unavailable' },
          { label: 'Schwab validator', status: sv.pass ? 'ok' : (sv.summary ? 'block' : 'warn'), value: sv.summary || 'checking…' },
          { label: 'Execution state', status: exec.operator_live_via_2fa_allowed ? 'ok' : 'block', value: exec.operator_live_via_2fa_allowed ? 'operator 2FA live allowed' : (exec.error || 'blocked') },
          { label: 'Active approval', status: ap.exists ? 'warn' : 'ok', value: ap.exists ? `existing lock${ap.expires_at ? `, expires ${String(ap.expires_at).slice(0, 19)}` : ''}` : 'none' },
          { label: 'Whole-share confirmation', status: logic.residualQty > 1e-6 ? (wholeShareConfirmed ? 'ok' : 'warn') : 'ok', value: logic.residualQty > 1e-6 ? (wholeShareConfirmed ? 'checked' : 'unchecked') : 'whole position' },
          { label: 'Preflight', status: rd.preflight_status === 'approval_present' ? 'ok' : 'warn', value: rd.preflight_status === 'approval_present' ? 'evidence approval present' : 'not run — operator runs dry-run preflight' },
          { label: 'OCO', status: rd.oco_brackets_schwab_off === false ? 'block' : 'ok', value: rd.oco_brackets_schwab_off === false ? 'ON (must be off!)' : 'off' },
          { label: 'Broker submit', status: 'warn', value: 'disabled until per-order 2FA approval' },
        ]
        return (
          <div data-testid="live-stop-readiness" style={{ marginTop: 10, padding: '9px 10px', borderRadius: 8, background: 'rgba(2,6,23,.45)', border: '1px solid rgba(148,163,184,.2)' }}>
            {/* Explicit protective-stop preview — never inferred from the current filter; binds symbol/account/qty/residual. */}
            <div data-testid="canary-target" style={{ marginBottom: 8, padding: '8px 10px', borderRadius: 7, background: 'rgba(59,130,246,.1)', border: `1px solid ${BLUE}55` }}>
              <div style={{ fontSize: 12, color: BLUE, fontWeight: 900, letterSpacing: 0.4, marginBottom: 3 }}>PROTECTIVE STOP PREVIEW — NOT SUBMITTED</div>
              <div style={{ fontSize: 13, color: TEXT0, fontWeight: 800, lineHeight: 1.5 }}>
                Symbol: <b>{sym}</b> · Account: <b>{acct}</b><br />
                Fixed: <b>{orderPreviewLine('STOP')}</b><br />
                {trailPct != null && <>Trail: <b>{orderPreviewLine('TRAILING')}</b><br /></>}
                {selectedKind !== 'STOP' && selectedKind !== 'TRAILING' && (
                  <>Selected: <b>{orderPreviewLine(selectedKind)}</b><br /></>
                )}
                Residual: <b>{logic.residualQty.toFixed(4)} monitored</b>
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
              <div style={{ fontSize: 12, color: MUTED, fontWeight: 900, letterSpacing: 0.3 }}>LIVE STOP READINESS</div>
              <button onClick={e => { e.stopPropagation(); refreshQuote() }} disabled={refreshing}
                title="Fetch the latest available quote (read-only; no broker order is placed)"
                style={{ fontSize: 10, fontWeight: 800, padding: '3px 9px', borderRadius: 5, cursor: refreshing ? 'wait' : 'pointer',
                  border: `1px solid ${BLUE}`, background: `${BLUE}18`, color: BLUE }}>
                {refreshing ? '…' : '↻ Refresh latest quote'}</button>
              {rd.canary_state && (() => {
                const cs = rd.canary_state
                const wholeOk = logic.residualQty <= 1e-6 || wholeShareConfirmed
                const fullReady = cs === 'READY_FOR_OPERATOR' && quoteFresh && wholeOk
                const label = fullReady ? '✅ READY_FOR_OPERATOR' : cs === 'READY_FOR_OPERATOR' ? '⚠️ CONFIRM WHOLE SHARES' : '⛔ BLOCKED — resolve gates'
                const col = fullReady ? GREEN : cs === 'READY_FOR_OPERATOR' ? AMBER : RED
                return (
                  <span data-testid="canary-state" style={{ fontSize: 11, fontWeight: 900, padding: '2px 8px', borderRadius: 999,
                    color: fullReady ? GREEN : AMBER, background: `${col}1e`, border: `1px solid ${fullReady ? GREEN : AMBER}` }}>{label}</span>
                )
              })()}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(210px,1fr))', gap: 4 }}>
              {rows.map(r => (
                <div key={r.label} style={{ fontSize: 11.5, display: 'flex', gap: 6, alignItems: 'baseline', color: r.status === 'block' ? RED : r.status === 'warn' ? AMBER : TEXT0 }}>
                  <span>{ICON(r.status)}</span>
                  <span style={{ color: MUTED }}>{r.label}:</span>
                  <span style={{ fontWeight: 700 }}>{r.value}</span>
                </div>
              ))}
            </div>
            {/* Human-readable readiness message — never a raw parse error. */}
            <div data-testid="readiness-message" style={{ marginTop: 7, fontSize: 11.5, fontWeight: 700,
              color: rd.canary_state === 'READY_FOR_OPERATOR' ? GREEN : RED }}>
              {!quoteParseOk ? 'Quote timestamp could not be parsed; refresh quote.'
                : rd.canary_state === 'READY_FOR_OPERATOR'
                  ? (rd.canary_note || 'GTC stop — valid 24/7 when quote is fresh.')
                  : (rd.canary_blocker || 'Resolve the gates above before requesting a live stop.')}
            </div>
          </div>
        )
      })()}

      {/* Whole-share confirmation — placed IMMEDIATELY above the action buttons so the operator sees exactly
          what unblocks them. When this is the only blocker, checking it enables the Schwab live-stop buttons. */}
      {isSchwab && logic.residualQty > 1e-6 && showProtect && (
        <label
          onClick={e => e.stopPropagation()}
          style={{ marginTop: 10, marginBottom: 2, display: 'flex', gap: 9, alignItems: 'flex-start', fontSize: 13, color: TEXT0,
                   fontWeight: 700, padding: '10px 11px', borderRadius: 8, cursor: 'pointer',
                   background: wholeShareConfirmed ? 'rgba(34,197,94,.12)' : 'rgba(245,158,11,.14)',
                   border: `1px solid ${wholeShareConfirmed ? GREEN : AMBER}` }}>
          <input type="checkbox" checked={wholeShareConfirmed} onChange={e => setWholeShareConfirmed(e.target.checked)}
                 style={{ width: 18, height: 18, marginTop: 1, accentColor: wholeShareConfirmed ? GREEN : AMBER, flexShrink: 0 }} />
          <span>{wholeShareConfirmed ? '✅ ' : '⚠️ '}I confirm this Schwab stop will sell {logic.wholeQty} whole shares of {sym}; residual {logic.residualQty.toFixed(4)} shares remain monitored.</span>
        </label>
      )}

      {pendingAction && preflightDiff && (
        <PreflightChangedPanel
          diff={preflightDiff}
          busy={busy}
          validating={validating}
          onProceed={() => {
            const pa = pendingAction
            setPendingAction(null); setPreflightDiff(null)
            if (pa?.kind === 'request') requestOrder(pa.orderKind, { skipPreflight: true, liveSnap: liveStopOverride ?? effectiveConfirmed })
            else if (pa?.kind === 'confirm') confirmOrder(pa.channel, true)
          }}
          onCancel={() => { setPendingAction(null); setPreflightDiff(null); setMsg('') }}
        />
      )}

      {showProtect && isSchwab && (() => {
        const fb = effectivePr?.family_bounds || {}
        const advTrail = trail?.pct ?? (effectivePr?.suggested_trail_pct != null ? Number(effectivePr.suggested_trail_pct) : null)
        const tMin = fb.trail_min_pct != null ? Number(fb.trail_min_pct) : null
        const tMax = fb.trail_max_pct != null ? Number(fb.trail_max_pct) : null
        const trailVal = numOr(ovTrail)
        const trailOutOfBand = trailVal != null && tMin != null && tMax != null && (trailVal < tMin || trailVal > tMax)
        const field = (label: string, val: string, set: (v: string) => void, ph: string, warn = false, hint = '') => (
          <label style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 10, color: MUTED, fontWeight: 700 }}>
            {label}{hint ? <span style={{ fontWeight: 400 }}> {hint}</span> : null}
            <input value={val} onChange={e => set(e.target.value.replace(/[^0-9.]/g, ''))} placeholder={ph}
              onClick={e => e.stopPropagation()} inputMode="decimal"
              style={{ width: 110, fontSize: 12, fontWeight: 700, padding: '4px 7px', borderRadius: 6,
                       background: 'var(--bg2, #1e293b)', color: TEXT0,
                       border: `1px solid ${warn ? AMBER : 'rgba(148,163,184,.35)'}` }} />
          </label>
        )
        return (
          <div onClick={e => e.stopPropagation()}
               style={{ marginTop: 10, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end',
                        padding: '8px 11px', borderRadius: 8, background: 'rgba(148,163,184,.06)',
                        border: '1px solid rgba(148,163,184,.18)' }}>
            <span style={{ fontSize: 10, color: MUTED, fontWeight: 800, alignSelf: 'center' }}>Order parameters<br />
              <span style={{ fontWeight: 400 }}>blank = advisory</span></span>
            {field('Stop $ (fixed / stop-limit)', ovStop, setOvStop,
                   logic.advisoryStop != null ? logic.advisoryStop.toFixed(2) : '—')}
            {field('Limit $ (stop-limit only)', ovLimit, setOvLimit,
                   numOr(ovStop) != null ? String(numOr(ovStop)!.toFixed(2)) : (logic.advisoryStop != null ? logic.advisoryStop.toFixed(2) : '—'))}
            {field('Trail % (trailing)', ovTrail, setOvTrail,
                   advTrail != null ? String(advTrail) : '—', trailOutOfBand,
                   tMin != null && tMax != null ? `(tier band ${tMin}\u2013${tMax}%)` : '')}
            {trailOutOfBand && (
              <span style={{ fontSize: 10, color: AMBER, fontWeight: 700, flexBasis: '100%' }}>
                ⚠ Trail {trailVal}% is outside the {String(effectivePr?.volatility_tier || logic.familyFloorLabel || 'tier').toUpperCase()} advisory band {tMin}\u2013{tMax}% — allowed, but the advisory disagrees. 2FA still required.
              </span>
            )}
          </div>
        )
      })()}

      {showProtect && (
        <div style={{ marginTop: 8, display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: MUTED, fontWeight: 800 }}>Action:</span>
          {isSchwab && btn(`Apply Fixed Stop (2FA)`, 'STOP', !preferTrail && logic.advisory_stop_is_tighter_than_existing)}
          {isSchwab && (trailPct != null || numOr(ovTrail) != null) && btn(numOr(ovTrail) != null ? `Apply Trailing Stop (2FA)` : `Apply Advisory Trailing Stop (2FA)`, 'TRAILING', preferTrail)}
          {isSchwab && btn('Apply Stop-Limit (2FA)', 'STOP_LIMIT')}
          {(logic.liveStop != null || logic.liveStopIsTrailing) && (
            <button
              onClick={async e => {
                e.stopPropagation()
                const keptLabel = logic.liveStop != null ? `$${logic.liveStop.toFixed(2)}`
                  : logic.liveTrailPct != null ? `${logic.liveTrailPct}% trailing` : 'current stop'
                try {
                  const raw = await fetch('/api/v2/holdings/protective-stop/keep', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ symbol: sym, account: acct, live_stop: logic.liveStop,
                                           live_trail_pct: logic.liveTrailPct,
                                           advised_stop: logic.advisoryStop }),
                  }).then(x => x.json())
                  const r = unwrapApi(raw)
                  setMsg(r?.ok !== false ? `\u2705 Kept ${keptLabel} \u2014 decision recorded` : `\u26d4 ${r?.error || 'keep failed'}`)
                } catch { setMsg('\u26d4 keep request failed') }
              }}
              disabled={busy || validating}
              title="Record that you reviewed the advisory and are keeping the current live stop. No broker action."
              style={{ fontSize: 12, fontWeight: 700, padding: '5px 12px', borderRadius: 6, cursor: 'pointer',
                       border: `1px solid ${MUTED}`, background: 'transparent', color: TEXT0 }}>
              Keep Current Stop
            </button>
          )}
          {/* A disabled Schwab live-stop button is NEVER silent — the reason sits right beside it. */}
          {isSchwab && liveBlocked && disabledReasonHuman && (
            <div data-testid="schwab-stop-disabled-reason"
                 style={{ flexBasis: '100%', fontSize: 12, color: AMBER, fontWeight: 700, marginTop: 4 }}>
              ⛔ Disabled: {disabledReasonHuman}
              {logic.disabledReason === 'fractional_qty' ? ' — check the whole-share confirmation above to enable.' : ''}
            </div>
          )}
          {isFidelity && (
            <button
              onClick={e => { e.stopPropagation(); preflightAndRequest(logic.liveStop != null ? 'STOP_LIMIT' : 'STOP') }}
              disabled={busy || validating || liveBlocked || fidelityReviewDisabled}
              title={liveBlocked ? 'Refresh quote / resolve blockers before creating a Fidelity manual ticket' : 'Generate manual Fidelity ticket only; Trade AI does not submit to Fidelity'}
              style={{
                fontSize: 12, fontWeight: 900, minHeight: 34, padding: '7px 10px', borderRadius: 6,
                border: `1px solid ${PURPLE}`, background: 'rgba(168,85,247,.16)', color: (busy || liveBlocked) ? MUTED : PURPLE,
                cursor: (busy || liveBlocked || fidelityReviewDisabled) ? 'not-allowed' : 'pointer',
              }}
            >{validating ? 'Validating…' : busy ? '…' : fidelityTicketLabel}</button>
          )}
          {brokerUrl && (
            <a href={brokerUrl} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}
              style={{ fontSize: 12, fontWeight: 800, minHeight: 34, display: 'inline-flex', alignItems: 'center', padding: '0 10px', borderRadius: 6, border: `1px solid ${isFidelity ? PURPLE : BLUE}`, background: `${isFidelity ? PURPLE : BLUE}18`, color: isFidelity ? PURPLE : BLUE, textDecoration: 'none' }}>
              {isFidelity ? 'Review Fidelity stop' : 'Open Schwab'} ↗
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
            {(() => {
              const a = advisedForKind(selectedKind)
              const kindLbl = selectedKind === 'TRAILING' && a.trailPct != null
                ? `TRAILING ${trailLabelFor(a.trailPct)}%`
                : selectedKind === 'STOP' && a.advisoryStop != null ? `STOP $${a.advisoryStop.toFixed(2)}` : selectedKind
              return `Order: ${kindLbl} · current ${logic.currentPrice != null ? `$${logic.currentPrice.toFixed(2)}` : 'missing'} · qty ${isSchwab && logic.residualQty > 1e-6 ? logic.wholeQty : qty} · ${acct} · 2FA pending`
            })()}
          </div>
          <div style={{ fontSize: 12, color: MUTED, marginBottom: 6 }}>
            Approve via <b style={{ color: TEXT0 }}>Telegram</b> (auto-submits) or type ticker <b style={{ color: TEXT0 }}>{sym}</b> / 6-digit code here
          </div>
          <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
            <input value={approveTk} onChange={e => setApproveTk(e.target.value.toUpperCase())} placeholder={sym}
              onClick={e => e.stopPropagation()}
              style={{ flex: 1, fontSize: 10, padding: '4px 6px', borderRadius: 4, border: `1px solid ${tkOk ? GREEN : 'rgba(148,163,184,.3)'}`, background: 'rgba(15,23,42,.6)', color: TEXT0 }} />
            <button onClick={e => { e.stopPropagation(); preflightAndConfirm('web') }} disabled={busy || validating || !tkOk}
              style={{ fontSize: 12, fontWeight: 800, minHeight: 34, padding: '4px 10px', borderRadius: 4, border: 'none', cursor: (busy || !tkOk) ? 'not-allowed' : 'pointer', background: tkOk ? AMBER : '#334155', color: tkOk ? '#fff' : MUTED }}>
              approve
            </button>
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            <input value={approveCode} onChange={e => setApproveCode(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="6-digit code" inputMode="numeric"
              onClick={e => e.stopPropagation()}
              style={{ flex: 1, fontSize: 10, padding: '4px 6px', borderRadius: 4, border: `1px solid ${codeOk ? GREEN : 'rgba(148,163,184,.3)'}`, background: 'rgba(15,23,42,.6)', color: TEXT0, letterSpacing: 2, fontFamily: 'monospace' }} />
            <button onClick={e => { e.stopPropagation(); preflightAndConfirm('telegram') }} disabled={busy || validating || !codeOk}
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
        <div style={{ fontSize: 12, color: MUTED, marginTop: 8, lineHeight: 1.5 }}>{protectionExplain(effectivePr, trail, { brokerFixedActive: confirmedIsFixed })}</div>
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

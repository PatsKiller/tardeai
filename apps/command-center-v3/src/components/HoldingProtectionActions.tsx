import { useEffect, useState } from 'react'
import { protectionExplain, resolvedTrailPct } from '../lib/protectionTrail'
import { buildStopLogic, isTrailingBrokerStop, resolveLiveStop, type StopLogic, type StopOrderKind } from '../lib/stopManagement'
import { formatReviewStamp, stopReviewTooltip } from '../lib/stopReviewTooltip'

const MUTED = '#94a3b8', TEXT0 = '#f8fafc', GREEN = '#22c55e', AMBER = '#f59e0b', BLUE = '#60a5fa', PURPLE = '#a855f7', RED = '#ef4444'
const SCHWAB_SELL_ALL_MAX_SHARES = 40
const unwrapApi = (j: any) => (j && typeof j === 'object' && 'data' in j && j.data && typeof j.data === 'object') ? j.data : j
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

type PreflightField<T> = { before: T; after: T }
type PreflightDiff = {
  price?: PreflightField<number | null>
  decision?: PreflightField<string>
  action?: PreflightField<string>
  state?: PreflightField<string>
  advisoryStop?: PreflightField<number | null>
  liveStop?: PreflightField<string>
  blockers?: { added: string[]; removed: string[] }
}

const fmtPx = (v: number | null | undefined) => v != null ? `$${v.toFixed(2)}` : 'none'
const fmtLiveStop = (lg: StopLogic) => lg.liveStopIsTrailing && lg.liveTrailPct != null
  ? `TRAILING ${lg.liveTrailPct}%` + (lg.liveStop != null ? ` (~$${lg.liveStop.toFixed(2)})` : '')
  : lg.liveStop != null ? `$${lg.liveStop.toFixed(2)}` : 'none'

// Material price-move threshold for the "logic changed — re-confirm" gate. A stop is a % offset, so
// sub-% ticks during market hours don't change the protective decision. A tight $0.02 ABSOLUTE threshold
// forced an endless re-confirm loop on any live tick (e.g. V $342.76→$342.39 = 0.1%). 0.4% of price still
// re-confirms on a real move while ignoring noise. Decision/state/blocker diffs below still fire on their own.
const MATERIAL_PRICE_MOVE_PCT = 0.4
function buildPreflightDiff(before: StopLogic, after: StopLogic): PreflightDiff | null {
  const diff: PreflightDiff = {}
  const pxB = before.currentPrice ?? 0
  const pxA = after.currentPrice ?? 0
  if (pxB > 0 && Math.abs(pxB - pxA) / pxB * 100 > MATERIAL_PRICE_MOVE_PCT) {
    diff.price = { before: before.currentPrice, after: after.currentPrice }
  }
  if (before.stop_action_decision !== after.stop_action_decision) {
    diff.decision = { before: before.stop_action_decision, after: after.stop_action_decision }
  }
  if (before.primary_operator_action !== after.primary_operator_action) {
    diff.action = { before: before.primary_operator_action, after: after.primary_operator_action }
  }
  if (before.state !== after.state) diff.state = { before: before.state, after: after.state }
  if (Math.abs((before.advisoryStop ?? 0) - (after.advisoryStop ?? 0)) > 0.02) {
    diff.advisoryStop = { before: before.advisoryStop, after: after.advisoryStop }
  }
  const liveBefore = fmtLiveStop(before)
  const liveAfter = fmtLiveStop(after)
  if (liveBefore !== liveAfter) diff.liveStop = { before: liveBefore, after: liveAfter }
  const bCodes = new Set(before.blockers.map(b => b.code))
  const aCodes = new Set(after.blockers.map(b => b.code))
  const added = after.blockers.filter(b => !bCodes.has(b.code)).map(b => b.message)
  const removed = before.blockers.filter(b => !aCodes.has(b.code)).map(b => b.message)
  if (added.length || removed.length) diff.blockers = { added, removed }
  return Object.keys(diff).length ? diff : null
}

export default function HoldingProtectionActions({ h, pr, monitored, confirmedStop, brokerStopsFetchedAt, onRefresh, onPreflightUpdate }: {
  h: any; pr: any; monitored?: any; confirmedStop?: any; brokerStopsFetchedAt?: string | null
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
  const [afterHoursAck, setAfterHoursAck] = useState(false)
  const [activeApproval, setActiveApproval] = useState<any>(null)
  const [readiness, setReadiness] = useState<any>(null)
  const [refreshedQuote, setRefreshedQuote] = useState<any>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [validating, setValidating] = useState(false)
  const [preflightDiff, setPreflightDiff] = useState<PreflightDiff | null>(null)
  const [advisoryOverride, setAdvisoryOverride] = useState<any>(null)
  const [pendingAction, setPendingAction] = useState<{ kind: 'request'; orderKind: 'STOP' | 'TRAILING' | 'STOP_LIMIT' | 'MARKET' } | { kind: 'confirm'; channel: 'web' | 'telegram' } | null>(null)
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
  const baseQuoteTs = h?.source_timestamp ?? h?.price_as_of ?? h?.quote_at ?? h?.price_timestamp ?? h?.last_repriced ?? ''
  const quoteTsForReadiness = refreshedQuote?.quote_time_normalized ?? baseQuoteTs
  useEffect(() => {
    if (!isSchwab) return
    fetch(`/api/v2/holdings/stop-readiness?symbol=${encodeURIComponent(sym)}&account=${encodeURIComponent(acct)}&quote_at=${encodeURIComponent(String(quoteTsForReadiness))}`)
      .then(x => x.json()).then(j => setReadiness(unwrapApi(j))).catch(() => {})
  }, [isSchwab, sym, acct, quoteTsForReadiness])

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

  /** Click-time preflight: refresh quote, advisory, live broker stop, readiness — recalc before 2FA / manual ticket. */
  const runClickPreflight = async (orderKind: StopOrderKind) => {
    const before = computeLogic(orderKind)
    setValidating(true)
    setPreflightDiff(null)
    setPendingAction(null)
    setMsg('⏳ Validating quote + advisory + stop logic…')
    let quoteSnap: any = null
    let readinessSnap: any = null
    let liveSnap: any = effectiveConfirmed
    let advisorySnap: any = null
    try {
      const qRaw = await fetch('/api/v2/holdings/protective-stop/refresh-quote', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: sym, account: acct, order_kind: orderKind, trail_pct: trailPct }),
      }).then(x => x.json())
      quoteSnap = unwrapApi(qRaw)
      setRefreshedQuote(quoteSnap)
      const qTs = quoteSnap?.quote_time_normalized ?? quoteSnap?.quote_time_raw ?? priceTimestamp
      try {
        const covRaw = await fetch('/api/v2/portfolio/llm-coverage').then(x => x.json())
        const cov = unwrapApi(covRaw)
        advisorySnap = cov?.protection?.[sym] ?? null
        if (advisorySnap) {
          const merged = { ...advisorySnap, price: quoteSnap?.quote_price ?? advisorySnap.price }
          setAdvisoryOverride(merged)
        }
      } catch { /* advisory refresh is best-effort */ }
      if (isSchwab) {
        const rRaw = await fetch(`/api/v2/holdings/stop-readiness?symbol=${encodeURIComponent(sym)}&account=${encodeURIComponent(acct)}&quote_at=${encodeURIComponent(String(qTs ?? ''))}`)
          .then(x => x.json())
        readinessSnap = unwrapApi(rRaw)
        setReadiness(readinessSnap)
      }
      try {
        const lsRaw = await fetch('/api/v2/holdings/live-stops').then(x => x.json())
        const ls = unwrapApi(lsRaw)
        const key = `${sym}:${acct}`
        const row = ls?.by_key?.[key]
        if (row) { liveSnap = row; setLiveStopOverride(row) }
      } catch { /* optional */ }
      const qPx = quoteSnap?.quote_price
      if (qPx != null) {
        const holdingPatch: Record<string, unknown> = {
          current_price: qPx,
          source_timestamp: qTs ?? null,
          price_as_of: qTs ?? null,
        }
        if (qty > 0) holdingPatch.market_value = Number(qPx) * qty
        const protPatch = advisorySnap ? { ...advisorySnap, price: qPx } : undefined
        onPreflightUpdate?.(sym, acct, { holding: holdingPatch, protection: protPatch })
      }
      onRefresh?.()
    } catch (e: any) {
      return { ok: false, error: String(e.message || e).slice(0, 120), before, after: before }
    } finally {
      setValidating(false)
    }
    const qPx = quoteSnap?.quote_price ?? effectivePrice
    const qTs = quoteSnap?.quote_time_normalized ?? quoteSnap?.quote_time_raw ?? priceTimestamp
    const afterPr = advisorySnap ? { ...effectivePr, ...advisorySnap, price: qPx } : { ...effectivePr, price: qPx }
    const after = buildStopLogic({
      h: { ...h, current_price: qPx, price: qPx, source_timestamp: qTs },
      pr: afterPr,
      monitored,
      confirmedStop: liveSnap,
      trailPct,
      orderKind,
      wholeShareConfirmed,
      sourceTimestamp: qTs,
    })
    const quoteBlockers = (quoteSnap?.blockers ?? []) as string[]
    const readinessBlocked = isSchwab && readinessSnap && (
      readinessSnap.quote_parse_ok === false || readinessSnap.quote_fresh === false
      || readinessSnap.canary_state === 'BLOCKED'
    )
    const blockers = [...after.blockers.map(b => b.message)]
    if (quoteBlockers.length) blockers.push(...quoteBlockers)
    if (readinessBlocked && readinessSnap?.canary_blocker) blockers.push(readinessSnap.canary_blocker)
    const hardCodes = new Set(['stale_quote', 'missing_quote', 'source_mismatch', 'stop_not_protective'])
    const ok = isFidelity
      ? !after.blockers.some(b => hardCodes.has(b.code)) && quoteSnap?.ok !== false
      : after.canRequestLive && blockers.length === 0 && quoteSnap?.ok !== false
    const diffObj = buildPreflightDiff(before, after)
    const changed = diffObj != null
    return { ok, before, after, quoteSnap, readinessSnap, liveSnap, advisorySnap, changed, diffObj, blockers }
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

  const requestOrder = async (kind: 'STOP' | 'TRAILING' | 'STOP_LIMIT' | 'MARKET', opts?: { label?: string; skipPreflight?: boolean }) => {
    setSelectedKind(kind)
    const nextLogic = computeLogic(kind)
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
        current_price: effectivePrice,
        source_broker: effectivePr?.source_broker ?? effectivePr?.broker ?? effectivePr?.account ?? effectivePr?.source_account,
        instrument_type: nextLogic.instrumentType,
        quote_at: priceTimestamp ?? advisoryTimestamp,
        whole_share_confirmed: wholeShareConfirmed,
        after_hours_ack: afterHoursAck,
        preflight_at: new Date().toISOString(),
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
    await requestOrder(kind, { ...opts, skipPreflight: true })
  }

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
      if ((r?.stage === 'submit' || submitted || oid) && submitted && r?.ok !== false) {
        setSellAllDone(true)
        setMsg(`✅ LIVE sell placed on Schwab · order #${oid ?? '—'} (${ostatus ?? 'submitted'})`)
        onRefresh?.()
      } else if (r?.stage === 'confirm' && r?.ok && r?.fully_approved === false) {
        setMsg('channel confirmed — waiting on the other factor')
      } else if (r?.mode === 'blocked' || r?.broker_submitted === false) {
        setMsg(`⛔ ${internalBlockMessage(r) ?? apiReason(r)}`)
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
          : !readiness.quote_fresh ? 'Blocked: quote is stale or after-hours freshness is not valid. Refresh latest quote first.'
            : readiness.oco_brackets_schwab_off === false ? 'OCO is ON — must be OFF before any Schwab stop.'
              : (readiness.db_available === false || readiness.evidence_store_available === false) ? 'DB unavailable / evidence store unavailable.'
                : (readiness.execution && readiness.execution.operator_live_via_2fa_allowed === false) ? 'Schwab 2FA live path disabled by execution_state.'
                  : readiness.canary_state === 'READY_FOR_OPERATOR_NEXT_REGULAR_SESSION' ? 'After-hours: restricted to next regular session unless SCHWAB_AFTER_HOURS_STOP_OVERRIDE=1 is enabled and you acknowledge after-hours GTC.'
                    : (readiness.requires_after_hours_ack && !afterHoursAck) ? 'Check the after-hours GTC acknowledgement below to proceed.'
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
        <div title={reviewTip}><span style={{ color: MUTED }}>{isFidelity ? 'Current stop' : 'Broker live stop'}</span><br /><b style={{ color: logic.liveStop != null || logic.liveStopIsTrailing ? GREEN : MUTED }}>{logic.liveStopIsTrailing && logic.liveTrailPct != null ? `TRAILING ${logic.liveTrailPct}%` : logic.liveStop != null ? `$${logic.liveStop.toFixed(2)}` : 'none'}</b>{logic.liveStopIsTrailing && logic.liveStop != null ? ` (~$${logic.liveStop.toFixed(2)} now)` : ''}{logic.liveStopDistancePct != null ? ` (${logic.liveStopDistancePct.toFixed(1)}% below)` : ''}</div>
        <div title={reviewTip}><span style={{ color: MUTED }}>Advisor fixed stop</span><br /><b style={{ color: AMBER }}>{logic.advisoryStop != null ? `$${logic.advisoryStop.toFixed(2)}` : 'none'}</b>{logic.distancePct != null ? ` (${logic.distancePct.toFixed(1)}% below)` : ''}</div>
        <div><span style={{ color: MUTED }}>Optional trail</span><br /><b>{trailPct != null ? `${trailLabel}%` : 'none'}</b>{trailingFloorNow != null ? <span style={{ color: GREEN, fontSize: 11 }}> (≈${trailingFloorNow.toFixed(2)} now)</span> : null}</div>
        <div><span style={{ color: MUTED }}>Family floor/cap</span><br /><b style={{ color: logic.floor_math_consistent ? TEXT0 : RED }}>{logic.familyFloorLabel}</b></div>
        <div><span style={{ color: MUTED }}>Price timestamp</span><br /><b>{String(priceTimestamp ?? 'missing').slice(0, 19)}</b></div>
        <div><span style={{ color: MUTED }}>Advisor timestamp</span><br /><b>{String(advisoryTimestamp ?? 'missing').slice(0, 19)}</b></div>
      </div>

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
      {/* LOCK-IN PROFITS — fixed stop is live, but trailing now locks a HIGHER floor → advise the switch */}
      {lockInTrail && liveFixedStopPx != null && trailingFloorNow != null && (
        <div style={{ fontSize: 11, color: GREEN, fontWeight: 700, marginBottom: 6, padding: '5px 8px', borderRadius: 6, background: `${GREEN}12`, border: `1px solid ${GREEN}45`, lineHeight: 1.45 }}>
          <div style={{ fontWeight: 900, marginBottom: 2 }}>📈 Lock in profits — switch to {trailLabel}% trailing</div>
          A {trailLabel}% trailing stop now sits at <b style={{ fontFamily: 'monospace' }}>${trailingFloorNow.toFixed(2)}</b>
          {' '}— <b>{lockInGapPct != null ? `${lockInGapPct.toFixed(1)}%` : ''}</b> above your live fixed stop
          {' '}<b style={{ fontFamily: 'monospace' }}>${liveFixedStopPx.toFixed(2)}</b>. It keeps ratcheting up as price rises.
          <div style={{ marginTop: 5, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <button
              onClick={e => { e.stopPropagation(); requestOrder('TRAILING') }}
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
        const sessionStatus: 'ok' | 'warn' | 'block' = session === 'regular' ? 'ok' : (session === 'after_hours' || session === 'pre_market') ? 'warn' : 'block'
        const rows: { label: string; status: 'ok' | 'warn' | 'block'; value: string }[] = [
          { label: 'Build', status: 'ok', value: rd.build_marker || 'cc-v3 stop-evidence PR33 2026-06-30' },
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
                Order: <b>SELL {logic.wholeQty} {sym} {selectedKind === 'TRAILING' ? `TRAILING_STOP ${trailLabel}%` : selectedKind} GTC</b><br />
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
                const ackOk = cs !== 'READY_FOR_OPERATOR_AFTER_HOURS_GTC' || afterHoursAck
                const fullReady = (cs === 'READY_FOR_OPERATOR' || cs === 'READY_FOR_OPERATOR_AFTER_HOURS_GTC') && quoteFresh && wholeOk && ackOk
                const label = fullReady
                  ? (cs === 'READY_FOR_OPERATOR_AFTER_HOURS_GTC' ? '✅ READY — AFTER-HOURS GTC' : '✅ READY_FOR_OPERATOR')
                  : cs === 'READY_FOR_OPERATOR_AFTER_HOURS_GTC' ? '⚠️ READY — ACKNOWLEDGE AFTER-HOURS'
                    : cs === 'READY_FOR_OPERATOR_NEXT_REGULAR_SESSION' ? '⚠️ NEXT REGULAR SESSION'
                      : '⛔ BLOCKED — resolve gates'
                const col = fullReady ? GREEN : RED
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
              color: (rd.canary_state === 'READY_FOR_OPERATOR' || rd.canary_state === 'READY_FOR_OPERATOR_AFTER_HOURS_GTC') ? GREEN : RED }}>
              {!quoteParseOk ? 'Quote timestamp could not be parsed; refresh quote.'
                : rd.canary_state === 'READY_FOR_OPERATOR_AFTER_HOURS_GTC'
                  ? (afterHoursAck ? 'After-hours GTC stop — acknowledged. Valid 24/7; rests until triggered.'
                    : (rd.canary_note || 'After-hours GTC stop: valid 24/7. Check the after-hours acknowledgement to proceed.'))
                  : rd.canary_state === 'READY_FOR_OPERATOR' ? 'Quote fresh.'
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

      {/* After-hours acknowledgement — a GTC stop is valid 24/7 (rests until triggered), but after-hours the
          operator must acknowledge that trigger behavior depends on regular-market conditions. */}
      {isSchwab && showProtect && readiness?.requires_after_hours_ack && (
        <label
          onClick={e => e.stopPropagation()}
          style={{ marginTop: 8, marginBottom: 2, display: 'flex', gap: 9, alignItems: 'flex-start', fontSize: 13, color: TEXT0,
                   fontWeight: 700, padding: '10px 11px', borderRadius: 8, cursor: 'pointer',
                   background: afterHoursAck ? 'rgba(34,197,94,.12)' : 'rgba(245,158,11,.14)',
                   border: `1px solid ${afterHoursAck ? GREEN : AMBER}` }}>
          <input type="checkbox" checked={afterHoursAck} onChange={e => setAfterHoursAck(e.target.checked)}
                 style={{ width: 18, height: 18, marginTop: 1, accentColor: afterHoursAck ? GREEN : AMBER, flexShrink: 0 }} />
          <span>{afterHoursAck ? '✅ ' : '⚠️ '}I understand this is an after-hours GTC Schwab protective stop request. The order may rest as GTC, and execution/trigger behavior is governed by Schwab’s order rules. Submit only after per-order 2FA and broker read-back.</span>
        </label>
      )}

      {pendingAction && preflightDiff && (
        <div data-testid="preflight-changed" style={{ marginTop: 10, padding: '10px 11px', borderRadius: 8, background: 'rgba(245,158,11,.12)', border: `1px solid ${AMBER}` }}>
          <div style={{ fontSize: 12, fontWeight: 900, color: AMBER, marginBottom: 6 }}>Logic changed after live validation</div>
          <div data-testid="preflight-diff" style={{ display: 'grid', gap: 5, fontSize: 11.5, color: TEXT0, lineHeight: 1.45 }}>
            {preflightDiff.price && (
              <div><span style={{ color: MUTED, fontWeight: 800 }}>Price: </span>{fmtPx(preflightDiff.price.before)} → <b>{fmtPx(preflightDiff.price.after)}</b></div>
            )}
            {preflightDiff.decision && (
              <div><span style={{ color: MUTED, fontWeight: 800 }}>Decision: </span>{preflightDiff.decision.before.replace(/_/g, ' ')} → <b>{preflightDiff.decision.after.replace(/_/g, ' ')}</b></div>
            )}
            {preflightDiff.state && (
              <div><span style={{ color: MUTED, fontWeight: 800 }}>Status: </span>{preflightDiff.state.before} → <b>{preflightDiff.state.after}</b></div>
            )}
            {preflightDiff.advisoryStop && (
              <div><span style={{ color: MUTED, fontWeight: 800 }}>Advisor stop: </span>{fmtPx(preflightDiff.advisoryStop.before)} → <b>{fmtPx(preflightDiff.advisoryStop.after)}</b></div>
            )}
            {preflightDiff.liveStop && (
              <div><span style={{ color: MUTED, fontWeight: 800 }}>Broker stop: </span>{preflightDiff.liveStop.before} → <b>{preflightDiff.liveStop.after}</b></div>
            )}
            {preflightDiff.action && (
              <div><span style={{ color: MUTED, fontWeight: 800 }}>Recommendation: </span>{preflightDiff.action.before} → <b>{preflightDiff.action.after}</b></div>
            )}
            {preflightDiff.blockers && (preflightDiff.blockers.added.length > 0 || preflightDiff.blockers.removed.length > 0) && (
              <div>
                {preflightDiff.blockers.added.map((m, i) => (
                  <div key={`add-${i}`} style={{ color: RED }}>+ {m}</div>
                ))}
                {preflightDiff.blockers.removed.map((m, i) => (
                  <div key={`rm-${i}`} style={{ color: GREEN }}>− {m}</div>
                ))}
              </div>
            )}
          </div>
          <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <button onClick={e => {
              e.stopPropagation()
              const pa = pendingAction
              setPendingAction(null); setPreflightDiff(null)
              if (pa?.kind === 'request') requestOrder(pa.orderKind, { skipPreflight: true })
              else if (pa?.kind === 'confirm') confirmOrder(pa.channel, true)
            }} disabled={busy || validating}
              style={{ fontSize: 12, fontWeight: 800, padding: '6px 12px', borderRadius: 6, border: `1px solid ${GREEN}`, background: `${GREEN}22`, color: GREEN, cursor: 'pointer' }}>
              Proceed anyway
            </button>
            <button onClick={e => { e.stopPropagation(); setPendingAction(null); setPreflightDiff(null); setMsg('') }}
              style={{ fontSize: 12, fontWeight: 700, padding: '6px 12px', borderRadius: 6, border: '1px solid rgba(148,163,184,.35)', background: 'transparent', color: MUTED, cursor: 'pointer' }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {showProtect && (
        <div style={{ marginTop: 8, display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: MUTED, fontWeight: 800 }}>Action:</span>
          {isSchwab && btn(`Request Schwab fixed stop via 2FA`, 'STOP', !preferTrail && logic.advisory_stop_is_tighter_than_existing)}
          {isSchwab && trailPct != null && btn(`Request Schwab trailing stop via 2FA`, 'TRAILING', preferTrail)}
          {isSchwab && btn('Request Schwab stop-limit via 2FA', 'STOP_LIMIT')}
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
            Formula: current {logic.currentPrice != null ? `$${logic.currentPrice.toFixed(2)}` : 'missing'} · trail {trailPct != null ? `${trailLabel}%` : 'n/a'} · initial stop {logic.advisoryStop != null ? `$${logic.advisoryStop.toFixed(2)}` : 'n/a'} · qty {isSchwab && logic.residualQty > 1e-6 ? logic.wholeQty : qty} · broker Schwab · account {acct} · 2FA pending
          </div>
          <div style={{ fontSize: 12, color: MUTED, marginBottom: 6 }}>Type ticker <b style={{ color: TEXT0 }}>{sym}</b> or 6-digit code (either channel)</div>
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

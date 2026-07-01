import type { StopLogic, StopOrderKind } from './stopManagement'

export const MATERIAL_PRICE_MOVE_PCT = 0.4

export const unwrapApi = (j: any) =>
  (j && typeof j === 'object' && 'data' in j && j.data && typeof j.data === 'object') ? j.data : j

export type PreflightField<T> = { before: T; after: T }
export type PreflightDiff = {
  price?: PreflightField<number | null>
  decision?: PreflightField<string>
  action?: PreflightField<string>
  state?: PreflightField<string>
  advisoryStop?: PreflightField<number | null>
  liveStop?: PreflightField<string>
  blockers?: { added: string[]; removed: string[] }
}

export const fmtPx = (v: number | null | undefined) => v != null ? `$${v.toFixed(2)}` : 'none'
export const fmtLiveStop = (lg: StopLogic) => lg.liveStopIsTrailing && lg.liveTrailPct != null
  ? `TRAILING ${lg.liveTrailPct}%` + (lg.liveStop != null ? ` (~$${lg.liveStop.toFixed(2)})` : '')
  : lg.liveStop != null ? `$${lg.liveStop.toFixed(2)}` : 'none'

export function buildPreflightDiff(before: StopLogic, after: StopLogic): PreflightDiff | null {
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

export type ProtectiveStopPreflightResult = {
  ok: boolean
  before: StopLogic
  after: StopLogic
  quoteSnap: any
  readinessSnap: any
  liveSnap: any
  advisorySnap: any
  changed: boolean
  diffObj: PreflightDiff | null
  blockers: string[]
  error?: string
}

export type ProtectiveStopPreflightParams = {
  sym: string
  acct: string
  orderKind: StopOrderKind
  trailPct: number | null
  isSchwab: boolean
  isFidelity: boolean
  priceTimestamp?: string | null
  effectivePrice?: number | null
  effectiveConfirmed?: any
  computeLogic: (orderKind: StopOrderKind, overrides?: {
    quotePrice?: number | null
    quoteTs?: string | null
    liveStop?: any
    advisorySnap?: any
  }) => StopLogic
}

/** Click-time preflight: refresh quote, advisory, live broker stop, readiness — recalc before 2FA / manual ticket. */
export async function runProtectiveStopPreflight(params: ProtectiveStopPreflightParams): Promise<ProtectiveStopPreflightResult> {
  const {
    sym, acct, orderKind, trailPct, isSchwab, isFidelity,
    priceTimestamp, effectivePrice, effectiveConfirmed, computeLogic,
  } = params
  const before = computeLogic(orderKind)
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
    const qTs = quoteSnap?.quote_time_normalized ?? quoteSnap?.quote_time_raw ?? priceTimestamp
    try {
      const covRaw = await fetch('/api/v2/portfolio/llm-coverage').then(x => x.json())
      const cov = unwrapApi(covRaw)
      advisorySnap = cov?.protection?.[sym] ?? null
    } catch { /* advisory refresh is best-effort */ }
    if (isSchwab) {
      const rRaw = await fetch(`/api/v2/holdings/stop-readiness?symbol=${encodeURIComponent(sym)}&account=${encodeURIComponent(acct)}&quote_at=${encodeURIComponent(String(qTs ?? ''))}`)
        .then(x => x.json())
      readinessSnap = unwrapApi(rRaw)
    }
    try {
      const lsRaw = await fetch('/api/v2/holdings/live-stops').then(x => x.json())
      const ls = unwrapApi(lsRaw)
      const key = `${sym}:${acct}`
      const row = ls?.by_key?.[key]
      if (row) liveSnap = row
    } catch { /* optional */ }
  } catch (e: any) {
    return { ok: false, error: String(e.message || e).slice(0, 120), before, after: before, quoteSnap: null, readinessSnap: null, liveSnap: effectiveConfirmed, advisorySnap: null, changed: false, diffObj: null, blockers: [] }
  }
  const qPx = quoteSnap?.quote_price ?? effectivePrice
  const qTs = quoteSnap?.quote_time_normalized ?? quoteSnap?.quote_time_raw ?? priceTimestamp
  const after = computeLogic(orderKind, { quotePrice: qPx, quoteTs: qTs, liveStop: liveSnap, advisorySnap })
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
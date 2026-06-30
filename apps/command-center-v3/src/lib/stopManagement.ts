export type StopState =
  | 'LIVE BROKER STOP'
  | 'FIDELITY STOP RECORDED — MANUAL'
  | 'FIDELITY STOP VERIFIED'
  | 'ADVISORY ONLY — NOT PLACED'
  | 'MONITORED — SOFTWARE ONLY'
  | 'NOT APPLICABLE'
  | 'SOURCE MISMATCH — BLOCKED'
  | 'ACTION REQUIRED'

export type StopOrderKind = 'STOP' | 'TRAILING' | 'STOP_LIMIT' | 'OCO' | 'MARKET'

export type StopActionDecision =
  | 'KEEP_EXISTING_STOP'
  | 'PLACE_NEW_STOP'
  | 'MODIFY_EXISTING_STOP'
  | 'CONSIDER_TRAILING_STOP'
  | 'MANUAL_REVIEW_REQUIRED'
  | 'NOT_APPLICABLE'
  | 'BLOCKED_STALE_QUOTE'
  | 'BLOCKED_SOURCE_MISMATCH'

export type StopBlocker = {
  code: string
  message: string
}

export type StopLogic = {
  state: StopState
  broker: string
  instrumentType: string
  currentPrice: number | null
  advisoryStop: number | null
  liveStop: number | null
  liveStopDistancePct: number | null
  distancePct: number | null
  familyFloorPct: number | null
  familyFloorLabel: string
  floorMathConsistent: boolean
  wholeQty: number
  residualQty: number
  canRequestLive: boolean
  actionLabel: string
  nextAction: string
  stop_action_decision: StopActionDecision
  action_summary: string
  primary_operator_action: string
  secondary_operator_actions: string[]
  stop_delta_amount: number | null
  stop_delta_pct: number | null
  existing_stop_is_tighter_than_advisory: boolean
  advisory_stop_is_tighter_than_existing: boolean
  floor_math_consistent: boolean
  why: { label: string; value: string }[]
  blockers: StopBlocker[]
  isFundLike: boolean
  // The single highest-priority reason the live-stop request is disabled (null when it can be requested).
  // The UI must surface this on every disabled Schwab action button — a disabled button is never silent.
  disabledReason: string | null
  disabledReasonHuman: string | null
}

// Blocker priority — the first present is the one shown as the primary disabled reason. Whole-share
// confirmation (fractional_qty) is intentionally LAST among hard blockers so a genuine data problem
// (stale quote, source mismatch, non-protective stop) is reported before the operator-confirmable one.
const BLOCKER_PRIORITY = [
  'instrument_not_applicable', 'source_mismatch', 'missing_quote', 'stale_quote',
  'stop_not_protective', 'trail_start_mismatch', 'floor_mismatch', 'fractional_qty',
]

const FUND_SYMBOLS = new Set(['FCNTX', 'SPAXX'])
const LIVE_STOP_KINDS = new Set<StopOrderKind>(['STOP', 'TRAILING', 'STOP_LIMIT', 'OCO'])
const QUOTE_MAX_AGE_SEC = 15 * 60
const TRAIL_TOLERANCE = 0.35
const STOP_MATCH_TOLERANCE_DOLLARS = 0.05
const FLOOR_TOLERANCE_PCT = 0.15

export function accountBroker(account: string): string {
  const a = String(account || '').toLowerCase()
  if (a.startsWith('schwab')) return 'schwab'
  if (a.startsWith('fidelity')) return 'fidelity'
  if (a.startsWith('alpaca')) return 'alpaca'
  return 'unknown'
}

export function normalizeInstrumentType(h: any): string {
  const raw = String(h?.instrument_type ?? h?.asset_type ?? h?.security_type ?? h?.type ?? '').trim()
  const name = String(h?.name ?? h?.description ?? '').toLowerCase()
  const sym = String(h?.symbol ?? '').toUpperCase()
  if (FUND_SYMBOLS.has(sym)) return sym === 'SPAXX' ? 'money_market_fund' : 'mutual_fund'
  if (/money\s*market|sweep|cash equivalent/.test(name)) return 'money_market_fund'
  if (/mutual fund|fund class|fidelity contrafund/.test(name)) return 'mutual_fund'
  if (raw) return raw.toLowerCase().replace(/\s+/g, '_')
  return 'equity'
}

export function isFundLikeInstrument(h: any): boolean {
  const t = normalizeInstrumentType(h)
  return t.includes('mutual_fund') || t.includes('money_market') || t === 'cash'
}

export function quoteAgeSeconds(sourceTimestamp?: string | null, nowMs = Date.now()): number | null {
  if (!sourceTimestamp) return null
  const ts = parseTimestampMs(sourceTimestamp)
  if (!Number.isFinite(ts)) return null
  return Math.max(0, Math.round((nowMs - ts) / 1000))
}

export function parseTimestampMs(sourceTimestamp?: string | null): number {
  if (!sourceTimestamp) return NaN
  const raw = String(sourceTimestamp).trim()
  const direct = Date.parse(raw)
  if (Number.isFinite(direct)) return direct
  const et = raw.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2}(?::\d{2})?)\s+E[DS]?T$/i)
  if (et) {
    const month = Number(et[1].slice(5, 7))
    const offset = month >= 3 && month <= 11 ? '-04:00' : '-05:00'
    return Date.parse(`${et[1]}T${et[2]}${offset}`)
  }
  return NaN
}

export function buildStopLogic(input: {
  h: any
  pr: any
  monitored?: any
  confirmedStop?: any
  trailPct?: number | null
  orderKind?: StopOrderKind
  wholeShareConfirmed?: boolean
  sourceTimestamp?: string | null
  nowMs?: number
}): StopLogic {
  const { h, pr, monitored, confirmedStop, trailPct = null, orderKind = 'STOP', wholeShareConfirmed = false } = input
  const symbol = String(h?.symbol ?? '').toUpperCase()
  const broker = accountBroker(String(h?.account ?? ''))
  const sourceBroker = accountBroker(String(pr?.source_broker ?? pr?.broker ?? pr?.account ?? pr?.source_account ?? h?.stop_source_account ?? ''))
  const currentPrice = finiteNum(pr?.price) ?? finiteNum(h?.current_price) ?? finiteNum(h?.price) ?? null
  const advisoryStop = finiteNum(pr?.stop_price)
  const liveStop = finiteNum(confirmedStop?.stop_price) ?? (monitored?.status === 'armed' ? finiteNum(monitored?.effective_stop ?? monitored?.stop_price) : null)
  const stopVerified = confirmedStop?.source === 'broker' || confirmedStop?.verified === true || confirmedStop?.broker_verified === true
  const qty = Math.max(0, finiteNum(h?.shares) ?? 0)
  const wholeQty = Math.floor(qty)
  const residualQty = Math.max(0, qty - wholeQty)
  const instrumentType = normalizeInstrumentType(h)
  const isFundLike = isFundLikeInstrument(h)
  const blockers: StopBlocker[] = []
  const quoteAge = quoteAgeSeconds(input.sourceTimestamp ?? pr?.source_timestamp ?? pr?.quote_at ?? pr?.at ?? null, input.nowMs)
  const staleQuote = quoteAge == null || quoteAge > QUOTE_MAX_AGE_SEC
  const familyFloorPct = extractFamilyFloorPct(pr)
  const familyFloorLabel = String(pr?.family_floor ?? pr?.floor_label ?? pr?.family ?? 'not provided')

  if (isFundLike) {
    blockers.push({ code: 'instrument_not_applicable', message: `${symbol} is ${instrumentType.replace(/_/g, ' ')}; live stop execution controls are not applicable.` })
  }
  if (sourceBroker !== 'unknown' && broker !== 'unknown' && sourceBroker !== broker) {
    blockers.push({ code: 'source_mismatch', message: `Stop source is ${sourceBroker}, but account broker is ${broker}.` })
  }
  if (currentPrice == null || currentPrice <= 0) {
    blockers.push({ code: 'missing_quote', message: 'Missing current quote; live stop request blocked.' })
  }
  if (staleQuote) {
    blockers.push({ code: 'stale_quote', message: 'Quote is stale or timestamp is missing; refresh price before requesting a live stop.' })
  }
  if (advisoryStop != null && currentPrice != null && advisoryStop >= currentPrice) {
    blockers.push({ code: 'stop_not_protective', message: `Advisory stop $${advisoryStop.toFixed(2)} is at/above current price $${currentPrice.toFixed(2)}.` })
  }
  if (broker === 'schwab' && LIVE_STOP_KINDS.has(orderKind) && residualQty > 1e-6 && !wholeShareConfirmed) {
    blockers.push({
      code: 'fractional_qty',
      message: `Schwab stop orders require whole shares. Suggested: SELL ${wholeQty} ${symbol}. Residual ${residualQty.toFixed(4)} shares remain monitored.`,
    })
  }
  if (orderKind === 'TRAILING' && trailPct != null && currentPrice != null && advisoryStop != null) {
    const expected = currentPrice * (1 - trailPct / 100)
    if (Math.abs(expected - advisoryStop) / currentPrice * 100 > TRAIL_TOLERANCE) {
      blockers.push({
        code: 'trail_start_mismatch',
        message: `Trailing start estimate $${expected.toFixed(2)} does not match advisory stop $${advisoryStop.toFixed(2)} for ${trailPct}% trail.`,
      })
    }
  }

  let state: StopState
  if (isFundLike) state = 'NOT APPLICABLE'
  else if (blockers.some(b => b.code === 'source_mismatch')) state = 'SOURCE MISMATCH — BLOCKED'
  else if (confirmedStop?.stop_price != null && broker === 'fidelity') state = stopVerified ? 'FIDELITY STOP VERIFIED' : 'FIDELITY STOP RECORDED — MANUAL'
  else if (confirmedStop?.stop_price != null) state = 'LIVE BROKER STOP'
  else if (monitored?.status === 'armed') state = 'MONITORED — SOFTWARE ONLY'
  else if (blockers.length) state = 'ACTION REQUIRED'
  else state = 'ADVISORY ONLY — NOT PLACED'

  const distancePct = advisoryStop != null && currentPrice != null && currentPrice > 0
    ? ((currentPrice - advisoryStop) / currentPrice) * 100
    : null
  const liveStopDistancePct = liveStop != null && currentPrice != null && currentPrice > 0
    ? ((currentPrice - liveStop) / currentPrice) * 100
    : null
  const floorMathConsistent = familyFloorPct == null || distancePct == null || distancePct + FLOOR_TOLERANCE_PCT >= familyFloorPct
  if (!floorMathConsistent) {
    blockers.push({
      code: 'floor_mismatch',
      message: `Floor mismatch: displayed stop is inside the ${familyFloorPct.toFixed(1)}% floor.`,
    })
  }

  // Order blockers by priority so the UI lists them most-important-first, and pick the primary reason the
  // live-stop request is disabled (shown on the disabled button itself — never a silent gray-out).
  blockers.sort((a, b) => {
    const ia = BLOCKER_PRIORITY.indexOf(a.code); const ib = BLOCKER_PRIORITY.indexOf(b.code)
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
  })
  const primaryBlocker = blockers[0] ?? null

  const decision = decideStopAction({
    broker,
    advisoryStop,
    liveStop,
    staleQuote,
    isFundLike,
    sourceMismatch: blockers.some(b => b.code === 'source_mismatch'),
    trailPct,
  })
  const actionLabel = broker === 'schwab'
    ? 'Request Schwab stop via 2FA'
    : broker === 'fidelity'
      ? (liveStop != null ? 'Review Fidelity stop' : 'Create Fidelity manual ticket')
      : 'Not applicable'

  return {
    state,
    broker,
    instrumentType,
    currentPrice,
    advisoryStop,
    liveStop,
    liveStopDistancePct,
    distancePct,
    familyFloorPct,
    familyFloorLabel,
    floorMathConsistent,
    wholeQty,
    residualQty,
    canRequestLive: !isFundLike && blockers.length === 0,
    actionLabel,
    nextAction: decision.primary_operator_action,
    stop_action_decision: decision.stop_action_decision,
    action_summary: decision.action_summary,
    primary_operator_action: decision.primary_operator_action,
    secondary_operator_actions: decision.secondary_operator_actions,
    stop_delta_amount: decision.stop_delta_amount,
    stop_delta_pct: decision.stop_delta_pct,
    existing_stop_is_tighter_than_advisory: decision.existing_stop_is_tighter_than_advisory,
    advisory_stop_is_tighter_than_existing: decision.advisory_stop_is_tighter_than_existing,
    floor_math_consistent: floorMathConsistent,
    why: buildWhy(pr, liveStop, advisoryStop, trailPct, decision, familyFloorLabel, floorMathConsistent),
    blockers,
    isFundLike,
    disabledReason: primaryBlocker?.code ?? null,
    disabledReasonHuman: primaryBlocker?.message ?? null,
  }
}

function decideStopAction(input: {
  broker: string
  advisoryStop: number | null
  liveStop: number | null
  staleQuote: boolean
  isFundLike: boolean
  sourceMismatch: boolean
  trailPct: number | null
}): Pick<StopLogic,
  'stop_action_decision' | 'action_summary' | 'primary_operator_action' | 'secondary_operator_actions' |
  'stop_delta_amount' | 'stop_delta_pct' | 'existing_stop_is_tighter_than_advisory' |
  'advisory_stop_is_tighter_than_existing'> {
  const { broker, advisoryStop, liveStop, staleQuote, isFundLike, sourceMismatch, trailPct } = input
  if (isFundLike) {
    return decision('NOT_APPLICABLE', 'Not applicable for live stop execution.', 'Review allocation/rebalance instead.', [], null, null, false, false)
  }
  if (sourceMismatch) {
    return decision('BLOCKED_SOURCE_MISMATCH', 'Stop source does not match the account broker.', 'Resolve source mismatch before action.', [], null, null, false, false)
  }
  if (liveStop != null && advisoryStop != null) {
    const delta = liveStop - advisoryStop
    const deltaAbs = roundMoney(Math.abs(delta))
    const deltaPct = advisoryStop > 0 ? roundPct((delta / advisoryStop) * 100) : null
    const secondary = staleQuote
      ? ['Refresh quote before modifying or placing any order.']
      : trailPct != null
        ? [`Consider ${formatPct(trailPct)} trailing stop only after review.`]
        : []
    if (delta > STOP_MATCH_TOLERANCE_DOLLARS) {
      const action = `Keep existing $${liveStop.toFixed(2)} stop; it is $${deltaAbs.toFixed(2)} tighter than advisor stop.`
      return decision('KEEP_EXISTING_STOP', action, stalePrefix(staleQuote, action), secondary, deltaAbs, deltaPct, true, false)
    }
    if (delta < -STOP_MATCH_TOLERANCE_DOLLARS) {
      const brokerPhrase = broker === 'fidelity' ? 'Create modify ticket' : 'Modify existing stop'
      const action = `Advisor suggests tightening stop from $${liveStop.toFixed(2)} to $${advisoryStop.toFixed(2)}.`
      return decision('MODIFY_EXISTING_STOP', action, stalePrefix(staleQuote, action), [brokerPhrase, ...secondary], deltaAbs, deltaPct, false, true)
    }
    const action = 'Existing stop matches advisor recommendation.'
    return decision('KEEP_EXISTING_STOP', action, stalePrefix(staleQuote, action), secondary, deltaAbs, deltaPct, false, false)
  }
  if (staleQuote) {
    const action = 'Recommendation based on stale quote — refresh required before action.'
    return decision('BLOCKED_STALE_QUOTE', action, action, ['Refresh quote'], null, null, false, false)
  }
  if (advisoryStop != null) {
    const action = broker === 'fidelity'
      ? `Create Fidelity manual ticket for advisor stop $${advisoryStop.toFixed(2)}.`
      : `Place new stop at $${advisoryStop.toFixed(2)}.`
    return decision('PLACE_NEW_STOP', action, action, trailPct != null ? [`Optional ${formatPct(trailPct)} trailing stop review`] : [], null, null, false, false)
  }
  return decision('MANUAL_REVIEW_REQUIRED', 'Manual review required; no actionable stop recommendation.', 'Manual review required.', [], null, null, false, false)
}

function decision(
  stop_action_decision: StopActionDecision,
  action_summary: string,
  primary_operator_action: string,
  secondary_operator_actions: string[],
  stop_delta_amount: number | null,
  stop_delta_pct: number | null,
  existing_stop_is_tighter_than_advisory: boolean,
  advisory_stop_is_tighter_than_existing: boolean,
) {
  return {
    stop_action_decision,
    action_summary,
    primary_operator_action,
    secondary_operator_actions,
    stop_delta_amount,
    stop_delta_pct,
    existing_stop_is_tighter_than_advisory,
    advisory_stop_is_tighter_than_existing,
  }
}

function stalePrefix(staleQuote: boolean, action: string): string {
  return staleQuote ? `Recommendation based on stale quote — refresh required before action. ${action}` : action
}

function buildWhy(pr: any, liveStop: number | null, advisoryStop: number | null, trailPct: number | null, decisionInfo: ReturnType<typeof decideStopAction>, familyFloorLabel: string, floorOk: boolean): { label: string; value: string }[] {
  const anchor = String(pr?.anchor ?? pr?.stop_anchor ?? pr?.support_label ?? '20d swing low')
  const policy = floorOk ? familyFloorLabel : `${familyFloorLabel}; floor mismatch`
  const mode = trailPct != null ? `fixed stop; ${formatPct(trailPct)} trailing optional` : 'fixed stop'
  const reason = liveStop != null && advisoryStop != null
    ? decisionInfo.action_summary
    : String(pr?.reason_short ?? pr?.reason ?? pr?.rationale ?? 'Advisor stop policy')
  return [
    { label: 'Anchor', value: anchor },
    { label: 'Policy', value: policy },
    { label: 'Mode', value: mode },
    { label: 'Reason to act', value: reason },
  ]
}

function extractFamilyFloorPct(pr: any): number | null {
  const direct = finiteNum(pr?.family_floor_pct) ?? finiteNum(pr?.floor_pct) ?? finiteNum(pr?.min_stop_distance_pct)
  if (direct != null) return direct
  const text = String(pr?.family_floor ?? pr?.floor_label ?? pr?.family_floor_label ?? '').toLowerCase()
  const pct = text.match(/(\d+(?:\.\d+)?)\s*%/)
  return pct ? Number(pct[1]) : null
}

function formatPct(v: number): string {
  return Math.abs(v - Math.round(v)) < 0.15 ? `${Math.round(v)}%` : `${v.toFixed(1)}%`
}

function roundMoney(v: number): number {
  return Math.round(v * 100) / 100
}

function roundPct(v: number): number {
  return Math.round(v * 100) / 100
}

function finiteNum(v: any): number | null {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

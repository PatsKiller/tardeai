export type StopState =
  | 'LIVE BROKER STOP'
  | 'FIDELITY STOP RECORDED — MANUAL'
  | 'FIDELITY STOP VERIFIED'
  | 'ADVISORY ONLY — NOT PLACED'
  | 'MONITORED — SOFTWARE ONLY'
  | 'NOT APPLICABLE'
  | 'SOURCE MISMATCH — BLOCKED'
  | 'ACTION REQUIRED'

export type StopOrderKind = 'STOP' | 'TRAILING' | 'TRAILING_LIMIT' | 'STOP_LIMIT' | 'OCO' | 'MARKET'

/** Normalize a live broker order_type + trailing flag into a pill kind
 *  (FIXED / STOP_LIMIT / TRAILING / TRAILING_LIMIT / MONITORED / PLANNED / NONE).
 *  Single source shared by the Stop Management desk and the Holdings table; mirrors
 *  the server-side derivation in api_v2.py. */
export function deriveStopKind(opts: {
  orderType?: string | null; isTrailing?: boolean | null; hasLiveStop?: boolean | null
  monitored?: boolean | null; planned?: boolean | null
}): string {
  const ot = String(opts.orderType || '').toUpperCase()
  const hasLimit = ot.includes('LIMIT')
  if (opts.isTrailing) return hasLimit ? 'TRAILING_LIMIT' : 'TRAILING'
  if (opts.hasLiveStop) return hasLimit ? 'STOP_LIMIT' : 'FIXED'
  if (opts.monitored) return 'MONITORED'
  if (opts.planned) return 'PLANNED'
  return 'NONE'
}

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

export type LiveStopResolution = {
  price: number | null
  isTrailing: boolean
  trailPct: number | null
  hasLiveBrokerOrder: boolean
}

export type StopLogic = {
  state: StopState
  broker: string
  instrumentType: string
  currentPrice: number | null
  advisoryStop: number | null
  liveStop: number | null
  liveStopIsTrailing: boolean
  liveTrailPct: number | null
  liveStopDistancePct: number | null
  distancePct: number | null
  familyFloorPct: number | null
  familyFloorLabel: string
  volatilityTier: string | null      // low | medium | high (dynamic beta/ATR/yield classification)
  regime: string | null              // risk_on | risk_off | neutral posture at advisory time
  regimeAdjustmentPct: number | null // +widen / -tighten applied to the band cap by regime
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
const LIVE_STOP_KINDS = new Set<StopOrderKind>(['STOP', 'TRAILING', 'TRAILING_LIMIT', 'STOP_LIMIT', 'OCO'])
/** Match brokers/quote_time.py — regular 15m; extended 60m; closed/overnight 18h (GTC rests until RTH). */
const FRESH_MAX_AGE_SEC = 15 * 60
const AFTER_HOURS_MAX_AGE_SEC = 60 * 60
const CLOSED_MAX_AGE_SEC = 18 * 60 * 60
// Tolerance (% of price) between a trailing stop's start (current × (1−trail%)) and the advised FIXED stop.
// These use different methodologies — the fixed stop is swing-low-anchored while the trail is a whole-number
// % — so they legitimately differ by (|swing-low-dist% − trail%|) + price drift since the advisory ran
// (commonly 1–3%). 0.35% falsely blocked the advisor's own recommended trail (e.g. V: 10% trail start
// $307.49 vs swing-low stop $309.00 = 0.44%). 3% still catches a grossly-wrong trail (e.g. 20% vs 10%).
const TRAIL_TOLERANCE = 3.0
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

export type QuoteSession = 'regular' | 'pre_market' | 'after_hours' | 'closed' | 'unknown'

export function quoteAgeSeconds(sourceTimestamp?: string | null, nowMs = Date.now()): number | null {
  if (!sourceTimestamp) return null
  const ts = parseTimestampMs(sourceTimestamp)
  if (!Number.isFinite(ts)) return null
  return Math.max(0, Math.round((nowMs - ts) / 1000))
}

/** US-equity session for the quote time (America/New_York) — mirrors scripts/brokers/quote_time.py. */
export function classifyQuoteSession(sourceTimestamp?: string | null): QuoteSession {
  const ms = parseTimestampMs(sourceTimestamp)
  if (!Number.isFinite(ms)) return 'unknown'
  const wd = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short' }).format(new Date(ms))
  if (wd === 'Sat' || wd === 'Sun') return 'closed'
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: 'numeric', hour12: false }).formatToParts(new Date(ms))
  const hour = Number(parts.find(p => p.type === 'hour')?.value ?? 0)
  const minute = Number(parts.find(p => p.type === 'minute')?.value ?? 0)
  const mins = hour * 60 + minute
  if (mins >= 9 * 60 + 30 && mins < 16 * 60) return 'regular'
  if (mins >= 4 * 60 && mins < 9 * 60 + 30) return 'pre_market'
  if (mins >= 16 * 60 && mins < 20 * 60) return 'after_hours'
  return 'closed'
}

export function freshMaxAgeSec(session: QuoteSession): number {
  if (session === 'after_hours' || session === 'pre_market') return AFTER_HOURS_MAX_AGE_SEC
  if (session === 'closed') return CLOSED_MAX_AGE_SEC
  return FRESH_MAX_AGE_SEC
}

/** Session for *now* (operator arming time) — mirrors brokers/quote_time.current_session. */
export function currentQuoteSession(nowMs = Date.now()): QuoteSession {
  return classifyQuoteSession(new Date(nowMs).toISOString())
}

export function isQuoteFresh(sourceTimestamp?: string | null, nowMs = Date.now()): boolean {
  const age = quoteAgeSeconds(sourceTimestamp, nowMs)
  if (age === null) return false
  // Window follows current clock session, not print session (AH print usable overnight for GTC).
  return age <= freshMaxAgeSec(currentQuoteSession(nowMs))
}

export function isTrailingBrokerStop(stop?: any, monitored?: any): boolean {
  if (!stop && !monitored) return false
  const ot = String(stop?.order_type ?? stop?.orderType ?? monitored?.order_type ?? '').toUpperCase()
  if (ot.includes('TRAILING')) return true
  if (finiteNum(stop?.trail_offset) != null || finiteNum(stop?.trail_pct) != null) return true
  if (finiteNum(monitored?.trail_offset) != null || finiteNum(monitored?.trail_pct) != null) return true
  return /trailing|trail\s+\d/i.test(String(stop?.note ?? ''))
}

export function hasLiveBrokerStopOrder(stop?: any, monitored?: any): boolean {
  if (!stop && !monitored) return false
  if (stop?.source === 'broker' || stop?.source === 'fidelity_manual' || stop?.verified === true || stop?.broker_verified === true) return true
  if (isTrailingBrokerStop(stop, monitored)) return true
  if (finiteNum(stop?.stop_price) != null) return true
  if (String(stop?.order_id ?? '').trim()) return true
  return false
}

/** Resolve the effective live stop for display/decisions — fixed price, trailing estimate, or monitored level. */
export function resolveLiveStop(
  confirmedStop?: any,
  monitored?: any,
  currentPrice?: number | null,
): LiveStopResolution {
  const trailing = isTrailingBrokerStop(confirmedStop, monitored)
  const trailPct = finiteNum(confirmedStop?.trail_offset)
    ?? finiteNum(confirmedStop?.trail_pct)
    ?? finiteNum(monitored?.trail_offset)
    ?? finiteNum(monitored?.trail_pct)
  const fixedPrice = finiteNum(confirmedStop?.stop_price)
  const hasLiveBrokerOrder = hasLiveBrokerStopOrder(confirmedStop, monitored)

  if (trailing) {
    const est = trailPct != null && currentPrice != null && currentPrice > 0
      ? currentPrice * (1 - trailPct / 100)
      : fixedPrice
    return { price: est, isTrailing: true, trailPct, hasLiveBrokerOrder }
  }
  if (fixedPrice != null) {
    return { price: fixedPrice, isTrailing: false, trailPct: null, hasLiveBrokerOrder }
  }
  if (monitored?.status === 'armed') {
    return {
      price: finiteNum(monitored?.effective_stop ?? monitored?.stop_price),
      isTrailing: false,
      trailPct: null,
      hasLiveBrokerOrder: false,
    }
  }
  return { price: null, isTrailing: false, trailPct: null, hasLiveBrokerOrder }
}

export function parseTimestampMs(sourceTimestamp?: string | null): number {
  if (!sourceTimestamp) return NaN
  const raw = String(sourceTimestamp).trim()
  // Portfolio/Finviz quotes are America/New_York — parse naive "YYYY-MM-DD HH:MM:SS" as ET, not browser-local/UTC.
  const naiveEt = raw.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2}(?::\d{2})?)(\s+E[DS]?T)?$/i)
  if (naiveEt) {
    const month = Number(naiveEt[1].slice(5, 7))
    const offset = month >= 3 && month <= 11 ? '-04:00' : '-05:00'
    const parsed = Date.parse(`${naiveEt[1]}T${naiveEt[2]}${offset}`)
    if (Number.isFinite(parsed)) return parsed
  }
  const direct = Date.parse(raw.replace('Z', '+00:00'))
  if (Number.isFinite(direct)) return direct
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
  // Prefer the LIVE holdings price over pr.price. On the Holdings table pr is the advisory/technicals
  // snapshot (e.g. 07:59), so a stale pr.price made the TRAILING estimate price×(1−trail%) drift from
  // the live Stop desk (ANET showed $169.63 off the 07:59 price vs the desk's $163.55 off the live
  // price — and the pill %, distance and "if fired" P/L inherited the drift). The placement UI
  // (HoldingProtectionActions) sets pr.price === h.current_price, so this reordering is a no-op there
  // and only corrects the stale-snapshot case. Fixed stops use a static stop_price and are unaffected.
  const currentPrice = finiteNum(h?.current_price) ?? finiteNum(h?.price) ?? finiteNum(pr?.price) ?? null
  const familyFloorPctRaw = extractFamilyFloorPct(pr)
  const rawAdvisoryStop = finiteNum(pr?.stop_price)
  // Family-floor reconciliation: a FIXED advised stop is frozen at advisory time. If price has since
  // drifted DOWN, an income stop that was 4% wide can now sit INSIDE the floor (e.g. JEPI $54.22 was 4%
  // below the advisory-day price, now 3.6% below current). The methodology says respect the floor, so
  // WIDEN the effective advised stop to the family floor against the CURRENT price instead of hard-
  // blocking. Only ever widens (lowers a long stop), never tightens. Mirrors holding_protection_advisor's
  // run-time floor enforcement, applied live so intraday drift doesn't dead-end placement.
  const _floorLevelStop = (familyFloorPctRaw != null && currentPrice != null && currentPrice > 0)
    ? Number((currentPrice * (1 - familyFloorPctRaw / 100)).toFixed(2)) : null
  const advisoryStopWidenedToFloor = rawAdvisoryStop != null && _floorLevelStop != null
    && rawAdvisoryStop > _floorLevelStop + 0.01
  const advisoryStop = advisoryStopWidenedToFloor ? _floorLevelStop : rawAdvisoryStop
  const liveResolved = resolveLiveStop(confirmedStop, monitored, currentPrice)
  const liveStop = liveResolved.price
  const stopVerified = confirmedStop?.source === 'broker' || confirmedStop?.verified === true || confirmedStop?.broker_verified === true
  const qty = Math.max(0, finiteNum(h?.shares) ?? 0)
  const wholeQty = Math.floor(qty)
  const residualQty = Math.max(0, qty - wholeQty)
  const instrumentType = normalizeInstrumentType(h)
  const isFundLike = isFundLikeInstrument(h)
  const blockers: StopBlocker[] = []
  const quoteTs = input.sourceTimestamp ?? input.h?.source_timestamp ?? pr?.source_timestamp ?? pr?.quote_at ?? pr?.at ?? null
  const quoteSession = classifyQuoteSession(quoteTs)
  const quoteMaxAge = freshMaxAgeSec(currentQuoteSession(input.nowMs))
  const quoteAge = quoteAgeSeconds(quoteTs, input.nowMs)
  const staleQuote = !isQuoteFresh(quoteTs, input.nowMs)
  const familyFloorPct = familyFloorPctRaw
  const familyFloorLabel = advisoryStopWidenedToFloor
    ? `${String(pr?.family_floor ?? pr?.floor_label ?? pr?.family ?? 'family')} — advised stop widened to the ${familyFloorPct?.toFixed(1)}% floor (was inside it after price drift)`
    : String(pr?.family_floor ?? pr?.floor_label ?? pr?.family ?? 'not provided')

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
    const ageNote = quoteAge != null ? `${Math.round(quoteAge / 60)}m old` : 'timestamp missing/unparseable'
    const nowSession = currentQuoteSession(input.nowMs)
    const nowMax = freshMaxAgeSec(nowSession)
    const winNote = `${nowMax / 60}m ${nowSession.replace('_', ' ')} window`
    blockers.push({
      code: 'stale_quote',
      message: `Quote is outside the ${winNote} (${ageNote}); refresh price before requesting a live stop.`,
    })
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
    // The initial trigger of an X% trailing order is, by definition, X% below the current price —
    // internally consistent. advisoryStop is the SEPARATE fixed fallback (swing-low anchored, family-
    // floor capped), so when the swing low sits far from price the two legitimately diverge (e.g. ARKG:
    // 8% trail start $39.65 vs $37.01 fixed floor). Only flag when the trail start is materially LOOSER
    // (further below) than the advisory floor — that means the trail% gives less protection than the
    // advisor intends. A trail start AT/ABOVE the floor is tighter protection and always safe.
    const expected = currentPrice * (1 - trailPct / 100)
    const looserThanFloorPct = ((advisoryStop - expected) / currentPrice) * 100
    if (looserThanFloorPct > TRAIL_TOLERANCE) {
      blockers.push({
        code: 'trail_start_mismatch',
        message: `Trailing start estimate $${expected.toFixed(2)} is more than ${TRAIL_TOLERANCE}% below the advisory floor $${advisoryStop.toFixed(2)} for a ${trailPct}% trail — the trail is looser than the advised stop.`,
      })
    }
  }

  let state: StopState
  if (isFundLike) state = 'NOT APPLICABLE'
  else if (blockers.some(b => b.code === 'source_mismatch')) state = 'SOURCE MISMATCH — BLOCKED'
  else if (liveResolved.hasLiveBrokerOrder && broker === 'fidelity') state = stopVerified ? 'FIDELITY STOP VERIFIED' : 'FIDELITY STOP RECORDED — MANUAL'
  else if (liveResolved.hasLiveBrokerOrder) state = 'LIVE BROKER STOP'
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
    liveStopIsTrailing: liveResolved.isTrailing,
    liveTrailPct: liveResolved.trailPct,
    liveStopDistancePct,
    distancePct,
    familyFloorPct,
    familyFloorLabel,
    volatilityTier: (pr?.volatility_tier ?? null) as string | null,
    regime: (pr?.regime ?? null) as string | null,
    regimeAdjustmentPct: pr?.regime_adjustment_pct != null ? Number(pr.regime_adjustment_pct) : null,
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
  const bounds = pr?.family_bounds
  const direct = finiteNum(pr?.family_floor_pct)
    ?? finiteNum(bounds?.stop_min_pct)
    ?? finiteNum(pr?.floor_pct)
    ?? finiteNum(pr?.min_stop_distance_pct)
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

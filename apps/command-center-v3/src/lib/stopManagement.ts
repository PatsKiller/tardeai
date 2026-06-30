export type StopState =
  | 'LIVE BROKER STOP'
  | 'ADVISORY ONLY — NOT PLACED'
  | 'MONITORED — SOFTWARE ONLY'
  | 'NOT APPLICABLE'
  | 'SOURCE MISMATCH — BLOCKED'
  | 'ACTION REQUIRED'

export type StopOrderKind = 'STOP' | 'TRAILING' | 'STOP_LIMIT' | 'OCO' | 'MARKET'

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
  distancePct: number | null
  wholeQty: number
  residualQty: number
  canRequestLive: boolean
  actionLabel: string
  nextAction: string
  blockers: StopBlocker[]
  isFundLike: boolean
}

const FUND_SYMBOLS = new Set(['FCNTX', 'SPAXX'])
const LIVE_STOP_KINDS = new Set<StopOrderKind>(['STOP', 'TRAILING', 'STOP_LIMIT', 'OCO'])
const QUOTE_MAX_AGE_SEC = 15 * 60
const TRAIL_TOLERANCE = 0.35

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
  const ts = Date.parse(sourceTimestamp)
  if (!Number.isFinite(ts)) return null
  return Math.max(0, Math.round((nowMs - ts) / 1000))
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
  const qty = Math.max(0, finiteNum(h?.shares) ?? 0)
  const wholeQty = Math.floor(qty)
  const residualQty = Math.max(0, qty - wholeQty)
  const instrumentType = normalizeInstrumentType(h)
  const isFundLike = isFundLikeInstrument(h)
  const blockers: StopBlocker[] = []
  const quoteAge = quoteAgeSeconds(input.sourceTimestamp ?? pr?.source_timestamp ?? pr?.quote_at ?? pr?.at ?? null, input.nowMs)

  if (isFundLike) {
    blockers.push({ code: 'instrument_not_applicable', message: `${symbol} is ${instrumentType.replace(/_/g, ' ')}; live stop execution controls are not applicable.` })
  }
  if (sourceBroker !== 'unknown' && broker !== 'unknown' && sourceBroker !== broker) {
    blockers.push({ code: 'source_mismatch', message: `Stop source is ${sourceBroker}, but account broker is ${broker}.` })
  }
  if (currentPrice == null || currentPrice <= 0) {
    blockers.push({ code: 'missing_quote', message: 'Missing current quote; live stop request blocked.' })
  }
  if (quoteAge == null || quoteAge > QUOTE_MAX_AGE_SEC) {
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
  else if (confirmedStop?.stop_price != null) state = 'LIVE BROKER STOP'
  else if (monitored?.status === 'armed') state = 'MONITORED — SOFTWARE ONLY'
  else if (blockers.length) state = 'ACTION REQUIRED'
  else state = 'ADVISORY ONLY — NOT PLACED'

  const distancePct = advisoryStop != null && currentPrice != null && currentPrice > 0
    ? ((currentPrice - advisoryStop) / currentPrice) * 100
    : null
  const actionLabel = broker === 'schwab'
    ? 'Request Schwab stop'
    : broker === 'fidelity'
      ? 'Manual Fidelity ticket'
      : 'Not applicable'
  const nextAction = isFundLike
    ? 'Not applicable; advisory monitoring only'
    : broker === 'schwab'
      ? (blockers.length ? 'Resolve blockers before requesting Schwab stop' : 'Request Schwab stop')
      : broker === 'fidelity'
        ? 'Manual Fidelity ticket'
        : 'Not applicable'

  return {
    state,
    broker,
    instrumentType,
    currentPrice,
    advisoryStop,
    liveStop,
    distancePct,
    wholeQty,
    residualQty,
    canRequestLive: !isFundLike && blockers.length === 0,
    actionLabel,
    nextAction,
    blockers,
    isFundLike,
  }
}

function finiteNum(v: any): number | null {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

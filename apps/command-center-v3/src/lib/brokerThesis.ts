/** Thesis validity / drift gap helpers for broker proposals */

export type ThesisValidity = {
  ok?: boolean
  label?: string
  valid_low?: number
  valid_high?: number
  entry?: number
  stop?: number
  target?: number
  current_price?: number | null
  drift_pct?: number | null
  current_rr?: number | null
  planned_rr?: number | null
  room_up_pct?: number | null
  room_down_pct?: number | null
  zone_status?: string
  zone_color?: string
  reasons?: string[]
  actionable?: boolean
  price_stale?: boolean
  price_age_min?: number | null
  price_as_of?: string | null
  price_source?: string
  stale_display_price?: number
}

const ZONE_COLORS: Record<string, string> = {
  green: '#22c55e',
  yellow: '#f59e0b',
  red: '#ef4444',
  gray: '#94a3b8',
}

export function zoneColor(status?: string, fallback?: string): string {
  if (fallback && ZONE_COLORS[fallback]) return ZONE_COLORS[fallback]
  const s = String(status || '').toLowerCase()
  if (s === 'comfortable') return ZONE_COLORS.green
  if (s === 'approaching') return ZONE_COLORS.yellow
  if (s === 'at_risk' || s === 'invalid') return ZONE_COLORS.red
  if (s === 'stale_price') return ZONE_COLORS.gray
  return ZONE_COLORS.gray
}

export function brokerOf(accountKey: string): 'Schwab' | 'Fidelity' | '—' {
  const k = (accountKey || '').toLowerCase()
  if (k.startsWith('fidelity')) return 'Fidelity'
  if (k.startsWith('schwab')) return 'Schwab'
  return '—'
}

export function fmtMoney(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}k`
  return `$${Math.round(n)}`
}

export type OversightPacket = {
  status?: string
  violations?: string[]
  warnings?: string[]
  agents?: { pending?: string[]; reviews?: any[] }
  local_llm?: { status?: string; model?: string }
  cloud_review?: {
    status?: string
    ran_at?: string
    consensus?: { verdict?: string; lanes_ok?: number }
    lanes?: Record<string, any>
    cached?: boolean
    fresh_run?: boolean
  }
  lanes_available?: { grok?: boolean; chatgpt?: boolean }
}

function oversightCloudTs(ov?: OversightPacket | null): number {
  const ran = ov?.cloud_review?.ran_at
  if (!ran) {
    const st = String(ov?.cloud_review?.status || '').toLowerCase()
    return st && st !== 'not_run' && st !== 'unknown' ? 1 : 0
  }
  const s = String(ran).trim()
  const iso = s.includes('T') ? s : s.replace(' ', 'T')
  const hasTz = /[zZ]$/.test(iso) || /[+-]\d{2}:\d{2}$/.test(iso)
  const t = Date.parse(hasTz ? iso : `${iso}Z`)
  return Number.isNaN(t) ? 0 : t
}

/** Prefer newest cloud_review.ran_at across list row, detail prefetch, and post-run updates. */
export function pickFreshOversight(...sources: Array<OversightPacket | null | undefined>): OversightPacket {
  let best: OversightPacket = {}
  let bestTs = -1
  for (const src of sources) {
    if (!src || typeof src !== 'object') continue
    const ts = oversightCloudTs(src)
    const weight = ts > 0 ? ts : (src.status ? 1 : 0)
    if (weight > bestTs) {
      best = src
      bestTs = weight
    }
  }
  if (bestTs < 0) {
    for (const src of sources) {
      if (src && Object.keys(src).length) return src
    }
  }
  return best
}

export function formatCloudRanAt(ranAt?: string | null): { label: string; ageMin: number | null; stale: boolean } {
  if (!ranAt) return { label: 'no timestamp', ageMin: null, stale: true }
  const raw = String(ranAt).trim()
  const iso = raw.includes('T') ? raw : raw.replace(' ', 'T')
  const hasTz = /[zZ]$/.test(iso) || /[+-]\d{2}:\d{2}$/.test(iso)
  let ms = Date.parse(hasTz ? iso : `${iso}Z`)
  if (Number.isNaN(ms)) return { label: raw, ageMin: null, stale: true }
  const ageMin = Math.max(0, Math.round((Date.now() - ms) / 60_000))
  const stale = ageMin > 24 * 60
  let age = ''
  if (ageMin < 2) age = 'just now'
  else if (ageMin < 60) age = `${ageMin}m ago`
  else if (ageMin < 24 * 60) age = `${Math.floor(ageMin / 60)}h ago`
  else age = `${Math.floor(ageMin / (24 * 60))}d ago`
  const et = new Date(ms).toLocaleString('en-US', {
    timeZone: 'America/New_York',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
  return {
    label: `${et} ET · ${age}${stale ? ' · stale' : ''}`,
    ageMin,
    stale,
  }
}

export function localLlmLabel(status?: string | null): string {
  const s = String(status || '').toLowerCase()
  if (s === 'watchlist_plan') return 'watchlist plan'
  if (s === 'complete') return 'complete'
  if (s === 'queued') return 'queued'
  if (s === 'missing') return 'missing'
  if (s === 'error') return 'error'
  return status || 'unknown'
}

export function tradeEconomics(shares: number, entry: number, stop: number, target: number) {
  const sh = Number(shares) || 0
  const en = Number(entry) || 0
  const st = Number(stop) || 0
  const tg = Number(target) || 0
  const riskPs = Math.max(0, en - st)
  const rewardPs = Math.max(0, tg - en)
  return {
    shares: sh,
    investment: sh && en ? sh * en : null,
    max_risk: sh && riskPs ? riskPs * sh : null,
    profit_at_target: sh && rewardPs ? rewardPs * sh : null,
  }
}

export type LiveQuote = {
  price: number | null
  driftPct: number | null
  stale: boolean
  label: 'Live' | 'Last'
  provider?: string
}

/** Best available quote for broker cards — list live quote beats stale DB price. */
export type TickerContext = {
  strategyDisplay: string
  strategyTypeLabel?: string | null
  strategyPurpose?: string | null
  sector?: string | null
  industry?: string | null
  instrumentType?: string | null
  signalGrade?: string | null
  companyLine?: string | null
}

export function resolveTickerContext(proposal: Record<string, any> | null | undefined, intel?: any): TickerContext {
  const co = intel?.company || {}
  const st = intel?.strategy || {}
  const tech = intel?.technicals || {}
  const why = intel?.why_purchase || {}
  const desc = co.description || proposal?.company_description
  let companyLine: string | null = null
  if (desc) {
    const s = String(desc).trim()
    const dot = s.search(/[.!?]/)
    companyLine = (dot > 20 ? s.slice(0, dot + 1) : s.slice(0, 140)).trim()
  }
  return {
    strategyDisplay: proposal?.strategy_display_name || st.display_name || proposal?.strategy_id || '—',
    strategyTypeLabel: proposal?.strategy_type_label || st.strategy_type_label || proposal?.strategy_type || null,
    strategyPurpose: proposal?.strategy_description || st.purpose || why.strategy_purpose || null,
    sector: proposal?.sector || co.sector || null,
    industry: proposal?.industry || co.industry || null,
    instrumentType: proposal?.instrument_type || co.instrument_type || null,
    signalGrade: tech.grade || why.signal_grade || null,
    companyLine,
  }
}

export function resolveLiveQuote(proposal: {
  thesis_validity?: ThesisValidity | null
  quote_last?: number | null
  current_price?: number | null
  price_drift_pct?: number | null
  price_stale?: boolean
  quote_provider?: string
} | null | undefined): LiveQuote {
  const tv = proposal?.thesis_validity
  const raw = tv?.current_price ?? proposal?.quote_last ?? proposal?.current_price
  const price = raw != null && !Number.isNaN(Number(raw)) ? Number(raw) : null
  const driftRaw = tv?.drift_pct ?? proposal?.price_drift_pct
  const driftPct = driftRaw != null && !Number.isNaN(Number(driftRaw)) ? Number(driftRaw) : null
  const stale = Boolean(tv?.price_stale ?? proposal?.price_stale)
  return {
    price,
    driftPct,
    stale,
    label: stale ? 'Last' : 'Live',
    provider: proposal?.quote_provider || tv?.price_source,
  }
}
/** Format holdings pricing freshness for the v3 header / portfolio strip. */

export type PricingMeta = {
  last_repriced?: string
  reprice_source?: string
  finviz_cache_updated?: string
  market_quotes_as_of?: string
  enrichment_as_of?: string
  price_sources?: Record<string, number>
  note?: string
}

const SRC_LABEL: Record<string, string> = {
  finviz_live: 'Finviz live',
  finviz_afterhours: 'Finviz after-hours',
  finviz_premarket: 'Finviz pre-market',
  finviz_overnight: 'Finviz overnight',
  schwab: 'Schwab sync',
  market_quotes: 'Market quotes',
  finviz: 'Finviz',
  holdings: 'Holdings file',
  snaptrade: 'SnapTrade (laggy)',
  technical_snapshot: 'Technical snapshot',
  cash_unit: 'Cash balances',
}

// Provider segment of a `source:provider` price key.
const PROVIDER_LABEL: Record<string, string> = {
  alpaca: 'Alpaca',
  yfinance: 'Yahoo',
  polygon: 'Polygon',
  schwab: 'Schwab',
  finviz: 'Finviz',
}

/**
 * FQ-050 (2026-11-04): the price line used to print the internal key
 * `data_broker.market_quotes:alpaca` as "data broker.market quotes:alpaca". The face is operator
 * words ("Alpaca quotes"); the raw key stays recoverable in the `title` of the stamp.
 */
export function priceSourceLabel(src?: string): string {
  if (!src) return '—'
  const known = SRC_LABEL[src]
  if (known) return known
  const [baseRaw, providerRaw] = String(src).split(':')
  const base = baseRaw.replace(/^(data_broker|broker)\./, '')
  const baseLabel = SRC_LABEL[base] ?? base.replace(/_/g, ' ')
  if (!providerRaw) return baseLabel
  const provider = PROVIDER_LABEL[providerRaw.toLowerCase()]
    ?? providerRaw.charAt(0).toUpperCase() + providerRaw.slice(1)
  // "Market quotes" + Alpaca reads as "Alpaca quotes"; any other base keeps the provider in front.
  if (base === 'market_quotes') return `${provider} quotes`
  return `${provider} · ${baseLabel.charAt(0).toLowerCase()}${baseLabel.slice(1)}`
}

/** Parse server stamps like "2026-06-23 09:55:54 ET" or ISO. */
export function formatPricingTime(raw?: string | null): string | null {
  if (!raw) return null
  const s = String(raw).trim()
  if (/ ET$/.test(s)) {
    const m = s.match(/(\d{1,2}):(\d{2})/)
    if (m) return `${m[1]}:${m[2]} ET`
    return s.replace(/.*(\d{4}-\d{2}-\d{2})\s+/, '').replace(' ET', ' ET')
  }
  try {
    const d = new Date(s)
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    }
  } catch { /* ignore */ }
  return s.length > 24 ? s.slice(0, 24) : s
}

export function pricingStampLine(p?: PricingMeta | null, opts?: { includeTechnicals?: boolean }): string | null {
  if (!p?.last_repriced && !p?.finviz_cache_updated) return null
  const when = formatPricingTime(p.last_repriced) ?? formatPricingTime(p.finviz_cache_updated)
  const src = priceSourceLabel(p.reprice_source)
  let line = when ? `Prices ${when} · ${src}` : `Prices · ${src}`
  if (opts?.includeTechnicals && p.enrichment_as_of) {
    const tech = formatPricingTime(p.enrichment_as_of)
    if (tech) line += ` · technicals ${tech}`
  }
  if (p.price_sources && Object.keys(p.price_sources).length) {
    const parts = Object.entries(p.price_sources)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([k, n]) => `${priceSourceLabel(k)} (${n})`)
    if (parts.length) line += ` · ${parts.join(', ')}`
  }
  return line
}
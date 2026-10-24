/**
 * Display labels for raw identifiers (P3 site validation 2026-10-23, operator-approved mockups).
 *
 * Pure. Every function keeps the identifier recoverable: callers put the raw value in `title`.
 */

// Tokens that read wrong in title case. Keys are lower-case identifier segments.
const ACRONYMS: Record<string, string> = {
  macd: 'MACD', rsi: 'RSI', vwap: 'VWAP', ema: 'EMA', sma: 'SMA', atr: 'ATR', orb: 'ORB', ai: 'AI',
  reit: 'REIT', etf: 'ETF', ipo: 'IPO', rr: 'R:R', pnl: 'P&L', iv: 'IV', dte: 'DTE', l2: 'L2', spy: 'SPY',
  qqq: 'QQQ', fib: 'Fib', hod: 'HOD', lod: 'LOD', ttm: 'TTM', bb: 'BB', adx: 'ADX', obv: 'OBV',
}
// Short connecting words stay lower-case unless they lead.
const MINOR = new Set(['and', 'or', 'of', 'the', 'to', 'vs', 'in', 'on', 'at', 'a', 'an', 'for', 'by'])

/** True for a snake_case / kebab identifier such as `fib_retracement_bounce` or `review-risk-reward`. */
export function looksLikeIdentifier(raw: unknown): boolean {
  return typeof raw === 'string' && /^[a-z][a-z0-9]*(?:[_-][a-z0-9]+)+$/.test(raw.trim())
}

/**
 * `fib_retracement_bounce` → "Fib Retracement Bounce", `pullback_macd_reversal` → "Pullback MACD Reversal",
 * `review_risk_reward` → "Review Risk Reward". A single lower-case word is capitalised; anything that is not
 * an identifier (already human, mixed case, sentences) is returned unchanged.
 */
export function humanizeIdentifier(raw: unknown): string {
  if (raw == null) return ''
  const s = String(raw).trim()
  if (!s) return ''
  const single = /^[a-z][a-z0-9]*$/.test(s)
  if (!single && !looksLikeIdentifier(s)) return s
  return s.split(/[_-]+/).map((w, i) => {
    const lw = w.toLowerCase()
    if (ACRONYMS[lw]) return ACRONYMS[lw]
    if (i > 0 && MINOR.has(lw)) return lw
    return lw.charAt(0).toUpperCase() + lw.slice(1)
  }).join(' ')
}

/**
 * Header TRADING tile value. "trades" was dropped from the face (the count is the second figure, and
 * the tooltip spells it out); the line may wrap to two lines inside the tile instead of being cut.
 */
export function tradingTileValue(winRate: number | null | undefined, trades: number | null | undefined, pnlText: string | null): string {
  if (winRate == null) return '—'
  return `${winRate}% win${trades ? ` · ${trades}` : ''}${pnlText != null ? ` · ${pnlText} P&L` : ''}`
}

// Header price stamp: the full source name lives in the tooltip; the face keeps the session word.
const SHORT_PRICE_SOURCE: Record<string, string> = {
  finviz_live: 'live',
  finviz_afterhours: 'after-hours',
  finviz_premarket: 'pre-market',
  schwab: 'Schwab',
  market_quotes: 'quotes',
  finviz: 'Finviz',
  holdings: 'holdings file',
  snaptrade: 'SnapTrade',
  technical_snapshot: 'snapshot',
}

export function shortPriceSource(src?: string | null): string {
  if (!src) return '—'
  return SHORT_PRICE_SOURCE[src] ?? src.replace(/_/g, ' ')
}

/**
 * Header price stamp face: "Prices 16:45 ET · after-hours · 12/12". Coverage stays on the face (the
 * operator pinned it visible even when healthy) but as a bare ratio; the full stamp is the tooltip.
 */
export function shortPriceStamp(when: string | null, src: string | null | undefined, covered?: number | null, total?: number | null, degraded?: boolean): string {
  const cov = covered != null && total != null ? ` · ${covered}/${total}` : ''
  return `Prices${when ? ` ${when}` : ''} · ${shortPriceSource(src)}${cov}${degraded ? ' DEGRADED' : ''}`
}

const VIX_SOURCE: Record<string, string> = {
  trade_ai_run_summary: 'scanner',
  trade_ai_scanner: 'scanner',
  finviz: 'Finviz',
  cboe: 'CBOE',
  yahoo: 'Yahoo',
}

/** "1730" → "17:30"; anything else unchanged. */
export function slotClock(slot: unknown): string | null {
  if (slot == null) return null
  const s = String(slot).trim()
  const m = s.match(/^(\d{2})(\d{2})$/)
  return m ? `${m[1]}:${m[2]}` : s || null
}

/**
 * Header VIX provenance face: "scanner · 17:30 run" when the VIX was read by a scanner run, else the
 * short source plus the observation time in ET. `observedEt` is already formatted ("22:21 ET").
 */
export function vixProvenance(src: string | null | undefined, runSlot: unknown, observedEt: string | null): string {
  const label = src ? (VIX_SOURCE[src] ?? src.replace(/_/g, ' ')) : 'source —'
  const slot = slotClock(runSlot)
  if (src && /^trade_ai/.test(src) && slot) return `${label} · ${slot} run`
  return observedEt ? `${label} · ${observedEt}` : label
}

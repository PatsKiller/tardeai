import type { AutoscaleInfo, IChartApi, ISeriesApi } from 'lightweight-charts'

/** OHLC bar shape from /api/v2/trade-chart */
export type ReplayOhlcBar = { time: number | string; open: number; high: number; low: number; close: number }

export type BarBounds = {
  min: number
  max: number
  rawMin: number
  rawMax: number
}

export type BackendPriceBounds = { min_low?: number; max_high?: number }

/** Deterministic min/max from OHLC bars only (for integrity checks). */
export function computeOhlcBounds(bars: ReplayOhlcBar[]): BarBounds | null {
  if (!bars.length) return null
  let rawMin = Infinity
  let rawMax = -Infinity
  for (const b of bars) {
    rawMin = Math.min(rawMin, b.low)
    rawMax = Math.max(rawMax, b.high)
  }
  if (!Number.isFinite(rawMin) || !Number.isFinite(rawMax)) return null
  const span = rawMax - rawMin
  const pad = span > 0 ? span * 0.06 : Math.max(rawMax * 0.02, 0.01)
  return { min: rawMin - pad, max: rawMax + pad, rawMin, rawMax }
}

/** Deterministic min/max from visible OHLC + annotation levels (BUY/SELL, STOP, MFE, etc.). */
export function computeBarBounds(bars: ReplayOhlcBar[], levels: number[] = []): BarBounds | null {
  const ohlc = computeOhlcBounds(bars)
  if (!ohlc) return null
  let rawMin = ohlc.rawMin
  let rawMax = ohlc.rawMax
  for (const p of levels) {
    if (Number.isFinite(p) && p > 0) {
      rawMin = Math.min(rawMin, p)
      rawMax = Math.max(rawMax, p)
    }
  }
  const span = rawMax - rawMin
  const pad = span > 0 ? span * 0.06 : Math.max(rawMax * 0.02, 0.01)
  return { min: rawMin - pad, max: rawMax + pad, rawMin, rawMax }
}

/**
 * Candle-only autoscale — volume/L2/VWAP/SPY must not pollute the right price axis.
 * Falls back to full bar set when visible replay window is empty (first paint race).
 */
export function makeCandleAutoscaleProvider(
  getBars: () => ReplayOhlcBar[],
  getLevels: () => number[],
  getAllBars?: () => ReplayOhlcBar[],
  lockToFull?: () => boolean,
): () => AutoscaleInfo | null {
  return () => {
    const useAll = lockToFull?.()
    const all = getAllBars?.() || []
    let bars = (useAll && all.length ? all : getBars()) || []
    if (!bars.length) bars = all.length ? all : getBars()
    const bounds = computeBarBounds(bars, getLevels())
    if (!bounds) return null
    return {
      priceRange: { minValue: bounds.min, maxValue: bounds.max },
      margins: { above: 12, below: 12 },
    }
  }
}

/** Exclude overlay line series from price autoscale (VWAP, SPY). */
export const NO_PRICE_AUTOSCALE = {
  autoscaleInfoProvider: () => null,
} as const

/** Right axis: candles + journal price lines only. */
export function configurePriceScale(chart: IChartApi) {
  chart.priceScale('right').applyOptions({
    autoScale: true,
    scaleMargins: { top: 0.05, bottom: 0.2 },
  })
}

export function configureVolumeScale(chart: IChartApi) {
  chart.priceScale('volume').applyOptions({
    autoScale: true,
    visible: false,
    scaleMargins: { top: 0.82, bottom: 0 },
  })
}

export function configureL2Scale(chart: IChartApi) {
  chart.priceScale('l2').applyOptions({
    autoScale: true,
    visible: false,
    scaleMargins: { top: 0.9, bottom: 0 },
  })
}

/** Link time axes across main + MACD + RSI panes. */
export function linkTimeScales(charts: IChartApi[]) {
  if (charts.length < 2) return () => {}
  const [main, ...subs] = charts
  let syncing = false
  const handler = (range: any) => {
    if (syncing || !range) return
    syncing = true
    for (const c of subs) {
      try { c.timeScale().setVisibleLogicalRange(range) } catch { /* noop */ }
    }
    syncing = false
  }
  main.timeScale().subscribeVisibleLogicalRangeChange(handler)
  return () => {
    try { main.timeScale().unsubscribeVisibleLogicalRangeChange(handler) } catch { /* noop */ }
  }
}

export type SyncReplayOptions = { fitTime?: boolean }

/** Refresh candle autoscale; optionally fit time axis (initial load / Re-sync only). */
export function syncReplayCharts(
  charts: IChartApi[],
  mainChart?: IChartApi | null,
  candle?: ISeriesApi<any> | null,
  opts: SyncReplayOptions = {},
) {
  const fitTime = opts.fitTime ?? false
  for (const c of charts) {
    try {
      if (fitTime) c.timeScale().fitContent()
      c.priceScale('right').applyOptions({ autoScale: true })
    } catch { /* chart may be mid-teardown */ }
  }
  if (mainChart) {
    try {
      mainChart.priceScale('right').applyOptions({ autoScale: true })
      candle?.applyOptions({})
    } catch { /* noop */ }
  }
}

const DEV = typeof import.meta !== 'undefined' && !!(import.meta as any).env?.DEV

function _priceTol(ref: number): number {
  // 2% or $0.03 minimum — avoids false positives from split-adjust vs rounded API bounds.
  return Math.max(0.03, Math.abs(ref) * 0.02)
}

export function checkPriceIntegrity(
  bounds: BarBounds | null,
  label: string,
  backend?: BackendPriceBounds,
  markerAligned?: boolean,
): string | null {
  const issues: string[] = []
  if (markerAligned === false) issues.push('marker price misaligned with bar OHLC')
  if (bounds && backend?.min_low != null && backend?.max_high != null) {
    const loTol = _priceTol(backend.min_low)
    const hiTol = _priceTol(backend.max_high)
    const dLo = Math.abs(bounds.rawMin - backend.min_low)
    const dHi = Math.abs(bounds.rawMax - backend.max_high)
    if (dLo > loTol) {
      issues.push(`low: client=${bounds.rawMin.toFixed(4)} api=${backend.min_low} (Δ${dLo.toFixed(3)})`)
    }
    if (dHi > hiTol) {
      issues.push(`high: client=${bounds.rawMax.toFixed(4)} api=${backend.max_high} (Δ${dHi.toFixed(3)})`)
    }
  }
  if (issues.length) {
    const msg = `[replay-scale:${label}] ${issues.join('; ')}`
    if (DEV) console.warn(msg, bounds)
    return msg
  }
  return null
}
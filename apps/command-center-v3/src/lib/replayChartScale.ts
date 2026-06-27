import type { AutoscaleInfo, IChartApi } from 'lightweight-charts'

/** OHLC bar shape from /api/v2/trade-chart */
export type ReplayOhlcBar = { time: number | string; open: number; high: number; low: number; close: number }

export type BarBounds = {
  min: number
  max: number
  rawMin: number
  rawMax: number
}

export type BackendPriceBounds = { min_low?: number; max_high?: number }

/** Deterministic min/max from visible OHLC + annotation levels (BUY/SELL, STOP, MFE, etc.). */
export function computeBarBounds(bars: ReplayOhlcBar[], levels: number[] = []): BarBounds | null {
  if (!bars.length) return null
  let rawMin = Infinity
  let rawMax = -Infinity
  for (const b of bars) {
    rawMin = Math.min(rawMin, b.low)
    rawMax = Math.max(rawMax, b.high)
  }
  for (const p of levels) {
    if (Number.isFinite(p) && p > 0) {
      rawMin = Math.min(rawMin, p)
      rawMax = Math.max(rawMax, p)
    }
  }
  if (!Number.isFinite(rawMin) || !Number.isFinite(rawMax)) return null
  const span = rawMax - rawMin
  const pad = span > 0 ? span * 0.06 : Math.max(rawMax * 0.02, 0.01)
  return { min: rawMin - pad, max: rawMax + pad, rawMin, rawMax }
}

/**
 * Candle-only autoscale — never let volume/L2 histogram values pollute the right price axis.
 * Root cause of GOVX-style misalignment: volume shared priceScaleId '' with candles.
 */
export function makeCandleAutoscaleProvider(
  getBars: () => ReplayOhlcBar[],
  getLevels: () => number[],
): () => AutoscaleInfo | null {
  return () => {
    const bounds = computeBarBounds(getBars(), getLevels())
    if (!bounds) return null
    return {
      priceRange: { minValue: bounds.min, maxValue: bounds.max },
      margins: { above: 12, below: 12 },
    }
  }
}

/** Right axis: candles, VWAP, SPY overlay, BUY/SELL price lines. */
export function configurePriceScale(chart: IChartApi) {
  chart.priceScale('right').applyOptions({
    autoScale: true,
    scaleMargins: { top: 0.05, bottom: 0.2 },
  })
}

/** Volume histogram on an isolated overlay scale (axis hidden). */
export function configureVolumeScale(chart: IChartApi) {
  chart.priceScale('volume').applyOptions({
    autoScale: true,
    visible: false,
    scaleMargins: { top: 0.82, bottom: 0 },
  })
}

/** L2 imbalance strip — separate scale, hidden axis. */
export function configureL2Scale(chart: IChartApi) {
  chart.priceScale('l2').applyOptions({
    autoScale: true,
    visible: false,
    scaleMargins: { top: 0.9, bottom: 0 },
  })
}

/** Fit time axis + refresh autoscale on main and sub-panels after each replay paint step. */
export function syncReplayCharts(charts: IChartApi[], mainChart?: IChartApi | null) {
  for (const c of charts) {
    try {
      c.timeScale().fitContent()
      c.priceScale('right').applyOptions({ autoScale: true })
    } catch { /* chart may be mid-teardown */ }
  }
  if (mainChart) {
    try {
      mainChart.priceScale('right').applyOptions({ autoScale: true })
    } catch { /* noop */ }
  }
}

const DEV = typeof import.meta !== 'undefined' && !!(import.meta as any).env?.DEV

/** Dev-only: compare client bounds vs server price_bounds; returns warning text or null. */
export function checkPriceIntegrity(
  bounds: BarBounds | null,
  label: string,
  backend?: BackendPriceBounds,
): string | null {
  if (!bounds) return null
  const issues: string[] = []
  if (backend?.min_low != null && backend?.max_high != null) {
    const tol = Math.max(0.01, bounds.rawMax * 0.001)
    if (Math.abs(bounds.rawMin - backend.min_low) > tol) {
      issues.push(`low: client=${bounds.rawMin.toFixed(4)} api=${backend.min_low}`)
    }
    if (Math.abs(bounds.rawMax - backend.max_high) > tol) {
      issues.push(`high: client=${bounds.rawMax.toFixed(4)} api=${backend.max_high}`)
    }
  }
  if (issues.length) {
    const msg = `[replay-scale:${label}] ${issues.join('; ')}`
    if (DEV) console.warn(msg, bounds)
    return msg
  }
  return null
}
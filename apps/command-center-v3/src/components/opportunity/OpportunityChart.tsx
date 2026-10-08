/** Compact daily chart for the opportunity modal: candles (or a close line), support/resistance price lines, the
 *  entry zone, the invalidation level and the targets. Colours come from CHART_HEX (charts cannot read var()). */
import { useEffect, useRef } from 'react'
import { createChart, type IChartApi } from 'lightweight-charts'
import { CHART_HEX } from '../../lib/designTokens'
import { useTheme } from '../../hooks/useTheme'

export type ChartLevel = { price: number; title: string; kind: 'support' | 'resistance' | 'entry' | 'invalidation' | 'target' }

export default function OpportunityChart({ bars, kind, levels, height = 240 }: {
  bars: any[]; kind: string; levels: ChartLevel[]; height?: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [, , themeName] = useTheme()
  useEffect(() => {
    if (!ref.current || !bars?.length) return
    const hx = CHART_HEX[themeName] || CHART_HEX.dark
    const c: IChartApi = createChart(ref.current, {
      width: ref.current.clientWidth, height, autoSize: true,
      layout: { background: { color: 'transparent' }, textColor: hx.text },
      grid: { vertLines: { color: hx.grid }, horzLines: { color: hx.grid } },
      timeScale: { borderColor: hx.grid, timeVisible: false },
      rightPriceScale: { borderColor: hx.grid },
    } as any)
    const series: any = kind === 'candles'
      ? c.addCandlestickSeries({ upColor: hx.success, downColor: hx.danger, borderVisible: false, wickUpColor: hx.success, wickDownColor: hx.danger })
      : c.addLineSeries({ color: hx.series[0], lineWidth: 2 })
    series.setData(kind === 'candles'
      ? bars.map((b: any) => ({ time: b.time, open: b.open ?? b.close, high: b.high ?? b.close, low: b.low ?? b.close, close: b.close }))
      : bars.map((b: any) => ({ time: b.time, value: b.close })))
    const color: Record<ChartLevel['kind'], string> = {
      support: hx.success, resistance: hx.danger, entry: hx.series[0], invalidation: hx.warning, target: hx.series[3],
    }
    for (const lv of levels) {
      if (!Number.isFinite(lv.price)) continue
      series.createPriceLine({ price: lv.price, color: color[lv.kind], lineWidth: lv.kind === 'entry' ? 2 : 1,
        lineStyle: lv.kind === 'support' || lv.kind === 'resistance' ? 2 : 0, axisLabelVisible: true, title: lv.title })
    }
    c.timeScale().fitContent()
    return () => c.remove()
  }, [bars, kind, levels, height, themeName])
  if (!bars?.length) return <div style={{ padding: 24, textAlign: 'center', color: 'var(--text3)', fontSize: 11 }}>No daily bars for this symbol.</div>
  return <div ref={ref} data-opportunity-chart style={{ width: '100%' }} />
}

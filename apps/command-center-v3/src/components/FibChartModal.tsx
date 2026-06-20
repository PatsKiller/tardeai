import { useEffect, useRef } from 'react'
import { createChart, IChartApi } from 'lightweight-charts'

// Multi-timeframe Fib chart modal: stacks a DAILY and a MONTHLY candlestick chart, each drawing every
// analyzed level (Fib retr/ext · swing hi/lo · confluence zones) as horizontal price lines, with the
// clicked level highlighted. Read-only. Bars come from the fib-confluence engine (no extra fetch).

export type FibLevel = { price: number; title: string; color: string; bold?: boolean }

const DARK = {
  layout: { background: { color: 'transparent' }, textColor: '#9ca3af' },
  grid: { vertLines: { color: 'rgba(255,255,255,.04)' }, horzLines: { color: 'rgba(255,255,255,.04)' } },
  timeScale: { borderColor: 'rgba(255,255,255,.1)', timeVisible: false },
  rightPriceScale: { borderColor: 'rgba(255,255,255,.1)' },
}

function TFChart({ label, bars, levels }: { label: string; bars: any[]; levels: FibLevel[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current || !bars?.length) return
    const c: IChartApi = createChart(ref.current, { ...DARK, width: ref.current.clientWidth, height: 300, autoSize: true } as any)
    const candle = c.addCandlestickSeries({ upColor: '#22c55e', downColor: '#ef4444', borderVisible: false, wickUpColor: '#22c55e', wickDownColor: '#ef4444' })
    candle.setData(bars.map(b => ({ time: b.t, open: b.o ?? b.l, high: b.h, low: b.l, close: b.c })))
    // only draw levels within the chart's visible price range (so a far long-term level doesn't squash the candles)
    const lo = Math.min(...bars.map(b => b.l)), hi = Math.max(...bars.map(b => b.h))
    for (const lv of levels) {
      if (lv.price > 0 && lv.price >= lo * 0.97 && lv.price <= hi * 1.03)
        candle.createPriceLine({ price: lv.price, color: lv.color, lineWidth: lv.bold ? 2 : 1, lineStyle: lv.bold ? 0 : 2, axisLabelVisible: true, title: lv.title })
    }
    c.timeScale().fitContent()
    return () => c.remove()
  }, [bars, levels])
  return (
    <div style={{ flex: '1 1 380px', minWidth: 320 }}>
      <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text2)', marginBottom: 4 }}>{label}</div>
      {bars?.length ? <div ref={ref} style={{ width: '100%' }} /> : <div style={{ padding: 30, textAlign: 'center', color: 'var(--text3)', fontSize: 11 }}>no {label.toLowerCase()} data</div>}
    </div>
  )
}

export default function FibChartModal({ symbol, bars, barsMonthly, levels, onClose }: {
  symbol: string; bars: any[]; barsMonthly?: any[]; levels: FibLevel[]; onClose: () => void
}) {
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.74)', zIndex: 95, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 16, width: 'min(1100px,97vw)', maxHeight: '92vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
          <span style={{ fontSize: 15, fontWeight: 900, color: 'var(--text0)' }}>{symbol}</span>
          <span style={{ fontSize: 10, color: 'var(--text3)' }}>daily &amp; monthly · Fib levels, swing points &amp; confluence as price lines · advisory</span>
          <span style={{ flex: 1 }} />
          <button onClick={onClose} style={{ fontSize: 12, padding: '4px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text2)', cursor: 'pointer' }}>close</button>
        </div>
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
          <TFChart label="Daily" bars={bars} levels={levels} />
          {barsMonthly?.length ? <TFChart label="Monthly" bars={barsMonthly} levels={levels} /> : null}
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 10 }}>
          {levels.filter(l => l.price > 0).map((l, i) => (
            <span key={i} style={{ fontSize: 9.5, color: l.color, display: 'flex', alignItems: 'center', gap: 4 }}><span style={{ width: 10, height: 2, background: l.color, display: 'inline-block' }} />{l.title} ${l.price}</span>
          ))}
        </div>
      </div>
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import { createChart, IChartApi, ISeriesApi, UTCTimestamp } from 'lightweight-charts'

// Per-trade replay chart (TradingView Lightweight Charts, MIT). Candles + volume + VWAP + MACD + RSI panes,
// entry ↑ / exit ↓ markers + price lines, and a ▶ replay scrubber. Data: /api/v2/trade-chart (Alpaca ->
// Schwab -> Finviz image fallback). No TradingView account, no metered API.
type Trade = { symbol: string; entry_date: string; exit_date?: string; entry_price?: number | string; exit_price?: number | string; entry_time?: string; exit_time?: string }

const DARK = {
  layout: { background: { color: 'transparent' }, textColor: '#9ca3af' },
  grid: { vertLines: { color: 'rgba(255,255,255,.04)' }, horzLines: { color: 'rgba(255,255,255,.04)' } },
  timeScale: { borderColor: 'rgba(255,255,255,.1)', timeVisible: true },
  rightPriceScale: { borderColor: 'rgba(255,255,255,.1)' },
}

export default function TradeReplayChart({ trade, onClose }: { trade: Trade; onClose: () => void }) {
  const [data, setData] = useState<any>(null)
  const [err, setErr] = useState('')
  const [show, setShow] = useState({ vol: true, vwap: true, macd: true, rsi: true, spy: false, l2: true })
  const [n, setN] = useState(0)            // replay cursor (#bars revealed); 0 = all
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)    // replay speed multiplier
  const [fvImg, setFvImg] = useState('')   // Finviz fallback image (base64 data URI)
  const priceRef = useRef<HTMLDivElement>(null)
  const macdRef = useRef<HTMLDivElement>(null)
  const rsiRef = useRef<HTMLDivElement>(null)
  const charts = useRef<IChartApi[]>([])
  const series = useRef<Record<string, ISeriesApi<any>>>({})

  useEffect(() => {
    const qs = new URLSearchParams({ symbol: trade.symbol, entry_date: String(trade.entry_date).slice(0, 10),
      exit_date: String(trade.exit_date || trade.entry_date).slice(0, 10),
      ...(trade.entry_price ? { entry_price: String(trade.entry_price) } : {}),
      ...(trade.exit_price ? { exit_price: String(trade.exit_price) } : {}),
      // pass full timestamps when known: fixes same-day detection for overnight intraday holds (audit bug)
      ...((trade as any).entry_time || (trade as any).entryTimeFull ? { entry_time: String((trade as any).entry_time || (trade as any).entryTimeFull) } : {}),
      ...((trade as any).exit_time || (trade as any).exitTimeFull ? { exit_time: String((trade as any).exit_time || (trade as any).exitTimeFull) } : {}) })
    fetch(`/api/v2/trade-chart?${qs}`).then(r => r.json()).then(j => {
      const d = j?.data ?? j
      if (d?.error) setErr(d.error); else setData(d)
      if (d?.fallback === 'finviz' && d?.fallback_image) {
        fetch(d.fallback_image).then(r => r.json()).then(jj => { const dd = jj?.data ?? jj; if (dd?.image) setFvImg(dd.image); else setErr((dd?.error || 'finviz image unavailable') + ' — if persistent, the Finviz Elite cookie may have expired (refresh FINVIZ_COOKIE)') })
      }
    }).catch(e => setErr(String(e)))
  }, [trade.symbol, trade.entry_date])

  // build charts once data arrives
  useEffect(() => {
    if (!data?.bars?.length || !priceRef.current) return
    charts.current.forEach(c => c.remove()); charts.current = []; series.current = {}
    const mk = (el: HTMLDivElement, h: number) => { const c = createChart(el, { ...DARK, width: el.clientWidth, height: h, autoSize: true } as any); charts.current.push(c); return c }

    const pc = mk(priceRef.current, 300)
    const candle = pc.addCandlestickSeries({ upColor: '#22c55e', downColor: '#ef4444', borderVisible: false, wickUpColor: '#22c55e', wickDownColor: '#ef4444' })
    series.current.candle = candle
    if (show.vol) { const v = pc.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: '' }); ;(v as any).priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } }); series.current.vol = v }
    if (show.vwap) series.current.vwap = pc.addLineSeries({ color: '#eab308', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
    if (show.spy && data.spy_overlay?.length) series.current.spy = pc.addLineSeries({ color: 'rgba(148,163,184,.8)', lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: true, title: 'SPY (rebased)' })
    if (show.l2 && data.l2_strip?.length) { const l2 = pc.addHistogramSeries({ priceScaleId: 'l2' }); pc.priceScale('l2').applyOptions({ scaleMargins: { top: 0.9, bottom: 0 } }); series.current.l2 = l2 }
    if (show.macd && macdRef.current) { const mc = mk(macdRef.current, 110); series.current.macd = mc.addLineSeries({ color: '#60a5fa', lineWidth: 1 }); series.current.signal = mc.addLineSeries({ color: '#f97316', lineWidth: 1 }); series.current.hist = mc.addHistogramSeries({}) }
    if (show.rsi && rsiRef.current) { const rc = mk(rsiRef.current, 90); series.current.rsi = rc.addLineSeries({ color: '#a855f7', lineWidth: 1 }); ;[30, 70].forEach(lv => series.current.rsi.createPriceLine({ price: lv, color: 'rgba(168,85,247,.3)', lineWidth: 1, lineStyle: 2, axisLabelVisible: false })) }

    // entry/exit price lines on the candle series
    for (const m of data.markers || []) candle.createPriceLine({ price: m.price, color: m.type === 'entry' ? '#22c55e' : '#ef4444', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: m.type === 'entry' ? 'BUY' : 'SELL' })
    // planned STOP/TARGET lines (replay audit #1): did price stop you out or did you hit plan?
    const t0: any = trade as any
    const plannedStop = Number(t0.stop ?? t0.stop_loss ?? t0.planned_stop) || null
    const plannedTgt = Number(t0.target ?? t0.target_1 ?? t0.target_price) || null
    if (plannedStop) candle.createPriceLine({ price: plannedStop, color: '#ef4444', lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: 'STOP (plan)' })
    if (plannedTgt) candle.createPriceLine({ price: plannedTgt, color: '#22c55e', lineWidth: 1, lineStyle: 0, axisLabelVisible: true, title: 'TARGET (plan)' })
    // execution overlay: MFE (max opportunity), MAE, post-exit high — with % badges (audit #3)
    const ex: any = (trade as any).exec
    if (ex) {
      const ep = Number(ex.entry_price) || 0
      if (ex.mfe_after_entry != null && ep) candle.createPriceLine({ price: ep + Number(ex.mfe_after_entry), color: '#3b82f6', lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: `MFE +${(100 * Number(ex.mfe_after_entry) / ep).toFixed(1)}%` })
      if (ex.mae_after_entry != null && ep) candle.createPriceLine({ price: ep - Number(ex.mae_after_entry), color: '#9333ea', lineWidth: 1, lineStyle: 3, axisLabelVisible: true, title: `MAE -${(100 * Number(ex.mae_after_entry) / ep).toFixed(1)}%` })
      if (ex.post_exit_high != null) {
        // runner annotation (audit #2): name the post-exit move so the lesson is on the chart
        const rt = ex.runner_type as string | undefined
        const gb = ex.post_exit_gave_back_ratio != null ? ` · gave back ${Math.round(100 * Number(ex.post_exit_gave_back_ratio))}%` : ''
        const rtLabel = rt === 'parabolic_pump' ? `⚡ pump — exit was right${gb}`
          : rt === 'sustained_trend' ? '↗ real runner — scale-out lesson'
          : rt === 'trend_top' ? '⛰ trend top after exit'
          : rt === 'faded' ? 'faded after exit'
          : 'max after exit'
        candle.createPriceLine({ price: Number(ex.post_exit_high), color: rt === 'sustained_trend' ? '#22c55e' : '#f59e0b', lineWidth: 1, lineStyle: 1, axisLabelVisible: true, title: rtLabel })
      }
    }
    paint(data.bars.length)
    const onResize = () => charts.current.forEach(c => c.timeScale().fitContent())
    window.addEventListener('resize', onResize)
    return () => { window.removeEventListener('resize', onResize); charts.current.forEach(c => c.remove()); charts.current = [] }
  }, [data, show.vol, show.vwap, show.macd, show.rsi])

  // replay paint: reveal the first `count` bars (0 => all)
  const paint = (count: number) => {
    if (!data?.bars) return
    const k = count <= 0 ? data.bars.length : count
    const cut = (arr: any[]) => (arr || []).filter((_: any, i: number) => i < k)
    series.current.candle?.setData(cut(data.bars))
    series.current.vol?.setData(cut(data.volume))
    series.current.vwap?.setData(cut(data.vwap))
    series.current.macd?.setData(cut(data.macd).map((x: any) => ({ time: x.time, value: x.macd })))
    series.current.signal?.setData(cut(data.macd).map((x: any) => ({ time: x.time, value: x.signal })))
    series.current.hist?.setData(cut(data.macd).map((x: any) => ({ time: x.time, value: x.hist, color: x.hist >= 0 ? 'rgba(34,197,94,.5)' : 'rgba(239,68,68,.5)' })))
    series.current.rsi?.setData(cut(data.rsi))
    series.current.spy?.setData((data.spy_overlay || []).filter((x: any) => shownTime(x.time)))
    series.current.l2?.setData((data.l2_strip || []).filter((x: any) => shownTime(x.time)).map((x: any) => ({ time: x.time, value: x.value, color: x.value >= 0 ? 'rgba(34,197,94,.6)' : 'rgba(239,68,68,.6)' })))
    // markers only show once their bar is revealed; include the 9:30 session-open marker
    const shown = new Set(cut(data.bars).map((b: any) => String(b.time)))
    const shownTime = (t: any) => shown.has(String(t))
    const mks = (data.markers || []).filter((m: any) => shown.has(String(m.time))).map((m: any) => ({
      time: m.time, position: m.type === 'entry' ? 'belowBar' : 'aboveBar',
      color: m.type === 'entry' ? '#22c55e' : '#ef4444', shape: m.type === 'entry' ? 'arrowUp' : 'arrowDown', text: m.label }))
    if (data.session_open_time && shown.has(String(data.session_open_time)))
      mks.push({ time: data.session_open_time, position: 'aboveBar', color: '#eab308', shape: 'circle', text: '9:30 open' })
    if (data.session_close_time && shown.has(String(data.session_close_time)))
      mks.push({ time: data.session_close_time, position: 'aboveBar', color: '#f97316', shape: 'circle', text: '16:00 close' })
    for (const ne of (data.news_events || []))
      if (shown.has(String(ne.time))) mks.push({ time: ne.time, position: 'aboveBar', color: '#22d3ee', shape: 'circle', text: '📰' })
    mks.sort((a: any, b: any) => (typeof a.time === 'number' ? a.time - b.time : String(a.time).localeCompare(String(b.time))))
    series.current.candle?.setMarkers(mks)
  }
  useEffect(() => { paint(n) }, [n])

  // play animation — interval scales with speed (0.5x..8x)
  useEffect(() => {
    if (!playing || !data?.bars) return
    if (n === 0) setN(1)
    const step = Math.max(1, Math.floor(data.bars.length / 90))
    const id = setInterval(() => setN(v => { const nx = (v || 1) + step; if (nx >= data.bars.length) { setPlaying(false); return 0 } return nx }), Math.round(120 / speed))
    return () => clearInterval(id)
  }, [playing, data, speed])

  const pnl = data?.markers?.length === 2 ? (Number(data.markers[1].price) - Number(data.markers[0].price)) : null

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 50, display: 'flex', justifyContent: 'center', alignItems: 'flex-start', padding: '4vh 2vw', overflow: 'auto' }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 12, padding: 16, width: 'min(900px, 96vw)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text0)' }}>{trade.symbol} <span style={{ fontSize: 11, color: 'var(--text3)', fontWeight: 400 }}>{String(trade.entry_date).slice(0, 10)} → {String(trade.exit_date || '').slice(0, 10)}</span></div>
          {data && <span style={{ fontSize: 10, color: 'var(--text3)' }}>{data.timeframe} · {data.bar_count} bars · src:{data.source}</span>}
          {pnl != null && <span style={{ fontSize: 12, fontWeight: 700, color: pnl >= 0 ? '#22c55e' : '#ef4444' }}>{pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}/sh</span>}
          {(trade as any).exec && <span style={{ fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 4, background: ((trade as any).exec.execution_grade === 'poor' ? '#ef4444' : (trade as any).exec.execution_grade === 'weak' ? '#f59e0b' : '#22c55e') + '22', color: (trade as any).exec.execution_grade === 'poor' ? '#ef4444' : (trade as any).exec.execution_grade === 'weak' ? '#f59e0b' : '#22c55e' }}
            title={[
              ...[['no_volume_entry_flag', 'entered without volume confirmation'], ['premature_exit_flag', 'exited prematurely'],
                   ['early_entry_flag', 'entry early vs setup'], ['late_entry_flag', 'entry late/chased']]
                .filter(([k]) => (trade as any).exec[k]).map(([, label]) => `• ${label}`),
              (trade as any).exec.grok_what_to_do_next_time ? `Coach: ${(trade as any).exec.grok_what_to_do_next_time}` : ((trade as any).exec.computed_summary || ''),
            ].filter(Boolean).join('\n')}>{(trade as any).exec.outcome_grade}/{(trade as any).exec.execution_grade} · cap {Math.round(((trade as any).exec.capture_ratio ?? 0) * 100)}%</span>}
          <span style={{ flex: 1 }} />
          {(['vol', 'vwap', 'macd', 'rsi', 'spy', 'l2'] as const).map(k => <button key={k} onClick={() => setShow(s => ({ ...s, [k]: !s[k] }))} style={{ fontSize: 9, padding: '2px 7px', borderRadius: 5, border: '1px solid var(--border)', background: show[k] ? '#1d4ed8' : 'var(--bg2)', color: show[k] ? '#fff' : 'var(--text3)', cursor: 'pointer' }}>{k.toUpperCase()}</button>)}
          <button onClick={onClose} style={{ fontSize: 11, padding: '2px 9px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer' }}>✕</button>
        </div>

        {err && <div style={{ fontSize: 12, color: '#ef4444', padding: 20 }}>Chart unavailable: {err}</div>}
        {data?.fallback === 'finviz' && fvImg && <div style={{ padding: 8 }}><div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>No Alpaca/Schwab bars — Finviz Elite chart image:</div><img src={fvImg} alt={trade.symbol} style={{ width: '100%', borderRadius: 6 }} /></div>}
        {!err && data?.bars?.length > 0 && <>
          <div ref={priceRef} style={{ width: '100%' }} />
          {show.macd && <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 4 }}>MACD</div>}
          <div ref={macdRef} style={{ width: '100%', display: show.macd ? 'block' : 'none' }} />
          {show.rsi && <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 4 }}>RSI</div>}
          <div ref={rsiRef} style={{ width: '100%', display: show.rsi ? 'block' : 'none' }} />
        {(data?.news_events?.length ?? 0) > 0 && (
          <div style={{ marginTop: 6, fontSize: 9, color: 'var(--text3)' }}>
            <b style={{ color: '#22d3ee' }}>📰 News during trade window:</b>
            {data.news_events.slice(0, 6).map((ne: any, i: number) => (
              <div key={i} style={{ marginTop: 2 }}>
                <span style={{ color: 'var(--text2)', fontWeight: 600 }}>{ne.at_et}</span>{ne.clamped && <span style={{ color: '#f59e0b' }}> ({ne.clamped}-window)</span>} · {ne.title}
                {ne.source && <span style={{ opacity: .6 }}> ({String(ne.source).slice(0, 24)})</span>}
              </div>
            ))}
          </div>
        )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10 }}>
            <button onClick={() => setPlaying(p => !p)} style={{ fontSize: 12, padding: '4px 12px', borderRadius: 6, border: '1px solid var(--border)', background: playing ? '#ef4444' : '#16a34a', color: '#fff', cursor: 'pointer', fontWeight: 700 }}>{playing ? '❚❚ pause' : '▶ replay'}</button>
            <div style={{ display: 'flex', gap: 2 }} title="Replay speed">
              {[0.5, 1, 2, 4, 8].map(s => <button key={s} onClick={() => setSpeed(s)} style={{ fontSize: 9, padding: '3px 6px', borderRadius: 4, border: '1px solid var(--border)', background: speed === s ? '#1d4ed8' : 'var(--bg2)', color: speed === s ? '#fff' : 'var(--text3)', cursor: 'pointer' }}>{s}×</button>)}
            </div>
            <input type="range" min={1} max={data.bars.length} value={n === 0 ? data.bars.length : n} onChange={e => { setPlaying(false); setN(Number(e.target.value)) }} style={{ flex: 1 }} />
            <span style={{ fontSize: 10, color: 'var(--text3)', minWidth: 70, textAlign: 'right' }}>{n === 0 ? data.bars.length : n}/{data.bars.length} bars</span>
          </div>
        </>}
        {!err && !data && <div style={{ fontSize: 12, color: 'var(--text3)', padding: 30, textAlign: 'center' }}>Loading {trade.symbol} chart…</div>}
      </div>
    </div>
  )
}

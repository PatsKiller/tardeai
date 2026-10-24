import { useTheme } from '../hooks/useTheme'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createChart, IChartApi, ISeriesApi, LineType } from 'lightweight-charts'
import {
  checkPriceIntegrity,
  computeOhlcBounds,
  computeTradeFocusRange,
  configureL2Scale,
  configurePriceScale,
  configureVolumeScale,
  linkTimeScales,
  makeCandleAutoscaleProvider,
  NO_PRICE_AUTOSCALE,
  syncReplayCharts,
  type TradeFocusRange,
} from '../lib/replayChartScale'
import { CHART_HEX, FONT, RADIUS, TOKENS, TYPE, toneVars } from '../lib/designTokens'

// Active Trader alerts on the trade chart (operator 2026-10-05: line up "what time you gave me the
// alert" with the fill). Colours come from the chart token palette (no raw hex in components).
const ALERT_SHORT: Record<string, string> = {
  TRIGGERED: 'BUY?', PULLBACK_ZONE: 'ZONE', APPROACHING: 'NEAR', ARMED: 'ARMED', EXTENDED: 'EXT', TRIGGER_CANCELLED: 'FAIL',
}
const alertColor = (kind: string, p = CHART_HEX.dark) => {
  return kind === 'TRIGGERED' || kind === 'PULLBACK_ZONE' ? p.success
    : kind === 'EXTENDED' || kind === 'TRIGGER_CANCELLED' ? p.danger
    : kind === 'APPROACHING' ? p.series[0] : p.warning
}

/** Exec/plan overlays — drawn as price lines but labeled in the HTML legend (not on the axis). */
type OverlayLevel = { price: number; color: string; label: string; style?: string }

// Per-trade replay chart (TradingView Lightweight Charts, MIT). Candles + volume + VWAP + MACD + RSI panes,
// entry ↑ / exit ↓ markers + price lines, and a ▶ replay scrubber. Data: /api/v2/trade-chart (Alpaca ->
// Schwab -> Finviz image fallback). No TradingView account, no metered API.
type Trade = { symbol: string; entry_date: string; exit_date?: string; entry_price?: number | string | null; exit_price?: number | string | null; entry_time?: string | null; exit_time?: string | null; trade_key?: string; account?: string }


const DEV = typeof import.meta !== 'undefined' && !!(import.meta as any).env?.DEV

export default function TradeReplayChart({ trade, onClose, embedded = false, providedData }: { trade: Trade; onClose: () => void; embedded?: boolean; providedData?: any }) {
  const [, , theme] = useTheme()
  const p = CHART_HEX[theme]
  const [data, setData] = useState<any>(providedData ?? null)
  const [err, setErr] = useState('')
  const [show, setShow] = useState({ vol: !embedded, vwap: !embedded, macd: !embedded, rsi: !embedded, spy: false, l2: !embedded })
  const [n, setN] = useState(0)            // replay cursor (#bars revealed); 0 = all
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)    // replay speed multiplier
  const [fvImg, setFvImg] = useState('')   // Finviz fallback image (base64 data URI)
  const [scaleWarn, setScaleWarn] = useState('')
  const [autoSyncScale, setAutoSyncScale] = useState(true)  // off = lock Y-axis to full trade range
  const [overlayLevels, setOverlayLevels] = useState<OverlayLevel[]>([])
  const focusRangeRef = useRef<TradeFocusRange | null>(null)
  const priceRef = useRef<HTMLDivElement>(null)
  const macdRef = useRef<HTMLDivElement>(null)
  const rsiRef = useRef<HTMLDivElement>(null)
  const charts = useRef<IChartApi[]>([])
  const priceChart = useRef<IChartApi | null>(null)
  const series = useRef<Record<string, ISeriesApi<any>>>({})
  const visibleBarsRef = useRef<any[]>([])
  const allBarsRef = useRef<any[]>([])
  const levelPricesRef = useRef<number[]>([])
  const autoSyncRef = useRef(true)
  const replayCursorRef = useRef(0)
  replayCursorRef.current = n
  autoSyncRef.current = autoSyncScale

  useEffect(() => {
    if (embedded) {
      // The new page supplies a store-only projection; even loading/empty never falls through to provider fetches.
      setData(providedData ?? null); setErr(providedData?.error || ''); setN(0); setPlaying(false)
      return
    }
    const qs = new URLSearchParams({ symbol: trade.symbol, entry_date: String(trade.entry_date).slice(0, 10),
      exit_date: String(trade.exit_date || trade.entry_date).slice(0, 10),
      ...(trade.entry_price ? { entry_price: String(trade.entry_price) } : {}),
      ...(trade.exit_price ? { exit_price: String(trade.exit_price) } : {}),
      ...((trade as any).trade_key ? { trade_key: String((trade as any).trade_key) } : {}),
      ...((trade as any).account ? { account: String((trade as any).account) } : {}),
      ...((trade as any).entry_time || (trade as any).entryTimeFull ? { entry_time: String((trade as any).entry_time || (trade as any).entryTimeFull) } : {}),
      ...((trade as any).exit_time || (trade as any).exitTimeFull ? { exit_time: String((trade as any).exitTimeFull || (trade as any).exit_time) } : {}) })
    fetch(`/api/v2/trade-chart?${qs}`).then(r => r.json()).then(j => {
      const d = j?.data ?? j
      if (d?.error) setErr(d.error); else setData(d)
      if (d?.fallback === 'finviz' && d?.fallback_image) {
        fetch(d.fallback_image).then(r => r.json()).then(jj => { const dd = jj?.data ?? jj; if (dd?.image) setFvImg(dd.image); else setErr((dd?.error || 'finviz image unavailable') + ' — if persistent, the Finviz Elite cookie may have expired (refresh FINVIZ_COOKIE)') })
      }
    }).catch(e => setErr(String(e)))
  }, [trade.symbol, trade.entry_date, trade.exit_date, (trade as any).trade_key, (trade as any).account, embedded, providedData])

  // build charts once data arrives
  useEffect(() => {
    if (!data?.bars?.length || !priceRef.current) return
    charts.current.forEach(c => c.remove()); charts.current = []; series.current = {}
    priceChart.current = null
    visibleBarsRef.current = []
    levelPricesRef.current = []

    const mk = (el: HTMLDivElement, h: number) => { const c = createChart(el, { layout: { background: { color: 'transparent' }, textColor: p.text }, grid: { vertLines: { color: p.grid }, horzLines: { color: p.grid } }, timeScale: { borderColor: p.grid, timeVisible: true }, rightPriceScale: { borderColor: p.grid }, width: el.clientWidth, height: h, autoSize: true } as any); charts.current.push(c); return c }

    const pc = mk(priceRef.current, embedded ? 470 : 300)
    priceChart.current = pc
    configurePriceScale(pc)

    allBarsRef.current = data.bars || []
    const candle = data.kind === 'closes' ? pc.addLineSeries({ color: p.series[0], lineWidth: 2 }) : pc.addCandlestickSeries({
      upColor: p.success, downColor: p.danger, borderVisible: false, wickUpColor: p.success, wickDownColor: p.danger,
      autoscaleInfoProvider: makeCandleAutoscaleProvider(
        () => visibleBarsRef.current,
        () => levelPricesRef.current,
        () => allBarsRef.current,
        () => !autoSyncRef.current,
      ),
    })
    series.current.candle = candle

    // Volume MUST use its own overlay scale — sharing '' with candles made the Y-axis show share counts (e.g. 500k)
    // while $3–4 candles sat at the bottom (GOVX replay bug).
    if (show.vol) {
      configureVolumeScale(pc)
      const v = pc.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'volume' })
      series.current.vol = v
    }
    if (show.vwap) series.current.vwap = pc.addLineSeries({ color: p.warning, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, ...NO_PRICE_AUTOSCALE })
    if (show.spy && data.spy_overlay?.length) series.current.spy = pc.addLineSeries({ color: p.text, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: true, title: 'SPY (rebased)', ...NO_PRICE_AUTOSCALE })
    if (show.l2 && data.l2_strip?.length) {
      configureL2Scale(pc)
      series.current.l2 = pc.addHistogramSeries({ priceScaleId: 'l2' })
    }
    if (show.macd && macdRef.current) { const mc = mk(macdRef.current, 110); series.current.macd = mc.addLineSeries({ color: p.series[0], lineWidth: 1 }); series.current.signal = mc.addLineSeries({ color: p.warning, lineWidth: 1 }); series.current.hist = mc.addHistogramSeries({}) }
    if (show.rsi && rsiRef.current) { const rc = mk(rsiRef.current, 90); series.current.rsi = rc.addLineSeries({ color: p.series[3], lineWidth: 1 }); ;[30, 70].forEach(lv => series.current.rsi.createPriceLine({ price: lv, color: p.series[3] + '55', lineWidth: 1, lineStyle: 2, axisLabelVisible: false })) }

    // Collect annotation prices for deterministic candle autoscale (BUY/SELL + plan + exec overlays).
    const levels: number[] = []
    for (const m of data.markers || []) if (m.price != null && Number(m.price) > 0) levels.push(Number(m.price))
    const t0: any = trade as any
    const plannedStop = Number(t0.stop ?? t0.stop_loss ?? t0.planned_stop) || null
    const plannedTgt = Number(t0.target ?? t0.target_1 ?? t0.target_price) || null
    if (plannedStop) levels.push(plannedStop)
    if (plannedTgt) levels.push(plannedTgt)
    const ex: any = (trade as any).exec
    if (ex) {
      const ep = Number(ex.entry_price) || 0
      if (ex.mfe_after_entry != null && ep) levels.push(ep + Number(ex.mfe_after_entry))
      if (ex.mae_after_entry != null && ep) levels.push(ep - Number(ex.mae_after_entry))
      if (ex.post_exit_high != null) levels.push(Number(ex.post_exit_high))
    }
    levelPricesRef.current = levels.filter(p => Number.isFinite(p) && p > 0)

    // HTML legend for secondary overlays — keeps the right axis uncluttered so BUY/SELL stay visible.
    const legend: OverlayLevel[] = []
    const addLine = (price: number, color: string, label: string, lineStyle = 2, onAxis = false) => {
      candle.createPriceLine({
        price, color, lineWidth: 1, lineStyle,
        axisLabelVisible: onAxis,
        title: onAxis ? label : '',
      })
      if (!onAxis) legend.push({ price, color, label })
    }

    for (const m of data.markers || []) {
      if (m.price == null || !Number.isFinite(Number(m.price)) || Number(m.price) <= 0 || m.kind && !['buy', 'sell'].includes(m.kind)) continue
      const isEntry = m.kind === 'buy' || m.type === 'entry'
      addLine(Number(m.price), isEntry ? p.success : p.danger, isEntry ? `BUY ${m.price}` : `SELL ${m.price}`, 2, true)
    }
    if (plannedStop) addLine(plannedStop, p.danger, `STOP ${plannedStop}`, 0)
    if (plannedTgt) addLine(plannedTgt, p.success, `TARGET ${plannedTgt}`, 0)
    if (ex) {
      const ep = Number(ex.entry_price) || 0
      if (ex.mfe_after_entry != null && ep) addLine(ep + Number(ex.mfe_after_entry), p.series[0], `MFE +${(100 * Number(ex.mfe_after_entry) / ep).toFixed(1)}%`, 1)
      if (ex.mae_after_entry != null && ep) addLine(ep - Number(ex.mae_after_entry), p.series[3], `MAE -${(100 * Number(ex.mae_after_entry) / ep).toFixed(1)}%`, 3)
      if (ex.post_exit_high != null) {
        const rt = ex.runner_type as string | undefined
        const gb = ex.post_exit_gave_back_ratio != null ? ` · gave back ${Math.round(100 * Number(ex.post_exit_gave_back_ratio))}%` : ''
        const rtLabel = rt === 'parabolic_pump' ? `Post-exit pump${gb}`
          : rt === 'sustained_trend' ? 'Post-exit runner'
          : rt === 'trend_top' ? 'Trend top after exit'
          : rt === 'faded' ? 'Faded after exit'
          : `Post-exit high $${Number(ex.post_exit_high).toFixed(2)}`
        addLine(Number(ex.post_exit_high), rt === 'sustained_trend' ? p.success : p.warning, rtLabel, 1)
      }
    }
    if (embedded && data.stop_steps?.length) series.current.stop = pc.addLineSeries({ color: p.danger, lineWidth: 1, lineType: LineType.WithSteps, priceLineVisible: false, lastValueVisible: false, ...NO_PRICE_AUTOSCALE })
    setOverlayLevels(legend)

    // Trade-centric time window: entry context + post-exit bars for opportunity-cost review.
    focusRangeRef.current = computeTradeFocusRange(data.bars, (data.markers || []).map((m: any) => ({ ...m, type: m.kind === 'buy' ? 'entry' : m.kind === 'sell' ? 'exit' : m.type })), { preBars: 25, postBars: 30 })

    const cur = replayCursorRef.current
    paint(cur <= 0 ? data.bars.length : cur, { fitTime: true })
    const unlink = linkTimeScales(charts.current)
    const onResize = () => syncReplayCharts(charts.current, priceChart.current, series.current.candle, { fitTime: true })
    window.addEventListener('resize', onResize)
    return () => { unlink(); window.removeEventListener('resize', onResize); charts.current.forEach(c => c.remove()); charts.current = []; priceChart.current = null }
  }, [data, show.vol, show.vwap, show.macd, show.rsi, show.spy, show.l2, theme])

  // replay paint: reveal the first `count` bars (0 => all)
  const paint = useCallback((count: number, opts?: { fitTime?: boolean }) => {
    if (!data?.bars) return
    const k = count <= 0 ? data.bars.length : count
    const cut = (arr: any[]) => (arr || []).filter((_: any, i: number) => i < k)
    const shown = new Set(cut(data.bars).map((b: any) => String(b.time)))
    const shownTime = (t: any) => shown.has(String(t))
    const visBars = cut(data.bars)
    visibleBarsRef.current = visBars

    series.current.candle?.setData(data.kind === 'closes' ? visBars.map((b: any) => ({ time: b.time, value: b.close })) : visBars)
    series.current.vol?.setData(cut(data.volume))
    series.current.vwap?.setData(cut(data.vwap))
    series.current.macd?.setData(cut(data.macd).map((x: any) => ({ time: x.time, value: x.macd })))
    series.current.signal?.setData(cut(data.macd).map((x: any) => ({ time: x.time, value: x.signal })))
    series.current.hist?.setData(cut(data.macd).map((x: any) => ({ time: x.time, value: x.hist, color: x.hist >= 0 ? p.success + '80' : p.danger + '80' })))
    series.current.rsi?.setData(cut(data.rsi))
    series.current.spy?.setData((data.spy_overlay || []).filter((x: any) => shownTime(x.time)))
    series.current.l2?.setData((data.l2_strip || []).filter((x: any) => shownTime(x.time)).map((x: any) => ({ time: x.time, value: x.value, color: x.value >= 0 ? p.success + '99' : p.danger + '99' })))

    if (series.current.stop) series.current.stop.setData((data.stop_steps || []).filter((m: any) => m.price != null && shown.has(String(m.time))).map((m: any) => ({ time: m.time, value: m.price })))
    // Legacy trade markers always render (not gated by replay cursor) — size 2 for visibility.
    const tradeMarkers = (data.markers || []).filter((m: any) => !embedded || shown.has(String(m.time))).map((m: any) => {
      const buy = m.kind === 'buy' || m.type === 'entry', sell = m.kind === 'sell' || m.type === 'exit'
      return { time: m.time, position: buy ? 'belowBar' : 'aboveBar', color: buy ? p.success : sell ? p.danger : m.kind === 'cio' ? p.warning : p.danger,
        shape: buy ? 'arrowUp' : sell ? 'arrowDown' : m.kind === 'cio' ? 'square' : 'circle', text: m.label, size: 2 }
    })
    const mks = [...tradeMarkers]
    if (data.session_open_time && shown.has(String(data.session_open_time)))
      mks.push({ time: data.session_open_time, position: 'aboveBar', color: p.warning, shape: 'circle', text: '9:30 open' })
    if (data.session_close_time && shown.has(String(data.session_close_time)))
      mks.push({ time: data.session_close_time, position: 'aboveBar', color: p.warning, shape: 'circle', text: '16:00 close' })
    for (const am of (data.alert_markers || []))
      if (shown.has(String(am.time))) mks.push({ time: am.time, position: 'aboveBar', color: alertColor(String(am.kind), p),
        shape: 'square', text: `${ALERT_SHORT[String(am.kind)] ?? am.kind} ${String(am.at_et || '').slice(0, 5)}${am.latency_s != null ? ` +${Math.round(am.latency_s)}s` : ''}` })
    for (const ne of (data.news_events || []))
      if (shown.has(String(ne.time))) mks.push({ time: ne.time, position: 'aboveBar', color: p.series[5], shape: 'circle', text: '📰' })
    mks.sort((a: any, b: any) => (typeof a.time === 'number' ? a.time - b.time : String(a.time).localeCompare(String(b.time))))
    series.current.candle?.setMarkers(mks)

    const fitTime = opts?.fitTime ?? false
    // Full view: trade window + 30 post-exit bars. Replay scrub: expand focus with revealed bars.
    const focus = fitTime
      ? (count <= 0
        ? focusRangeRef.current
        : computeTradeFocusRange(visBars, data.markers || [], { preBars: 10, postBars: 20 }))
      : null
    syncReplayCharts(charts.current, priceChart.current, series.current.candle, { fitTime, focusRange: focus })

    const integrityBars = allBarsRef.current.length ? allBarsRef.current : visBars
    const ohlcBounds = computeOhlcBounds(integrityBars)
    const integrity = checkPriceIntegrity(ohlcBounds, trade.symbol, data.price_bounds, data.integrity?.marker_aligned)
    const markerWarn = (data.integrity?.marker_aligned === false || data.integrity?.marker_in_range === false)
      ? (data.integrity.marker_warnings || []).join('; ')
      : ''
    const timeWarn = (data.integrity?.time_warnings || []).join('; ')
    const warn = [integrity, markerWarn, timeWarn].filter(Boolean).join(' · ')
    setScaleWarn(warn)
    if (DEV && ohlcBounds) {
      console.debug(`[replay-scale] ${trade.symbol} bars=${visBars.length}/${integrityBars.length}`, {
        ohlcBounds,
        api: data.price_bounds,
        integrity: data.integrity,
      })
    }
  }, [data, trade.symbol, theme, embedded])

  useEffect(() => { paint(n) }, [n, paint])
  useEffect(() => { paint(n) }, [autoSyncScale])

  const resyncScale = () => {
    paint(n <= 0 ? data?.bars?.length || 0 : n, { fitTime: true })
  }

  // play animation — interval scales with speed (0.5x..8x)
  useEffect(() => {
    if (!playing || !data?.bars) return
    if (n === 0) setN(1)
    const step = Math.max(1, Math.floor(data.bars.length / 90))
    const id = setInterval(() => setN(v => { const nx = (v || 1) + step; if (nx >= data.bars.length) { setPlaying(false); return 0 } return nx }), Math.round(120 / speed))
    return () => clearInterval(id)
  }, [playing, data, speed])

  const controlButton = { background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, color: TOKENS.text[1], borderRadius: RADIUS.md, minHeight: 44, minWidth: 44, cursor: 'pointer' } as const
  const pnl = !embedded && data?.markers?.length === 2 ? (Number(data.markers[1].price) - Number(data.markers[0].price)) : null
  const ti = data?.integrity?.time_integrity
  const holdSec = ti?.hold_seconds
  const holdLabel = holdSec != null
    ? (holdSec < 60 ? `${holdSec}s` : holdSec < 3600 ? `${Math.round(holdSec / 60)}m` : `${(holdSec / 3600).toFixed(1)}h`)
    : null
  const fillSrc = ti?.fill_source || data?.fill_times?.source
  const timeWarn = (data?.integrity?.time_warnings || []).join('; ')

  return (
    <div data-testid="trade-replay-chart" data-replay-position={n} style={embedded ? { minWidth: 0 } : { position: 'fixed', inset: 0, background: TOKENS.bg[0], zIndex: 50, display: 'flex', justifyContent: 'center', alignItems: 'flex-start', padding: '4vh 2vw', overflow: 'auto' }} onClick={embedded ? undefined : onClose}>
      <div onClick={e => e.stopPropagation()} style={embedded ? { minWidth: 0, width: '100%' } : { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg, padding: 16, width: 'min(900px, 96vw)' }}>
        {!embedded && <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
          <div style={{ fontSize: TYPE.lg, fontWeight: 700, color: 'var(--text0)' }}>{trade.symbol} <span style={{ fontSize: TYPE.sm, color: 'var(--text3)', fontWeight: 400 }}>{String(trade.entry_date).slice(0, 10)} → {String(trade.exit_date || '').slice(0, 10)}</span></div>
          {data && <span style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>{data.timeframe}{(data as any).hold_days > 0 ? ` · ${(data as any).hold_days}d hold` : ''} · {data.bar_count} bars · src:{data.source}</span>}
          {data?.entry_et && data?.exit_et && (
            <span style={{ fontSize: TYPE.xs, color: data?.integrity?.times_valid === false ? p.warning : 'var(--text2)', fontFamily: FONT.mono }}
              title={[ti?.entry_marker_et && `Entry bar: ${ti.entry_marker_et}`, ti?.exit_marker_et && `Exit bar: ${ti.exit_marker_et}`, fillSrc && `Fill source: ${fillSrc}`, timeWarn].filter(Boolean).join('\n')}>
              {data.entry_et} → {data.exit_et}{holdLabel ? ` · ${holdLabel}` : ''}{fillSrc ? ` · ${fillSrc}` : ''}
            </span>
          )}
          {data?.price_bounds && DEV && (
            <span style={{ fontSize: TYPE.xs, color: 'var(--text3)', fontFamily: FONT.mono }} title="Loaded OHLC bounds">
              ${data.price_bounds.min_low}–${data.price_bounds.max_high}
            </span>
          )}
          {pnl != null && <span style={{ fontSize: TYPE.base, fontWeight: 700, color: pnl >= 0 ? p.success : p.danger }}>{pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}/sh</span>}
          {(trade as any).exec && <span style={{ fontSize: TYPE.xs, fontWeight: 700, padding: '1px 6px', borderRadius: RADIUS.sm, background: ((trade as any).exec.execution_grade === 'poor' ? p.danger : (trade as any).exec.execution_grade === 'weak' ? p.warning : p.success) + '22', color: (trade as any).exec.execution_grade === 'poor' ? p.danger : (trade as any).exec.execution_grade === 'weak' ? p.warning : p.success }}
            title={[
              ...[['no_volume_entry_flag', 'entered without volume confirmation'], ['premature_exit_flag', 'exited prematurely'],
                   ['early_entry_flag', 'entry early vs setup'], ['late_entry_flag', 'entry late/chased']]
                .filter(([k]) => (trade as any).exec[k]).map(([, label]) => `• ${label}`),
              (trade as any).exec.grok_what_to_do_next_time ? `Coach: ${(trade as any).exec.grok_what_to_do_next_time}` : ((trade as any).exec.computed_summary || ''),
            ].filter(Boolean).join('\n')}>{(trade as any).exec.outcome_grade}/{(trade as any).exec.execution_grade} · cap {Math.round(((trade as any).exec.capture_ratio ?? 0) * 100)}%</span>}
          <span style={{ flex: 1 }} />
          {(['vol', 'vwap', 'macd', 'rsi', 'spy', 'l2'] as const).map(k => <button key={k} onClick={() => setShow(s => ({ ...s, [k]: !s[k] }))} style={{ fontSize: TYPE.xs, padding: '2px 7px', borderRadius: RADIUS.sm, border: '1px solid var(--border)', background: show[k] ? p.series[0] : 'var(--bg2)', color: show[k] ? TOKENS.text[0] : 'var(--text3)', cursor: 'pointer' }}>{k.toUpperCase()}</button>)}
          <button onClick={onClose} style={{ fontSize: TYPE.sm, padding: '2px 9px', borderRadius: RADIUS.sm, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer' }}>✕</button>
        </div>

        }
        {err && <div style={{ fontSize: TYPE.base, color: p.danger, padding: 20 }}>Chart unavailable: {err}</div>}
        {scaleWarn && (
          <div style={{ fontSize: TYPE.xs, color: p.warning, padding: '4px 8px', marginBottom: 6, borderRadius: RADIUS.sm, background: toneVars('warning').bg, border: `1px solid ${toneVars('warning').border}` }}>
            ⚠ {scaleWarn}
          </div>
        )}
        {data?.fallback === 'finviz' && fvImg && <div style={{ padding: 8 }}><div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginBottom: 6 }}>No Alpaca/Schwab bars — Finviz Elite chart image:</div><img src={fvImg} alt={trade.symbol} style={{ width: '100%', borderRadius: RADIUS.sm }} /></div>}
        {!err && data?.bars?.length > 0 && <>
          {overlayLevels.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8, padding: '6px 8px', borderRadius: RADIUS.md, background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}` }}>
              <span style={{ fontSize: TYPE.xs, color: 'var(--text3)', alignSelf: 'center', marginRight: 2 }}>Levels</span>
              {overlayLevels.map((lv, i) => (
                <span key={i} title={`$${lv.price.toFixed(2)}`} style={{ fontSize: TYPE.xs, padding: '2px 8px', borderRadius: RADIUS.sm, border: `1px solid ${lv.color}55`, color: lv.color, background: `${lv.color}18`, whiteSpace: 'nowrap' }}>
                  {lv.label}
                </span>
              ))}
            </div>
          )}
          <div ref={priceRef} style={{ width: '100%' }} />
          {show.macd && <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginTop: 4 }}>MACD</div>}
          <div ref={macdRef} style={{ width: '100%', display: show.macd ? 'block' : 'none' }} />
          {show.rsi && <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginTop: 4 }}>RSI</div>}
          <div ref={rsiRef} style={{ width: '100%', display: show.rsi ? 'block' : 'none' }} />
        {(data?.alert_markers?.length ?? 0) > 0 && (
          <div style={{ marginTop: 6, fontSize: TYPE.xs, color: 'var(--text3)' }} data-testid="trade-chart-alerts">
            <b style={{ color: 'var(--text2)' }}>Active Trader alerts in this window:</b>
            {data.alert_markers.slice(0, 12).map((am: any, i: number) => (
              <div key={i} style={{ marginTop: 2 }}>
                <span style={{ color: alertColor(String(am.kind), p), fontWeight: 600 }}>{am.at_et}</span> · {String(am.kind).replace('_', ' ')}
                {am.intrabar ? ' (intrabar)' : ''} · last {am.last ?? '—'}{am.entry != null ? ` · entry ${Number(am.entry).toFixed(3)}` : ''}
                {am.latency_s != null && <span> · {Math.round(am.latency_s)}s after {String(am.latency_event || '').replace('_', ' ')}</span>}
                {am.sent ? ' · ✓ Telegram' : ''}{am.source === 'fast' ? ' · fast loop' : ''}
              </div>
            ))}
          </div>
        )}
        {(data?.news_events?.length ?? 0) > 0 && (
          <div style={{ marginTop: 6, fontSize: TYPE.xs, color: 'var(--text3)' }}>
            <b style={{ color: p.series[5] }}>📰 News during trade window:</b>
            {data.news_events.slice(0, 6).map((ne: any, i: number) => (
              <div key={i} style={{ marginTop: 2 }}>
                <span style={{ color: 'var(--text2)', fontWeight: 600 }}>{ne.at_et}</span>{ne.clamped && <span style={{ color: p.warning }}> ({ne.clamped}-window)</span>} · {ne.title}
                {ne.source && <span style={{ opacity: .6 }}> ({String(ne.source).slice(0, 24)})</span>}
              </div>
            ))}
          </div>
        )}
          <div className="tradeinview-controls" style={{ gap: 10, marginTop: 10 }}>
            <button type="button" aria-label="Step back" onClick={() => { setPlaying(false); setN(v => Math.max(1, (v || data.bars.length) - 1)) }} style={{ ...controlButton }}>⏮</button>
            <button type="button" aria-label="Step forward" onClick={() => { setPlaying(false); setN(v => Math.min(data.bars.length, (v || data.bars.length) + 1)) }} style={{ ...controlButton }}>⏭</button>
            <button type="button" aria-label={playing ? 'Pause' : 'Play'} onClick={() => setPlaying(p => !p)} style={{ fontSize: TYPE.base, padding: '4px 12px', borderRadius: RADIUS.sm, border: '1px solid var(--border)', background: playing ? p.danger : p.success, color: TOKENS.text[0], cursor: 'pointer', fontWeight: 700 }}>{playing ? '❚❚ pause' : '▶ replay'}</button>
            <button onClick={() => setAutoSyncScale(v => !v)} title="Auto-sync Y-axis to visible replay bars (off = lock to full trade)" style={{ fontSize: TYPE.xs, padding: '4px 10px', borderRadius: RADIUS.sm, border: '1px solid var(--border)', background: autoSyncScale ? p.series[0] : 'var(--bg2)', color: autoSyncScale ? TOKENS.text[0] : 'var(--text2)', cursor: 'pointer' }}>{autoSyncScale ? '⟳ Auto scale' : '🔒 Locked'}</button>
            <button onClick={resyncScale} title="Re-fit price and time axes now" style={{ fontSize: TYPE.xs, padding: '4px 10px', borderRadius: RADIUS.sm, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer' }}>↻ Re-sync</button>
            <div style={{ display: 'flex', gap: 2 }} title="Replay speed">
              {(embedded ? [1, 4, 16] : [0.5, 1, 2, 4, 8]).map(s => <button key={s} onClick={() => setSpeed(s)} style={{ fontSize: TYPE.xs, padding: '3px 6px', borderRadius: RADIUS.sm, border: '1px solid var(--border)', background: speed === s ? p.series[0] : 'var(--bg2)', color: speed === s ? TOKENS.text[0] : 'var(--text3)', cursor: 'pointer' }}>{s}×</button>)}
            </div>
            <input type="range" aria-label="Replay position" min={1} max={data.bars.length} value={n === 0 ? data.bars.length : n} onChange={e => { setPlaying(false); setN(Number(e.target.value)) }} style={{ flex: 1 }} />
            <span style={{ fontSize: TYPE.xs, color: 'var(--text3)', minWidth: 70, textAlign: 'right' }}>{n === 0 ? data.bars.length : n}/{data.bars.length} bars</span>
          </div>
        </>}
        {!err && data && !data.bars?.length && <div className="tradeinview-gap" style={{ padding: 24, fontSize: TYPE.base }}>No stored bars available for this trade and interval.</div>}
        {!err && !data && <div style={{ fontSize: TYPE.base, color: 'var(--text3)', padding: 30, textAlign: 'center' }}>Loading {trade.symbol} chart…</div>}
      </div>
    </div>
  )
}
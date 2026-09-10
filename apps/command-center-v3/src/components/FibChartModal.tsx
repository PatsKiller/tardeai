import { useEffect, useRef, useState } from 'react'
import { createChart, IChartApi } from 'lightweight-charts'
import { BB, T } from '../lib/watchTokens'

// Multi-timeframe Fib chart modal: stacks a DAILY and a MONTHLY candlestick chart, each drawing the
// levels relevant to that pane (Fib retr/ext · swing hi/lo · confluence) as horizontal price lines, with
// the clicked level highlighted. Read-only. Bars come from the fib-confluence engine (no extra fetch).
//
// Decluttering strategy (holding drawer): draw only the levels the current "mode" selects within a
// near-price / visible-range gate, dedupe levels that stack at the same price, put axis labels on a
// priority subset only (confluence + highlight + nearest above/below), pin the price scale to the recent
// window so an old swing/outlier can't squash recent candles, and skip the time scale to the latest bars.

// Semantic chart colors — single source of truth (BB/T tokens, no raw hex in components).
const FIB_COLOR = {
  swingHi: BB.red,
  swingLo: BB.green,
  retr: T.link,
  ext: T.extIntel.hermes,
  confluence: BB.amber,
  text3: BB.text3,
} as const

export type FibLevel = {
  price: number
  title: string
  color: string
  bold?: boolean
  showAxis?: boolean
  tf?: 'D' | 'W' | 'M'
  kind?: 'swing_hi' | 'swing_lo' | 'fib_retr' | 'fib_ext' | 'confluence'
  ratio?: number
}

export type FibMode = 'core' | 'allFibs' | 'extensions' | 'allTfs' | 'confluenceOnly'

export const FIB_MODES: { id: FibMode; label: string }[] = [
  { id: 'core', label: 'Core' },
  { id: 'allFibs', label: 'All Fibs' },
  { id: 'extensions', label: 'Extensions' },
  { id: 'allTfs', label: 'All TFs' },
  { id: 'confluenceOnly', label: 'Confluence only' },
]

const CORE_RATIOS = new Set([0.382, 0.5, 0.618])
const NEAR_PCT = 0.05            // near-price gate for core/confluence modes (vs last close)
const DEDUPE_PCT = 0.0015        // levels within this % of price stack into one label
const DAILY_FOCUS = 60           // last N daily bars shown by default
const MONTHLY_FOCUS = 36         // last N monthly bars shown by default

const DARK = {
  layout: { background: { color: 'transparent' }, textColor: FIB_COLOR.text3 },
  grid: { vertLines: { color: 'rgba(255,255,255,.04)' }, horzLines: { color: 'rgba(255,255,255,.04)' } },
  timeScale: { borderColor: 'rgba(255,255,255,.1)', timeVisible: false },
  rightPriceScale: { borderColor: 'rgba(255,255,255,.1)' },
}

// every analyzed level in a fib-confluence response → tagged FibLevel (source TF + kind + ratio for the legend/modes)
export function buildFibLevels(data: any, highlight?: number): FibLevel[] {
  const out: FibLevel[] = []
  for (const t of (data?.timeframes ?? []).filter((x: any) => x.available)) {
    const tag = (t.timeframe[0] || '').toUpperCase() as 'D' | 'W' | 'M'
    out.push({ price: t.swing_high, title: `${tag} swing hi`, color: FIB_COLOR.swingHi, tf: tag, kind: 'swing_hi' })
    out.push({ price: t.swing_low, title: `${tag} swing lo`, color: FIB_COLOR.swingLo, tf: tag, kind: 'swing_lo' })
    for (const r of t.retracements) out.push({ price: r.price, title: `${tag} ${r.label}`, color: FIB_COLOR.retr, tf: tag, kind: 'fib_retr', ratio: r.ratio })
    for (const e of t.extensions) out.push({ price: e.price, title: `${tag} ext ${e.label}`, color: FIB_COLOR.ext, tf: tag, kind: 'fib_ext', ratio: e.ratio })
  }
  for (const z of (data?.confluence_zones ?? []).slice(0, 4)) out.push({ price: z.price_mid, title: `confluence (${z.confidence})`, color: FIB_COLOR.confluence, kind: 'confluence' })
  return out.map(l => ({ ...l, bold: highlight != null && Math.abs(l.price - highlight) < 0.01 }))
}

function includeByMode(l: FibLevel, paneTf: 'D' | 'M', mode: FibMode): boolean {
  if (mode === 'confluenceOnly') return l.kind === 'confluence'
  if (l.kind === 'confluence') return true
  if (mode === 'core') {
    if (l.kind === 'swing_hi' || l.kind === 'swing_lo') return l.tf === paneTf
    if (l.kind === 'fib_retr') return (l.tf === 'D' || l.tf === 'W') && CORE_RATIOS.has(l.ratio ?? -1)
    return false
  }
  if (mode === 'allTfs') {
    if (l.kind === 'swing_hi' || l.kind === 'swing_lo') return true
    if (l.kind === 'fib_retr') return CORE_RATIOS.has(l.ratio ?? -1)
    return false
  }
  if (mode === 'extensions') {
    if (l.kind === 'fib_ext') return true
    if (l.kind === 'swing_hi' || l.kind === 'swing_lo') return l.tf === paneTf
    return false
  }
  if (mode === 'allFibs') return true
  return false
}

// Merge levels that stack within DEDUPE_PCT into one (combined title; confluence/bold styling wins).
function dedupeLevels(draw: FibLevel[], lastClose: number): FibLevel[] {
  const tol = Math.max(0.01, lastClose * DEDUPE_PCT)
  const out: FibLevel[] = []
  for (const l of draw) {
    const hit = out.find(o => Math.abs(o.price - l.price) <= tol)
    if (!hit) { out.push({ ...l }); continue }
    if (l.kind === 'confluence') { hit.kind = 'confluence'; hit.color = FIB_COLOR.confluence }
    if (l.kind === 'confluence' || l.bold) hit.bold = true
    const parts = hit.title.split(' · ')
    if (!parts.includes(l.title)) parts.push(l.title)
    hit.title = parts.slice(0, 3).join(' · ')
  }
  return out
}

export type FibSelection = { draw: FibLevel[]; offScale: FibLevel[] }

// Select which catalog levels to draw on a pane, gated to the recent window so the view stays readable.
export function selectFibLevelsForChart(opts: {
  levels: FibLevel[]
  bars: any[]
  paneTf: 'D' | 'M'
  mode: FibMode
  focusBars?: number
}): FibSelection {
  const { levels, bars, paneTf, mode, focusBars = DAILY_FOCUS } = opts
  if (!bars?.length) return { draw: [], offScale: [] }
  const lastClose = bars[bars.length - 1].c
  const from = Math.max(0, bars.length - focusBars)
  let lo = Infinity, hi = -Infinity
  for (let i = from; i < bars.length; i++) { lo = Math.min(lo, bars[i].l); hi = Math.max(hi, bars[i].h) }

  const included = levels.filter(l => l.price > 0 && includeByMode(l, paneTf, mode))
  const draw0: FibLevel[] = []
  const offScale: FibLevel[] = []
  // Swings + confluence are near-price gated (±5% of last close) so a far swing extreme (e.g. a
  // monthly $83.86 swing on a ~$35 name) never lands on the pane. Fib retr/ext are range-gated to the
  // recent window instead — otherwise a symbol sitting at its swing high would hide its own retracements.
  const confluenceOnly = mode === 'confluenceOnly'
  for (const l of included) {
    let ok = true
    if (!confluenceOnly) {
      ok = (l.kind === 'confluence' || l.kind === 'swing_hi' || l.kind === 'swing_lo')
        ? Math.abs(l.price - lastClose) / lastClose <= NEAR_PCT
        : (l.price >= lo * 0.97 && l.price <= hi * 1.03)
    }
    ;(ok ? draw0 : offScale).push(l)
  }

  const draw = dedupeLevels(draw0, lastClose)

  // Axis labels: confluence + highlighted + nearest level above/below last close only.
  let above: FibLevel | null = null
  let below: FibLevel | null = null
  for (const l of draw) {
    if (l.price >= lastClose) { if (!above || l.price < above.price) above = l }
    else if (!below || l.price > below.price) below = l
  }
  const keys = new Set<string>()
  const mark = (l: FibLevel | null) => { if (l) keys.add(String(Math.round(l.price * 100))) }
  for (const l of draw) if (l.kind === 'confluence' || l.bold) mark(l)
  mark(above); mark(below)
  for (const l of draw) l.showAxis = keys.has(String(Math.round(l.price * 100)))

  return { draw, offScale }
}

export function TFChart({ label, bars, levels, paneTf, mode = 'core', focusBars = DAILY_FOCUS, latestNonce = 0 }: {
  label: string
  bars: any[]
  levels: FibLevel[]
  paneTf: 'D' | 'M'
  mode?: FibMode
  focusBars?: number
  latestNonce?: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current || !bars?.length) return
    const c: IChartApi = createChart(ref.current, { ...DARK, width: ref.current.clientWidth, height: 300, autoSize: true } as any)
    const candle = c.addCandlestickSeries({
      upColor: BB.green, downColor: BB.red, borderVisible: false, wickUpColor: BB.green, wickDownColor: BB.red,
      // Pin price scale to the recent window so a distant swing high/outlier can't squash recent candles.
      autoscaleInfoProvider: () => {
        const from = Math.max(0, bars.length - focusBars)
        let lo = Infinity, hi = -Infinity
        for (let i = from; i < bars.length; i++) { lo = Math.min(lo, bars[i].l); hi = Math.max(hi, bars[i].h) }
        if (!Number.isFinite(lo)) return null
        const span = hi - lo
        const pad = span > 0 ? span * 0.06 : Math.max(hi * 0.02, 0.01)
        return { priceRange: { minValue: lo - pad, maxValue: hi + pad }, margins: { above: 12, below: 12 } }
      },
    })
    candle.setData(bars.map(b => ({ time: b.t, open: b.o ?? b.l, high: b.h, low: b.l, close: b.c })))

    const { draw } = selectFibLevelsForChart({ levels, bars, paneTf, mode, focusBars })
    for (const lv of draw) {
      const solid = lv.kind === 'confluence' || lv.bold
      candle.createPriceLine({
        price: lv.price, color: lv.color,
        lineWidth: solid ? 2 : 1,
        lineStyle: solid ? 0 : 2,
        axisLabelVisible: !!lv.showAxis,
        title: lv.title,
      })
    }

    c.timeScale().applyOptions({ rightOffset: 6, barSpacing: 6 })
    c.timeScale().setVisibleLogicalRange({ from: Math.max(0, bars.length - focusBars), to: bars.length + 2 })
    return () => c.remove()
  }, [bars, levels, paneTf, mode, focusBars, latestNonce])
  return (
    <div style={{ flex: '1 1 380px', minWidth: 320 }}>
      <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text2)', marginBottom: 4 }}>{label}</div>
      {bars?.length ? <div ref={ref} style={{ width: '100%' }} /> : <div style={{ padding: 30, textAlign: 'center', color: 'var(--text3)', fontSize: 11 }}>no {label.toLowerCase()} data</div>}
    </div>
  )
}

function groupForLegend(levels: FibLevel[]) {
  const confluence: FibLevel[] = []
  const swings: FibLevel[] = []
  const fibs: { D: FibLevel[]; W: FibLevel[]; M: FibLevel[] } = { D: [], W: [], M: [] }
  const extensions: FibLevel[] = []
  for (const l of levels) {
    if (l.kind === 'confluence') confluence.push(l)
    else if (l.kind === 'swing_hi' || l.kind === 'swing_lo') swings.push(l)
    else if (l.kind === 'fib_retr') fibs[l.tf ?? 'D'].push(l)
    else if (l.kind === 'fib_ext') extensions.push(l)
  }
  return { confluence, swings, fibs, extensions }
}

function unionLevels(a: FibLevel[], b: FibLevel[]): FibLevel[] {
  const seen = new Set<string>()
  const out: FibLevel[] = []
  for (const l of [...a, ...b]) {
    const k = String(Math.round(l.price * 100))
    if (seen.has(k)) continue
    seen.add(k)
    out.push(l)
  }
  return out
}

const LEGEND_LABEL = { fontSize: 10, fontWeight: 800, color: 'var(--text3)', minWidth: 68, textTransform: 'uppercase', letterSpacing: 0.3 } as const
const LEGEND_ITEM = { fontSize: 10, display: 'flex', alignItems: 'center', gap: 4 } as const

function FibLegend({ drawn, offScale, compact }: { drawn: FibLevel[]; offScale: FibLevel[]; compact?: boolean }) {
  const g = groupForLegend(drawn)
  const sections: { label: string; items: FibLevel[] }[] = [
    { label: 'Confluence', items: g.confluence },
    { label: 'Swings', items: g.swings },
    { label: 'Fibs', items: [...g.fibs.D, ...g.fibs.W, ...g.fibs.M] },
    { label: 'Extensions', items: g.extensions },
  ]
  const shown = sections.filter(s => s.items.length)
  return (
    <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {shown.map(s => (
        <div key={s.label} style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={LEGEND_LABEL}>{s.label}</span>
          {s.items.map((l, i) => (
            <span key={i} style={{ ...LEGEND_ITEM, color: l.color }}>
              <span style={{ width: 10, height: (l.kind === 'confluence' || l.bold) ? 2 : 1, background: l.color, display: 'inline-block' }} />{l.title} ${l.price}
            </span>
          ))}
        </div>
      ))}
      {offScale.length > 0 && !compact && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', opacity: .55 }}>
          <span style={LEGEND_LABEL}>Outside view</span>
          {offScale.map((l, i) => <span key={i} style={{ ...LEGEND_ITEM, color: l.color }}>{l.title} ${l.price}</span>)}
        </div>
      )}
      {compact && offScale.length > 0 && <span style={{ fontSize: 10, color: 'var(--text3)' }}>+{offScale.length} more — All Fibs</span>}
    </div>
  )
}

const chip = (active: boolean) => ({
  fontSize: 10, fontWeight: 700, padding: '3px 10px', borderRadius: 6, cursor: 'pointer',
  border: '1px solid var(--border)',
  background: active ? 'rgba(148,163,184,.16)' : 'transparent',
  color: active ? 'var(--text0)' : 'var(--text2)',
})

// Shared daily + monthly chart body (mode chips + Latest + grouped legend) for inline + modal.
export function FibChartsView({ bars, barsMonthly, levels, compact }: {
  bars: any[]
  barsMonthly?: any[]
  levels: FibLevel[]
  compact?: boolean
}) {
  const [mode, setMode] = useState<FibMode>('core')
  const [latestNonce, setLatestNonce] = useState(0)

  const dailySel = bars?.length ? selectFibLevelsForChart({ levels, bars, paneTf: 'D', mode, focusBars: DAILY_FOCUS }) : null
  const monthlySel = barsMonthly?.length ? selectFibLevelsForChart({ levels, bars: barsMonthly, paneTf: 'M', mode, focusBars: MONTHLY_FOCUS }) : null
  const drawn = unionLevels(dailySel?.draw ?? [], monthlySel?.draw ?? [])
  const offScale = unionLevels(dailySel?.offScale ?? [], monthlySel?.offScale ?? [])

  return (
    <div>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        <TFChart label="Daily" bars={bars} levels={levels} paneTf="D" mode={mode} focusBars={DAILY_FOCUS} latestNonce={latestNonce} />
        {barsMonthly?.length ? <TFChart label="Monthly" bars={barsMonthly} levels={levels} paneTf="M" mode={mode} focusBars={MONTHLY_FOCUS} latestNonce={latestNonce} /> : null}
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8, alignItems: 'center' }}>
        {FIB_MODES.map(m => (
          <button key={m.id} onClick={() => setMode(m.id)} style={chip(mode === m.id)}>{m.label}</button>
        ))}
        <button onClick={() => setLatestNonce(n => n + 1)} style={chip(false)}>Latest</button>
      </div>
      <FibLegend drawn={drawn} offScale={offScale} compact={compact} />
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
        <FibChartsView bars={bars} barsMonthly={barsMonthly} levels={levels} />
      </div>
    </div>
  )
}

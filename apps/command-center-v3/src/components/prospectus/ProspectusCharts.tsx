/** Ticker Prospectus charts — rendered from the prospectus `charts[]` (contract 2026-10-26).
 *  line → price with stop / entry reference lines; bar → grouped bars; range → analyst target range bar.
 *  Colours come from CHART_HEX per resolved theme (recharts props cannot read CSS vars); chrome uses tokens. */
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CHART_HEX, RADIUS, TOKENS, TYPE, numStyle } from '../../lib/designTokens'
import { useTheme } from '../../hooks/useTheme'
import { chartKind, chartRows, priceLines, targetRange, type ProspectusChart } from '../../lib/prospectusModel'

const H = 220

function ChartFrame({ chart, children }: { chart: ProspectusChart; children: React.ReactNode }) {
  return (
    <figure className="psp-chart" data-testid="prospectus-chart" data-chart-id={chart.id} data-chart-type={chart.type}>
      <figcaption className="psp-chart-title">{chart.title}</figcaption>
      {children}
    </figure>
  )
}

function LineChartView({ chart }: { chart: ProspectusChart }) {
  const [, , theme] = useTheme()
  const hex = CHART_HEX[theme]
  const rows = chartRows(chart.series)
  const lines = priceLines(chart)
  const lineHex = { danger: hex.danger, success: hex.success, warning: hex.warning, info: hex.series[0] }
  const ys = [...rows.flatMap(r => chart.series.map(s => r[s.name])).filter((v): v is number => typeof v === 'number'), ...lines.map(l => l.y)]
  const lo = ys.length ? Math.min(...ys) : 0, hi = ys.length ? Math.max(...ys) : 1
  const pad = (hi - lo) * 0.08 || 1
  return (
    <ChartFrame chart={chart}>
      <div style={{ width: '100%', height: H }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid stroke={hex.grid} strokeDasharray="3 3" />
            <XAxis dataKey="x" tick={{ fill: hex.text, fontSize: TYPE.xs }} stroke={hex.grid} minTickGap={16} />
            <YAxis domain={[lo - pad, hi + pad]} tick={{ fill: hex.text, fontSize: TYPE.xs }} stroke={hex.grid} tickFormatter={v => Number(v).toFixed(0)} />
            <Tooltip contentStyle={{ background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, fontSize: TYPE.sm }} />
            {chart.series.map((s, i) => <Line key={s.name} type="monotone" dataKey={s.name} stroke={hex.series[(i + 0) % hex.series.length]} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />)}
            {lines.map((l, i) => (
              <ReferenceLine key={i} y={l.y} stroke={lineHex[l.tone]} strokeDasharray="5 4" strokeWidth={1.5}
                label={{ value: l.label, position: 'insideTopRight', fill: lineHex[l.tone], fontSize: TYPE.xs }} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {lines.length > 0 && (
        <div className="psp-chart-legend" data-testid="prospectus-chart-levels">
          {lines.map((l, i) => <span key={i} className={`psp-level psp-tone-${l.tone}`}>{l.label}</span>)}
        </div>
      )}
    </ChartFrame>
  )
}

function BarChartView({ chart }: { chart: ProspectusChart }) {
  const [, , theme] = useTheme()
  const hex = CHART_HEX[theme]
  const rows = chartRows(chart.series)
  // Two series on very different scales (revenue vs EPS): the second gets its own right-hand axis so it stays readable.
  const maxOf = (name: string) => Math.max(0, ...rows.map(r => Math.abs(Number(r[name]) || 0)))
  const dual = chart.series.length === 2 && maxOf(chart.series[0].name) > 0 && maxOf(chart.series[1].name) > 0
    && Math.max(maxOf(chart.series[0].name), maxOf(chart.series[1].name)) / Math.min(maxOf(chart.series[0].name), maxOf(chart.series[1].name)) > 4
  return (
    <ChartFrame chart={chart}>
      <div style={{ width: '100%', height: H }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 8, right: dual ? 0 : 12, bottom: 0, left: -12 }}>
            <CartesianGrid stroke={hex.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="x" tick={{ fill: hex.text, fontSize: TYPE.xs }} stroke={hex.grid} />
            <YAxis yAxisId="l" tick={{ fill: hex.text, fontSize: TYPE.xs }} stroke={hex.grid} />
            {dual && <YAxis yAxisId="r" orientation="right" tick={{ fill: hex.series[1], fontSize: TYPE.xs }} stroke={hex.grid} />}
            <Tooltip cursor={{ fill: hex.grid, opacity: 0.3 }} contentStyle={{ background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, fontSize: TYPE.sm }} />
            {chart.series.length > 1 && <Legend wrapperStyle={{ fontSize: TYPE.sm, color: hex.text }} />}
            {chart.series.map((s, i) => <Bar key={s.name} yAxisId={dual && i === 1 ? 'r' : 'l'} dataKey={s.name} fill={hex.series[i % hex.series.length]} radius={[3, 3, 0, 0]} isAnimationActive={false} />)}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartFrame>
  )
}

/** Analyst target range: a low→high band with markers for the mean and the current price. Plain DOM, tokens only. */
function RangeView({ chart }: { chart: ProspectusChart }) {
  const r = targetRange(chart)
  const vals = [r.low, r.high, r.mean, r.current].filter((v): v is number => v != null)
  if (r.low == null || r.high == null || vals.length < 2) return <ChartFrame chart={chart}><p className="psp-muted">Target range not available in this version.</p></ChartFrame>
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1
  const at = (v: number) => `${((v - lo) / span) * 100}%`
  return (
    <ChartFrame chart={chart}>
      <div className="psp-range" data-testid="prospectus-target-range">
        <div className="psp-range-track">
          <div className="psp-range-band" style={{ left: at(r.low), width: `calc(${at(r.high)} - ${at(r.low)})` }} />
          {r.mean != null && <div className="psp-range-mark psp-range-mean" style={{ left: at(r.mean) }} title={`Mean ${r.mean}`} />}
          {r.current != null && <div className="psp-range-mark psp-range-current" style={{ left: at(r.current) }} title={`Price ${r.current}`} />}
        </div>
        <div className="psp-range-labels" style={numStyle}>
          <span>Low {r.low}</span>
          {r.mean != null && <span className="psp-tone-ai">Mean {r.mean}</span>}
          {r.current != null && <span className="psp-tone-info">Price {r.current}</span>}
          <span>High {r.high}</span>
        </div>
      </div>
    </ChartFrame>
  )
}

export default function ProspectusCharts({ charts }: { charts: ProspectusChart[] }) {
  const list = (charts ?? []).filter(c => c && (c.series?.length || c.annotations?.length))
  if (!list.length) return null
  return (
    <section className="psp-charts" aria-label="Charts" data-testid="prospectus-charts">
      {list.map(c => {
        const k = chartKind(c)
        if (k === 'line') return <LineChartView key={c.id} chart={c} />
        if (k === 'bar') return <BarChartView key={c.id} chart={c} />
        if (k === 'range') return <RangeView key={c.id} chart={c} />
        return <BarChartView key={c.id} chart={c} />
      })}
    </section>
  )
}

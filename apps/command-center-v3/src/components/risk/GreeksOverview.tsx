import { useMemo } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

type Position = {
  underlying?: string
  delta?: number
  qty?: number
  side?: string
  unrealized_pnl?: number
  dte?: number
}

const GREEK_COLORS: Record<string, string> = {
  'Net Δ': '#60a5fa',
  'Short Δ': '#f59e0b',
  'Long Δ': '#22c55e',
  'Est. Θ/day': '#a855f7',
}

type Props = { positions: Position[]; compact?: boolean }

/** Aggregate greeks from open option legs (delta from chain; theta estimated). */
export default function GreeksOverview({ positions, compact }: Props) {
  const { bars, summary } = useMemo(() => {
    let netDelta = 0
    let shortDelta = 0
    let longDelta = 0
    let thetaEst = 0
    for (const p of positions) {
      const d = Number(p.delta) || 0
      const q = Number(p.qty) || 1
      const mult = p.side === 'short' ? -1 : 1
      const legDelta = d * q * mult * 100
      netDelta += legDelta
      if (mult < 0) shortDelta += Math.abs(legDelta)
      else longDelta += legDelta
      const dte = Math.max(1, Number(p.dte) || 21)
      const markDecay = (Number(p.unrealized_pnl) || 0) / dte
      thetaEst += markDecay * 0.15
    }
    const bars = [
      { name: 'Net Δ', value: Math.round(netDelta * 10) / 10 },
      { name: 'Short Δ', value: Math.round(shortDelta * 10) / 10 },
      { name: 'Long Δ', value: Math.round(longDelta * 10) / 10 },
      { name: 'Est. Θ/day', value: Math.round(thetaEst) },
    ]
    return { bars, summary: { netDelta, legs: positions.length } }
  }, [positions])

  if (!positions.length) {
    return <div style={{ fontSize: 9, color: 'var(--text3)', fontStyle: 'italic' }}>No open option legs</div>
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text0)' }}>Greeks overview</div>
        <div style={{ fontSize: 9, color: 'var(--text3)' }}>{summary.legs} legs · net Δ {summary.netDelta.toFixed(1)}</div>
      </div>
      <ResponsiveContainer width="100%" height={compact ? 120 : 150}>
        <BarChart data={bars} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <XAxis dataKey="name" tick={{ fontSize: 9, fill: 'var(--text2)' }} />
          <YAxis tick={{ fontSize: 8, fill: 'var(--text3)' }} width={36} />
          <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} />
          <Bar dataKey="value" radius={[4, 4, 0, 0]}>
            {bars.map(b => <Cell key={b.name} fill={GREEK_COLORS[b.name] || '#60a5fa'} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div style={{ fontSize: 8, color: 'var(--text3)' }}>Δ from Schwab chain · Θ estimated from DTE decay (advisory)</div>
    </div>
  )
}
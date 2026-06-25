import { useMemo } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'
import { optionsPayoffCurve } from '../../lib/riskMath'

type Props = {
  underlying: string
  side?: string
  optionType?: string
  strike?: number
  spot?: number
  qty?: number
  avgEntry?: number
  mark?: number
  compact?: boolean
  hideTitle?: boolean
}

export default function OptionsPnLProfile({
  underlying, side = 'short', optionType = 'call', strike = 0, spot = 0,
  qty = 1, avgEntry, mark, compact, hideTitle,
}: Props) {
  const data = useMemo(() => {
    if (!strike || !spot) return []
    const s = side.includes('short') ? 'short' as const : 'long' as const
    const t = optionType.includes('put') ? 'put' as const : 'call' as const
    return optionsPayoffCurve({ side: s, optionType: t, strike, spot, qty, avgEntry, mark })
  }, [side, optionType, strike, spot, qty, avgEntry, mark])

  if (!data.length) {
    return <div style={{ fontSize: 9, color: 'var(--text3)', fontStyle: 'italic' }}>P/L profile unavailable</div>
  }

  const h = compact ? 140 : 180
  return (
    <div>
      {!hideTitle && (
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>
          Risk profile · {underlying} {side} {optionType} @ ${strike}
        </div>
      )}
      <ResponsiveContainer width="100%" height={h}>
        <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
          <XAxis
            dataKey="price" tick={{ fontSize: 8, fill: 'var(--text3)' }}
            tickFormatter={v => `$${Number(v).toFixed(0)}`}
          />
          <YAxis tick={{ fontSize: 8, fill: 'var(--text3)' }} tickFormatter={v => `$${v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v}`} width={42} />
          <Tooltip
            contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }}
            formatter={(v: number) => [`$${Math.round(v).toLocaleString()}`, 'P/L @ expiry']}
            labelFormatter={l => `Underlying $${l}`}
          />
          <ReferenceLine y={0} stroke="rgba(148,163,184,.4)" strokeDasharray="4 4" />
          <ReferenceLine x={spot} stroke="#60a5fa" strokeDasharray="3 3" label={{ value: 'spot', fontSize: 8, fill: '#60a5fa' }} />
          <ReferenceLine x={strike} stroke="#a855f7" strokeDasharray="2 4" label={{ value: 'K', fontSize: 8, fill: '#a855f7' }} />
          <Line type="monotone" dataKey="pnl" stroke="#22c55e" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 4 }}>
        Expiry P/L approximation · qty {qty} · not live greeks
      </div>
    </div>
  )
}
import { useMemo } from 'react'
import { useApi } from '../../hooks/useApi'
import { fmt$ } from '../../lib/format'
import { Area, XAxis, YAxis, Tooltip, ResponsiveContainer, Line, ComposedChart } from 'recharts'

interface Props {
  account?: string
  days: number
  /** Auto-refresh interval; 0 = fetch once per filter change */
  refreshMs?: number
  compact?: boolean
}

type McData = {
  ok?: boolean
  error?: string
  simulations?: number
  trades_per_path?: number
  path_auto?: boolean
  sample_size?: number
  median_pnl?: number
  p10?: number
  p90?: number
  prob_profit?: number
  bands?: { trade: number; p10: number; p50: number; p90: number }[]
  sample_paths?: number[][]
}

export default function MonteCarloPanel({ account, days, refreshMs = 300_000, compact }: Props) {
  const q = `/api/v2/journal/monte-carlo?days=${days}&path=auto&sims=500${account ? `&account=${encodeURIComponent(account)}` : ''}`
  const { data: raw, loading, stale } = useApi<McData>(q, refreshMs > 0 ? refreshMs : undefined)
  const m = (raw as any)?.data ?? raw

  const { chartData, sampleKeys } = useMemo(() => {
    const bands: any[] = m?.bands || []
    const paths: number[][] = m?.sample_paths || []
    const maxSp = compact ? 6 : 10
    const keys = paths.slice(0, maxSp).map((_, i) => `sp${i}`)
    const rows = bands.map((b, i) => {
      const row: Record<string, number> = {
        trade: b.trade,
        p10: b.p10,
        p50: b.p50,
        p90: b.p90,
        bandBase: b.p10,
        bandTop: b.p90 - b.p10,
      }
      keys.forEach((k, pi) => {
        if (paths[pi]?.[i] != null) row[k] = paths[pi][i]
      })
      return row
    })
    return { chartData: rows, sampleKeys: keys }
  }, [m?.bands, m?.sample_paths, compact])

  if (loading && !m) {
    return (
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Monte Carlo projection</div>
        <div style={{ fontSize: 10, color: 'var(--text3)' }}>Running bootstrap simulation…</div>
      </div>
    )
  }

  if (!m?.ok) {
    return (
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Monte Carlo projection</div>
        <div style={{ fontSize: 10, color: 'var(--text3)' }}>{m?.error || 'Need at least 5 closed trades in range'}</div>
      </div>
    )
  }

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Monte Carlo projection</div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>
            Bootstrap · {m.simulations} sims × {m.trades_per_path} trades{m.path_auto ? ' (auto path)' : ''} · {m.sample_size} historical
            {stale ? ' · cached' : ''}
          </div>
        </div>
        <div style={{ fontSize: 8, color: 'var(--text3)' }}>Auto-updates with filters</div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: compact ? 'repeat(4,1fr)' : 'repeat(5,1fr)', gap: 8, marginBottom: 12 }}>
        {[
          { l: 'Median', v: fmt$(m.median_pnl, 0), c: 'var(--text0)' },
          { l: 'P10 (bad)', v: fmt$(m.p10, 0), c: '#ef4444' },
          { l: 'P90 (good)', v: fmt$(m.p90, 0), c: '#22c55e' },
          { l: 'Prob profit', v: `${m.prob_profit}%`, c: (m.prob_profit ?? 0) >= 50 ? '#22c55e' : '#f59e0b' },
          ...(!compact ? [{ l: 'Horizon', v: `${m.trades_per_path}t`, c: '#60a5fa' }] : []),
        ].map(k => (
          <div key={k.l} style={{ background: 'var(--bg2)', borderRadius: 6, padding: '8px 10px', textAlign: 'center' }}>
            <div style={{ fontSize: compact ? 14 : 16, fontWeight: 700, color: k.c, fontFamily: 'monospace' }}>{k.v}</div>
            <div style={{ fontSize: 8, color: 'var(--text3)' }}>{k.l}</div>
          </div>
        ))}
      </div>

      {chartData.length > 1 ? (
        <ResponsiveContainer width="100%" height={compact ? 160 : 200}>
          <ComposedChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="mcBand" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#22c55e" stopOpacity={0.25} />
                <stop offset="95%" stopColor="#22c55e" stopOpacity={0.04} />
              </linearGradient>
            </defs>
            <XAxis dataKey="trade" tick={{ fontSize: 8, fill: 'var(--text3)' }} label={{ value: 'Trade #', position: 'insideBottom', offset: -2, fontSize: 8, fill: 'var(--text3)' }} />
            <YAxis tick={{ fontSize: 8, fill: 'var(--text3)' }} tickFormatter={(v: number) => `$${Math.round(v / 1000)}k`} width={42} />
            <Tooltip
              contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }}
              formatter={(v: number, name: string) => [fmt$(v, 0), name === 'p50' ? 'Median' : name.toUpperCase()]}
              labelFormatter={(l) => `After trade ${l}`}
            />
            <Area type="monotone" dataKey="bandBase" stackId="band" stroke="none" fill="var(--bg1)" />
            <Area type="monotone" dataKey="bandTop" stackId="band" stroke="none" fill="url(#mcBand)" />
            {sampleKeys.map(k => (
              <Line key={k} type="monotone" dataKey={k} stroke="var(--text3)" strokeWidth={0.6} dot={false} opacity={0.3} />
            ))}
            <Line type="monotone" dataKey="p50" stroke="#60a5fa" strokeWidth={2.5} dot={false} name="p50" />
            <Line type="monotone" dataKey="p10" stroke="#ef4444" strokeWidth={1} strokeDasharray="4 3" dot={false} name="p10" />
            <Line type="monotone" dataKey="p90" stroke="#22c55e" strokeWidth={1} strokeDasharray="4 3" dot={false} name="p90" />
          </ComposedChart>
        </ResponsiveContainer>
      ) : (
        <div style={{ fontSize: 10, color: 'var(--text3)', padding: 16, textAlign: 'center' }}>Insufficient path length for chart</div>
      )}

      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8, lineHeight: 1.4 }}>
        Resamples your historical trade P&Ls with replacement. Shaded band = P10–P90 range; blue = median path.
        Not a price forecast — assumes future trades resemble past closes in this filter.
      </div>
    </div>
  )
}
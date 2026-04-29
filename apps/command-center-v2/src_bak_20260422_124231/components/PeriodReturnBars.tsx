import { fmt$, fmtPct, deltaColor } from '../lib/format'

interface Period { change_pct: number | null; change: number | null; start_date?: string; estimated?: boolean; source?: string }

interface Props {
  periods: Record<string, Period>
  labels?: string[]
  selectedPeriod?: string | null
  onPeriodClick?: (period: string) => void
}

export default function PeriodReturnBars({ periods, labels = ['1D','1W','1M','3M','6M','YTD','1Y'], selectedPeriod, onPeriodClick }: Props) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      {labels.map(k => {
        const p = periods[k]
        if (!p || p.change_pct == null) return (
          <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)', opacity: 0.4 }}>
            <span style={{ width: 28, fontSize: 10, fontWeight: 600, color: 'var(--text3)' }}>{k}</span>
            <span style={{ flex: 1, fontSize: 10, color: 'var(--text3)' }}>—</span>
          </div>
        )
        const pct = p.change_pct
        const chg = p.change ?? 0
        const col = pct >= 0 ? 'var(--green)' : 'var(--red)'
        const barW = Math.min(Math.abs(pct) * 3, 100)
        const est = p.estimated || p.source === 'repriced'

        return (
          <div key={k} onClick={() => onPeriodClick?.(k)} style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: '4px 0',
            borderBottom: '1px solid var(--border-subtle)',
            cursor: onPeriodClick ? 'pointer' : 'default',
            background: selectedPeriod === k ? 'var(--accent-dim)' : 'transparent',
            borderLeft: selectedPeriod === k ? '2px solid var(--accent)' : '2px solid transparent',
            paddingLeft: 4,
          }}>
            <span style={{ width: 28, fontSize: 10, fontWeight: 600, color: selectedPeriod === k ? 'var(--accent)' : 'var(--text2)' }}>{k}{est ? '*' : ''}{selectedPeriod === k ? ' \u25bc' : ''}</span>
            <div style={{ flex: 1, height: 8, background: 'var(--bg3)', borderRadius: 3, position: 'relative', overflow: 'hidden' }}>
              <div style={{
                position: 'absolute', [pct >= 0 ? 'left' : 'right']: 0, top: 0,
                width: `${barW}%`, height: '100%',
                background: col, opacity: 0.6, borderRadius: 3,
              }} />
            </div>
            <span style={{ width: 58, textAlign: 'right', fontSize: 11, fontWeight: 600, color: col }}>{fmtPct(pct)}</span>
            <span style={{ width: 72, textAlign: 'right', fontSize: 10, color: col }}>
              {chg >= 0 ? '+' : '-'}${Math.abs(chg).toLocaleString('en-US', { maximumFractionDigits: 0 })}
            </span>
            {p.start_date && <span style={{ width: 62, textAlign: 'right', fontSize: 8, color: 'var(--text3)' }}>{p.start_date}</span>}
          </div>
        )
      })}
    </div>
  )
}

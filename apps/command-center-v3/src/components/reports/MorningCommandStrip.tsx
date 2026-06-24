export interface StripCell {
  label: string
  val: string
  sub?: string
  color?: string
  onClick?: () => void
}

export function buildStripCells(opts: {
  portfolioValue?: number
  todayChange?: number
  heatPct?: number
  triggeredCount?: number
  unprotectedCount?: number
  regimeLabel?: string
  vix?: number
  onRisk?: () => void
  onPortfolio?: () => void
}): StripCell[] {
  const fmt$ = (v?: number) => (v == null || !Number.isFinite(v) ? '—' : `$${Math.round(v).toLocaleString()}`)
  const ch = opts.todayChange
  const chColor = ch == null ? undefined : ch >= 0 ? '#22c55e' : '#ef4444'
  const chStr = ch == null ? '—' : `${ch >= 0 ? '+' : ''}$${Math.abs(Math.round(ch)).toLocaleString()}`
  return [
    { label: 'Portfolio', val: fmt$(opts.portfolioValue), sub: 'click for holdings', onClick: opts.onPortfolio },
    { label: 'Today', val: chStr, sub: opts.heatPct != null ? `heat ${opts.heatPct.toFixed?.(1) ?? opts.heatPct}%` : undefined, color: chColor },
    { label: 'Stops', val: String(opts.triggeredCount ?? 0), sub: `${opts.unprotectedCount ?? 0} unprotected`, color: (opts.triggeredCount ?? 0) > 0 ? '#ef4444' : '#22c55e', onClick: opts.onRisk },
    { label: 'Regime', val: opts.regimeLabel ?? '—', sub: opts.vix != null ? `VIX ${opts.vix}` : undefined, color: '#60a5fa' },
  ]
}

export default function MorningCommandStrip({ cells }: { cells: StripCell[] }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
      {cells.map(c => (
        <div key={c.label} onClick={c.onClick}
          style={{
            background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 14px',
            cursor: c.onClick ? 'pointer' : 'default',
          }}>
          <div style={{ fontSize: 9, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.4 }}>{c.label}</div>
          <div style={{ fontSize: 20, fontWeight: 900, color: c.color || 'var(--text0)', marginTop: 4 }}>{c.val}</div>
          {c.sub && <div style={{ fontSize: 10, color: c.color || 'var(--text3)', marginTop: 3 }}>{c.sub}</div>}
        </div>
      ))}
    </div>
  )
}
type Props = {
  queuedShares: number
  capShares: number
  accountLabel?: string
  alwaysShow?: boolean
}

export default function PositionSizingRiskBar({ queuedShares, capShares, accountLabel, alwaysShow }: Props) {
  const q = Math.max(0, queuedShares)
  const c = Math.max(0, capShares)
  if (!q || !c) return null
  const oversized = q > c
  if (!oversized && !alwaysShow) return null

  const fillPct = Math.min(100, Math.round((q / c) * 100))
  const capW = oversized ? Math.min(100, Math.round((c / q) * 100)) : fillPct
  const overPct = oversized ? Math.round(((q - c) / c) * 100) : 0
  const headColor = oversized ? '#ef4444' : fillPct >= 85 ? '#f59e0b' : '#22c55e'
  const bg = oversized ? 'rgba(239,68,68,.06)' : fillPct >= 85 ? 'rgba(245,158,11,.06)' : 'rgba(34,197,94,.06)'
  const border = oversized ? 'rgba(239,68,68,.22)' : fillPct >= 85 ? 'rgba(245,158,11,.22)' : 'rgba(34,197,94,.22)'

  return (
    <div style={{ marginTop: 8, padding: '8px 10px', borderRadius: 8, background: bg, border: `1px solid ${border}` }}>
      <div style={{ fontSize: 9, fontWeight: 800, color: headColor, marginBottom: 6, textTransform: 'uppercase' }}>
        {oversized
          ? `Position sizing risk · ${overPct}% over cap`
          : `Sizing vs cap · ${fillPct}% of limit`}
      </div>
      <div style={{ position: 'relative', height: 10, borderRadius: 5, background: 'rgba(15,23,42,.6)', overflow: 'hidden' }}>
        {oversized && (
          <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: '100%', background: 'rgba(239,68,68,.35)' }} title={`Queued ${q.toLocaleString()} sh`} />
        )}
        <div
          style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${capW}%`, background: oversized ? '#22c55e' : headColor, opacity: 0.85 }}
          title={oversized ? `Cap ${c.toLocaleString()} sh` : `${q.toLocaleString()} sh of ${c.toLocaleString()} cap`}
        />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8.5, color: 'var(--text3)', marginTop: 5 }}>
        <span>Cap {c.toLocaleString()} sh{accountLabel ? ` · ${accountLabel}` : ''}</span>
        <span style={{ color: oversized ? '#ef4444' : 'var(--text1)' }}>Queued {q.toLocaleString()} sh</span>
      </div>
    </div>
  )
}
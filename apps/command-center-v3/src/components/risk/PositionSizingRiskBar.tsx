type Props = {
  queuedShares: number
  capShares: number
  accountLabel?: string
}

export default function PositionSizingRiskBar({ queuedShares, capShares, accountLabel }: Props) {
  const q = Math.max(0, queuedShares)
  const c = Math.max(0, capShares)
  if (!q || !c || q <= c) return null
  const overPct = Math.round(((q - c) / q) * 100)
  const capW = Math.min(100, Math.round((c / q) * 100))
  return (
    <div style={{ marginTop: 8, padding: '8px 10px', borderRadius: 8, background: 'rgba(239,68,68,.06)', border: '1px solid rgba(239,68,68,.22)' }}>
      <div style={{ fontSize: 9, fontWeight: 800, color: '#ef4444', marginBottom: 6, textTransform: 'uppercase' }}>
        Position sizing risk · {overPct}% over cap
      </div>
      <div style={{ position: 'relative', height: 10, borderRadius: 5, background: 'rgba(15,23,42,.6)', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: '100%', background: 'rgba(239,68,68,.35)' }} title={`Queued ${q.toLocaleString()} sh`} />
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${capW}%`, background: '#22c55e', opacity: 0.85 }} title={`Cap ${c.toLocaleString()} sh`} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8.5, color: 'var(--text3)', marginTop: 5 }}>
        <span>Cap {c.toLocaleString()} sh{accountLabel ? ` · ${accountLabel}` : ''}</span>
        <span style={{ color: '#ef4444' }}>Queued {q.toLocaleString()} sh</span>
      </div>
    </div>
  )
}
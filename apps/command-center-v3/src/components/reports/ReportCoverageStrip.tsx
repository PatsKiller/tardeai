export default function ReportCoverageStrip({ categories }: { categories: any[] }) {
  const total = categories.reduce((a: number, c: any) => a + (c.count || 0), 0)
  const top = [...categories].sort((a, b) => (b.count || 0) - (a.count || 0)).slice(0, 6)
  return (
    <div style={{
      display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap',
      padding: '10px 14px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10,
    }}>
      <div>
        <div style={{ fontSize: 10, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase' }}>Report coverage</div>
        <div style={{ fontSize: 18, fontWeight: 900, color: 'var(--text0)' }}>{total.toLocaleString()} <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text3)' }}>items indexed</span></div>
      </div>
      <div style={{ flex: 1, display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        {top.map((c: any) => (
          <span key={c.key} title={c.label} style={{
            fontSize: 10, fontWeight: 700, padding: '4px 9px', borderRadius: 6,
            background: 'var(--bg2)', color: 'var(--text2)', border: '1px solid var(--border)',
          }}>
            {c.icon} {c.label} <span style={{ color: '#60a5fa' }}>{c.count}</span>
          </span>
        ))}
      </div>
    </div>
  )
}
const FQDN = typeof window !== 'undefined' ? window.location.origin : ''
const rel = (u?: string) => (u ? u.replace(/^https?:\/\/[^/]+/, '') : '/v3/')

export interface ActionRow {
  id: string
  rank: number
  type: string
  typeColor: string
  symbol: string
  issue: string
  owner?: string
  due?: string
  route?: string
  routeLabel?: string
}

const TYPE_COLOR: Record<string, string> = {
  stop_triggered: '#ef4444',
  unprotected_position: '#ef4444',
  risk_review: '#f59e0b',
  approval_needed: '#a855f7',
  broker_manual: '#a855f7',
  recovery: '#06b6d4',
  system_health: '#60a5fa',
  hermes_review: '#22d3ee',
  research_needed: '#14b8a6',
  portfolio_review: '#eab308',
}

const TYPE_LABEL: Record<string, string> = {
  stop_triggered: 'Stop',
  unprotected_position: 'Unprotected',
  risk_review: 'Risk',
  approval_needed: 'Approval',
  broker_manual: 'Manual',
  recovery: 'Recovery',
  system_health: 'System',
  hermes_review: 'Hermes',
  research_needed: 'Research',
  portfolio_review: 'Portfolio',
}

export function actionsToRows(actions: any[], cap = 12): ActionRow[] {
  const sevRank = (s: string) => ({ urgent: 4, critical: 4, warning: 2, info: 1 } as any)[(s || '').toLowerCase()] || 0
  const sorted = [...actions].sort((a, b) => sevRank(b.severity) - sevRank(a.severity) || (Date.parse(b.created_at || '') - Date.parse(a.created_at || '')))
  return sorted.slice(0, cap).map((a, i) => {
    const cls = (a._classes || [a.action_class])[0] || 'info'
    const tg = a.target || {}
    return {
      id: a.id || String(i),
      rank: i + 1,
      type: TYPE_LABEL[cls] || cls,
      typeColor: TYPE_COLOR[cls] || '#60a5fa',
      symbol: a.symbol || '—',
      issue: (a.text || '').slice(0, 120),
      owner: cls.includes('approval') ? 'John' : cls.includes('hermes') ? 'Hermes' : cls.includes('stop') || cls.includes('unprotected') ? 'John' : 'Monitor',
      due: ['urgent', 'critical'].includes((a.severity || '').toLowerCase()) ? 'Now' : 'Today',
      route: tg.route || a.route,
      routeLabel: tg.route_label || a.route_label || 'Open',
    }
  })
}

export default function PriorityActionBoard({ rows }: { rows: ActionRow[] }) {
  if (!rows.length) {
    return (
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '28px 16px', textAlign: 'center', color: 'var(--text3)', fontSize: 12 }}>
        No priority actions — portfolio stable.
      </div>
    )
  }
  const grid = '4px 28px 72px 56px 1fr 64px 52px 72px'
  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ display: 'grid', gridTemplateColumns: grid, background: 'var(--bg2)', borderBottom: '1px solid var(--border)' }}>
        {['', '#', 'Type', 'Sym', 'Issue', 'Owner', 'Due', ''].map((h, i) => (
          <div key={i} style={{ padding: '6px 8px', fontSize: 8, fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.3 }}>{h}</div>
        ))}
      </div>
      {rows.map(r => {
        const urgent = r.rank <= 3 && (r.typeColor === '#ef4444' || r.typeColor === '#f59e0b')
        return (
          <div
            key={r.id}
            style={{
              display: 'grid',
              gridTemplateColumns: grid,
              alignItems: 'center',
              borderBottom: '1px solid var(--border-subtle)',
              background: urgent ? 'rgba(239,68,68,.04)' : 'transparent',
            }}
          >
            <div style={{ width: 4, alignSelf: 'stretch', background: r.typeColor }} />
            <div style={{ padding: '8px', fontSize: 12, fontWeight: 900, color: r.rank <= 3 ? '#ef4444' : 'var(--text2)' }}>{r.rank}</div>
            <div style={{ padding: '8px' }}>
              <span style={{ fontSize: 8, fontWeight: 800, padding: '2px 6px', borderRadius: 4, background: r.typeColor + '22', color: r.typeColor }}>{r.type}</span>
            </div>
            <div style={{ padding: '8px', fontSize: 11, fontWeight: 800, fontFamily: 'var(--mono)', color: '#60a5fa' }}>{r.symbol}</div>
            <div style={{ padding: '8px', fontSize: 10, color: 'var(--text1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.issue}</div>
            <div style={{ padding: '8px', fontSize: 9, fontWeight: 700, color: r.owner === 'John' ? '#f59e0b' : 'var(--text3)' }}>{r.owner}</div>
            <div style={{ padding: '8px', fontSize: 9, fontWeight: 700, color: r.due === 'Now' ? '#ef4444' : '#f59e0b' }}>{r.due}</div>
            <div style={{ padding: '8px' }}>
              {r.route && (
                <a href={FQDN + rel(r.route)} style={{ fontSize: 9, fontWeight: 800, color: '#60a5fa', textDecoration: 'none' }}>{r.routeLabel} →</a>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
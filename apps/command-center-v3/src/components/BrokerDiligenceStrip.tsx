const MUTED = '#94a3b8', GREEN = '#22c55e', AMBER = '#f59e0b', RED = '#ef4444', BLUE = '#60a5fa', PURPLE = '#a78bfa', TEXT0 = '#f8fafc'

const STATUS_STYLE: Record<string, { icon: string; color: string; bg: string }> = {
  PASS: { icon: '✓', color: GREEN, bg: 'rgba(34,197,94,.12)' },
  WARN: { icon: '⚠', color: AMBER, bg: 'rgba(245,158,11,.12)' },
  BLOCK: { icon: '⛔', color: RED, bg: 'rgba(239,68,68,.12)' },
  PENDING: { icon: '…', color: BLUE, bg: 'rgba(96,165,250,.12)' },
}

type Stage = { id?: string; label: string; status: string; detail?: string; action?: string }
type Summary = {
  status?: string
  promote_ready?: boolean
  next_action?: string
  blockers?: string[]
  completed_steps?: number
  total_steps?: number
  current_step?: number
}

type Props = {
  stages?: Stage[]
  summary?: Summary | null
  compact?: boolean
}

export default function BrokerDiligenceStrip({ stages, summary, compact = false }: Props) {
  const st = stages || []
  const ov = summary?.status || (summary?.promote_ready ? 'PASS' : summary?.blockers?.length ? 'BLOCK' : 'PENDING')
  const style = STATUS_STYLE[ov || 'PENDING'] || STATUS_STYLE.PENDING

  if (!st.length && !summary) return null

  return (
    <div style={{
      padding: compact ? '6px 10px' : '8px 12px',
      borderRadius: 8,
      background: 'rgba(15,23,42,.45)',
      border: `1px solid ${style.color}33`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: st.length ? 6 : 0 }}>
        <span style={{ fontSize: 9, fontWeight: 800, color: PURPLE, textTransform: 'uppercase', letterSpacing: '0.35px' }}>
          Broker diligence
        </span>
        <span style={{
          fontSize: 9, fontWeight: 800, padding: '2px 8px', borderRadius: 4,
          background: style.bg, color: style.color,
        }}>
          {summary?.promote_ready ? 'PROMOTE READY' : ov}
        </span>
        {summary?.current_step != null && summary?.total_steps != null && (
          <span style={{ fontSize: 9, color: MUTED }}>
            Step {summary.current_step}/{summary.total_steps}
            {summary.completed_steps != null ? ` · ${summary.completed_steps} done` : ''}
          </span>
        )}
      </div>

      {summary?.next_action && (
        <div style={{ fontSize: 9.5, color: TEXT0, marginBottom: st.length ? 6 : 0 }}>
          Next: <span style={{ color: style.color, fontWeight: 700 }}>{summary.next_action}</span>
        </div>
      )}

      {summary?.blockers && summary.blockers.length > 0 && !st.length && (
        <div style={{ fontSize: 9, color: RED }}>
          {summary.blockers.map((b, i) => <div key={i}>⛔ {b}</div>)}
        </div>
      )}

      {st.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 2, overflowX: 'auto', paddingTop: 2 }}>
          {st.map((s, i) => {
            const si = STATUS_STYLE[s.status] || STATUS_STYLE.PENDING
            return (
              <div key={s.id || i} style={{ display: 'flex', alignItems: 'center', gap: 2, flexShrink: 0 }}>
                {i > 0 && <span style={{ fontSize: 8, color: MUTED }}>→</span>}
                <div
                  title={[s.detail, s.action].filter(Boolean).join(' · ')}
                  style={{
                    display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: compact ? 52 : 64,
                    padding: '3px 5px', borderRadius: 5, border: `1px solid ${si.color}35`, background: si.bg,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                    <span style={{ fontSize: 9, color: si.color }}>{si.icon}</span>
                    <span style={{ fontSize: 8.5, fontWeight: 700, color: si.color }}>{s.label}</span>
                  </div>
                  {s.detail && !compact && (
                    <span style={{ fontSize: 7.5, color: MUTED, marginTop: 1, maxWidth: 72, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {s.detail}
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
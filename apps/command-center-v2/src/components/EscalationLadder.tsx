import { timeAgo } from '../lib/format'

const STEP_ICONS: Record<string, string> = {
  event: '📍', router: '🔀', agent_call: '🤖', peer_call: '🤖',
  conflict: '⚠️', debate: '🗣️', alex_escalation: '🎯',
  human_queue: '👤', outcome: '✅',
}

interface Props {
  data: any
  loading: boolean
}

export function EscalationLadder({ data, loading }: Props) {
  if (loading) return <div style={{ padding: 12, color: 'rgba(255,255,255,0.3)', fontSize: 11 }}>Loading trace...</div>
  const trace = data?.data?.trace || data?.trace || []
  if (trace.length === 0) return <div style={{ padding: 12, color: 'rgba(255,255,255,0.3)', fontSize: 11 }}>No escalation trace for this analysis.</div>

  return (
    <div style={{ background: 'rgba(255,255,255,0.02)', borderRadius: 6, padding: '12px 16px', marginTop: 8, borderLeft: '2px solid rgba(99,102,241,0.5)' }}>
      <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '.05em', textTransform: 'uppercase' as const, color: 'rgba(255,255,255,0.3)', marginBottom: 10 }}>Escalation Trace</div>

      {(data?.data?.rules_fired || data?.rules_fired || []).length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', marginRight: 6 }}>Rules:</span>
          {(data?.data?.rules_fired || data?.rules_fired || []).map((r: string) => (
            <span key={r} style={{ background: 'rgba(245,158,11,0.15)', color: '#f59e0b', border: '1px solid rgba(245,158,11,0.3)', padding: '1px 6px', borderRadius: 4, fontSize: 10, fontFamily: 'monospace', marginRight: 4 }}>{r}</span>
          ))}
        </div>
      )}

      <div style={{ position: 'relative', paddingLeft: 24 }}>
        {trace.map((step: any, i: number) => {
          const isLast = i === trace.length - 1
          const dimmed = step.did_not_occur
          return (
            <div key={i} style={{ position: 'relative', paddingBottom: isLast ? 0 : 14, opacity: dimmed ? 0.45 : 1 }}>
              {!isLast && <div style={{ position: 'absolute', left: -13, top: 18, bottom: 0, width: 2, background: 'rgba(99,102,241,0.2)' }} />}
              <div style={{ position: 'absolute', left: -24, top: 0, width: 22, height: 22, borderRadius: '50%', background: 'rgba(255,255,255,0.04)', border: step.is_focus ? '2px solid rgba(99,102,241,0.6)' : '1px solid rgba(255,255,255,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11 }}>
                {STEP_ICONS[step.type] || '•'}
              </div>
              <div style={{ paddingLeft: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={{ fontSize: 11, fontWeight: step.is_focus ? 700 : 500, color: step.is_focus ? 'rgba(165,180,252,0.9)' : 'rgba(255,255,255,0.7)' }}>
                    {step.label}
                    {step.is_focus && <span style={{ marginLeft: 6, fontSize: 9, color: 'rgba(99,102,241,0.7)' }}>← this analysis</span>}
                  </span>
                  {step.ts && <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.25)', fontFamily: 'monospace' }}>{timeAgo(step.ts)}</span>}
                </div>
                {step.detail && <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', marginTop: 2 }}>{step.detail}</div>}
                {step.did_not_occur_reason && <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.25)', fontStyle: 'italic', marginTop: 2 }}>did not occur: {step.did_not_occur_reason}</div>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

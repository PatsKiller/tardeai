import { useApi } from '../hooks/useApi'

const panel = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 } as const

export default function ExecutionStatePanel() {
  const { data: state, loading } = useApi<any>('/api/v2/execution/current-state', 120_000)
  const { data: kills } = useApi<any>('/api/v2/execution/kill-switches', 120_000)

  const blockers: string[] = state?.current_blockers || []
  const releaseNotes: string[] = state?.release_notes || []
  const gates: string[] = state?.required_live_gates || []
  const liveOn = !!state?.live_trading_global_allowed
  const operatorPath = !!state?.operator_approved_live_submit_possible
  const unlockVia = state?.live_unlock?.unlock_via as string | undefined
  const optionsArmed = state?.live_paths?.options?.armed_for_execution

  const bannerColor = liveOn && operatorPath ? '#22c55e' : liveOn ? '#60a5fa' : '#f59e0b'
  const bannerText = liveOn
    ? `Live Schwab submit ENABLED (${unlockVia || 'standing unlock'}) — every order needs operator 2FA (type ticker or Telegram). Not autonomous.`
    : 'Live path locked — standing operator unlock required before 2FA can arm any submit.'

  return (
    <div style={panel}>
      <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', marginBottom: 8 }}>
        Execution state {loading && <span style={{ fontWeight: 400, color: 'var(--text3)' }}>…</span>}
      </div>
      <div style={{ fontSize: 10.5, color: bannerColor, marginBottom: 10, lineHeight: 1.45 }}>
        {bannerText}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8, marginBottom: 12 }}>
        {[
          { l: 'Live unlocked', v: liveOn ? 'yes' : 'no', c: liveOn ? '#22c55e' : '#f59e0b' },
          { l: 'Per-order 2FA', v: state?.per_order_2fa_required !== false ? 'required' : '—', c: '#a855f7' },
          { l: 'Options armed', v: optionsArmed ? 'yes' : 'no', c: optionsArmed ? '#22c55e' : 'var(--text3)' },
          { l: 'Autonomous', v: 'no', c: '#ef4444' },
          { l: 'Operator path', v: operatorPath ? 'ready' : 'blocked', c: operatorPath ? '#22c55e' : '#f59e0b' },
          { l: 'Live-adj dirty', v: String(state?.live_adjacent_dirty_count ?? '—'), c: (state?.live_adjacent_dirty_count || 0) > 0 ? '#f59e0b' : 'var(--text2)' },
        ].map(k => (
          <div key={k.l} style={{ background: 'var(--bg2)', borderRadius: 6, padding: 8 }}>
            <div style={{ fontSize: 8, color: 'var(--text3)' }}>{k.l}</div>
            <div style={{ fontSize: 11, fontWeight: 700, color: k.c }}>{k.v}</div>
          </div>
        ))}
      </div>
      {blockers.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 9, fontWeight: 800, color: '#ef4444', marginBottom: 4 }}>Hard blockers</div>
          {blockers.map((b, i) => (
            <div key={i} style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 2 }}>• {b}</div>
          ))}
        </div>
      )}
      {releaseNotes.length > 0 && (
        <div style={{ marginBottom: 10, fontSize: 10, color: 'var(--text3)' }}>
          {releaseNotes.map((n, i) => <div key={i}>ⓘ {n}</div>)}
        </div>
      )}
      {(kills?.active || []).length > 0 && (
        <div style={{ marginBottom: 10, borderLeft: '3px solid #ef4444', paddingLeft: 8 }}>
          <div style={{ fontSize: 9, fontWeight: 800, color: '#ef4444' }}>Kill switches active</div>
          {(kills.active as { level: string; reason?: string }[]).map((k, i) => (
            <div key={i} style={{ fontSize: 10, color: 'var(--text2)' }}>{k.level}: {k.reason || 'active'}</div>
          ))}
        </div>
      )}
      <details>
        <summary style={{ fontSize: 9, color: 'var(--text3)', cursor: 'pointer' }}>Required live gates ({gates.length})</summary>
        <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6, lineHeight: 1.5 }}>
          {gates.map(g => <div key={g}>{g}</div>)}
        </div>
      </details>
      <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 10 }}>
        Auto-prepare → Operator approve → 2FA confirm → Broker submit · LLMs advisory only · updated {state?.generated_at ? new Date(state.generated_at).toLocaleString() : '—'}
      </div>
    </div>
  )
}
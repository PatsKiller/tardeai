import { useApi } from '../../hooks/useApi'
import { TYPE } from '../../lib/watchTokens'
import { RADIUS } from '../../lib/designTokens'
import { bucketText, countsText, hitRateText, type AgentCalibrationResponse } from '../../lib/agentCalibration'

const panel = { border: '1px solid var(--border)', borderRadius: RADIUS.md, background: 'var(--bg1)', padding: 14 } as const

export default function AgentCalibrationPanel() {
  const { data, loading, error } = useApi<AgentCalibrationResponse>('/api/v3/agents/calibration', 300_000)
  const minSample = data?.min_sample ?? 20
  return <div style={{ display: 'grid', gap: 12 }} data-testid="agent-calibration">
    <div style={panel}>
      <div style={{ fontSize: TYPE.md, fontWeight: 800 }}>Calibration · stated confidence vs what happened</div>
      <div style={{ marginTop: 4, fontSize: TYPE.xs, color: 'var(--text3)', lineHeight: 1.5 }}>
        Only scored outcomes count: directional calls against their move, other calls against their recorded expectation
        (ExpectationPolicy@v1). Agents with fewer than {minSample} scored outcomes show "insufficient sample", never a rate.
        Read-only; it never changes a decision.
      </div>
      {loading && !data && <div style={{ marginTop: 10, fontSize: TYPE.xs, color: 'var(--text2)' }}>Loading calibration…</div>}
      {error && <div style={{ marginTop: 10, fontSize: TYPE.xs, color: 'var(--amber)' }}>Calibration unavailable: {String(error)}</div>}
      {data && <div style={{ marginTop: 8, fontSize: TYPE.xs, color: 'var(--text3)' }}>Unscored observations (no direction and no scored expectation): {data.unscored_observations ?? 0}</div>}
    </div>
    {(data?.agents || []).map(row => <div key={row.agent} style={panel} data-testid={`agent-calibration-${row.agent}`}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <div style={{ fontSize: TYPE.md, fontWeight: 800 }}>{row.agent}</div>
        <div style={{ fontSize: TYPE.xs, fontWeight: 750, color: row.status === 'MEASURED' ? 'var(--text1)' : 'var(--amber)' }}>{hitRateText(row, minSample)}</div>
      </div>
      <div style={{ marginTop: 6, fontSize: TYPE.xs, color: 'var(--text2)', lineHeight: 1.6 }}>
        <div>Scored by: {countsText(row.by_basis)}</div>
        <div>Surfaces: {countsText(row.by_surface)}</div>
        {row.brier !== null && <div>Brier score: {row.brier.toFixed(3)} (0 = perfect)</div>}
        {(row.by_confidence || []).map(b => <div key={b.bucket}>{bucketText(b)}</div>)}
      </div>
    </div>)}
    {data && (data.agents || []).length === 0 && <div style={{ ...panel, fontSize: TYPE.xs, color: 'var(--text2)' }}>No scored outcomes yet.</div>}
  </div>
}

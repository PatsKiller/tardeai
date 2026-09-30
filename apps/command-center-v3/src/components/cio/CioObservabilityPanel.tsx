import { useApi } from '../../hooks/useApi'
import { RADIUS, TYPE } from '../../lib/designTokens'

type Domain = {
  id: string; name: string; status: string; value?: unknown; source?: string
  last_success?: string | null; cadence?: string | null; blocker?: string | null
  owner?: string | null; downstream_impact?: string | null
  metrics?: Record<string, unknown>; drill_through?: string[]
}

type Observability = {
  as_of?: string
  overall?: { status?: string; working?: number; degraded?: number; blocked?: number; finding_count?: number }
  scorecards?: Domain[]
  workflows?: { id: string; label: string; status: string; throughput?: number | null }[]
  recommendation_funnel?: { id: string; label: string; count: number }[]
  findings?: { issue_id: string; severity: string; title: string; root_cause: string; status: string; component: string; residual_risk?: string | null }[]
  policy?: { status?: string; missing_fields?: string[]; missing_count?: number; blocked?: boolean }
}

const tone = (status?: string) => {
  if (status === 'WORKING') return 'var(--green)'
  if (status === 'DEGRADED') return 'var(--amber)'
  return 'var(--red)'
}

const fmt = (value: unknown) => value == null || value === '' ? '—' : String(value)

function StatusPill({ status }: { status?: string }) {
  return <span style={{ color: tone(status), border: `1px solid ${tone(status)}`, borderRadius: RADIUS.pill, padding: '2px 7px', fontSize: TYPE.xs, fontWeight: 800 }}>{status || 'BLOCKED'}</span>
}

export default function CioObservabilityPanel() {
  const { data, loading, error } = useApi<Observability>('/api/v3/cio/observability')
  if (loading && !data) return <div data-testid="cio-observability-loading" style={{ color: 'var(--text2)', padding: '10px 0' }}>Loading CIO operations…</div>
  if (error && !data) return <div data-testid="cio-observability-error" style={{ color: 'var(--red)', padding: '10px 0' }}>CIO operations unavailable: {String(error)}</div>
  const overall = data?.overall || {}
  const domains = data?.scorecards || []
  const findings = data?.findings || []
  return (
    <section data-testid="cio-observability" aria-label="CIO Desk observability" style={{ display: 'grid', gap: 12, marginBottom: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: '12px 14px', background: 'var(--bg2)' }}>
        <div>
          <div style={{ color: 'var(--text3)', fontSize: 10, fontWeight: 800, letterSpacing: '.7px' }}>CIO DESK OPERATING STATUS</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6 }}><StatusPill status={overall.status} /><span style={{ color: 'var(--text2)', fontSize: 11 }}>Live evidence-backed projection · as of {fmt(data?.as_of)}</span></div>
        </div>
        <div style={{ display: 'flex', gap: 14, fontSize: 11, fontFamily: 'var(--mono)' }}>
          <span style={{ color: 'var(--green)' }}>Working {overall.working ?? 0}</span>
          <span style={{ color: 'var(--amber)' }}>Degraded {overall.degraded ?? 0}</span>
          <span style={{ color: 'var(--red)' }}>Blocked {overall.blocked ?? 0}</span>
          <span style={{ color: 'var(--text2)' }}>Findings {overall.finding_count ?? 0}</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
        {domains.map(domain => (
          <article key={domain.id} data-testid={`cio-scorecard-${domain.id}`} style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 10, background: 'var(--bg2)', minWidth: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}><strong style={{ fontSize: 11, color: 'var(--text0)' }}>{domain.name}</strong><StatusPill status={domain.status} /></div>
            <div style={{ color: 'var(--text1)', fontSize: 12, marginTop: 8 }}>{fmt(domain.value)}</div>
            <div style={{ color: 'var(--text3)', fontSize: 10, marginTop: 5 }}>Source: {fmt(domain.source)} · Last success: {fmt(domain.last_success)}</div>
            {domain.blocker && <div style={{ color: 'var(--amber)', fontSize: 10, marginTop: 6 }}>Why: {domain.blocker}</div>}
            <div style={{ color: 'var(--text3)', fontSize: 10, marginTop: 5 }}>{domain.downstream_impact || domain.owner || 'No impact metadata'}</div>
          </article>
        ))}
      </div>

      <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 12, background: 'var(--bg2)' }}>
        <div style={{ color: 'var(--text0)', fontWeight: 800, fontSize: 12, marginBottom: 10 }}>Live CIO workflow</div>
        <div style={{ display: 'flex', gap: 6, overflowX: 'auto', alignItems: 'stretch' }} data-testid="cio-workflow-graph">
          {(data?.workflows || []).map((node, index) => <div key={node.id} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <div style={{ minWidth: 112, border: `1px solid ${tone(node.status)}`, borderRadius: RADIUS.sm, padding: 8 }}><div style={{ color: 'var(--text0)', fontSize: TYPE.xs, fontWeight: 700 }}>{node.label}</div><div style={{ marginTop: 5 }}><StatusPill status={node.status} /></div><div style={{ color: 'var(--text3)', fontSize: TYPE.xs, marginTop: 4 }}>Throughput {fmt(node.throughput)}</div></div>
            {index < (data?.workflows?.length || 0) - 1 && <span style={{ color: 'var(--text3)' }}>→</span>}
          </div>)}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 12, background: 'var(--bg2)' }} data-testid="cio-recommendation-funnel">
          <div style={{ color: 'var(--text0)', fontWeight: 800, fontSize: 12, marginBottom: 8 }}>Recommendation and learning funnel</div>
          {(data?.recommendation_funnel || []).map(stage => <div key={stage.id} style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border-subtle)', padding: '6px 0', fontSize: 10 }}><span style={{ color: 'var(--text2)' }}>{stage.label}</span><strong style={{ color: 'var(--text0)', fontFamily: 'var(--mono)' }}>{fmt(stage.count)}</strong></div>)}
        </div>
        <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 12, background: 'var(--bg2)' }} data-testid="cio-findings">
          <div style={{ color: 'var(--text0)', fontWeight: 800, fontSize: 12, marginBottom: 8 }}>Remediation and validation</div>
          {!findings.length && <div style={{ color: 'var(--green)', fontSize: 10 }}>No open findings.</div>}
          {findings.slice(0, 6).map(finding => <div key={finding.issue_id} style={{ borderBottom: '1px solid var(--border-subtle)', padding: '6px 0' }}><div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 10 }}><strong>{finding.issue_id} · {finding.title}</strong><StatusPill status={finding.status === 'FIXED_VALIDATED' ? 'WORKING' : 'DEGRADED'} /></div><div style={{ color: 'var(--text3)', fontSize: 10, marginTop: 3 }}>{finding.root_cause}</div></div>)}
        </div>
      </div>
      <div style={{ color: 'var(--text3)', fontSize: 10 }}>Policy: {fmt(data?.policy?.status)} · Missing fields: {data?.policy?.missing_count ?? 0} · Financial action: false</div>
    </section>
  )
}

import { useState } from 'react'
import { useApi } from '../../hooks/useApi'
import { BB, T, TYPE, numStyle } from '../../lib/watchTokens'

// Reports v3 WS-B: the whole-system rollup — everything the system did, one dashboard.
// Data: /api/v2/reports/system-rollup (deterministic COUNT aggregates + reused snapshots;
// every panel corpus-tagged and drill-linked to its home page). Trends read the nightly
// system_rollup_daily snapshots — honest empty state until >=3 days accrue.

const FQDN = typeof window !== 'undefined' ? window.location.origin : ''

const panelCard: React.CSSProperties = {
  background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '10px 12px',
}

function PanelHead({ title, corpus, drill, drillLabel }: { title: string; corpus?: string; drill?: string; drillLabel?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
      <span style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.06em', color: BB.text2, textTransform: 'uppercase' }}>{title}</span>
      {corpus && <span style={{ fontSize: 8.5, fontWeight: 700, color: BB.text3, textTransform: 'uppercase' }}>· {corpus}</span>}
      <span style={{ flex: 1 }} />
      {drill && <a href={FQDN + drill} target="_blank" rel="noreferrer" style={{ fontSize: TYPE.xs, fontWeight: 700, color: T.link, textDecoration: 'none' }}>{drillLabel || 'open'} ↗</a>}
    </div>
  )
}

function Row({ label, value, sub, color }: { label: string; value: any; sub?: string; color?: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, fontSize: TYPE.xs, padding: '2px 0', borderBottom: `1px solid ${BB.borderHair}`, alignItems: 'baseline' }}>
      <span style={{ color: color || BB.text2, minWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
      <span style={{ ...numStyle, color: color || BB.text1, marginLeft: 'auto' }}>{value}</span>
      {sub && <span style={{ ...numStyle, color: BB.text3, minWidth: 54, textAlign: 'right' }}>{sub}</span>}
    </div>
  )
}

function Spark({ points, color }: { points: number[]; color: string }) {
  if (points.length < 2) return null
  const mx = Math.max(1, ...points.map(Math.abs))
  return (
    <div style={{ display: 'flex', gap: 1, alignItems: 'flex-end', height: 18 }}>
      {points.map((v, i) => (
        <div key={i} style={{ width: 5, height: Math.max(2, (Math.abs(v) / mx) * 17), background: v < 0 ? BB.red : color, borderRadius: 1, opacity: 0.5 + 0.5 * (i / points.length) }} />
      ))}
    </div>
  )
}

export default function SystemRollupTab() {
  const [win, setWin] = useState<'24h' | '7d'>('24h')
  const { data } = useApi<any>(`/api/v2/reports/system-rollup?window=${win}`, 120_000)
  const p = data?.panels || {}
  const g = (n: string) => p[n]?.data || {}
  const corpus = (n: string) => p[n]?.corpus
  const pipes: any[] = g('pipelines').rows || []
  const failures = pipes.filter(r => Number(r.failures || 0) > 0)
  const agents: any[] = g('agents').rows || []
  const props: any[] = g('proposals').rows || []
  const alerts: any[] = g('alerts').rows || []
  const paper = g('paper_trades')
  const research = g('research')
  const reports = g('reports_generated').rows || []
  const directives = g('directives')
  const health = g('health')
  const trends = g('trends')
  const trendRows: any[] = (trends.rows || []).slice().reverse()
  const sevColor: Record<string, string> = { critical: BB.red, urgent: BB.red, warning: BB.orange, info: BB.text3 }
  const spark = (key: string) => trendRows.map((r: any) => Number(r.payload?.headlines?.[key] ?? 0))

  if (!data) return <div style={{ ...panelCard, textAlign: 'center', color: BB.text3, fontSize: 12, padding: 24 }}>loading system rollup…</div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <span style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.06em', color: BB.text3 }}>ACTIVITY WINDOW</span>
        {(['24h', '7d'] as const).map(w => (
          <button key={w} onClick={() => setWin(w)} style={{
            fontSize: TYPE.xs, fontWeight: win === w ? 800 : 600, padding: '2px 10px', borderRadius: 2, cursor: 'pointer',
            border: `1px solid ${win === w ? T.link : BB.border}`, background: win === w ? `${T.link}18` : 'transparent',
            color: win === w ? T.link : BB.text3,
          }}>{w}</button>
        ))}
        <span style={{ fontSize: TYPE.xs, color: BB.text3, marginLeft: 'auto' }}>deterministic rollup · {data.generated_at?.slice(11, 16)}Z · digest 20:40 nightly</span>
      </div>

      {/* health strip */}
      <div style={{ ...panelCard, borderLeft: `3px solid ${Number(health.health_score) >= 70 ? BB.green : Number(health.health_score) >= 40 ? BB.orange : BB.red}` }}>
        <PanelHead title="Health strip" corpus={corpus('health')} drill="/v3/health" drillLabel="Health hub" />
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'baseline' }}>
          <span style={{ ...numStyle, fontSize: 20, fontWeight: 800, color: Number(health.health_score) >= 70 ? BB.green : Number(health.health_score) >= 40 ? BB.orange : BB.red }}>{health.health_score ?? '—'}</span>
          {Object.entries(health.category_scores || {}).map(([k, v]: any) => (
            <span key={k} style={{ fontSize: TYPE.xs, color: BB.text3 }}>{k.replace(/_/g, ' ')} <b style={{ ...numStyle, color: v >= 70 ? BB.green : v >= 40 ? BB.orange : BB.red }}>{v}</b></span>
          ))}
          {health.data_sources && <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>data sources <b style={{ ...numStyle, color: health.data_sources.unhealthy ? BB.orange : BB.green }}>{health.data_sources.total - health.data_sources.unhealthy}/{health.data_sources.total} ok</b></span>}
          {health.llm && Object.keys(health.llm).length > 0 && <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>llm {Object.entries(health.llm).map(([k, v]: any) => `${k.replace(/_/g, ' ')} ${v}`).join(' · ')}</span>}
        </div>
      </div>

      {/* activity grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>
        <div style={panelCard}>
          <PanelHead title={`Pipelines (${pipes.reduce((s, r) => s + Number(r.runs || 0), 0)} runs)`} corpus={corpus('pipelines')} drill="/v3/system" drillLabel="System hub" />
          {failures.length > 0 && (
            <div style={{ borderLeft: `3px solid ${BB.red}`, paddingLeft: 8, marginBottom: 6 }}>
              {failures.slice(0, 5).map((r, i) => <Row key={i} label={r.pipeline_key} value={`${r.failures} failed`} sub={`of ${r.runs}`} color={BB.red} />)}
            </div>
          )}
          {pipes.slice(0, 6).map((r, i) => <Row key={i} label={r.pipeline_key} value={r.runs} sub={`${r.successes} ok`} />)}
          {pipes.length === 0 && <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>no runs in window</div>}
        </div>

        <div style={panelCard}>
          <PanelHead title={`Agents (${agents.reduce((s, r) => s + Number(r.analyses || 0), 0)} analyses)`} corpus={corpus('agents')} drill="/v3/agents" drillLabel="Agents hub" />
          {agents.slice(0, 8).map((r, i) => <Row key={i} label={r.agent} value={r.analyses} sub={`conf ${r.avg_conf ?? '—'}`} />)}
        </div>

        <div style={panelCard}>
          <PanelHead title={`Proposals (${props.reduce((s, r) => s + Number(r.cnt || 0), 0)})`} corpus={corpus('proposals')} drill="/v3/trading?tab=Proposals" drillLabel="Approvals" />
          {props.slice(0, 8).map((r, i) => <Row key={i} label={r.status} value={r.cnt} />)}
        </div>

        <div style={panelCard}>
          <PanelHead title="Paper trades closed" corpus={corpus('paper_trades')} drill="/v3/journal" drillLabel="Journal" />
          <Row label="closed" value={paper.closed ?? 0} />
          <Row label="wins / losses" value={`${paper.wins ?? 0} / ${paper.losses ?? 0}`} />
          <Row label="P&L" value={`$${paper.pnl ?? 0}`} color={Number(paper.pnl || 0) >= 0 ? BB.green : BB.red} />
        </div>

        <div style={panelCard}>
          <PanelHead title={`Alerts (${alerts.reduce((s, r) => s + Number(r.n || 0), 0)})`} corpus={corpus('alerts')} drill="/v3/reports?mode=archive" drillLabel="Archive" />
          {alerts.map((r, i) => <Row key={i} label={r.severity} value={Number(r.n).toLocaleString()} color={sevColor[(r.severity || '').toLowerCase()]} />)}
        </div>

        <div style={panelCard}>
          <PanelHead title="Research & reports" corpus={corpus('research')} drill="/v3/research-intel" drillLabel="Research Intel" />
          <Row label="hermes research items" value={research.hermes_items ?? 0} />
          <Row label="topic iterations" value={research.topic_iterations ?? 0} />
          {reports.map((r: any, i: number) => <Row key={i} label={`report · ${r.report_type}`} value={r.n} />)}
        </div>

        <div style={panelCard}>
          <PanelHead title="Directives" corpus={corpus('directives')} drill="/v3/watch" drillLabel="Watch" />
          <Row label="created" value={directives.created ?? 0} />
          <Row label="hits surfaced" value={directives.hits ?? 0} />
        </div>

        <div style={panelCard}>
          <PanelHead title={`Trends (${trends.days ?? 0} daily snapshots)`} corpus={corpus('trends')} />
          {(trends.days ?? 0) >= 3 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {(['pipelines_run', 'agent_analyses', 'alerts_raw', 'paper_pnl', 'health_score'] as string[]).map(k => (
                <div key={k} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span style={{ fontSize: TYPE.xs, color: BB.text3, minWidth: 110 }}>{k.replace(/_/g, ' ')}</span>
                  <Spark points={spark(k)} color={T.link} />
                  <span style={{ ...numStyle, fontSize: TYPE.xs, color: BB.text1, marginLeft: 'auto' }}>{spark(k).slice(-1)[0]?.toLocaleString?.() ?? '—'}</span>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>
              {trends.days ?? 0} of 3 daily snapshots accrued — sparklines render once ≥3 days exist (nightly 20:40 job). No fabricated history.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

const STATUS_COLORS: Record<string, string> = {
  success: '#0ecb81', failed: '#f6465d', degraded: '#f0b90b',
  skipped: '#848e9c', running: '#4a90f4', pending: '#848e9c',
  healthy: '#0ecb81', error: '#f6465d', unknown: '#848e9c',
}
const dot = (s: string) => <span style={{ display:'inline-block', width:8, height:8, borderRadius:4, background: STATUS_COLORS[s] || '#848e9c', marginRight:6 }}/>
const btn: React.CSSProperties = { fontSize:10, padding:'4px 10px', border:'1px solid var(--border)', borderRadius:4, background:'var(--bg1)', color:'var(--text1)', cursor:'pointer' }

const GROUPS = ['data_collection','enrichment','scoring','intelligence','proposals','execution','overnight']

export default function PipelineController() {
  const [rk, setRk] = useState(0)
  const { data: statusData } = useApi<any>(`/api/v2/pipeline-controller/status?_r=${rk}`)
  const { data: stagesData } = useApi<any>(`/api/v2/pipeline-controller/stages?_r=${rk}`)
  const { data: failuresData } = useApi<any>(`/api/v2/pipeline-controller/failures?_r=${rk}`)
  const { data: runsData } = useApi<any>(`/api/v2/pipeline-controller/runs?limit=10&_r=${rk}`)
  const { data: sourceHealth } = useApi<any>(`/api/v2/discovery-source-health?_r=${rk}`)
  const { data: validationData } = useApi<any>(`/api/v2/paper-validation-status?_r=${rk}`)
  const { data: factsData } = useApi<any>(`/api/v2/system-facts?_r=${rk}`)

  const latest = statusData?.data
  const stages = stagesData?.data || []
  const failures = failuresData?.data || []
  const runs = runsData?.data || []
  const sources = sourceHealth?.data || []
  const validation = validationData?.data || {}
  const facts = factsData?.data || {}

  const stagesByGroup: Record<string, any[]> = {}
  for (const g of GROUPS) stagesByGroup[g] = []
  for (const s of stages) {
    const g = s.group_key || 'unknown'
    if (!stagesByGroup[g]) stagesByGroup[g] = []
    stagesByGroup[g].push(s)
  }

  return (
    <>
      <PageHeader title="Pipeline Controller" subtitle="Dependency-aware orchestration, source health, trading gate, system facts" actions={
        <button onClick={() => setRk(k=>k+1)} style={btn}>Refresh</button>
      }/>

      {/* Paper Validation Banner */}
      <div style={{ padding:'8px 14px', marginBottom:12, borderRadius:6,
        background: validation?.allowed ? 'rgba(246,70,93,.15)' : 'rgba(14,203,129,.08)',
        border: `1px solid ${validation?.allowed ? '#f6465d' : '#0ecb81'}`,
        display:'flex', alignItems:'center', gap:12 }}>
        <span style={{ fontSize:13, fontWeight:700, color: validation?.allowed ? '#f6465d' : '#0ecb81' }}>
          {validation?.allowed ? 'LIVE TRADING ALLOWED' : 'PAPER MODE ACTIVE'}
        </span>
        <span style={{ fontSize:11, color:'var(--text2)' }}>
          {validation?.gates?.validation_days_elapsed ?? '?'}/{validation?.gates?.validation_days_required ?? '?'} days
          {' | '}{validation?.gates?.closed_trades ?? '?'}/{validation?.gates?.closed_trades_required ?? '?'} trades
          {' | '}WR: {((validation?.gates?.win_rate ?? 0)*100).toFixed(0)}%/{((validation?.gates?.win_rate_required ?? 0)*100).toFixed(0)}%
          {' | '}PF: {validation?.gates?.profit_factor ?? '?'}/{validation?.gates?.profit_factor_required ?? '?'}
          {' | '}Gov: {validation?.gates?.governance_approved ? 'Yes' : 'No'}
        </span>
      </div>

      {/* Latest Run */}
      <Card title={`Latest Run: ${latest?.run_id || 'none'}`} style={{ marginBottom:12 }}>
        {latest ? (
          <div style={{ display:'flex', gap:20, fontSize:11, color:'var(--text2)' }}>
            <div>{dot(latest.status)}{(latest.status||'').toUpperCase()}</div>
            <div>Label: {latest.run_label}</div>
            <div>Duration: {latest.duration_seconds ? `${Math.round(latest.duration_seconds)}s` : '-'}</div>
            <div>Trigger: {latest.trigger_source}</div>
            <div>Started: {latest.started_at ? new Date(latest.started_at).toLocaleString() : '-'}</div>
            {latest.summary && (
              <div>OK:{latest.summary.success} Fail:{latest.summary.failed} Deg:{latest.summary.degraded} Skip:{latest.summary.skipped}</div>
            )}
          </div>
        ) : <div style={{ fontSize:11, color:'var(--text3)' }}>No pipeline runs yet</div>}
      </Card>

      {/* Stage Grid by Group */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(280px, 1fr))', gap:10, marginBottom:14 }}>
        {GROUPS.map(g => (
          <Card key={g} title={g.replace(/_/g,' ').toUpperCase()} compact>
            {(stagesByGroup[g] || []).length === 0
              ? <div style={{ fontSize:10, color:'var(--text3)' }}>No stages</div>
              : (stagesByGroup[g] || []).map((s: any) => (
                <div key={s.stage_key} style={{ fontSize:10, padding:'3px 0', borderBottom:'1px solid var(--border)',
                  display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                  <span>{s.stage_key}</span>
                  <span style={{ color:'var(--text3)' }}>
                    {s.timeout_seconds}s{s.can_degrade ? ' [D]' : ''}
                  </span>
                </div>
              ))
            }
          </Card>
        ))}
      </div>

      {/* Failures */}
      {failures.length > 0 && (
        <Card title={`Recent Failures (${failures.length})`} style={{ marginBottom:12 }}>
          <table style={{ width:'100%', fontSize:10, borderCollapse:'collapse' }}>
            <thead><tr style={{ borderBottom:'1px solid var(--border)', color:'var(--text3)' }}>
              <th style={{ textAlign:'left', padding:4 }}>Run</th>
              <th style={{ textAlign:'left', padding:4 }}>Stage</th>
              <th style={{ textAlign:'left', padding:4 }}>Status</th>
              <th style={{ textAlign:'left', padding:4 }}>Error</th>
              <th style={{ textAlign:'right', padding:4 }}>Duration</th>
            </tr></thead>
            <tbody>
              {failures.slice(0,10).map((f: any, i: number) => (
                <tr key={i} style={{ borderBottom:'1px solid var(--border)' }}>
                  <td style={{ padding:4, color:'var(--text2)' }}>{f.run_id?.slice(-15)}</td>
                  <td style={{ padding:4 }}>{f.stage_key}</td>
                  <td style={{ padding:4 }}>{dot(f.status)}{f.status}</td>
                  <td style={{ padding:4, color:'var(--text3)', maxWidth:200, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{f.error_message || '-'}</td>
                  <td style={{ padding:4, textAlign:'right' }}>{f.duration_seconds ? `${Math.round(f.duration_seconds)}s` : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* Discovery Source Health */}
      <Card title="Discovery Source Health" style={{ marginBottom:12 }}>
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(200px,1fr))', gap:8 }}>
          {sources.map((s: any) => (
            <div key={s.source_key} style={{ fontSize:10, padding:'6px 10px', border:'1px solid var(--border)', borderRadius:4,
              background: s.degraded ? 'rgba(240,185,11,.05)' : 'transparent' }}>
              <div style={{ fontWeight:600, marginBottom:2 }}>{dot(s.status)}{s.source_key}</div>
              <div style={{ color:'var(--text3)' }}>
                Rows: {s.last_row_count ?? '-'} | Fails: {s.failure_count}
                {s.last_error && <div style={{ color:'#f6465d', marginTop:2 }}>{s.last_error.slice(0,80)}</div>}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* System Facts Summary */}
      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:10, marginBottom:14 }}>
        <Card title="System Facts" compact>
          {facts?.database ? (
            <div style={{ fontSize:10, color:'var(--text2)' }}>
              <div>Tables: {facts.database.table_count} | Scripts: {facts.codebase?.python_script_count}</div>
              <div>Strategies: {facts.codebase?.strategy_count} | Crons: {facts.codebase?.cron_job_count}</div>
              <div>LLM: {facts.llm?.ollama_available ? `Ollama (${facts.llm.ollama_models?.join(', ')})` : 'Offline'}</div>
              <div>Holdings: ${(facts.safety?.holdings_value||0).toLocaleString()} | Guard: {facts.safety?.holdings_guard_passed ? 'PASS' : 'FAIL'}</div>
            </div>
          ) : <div style={{ fontSize:10, color:'var(--text3)' }}>Run generate_system_facts.py first</div>}
        </Card>
        <Card title="Recent Runs" compact>
          {runs.slice(0,5).map((r: any) => (
            <div key={r.run_id} style={{ fontSize:10, padding:'2px 0', borderBottom:'1px solid var(--border)',
              display:'flex', justifyContent:'space-between' }}>
              <span>{dot(r.status)}{r.run_id?.slice(-20)}</span>
              <span style={{ color:'var(--text3)' }}>{r.duration_seconds ? `${Math.round(r.duration_seconds)}s` : '-'}</span>
            </div>
          ))}
          {runs.length === 0 && <div style={{ fontSize:10, color:'var(--text3)' }}>No runs yet</div>}
        </Card>
      </div>
    </>
  )
}

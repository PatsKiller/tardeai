import { useState, useMemo } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'

interface HermesRow {
  id: number; symbol: string; hermes_agent_name: string; research_type: string
  topic: string; summary: string; thesis: string; confidence_score: number
  status: string; model_used: string; freshness_date: string; created_at: string
  embedded: boolean
}

interface IntelData {
  rows: HermesRow[]
  total: number; embedded: number; promoted: number; staged: number
  audit: Array<{ source_id: number; target_table: string; promoted_at: string }>
}

const statusColor: Record<string, string> = {
  promoted: 'var(--accent)', staged: 'var(--text3)', embedded: 'var(--green)',
}

export default function HermesIntelligence() {
  const [rk, setRk] = useState(0)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [detail, setDetail] = useState<HermesRow | null>(null)
  const { data, loading, error } = useApi<IntelData>(`/api/v2/hermes/intelligence?_r=${rk}`)
  const { data: prData } = useApi<{ candidates: Array<{ hermes_row_id: number; symbol_or_topic: string; recommended_disposition: string; confidence_score: number; rationale: string }>; duplicates: Array<{ id: number; symbol: string; reason: string }>; total_candidates: number; total_duplicates: number; advisory_notice: string }>(`/api/v2/hermes/promotion-review?_r=${rk}`)
  const { data: pqData } = useApi<{ findings: Array<{ id: number; finding_type: string; severity: string; description: string; recommended_action: string; status: string; created_at: string }>; total: number }>(`/api/v2/hermes/pipeline-quality?_r=${rk}`)
  const { data: blData } = useApi<{ items: Array<{ id: number; symbol: string | null; topic: string; summary: string; confidence_score: number; status: string; priority: string; owner_agent: string; backlog_type: string; created_at: string }>; total: number; advisory_notice: string }>(`/api/v2/hermes/research-backlog?_r=${rk}`)

  const filtered = useMemo(() => {
    if (!data) return []
    return data.rows.filter(r => {
      if (search && !(r.symbol || '').toLowerCase().includes(search.toLowerCase()) && !r.topic.toLowerCase().includes(search.toLowerCase())) return false
      if (statusFilter === 'promoted' && r.status !== 'promoted') return false
      if (statusFilter === 'staged' && r.status !== 'staged') return false
      if (statusFilter === 'embedded' && !r.embedded) return false
      return true
    })
  }, [data, search, statusFilter])

  if (loading && !data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading...</div>
  if (error) return <div style={{ padding: 24, color: 'var(--red)' }}>Error: {error}</div>
  if (!data) return null

  return (
    <>
      <PageHeader title="Hermes Intelligence" subtitle="Advisory research, challenger findings, and promotion audit" actions={
        <button onClick={() => setRk(k => k + 1)} style={{ fontSize: 11, padding: '4px 12px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text1)', cursor: 'pointer' }}>Refresh</button>
      } />

      <div style={{ fontSize: 9, color: 'var(--amber)', marginBottom: 10, padding: '4px 10px', background: 'rgba(246,190,0,.06)', border: '1px solid rgba(246,190,0,.15)', borderRadius: 4 }}>
        Advisory Only — Not Execution — Not Broker-Connected — Hermes Challenger Intelligence
      </div>

      {/* Summary */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
        {[
          { label: 'Total', value: data.total, color: 'var(--text0)' },
          { label: 'Promoted', value: data.promoted, color: 'var(--accent)' },
          { label: 'Staged', value: data.staged, color: 'var(--text3)' },
          { label: 'Embedded', value: data.embedded, color: 'var(--green)' },
          { label: 'Audit Records', value: data.audit?.length || 0, color: 'var(--text2)' },
          { label: 'Pipeline Findings', value: pqData?.total || 0, color: 'var(--amber)' },
        ].map((m, i) => (
          <div key={i} style={{ padding: '8px 16px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, textAlign: 'center' }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: m.color }}>{m.value}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)' }}>{m.label}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search symbol/topic..."
          style={{ fontSize: 11, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text1)', width: 180 }} />
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
          style={{ fontSize: 11, padding: '4px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text1)' }}>
          <option value="all">All Status</option>
          <option value="promoted">Promoted</option>
          <option value="staged">Staged</option>
          <option value="embedded">Embedded</option>
        </select>
      </div>

      {/* Table */}
      <Card>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              {['ID', 'Symbol', 'Type', 'Confidence', 'Status', 'Summary', 'Date', ''].map(h => (
                <th key={h} style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text3)', fontWeight: 600, fontSize: 10 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(r => (
              <tr key={r.id} style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '6px 8px', color: 'var(--text3)', fontFamily: 'monospace' }}>{r.id}</td>
                <td style={{ padding: '6px 8px', color: 'var(--text0)', fontWeight: 600 }}>{r.symbol || 'SYSTEM'}</td>
                <td style={{ padding: '6px 8px', color: 'var(--text2)', fontSize: 10 }}>{r.research_type.replace(/_/g, ' ')}</td>
                <td style={{ padding: '6px 8px', color: 'var(--text1)' }}>{r.confidence_score}</td>
                <td style={{ padding: '6px 8px' }}>
                  <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 3, background: `${statusColor[r.status] || 'var(--text3)'}22`, color: statusColor[r.status] || 'var(--text3)' }}>
                    {r.status}{r.embedded && r.status !== 'promoted' ? ' + RAG' : ''}
                  </span>
                </td>
                <td style={{ padding: '6px 8px', color: 'var(--text2)', fontSize: 10, maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.summary?.substring(0, 80)}</td>
                <td style={{ padding: '6px 8px', color: 'var(--text3)', fontSize: 10 }}>{new Date(r.created_at).toLocaleDateString()}</td>
                <td style={{ padding: '6px 8px' }}>
                  <button onClick={() => setDetail(r)} style={{ fontSize: 9, padding: '2px 6px', border: '1px solid var(--accent)', borderRadius: 3, background: 'transparent', color: 'var(--accent)', cursor: 'pointer' }}>View</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {/* Pipeline Quality Findings */}
      {pqData && pqData.findings.length > 0 && (
        <Card title="Pipeline Quality Findings">
          <div style={{ fontSize: 9, color: 'var(--amber)', marginBottom: 6 }}>Advisory Only — Not Auto-Promoted</div>
          {pqData.findings.map(f => (
            <div key={f.id} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 2 }}>
                <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, background: f.severity === 'warning' ? 'rgba(246,190,0,.15)' : 'rgba(74,144,244,.1)', color: f.severity === 'warning' ? 'var(--amber)' : 'var(--accent)' }}>{f.severity}</span>
                <span style={{ color: 'var(--text2)', fontSize: 10 }}>{f.finding_type.replace(/_/g, ' ')}</span>
                <span style={{ color: 'var(--text3)', fontSize: 9 }}>{new Date(f.created_at).toLocaleDateString()}</span>
              </div>
              <div style={{ color: 'var(--text0)', fontSize: 11 }}>{f.description}</div>
              {f.recommended_action && <div style={{ color: 'var(--text3)', fontSize: 10, marginTop: 2 }}>Action: {f.recommended_action}</div>}
            </div>
          ))}
        </Card>
      )}

      {/* Promotion Review */}
      {prData && prData.total_candidates > 0 && (
        <Card title={`Promotion Review (${prData.total_candidates} candidates)`}>
          <div style={{ fontSize: 9, color: 'var(--amber)', marginBottom: 6, padding: '3px 6px', background: 'rgba(246,190,0,.08)', borderRadius: 3 }}>Dry-Run Only — Auto-Promotion Prohibited — Operator Review Required</div>
          {prData.candidates.map((c, i) => (
            <div key={i} style={{ padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 2 }}>
                <span style={{ color: 'var(--text0)', fontWeight: 600 }}>{c.symbol_or_topic}</span>
                <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, background: c.recommended_disposition === 'candidate_for_future_promotion' ? 'rgba(74,144,244,.1)' : 'rgba(246,190,0,.1)', color: c.recommended_disposition === 'candidate_for_future_promotion' ? 'var(--accent)' : 'var(--amber)' }}>{c.recommended_disposition.replace(/_/g, ' ')}</span>
                <span style={{ color: 'var(--text3)', fontSize: 9 }}>conf: {c.confidence_score}</span>
              </div>
              <div style={{ color: 'var(--text2)', fontSize: 10 }}>{c.rationale}</div>
            </div>
          ))}
          {prData.total_duplicates > 0 && <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 6 }}>{prData.total_duplicates} already promoted (skipped)</div>}
        </Card>
      )}

      {/* Research Backlog */}
      {blData && blData.total > 0 && (
        <Card title={`Research Backlog (${blData.total} items)`}>
          <div style={{ fontSize: 9, color: 'var(--amber)', marginBottom: 6, padding: '3px 6px', background: 'rgba(246,190,0,.08)', borderRadius: 3 }}>Advisory Only — Research Needed — Not Execution — No Autonomous Research</div>
          {blData.items.map(b => (
            <div key={b.id} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 2, flexWrap: 'wrap' }}>
                <span style={{ color: 'var(--text0)', fontWeight: 600 }}>{b.symbol || 'SYSTEM'}</span>
                <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, background: b.priority === 'medium' ? 'rgba(246,190,0,.15)' : b.priority === 'high' ? 'rgba(234,57,67,.15)' : 'rgba(74,144,244,.1)', color: b.priority === 'medium' ? 'var(--amber)' : b.priority === 'high' ? 'var(--red)' : 'var(--accent)' }}>{b.priority}</span>
                <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 3, background: 'rgba(74,144,244,.08)', color: 'var(--text3)' }}>{b.backlog_type.replace(/_/g, ' ')}</span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{b.owner_agent.replace(/_/g, ' ')}</span>
              </div>
              <div style={{ color: 'var(--text1)', fontSize: 11, marginBottom: 2 }}>{b.topic}</div>
              <div style={{ color: 'var(--text2)', fontSize: 10 }}>{b.summary?.substring(0, 150)}</div>
              <div style={{ color: 'var(--text3)', fontSize: 9, marginTop: 2 }}>conf: {b.confidence_score} | {new Date(b.created_at).toLocaleDateString()}</div>
            </div>
          ))}
        </Card>
      )}

      {detail && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setDetail(null)}>
          <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 20, maxWidth: 600, width: '90%', maxHeight: '80vh', overflowY: 'auto' }}>
            <div style={{ fontSize: 9, color: 'var(--amber)', marginBottom: 8, padding: '3px 6px', background: 'rgba(246,190,0,.08)', borderRadius: 3 }}>Advisory Only — Not Execution</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>{detail.symbol || 'SYSTEM'} — {detail.research_type.replace(/_/g, ' ')}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>ID: {detail.id} | Agent: {detail.hermes_agent_name} | Model: {detail.model_used} | Confidence: {detail.confidence_score}</div>
            <div style={{ fontSize: 12, color: 'var(--text0)', marginBottom: 8, lineHeight: 1.5 }}><strong>Summary:</strong> {detail.summary}</div>
            {detail.thesis && <div style={{ fontSize: 11, color: 'var(--text1)', marginBottom: 8, lineHeight: 1.5 }}><strong>Thesis:</strong> {detail.thesis}</div>}
            <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
              <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 3, background: `${statusColor[detail.status]}22`, color: statusColor[detail.status] }}>{detail.status}</span>
              {detail.embedded && <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 3, background: 'rgba(14,203,129,.15)', color: 'var(--green)' }}>RAG</span>}
            </div>
            <button onClick={() => setDetail(null)} style={{ marginTop: 12, fontSize: 11, padding: '6px 16px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text1)', cursor: 'pointer' }}>Close</button>
          </div>
        </div>
      )}
    </>
  )
}

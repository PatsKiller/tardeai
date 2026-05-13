import { useState, useCallback } from 'react'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import { useApi } from '../hooks/useApi'
import { timeAgo } from '../lib/format'

/* ── Types ──────────────────────────────────────────────────────────── */

interface QueueSummary {
  pending: number
  done_today: number
  failed: number
  running: number
  cap_tonight: number
  window_start: string
  window_end: string
  next_window_in_hours: number
  estimated_completion_nights: number
  by_status: { status: string; count: number }[]
  job_budget: {
    cap: number
    pending_p0: number
    pending_p1: number
    pending_p2: number
    pending_p3: number
    pending_p4: number
    will_run_tonight: number
    wont_run_tonight: number
  }
}

interface PendingJob {
  id: number
  job_type: string
  symbol: string
  priority_tier: string
  priority_score: number
  reason_codes: string[]
  queued_at: string
  age_hours: number
  attempt_count: number
  will_run_tonight: boolean
}

interface CompletedJob {
  id: number
  job_type: string
  symbol: string
  priority_tier: string
  completed_at: string
  duration_seconds: number
  summary: string
  curation_verdict: string | null
  risk_narrative: string | null
  reentry_verdict: string | null
  cc_verdict: string | null
  had_error: boolean
}

interface FailedJob {
  id: number
  job_type: string
  symbol: string
  priority_tier: string
  priority_score: number
  attempt_count: number
  last_error: string
  queued_at: string
}

interface CompletedData {
  jobs: CompletedJob[]
  total: number
  stats: { total_ran: number; avg_duration: number; fastest: number; slowest: number; error_count: number }
}

/* ── Sub-tab state ──────────────────────────────────────────────────── */

const SUB_TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'pending', label: 'Pending Queue' },
  { id: 'completed', label: 'Completed' },
  { id: 'failed', label: 'Failed' },
  { id: 'schedule', label: 'Schedule & Controls' },
]

/* ── Main component ─────────────────────────────────────────────────── */

export default function LLMQueue() {
  const [tab, setTab] = useState('overview')

  return (
    <>
      {/* Sub-tabs */}
      <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--border)', marginBottom: 14 }}>
        {SUB_TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding: '7px 14px', fontSize: 11, fontWeight: tab === t.id ? 600 : 400,
            color: tab === t.id ? 'var(--accent)' : 'var(--text3)',
            background: 'none', border: 'none', cursor: 'pointer',
            borderBottom: tab === t.id ? '2px solid var(--accent)' : '2px solid transparent',
            marginBottom: -1,
          }}>{t.label}</button>
        ))}
      </div>

      {tab === 'overview' && <OverviewTab />}
      {tab === 'pending' && <PendingTab />}
      {tab === 'completed' && <CompletedTab />}
      {tab === 'failed' && <FailedTab />}
      {tab === 'schedule' && <ScheduleTab />}
    </>
  )
}

/* ── Helpers ─────────────────────────────────────────────────────────── */

const tierColor = (tier: string) =>
  tier === 'P0' ? 'var(--red)' : tier === 'P1' ? 'var(--amber)' : 'var(--text3)'

const tierBorder = (tier: string) =>
  tier === 'P0' ? '3px solid var(--red)' : tier === 'P1' ? '3px solid var(--amber)' : 'none'

const verdictBadge = (verdict: string | null, type: 'curation' | 'reentry' | 'cc') => {
  if (!verdict) return null
  const map: Record<string, { bg: string; fg: string }> = {
    APPROVE_BOOST: { bg: 'var(--green-dim)', fg: 'var(--green)' },
    APPROVE_STANDARD: { bg: 'rgba(74,144,244,.15)', fg: 'var(--accent)' },
    LOW_QUALITY: { bg: 'var(--bg3)', fg: 'var(--text3)' },
    SUPERSEDED: { bg: 'rgba(255,160,0,.12)', fg: 'var(--amber)' },
    THESIS_INTACT: { bg: 'var(--green-dim)', fg: 'var(--green)' },
    THESIS_INVALIDATED: { bg: 'var(--red-dim)', fg: 'var(--red)' },
    NEEDS_MORE_DATA: { bg: 'rgba(255,160,0,.12)', fg: 'var(--amber)' },
    FAVORABLE: { bg: 'var(--green-dim)', fg: 'var(--green)' },
    MARGINAL: { bg: 'rgba(255,160,0,.12)', fg: 'var(--amber)' },
    SKIP: { bg: 'var(--bg3)', fg: 'var(--text3)' },
  }
  const s = map[verdict] || { bg: 'var(--bg3)', fg: 'var(--text2)' }
  return <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 4, background: s.bg, color: s.fg }}>{verdict}</span>
}

const TH: React.CSSProperties = { padding: '5px 8px', textAlign: 'left', color: 'var(--text3)', fontSize: 10, fontWeight: 600, borderBottom: '1px solid var(--border)', position: 'sticky' as const, top: 0, background: 'var(--bg1)' }
const TD: React.CSSProperties = { padding: '4px 8px', borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,.04))', fontSize: 11 }
const TDR: React.CSSProperties = { ...TD, textAlign: 'right' }

/* ── Tab 1: Overview ────────────────────────────────────────────────── */

function OverviewTab() {
  const { data: summary } = useApi<QueueSummary>('/api/v2/queue/summary', 30000)
  const { data: pending } = useApi<{ jobs: PendingJob[]; total: number }>('/api/v2/queue/pending')

  if (!summary) return <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20 }}>Loading queue data...</div>

  const b = summary.job_budget
  const pctWill = b.cap > 0 ? (b.will_run_tonight / b.cap) * 100 : 0
  const pctP0 = b.cap > 0 ? (b.pending_p0 / b.cap) * 100 : 0
  const pctP1 = b.cap > 0 ? (Math.min(b.pending_p1, b.will_run_tonight - b.pending_p0) / b.cap) * 100 : 0

  // Group pending jobs by type for breakdown
  const byType: Record<string, { tier: string; count: number; totalScore: number; willRun: number }> = {}
  for (const j of (pending?.jobs ?? [])) {
    const key = j.job_type
    if (!byType[key]) byType[key] = { tier: j.priority_tier, count: 0, totalScore: 0, willRun: 0 }
    byType[key].count++
    byType[key].totalScore += j.priority_score
    if (j.will_run_tonight) byType[key].willRun++
  }

  const clearDate = new Date()
  clearDate.setDate(clearDate.getDate() + Math.ceil(summary.estimated_completion_nights))
  const clearDay = clearDate.toLocaleDateString('en-US', { weekday: 'long' })

  return (
    <>
      {/* Header metrics */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        <MetricTile label="Pending" value={String(summary.pending)} deltaColor={summary.pending > 200 ? 'var(--amber)' : 'var(--text0)'} />
        <MetricTile label="Done Today" value={String(summary.done_today)} deltaColor="var(--green)" />
        <MetricTile label="Cap Tonight" value={String(summary.cap_tonight)} />
        <MetricTile label="Avg Job Time" value="~40s" tooltip="Observed average from nightly runs" />
        <MetricTile label="Next Window" value={summary.next_window_in_hours < 1 ? 'NOW' : `${summary.next_window_in_hours}h`} delta={`${summary.window_start} - ${summary.window_end}`} />
        {summary.failed > 0 && <MetricTile label="Failed" value={String(summary.failed)} deltaColor="var(--red)" />}
        {summary.running > 0 && <MetricTile label="Running" value={String(summary.running)} deltaColor="var(--accent)" />}
      </div>

      {/* Budget bar */}
      <SectionHeader title="Tonight's Budget" />
      <Card compact>
        <div style={{ marginBottom: 6, fontSize: 10, color: 'var(--text2)' }}>
          <strong style={{ color: 'var(--text0)' }}>{b.will_run_tonight}</strong> will run tonight
          {b.wont_run_tonight > 0 && <> &middot; <span style={{ color: 'var(--amber)' }}>{b.wont_run_tonight}</span> pushed to tomorrow</>}
        </div>
        <div style={{ width: '100%', height: 24, borderRadius: 6, background: 'var(--bg3)', overflow: 'hidden', display: 'flex', position: 'relative' }}>
          <div style={{ width: `${pctP0}%`, background: 'var(--red)', height: '100%', transition: 'width .3s' }} title={`P0: ${b.pending_p0}`} />
          <div style={{ width: `${pctP1}%`, background: 'var(--amber)', height: '100%', transition: 'width .3s' }} title={`P1: ${b.pending_p1}`} />
          <div style={{ width: `${Math.max(0, pctWill - pctP0 - pctP1)}%`, background: 'rgba(255,255,255,.15)', height: '100%', transition: 'width .3s' }} title="P2+" />
          {b.wont_run_tonight > 0 && (
            <div style={{ flex: 1, background: 'rgba(255,60,60,.12)', height: '100%' }} title={`${b.wont_run_tonight} won't run`} />
          )}
        </div>
        <div style={{ display: 'flex', gap: 14, marginTop: 6, fontSize: 9, color: 'var(--text3)' }}>
          <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: 'var(--red)', marginRight: 3, verticalAlign: 'middle' }} />P0 ({b.pending_p0})</span>
          <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: 'var(--amber)', marginRight: 3, verticalAlign: 'middle' }} />P1 ({b.pending_p1})</span>
          <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: 'rgba(255,255,255,.15)', marginRight: 3, verticalAlign: 'middle' }} />P2+ ({b.pending_p2 + (b.pending_p3 || 0) + (b.pending_p4 || 0)})</span>
          {b.wont_run_tonight > 0 && <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: 'rgba(255,60,60,.12)', border: '1px solid var(--red)', marginRight: 3, verticalAlign: 'middle' }} />Overflow ({b.wont_run_tonight})</span>}
        </div>
      </Card>

      {/* Job type breakdown */}
      <SectionHeader title="Job Type Breakdown" count={Object.keys(byType).length} />
      <Card compact>
        <div style={{ overflow: 'auto', maxHeight: 300 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              {['Job Type', 'Tier', 'Pending', 'Avg Score', 'Will Run', 'Est Time'].map(h => (
                <th key={h} style={{ ...TH, textAlign: h === 'Job Type' ? 'left' : 'right' }}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {Object.entries(byType).sort((a, b) => (b[1].totalScore / b[1].count) - (a[1].totalScore / a[1].count)).map(([type, d]) => (
                <tr key={type}>
                  <td style={{ ...TD, fontWeight: 600, color: 'var(--text0)' }}>{type.replace(/_/g, ' ')}</td>
                  <td style={{ ...TDR, color: tierColor(d.tier) }}>{d.tier}</td>
                  <td style={TDR}>{d.count}</td>
                  <td style={TDR}>{Math.round(d.totalScore / d.count)}</td>
                  <td style={TDR}>
                    {d.willRun === d.count
                      ? <span style={{ color: 'var(--green)', fontWeight: 600 }}>ALL ({d.count})</span>
                      : <span>{d.willRun}/{d.count}</span>}
                  </td>
                  <td style={{ ...TDR, color: 'var(--text3)' }}>~{Math.round(d.count * 0.7)}m</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Backlog estimate */}
      {summary.estimated_completion_nights > 1 && (
        <Card compact style={{ marginTop: 10 }}>
          <div style={{ fontSize: 11, color: 'var(--text2)' }}>
            At {summary.cap_tonight} jobs/night: backlog clears in ~{summary.estimated_completion_nights} nights (by {clearDay})
          </div>
        </Card>
      )}
    </>
  )
}

/* ── Tab 2: Pending Queue ───────────────────────────────────────────── */

function PendingTab() {
  const { data, refetch } = useApi<{ jobs: PendingJob[]; total: number }>('/api/v2/queue/pending')
  const [filterType, setFilterType] = useState('')
  const [filterTier, setFilterTier] = useState('')
  const [filterSymbol, setFilterSymbol] = useState('')
  const [actionMsg, setActionMsg] = useState<string | null>(null)

  const doAction = useCallback(async (endpoint: string, body: Record<string, unknown>, label: string) => {
    try {
      const r = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const d = await r.json()
      setActionMsg(d.ok ? label : `Failed: ${d.error || 'unknown'}`)
      refetch()
      setTimeout(() => setActionMsg(null), 3000)
    } catch (e) {
      setActionMsg(`Error: ${e}`)
    }
  }, [refetch])

  const jobs = (data?.jobs ?? []).filter(j => {
    if (filterType && j.job_type !== filterType) return false
    if (filterTier && j.priority_tier !== filterTier) return false
    if (filterSymbol && !j.symbol?.toLowerCase().includes(filterSymbol.toLowerCase())) return false
    return true
  })

  const types = [...new Set((data?.jobs ?? []).map(j => j.job_type))]

  return (
    <>
      {actionMsg && (
        <div style={{ padding: '6px 12px', marginBottom: 10, borderRadius: 6, fontSize: 10,
          background: actionMsg.startsWith('Failed') || actionMsg.startsWith('Error') ? 'var(--red-dim)' : 'var(--green-dim)',
          color: actionMsg.startsWith('Failed') || actionMsg.startsWith('Error') ? 'var(--red)' : 'var(--green)',
        }}>{actionMsg}</div>
      )}

      {/* Filters */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <select value={filterType} onChange={e => setFilterType(e.target.value)} style={selectStyle}>
          <option value="">All Types</option>
          {types.map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
        </select>
        <select value={filterTier} onChange={e => setFilterTier(e.target.value)} style={selectStyle}>
          <option value="">All Tiers</option>
          {['P0', 'P1', 'P2', 'P3', 'P4'].map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <input value={filterSymbol} onChange={e => setFilterSymbol(e.target.value)} placeholder="Search symbol..." style={{ ...selectStyle, width: 120 }} />
        <span style={{ fontSize: 10, color: 'var(--text3)', marginLeft: 'auto' }}>{jobs.length} jobs shown / {data?.total ?? 0} total</span>
      </div>

      <Card compact>
        <div style={{ overflow: 'auto', maxHeight: 500 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              {['Priority', 'Job Type', 'Symbol', 'Score', 'Queued', 'Age', 'Actions'].map(h => (
                <th key={h} style={TH}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {jobs.map(j => (
                <tr key={j.id} style={{
                  borderLeft: tierBorder(j.priority_tier),
                  opacity: j.will_run_tonight ? 1 : 0.6,
                  background: j.will_run_tonight ? 'rgba(255,255,255,.02)' : 'transparent',
                }}>
                  <td style={TD}>
                    <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: j.priority_tier === 'P0' ? 'var(--red-dim)' : j.priority_tier === 'P1' ? 'rgba(255,160,0,.12)' : 'var(--bg3)', color: tierColor(j.priority_tier) }}>{j.priority_tier}</span>
                  </td>
                  <td style={{ ...TD, color: 'var(--text1)' }}>{j.job_type.replace(/_/g, ' ')}</td>
                  <td style={{ ...TD, fontWeight: 700, color: 'var(--text0)' }}>{j.symbol || '—'}</td>
                  <td style={{ ...TD, textAlign: 'right', fontWeight: 600, color: 'var(--text0)' }}>{j.priority_score}</td>
                  <td style={{ ...TD, fontSize: 9, color: 'var(--text3)' }}>{j.queued_at ? timeAgo(j.queued_at) : '—'}</td>
                  <td style={{ ...TD, fontSize: 9, color: j.age_hours > 24 ? 'var(--amber)' : 'var(--text3)' }}>{j.age_hours.toFixed(1)}h</td>
                  <td style={TD}>
                    <div style={{ display: 'flex', gap: 4 }}>
                      <button onClick={() => doAction('/api/v2/queue/boost', { job_id: j.id, boost_amount: 50 }, `Boosted #${j.id}`)} style={actionBtn}>↑ Boost</button>
                      <button onClick={() => doAction('/api/v2/queue/cancel', { job_id: j.id }, `Cancelled #${j.id}`)} style={{ ...actionBtn, color: 'var(--red)', borderColor: 'var(--red)' }}>✕</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {jobs.length === 0 && <div style={{ textAlign: 'center', padding: 20, color: 'var(--text3)', fontSize: 11 }}>No pending jobs match filters</div>}
        </div>
      </Card>
    </>
  )
}

/* ── Tab 3: Completed ───────────────────────────────────────────────── */

function CompletedTab() {
  const { data } = useApi<CompletedData>('/api/v2/queue/completed')
  const jobs = data?.jobs ?? []
  const stats = data?.stats

  return (
    <>
      {stats && (
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
          <MetricTile label="Total Ran" value={String(stats.total_ran)} deltaColor="var(--green)" />
          <MetricTile label="Avg Duration" value={`${stats.avg_duration}s`} />
          <MetricTile label="Fastest" value={`${stats.fastest}s`} />
          <MetricTile label="Slowest" value={`${stats.slowest}s`} />
          <MetricTile label="Error Rate" value={stats.total_ran > 0 ? `${((stats.error_count / stats.total_ran) * 100).toFixed(1)}%` : '0%'} deltaColor={stats.error_count > 0 ? 'var(--red)' : 'var(--green)'} />
        </div>
      )}

      <Card compact>
        <div style={{ overflow: 'auto', maxHeight: 500 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              {['Job Type', 'Symbol', 'Duration', 'Verdict / Summary', 'Completed'].map(h => (
                <th key={h} style={TH}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {jobs.map(j => (
                <tr key={j.id}>
                  <td style={{ ...TD, color: 'var(--text1)' }}>{j.job_type.replace(/_/g, ' ')}</td>
                  <td style={{ ...TD, fontWeight: 700, color: 'var(--text0)' }}>{j.symbol || '—'}</td>
                  <td style={{ ...TDR, color: 'var(--text2)' }}>{j.duration_seconds ? `${Math.round(j.duration_seconds)}s` : '—'}</td>
                  <td style={{ ...TD, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {j.job_type === 'rag_content_curation' && verdictBadge(j.curation_verdict, 'curation')}
                    {j.job_type === 'recovery_watch_review' && verdictBadge(j.reentry_verdict, 'reentry')}
                    {j.job_type === 'covered_call_scoring' && verdictBadge(j.cc_verdict, 'cc')}
                    {j.job_type === 'risk_synthesis' && j.risk_narrative && (
                      <span style={{ fontSize: 10, color: 'var(--text2)' }}>{j.risk_narrative.slice(0, 100)}...</span>
                    )}
                    {!j.curation_verdict && !j.reentry_verdict && !j.cc_verdict && !j.risk_narrative && j.summary && (
                      <span style={{ fontSize: 10, color: 'var(--text2)' }}>{j.summary.slice(0, 100)}</span>
                    )}
                  </td>
                  <td style={{ ...TD, fontSize: 9, color: 'var(--text3)' }}>{j.completed_at ? timeAgo(j.completed_at) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {jobs.length === 0 && <div style={{ textAlign: 'center', padding: 20, color: 'var(--text3)', fontSize: 11 }}>No completed jobs in last 24 hours</div>}
        </div>
      </Card>
    </>
  )
}

/* ── Tab 4: Failed ──────────────────────────────────────────────────── */

function FailedTab() {
  const { data, refetch } = useApi<{ jobs: FailedJob[]; total: number }>('/api/v2/queue/failed')
  const [actionMsg, setActionMsg] = useState<string | null>(null)

  const retry = useCallback(async (jobId: number) => {
    try {
      const r = await fetch('/api/v2/queue/retry', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: jobId }) })
      const d = await r.json()
      setActionMsg(d.ok ? `Retried #${jobId}` : `Failed: ${d.error}`)
      refetch()
      setTimeout(() => setActionMsg(null), 3000)
    } catch (e) {
      setActionMsg(`Error: ${e}`)
    }
  }, [refetch])

  const jobs = data?.jobs ?? []

  if (jobs.length === 0) {
    return (
      <Card compact>
        <div style={{ textAlign: 'center', padding: 30 }}>
          <div style={{ fontSize: 24, marginBottom: 6 }}>&#x2705;</div>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--green)' }}>All jobs healthy</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>No failed or errored jobs in the queue</div>
        </div>
      </Card>
    )
  }

  return (
    <>
      {actionMsg && (
        <div style={{ padding: '6px 12px', marginBottom: 10, borderRadius: 6, fontSize: 10,
          background: actionMsg.startsWith('Failed') ? 'var(--red-dim)' : 'var(--green-dim)',
          color: actionMsg.startsWith('Failed') ? 'var(--red)' : 'var(--green)',
        }}>{actionMsg}</div>
      )}
      <Card compact>
        <div style={{ overflow: 'auto', maxHeight: 400 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              {['Job Type', 'Symbol', 'Error', 'Attempts', 'Last Try', 'Action'].map(h => (
                <th key={h} style={TH}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {jobs.map(j => (
                <tr key={j.id}>
                  <td style={{ ...TD, color: 'var(--text1)' }}>{j.job_type.replace(/_/g, ' ')}</td>
                  <td style={{ ...TD, fontWeight: 700, color: 'var(--text0)' }}>{j.symbol || '—'}</td>
                  <td style={{ ...TD, color: 'var(--red)', fontSize: 10, maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{j.last_error || '—'}</td>
                  <td style={{ ...TDR }}>{j.attempt_count}</td>
                  <td style={{ ...TD, fontSize: 9, color: 'var(--text3)' }}>{j.queued_at ? timeAgo(j.queued_at) : '—'}</td>
                  <td style={TD}>
                    <button onClick={() => retry(j.id)} style={actionBtn}>&#x21ba; Retry</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}

/* ── Tab 5: Schedule & Controls ─────────────────────────────────────── */

function ScheduleTab() {
  const [confirmRun, setConfirmRun] = useState(false)

  const SCHEDULE = [
    { type: 'risk_synthesis', label: 'Risk Synthesis', days: [1,1,1,1,1,1,1], note: 'Nightly P0' },
    { type: 'strategy_classification', label: 'Strategy Classification', days: [1,1,1,1,1,1,1], note: 'Nightly, held+watchlist' },
    { type: 'rag_content_curation', label: 'RAG Content Curation', days: [1,1,1,1,1,1,1], note: 'Up to 20/night' },
    { type: 'closed_trade_review', label: 'Closed Trade Review', days: [1,1,1,1,1,1,1], note: 'Nightly backlog' },
    { type: 'proposal_review', label: 'Proposal Review', days: [1,1,1,1,1,1,1], note: 'Pending proposals' },
    { type: 'recovery_watch_review', label: 'Recovery Watch', days: [0,1,0,1,0,0,0], note: 'Tue/Thu only' },
    { type: 'covered_call_scoring', label: 'Covered Call Scoring', days: [0,0,0,0,0,0,1], note: 'Sunday only' },
    { type: 'weekly_behavioral_review', label: 'Behavioral Review', days: [0,0,0,0,0,0,1], note: 'Sunday, gated 20+ trades' },
    { type: 'rebalance_analysis', label: 'Rebalance Analysis', days: [2,0,0,0,0,0,0], note: 'Monthly (1st)' },
  ]
  const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

  return (
    <>
      <SectionHeader title="Weekly Schedule Grid" />
      <Card compact>
        <div style={{ overflow: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={{ ...TH, width: 180 }}>Job Type</th>
              {DAY_LABELS.map(d => <th key={d} style={{ ...TH, textAlign: 'center', width: 50 }}>{d}</th>)}
              <th style={TH}>Note</th>
            </tr></thead>
            <tbody>
              {SCHEDULE.map(s => (
                <tr key={s.type}>
                  <td style={{ ...TD, fontWeight: 600, color: 'var(--text1)' }}>{s.label}</td>
                  {s.days.map((d, i) => (
                    <td key={i} style={{ ...TD, textAlign: 'center' }}>
                      {d === 1 ? <span style={{ color: 'var(--green)', fontWeight: 700 }}>&#x2713;</span>
                        : d === 2 ? <span style={{ color: 'var(--accent)', fontSize: 9 }}>1st</span>
                        : <span style={{ color: 'var(--text3)' }}>—</span>}
                    </td>
                  ))}
                  <td style={{ ...TD, fontSize: 9, color: 'var(--text3)' }}>{s.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ display: 'flex', gap: 16, marginTop: 10, fontSize: 10, color: 'var(--text2)' }}>
          <span>Window: <strong>23:00 &rarr; 03:00</strong> nightly</span>
          <span>Model: <strong>gemma3-overnight</strong></span>
          <span>Friday extended: <strong>16:00 Fri &rarr; 03:00 Sat</strong> (11h, 400 jobs)</span>
        </div>
      </Card>

      <SectionHeader title="Manual Controls" />
      <Card>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <button onClick={() => setConfirmRun(true)} style={{
            padding: '6px 16px', fontSize: 11, fontWeight: 600,
            border: '1px solid var(--accent)', borderRadius: 'var(--radius)',
            background: 'var(--accent-dim)', color: 'var(--accent)',
            cursor: 'pointer', fontFamily: 'var(--mono)',
          }}>&#x25b6; Run Window Now</button>
        </div>
        <div style={{ marginTop: 8, fontSize: 9, color: 'var(--text3)' }}>
          Loads gemma3-overnight, evicts qwen3:14b, processes queue, restores models.
        </div>
      </Card>

      {/* Confirmation modal */}
      {confirmRun && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setConfirmRun(false)}>
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '20px 24px', width: 420 }} onClick={e => e.stopPropagation()}>
            <h3 style={{ fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 700, color: 'var(--text0)', margin: '0 0 10px' }}>Run Deep Overnight Window</h3>
            <p style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.5, margin: '0 0 12px' }}>
              This will load gemma3-overnight and evict qwen3:14b for the duration of the run. Other LLM features (classification, scoring, chat) will be unavailable during this time.
            </p>
            <div style={{ padding: '8px 10px', background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 'var(--radius)', fontSize: 10, color: 'var(--amber)', marginBottom: 16 }}>
              Manual run outside normal window. Ensure no market-hours operations depend on qwen3:14b.
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={() => setConfirmRun(false)} style={{ padding: '6px 16px', fontSize: 10, border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Cancel</button>
              <button onClick={() => setConfirmRun(false)} style={{ padding: '6px 16px', fontSize: 10, fontWeight: 700, border: '1px solid var(--amber)', borderRadius: 'var(--radius)', background: 'var(--amber-dim)', color: 'var(--amber)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Confirm &amp; Run</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

/* ── Shared styles ──────────────────────────────────────────────────── */

const selectStyle: React.CSSProperties = {
  padding: '4px 8px', fontSize: 10, fontFamily: 'var(--mono)',
  background: 'var(--bg3)', color: 'var(--text1)',
  border: '1px solid var(--border)', borderRadius: 'var(--radius)',
}

const actionBtn: React.CSSProperties = {
  padding: '2px 8px', fontSize: 9, fontFamily: 'var(--mono)',
  background: 'var(--bg3)', color: 'var(--accent)',
  border: '1px solid var(--border)', borderRadius: 'var(--radius)',
  cursor: 'pointer',
}

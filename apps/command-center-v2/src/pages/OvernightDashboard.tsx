import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import { useApi } from '../hooks/useApi'
import { timeAgo } from '../lib/format'

/*
  Overnight Intelligence Dashboard v2 — /v2/overnight
  5-second morning briefing with parsed gemma3 outputs, actionable signals,
  data quality alerts, per-ticker RAG, duplicate detection, and grade buttons.
*/

// ── Types (v2 — parsed server-side) ──────────────────────────────────────

type WindowData = {
  window_start: string | null; window_end: string | null
  done_count: number | null; failed_count: number | null
  running_count: number | null; pending_count: number | null; avg_sec: number | null
}
type JobType = { job_type: string; done: number; failed: number; pending: number; avg_sec: number | null; avg_chars: number | null }
type RiskSynth = { generated_at: string | null; narrative: string | null; top_risks: any; portfolio_value: number | null; heat_pct: number | null; narrative_chars: number | null }
type RecoveryVerdict = { queue_id: number; result_id: number; symbol: string; summary: string | null; verdict: string | null; reentry_signal: string | null; confidence: string | null; key_factor: string | null; created_at: string }
type TradeReview = { queue_id: number; result_id: number; symbol: string; trade_id: number | null; grade: string | null; outcome: string; lesson: string; risk_mgmt: string; pnl: number | null; pnl_pct: number | null; hold_days: number | null; stop_used: boolean | null; created_at: string }
type StrategyClass = { symbol: string; classification: string; recommendation: string; thesis_intact: string; evidence: string; current_strategy: string; risks: string; created_at: string }
type RagItem = { symbol: string; verdict: string | null; quality_score: number | null; summary: string | null; created_at: string }
type CoveredCall = { symbol: string; summary: string | null; verdict: string | null; strike: number | null; yield_est: number | null; created_at: string }
type OpportunityItem = { symbol: string; strategy: string; score: number | null; thesis: string; timeframe?: string; created_at: string }
type FailedJob = { id: number; job_type: string; symbol: string | null; attempt_count: number; last_error: string | null; started_at: string | null }
type CalibrationRow = { job_type: string; total_events: number; correct: number; hallucinated: number; partial: number; pending_grade: number }
type Proposal = { symbol: string; strategy_id: string | null; score: number | null; grade: string | null; entry_price: number | null; status: string; created_at: string }
type DuplicateRow = { symbol: string | null; job_type: string; cnt: number }
type DataQualityAlert = { severity: string; section: string; message: string }
type ActionableSignal = { type: string; symbol: string; detail: string }

type DashboardData = {
  generated_at: string; version: number
  window: WindowData; by_job_type: JobType[]
  risk_synthesis: RiskSynth
  recovery_verdicts: RecoveryVerdict[]; recovery_template_fallback: boolean
  trade_reviews: TradeReview[]
  strategy_classifications: StrategyClass[]
  rag_curation: RagItem[]; rag_by_ticker: Record<string, { approved: number; rejected: number; flagged: number }>
  covered_calls: CoveredCall[]
  opportunity_scan: OpportunityItem[]
  failed_jobs: FailedJob[]
  gemma3_calibration: CalibrationRow[]
  new_proposals: Proposal[]
  duplicates: DuplicateRow[]
  data_quality: DataQualityAlert[]
  actionable_signals: ActionableSignal[]
}

// ── Styles ───────────────────────────────────────────────────────────────

const btn: React.CSSProperties = { fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg1)', color: 'var(--text1)', cursor: 'pointer' }
const th: React.CSSProperties = { padding: '6px 8px', textAlign: 'left', color: '#848e9c', fontSize: 10, fontWeight: 600, borderBottom: '1px solid var(--border)' }
const td: React.CSSProperties = { padding: '6px 8px', fontSize: 11, borderBottom: '1px solid rgba(255,255,255,0.03)' }
const sevColor: Record<string, string> = { high: '#f6465d', medium: '#f0b90b', low: '#848e9c' }

function vColor(v: string | null) {
  if (!v) return '#848e9c'
  const u = v.toUpperCase()
  if (['RE_ENTER', 'BUY', 'REENTER', 'APPROVE', 'YES', 'CORRECT', 'APPROPRIATE'].some(k => u.includes(k))) return '#0ecb81'
  if (['BROKEN', 'CUT', 'REJECT', 'NO', 'HALLUCINATION', 'MISCLASSIFIED'].some(k => u.includes(k))) return '#f6465d'
  if (['NEEDS_MORE', 'WAIT', 'HOLD', 'PARTIAL', 'POTENTIALLY', 'FLAG'].some(k => u.includes(k))) return '#f0b90b'
  return '#848e9c'
}

function humanize(v?: string | null) {
  if (!v) return '-'
  return v.replace(/_/g, ' ').replace(/\b\w/g, s => s.toUpperCase())
}

function fmtTime(iso: string | null) {
  if (!iso) return '-'
  try { return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'America/New_York' }) } catch { return '-' }
}

function fmtDate(iso: string | null) {
  if (!iso) return '-'
  try { return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'America/New_York' }) } catch { return '-' }
}

function truncate(s: string | null, n: number) {
  if (!s) return '-'
  const clean = s.replace(/```json\s*/g, '').replace(/```\s*/g, '').trim()
  return clean.length > n ? clean.slice(0, n) + '...' : clean
}

function fmtPnl(v: number | null) {
  if (v == null) return '-'
  const sign = v >= 0 ? '+' : ''
  return `${sign}$${v.toFixed(0)}`
}

// ── Component ────────────────────────────────────────────────────────────

export default function OvernightDashboard() {
  const [rk, setRk] = useState(0)
  const { data, loading, error } = useApi<DashboardData>(`/api/v2/overnight-dashboard?_r=${rk}`)
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({})
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({})

  const toggle = (key: string) => setExpandedRows(prev => ({ ...prev, [key]: !prev[key] }))
  const toggleSection = (key: string) => setExpandedSections(prev => ({ ...prev, [key]: !prev[key] }))

  const retryJob = (id: number) => {
    fetch(`/api/v2/overnight-retry/${id}`, { method: 'POST' }).then(() => setRk(k => k + 1))
  }

  if (loading && !data) return <div style={{ padding: 24, color: 'var(--text2)' }}>Loading overnight data...</div>
  if (error) return <div style={{ padding: 24, color: 'var(--red)' }}>Error: {error}</div>
  if (!data) return <div style={{ padding: 24, color: 'var(--text3)' }}>No data available</div>

  const w = data.window
  const totalJobs = (w.done_count || 0) + (w.failed_count || 0) + (w.running_count || 0) + (w.pending_count || 0)
  const windowComplete = (w.running_count || 0) === 0 && (w.pending_count || 0) === 0

  return (
    <div style={{ padding: '16px 24px', maxWidth: 1200 }}>
      <PageHeader
        title="Overnight Intelligence"
        subtitle={`v${data.version || 1} · ${data.generated_at ? timeAgo(data.generated_at) : '-'}`}
        actions={<button onClick={() => setRk(k => k + 1)} style={btn}>Refresh</button>}
      />

      {/* ── DATA QUALITY ALERTS ── */}
      {data.data_quality.length > 0 && (
        <div style={{ marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {data.data_quality.map((dq, i) => (
            <div key={`dq-${i}`} style={{
              padding: '6px 12px', borderRadius: 6, fontSize: 11,
              background: dq.severity === 'high' ? 'rgba(246,70,93,0.08)' : dq.severity === 'medium' ? 'rgba(240,185,11,0.08)' : 'rgba(255,255,255,0.03)',
              border: `1px solid ${dq.severity === 'high' ? 'rgba(246,70,93,0.25)' : dq.severity === 'medium' ? 'rgba(240,185,11,0.25)' : 'rgba(255,255,255,0.06)'}`,
              color: sevColor[dq.severity] || 'var(--text2)',
            }}>
              <span style={{ fontWeight: 700, marginRight: 8 }}>{dq.severity.toUpperCase()}</span>
              <span style={{ color: 'var(--text2)' }}>{dq.message}</span>
            </div>
          ))}
        </div>
      )}

      {/* ── ACTIONABLE SIGNALS TODAY ── */}
      {data.actionable_signals.length > 0 && (
        <Card title="Actionable Signals Today" accentColor="#4a90f4" style={{ marginBottom: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={th}>Type</th><th style={th}>Symbol</th><th style={th}>Detail</th>
            </tr></thead>
            <tbody>
              {data.actionable_signals.map((a, i) => (
                <tr key={`as-${i}`}>
                  <td style={{ ...td, color: a.type === 'no_stop_alert' ? '#f6465d' : a.type === 'new_proposal' ? '#0ecb81' : '#4a90f4', fontWeight: 600 }}>
                    {a.type === 'recovery_reentry' ? 'Re-enter' : a.type === 'new_proposal' ? 'Proposal' : a.type === 'no_stop_alert' ? 'No Stop' : humanize(a.type)}
                  </td>
                  <td style={{ ...td, fontWeight: 700, color: 'var(--text0)' }}>{a.symbol}</td>
                  <td style={{ ...td, color: 'var(--text2)' }}>{a.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* ── WINDOW STATUS ── */}
      <Card style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 11, color: 'var(--text2)' }}>
              WINDOW: {fmtTime(w.window_start)} → {fmtTime(w.window_end)} ET
            </span>
            <span style={{
              fontSize: 9, padding: '2px 8px', borderRadius: 3, fontWeight: 700,
              background: windowComplete ? 'rgba(14,203,129,0.12)' : 'rgba(240,185,11,0.12)',
              color: windowComplete ? '#0ecb81' : '#f0b90b',
            }}>
              {windowComplete ? 'COMPLETED' : 'IN PROGRESS'}
            </span>
          </div>
          <div style={{ display: 'flex', gap: 16, fontSize: 11 }}>
            <span style={{ color: '#0ecb81' }}>{w.done_count || 0} done</span>
            {(w.failed_count || 0) > 0 && <span style={{ color: '#f6465d' }}>{w.failed_count} failed</span>}
            {(w.running_count || 0) > 0 && <span style={{ color: '#f0b90b' }}>{w.running_count} running</span>}
            {(w.pending_count || 0) > 0 && <span style={{ color: 'var(--text3)' }}>{w.pending_count} pending</span>}
            <span style={{ color: 'var(--text3)' }}>avg {w.avg_sec || 0}s</span>
          </div>
        </div>
        {data.by_job_type.length > 0 && (
          <div style={{ marginTop: 10, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {data.by_job_type.map(jt => (
              <span key={jt.job_type} style={{
                fontSize: 9, padding: '2px 8px', borderRadius: 3,
                background: 'rgba(255,255,255,0.04)', color: 'var(--text2)',
                border: (jt.failed || 0) > 0 ? '1px solid rgba(246,70,93,0.3)' : '1px solid rgba(255,255,255,0.06)',
              }}>
                {jt.job_type.replace(/_/g, ' ')}: {jt.done || 0}
                {(jt.failed || 0) > 0 && <span style={{ color: '#f6465d' }}> / {jt.failed}F</span>}
              </span>
            ))}
          </div>
        )}
      </Card>

      {/* ── MORNING BRIEF (Risk Synthesis) ── */}
      {data.risk_synthesis.narrative && (
        <Card title="Morning Brief" subtitle={data.risk_synthesis.generated_at ? fmtDate(data.risk_synthesis.generated_at) : ''} style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
            {expandedSections['brief'] ? data.risk_synthesis.narrative : truncate(data.risk_synthesis.narrative, 500)}
          </div>
          {(data.risk_synthesis.narrative_chars || 0) > 500 && (
            <button onClick={() => toggleSection('brief')} style={{ ...btn, marginTop: 8, fontSize: 9 }}>
              {expandedSections['brief'] ? 'Collapse' : 'Expand full narrative'}
            </button>
          )}
          {data.risk_synthesis.top_risks && Array.isArray(data.risk_synthesis.top_risks) && (
            <div style={{ marginTop: 10, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
              <div style={{ fontSize: 10, color: '#848e9c', fontWeight: 600, marginBottom: 4 }}>KEY RISKS</div>
              {data.risk_synthesis.top_risks.map((r: any, i: number) => (
                <div key={i} style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 2, paddingLeft: 8 }}>
                  - {typeof r === 'string' ? r : JSON.stringify(r)}
                </div>
              ))}
            </div>
          )}
          <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 10, color: 'var(--text3)' }}>
            {data.risk_synthesis.portfolio_value && <span>Portfolio: ${Math.round(data.risk_synthesis.portfolio_value).toLocaleString()}</span>}
            {data.risk_synthesis.heat_pct != null && <span>Heat: {Number(data.risk_synthesis.heat_pct).toFixed(1)}%</span>}
          </div>
        </Card>
      )}

      {/* ── RECOVERY WATCH VERDICTS ── */}
      {data.recovery_verdicts.length > 0 && (
        <Card title="Recovery Watch Verdicts" subtitle={`${data.recovery_verdicts.length} symbols`}
          accentColor={data.recovery_template_fallback ? '#f0b90b' : undefined} style={{ marginBottom: 12 }}>
          {data.recovery_template_fallback && (
            <div style={{ padding: '4px 10px', marginBottom: 8, borderRadius: 4, fontSize: 10, color: '#f0b90b',
              background: 'rgba(240,185,11,0.08)', border: '1px solid rgba(240,185,11,0.2)' }}>
              Template fallback detected — all {data.recovery_verdicts.length} verdicts are identical. These may not reflect real per-symbol analysis.
            </div>
          )}
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={th}>Symbol</th><th style={th}>Verdict</th><th style={th}>Re-entry</th><th style={th}>Key Factor</th><th style={th}>Time</th>
            </tr></thead>
            <tbody>
              {data.recovery_verdicts.map((rv, i) => (
                <tr key={`rv-${i}`} onClick={() => toggle(`rv-${i}`)} style={{ cursor: 'pointer', opacity: data.recovery_template_fallback ? 0.6 : 1 }}>
                  <td style={{ ...td, fontWeight: 700, color: 'var(--text0)' }}>{rv.symbol}</td>
                  <td style={{ ...td, color: vColor(rv.verdict) }}>{humanize(rv.verdict)}</td>
                  <td style={{ ...td, color: vColor(rv.reentry_signal) }}>{humanize(rv.reentry_signal)}</td>
                  <td style={{ ...td, color: 'var(--text2)', fontSize: 10 }}>{rv.key_factor || '-'}</td>
                  <td style={{ ...td, color: 'var(--text3)' }}>{fmtTime(rv.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* ── CLOSED TRADE LESSONS (parsed) ── */}
      {data.trade_reviews.length > 0 && (
        <Card title="Closed Trade Lessons" subtitle={`${data.trade_reviews.length} reviews`} style={{ marginBottom: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={th}>Symbol</th><th style={th}>P&L</th><th style={th}>Hold</th><th style={th}>Stop</th><th style={th}>Outcome</th><th style={th}>Lesson</th>
            </tr></thead>
            <tbody>
              {data.trade_reviews.map((tr, i) => (
                <tr key={`tr-${i}`} onClick={() => toggle(`tr-${i}`)} style={{ cursor: 'pointer' }}>
                  <td style={{ ...td, fontWeight: 700, color: 'var(--text0)' }}>{tr.symbol}</td>
                  <td style={{ ...td, color: tr.pnl != null ? (tr.pnl >= 0 ? '#0ecb81' : '#f6465d') : 'var(--text3)', fontWeight: 700 }}>
                    {fmtPnl(tr.pnl)}
                    {tr.pnl_pct != null && <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 3 }}>({tr.pnl_pct.toFixed(1)}%)</span>}
                  </td>
                  <td style={td}>{tr.hold_days != null ? `${tr.hold_days}d` : '-'}</td>
                  <td style={{ ...td, color: tr.stop_used === false ? '#f6465d' : tr.stop_used === true ? '#0ecb81' : 'var(--text3)' }}>
                    {tr.stop_used === false ? 'NO' : tr.stop_used === true ? 'Yes' : '-'}
                  </td>
                  <td style={{ ...td, color: 'var(--text2)', maxWidth: 200, fontSize: 10 }}>{truncate(tr.outcome, 80)}</td>
                  <td style={{ ...td, color: 'var(--text2)', maxWidth: 200, fontSize: 10 }}>{truncate(tr.lesson, 80)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* ── STRATEGY CLASSIFICATIONS (parsed) ── */}
      {data.strategy_classifications.length > 0 && (
        <Card title="Strategy Classifications" subtitle={`${data.strategy_classifications.length} positions`} style={{ marginBottom: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={th}>Symbol</th><th style={th}>Classification</th><th style={th}>Recommendation</th>
            </tr></thead>
            <tbody>
              {data.strategy_classifications.map((sc, i) => (
                <tr key={`sc-${i}`} onClick={() => toggle(`sc-${i}`)} style={{ cursor: 'pointer' }}>
                  <td style={{ ...td, fontWeight: 700, color: 'var(--text0)' }}>{sc.symbol}</td>
                  <td style={{ ...td, color: vColor(sc.classification), maxWidth: 350, fontSize: 10 }}>
                    {truncate(sc.classification, 100)}
                  </td>
                  <td style={{ ...td, color: sc.recommendation.toLowerCase().includes('flag') || sc.recommendation.toLowerCase().includes('review') ? '#f0b90b' : '#0ecb81', fontSize: 10 }}>
                    {truncate(sc.recommendation, 60)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* ── STRATEGY OPPORTUNITIES (parsed per-symbol) ── */}
      {data.opportunity_scan.length > 0 && (
        <Card title="Strategy Opportunities" subtitle={`${data.opportunity_scan.length} candidates`} style={{ marginBottom: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={th}>Symbol</th><th style={th}>Strategy</th><th style={th}>Score</th><th style={th}>Thesis</th>
            </tr></thead>
            <tbody>
              {data.opportunity_scan.map((o, i) => (
                <tr key={`os-${i}`}>
                  <td style={{ ...td, fontWeight: 700, color: 'var(--text0)' }}>{o.symbol}</td>
                  <td style={{ ...td, color: '#4a90f4' }}>{humanize(o.strategy)}</td>
                  <td style={{ ...td, fontWeight: 700, color: o.score && o.score >= 80 ? '#0ecb81' : o.score && o.score >= 60 ? '#f0b90b' : 'var(--text2)' }}>
                    {o.score ?? '-'}
                  </td>
                  <td style={{ ...td, color: 'var(--text2)', fontSize: 10, maxWidth: 400 }}>{truncate(o.thesis, 100)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* ── COVERED CALL CANDIDATES ── */}
      {data.covered_calls.length > 0 && (
        <Card title="Covered Call Candidates" subtitle={`${data.covered_calls.length} scored`} style={{ marginBottom: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={th}>Symbol</th><th style={th}>Verdict</th><th style={th}>Strike</th><th style={th}>Est. Yield</th><th style={th}>Time</th>
            </tr></thead>
            <tbody>
              {data.covered_calls.map((cc, i) => (
                <tr key={`cc-${i}`} onClick={() => toggle(`cc-${i}`)} style={{ cursor: 'pointer' }}>
                  <td style={{ ...td, fontWeight: 700, color: 'var(--text0)' }}>{cc.symbol}</td>
                  <td style={{ ...td, color: vColor(cc.verdict) }}>{humanize(cc.verdict)}</td>
                  <td style={td}>{cc.strike ? `$${Number(cc.strike).toFixed(0)}` : '-'}</td>
                  <td style={td}>{cc.yield_est ? `${Number(cc.yield_est).toFixed(2)}%` : '-'}</td>
                  <td style={{ ...td, color: 'var(--text3)' }}>{fmtTime(cc.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* ── RAG CURATION (per-ticker breakdown) ── */}
      {data.rag_curation.length > 0 && (
        <Card title="RAG Curation Results" subtitle={`${data.rag_curation.length} articles`} style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
            {Object.entries(data.rag_by_ticker || {}).map(([sym, counts]) => (
              <span key={sym} style={{
                fontSize: 9, padding: '2px 8px', borderRadius: 3,
                background: 'rgba(255,255,255,0.04)', color: 'var(--text2)',
                border: `1px solid ${counts.rejected > 0 ? 'rgba(246,70,93,0.3)' : 'rgba(255,255,255,0.06)'}`,
              }}>
                {sym}: <span style={{ color: '#0ecb81' }}>{counts.approved}</span>
                {counts.flagged > 0 && <span style={{ color: '#f0b90b' }}>/{counts.flagged}F</span>}
                {counts.rejected > 0 && <span style={{ color: '#f6465d' }}>/{counts.rejected}R</span>}
              </span>
            ))}
          </div>
          {expandedSections['rag'] && (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr>
                <th style={th}>Symbol</th><th style={th}>Verdict</th><th style={th}>Weight</th><th style={th}>Time</th>
              </tr></thead>
              <tbody>
                {data.rag_curation.map((r, i) => (
                  <tr key={`rag-${i}`}>
                    <td style={{ ...td, fontWeight: 700, color: 'var(--text0)' }}>{r.symbol}</td>
                    <td style={{ ...td, color: vColor(r.verdict) }}>{humanize(r.verdict)}</td>
                    <td style={td}>{r.quality_score != null ? Number(r.quality_score).toFixed(2) : '-'}</td>
                    <td style={{ ...td, color: 'var(--text3)' }}>{fmtTime(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <button onClick={() => toggleSection('rag')} style={{ ...btn, fontSize: 9, marginTop: 4 }}>
            {expandedSections['rag'] ? 'Collapse' : 'Show all articles'}
          </button>
        </Card>
      )}

      {/* ── NEW PROPOSALS OVERNIGHT ── */}
      {data.new_proposals.length > 0 && (
        <Card title="New Proposals Overnight" subtitle={`${data.new_proposals.length} proposals`} style={{ marginBottom: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={th}>Symbol</th><th style={th}>Strategy</th><th style={th}>Score</th><th style={th}>Grade</th><th style={th}>Entry</th><th style={th}>Status</th>
            </tr></thead>
            <tbody>
              {data.new_proposals.map((p, i) => (
                <tr key={`p-${i}`}>
                  <td style={{ ...td, fontWeight: 700, color: 'var(--text0)' }}>{p.symbol}</td>
                  <td style={{ ...td, color: 'var(--text2)' }}>{humanize(p.strategy_id)}</td>
                  <td style={td}>{p.score != null ? Number(p.score).toFixed(0) : '-'}</td>
                  <td style={{ ...td, color: vColor(p.grade), fontWeight: 700 }}>{p.grade || '-'}</td>
                  <td style={td}>{p.entry_price ? `$${Number(p.entry_price).toFixed(2)}` : '-'}</td>
                  <td style={{ ...td, color: 'var(--text3)' }}>{humanize(p.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* ── DUPLICATES ── */}
      {data.duplicates.length > 0 && (
        <Card title="Duplicate Results" subtitle={`${data.duplicates.length} groups`} style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {data.duplicates.map((d, i) => (
              <span key={`dup-${i}`} style={{
                fontSize: 9, padding: '2px 8px', borderRadius: 3,
                background: d.cnt > 3 ? 'rgba(246,70,93,0.08)' : 'rgba(255,255,255,0.04)',
                color: d.cnt > 3 ? '#f6465d' : 'var(--text2)',
                border: `1px solid ${d.cnt > 3 ? 'rgba(246,70,93,0.3)' : 'rgba(255,255,255,0.06)'}`,
              }}>
                {d.symbol || '(blank)'} / {d.job_type.replace(/_/g, ' ')}: {d.cnt}x
              </span>
            ))}
          </div>
        </Card>
      )}

      {/* ── FAILED JOBS (with retry) ── */}
      {data.failed_jobs.length > 0 && (
        <Card title="Failed Jobs" subtitle={`${data.failed_jobs.length} failures`} accentColor="#f6465d" style={{ marginBottom: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={th}>Job Type</th><th style={th}>Symbol</th><th style={th}>Attempts</th><th style={th}>Error</th><th style={th}></th>
            </tr></thead>
            <tbody>
              {data.failed_jobs.map((fj, i) => (
                <tr key={`fj-${i}`}>
                  <td style={{ ...td, color: 'var(--text2)' }}>{fj.job_type.replace(/_/g, ' ')}</td>
                  <td style={{ ...td, fontWeight: 700, color: 'var(--text0)' }}>{fj.symbol || '-'}</td>
                  <td style={td}>{fj.attempt_count}</td>
                  <td style={{ ...td, color: '#f6465d', fontSize: 10, maxWidth: 300 }}>{truncate(fj.last_error, 100)}</td>
                  <td style={td}>
                    <button onClick={(e) => { e.stopPropagation(); retryJob(fj.id) }}
                      style={{ ...btn, fontSize: 9, padding: '2px 8px', color: '#4a90f4', borderColor: 'rgba(74,144,244,0.3)' }}>
                      Retry
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* ── GEMMA3 CALIBRATION (7-day) ── */}
      {data.gemma3_calibration.length > 0 && (
        <Card title="Gemma3 Calibration" subtitle="7-day rolling" style={{ marginBottom: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={th}>Job Type</th><th style={th}>Correct</th><th style={th}>Hallucinated</th><th style={th}>Partial</th><th style={th}>Pending</th><th style={th}>Accuracy</th>
            </tr></thead>
            <tbody>
              {data.gemma3_calibration.map((c, i) => {
                const graded = c.correct + c.hallucinated + c.partial
                const accuracy = graded > 0 ? ((c.correct / graded) * 100).toFixed(0) : '-'
                return (
                  <tr key={`cal-${i}`}>
                    <td style={{ ...td, color: 'var(--text2)' }}>{c.job_type.replace(/_/g, ' ')}</td>
                    <td style={{ ...td, color: '#0ecb81' }}>{c.correct}</td>
                    <td style={{ ...td, color: c.hallucinated > 0 ? '#f6465d' : 'var(--text3)' }}>{c.hallucinated}</td>
                    <td style={{ ...td, color: c.partial > 0 ? '#f0b90b' : 'var(--text3)' }}>{c.partial}</td>
                    <td style={{ ...td, color: 'var(--text3)' }}>{c.pending_grade}</td>
                    <td style={{ ...td, fontWeight: 700, color: accuracy !== '-' ? (Number(accuracy) >= 90 ? '#0ecb81' : Number(accuracy) >= 70 ? '#f0b90b' : '#f6465d') : 'var(--text3)' }}>
                      {accuracy}{accuracy !== '-' ? '%' : ''}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {(() => {
            const totalPending = data.gemma3_calibration.reduce((s, c) => s + c.pending_grade, 0)
            return totalPending > 0 ? <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 6 }}>Pending grading: {totalPending}</div> : null
          })()}
        </Card>
      )}

      {/* ── Empty state ── */}
      {totalJobs === 0 && !data.risk_synthesis.narrative && (
        <Card style={{ marginTop: 20 }}>
          <div style={{ textAlign: 'center', padding: 40, color: 'var(--text3)' }}>
            <div style={{ fontSize: 14, marginBottom: 8 }}>No overnight data in the last 24 hours</div>
            <div style={{ fontSize: 11 }}>The overnight window typically runs 23:00 - 03:00 ET</div>
          </div>
        </Card>
      )}
    </div>
  )
}

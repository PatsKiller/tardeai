import { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import ImportModal from '../components/ImportModal'
import { useApi } from '../hooks/useApi'
import { timeAgo } from '../lib/format'

interface AuditData {
  recent_runs: { name: string; size_kb: number; modified: string; last_line: string; success: boolean }[]
  recent_imports: { timestamp?: string; import_type?: string; filename?: string; account?: string; rows_received?: number; status?: string; message?: string; raw?: string }[]
  recovery_log: string[]
}

const ACTIONS = [
  { id: 'daily', label: 'Run Daily Pipeline', endpoint: '/api/run-portfolio', desc: 'Full daily pipeline — reprice, compute signals, update snapshots, generate reports.', icon: '\u25b6', color: 'var(--green)', output: 'Portfolio daily report + Trade AI dashboard in Reports', dest: '/reports' },
  { id: 'reprice', label: 'Run Reprice Only', endpoint: '/api/run-reprice', desc: 'Refresh current prices without running full pipeline. Fast (~30s).', icon: '\u27f3', color: 'var(--accent)', output: 'Updated Holdings, Risk, and Returns data', dest: '/portfolio' },
  { id: 'tradeai', label: 'Run Trade AI Scan', endpoint: '/api/run-trade-ai', desc: 'Scalp screener — scan for GO/WAIT/AVOID setups. Takes 5-7 minutes.', icon: '\u26a1', color: 'var(--amber)', output: 'Trade AI dashboard in Reports + updated Trade AI page', dest: '/trade-ai' },
  { id: 'recovery', label: 'Run Recovery Review', endpoint: '/api/run-recovery-review', desc: 'Stop-out detection, analyst review, stop confirmation reminders, allocation advisor.', icon: '\u{1f6e1}', color: 'var(--accent)', output: 'Updated Recovery Watch page + Telegram notifications', dest: '/recovery' },
  { id: 'aegis', label: 'Run Aegis Surveillance', endpoint: '/api/run-aegis', desc: 'Aegis portfolio surveillance — concentration, stops, income, risk posture analysis.', icon: '\u{1f6e1}', color: 'var(--purple)', output: 'Aegis findings in Approvals + Recovery + Orchestration', dest: '/orchestration' },
  { id: 'rebalance', label: 'Run Rebalance', endpoint: '/api/run-pipeline', desc: 'Rebalance analysis — concentration, income architecture, YAML health.', icon: '\u2696', color: 'var(--text1)', output: 'Updated Rebalance page with observations + suggestions', dest: '/rebalance' },
]

export default function ActionCenter() {
  const navigate = useNavigate()
  const { data: audit } = useApi<AuditData>('/api/v2/ops/audit')
  const [showImport, setShowImport] = useState(false)
  const [running, setRunning] = useState<string | null>(null)
  const [runState, setRunState] = useState<'idle' | 'started' | 'polling' | 'completed' | 'failed'>('idle')
  const [result, setResult] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<typeof ACTIONS[0] | null>(null)
  const [auditRefresh, setAuditRefresh] = useState(0)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Refresh audit data when auditRefresh changes
  const { data: freshAudit } = useApi<AuditData>(`/api/v2/ops/audit?_r=${auditRefresh}`)
  const auditData = freshAudit || audit

  // Map action IDs to latest audit run
  const lastRuns: Record<string, { time: string; success: boolean; line: string }> = {}
  for (const r of (auditData?.recent_runs || []).slice(0, 20)) {
    const name = r.name.toLowerCase()
    if (name.includes('portfolio') && !name.includes('reprice') && !lastRuns['daily']) lastRuns['daily'] = { time: r.modified, success: r.success, line: r.last_line }
    if (name.includes('reprice') && !lastRuns['reprice']) lastRuns['reprice'] = { time: r.modified, success: r.success, line: r.last_line }
    if (name.includes('continuous') && !lastRuns['tradeai']) lastRuns['tradeai'] = { time: r.modified, success: r.success, line: r.last_line }
  }
  const recoveryLine = (auditData?.recovery_log || []).find(l => l.includes('Complete'))
  if (recoveryLine) lastRuns['recovery'] = { time: new Date().toISOString(), success: true, line: 'Complete' }

  // Stop polling on unmount
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current) }, [])

  const execute = useCallback(async (action: typeof ACTIONS[0]) => {
    setConfirm(null)
    setRunning(action.id)
    setRunState('started')
    setResult(null)
    try {
      const body = action.id === 'rebalance' ? JSON.stringify({ pipeline: 'daily' }) : '{}'
      const resp = await fetch(action.endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body })
      const data = await resp.json().catch(() => ({}))
      if (data.ok !== false) {
        setResult(`${action.label} started — polling for completion...`)
        setRunState('polling')
        // Poll audit endpoint every 8s to detect completion
        let polls = 0
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = setInterval(() => {
          polls++
          setAuditRefresh(Date.now())
          if (polls >= 15) { // Stop after ~2 min
            if (pollRef.current) clearInterval(pollRef.current)
            setRunState('completed')
            setResult(`${action.label} — check audit log for result`)
            setRunning(null)
          }
        }, 8000)
        // Also do a quick refresh after 3s
        setTimeout(() => setAuditRefresh(Date.now()), 3000)
      } else {
        setResult(`Failed: ${data.error || 'unknown'}`)
        setRunState('failed')
        setRunning(null)
      }
    } catch (e) {
      setResult(`Failed: ${e}`)
      setRunState('failed')
      setRunning(null)
    }
  }, [])

  return (
    <>
      {showImport && <ImportModal onClose={() => setShowImport(false)} />}

      <PageHeader title="Action Center" subtitle="Pipeline execution and imports — runtime ~5-8 min. Do not run multiple simultaneously. Updates all accounts." actions={
        <button onClick={() => navigate('/reports')} style={{ padding: '3px 10px', fontSize: 10, border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>View Reports</button>
      } />

      {/* Quick nav — what to do next */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 14, flexWrap: 'wrap' }}>
        <button onClick={() => navigate('/approvals')} style={quickNavStyle}>Review Approvals</button>
        <button onClick={() => navigate('/recovery')} style={quickNavStyle}>Recovery Watch</button>
        <button onClick={() => navigate('/risk')} style={quickNavStyle}>Risk Manager</button>
        <button onClick={() => navigate('/journal-analytics')} style={quickNavStyle}>Journal Analytics</button>
        <button onClick={() => navigate('/ops')} style={quickNavStyle}>Ops / Audit</button>
        <button onClick={() => navigate('/orchestration')} style={quickNavStyle}>Orchestration</button>
      </div>

      {/* Pending tasks banner */}
      <PendingTasksBanner />

      {/* Pipeline actions */}
      <SectionHeader title="Pipeline Execution" count={ACTIONS.length} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10, marginBottom: 14 }}>
        {ACTIONS.map(a => (
          <button key={a.id} onClick={() => setConfirm(a)} disabled={running !== null}
            style={{
              padding: '14px 16px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
              background: 'var(--bg-card)', cursor: running ? 'wait' : 'pointer', textAlign: 'left',
              opacity: running && running !== a.id ? 0.5 : 1, transition: 'all var(--transition)',
            }}
            onMouseEnter={e => { if (!running) (e.currentTarget as HTMLElement).style.borderColor = a.color }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span style={{ fontSize: 18 }}>{a.icon}</span>
              <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>
                {running === a.id ? 'Running...' : a.label}
              </span>
            </div>
            <div style={{ fontSize: 9, color: 'var(--text3)', lineHeight: 1.4 }}>{a.desc}</div>
            <div style={{ display: 'flex', gap: 6, marginTop: 4, alignItems: 'center' }}>
              {a.output && <span style={{ fontSize: 8, color: 'var(--text3)', opacity: 0.7, flex: 1 }}>Output: {a.output}</span>}
              {a.dest && <button onClick={(e) => { e.stopPropagation(); navigate(a.dest!) }} style={{ fontSize: 8, padding: '2px 6px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--accent)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>View</button>}
            </div>
            {lastRuns[a.id] && (
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 8 }}>
                <span style={{ fontWeight: 700, padding: '0px 4px', borderRadius: 2, background: lastRuns[a.id].success ? 'var(--green-dim)' : 'var(--red-dim)', color: lastRuns[a.id].success ? 'var(--green)' : 'var(--red)' }}>{lastRuns[a.id].success ? 'OK' : 'ERR'}</span>
                <span style={{ color: 'var(--text3)' }}>Last: {timeAgo(lastRuns[a.id].time)}</span>
              </div>
            )}
          </button>
        ))}
      </div>

      {result && (
        <div style={{ padding: '8px 12px', borderRadius: 'var(--radius)', marginBottom: 12,
          background: runState === 'failed' ? 'var(--red-dim)' : runState === 'polling' ? 'var(--accent-dim)' : 'var(--green-dim)',
          border: `1px solid ${runState === 'failed' ? 'var(--red)' : runState === 'polling' ? 'var(--accent)' : 'var(--green)'}`,
        }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 10, fontWeight: 600, color: runState === 'failed' ? 'var(--red)' : runState === 'polling' ? 'var(--accent)' : 'var(--green)' }}>
            {runState === 'polling' && <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: 'var(--accent)' }} />}
            {result}
            {runState === 'polling' && (
              <button onClick={() => { if (pollRef.current) clearInterval(pollRef.current); setRunState('completed'); setRunning(null); setResult('Stopped polling — check audit log'); setAuditRefresh(Date.now()) }}
                style={{ marginLeft: 'auto', fontSize: 9, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>
                Stop polling
              </button>
            )}
          </div>
          {runState !== 'polling' && runState !== 'failed' && running && (
            <div style={{ fontSize: 9, color: 'var(--text2)', marginTop: 4 }}>
              Next: check {ACTIONS.find(a => a.id === running)?.output || 'audit log'} for results
            </div>
          )}
        </div>
      )}

      {/* Import Center */}
      <SectionHeader title="Import Center" />
      <Card>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 10 }}>
          <button onClick={() => setShowImport(true)} style={{
            padding: '8px 20px', fontSize: 11, fontWeight: 600,
            border: '1px solid var(--accent)', borderRadius: 'var(--radius)',
            background: 'var(--accent-dim)', color: 'var(--accent)',
            cursor: 'pointer', fontFamily: 'var(--mono)',
          }}>Open Import Wizard</button>
          <span style={{ fontSize: 10, color: 'var(--text3)' }}>Upload positions or transactions from Schwab / Fidelity CSV exports</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
          <div style={{ padding: '6px 10px', background: 'var(--bg3)', borderRadius: 'var(--radius)', fontSize: 10 }}>
            <div style={{ fontWeight: 600, color: 'var(--text0)' }}>Schwab Positions</div>
            <div style={{ color: 'var(--text3)', fontSize: 9 }}>Replaces account holdings from CSV export</div>
          </div>
          <div style={{ padding: '6px 10px', background: 'var(--bg3)', borderRadius: 'var(--radius)', fontSize: 10 }}>
            <div style={{ fontWeight: 600, color: 'var(--text0)' }}>Schwab Transactions</div>
            <div style={{ color: 'var(--text3)', fontSize: 9 }}>Appends new trades to journal</div>
          </div>
          <div style={{ padding: '6px 10px', background: 'var(--bg3)', borderRadius: 'var(--radius)', fontSize: 10 }}>
            <div style={{ fontWeight: 600, color: 'var(--text0)' }}>Fidelity Positions</div>
            <div style={{ color: 'var(--text3)', fontSize: 9 }}>Replaces 401k holdings from CSV export</div>
          </div>
        </div>
      </Card>

      {/* Recent activity */}
      {audit && (
        <>
          {(audit.recent_runs?.length ?? 0) > 0 && (
            <>
              <SectionHeader title="Recent Runs" count={audit.recent_runs.length} />
              <Card compact>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {audit.recent_runs.slice(0, 6).map((r, i) => (
                    <div key={i} style={{ display: 'flex', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, alignItems: 'center' }}>
                      <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: r.success ? 'var(--green-dim)' : 'var(--red-dim)', color: r.success ? 'var(--green)' : 'var(--red)' }}>{r.success ? 'OK' : 'ERR'}</span>
                      <span style={{ fontWeight: 600, color: 'var(--text0)', width: 160 }}>{r.name}</span>
                      <span style={{ color: 'var(--text3)' }}>{timeAgo(r.modified)}</span>
                      <span style={{ flex: 1, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 9 }}>{r.last_line}</span>
                    </div>
                  ))}
                </div>
              </Card>
            </>
          )}

          {(audit.recent_imports?.length ?? 0) > 0 && (
            <>
              <SectionHeader title="Recent Imports" count={audit.recent_imports.length} />
              <Card compact>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {audit.recent_imports.slice(0, 4).map((imp, i) => (
                    <div key={i} style={{ display: 'flex', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, alignItems: 'center' }}>
                      {imp.raw ? (
                        <span style={{ color: 'var(--text2)', fontFamily: 'var(--mono)', fontSize: 9 }}>{imp.raw}</span>
                      ) : (
                        <>
                          <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: imp.status === 'success' ? 'var(--green-dim)' : 'var(--red-dim)', color: imp.status === 'success' ? 'var(--green)' : 'var(--red)' }}>{imp.status?.toUpperCase()}</span>
                          <span style={{ fontWeight: 600, color: 'var(--text0)' }}>{imp.import_type || '—'}</span>
                          {imp.rows_received != null && <span>{imp.rows_received} rows</span>}
                          {imp.timestamp && <span style={{ color: 'var(--text3)' }}>{timeAgo(imp.timestamp)}</span>}
                        </>
                      )}
                    </div>
                  ))}
                </div>
              </Card>
            </>
          )}
        </>
      )}

      {/* Confirmation modal */}
      {confirm && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setConfirm(null)}>
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '20px 24px', width: 400 }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <span style={{ fontSize: 20 }}>{confirm.icon}</span>
              <h3 style={{ fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 700, color: 'var(--text0)', margin: 0 }}>{confirm.label}</h3>
            </div>
            <p style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.5, margin: '0 0 16px' }}>{confirm.desc}</p>
            <div style={{ padding: '8px 10px', background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 'var(--radius)', fontSize: 10, color: 'var(--amber)', marginBottom: 16 }}>
              This triggers a live pipeline run. Results appear in the audit log below.
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={() => setConfirm(null)} style={{ padding: '6px 16px', fontSize: 10, border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Cancel</button>
              <button onClick={() => execute(confirm)} style={{ padding: '6px 16px', fontSize: 10, fontWeight: 700, border: `1px solid ${confirm.color}`, borderRadius: 'var(--radius)', background: `color-mix(in srgb, ${confirm.color} 10%, transparent)`, color: confirm.color, cursor: 'pointer', fontFamily: 'var(--mono)' }}>Confirm &amp; Run</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

const quickNavStyle: React.CSSProperties = { padding: '5px 12px', fontSize: 10, border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg-card)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--mono)', transition: 'border-color var(--transition)' }

function PendingTasksBanner() {
  const navigate = useNavigate()
  const { data } = useApi<{ count: number; urgent: number; pending: number; failed_automation: number }>('/api/v2/tasks')
  if (!data || data.count === 0) return null
  return (
    <div style={{ display: 'flex', gap: 10, marginBottom: 14, padding: '10px 14px', background: 'var(--bg-card)', border: `1px solid ${data.urgent > 0 ? 'var(--red)' : 'var(--amber)'}`, borderRadius: 'var(--radius-md)', borderLeft: `4px solid ${data.urgent > 0 ? 'var(--red)' : 'var(--amber)'}`, alignItems: 'center', cursor: 'pointer' }} onClick={() => navigate('/approvals')}>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', fontFamily: 'var(--sans)' }}>
          {data.pending} pending task{data.pending !== 1 ? 's' : ''}{data.urgent > 0 ? ` (${data.urgent} urgent)` : ''}
        </div>
        {data.failed_automation > 0 && (
          <div style={{ fontSize: 10, color: 'var(--red)', marginTop: 2 }}>{data.failed_automation} failed automation review{data.failed_automation !== 1 ? 's' : ''} need manual decision</div>
        )}
      </div>
      <button onClick={e => { e.stopPropagation(); navigate('/approvals') }} style={{ padding: '5px 14px', fontSize: 10, fontWeight: 700, border: '1px solid var(--amber)', borderRadius: 'var(--radius)', background: 'var(--amber-dim)', color: 'var(--amber)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Review Tasks</button>
    </div>
  )
}

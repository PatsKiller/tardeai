import { useState, useCallback } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import ImportModal from '../components/ImportModal'
import AdminModal from '../components/AdminModals'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import { useApi } from '../hooks/useApi'
import { useFetch } from '../hooks/useFetch'
import { timeAgo } from '../lib/format'

interface AuditData {
  recent_runs: { name: string; size_kb: number; modified: string; last_line: string; success: boolean }[]
  recent_imports: ({ timestamp?: string; type?: string; import_type?: string; filename?: string; account?: string; rows_received?: number; rows_accepted?: number; status?: string; message?: string; raw?: string; before?: { positions: number; total_value: number }; after?: { positions: number; total_value: number }; delta_value?: number })[]
  recent_notifications: { notification_type: string; channel: string; subject: string; status: string; sent_at: string }[]
  recovery_log: string[]
}

interface OpsData {
  pipeline: { status: string; completed_at: string; duration_seconds: number; steps: number; run_type: string; holdings_hash: string; run_id: string }
  database: { table_count: number; total_rows: number; tables: { name: string; live_rows: number; dead_rows: number; size: string; last_autovacuum: string | null; last_autoanalyze: string | null }[] }
}

export default function Ops() {
  const [showImport, setShowImport] = useState(false)
  const [adminModal, setAdminModal] = useState<'personal' | 'yaml' | 'env' | 'settings' | null>(null)
  const { data: ops } = useApi<OpsData>('/api/v2/ops/summary')
  const { data: audit } = useApi<AuditData>('/api/v2/ops/audit')
  // Fallback for dead_rows/vacuum not in v2 yet — use legacy for full detail
  const { data: healthLegacy } = useFetch<{ tables: { name: string; live_rows: number; dead_rows: number; size: string; last_autovacuum: string | null; last_autoanalyze: string | null }[] }>('/api/db/health')

  const fresh = ops?.pipeline
  const tables = healthLegacy?.tables ?? ops?.database?.tables ?? []

  const pipeAge = fresh?.completed_at ? timeAgo(fresh.completed_at) : '—'
  const pipeOk = fresh?.status === 'fresh'
  const totalRows = tables.reduce((s, t) => s + (t.live_rows || 0), 0)
  const deadRows = tables.reduce((s, t) => s + (t.dead_rows || 0), 0)

  return (
    <>
      {showImport && <ImportModal onClose={() => setShowImport(false)} />}
      {adminModal && <AdminModal type={adminModal} onClose={() => setAdminModal(null)} />}
      <PageHeader title="Operations" subtitle="Pipeline health, database, and infrastructure. Import CSV: Fidelity Position Export format. Dead rows >10K = check autovacuum." actions={
        <button onClick={() => setShowImport(true)} style={{ padding: '3px 10px', fontSize: 10, border: '1px solid var(--accent)', borderRadius: 'var(--radius)', background: 'var(--accent-dim)', color: 'var(--accent)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Import CSV</button>
      } />

      {/* Pipeline status */}
      <SectionHeader title="Pipeline" />
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        <MetricTile label="Status" value={fresh?.status ?? '—'} deltaColor={pipeOk ? 'var(--green)' : 'var(--red)'} />
        <MetricTile label="Last Run" value={pipeAge} />
        <MetricTile label="Duration" value={fresh?.duration_seconds ? `${fresh.duration_seconds.toFixed(0)}s` : '—'} />
        <MetricTile label="Steps" value={String(fresh?.steps ?? '—')} />
        <MetricTile label="Run Type" value={fresh?.run_type ?? '—'} />
        <MetricTile label="Holdings Hash" value={fresh?.holdings_hash?.slice(0, 8) ?? '—'} />
      </div>

      {fresh && (
        <Card title="Pipeline Detail" subtitle={`Run ID: ${fresh.run_id || '—'}`}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, fontSize: 11 }}>
            <div><span style={{ color: 'var(--text3)', fontSize: 9 }}>Completed</span><div style={{ color: 'var(--text0)' }}>{fresh.completed_at?.slice(0, 19)}</div></div>
            <div><span style={{ color: 'var(--text3)', fontSize: 9 }}>Run Type</span><div style={{ color: 'var(--text0)' }}>{fresh.run_type}</div></div>
            <div><span style={{ color: 'var(--text3)', fontSize: 9 }}>Full Hash</span><div style={{ color: 'var(--text2)' }}>{fresh.holdings_hash}</div></div>
          </div>
        </Card>
      )}

      {/* Pipeline triggers */}
      <PipelineTriggers />

      {/* Database health */}
      <SectionHeader title="Database" count={tables.length} />
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        <MetricTile label="Tables" value={String(tables.length)} />
        <MetricTile label="Total Rows" value={totalRows.toLocaleString()} />
        <MetricTile label="Dead Rows" value={deadRows.toLocaleString()} deltaColor={deadRows > 1000 ? 'var(--amber)' : 'var(--text2)'} />
        <MetricTile label="Status" value={ops?.pipeline?.status ?? '—'} />
      </div>

      <Card title="Table Inventory">
        <div style={{ overflow: 'auto', maxHeight: 350 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ position: 'sticky', top: 0, background: 'var(--bg1)' }}>
                {['Table', 'Rows', 'Dead', 'Size', 'Last Vacuum', 'Last Analyze'].map(h => (
                  <th key={h} style={{ padding: '5px 8px', textAlign: h === 'Table' ? 'left' : 'right', color: 'var(--text3)', fontSize: 10, fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tables.map(t => (
                <tr key={t.name}>
                  <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', color: 'var(--text1)' }}>{t.name}</td>
                  <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', textAlign: 'right', color: 'var(--text0)', fontWeight: 600 }}>{t.live_rows.toLocaleString()}</td>
                  <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', textAlign: 'right', color: t.dead_rows > 100 ? 'var(--amber)' : 'var(--text3)' }}>{t.dead_rows}</td>
                  <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', textAlign: 'right', color: 'var(--text2)' }}>{t.size}</td>
                  <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', textAlign: 'right', fontSize: 9, color: 'var(--text3)' }}>{t.last_autovacuum?.slice(0, 16) || '—'}</td>
                  <td style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', textAlign: 'right', fontSize: 9, color: 'var(--text3)' }}>{t.last_autoanalyze?.slice(0, 16) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Backup status */}
      <SectionHeader title="Backups" />
      <Card title="Backup Inventory" subtitle="Read from filesystem">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 11 }}>
          <div>
            <div style={{ color: 'var(--text3)', fontSize: 9 }}>Fresh Validated Set</div>
            <div style={{ color: 'var(--green)' }}>backups/fresh_20260421_162922/</div>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>Git bundle + OpenClaw archive + DB dump (19 tables)</div>
          </div>
          <div>
            <div style={{ color: 'var(--text3)', fontSize: 9 }}>Automated Daily pg_dump</div>
            <div style={{ color: 'var(--text1)' }}>db_backups/trade_ai_*.sql.gz</div>
            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>Timer: daily 02:00, 30-day retention</div>
          </div>
        </div>
      </Card>

      {/* Action Audit Trail */}
      {audit && (
        <>
          {(audit.recent_runs?.length ?? 0) > 0 && (
            <>
              <SectionHeader title="Recent Pipeline Runs" count={audit.recent_runs.length} />
              <Card compact>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {audit.recent_runs.map((r, i) => (
                    <div key={i} style={{ display: 'flex', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, alignItems: 'center' }}>
                      <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: r.success ? 'var(--green-dim)' : 'var(--red-dim)', color: r.success ? 'var(--green)' : 'var(--red)' }}>{r.success ? 'OK' : 'ERR'}</span>
                      <span style={{ fontWeight: 600, color: 'var(--text0)', width: 160 }}>{r.name}</span>
                      <span style={{ color: 'var(--text3)' }}>{r.size_kb} KB</span>
                      <span style={{ color: 'var(--text3)' }}>{timeAgo(r.modified)}</span>
                      <span style={{ flex: 1, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.last_line}</span>
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
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {audit.recent_imports.map((imp, i) => imp.raw ? (
                    <div key={i} style={{ fontSize: 9, color: 'var(--text2)', padding: '2px 0', borderBottom: '1px solid var(--border-subtle)', fontFamily: 'var(--mono)' }}>{imp.raw}</div>
                  ) : (
                    <div key={i} style={{ display: 'flex', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, alignItems: 'center' }}>
                      <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: imp.status === 'success' ? 'var(--green-dim)' : 'var(--red-dim)', color: imp.status === 'success' ? 'var(--green)' : 'var(--red)' }}>{imp.status?.toUpperCase()}</span>
                      <span style={{ fontWeight: 600, color: 'var(--text0)' }}>{imp.import_type || imp.type || '—'}</span>
                      {imp.filename && <span style={{ color: 'var(--text2)', fontFamily: 'var(--mono)', fontSize: 9 }}>{imp.filename}</span>}
                      {imp.account && <span style={{ color: 'var(--text3)' }}>{imp.account}</span>}
                      {imp.rows_received != null && <span style={{ color: 'var(--text1)' }}>{imp.rows_received} rows</span>}
                      {imp.before && imp.after && <span style={{ color: imp.delta_value && imp.delta_value > 0 ? 'var(--green)' : 'var(--text2)' }}>{imp.before.positions}→{imp.after.positions} pos</span>}
                      {imp.message && <span style={{ color: 'var(--text2)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{imp.message}</span>}
                      {imp.timestamp && <span style={{ color: 'var(--text3)', fontSize: 9 }}>{timeAgo(imp.timestamp)}</span>}
                    </div>
                  ))}
                </div>
              </Card>
            </>
          )}

          {(audit.recovery_log?.length ?? 0) > 0 && (
            <>
              <SectionHeader title="Recovery Watch Log" count={audit.recovery_log.length} />
              <Card compact>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  {audit.recovery_log.map((line, i) => (
                    <div key={i} style={{ fontSize: 9, color: line.includes('Complete') ? 'var(--green)' : line.includes('Starting') ? 'var(--accent)' : 'var(--text2)', padding: '1px 0', fontFamily: 'var(--mono)' }}>{line}</div>
                  ))}
                </div>
              </Card>
            </>
          )}
        </>
      )}

      {/* LLM Routing Audit */}
      <LLMRoutingAudit />

      {/* Cron Health Grid */}
      <CronHealth />

      {/* John Decision Audit Trail */}
      <DecisionAuditTrail />

      {/* Admin utilities — not primary analyst nav */}
      <SectionHeader title="Admin Utilities" />
      <Card compact>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {([['personal', '\u{1f464} Personal Situation'], ['yaml', '\u2699 YAML Config'], ['env', '\u{1f511} ENV Keys'], ['settings', '\u{1f4ca} System Info']] as [string, string][]).map(([key, label]) => (
            <button key={key} onClick={() => setAdminModal(key as 'personal' | 'yaml' | 'env' | 'settings')} style={{
              padding: '5px 12px', fontSize: 10, border: '1px solid var(--border)', borderRadius: 'var(--radius)',
              background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)',
            }}>{label}</button>
          ))}
        </div>
      </Card>
    </>
  )
}


function PipelineTriggers() {
  const [running, setRunning] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<{ label: string; endpoint: string; desc: string } | null>(null)

  const trigger = useCallback(async (endpoint: string, label: string) => {
    setConfirm(null)
    setRunning(label)
    setResult(null)
    try {
      const resp = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const data = await resp.json().catch(() => ({}))
      setResult(data.ok !== false ? `${label} started` : `${label} failed: ${data.error || 'unknown'}`)
    } catch (e) {
      setResult(`${label} failed: ${e}`)
    } finally {
      setRunning(null)
    }
  }, [])

  const btns = [
    { label: 'Run Portfolio', endpoint: '/api/run-portfolio', desc: 'Full daily pipeline — reprices, computes signals, updates snapshots' },
    { label: 'Run Reprice', endpoint: '/api/run-reprice', desc: 'Price refresh only — updates current prices without full pipeline' },
    { label: 'Run Trade AI', endpoint: '/api/run-pipeline', desc: 'Scalp screener — scans for GO/WAIT/AVOID setups' },
    { label: 'Run Rebalance', endpoint: '/api/run-pipeline', desc: 'Rebalance analysis — concentration, income architecture' },
  ]

  return (
    <>
      <SectionHeader title="Pipeline Controls" />
      <Card>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          {btns.map(b => (
            <button
              key={b.label}
              onClick={() => setConfirm(b)}
              disabled={running !== null}
              style={{
                padding: '6px 16px', fontSize: 11, fontWeight: 600,
                border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                background: running === b.label ? 'var(--accent-dim)' : 'var(--bg3)',
                color: running === b.label ? 'var(--accent)' : 'var(--text1)',
                cursor: running ? 'wait' : 'pointer', fontFamily: 'var(--mono)',
                opacity: running && running !== b.label ? 0.5 : 1,
              }}
            >
              {running === b.label ? 'Running...' : b.label}
            </button>
          ))}
          {result && (
            <span style={{
              fontSize: 10, padding: '4px 10px', borderRadius: 'var(--radius)',
              background: result.includes('failed') ? 'var(--red-dim)' : 'var(--green-dim)',
              color: result.includes('failed') ? 'var(--red)' : 'var(--green)',
            }}>{result}</span>
          )}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, marginTop: 8 }}>
          {btns.map(b => (
            <span key={b.label} style={{ fontSize: 9, color: 'var(--text3)' }}>{b.desc}</span>
          ))}
        </div>
      </Card>

      {/* Confirmation modal */}
      {confirm && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setConfirm(null)}>
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '20px 24px', width: 380 }} onClick={e => e.stopPropagation()}>
            <h3 style={{ fontFamily: 'var(--sans)', fontSize: 14, fontWeight: 700, color: 'var(--text0)', margin: '0 0 10px' }}>Confirm: {confirm.label}</h3>
            <p style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.5, margin: '0 0 16px' }}>{confirm.desc}</p>
            <div style={{ padding: '8px 10px', background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 'var(--radius)', fontSize: 10, color: 'var(--amber)', marginBottom: 16 }}>
              This triggers a live pipeline run on the server.
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={() => setConfirm(null)} style={{ padding: '6px 16px', fontSize: 10, border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Cancel</button>
              <button onClick={() => trigger(confirm.endpoint, confirm.label)} style={{ padding: '6px 16px', fontSize: 10, fontWeight: 700, border: '1px solid var(--green)', borderRadius: 'var(--radius)', background: 'var(--green-dim)', color: 'var(--green)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Confirm &amp; Run</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}


function DecisionAuditTrail() {
  const { data } = useApi<{ count: number; history: { id: number; symbol: string; category: string; title: string; priority: string; old_status: string; new_status: string; decision: string; reasoning: string; changed_at: string }[] }>('/api/v2/tasks/history')
  const items = data?.history ?? []

  return (
    <>
      <SectionHeader title="Decision Audit Trail" count={items.length} />
      {items.length === 0 ? (
        <Card compact><div style={{ color: 'var(--text3)', fontSize: 10, padding: 8, textAlign: 'center' }}>No decision history yet. Resolve or defer tasks from Approvals to build audit trail.</div></Card>
      ) : (
        <Card compact>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {items.map(h => (
              <div key={h.id} style={{ display: 'flex', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, alignItems: 'center' }}>
                <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3,
                  background: h.new_status === 'decided_action' ? 'var(--green-dim)' : h.new_status === 'deferred' ? 'var(--amber-dim)' : h.new_status === 'rejected' ? 'var(--red-dim)' : 'var(--bg3)',
                  color: h.new_status === 'decided_action' ? 'var(--green)' : h.new_status === 'deferred' ? 'var(--amber)' : h.new_status === 'rejected' ? 'var(--red)' : 'var(--text3)',
                }}>{h.new_status?.replace(/_/g, ' ')}</span>
                <span style={{ fontWeight: 700, color: 'var(--text0)', width: 50 }}>{h.symbol || '—'}</span>
                <span style={{ color: 'var(--text3)', fontSize: 9 }}>{(h.category || '').replace(/_/g, ' ')}</span>
                <span style={{ flex: 1, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h.reasoning || h.decision || '—'}</span>
                <span style={{ color: 'var(--text3)', fontSize: 9 }}>{h.changed_at ? timeAgo(h.changed_at) : '—'}</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </>
  )
}


function LLMRoutingAudit() {
  const { data } = useApi<{ entries: { timestamp: string; caller: string; process_type: string; model: string; latency_ms: number; status: string; fallback_triggered: boolean }[] }>('/api/v2/ops/llm-audit')
  const entries = data?.entries ?? []
  return (
    <>
      <SectionHeader title="LLM Routing Audit" count={entries.length} />
      {entries.length === 0 ? (
        <Card compact><div style={{ color: 'var(--text3)', fontSize: 10, padding: 8, textAlign: 'center' }}>No LLM audit entries found. Calls logged to logs/llm_routing_audit.jsonl.</div></Card>
      ) : (
        <Card compact>
          <div style={{ overflow: 'auto', maxHeight: 300 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
              <thead><tr style={{ position: 'sticky', top: 0, background: 'var(--bg1)' }}>
                {['Time', 'Script', 'Process Type', 'Model', 'Latency', 'Status'].map(h => (
                  <th key={h} style={{ padding: '5px 8px', textAlign: 'left', color: 'var(--text3)', fontSize: 9, fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {entries.slice(0, 50).map((e, i) => (
                  <tr key={i}>
                    <td style={{ padding: '3px 8px', borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,.04))', color: 'var(--text3)', fontSize: 9 }}>{e.timestamp?.slice(11, 19) || '—'}</td>
                    <td style={{ padding: '3px 8px', borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,.04))', color: 'var(--text1)', fontWeight: 600 }}>{e.caller || '—'}</td>
                    <td style={{ padding: '3px 8px', borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,.04))', color: 'var(--text2)' }}>{e.process_type || '—'}</td>
                    <td style={{ padding: '3px 8px', borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,.04))', color: e.fallback_triggered ? 'var(--amber)' : e.status === 'error' ? 'var(--red)' : 'var(--green)' }}>{e.model || '—'}</td>
                    <td style={{ padding: '3px 8px', borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,.04))', textAlign: 'right', color: 'var(--text2)' }}>{e.latency_ms ? `${Math.round(e.latency_ms)}ms` : '—'}</td>
                    <td style={{ padding: '3px 8px', borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,.04))' }}>
                      {e.fallback_triggered ? <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'rgba(255,160,0,.12)', color: 'var(--amber)' }}>FALLBACK</span>
                        : e.status === 'error' ? <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'var(--red-dim)', color: 'var(--red)' }}>ERROR</span>
                        : <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'var(--green-dim)', color: 'var(--green)' }}>LOCAL</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  )
}


function CronHealth() {
  const { data } = useApi<{ crons: { name: string; display_name?: string; schedule?: string; last_run: string; last_status: string; runs_today: number; status: string; critical: boolean }[] }>('/api/v2/ops/cron-health')
  const crons = data?.crons ?? []
  const badge = (s: string) => {
    const m: Record<string, { bg: string; fg: string }> = { ok: { bg: 'var(--green-dim)', fg: 'var(--green)' }, stale: { bg: 'rgba(255,160,0,.12)', fg: 'var(--amber)' }, failed: { bg: 'var(--red-dim)', fg: 'var(--red)' } }
    const c = m[s] || { bg: 'var(--bg3)', fg: 'var(--text3)' }
    return <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: c.bg, color: c.fg }}>{s.toUpperCase()}</span>
  }
  return (
    <>
      <SectionHeader title="Cron Health" count={crons.length} />
      {crons.length === 0 ? (
        <Card compact><div style={{ color: 'var(--text3)', fontSize: 10, padding: 8, textAlign: 'center' }}>Cron health data loading...</div></Card>
      ) : (
        <Card compact>
          <div style={{ overflow: 'auto', maxHeight: 350 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
              <thead><tr style={{ position: 'sticky', top: 0, background: 'var(--bg1)' }}>
                {['Cron Name', 'Time', 'Last Run', 'Status', 'Runs/24h'].map(h => (
                  <th key={h} style={{ padding: '5px 8px', textAlign: h === 'Cron Name' ? 'left' : 'right', color: 'var(--text3)', fontSize: 9, fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {crons.map((c, i) => (
                  <tr key={i}>
                    <td style={{ padding: '3px 8px', borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,.04))', color: 'var(--text1)', fontWeight: 600 }}>{c.display_name || c.name?.replace(/_/g, ' ') || '—'}</td>
                    <td style={{ padding: '3px 8px', borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,.04))', textAlign: 'right', color: 'var(--text3)', fontSize: 9 }}>{c.schedule || '—'}</td>
                    <td style={{ padding: '3px 8px', borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,.04))', textAlign: 'right', color: 'var(--text2)', fontSize: 9 }}>{c.last_run ? timeAgo(c.last_run) : 'never'}</td>
                    <td style={{ padding: '3px 8px', borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,.04))', textAlign: 'right' }}>{badge(c.status)}</td>
                    <td style={{ padding: '3px 8px', borderBottom: '1px solid var(--border-subtle, rgba(255,255,255,.04))', textAlign: 'right', color: 'var(--text2)' }}>{c.runs_today ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  )
}

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

interface OpsData {
  pipeline: { status: string; completed_at: string; duration_seconds: number; steps: number; run_type: string; holdings_hash: string; run_id: string }
  database: { table_count: number; total_rows: number; tables: { name: string; live_rows: number; dead_rows: number; size: string; last_autovacuum: string | null; last_autoanalyze: string | null }[] }
}

export default function Ops() {
  const [showImport, setShowImport] = useState(false)
  const [adminModal, setAdminModal] = useState<'personal' | 'yaml' | 'env' | 'settings' | null>(null)
  const { data: ops } = useApi<OpsData>('/api/v2/ops/summary')
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
      <PageHeader title="Operations" subtitle="System health, pipeline, and infrastructure" actions={
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

  const trigger = useCallback(async (endpoint: string, label: string) => {
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
    { label: 'Run Portfolio', endpoint: '/api/run-portfolio', desc: 'Full daily pipeline' },
    { label: 'Run Reprice', endpoint: '/api/run-reprice', desc: 'Price refresh only' },
    { label: 'Run Trade AI', endpoint: '/api/run-pipeline', desc: 'Scalp screener pipeline' },
  ]

  return (
    <>
      <SectionHeader title="Pipeline Controls" />
      <Card>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          {btns.map(b => (
            <button
              key={b.label}
              onClick={() => trigger(b.endpoint, b.label)}
              disabled={running !== null}
              style={{
                padding: '6px 16px', fontSize: 11, fontWeight: 600,
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius)',
                background: running === b.label ? 'var(--accent-dim)' : 'var(--bg3)',
                color: running === b.label ? 'var(--accent)' : 'var(--text1)',
                cursor: running ? 'wait' : 'pointer',
                fontFamily: 'var(--mono)',
                opacity: running && running !== b.label ? 0.5 : 1,
                transition: 'all var(--transition)',
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
            }}>
              {result}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 16, marginTop: 8 }}>
          {btns.map(b => (
            <span key={b.label} style={{ fontSize: 9, color: 'var(--text3)' }}>{b.label}: {b.desc}</span>
          ))}
        </div>
      </Card>
    </>
  )
}

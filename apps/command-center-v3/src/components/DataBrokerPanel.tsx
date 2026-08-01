import { useMemo, useState, type CSSProperties, Fragment } from 'react'
import { useApi } from '../hooks/useApi'
import { BB, T } from '../lib/watchTokens'

// Data Management page — administrator view of the Data Broker registry.
// Backed by config/data_registry.yaml via /api/v2/data/registry + /api/v2/data/coverage.
// See docs/DATA_ARCHITECTURE_AUDIT_2026_07_31.md for the audit this implements.

const STATUS_COLOR: Record<string, string> = {
  broker: BB.green,   // sole canonical producer, fully adopted
  partial: BB.amber,  // canonical producer exists but not universally adopted
  legacy: BB.red,      // multiple known duplicate producers still active
}
const STATUS_DIM: Record<string, string> = {
  broker: BB.greenDim, partial: BB.amberDim, legacy: BB.redDim,
}
const STATUS_LABEL: Record<string, string> = {
  broker: 'BROKER', partial: 'PARTIAL', legacy: 'LEGACY',
}
const HEALTH_COLOR: Record<string, string> = {
  healthy: BB.green, error: BB.red, unknown: BB.text3,
}

type DT = {
  id: string; domain: string; producer?: string; store?: string
  ttl_seconds?: number | null; cadence?: string; authority?: string
  status?: string; deprecated_producers?: string[]; notes?: string
}
type ConsumerRow = { page?: string; alert?: string; script?: string; route?: string; notes?: string
  reads: { data_type: string; via: string; broker: boolean }[] }
type Matrix = { pages: ConsumerRow[]; alerts: ConsumerRow[]; pipeline_scripts: ConsumerRow[] }

const SUBTABS = ['Registry', 'Matrix', 'Duplication', 'Source Health'] as const

function fmtTtl(s: number | null | undefined): string {
  if (s == null) return 'event-sourced'
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  if (s < 86400) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

const card: CSSProperties = { background: BB.bgShift, border: `1px solid ${BB.border}`, borderRadius: 10, padding: 14 }
const th: CSSProperties = { fontSize: 10, color: BB.text3, padding: '3px 6px', textAlign: 'left', textTransform: 'uppercase', borderBottom: `1px solid ${BB.border}` }
const td: CSSProperties = { fontSize: 11, padding: '5px 6px', borderBottom: `1px solid ${BB.border}`, verticalAlign: 'top' }
const foot: CSSProperties = { fontSize: 10, color: BB.text3, marginTop: 8 }
const input: CSSProperties = { background: BB.bgPanel, border: `1px solid ${BB.border}`, color: BB.text1, borderRadius: 5, padding: '5px 10px', fontSize: 11 }

export default function DataBrokerPanel() {
  const [sub, setSub] = useState<typeof SUBTABS[number]>('Registry')
  const [domainFilter, setDomainFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [q, setQ] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)

  const { data: reg, loading: regLoading, error: regError } = useApi<any>('/api/v2/data/registry', 120_000)
  const { data: cov, loading: covLoading } = useApi<any>('/api/v2/data/coverage', 120_000)

  const dataTypes: DT[] = reg?.data_types ?? []
  const matrix: Matrix = reg?.consumers ?? { pages: [], alerts: [], pipeline_scripts: [] }
  const summary = reg?.summary ?? {}
  const sourceHealth: any[] = reg?.source_health ?? []

  const domains = useMemo(() => Array.from(new Set(dataTypes.map(d => d.domain))).sort(), [dataTypes])

  const filteredTypes = useMemo(() => dataTypes.filter(d => {
    if (domainFilter !== 'all' && d.domain !== domainFilter) return false
    if (statusFilter !== 'all' && d.status !== statusFilter) return false
    if (q && !`${d.id} ${d.producer ?? ''} ${d.store ?? ''}`.toLowerCase().includes(q.toLowerCase())) return false
    return true
  }), [dataTypes, domainFilter, statusFilter, q])

  // consumer count per data_type, for the registry table
  const consumerCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const group of [matrix.pages ?? [], matrix.alerts ?? [], matrix.pipeline_scripts ?? []]) {
      for (const row of group) for (const r of row.reads ?? []) counts[r.data_type] = (counts[r.data_type] ?? 0) + 1
    }
    return counts
  }, [matrix])

  if (regLoading && !reg) return <div style={{ padding: 20, color: BB.text3 }}>Loading Data Broker registry…</div>
  if (regError && !reg) return <div style={{ padding: 20, color: BB.red }}>Failed to load registry: {regError}</div>

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 10, marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 800, color: BB.text0 }}>Data Broker — Data Management</div>
          <div style={{ fontSize: 11, color: BB.text3, marginTop: 2, maxWidth: 720 }}>
            Single source of truth for every data type on the site: producer, canonical store, TTL, authority,
            and every consumer (page + alert + pipeline script). Config: <code>config/data_registry.yaml</code>.
            Audit: <code>docs/DATA_ARCHITECTURE_AUDIT_2026_07_31.md</code>.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {[
            ['Data types', summary.data_type_count, BB.text0],
            ['Broker', summary.by_status?.broker ?? 0, BB.green],
            ['Partial', summary.by_status?.partial ?? 0, BB.amber],
            ['Legacy', summary.by_status?.legacy ?? 0, BB.red],
            ['Pages', summary.page_count, T.link],
            ['Alerts', summary.alert_count, T.extIntel.hermes],
          ].map(([k, v, c]: any) => (
            <div key={k} style={{ background: BB.bgShift, border: `1px solid ${BB.border}`, borderRadius: 8, padding: '6px 12px', minWidth: 70, textAlign: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: c }}>{v ?? '—'}</div>
              <div style={{ fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}>{k}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
        {SUBTABS.map(t => (
          <button key={t} onClick={() => setSub(t)}
            style={{
              background: sub === t ? BB.bgPanel : 'transparent', color: sub === t ? BB.text0 : BB.text3,
              border: `1px solid ${BB.border}`, borderRadius: 6, padding: '5px 12px', fontSize: 11, fontWeight: 700, cursor: 'pointer',
            }}>{t}</button>
        ))}
      </div>

      {sub === 'Registry' && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
            <input placeholder="search data type / producer / store…" value={q} onChange={e => setQ(e.target.value)}
              style={{ ...input, width: 260 }} />
            <select value={domainFilter} onChange={e => setDomainFilter(e.target.value)} style={input}>
              <option value="all">all domains</option>
              {domains.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
            <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={input}>
              <option value="all">all statuses</option>
              <option value="broker">broker</option>
              <option value="partial">partial</option>
              <option value="legacy">legacy</option>
            </select>
            <span style={{ fontSize: 11, color: BB.text3, alignSelf: 'center' }}>{filteredTypes.length} / {dataTypes.length}</span>
          </div>
          <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={th}>Data type</th><th style={th}>Domain</th><th style={th}>Producer</th>
                  <th style={th}>Store</th><th style={th}>TTL</th><th style={th}>Consumers</th><th style={th}>Status</th>
                </tr>
              </thead>
              <tbody>
                {filteredTypes.map(d => (
                  <Fragment key={d.id}>
                    <tr onClick={() => setExpanded(expanded === d.id ? null : d.id)} style={{ cursor: 'pointer' }}>
                      <td style={{ ...td, fontWeight: 700, color: BB.text0, fontFamily: 'var(--mono)' }}>{d.id}</td>
                      <td style={{ ...td, color: BB.text3 }}>{d.domain}</td>
                      <td style={{ ...td, color: BB.text2, fontFamily: 'var(--mono)', fontSize: 10 }}>{d.producer}</td>
                      <td style={{ ...td, color: BB.text3, fontFamily: 'var(--mono)', fontSize: 10 }}>{d.store}</td>
                      <td style={{ ...td, color: BB.text3 }}>{fmtTtl(d.ttl_seconds)}</td>
                      <td style={{ ...td, color: BB.text2 }}>{consumerCounts[d.id] ?? 0}</td>
                      <td style={td}>
                        <span style={{ fontSize: 10, fontWeight: 800, padding: '2px 7px', borderRadius: 5, color: STATUS_COLOR[d.status ?? ''] ?? BB.text3, background: STATUS_DIM[d.status ?? ''] ?? 'rgba(148,163,184,.12)' }}>
                          {STATUS_LABEL[d.status ?? ''] ?? d.status}
                        </span>
                      </td>
                    </tr>
                    {expanded === d.id && (
                      <tr>
                        <td colSpan={7} style={{ ...td, background: BB.bgPanel }}>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '4px 8px' }}>
                            <div><b style={{ color: BB.text2 }}>Authority: </b><span style={{ color: BB.text3 }}>{d.authority || '—'}</span></div>
                            <div><b style={{ color: BB.text2 }}>Cadence: </b><span style={{ color: BB.text3 }}>{d.cadence || '—'}</span></div>
                            {d.notes && <div><b style={{ color: BB.text2 }}>Notes: </b><span style={{ color: BB.text3 }}>{d.notes}</span></div>}
                            {(d.deprecated_producers?.length ?? 0) > 0 && (
                              <div>
                                <b style={{ color: BB.amber }}>Deprecated / duplicate producers ({d.deprecated_producers!.length}): </b>
                                <ul style={{ margin: '4px 0 0 16px', color: BB.text3 }}>
                                  {d.deprecated_producers!.map((p, i) => <li key={i} style={{ fontFamily: 'var(--mono)', fontSize: 10 }}>{p}</li>)}
                                </ul>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          <div style={foot}>Source: /api/v2/data/registry (config/data_registry.yaml). Click a row for authority/cadence/deprecated-producer detail.</div>
        </div>
      )}

      {sub === 'Matrix' && <MatrixView matrix={matrix} />}

      {sub === 'Duplication' && <DuplicationView cov={cov} loading={covLoading} />}

      {sub === 'Source Health' && (
        <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr><th style={th}>Source</th><th style={th}>Status</th><th style={th}>Last success</th><th style={th}>Last failure</th><th style={th}>Row count</th><th style={th}>Failures</th></tr></thead>
            <tbody>
              {sourceHealth.length === 0 && <tr><td style={td} colSpan={6}><span style={{ color: BB.text3 }}>No data_source_health rows (JSON-only mode or table empty).</span></td></tr>}
              {sourceHealth.map((s, i) => (
                <tr key={i}>
                  <td style={{ ...td, fontFamily: 'var(--mono)', color: BB.text1 }}>{s.source_key}</td>
                  <td style={td}><span style={{ color: HEALTH_COLOR[s.status] ?? BB.text3, fontWeight: 700 }}>{s.status ?? 'unknown'}</span></td>
                  <td style={{ ...td, color: BB.text3 }}>{s.last_success_at ? new Date(s.last_success_at).toLocaleString() : '—'}</td>
                  <td style={{ ...td, color: BB.text3 }}>{s.last_failure_at ? new Date(s.last_failure_at).toLocaleString() : '—'}</td>
                  <td style={{ ...td, color: BB.text2 }}>{s.last_row_count ?? '—'}</td>
                  <td style={{ ...td, color: (s.failure_count ?? 0) > 0 ? BB.red : BB.text3 }}>{s.failure_count ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ ...foot, margin: '8px' }}>Source: data_source_health table (existing per-source liveness signal, composed here — not replaced).</div>
        </div>
      )}
    </div>
  )
}

function MatrixView({ matrix }: { matrix: Matrix }) {
  const [group, setGroup] = useState<'pages' | 'alerts' | 'pipeline_scripts'>('pages')
  const rows = matrix[group] ?? []
  return (
    <div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        {(['pages', 'alerts', 'pipeline_scripts'] as const).map(g => (
          <button key={g} onClick={() => setGroup(g)}
            style={{ background: group === g ? BB.bgPanel : 'transparent', color: group === g ? BB.text0 : BB.text3, border: `1px solid ${BB.border}`, borderRadius: 6, padding: '4px 10px', fontSize: 10, fontWeight: 700, cursor: 'pointer' }}>
            {g === 'pipeline_scripts' ? 'Pipeline scripts' : g.charAt(0).toUpperCase() + g.slice(1)} ({(matrix[g] ?? []).length})
          </button>
        ))}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rows.map((row, i) => {
          const label = row.page || row.alert || row.script || '?'
          return (
            <div key={i} style={card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: BB.text0 }}>{label}</div>
                {row.route && <div style={{ fontSize: 10, color: BB.text3, fontFamily: 'var(--mono)' }}>{row.route}</div>}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {(row.reads ?? []).map((r, j) => (
                  <span key={j} title={r.via}
                    style={{
                      fontSize: 10, padding: '3px 8px', borderRadius: 5, fontFamily: 'var(--mono)',
                      background: r.broker ? BB.greenDim : BB.redDim,
                      color: r.broker ? BB.green : BB.red, border: `1px solid ${r.broker ? BB.green : BB.red}`,
                    }}>
                    {r.data_type} {r.broker ? '✓' : '⚠ bypass'}
                  </span>
                ))}
              </div>
              {row.notes && <div style={{ fontSize: 10, color: BB.text3, marginTop: 6 }}>{row.notes}</div>}
            </div>
          )
        })}
      </div>
      <div style={foot}>
        Green ✓ = reads through the canonical broker producer/store. Red ⚠ bypass = known ad-hoc/duplicate path (see Duplication tab). Source: /api/v2/data/matrix.
      </div>
    </div>
  )
}

function DuplicationView({ cov, loading }: { cov: any; loading: boolean }) {
  if (loading && !cov) return <div style={{ padding: 20, color: BB.text3 }}>Loading coverage report…</div>
  const dup: any[] = cov?.duplication ?? []
  const counts = cov?.counts ?? {}
  const pending = dup.filter(d => d.exists === true)
  const migrated = dup.filter(d => d.exists === false)
  const unknown = dup.filter(d => d.exists === null)
  return (
    <div>
      <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        {[
          ['Pending migrations', counts.pending_migrations, BB.red],
          ['Migrated', counts.migrated, BB.green],
          ['Orphan data types', counts.orphan_data_types, counts.orphan_data_types > 0 ? BB.amber : BB.text3],
          ['Dangling refs', counts.dangling_consumer_refs, counts.dangling_consumer_refs > 0 ? BB.red : BB.text3],
        ].map(([k, v, c]: any) => (
          <div key={k} style={{ background: BB.bgShift, border: `1px solid ${BB.border}`, borderRadius: 8, padding: '8px 14px', minWidth: 100 }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: c }}>{v ?? 0}</div>
            <div style={{ fontSize: 10, color: BB.text3, textTransform: 'uppercase' }}>{k}</div>
          </div>
        ))}
      </div>

      <div style={{ fontSize: 11, fontWeight: 700, color: BB.red, marginBottom: 6 }}>Migration pending ({pending.length}) — ad-hoc producer still present in the repo</div>
      <div style={{ ...card, padding: 0, overflow: 'hidden', marginBottom: 14 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr><th style={th}>Data type</th><th style={th}>File</th><th style={th}>Detail</th></tr></thead>
          <tbody>
            {pending.length === 0 && <tr><td style={td} colSpan={3}><span style={{ color: BB.text3 }}>None — fully migrated.</span></td></tr>}
            {pending.map((d, i) => (
              <tr key={i}>
                <td style={{ ...td, fontFamily: 'var(--mono)', color: BB.text1 }}>{d.data_type}</td>
                <td style={{ ...td, fontFamily: 'var(--mono)', color: BB.red }}>{d.producer_path}</td>
                <td style={{ ...td, color: BB.text3, fontSize: 10 }}>{d.raw}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ fontSize: 11, fontWeight: 700, color: BB.green, marginBottom: 6 }}>Migrated ({migrated.length}) — deprecated producer removed</div>
      <div style={{ ...card, padding: 0, overflow: 'hidden', marginBottom: 14 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <tbody>
            {migrated.length === 0 && <tr><td style={td}><span style={{ color: BB.text3 }}>None yet.</span></td></tr>}
            {migrated.map((d, i) => (
              <tr key={i}><td style={{ ...td, fontFamily: 'var(--mono)', color: BB.text1 }}>{d.data_type}</td><td style={{ ...td, fontFamily: 'var(--mono)', color: BB.green }}>{d.producer_path}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      {unknown.length > 0 && (
        <>
          <div style={{ fontSize: 11, fontWeight: 700, color: BB.text3, marginBottom: 6 }}>Prose notes (not file-checkable) ({unknown.length})</div>
          <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <tbody>
                {unknown.map((d, i) => (
                  <tr key={i}><td style={{ ...td, fontFamily: 'var(--mono)', color: BB.text1 }}>{d.data_type}</td><td style={{ ...td, color: BB.text3, fontSize: 10 }}>{d.raw}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <div style={foot}>Source: /api/v2/data/coverage — greps for whether each registry-listed deprecated producer file still exists in the repo.</div>
    </div>
  )
}

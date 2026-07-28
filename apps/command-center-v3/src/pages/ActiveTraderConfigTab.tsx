/**
 * Active Trader — Configuration tab (Stage AT-CFG-S1). READ-ONLY.
 *
 * Self-contained, self-fetching subtab. Renders the EIGHT read-only panels of
 * `GET /api/v3/active-trader/config` (contract `active-trader-at-cfg-s1-read-v1`).
 *
 * HARD RULES honored here (mirrors the backend contract):
 *   - Display only. No write controls, no POST, no <form> that submits, no edit buttons.
 *   - NEVER renders a secret value — credential slots show {name, populated} only, and
 *     the panel LINKS to the existing Secrets Manager surface (System → Admin) for the rest.
 *   - Honest states: an "unknown object" ({value:null,status:"unknown",reason}) renders as
 *     "unknown" with its reason; null → "—"; db_available:false → a clear degraded banner.
 *   - The two live momentum_scalp contradictions (float ceiling YAML 20 / DB 100 / engine 30;
 *     stop cap 8% vs 15%) are surfaced VERBATIM and NOT reconciled.
 *
 * House style: watchTokens (BB / T / TYPE / statePill / metricChip / numStyle). No raw hex,
 * nothing below 10px — satisfies scripts/check_design_tokens.sh.
 */
import { Fragment, useState, type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { BB, T, TYPE, statePill, metricChip, numStyle } from '../lib/watchTokens'

const NUM = numStyle as CSSProperties

// ── honest-value helpers ─────────────────────────────────────────────────────────────────────────
const isUnknownObj = (v: any): boolean =>
  !!v && typeof v === 'object' && !Array.isArray(v) && v.status === 'unknown'

function Unknown({ reason }: { reason?: string }) {
  return (
    <span title={reason} style={{ color: BB.text3, fontStyle: 'italic', cursor: reason ? 'help' : 'default' }}>
      unknown{reason ? ' ⓘ' : ''}
    </span>
  )
}

/** Render any contract value honestly — unknown-object → "unknown ⓘ" (reason on hover); null → "—". */
function Val({ v, mono = true }: { v: any; mono?: boolean }) {
  if (v === null || v === undefined) return <span style={{ color: BB.text3 }}>—</span>
  if (isUnknownObj(v)) return <Unknown reason={v.reason} />
  if (Array.isArray(v)) {
    return (
      <span style={mono ? NUM : undefined}>
        [{v.map((x) => (isUnknownObj(x) ? 'unknown' : x === null ? '—' : String(x))).join(', ')}]
      </span>
    )
  }
  if (typeof v === 'boolean') return <span style={{ color: v ? BB.green : BB.text3, fontWeight: 700 }}>{String(v)}</span>
  return <span style={mono ? NUM : undefined}>{String(v)}</span>
}

function fmtTs(iso: any): string {
  if (!iso || typeof iso !== 'string') return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return String(iso)
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}
function fmtAgeSec(s: any): string {
  if (s == null || typeof s !== 'number' || !isFinite(s)) return '—'
  if (s < 90) return `${Math.round(s)}s ago`
  if (s < 5400) return `${Math.round(s / 60)}m ago`
  if (s < 172800) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}
const pct = (n: any): string => (typeof n === 'number' && isFinite(n) ? `${(n * 100).toFixed(1)}%` : '—')

type Tone = 'green' | 'amber' | 'red' | 'slate'
const freshTone = (status?: string): Tone => (status === 'fresh' ? 'green' : status === 'stale' ? 'red' : 'slate')

// ── shared chrome ────────────────────────────────────────────────────────────────────────────────
const panelBox: CSSProperties = { background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: 14 }
const sectionTitle: CSSProperties = { fontSize: TYPE.md, fontWeight: 800, color: BB.text0, letterSpacing: '.02em' }
const subNote: CSSProperties = { fontSize: TYPE.xs, color: BB.text3, lineHeight: 1.5 }
const th: CSSProperties = {
  fontSize: TYPE.xs, color: BB.text3, textTransform: 'uppercase', letterSpacing: '.04em',
  textAlign: 'left', padding: '5px 8px', borderBottom: `1px solid ${BB.border}`, whiteSpace: 'nowrap', fontWeight: 700,
}
const td: CSSProperties = {
  fontSize: TYPE.sm, color: BB.text1, padding: '6px 8px', borderBottom: `1px solid ${BB.borderHair}`, verticalAlign: 'top',
}
const scrollX: CSSProperties = { overflowX: 'auto', width: '100%' }
const mono: CSSProperties = { ...NUM, color: BB.text2, fontSize: TYPE.xs, wordBreak: 'break-all' }

function Card({ title, source, children }: { title: string; source?: ReactNode; children: ReactNode }) {
  return (
    <div style={panelBox}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
        <div style={sectionTitle}>{title}</div>
        {source && <div style={{ ...subNote, fontFamily: BB.mono }}>{source}</div>}
      </div>
      {children}
    </div>
  )
}

/** A panel object may fail-closed to {status:"unknown", reason}. Render that honestly. */
function PanelDegraded({ panel }: { panel: any }) {
  if (!panel || panel.status !== 'unknown') return null
  return (
    <div style={{ ...panelBox, borderColor: BB.amber, background: BB.amberDim, color: BB.text1, fontSize: TYPE.sm, lineHeight: 1.5 }}>
      <b style={{ color: BB.amber }}>Panel unavailable.</b> {panel.reason || 'no reason provided'}
    </div>
  )
}

function Pill({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return <span title={title} style={statePill(tone)}>{children}</span>
}

// ── Panel 1: Strategy registry ─────────────────────────────────────────────────────────────────────
function StrategyRegistryPanel({ panel }: { panel: any }) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  if (panel?.status === 'unknown') return <PanelDegraded panel={panel} />
  const strategies: any[] = panel?.strategies ?? []
  const stateTone = (s: string): Tone => (s === 'enabled' ? 'green' : s === 'suspended' ? 'red' : s === 'shadow_candidate' ? 'amber' : 'slate')

  return (
    <Card title="Strategy registry" source={panel?.source}>
      <div style={scrollX}>
        <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 880 }}>
          <thead>
            <tr>
              {['Strategy', 'State', 'Review gate (trades · WR · PF)', 'Config file', 'Git SHA', 'Last modified', 'Drift'].map((h) => (
                <th key={h} style={th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {strategies.map((s) => {
              const rg = s.review_gate
              const gate = !isUnknownObj(rg) ? rg : null
              const drift = s.drift || {}
              const hasDrift = !!drift.has_drift
              const isOpen = !!open[s.key]
              return (
                <Fragment key={s.key}>
                  <tr>
                    <td style={{ ...td, fontWeight: 700, color: BB.text0, ...NUM }}>
                      {s.key}
                      {s.status && <span style={{ marginLeft: 6, fontSize: TYPE.xs, color: BB.text3 }}>{s.status}</span>}
                    </td>
                    <td style={td}><Pill tone={stateTone(s.state)}>{s.state}</Pill></td>
                    <td style={td}>
                      {gate ? (() => {
                        const p = gate.progress_yaml_performance_context || {}
                        const t = gate.thresholds || {}
                        const met = gate.gate_met
                        return (
                          <span style={{ color: met ? BB.green : BB.amber, ...NUM, fontSize: TYPE.xs }}>
                            {p.closed_paper_trades ?? '—'}/{t.min_closed_validation_trades ?? '—'} tr ·
                            {' '}WR {pct(p.win_rate)}/{pct(t.min_win_rate)} ·
                            {' '}PF {p.profit_factor ?? '—'}/{t.min_profit_factor ?? '—'}
                            {' '}<b>{met ? '✓ met' : '✗ not met'}</b>
                          </span>
                        )
                      })() : <Unknown reason={isUnknownObj(rg) ? rg.reason : undefined} />}
                    </td>
                    <td style={td}>{isUnknownObj(s.config_file) ? <Unknown reason={s.config_file.reason} /> : <span style={mono}>{s.config_file}</span>}</td>
                    <td style={{ ...td, ...NUM, color: BB.text2 }}>{s.git_sha || '—'}</td>
                    <td style={{ ...td, color: BB.text2 }}>{fmtTs(s.last_modified)}</td>
                    <td style={td}>
                      {hasDrift ? (
                        <button type="button" onClick={() => setOpen((o) => ({ ...o, [s.key]: !o[s.key] }))}
                          style={{ ...statePill('red'), cursor: 'pointer', border: `1px solid ${BB.red}` }}>
                          DRIFT {isOpen ? '▲' : '▼'}
                        </button>
                      ) : drift.db_values ? (
                        <Pill tone="slate" title="DB registry values only (per-strategy YAML/running reconciliation not in S1 scope)">DB-only</Pill>
                      ) : (
                        <Pill tone="slate">—</Pill>
                      )}
                    </td>
                  </tr>
                  {hasDrift && isOpen && (
                    <tr key={s.key + '-drift'}>
                      <td colSpan={7} style={{ ...td, background: BB.bgShift }}>
                        <DriftDetail drift={drift} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
      {panel?.note && <div style={{ ...subNote, marginTop: 8 }}>{panel.note}</div>}
    </Card>
  )
}

function DriftDetail({ drift }: { drift: any }) {
  const fc = drift.float_ceiling
  const sc = drift.stop_cap
  const row = (label: string, obj: any) => (
    <tr key={label}>
      <td style={{ ...td, color: BB.text3, whiteSpace: 'nowrap' }}>{label}</td>
      <td style={{ ...td, ...NUM, color: BB.text0, fontWeight: 700 }}>
        <Val v={obj?.value} />
        {obj?.preferred != null && <span style={{ color: BB.text3, fontWeight: 400 }}> (pref {obj.preferred})</span>}
      </td>
      <td style={{ ...td, ...mono }}>{obj?.source || '—'}</td>
    </tr>
  )
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {fc && (
        <div>
          <div style={{ fontSize: TYPE.sm, fontWeight: 800, color: BB.red, marginBottom: 4 }}>
            Float ceiling — 3-way YAML ‖ DB ‖ engine {fc.agree ? '(agree)' : '· DISAGREE (not reconciled)'}
          </div>
          <div style={scrollX}>
            <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 620 }}>
              <tbody>
                {row('YAML', fc.values?.yaml)}
                {row('DB', fc.values?.db)}
                {row('engine', fc.values?.engine)}
                {row('finviz running', fc.values?.finviz_running_screen)}
              </tbody>
            </table>
          </div>
          <div style={{ ...subNote, marginTop: 4 }}>{fc.note}</div>
        </div>
      )}
      {sc && (
        <div>
          <div style={{ fontSize: TYPE.sm, fontWeight: 800, color: BB.red, marginBottom: 4 }}>
            Stop cap {sc.agree ? '(agree)' : '· DISAGREE (not reconciled)'}
          </div>
          <div style={scrollX}>
            <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 620 }}>
              <tbody>
                {row('fallback cap', sc.values?.yaml_fallback_cap)}
                {row('disqualifier', sc.values?.yaml_disqualifier)}
                {row('engine alt', sc.values?.engine_alt)}
              </tbody>
            </table>
          </div>
          <div style={{ ...subNote, marginTop: 4 }}>{sc.note}</div>
        </div>
      )}
    </div>
  )
}

// ── Panel 2: Setup taxonomy ──────────────────────────────────────────────────────────────────────
function SetupTaxonomyPanel({ panel }: { panel: any }) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  if (panel?.status === 'unknown') return <PanelDegraded panel={panel} />
  const setups: any[] = panel?.setups ?? []
  const persisted = panel?.persisted || {}
  const total = persisted.total_rows ?? 0
  const populated = persisted.primary_setup_id_populated_total ?? 0
  const nul = persisted.primary_setup_id_null_total ?? 0

  return (
    <Card title="Setup taxonomy" source={panel?.source}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10, fontSize: TYPE.xs, color: BB.text3 }}>
        <span>registry <b style={{ color: BB.text1 }}>{panel?.registry_version || 'unknown'}</b></span>
        {panel?.registry_hash && <span style={mono}>{panel.registry_hash}</span>}
      </div>

      {/* Persisted populated-vs-null — reported honestly */}
      <div style={{ background: persisted.fully_null ? BB.amberDim : BB.bgShift, border: `1px solid ${persisted.fully_null ? BB.amber : BB.border}`, borderRadius: 2, padding: '8px 10px', marginBottom: 12 }}>
        <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: persisted.fully_null ? BB.amber : BB.text1, marginBottom: 3 }}>
          Persisted onto {persisted.table || 'scalp_ignition_events'}: {populated} populated / {nul} NULL of {total} rows
          {persisted.fully_null && ' — taxonomy 100% NULL on all rows'}
        </div>
        <div style={subNote}>{persisted.note}</div>
      </div>

      <div style={scrollX}>
        <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 760 }}>
          <thead>
            <tr>{['Setup', 'Family', 'Strategy', 'State', 'Tier', 'Criteria'].map((h) => <th key={h} style={th}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {setups.map((s) => {
              const isOpen = !!open[s.setup_id]
              const c = s.defining_criteria || {}
              return (
                <Fragment key={s.setup_id}>
                  <tr>
                    <td style={{ ...td, fontWeight: 700, color: BB.text0 }}>
                      {s.display_label}
                      <div style={{ ...mono, color: BB.text3 }}>{s.setup_id}</div>
                    </td>
                    <td style={td}>{s.family}</td>
                    <td style={{ ...td, fontSize: TYPE.xs, color: BB.text2 }}>{s.strategy}</td>
                    <td style={td}><Pill tone={s.operating_state === 'DISABLED' ? 'red' : s.operating_state === 'SHADOW' ? 'amber' : 'slate'}>{s.operating_state}</Pill></td>
                    <td style={{ ...td, ...NUM }}>{s.required_data_tier}</td>
                    <td style={td}>
                      <button type="button" onClick={() => setOpen((o) => ({ ...o, [s.setup_id]: !o[s.setup_id] }))}
                        style={{ ...metricChip(true), cursor: 'pointer' }}>{isOpen ? 'hide' : 'criteria'} {isOpen ? '▲' : '▼'}</button>
                    </td>
                  </tr>
                  {isOpen && (
                    <tr key={s.setup_id + '-c'}>
                      <td colSpan={6} style={{ ...td, background: BB.bgShift }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: TYPE.xs, color: BB.text1, lineHeight: 1.5 }}>
                          <div><b style={{ color: BB.text3 }}>entry:</b> {c.entry_rule || '—'}</div>
                          <div><b style={{ color: BB.text3 }}>invalidation:</b> {c.invalidation_rule || '—'}</div>
                          <div><b style={{ color: BB.text3 }}>stop:</b> {c.stop_rule || '—'}</div>
                          <div><b style={{ color: BB.text3 }}>inputs:</b> <span style={NUM}>{(c.required_inputs || []).join(', ') || '—'}</span></div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

// ── Panel 3: Criteria matrix ─────────────────────────────────────────────────────────────────────
function CriteriaMatrixPanel({ panel }: { panel: any }) {
  if (panel?.status === 'unknown') return <PanelDegraded panel={panel} />
  const ms = panel?.strategies?.momentum_scalp || {}
  const criteria: any[] = ms.criteria ?? []
  // "Real" drift = a gating criterion whose three sources disagree (float_ceiling, stop_cap).
  const isDrift = (c: any) => c.agree === false && c.counts_toward_match_minimum
  const driftRows = criteria.filter(isDrift)
  const [driftOnly, setDriftOnly] = useState<boolean>(driftRows.length > 0)
  const rows = driftOnly ? criteria.filter(isDrift) : criteria
  const guard = ms._classifier_guard_evidence

  return (
    <Card title="Criteria matrix — momentum_scalp" source={panel?.source}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
        {driftRows.length > 0 && (
          <Pill tone="red">{driftRows.length} gating contradiction{driftRows.length > 1 ? 's' : ''} (not reconciled)</Pill>
        )}
        <button type="button" onClick={() => setDriftOnly((v) => !v)} style={{ ...metricChip(true), cursor: 'pointer' }}>
          {driftOnly ? `show all ${criteria.length}` : 'show drift only'}
        </button>
      </div>
      <div style={scrollX}>
        <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 820 }}>
          <thead>
            <tr>{['Criterion', 'yaml_value', 'db_value', 'running_value', 'agree', 'gating?'].map((h) => <th key={h} style={th}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const contradiction = isDrift(c)
              return (
                <Fragment key={c.criterion}>
                  <tr style={contradiction ? { background: BB.redDim } : undefined}>
                    <td style={{ ...td, fontWeight: 700, color: contradiction ? BB.red : BB.text0, ...NUM }}>{c.criterion}</td>
                    <td style={td}><Val v={c.yaml_value} /></td>
                    <td style={td}><Val v={c.db_value} /></td>
                    <td style={td}><Val v={c.running_value} /></td>
                    <td style={td}>
                      {c.agree === true ? <Pill tone="green">agree</Pill>
                        : c.agree === false ? <Pill tone="red">disagree</Pill>
                        : <Pill tone="slate">n/a</Pill>}
                    </td>
                    <td style={td}>
                      {c.counts_toward_match_minimum
                        ? <Pill tone="amber" title="Counts toward the GO match minimum">counts → GO</Pill>
                        : <Pill tone="slate" title="Informational only — does not gate GO">info only</Pill>}
                    </td>
                  </tr>
                  {c.note && (
                    <tr key={c.criterion + '-n'}>
                      <td colSpan={6} style={{ ...td, borderBottom: `1px solid ${BB.border}`, background: contradiction ? BB.redDim : undefined }}>
                        <span style={{ ...subNote, color: contradiction ? BB.text1 : BB.text3 }}>{c.note}</span>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
      {guard && (
        <div style={{ marginTop: 12, borderTop: `1px solid ${BB.border}`, paddingTop: 8 }}>
          <div style={{ fontSize: TYPE.xs, fontWeight: 700, color: BB.text2, marginBottom: 4 }}>Classifier guard (S0.5): social never counts toward GO</div>
          <div style={{ ...subNote, marginBottom: 6 }}>{guard.rule}</div>
          {(guard.enforcing_lines || []).map((e: any, i: number) => (
            <div key={i} style={{ ...mono, marginBottom: 4 }}>
              <b style={{ color: BB.text2 }}>{e.file}:{e.lines}</b> — {e.quote}
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

// ── Panel 4: Data sources ────────────────────────────────────────────────────────────────────────
function DataSourcesPanel({ panel }: { panel: any }) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  if (panel?.status === 'unknown') return <PanelDegraded panel={panel} />
  const sources: any[] = panel?.sources ?? []
  const stale: string[] = panel?.stale_sources ?? []
  // Stale sorts to the top.
  const ordered = [...sources].sort((a, b) => {
    const sa = a.freshness?.status === 'stale' ? 0 : 1
    const sb = b.freshness?.status === 'stale' ? 0 : 1
    return sa - sb
  })

  return (
    <Card title="Data sources" source={panel?.source}>
      {stale.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          <Pill tone="red">{stale.length} stale: {stale.join(', ')}</Pill>
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {ordered.map((s) => {
          const f = s.freshness || {}
          const isStale = f.status === 'stale'
          const isOpen = !!open[s.name]
          const screeners: any[] = s.query_definition?.screeners
          const filterStr = s.query_definition?.finviz_url_filters
          return (
            <div key={s.name} style={{
              border: `1px solid ${isStale ? BB.red : BB.border}`,
              borderLeft: `3px solid ${isStale ? BB.red : BB.border}`,
              background: isStale ? BB.redDim : BB.bgShift, borderRadius: 2, padding: '8px 10px',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', alignItems: 'baseline' }}>
                <span style={{ ...NUM, fontWeight: 700, color: BB.text0, fontSize: TYPE.sm }}>{s.name}</span>
                <span style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  {isUnknownObj(f)
                    ? <Unknown reason={f.reason} />
                    : <Pill tone={freshTone(f.status)} title={`age ${fmtAgeSec(f.age_seconds)} vs threshold ${fmtAgeSec(f.stale_threshold_seconds)}`}>{f.status}</Pill>}
                  {s.monitor_status && <Pill tone={s.degraded ? 'red' : 'slate'}>{s.monitor_status}</Pill>}
                </span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 6, marginTop: 6, fontSize: TYPE.xs, color: BB.text3 }}>
                <div>consumers: <span style={{ color: BB.text2 }}>{Array.isArray(s.consuming_strategies) ? (s.consuming_strategies.join(', ') || '—') : <Unknown reason={s.consuming_strategies?.reason} />}</span></div>
                <div>cadence: <span style={{ color: BB.text2 }}>{isUnknownObj(s.refresh_cadence) ? <Unknown reason={s.refresh_cadence.reason} /> : s.refresh_cadence}</span></div>
                <div>table: <span style={{ ...NUM, color: BB.text2 }}>{s.output_table || '—'}</span></div>
                <div>rows: <span style={{ ...NUM, color: BB.text2 }}>{s.row_count ?? '—'}</span></div>
                <div>last run: <span style={{ color: BB.text2 }}>{fmtTs(s.last_successful_run)}</span></div>
                <div>newest row: <span style={{ color: BB.text2 }}>{fmtAgeSec(s.newest_row_age_seconds)}</span></div>
              </div>
              {filterStr && (
                <div style={{ marginTop: 6 }}>
                  <span style={subNote}>finviz filter: </span><span style={mono}>{filterStr}</span>
                  {s.query_definition?.finviz_order && <span style={{ ...mono, color: BB.text3 }}> · order={s.query_definition.finviz_order}</span>}
                </div>
              )}
              {s.query_definition?.last_error && (
                <div style={{ marginTop: 6, fontSize: TYPE.xs, color: BB.red }}>last_error: {String(s.query_definition.last_error)}</div>
              )}
              {Array.isArray(screeners) && (
                <div style={{ marginTop: 6 }}>
                  <button type="button" onClick={() => setOpen((o) => ({ ...o, [s.name]: !o[s.name] }))} style={{ ...metricChip(true), cursor: 'pointer' }}>
                    {isOpen ? 'hide' : `${screeners.length} screener filter strings`} {isOpen ? '▲' : '▼'}
                  </button>
                  {isOpen && (
                    <div style={{ ...scrollX, marginTop: 6 }}>
                      <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 760 }}>
                        <thead><tr>{['Screener', 'Strategy', 'Full Finviz filter', 'Schedule', 'Last run', 'Rows', 'Exec elig', 'Review only'].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
                        <tbody>
                          {screeners.map((r: any) => (
                            <tr key={r.screener_id}>
                              <td style={{ ...td, ...NUM, color: BB.text0 }}>{r.screener_id}</td>
                              <td style={{ ...td, fontSize: TYPE.xs }}>{r.strategy_type}</td>
                              <td style={{ ...td, ...mono, maxWidth: 340 }}>{r.finviz_url}</td>
                              <td style={{ ...td, ...NUM }}>{r.schedule}</td>
                              <td style={td}>{fmtTs(r.last_run)}</td>
                              <td style={{ ...td, ...NUM }}>{r.results_count ?? '—'}</td>
                              <td style={td}><Val v={r.execution_eligible} /></td>
                              <td style={td}><Val v={r.human_review_only} /></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {s.note && <div style={{ ...subNote, marginTop: 4 }}>{s.note}</div>}
                </div>
              )}
              {s.name === 'drive_doc_sync' && isUnknownObj(f) && (
                <div style={{ ...subNote, marginTop: 4, color: BB.amber }}>Reported honestly as unknown — no live monitor row to verify against.</div>
              )}
            </div>
          )
        })}
      </div>
    </Card>
  )
}

// ── Panel 5: Feed & tier ladder ──────────────────────────────────────────────────────────────────
function FeedTierPanel({ panel }: { panel: any }) {
  if (panel?.status === 'unknown') return <PanelDegraded panel={panel} />
  const em = panel?.entitlement_matrix || {}
  const consumers = em.consumers || {}
  const feeds = em.feed_availability || {}
  const ladder: any[] = panel?.tier_ladder ?? []
  const ok = panel?.invariant_ok
  const violations: any[] = panel?.invariant_violations ?? []

  return (
    <Card title="Feed & tier ladder" source={panel?.source}>
      {/* Invariant status */}
      <div style={{
        border: `1px solid ${ok === false ? BB.red : ok === true ? BB.green : BB.amber}`,
        background: ok === false ? BB.redDim : ok === true ? BB.greenDim : BB.amberDim,
        borderRadius: 2, padding: '8px 10px', marginBottom: 12,
      }}>
        <div style={{ fontSize: TYPE.sm, fontWeight: 800, color: ok === false ? BB.red : ok === true ? BB.green : BB.amber }}>
          {ok === true ? 'INVARIANT OK' : ok === false ? '⚠ INVARIANT VIOLATED' : 'INVARIANT UNKNOWN'}
        </div>
        <div style={{ ...subNote, marginTop: 3 }}>{panel?.invariant_definition}</div>
        {ok === false && violations.map((v, i) => (
          <div key={i} style={{ fontSize: TYPE.xs, color: BB.red, marginTop: 3, ...NUM }}>
            {(v.between || []).join('→')}: {v.field} values {(v.values || []).join(', ')} — expected {v.expected}
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 12 }}>
        {/* Tier ladder */}
        <div>
          <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: BB.text1, marginBottom: 6 }}>Tier ladder (best → worst)</div>
          <div style={scrollX}>
            <table style={{ borderCollapse: 'collapse', width: '100%' }}>
              <thead><tr>{['Tier', 'Label', 'Size mult', 'Slippage bps'].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
              <tbody>
                {ladder.map((t) => (
                  <tr key={t.tier}>
                    <td style={{ ...td, ...NUM, fontWeight: 700, color: BB.text0 }}>{t.tier}</td>
                    <td style={{ ...td, fontSize: TYPE.xs }}>{t.label}</td>
                    <td style={{ ...td, ...NUM }}><Val v={t.size_multiplier} /></td>
                    <td style={{ ...td, ...NUM }}><Val v={t.assumed_slippage_bps} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ ...subNote, marginTop: 4 }}>quality order: {(panel?.quality_order || []).join(' → ')}</div>
        </div>

        {/* Entitlement */}
        <div>
          <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: BB.text1, marginBottom: 6 }}>Entitlement matrix</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {Object.entries(consumers).map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: TYPE.xs, padding: '3px 0', borderBottom: `1px solid ${BB.borderHair}` }}>
                <span style={{ ...NUM, color: BB.text2 }}>{k}</span><span style={{ color: BB.text3, textAlign: 'right' }}>{String(v)}</span>
              </div>
            ))}
          </div>
          <div style={{ fontSize: TYPE.xs, fontWeight: 700, color: BB.text3, margin: '8px 0 3px', textTransform: 'uppercase' }}>Feed availability</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {Object.entries(feeds).map(([k, v]) => (
              <span key={k} style={metricChip()}>{k}: {String(v)}</span>
            ))}
          </div>
        </div>
      </div>
    </Card>
  )
}

// ── Panel 6: Job health ──────────────────────────────────────────────────────────────────────────
function JobHealthPanel({ panel }: { panel: any }) {
  if (panel?.status === 'unknown') return <PanelDegraded panel={panel} />
  const vp = panel?.volume_profile_coverage || {}
  const scan = panel?.scanner || {}
  const nightly = panel?.nightly_refresh || {}
  const backfill = panel?.backfill_rollup || {}
  const behind: any[] = panel?.jobs_behind_schedule ?? []
  const kv = (k: string, v: ReactNode, c?: string) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: TYPE.xs, padding: '3px 0', borderBottom: `1px solid ${BB.borderHair}` }}>
      <span style={{ color: BB.text3 }}>{k}</span><span style={{ ...NUM, color: c || BB.text1, textAlign: 'right' }}>{v}</span>
    </div>
  )
  const vpBad = (vp.symbols_below_minimum ?? 0) > 0

  return (
    <Card title="Job health" source={panel?.source}>
      {behind.length > 0 ? (
        <div style={{ marginBottom: 10 }}><Pill tone="red">{behind.length} job(s) behind schedule</Pill>
          {behind.map((b, i) => (
            <div key={i} style={{ fontSize: TYPE.xs, color: BB.red, marginTop: 3, ...NUM }}>{b.job}: {fmtAgeSec(b.age_seconds)} (expected every {fmtAgeSec(b.expected_interval_seconds)})</div>
          ))}
        </div>
      ) : (
        <div style={{ marginBottom: 10 }}><Pill tone="green">no jobs behind schedule</Pill></div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(240px,1fr))', gap: 12 }}>
        <div>
          <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: BB.text1, marginBottom: 4 }}>Volume-profile coverage</div>
          {kv('table', vp.table || '—')}
          {kv('symbols', vp.symbols ?? '—')}
          {kv('min sessions req', vp.min_sessions_required ?? '—')}
          {kv('below minimum', vp.symbols_below_minimum ?? '—', vpBad ? BB.red : BB.green)}
          {kv('newest built', fmtAgeSec(vp.newest_built_age_seconds))}
          {vpBad && <div style={{ ...subNote, color: BB.amber, marginTop: 3 }}>below-min: {(vp.symbols_below_minimum_list || []).join(', ')}</div>}
        </div>
        <div>
          <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: BB.text1, marginBottom: 4 }}>Scanner</div>
          {kv('table', scan.table || '—')}
          {kv('last run', fmtAgeSec(scan.last_run_age_seconds))}
          {kv('cadence', scan.cadence || '—')}
          <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: BB.text1, margin: '10px 0 4px' }}>Nightly refresh</div>
          {kv('job', nightly.job || '—')}
          {kv('schedule', nightly.schedule || '—')}
          {kv('last success', fmtAgeSec(nightly.last_success_age_seconds))}
        </div>
        <div>
          <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: BB.text1, marginBottom: 4 }}>Backfill / rollup</div>
          {kv('backfill days', backfill.backfill_days ?? '—')}
          {kv('lookback sessions', backfill.lookback_sessions ?? '—')}
          <div style={{ ...subNote, marginTop: 3 }}>{backfill.status}</div>
        </div>
      </div>
    </Card>
  )
}

// ── Panel 7: Execution posture ───────────────────────────────────────────────────────────────────
function ExecutionPosturePanel({ panel }: { panel: any }) {
  if (panel?.status === 'unknown') return <PanelDegraded panel={panel} />
  const flags = panel?.flags || {}
  const standing = panel?.standing_db_unlock || {}
  const accounts: any[] = panel?.broker_accounts ?? []
  const slots: any[] = panel?.credential_slots ?? []

  return (
    <Card title="Execution posture" source={panel?.source}>
      {/* Standing DB unlock — explicit scope + routable accounts */}
      <div style={{
        border: `1px solid ${standing.unlocked ? BB.amber : BB.border}`,
        background: standing.unlocked ? BB.amberDim : BB.bgShift, borderRadius: 2, padding: '8px 10px', marginBottom: 12,
      }}>
        <div style={{ fontSize: TYPE.sm, fontWeight: 800, color: standing.unlocked ? BB.amber : BB.text2 }}>
          Standing DB unlock: {standing.unlocked ? 'UNLOCKED' : 'locked'} · scope {standing.scope || 'unknown'}
        </div>
        <div style={{ fontSize: TYPE.xs, color: BB.text2, marginTop: 4, lineHeight: 1.6 }}>
          pilot armed until <span style={NUM}>{standing.pilot_armed_until || '—'}</span> · active approvals <span style={NUM}>{standing.active_approvals ?? '—'}</span><br />
          routable accounts: <span style={{ ...NUM, color: BB.text0 }}>{(standing.routable_accounts || []).join(', ') || 'none'}</span><br />
          remaining gate: <span style={{ color: BB.text1 }}>{standing.remaining_gate || '—'}</span>
        </div>
        {standing.note && <div style={{ ...subNote, marginTop: 4 }}>{standing.note}</div>}
      </div>

      {/* Flags */}
      <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: BB.text1, marginBottom: 4 }}>Flags</div>
      <div style={{ ...scrollX, marginBottom: 12 }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 620 }}>
          <thead><tr>{['Flag', 'Value', 'Source of truth', 'Last changed'].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
          <tbody>
            {Object.entries(flags).map(([name, f]: [string, any]) => (
              <tr key={name}>
                <td style={{ ...td, ...NUM, fontWeight: 700, color: BB.text0 }}>{name}</td>
                <td style={td}>{isUnknownObj(f) ? <Unknown reason={f.reason} /> : <Val v={f.value} />}</td>
                <td style={{ ...td, ...mono }}>{f.source_of_truth || '—'}</td>
                <td style={{ ...td, color: BB.text2 }}>{f.last_changed ? fmtTs(f.last_changed) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Broker accounts */}
      <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: BB.text1, marginBottom: 4 }}>Broker accounts</div>
      <div style={{ ...scrollX, marginBottom: 12 }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 640 }}>
          <thead><tr>{['Account', 'Environment', 'Enabled', 'API write', 'API read', 'Credential slot (name)'].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
          <tbody>
            {accounts.map((a) => (
              <tr key={a.account_key}>
                <td style={{ ...td, ...NUM, fontWeight: 700, color: BB.text0 }}>{a.account_key}</td>
                <td style={td}><Pill tone={a.environment === 'live' ? 'red' : 'slate'}>{a.environment}</Pill></td>
                <td style={td}><Val v={a.is_enabled} /></td>
                <td style={td}><Val v={a.api_write} /></td>
                <td style={td}><Val v={a.api_read} /></td>
                <td style={{ ...td, ...NUM, color: BB.text3 }}>{a.credential_slot_name || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Credential slots — NAME + populated ONLY, never a value */}
      <div style={{ fontSize: TYPE.sm, fontWeight: 700, color: BB.text1, marginBottom: 4 }}>
        Credential slots <span style={{ ...subNote, fontWeight: 400 }}>(name + populated only — never a value)</span>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {slots.map((s) => (
          <span key={s.name} style={{ ...metricChip(), borderColor: s.populated ? BB.green : BB.border, color: s.populated ? BB.green : BB.text3 }}>
            {s.name}: {s.populated ? 'populated' : 'empty'}
          </span>
        ))}
      </div>
      <div style={{ ...subNote, marginTop: 8 }}>
        {panel?.note} Manage / rotate secrets in{' '}
        <Link to="/system?tab=Admin" style={{ color: T.link, fontWeight: 700, textDecoration: 'none' }}>System → Admin → Secrets Manager</Link>.
        {' '}This tab never shows or accepts a secret value.
      </div>
    </Card>
  )
}

// ── Panel 8: Provenance footer ───────────────────────────────────────────────────────────────────
function ProvenanceFooter({ panel, generatedAt }: { panel: any; generatedAt?: string }) {
  const files = panel?.config_files || {}
  const clean = panel?.working_tree_clean
  return (
    <div style={{ ...panelBox, background: BB.bgShift }}>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: TYPE.sm, fontWeight: 800, color: BB.text1 }}>Provenance</span>
        <span style={metricChip()}>commit {panel?.config_commit_sha || 'unknown'}</span>
        <Pill tone={clean === true ? 'green' : clean === false ? 'amber' : 'slate'}>
          {clean === true ? 'working tree clean' : clean === false ? 'working tree DIRTY' : 'tree state unknown'}
        </Pill>
        <span style={subNote}>fetched {fmtTs(panel?.fetched_at)}{generatedAt ? ` · generated ${fmtTs(generatedAt)}` : ''}</span>
      </div>
      <div style={scrollX}>
        <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 620 }}>
          <thead><tr>{['Config file', 'Path', 'Git SHA', 'Last modified'].map((h) => <th key={h} style={th}>{h}</th>)}</tr></thead>
          <tbody>
            {Object.entries(files).map(([k, f]: [string, any]) => (
              <tr key={k}>
                <td style={{ ...td, ...NUM, color: BB.text1 }}>{k}</td>
                <td style={{ ...td, ...mono }}>{f.path}</td>
                <td style={{ ...td, ...NUM, color: BB.text2 }}>{f.git_sha || '—'}</td>
                <td style={{ ...td, color: BB.text2 }}>{fmtTs(f.last_modified)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Top-level component ──────────────────────────────────────────────────────────────────────────
const PANELS = [
  { key: 'strategy_registry', label: 'Strategy Registry' },
  { key: 'setup_taxonomy', label: 'Setup Taxonomy' },
  { key: 'criteria_matrix', label: 'Criteria Matrix' },
  { key: 'data_sources', label: 'Data Sources' },
  { key: 'feed_tier_ladder', label: 'Feed & Tiers' },
  { key: 'job_health', label: 'Job Health' },
  { key: 'execution_posture', label: 'Execution Posture' },
] as const

export default function ActiveTraderConfigTab() {
  const { data, loading, error } = useApi<any>('/api/v3/active-trader/config', 30_000)
  const [sel, setSel] = useState<string>('strategy_registry')

  if (!data) {
    return (
      <div style={{ ...panelBox, borderColor: error ? BB.red : BB.border }}>
        <div style={sectionTitle}>Active Trader — Configuration</div>
        <div style={{ fontSize: TYPE.sm, color: error ? BB.red : BB.text3, marginTop: 8 }}>
          {loading && !error ? 'Loading configuration…'
            : error ? `⚠ Config API unavailable — ${String(error).slice(0, 120)} (auto-retrying).`
            : 'No configuration data.'}
        </div>
        <div style={{ ...subNote, marginTop: 6 }}>Source: /api/v3/active-trader/config (read-only, polled every 30s)</div>
      </div>
    )
  }

  const selPanel = (data as any)[sel]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* READ-ONLY banner */}
      <div style={{ background: BB.bgShift, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '8px 12px', fontSize: TYPE.xs, color: BB.text2, lineHeight: 1.6 }}>
        <b style={{ color: BB.amber }}>READ-ONLY CONFIGURATION AUDIT.</b> Live projection of strategy YAML ‖ DB ‖ running values, data-source freshness, feed entitlements, and execution posture — no controls, no writes. Contradictions are shown verbatim, never reconciled. Secret values are never rendered.
        <span style={{ marginLeft: 8, color: BB.text3 }}>· contract {data.contract} · stage {data.stage}</span>
      </div>

      {/* db_available honesty */}
      {data.db_available === false && (
        <div style={{ background: BB.amberDim, border: `1px solid ${BB.amber}`, borderRadius: 2, padding: '8px 12px', fontSize: TYPE.sm, color: BB.text1, lineHeight: 1.5 }}>
          <b style={{ color: BB.amber }}>Config DB unavailable this fetch.</b> DB-backed panels degrade to "unknown"; git/YAML-derived panels (config files, tier ladder, provenance) are still valid.
        </div>
      )}

      {/* Panel selector */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {PANELS.map((p) => {
          const active = sel === p.key
          const panelObj = (data as any)[p.key]
          const degraded = panelObj?.status === 'unknown'
          return (
            <button key={p.key} type="button" onClick={() => setSel(p.key)} style={{
              fontSize: TYPE.xs, fontWeight: active ? 800 : 600, padding: '4px 10px', borderRadius: 2, cursor: 'pointer',
              border: `1px solid ${active ? BB.amber : BB.border}`, background: active ? BB.amberDim : BB.bgShift,
              color: degraded ? BB.red : active ? BB.amber : BB.text3, letterSpacing: '.04em', textTransform: 'uppercase',
            }}>{p.label}{degraded ? ' ⚠' : ''}</button>
          )
        })}
      </div>

      {/* Active panel */}
      {sel === 'strategy_registry' && <StrategyRegistryPanel panel={selPanel} />}
      {sel === 'setup_taxonomy' && <SetupTaxonomyPanel panel={selPanel} />}
      {sel === 'criteria_matrix' && <CriteriaMatrixPanel panel={selPanel} />}
      {sel === 'data_sources' && <DataSourcesPanel panel={selPanel} />}
      {sel === 'feed_tier_ladder' && <FeedTierPanel panel={selPanel} />}
      {sel === 'job_health' && <JobHealthPanel panel={selPanel} />}
      {sel === 'execution_posture' && <ExecutionPosturePanel panel={selPanel} />}

      {/* Provenance footer — always visible */}
      <ProvenanceFooter panel={data.provenance} generatedAt={data.generated_at} />
    </div>
  )
}

import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import SoulEditor from './HermesSoulEditor'

// Hermes global-profile management panel (Command Center → System → Hermes).
// Read-only status + safe SOUL/identity editing (shared HermesSoulEditor). Never enables the sidecar gateway.

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button onClick={() => { navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1200) }}
      style={{ marginLeft: 8, fontSize: 10, padding: '1px 6px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg2)', color: 'var(--text3)', cursor: 'pointer' }}>
      {done ? '✓' : 'copy'}
    </button>
  )
}

// One self-learning loop row + on-demand drill-down (process steps, queue/completed, recent items + timestamps).
function LoopRow({ loop, expanded, onToggle }: { loop: any; expanded: boolean; onToggle: () => void }) {
  const { data: detail } = useApi<any>(expanded ? `/api/v2/hermes/loop-detail?loop=${loop.loop}` : '', 60_000)
  const sc = loop.affects_scoring === true ? '#ef4444' : loop.affects_scoring === 'gated' ? '#f59e0b' : 'var(--text3)'
  return (
    <>
      <tr onClick={onToggle} style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
        <td style={{ padding: '3px 6px', color: 'var(--text3)' }}>{expanded ? '▾' : '▸'}</td>
        <td style={{ padding: '3px 6px', fontWeight: 600 }}>{loop.loop}{loop.affects_scoring ? <span style={{ color: sc, fontSize: 9 }} title={`This loop affects scoring (${loop.affects_scoring}) — operator-gated; not auto-applied`}> ⚑scoring</span> : null}</td>
        <td style={{ padding: '3px 6px', color: 'var(--text3)' }}>{loop.what_learned}</td>
        <td style={{ padding: '3px 6px' }}>{loop.rows ?? '—'}</td>
        <td style={{ padding: '3px 6px', color: loop.queued ? '#f59e0b' : 'var(--text3)' }}>{loop.queued ?? '—'}</td>
        <td style={{ padding: '3px 6px', color: '#22c55e' }}>{loop.completed ?? (loop.rows ?? '—')}</td>
        <td style={{ padding: '3px 6px', color: 'var(--text3)', fontSize: 10 }}>{(loop.last || '').slice(0, 16) || '—'}</td>
      </tr>
      {expanded && (
        <tr><td colSpan={7} style={{ padding: '4px 10px 10px', background: 'var(--bg2)' }}>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 4 }}>
            Process: {(detail?.process_steps || loop.process_steps || []).map((s: string, i: number) => (
              <span key={i}>{i > 0 ? ' → ' : ''}<b style={{ color: 'var(--text1)' }}>{s}</b></span>
            ))}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 4 }}>
            table <code>{loop.table}</code> · {loop.advisory_only ? 'advisory-only' : 'NON-advisory'} ·
            scoring: <b style={{ color: sc }}>{String(loop.affects_scoring)}</b>{loop.affects_scoring ? ' (operator-gated)' : ''}
          </div>
          {!detail ? <div style={{ fontSize: 10, color: 'var(--text3)' }}>loading recent items…</div> : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
              <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
                {Object.keys((detail.recent_items || [{}])[0] || {}).map(h => <th key={h} style={{ padding: '2px 6px' }}>{h}</th>)}
              </tr></thead>
              <tbody>
                {(detail.recent_items || []).map((it: any, i: number) => (
                  <tr key={i}>{Object.values(it).map((v: any, j: number) => (
                    <td key={j} style={{ padding: '2px 6px', color: 'var(--text3)', whiteSpace: 'nowrap' }}>{String(v ?? '—').slice(0, 28)}</td>
                  ))}</tr>
                ))}
                {(detail.recent_items || []).length === 0 && <tr><td style={{ padding: '2px 6px', color: 'var(--text3)' }}>no items yet</td></tr>}
              </tbody>
            </table>
          )}
        </td></tr>
      )}
    </>
  )
}

export default function HermesPanel() {
  const { data: st } = useApi<any>('/api/v2/hermes/profiles-status', 60_000)
  const { data: tc } = useApi<any>('/api/v2/hermes/terminal-commands', 300_000)
  const { data: codex } = useApi<any>('/api/v2/hermes/codex-dev-status', 120_000)
  const { data: legacy } = useApi<any>('/api/v2/hermes/legacy-agents', 300_000)
  const { data: wfm } = useApi<any>('/api/v2/hermes/workflow-matrix', 300_000)
  const { data: sll } = useApi<any>('/api/v2/hermes/self-learning-loops', 300_000)
  const { data: rmx } = useApi<any>('/api/v2/hermes/researcher-matrix', 300_000)
  const { data: auth } = useApi<any>('/api/v2/hermes/llm-auth-status', 120_000)
  const { data: retry } = useApi<any>('/api/v2/system/llm-retry-health', 300_000)
  const { data: smat } = useApi<any>('/api/v2/hermes/source-maturity', 300_000)
  const { data: ccal } = useApi<any>('/api/v2/hermes/catalyst-calibration', 300_000)
  const { data: pa } = useApi<any>('/api/v2/pro-analyst/pills', 300_000)
  const { data: wd } = useApi<any>('/api/v2/watch-directives', 120_000)
  const { data: gov } = useApi<any>('/api/v2/hermes/research-governance', 120_000)
  const [editProfile, setEditProfile] = useState<string | null>(null)
  const [openLoop, setOpenLoop] = useState<string | null>(null)

  const card: React.CSSProperties = { background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, marginBottom: 14 }
  const kv: React.CSSProperties = { fontSize: 12, color: 'var(--text3)' }
  const gwActive = (st?.gateway_service_active || '').toLowerCase()
  const gwOk = gwActive !== 'active'

  return (
    <div>
      {editProfile && <SoulEditor profile={editProfile} onClose={() => setEditProfile(null)} />}

      {/* Status card */}
      <div style={card}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>Hermes Global Profiles</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))', gap: 6 }}>
          <div style={kv}>Version: <b style={{ color: 'var(--text1)' }}>{st?.version || '…'}</b></div>
          <div style={kv}>CLI: <code>{st?.cli_path}</code></div>
          <div style={kv}>venv: <code>{st?.venv_path}</code></div>
          <div style={kv}>home: <code>{st?.home_path}</code></div>
          <div style={kv}>Old sidecar: <span style={{ color: '#f59e0b' }}>{st?.sidecar_status}</span></div>
          <div style={kv}>Gateway service: <b style={{ color: gwOk ? '#22c55e' : '#ef4444' }}>{st?.gateway_service_active} / {st?.gateway_service_enabled}</b></div>
        </div>
        {st?.sidecar_retired_dirs?.length > 0 && <div style={{ ...kv, marginTop: 6 }}>Retired dirs: {st.sidecar_retired_dirs.join(', ')}</div>}
        <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 6 }}>⚠ {st?.gateway_note}</div>
      </div>

      {/* Research Governance (read-only) — research scope by tier/lane + budget posture */}
      {gov && (
        <div style={{ ...card, borderColor: gov.status === 'WARN' ? '#f59e0b' : 'var(--border)' }}>
          <div style={{ fontWeight: 700, marginBottom: 6 }}>
            Hermes Research Governance {gov.status === 'WARN' && <span style={{ color: '#f59e0b', fontSize: 11 }}>⚠ WARN</span>}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 8 }}>
            30d: <b style={{ color: 'var(--text1)' }}>{gov.windows?.['30d']?.total_calls}</b> research calls ·
            external {gov.windows?.['30d']?.external_distinct_symbols} symbols ·
            local GPU {gov.local_gpu_calls_30d} calls · 1d: {gov.windows?.['1d']?.external_distinct_symbols} symbols
          </div>
          {/* By tier */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(120px,1fr))', gap: 6, marginBottom: 8 }}>
            {Object.entries(gov.by_tier || {}).map(([t, v]: any) => (
              <div key={t} style={{ ...kv, background: t === 'T3' ? 'rgba(245,158,11,.10)' : 'var(--bg1)', borderRadius: 6, padding: '4px 8px' }}>
                <b style={{ color: t === 'T3' ? '#f59e0b' : 'var(--text1)' }}>{t}</b>: {v.calls} calls / {v.symbols} sym
              </div>
            ))}
          </div>
          {/* Lanes */}
          <div style={{ fontSize: 11, marginBottom: 6 }}>
            Lanes (30d): {Object.entries(gov.llm_by_lane || {}).map(([l, n]: any) => (
              <span key={l} style={{ marginRight: 10, color: l === 'cloud_paid' ? '#ef4444' : 'var(--text3)' }}>
                {l}=<b style={{ color: 'var(--text1)' }}>{n}</b>
              </span>
            ))}
          </div>
          {/* Posture */}
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>
            broad-universe LLM: <b style={{ color: '#22c55e' }}>{gov.policy?.broad_universe_llm}</b> ·
            paid fallback: <b style={{ color: '#22c55e' }}>{gov.policy?.paid_fallback}</b> ·
            market-hours 27B/31B: <b style={{ color: '#22c55e' }}>{gov.policy?.market_hours_local_heavy}</b>
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>
            duplicate: <b style={{ color: '#f59e0b' }}>{gov.duplicate?.redundant_calls}</b> redundant calls ({gov.duplicate?.pct_of_external}%) ·
            no-trigger: {gov.no_active_trigger?.researched_with_no_trigger}/{gov.no_active_trigger?.researched_distinct_30d} ·
            stale &gt;30d: {gov.stale?.stale_gt30d || 0} sym
          </div>
          {/* Top expensive sources */}
          {gov.top_expensive_sources?.length > 0 && (
            <details style={{ fontSize: 11 }}>
              <summary style={{ cursor: 'pointer', color: 'var(--text3)' }}>Top expensive sources</summary>
              <table style={{ width: '100%', fontSize: 10, marginTop: 6, borderCollapse: 'collapse' }}>
                <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
                  <th>Source</th><th>Lane</th><th>Calls</th><th>Symbols</th><th>Cost</th></tr></thead>
                <tbody>
                  {gov.top_expensive_sources.slice(0, 10).map((e: any, i: number) => (
                    <tr key={i} style={{ borderTop: '1px solid var(--border)' }}>
                      <td>{e.source}</td><td>{e.lane}</td><td>{e.calls}</td><td>{e.symbols}</td><td>{e.cost_units}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6 }}>{gov.note}</div>
        </div>
      )}

      {/* Workflow Matrix (Phase 209, read-only) */}
      {wfm && (
        <div style={card}>
          <div style={{ fontWeight: 700, marginBottom: 6 }}>Workflow Matrix — who owns what</div>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 6 }}>
            {wfm.workflow_count} workflows · {wfm.graph_nodes?.length || 0} graph nodes · {wfm.db_lineage?.length || 0} DB tables · {wfm.safe_views_count} safe views ·
            CLI profile used by automation: <b style={{ color: wfm.any_cli_profile_in_jobs ? '#ef4444' : '#22c55e' }}>{String(!!wfm.any_cli_profile_in_jobs)}</b>
          </div>
          <div style={{ fontSize: 11, marginBottom: 4 }}>🔎 <b>Who owns Librarian?</b> <span style={{ color: 'var(--text3)' }}>{wfm.quick_answers?.who_owns_librarian}</span></div>
          <div style={{ fontSize: 11, marginBottom: 4 }}>🔎 <b>tradeai vs tradeai12b:</b> <span style={{ color: 'var(--text3)' }}>{wfm.quick_answers?.tradeai_vs_tradeai12b}</span></div>
          <div style={{ fontSize: 11, marginBottom: 8 }}>🔎 <b>tradeai12b automated?</b> <span style={{ color: 'var(--text3)' }}>{wfm.quick_answers?.tradeai12b_automated}</span></div>
          {(wfm.db_lineage || []).filter((t: any) => t.exists).length > 0 && (
            <div style={{ fontSize: 10, color: 'var(--text3)' }}>DB writes/24h: {(wfm.db_lineage || []).filter((t: any) => t.exists && t.writes_24h).map((t: any) => `${t.table.replace('hermes_', '')}=${t.writes_24h}`).join(' · ')}</div>
          )}
        </div>
      )}

      {/* LLM Auth / OAuth status (read-only; guided login — no credential entry) */}
      {auth && (
        <div style={card}>
          <div style={{ fontWeight: 700, marginBottom: 6 }}>LLM Auth / OAuth</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
              {['Lane', 'Type', 'Status', 'Login (run in terminal)'].map(h => <th key={h} style={{ padding: '3px 6px', borderBottom: '1px solid var(--border)' }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {(auth.lanes || []).map((l: any) => (
                <tr key={l.provider} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '4px 6px', fontWeight: 600 }}>{l.lane}</td>
                  <td style={{ padding: '4px 6px', color: 'var(--text3)' }}>{l.kind}</td>
                  <td title={`${l.lane}: ${l.usable ? 'ready for use' : l.authed ? 'authenticated but the OAuth proxy is not running' : 'not authenticated — run the login command'}${l.reason_code ? ' (' + l.reason_code + ')' : ''}`} style={{ padding: '4px 6px', color: l.usable ? '#22c55e' : l.authed ? '#f59e0b' : '#f59e0b', fontWeight: 600 }}>{l.usable ? '✓ ready' : l.authed ? 'authed · needs proxy' : 'auth pending'}</td>
                  <td style={{ padding: '4px 6px', fontFamily: 'monospace', fontSize: 10 }}>{l.login_command !== '(none — local gemma3 via Ollama)' && <>{l.login_command}<Copy text={l.login_command} /></>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {auth.proxy && (
            <div style={{ fontSize: 10, marginTop: 6 }}>
              <span style={{ color: 'var(--text3)' }}>OAuth proxy (:8645): </span>
              <b style={{ color: auth.proxy.running ? '#22c55e' : '#ef4444' }}>{auth.proxy.running ? 'UP' : 'DOWN'}</b>
              {auth.proxy.needed_by?.length > 0 && <span style={{ color: 'var(--text3)' }}> · used by {auth.proxy.needed_by.join(', ')}</span>}
              {auth.proxy.warning && <span style={{ color: '#ef4444' }}> · ⚠ {auth.proxy.warning} (<code>{auth.proxy.start_command}</code>)</span>}
            </div>
          )}
          <div style={{ fontSize: 10, color: '#60a5fa', marginTop: 6 }}>🔐 {auth.google_sso_note}</div>
          {retry?.last_24h && (
            <div style={{ fontSize: 10, marginTop: 5, color: 'var(--text3)' }}>
              LLM resilience (24h): <b style={{ color: retry.status === 'DEGRADED' ? '#ef4444' : retry.status === 'ELEVATED' ? '#f59e0b' : '#22c55e' }}>{retry.status}</b>
              {' '}· {retry.last_24h.incidents} transient retries · {retry.last_24h.recovered} recovered · <span style={{ color: retry.last_24h.gave_up > 0 ? '#ef4444' : 'var(--text3)' }}>{retry.last_24h.gave_up} gave up</span>
              {(retry.notes || []).length > 0 && <span style={{ color: '#f59e0b' }}> · {retry.notes.join('; ')}</span>}
            </div>
          )}
        </div>
      )}

      {/* Source Maturity board (Gate 1-5, read-only) */}
      {smat?.top_sources && (
        <div style={card}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Source Maturity</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 4 }}>
            tiers: {Object.entries(smat.tier_counts || {}).map(([t, n]: any) => `${t}:${n}`).join(' · ')} · {smat.source_count} sources
            {smat.operator_actions?.length > 0 && <span style={{ color: '#f59e0b' }}> · {smat.operator_actions.length} operator action(s)</span>}
          </div>
          {smat.attribution_health?.overlap_pct != null && (
            <div style={{ fontSize: 10, marginBottom: 6, color: 'var(--text3)' }}>
              attribution: news↔trade overlap <b style={{ color: smat.attribution_health.overlap_pct >= 70 ? '#22c55e' : '#f59e0b' }}>{smat.attribution_health.overlap_pct}%</b>
              {' '}({smat.attribution_health.traded_with_news_7d}/{smat.attribution_health.traded_30d}) ·
              attributions <b>{smat.attribution_health.total_attributions}</b> ·
              status <b style={{ color: smat.attribution_health.status === 'HEALTHY' ? '#22c55e' : smat.attribution_health.status === 'STALLED' ? '#ef4444' : '#f59e0b' }}>{smat.attribution_health.status}</b>
              {(smat.attribution_health.notes || []).length > 0 && <span style={{ color: '#f59e0b' }}> — {smat.attribution_health.notes.join('; ')}</span>}
            </div>
          )}
          {(smat.attribution_health?.recent_tier_transitions || []).length > 0 && (
            <div style={{ fontSize: 10, marginBottom: 6, color: 'var(--text3)' }}>
              recent tier moves: {smat.attribution_health.recent_tier_transitions.slice(0, 5).map((t: any, i: number) => (
                <span key={i} style={{ color: t.direction === 'promotion' ? '#22c55e' : '#ef4444' }}>{i > 0 ? ' · ' : ''}{t.direction === 'promotion' ? '↑' : '↓'}{t.source.slice(0, 16)} {t.from}→{t.to}</span>
              ))}
            </div>
          )}
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
              {['Source', 'Tier', 'Score', 'Go-rate', 'Signals', 'Trades'].map(h => <th key={h} style={{ padding: '3px 6px', borderBottom: '1px solid var(--border)' }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {smat.top_sources.slice(0, 12).map((s: any) => (
                <tr key={s.source} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '3px 6px', fontFamily: 'monospace' }}>{s.source.slice(0, 26)}</td>
                  <td title={`Maturity tier: ${s.tier} (score ${s.maturity_score}) — core=operator-trusted, trusted/probationary=earning trust, candidate=unvetted, demoted=noise. Advisory; scales catalyst confidence.`} style={{ padding: '3px 6px', fontWeight: 600, color: s.tier === 'core' ? '#22c55e' : s.tier === 'trusted' ? '#14b8a6' : s.tier === 'demoted' ? '#ef4444' : 'var(--text3)' }}>{s.tier}</td>
                  <td style={{ padding: '3px 6px' }}>{s.maturity_score}</td>
                  <td style={{ padding: '3px 6px', color: 'var(--text3)' }}>{(s.go_rate * 100).toFixed(1)}%</td>
                  <td style={{ padding: '3px 6px', color: 'var(--text3)' }}>{s.total_signals}</td>
                  <td style={{ padding: '3px 6px', color: s.outcome_proven ? '#22c55e' : 'var(--text3)' }}>{s.trades_matched || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 5 }}>ℹ {smat.note}</div>
        </div>
      )}

      {/* Operator Watch Directives (advisory; Trade AI + Hermes honor, firewall) */}
      {wd && (
        <div style={card}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Operator Watch Directives</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>
            {wd.directive_count} active · promoted to watched universe: {wd.promoted_to_watchlist} · Hermes staging: {wd.hermes_staging?.undrained || 0} undrained
          </div>
          {wd.health?.status && (
            <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>
              servicing: <b style={{ color: wd.health.status === 'ACTIVE' ? '#22c55e' : wd.health.status === 'STALLED' ? '#ef4444' : 'var(--text2)' }}>{wd.health.status}</b>
              {' '}· {wd.health.hits_24h} hits/24h{wd.health.by_status_24h ? ' (' + Object.entries(wd.health.by_status_24h).map(([k, v]: any) => `${v} ${k.toLowerCase().replace('_', ' ')}`).join(', ') + ')' : ''}
              {' '}· {wd.health.promoted_total} promoted
              {(wd.health.notes || []).length > 0 && <span style={{ color: '#f59e0b' }}> · {wd.health.notes.join('; ')}</span>}
            </div>
          )}
          {wd.directive_count === 0 ? (
            <div style={{ fontSize: 10, color: 'var(--text3)' }}>No directives yet. Operator adds ticker/sector/trend directives → Trade AI + Hermes honor them (Hermes proposes via staging only).</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
              <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>{['Directive', 'Kind', 'TA', 'Hermes', 'Last serviced'].map(h => <th key={h} style={{ padding: '3px 6px', borderBottom: '1px solid var(--border)' }}>{h}</th>)}</tr></thead>
              <tbody>{wd.directives.slice(0, 8).map((d: any) => (
                <tr key={d.id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '3px 6px', fontWeight: 600 }}>{d.label}</td>
                  <td style={{ padding: '3px 6px', color: 'var(--text3)' }}>{d.kind}</td>
                  <td style={{ padding: '3px 6px', color: d.trade_ai_enabled ? '#22c55e' : 'var(--text3)' }}>{d.trade_ai_enabled ? '✓' : '—'}</td>
                  <td style={{ padding: '3px 6px', color: d.hermes_enabled ? '#22c55e' : 'var(--text3)' }}>{d.hermes_enabled ? '✓' : '—'}</td>
                  <td style={{ padding: '3px 6px', color: 'var(--text3)', fontSize: 10 }}>{(d.last_serviced_at || '—').slice(0, 16)}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
          {(wd.recent_hits || []).length > 0 && (
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 5 }}>recent hits: {wd.recent_hits.slice(0, 6).map((h: any) => `${h.symbol}(${h.surfaced_by})`).join(' · ')}</div>
          )}
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 5 }}>ℹ {wd.note}</div>
        </div>
      )}

      {/* Professional Analyst Layer (Gate A, advisory) */}
      {pa?.pills && (
        <div style={card}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Professional Analyst Consensus <span style={{ fontSize: 9, color: 'var(--text3)' }}>(advisory · Yahoo)</span></div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>
            {pa.with_consensus} symbols with Street consensus · coverage: {Object.entries(pa.coverage_by_tier || {}).map(([t, v]: any) => `${t} ${v.pct}%`).join(' · ')}
            {(pa.divergent || []).length > 0 && <span style={{ color: '#f59e0b' }}> · divergent: {pa.divergent.join(', ')}</span>}
          </div>
          {pa.coverage_health?.coverage_pct != null && (
            <div style={{ fontSize: 10, marginBottom: 6, color: 'var(--text3)' }}>
              coverage trend: <b style={{ color: pa.coverage_health.status === 'EXPANDING' ? '#22c55e' : pa.coverage_health.status === 'REGRESSED' ? '#ef4444' : 'var(--text2)' }}>{pa.coverage_health.status}</b>
              {' '}· {pa.coverage_health.coverage_pct}% ({pa.coverage_health.with_consensus} symbols){pa.coverage_health.stale > 0 ? ` · ${pa.coverage_health.stale} stale` : ''}
              {(pa.coverage_health.notes || []).length > 0 && <span style={{ color: '#22c55e' }}> · {pa.coverage_health.notes.join('; ')}</span>}
            </div>
          )}
          {pa.coverage_health?.comparable != null && (
            <div style={{ fontSize: 10, marginBottom: 6, color: 'var(--text3)' }}>
              divergence (internal vs Street): {pa.coverage_health.comparable} comparable ·
              {' '}<span style={{ color: '#22c55e' }}>{pa.coverage_health.divergence_counts?.aligned || 0} aligned</span> ·
              {' '}<span style={{ color: '#ef4444' }}>{pa.coverage_health.divergent || pa.coverage_health.divergence_counts?.divergent || 0} divergent</span>
              {Object.keys(pa.coverage_health.divergent_symbols || {}).length > 0 && <span style={{ color: '#ef4444' }}> ⚡ {Object.entries(pa.coverage_health.divergent_symbols).map(([s, v]: any) => `${s} (${v.internal}↔${v.street})`).join(', ')} — review</span>}
            </div>
          )}
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
              {['Symbol', 'Street', 'Analysts', 'Mean target', 'Upside', 'Internal', 'Divergence'].map(h => <th key={h} style={{ padding: '3px 6px', borderBottom: '1px solid var(--border)' }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {pa.pills.slice(0, 12).map((p: any) => (
                <tr key={p.symbol} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '3px 6px', fontFamily: 'monospace', fontWeight: 600 }}>{p.symbol}{p.stale && <span title="stale >7d" style={{ color: '#f59e0b' }}> ⚠</span>}</td>
                  <td style={{ padding: '3px 6px', fontWeight: 600, color: (p.recommendation_key || '').includes('buy') ? '#22c55e' : (p.recommendation_key || '').includes('sell') ? '#ef4444' : 'var(--text2)' }}>{p.recommendation_key || '—'}</td>
                  <td style={{ padding: '3px 6px', color: 'var(--text3)' }}>{p.number_of_analyst_opinions || '—'}</td>
                  <td style={{ padding: '3px 6px', color: 'var(--text3)' }}>{p.target_mean_price != null ? '$' + p.target_mean_price : '—'}</td>
                  <td style={{ padding: '3px 6px', color: (p.upside_to_mean_target_pct ?? 0) > 0 ? '#22c55e' : '#ef4444' }}>{p.upside_to_mean_target_pct != null ? p.upside_to_mean_target_pct + '%' : '—'}</td>
                  <td style={{ padding: '3px 6px', color: 'var(--text3)' }}>{p.internal_direction || '—'}</td>
                  <td style={{ padding: '3px 6px', color: p.divergence === 'divergent' ? '#ef4444' : p.divergence === 'aligned' ? '#22c55e' : 'var(--text3)' }}>{p.divergence}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 5 }}>ℹ {pa.note} Microcaps/ETFs without coverage show as "no professional coverage" (info, not failure).</div>
        </div>
      )}

      {/* Catalyst Calibration (read-only, sharpening trend) */}
      {ccal?.by_type && (
        <div style={card}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Catalyst Calibration</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>
            {ccal.credible_samples} credible samples · {ccal.trusted_type_count} trusted types · settle {ccal.settle_days}d
            {(ccal.recent_transitions || []).length > 0 && <span style={{ color: '#22c55e' }}> · {ccal.recent_transitions.length} recent move(s)</span>}
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
              {['Catalyst type', 'Samples', 'Hit-rate', 'Multiplier', 'Trusted'].map(h => <th key={h} style={{ padding: '3px 6px', borderBottom: '1px solid var(--border)' }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {ccal.by_type.slice(0, 10).map((t: any) => (
                <tr key={t.catalyst_type} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '3px 6px', fontFamily: 'monospace' }}>{t.catalyst_type}</td>
                  <td style={{ padding: '3px 6px', color: 'var(--text3)' }}>{t.samples}</td>
                  <td style={{ padding: '3px 6px', color: 'var(--text3)' }}>{t.hit_rate != null ? (t.hit_rate * 100).toFixed(0) + '%' : '—'}</td>
                  <td title={`Calibration multiplier: scales this catalyst type's impact by ${t.weight_multiplier}× based on realized 2-day moves (hit-rate ${t.hit_rate != null ? (t.hit_rate * 100).toFixed(0) + '%' : 'n/a'}, ${t.samples} samples). >1 boosts, <1 dampens.`} style={{ padding: '3px 6px', fontWeight: 600, color: t.weight_multiplier >= 1.05 ? '#22c55e' : t.weight_multiplier <= 0.85 ? '#ef4444' : 'var(--text2)' }}>{t.weight_multiplier?.toFixed(2)}×</td>
                  <td style={{ padding: '3px 6px', color: t.trusted ? '#22c55e' : 'var(--text3)' }}>{t.trusted ? '✓' : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 5 }}>ℹ {ccal.note}</div>
        </div>
      )}

      {/* Self-Learning + Research Lanes (Phase 210, read-only) */}
      {(sll || rmx) && (
        <div style={card}>
          <div style={{ fontWeight: 700, marginBottom: 6 }}>Self-Learning & Research Lanes</div>
          {sll && (
            <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 6 }}>
              Closed-loop: <b style={{ color: '#f59e0b' }}>{(sll.closed_loop_status || '').split('—')[0]}</b> ·
              {sll.loop_count} loops · {sll.advisory_only_loops} advisory-only · {sll.loops_affecting_prompts} feed prompts ·
              <b style={{ color: '#22c55e' }}> {sll.loops_affecting_scoring_directly} mutate scoring</b> (operator-gated)
            </div>
          )}
          {/* per-loop drill-down: process steps, queue/completed, recent items + timestamps */}
          {sll?.loops && (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, margin: '4px 0 8px' }}>
              <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
                {['', 'Loop', 'Learns', 'Total', 'Queued', 'Done', 'Last'].map(h => <th key={h} style={{ padding: '3px 6px', borderBottom: '1px solid var(--border)' }}>{h}</th>)}
              </tr></thead>
              <tbody>
                {sll.loops.map((l: any) => (
                  <LoopRow key={l.loop} loop={l} expanded={openLoop === l.loop} onToggle={() => setOpenLoop(openLoop === l.loop ? null : l.loop)} />
                ))}
              </tbody>
            </table>
          )}
          {rmx && (
            <div style={{ fontSize: 11, color: 'var(--text3)' }}>
              Internal deep lane: <b>{rmx.internal_deep_research_lane?.model}</b> ({rmx.internal_deep_research_lane?.status}) ·
              gemma4 {rmx.internal_deep_research_lane?.gemma4} · External lanes: {(rmx.external_lanes || []).map((l: any) => l.lane.split(' ')[0]).join(', ')} (designed, advisory-only)
            </div>
          )}
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 6 }}>ℹ Hermes self-learns to improve TradeAI: observe→normalize→evaluate→learn→promote→apply. Scoring changes require a separate operator gate. Read-only. Click a loop to drill into its steps, queue/completed, and recent items.</div>
        </div>
      )}

      {/* Profile matrix */}
      <div style={card}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>Profiles</div>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
            {['Profile', 'Model', 'Tools', 'Status', 'Purpose', 'Actions'].map(h => <th key={h} style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>{h}</th>)}
          </tr></thead>
          <tbody>
            {(st?.profiles || []).map((p: any) => (
              <tr key={p.profile} style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '6px 8px', fontWeight: 600 }}>{p.profile}</td>
                <td style={{ padding: '6px 8px' }}><code>{p.model}</code></td>
                <td style={{ padding: '6px 8px', color: /enabled:/.test(p.tools) ? '#f59e0b' : p.tools === 'disabled' ? '#22c55e' : 'var(--text3)' }}>{p.tools}</td>
                <td style={{ padding: '6px 8px' }}>{p.status}</td>
                <td style={{ padding: '6px 8px', color: 'var(--text3)' }}>{p.purpose}</td>
                <td style={{ padding: '6px 8px' }}>
                  <button onClick={() => setEditProfile(p.profile)} style={{ fontSize: 11, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg1)', color: '#60a5fa', cursor: 'pointer' }}>Edit Identity</button>
                  {p.soul_hash && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }} title={p.soul_mtime ? `modified ${new Date(p.soul_mtime * 1000).toLocaleString()}` : ''}>SOUL {p.soul_hash}{p.soul_mtime ? ` · ${new Date(p.soul_mtime * 1000).toLocaleDateString()}` : ''}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {st?.tools_note && <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 8 }}>ℹ {st.tools_note}</div>}
      </div>

      {/* Legacy / Retired Agents — read-only audit (Phase 206) */}
      <div style={{ ...card, border: '1px solid rgba(239,68,68,.3)', background: 'rgba(239,68,68,.05)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Legacy / Retired Agents — Read Only</div>
          <span style={{ fontSize: 9, color: 'var(--text3)' }}>
            {(legacy?.total ?? 0)} items · gateway {legacy?.gateway_service_active}/{legacy?.gateway_service_enabled} · scanned {legacy?.scanned_at ? new Date(legacy.scanned_at).toLocaleString() : '—'}
          </span>
        </div>
        <div style={{ fontSize: 10, color: '#ef4444', marginBottom: 8, fontWeight: 600 }}>
          ⚠ Retired sidecar artifacts are shown for audit only. Do not enable the retired gateway or execute retired wrappers.
        </div>
        {!legacy ? <div style={{ fontSize: 11, color: 'var(--text3)' }}>Loading legacy inventory…</div> :
         (legacy.items || []).filter((i: any) => i.status !== 'ACTIVE_PROFILE').length === 0 ?
         <div style={{ fontSize: 11, color: 'var(--text3)' }}>No retired agent artifacts found.</div> : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
              {['Name', 'Source', 'Classification', 'Model', 'Tools', 'Purpose / Safety', 'Modified', 'Recommendation'].map(h =>
                <th key={h} style={{ padding: '4px 6px', borderBottom: '1px solid var(--border)' }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {(legacy.items || []).filter((i: any) => i.status !== 'ACTIVE_PROFILE').map((i: any, idx: number) => {
                const danger = i.status === 'RETIRED_WRAPPER' || i.status === 'UNSAFE_RUNTIME_ARTIFACT'
                const tools = i.tools && (i.tools.toolsets || i.tools.disabled_toolsets)
                  ? `ts:${JSON.stringify(i.tools.toolsets ?? [])}` : '—'
                return (
                  <tr key={idx} style={{ borderBottom: '1px solid var(--border)', opacity: 0.92 }}>
                    <td style={{ padding: '5px 6px', fontFamily: 'monospace' }}>{i.name}</td>
                    <td style={{ padding: '5px 6px', color: 'var(--text3)', fontSize: 9 }}>{i.source_dir}</td>
                    <td style={{ padding: '5px 6px', color: danger ? '#ef4444' : '#f59e0b', fontWeight: 600 }}>{i.status}</td>
                    <td style={{ padding: '5px 6px' }}>{i.model ? <code>{i.model}</code> : '—'}</td>
                    <td style={{ padding: '5px 6px', color: 'var(--text3)' }}>{tools}</td>
                    <td style={{ padding: '5px 6px', color: 'var(--text3)' }}>{i.purpose || i.safety_note}</td>
                    <td style={{ padding: '5px 6px', color: 'var(--text3)', fontSize: 9 }}>{i.last_modified ? new Date(i.last_modified).toLocaleDateString() : '—'}</td>
                    <td style={{ padding: '5px 6px', color: danger ? '#ef4444' : 'var(--text2)' }}>{i.migration_recommendation}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8 }}>
          Source: /api/v2/hermes/legacy-agents · read-only · no enable/run/edit · secrets redacted · runtime-state contents not exposed.
        </div>
      </div>

      {/* Terminal commands */}
      <div style={card}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>How to call Hermes from terminal</div>
        {(tc?.chat || []).map((c: string) => (
          <div key={c} style={{ fontFamily: 'monospace', fontSize: 12, marginBottom: 3 }}>{c}<Copy text={c} /></div>
        ))}
        <div style={{ fontWeight: 600, fontSize: 11, color: 'var(--text3)', margin: '8px 0 4px' }}>Diagnostics</div>
        {(tc?.diagnostics || []).map((c: string) => (
          <div key={c} style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text3)', marginBottom: 2 }}>{c}<Copy text={c} /></div>
        ))}
        <div style={{ fontSize: 10, color: '#ef4444', marginTop: 8 }}>⚠ {tc?.warning}</div>
      </div>

      {/* Codex dev */}
      <div style={card}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>ChatGPT / Codex Dev Profile</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 6, marginBottom: 8 }}>
          <div style={kv}>dev profile exists: <b>{String(codex?.dev_profile_exists)}</b></div>
          <div style={kv}>dev SOUL exists: <b>{String(codex?.dev_soul_exists)}</b></div>
          <div style={kv}>dev model configured: <b>{String(codex?.dev_model_configured)}</b></div>
          <div style={kv}>Codex auth: <b>{codex?.codex_auth_configured}</b></div>
          <div style={kv}>Codex runtime enabled: <b style={{ color: '#22c55e' }}>{String(codex?.codex_runtime_enabled)}</b></div>
        </div>
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 6, padding: 10 }}>
          {(codex?.terminal_instructions || []).map((l: string, i: number) => (
            <div key={i} style={{ fontFamily: 'monospace', fontSize: 11, color: l.startsWith('#') ? 'var(--text3)' : 'var(--text1)' }}>{l}</div>
          ))}
        </div>
        <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 8 }}>ℹ {codex?.note}</div>
      </div>
    </div>
  )
}

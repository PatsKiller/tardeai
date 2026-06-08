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
        <td style={{ padding: '3px 6px', fontWeight: 600 }}>{loop.loop}{loop.affects_scoring ? <span style={{ color: sc, fontSize: 9 }}> ⚑scoring</span> : null}</td>
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
  const { data: smat } = useApi<any>('/api/v2/hermes/source-maturity', 300_000)
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
                  <td style={{ padding: '4px 6px', color: l.usable ? '#22c55e' : l.authed ? '#f59e0b' : '#f59e0b', fontWeight: 600 }}>{l.usable ? '✓ ready' : l.authed ? 'authed · needs proxy' : 'auth pending'}</td>
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
        </div>
      )}

      {/* Source Maturity board (Gate 1-5, read-only) */}
      {smat?.top_sources && (
        <div style={card}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Source Maturity</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6 }}>
            tiers: {Object.entries(smat.tier_counts || {}).map(([t, n]: any) => `${t}:${n}`).join(' · ')} · {smat.source_count} sources
            {smat.operator_actions?.length > 0 && <span style={{ color: '#f59e0b' }}> · {smat.operator_actions.length} operator action(s)</span>}
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead><tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
              {['Source', 'Tier', 'Score', 'Go-rate', 'Signals', 'Trades'].map(h => <th key={h} style={{ padding: '3px 6px', borderBottom: '1px solid var(--border)' }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {smat.top_sources.slice(0, 12).map((s: any) => (
                <tr key={s.source} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '3px 6px', fontFamily: 'monospace' }}>{s.source.slice(0, 26)}</td>
                  <td style={{ padding: '3px 6px', fontWeight: 600, color: s.tier === 'core' ? '#22c55e' : s.tier === 'trusted' ? '#14b8a6' : s.tier === 'demoted' ? '#ef4444' : 'var(--text3)' }}>{s.tier}</td>
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

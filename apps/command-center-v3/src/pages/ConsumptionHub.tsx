import { useCallback, useEffect, useState } from 'react'
import CloudLlmRunButtons from '../components/CloudLlmRunButtons'
import { lanePolicyColor, lanePolicyHint, PROCESS_LANE_POLICIES, runManualCloud } from '../lib/cloudLlmRun'
import { useOAuthLanes, laneReady } from '../hooks/useOAuthLanes'

const GREEN = '#22c55e', RED = '#ef4444', AMBER = '#f59e0b', BLUE = '#60a5fa', MUTED = '#94a3b8', TEXT = '#f8fafc'

type ProcessRow = {
  process_id: string
  process_name: string
  category?: string
  mode: 'automated' | 'manual'
  calls_30d?: number
  calls_today?: number
  relative_units_30d?: number
  last_used?: string | null
  description?: string
  lane_policy?: string
  lane_policy_label?: string
}

type LogRow = {
  id: number
  created_at: string
  model_lane: string
  process_name: string
  task_summary: string
  trigger_mode: string
  relative_units?: number
  success: boolean
}

export default function ConsumptionHub() {
  const oauth = useOAuthLanes(90_000)
  const [overview, setOverview] = useState<any>(null)
  const [processes, setProcesses] = useState<ProcessRow[]>([])
  const [logs, setLogs] = useState<LogRow[]>([])
  const [filterPid, setFilterPid] = useState<string | null>(null)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    try {
      const nocache = { cache: 'no-store' as RequestCache }
      const [ov, pr, reg, lg] = await Promise.all([
        fetch('/api/v2/consumption/overview', nocache).then(r => r.json()),
        fetch('/api/v2/consumption/processes', nocache).then(r => r.json()),
        fetch('/api/v2/consumption/lane-registry', nocache).then(r => r.json()).catch(() => null),
        fetch(`/api/v2/consumption/logs?limit=40${filterPid ? `&process_id=${encodeURIComponent(filterPid)}` : ''}`, nocache).then(r => r.json()),
      ])
      setOverview((ov?.data ?? ov)?.overview ?? null)
      const regData = reg?.data ?? reg
      const policyMap: Record<string, string> = regData?.processes ?? {}
      const policyLabels: Record<string, string> = regData?.policy_labels ?? {}
      const prPayload = pr?.data ?? pr
      const raw: ProcessRow[] = prPayload?.processes ?? prPayload?.data?.processes ?? []
      setProcesses(raw.map(p => {
        const lp = p.lane_policy || policyMap[p.process_id] || PROCESS_LANE_POLICIES[p.process_id] || 'either'
        return {
          ...p,
          lane_policy: lp,
          lane_policy_label: p.lane_policy_label || policyLabels[lp] || lanePolicyHint(lp),
        }
      }))
      setLogs((lg?.data ?? lg)?.logs ?? [])
    } catch { /* surfaced via empty state */ }
  }, [filterPid])

  useEffect(() => { void load() }, [load])

  const setMode = async (pid: string, mode: 'automated' | 'manual') => {
    setBusy(pid)
    try {
      const res = await fetch('/api/v2/consumption/process-mode', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ process_id: pid, mode }),
      })
      const j = await res.json()
      setMsg(j?.ok ? `✓ ${pid} → ${mode}` : `⛔ ${j?.error || 'failed'}`)
      await load()
    } finally {
      setBusy('')
    }
  }

  const testLane = async (lane: 'grok' | 'chatgpt') => {
    setBusy(`test-${lane}`)
    setMsg('')
    try {
      const res = await runManualCloud({
        process_id: 'oauth_lane_keepalive',
        lane,
        prompt: 'Reply with exactly: OK',
        task_summary: `${lane} OAuth test from Consumption`,
      })
      if (res?.ok) setMsg(`✓ ${lane} OAuth test OK — "${(res.text || '').trim().slice(0, 40)}"`)
      else setMsg(`⛔ ${lane} test failed: ${res?.error || 'unknown'}`)
      await oauth.refresh()
      await load()
    } catch (e: any) {
      setMsg(`⛔ ${lane} test error: ${String(e?.message || e).slice(0, 80)}`)
    } finally {
      setBusy('')
    }
  }

  const runKeepalive = async () => {
    setBusy('keepalive')
    await fetch('/api/v2/llm/oauth-lanes/keepalive', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    await oauth.refresh()
    await load()
    setMsg('✓ OAuth keepalive ran — lanes + process table refreshed')
    setBusy('')
  }

  const grokLane = oauth.grok
  const chatLane = oauth.chatgpt

  return (
    <div style={{ maxWidth: 1100 }}>
      <h1 style={{ fontSize: 22, fontWeight: 800, color: TEXT, marginBottom: 4 }}>LLM Consumption</h1>
      <p style={{ fontSize: 12, color: MUTED, marginBottom: 16, lineHeight: 1.5 }}>
        Track and control <b style={{ color: TEXT }}>free OAuth</b> usage — Grok (xAI :8645) and ChatGPT (codex :8646).
        No metered API keys. <b>Manual</b> mode blocks automatic calls; use per-lane <b>▶ Grok / ▶ ChatGPT</b> on feature cards or below.
        <b> Automated</b> when you want hands-off cron.
      </p>
      <div style={{ fontSize: 10, color: MUTED, marginBottom: 14, lineHeight: 1.5, padding: '8px 10px', borderRadius: 8, background: 'var(--bg1)', border: '1px solid var(--border)' }}>
        <b style={{ color: TEXT }}>Lane policies:</b>{' '}
        <span>Grok only</span> · <span>Grok or ChatGPT (pick one)</span> · <span>Both preferred</span> · <span>Ensemble (run both)</span>.
        Stop advisories stay <b>Manual</b> — use Grok batch (top 6) on Portfolio → Stop Management or the batch row here.
      </div>

      {/* OAuth lane status */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 10, marginBottom: 16 }}>
        {(['grok', 'chatgpt'] as const).map(id => {
          const ln = id === 'grok' ? grokLane : chatLane
          const ok = laneReady(ln)
          return (
            <div key={id} style={{ padding: 14, borderRadius: 10, background: 'var(--bg1)', border: `1px solid ${ok ? GREEN : RED}44` }}>
              <div style={{ fontSize: 11, fontWeight: 800, color: MUTED, textTransform: 'uppercase' }}>{ln?.label || id}</div>
              <div style={{ fontSize: 18, fontWeight: 900, color: ok ? GREEN : RED, marginTop: 4 }}>
                {ok ? '✓ Ready' : (ln?.status || 'offline')}
              </div>
              <div style={{ fontSize: 10, color: MUTED, marginTop: 4 }}>
                Free OAuth · :{ln?.port ?? (id === 'grok' ? 8645 : 8646)}
                {ln?.consec_fail ? ` · ${ln.consec_fail} recent fail(s)` : ''}
              </div>
              {!ok && ln?.hint && (
                <div style={{ fontSize: 10, color: AMBER, marginTop: 6 }}>
                  {ln.hint}
                  {id === 'grok' && ln?.authenticated && (
                    <span> — or click <b>↻ Roll OAuth tokens</b> below (refreshes without re-login)</span>
                  )}
                </div>
              )}
            </div>
          )
        })}
        <div style={{ padding: 14, borderRadius: 10, background: 'var(--bg1)', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 8 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            <button type="button" onClick={() => void testLane('grok')} disabled={!!busy}
              style={{ fontSize: 10, fontWeight: 800, padding: '6px 10px', borderRadius: 6, border: '1px solid #1d9bf066', background: '#1d9bf014', color: '#1d9bf0', cursor: busy ? 'wait' : 'pointer' }}>
              {busy === 'test-grok' ? '…' : '▶ Test Grok'}
            </button>
            <button type="button" onClick={() => void testLane('chatgpt')} disabled={!!busy}
              style={{ fontSize: 10, fontWeight: 800, padding: '6px 10px', borderRadius: 6, border: '1px solid #10a37f66', background: '#10a37f14', color: '#10a37f', cursor: busy ? 'wait' : 'pointer' }}>
              {busy === 'test-chatgpt' ? '…' : '▶ Test ChatGPT'}
            </button>
          </div>
          <button onClick={() => void runKeepalive()} disabled={!!busy}
            style={{ fontSize: 12, fontWeight: 800, padding: '8px 12px', borderRadius: 6, border: `1px solid ${BLUE}`, background: `${BLUE}22`, color: BLUE, cursor: busy ? 'wait' : 'pointer' }}>
            ↻ Roll OAuth tokens
          </button>
          <button onClick={() => { void oauth.refresh(); void load() }} style={{ fontSize: 11, color: MUTED, background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left' }}>
            Refresh lane probe
          </button>
        </div>
      </div>

      {/* Overview cards */}
      {overview && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 8, marginBottom: 16 }}>
          {(['grok', 'chatgpt'] as const).flatMap(lane => {
            const t = overview?.by_lane?.[lane]?.today
            const w = overview?.by_lane?.[lane]?.week
            if (!t && !w) return []
            return [
              <div key={`${lane}-today`} style={{ padding: 12, borderRadius: 8, background: 'var(--bg1)', border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 10, color: MUTED }}>{lane} today</div>
                <div style={{ fontSize: 20, fontWeight: 900, color: TEXT }}>{t?.calls ?? 0}</div>
                <div style={{ fontSize: 10, color: MUTED }}>{(t?.relative_units ?? 0).toFixed(1)} rel. units</div>
              </div>,
              <div key={`${lane}-week`} style={{ padding: 12, borderRadius: 8, background: 'var(--bg1)', border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 10, color: MUTED }}>{lane} 7d</div>
                <div style={{ fontSize: 20, fontWeight: 900, color: TEXT }}>{w?.calls ?? 0}</div>
                <div style={{ fontSize: 10, color: MUTED }}>{(w?.relative_units ?? 0).toFixed(1)} rel. units</div>
              </div>,
            ]
          })}
        </div>
      )}

      {msg && <div style={{ fontSize: 12, color: msg.startsWith('✓') ? GREEN : RED, marginBottom: 10 }}>{msg}</div>}

      {/* Process table */}
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 16 }}>
        <div style={{ fontSize: 14, fontWeight: 800, color: TEXT, marginBottom: 10 }}>Processes</div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr style={{ color: MUTED, textAlign: 'left' }}>
                <th style={{ padding: '6px 8px' }}>Process</th>
                <th>Category</th>
                <th>Lanes</th>
                <th>Mode</th>
                <th>30d calls</th>
                <th>Rel. units</th>
                <th>Last used</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {processes.map(p => (
                <tr key={p.process_id} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '8px', color: TEXT, fontWeight: 700 }}>
                    {p.process_name}
                    <div style={{ fontSize: 9, color: MUTED, fontWeight: 400 }}>{p.process_id}</div>
                  </td>
                  <td style={{ color: MUTED }}>{p.category || '—'}</td>
                  <td style={{ fontSize: 10, whiteSpace: 'nowrap' }}>
                    <span title={p.lane_policy_label || p.description}
                      style={{ fontWeight: 700, color: lanePolicyColor(p.lane_policy) }}>
                      {lanePolicyHint(p.lane_policy)}
                    </span>
                    {p.process_id === 'holding_protection_advisor_batch' && (
                      <div style={{ marginTop: 4 }}>
                        <CloudLlmRunButtons
                          processId={p.process_id}
                          lanePolicy="grok_only"
                          batchLimit={6}
                          compact
                          onDone={() => void load()}
                        />
                      </div>
                    )}
                  </td>
                  <td>
                    <span style={{
                      fontSize: 10, fontWeight: 800, padding: '2px 8px', borderRadius: 999,
                      color: p.mode === 'automated' ? GREEN : AMBER,
                      background: `${p.mode === 'automated' ? GREEN : AMBER}18`,
                      border: `1px solid ${p.mode === 'automated' ? GREEN : AMBER}55`,
                    }}>{p.mode}</span>
                  </td>
                  <td style={{ color: TEXT }}>{p.calls_30d ?? 0}{p.calls_today ? ` (${p.calls_today} today)` : ''}</td>
                  <td style={{ color: TEXT }}>{(p.relative_units_30d ?? 0).toFixed(1)}</td>
                  <td style={{ color: MUTED, fontSize: 10 }}>{p.last_used ? new Date(p.last_used).toLocaleString() : '—'}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    <button disabled={busy === p.process_id || p.mode === 'automated'}
                      onClick={() => void setMode(p.process_id, 'automated')}
                      style={{ fontSize: 10, marginRight: 4, padding: '4px 8px', borderRadius: 4, border: `1px solid ${GREEN}`, color: GREEN, background: 'transparent', cursor: 'pointer' }}>
                      Auto
                    </button>
                    <button disabled={busy === p.process_id || p.mode === 'manual'}
                      onClick={() => void setMode(p.process_id, 'manual')}
                      style={{ fontSize: 10, marginRight: 4, padding: '4px 8px', borderRadius: 4, border: `1px solid ${AMBER}`, color: AMBER, background: 'transparent', cursor: 'pointer' }}>
                      Manual
                    </button>
                    <button onClick={() => setFilterPid(filterPid === p.process_id ? null : p.process_id)}
                      style={{ fontSize: 10, padding: '4px 8px', borderRadius: 4, border: '1px solid var(--border)', color: BLUE, background: 'transparent', cursor: 'pointer' }}>
                      {filterPid === p.process_id ? 'Clear logs' : 'Logs'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ fontSize: 9, color: MUTED, marginTop: 8 }}>Default for new processes: Manual. Relative units ≈ (prompt+response chars)/1000 on free tier ($0).</div>
      </div>

      {/* Recent activity */}
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
        <div style={{ fontSize: 14, fontWeight: 800, color: TEXT, marginBottom: 8 }}>
          Recent activity{filterPid ? ` · ${filterPid}` : ''}
        </div>
        {logs.length === 0 ? (
          <div style={{ fontSize: 11, color: MUTED }}>No logged calls yet — calls appear after processes use Grok/ChatGPT with tracking.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {logs.map(l => (
              <div key={l.id} style={{ padding: '8px 10px', borderRadius: 6, background: 'var(--bg2)', border: '1px solid var(--border)', fontSize: 11 }}>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                  <span style={{ color: MUTED }}>{new Date(l.created_at).toLocaleString()}</span>
                  <span style={{ fontWeight: 800, color: l.model_lane === 'grok' ? '#1d9bf0' : '#10a37f' }}>{l.model_lane}</span>
                  <span style={{ color: TEXT, fontWeight: 700 }}>{l.process_name}</span>
                  <span style={{ color: l.trigger_mode === 'manual' ? AMBER : MUTED, fontSize: 10 }}>{l.trigger_mode}</span>
                  {!l.success && <span style={{ color: RED }}>failed</span>}
                </div>
                <div style={{ color: MUTED, marginTop: 4 }}>{l.task_summary}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
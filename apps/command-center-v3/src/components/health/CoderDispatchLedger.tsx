import { useState } from 'react'

const OUTCOME_COLOR: Record<string, string> = {
  pr_opened: '#22c55e', advisory_diff: '#22c55e', verified: '#22c55e',
  queued: '#f59e0b', planned: '#60a5fa', investigating: '#60a5fa',
  no_changes: '#94a3b8', attempted: '#f59e0b',
  verify_failed: '#ef4444', worktree_failed: '#ef4444', error: '#ef4444',
  no_backend_available: '#ef4444', failed: '#ef4444',
}

const OUTCOME_LABEL: Record<string, string> = {
  pr_opened: 'PR opened', advisory_diff: 'Diff saved', verify_failed: 'Verify failed',
  worktree_failed: 'Worktree failed', no_changes: 'No changes', error: 'Error',
  no_backend_available: 'No coder', planned: 'Planned', queued: 'Queued',
}

function fmtWhen(s?: string) {
  if (!s) return '—'
  try { return new Date(s).toLocaleString() } catch { return s }
}

function compLabel(c?: string) {
  if (!c) return '—'
  const p = c.replace(/^health:/, '').split(':')
  if (p.length >= 2) return `${p[0].replace(/_/g, ' ')} · ${p[1].replace(/_/g, ' ')}`
  return c.replace(/^health:/, '').replace(/_/g, ' ')
}

function linkFor(url?: string | null) {
  if (!url) return null
  if (url.startsWith('http')) return url
  const name = url.split('/').pop() || ''
  if (url.includes('coder_dispatch_diffs') && name) return `/logs/coder_dispatch_diffs/${name}`
  return null
}

function OutcomeBadge({ outcome }: { outcome?: string }) {
  const o = (outcome || 'unknown').toLowerCase()
  const c = OUTCOME_COLOR[o] || '#94a3b8'
  return (
    <span style={{
      fontSize: 8, fontWeight: 800, textTransform: 'uppercase', letterSpacing: 0.3,
      padding: '2px 7px', borderRadius: 5, background: c + '18', color: c, whiteSpace: 'nowrap',
    }}>{OUTCOME_LABEL[o] || o.replace(/_/g, ' ')}</span>
  )
}

const panel = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 } as const

export default function CoderDispatchLedger({ data, loading }: { data: any; loading?: boolean }) {
  const [openId, setOpenId] = useState<number | string | null>(null)

  if (loading) return <div style={{ fontSize: 11, color: 'var(--text3)', padding: 16 }}>Loading dispatch ledger…</div>
  if (!data) return null

  const stats = data.stats || {}
  const queue: any[] = data.queue || []
  const ledger: any[] = data.ledger || []
  const interventions: any[] = data.interventions || []

  const stat = (label: string, value: number | string, color?: string) => (
    <div style={{ padding: '8px 12px', ...panel, minWidth: 90 }}>
      <div style={{ fontSize: 16, fontWeight: 800, color: color || 'var(--text0)' }}>{value}</div>
      <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', marginTop: 2 }}>{label}</div>
    </div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Stats */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {stat('queued for coder', stats.queued_code_fix ?? 0, '#f59e0b')}
        {stat('dispatches', stats.total_dispatches ?? 0)}
        {stat('PRs opened', stats.pr_opened ?? 0, '#22c55e')}
        {stat('diffs saved', stats.advisory_diff ?? 0, '#22c55e')}
        {stat('failed', stats.failed ?? 0, '#ef4444')}
        {stat('today OK', `${stats.dispatched_today ?? 0}/${stats.daily_cap ?? 6}`)}
      </div>

      {/* Pending queue */}
      <div style={{ ...panel, padding: '12px 14px' }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text0)', marginBottom: 8 }}>
          Pending code-fix queue
          <span style={{ fontWeight: 400, color: 'var(--text3)', marginLeft: 8 }}>
            — waiting for coder_dispatch (--from-queue)
          </span>
        </div>
        {queue.length === 0 && (
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Nothing queued for coders right now.</div>
        )}
        {queue.map((q: any, i: number) => (
          <div key={i} style={{
            padding: '8px 10px', marginBottom: 5, borderRadius: 6,
            border: '1px solid var(--border-subtle)', borderLeft: '3px solid #f59e0b',
            background: 'var(--bg2)',
          }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 9, fontWeight: 700, color: '#f59e0b', textTransform: 'uppercase' }}>queued</span>
              <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)' }}>{compLabel(q.component)}</span>
              {q.kind && <span style={{ fontSize: 9, color: 'var(--text3)' }}>kind: {q.kind}</span>}
              {q.source && <span style={{ fontSize: 9, color: 'var(--text3)' }}>via {q.source}</span>}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4, lineHeight: 1.45 }}>{q.detail || q.problem}</div>
          </div>
        ))}
      </div>

      {/* Dispatch ledger */}
      <div style={{ ...panel, padding: '12px 14px' }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text0)', marginBottom: 8 }}>
          Dispatch ledger
          <span style={{ fontWeight: 400, color: 'var(--text3)', marginLeft: 8 }}>— what was sent to coders and how it resolved</span>
        </div>
        {ledger.length === 0 && (
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>No coder dispatches recorded yet.</div>
        )}
        {ledger.map((d: any) => {
          const id = d.id ?? d.created_at
          const open = openId === id
          const href = linkFor(d.artifact_url || d.pr_url)
          const isPr = d.pr_url?.startsWith('http')
          return (
            <div key={id} style={{
              marginBottom: 6, borderRadius: 6, border: `1px solid ${open ? '#60a5fa55' : 'var(--border-subtle)'}`,
              overflow: 'hidden',
            }}>
              <button type="button" onClick={() => setOpenId(open ? null : id)} style={{
                display: 'flex', width: '100%', gap: 8, alignItems: 'center', flexWrap: 'wrap',
                padding: '8px 10px', border: 'none', background: open ? 'rgba(96,165,250,.06)' : 'var(--bg2)',
                cursor: 'pointer', textAlign: 'left',
              }}>
                <span style={{ fontSize: 9, color: 'var(--text3)', width: 118, flexShrink: 0 }}>{fmtWhen(d.created_at)}</span>
                <OutcomeBadge outcome={d.outcome} />
                <span style={{ fontSize: 10, fontWeight: 700, color: '#60a5fa', width: 88, flexShrink: 0 }}>{d.backend_display || d.backend}</span>
                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)', flex: 1, minWidth: 0,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {compLabel(d.component)}
                </span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{open ? '▲' : '▼'}</span>
              </button>
              {open && (
                <div style={{ padding: '10px 12px', borderTop: '1px solid var(--border-subtle)', fontSize: 10.5, lineHeight: 1.5 }}>
                  <div style={{ marginBottom: 6 }}>
                    <span style={{ fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', fontSize: 9 }}>Problem </span>
                    <span style={{ color: 'var(--text1)' }}>{d.problem || '—'}</span>
                  </div>
                  {d.resolution && (
                    <div style={{ marginBottom: 6 }}>
                      <span style={{ fontWeight: 800, color: 'var(--text3)', textTransform: 'uppercase', fontSize: 9 }}>Resolution </span>
                      <span style={{ color: 'var(--text2)' }}>{d.resolution}</span>
                    </div>
                  )}
                  {d.reasoning && (
                    <div style={{ marginBottom: 6, color: 'var(--text3)' }}>Router: {d.reasoning}</div>
                  )}
                  <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 6, color: 'var(--text3)' }}>
                    {d.mode && <span>mode: <b style={{ color: 'var(--text2)' }}>{d.mode}</b></span>}
                    {d.branch && <span>branch: <code style={{ fontSize: 9 }}>{d.branch}</code></span>}
                    {d.kind && <span>kind: {d.kind}</span>}
                  </div>
                  {(d.files_changed || []).length > 0 && (
                    <div style={{ marginBottom: 6 }}>
                      <span style={{ fontWeight: 800, color: 'var(--text3)', fontSize: 9 }}>FILES </span>
                      {(d.files_changed || []).map((f: string) => (
                        <span key={f} style={{ fontSize: 9, marginRight: 6, padding: '1px 6px', borderRadius: 4, background: 'var(--bg1)', color: '#60a5fa' }}>{f}</span>
                      ))}
                    </div>
                  )}
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    {isPr && <a href={d.pr_url} target="_blank" rel="noreferrer" style={{ color: '#60a5fa', fontWeight: 700 }}>View PR ↗</a>}
                    {href && !isPr && <a href={href} target="_blank" rel="noreferrer" style={{ color: '#60a5fa', fontWeight: 700 }}>View diff ↓</a>}
                  </div>
                  {d.detail && (
                    <pre style={{ marginTop: 8, padding: 8, background: 'var(--bg0)', borderRadius: 6, fontSize: 9,
                      color: 'var(--text2)', whiteSpace: 'pre-wrap', maxHeight: 120, overflow: 'auto' }}>{d.detail}</pre>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Escalation handler resolutions */}
      {interventions.length > 0 && (
        <div style={{ ...panel, padding: '12px 14px' }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text0)', marginBottom: 8 }}>
            Escalation handler resolutions
            <span style={{ fontWeight: 400, color: 'var(--text3)', marginLeft: 8 }}>— retries / LLM tier before coders</span>
          </div>
          {interventions.map((r: any, i: number) => (
            <div key={i} style={{
              display: 'flex', gap: 8, alignItems: 'flex-start', padding: '6px 8px', marginBottom: 4,
              borderRadius: 5, background: 'var(--bg2)', fontSize: 10.5,
            }}>
              <span style={{ color: 'var(--text3)', width: 118, flexShrink: 0 }}>{fmtWhen(r.at)}</span>
              <OutcomeBadge outcome={r.status} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, color: 'var(--text0)' }}>{compLabel(r.component)}</div>
                {(r.diagnosis || r.solution) && (
                  <div style={{ color: 'var(--text2)', marginTop: 2, lineHeight: 1.4 }}>
                    {r.solution || r.diagnosis}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
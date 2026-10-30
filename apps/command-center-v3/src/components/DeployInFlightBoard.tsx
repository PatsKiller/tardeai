// Deploy console P1+P2 — the "not live / in flight" open-PR board (DSN-20261029-deploy-console).
// P1 (read-only): fetches GET /api/v2/ops/in-flight (scripts/lib/deploy_in_flight.py) and renders the open PRs to
// main with ⓘ tooltips. P2 (write path): four operator actions behind POST /api/v2/ops/in-flight/action
// (scripts/lib/deploy_console_actions.py) — Approve (add operator-merge, bound to head SHA), Hold (remove it),
// Refresh hints (re-run the duration-hints refresh), Push (bound git-push grant + fast-forward push). Every POST is
// operator-session + same-origin CSRF protected on the server (cc_auth); no authority is newly granted here.
import { useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow } from './primitives'
import { RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../lib/designTokens'

const IN_FLIGHT_PATH = '/api/v2/ops/in-flight'
const ACTION_PATH = '/api/v2/ops/in-flight/action'
const SCHEMA = 'DeployInFlight@v1'

export type InFlightPr = {
  number: number
  title: string
  url: string
  head_sha: string
  head_sha_short: string
  branch: string
  has_operator_merge: boolean
  mergeable: 'MERGEABLE' | 'CONFLICTING' | 'UNKNOWN'
  merge_state: string
  is_draft: boolean
  why_held: string | null
  next: 'auto-merge' | 'coordinator' | 'auto-rebase' | 'blocked-shard-hints'
}

export type DeployInFlightWire = {
  schema?: string
  authority?: string
  generated_at?: string
  repo?: string
  prs?: InFlightPr[] | null
  count?: number | null
  status?: string
  freshness?: 'OK' | 'STALE' | 'UNAVAILABLE'
  source?: string
  reason?: string | null
}

type ActionOutcome = { ok: boolean; outcome?: string; error?: string; refusal?: string; reason?: string }

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 14, minWidth: 0, display: 'grid', gap: 8 }
const h2: CSSProperties = { margin: 0, fontSize: TYPE.md, fontWeight: 800, color: TOKENS.text[0] }
const muted: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[2], margin: 0 }
const th: CSSProperties = { padding: '6px 6px', fontSize: TYPE.xs, color: TOKENS.text[3], whiteSpace: 'nowrap', textTransform: 'uppercase', textAlign: 'left', verticalAlign: 'top' }
const td: CSSProperties = { padding: '6px 6px', fontSize: TYPE.sm, color: TOKENS.text[1], verticalAlign: 'top', textAlign: 'left' }

const nextTone = (n: InFlightPr['next']): Tone => (n === 'auto-merge' ? 'success' : n === 'coordinator' ? 'warning' : n === 'auto-rebase' ? 'info' : 'danger')
const stateTone = (s: string): Tone => {
  const u = String(s || '').toUpperCase()
  if (u === 'CLEAN') return 'success'
  if (u === 'BLOCKED') return 'danger'
  if (u === 'DIRTY' || u === 'BEHIND' || u === 'UNSTABLE' || u === 'DRAFT' || u === 'UNKNOWN') return 'warning'
  return 'neutral'
}

const prTooltip = (p: InFlightPr): string =>
  `#${p.number} — ${p.title}\nhead ${p.head_sha}${p.branch ? `\nbranch ${p.branch}` : ''}\nmergeable: ${p.mergeable}${p.is_draft ? '\ndraft' : ''}${p.why_held ? `\nwhy held: ${p.why_held}` : ''}`

const btn = (tone: Tone, disabled: boolean): CSSProperties => {
  const t = toneVars(tone)
  return {
    padding: '2px 8px', borderRadius: RADIUS.pill, border: `1px solid ${t.border}`, background: t.bg, color: t.color,
    fontSize: TYPE.xs, fontWeight: 700, cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.4 : 1,
    whiteSpace: 'nowrap',
  }
}

export default function DeployInFlightBoard() {
  const api = useApi<DeployInFlightWire>(IN_FLIGHT_PATH, 60_000)
  const [busy, setBusy] = useState<string | null>(null)   // "approve:2211" | "hold:2211" | "push:2211" | "refresh_hints"
  const [last, setLast] = useState<ActionOutcome | null>(null)
  const [overrideBudget, setOverrideBudget] = useState(false)
  const data = api.data
  const known = !!data && data.schema === SCHEMA
  const prs = known ? (data!.prs ?? null) : null
  const unavailable = !known || data?.freshness === 'UNAVAILABLE' || (prs === null && api.error)
  const staleHint = api.stale || (known && data!.freshness === 'STALE')

  const post = async (body: Record<string, unknown>, key: string): Promise<void> => {
    if (busy) return
    setBusy(key)
    setLast(null)
    try {
      const r = await fetch(ACTION_PATH, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      let out: ActionOutcome | null = null
      try { out = await r.json() } catch { out = null }
      setLast(out ?? { ok: false, error: `HTTP ${r.status}, unreadable body` })
    } catch (e) {
      setLast({ ok: false, error: String(e) })
    } finally {
      setBusy(null)
      api.refetch()
    }
  }

  const approve = (p: InFlightPr) => post({ action: 'approve', pr_number: p.number, head_sha: p.head_sha }, `approve:${p.number}`)
  const hold = (p: InFlightPr) => post({ action: 'hold', pr_number: p.number, head_sha: p.head_sha }, `hold:${p.number}`)
  const push = (p: InFlightPr) => post({ action: 'push', branch: p.branch, head_sha: p.head_sha, override: overrideBudget }, `push:${p.number}`)
  const refreshHints = () => post({ action: 'refresh_hints' }, 'refresh_hints')

  const canApprove = (p: InFlightPr) => !p.is_draft && p.mergeable !== 'CONFLICTING' && !p.has_operator_merge
  const canHold = (p: InFlightPr) => p.has_operator_merge
  const canPush = (p: InFlightPr) => !p.is_draft && p.branch !== ''

  return <section data-testid="deploy-in-flight" style={panel}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
      <h2 style={h2}>In flight · open PRs to main</h2>
      <ChipRow>
        {unavailable && !prs
          ? <Chip tone="warning">UNAVAILABLE</Chip>
          : api.loading && !data
            ? <Chip tone="neutral">Loading</Chip>
            : <Chip tone={staleHint ? 'warning' : 'neutral'}>{known && data!.freshness === 'UNAVAILABLE' ? 'UNAVAILABLE' : staleHint ? 'STALE' : data?.status ?? '—'}</Chip>}
        {known && data!.count != null ? <Chip tone="neutral">{data!.count} open</Chip> : null}
      </ChipRow>
    </div>

    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      <button type="button" data-testid="refresh-hints-button" onClick={refreshHints} disabled={busy !== null}
        style={btn('info', busy !== null)} title="Re-runs scripts/run_cio_hardening_ci.py --write-duration-hints (the self-contained duration-hints refresh).">
        Refresh hints
      </button>
      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: TYPE.sm, color: TOKENS.text[1] }}>
        <input type="checkbox" checked={overrideBudget} onChange={e => setOverrideBudget(e.target.checked)} />
        lift push budget (“override”)
      </label>
      {busy ? <Chip tone="info">working…</Chip> : null}
      {last ? <Chip tone={last.ok ? 'success' : 'danger'}>{last.ok ? (last.outcome ?? 'done') : (last.refusal ?? last.error ?? 'refused')}</Chip> : null}
    </div>

    {unavailable && !prs
      ? <p role="status" style={{ ...muted, color: toneVars('warning').color, fontWeight: 700 }}>
          UNAVAILABLE{data?.reason ? ` · ${data.reason}` : api.error ? ` · ${api.error}` : ''} — not empty, not healthy: unknown.
        </p>
      : null}

    {prs !== null && (
      <div style={{ overflowX: 'auto' }}>
        <table className="ops-evidence-table" aria-label="Open pull requests not yet live" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={th}>PR</th><th style={th}>What it is</th><th style={th}>State</th><th style={th}>Next</th><th style={th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {prs.map((p) => (
              <tr key={p.number} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
                <td data-label="PR" style={td}>
                  <a href={p.url} target="_blank" rel="noreferrer" style={{ color: TOKENS.primary }} title={prTooltip(p)}>#{p.number}</a>{' '}
                  <span role="img" aria-label="details" title={prTooltip(p)} style={{ cursor: 'help', color: TOKENS.text[3] }}>ⓘ</span>
                </td>
                <td data-label="What it is" style={td}><span style={{ overflowWrap: 'anywhere' }}>{p.title}</span></td>
                <td data-label="State" style={td}>
                  <span title={`mergeable: ${p.mergeable}`}><Chip tone={stateTone(p.merge_state)}>{p.merge_state}{p.is_draft ? ' · DRAFT' : ''}</Chip></span>
                  {p.has_operator_merge ? <span style={{ ...muted, display: 'block' }}>operator-merge set</span> : null}
                  {p.why_held ? <span style={{ ...muted, display: 'block' }}>{p.why_held}</span> : null}
                </td>
                <td data-label="Next" style={td}><Chip tone={nextTone(p.next)} variant="solid">{p.next}</Chip></td>
                <td data-label="Actions" style={td}>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <button type="button" data-testid={`approve-${p.number}`} onClick={() => approve(p)}
                      disabled={busy !== null || !canApprove(p)} style={btn('success', busy !== null || !canApprove(p))}
                      title="Adds operator-merge (bound to this head SHA) so Mergify queues the PR.">
                      Approve
                    </button>
                    <button type="button" data-testid={`hold-${p.number}`} onClick={() => hold(p)}
                      disabled={busy !== null || !canHold(p)} style={btn('warning', busy !== null || !canHold(p))}
                      title="Removes operator-merge so Mergify will not queue the PR.">
                      Hold
                    </button>
                    <button type="button" data-testid={`push-${p.number}`} onClick={() => push(p)}
                      disabled={busy !== null || !canPush(p)} style={btn('info', busy !== null || !canPush(p))}
                      title="Issues a git-push guard grant bound to this branch + head SHA and fast-forward pushes it. Force-push stays refused.">
                      Push
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!prs.length ? <tr><td colSpan={5} style={{ ...td, color: TOKENS.text[2] }}>No open PRs to main.</td></tr> : null}
          </tbody>
        </table>
      </div>
    )}

    <p style={muted}>
      Approve / Hold reuse the same operator-merge label the Telegram tap already sets; Push writes a bound git-push
      grant and fast-forwards (force stays refused). Every action is operator-session + same-origin CSRF protected and
      writes a durable receipt. {data?.source ? `Source: ${data.source}.` : ''}
    </p>
  </section>
}

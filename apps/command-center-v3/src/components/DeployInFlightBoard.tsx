// Deploy console — in-flight open-PR board with operator clarity (DSN-20261029).
// GET /api/v2/ops/in-flight + POST /api/v2/ops/in-flight/action. Approve matches Telegram READY.
import { useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow } from './primitives'
import DeployGateChecklist from './DeployGateChecklist'
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
  plain_english?: Record<string, string> | null
  plain_english_missing?: boolean
  checks?: Record<string, string> | null
  digest_status?: string
  digest_reason?: string
  can_approve?: boolean
  created_at?: string | null
  updated_at?: string | null
  created_age?: string | null
  updated_age?: string | null
  next_plain?: string | null
  author?: string | null
}

export type DeployInFlightWire = {
  schema?: string
  authority?: string
  generated_at?: string
  repo?: string
  prs?: InFlightPr[] | null
  count?: number | null
  ready_count?: number | null
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

const statusTone = (s: string | undefined): Tone => {
  const u = String(s || '').toLowerCase()
  if (u === 'ready') return 'success'
  if (u === 'approved') return 'info'
  if (u === 'conflict' || u === 'blocked') return 'danger'
  if (u === 'waiting_ci' || u === 'not_described' || u === 'needs_operator' || u === 'draft') return 'warning'
  return 'neutral'
}

const prTooltip = (p: InFlightPr): string =>
  `#${p.number} — ${p.title}\nhead ${p.head_sha}${p.branch ? `\nbranch ${p.branch}` : ''}\nmergeable: ${p.mergeable}` +
  `${p.is_draft ? '\ndraft' : ''}${p.why_held ? `\nwhy held: ${p.why_held}` : ''}` +
  `${p.digest_status ? `\nstatus: ${p.digest_status} (${p.digest_reason ?? ''})` : ''}`

const btn = (tone: Tone, disabled: boolean): CSSProperties => {
  const t = toneVars(tone)
  return {
    padding: '2px 8px', borderRadius: RADIUS.pill, border: `1px solid ${t.border}`, background: t.bg, color: t.color,
    fontSize: TYPE.xs, fontWeight: 700, cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.4 : 1,
    whiteSpace: 'nowrap',
  }
}

function PlainEnglishCell({ p }: { p: InFlightPr }) {
  const [open, setOpen] = useState(false)
  const pe = p.plain_english
  const what = pe?.['What changes']
  const why = pe?.['Why']
  if (!pe || p.plain_english_missing) {
    return (
      <div>
        <span style={{ overflowWrap: 'anywhere' }}>{p.title}</span>
        <p style={{ ...muted, color: toneVars('warning').color }}>Plain English missing — Approve stays off (same as Telegram).</p>
      </div>
    )
  }
  return (
    <div style={{ display: 'grid', gap: 4, maxWidth: 420 }}>
      <span style={{ fontWeight: 700, overflowWrap: 'anywhere' }}>{what || p.title}</span>
      {why ? <span style={muted}>{why}</span> : null}
      <button type="button" onClick={() => setOpen(o => !o)}
        style={{ ...btn('neutral', false), justifySelf: 'start', fontWeight: 600 }}
        title="Show the six plain-English answers from the PR">
        {open ? 'Hide details' : 'More plain English'}
      </button>
      {open ? (
        <dl style={{ margin: 0, display: 'grid', gap: 4 }}>
          {Object.entries(pe).map(([k, v]) => (
            <div key={k}>
              <dt style={{ fontWeight: 700, fontSize: TYPE.xs, color: TOKENS.text[3] }}>{k}</dt>
              <dd style={{ margin: 0, fontSize: TYPE.sm, overflowWrap: 'anywhere' }}>{v}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  )
}

export default function DeployInFlightBoard() {
  const api = useApi<DeployInFlightWire>(IN_FLIGHT_PATH, 60_000)
  const [busy, setBusy] = useState<string | null>(null)
  const [last, setLast] = useState<ActionOutcome | null>(null)
  const [overrideBudget, setOverrideBudget] = useState(false)
  const [advanced, setAdvanced] = useState(false)
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

  // Operator clarity: Approve only when digest READY (can_approve). Fall back to legacy rule if field absent.
  const canApprove = (p: InFlightPr) =>
    p.can_approve === true
      ? !p.has_operator_merge
      : p.can_approve === false
        ? false
        : !p.is_draft && p.mergeable !== 'CONFLICTING' && !p.has_operator_merge
  const canHold = (p: InFlightPr) => p.has_operator_merge
  const canPush = (p: InFlightPr) => !p.is_draft && p.branch !== ''

  const approveTitle = (p: InFlightPr) => {
    if (p.has_operator_merge) return 'Already Approved — Hold to take it back. (operator-merge set)'
    if (p.can_approve) return 'Safe to Approve — same READY rules as Telegram. Adds operator-merge so Mergify can queue the merge. Does not put this on the live site.'
    return `Approve disabled: ${p.next_plain || p.digest_reason || p.why_held || 'not READY'}`
  }

  return <section data-testid="deploy-in-flight" style={panel}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
      <h2 style={h2}>In flight · waiting to merge (not live yet)</h2>
      <ChipRow>
        {unavailable && !prs
          ? <Chip tone="warning">UNAVAILABLE</Chip>
          : api.loading && !data
            ? <Chip tone="neutral">Loading</Chip>
            : <Chip tone={staleHint ? 'warning' : 'neutral'}>{known && data!.freshness === 'UNAVAILABLE' ? 'UNAVAILABLE' : staleHint ? 'STALE' : data?.status ?? '—'}</Chip>}
        {known && data!.count != null ? <Chip tone="neutral">{data!.count} open</Chip> : null}
        {known && data!.ready_count != null ? <Chip tone={data!.ready_count > 0 ? 'success' : 'neutral'}>{data!.ready_count} READY</Chip> : null}
      </ChipRow>
    </div>

    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: TYPE.sm, color: TOKENS.text[1] }}>
        <input type="checkbox" checked={advanced} onChange={e => setAdvanced(e.target.checked)} data-testid="deploy-advanced-toggle" />
        Advanced (branch push / hints)
      </label>
      {advanced ? <>
        <button type="button" data-testid="refresh-hints-button" onClick={refreshHints} disabled={busy !== null}
          style={btn('info', busy !== null)} title="Re-runs duration-hints refresh (advanced CI shard tooling).">
          Refresh hints
        </button>
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: TYPE.sm, color: TOKENS.text[1] }}>
          <input type="checkbox" checked={overrideBudget} onChange={e => setOverrideBudget(e.target.checked)} />
          lift push budget (“override”)
        </label>
      </> : null}
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
              <th style={th}>PR</th>
              <th style={th}>In plain English</th>
              <th style={th}>Gates</th>
              <th style={th}>Updated</th>
              <th style={th}>Status</th>
              <th style={th}>Your move</th>
            </tr>
          </thead>
          <tbody>
            {prs.map((p) => (
              <tr key={p.number} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
                <td data-label="PR" style={td}>
                  <a href={p.url} target="_blank" rel="noreferrer" style={{ color: TOKENS.primary }} title={prTooltip(p)}>#{p.number}</a>{' '}
                  <span role="img" aria-label="details" title={prTooltip(p)} style={{ cursor: 'help', color: TOKENS.text[3] }}>ⓘ</span>
                </td>
                <td data-label="In plain English" style={td}><PlainEnglishCell p={p} /></td>
                <td data-label="Gates" style={td}>
                  <DeployGateChecklist checks={p.checks} mergeable={p.mergeable} />
                </td>
                <td data-label="Updated" style={td}>
                  <span title={p.updated_at ?? p.created_at ?? ''}>{p.updated_age ?? p.created_age ?? '—'}</span>
                  {p.created_age && p.updated_age && p.created_age !== p.updated_age
                    ? <span style={{ ...muted, display: 'block' }}>opened {p.created_age}</span>
                    : null}
                </td>
                <td data-label="Status" style={td}>
                  <Chip tone={statusTone(p.digest_status)} title={`digest: ${p.digest_status ?? '—'} · ${p.digest_reason ?? ''} · next slug: ${p.next}`}>
                    {p.digest_status ?? p.merge_state}{p.is_draft ? ' · draft' : ''}
                  </Chip>
                  <p style={{ ...muted, marginTop: 4 }}>{p.next_plain ?? p.why_held ?? p.next}</p>
                  {p.has_operator_merge ? <span style={{ ...muted, display: 'block', color: toneVars('info').color }}>Approved — waiting on Mergify</span> : null}
                </td>
                <td data-label="Your move" style={td}>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <button type="button" data-testid={`approve-${p.number}`} onClick={() => approve(p)}
                      disabled={busy !== null || !canApprove(p)} style={btn('success', busy !== null || !canApprove(p))}
                      title={approveTitle(p)}>
                      Approve
                    </button>
                    <button type="button" data-testid={`hold-${p.number}`} onClick={() => hold(p)}
                      disabled={busy !== null || !canHold(p)} style={btn('warning', busy !== null || !canHold(p))}
                      title="Removes Approve (operator-merge) so Mergify will not queue this PR.">
                      Hold
                    </button>
                    {advanced ? (
                      <button type="button" data-testid={`push-${p.number}`} onClick={() => push(p)}
                        disabled={busy !== null || !canPush(p)} style={btn('info', busy !== null || !canPush(p))}
                        title="Advanced: updates the PR branch on GitHub only (fast-forward). Does NOT put the change on your live site.">
                        Update branch
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
            {!prs.length ? <tr><td colSpan={6} style={{ ...td, color: TOKENS.text[2] }}>No open PRs to main.</td></tr> : null}
          </tbody>
        </table>
      </div>
    )}

    <p style={muted}>
      Approve / Hold use the same operator-merge label as Telegram. Approve is enabled only when READY
      (plain English + four checks green + not held/draft/conflict). That queues a merge — it does not update the live site.
      {advanced ? ' Advanced “Update branch” writes a bound git-push grant and fast-forwards the feature branch (force refused).' : ''}
      {' '}Every action is operator-session + CSRF protected and writes a receipt.
      {data?.source ? ` Source: ${data.source}.` : ''}
    </p>
  </section>
}

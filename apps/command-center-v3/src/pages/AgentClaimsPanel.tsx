// Who's working on what (agent claim board, operator-approved 2026-10-22). Read-only view of
// GET /api/v2/coordination/claims (scripts/lib/agent_claim_board.py): every Claude, Codex and Cursor session's claim
// on files — branch, PR, since, last heartbeat. All vendors are equal peers; nothing here claims or releases.
import { useMemo, useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow } from '../components/primitives'
import { RADIUS, TOKENS, TYPE, FONT, type Tone } from '../lib/designTokens'

export type AgentClaimRow = {
  claim_id: string
  state: 'live' | 'stale' | 'done' | 'abandoned'
  status?: string
  vendor?: string | null
  session?: string | null
  agent?: string | null
  task?: string | null
  paths?: string[]
  branch?: string | null
  pr?: string | null
  started_at?: string | null
  heartbeat_at?: string | null
  ended_at?: string | null
  heartbeat_age_minutes?: number | null
  note?: string | null
  takeover_of?: string[]
  taken_over_by?: string[]
}

export type AgentClaimBoardPayload = {
  schema?: string
  as_of?: string
  claims_dir?: string
  dir_present?: boolean
  stale_after_hours?: number
  compact_after_days?: number
  counts?: Partial<Record<AgentClaimRow['state'], number>>
  unreadable?: string[]
  truncated?: boolean
  claims?: AgentClaimRow[]
}

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 14, minWidth: 0 }
const cell: CSSProperties = { padding: '6px 6px', fontSize: TYPE.sm, color: TOKENS.text[1], verticalAlign: 'top', textAlign: 'left' }
const mono: CSSProperties = { ...cell, fontFamily: FONT.mono }
const muted: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[2] }
const s = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : String(v))

export const STATE_HELP: Record<AgentClaimRow['state'], string> = {
  live: 'Active claim with a heartbeat inside the stale window. Other sessions are refused on these paths.',
  stale: 'Active claim with no heartbeat inside the stale window (or taken over). It no longer blocks; a new claim over it records a takeover.',
  done: 'Released as finished. Kept until weekly compaction archives it to claims_history.jsonl.',
  abandoned: 'Released without finishing (or lost a simultaneous-claim race). Kept until weekly compaction.',
}
const STATE_TONE: Record<AgentClaimRow['state'], Tone> = { live: 'success', stale: 'warning', done: 'neutral', abandoned: 'neutral' }

export function etTime(v: unknown): string {
  const t = Date.parse(String(v ?? ''))
  if (!Number.isFinite(t)) return s(v)
  return new Date(t).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) + ' ET'
}

export function ageLabel(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || !Number.isFinite(minutes)) return '—'
  if (minutes < 60) return `${Math.round(minutes)}m ago`
  if (minutes < 48 * 60) return `${(minutes / 60).toFixed(1)}h ago`
  return `${Math.round(minutes / 1440)}d ago`
}

export default function AgentClaimsPanel({ active = true }: { active?: boolean }) {
  const [showFinished, setShowFinished] = useState(false)
  const api = useApi<AgentClaimBoardPayload>('/api/v2/coordination/claims', 30_000, { enabled: active })
  const d = api.data
  const rows = useMemo(
    () => (Array.isArray(d?.claims) ? d!.claims! : []).filter(r => showFinished || r.state === 'live' || r.state === 'stale'),
    [d, showFinished],
  )
  const counts = d?.counts || {}
  const staleH = d?.stale_after_hours ?? 2
  return <section data-testid="agent-claims" style={{ display: 'grid', gap: 12, minWidth: 0, maxWidth: '100%' }}>
    <div style={panel}>
      <h1 style={{ margin: 0, fontSize: TYPE.lg, color: TOKENS.text[0] }}>Who's working on what</h1>
      <p style={muted}>
        Each coding-agent session (Claude, Codex, Cursor — equal peers, no master) claims the files it will edit before it starts.
        A second session asking for an overlapping path is refused and told who holds it. Read-only here; agents use{' '}
        <code style={{ fontFamily: FONT.mono }}>scripts/agent_claim.py</code>.
      </p>
      <ChipRow>
        <Chip tone={api.error ? 'warning' : 'neutral'} title="Board read status">{api.loading && !d ? 'Loading' : api.error ? 'Unavailable' : d?.dir_present === false ? 'No claims yet' : 'Read'}</Chip>
        <Chip tone="neutral" title="When the server read the claims directory">Observed {etTime(d?.as_of)}</Chip>
        <Chip tone={(counts.live || 0) > 0 ? 'success' : 'neutral'} title={STATE_HELP.live}>live {counts.live ?? 0}</Chip>
        <Chip tone={(counts.stale || 0) > 0 ? 'warning' : 'neutral'} title={STATE_HELP.stale}>stale {counts.stale ?? 0}</Chip>
        <Chip tone="neutral" title={STATE_HELP.done}>done {counts.done ?? 0}</Chip>
        <Chip tone="neutral" title={STATE_HELP.abandoned}>abandoned {counts.abandoned ?? 0}</Chip>
        <Chip tone="neutral" title={`A claim with no heartbeat for ${staleH} h stops blocking; finished and stale claims older than ${d?.compact_after_days ?? 7} days are archived weekly.`}>stale after {staleH}h</Chip>
        <Chip tone="info" onClick={() => setShowFinished(v => !v)} title="Show or hide claims already released (done / abandoned)">
          {showFinished ? 'hide finished' : 'show finished'}
        </Chip>
      </ChipRow>
      {api.error ? <p role="alert" style={muted}>Claim board unavailable. No claims are shown — that is not the same as nobody working.</p> : null}
      {d?.unreadable?.length ? <p role="alert" style={muted} title={d.unreadable.join(', ')}>{d.unreadable.length} claim file(s) unreadable — not counted above.</p> : null}
    </div>
    <div style={panel}>
      <div style={{ overflowX: 'auto' }}>
        <table aria-label="Agent claims" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr>
            {[
              ['State', 'live blocks other sessions; stale no longer blocks'],
              ['Who', 'vendor / agent (session id on hover)'],
              ['Task', 'what the session said it is doing'],
              ['Paths', 'files, directories or globs claimed; a directory claims everything under it'],
              ['Branch / PR', 'where the work lands'],
              ['Since', 'when the claim was made (ET)'],
              ['Heartbeat', 'last sign of life; refreshed by the agent while it works'],
            ].map(([h, tip]) => <th key={h} title={tip} style={{ ...cell, color: TOKENS.text[3], whiteSpace: 'nowrap' }}>{h}</th>)}
          </tr></thead>
          <tbody>
            {rows.map(r => <tr key={r.claim_id} data-testid="agent-claim-row" style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
              <td style={cell}><Chip tone={STATE_TONE[r.state] || 'neutral'} title={STATE_HELP[r.state] + (r.taken_over_by?.length ? ` Taken over by ${r.taken_over_by.join(', ')}.` : '')}>{r.state}</Chip></td>
              <td style={cell} title={`session ${s(r.session)} · claim ${r.claim_id}`}>{s(r.vendor)} / {s(r.agent || r.session)}</td>
              <td style={cell} title={r.note ? `note: ${r.note}` : undefined}>{s(r.task)}</td>
              <td style={mono} title={(r.paths || []).join('\n')}>{(r.paths || []).slice(0, 4).join(', ')}{(r.paths?.length || 0) > 4 ? ` +${(r.paths!.length - 4)}` : ''}</td>
              <td style={mono}>{s(r.branch)}{r.pr ? <> · PR {r.pr}</> : null}</td>
              <td style={mono} title={s(r.started_at)}>{etTime(r.started_at)}</td>
              <td style={mono} title={s(r.heartbeat_at)}>{ageLabel(r.heartbeat_age_minutes)}{r.takeover_of?.length ? ` · took over ${r.takeover_of.length}` : ''}</td>
            </tr>)}
            {!rows.length ? <tr><td colSpan={7} style={{ ...cell, color: TOKENS.text[2] }}>{api.error ? 'Unavailable.' : showFinished ? 'No claims on the board.' : 'Nobody has an active claim right now.'}</td></tr> : null}
          </tbody>
        </table>
      </div>
      {d?.truncated ? <p style={muted}>Showing the first {rows.length} claims.</p> : null}
    </div>
  </section>
}

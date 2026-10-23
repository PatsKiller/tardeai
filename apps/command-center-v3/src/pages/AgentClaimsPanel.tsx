// Who's working on what (agent claim board, operator-approved 2026-10-22; lifecycle whiteboard 2026-10-23).
// Read-only view of GET /api/v2/coordination/claims (scripts/lib/agent_claim_board.py + agent_claim_lifecycle.py):
// every Claude, Codex and Cursor session's claim on files and where that work is — claimed, building, PR open,
// CI green, merged, released (live) — with a time per stage. All vendors are equal peers; nothing here claims,
// stages or releases (agents use scripts/agent_claim.py). Grouping/filter/label logic: lib/agentClaimLifecycle.ts.
import { useMemo, useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow } from '../components/primitives'
import { RADIUS, TOKENS, TYPE, FONT, type Tone } from '../lib/designTokens'
import {
  STAGES, STAGE_HELP, STAGE_LABEL, STAGE_TONE, ageLabel as shortAge, ciView, filterCards, groupByStage, lockView,
  prLabel, stageOf, timeline, vendorsOf, warningOf, type ClaimCard, type Stage,
} from '../lib/agentClaimLifecycle'

export type AgentClaimRow = ClaimCard

export type AgentClaimBoardPayload = {
  schema?: string
  as_of?: string
  claims_dir?: string
  dir_present?: boolean
  stale_after_hours?: number
  compact_after_days?: number
  counts?: Partial<Record<AgentClaimRow['state'], number>>
  stages?: Stage[]
  stage_counts?: Partial<Record<Stage, number>>
  stage_help?: Partial<Record<Stage, string>>
  lifecycle?: { observed_at?: string | null; warning?: string | null; refreshing?: boolean; ttl_s?: number; repo?: string | null }
  unreadable?: string[]
  truncated?: boolean
  claims?: AgentClaimRow[]
}

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 14, minWidth: 0 }
const cell: CSSProperties = { padding: '6px 6px', fontSize: TYPE.sm, color: TOKENS.text[1], verticalAlign: 'top', textAlign: 'left' }
const mono: CSSProperties = { ...cell, fontFamily: FONT.mono }
const muted: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[2] }
const small: CSSProperties = { fontSize: TYPE.xs, color: TOKENS.text[2] }
const select: CSSProperties = { background: TOKENS.bg[2], color: TOKENS.text[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, padding: '3px 6px', fontSize: TYPE.sm }
const s = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : String(v))

export const STATE_HELP: Record<AgentClaimRow['state'], string> = {
  live: 'Active claim with a heartbeat inside the stale window. Other sessions are refused on these paths until it merges.',
  stale: 'Active claim with no heartbeat inside the stale window (or taken over). It no longer blocks; a new claim over it records a takeover.',
  done: 'Released by its agent. A claim with a PR stays on the board until the PR is merged and live.',
  abandoned: 'Released without finishing (or lost a simultaneous-claim race). Kept until weekly compaction.',
}
const STATE_TONE: Record<AgentClaimRow['state'], Tone> = { live: 'success', stale: 'warning', done: 'neutral', abandoned: 'neutral' }

export function etTime(v: unknown): string {
  const t = Date.parse(String(v ?? ''))
  if (!Number.isFinite(t)) return s(v)
  return new Date(t).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) + ' ET'
}

export function ageLabel(minutes: number | null | undefined): string {
  const a = shortAge(minutes)
  return a === '—' ? a : `${a} ago`
}

function PrLink({ c }: { c: ClaimCard }) {
  const label = prLabel(c)
  if (label === '—') return <span title="No pull request yet">no PR</span>
  return c.pr_url
    ? <a href={c.pr_url} target="_blank" rel="noreferrer" title={`Open the pull request on GitHub${c.pr_base ? ` (base ${c.pr_base})` : ''}`} style={{ color: TOKENS.text[0] }}>{label}</a>
    : <span title="PR number declared by the agent; not yet observed on GitHub">{label}</span>
}

function StageTimes({ c }: { c: ClaimCard }) {
  const tl = timeline(c)
  return <span title={tl.map(x => `${STAGE_LABEL[x.stage]}: ${etTime(x.at)}`).join('\n')}>
    {tl.map((x, i) => <span key={x.stage}>{i ? ' → ' : ''}{STAGE_LABEL[x.stage]} {etTime(x.at).replace(' ET', '')}</span>)}
  </span>
}

function Card({ c, staleH }: { c: ClaimCard; staleH: number }) {
  const ci = ciView(c)
  const lock = lockView(c)
  const warn = warningOf(c)
  return <div data-testid="agent-claim-card" style={{ border: `1px solid ${warn ? TOKENS.warning : TOKENS.borderSubtle}`, borderRadius: RADIUS.sm, padding: 8, display: 'grid', gap: 4, background: TOKENS.bg[0], minWidth: 0 }}>
    <div style={{ fontSize: TYPE.sm, color: TOKENS.text[0], overflowWrap: 'anywhere' }} title={c.note ? `note: ${c.note}` : 'What the agent said it is doing'}>{s(c.task)}</div>
    <div style={small} title={`session ${s(c.session)} · claim ${c.claim_id}`}>{s(c.vendor)} / {s(c.agent || c.session)}</div>
    <div style={{ ...small, fontFamily: FONT.mono, overflowWrap: 'anywhere' }} title={(c.paths || []).join('\n')}>
      {(c.paths || []).slice(0, 3).join(', ')}{(c.paths?.length || 0) > 3 ? ` +${c.paths!.length - 3}` : ''}
    </div>
    <div style={{ ...small, fontFamily: FONT.mono, overflowWrap: 'anywhere' }} title="Branch the work lands on">{s(c.branch)}</div>
    <ChipRow>
      <Chip tone="neutral" title="Pull request (GitHub, read-only)"><PrLink c={c} /></Chip>
      <Chip tone={ci.tone} title={ci.title}>{ci.label}</Chip>
      <Chip tone={c.state === 'stale' && c.locks_held !== false ? 'warning' : 'neutral'} title={lock.title}>{lock.label}</Chip>
      <Chip tone={STATE_TONE[c.state] || 'neutral'} title={STATE_HELP[c.state] + ` Stale after ${staleH} h without a heartbeat.`}>{c.state} · hb {shortAge(c.heartbeat_age_minutes)}</Chip>
    </ChipRow>
    <div style={small}><StageTimes c={c} /></div>
    <div style={small} title="Time since the claim was made (to release, once live)">age {shortAge(c.age_minutes)}</div>
    {warn ? <div role="alert" style={{ ...small, color: TOKENS.text[0] }} title={(c.warnings || [warn]).join('\n')}>⚠ {warn}</div> : null}
  </div>
}

export default function AgentClaimsPanel({ active = true }: { active?: boolean }) {
  const [showFinished, setShowFinished] = useState(false)
  const [vendor, setVendor] = useState('all')
  const [stage, setStage] = useState<Stage | 'all'>('all')
  const [view, setView] = useState<'board' | 'table'>('board')
  const api = useApi<AgentClaimBoardPayload>('/api/v2/coordination/claims', 30_000, { enabled: active })
  const d = api.data
  const all = useMemo(() => (Array.isArray(d?.claims) ? d!.claims! : []), [d])
  const rows = useMemo(() => filterCards(all, { vendor, stage, showFinished }), [all, vendor, stage, showFinished])
  const groups = useMemo(() => groupByStage(rows), [rows])
  const vendors = useMemo(() => vendorsOf(all), [all])
  const help = (st: Stage) => d?.stage_help?.[st] || STAGE_HELP[st]
  const counts = d?.counts || {}
  const staleH = d?.stale_after_hours ?? 2
  const lc = d?.lifecycle
  const columns = STAGES.filter(st => stage === 'all' ? (showFinished || (st !== 'released' && st !== 'abandoned') || groups[st].length > 0) : st === stage)
  return <section data-testid="agent-claims" style={{ display: 'grid', gap: 12, minWidth: 0, maxWidth: '100%' }}>
    <div style={panel}>
      <h1 style={{ margin: 0, fontSize: TYPE.lg, color: TOKENS.text[0] }}>Who's working on what</h1>
      <p style={muted}>
        Each coding-agent session (Claude, Codex, Cursor — equal peers, no master) claims the files it will edit before it starts,
        and its card moves from <b>claimed</b> to <b>released (live)</b>. A second session asking for an overlapping path is refused
        until the holder's PR merges. Read-only here; agents use <code style={{ fontFamily: FONT.mono }}>scripts/agent_claim.py</code>.
      </p>
      <ChipRow>
        <Chip tone={api.error ? 'warning' : 'neutral'} title="Board read status">{api.loading && !d ? 'Loading' : api.error ? 'Unavailable' : d?.dir_present === false ? 'No claims yet' : 'Read'}</Chip>
        <Chip tone="neutral" title="When the server read the claims directory">Observed {etTime(d?.as_of)}</Chip>
        <Chip tone={lc?.warning ? 'warning' : 'neutral'} title={lc?.warning ? `GitHub/release observation degraded: ${lc.warning}. Stages fall back to what agents declared; locks stay held.` : `PR, CI and release stages last observed ${etTime(lc?.observed_at)} (GitHub GET only, cached ${lc?.ttl_s ?? 120} s; release receipts on this host).`}>
          {lc?.warning ? 'GitHub: degraded' : `GitHub ${etTime(lc?.observed_at)}`}
        </Chip>
        <Chip tone={(counts.live || 0) > 0 ? 'success' : 'neutral'} title={STATE_HELP.live}>live {counts.live ?? 0}</Chip>
        <Chip tone={(counts.stale || 0) > 0 ? 'warning' : 'neutral'} title={STATE_HELP.stale}>stale {counts.stale ?? 0}</Chip>
        <Chip tone="neutral" title={`A claim with no heartbeat for ${staleH} h stops blocking; released, finished and stale claims older than ${d?.compact_after_days ?? 7} days are archived weekly. Work with a PR stays until it is live.`}>stale after {staleH}h</Chip>
      </ChipRow>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginTop: 8 }}>
        <label style={muted} title="Show one vendor's sessions only">Vendor{' '}
          <select aria-label="Filter by vendor" style={select} value={vendor} onChange={e => setVendor(e.target.value)}>
            <option value="all">all</option>
            {vendors.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label style={muted} title="Show one lifecycle stage only">Stage{' '}
          <select aria-label="Filter by stage" style={select} value={stage} onChange={e => setStage(e.target.value as Stage | 'all')}>
            <option value="all">all</option>
            {STAGES.map(st => <option key={st} value={st} title={help(st)}>{STAGE_LABEL[st]}</option>)}
          </select>
        </label>
        <Chip tone="info" onClick={() => setShowFinished(v => !v)} title="Show or hide finished work: released (live), abandoned, and claims released with no PR">
          {showFinished ? 'hide finished' : 'show finished'}
        </Chip>
        <Chip tone="info" onClick={() => setView(v => v === 'board' ? 'table' : 'board')} title="Switch between the stage columns and one table">
          {view === 'board' ? 'table view' : 'board view'}
        </Chip>
      </div>
      {api.error ? <p role="alert" style={muted}>Claim board unavailable. No claims are shown — that is not the same as nobody working.</p> : null}
      {d?.unreadable?.length ? <p role="alert" style={muted} title={d.unreadable.join(', ')}>{d.unreadable.length} claim file(s) unreadable — not counted above.</p> : null}
    </div>
    {view === 'board' ? <div style={{ ...panel, overflowX: 'auto' }}>
      <div data-testid="agent-claim-kanban" style={{ display: 'grid', gridTemplateColumns: `repeat(${columns.length}, minmax(220px, 1fr))`, gap: 10 }}>
        {columns.map(st => <div key={st} data-testid={`agent-claim-col-${st}`} style={{ display: 'grid', gap: 8, alignContent: 'start', minWidth: 0 }}>
          <div title={help(st)} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6 }}>
            <Chip tone={STAGE_TONE[st]} title={help(st)}>{STAGE_LABEL[st]}</Chip>
            <span style={small}>{groups[st].length}</span>
          </div>
          {groups[st].map(c => <Card key={c.claim_id} c={c} staleH={staleH} />)}
          {!groups[st].length ? <div style={small}>—</div> : null}
        </div>)}
      </div>
      {!rows.length ? <p style={muted}>{api.error ? 'Unavailable.' : showFinished ? 'No claims on the board.' : 'Nobody has work in flight right now.'}</p> : null}
    </div> : <div style={panel}>
      <div style={{ overflowX: 'auto' }}>
        <table aria-label="Agent claims" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr>
            {[
              ['Stage', 'Lifecycle stage: claimed → building → PR open → CI green → merged → released (live)'],
              ['Who', 'vendor / agent (session id on hover)'],
              ['Task', 'what the session said it is doing'],
              ['Paths', 'files, directories or globs claimed; a directory claims everything under it'],
              ['Branch / PR', 'where the work lands; PR links to GitHub'],
              ['CI', 'required checks on the PR head commit'],
              ['Files', 'held = other sessions are refused; free after merge'],
              ['Stage times', 'when each stage was reached (ET)'],
              ['Age', 'since the claim was made'],
              ['Heartbeat', 'last sign of life; refreshed by the agent while it works'],
              ['Warning', 'stale, CI failing, PR closed unmerged, merged but not live'],
            ].map(([h, tip]) => <th key={h} title={tip} style={{ ...cell, color: TOKENS.text[3], whiteSpace: 'nowrap' }}>{h}</th>)}
          </tr></thead>
          <tbody>
            {rows.map(r => {
              const st = stageOf(r)
              const ci = ciView(r)
              const lock = lockView(r)
              return <tr key={r.claim_id} data-testid="agent-claim-row" style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
                <td style={cell}><Chip tone={STAGE_TONE[st]} title={help(st) + (r.taken_over_by?.length ? ` Taken over by ${r.taken_over_by.join(', ')}.` : '')}>{STAGE_LABEL[st]}</Chip></td>
                <td style={cell} title={`session ${s(r.session)} · claim ${r.claim_id}`}>{s(r.vendor)} / {s(r.agent || r.session)}</td>
                <td style={cell} title={r.note ? `note: ${r.note}` : undefined}>{s(r.task)}</td>
                <td style={mono} title={(r.paths || []).join('\n')}>{(r.paths || []).slice(0, 4).join(', ')}{(r.paths?.length || 0) > 4 ? ` +${(r.paths!.length - 4)}` : ''}</td>
                <td style={mono}>{s(r.branch)} · <PrLink c={r} /></td>
                <td style={cell}><Chip tone={ci.tone} title={ci.title}>{ci.label}</Chip></td>
                <td style={cell} title={lock.title}>{lock.label}</td>
                <td style={{ ...cell, fontSize: TYPE.xs }}><StageTimes c={r} /></td>
                <td style={mono}>{shortAge(r.age_minutes)}</td>
                <td style={mono} title={`${s(r.heartbeat_at)} · ${STATE_HELP[r.state]}`}>{r.state} · {ageLabel(r.heartbeat_age_minutes)}{r.takeover_of?.length ? ` · took over ${r.takeover_of.length}` : ''}</td>
                <td style={cell} title={(r.warnings || []).join('\n')}>{warningOf(r) || '—'}</td>
              </tr>
            })}
            {!rows.length ? <tr><td colSpan={11} style={{ ...cell, color: TOKENS.text[2] }}>{api.error ? 'Unavailable.' : showFinished ? 'No claims on the board.' : 'Nobody has work in flight right now.'}</td></tr> : null}
          </tbody>
        </table>
      </div>
      {d?.truncated ? <p style={muted}>Showing the first {rows.length} claims.</p> : null}
    </div>}
  </section>
}

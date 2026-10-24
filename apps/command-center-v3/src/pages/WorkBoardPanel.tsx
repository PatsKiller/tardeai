// Coordination → Work board (operator 2026-10-23): ALL queued work broken into tasks — task board entries, operator
// to-dos, claims and open PRs — with stage open → claimed → in progress → in review → merged → live, who holds each,
// and the designs it belongs to (DSN-<date>-<slug> → P<n> → T<m>) plus what awaits operator approval.
// Read-only: GET /api/v2/coordination/tasks and /designs (scripts/lib/design_registry.py). Taking work is a CLI act:
// scripts/agent_claim.py take <task-id> (refused on a file-level overlap). Model: lib/workBoard.ts.
import { useMemo, useState, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow } from '../components/primitives'
import { RADIUS, TOKENS, TYPE, FONT } from '../lib/designTokens'
import {
  WORK_STAGES, WORK_STAGE_HELP, WORK_STAGE_LABEL, designProgress, filterWork, groupWork, holderLabel, phaseProgress,
  sourcesOf, statusTone, takeCommand, type AwaitingItem, type Design, type WorkItem, type WorkStage,
} from '../lib/workBoard'

type TasksPayload = { as_of?: string; items?: WorkItem[]; counts?: Record<string, number>; open_prs_warning?: string | null; sources?: Record<string, number | null> }
type DesignsPayload = { as_of?: string; designs?: Design[]; awaiting_approval?: AwaitingItem[]; errors?: Array<{ path: string; error: string }>; store?: string }

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 14, minWidth: 0 }
const muted: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[2] }
const small: CSSProperties = { fontSize: TYPE.xs, color: TOKENS.text[2] }
const select: CSSProperties = { background: TOKENS.bg[2], color: TOKENS.text[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, padding: '3px 6px', fontSize: TYPE.sm }
const cell: CSSProperties = { padding: '5px 6px', fontSize: TYPE.sm, color: TOKENS.text[1], verticalAlign: 'top', textAlign: 'left' }

function et(v: unknown): string {
  const t = Date.parse(String(v ?? ''))
  return Number.isFinite(t) ? new Date(t).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) + ' ET' : '—'
}

function ItemCard({ it }: { it: WorkItem }) {
  const take = takeCommand(it)
  return <div data-testid="work-item" style={{ border: `1px solid ${it.blocked_by?.length ? TOKENS.warning : TOKENS.borderSubtle}`, borderRadius: RADIUS.sm, padding: 8, display: 'grid', gap: 4, background: TOKENS.bg[0], minWidth: 0 }}>
    <div style={{ fontSize: TYPE.sm, color: TOKENS.text[0], overflowWrap: 'anywhere' }} title={it.title || it.id}>{it.title || it.id}</div>
    <div style={{ ...small, fontFamily: FONT.mono, overflowWrap: 'anywhere' }} title={`id ${it.id}${it.design_id ? ` · design ${it.design_id}` : ''}`}>{it.id}</div>
    {it.areas?.length ? <div style={{ ...small, fontFamily: FONT.mono, overflowWrap: 'anywhere' }} title={it.areas.join('\n')}>{it.areas.slice(0, 3).join(', ')}{it.areas.length > 3 ? ` +${it.areas.length - 3}` : ''}</div> : null}
    <ChipRow>
      <Chip tone="neutral" title="Where this item comes from: task board, operator to-do, design task, a claim with no task, or an open PR">{it.source || '?'}</Chip>
      <Chip tone={it.holder ? 'info' : 'neutral'} title={it.claimed_at ? `Held since ${et(it.claimed_at)}${it.claim_id ? ` · claim ${it.claim_id}` : ''}` : 'Nobody holds it'}>{holderLabel(it)}</Chip>
      {it.pr_number ? <Chip tone="neutral" title="Linked pull request">{it.pr_url ? <a href={it.pr_url} target="_blank" rel="noreferrer" style={{ color: TOKENS.text[0] }}>PR {it.pr_number}{it.draft ? ' draft' : ''}</a> : `PR ${it.pr_number}`}</Chip> : null}
      {it.claim_id ? <Chip tone={it.worklog ? 'neutral' : 'warning'} title={it.worklog ? "Worklog: open it on Who's working (worklog chip), or agent_claim.py takeover <claim_id>" : 'This claim has no worklog'}>{it.worklog ? 'worklog' : 'no worklog'}</Chip> : null}
      {it.blocked_by?.length ? <Chip tone="warning" title={`Waits on ${it.blocked_by.join(', ')}`}>blocked</Chip> : null}
    </ChipRow>
    {take ? <code style={{ ...small, fontFamily: FONT.mono, overflowWrap: 'anywhere' }} title="Any agent takes it with this command (refused if its files overlap a live claim)">{take}</code> : null}
  </div>
}

export default function WorkBoardPanel({ active = true }: { active?: boolean }) {
  const tasks = useApi<TasksPayload>('/api/v2/coordination/tasks', 30_000, { enabled: active })
  const designs = useApi<DesignsPayload>('/api/v2/coordination/designs', 60_000, { enabled: active })
  const [source, setSource] = useState('all')
  const [stage, setStage] = useState<WorkStage | 'all'>('all')
  const [text, setText] = useState('')
  const items = useMemo(() => tasks.data?.items || [], [tasks.data])
  const shown = useMemo(() => filterWork(items, { source, stage, text }), [items, source, stage, text])
  const g = useMemo(() => groupWork(shown), [shown])
  const cols = stage === 'all' ? WORK_STAGES : WORK_STAGES.filter(s => s === stage)
  const ds = designs.data?.designs || []
  const awaiting = designs.data?.awaiting_approval || []
  return <section data-testid="work-board" style={{ display: 'grid', gap: 12, minWidth: 0 }}>
    <div style={panel}>
      <h1 style={{ margin: 0, fontSize: TYPE.lg, color: TOKENS.text[0] }}>Work board</h1>
      <p style={muted}>All queued work, broken into tasks: the task board (agent and operator to-dos, design tasks), claims with no task, and open pull requests.
        Any agent takes an open task with <code style={{ fontFamily: FONT.mono }}>scripts/agent_claim.py take &lt;task-id&gt;</code>; a task whose files overlap a live claim is refused. Read-only here.</p>
      <ChipRow>
        <Chip tone={tasks.error ? 'warning' : 'neutral'} title="When the server built this view (rebuilt at most every 30 s)">{tasks.error ? 'Unavailable' : `Observed ${et(tasks.data?.as_of)}`}</Chip>
        {tasks.data?.open_prs_warning ? <Chip tone="warning" title={tasks.data.open_prs_warning}>open PRs: degraded</Chip> : <Chip tone="neutral" title="Open pull requests read from GitHub (GET only, cached)">open PRs {tasks.data?.sources?.open_prs ?? '—'}</Chip>}
        {WORK_STAGES.map(s => <Chip key={s} tone="neutral" title={WORK_STAGE_HELP[s]}>{WORK_STAGE_LABEL[s]} {tasks.data?.counts?.[s] ?? 0}</Chip>)}
      </ChipRow>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', marginTop: 8 }}>
        <label style={muted} title="Show one source only">Source{' '}
          <select aria-label="Filter by source" style={select} value={source} onChange={e => setSource(e.target.value)}>
            <option value="all">all</option>{sourcesOf(items).map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label style={muted} title="Show one stage only">Stage{' '}
          <select aria-label="Filter by stage" style={select} value={stage} onChange={e => setStage(e.target.value as WorkStage | 'all')}>
            <option value="all">all</option>{WORK_STAGES.map(s => <option key={s} value={s}>{WORK_STAGE_LABEL[s]}</option>)}
          </select>
        </label>
        <label style={muted} title="Match id, title or files">Find{' '}
          <input aria-label="Search work" style={select} value={text} onChange={e => setText(e.target.value)} placeholder="id, title, file" />
        </label>
      </div>
      {tasks.error ? <p role="alert" style={muted}>Work board unavailable — that is not the same as no work queued.</p> : null}
    </div>
    <div style={{ ...panel, overflowX: 'auto' }}>
      <div data-testid="work-kanban" style={{ display: 'grid', gridTemplateColumns: `repeat(${cols.length}, minmax(210px, 1fr))`, gap: 10 }}>
        {cols.map(s => <div key={s} style={{ display: 'grid', gap: 8, alignContent: 'start', minWidth: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><Chip tone={s === 'live' || s === 'merged' ? 'success' : s === 'open' ? 'neutral' : 'info'} title={WORK_STAGE_HELP[s]}>{WORK_STAGE_LABEL[s]}</Chip><span style={small}>{g[s].length}</span></div>
          {g[s].map(it => <ItemCard key={it.id} it={it} />)}
          {!g[s].length ? <div style={small}>—</div> : null}
        </div>)}
      </div>
    </div>
    <div style={panel} data-testid="designs-awaiting">
      <h2 style={{ margin: '0 0 8px', fontSize: TYPE.md, color: TOKENS.text[0] }} title="Designs, packages and packets whose next step is an operator decision">Designs awaiting approval ({awaiting.length})</h2>
      {designs.error ? <p role="alert" style={muted}>Designs unavailable.</p> : null}
      <div style={{ overflowX: 'auto' }}>
        <table aria-label="Designs awaiting approval" style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr>{[['Kind', 'design (docs/designs) or operator packet (docs/ops/packets)'], ['Item', 'id and title'], ['Status', 'as written in the file'], ['Approval', 'awaiting operator / approved'], ['File', 'where to read it']].map(([h, tip]) => <th key={h} title={tip} style={{ ...cell, color: TOKENS.text[3] }}>{h}</th>)}</tr></thead>
          <tbody>
            {awaiting.map(a => <tr key={`${a.kind}-${a.id}`} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
              <td style={cell}>{a.kind}</td>
              <td style={cell} title={a.id}>{a.title}</td>
              <td style={cell}><Chip tone={statusTone(a.status)} title={a.status}>{a.status.slice(0, 40)}</Chip></td>
              <td style={cell}>{a.approval}</td>
              <td style={{ ...cell, fontFamily: FONT.mono, overflowWrap: 'anywhere' }}>{a.path || '—'}</td>
            </tr>)}
            {!awaiting.length ? <tr><td colSpan={5} style={{ ...cell, color: TOKENS.text[2] }}>Nothing awaiting the operator.</td></tr> : null}
          </tbody>
        </table>
      </div>
    </div>
    <div style={panel} data-testid="designs-tree">
      <h2 style={{ margin: '0 0 8px', fontSize: TYPE.md, color: TOKENS.text[0] }} title={`Registry: ${designs.data?.store || 'docs/designs'}/<DSN id>.md`}>Designs → phases → tasks</h2>
      {designs.data?.errors?.length ? <p role="alert" style={muted} title={designs.data.errors.map(e => `${e.path}: ${e.error}`).join('\n')}>{designs.data.errors.length} design file(s) do not parse — not shown.</p> : null}
      {ds.map(d => {
        const pr = designProgress(d)
        return <details key={d.id} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}`, padding: '6px 0' }}>
          <summary style={{ cursor: 'pointer', fontSize: TYPE.sm, color: TOKENS.text[0] }} title={d.summary || d.id}>
            <Chip tone={statusTone(d.status)} title="Design status">{d.status}</Chip> {d.title} <span style={small}>· {d.id} · {pr.phases} · {pr.tasks}{d.approval ? ` · approval: ${d.approval}` : ''}</span>
          </summary>
          <div style={{ display: 'grid', gap: 6, padding: '6px 0 0 12px' }}>
            {d.path ? <div style={{ ...small, fontFamily: FONT.mono }} title="The design file">{d.path}{d.source ? ` · source ${d.source}` : ''}</div> : null}
            {d.phases.map(p => <div key={p.id}>
              <div style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }} title={p.id}><Chip tone={statusTone(p.status)} title="Phase status">{p.status}</Chip> {p.id.split('-').slice(-1)[0]} {p.title} <span style={small}>· {phaseProgress(p)}</span></div>
              {p.tasks.map(t => <div key={t.id} style={{ ...small, paddingLeft: 16 }} title={(t.areas || []).join('\n') || t.id}>
                <Chip tone={statusTone(t.status)} title="Task status (a task taken on the board shows IN_PROGRESS)">{t.status}</Chip> <span style={{ fontFamily: FONT.mono }}>{t.id.split('-').slice(-2).join('-')}</span> {t.title} · {t.holder || (t.registered ? 'free on the board' : 'not on the task board yet')}
              </div>)}
            </div>)}
          </div>
        </details>
      })}
      {!ds.length ? <p style={muted}>No designs registered yet (docs/designs/DSN-*.md).</p> : null}
    </div>
  </section>
}

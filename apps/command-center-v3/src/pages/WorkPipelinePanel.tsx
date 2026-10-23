// Coordination → Work pipeline (operator 2026-10-23 13:15 ET): the default Coordination view. One row per WORK ITEM
// (task, PR, design phase), not per file, staged as an incubator workflow Proposed → … → Verified live, each stage
// cell green (done) / amber (in progress or waiting) / red (blocked, failed, stale) / grey (not reached), with who,
// what, when, where, how, the blocker and the NEXT STEP with its owner. Filters live in the URL.
// Read: GET /api/v2/coordination/pipeline (scripts/lib/work_pipeline.py). Act (Tier 1, operator only):
// POST /api/v2/coordination/commands (scripts/lib/work_pipeline_commands.py). Model: lib/workPipeline.ts.
import { useCallback, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { Chip } from '../components/primitives'
import { RADIUS, TOKENS, TYPE, FONT, toneVars } from '../lib/designTokens'
import {
  PIPELINE_STAGES, PRESETS, STAGE_LABEL, ageLabel, cardActions, cellTitle, filterFromParams, filterItems, filterOptions,
  filterToParams, planLabel, queuedSections, ragTone, summarize, type PipelineFilter, type PipelineItem, type PipelinePayload,
} from '../lib/workPipeline'
import { copyText, parseSplitParts, sendCommand, type CommandName, type CommandResult } from '../lib/workPipelineActions'

const QUEUE_CAP = 6
const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 12, minWidth: 0 }
const small: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[2] }
const mono: CSSProperties = { fontFamily: FONT.mono, fontSize: TYPE.sm, overflowWrap: 'anywhere' }
const select: CSSProperties = { background: TOKENS.bg[2], color: TOKENS.text[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, padding: '4px 6px', fontSize: TYPE.sm, maxWidth: '100%' }
const btn: CSSProperties = { background: TOKENS.bg[2], color: TOKENS.text[0], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, padding: '3px 8px', fontSize: TYPE.sm, cursor: 'pointer' }
const linkStyle: CSSProperties = { color: TOKENS.info, fontSize: TYPE.sm }
const dt: CSSProperties = { fontSize: TYPE.xs, color: TOKENS.text[3], textTransform: 'uppercase', letterSpacing: 0.4, paddingTop: 2 }
const dd: CSSProperties = { margin: 0, fontSize: TYPE.base, color: TOKENS.text[1], overflowWrap: 'anywhere', minWidth: 0 }

function et(v: unknown): string {
  const t = Date.parse(String(v ?? ''))
  return Number.isFinite(t) ? new Date(t).toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) + ' ET' : '—'
}

function cellStyle(rag: PipelineItem['rag'], current: boolean): CSSProperties {
  const tone = toneVars(ragTone(rag))
  return {
    height: 22, borderRadius: RADIUS.sm, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 2px',
    fontSize: TYPE.xs, fontWeight: current ? 800 : 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0,
    background: rag === 'grey' ? TOKENS.bg[2] : tone.bg, color: rag === 'grey' ? TOKENS.text[3] : tone.color,
    border: `1px solid ${current ? tone.color : rag === 'grey' ? TOKENS.borderSubtle : tone.border}`,
  }
}

function StageCells({ it }: { it: PipelineItem }) {
  return <div data-testid="stage-cells" className="wp-stages" style={{ display: 'grid', gridTemplateColumns: 'repeat(11, minmax(0, 1fr))', gap: 3 }}>
    {it.cells.map(c => <div key={c.stage} data-stage={c.stage} data-rag={c.rag} title={cellTitle(c)} aria-label={cellTitle(c)} style={cellStyle(c.rag, c.stage === it.stage)}>
      <span className="wp-cell-text">{c.stage === it.stage && c.label ? c.label : STAGE_LABEL[c.stage]}</span>
    </div>)}
  </div>
}

type Busy = { itemId: string; text: string; ok?: boolean } | null

function ItemCard({ it, onAct, busy, onWorklog }: {
  it: PipelineItem
  onAct: (it: PipelineItem, cmd: CommandName, params: Record<string, unknown>) => void
  busy: Busy
  onWorklog: (claimId: string) => void
}) {
  const [compose, setCompose] = useState<null | 'note' | 'hold' | 'split' | 'release'>(null)
  const [text, setText] = useState('')
  const [copied, setCopied] = useState(false)
  const tone = toneVars(ragTone(it.rag))
  const acts = cardActions(it)
  const opNext = it.next.owner === 'operator'
  const pr = it.pr_number
  const prItem = pr ? `PR-${pr}` : it.id
  const target = it.what.task_id || (it.kind === 'claim' ? it.id : prItem)
  const submit = () => {
    if (compose === 'note' && text.trim()) onAct(it, 'note', { item: target, text: text.trim() })
    if (compose === 'hold') onAct(it, 'hold', { item: it.what.task_id || prItem, reason: text.trim() || undefined })
    if (compose === 'split') { const parts = parseSplitParts(text); if (parts.length) onAct(it, 'task_split', { task_id: it.what.task_id, parts }) }
    if (compose === 'release') onAct(it, 'release_stale_claim', { claim_id: it.actions?.stale_claims?.[0] })
    setCompose(null); setText('')
  }
  return <article data-testid="pipeline-item" data-item-id={it.id} data-rag={it.rag} data-stage={it.stage} data-owner={it.next.owner}
    style={{ border: `1px solid ${TOKENS.borderSubtle}`, borderLeft: `4px solid ${it.rag === 'grey' ? TOKENS.border : tone.color}`, borderRadius: RADIUS.sm, padding: '8px 10px', background: TOKENS.bg[0], display: 'grid', gap: 6, minWidth: 0 }}>
    <div className="wp-card-grid" style={{ display: 'grid', gap: '6px 14px' }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: TYPE.md, fontWeight: 650, color: TOKENS.text[0], overflowWrap: 'anywhere' }}>{it.what.title || it.id}</div>
        <div style={{ ...mono, color: TOKENS.text[2], display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <span>{it.id}</span>
          {it.what.design_id ? <span>{it.what.design_id}</span> : null}
          {it.what.priority ? <span>P{it.what.priority}</span> : null}
          {it.batch && !it.is_batch ? <span>batch PR {it.batch}</span> : null}
        </div>
        <dl style={{ display: 'grid', gridTemplateColumns: '48px minmax(0, 1fr)', gap: '2px 6px', margin: '4px 0 0' }}>
          <dt style={dt}>Who</dt><dd style={dd} data-testid="who">{it.who.label}{it.who.session ? <span style={{ ...small, fontFamily: FONT.mono }}> · {it.who.session}</span> : null}</dd>
          <dt style={dt}>When</dt><dd style={dd} data-testid="when">started {et(it.when.started)} · last activity {et(it.when.last_activity)} · <b>{ageLabel(it.when.stage_age_minutes)} in {STAGE_LABEL[it.stage]}</b></dd>
        </dl>
      </div>
      <div style={{ minWidth: 0 }}>
        <dl style={{ display: 'grid', gridTemplateColumns: '48px minmax(0, 1fr)', gap: '2px 6px', margin: 0 }}>
          <dt style={dt}>Where</dt>
          <dd style={dd} data-testid="where">
            <span style={mono}>{it.where.branch || '—'}</span>{it.where.worktree ? <span style={small}> · {it.where.worktree}</span> : null}
            {it.where.file_count ? <details style={{ display: 'inline' }}><summary style={{ ...small, cursor: 'pointer', display: 'inline' }}> · {it.where.file_count} file{it.where.file_count === 1 ? '' : 's'}</summary>
              <ul style={{ margin: '4px 0 0', paddingLeft: 16, ...mono }}>{it.where.files.map(f => <li key={f}>{f}</li>)}{it.where.file_count > it.where.files.length ? <li>…{it.where.file_count - it.where.files.length} more</li> : null}</ul>
            </details> : null}
          </dd>
          <dt style={dt}>How</dt>
          <dd style={dd} data-testid="how">plan {planLabel(it)}{it.how.latest ? <> · <i>{it.how.latest}</i></> : null}{it.how.operator_note?.text ? <> · <span style={{ color: TOKENS.info }}>note: {it.how.operator_note.text}</span></> : null}</dd>
          {it.blocker ? <><dt style={dt}>Blocker</dt><dd style={{ ...dd, color: TOKENS.danger }} data-testid="blocker">{it.blocker}</dd></> : null}
        </dl>
      </div>
    </div>
    <StageCells it={it} />
    <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }} data-testid="next">
      <span style={dt}>Next</span>
      <Chip tone={opNext ? 'info' : 'neutral'} variant={opNext ? 'solid' : 'outline'} title={opNext ? 'The operator owns this step' : 'An agent owns this step'}>{opNext ? 'OPERATOR' : 'AGENT'}</Chip>
      <b style={{ fontSize: TYPE.base, color: TOKENS.text[0], overflowWrap: 'anywhere' }}>{it.next.text}</b>
      {opNext && it.next.command ? <button type="button" style={btn} data-testid="copy-command" title={it.next.command}
        onClick={async () => { setCopied(await copyText(it.next.command || '')); setTimeout(() => setCopied(false), 2500) }}>{copied ? 'Copied' : 'Copy command'}</button> : null}
      {opNext && it.next.command ? <code style={{ ...mono, color: TOKENS.text[2] }} data-testid="command-text">{it.next.command}</code> : null}
    </div>
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }} data-testid="actions">
      {it.links?.pr ? <a style={linkStyle} href={it.links.pr} target="_blank" rel="noreferrer" data-testid="link-pr">Open PR</a> : null}
      {it.links?.ci ? <a style={linkStyle} href={it.links.ci} target="_blank" rel="noreferrer" data-testid="link-ci">CI log</a> : null}
      {it.links?.diff ? <a style={linkStyle} href={it.links.diff} target="_blank" rel="noreferrer" data-testid="link-diff">Diff</a> : null}
      {it.links?.worklog_claim ? <button type="button" style={{ ...btn, background: 'transparent', color: TOKENS.info, border: 'none', padding: 0 }} data-testid="link-worklog" onClick={() => onWorklog(it.links!.worklog_claim!)}>Worklog</button> : null}
      <span style={{ flex: 1 }} />
      {acts.includes('note') ? <button type="button" style={btn} data-testid="act-note" onClick={() => setCompose(compose === 'note' ? null : 'note')}>Add note</button> : null}
      {acts.includes('set_priority') && it.what.task_id ? <select style={select} aria-label="Priority" data-testid="act-priority" value={String(it.what.priority ?? '')}
        onChange={e => onAct(it, 'set_priority', { task_id: it.what.task_id, priority: Number(e.target.value) })}>
        {!it.what.priority ? <option value="">P?</option> : null}{[1, 2, 3, 4].map(p => <option key={p} value={p}>P{p}</option>)}
      </select> : null}
      {acts.includes('hold') ? <button type="button" style={btn} data-testid="act-hold" onClick={() => setCompose(compose === 'hold' ? null : 'hold')}>Hold</button> : null}
      {acts.includes('unhold') ? <button type="button" style={btn} data-testid="act-unhold" onClick={() => onAct(it, 'unhold', { item: it.what.task_id || prItem })}>Unhold</button> : null}
      {acts.includes('batch_add') ? <button type="button" style={btn} data-testid="act-batch-add" onClick={() => onAct(it, 'batch_add', { pr })}>Add to next batch</button> : null}
      {acts.includes('batch_remove') ? <button type="button" style={btn} data-testid="act-batch-remove" onClick={() => onAct(it, 'batch_remove', { pr })}>Remove from next batch</button> : null}
      {acts.includes('task_done') && it.what.task_id ? <button type="button" style={btn} data-testid="act-task-done" onClick={() => onAct(it, 'task_done', { task_id: it.what.task_id })}>Mark done</button> : null}
      {acts.includes('task_split') ? <button type="button" style={btn} data-testid="act-split" onClick={() => setCompose(compose === 'split' ? null : 'split')}>Split</button> : null}
      {acts.includes('release_stale_claim') ? <button type="button" style={{ ...btn, color: TOKENS.danger, borderColor: TOKENS.danger }} data-testid="act-release-stale" onClick={() => setCompose('release')}>Release stale claim</button> : null}
    </div>
    {compose ? <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'flex-start' }} data-testid="composer">
      {compose === 'release'
        ? <span style={{ ...small, color: TOKENS.danger }}>Frees the files of {it.actions?.stale_claims?.[0]}, keeps its worklog, logged as an operator takeover.</span>
        : compose === 'split'
          ? <textarea style={{ ...select, minWidth: 260, flex: 1, minHeight: 54 }} data-testid="composer-text" value={text} onChange={e => setText(e.target.value)} placeholder={'one part per line: title | area1,area2 | acceptance1; acceptance2'} />
          : <input style={{ ...select, minWidth: 200, flex: 1 }} data-testid="composer-text" value={text} onChange={e => setText(e.target.value)} placeholder={compose === 'note' ? 'Note for the agent (lands in its worklog, tagged operator)' : 'Why hold (optional)'} maxLength={1000} />}
      <button type="button" style={btn} data-testid="composer-submit" onClick={submit}>{compose === 'release' ? 'Confirm release' : compose === 'hold' ? 'Hold' : compose === 'split' ? 'Split task' : 'Add note'}</button>
      <button type="button" style={{ ...btn, color: TOKENS.text[2] }} onClick={() => { setCompose(null); setText('') }}>Cancel</button>
    </div> : null}
    {busy && busy.itemId === it.id ? <div data-testid="action-result" style={{ ...small, color: busy.ok === false ? TOKENS.danger : busy.ok ? TOKENS.success : TOKENS.text[2] }}>{busy.text}</div> : null}
  </article>
}

function Tile({ label, value, tone, active, onClick, testId, title }: { label: string; value: number; tone?: 'danger' | 'warning' | 'info'; active?: boolean; onClick?: () => void; testId?: string; title?: string }) {
  const tv = tone ? toneVars(tone) : null
  return <button type="button" onClick={onClick} data-testid={testId} title={title} style={{
    background: TOKENS.bg[2], border: `1px solid ${active ? TOKENS.info : tv ? tv.border : 'transparent'}`, borderRadius: RADIUS.sm, padding: '6px 4px', textAlign: 'center', cursor: 'pointer', minWidth: 0,
  }}>
    <b style={{ display: 'block', fontSize: TYPE.lg, color: tv ? tv.color : TOKENS.text[0], fontVariantNumeric: 'tabular-nums' }}>{value}</b>
    <span style={{ fontSize: TYPE.xs, color: TOKENS.text[2], textTransform: 'uppercase', letterSpacing: 0.3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', display: 'block' }}>{label}</span>
  </button>
}

function QueueCard({ it, children }: { it: PipelineItem; children?: ReactNode }) {
  const tone = toneVars(ragTone(it.rag))
  return <div data-testid="queued-card" data-item-id={it.id} style={{ border: `1px solid ${TOKENS.borderSubtle}`, borderLeft: `3px solid ${tone.color}`, borderRadius: RADIUS.sm, padding: '6px 8px', background: TOKENS.bg[0], minWidth: 0 }}>
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>{children}</div>
    <div style={{ fontSize: TYPE.base, color: TOKENS.text[0], fontWeight: 600, overflowWrap: 'anywhere' }}>{it.what.title}</div>
    <div style={{ ...mono, color: TOKENS.text[2] }}>{it.id}{it.blocker ? <span style={{ color: TOKENS.danger }}> · {it.blocker}</span> : null}</div>
  </div>
}

function NewTaskForm({ onCreate }: { onCreate: (p: Record<string, unknown>) => void }) {
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({ title: '', kind: 'build', areas: '', priority: '3', acceptance: '' })
  if (!open) return <button type="button" style={btn} data-testid="new-task" onClick={() => setOpen(true)}>New task</button>
  return <div data-testid="new-task-form" style={{ display: 'grid', gap: 6, gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', width: '100%' }}>
    <input style={select} placeholder="Title (OPERATOR: … for your own to-do)" value={f.title} onChange={e => setF({ ...f, title: e.target.value })} data-testid="new-task-title" />
    <select style={select} value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })} aria-label="Kind">{['build', 'fix', 'design', 'review'].map(k => <option key={k}>{k}</option>)}</select>
    <input style={select} placeholder="Areas: files, dirs or globs, comma-separated" value={f.areas} onChange={e => setF({ ...f, areas: e.target.value })} data-testid="new-task-areas" />
    <select style={select} value={f.priority} onChange={e => setF({ ...f, priority: e.target.value })} aria-label="Priority">{['1', '2', '3', '4'].map(p => <option key={p} value={p}>P{p}</option>)}</select>
    <input style={select} placeholder="Acceptance (; separated)" value={f.acceptance} onChange={e => setF({ ...f, acceptance: e.target.value })} />
    <div style={{ display: 'flex', gap: 6 }}>
      <button type="button" style={btn} data-testid="new-task-submit" disabled={!f.title.trim() || !f.areas.trim()} onClick={() => { onCreate({ ...f, priority: Number(f.priority) }); setOpen(false); setF({ title: '', kind: 'build', areas: '', priority: '3', acceptance: '' }) }}>Add task</button>
      <button type="button" style={{ ...btn, color: TOKENS.text[2] }} onClick={() => setOpen(false)}>Cancel</button>
    </div>
  </div>
}

function WorklogDrawer({ claimId, onClose }: { claimId: string; onClose: () => void }) {
  const wl = useApi<{ text?: string | null; found?: boolean; path?: string | null }>(`/api/v2/coordination/claims?worklog=${encodeURIComponent(claimId)}`)
  return <div role="dialog" aria-label={`Worklog ${claimId}`} data-testid="worklog-drawer" style={{ ...panel, position: 'fixed', inset: '8% 4% auto 4%', maxHeight: '80vh', overflow: 'auto', zIndex: 50, boxShadow: 'var(--shadow-3)' }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
      <b style={{ ...mono, color: TOKENS.text[0] }}>Worklog {claimId}</b>
      <button type="button" style={btn} onClick={onClose}>Close</button>
    </div>
    <pre style={{ ...mono, whiteSpace: 'pre-wrap', color: TOKENS.text[1] }}>{wl.loading ? 'Loading…' : wl.data?.found ? wl.data.text : 'No worklog found.'}</pre>
  </div>
}

export default function WorkPipelinePanel({ active = true }: { active?: boolean }) {
  const api = useApi<PipelinePayload>('/api/v2/coordination/pipeline', 30_000, { enabled: active })
  const [params, setParams] = useSearchParams()
  const f = useMemo(() => filterFromParams(params), [params])
  const setF = useCallback((patch: Partial<PipelineFilter>) => setParams(filterToParams({ ...f, ...patch }, params), { replace: true }), [f, params, setParams])
  const [busy, setBusy] = useState<Busy>(null)
  const [worklog, setWorklog] = useState<string | null>(null)
  const [queueOpen, setQueueOpen] = useState(true)
  const [queueAll, setQueueAll] = useState(false)
  const cap = <T,>(xs: T[]) => (queueAll ? xs : xs.slice(0, QUEUE_CAP))

  const items = useMemo(() => api.data?.items || [], [api.data])
  const s = useMemo(() => summarize(items), [items])
  const opts = useMemo(() => filterOptions(items), [items])
  const shown = useMemo(() => filterItems(items, f), [items, f])
  const q = useMemo(() => queuedSections(items), [items])
  const filtering = !!(f.preset || f.stage || f.rag || f.owner || f.vendor || f.design || f.batch || f.q)
  const list = filtering ? shown : shown.filter(i => i.stage !== 'queued')

  const act = useCallback(async (it: PipelineItem | null, cmd: CommandName, p: Record<string, unknown>) => {
    const id = it?.id || 'queued'
    setBusy({ itemId: id, text: `${cmd}: sending…` })
    const r: CommandResult = await sendCommand(cmd, p)
    setBusy({ itemId: id, ok: r.ok, text: r.ok ? `${cmd}: done${r.replayed ? ' (replayed)' : ''}` : `${cmd} refused: ${r.error || r.status}${r.detail ? ` — ${r.detail}` : ''}` })
    if (r.ok) api.refetch()
  }, [api])

  const served = api.data?.sources?.served
  const census = api.data?.sources?.census
  return <section data-testid="work-pipeline" style={{ display: 'grid', gap: 12, minWidth: 0 }}>
    <style>{`
      .wp-card-grid { grid-template-columns: minmax(0, 1.4fr) minmax(0, 2fr); }
      .wp-strip { grid-template-columns: repeat(14, minmax(0, 1fr)); }
      .wp-queue { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      @media (max-width: 760px) {
        .wp-card-grid { grid-template-columns: minmax(0, 1fr); }
        .wp-strip { grid-template-columns: repeat(4, minmax(0, 1fr)); }
        .wp-queue { grid-template-columns: minmax(0, 1fr); }
        .wp-stages > div { height: 14px !important; }
        .wp-cell-text { display: none; }
      }
    `}</style>
    <div style={panel}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div style={{ minWidth: 0 }}>
          <h1 style={{ margin: 0, fontSize: TYPE.lg, color: TOKENS.text[0] }}>Work pipeline</h1>
          <div style={small} data-testid="pipeline-sources">
            One row per work item (task, PR or design phase). As of {et(api.data?.as_of)} · PR census {census?.refreshed_at ? `${api.data?.sources?.census_age_s ?? '?'} s old` : 'pending'} (refreshed at most once a minute)
            {served?.sha ? ` · served ${String(served.sha).slice(0, 9)} health ${served.ok ? 'ok' : served.ok === false ? 'FAILED' : 'unknown'}` : ''}
            {census?.warning ? <span style={{ color: TOKENS.warning }}> · {census.warning}</span> : null}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', ...small }}>
          {(['green', 'amber', 'red', 'grey'] as const).map(r => <span key={r} style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
            <i style={{ display: 'inline-block', width: 10, height: 10, borderRadius: RADIUS.sm, background: r === 'grey' ? TOKENS.bg[3] : toneVars(ragTone(r)).color }} />
            {r === 'green' ? 'done' : r === 'amber' ? 'in progress / waiting' : r === 'red' ? 'blocked, failed, stale' : 'not reached'}
          </span>)}
        </div>
      </div>
      <div className="wp-strip" data-testid="pipeline-strip" style={{ display: 'grid', gap: 6, marginTop: 10 }}>
        {PIPELINE_STAGES.map(st => <Tile key={st} label={STAGE_LABEL[st]} value={s.counts[st]} active={f.stage === st} testId={`strip-${st}`} title={`Items whose current step is ${STAGE_LABEL[st]}`} onClick={() => setF({ stage: f.stage === st ? '' : st, preset: '' })} />)}
        <Tile label="Red" value={s.red} tone="danger" active={f.rag === 'red'} testId="strip-red" onClick={() => setF({ rag: f.rag === 'red' ? '' : 'red' })} />
        <Tile label="Amber" value={s.amber} tone="warning" active={f.rag === 'amber'} testId="strip-amber" onClick={() => setF({ rag: f.rag === 'amber' ? '' : 'amber' })} />
        <Tile label="Needs me" value={s.needsMe} tone="info" active={f.preset === 'needs-me'} testId="strip-needs-me" title="Next steps the operator owns" onClick={() => setF({ preset: f.preset === 'needs-me' ? '' : 'needs-me' })} />
      </div>
    </div>

    <div style={panel} data-testid="pipeline-filters">
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
        <span style={small}>Presets:</span>
        {PRESETS.map(p => <button key={p.id} type="button" data-testid={`preset-${p.id}`} aria-pressed={f.preset === p.id} onClick={() => setF({ preset: f.preset === p.id ? '' : p.id })}
          style={{ ...btn, borderRadius: 999, borderColor: f.preset === p.id ? TOKENS.info : TOKENS.border, color: f.preset === p.id ? TOKENS.text[0] : TOKENS.text[1] }}>{p.label}</button>)}
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <select style={select} aria-label="Stage" data-testid="filter-stage" value={f.stage} onChange={e => setF({ stage: e.target.value as PipelineFilter['stage'] })}>
          <option value="">Stage: all</option>{PIPELINE_STAGES.map(st => <option key={st} value={st}>{STAGE_LABEL[st]}</option>)}
        </select>
        <select style={select} aria-label="RAG" data-testid="filter-rag" value={f.rag} onChange={e => setF({ rag: e.target.value as PipelineFilter['rag'] })}>
          <option value="">RAG: all</option><option value="red">Red</option><option value="amber">Amber</option><option value="green">Green</option>
        </select>
        <select style={select} aria-label="Next-step owner" data-testid="filter-owner" value={f.owner} onChange={e => setF({ owner: e.target.value as PipelineFilter['owner'] })}>
          <option value="">Next step: anyone</option><option value="operator">Me (operator)</option><option value="agent">Agents</option>
        </select>
        <select style={select} aria-label="Vendor" data-testid="filter-vendor" value={f.vendor} onChange={e => setF({ vendor: e.target.value })}>
          <option value="">Vendor: all</option>{opts.vendors.map(v => <option key={v} value={v}>{v}</option>)}
        </select>
        <select style={select} aria-label="Design" data-testid="filter-design" value={f.design} onChange={e => setF({ design: e.target.value })}>
          <option value="">Design: all</option>{opts.designs.map(v => <option key={v} value={v}>{v}</option>)}
        </select>
        <select style={select} aria-label="PR or batch" data-testid="filter-batch" value={f.batch} onChange={e => setF({ batch: e.target.value })}>
          <option value="">PR/batch: all</option><option value="none">Green, not in a batch</option>{opts.batches.map(b => <option key={b} value={String(b)}>In batch PR {b}</option>)}
        </select>
        <input style={{ ...select, minWidth: 180, flex: '1 1 180px' }} aria-label="Search" data-testid="filter-q" placeholder="Search title, PR, branch, file…" value={f.q} onChange={e => setF({ q: e.target.value })} />
        <label style={{ ...small, display: 'inline-flex', gap: 4, alignItems: 'center' }}><input type="checkbox" data-testid="filter-finished" checked={f.finished} onChange={e => setF({ finished: e.target.checked })} /> show finished ({s.finished})</label>
        {filtering ? <button type="button" style={btn} data-testid="filter-clear" onClick={() => setF({ preset: '', stage: '', rag: '', owner: '', vendor: '', design: '', batch: '', q: '' })}>Clear</button> : null}
      </div>
    </div>

    {api.error && !api.data ? <div style={{ ...panel, color: TOKENS.danger }}>Work pipeline unavailable: {api.error}</div> : null}

    <div style={panel} data-testid="queued-section">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: TYPE.md, color: TOKENS.text[0] }}>
          <button type="button" onClick={() => setQueueOpen(!queueOpen)} style={{ ...btn, border: 'none', background: 'transparent', padding: 0, fontSize: TYPE.md, fontWeight: 700 }} aria-expanded={queueOpen}>{queueOpen ? '▾' : '▸'} Queued</button>
          <span style={{ ...small, fontWeight: 400 }}> {q.tasks.length} free tasks · {q.green.length} green PRs not in a batch · {q.operator.length} operator to-dos</span>
        </h2>
        <NewTaskForm onCreate={p => act(null, 'task_add', p)} />
      </div>
      {busy?.itemId === 'queued' ? <div data-testid="action-result" style={{ ...small, color: busy.ok === false ? TOKENS.danger : TOKENS.success }}>{busy.text}</div> : null}
      {queueOpen ? <div className="wp-queue" style={{ display: 'grid', gap: 10, marginTop: 8 }}>
        <div data-testid="queued-tasks" style={{ display: 'grid', gap: 6, alignContent: 'start' }}>
          <div style={small}>Task board: free, not started (agents pick with <code>agent_claim.py next</code>)</div>
          {cap(q.tasks).map(it => <QueueCard key={it.id} it={it}><Chip tone="neutral">P{it.what.priority ?? '?'}</Chip>{it.what.kind ? <Chip tone="neutral">{it.what.kind}</Chip> : null}{it.held ? <Chip tone="warning">held</Chip> : null}</QueueCard>)}
          {!q.tasks.length ? <div style={small}>No free tasks.</div> : null}
        </div>
        <div data-testid="queued-green" style={{ display: 'grid', gap: 6, alignContent: 'start' }}>
          <div style={small}>Green PRs not in a batch{api.data?.batch_queue?.next_batch?.length ? ` · next batch: ${api.data.batch_queue.next_batch.map(n => `PR ${n}`).join(', ')}` : ''}</div>
          {cap(q.green).map(it => <QueueCard key={it.id} it={it}><Chip tone="warning">{it.label}</Chip>{it.links?.pr ? <a style={linkStyle} href={it.links.pr} target="_blank" rel="noreferrer">PR {it.pr_number}</a> : null}</QueueCard>)}
          {!q.green.length ? <div style={small}>None waiting.</div> : null}
        </div>
        <div data-testid="queued-operator" style={{ display: 'grid', gap: 6, alignContent: 'start' }}>
          <div style={small}>Operator to-dos</div>
          {cap(q.operator).map(it => <QueueCard key={it.id} it={it}><Chip tone="info" variant="solid">OPERATOR</Chip>
            {it.next.command ? <code style={{ ...mono, color: TOKENS.text[2] }}>{it.next.command}</code> : null}
            {cardActions(it).includes('task_done') ? <button type="button" style={btn} data-testid="queued-task-done" onClick={() => act(null, 'task_done', { task_id: it.what.task_id })}>Mark done</button> : null}</QueueCard>)}
          {!q.operator.length ? <div style={small}>Nothing for you.</div> : null}
        </div>
      </div> : null}
      {queueOpen && Math.max(q.tasks.length, q.green.length, q.operator.length) > QUEUE_CAP
        ? <button type="button" style={{ ...btn, marginTop: 8 }} data-testid="queue-all" onClick={() => setQueueAll(!queueAll)}>{queueAll ? 'Show fewer' : `Show all (${q.tasks.length + q.green.length + q.operator.length})`}</button> : null}
    </div>

    <div style={panel}>
      <h2 style={{ margin: '0 0 6px', fontSize: TYPE.md, color: TOKENS.text[0] }}>{filtering ? 'Matching items' : 'In flight'} <span style={{ ...small, fontWeight: 400 }} data-testid="pipeline-count">{list.length} shown</span></h2>
      <div style={{ display: 'grid', gap: 8 }}>
        {list.map(it => <ItemCard key={it.id} it={it} onAct={act} busy={busy} onWorklog={setWorklog} />)}
        {!list.length && !api.loading ? <div style={small} data-testid="pipeline-empty">Nothing matches.</div> : null}
        {api.loading && !api.data ? <div style={small}>Loading…</div> : null}
      </div>
    </div>
    {worklog ? <WorklogDrawer claimId={worklog} onClose={() => setWorklog(null)} /> : null}
  </section>
}

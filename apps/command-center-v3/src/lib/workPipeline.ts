// Coordination → Work pipeline model (operator 2026-10-23 13:15 ET): one row per work item (task, PR, design
// phase) staged Proposed → … → Verified live with RAG, who/what/when/where/how, blocker and NEXT STEP + owner.
// Server: GET /api/v2/coordination/pipeline (scripts/lib/work_pipeline.py). This file is the pure UI model:
// filters (all kept in the URL), presets, the summary strip, the Queued section and the RAG → tone mapping.

export const PIPELINE_STAGES = [
  'proposed', 'approved', 'queued', 'claimed', 'building', 'pr_open', 'ci', 'in_batch', 'merged', 'released', 'verified',
] as const
export type PipelineStage = (typeof PIPELINE_STAGES)[number]
export type Rag = 'green' | 'amber' | 'red' | 'grey'
export type Owner = 'operator' | 'agent'

export const STAGE_LABEL: Record<PipelineStage, string> = {
  proposed: 'Proposed', approved: 'Approved', queued: 'Queued', claimed: 'Claimed', building: 'Building',
  pr_open: 'PR open', ci: 'CI', in_batch: 'In batch', merged: 'Merged', released: 'Released', verified: 'Verified live',
}

/** Work-package labels of a task (operator 2026-10-23: problem / definition of done / agent prompt / operator
 *  commands / proof of completion on every task). Section TEXT is fetched per task from /api/v2/coordination/task. */
export type OwnerKind = 'AGENT' | 'OPERATOR' | 'BOTH'
export type WpBlock = {
  wp_id?: string | null
  stage?: string | null
  owner_kind?: OwnerKind | null
  owner_label?: string | null
  wp_status?: 'not_started' | 'in_progress' | 'done' | 'repeating' | null
  status_note?: string | null
  sections: string[]
  depends_on: string[]
  blocked_by: string[]
  related_tasks?: string[]
  status?: string | null
}
export type WpStage = { stage: string; title?: string | null; description?: string | null }
export type TaskDetail = {
  task_id: string; title?: string; status?: string; wp_id?: string | null; stage?: string | null; owner_kind?: OwnerKind | null
  owner_label?: string | null; wp_status?: string | null; wp_status_note?: string | null; depends_on?: string[] | null; related_tasks?: string[] | null
  problem?: string | null; definition_of_done?: string | null; agent_prompt?: string | null; operator_commands?: string | null
  proof?: string | null; proof_evidence?: string | null; notes?: string | null; full_prompt?: string | null; done_at?: string | null
  preamble?: { source?: string | null; sha256?: string | null; present?: boolean }
  evidence?: string[] | null; summary?: string | null; source_ref?: string | null; priority?: number | null; kind?: string | null
  history?: Array<Record<string, unknown>>; history_len?: number; schema?: string
}
export const SECTION_ORDER = [
  { key: 'problem', label: 'Problem' },
  { key: 'definition_of_done', label: 'Definition of done' },
  { key: 'agent_prompt', label: 'Agent prompt' },
  { key: 'operator_commands', label: 'Operator commands' },
  { key: 'proof', label: 'Proof of completion' },
] as const

export type StageCell = { stage: PipelineStage; rag: Rag; label: string; at?: string | null; evidence?: string }
export type PipelineItem = {
  id: string
  kind: string
  stage: PipelineStage
  rag: Rag
  label: string
  stale?: boolean
  finished?: boolean
  cells: StageCell[]
  blocker?: string | null
  next: { owner: Owner; text: string; command?: string | null }
  title?: string
  pr_number?: number | null
  batch?: number | null
  is_batch?: boolean
  waiting_for_batch?: boolean
  held?: { by?: string; at?: string; reason?: string | null } | null
  queue_position?: number | null
  who: { kind: string; label: string; vendor?: string | null; agent?: string | null; session?: string | null }
  what: { title: string; design_id?: string | null; task_id?: string | null; pr_number?: number | null; pr_url?: string | null; batch?: number | null; kind?: string | null; priority?: number | null; wp_id?: string | null; stage?: string | null }
  wp?: WpBlock | null
  when: { started?: string | null; last_activity?: string | null; stage_since?: string | null; stage_age_minutes?: number | null; idle_minutes?: number | null }
  where: { branch?: string | null; worktree?: string | null; file_count: number; files: string[] }
  how: { plan_done?: number | null; plan_total?: number | null; latest?: string | null; worklog?: boolean; claim_ids?: string[]; operator_note?: { by?: string; at?: string; text?: string } | null }
  links?: { pr?: string | null; ci?: string | null; diff?: string | null; worklog_claim?: string | null }
  actions?: { available: string[]; stale_claims: string[]; tier2?: import('./workPipelineTier2').Tier2Action[] }
}
export type PipelinePayload = {
  schema?: string
  as_of?: string
  items?: PipelineItem[]
  summary?: { counts: Record<string, number>; red: number; amber: number; needs_me: number; waiting_for_batch: number; finished: number; total: number }
  sources?: { census?: { refreshed_at?: string | null; warning?: string | null; refreshing?: boolean }; census_age_s?: number | null; served?: { sha?: string | null; ok?: boolean | null; at?: string | null }; batches?: number[] | null }
  batch_queue?: { next_batch: number[]; held_prs: number[]; updated_at?: string | null }
  tier2?: { kinds?: Array<{ kind: string; label: string; enabled: boolean; policy_note?: string | null }>; release?: import('./workPipelineTier2').Tier2Action & { merged_waiting?: number } }
  stale_hours?: number
  wp_stages?: WpStage[]
  stages?: string[]
}

export const PRESETS = [
  { id: 'needs-me', label: 'Needs me' },
  { id: 'queued', label: 'Queued: not started' },
  { id: 'waiting-batch', label: 'Waiting for batch' },
  { id: 'red', label: 'Blocked/red' },
  { id: 'live-today', label: 'Live today' },
  { id: 'next-up', label: 'Next up' },
] as const
export type PresetId = (typeof PRESETS)[number]['id']

export type PipelineFilter = {
  preset: PresetId | ''
  stage: PipelineStage | ''
  rag: Rag | ''
  owner: Owner | ''
  vendor: string
  design: string
  batch: string // '' | 'none' (green, not in a batch) | '<batch pr number>'
  wp: string // '' | 'Stage 2' | 'WP-07'
  q: string
  finished: boolean
}
export const EMPTY_FILTER: PipelineFilter = { preset: '', stage: '', rag: '', owner: '', vendor: '', design: '', batch: '', wp: '', q: '', finished: false }
const KEYS = ['preset', 'stage', 'rag', 'owner', 'vendor', 'design', 'batch', 'wp', 'q'] as const

/** URL search params → filter (unknown values ignored). */
export function filterFromParams(p: URLSearchParams): PipelineFilter {
  const f: PipelineFilter = { ...EMPTY_FILTER }
  const preset = p.get('preset') || ''
  if (PRESETS.some(x => x.id === preset)) f.preset = preset as PresetId
  const stage = p.get('stage') || ''
  if ((PIPELINE_STAGES as readonly string[]).includes(stage)) f.stage = stage as PipelineStage
  const rag = p.get('rag') || ''
  if (['green', 'amber', 'red'].includes(rag)) f.rag = rag as Rag
  const owner = p.get('owner') || ''
  if (owner === 'operator' || owner === 'agent') f.owner = owner
  f.vendor = (p.get('vendor') || '').slice(0, 40)
  f.design = (p.get('design') || '').slice(0, 80)
  f.batch = (p.get('batch') || '').slice(0, 12)
  const wp = (p.get('wp') || '').slice(0, 20)
  if (/^(Stage \d{1,2}|WP-\d{2,3})$/.test(wp)) f.wp = wp
  f.q = (p.get('q') || '').slice(0, 120)
  f.finished = p.get('finished') === '1'
  return f
}

/** Filter → URL params (keeps unrelated params such as tab). */
export function filterToParams(f: PipelineFilter, base: URLSearchParams): URLSearchParams {
  const next = new URLSearchParams(base)
  for (const k of KEYS) {
    const v = f[k]
    if (v) next.set(k, String(v)); else next.delete(k)
  }
  if (f.finished) next.set('finished', '1'); else next.delete('finished')
  return next
}

function etDay(iso?: string | null): string {
  const t = Date.parse(String(iso ?? ''))
  return Number.isFinite(t) ? new Date(t).toLocaleDateString('en-CA', { timeZone: 'America/New_York' }) : ''
}

/** Released/verified with the release (or verification) on today's ET date. */
export function liveToday(it: PipelineItem, now: Date = new Date()): boolean {
  if (!(it.stage === 'verified' || it.stage === 'released')) return false
  const at = it.cells.find(c => c.stage === 'released')?.at || it.when.stage_since
  return etDay(at) === etDay(now.toISOString())
}

export function matchesPreset(it: PipelineItem, preset: PresetId | '', now: Date = new Date()): boolean {
  switch (preset) {
    case 'needs-me': return !it.finished && it.next.owner === 'operator'
    case 'queued': return !it.finished && it.stage === 'queued'
    case 'waiting-batch': return !it.finished && !!it.waiting_for_batch
    case 'red': return !it.finished && it.rag === 'red'
    case 'live-today': return liveToday(it, now)
    case 'next-up': return isReadyWp(it)
    default: return true
  }
}

export function filterItems(items: PipelineItem[], f: PipelineFilter, now: Date = new Date()): PipelineItem[] {
  const q = f.q.trim().toLowerCase()
  return items.filter(it => {
    if (!matchesPreset(it, f.preset, now)) return false
    if (it.finished && !f.finished && f.preset !== 'live-today') return false
    if (f.stage && it.stage !== f.stage) return false
    if (f.rag && it.rag !== f.rag) return false
    if (f.owner && it.next.owner !== f.owner) return false
    if (f.vendor && (it.who.vendor || '') !== f.vendor) return false
    if (f.design && (it.what.design_id || '') !== f.design) return false
    if (f.batch === 'none' && !it.waiting_for_batch) return false
    if (f.batch && f.batch !== 'none' && String(it.batch ?? '') !== f.batch) return false
    if (f.wp && !matchesWp(it, f.wp)) return false
    if (q) {
      const hay = [it.id, it.what.title, it.what.design_id, it.what.task_id, it.wp?.wp_id, it.wp?.stage, it.pr_number ? `#${it.pr_number}` : '', it.where.branch,
        it.who.label, it.next.text, it.blocker, ...(it.where.files || [])].join(' ').toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
}

/** Distinct option values for the vendor / design / batch selects. */
export function filterOptions(items: PipelineItem[]): { vendors: string[]; designs: string[]; batches: number[] } {
  const vendors = new Set<string>(), designs = new Set<string>(), batches = new Set<number>()
  for (const it of items) {
    if (it.who.vendor) vendors.add(it.who.vendor)
    if (it.what.design_id) designs.add(it.what.design_id)
    if (it.batch) batches.add(it.batch)
  }
  return { vendors: [...vendors].sort(), designs: [...designs].sort(), batches: [...batches].sort((a, b) => b - a) }
}

/** The strip: count per stage (unfinished), red/amber totals, Needs me. */
export function summarize(items: PipelineItem[]) {
  const live = items.filter(i => !i.finished)
  const counts = Object.fromEntries(PIPELINE_STAGES.map(s => [s, live.filter(i => i.stage === s).length])) as Record<PipelineStage, number>
  return {
    counts,
    red: live.filter(i => i.rag === 'red').length,
    amber: live.filter(i => i.rag === 'amber').length,
    needsMe: live.filter(i => i.next.owner === 'operator').length,
    waitingForBatch: live.filter(i => i.waiting_for_batch).length,
    finished: items.length - live.length,
  }
}

const OPERATOR_TITLE = /^\s*OPERATOR\s*:/i
const isOperatorTask = (i: PipelineItem) => OPERATOR_TITLE.test(i.what.title || '') || i.wp?.owner_kind === 'OPERATOR'

/** `WP-07` → 7 (unknown → a large number, so labelled work sorts first). */
export function wpNumber(id?: string | null): number {
  const m = /^WP-(\d+)$/.exec(id || '')
  return m ? Number(m[1]) : 1e6
}

/** Stage filter value: `Stage 2` matches the WP's stage, `WP-07` the WP itself. */
export function matchesWp(it: PipelineItem, v: string): boolean {
  if (!v) return true
  if (v.startsWith('WP-')) return it.wp?.wp_id === v
  return it.wp?.stage === v
}

/** A work package whose dependencies are met and which is not finished (the "Next up" candidates). */
export function isReadyWp(it: PipelineItem): boolean {
  const w = it.wp
  if (!w?.wp_id || it.finished) return false
  if (w.wp_status === 'done' || w.status === 'done' || w.status === 'split') return false
  return (w.blocked_by || []).length === 0
}

/** "Next up": per owner kind (AGENT / OPERATOR / BOTH), the ready work packages in plan order; `first` is the next one. */
export function nextUp(items: PipelineItem[]): Array<{ owner: OwnerKind; first: PipelineItem; rest: PipelineItem[] }> {
  const ready = items.filter(isReadyWp).sort((a, b) => wpNumber(a.wp?.wp_id) - wpNumber(b.wp?.wp_id))
  const out: Array<{ owner: OwnerKind; first: PipelineItem; rest: PipelineItem[] }> = []
  for (const owner of ['AGENT', 'OPERATOR', 'BOTH'] as const) {
    const xs = ready.filter(i => (i.wp?.owner_kind || 'AGENT') === owner)
    if (xs.length) out.push({ owner, first: xs[0], rest: xs.slice(1) })
  }
  return out
}

/** Stage / WP select options: the imported stages (with titles) and every WP id, in plan order. */
export function wpOptions(items: PipelineItem[], stages: WpStage[] = []): { stages: WpStage[]; wps: Array<{ id: string; title: string }> } {
  const seen = new Set(stages.map(s => s.stage))
  const extra: WpStage[] = []
  const wps = new Map<string, string>()
  for (const it of items) {
    const st = it.wp?.stage
    if (st && !seen.has(st)) { seen.add(st); extra.push({ stage: st }) }
    if (it.wp?.wp_id) wps.set(it.wp.wp_id, it.what.title)
  }
  return {
    stages: [...stages, ...extra.sort((a, b) => a.stage.localeCompare(b.stage, 'en', { numeric: true }))],
    wps: [...wps.entries()].sort((a, b) => wpNumber(a[0]) - wpNumber(b[0])).map(([id, title]) => ({ id, title })),
  }
}

/** The text "Copy commands" puts on the clipboard: the fenced code blocks' bodies when there are any, else the text. */
export function commandsToCopy(md?: string | null): string {
  const text = md || ''
  const blocks = [...text.matchAll(/```[^\n]*\n([\s\S]*?)```/g)].map(m => m[1].replace(/\n$/, ''))
  return blocks.length ? blocks.join('\n') : text.trim()
}

/** Marking a task done needs evidence when it names a proof of completion. */
export function needsEvidence(it: PipelineItem): boolean {
  return (it.wp?.sections || []).includes('proof')
}

/** The Queued section: free task-board tasks, green PRs not yet in a batch, operator to-dos. */
export function queuedSections(items: PipelineItem[]) {
  const live = items.filter(i => !i.finished)
  const operator = live.filter(i => i.kind === 'task' && isOperatorTask(i) && i.stage === 'queued')
  const tasks = live.filter(i => i.kind === 'task' && i.stage === 'queued' && !operator.includes(i))
    .sort((a, b) => (a.what.priority ?? 9) - (b.what.priority ?? 9) || a.id.localeCompare(b.id))
  const green = live.filter(i => i.waiting_for_batch)
    .sort((a, b) => (a.queue_position ?? 999) - (b.queue_position ?? 999) || (a.pr_number ?? 0) - (b.pr_number ?? 0))
  return { tasks, green, operator }
}

export function ragTone(r: Rag): 'success' | 'warning' | 'danger' | 'neutral' {
  return r === 'green' ? 'success' : r === 'amber' ? 'warning' : r === 'red' ? 'danger' : 'neutral'
}

export function ageLabel(minutes?: number | null): string {
  if (minutes == null || !Number.isFinite(minutes)) return '—'
  if (minutes < 60) return `${Math.max(0, Math.round(minutes))}m`
  if (minutes < 48 * 60) return `${(minutes / 60).toFixed(1)}h`
  return `${Math.round(minutes / 1440)}d`
}

export function planLabel(it: PipelineItem): string {
  const { plan_done: d, plan_total: t } = it.how
  return t ? `${d ?? 0}/${t}` : it.how.worklog ? 'no plan' : 'no worklog'
}

export function cellTitle(c: StageCell): string {
  const when = c.at ? ` · ${c.at}` : ''
  return `${STAGE_LABEL[c.stage]}: ${c.rag === 'grey' ? 'not reached' : c.label || c.rag}${when}${c.evidence ? ` — ${c.evidence}` : ''}`
}

/** Which buttons a card shows: the server's `actions.available`, intersected with what the UI implements. */
export const UI_ACTIONS = ['note', 'set_priority', 'hold', 'unhold', 'batch_add', 'batch_remove', 'task_split', 'task_done', 'release_stale_claim'] as const
export function cardActions(it: PipelineItem): string[] {
  const avail = it.actions?.available || []
  return UI_ACTIONS.filter(a => avail.includes(a))
}

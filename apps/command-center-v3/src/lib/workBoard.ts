// Coordination → Work board (operator 2026-10-23): ALL queued work broken into tasks, the designs it belongs to
// (DSN-<date>-<slug> → P<n> → T<m>), and what is awaiting operator approval. Server: scripts/lib/design_registry.py,
// GET /api/v2/coordination/tasks and /designs. Pure module: no React, no DOM, no fetch. Nothing here takes or
// changes work: agents use scripts/agent_claim.py take <task-id>.

export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'
export type WorkStage = 'open' | 'claimed' | 'in_progress' | 'in_review' | 'merged' | 'live'
export const WORK_STAGES: WorkStage[] = ['open', 'claimed', 'in_progress', 'in_review', 'merged', 'live']
export const WORK_STAGE_LABEL: Record<WorkStage, string> = {
  open: 'Open', claimed: 'Claimed', in_progress: 'In progress', in_review: 'In review', merged: 'Merged', live: 'Live',
}
export const WORK_STAGE_HELP: Record<WorkStage, string> = {
  open: 'Nobody holds it. Any agent can take it: agent_claim.py take <task-id> (or next).',
  claimed: 'An agent claimed the files; work not declared started yet.',
  in_progress: 'The agent declared building.',
  in_review: 'A pull request is open (CI may still be running).',
  merged: 'Merged; not yet in a release this host serves.',
  live: 'In a release this host serves.',
}

export type WorkItem = {
  id: string; title?: string | null; source?: string; design_id?: string | null; areas?: string[]; stage: WorkStage | string
  holder?: string | null; claimed_at?: string | null; claim_id?: string | null; worklog?: boolean
  pr_number?: number | null; pr_url?: string | null; blocked_by?: string[]; draft?: boolean; branch?: string | null
}

export type DesignStatus = 'PROPOSED' | 'APPROVED' | 'IN_PROGRESS' | 'DONE' | 'LIVE' | 'HELD'
export type DesignTask = { id: string; title?: string; status: DesignStatus | string; areas?: string[]; registered?: boolean; holder?: string | null; claim_id?: string | null }
export type DesignPhase = { id: string; title?: string; status: DesignStatus | string; tasks: DesignTask[]; tasks_done?: number; tasks_total?: number }
export type Design = { id: string; title: string; status: DesignStatus | string; approval?: string | null; source?: string | null; path?: string; summary?: string; phases: DesignPhase[] }
export type AwaitingItem = { kind: 'design' | 'packet' | string; id: string; title: string; status: string; approval: string; path?: string | null }

export const STATUS_TONE: Record<DesignStatus, Tone> = {
  PROPOSED: 'warning', APPROVED: 'info', IN_PROGRESS: 'info', DONE: 'success', LIVE: 'success', HELD: 'neutral',
}
export function statusTone(s: string | null | undefined): Tone {
  return STATUS_TONE[String(s || '').toUpperCase() as DesignStatus] || 'neutral'
}

export function groupWork(items: WorkItem[]): Record<WorkStage, WorkItem[]> {
  const out = Object.fromEntries(WORK_STAGES.map(s => [s, [] as WorkItem[]])) as Record<WorkStage, WorkItem[]>
  for (const it of items) out[(WORK_STAGES as string[]).includes(String(it.stage)) ? it.stage as WorkStage : 'open'].push(it)
  return out
}

export type WorkFilter = { source?: string; stage?: WorkStage | 'all'; holder?: string; text?: string }
export function filterWork(items: WorkItem[], f: WorkFilter): WorkItem[] {
  const q = (f.text || '').trim().toLowerCase()
  return items.filter(it =>
    (!f.source || f.source === 'all' || it.source === f.source)
    && (!f.stage || f.stage === 'all' || it.stage === f.stage)
    && (!f.holder || f.holder === 'all' || (it.holder || 'nobody').startsWith(f.holder))
    && (!q || `${it.id} ${it.title || ''} ${(it.areas || []).join(' ')}`.toLowerCase().includes(q)))
}

export function sourcesOf(items: WorkItem[]): string[] {
  return Array.from(new Set(items.map(i => i.source || 'unknown'))).sort()
}

export function holderLabel(it: WorkItem): string {
  return it.holder || 'nobody — take it'
}

export function takeCommand(it: WorkItem): string | null {
  if (it.stage !== 'open' || it.source === 'open PR' || it.source === 'claim') return null
  return `python3 scripts/agent_claim.py take ${it.id}`
}

export function phaseProgress(p: DesignPhase): string {
  const total = p.tasks_total ?? p.tasks.length
  const done = p.tasks_done ?? p.tasks.filter(t => t.status === 'DONE' || t.status === 'LIVE').length
  return total ? `${done}/${total} tasks` : 'no tasks yet'
}

export function designProgress(d: Design): { phases: string; tasks: string } {
  const ph = d.phases.length
  const phDone = d.phases.filter(p => p.status === 'DONE' || p.status === 'LIVE').length
  const tt = d.phases.reduce((n, p) => n + (p.tasks_total ?? p.tasks.length), 0)
  const td = d.phases.reduce((n, p) => n + (p.tasks_done ?? 0), 0)
  return { phases: `${phDone}/${ph} phases`, tasks: tt ? `${td}/${tt} tasks` : 'no tasks yet' }
}

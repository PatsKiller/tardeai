/**
 * My questions grouping (Screen 5) — pure helpers over GET /api/v2/cio/asks?group_by=… (scripts/lib/cio_ask_groups.py).
 * The server groups, counts and summarises; this file only builds paths, validates the shape and formats text.
 * READ_ONLY_ADVISORY — nothing here sizes, orders, stops or weights.
 */
export const GROUP_BYS = ['security', 'sector', 'theme', 'date', 'none'] as const
export type GroupBy = typeof GROUP_BYS[number]
export const GROUP_LABEL: Record<GroupBy, string> = { security: 'Security', sector: 'Sector', theme: 'Theme', date: 'Date', none: 'None' }
export const CHANNEL_OPTIONS = [['', 'CC + Telegram'], ['cc', 'Command Center'], ['telegram', 'Telegram']] as const

export interface GroupQuestion {
  ask_id: string; thread_id: string; question: string | null; channel: string; asked_at: string | null
  turn_kind?: string; depth?: string | null; status?: string | null; answered_at?: string | null
  override?: { group_key: string | null; at?: string | null }
}
export interface GroupMemory {
  last_answer_at: string | null; last_answer_missing_reason?: string | null
  stance: string | null; conviction: number | null; stance_as_of?: string | null; stance_source?: string | null
  stance_missing_reason?: string | null
}
export interface QuestionGroup {
  key: string; label: string; sub: string | null; symbol: string | null; security_guid: string | null
  questions: GroupQuestion[]; thread_ids: string[]; symbols: string[]
  counts: { questions: number; threads: number; names: number }; memory: GroupMemory
  lifecycle?: unknown
}
export interface GroupedQuestions {
  group_by: GroupBy; q: string; channel: string | null; groups: QuestionGroup[]
  counts: { groups: number; questions: number; threads: number }
  group_bys: { id: GroupBy; available: boolean; reason: string | null }[]
}
export interface RelatedAsk { ask_id: string; thread_id: string | null; question: string | null; asked_at: string | null; missing_reason: string | null }

export function groupBy(params: URLSearchParams): GroupBy {
  const g = params.get('group')
  return (GROUP_BYS as readonly string[]).includes(g || '') ? g as GroupBy : 'security'
}
export function groupedPath(gb: GroupBy, q: string, channel: string): string {
  const p = new URLSearchParams({ group_by: gb })
  if (q.trim()) p.set('q', q.trim())
  if (channel) p.set('channel', channel)
  return `/api/v2/cio/asks?${p}`
}
export const regroupPath = (threadId: string) => `/api/v2/cio/asks/${encodeURIComponent(threadId)}/regroup`

/** The grouped block only when it answers THIS request; anything else is "grouping unavailable", never a stale group. */
export function groupedPayload(res: unknown, want: { group_by: GroupBy; q: string; channel: string }): GroupedQuestions | null {
  const data = (res as { data?: { grouped?: unknown } } | null)?.data ?? (res as { grouped?: unknown } | null)
  const g = (data as { grouped?: GroupedQuestions } | null)?.grouped
  if (!g || !Array.isArray(g.groups) || !Array.isArray(g.group_bys) || g.group_by !== want.group_by) return null
  if ((g.q || '') !== want.q.trim() || (g.channel || '') !== want.channel) return null
  return g
}
export function relatedFor(res: unknown): Record<string, RelatedAsk[]> {
  const o = res as { data?: { related_from_memory?: unknown }; related_from_memory?: unknown } | null
  const r = o?.data?.related_from_memory ?? o?.related_from_memory
  return r && typeof r === 'object' && !Array.isArray(r) ? r as Record<string, RelatedAsk[]> : {}
}
export function countsText(g: QuestionGroup, groupBy: GroupBy): string {
  const q = `${g.counts.questions} question${g.counts.questions === 1 ? '' : 's'}`
  const t = `${g.counts.threads} thread${g.counts.threads === 1 ? '' : 's'}`
  const n = groupBy !== 'security' && g.counts.names > 1 ? ` · ${g.counts.names} names` : ''
  return `${q} · ${t}${n}`
}
/** Saved answer history and current per-security stance are independent receipts. */
export function memoryText(m: GroupMemory, when: (iso: string) => string, withStance = true): string {
  const saved = m?.last_answer_at ? `Question memory: answer recorded ${when(m.last_answer_at)}`
    : `Question memory: ${m?.last_answer_missing_reason || 'not measured'}`
  if (!withStance) return saved
  const shadow = /shadow/i.test(`${m?.stance_source ?? ''} ${m?.stance_missing_reason ?? ''}`)
  const stance = m?.stance && !shadow ? `${m.stance}${m.conviction == null ? '' : ` · conviction ${Math.round(m.conviction)}`}`
    : `unavailable${shadow ? ' (shadow record)' : ''}${m?.stance_missing_reason ? ` — ${m.stance_missing_reason}` : ''}`
  return `${saved} · Current stance: ${stance}`
}

// Ops › Job catalog + job descriptions (operator 2026-11-06: "at least a line or two of normalization of what each job
// does" and "another page that categorizes all of the jobs"). Wire types for the description fields jobs-history now
// carries, GET /api/v2/jobs-catalog (JobCatalog@v1), and the pure helpers both pages use. No React, no fetch.
import { RESULT_LABEL, etTime } from './jobRunHistory.ts'
import type { HistoryListRow, HistoryListWire, HistoryStatus, RunResult, SourceClock } from './jobRunHistory.ts'

export const JOB_CATALOG_PATH = '/ops/jobs-catalog'
export const JOBS_CATALOG_API = '/api/v2/jobs-catalog'

/** A jobs-history row with its plain-English description (every field null until a description is written). */
export interface DescribedRow extends HistoryListRow {
  title?: string | null; category?: string | null; does?: string | null; breaks?: string | null
  owner?: string | null; category_fallback?: string | null; category_key?: string | null
}
export interface Category { key: string; label: string; blurb: string }
export interface DescribedListWire extends Omit<HistoryListWire, 'rows'> {
  rows: DescribedRow[]; categories?: Category[]; status?: string | null; category?: string | null
}

export type StatusMix = Record<'failed' | 'missed' | 'late' | 'running' | 'ok' | 'ok_unverified' | 'not_measured' | 'inactive', number>
export interface CatalogCategory extends Category {
  jobs: number; described: number; with_missed: number; fixed_14d: number; status_mix: StatusMix
}
export interface CatalogWire {
  schema: string; computed_at: string; jobs: number; described: number; categories: CatalogCategory[]
  sources: SourceClock[]; gaps: string[]; note: string
}

/** The readable name: the written title, else the registry's generated name. */
export const jobTitle = (r: Pick<DescribedRow, 'title' | 'job'>): string => (r.title && r.title.trim()) || r.job

/** The category a job is grouped under: the described one, else the owner fallback, else Other. */
export const categoryKeyOf = (r: Pick<DescribedRow, 'category' | 'category_key' | 'category_fallback'>): string =>
  r.category || r.category_key || r.category_fallback || 'other'

export function categoryLabel(key: string | null | undefined, categories: Category[] | null | undefined): string {
  if (!key) return 'Other'
  return categories?.find(c => c.key === key)?.label ?? key.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())
}

/** The two description lines; null fields say so instead of inventing text. */
export function descriptionLines(r: Pick<DescribedRow, 'does' | 'breaks'>): { does: string | null; breaks: string | null; missing: boolean } {
  const does = r.does?.trim() || null, breaks = r.breaks?.trim() || null
  return { does, breaks, missing: !does && !breaks }
}

// ── status mix ("3 failed · 40 ok · 12 not measured") ───────────────────────────────────────────────────────────
const MIX_ORDER: Array<[keyof StatusMix, string]> = [
  ['failed', 'failed'], ['missed', 'missed a run'], ['late', 'late'], ['running', 'running'], ['ok', 'ok'],
  ['ok_unverified', 'ok, unproven'], ['not_measured', 'not measured'], ['inactive', 'paused or retired'],
]
export function mixParts(mix: Partial<StatusMix> | null | undefined): Array<{ key: keyof StatusMix; count: number; text: string }> {
  return MIX_ORDER.filter(([k]) => (mix?.[k] ?? 0) > 0).map(([k, label]) => ({ key: k, count: mix![k]!, text: `${mix![k]} ${label}` }))
}
export function mixText(mix: Partial<StatusMix> | null | undefined): string {
  const parts = mixParts(mix)
  return parts.length ? parts.map(p => p.text).join(' · ') : 'No jobs'
}
export const mixTone = (k: keyof StatusMix): 'danger' | 'warning' | 'success' | 'info' | 'neutral' =>
  k === 'failed' ? 'danger' : k === 'missed' || k === 'late' ? 'warning' : k === 'ok' ? 'success' : k === 'running' || k === 'ok_unverified' ? 'info' : 'neutral'

/** Catalog search: a category matches on its label or blurb (job matches come from the jobs-history search). */
export function matchesCategory(c: Category, q: string): boolean {
  const s = q.trim().toLowerCase()
  return !s || c.label.toLowerCase().includes(s) || c.blurb.toLowerCase().includes(s) || c.key.includes(s)
}

// ── jobs-history query with the new filters ─────────────────────────────────────────────────────────────────────
export const HISTORY_STATUS_KEYS = ['failed', 'missed', 'late', 'ok', 'ok_unverified', 'fixed', 'running', 'not_measured',
  'paused', 'retired', 'never_scheduled'] as const
export type HistoryStatusKey = typeof HISTORY_STATUS_KEYS[number]
export const isHistoryStatus = (s: string | null | undefined): s is HistoryStatusKey => !!s && (HISTORY_STATUS_KEYS as readonly string[]).includes(s)

export function describedHistoryQuery(o: { filter: string; offset?: number; limit?: number; q?: string; status?: string | null; category?: string | null }): string {
  const p = new URLSearchParams({ filter: o.filter, offset: String(o.offset ?? 0), limit: String(o.limit ?? 50) })
  if (o.status) p.set('status', o.status)
  if (o.category) p.set('category', o.category)
  if (o.q && o.q.trim()) p.set('q', o.q.trim())
  return `/api/v2/jobs-history?${p.toString()}`
}

/** A tapped status tile counts over every job, so the list it filters reads every job too ("All jobs" keeps its
 *  scheduler pill). Without a status the tab's own filter applies. */
export function effectiveHistoryFilter(tab: 'needs' | 'all' | 'fixes', tabFilter: string, status: string | null): string {
  return status && tab !== 'all' ? 'all' : tabFilter
}

/** Tapping the active tile clears it; tapping another selects it. */
export const toggleStatus = (current: string | null, picked: string): string | null => (current === picked ? null : picked)

/** Link from a catalog card into Jobs & n8n run history for that job. */
export const runHistoryHref = (laneId: string) => `/ops/jobs-n8n?tab=all&history=${encodeURIComponent(laneId)}`

// ── chip tooltips + click-to-filter (operator 2026-11-07 LQ-181) ────────────────────────────────────────────────
/** What each catalog chip means, in plain words (tap/hover tooltip head). */
export const MIX_MEANING: Record<keyof StatusMix, string> = {
  failed: 'The last run of these jobs ended in an error, a timeout or a refusal.',
  missed: 'These jobs were due to run on schedule and no run started.',
  late: 'These jobs have not run as recently as their schedule expects, but are not yet counted as missed.',
  running: 'These jobs are running right now.',
  ok: 'The last run finished OK and its output arrived on time.',
  ok_unverified: 'The last run finished and its output was on time, but nothing proves the work itself succeeded.',
  not_measured: 'No schedule or run record exists to judge these jobs against, so their health is unknown, not good.',
  inactive: 'These jobs are paused, retired or were never scheduled, so no run is expected.',
}
/** What each status badge on a job card means. */
export const STATUS_MEANING: Record<HistoryStatus, string> = {
  ok: 'Running on schedule: the last run succeeded and the output arrived on time.',
  ok_unverified: 'Output on time, success unproven: the job ran and wrote on time, but no check confirms the work was right.',
  failed: 'Last run failed: the most recent run ended in an error, timeout or refusal.',
  missed: 'Missed a run: a scheduled run never started.',
  late: 'Late: the job has not run as recently as its schedule expects.',
  running: 'Running now.',
  not_measured: 'Not measured: there is no schedule or run record to judge this job against, so its health is unknown.',
  paused: 'Paused: the job is switched off on purpose, so no run is expected.',
  retired: 'Retired: the job was replaced or removed, so no run is expected.',
  never_scheduled: 'Never scheduled: the job exists but has no schedule, so no run is expected.',
}
export const RESULT_MEANING: Record<RunResult, string> = {
  succeeded: 'The last run finished and reported success.',
  failed: 'The last run ended in an error.',
  timed_out: 'The last run was stopped because it took longer than allowed.',
  refused: 'The last run was refused by a safety rule and did not do its work.',
  skipped_lock: 'The last run did not start because the previous run was still going.',
  running: 'A run is in progress.',
  requested: 'A run was requested and is waiting to start.',
  unknown: 'A run was recorded but it did not say how it ended.',
}

/** The jobs-history `status` value a chip filters on (the API takes a comma list). */
export const mixStatusParam = (k: keyof StatusMix): string => (k === 'inactive' ? 'paused,retired,never_scheduled' : k)

/** The category page already filtered to the chip's state. */
export const catalogFilterHref = (category: string, k: keyof StatusMix): string =>
  `${JOB_CATALOG_PATH}?${new URLSearchParams({ category, status: mixStatusParam(k) }).toString()}`

const MAX_TIP_JOBS = 8
/** Tooltip text: "<n> <state> — meaning", then one line per job (up to 8) and "+N more". Pure. */
export function chipTipText(k: keyof StatusMix, count: number, rows: ReadonlyArray<Pick<DescribedRow, 'title' | 'job' | 'last_run'>>): string {
  const label = MIX_ORDER.find(([key]) => key === k)?.[1] ?? k
  const lines = [`${count} ${label} — ${MIX_MEANING[k]}`]
  for (const r of rows.slice(0, MAX_TIP_JOBS)) {
    const run = r.last_run
    if (!run) { lines.push(`${jobTitle(r)} — no run recorded`); continue }
    const exit = run.exit_code != null && run.exit_code !== 0 ? ` (exit_${run.exit_code})` : ''
    lines.push(`${jobTitle(r)} — last run ${etTime(run.started_at || run.finished_at)} ${(RESULT_LABEL[run.result] ?? run.result).toLowerCase()}${exit}`)
  }
  if (count > Math.min(rows.length, MAX_TIP_JOBS)) lines.push(`+${count - Math.min(rows.length, MAX_TIP_JOBS)} more`)
  return lines.join('\n')
}

/** `?status=failed,late` → known statuses only. */
export const parseStatusFilter = (raw: string | null | undefined): string[] =>
  (raw ?? '').split(',').map(x => x.trim()).filter((x, i, a) => isHistoryStatus(x) && a.indexOf(x) === i)
export const toggleStatusFilter = (cur: string[], picked: string): string[] =>
  cur.includes(picked) ? cur.filter(x => x !== picked) : [...cur, picked]
export const filterBarText = (statuses: string[], shown: number): string =>
  `Showing: ${statuses.map(s => s.replace(/_/g, ' ')).join(', ')} (${shown})`

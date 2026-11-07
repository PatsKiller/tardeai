// Ops › Jobs & n8n › Quality (design pages/jobs v003 "Run quality", operator-approved 2026-11-06: "Just saying it ran
// is a false positive. It may have ran garbage in, garbage out."). Wire types for the per-row `quality` block of
// GET /api/v2/jobs-history (scripts/lib/run_quality.py) and the pure helpers that put it in plain words.
// No React, no fetch.
/** The tones this module uses (a subset both designTokens and the Jobs & n8n tiles accept). */
export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'

export type QualityGrade = 'GOOD' | 'DEGRADED' | 'EMPTY' | 'FAILED' | 'NOT_LIVE' | 'UNPROVEN'
export type CheckResult = 'pass' | 'fail' | 'unknown'
export interface QualityCheck { result: CheckResult; value?: unknown; detail?: string | null }
export interface RunQuality {
  grade: QualityGrade; sub?: string | null; headline?: string | null; reasons?: string[] | null
  checks?: Record<string, QualityCheck> | null; as_designed?: boolean | null; design_issues?: string[] | null
  graded_run?: { source?: string | null; started_at?: string | null; finished_at?: string | null; mode?: string | null; result?: string | null; run_id?: string | null } | null
  count?: number | null
}

/** The six grades in the mockup's order, with the tile label, tone, `?quality=` key and the one-line definition. */
export const QUALITY_GRADES: ReadonlyArray<{ grade: QualityGrade; key: string; label: string; tone: Tone; means: string }> = [
  { grade: 'GOOD', key: 'good', label: 'Good', tone: 'success', means: 'Ran live, exited ok, wrote its output this run, item count in its normal range, no partial or gap flags, inputs fresh.' },
  { grade: 'DEGRADED', key: 'degraded', label: 'Degraded', tone: 'warning', means: 'Ran and wrote output, but something is off: partial or fallback receipt, count far below its own median, runtime far outside history, or a stale or implausible input (garbage in).' },
  { grade: 'EMPTY', key: 'empty', label: 'Empty', tone: 'warning', means: 'Said ok but produced nothing: zero items, or its output was not touched by this run (garbage out).' },
  { grade: 'FAILED', key: 'failed', label: 'Failed', tone: 'danger', means: 'Errored, lost its executor, or exited 0 while its own receipt says it failed.' },
  { grade: 'NOT_LIVE', key: 'not_live', label: 'Not live', tone: 'neutral', means: 'The last run was a dry run, a shadow or a skip, or the job is paused or retired. Never shown as OK.' },
  { grade: 'UNPROVEN', key: 'unproven', label: 'Unproven', tone: 'info', means: 'It ran, but nothing can check its output. The reason names what is missing.' },
] as const

const BY_GRADE = Object.fromEntries(QUALITY_GRADES.map(g => [g.grade, g])) as Record<QualityGrade, typeof QUALITY_GRADES[number]>
const BY_KEY = Object.fromEntries(QUALITY_GRADES.map(g => [g.key, g])) as Record<string, typeof QUALITY_GRADES[number]>
export const isQualityKey = (s: string | null | undefined): boolean => !!s && s in BY_KEY
export const qualityKeyLabel = (key: string): string | null => BY_KEY[key]?.label ?? null
export const qualityMeans = (g: QualityGrade): string => BY_GRADE[g]?.means ?? ''

const SUB_WORD: Record<string, string> = { inactive: 'paused or retired', dry_run: 'dry run', shadow: 'shadow', skipped: 'skipped' }

/** "Not live · skipped", "Degraded", …; null quality → null (the caller shows nothing, never a made-up grade). */
export function gradeChip(q: RunQuality | null | undefined): { label: string; tone: Tone } | null {
  if (!q || !BY_GRADE[q.grade]) return null
  const g = BY_GRADE[q.grade]
  const sub = q.grade === 'NOT_LIVE' && q.sub ? SUB_WORD[q.sub] ?? q.sub.replace(/_/g, ' ') : null
  return { label: sub ? `${g.label} · ${sub}` : g.label, tone: g.tone }
}

/** The ⚠ flag: the job's label disagrees with what ran. Only an explicit false counts (null = not judged). */
export const notAsDesigned = (q: RunQuality | null | undefined): boolean => q?.as_designed === false

/** Tiles from summary.quality_counts. A missing count renders "—", never 0. */
export function qualityTiles(s: Record<string, unknown> | null | undefined): Array<{ label: string; value: number | null; tone: Tone; key: string }> {
  const counts = (s && typeof s.quality_counts === 'object' && s.quality_counts) as Record<string, unknown> | null
  return QUALITY_GRADES.map(g => ({ label: g.label, tone: g.tone, key: g.key, value: counts && typeof counts[g.grade] === 'number' ? counts[g.grade] as number : null }))
}
export function notAsDesignedCount(s: Record<string, unknown> | null | undefined): number | null {
  return s && typeof s.quality_not_as_designed === 'number' ? s.quality_not_as_designed : null
}

/** The query for the Quality tab: every job (`filter=all`), narrowed to the picked grades (`degraded,empty` = either;
 *  an unknown key is dropped). */
export function qualityHistoryQuery(o: { quality: string | null; offset?: number; limit?: number; q?: string }): string {
  const p = new URLSearchParams({ filter: 'all', offset: String(o.offset ?? 0), limit: String(o.limit ?? 50) })
  const picked = [...new Set(String(o.quality ?? '').split(',').map(k => k.trim()).filter(isQualityKey))]
  if (picked.length) p.set('quality', picked.join(','))
  if (o.q && o.q.trim()) p.set('q', o.q.trim())
  return `/api/v2/jobs-history?${p.toString()}`
}

const CHECK_LABEL: Record<string, string> = {
  ran_live: 'Ran live', run_result: 'Exit / result', output_written: 'Output touched this run', item_count: 'Items produced',
  receipt_flags: 'Receipt flags (partial / gaps / fallback)', count_vs_history: 'Count vs its median', duration_vs_history: 'Runtime vs history',
  input_freshness: 'Inputs fresh', data_plausibility: 'Inputs plausible', as_designed: 'As designed',
}
const CHECK_ORDER = Object.keys(CHECK_LABEL)

function valueText(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (typeof v === 'number' || typeof v === 'string') return String(v)
  try { return JSON.stringify(v) } catch { return String(v) }
}

/** The check list for the detail sheet, in a fixed order (unknown keys last): ✓ pass, ✕ fail, – not measured. */
export function checkRows(q: RunQuality | null | undefined): Array<{ key: string; label: string; mark: '✓' | '✕' | '–'; tone: Tone; value: string; detail: string | null }> {
  const c = q?.checks ?? {}
  const keys = Object.keys(c).sort((a, b) => (CHECK_ORDER.indexOf(a) + 1 || 99) - (CHECK_ORDER.indexOf(b) + 1 || 99))
  return keys.map(k => {
    const r = c[k]
    const mark = r.result === 'pass' ? '✓' : r.result === 'fail' ? '✕' : '–'
    const value = k === 'as_designed' && typeof r.value === 'number' ? (r.value ? `${r.value} issue${r.value === 1 ? '' : 's'}` : 'no issues') : valueText(r.value)
    return { key: k, label: CHECK_LABEL[k] ?? k.replace(/_/g, ' '), mark, tone: r.result === 'pass' ? 'success' : r.result === 'fail' ? 'danger' : 'neutral', value, detail: r.detail ?? null }
  })
}

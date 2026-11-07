// Ops › Jobs & n8n: one sort / filter vocabulary for every tab (operator 2026-11-06: "It needs to be able to sort and
// filter, multi-select by quality also. All of those pages need to be able to filter by last run, sort, etc.").
// The history tabs send `?ran=` / `?sort=` / multi `?quality=a,b` / `?status=a,b` to GET /api/v2/jobs-history (the server
// filters and pages); the checks, n8n and incidents tabs apply the same `ran` / `sort` to their rows here, client-side.
// Pure: no React, no fetch.

export type RanWindow = '1h' | '24h' | '7d' | 'older' | 'never'
export type ListSort = 'attention' | 'last_run_desc' | 'last_run_asc' | 'name' | 'quality' | 'missed'

/** Last-run choices, in menu order. '' = any time. Same keys as the server's RAN_FILTERS. */
export const RAN_OPTIONS: ReadonlyArray<readonly [RanWindow | '', string]> = [
  ['', 'Any time'], ['1h', 'In the last hour'], ['24h', 'In the last 24 h'], ['7d', 'In the last 7 days'],
  ['older', 'Over 7 days ago'], ['never', 'Never ran'],
]
const RAN_KEYS = RAN_OPTIONS.map(([k]) => k).filter(Boolean) as RanWindow[]
const RAN_MS: Record<'1h' | '24h' | '7d', number> = { '1h': 3_600_000, '24h': 86_400_000, '7d': 7 * 86_400_000 }

/** Sort choices per tab. The history tabs get every server sort; the other tabs the ones their rows can answer. */
export const HISTORY_SORTS: ReadonlyArray<readonly [ListSort, string]> = [
  ['attention', 'Worst first'], ['last_run_desc', 'Newest run first'], ['last_run_asc', 'Oldest run first'],
  ['quality', 'Quality, worst first'], ['missed', 'Most missed runs'], ['name', 'Name A–Z'],
]
export const CLIENT_SORTS: ReadonlyArray<readonly [ListSort, string]> = [
  ['attention', 'Worst first'], ['last_run_desc', 'Newest run first'], ['last_run_asc', 'Oldest run first'], ['name', 'Name A–Z'],
]

export const isRan = (s: string | null | undefined): s is RanWindow => !!s && (RAN_KEYS as string[]).includes(s)
export const isSortIn = (opts: ReadonlyArray<readonly [ListSort, string]>, s: string | null | undefined): s is ListSort => !!s && opts.some(([k]) => k === s)

/** `a,b,,a` → ['a','b'], keeping only the values `valid` accepts (an unknown key in a shared link is dropped). */
export function parseMulti(raw: string | null | undefined, valid: (s: string) => boolean): string[] {
  const out: string[] = []
  for (const p of String(raw ?? '').split(',')) {
    const k = p.trim()
    if (k && valid(k) && !out.includes(k)) out.push(k)
  }
  return out
}

/** Tap a chip: in if it was out, out if it was in. Order follows the tap order. */
export const toggleMulti = (list: readonly string[], key: string): string[] => (list.includes(key) ? list.filter(k => k !== key) : [...list, key])

/** The list as a URL value, or null when empty (the param is then removed). */
export const joinMulti = (list: readonly string[]): string | null => (list.length ? list.join(',') : null)

/** Is a last-run time inside the window? `at` null/unparseable = never ran. */
export function ranMatches(at: string | null | undefined, window: RanWindow | null | undefined, nowMs: number): boolean {
  if (!window) return true
  const t = at ? Date.parse(at) : NaN
  if (window === 'never') return !Number.isFinite(t)
  if (!Number.isFinite(t)) return false
  if (window === 'older') return nowMs - t > RAN_MS['7d']
  return nowMs - t <= RAN_MS[window]
}

/** Sort rows that already arrive worst-first (`attention` keeps that order). Never-ran rows always go last when
 *  sorting by run time. Stable; returns a new array. */
export function sortRows<T>(rows: readonly T[], sort: ListSort | null | undefined, at: (r: T) => string | null | undefined, name: (r: T) => string): T[] {
  const idx = new Map(rows.map((r, i) => [r, i]))
  const tie = (a: T, b: T) => (idx.get(a)! - idx.get(b)!)
  const time = (r: T) => { const v = at(r); const t = v ? Date.parse(v) : NaN; return Number.isFinite(t) ? t : null }
  if (!sort || sort === 'attention' || sort === 'quality' || sort === 'missed') return [...rows]
  if (sort === 'name') return [...rows].sort((a, b) => name(a).localeCompare(name(b), undefined, { sensitivity: 'base' }) || tie(a, b))
  const dir = sort === 'last_run_desc' ? -1 : 1
  return [...rows].sort((a, b) => {
    const ta = time(a), tb = time(b)
    if (ta === null || tb === null) return ta === tb ? tie(a, b) : ta === null ? 1 : -1
    return (ta - tb) * dir || tie(a, b)
  })
}

/** Add `ran` / `sort` to a jobs-history query (default sort is the server's; left off the URL). */
export function withSortFilter(path: string, o: { ran?: string | null; sort?: string | null }): string {
  const [base, qs = ''] = path.split('?')
  const p = new URLSearchParams(qs)
  if (o.ran && isRan(o.ran)) p.set('ran', o.ran)
  if (o.sort && o.sort !== 'attention' && isSortIn(HISTORY_SORTS, o.sort)) p.set('sort', o.sort)
  return `${base}?${p.toString()}`
}

/** "Showing Degraded or Empty": the picked labels in plain words. */
export const pickedLabel = (labels: readonly string[]): string => (labels.length <= 1 ? labels[0] ?? '' : `${labels.slice(0, -1).join(', ')} or ${labels[labels.length - 1]}`)

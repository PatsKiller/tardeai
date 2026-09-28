/** Shared table sorting (PR2, 2026-09-27). Pure helpers + a hook; SortHeader renders the control. */
import { useMemo, useState } from 'react'

export type SortDir = 'asc' | 'desc'
export type SortState = { key: string; dir: SortDir } | null

export function compareValues(a: unknown, b: unknown): number {
  const na = a === null || a === undefined || a === '', nb = b === null || b === undefined || b === ''
  if (na && nb) return 0
  if (na) return 1          // empties last
  if (nb) return -1
  const fa = typeof a === 'number' ? a : Number(a), fb = typeof b === 'number' ? b : Number(b)
  if (Number.isFinite(fa) && Number.isFinite(fb) && String(a).trim() !== '' && String(b).trim() !== '') return fa - fb
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' })
}

export function sortRows<T>(rows: T[], state: SortState, get?: (row: T, key: string) => unknown): T[] {
  if (!state) return rows
  const pick = get || ((r: T, k: string) => (r as any)[k])
  const out = rows.map((r, i) => ({ r, i }))
  const empty = (v: unknown) => v === null || v === undefined || v === ''
  out.sort((x, y) => {
    const a = pick(x.r, state.key), b = pick(y.r, state.key)
    // empties always last, whatever the direction
    if (empty(a) !== empty(b)) return empty(a) ? 1 : -1
    const c = compareValues(a, b)
    if (c !== 0) return state.dir === 'asc' ? c : -c
    return x.i - y.i   // stable
  })
  return out.map(o => o.r)
}

/** Click cycles none → desc → asc → none for numbers; asc first for text via `firstDir`. */
export function nextSort(state: SortState, key: string, firstDir: SortDir = 'desc'): SortState {
  if (!state || state.key !== key) return { key, dir: firstDir }
  if (state.dir === firstDir) return { key, dir: firstDir === 'desc' ? 'asc' : 'desc' }
  return null
}

export function useSort<T>(rows: T[], initial: SortState = null, get?: (row: T, key: string) => unknown) {
  const [state, setState] = useState<SortState>(initial)
  const sorted = useMemo(() => sortRows(rows, state, get), [rows, state, get])
  const toggle = (key: string, firstDir: SortDir = 'desc') => setState(s => nextSort(s, key, firstDir))
  return { rows: sorted, sort: state, toggle, setSort: setState }
}

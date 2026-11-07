import type { CSSProperties } from 'react'
import { useSearchParams } from 'react-router-dom'
import { RADIUS, TOKENS, TYPE } from '../lib/designTokens'
import { RAN_OPTIONS, isRan, isSortIn, type ListSort, type RanWindow } from '../lib/jobsSortFilter'

// Ops › Jobs & n8n: the one "Last run" + "Sort" bar every tab shares (operator 2026-11-06). Both live in the URL
// (`?ran=` / `?sort=`) so a filtered, sorted list is a shareable link and survives a reload. Phone first: two 44 px
// selects that wrap to their own lines at 390 px, never a sideways scroll.

const select: CSSProperties = { minHeight: 44, padding: '0 10px', borderRadius: RADIUS.sm, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[1], color: TOKENS.text[0], fontSize: TYPE.base, boxSizing: 'border-box', width: '100%', minWidth: 0 }
const label: CSSProperties = { display: 'grid', gap: 4, flex: '1 1 160px', minWidth: 0, maxWidth: 260 }
const cap: CSSProperties = { color: TOKENS.text[2], fontSize: TYPE.sm }

/** `?ran=` and `?sort=` on the current URL; unknown values read as "any time" / "worst first". Replace, not push. */
export function useSortFilterParams(sorts: ReadonlyArray<readonly [ListSort, string]>): { ran: RanWindow | null; sort: ListSort; setRan: (v: string | null) => void; setSort: (v: string | null) => void } {
  const [params, setParams] = useSearchParams()
  const rawRan = params.get('ran'), rawSort = params.get('sort')
  const set = (k: string, v: string | null) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v); else next.delete(k)
    setParams(next, { replace: true })
  }
  return {
    ran: isRan(rawRan) ? rawRan : null,
    sort: isSortIn(sorts, rawSort) ? rawSort : 'attention',
    setRan: v => set('ran', v && isRan(v) ? v : null),
    setSort: v => set('sort', v && v !== 'attention' && isSortIn(sorts, v) ? v : null),
  }
}

export default function JobsSortFilterBar({ sorts, what = 'jobs' }: { sorts: ReadonlyArray<readonly [ListSort, string]>; what?: string }) {
  const { ran, sort, setRan, setSort } = useSortFilterParams(sorts)
  return <div role="group" aria-label={`Filter and sort ${what}`} data-testid="jobs-sort-filter-bar" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', minWidth: 0 }}>
    <label style={label}><span style={cap}>Last run</span>
      <select data-testid="jobs-ran-select" value={ran ?? ''} onChange={e => setRan(e.target.value || null)} style={select}>
        {RAN_OPTIONS.map(([k, l]) => <option key={k || 'any'} value={k}>{l}</option>)}
      </select>
    </label>
    <label style={label}><span style={cap}>Sort</span>
      <select data-testid="jobs-sort-select" value={sort} onChange={e => setSort(e.target.value)} style={select}>
        {sorts.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </select>
    </label>
  </div>
}

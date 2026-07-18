// Type declarations for chipScope.mjs (kept as plain JS so node runs it directly in the build gate).
export interface ScopedRow {
  name: string
  value: number
  prevValue: number | null
  rank: number
  prevRank: number | null
  delta: number | null
  isNew: boolean
  [k: string]: unknown
}
export function rankWithinScope(rows: Array<{ name: string; value: number | null; prevValue: number | null; [k: string]: unknown }>): ScopedRow[]
export function boardCallout(ranked: ScopedRow[], tf: string, longerTf: string): string

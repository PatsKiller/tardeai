// FQ-043 (/manual-execution D) — the audit asked for "a compact shortlist and separate full-screen
// details instead of expanding every candidate". A phone gets a full-screen sheet; a wide screen can
// expand in place where there is room for it. One decision, in one place, so the desk and its test agree.

export const SHEET_MAX_WIDTH = 820

export function rowDetailMode(width: number | null | undefined): 'sheet' | 'inline' {
  const w = Number(width)
  return Number.isFinite(w) && w > 0 && w <= SHEET_MAX_WIDTH ? 'sheet' : 'inline'
}

export function currentRowDetailMode(): 'sheet' | 'inline' {
  if (typeof window === 'undefined') return 'inline'   // server render: no sheet, nothing hidden
  return rowDetailMode(window.innerWidth)
}

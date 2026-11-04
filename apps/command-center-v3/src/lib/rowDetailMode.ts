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

/** codex B2: what the detail control must do when it is pressed.
 *
 * On a phone the ticket is one sheet. Pressing the control on the OPEN row must close that sheet (null);
 * pressing it on any other row opens that row. In inline mode it toggles the row's own open flag.
 * Extracted so the decision is testable without a browser, and used by the page's real handler.
 */
export function nextDetailState(mode: 'sheet' | 'inline', currentSheetKey: string | null, rowKey: string,
                               openFlags: Record<string, boolean>): { sheetKey: string | null; openFlags: Record<string, boolean> } {
  if (mode === 'sheet') return { sheetKey: currentSheetKey === rowKey ? null : rowKey, openFlags }
  return { sheetKey: currentSheetKey, openFlags: { ...openFlags, [rowKey]: !openFlags[rowKey] } }
}

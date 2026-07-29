/** The "Read" column of the Transitions table (visual contract §2, section 4).
 *
 * DETERMINISTIC, NOT NARRATIVE. The mockup's one-liners were authored copy; the
 * operator's 2026-07-29 decision converts them to rules over fields that exist.
 * Nothing here writes prose that the data does not support.
 *
 *   style row                        -> "Broadening away from megacap growth"
 *   largest book weight on the board -> "Already your largest — confirmation, not an entry"
 *   breadth < 40%                    -> "Narrow participation — {n}% above 20DMA"
 *   highest slope on the board       -> "Strongest slope on the board (+{slope})"
 *   no rule fires                    -> "" (EMPTY CELL)
 *
 * An empty cell is correct here and is NOT a null: absence of commentary is not
 * a missing value, so it must not render through <Unk>. That distinction is the
 * whole reason this file exists rather than a lookup table of sentences.
 */

export interface SectorRow {
  etf?: string | null
  sector?: string | null
  book_pct?: number | null
  breadth_pct?: number | null
  slope?: number | null
}

export interface TransitionRow {
  sector?: string | null
  etf?: string | null
  from?: string | null
  to?: string | null
}

const NARROW_BREADTH_PCT = 40

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** Style/index pseudo-sectors share the momentum table under a STYLE: prefix. */
export const isStyleRow = (etf?: string | null) => !!etf && etf.startsWith('STYLE')

export function transitionRead(t: TransitionRow, rows: SectorRow[]): string {
  if (isStyleRow(t.etf)) return 'Broadening away from megacap growth'

  const sectors = rows.filter(r => !isStyleRow(r.etf))
  const row = sectors.find(r => r.etf === t.etf) || sectors.find(r => r.sector === t.sector)
  if (!row) return ''

  const weights = sectors.map(r => r.book_pct).filter(isNum)
  if (isNum(row.book_pct) && weights.length && row.book_pct === Math.max(...weights)) {
    return 'Already your largest — confirmation, not an entry'
  }

  if (isNum(row.breadth_pct) && row.breadth_pct < NARROW_BREADTH_PCT) {
    return `Narrow participation — ${Math.round(row.breadth_pct)}% above 20DMA`
  }

  const slopes = sectors.map(r => r.slope).filter(isNum)
  if (isNum(row.slope) && slopes.length && row.slope === Math.max(...slopes)) {
    return `Strongest slope on the board (${row.slope > 0 ? '+' : ''}${row.slope})`
  }

  return ''
}

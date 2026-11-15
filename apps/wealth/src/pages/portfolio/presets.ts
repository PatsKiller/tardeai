// Column definitions for the Holdings tab presets.
//
// The column NAMES are the honest ones from the map pass (2026-11-14): a served field keeps the reference's
// label; an absent field keeps its own name plus a stated limit instead of being relabelled into something
// that looks measured. Nothing here is styled — shared v02 components are owned by the shell slice; this file
// only says what each preset measures and what it cannot.

export type PresetId = 'holdings' | 'fundamentals' | 'protection' | 'levels'

export interface Column {
  key: string
  header: string
}

export interface Preset {
  id: PresetId
  label: string
  columns: Column[]
  /** Rendered under the table: what the numbers are and where they come from. */
  methodNote: string
  /** Rendered under the table: columns or claims this preset does not have. */
  limits: string[]
}

const SECURITY: Column = { key: 'security', header: 'Security / account' }

export const PRESETS: Preset[] = [
  {
    id: 'holdings',
    label: 'Holdings',
    columns: [
      SECURITY,
      { key: 'shares', header: 'Shares' },
      { key: 'price', header: 'Price' },
      { key: 'avgCost', header: 'Avg cost' },
      { key: 'value', header: 'Value' },
      { key: 'day', header: 'Day $ / % (no declared clock)' },
      { key: 'unrealized', header: 'Unrealized $ / %' },
      { key: 'weight', header: 'Weight' },
      { key: 'protection', header: 'Protection' },
    ],
    methodNote:
      'Value, day change, unrealized change and weight are served fields. Weight is a percent of the cash-inclusive book, so the rows sum to 100. Avg cost is remaining basis per remaining share.',
    limits: [
      'Day $/% carries no declared per-row observation clock; the column is labelled UNKNOWN rather than given an invented clock.',
      'Unrealized $/% is unrealized only. Realized profit and reconciled period profit are not on this read: the reconciliation is reported PARTIAL and its residual is reported, never allocated to a row.',
      'The book-level verified daily P&L is UNKNOWN (no stored reconciliation), so it is shown as UNKNOWN and never as a zero or as the price-move estimate.',
      'Cash is one row and is inside the weight denominator.',
    ],
  },
  {
    id: 'fundamentals',
    label: 'Fundamentals',
    columns: [
      SECURITY,
      { key: 'price', header: 'Price' },
      { key: 'peTrailing', header: 'Trailing P/E' },
      { key: 'peForward', header: 'Forward P/E' },
      { key: 'peerMedian', header: 'Peer TTM median' },
      { key: 'marketCap', header: 'Market cap' },
      { key: 'yield', header: 'Yield' },
      { key: 'evidence', header: 'Evidence' },
    ],
    methodNote:
      'P/E cells are valuation-assessment@1 assessments rendered as served: a multiple only when the status is ASSESSED or UNASSESSED with a value, otherwise the contract status word. There is no universal cutoff and no cheap/buy verdict. Market cap is the wire value in millions.',
    limits: [
      'Peer TTM median has no reader on any served route; the column states that rather than showing a guess.',
      'Funds and cash carry FUND_METRIC / N/A; a company P/E is not applicable to them.',
    ],
  },
  {
    id: 'protection',
    label: 'Protection',
    columns: [
      SECURITY,
      { key: 'held', header: 'Held' },
      { key: 'stop', header: 'Resting stop' },
      { key: 'stopBasis', header: 'Stop basis' },
      { key: 'stopRead', header: 'Stop read as of' },
      { key: 'protectionState', header: 'State' },
      { key: 'protectionNext', header: 'Next step' },
    ],
    methodNote:
      'State is the protection producer verdict (PROTECTED / GAP / UNKNOWN) with the clock of the broker stop read shown per row.',
    limits: [
      'Downside to stop is not served, so it is not shown: it would be a calculated field, not a served one.',
      'An UNKNOWN state is a read failure for that account, not a claim that the position is unprotected.',
    ],
  },
  {
    id: 'levels',
    label: 'Levels',
    columns: [
      SECURITY,
      { key: 'price', header: 'Price' },
      { key: 'method', header: 'Method' },
      { key: 'ladder', header: 'Retracement ladder' },
      { key: 'nearestLevel', header: 'Nearest level' },
      { key: 'fromHigh', header: 'From 52-week high' },
      { key: 'range', header: '52-week range' },
    ],
    methodNote:
      'The ladder is a Fibonacci retracement of the stored 52-week high and low, labelled as such. Funds carry the nearest level and the retracement only.',
    limits: [
      'Support / Resistance / Timeframe / Next review columns have no reader; they are not shown under another name.',
      'No pivot, support or resistance field exists on the row, so no support/resistance claim is made.',
    ],
  },
]

export function preset(id: PresetId): Preset {
  const p = PRESETS.find(x => x.id === id)
  if (!p) throw new Error(`unknown preset: ${id}`)
  return p
}

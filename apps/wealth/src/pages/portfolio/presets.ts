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
    label: 'Overview',
    columns: [
      SECURITY,
      { key: 'shares', header: 'Shares' },
      { key: 'price', header: 'Price' },
      { key: 'avgCost', header: 'Avg cost' },
      { key: 'value', header: 'Value' },
      { key: 'day', header: 'Day $ / %' },
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
      'Trailing and forward P/E print the SERVED provider multiple (wire pe / forward_pe), with the field named on hover. They are not valuation-assessment@1 assessments: the Evidence column states that contract’s own status, separately, and no cutoff, ranking or good/bad verdict is applied to any multiple.',
    limits: [
      'Peer TTM median has no reader on any served route; the column states that rather than showing a guess.',
      'EPS, PEG, beta, sector, industry, performance and ownership are served per row and shown in the row detail, which is why they are not extra columns here: the approved preset has these eight.',
      'Funds and cash carry N/A; a company P/E is not applicable to them.',
    ],
  },
  {
    id: 'protection',
    label: 'Protection',
    columns: [
      SECURITY,
      { key: 'held', header: 'Held / covered' },
      { key: 'mark', header: 'Mark' },
      { key: 'stop', header: 'Resting stop' },
      { key: 'downsideToStop', header: 'Downside to stop' },
      { key: 'protectionState', header: 'State' },
      { key: 'protectionNext', header: 'Next step' },
    ],
    methodNote:
      'The v04 column set. Mark is the served price for the row; Resting stop and State come from the stops read, and Next step is the producer’s own words. The stop basis and its read clock are in the cell tooltip and in the row drawer rather than in columns of their own.',
    limits: [
      'Downside to stop is not served: the route publishes no such field and this page never computes one, so the column prints N/A with its reason.',
      'Held / covered prints the served held shares. The read does not carry a covered count; coverage is the State column, not a second number.',
      'An UNKNOWN state is a read failure for that account, not a claim that the position is unprotected.',
    ],
  },
  {
    id: 'levels',
    label: 'Levels',
    columns: [
      SECURITY,
      { key: 'price', header: 'Price' },
      { key: 'support', header: 'Support' },
      { key: 'resistance', header: 'Resistance' },
      { key: 'timeframe', header: 'Timeframe' },
      { key: 'method', header: 'Method' },
      { key: 'nextReview', header: 'Next review' },
    ],
    // Two served sets exist for this preset and only one of them is v04's column list. The columns are v04's
    // (verdict 2026-11-15T0342Z B2); the served provider technicals — RSI, the three SMA distances, the 52-week-high
    // distance and the Fibonacci ladder — are in the row drawer's Levels section instead, so the preset stays seven
    // columns wide and none of the served numbers is lost.
    methodNote:
      'The v04 column set. Of these value columns only Price is served on this route today: the levels read (support, resistance, timeframe, next review) has no producer, and the wire’s Fibonacci block carries no clock, so Method cannot be dated either. Each empty cell names its own gap on hover. The served technicals — RSI, the SMA distances and the 52-week-high distance — are in the row drawer’s Levels section, printed as served with no threshold applied.',
    limits: [
      'Support, Resistance, Timeframe and Next review have no producer on this route: they are drawn as N/A columns rather than replaced by a different label.',
      'The wire serves a Fibonacci ladder but no clock for it; a ladder that cannot be dated is not shown as if it were current. The ladder itself, as a retracement of the stored 52-week range, is in the drawer.',
      'No pivot, support or resistance field exists on the row, so no support/resistance claim is made anywhere on this page.',
      'RSI and the moving averages are served numbers, not a signal: no overbought/oversold or crossover claim is made and no cutoff is applied to them.',
    ],
  },
]

export function preset(id: PresetId): Preset {
  const p = PRESETS.find(x => x.id === id)
  if (!p) throw new Error(`unknown preset: ${id}`)
  return p
}

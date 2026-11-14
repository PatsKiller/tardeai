// Valuation-assessment contract, version 1 (John, 2026-11-14).
//
// One versioned contract shared by the row, the drawer, the fundamentals view, the CIO and the CSV.
// The CLIENT DOES NOT COMPUTE an assessment. It renders what the canonical backend contract returns.
// Reusing an existing approved backend methodology is required; until one is wired, every row is
// UNASSESSED with the reason "no approved valuation methodology wired" (never a client guess).
//
// Rules carried by the type:
// - Trailing and forward P/E are separate measures, each with its earnings period and basis.
// - Benchmarks are sector/industry peers AND the security's own history; never a universal cutoff.
// - A low P/E is never by itself a buy signal; the contract has no "cheap => buy" field.
// - Nonpositive earnings => N_M with a reason; it is never shown as cheap.
// - Cash => N_A. Funds/ETFs => FUND_METRIC (a separately defined, sourced fund metric) or N_A.
// - Missing or stale peer data => UNASSESSED (neutral), never a coloured verdict.
// - Thresholds in demos/fixtures are illustrations, not financial policy.

export const VALUATION_CONTRACT_VERSION = 'valuation-assessment@1' as const

export type PeMeasure = 'PE_TRAILING' | 'PE_FORWARD'

export type AssessmentStatus =
  | 'ASSESSED'     // evidence + benchmark + coverage sufficient under the backend methodology
  | 'UNASSESSED'   // missing/stale evidence or peers; neutral, carries a reason
  | 'N_M'          // not meaningful (e.g. nonpositive earnings); carries a reason
  | 'N_A'          // not applicable (cash; instrument without the measure)
  | 'FUND_METRIC'  // fund/ETF: a separately defined fund metric, not a company P/E

export interface EarningsBasis {
  /** e.g. "TTM to 2026-09-30" or "NTM consensus as of 2026-11-13" */
  period: string
  /** e.g. "GAAP diluted", "adjusted", "consensus mean" */
  basis: string
  source: string
  as_of: string // ISO-8601
}

export interface Benchmark {
  kind: 'SECTOR_PEERS' | 'INDUSTRY_PEERS' | 'OWN_HISTORY'
  /** Human label, e.g. "GICS Semiconductors, 24 peers" or "own 5y monthly range" */
  label: string
  /** Statistic the backend used, e.g. "median" with value; null if unavailable */
  statistic: string | null
  value: number | null
  coverage: { members_used: number | null; members_expected: number | null }
  as_of: string | null
  stale: boolean
}

export interface PeAssessment {
  measure: PeMeasure
  status: AssessmentStatus
  value: number | null          // null unless status is ASSESSED or UNASSESSED-with-value
  earnings: EarningsBasis | null
  benchmarks: Benchmark[]
  /** Relative position under the backend methodology; null when not ASSESSED. Not a buy/sell call. */
  relative: 'BELOW_RANGE' | 'WITHIN_RANGE' | 'ABOVE_RANGE' | null
  reason: string                // always present: why this status
  evidence_ids: string[]
}

export interface FundMetric {
  name: string                  // explicitly defined, e.g. "weighted holdings P/E (provider-defined)"
  definition: string
  value: number | null
  source: string
  as_of: string | null
}

export interface ValuationAssessment {
  contract: typeof VALUATION_CONTRACT_VERSION
  methodology_id: string | null // the backend methodology + version; null => nothing wired
  account_security_key: string
  instrument_type: 'EQUITY' | 'FUND' | 'CASH' | 'OPTION' | 'OTHER'
  status: AssessmentStatus      // overall
  trailing: PeAssessment | null
  forward: PeAssessment | null
  fund_metric: FundMetric | null
  as_of: string | null
  reason: string
}

/** The only client-side constructor: an explicit UNASSESSED for when the backend sent nothing. */
export function unassessed(key: string, instrument: ValuationAssessment['instrument_type'], reason: string): ValuationAssessment {
  return {
    contract: VALUATION_CONTRACT_VERSION,
    methodology_id: null,
    account_security_key: key,
    instrument_type: instrument,
    status: instrument === 'CASH' ? 'N_A' : 'UNASSESSED',
    trailing: null,
    forward: null,
    fund_metric: null,
    as_of: null,
    reason: instrument === 'CASH' ? 'cash has no earnings multiple' : reason,
  }
}

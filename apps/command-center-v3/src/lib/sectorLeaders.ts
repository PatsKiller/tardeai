/** Sector Leaders card (SL-S1) — feature flag + payload types.
 *
 * DEFAULT OFF. The existing RESEARCH WATCH tile stays rendered and unmodified;
 * this card renders alongside it so the operator can compare them on live data.
 * Retiring the old tile is a separate change after that comparison.
 *
 * Enable:  localStorage.setItem('SECTOR_LEADERS_V1', 'on')   then reload
 * Disable: localStorage.removeItem('SECTOR_LEADERS_V1')
 *
 * Mirrors the watchV5Enabled() flag shape, inverted to default-off.
 */

export function sectorLeadersEnabled(): boolean {
  try {
    return localStorage.getItem('SECTOR_LEADERS_V1') === 'on'
  } catch {
    return false
  }
}

/** Every numeric field is nullable — the server returns null plus a data_gaps
 * reason rather than a fabricated value. Render all of them through <Val>. */
export interface SLConstituent {
  symbol: string
  price: number | null
  rs_vs_industry: number | null
  rs_vs_spy: number | null
  return_pct: number | null
  pct_from_52w_high: number | null
  adv_20d: number | null
  market_cap: number | null
  days_to_earnings: number | null
  held: { positions: Array<{ account: string | null; shares: number | null; market_value: number | null }> } | null
  is_core: boolean
  lags_own_group: boolean
  blocked_accounts: string[]
  blocked_reason: string | null
  data_age_hours: number | null
}

export interface SLIndustry {
  key: string
  name: string
  state: string | null
  rank: number | null
  rank_change: number | null
  composite_return_pct: number | null
  constituent_count: number | null
  passing_count: number | null
  filter_summary: string | null
  source_note: string | null
  dispersion: { spread_pp: number | null; top_quartile_excess_pp: number | null; n: number } | null
  dispersion_verdict: string | null
  constituents: SLConstituent[]
}

export interface SLSector {
  key: string
  name: string
  etf: string
  state: string | null
  rank: number | null
  rank_total: number | null
  rank_change: number | null
  rs20: number | null
  as_of: string | null
  horizon: string
  horizon_label: string | null
  book_weight_pct: number | null
  book_weight_basis: string | null
  rank_implied_weight_pct: [number, number] | null
  exposure_gap: { pp: number; state: string } | null
  data_age_hours: number | null
  refresh_interval_hours: number | null
  dispersion: { spread_pp: number | null; top_quartile_excess_pp: number | null; n: number } | null
  dispersion_verdict: string | null
  dispersion_scope: string | null
  /** Set when the card has no industries. Distinguishes a JOIN FAILURE from a
   *  genuine absence of candidates — identical on screen, only one is a bug. */
  empty_reason: string | null
  accounts: {
    routable_long: string[]
    blocked_long: string[]
    blocked_long_reason: string | null
    routable_short: string[]
    blocked_short: string[]
    note: string | null
  } | null
  defensive_lean: { enabled: boolean; defensive_sectors: string[]; set_by: string | null } | null
  industries: SLIndustry[]
  data_gaps: string[]
}

export interface SLStripRow {
  key: string
  name: string
  etf: string
  state: string | null
  rank: number | null
  rank_total: number | null
  rank_change: number | null
  rs20: number | null
  book_weight_pct: number | null
  as_of: string | null
}

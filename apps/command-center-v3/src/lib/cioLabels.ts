/**
 * CIO Desk plain-English labels — snake_case / internal field ids → operator copy.
 * READ_ONLY_ADVISORY presentation only; never invent values.
 */

export const CIO_FIELD_LABELS: Record<string, string> = {
  // Report field catalog (cio_report_v2)
  perf_QTD: 'QTD performance',
  perf_true_TWR: 'True TWR',
  perf_3Y: '3Y performance',
  perf_3M: '3M performance',
  perf_1M: '1M performance',
  perf_1Y: '1Y performance',
  perf_YTD: 'YTD performance',
  perf_inception: 'Inception return',
  style_value_blend_growth: 'Style: value/blend/growth',
  cash_band_min_pct: 'Cash band min %',
  cash_band_max_pct: 'Cash band max %',
  money_weighted_CAGR: 'Money-weighted CAGR',
  portfolio_vs_benchmark: 'Portfolio vs benchmark',
  tax_per_lot_details: 'Tax per-lot details',
  tax_adjusted_basis_quality: 'Tax-adjusted basis quality',
  valuation_pe: 'Valuation P/E',
  valuation_pb: 'Valuation P/B',
  valuation_ps: 'Valuation P/S',
  valuation_pcf: 'Valuation P/CF',
  valuation_forward: 'Forward valuation',
  market_cap_style_exposure: 'Market-cap / style exposure',
  // Common desk / thesis keys
  thesis_state: 'Thesis state',
  portfolio_role: 'Portfolio role',
  research_gaps: 'Research gaps',
  research_gap_count: 'Research gap count',
  symbol_thesis_version: 'Thesis version',
  governed_verdict: 'Governed verdict',
  vs_former_holdings: 'Vs former holdings',
  memory_behavior_influence: 'Memory behavior influence',
  source_traceability_pct: 'Source traceability',
  decision_id: 'Decision ID',
  product_id: 'Product ID',
  previous_product_id: 'Prior product ID',
  run_id: 'Run ID',
  source_sha: 'Source SHA',
  manifest_hash: 'Manifest hash',
  credentials_ready: 'Credentials ready',
  live_authorized: 'Live authorized',
  delivery_mode: 'Delivery mode',
  last_delivery_attempt: 'Last delivery attempt',
  last_success: 'Last success',
  last_failure: 'Last failure',
  financial_senses_receipts: 'Financial Senses receipts',
  fact_count: 'Fact count',
  fs_provider: 'FS provider',
  fs_capability: 'FS capability',
  pct_above_exit: '% above exit',
  reentry_zone_low: 'Re-entry zone low',
  reentry_zone_high: 'Re-entry zone high',
  reentry_signal: 'Re-entry signal',
  DO_NOW: 'Do now',
  WATCH_CLOSELY: 'Watch closely',
  RE_ENTER_IF: 'Re-enter if',
  NEW_POSITION_IF: 'New position if',
  HOLD_CASH_FOR: 'Hold cash for',
  AVOID: 'Avoid',
  CURRENT_HOLDINGS_THESIS: 'Current holdings thesis',
  RESEARCH_NEXT: 'Research next',
}

/** Title-case fallback for unknown snake_case keys. */
export function cioLabel(key: string | null | undefined): string {
  if (key == null || key === '') return '—'
  const k = String(key)
  if (CIO_FIELD_LABELS[k]) return CIO_FIELD_LABELS[k]
  return k
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bPct\b/g, '%')
    .replace(/\bTwR\b/gi, 'TWR')
    .replace(/\bQtd\b/gi, 'QTD')
    .replace(/\bYtd\b/gi, 'YTD')
    .replace(/\bCio\b/g, 'CIO')
    .replace(/\bSha\b/g, 'SHA')
    .replace(/\bFs\b/g, 'FS')
}

/** Format an instant as Eastern Time for CIO "As of" lines. */
export function formatAsOfET(iso: string | null | undefined, opts?: { utcSuffix?: boolean }): string {
  if (!iso) return '—'
  const raw = String(iso).trim()
  if (!raw) return '—'
  const d = new Date(/[zZ]$|[+-]\d{2}:?\d{2}$/.test(raw) ? raw : `${raw}Z`)
  if (Number.isNaN(d.getTime())) return raw.slice(0, 19).replace('T', ' ')
  const et = d.toLocaleString('en-US', {
    timeZone: 'America/New_York',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  })
  if (opts?.utcSuffix === false) return et
  const utc = d.toISOString().slice(0, 16).replace('T', ' ')
  return `${et} (${utc} UTC)`
}

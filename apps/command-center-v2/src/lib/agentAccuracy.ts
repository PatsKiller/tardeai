// LQ-20261107-264 — one minimum-sample rule for every surface that prints an agent accuracy.
//
// An accuracy computed from one or two scored recommendations is noise, and the history table held rows
// such as tax_agent 100% on a single recommendation (2026-10-07..2026-11-06). Below the bar the cell reads
// "not enough data" instead of a number nobody should act on.
//
// The bar is the repository's agent-calibration insight threshold (scripts/learning_governance.py
// AGENT_SAMPLE_INSIGHT = 25), not a new number: tests/test_agent_performance_history_20261107.py fails if
// this copy and the Python constant drift apart.

export const MIN_SAMPLES_FOR_ACCURACY = 25

export const NOT_ENOUGH_DATA = 'not enough data'

export interface AccuracyRow {
  total_recommendations?: number | string | null
  accuracy_pct?: number | string | null
}

/** What an accuracy cell should show: a percentage, an em dash, or the honest refusal. */
export function accuracyCell(row: AccuracyRow | null | undefined): string {
  // An absent count is not a small one: Number(undefined) is NaN and fails the check below, so the cell
  // reads "not enough data" rather than implying a measured zero.
  const total = Number(row?.total_recommendations)
  if (!Number.isFinite(total) || total < MIN_SAMPLES_FOR_ACCURACY) return NOT_ENOUGH_DATA
  return row?.accuracy_pct != null ? `${row.accuracy_pct}%` : '—'
}

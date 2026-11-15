// Pure text decisions for the valuation cells — no React, no DOM, so the invariants can pin the rendering
// rather than leave it as prose (review F1/F9).
//
// F1: an UNASSESSED assessment that CARRIES A VALUE is last-known-good. It must render the value with the
// status, never the bare word — valuation-assessment@1 states `value` is
// "null unless status is ASSESSED or UNASSESSED-with-value".
//
// No cutoff, no verdict, no colour: the words are the contract's own.

import type { PeAssessment, ValuationAssessment } from '../../contracts/valuation'
import { multiple } from './format'

/** One P/E cell. `measure` names which of the two separate measures to read. */
export function peCellText(v: ValuationAssessment | null, measure: 'trailing' | 'forward'): string {
  if (!v) return 'N/A — no assessment served'
  if (v.instrument_type === 'CASH') return 'N/A'
  if (v.status === 'FUND_METRIC') {
    return v.fund_metric?.value != null ? `${multiple(v.fund_metric.value)} · fund metric` : 'Fund metric'
  }
  const pe: PeAssessment | null = v[measure]
  if (!pe) return 'N/A'
  switch (pe.status) {
    case 'N_M':
      return 'N/M'
    case 'N_A':
      return 'N/A'
    case 'FUND_METRIC':
      return 'Fund metric'
    case 'ASSESSED':
      // ASSESSED with no value is a producer defect; say so instead of inventing a number.
      return pe.value === null ? 'N/A — assessed without a value' : multiple(pe.value)
    case 'UNASSESSED':
      return pe.value === null ? 'Unassessed' : `${multiple(pe.value)} · Unassessed (last known)`
    default: {
      // A1: the status union is contract-controlled. If valuation-assessment adds one, this guard fails the
      // BUILD. Without it the function falls through and returns `undefined`, which React renders as an empty
      // cell — the one outcome worse than "N/A". The fallback text is what a stale build would show.
      const _unhandled: never = pe.status
      void _unhandled
      return `N/A — unrenderable status ${String(pe.status)}`
    }
  }
}

/** The Evidence cell: the assessment's own status word and its reason, verbatim. */
export function assessmentSummary(v: ValuationAssessment | null): string {
  if (!v) return 'N/A — no assessment served'
  return `${v.status} · ${v.reason}`
}

/** Whether a cell text still carries a served multiple — used by the invariants to pin F1. */
export function cellCarriesValue(text: string): boolean {
  return /\d+(\.\d+)?x/.test(text)
}

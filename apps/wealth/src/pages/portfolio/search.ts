// The Holdings search predicate — extracted from the page so the acceptance test can drive the REAL matcher
// (SPCX display-identity spec T9) instead of a copy of it.
//
// The semantics are unchanged from the page's inline filter (spec R7): four fields, space-joined, lowercased,
// substring. One consequence is kept on purpose rather than fixed here — a row whose served `name` is its ticker
// is found by the ticker and NOT by its enrichment company name, because `row.name` is the ticker. Search is a
// match, not a display claim; making it match a name the row does not carry would change results, which R7
// forbids outside its own decision.

import type { HoldingsRow } from './contract'

export function rowMatchesQuery(
  row: Pick<HoldingsRow, 'symbol' | 'name' | 'accountLabel' | 'accountKey'>,
  query: string,
): boolean {
  const needle = query.trim().toLowerCase()
  if (needle === '') return true
  return `${row.symbol} ${row.name} ${row.accountLabel} ${row.accountKey}`.toLowerCase().includes(needle)
}

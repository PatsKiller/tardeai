// One line of a declared clock's ledger entry: the producer's WITHHELD datum, printed as diagnosis, or nothing.
//
// The adapter carries `withheldAsOf` when the wire served a producer datum (`last_read_as_of`) that it cannot
// let stand as the clock — today the stop read, when a displayed account has no dated broker read. Printing it
// in the `at` slot would turn diagnosis into an age the page then ages the book from (review
// 2026-11-15T0509Z §5.3), so it is printed under its own label instead: " · last stop read <t> — not the
// book's clock".
//
// Both directions are decided HERE, not by the caller's JSX, so both can be tested and neither can be lost in
// a tidy of the page:
//   * a datum with no standing clock is printed, under the label that denies it is the clock;
//   * a clock that stands (`at` present) prints nothing extra, even if a datum was carried — the datum cannot
//     be true of a clock that already exists;
//   * nothing withheld, or a blank datum, prints nothing at all (blank is not a timestamp).
//
// Pure, no imports: `scripts/tests/shell-logic.test.mjs` loads this file directly, and design-gate rule 8
// resolves HoldingsPage's import binding to this function and requires the ledger's <dd> to call it — a
// helper-only test would pin the sentence but not the call site (the M-B lesson).
export interface LedgerClock {
  role: string
  at: string | null
  withheldAsOf?: string | null
}

export function ledgerLine(clock: LedgerClock): string | null {
  const withheld = clock.withheldAsOf?.trim() ?? ''
  if (withheld === '') return null
  if ((clock.at ?? '').trim() !== '') return null
  const noun = clock.role === 'STOPS' ? 'stop' : clock.role.toLowerCase()
  return ` · last ${noun} read ${withheld} — not the book's clock`
}

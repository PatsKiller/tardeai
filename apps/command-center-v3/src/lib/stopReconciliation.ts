// OBS-R2 (operator, live Chrome 2026-11-14): Risk printed two clocks — "Positions · Nov 14, 11:00 ET" and
// "Stops · last broker read Nov 13, 8:55 PM ET" — with no statement of whether the stop states belong to the
// book the positions describe. This is that statement, computed from the two published clocks and nothing else.
//
// The rule (one implementation; the Defense stops line can use the same function):
//   • the stop read is RECONCILED when it is at or after the positions snapshot — every stop state was read
//     against a book at least as new as the one on screen;
//   • it is UNRECONCILED SINCE the stop read when the read is older: the two describe different books, and a
//     position opened, closed or resized after that read can carry a stop state read against another book;
//   • with either clock missing or unreadable the status is UNKNOWN — never "reconciled" by default.
// Synthetic fixtures only in the tests (public repo).

export type StopReconciliationState = 'reconciled' | 'unreconciled' | 'unknown'

export type StopReconciliation = {
  state: StopReconciliationState
  /** ISO clock the pair has been out of step since (the stop read); null unless unreconciled. */
  since: string | null
  /** What the state means, in operator words. The page prefixes "Reconciled" / "Unreconciled since <clock>". */
  reason: string
}

const ms = (v: unknown): number | null => {
  if (v == null || v === '') return null
  if (typeof v === 'number') return Number.isFinite(v) ? v : null
  if (v instanceof Date) return Number.isNaN(v.getTime()) ? null : v.getTime()
  if (typeof v !== 'string') return null
  const at = Date.parse(v)
  return Number.isNaN(at) ? null : at
}

const iso = (m: number): string => new Date(m).toISOString().replace('.000Z', 'Z')

export function stopReconciliation(input: {
  positionsAsOf?: unknown
  stopsAsOf?: unknown
}): StopReconciliation {
  // A clock that is absent and a clock that is present-but-unreadable are different failures and get different
  // words: "not published" would be a false claim about a field that is on the wire.
  const posPresent = input.positionsAsOf != null && input.positionsAsOf !== ''
  const stopsPresent = input.stopsAsOf != null && input.stopsAsOf !== ''
  const pos = ms(input.positionsAsOf)
  const stops = ms(input.stopsAsOf)
  if (posPresent && pos == null) {
    return { state: 'unknown', since: null,
      reason: `the positions snapshot clock ${JSON.stringify(input.positionsAsOf)} is not a readable time` }
  }
  if (stopsPresent && stops == null) {
    return { state: 'unknown', since: null,
      reason: `the stop read clock ${JSON.stringify(input.stopsAsOf)} is not a readable time` }
  }
  if (!posPresent && !stopsPresent) {
    return { state: 'unknown', since: null,
      reason: 'neither the positions snapshot time nor a broker stop read is published, so the two reads cannot be paired' }
  }
  if (!posPresent) {
    return { state: 'unknown', since: null,
      reason: 'the positions snapshot time is not published, so the broker stop read cannot be paired with it' }
  }
  if (!stopsPresent) {
    return { state: 'unknown', since: null,
      reason: 'no broker stop read is published, so its states cannot be dated against the positions snapshot' }
  }
  if (stops >= pos) {
    return { state: 'reconciled', since: null,
      reason: 'the broker order read is at or after the positions snapshot' }
  }
  const hours = Math.round(((pos - stops) / 3_600_000) * 10) / 10
  return { state: 'unreconciled', since: iso(stops),
    reason: `the broker order read is ${hours.toFixed(1)} h older than the positions snapshot; a position opened, ` +
      'closed or resized after that read can carry a stop state read against a different book' }
}

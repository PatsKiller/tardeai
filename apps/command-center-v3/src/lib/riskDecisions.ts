import type { DeskDecision } from '../components/DeskPage'

/** PR-016: the Risk page's decisions block, built only from served counts. `cio_truth` nulls these counts when the
 *  broker read did not complete, so a null is "not readable" — never a zero, and never a decision that there is
 *  nothing to review. The page derives no figure of its own: each title counts a served count. */
export function riskDecisions(data: any): DeskDecision[] {
  const stops = data?.stops
  if (!stops) return []
  const num = (v: unknown) => typeof v === 'number' && Number.isFinite(v) ? v : null
  const unproven = num(stops.unproven_count), unprotected = num(stops.unprotected_count)
  const pending = num(stops.pending_count), filled = num(stops.filled_count)
  const stopReview = '/portfolio?tab=Stop%20Management'
  if (unproven == null && unprotected == null && pending == null && filled == null) {
    return [{ id: 'stops-unreadable', title: 'Stop states were not readable — check the broker',
      detail: (typeof stops?.gap?.reason === 'string' && stops.gap.reason) || 'The last stop read did not complete, so this view cannot say which positions are protected.',
      href: '/ops/health' }]
  }
  const out: DeskDecision[] = []
  if (unproven) out.push({ id: 'stops-unproven', title: `Check ${unproven} ${unproven === 1 ? 'stop' : 'stops'} whose state was not recorded`,
    detail: 'A stop was observed at the broker but its state was unproven, so this view does not count it as protection.', href: stopReview })
  if (unprotected) out.push({ id: 'stops-unprotected', title: `Review ${unprotected} counted ${unprotected === 1 ? 'position' : 'positions'} with no broker stop`,
    detail: 'No resting order protects these rows at the broker. The stop review shows the advice and the evidence for each.', href: stopReview })
  if (pending) out.push({ id: 'stops-pending', title: `${pending} resting ${pending === 1 ? 'stop is' : 'stops are'} still awaiting activation`,
    detail: 'A stop resting at the broker is not yet providing protection; the position sheet names the activation condition.', href: stopReview })
  if (filled) out.push({ id: 'stops-filled', title: `${filled} ${filled === 1 ? 'stop has' : 'stops have'} filled and await the holdings sync`,
    detail: 'The sale is not in the holdings sync yet, so the position still appears in exposure.', href: '/risk?tab=exposure' })
  return out
}

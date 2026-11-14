/**
 * cioCatalyst.ts — what the CIO card's "Next catalyst" row says (LQ-20261113-3100, A06).
 *
 * Live 7b0cc18d0: `card.catalyst = {event, date, time_et, source_id}` with no `label`, and the row printed
 * "Next catalyst: " with nothing after it. The row now names the event from the fields the server really sends and,
 * when there is no event to name, says UNKNOWN or NONE with the reason and the as-of. It is never blank and never
 * invented. Pure; no React.
 */
export type CatalystFact = { event?: string | null; date?: string | null; time_et?: string | null; label?: string | null; source_id?: string; as_of?: string }
export type CatalystState = { state: 'UNKNOWN' | 'NONE'; reason: string; as_of?: string | null }

export type CatalystView =
  | { kind: 'event'; text: string; date: string; sourceId?: string }
  | { kind: 'state'; label: 'UNKNOWN' | 'NONE'; text: string; reason: string; asOf: string | null }

function clean(v: unknown): string { return String(v ?? '').trim() }

export function catalystView(cat: CatalystFact | null | undefined, state: CatalystState | null | undefined): CatalystView {
  const event = clean(cat?.event)
  const date = clean(cat?.date)
  if (cat && event && date) {
    const t = clean(cat.time_et)
    return { kind: 'event', text: `${event} · ${date}${t ? ` ${t} ET` : ''}`, date, sourceId: cat.source_id }
  }
  if (cat) {
    // A record that arrived without its event or date is a gap, said as one.
    const lacks = [!event ? 'event' : null, !date ? 'date' : null].filter(Boolean).join(' and ')
    return { kind: 'state', label: 'UNKNOWN', text: 'Next catalyst: UNKNOWN', reason: `the catalyst record carries no ${lacks}`, asOf: clean(cat.as_of) || null }
  }
  if (state && (state.state === 'NONE' || state.state === 'UNKNOWN') && clean(state.reason)) {
    return { kind: 'state', label: state.state, text: state.state === 'NONE' ? 'Next catalyst: none scheduled' : 'Next catalyst: UNKNOWN',
      reason: clean(state.reason), asOf: clean(state.as_of) || null }
  }
  // An older server sends neither field. Silence is not "nothing scheduled".
  return { kind: 'state', label: 'UNKNOWN', text: 'Next catalyst: UNKNOWN', reason: 'the card carries no catalyst information', asOf: null }
}

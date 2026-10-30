// Pure pinned-clock presentation regression; node --experimental-strip-types src/lib/watchMarketFactsPresentation.test.ts
import { levelFootnoteTime, levelSourceTag, levelText, levelTimeLabel, levelTimeUnknown, marketAmount, marketObserved, pricePresentation } from './watchMarketFactsPresentation.ts'
import type { WatchMarketField } from './watchListsModel.ts'
declare const process: { exit(code?: number): never }
let checks = 0
function eq(name: string, got: unknown, want: unknown) {
  checks++
  if (JSON.stringify(got) !== JSON.stringify(want)) throw new Error(`${name}: ${JSON.stringify(got)} != ${JSON.stringify(want)}`)
}
const field: WatchMarketField = { value: 10, as_of: '2026-10-23T19:45:00Z', source: 'data_broker.latest_quote:schwab',
  source_label: 'Stored quote · schwab', stale: true, freshness: 'STALE', reason: 'Price observation is stale.' }
const original = JSON.stringify(field)
for (const [name, now] of [['weekend', '2026-10-24T14:00:00Z'], ['Sunday', '2026-10-25T14:00:00Z'],
  ['overnight', '2026-10-24T02:00:00Z'], ['preopen', '2026-10-26T12:00:00Z']]) {
  eq(name, pricePresentation(field, new Date(now)), { state: 'Closed session · 2026-10-23', qualification: 'Intraday observation' })
}
eq('source identifies actual close', pricePresentation({ ...field, as_of: '2026-10-23T20:00:00Z', as_of_basis: 'session close' }, new Date('2026-10-24T14:00:00Z')),
  { state: 'Closed session · 2026-10-23 close', qualification: null })
eq('after-hours LAST is qualified', pricePresentation({ ...field, as_of: '2026-10-23T21:00:00Z' }, new Date('2026-10-24T14:00:00Z')).qualification, 'After-hours observation')
eq('older session stays stale', pricePresentation({ ...field, as_of: '2026-10-22T19:45:00Z' }, new Date('2026-10-24T14:00:00Z')).state, 'Stale')
eq('latest open session RTH does not qualify Friday', pricePresentation(field, new Date('2026-10-26T13:30:00Z')).state, 'Stale')
eq('intraday stale stays stale', pricePresentation(field, new Date('2026-10-23T19:59:00Z')).state, 'Stale')
eq('RTH current remains current', pricePresentation({ ...field, stale: false, freshness: 'CURRENT' }, new Date('2026-10-23T19:46:00Z')).state, 'Current')
eq('DST follows existing helper', pricePresentation({ ...field, as_of: '2026-11-06T20:45:00Z' }, new Date('2026-11-09T13:00:00Z')).state, 'Closed session · 2026-11-06')
for (const patch of [{ as_of: null }, { as_of: '2026-10-23' }, { as_of: '2026-10-24T20:00:00Z' },
  { freshness: 'UNKNOWN' }, { source: null }, { freshness: 'MISSING' }, { stale: null }]) {
  eq('missing/future/unknown cannot qualify', pricePresentation({ ...field, ...patch }, new Date('2026-10-24T14:00:00Z')).state, 'Time / freshness unknown')
}
eq('retained transport overrides closed-session label', pricePresentation(field, new Date('2026-10-24T14:00:00Z'), true).state, 'Last snapshot')
eq('missing cannot become last snapshot', pricePresentation({ ...field, value: null }, new Date('2026-10-24T14:00:00Z'), true).state, 'Missing')
eq('facts unchanged', JSON.stringify(field), original)
eq('original time retained', marketObserved(field.as_of), 'As of Oct 23, 2026, 03:45:00 PM EDT')
eq('date-only source is not invented time', marketObserved('2026-10-22'), 'As of 2026-10-22 · closed session')
eq('invalid timestamp unknown', marketObserved('bad'), 'Observation time unknown')
eq('micro price preserved', marketAmount(0.0042), '$0.0042')
eq('zero missing', marketAmount(0), '—')
const broken = { value: 8, source: 'watchlist_symbol_master', source_label: 'Watch symbol master', as_of: null, relation: 'BELOW_PRICE' }
eq('broken nearest is explicit', levelText('resistance', { ...field, value: 11, broken_reference: broken }), '$8.00 broken — nearest valid level: $11.00')
eq('no resistance fallback', levelText('resistance', { ...field, value: null, broken_reference: broken }), '$8.00 broken — none above price')
eq('no support fallback', levelText('support', { ...field, value: null, broken_reference: { ...broken, value: 12, relation: 'ABOVE_PRICE' } }), '$12.00 broken — none below price')
eq('source is chosen fallback source', levelSourceTag({ ...field, source: 'ui_prefs:portfolio.reentry.resistance.v1' }), 'Closed session')
eq('two unknowns produce one row flag', levelTimeUnknown([{ ...field, as_of: null }, { ...field, as_of_basis: 'strategy card created_at' }]), true)
eq('known source date has no unknown flag', levelTimeUnknown([{ ...field, as_of: '2026-10-22', as_of_basis: 'last closed session' }]), false)
eq('missing levels alone have no unknown flag', levelTimeUnknown([{ ...field, value: null, as_of: null }]), false)
eq('invalid level time remains unknown', levelTimeUnknown([{ ...field, as_of: 'bad', as_of_basis: 'observation timestamp' }]), true)
eq('invalid closed date remains unknown', levelTimeUnknown([{ ...field, as_of: '2026-02-30', as_of_basis: 'last closed session' }]), true)
eq('footnote shows a stored instant when the basis is unrecognized', levelFootnoteTime([{ ...field, as_of: '2026-10-23T19:45:00Z', as_of_basis: 'strategy card created_at' }]), 'Oct 23, 3:45 PM ET')
eq('footnote keeps a date-only session date', levelFootnoteTime([{ ...field, as_of: '2026-10-22', as_of_basis: 'last closed session' }]), '2026-10-22')
eq('footnote is unknown only when no time is stored', levelFootnoteTime([{ ...field, as_of: null }]), 'time unknown')
eq('footnote does not hide a known time beside an unknown level', levelFootnoteTime([{ ...field, as_of: '2026-10-23T19:45:00Z' }, { ...field, as_of: null }]), 'Oct 23, 3:45 PM ET')

// levelTimeLabel: the master source carries no per-level timestamp, so it is "not timestamped by
// source" — never reported as a generic "time unknown" bug when the source never carried one.
eq('master level is not timestamped by source', levelTimeLabel([{ ...field, as_of: null, as_of_basis: 'not exposed by source', source: 'watchlist_symbol_master' }]),
  'not timestamped by source')
eq('no valued levels → not measured', levelTimeLabel([{ ...field, value: null, as_of: null }]), 'not measured')
eq('genuinely unknown time stays time unknown', levelTimeLabel([{ ...field, as_of: 'bad', as_of_basis: 'observation timestamp' }]), 'time unknown')
eq('a known observation time is shown, not a flag', levelTimeLabel([{ ...field, as_of: '2026-10-22T19:45:00Z', as_of_basis: 'observation timestamp' }]), '2026-10-22T19:45:00Z')
eq('an undeclared level timestamp stays time unknown', levelTimeLabel([{ ...field, as_of: '2026-10-22T19:45:00Z' }]), 'time unknown')
eq('closed-session date is a known time', levelTimeLabel([{ ...field, as_of: '2026-10-22', as_of_basis: 'last closed session' }]), '2026-10-22')
console.log(`watchMarketFactsPresentation: ${checks} assertions passed`)

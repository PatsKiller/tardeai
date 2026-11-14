// LQ-20261113-3100 (A06): the setups tile and the catalyst row never read as fine when the source said UNKNOWN.
//   node --experimental-strip-types apps/command-center-v3/src/lib/homeSetupsCatalyst.test.ts
import { catalystView } from './cioCatalyst.ts'
import { renderSetupCounts, runHealthNote, setupTileTone, type SetupRunSummary } from './setupRunSummary.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

// Live 7b0cc18d0 shapes.
const liveCat = { event: 'Advance Retail Sales', date: '2026-11-17', time_et: '08:30', source_id: 'cio_synopsis:x', as_of: '2026-11-13T20:00:00Z' }
const liveSummary: SetupRunSummary = {
  run_id: '2026-11-13::1730', scanned_count: 24, classified_count: 7, go_count: 1, wait_count: 2, nogo_count: 4,
  excluded_count: 0, review_count: 0, error_count: 0, unclassified_count: 17, count_integrity: 'RECONCILED',
  freshness_status: 'UNKNOWN', quality: 'UNKNOWN',
}

console.log('catalyst')
{
  const v = catalystView(liveCat, null)
  check('live record without a label names the event, date and time', v.kind === 'event' && v.text === 'Advance Retail Sales · 2026-11-17 08:30 ET')
  check('a label is not needed', !('label' in liveCat))
  check('no time_et: no dangling "ET"', catalystView({ ...liveCat, time_et: null }, null).kind === 'event' && !(catalystView({ ...liveCat, time_et: null }, null) as any).text.includes('ET'))
  const none = catalystView(undefined, { state: 'NONE', reason: 'no event dated today or later', as_of: '2026-11-13T20:00:00Z' })
  check('NONE state: explicit text, reason and as_of', none.kind === 'state' && none.label === 'NONE' && none.text.includes('none scheduled') && !!none.reason && none.asOf === '2026-11-13T20:00:00Z')
  const unk = catalystView(undefined, { state: 'UNKNOWN', reason: 'no macro calendar', as_of: null })
  check('UNKNOWN state: says UNKNOWN with the reason', unk.kind === 'state' && unk.label === 'UNKNOWN' && unk.reason === 'no macro calendar')
  const old = catalystView(undefined, undefined)
  check('an older server (no field at all) is UNKNOWN, never "none scheduled"', old.kind === 'state' && old.label === 'UNKNOWN' && !old.text.includes('none'))
  const noEvent = catalystView({ ...liveCat, event: '' }, null)
  check('a record missing its event is UNKNOWN naming the gap, not "Next catalyst: "', noEvent.kind === 'state' && noEvent.reason.includes('event'))
  check('a state with an empty reason is not trusted', catalystView(undefined, { state: 'NONE', reason: ' ' }).kind === 'state' && (catalystView(undefined, { state: 'NONE', reason: ' ' }) as { label: string }).label === 'UNKNOWN')
}

console.log('setups tile')
{
  const bare = renderSetupCounts(liveSummary, {})
  check('embedded UNKNOWN, no fallback: health is unknown, not healthy', bare.healthUnknown === true && bare.healthDegraded === false)
  check('unknown health is not a success tile', setupTileTone(bare, { scanStale: false, present: true }) === 'warning')
  check('the face says "health UNKNOWN" with the run date beside it (no tooltip on a phone)', runHealthNote(bare, '2026-11-13') === 'health UNKNOWN · run 2026-11-13')
  check('no run date says so rather than dropping it', runHealthNote(bare) === 'health UNKNOWN · run date unknown' && runHealthNote(bare, '  ') === 'health UNKNOWN · run date unknown')
  check('a healthy or degraded note does not take the date', runHealthNote({ runHealth: 'healthy', runHealthStatus: 'RUN_HEALTHY', healthUnknown: false } as any, '2026-11-13') === null)

  const fb = renderSetupCounts(liveSummary, { fallbackStatus: 'RUN_UNDERFILLED' })
  check('the payload top-level RUN_UNDERFILLED replaces the embedded UNKNOWN', fb.runHealthStatus === 'RUN_UNDERFILLED' && fb.healthDegraded === true && fb.healthFromFallback === true && fb.healthUnknown === false)
  check('underfilled is a warning tile and says UNDERFILLED', setupTileTone(fb, { scanStale: false, present: true }) === 'warning' && runHealthNote(fb) === 'UNDERFILLED')

  const emb = renderSetupCounts({ ...liveSummary, freshness_status: 'RUN_HEALTHY' }, { fallbackStatus: 'RUN_UNDERFILLED' })
  check('a classifiable embedded status wins over the fallback', emb.runHealthStatus === 'RUN_HEALTHY' && emb.healthFromFallback === false)
  check('healthy and reconciled is success with no note', setupTileTone(emb, { scanStale: false, present: true }) === 'success' && runHealthNote(emb) === null)

  const fbUnk = renderSetupCounts(liveSummary, { fallbackStatus: 'UNKNOWN' })
  check('an unknown fallback does not hide the unknown', fbUnk.healthUnknown === true && fbUnk.healthFromFallback === false)
  check('a stale scan is a warning; with no payload the tile is the dash, not a verdict', setupTileTone(emb, { scanStale: true, present: true }) === 'warning' && setupTileTone({ degraded: false, healthDegraded: false, healthUnknown: true }, { scanStale: false, present: false }) === 'success')
  const st = renderSetupCounts(liveSummary, { stale: true, staleLabel: 'STALE', fallbackStatus: 'RUN_UNDERFILLED' })
  check('the stale branch carries the fallback health too', st.healthDegraded === true && st.healthUnknown === false)
}

console.log(`homeSetupsCatalyst.test.ts: ${pass} passed, ${fail} failed`)
process.exit(fail ? 1 : 0)

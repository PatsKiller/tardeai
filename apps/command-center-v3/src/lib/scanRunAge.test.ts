// Pure-logic tests for scanRunAge.ts.
//   node --experimental-strip-types src/lib/scanRunAge.test.ts
import { payloadRunAge, scanRunAge, inScalpWindow, latestRunPhrase, ageText } from './scanRunAge.ts'

declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) }
}

// 2026-10-23 is a Friday; EDT is UTC-4.
const at = (etHHMM: string) => new Date(`2026-10-23T${etHHMM}:00-04:00`)
const FIN = '2026-10-23T12:52:29.494073+00:00' // 08:52 ET, the live 0700 re-run

const fresh = scanRunAge(FIN, '0700', at('08:56'))
check('finished time is rendered in ET', fresh.finishedEt === '08:52 ET')
check('age is whole minutes', fresh.ageMin === 3)
check('face label states finished + age', fresh.label === 'finished 08:52 ET · 3 min ago')
check('3 min old in window is ok', fresh.tone === 'ok')
check('slot 0700 finishing 08:52 is a re-run', fresh.rerun && fresh.slotLabel === 'slot 0700 · re-run')
check('re-run tooltip says the data is not from 07:00', /not from 07:00/.test(fresh.tip))

check('7 min old in window is amber', scanRunAge(FIN, '0700', at('08:59')).tone === 'warn')
check('exactly 10 min is still amber', scanRunAge(FIN, '0700', at('09:02')).tone === 'warn')
check('11 min old in window is red', scanRunAge(FIN, '0700', at('09:04')).tone === 'bad')
check('2 h old in window is red', scanRunAge(FIN, '0700', at('10:54')).tone === 'bad')
check('outside the window (13:00) a 4 h old run is neutral', scanRunAge(FIN, '0700', at('13:00')).tone === 'ok')
check('weekend is outside the window', !inScalpWindow(new Date('2026-10-24T08:00:00-04:00')))
check('05:59 ET is outside, 06:00 inside, 12:00 outside',
  !inScalpWindow(at('05:59')) && inScalpWindow(at('06:00')) && !inScalpWindow(at('12:00')))

const onTime = scanRunAge('2026-10-23T11:05:00+00:00', '0700', at('07:06'))
check('a run finishing 07:05 for slot 0700 is not a re-run', !onTime.rerun && onTime.slotLabel === 'slot 0700')

const naive = scanRunAge('2026-10-23T08:52:29', '0700', at('08:56'))
check('naive stamp: age unknown, never assumed UTC/ET', naive.ageMin === null && naive.tone === 'warn' && /unzoned · age unknown/.test(naive.label))
const none = scanRunAge(null, '0700', at('08:56'))
check('missing stamp is amber and says so', none.tone === 'warn' && none.label === 'no finished stamp')
check('future stamp clamps to 0 (clock skew)', scanRunAge(FIN, '0700', at('08:50')).ageMin === 0)

check('ageText formats hours', ageText(125) === '2 h 5 min ago' && ageText(0) === 'just now')

check('latest-run phrase from SetupRunSummary', latestRunPhrase({ scanned_count: 17, go_count: 0, wait_count: 0, nogo_count: 6, review_count: 11 })
  === 'latest run: 17 scanned · 0 GO / 0 WAIT / 6 NOGO / 11 review')
check('latest-run phrase is null without a summary', latestRunPhrase(null) === null && latestRunPhrase({}) === null)

// Follow-up (cadence #1992): the served scan clock wins over the run summary, and server STALE forces red.
const P = { latest_run_timestamp: '2026-10-23T12:52:29+00:00', scan_freshness: { latest_scan_at: '2026-10-23T09:01:10-04:00', age_sec: 170, status: 'FRESH' } }
const pa = payloadRunAge(P, '0700', at('09:04'))
check('scan_freshness.latest_scan_at preferred over latest_run_timestamp', pa.source === 'scan' && pa.finishedEt === '09:01 ET' && pa.ageMin === 2 && pa.tone === 'ok')
check('scan label says latest scan, not finished', /^latest scan 09:01 ET/.test(pa.label))
const ps = payloadRunAge({ ...P, scan_freshness: { ...P.scan_freshness, status: 'STALE' } }, '0700', at('09:04'))
check('server STALE forces red', ps.tone === 'bad')
const pr = payloadRunAge({ latest_run_timestamp: '2026-10-23T12:52:29+00:00' }, '0700', at('09:04'))
check('falls back to the run stamp when scan_freshness is absent', pr.source === 'run' && pr.finishedEt === '08:52 ET' && pr.tone === 'bad')

console.log(`\nscanRunAge: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

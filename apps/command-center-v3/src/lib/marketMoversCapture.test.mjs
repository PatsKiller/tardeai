// node --experimental-strip-types src/lib/marketMoversCapture.test.mjs
// FQ-092 (HQ-08): a market-movers capture showed "capture 17:45Z" with no date and no age, so a three-day-old
// capture read like a twelve-minute-old one. The live capture was fresh when measured (12 min), which is exactly
// why this has to be proved with the component and an old clock rather than by waiting for a stale one.
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { captureStamp, captureLine, STALE_AFTER_MINUTES } from './marketMoversCapture.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

const NOW = Date.parse('2026-11-04T18:00:00Z')

// A fresh capture: date AND age, not stale.
const fresh = captureLine('2026-11-04T17:45:01.604621+00:00', NOW)
check(fresh.text.startsWith('finviz elite capture 2026-11-04 17:45Z'), 'the capture line does not carry the date')
check(/15 min old/.test(fresh.text), 'the capture line does not carry its age')
check(fresh.stale === false, 'a 15-minute capture is called stale')

// The defect: three days old must not read like today.
const old = captureLine('2026-11-01T17:45:01Z', NOW)
check(old.text.includes('2026-11-01'), 'an old capture does not show its own date')
check(/3 d old/.test(old.text), 'an old capture does not show its age')
check(old.stale === true, 'a three-day-old capture is not marked stale')

// Undatable and future captures are never presented as current.
check(captureStamp('', NOW).stale === true && /not recorded/.test(captureStamp('', NOW).at), 'a missing clock reads as current')
check(captureStamp('not-a-time', NOW).stale === true, 'an unparseable clock reads as current')
check(captureStamp('2026-11-05T09:00:00Z', NOW).stale === true, 'a future-dated capture reads as current')

// The board must render that line, and must not render the bare clock time.
const board = readFileSync(join(HERE, '../components/home/MarketMoversBoard.tsx'), 'utf8')
check(/captureLine\(/.test(board), 'the board does not use the capture line')
check(/market-movers-capture/.test(board), 'the capture line is not rendered with its test id')
check(!/slice\(11, 16\)/.test(board), 'the board still slices a bare HH:MM out of the timestamp')

if (failed) { console.error(`marketMoversCapture: ${failed} failure(s)`); process.exit(1) }
console.log('marketMoversCapture: ok')

// node --experimental-strip-types src/lib/reportCardText.test.mjs
// FQ-056 (/reports C) + FQ-057 (/reports E), measured live 2026-11-04: 10 report types, 4 never
// generated, and every card printed the raw generator ("…snapshot.py (20:40 nightly)"). These checks
// cover the words and pin that the card actually renders them.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { cadenceWords, scheduleWords, neverRunText } from './reportCardText.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

check(cadenceWords('daily') === 'Every day', 'daily cadence is not in words')
check(cadenceWords('weekly') === 'Every week', 'weekly cadence is not in words')
check(cadenceWords('on-event') === 'When an event occurs', 'event cadence is not in words')
check(cadenceWords(undefined) === 'Schedule not stated', 'an unknown cadence claims a schedule')

// A time from the generator string, and nothing invented when there is no time.
check(scheduleWords('system_rollup_snapshot.py (20:40 nightly)') === 'around 20:40', 'the nightly time is not read from the catalog')
check(scheduleWords('portfolio_orchestrator (07:30 controller)') === 'around 07:30', 'the morning time is not read from the catalog')
check(scheduleWords('aegis_morning_brief_delivery.py') === null, 'a time is invented where the catalog carries none')

// A never-run card: says what is true (nothing produced) and where to look; does not claim a fault.
const nr = neverRunText()
check(/No report has been produced yet/.test(nr), 'a never-run card still gives no explanation')
check(/Ops . Jobs/.test(nr), 'a never-run card gives no next step')
check(!/broken|failed|error/i.test(nr), 'a never-run card claims a failure the data does not show')

// The card must render these words, and the raw generator must survive inside a details block.
const page = readFileSync(join(HERE, '../components/reports/ReportLibrary.tsx'), 'utf8')
check(/cadenceWords\(/.test(page), 'ReportLibrary does not render the plain-language cadence')
check(/scheduleWords\(/.test(page), 'ReportLibrary does not render the plain-language schedule')
check(/neverRunText\(/.test(page), 'ReportLibrary does not explain a never-run card')
check(!/· \{t\.generator\}/.test(page), 'ReportLibrary still prints the raw generator in the summary line instead of behind details')
check(/<details[\s\S]{0,400}\{t\.generator\}/.test(page), 'the raw generator was removed instead of moved behind details')

if (failed) { console.error(`reportCardText: ${failed} failure(s)`); process.exit(1) }
console.log('reportCardText: ok')

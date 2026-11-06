// node --experimental-strip-types src/lib/reportCardText.test.mjs
// FQ-056 (/reports C) + FQ-057 (/reports E), measured live 2026-11-04: 10 report types, 4 never
// generated, and every card printed the raw generator ("…snapshot.py (20:40 nightly)"). These checks
// cover the words and pin that the card actually renders them.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { cadenceWords, scheduleWords, neverRunText, runStateOf } from './reportCardText.ts'

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

// A never-run card with no recorded state: says it cannot say which of the three it is, and where to look.
const nr = neverRunText(null)
check(/No report has been produced yet/.test(nr), 'a never-run card still gives no explanation')
check(/Ops . Jobs/.test(nr), 'a never-run card gives no next step')
check(/not possible to say/.test(nr), 'the card guesses a reason instead of saying the catalog carries none')

// The three states the acceptance names, when the catalog carries them.
check(/switched off/.test(neverRunText('disabled')), 'a disabled report is not described as switched off')
check(/last attempt failed/.test(neverRunText('failing')), 'a failing report is not described as failing')
check(/first run/.test(neverRunText('awaiting-first-run')), 'an awaiting-first-run report does not say so')
check(!/^This report is switched off|^This report has never been produced and its last attempt failed|^This report is scheduled but/.test(neverRunText(null)), 'the unknown state asserts one of the known states instead of naming all three as unknown')

// runStateOf maps only fields the catalog actually carries, and returns null for the live shape.
check(runStateOf({ status: 'never-generated', cadence: 'daily', generator: 'x.py', history: [] }) === null,
  'a row with no run-state field was given a state it does not carry')
check(runStateOf({ disabled: true }) === 'disabled', 'a disabled flag is not read')
check(runStateOf({ last_error: 'boom' }) === 'failing', 'a recorded error is not read')
check(runStateOf({ next_run_at: '2026-11-05T00:00Z' }) === 'awaiting-first-run', 'a scheduled next run is not read')

// The card must render these words, and the raw generator must survive inside a details block.
const page = readFileSync(join(HERE, '../components/reports/ReportLibrary.tsx'), 'utf8')
check(/cadenceWords\(/.test(page), 'ReportLibrary does not render the plain-language cadence')
check(/scheduleWords\(/.test(page), 'ReportLibrary does not render the plain-language schedule')
check(/neverRunText\(runStateOf\(t\)\)/.test(page), 'ReportLibrary does not pass the report\'s run state to the never-run text')
check(!/· \{t\.generator\}/.test(page), 'ReportLibrary still prints the raw generator in the summary line instead of behind details')
check(/<details[\s\S]{0,400}\{t\.generator\}/.test(page), 'the raw generator was removed instead of moved behind details')

if (failed) { console.error(`reportCardText: ${failed} failure(s)`); process.exit(1) }
console.log('reportCardText: ok')

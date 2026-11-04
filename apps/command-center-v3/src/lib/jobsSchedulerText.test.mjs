// node --experimental-strip-types src/lib/jobsSchedulerText.test.mjs
// FQ-048 (/ops/jobs E). Live 2026-11-04: scheduler values cron 18 / systemd 18 / n8n 9 / none 5,
// printed raw in the "Runs on" cell. These checks cover the words and the untouched unknowns; the card
// rendering (plain words + a tappable Technical disclosure) is proved by jobsScheduler.render.test.mjs.
import assert from 'node:assert/strict'
import { schedulerWords, schedulerTechnical } from './jobsSchedulerText.ts'

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

check(schedulerWords('cron') === 'Scheduled on this machine', 'cron is not in everyday words')
check(schedulerWords('systemd') === 'Background service on this machine', 'systemd is not in everyday words')
check(schedulerWords('n8n') === 'n8n workflow', 'n8n is not named plainly')
check(schedulerWords('none') === 'Not scheduled', '"none" does not read as not scheduled')
check(schedulerWords('') === 'Not recorded', 'a missing scheduler is rendered as empty')
check(schedulerWords('launchd') === 'launchd', 'an unknown scheduler was relabelled — it must keep its own name')

check(schedulerTechnical('systemd') === 'Scheduler: systemd', 'the exact scheduler value is no longer available')
check(schedulerTechnical('') === 'Scheduler not recorded', 'a missing scheduler has no technical text')

// The wiring is proved by rendering the real component: jobsScheduler.render.test.mjs.
// (cx-openai-3 F2: the source-regex wiring checks that used to sit here passed with the whole cell deleted.)

if (failed) { console.error(`jobsSchedulerText: ${failed} failure(s)`); process.exit(1) }
console.log('jobsSchedulerText: ok')

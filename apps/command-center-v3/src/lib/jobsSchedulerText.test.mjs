// node --experimental-strip-types src/lib/jobsSchedulerText.test.mjs
// FQ-048 (/ops/jobs E). Live 2026-11-04: scheduler values cron 18 / systemd 18 / n8n 9 / none 5,
// printed raw in the "Runs on" cell. These checks cover the words, the untouched unknowns, and that
// the job card renders them (with the exact value still reachable as a title).
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { schedulerWords, schedulerTechnical } from './jobsSchedulerText.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
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

const page = readFileSync(join(HERE, '../components/JobsHealth.tsx'), 'utf8')
check(/schedulerWords\(/.test(page), 'JobsHealth does not render the everyday scheduler words')
check(/schedulerTechnical\(/.test(page), 'JobsHealth dropped the exact scheduler value instead of keeping it as a detail')
check(!/>\{row\.scheduler\}</.test(page), 'JobsHealth still prints the raw scheduler in the cell')

if (failed) { console.error(`jobsSchedulerText: ${failed} failure(s)`); process.exit(1) }
console.log('jobsSchedulerText: ok')

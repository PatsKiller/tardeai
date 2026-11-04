// node src/lib/jobsWhyCompact.test.mjs
// FQ-047 (/ops/jobs D): the phone list repeated a long cause, a last-success line and a Review button on
// every card. The row now carries a one-line summary and opens the full detail behind a toggle — with
// nothing removed: the full cause, the last-success line and the Review job button all still exist.
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

const src = readFileSync(join(HERE, '../components/JobsHealth.tsx'), 'utf8')
check(/jobs-why-summary/.test(src), 'the row has no compact one-line why summary')
check(/slice\(0, 80\)/.test(src), 'the summary is not actually shortened — the long text is still on every card')
check(/jobs-why-toggle/.test(src), 'the row has no way to open the full why')
check(/openWhy\[row\.lane_id\] &&/.test(src), 'the full why is always rendered instead of on demand')
check(/jobs-why-detail/.test(src), 'the full why block is missing')
check(/Review job/.test(src), 'the Review job control was removed instead of moved behind the toggle')
check(/Last success:/.test(src), 'the last-success line was removed instead of moved behind the toggle')

if (failed) { console.error(`jobsWhyCompact: ${failed} failure(s)`); process.exit(1) }
console.log('jobsWhyCompact: ok')

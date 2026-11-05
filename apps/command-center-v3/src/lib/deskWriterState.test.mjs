// node --experimental-strip-types src/lib/deskWriterState.test.mjs
//
// cc-deepseek-2's BLOCK on PR 2646: the Source clocks panel mapped ACTIVE and RETIRED, and let the remaining declared
// states — PAUSED and NONE — fall through to "State unavailable". Both are read successfully: PAUSED is the one case where
// "is this source still being refreshed?" has a live, actionable answer, and NONE is the API saying no writer is scheduled.
// This pins one true sentence per declared state, and pins that the page uses this mapping rather than its own copy.
import { readFileSync } from 'node:fs'
import { writerStateWords } from './deskWriterState.ts'

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }
const unavailable = (s) => /unavailable/i.test(s)

check('ACTIVE reads as refreshing', writerStateWords('ACTIVE') === 'Refreshing', writerStateWords('ACTIVE'))
check('RETIRED says it is no longer refreshing', writerStateWords('RETIRED') === 'Retired — not refreshing this source')
check('PAUSED says it is paused, not that the state could not be read',
  writerStateWords('PAUSED') === 'Paused — not refreshing this source', writerStateWords('PAUSED'))
check('NONE says no writer is scheduled', writerStateWords('NONE') === 'No writer is scheduled for this source',
  writerStateWords('NONE'))
check('PAUSED is never described as unavailable', !unavailable(writerStateWords('PAUSED')))
check('NONE is never described as unavailable', !unavailable(writerStateWords('NONE')))
check('every declared, readable state has a distinct sentence',
  new Set(['ACTIVE', 'PAUSED', 'RETIRED', 'NONE'].map(s => writerStateWords(s))).size === 4)
check('an unread state while loading reads as checking', writerStateWords(null, true) === 'Checking')
check('an unread state after load is the only "unavailable"', unavailable(writerStateWords(null)))
check('an out-of-vocabulary state is not guessed into a neighbour',
  unavailable(writerStateWords('SOMETHING_ELSE')), writerStateWords('SOMETHING_ELSE'))

const page = readFileSync(new URL('../components/DeskPage.tsx', import.meta.url), 'utf8')
const at = page.indexOf('data-testid="source-writer-state"')
const visible = page.slice(page.lastIndexOf('const words =', at), at)
check('the panel derives its words from this mapping', /writerStateWords\(st, loading\)/.test(visible), visible.slice(0, 160))
check('the panel does not re-implement the mapping inline', !/'Refreshing'|'State unavailable'/.test(visible), visible.slice(0, 160))

console.log(`deskWriterState: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

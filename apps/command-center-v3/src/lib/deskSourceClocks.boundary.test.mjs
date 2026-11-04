// node --experimental-strip-types src/lib/deskSourceClocks.boundary.test.mjs
//
// FQ-051 (second half): the Source clocks panels printed the writer's own vocabulary — "Writer ACTIVE", "Writer RETIRED",
// "Last successful run: not measured", "Evidence captured: …" — in the normal view. The reader needs one fact: is this
// source still being refreshed. The mechanics stay on the card, in a Diagnostics disclosure.
import { readFileSync } from 'node:fs'

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

const src = readFileSync(new URL('../components/DeskPage.tsx', import.meta.url), 'utf8')
// the visible half: from the word mapping through to the disclosure that follows it
const blockStart = src.lastIndexOf('const st = writer?.state', src.indexOf('data-testid="source-writer-diagnostics"'))
const block = src.slice(blockStart, src.indexOf('data-testid="source-writer-diagnostics"'))

check('the writer state reads as words', /Refreshing/.test(block) && /Retired/.test(block), block.slice(0, 160))
check('and not as the writer\'s code', !/\{writer\?\.state\}|Writer \{/.test(block), block.slice(0, 160))
check('the mechanics sit in a Diagnostics disclosure', /<details[^>]*data-testid="source-writer-diagnostics"/.test(src))
const diagStart = src.indexOf('data-testid="source-writer-diagnostics"')
const diagEnd = src.indexOf('</details>', diagStart)
const diag = src.slice(diagStart, diagEnd)
check('the last-run clock is inside the disclosure', /Last successful run:/.test(diag))
check('the evidence capture is inside the disclosure', /Evidence captured:/.test(diag))
check('the raw state code is inside the disclosure', /Writer state:/.test(diag))
check('none of them are left in the visible part', !/Last successful run:|Evidence captured:/.test(block), block.slice(-160))
check('the consequence is still visible when the writer is not active', /not refreshing this source/.test(block))

console.log(`deskSourceClocks.boundary: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

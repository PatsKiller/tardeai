// node --experimental-strip-types src/lib/releaseHistory.boundary.test.mjs
//
// FQ-069 + FQ-070 boundary: the release history must never go back to a five-column nowrap table (819 px on a 390 px
// phone), and the hashes/receipt/raw reason must not return to the reading line.
import { readFileSync } from 'node:fs'
let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }
const src = readFileSync(new URL('../pages/ReleasesSchedules.tsx', import.meta.url), 'utf8')
const start = src.indexOf('data-testid="rs-history-rows"')
const end = src.indexOf('rs-release-errors')
const block = src.slice(start, end)
check('the history renders as rows, not a table', start > 0 && !/<Table label="Release history"/.test(src))
check('each row is a card with a purpose', /data-testid="rs-release-purpose"/.test(block))
check('the verdict is a pill from the structured kind', /m\.verdict\.tone/.test(block) && /m\.verdict\.label/.test(block))
check('the blocker and next action are on the card', /m\.blocker/.test(block) && /m\.nextAction/.test(block))
const diagStart = block.indexOf('rs-release-diagnostics')
const visible = block.slice(0, diagStart)
check('the hashes are not in the visible half', !/short_sha|r\.sha\b/.test(visible), visible.slice(0, 120))
check('the receipt and raw reason are not in the visible half', !/r\.receipt|verify_reason/.test(visible))
check('they are inside the disclosure', /m\.diagnostics\.map/.test(block.slice(diagStart)))
check('no nowrap on the row', !/whiteSpace: 'nowrap'/.test(block))
console.log(`releaseHistory.boundary: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

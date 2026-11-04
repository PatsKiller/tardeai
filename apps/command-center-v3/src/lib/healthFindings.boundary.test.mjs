// node --experimental-strip-types src/lib/healthFindings.boundary.test.mjs
//
// FQ-038's SOURCE boundary. The card can pass every render test and still leave the finding unfixed, because the page
// is what the operator sees: as long as HealthHub.tsx keeps its own always-visible six-column finding card, the wall of
// paths, unit names and repair commands is still there. This test reads the page and fails while that is true.
import { readFileSync } from 'node:fs'

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

// HEALTHHUB_SRC lets the same boundary be proved against a prepared copy while the page itself is claimed by another
// live session — the mount is then a verified one-liner, not an untested edit on someone else's file.
const src = process.env.HEALTHHUB_SRC
const page = readFileSync(src ? src : new URL('../pages/HealthHub.tsx', import.meta.url), 'utf8')
console.log(`  (source under test: ${src || 'pages/HealthHub.tsx'})`)

check('the page imports the finding card', /import\s+\{[^}]*HealthFindingCard[^}]*\}\s+from\s+'\.\.\/components\/HealthFindingCard'/.test(page),
  'no import of HealthFindingCard')
check('the page renders the card for its findings', /<HealthFindingCard\b/.test(page), 'HealthFindingCard is imported but not rendered')
// the wall: a label that is always visible, not behind a toggle
check('the page no longer prints "Why / root cause" in the always-visible area', !/Why \/ root cause/.test(page),
  'HealthHub.tsx still prints the root-cause label outside the card')
check('the page no longer prints the raw remediation detail inline', !/\{rem\.detail &&/.test(page),
  'HealthHub.tsx still prints remediation detail in the normal view')
check('the page no longer prints a monospace "who" string inline', !/fontFamily: 'ui-monospace, monospace' \}\)\{who\}/.test(page),
  'HealthHub.tsx still prints the raw detected-by string in the normal view')

console.log(`healthFindings.boundary: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

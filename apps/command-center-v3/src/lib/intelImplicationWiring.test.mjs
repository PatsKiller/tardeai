// node --experimental-strip-types src/lib/intelImplicationWiring.test.mjs
//
// FQ-040 R3: the model suite is deliberately pure (it drives the module, it does not grep source). This is the
// separate source-wiring check the reviewer asked for: the page must keep rendering the row, and the Decision
// implications panel must not silently go back to the 9 px wall of thesis text the row replaced.
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const page = readFileSync(join(here, '..', 'components', 'CentralIntelligencePages.tsx'), 'utf8')

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

const panel = page.slice(page.indexOf('Decision implications'))
const panelBody = panel.slice(0, panel.indexOf('Source health'))

check('the page imports the row component',
  /import\s*\{\s*IntelImplicationRow\s*\}\s*from\s*['"]\.\/IntelImplicationRow['"]/.test(page))
check('the Decision implications panel renders the row', /<IntelImplicationRow\b/.test(panelBody))
check('the row receives the page\'s own next step, so the two cannot drift',
  /<IntelImplicationRow[\s\S]{0,300}\bnextStep=/.test(panelBody))
check('the drill-down is passed to the row, not opened by the toggle',
  /<IntelImplicationRow[\s\S]{0,400}\bonOpen=/.test(panelBody))
check('the panel has not gone back to the 9 px thesis wall', !/fontSize:\s*9\b/.test(panelBody))

console.log(`intelImplicationWiring: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

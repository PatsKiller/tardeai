// FQ-030 follow-up (view test, .mjs like moneyFreshness/optionsDesk): the collapse controls are the only
// way out of the collapsed state, so they are touch targets and must clear the house 44px minimum — this
// page's whole finding is phone use. Runs in the CC-v3 build:
//   node src/lib/consumptionPresentation.view.test.mjs
import { readFileSync } from 'node:fs'
const src = readFileSync(new URL('../pages/ConsumptionHub.tsx', import.meta.url), 'utf8')
const lines = src.split('\n')
let pass = 0, fail = 0
function check(name, cond, got) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}${got !== undefined ? ` — got ${JSON.stringify(got)}` : ''}`) }
}
const buttons = lines.map((l, i) => ({ l, i })).filter(b => b.l.includes('aria-expanded={'))
check('both disclosure controls exist', buttons.length === 2, buttons.length)
const targets = buttons.filter(b => lines.slice(b.i, b.i + 4).join(' ').includes('minHeight: 44'))
check('every disclosure control is a 44px target', targets.length === buttons.length, `${targets.length}/${buttons.length}`)
check('the controls are labelled for assistive tech', buttons.every(b => lines.slice(b.i, b.i + 3).join(' ').includes('type="button"')), buttons.length)
console.log(`\nconsumptionPresentation.view: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

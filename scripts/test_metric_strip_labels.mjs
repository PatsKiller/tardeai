// MetricStrip label check — the PORTFOLIO/TODAY chips must not call the DATA
// clock "as_of".
//
// Cause (2026-09-01, #825 follow-up): `overviewSurfaceFreshness` was rebound to
// `data_as_of`, but MetricStrip still rendered a hardcoded `as_of {value}`. The
// number became right while the label named the one field it is specifically
// not reporting. #825 shipped with tsc + a TypeScript unit test, neither of
// which looks at the rendered label.
//
// LIMITATION, stated rather than glossed: this app has no jsdom/render harness,
// so this is a SOURCE-SHAPE assertion, not proof of what renders. It catches a
// regression of this exact defect and nothing more.
//
// Comments are stripped before matching: a substring search cannot otherwise
// tell code from a comment quoting it (AGENTS.md 7, detector shape).
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const target = path.join(here, '..', 'apps', 'command-center-v3', 'src', 'components', 'MetricStrip.tsx')

const raw = fs.readFileSync(target, 'utf8')
const code = raw
  .replace(/\/\*[\s\S]*?\*\//g, '')   // block comments
  .replace(/^\s*\/\/.*$/gm, '')       // whole-line // comments

let pass = 0, fail = 0
const check = (name, cond) => {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

check('renderer no longer hardcodes the as_of label',
  !/\n\s*as_of \{String\(\(t as any\)\.asOf\)/.test(code))
check('renderer takes the label from the tile',
  code.includes("(t as any).asOfLabel || 'as_of'"))
check('portfolio and today tiles both declare the data_as_of label',
  (code.match(/asOfLabel: 'data_as_of'/g) || []).length === 2)
check('an UNDATED tile renders a line rather than nothing',
  code.includes('data-surface-undated'))
check('the overview mark names data_as_of and states UNDATED',
  code.includes('· data_as_of ') && code.includes('data_as_of UNDATED'))

console.log(`\nmetric_strip_labels: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

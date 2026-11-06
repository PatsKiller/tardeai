// node --experimental-strip-types src/lib/intelImplicationWiring.test.mjs
//
// FQ-040 R3: structural source checks for the page/row seam. The BEHAVIOURAL proof lives in
// intelImplicationPage.view.test.mjs, which renders the real page and invokes the real callbacks. This file
// keeps only the invariants a DOM-less render cannot observe: the import, the panel's own structure, the panel
// not regressing to the 9 px thesis wall, and the row's internal `onClick={onOpen}` DOM binding.
//
// Reviewer P1: the previous version matched the raw TSX, so a commented-out block still satisfied every check.
// The TypeScript compiler strips comments (both `// …` and `{/* … */}`) before matching, so commented-out
// wiring cannot satisfy a check. NOTE the remaining blind spot is stated honestly: there is no browser in the
// build chain, so the row's internal onClick binding is asserted by stripped source inspection, not by a click.
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const app = join(here, '..', '..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')

// JsxEmit.Preserve keeps the JSX surface the regexes inspect; removeComments deletes `// …` and, because a JSX
// comment is an ordinary block comment inside an expression container, `{/* … */}` too.
const stripComments = (file) => ts.transpileModule(readFileSync(join(app, 'src', 'components', file), 'utf8'), {
  fileName: file,
  compilerOptions: { jsx: ts.JsxEmit.Preserve, removeComments: true, target: ts.ScriptTarget.ES2022 },
}).outputText

const page = stripComments('CentralIntelligencePages.tsx')
const row = stripComments('IntelImplicationRow.tsx')

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
// The row's DOM click binding cannot be exercised without a browser in this build chain; assert the binding
// itself, on comment-stripped source, so a disabled button/comment cannot pass.
check('the row binds its source-record control to the onOpen callback', /onClick=\{onOpen\}/.test(row))

console.log(`intelImplicationWiring: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

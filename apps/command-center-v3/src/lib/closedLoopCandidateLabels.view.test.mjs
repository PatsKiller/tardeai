// node src/lib/closedLoopCandidateLabels.view.test.mjs
//
// P2 (codex-cloud): keep candidate labels paired with their values when the columns wrap.
//
// CandidateTable lays the heading row and each candidate row out as separate CSS grids. While all four
// cells fit on one line the heading lines up. Once `repeat(auto-fit, minmax(120px, 1fr))` wraps, the
// heading's second visual row stacks above the first candidate row, so "Trigger" ends up over a
// candidate's threshold value instead of its trigger rate.
//
// A text/grep test cannot see that - the markup looked identical either way - so this MOUNTS the
// component and asserts the property that makes wrapping safe: every value cell carries its own label
// in the same element, and the narrow-width rule hides the separate heading and reveals those labels.
// Fail-before-fix: with labels only in the heading, `paired()` is false for every value and the counter
// is zero. Mutation proof: delete the per-cell label spans and this file goes red (see the commit note).
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8').replace(/import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (url: any): any => (globalThis as any).__closedLoopFixture(url)')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const { CandidateTable } = await import(compile(join(app, 'src/components/HermesClosedLoopPanel.tsx')))

let pass = 0, fail = 0
const check = (name, fn) => {
  try { fn(); pass++; console.log(`  [PASS] ${name}`) } catch (e) { fail++; console.log(`  [FAIL] ${name}: ${e.message}`) }
}

const rows = [
  { value: 0.62, score: 0.8123, trigger_rate: 0.25, is_current: true },
  { value: 0.71, score: 0.6410, trigger_rate: 0.50, is_proposed: true },
]
const html = renderToStaticMarkup(React.createElement(CandidateTable, { tid: 'threshold', rows }))

// A value is paired when its label and the value text are children of the SAME candidate cell.
const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const paired = (label, value) => new RegExp(
  `<span class="cc-cand-cell"><span class="cc-cand-cell-label">${label}</span>${escape(value)}</span>`,
).test(html)

const styleText = (html.match(/<style>([\s\S]*?)<\/style>/) || ['', ''])[1]
const cellLabels = (html.match(/class="cc-cand-cell-label"/g) || []).length

// The table still renders, and the desktop heading is still there.
check('the candidate table is rendered', () => {
  assert.match(html, /<div class="cc-cand-head"[^>]*>.*?Value.*?Score.*?Trigger/)
})

// The core invariant: label and value share one cell, for every value, in every row.
check('row 1: Value label sits in the same cell as its threshold value', () => assert.ok(paired('Value', '0.620'), 'Value label is not in the 0.620 cell'))
check('row 1: Score label sits in the same cell as its score', () => assert.ok(paired('Score', '0.8123'), 'Score label is not in the 0.8123 cell'))
check('row 1: Trigger label sits in the same cell as its trigger rate', () => assert.ok(paired('Trigger', '25%'), 'Trigger label is not in the 25% cell'))
check('row 2: Value label sits in the same cell as its threshold value', () => assert.ok(paired('Value', '0.710'), 'Value label is not in the 0.710 cell'))
check('row 2: Score label sits in the same cell as its score', () => assert.ok(paired('Score', '0.6410'), 'Score label is not in the 0.6410 cell'))
check('row 2: Trigger label sits in the same cell as its trigger rate', () => assert.ok(paired('Trigger', '50%'), 'Trigger label is not in the 50% cell'))

check('every rendered value carries its own label (3 per row)', () => {
  assert.equal(cellLabels, rows.length * 3, `expected ${rows.length * 3} in-cell labels, saw ${cellLabels}`)
})

// The narrow layout must actually switch: heading hidden, in-cell labels shown. Otherwise the labels
// would exist in the DOM but stay invisible while the misaligned heading is still displayed.
check('the grid is a container the width rule can query', () => {
  assert.match(styleText, /\.cc-cand\{container-type:inline-size\}/, 'no inline-size container on the table')
})
check('by default the separate heading supplies the labels (desktop unchanged)', () => {
  assert.match(styleText, /\.cc-cand-cell-label\{display:none\}/, 'in-cell labels are visible on desktop')
})
check('at the wrap width the heading steps aside and each cell shows its own label', () => {
  assert.match(styleText, /@container \(max-width:514px\)\{/, 'no container query at the wrap width')
  assert.match(styleText, /@container \(max-width:514px\)\{\.cc-cand-head\{display:none\}\.cc-cand-cell-label\{display:inline/, 'the narrow rule does not hide the heading and show in-cell labels')
})

console.log(`closedLoopCandidateLabels.view: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

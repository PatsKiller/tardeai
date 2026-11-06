// node src/lib/closedLoopLegible.view.test.mjs
//
// FQ-025 (cc-deepseek's re-check at 10edab87, cc-deepseek-2's block): the closed-loop candidate table was unreadable on
// a phone — a fixed `0.7fr 0.7fr 0.7fr 0.5fr` grid at fontSize 8 (header) and 10 (rows). The fix re-flowed it to
// `repeat(auto-fit, minmax(120px, 1fr))` at 11/12. A source-text test cannot tell "the style object says auto-fit" from
// "the rendered element carries it", so this RENDERS the component and asserts the emitted CSS.
//
// Mutation proof: restore the 0.7fr grid or the 8/10 sizes and this file goes red.
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

const fs = require('node:fs')
const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = fs.readFileSync(path, 'utf8').replace(/import \{ useApi \} from ['"][^'"]+['"]/,
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

const html = renderToStaticMarkup(React.createElement(CandidateTable, {
  tid: 'threshold',
  rows: [{ value: 0.62, score: 0.8123, trigger_rate: 0.25, is_current: true },
         { value: 0.71, score: 0.6410, trigger_rate: null, is_proposed: true }],
}))

check('the table is rendered at all', () => assert.ok(html.includes('Value') && html.includes('Score')))
check('cells re-flow instead of using the fixed 0.7fr columns', () => {
  assert.match(html, /grid-template-columns:repeat\(auto-fit, ?minmax\(120px, ?1fr\)\)/)
  assert.doesNotMatch(html, /0\.7fr/, 'the fixed four-column grid is back')
})
check('the row text is at least 12px, not 10', () => {
  assert.match(html, /font-size:12px/)
  assert.doesNotMatch(html, /font-size:10px/, 'a 10px row survived')
})
check('the header is at least 11px, not 8', () => {
  assert.match(html, /font-size:11px/)
  assert.doesNotMatch(html, /font-size:8px/, 'an 8px header survived')
})

console.log(`closedLoopLegible.view: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

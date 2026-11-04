/**
 * FQ-061 (operator page audit 2026-11-04T0011Z, /risk): the warning above the loss summary read
 * "Conflict check unavailable: conflict engine accepted source not yet integrated" — an internal
 * engine name and a producer status, with no consequence for the operator and no next step.
 *
 * Acceptance: the operator learns what could not be checked and how that limits the figures shown;
 * the raw producer reason stays available inside a closed technical-detail toggle.
 */
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
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
  const source = readFileSync(path, 'utf8').replace(/import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (..._args: any[]): any => (globalThis as any).__conflictFixture')
  let js = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
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

const { default: ConflictLine } = await import(compile(join(app, 'src/components/conflicts/ConflictLine.tsx')))

const results = []
function check(name, fn) {
  try { fn(); results.push({ name, passed: true }) }
  catch (e) { results.push({ name, passed: false, assertion: e.message.split('\n')[0] }) }
}
const render = section => renderToStaticMarkup(React.createElement(ConflictLine, { section, onOpen() {} }))
const visible = html => html.replace(/<details[\s\S]*?<\/details>/g, '')

const raw = 'conflict engine accepted source not yet integrated'
const html = render({ findings: [], headline: null, gap: { reason: raw } })

check('says what could not be checked and how it limits the risk figures', () => {
  assert.match(visible(html), /Cross-checks could not run: the comparison source is not connected yet\./)
  assert.match(visible(html), /The risk figures below use stops and positions only, so overlapping positions and conflicting signals are not counted\./)
})
check('does not present the producer string as the explanation', () => {
  assert.doesNotMatch(visible(html), /conflict engine accepted source not yet integrated/)
  assert.match(visible(html), /Conflict check unavailable:/, 'the existing heading is retained')
})
check('keeps the raw producer string behind a technical-detail toggle', () => {
  assert.match(html, /<details[^>]*>[\s\S]*conflict engine accepted source not yet integrated[\s\S]*?<\/details>/)
})
check('an unknown producer reason still gets the consequence sentence', () => {
  const unknown = render({ findings: [], headline: null, gap: { reason: 'some_new_producer_state' } })
  assert.match(visible(unknown), /Cross-checks could not run, so these figures may omit overlapping positions or conflicting signals\./)
  assert.match(unknown, /<details[^>]*>[\s\S]*some_new_producer_state[\s\S]*?<\/details>/)
})
check('a supplied reason is optional: no reason still explains the limit', () => {
  const none = render({ findings: [], headline: null, gap: {} })
  assert.match(visible(none), /Cross-checks did not run, so these figures may omit overlapping positions or conflicting signals\./)
  assert.doesNotMatch(none, /<details/)
})

const out = { results, passed: results.filter(x => x.passed).length, failed: results.filter(x => !x.passed).length }
console.log(JSON.stringify(out, null, 2))
if (out.failed) process.exit(1)

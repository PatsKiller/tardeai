import assert from 'node:assert/strict'
import { readFileSync, existsSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const root = resolve(app, '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8').replace(/import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (..._args: any[]): any => (globalThis as any).__rotationFixture')
  let js = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target+s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}
const { default: View } = await import(compile(join(app, 'src/components/intelligence/IntelligenceRotationTab.tsx')))
const at = new Date().toISOString()
const summary = {
  ok: true, summary: { trim_review: 99, add_review: 88, rotation_ideas: 77 },
  top_rotation_ideas: [{ from_symbol: 'AAA', to_symbol: 'BBB', action_class: 'ROTATE_REVIEW' }],
  publication: { schema: 'RotationPublication@v1', status: 'READY', reasons: [], checked_at: at,
    input_sha256: 'a'.repeat(64), source_as_of: at, cache_generated_at: at, producer_ok: true,
    source_as_of_basis: 'oldest_required_position_or_account_timestamp',
    coverage: { required_positions: 1, dated_positions: 1, accounts: 1, dated_accounts: 1 },
    accounts: [{ account_key: 'fixture', state: 'LIVE', source_as_of: at }] },
}
const cases = [
  ['ready control', summary, null, text => assert.match(text, /AAA/)],
  ['unavailable hides old advice', { ...summary, ok: false, publication: { ...summary.publication, status: 'UNAVAILABLE', reasons: ['missing_input'] } }, null,
    text => { assert.match(text, /UNAVAILABLE/); assert.doesNotMatch(text, /AAA|>99</) }],
  ['stale hides old advice', { ...summary, publication: { ...summary.publication, status: 'STALE', reasons: ['account_stale'] } }, null,
    text => { assert.match(text, /STALE/); assert.doesNotMatch(text, /AAA|>99</) }],
  ['unversioned producer is unavailable', { ...summary, publication: undefined }, null,
    text => { assert.match(text, /UNAVAILABLE/); assert.doesNotMatch(text, /AAA/) }],
  ['expired ready is stale', { ...summary, publication: { ...summary.publication, checked_at: new Date(Date.now()-901_000).toISOString() } }, null,
    text => { assert.match(text, /STALE/); assert.doesNotMatch(text, /AAA/) }],
  ['fetch error supersedes retained ready', summary, 'HTTP 503',
    text => { assert.match(text, /UNAVAILABLE/); assert.doesNotMatch(text, /AAA/); assert.match(text, /Source as of/) }],
]
const results = []
for (const [name, data, error, check] of cases) {
  globalThis.__rotationFixture = { data, error, loading: false }
  try { check(renderToStaticMarkup(React.createElement(View, { onDrill() {} }))); results.push({ name, passed: true }) }
  catch (e) { results.push({ name, passed: false, error: e.name, assertion: e.message.split('\n')[0] }) }
}
const out = { source_root: root, results, passed: results.filter(x=>x.passed).length, failed: results.filter(x=>!x.passed).length }
if (process.env.ROTATION_UI_RESULT) writeFileSync(process.env.ROTATION_UI_RESULT, JSON.stringify(out, null, 2)+'\n')
console.log(JSON.stringify(out, null, 2))
process.exitCode = out.failed ? 1 : 0

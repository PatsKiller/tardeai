/**
 * FQ-062 (operator page audit 2026-11-04T0011Z): the withheld Rotation notice listed
 * "account data stale · position evidence stale · stop claim unsupported" and offered only
 * Refresh Summary. The operator could not tell what evidence had to update or what to do.
 *
 * Acceptance: every withheld reason renders in plain English, says which evidence must update,
 * and names the next step. The raw code stays available inside a closed technical-detail toggle.
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
  const source = readFileSync(path, 'utf8')
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

const { default: Notice } = await import(compile(join(app, 'src/components/RotationPublicationNotice.tsx')))

const at = new Date().toISOString()
function summary(status, reasons) {
  return {
    ok: status === 'READY',
    publication: {
      schema: 'RotationPublication@v1', status, reasons, checked_at: at, source_as_of: at,
      cache_generated_at: at, producer_ok: status === 'READY', input_sha256: 'a'.repeat(64),
      source_as_of_basis: 'oldest_required_position_or_account_timestamp',
      coverage: { required_positions: 1, dated_positions: 1, accounts: 1, dated_accounts: 1 },
      accounts: [{ account_key: 'fixture', state: 'LIVE', source_as_of: at }],
    },
  }
}

const results = []
function check(name, fn) {
  try { fn(); results.push({ name, passed: true }) }
  catch (e) { results.push({ name, passed: false, assertion: e.message.split('\n')[0] }) }
}

const withheld = renderToStaticMarkup(React.createElement(Notice, {
  summary: summary('UNAVAILABLE', ['account_stale', 'position_evidence_stale', 'unsupported_stop_claim']),
}))

check('every blocker names the evidence that must update', () => {
  assert.match(withheld, /The account balances this review reads are older than its 15-minute window\./)
  assert.match(withheld, /The position quantities this review reads are older than its 15-minute window\./)
  assert.match(withheld, /could not be matched to a recorded stop/)
})
check('every blocker names the next step', () => {
  assert.match(withheld, /It clears when the next account sync writes a newer balance timestamp; then press Refresh Summary\./)
  assert.match(withheld, /It clears when the next position sync writes newer evidence; then press Refresh Summary\./)
  assert.match(withheld, /review that position in Risk → Recovery\./)
})
check('blockers are listed, not only chipped', () => {
  assert.match(withheld, /data-testid="rotation-blocker-next"/)
})
check('the raw reason code is behind a details toggle, never the operator explanation', () => {
  assert.doesNotMatch(withheld.replace(/<details[\s\S]*?<\/details>/g, ''), /account_stale|unsupported_stop_claim/)
  assert.match(withheld, /<details[^>]*>[\s\S]*account_stale[\s\S]*?<\/details>/)
})
check('an unknown reason still gets a next step and keeps its code in detail', () => {
  const unknown = renderToStaticMarkup(React.createElement(Notice, { summary: summary('UNAVAILABLE', ['brand_new_reason']) }))
  assert.match(unknown, /This condition is not one the page can explain yet\./)
  assert.match(unknown, /Press Refresh Summary after the sources update\./)
  assert.match(unknown, /<details[^>]*>[\s\S]*brand_new_reason[\s\S]*?<\/details>/)
})
check('a ready advisory renders no blocker list', () => {
  const ready = renderToStaticMarkup(React.createElement(Notice, { summary: summary('READY', []) }))
  assert.doesNotMatch(ready, /rotation-blocker-next/)
})
check('the live producer reason account_unavailable explains the missing evidence', () => {
  const live = renderToStaticMarkup(React.createElement(Notice, { summary: summary('UNAVAILABLE', ['account_unavailable', 'unsupported_stop_claim']) }))
  const visible = live.replace(/<details[\s\S]*?<\/details>/g, '')
  assert.match(visible, /The account data this review reads is unavailable, so it cannot tell which holdings are eligible to rotate\./)
  assert.match(visible, /It clears when the account sync returns a balance; then press Refresh Summary\./)
  assert.doesNotMatch(visible, /account_unavailable/)
})

const out = { results, passed: results.filter(x => x.passed).length, failed: results.filter(x => !x.passed).length }
console.log(JSON.stringify(out, null, 2))
if (out.failed) process.exit(1)

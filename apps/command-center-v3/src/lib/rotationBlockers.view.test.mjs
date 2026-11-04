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
  assert.match(withheld, /The account source itself reports this account as stale, so the review will not use it\./)
  assert.match(withheld, /The position quantities this review reads are older than the freshness window the account source declares/)
  assert.match(withheld, /does not show a stop-distance deterioration that would support acting/)
})
check('every blocker names the next step', () => {
  assert.match(withheld, /Waiting for this page’s clock will not clear it\./)
  assert.match(withheld, /It clears when the next position sync writes newer evidence and its age is inside that declared window; then press Refresh Summary\./)
  assert.match(withheld, /a deterministic stop-distance degradation with the thesis triggered, at danger or at warning/)
})
check('the account-evidence window is the declared one, never a fixed 15 minutes', () => {
  const declared = renderToStaticMarkup(React.createElement(Notice, { summary: summary('STALE', ['account_evidence_stale']) }))
  const visible = declared.replace(/<details[\s\S]*?<\/details>/g, '')
  assert.match(visible, /freshness window the account source declares/)
  assert.match(visible, /follows the sync interval and market hours/)
  assert.doesNotMatch(visible, /15-minute/)
})
check('the copy does not claim what the producer does not establish (P2622-style P2s)', () => {
  const visible = withheld.replace(/<details[\s\S]*?<\/details>/g, '')
  // The account/position windows come from the account state's sync_window_hours, not a fixed 15 minutes.
  assert.doesNotMatch(visible, /15-minute window/)
  // unsupported_stop_claim is a stop-DISTANCE degradation predicate, not a missing/recorded stop.
  assert.doesNotMatch(visible, /recorded stop|matched to a stop|covers the position/)
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
  assert.match(visible, /The account source reports this account as not live, so the review cannot use its balances to tell which holdings are eligible to rotate\./)
  assert.match(visible, /It clears when the account source reports the account live again; then press Refresh Summary\./)
  assert.doesNotMatch(visible, /account_unavailable/)
})
check('an explicit producer STALE refusal is not described as an elapsed-time window', () => {
  const stale = renderToStaticMarkup(React.createElement(Notice, { summary: summary('STALE', ['account_stale']) }))
  const visible = stale.replace(/<details[\s\S]*?<\/details>/g, '')
  assert.match(visible, /The account source itself reports this account as stale, so the review will not use it\./)
  assert.match(visible, /Waiting for this page’s clock will not clear it\./)
  assert.doesNotMatch(visible, /15-minute/)
})

// review of PR 2617 F3 (cx-openai-3): `publication_expired` fires on ANY of an old checked_at, an old
// cache_generated_at, or an explicit stale marker, so the sentence must describe the whole refusal and
// must never assert that the validation clock is the stale one.
function expired(overrides = {}) {
  const s = summary('STALE', ['publication_expired'])
  return { ...s, publication: { ...s.publication, ...overrides } }
}
check('a fresh validation with old producer output is not explained as an old validation', () => {
  const now = Date.now()
  const html = renderToStaticMarkup(React.createElement(Notice, {
    summary: expired({
      checked_at: new Date(now - 60_000).toISOString(),
      cache_generated_at: new Date(now - 20 * 60_000).toISOString(),
    }),
  }))
  const visible = html.replace(/<details[\s\S]*?<\/details>/g, '')
  assert.match(visible, /either the source validation, or the producer output it was built from, is older than 15 minutes/)
  assert.doesNotMatch(visible, /The last validation of these sources is older than 15 minutes\./)
})
check('an explicit producer stale marker is not explained as an old validation', () => {
  const now = Date.now()
  const html = renderToStaticMarkup(React.createElement(Notice, {
    summary: expired({ checked_at: new Date(now - 60_000).toISOString(), cache_generated_at: new Date(now - 60_000).toISOString(), stale: true }),
  }))
  const visible = html.replace(/<details[\s\S]*?<\/details>/g, '')
  assert.match(visible, /or the producer itself marked the result stale/)
  assert.doesNotMatch(visible, /The last validation of these sources is older than 15 minutes\./)
})

const out = { results, passed: results.filter(x => x.passed).length, failed: results.filter(x => !x.passed).length }
console.log(JSON.stringify(out, null, 2))
if (out.failed) process.exit(1)

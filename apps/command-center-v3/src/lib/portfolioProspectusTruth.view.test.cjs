// Real holdings and prospectus consumers; synthetic data and no network.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const app = path.resolve(__dirname, '../..')
const req = Module.createRequire(path.join(app, 'package.json'))
const ts = req('typescript')
const React = req('react')
const { renderToStaticMarkup } = req('react-dom/server')
const { MemoryRouter } = req('react-router-dom')
const SSR_LAYOUT_WARNING = 'Warning: useLayoutEffect does nothing on the server, because its effect cannot ' +
  "be encoded into the server renderer's output format. This will lead " +
  'to a mismatch between the initial, non-hydrated UI and the intended ' +
  'UI. To avoid this, useLayoutEffect should only be used in ' +
  'components that render exclusively on the client. ' +
  'See https://reactjs.org/link/uselayouteffect-ssr for common fixes.'
const originalError = console.error
let filteredWarnings = 0
console.error = (...args) => {
  if (args[0] === SSR_LAYOUT_WARNING || args[0] === SSR_LAYOUT_WARNING + '%s') { filteredWarnings++; return }
  originalError(...args)
}
for (const ext of ['.ts', '.tsx']) Module._extensions[ext] = (m, file) => {
  const source = fs.readFileSync(file, 'utf8')
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText
  m._compile(js, file)
}
Module._extensions['.css'] = m => { m.exports = {} }
let width = 1280
global.window = { matchMedia: () => ({ matches: width <= 820, addEventListener() {}, removeEventListener() {} }), location: { search: '' } }
let networkCalls = 0
global.fetch = () => { networkCalls++; throw new Error('Network forbidden in synthetic consumer tests') }
let indexFixture
const apiPath = req.resolve('./src/hooks/useApi.ts')
require.cache[apiPath] = { id: apiPath, filename: apiPath, loaded: true, exports: { useApi: () => ({ data: indexFixture, loading: false, error: null, refetch() { throw new Error('Unexpected refetch') } }) } }
const sharePath = req.resolve('./src/components/ShareReconciliationModal.tsx')
const shareExports = req(sharePath)
const ActualPill = shareExports.ShareDriftPill
let pills = []
require.cache[sharePath].exports = { ...shareExports, ShareDriftPill(props) {
  const button = ActualPill(props)
  pills.push(button)
  return button
} }
const model = req('./src/lib/prospectusModel.ts')
const Holdings = req('./src/components/HoldingsTableView.tsx').default
const Prospectus = req('./src/pages/ProspectusPage.tsx').default
const results = []
function check(name, fn) {
  try { fn(); results.push({ name, passed: true }) }
  catch (e) { results.push({ name, passed: false, assertion: e.message.split('\n')[0] }) }
}
const textOf = m => m.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/\s+/g, ' ').trim()
for (width of [390, 412, 800, 1280]) for (const drift of ['pending', 'broker-difference', 'none']) {
  check('holdings ' + width + ': ' + drift + ' warning and callback', () => {
    const h = { symbol: 'SYNTH', account: 'Demo', name: 'Synthetic security', shares: 10, price: 100, avg_cost: 90, market_value: 1000,
      share_drift_status: drift === 'pending' ? 'pending' : null, broker_actual_shares: drift === 'broker-difference' ? 11 : 10 }
    const ctx = { h }, reconciled = []
    pills = []
    const markup = renderToStaticMarkup(React.createElement(Holdings, { rows: [ctx], acctColor: () => '#999',
      onOpenDetail() {}, onOpenStops() {}, onShareDrift: row => reconciled.push(row) }))
    assert.ok(markup.includes('SYNTH'))
    assert.equal(markup.includes('holdings-mobile-list'), width <= 820)
    const pending = drift !== 'none'
    assert.equal(markup.includes('share-drift-pill'), pending)
    assert.equal(markup.includes('Shares need update'), pending)
    assert.equal(pills.length, pending ? 1 : 0)
    if (pending) {
      let stopped = 0
      pills[0].props.onClick({ stopPropagation() { stopped++ } })
      assert.equal(stopped, 1)
      assert.equal(reconciled.length, 1)
      assert.strictEqual(reconciled[0], ctx)
    } else assert.equal(reconciled.length, 0)
  })
}
function prospectus(budget, reason = null) {
  indexFixture = { items: [{ symbol: 'SYNTH', name: 'Synthetic security', scope: 'watch', status: reason ? 'failed' : 'ready',
    failure_reason: reason, generated_at: reason ? null : '2030-01-07T15:00:00Z' }], budget }
  return textOf(renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/prospectus'] }, React.createElement(Prospectus))))
}
for (width of [390, 1280]) {
  for (const [name, budget, headline] of [
    ['whitespace-refused', { credit_remaining_usd: ' ', status: 'UNAVAILABLE' }, 'Unavailable'],
    ['retained-refused', { credit_remaining_usd: 25, status: 'UNAVAILABLE', error: 'upstream failed' }, 'Unavailable'],
    ['error-status', { credit_remaining_usd: 25, status: 'ERROR' }, 'Unavailable'],
    ['error-text', { credit_remaining_usd: 25, status: 'OK', error: ' upstream failed ' }, 'Unavailable'],
    ['blank-ok', { credit_remaining_usd: ' ', status: 'OK' }, 'Not measured'],
    ['denied', { credit_remaining_usd: null, status: 'UNAVAILABLE', error: 'CreditDenied' }, 'Unavailable'],
  ]) check('credit ' + width + ': ' + name, () => {
    const text = prospectus(budget)
    assert.ok(text.includes(headline))
    assert.ok(!text.includes('$0.00') && !text.includes('$25.00'))
    assert.ok(!text.includes('Prospectus writing still works'))
    assert.equal(model.creditState(budget).measured, false)
    assert.equal(model.budgetView(budget).remaining, '—')
  })
  for (const amount of [25, '25', 0, '0']) check('credit ' + width + ': measured ' + JSON.stringify(amount), () => {
    const budget = { credit_remaining_usd: amount, status: 'OK', today_used_usd: 1, daily_cap_usd: 10 }
    assert.ok(prospectus(budget).includes(Number(amount) === 0 ? '$0.00' : '$25.00'))
    assert.equal(model.creditState(budget).measured, true)
  })
  for (const amount of [false, true, [], {}, NaN, Infinity]) check('credit ' + width + ': malformed ' + typeof amount + ' ' + String(amount), () => {
    const budget = { credit_remaining_usd: amount, status: 'OK' }
    assert.ok(prospectus(budget).includes('Not measured'))
    assert.equal(model.budgetView(budget).remaining, '—')
  })
  for (const reason of ['ParseError: Unable to generate a valid JSON object', 'Corporate service unavailable']) check('failure ' + width + ': ordinary ' + reason, () => {
    const text = prospectus({ credit_remaining_usd: 25, status: 'OK' }, reason)
    assert.ok(!text.includes('model allowance blocked') && !text.includes('allowance resets'))
    assert.equal(model.failureHeadline(reason).raw, reason)
  })
  for (const reason of ['RateLimitError: 429', 'QUOTA_EXCEEDED', 'insufficient_quota']) check('failure ' + width + ': allowance ' + reason, () => {
    assert.ok(prospectus({ credit_remaining_usd: 25, status: 'OK' }, reason).includes('model allowance blocked'))
  })
  check('failure ' + width + ': first generation does not invent previous version', () => {
    const text = prospectus({ credit_remaining_usd: 25, status: 'OK' }, 'TRANSPORT_FAILED')
    assert.ok(!text.includes('previous version'))
    assert.ok(text.includes('last run failed') && text.includes('re-run the rewrite'))
  })
  for (const [reason, words] of [
    ['GenerationFailed: OUTPUT_NOT_JSON', 'not in the expected format'],
    ['RequestError: TIMED_OUT', 'writer timed out'],
    ['Writer refused: too few cited facts (2 of 6 required)', 'Writer refused: too few cited facts (2 of 6 required)'],
  ]) check('failure ' + width + ': positive ' + reason, () => {
    assert.ok(prospectus({ credit_remaining_usd: 25, status: 'OK' }, reason).includes(words))
    assert.equal(model.failureHeadline(reason).raw, reason)
  })
}
check('synthetic consumers never fetch', () => assert.equal(networkCalls, 0))
console.error = originalError
const passed = results.filter(r => r.passed).length, failed = results.length - passed
console.log(JSON.stringify({ results, passed, failed, filteredWarnings, networkCalls }, null, 2))
if (failed) process.exitCode = 1

// FQ-015 — the advisory list on a phone: readable cards, and a full-screen detail entry.
//
// Live at release 105df180e at 412 px the advisory table measured 1150 px inside a 334 px box, so only symbol/class and a
// sliver of the next column were visible while the page itself did not overflow. The page's own overflow check was
// therefore "false" and said nothing.
//
// Red-first: at the parent page these controls fail — there is no card list at all, only the wide table.
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

let PHONE = true
globalThis.window = globalThis.window || {}
globalThis.window.matchMedia = (q) => ({
  matches: PHONE && String(q).includes('820'), media: q,
  addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
})
globalThis.window.location = globalThis.window.location || { origin: 'http://localhost:4173', pathname: '/v3/advisory', search: '', hash: '' }
globalThis.window.addEventListener = globalThis.window.addEventListener || (() => {})
globalThis.window.removeEventListener = globalThis.window.removeEventListener || (() => {})
globalThis.document = globalThis.document || { documentElement: { style: {} }, body: { style: {} },
  addEventListener() {}, removeEventListener() {}, querySelector: () => null, querySelectorAll: () => [] }

const memo = new Map()
// MobileDetailSheet renders through createPortal, which the server renderer refuses. Keep the real hook
// (the URL-driven detail id) and render the sheet's own children inline, so the phone path's markup is
// what the assertions read instead of the portal wrapper.
const sheetStubMemo = new Map()
function sheetStub(realPath) {
  if (sheetStubMemo.has(realPath)) return sheetStubMemo.get(realPath)
  const src = `import React from ${JSON.stringify(pathToFileURL(require.resolve('react')).href)};
import { useMobilePageDetail as realHook } from ${JSON.stringify(compile(realPath))};
export const useMobilePageDetail = realHook;
export function MobileDetailSheet({ children }) {
  return React.createElement('section', { 'data-detail-sheet': '1' }, children);
}
`
  const url = `data:text/javascript;base64,${Buffer.from(src).toString('base64')}`
  sheetStubMemo.set(realPath, url)
  return url
}
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8').replace(
    /import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (..._args: any[]): any => (globalThis as any).__apiFixture(String(_args[0] ?? \'\'))',
  )
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.replace(/import\s+['"][^'"]+\.css['"];?/g, '')
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (spec.endsWith('.css')) return 'from "data:text/javascript,export default {}"'
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map((s) => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    if (spec === '../components/MobileDetailSheet') return `from ${JSON.stringify(sheetStub(target))}`
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const rows = [
  { symbol: 'SPCX', account: 'schwab_taxable', row_class: 'holding', market_value: 27578, verdict: 'TRIM', confidence: 0.72,
    data_quality: { evidence_count: 4, gap_count: 1, quality: 'OK' }, why_call: 'Trim because the AI-compute thesis lost its catalyst.' },
  { symbol: 'SCHD', account: 'schwab_taxable', row_class: 'holding', market_value: 60000, verdict: 'HOLD', confidence: 0.55,
    data_quality: { evidence_count: 3, quality: 'OK' }, why_call: 'Hold: income sleeve, no new equity ticket.' },
]
globalThis.__apiFixture = (url) => {
  const banners = [{ id: 'DATA_CONFLICT', severity: 'warn', title: 'Two marks disagree for SPCX', detail: 'Mark 132.99 vs model 141.65' },
                   { id: 'PLAUSIBILITY_OK', severity: 'info', title: 'Distribution within bounds', detail: 'weights sum to 100%' }]
  if (url.includes('/api/v3/advisory')) return { data: { rows, banners, timestamps: {}, desk_health: { overall: 'DESK_DEGRADED' }, by_class: {}, metadata: {} }, loading: false, error: null }
  return { data: null, loading: false, error: null }
}

const { default: Page } = await import(compile(join(app, 'src/pages/AdvisoryDeskHub.tsx')))

function render(phone, entry = '/v3/advisory') {
  PHONE = phone
  return renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [entry] }, React.createElement(Page, {})))
}

const cases = []
function check(name, fn) { cases.push({ name, fn }) }

check('a phone renders one card per advisory row, not a wide table', () => {
  const html = render(true)
  assert.equal((html.match(/data-testid="card-/g) || []).length, rows.length, 'one card per row')
  assert.ok(html.includes('data-advisory-cards'))
  assert.ok(!html.includes('<table'), 'the wide table must not be the phone rendering')
})

check('the card shows the decision fields the table hid', () => {
  const html = render(true)
  for (const want of ['SPCX', 'TRIM', 'conf 0.72', 'ev 4', 'gaps 1', 'lost its catalyst']) {
    assert.ok(html.includes(want), `card is missing ${want}`)
  }
})

check('the card offers the full-screen detail entry', () => {
  const html = render(true)
  assert.match(html, /Open full details/)
})

// FQ-015 repair (cc-deepseek-6 F1): the sheet carries the row's feedback actions, not only its detail, so a
// phone operator can acknowledge, snooze and rate. The match is the desktop path's own button markup.
check('the phone detail sheet carries the row feedback actions', () => {
  const html = render(true, '/v3/advisory?detail=SPCX%3Aschwab_taxable%3A')
  const sheet = (html.match(/<section data-detail-sheet="1">([\s\S]*?)<\/section>/) || [])[1]
  assert.ok(sheet && />Ack<\/button>/.test(sheet), 'the phone sheet body does not carry the Ack control')
})

// FQ-015 repair (codex-cloud CX1): the desktop table names which kind of TRIM a row is — concentration
// policy, profit-taking rule, or housekeeping remnant. The phone card must keep that label and its
// explanation, or the three kinds of cut read as interchangeable.
check('the phone card keeps the trim-kind label and its explanation', () => {
  const prev = globalThis.__apiFixture
  const trimmed = [{ ...rows[0], trim_kind: 'rule' }, rows[1]]
  globalThis.__apiFixture = (url) => url.includes('/api/v3/advisory')
    ? { data: { rows: trimmed, banners: [], timestamps: {}, desk_health: {}, by_class: {}, metadata: {} }, loading: false, error: null }
    : { data: null, loading: false, error: null }
  try {
    const html = render(true)
    const card = (html.match(/data-testid="card-SPCX"[\s\S]*?<\/button>/) || [])[0]
    assert.ok(card, 'no SPCX card rendered')
    assert.match(card, /data-testid="trim-kind"/, 'the phone card lost the trim-kind marker')
    assert.match(card, />rule</, 'the phone card lost the trim-kind label text')
    assert.ok(card.includes('profit-taking threshold'), 'the phone card lost the trim-kind explanation')
  } finally {
    globalThis.__apiFixture = prev
  }
})

// FQ-015 repair (codex-cloud CX2): tapping Ack, Snooze, Useful or Not useful must show its result where
// the operator is. The full-screen sheet covers the toolbar where feedbackMsg was the only copy, so the
// action row owns a live status region instead.
check('the phone detail sheet shows the feedback result in its action row', () => {
  const html = render(true, '/v3/advisory?detail=SPCX%3Aschwab_taxable%3A')
  const sheet = (html.match(/<section data-detail-sheet="1">([\s\S]*?)<\/section>/) || [])[1]
  assert.ok(sheet, 'no sheet rendered for the detail entry')
  const actions = (sheet.match(/<div[^>]*data-testid="advisory-row-actions"[^>]*>([\s\S]*?)<\/div>/) || [])[1]
  assert.ok(actions, 'the sheet has no action row')
  const status = (actions.match(/<span[^>]*data-testid="advisory-feedback-status"[^>]*>/) || [])[0]
  assert.ok(status, 'the action row has no feedback status region')
  assert.match(status, /role="status"/, 'the feedback status is not a status region')
  assert.match(status, /aria-live="polite"/, 'the feedback status is not announced when it changes')
  assert.ok(actions.indexOf('data-testid="advisory-feedback-status"') > actions.indexOf('>Ack</button>'),
    'the feedback status does not sit alongside the action buttons')
})

// FQ-016 — the state vocabulary is a sentence, with the code kept in the tooltip.
check('state codes are not the page text', () => {
  const html = render(true)
  const text = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
  for (const raw of ['READ_ONLY_ADVISORY', 'DATA_CONFLICT', 'DESK_DEGRADED', 'PLAUSIBILITY_OK', 'LOTS_OK']) {
    assert.ok(!new RegExp(`(^|[^A-Z_])${raw}([^A-Z_]|$)`).test(text), `raw code ${raw} is in the reading text`)
  }
  assert.match(text, /Read-only advice/)
})

check('the raw code survives in the tooltip', () => {
  const html = render(true)
  assert.match(html, /title="READ_ONLY_ADVISORY"/)
})

check('desktop still gets the table', () => {
  const html = render(false)
  assert.ok(html.includes('<table'), 'desktop lost the table')
  assert.ok(!html.includes('data-advisory-cards'))
})

// FQ-003 — one effective freshness, and the page says which snapshot governs.
check('a current feed beside stale rows shows the stricter state and explains it', () => {
  const fixture = { rows, banners: [], timestamps: { watch: '2026-11-04T13:30:04Z', watch_freshness: 'CURRENT' },
    desk_health: {}, by_class: {}, metadata: {},
    dependency_clocks: { watch_intelligence: { freshness: 'STALE', age_seconds: 5443200, source_as_of: '2026-09-02T16:21:21Z' } } }
  globalThis.__apiFixture = (url) => url.includes('/api/v3/advisory')
    ? { data: fixture, loading: false, error: null } : { data: null, loading: false, error: null }
  const html = render(true)
  const t = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
  assert.match(html, /data-testid="watch-clock-note"/)
  assert.match(t, /the watch feed is current while the watch rows themselves are stale/i)
  assert.match(t, /the rows govern any advice/i)
})

check('when the two agree there is no note and the state is that state', () => {
  const fixture = { rows, banners: [], timestamps: { watch: '2026-11-04T13:30:04Z', watch_freshness: 'CURRENT' },
    desk_health: {}, by_class: {}, metadata: {},
    dependency_clocks: { watch_intelligence: { freshness: 'CURRENT', age_seconds: 60 } } }
  globalThis.__apiFixture = (url) => url.includes('/api/v3/advisory')
    ? { data: fixture, loading: false, error: null } : { data: null, loading: false, error: null }
  const html = render(true)
  assert.ok(!html.includes('watch-clock-note'), 'a note appeared when the clocks agree')
})


const results = []
for (const c of cases) {
  try { c.fn(); results.push({ name: c.name, passed: true }) }
  catch (e) { results.push({ name: c.name, passed: false, error: e.message.split('\n')[0] }) }
}
const out = { results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)

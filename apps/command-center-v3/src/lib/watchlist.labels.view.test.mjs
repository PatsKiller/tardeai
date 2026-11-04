// Rendering test for BOARD row 38 (/watchlist): internal codes must read as meaning, not as identifiers.
//
// The audit (2026-11-04) found capitals on /watchlist: DATA_UNAVAILABLE, DETERMINISTIC_FAIL, ANSWERED_PENDING_CIO.
// This test RENDERS the real page (server render, stubbed fetch hooks) and asserts the operator's text:
//   * sentence labels appear, the raw codes do not appear in the text;
//   * the raw code stays recoverable in the element's title attribute;
//   * an unknown code is humanised rather than dropped or guessed.
// It fails before the fix (the raw codes are the text) and after a regression that removes the labels.
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
const { MemoryRouter } = require('react-router-dom')

// The page's mobile-detail hook reads matchMedia in a useState initializer. A server render has no window; the
// browser this page actually runs in does, so the harness supplies the minimal shape (desktop, no scrolling).
globalThis.window = globalThis.window ?? {
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  innerWidth: 1400,
  scrollTo() {},
}

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8')
    .replace(/^\s*import\s+['"][^'"]+\.(css|svg|png)['"];?\s*$/gm, '')
    .replace(/import \{([^}]*)\} from (['"][^'"]+['"])/g, (whole, names, spec) => {
      const list = names.split(',').map(s => s.trim()).filter(Boolean)
      const kept = list.filter(n => n !== 'useApi' && n !== 'useGovernance')
      const stubs = []
      if (list.includes('useApi')) stubs.push('const useApi = (...a: any[]): any => (globalThis as any).__apiFixture(String(a[0] ?? ""))')
      if (list.includes('useGovernance')) stubs.push('const useGovernance = (...a: any[]): any => (globalThis as any).__govFixture(...a)')
      const imp = kept.length ? `import { ${kept.join(', ')} } from ${spec}` : ''
      return [imp, ...stubs].filter(Boolean).join('\n')
    })
  const jsx = path.endsWith('.tsx') ? ts.JsxEmit.ReactJSX : ts.JsxEmit.None
  let js = ts.transpileModule(source, { compilerOptions: { jsx, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, removeComments: true } }).outputText
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

const html = (el) => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [globalThis.__entry] }, el))
const text = (markup) => markup
  .replace(/<[^>]+>/g, ' ')
  .replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&gt;/g, '>').replace(/&lt;/g, '<')
  .replace(/&middot;|·/g, '·').replace(/\s+/g, ' ').trim()

const cards = [
  { symbol: 'AAA', trade_ai_state: 'DATA_UNAVAILABLE', street_rating: 'HOLD', last: 10, day_change_pct: 1,
    proposal_allowed: false, cio_review: { status: 'ANSWERED_PENDING_CIO' }, maria_review: { status: 'NOT_RUN' } },
  { symbol: 'BBB', trade_ai_state: 'DETERMINISTIC_FAIL', street_rating: 'BUY', last: 20, day_change_pct: -1,
    proposal_allowed: false, cio_review: { status: 'COMPLETE' }, maria_review: null },
  { symbol: 'CCC', trade_ai_state: 'SOME_NEW_CODE', street_rating: 'HOLD', last: 30, day_change_pct: 0,
    proposal_allowed: false },
]

globalThis.__apiFixture = (url) => {
  if (url.includes('watch-intelligence')) {
    return { data: { cards, summary: {}, counts: {}, data_quality: { status: 'OK' } }, loading: false, error: null }
  }
  if (url.includes('watch-filters')) {
    return { data: { views: {}, trade_ai_states: ['DATA_UNAVAILABLE', 'DETERMINISTIC_FAIL', 'READY'] }, loading: false, error: null }
  }
  if (url.includes('data-broker')) return { data: { projections: {} }, loading: false, error: null }
  return { data: null, loading: false, error: null }
}

const { default: Page } = await import(compile(join(app, 'src/pages/WatchIntelligenceUnified.tsx')))

const cases = []
function check(surface, name, ok, detail) { cases.push({ surface, name, passed: !!ok, detail: ok ? '' : detail }) }

for (const [surface, entry] of [['table', '/watch?tab=intelligence&view=top_ideas&layout=table'],
                                ['cards', '/watch?tab=intelligence&view=top_ideas']]) {
  globalThis.__entry = entry
  let markup = ''
  const t0 = Date.now()
  try { markup = html(React.createElement(Page)) } catch (e) {
    check(surface, 'renders', false, `render threw: ${e.name}: ${e.message}`); continue
  }
  check(surface, 'renders', true)
  cases.push({ surface, name: 'render cost', passed: true, detail: `${Date.now() - t0} ms (server render, fixtures)` })
  const t = text(markup)
  const RAW = ['DATA_UNAVAILABLE', 'DETERMINISTIC_FAIL', 'ANSWERED_PENDING_CIO', 'SOME_NEW_CODE']
  for (const raw of RAW) {
    const i = t.indexOf(raw)
    check(surface, `no raw code ${raw} in the operator's text`, i < 0, i < 0 ? '' : `…${t.slice(Math.max(0, i - 140), i + 140)}…`)
  }
  for (const label of surface === 'table' ? ['Data unavailable', 'Failed its checks', 'Answer ready'] : ['Data unavailable', 'Failed its checks']) {
    check(surface, `plain label "${label}" is rendered`, t.includes(label), t.slice(0, 400))
  }
  check(surface, 'an unknown code is humanised, not dropped', t.includes('Some new code'), t.slice(0, 400))
  // Recoverable means: the element that shows the label carries the code, not merely that the code appears somewhere.
  const stateSite = surface === 'table'
    ? /<td[^>]*title="DATA_UNAVAILABLE"[^>]*>Data unavailable/
    : /<span[^>]*title="DATA_UNAVAILABLE"[^>]*>Trade AI: Data unavailable/
  check(surface, 'the element showing the state carries the raw code in its title', stateSite.test(markup), 'label rendered without its code in a title')
  if (surface === 'table') {
    check(surface, 'the CIO status cell carries its code', /<td[^>]*title="ANSWERED_PENDING_CIO"[^>]*>Answer ready/.test(markup), 'no title on the CIO status cell')
  }
}

const out = { schema: 'WatchlistLabelsView@v1', cases, passed: cases.filter(c => c.passed).length, failed: cases.filter(c => !c.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) for (const c of cases.filter(x => !x.passed)) console.log(`FAIL ${c.surface}/${c.name}: ${c.detail}`)
process.exitCode = out.failed ? 1 : 0

// node src/lib/watchpoolPlain.view.test.mjs
//
// FQ-080 / FQ-132 (lead ruling 2026-11-05): the watchpool list must read in operator words on the RENDERED
// surface. This test renders the real page component with a fixture payload and asserts the visible text of
// the middle cell — the defect it exists to catch was a source-text test passing while the rendered column
// still printed the engine key `{r.strategy_id}` verbatim.
//
// Mutation proof (recorded in the PR body): restore `{r.strategy_id}` in that cell and this file goes red.
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

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  // The page fetches through useApi; the fixture replaces it so the render is deterministic and offline.
  let source = readFileSync(path, 'utf8').replace(/import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (url: any): any => (globalThis as any).__watchpoolFixture(url)')
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

const { default: WatchpoolHub } = await import(compile(join(app, 'src/pages/WatchpoolHub.tsx')))

const ROW = (over = {}) => ({
  id: 1, symbol: 'ABCD', strategy_id: 'core_growth_compounder', bucket: 'MULTI_DAY',
  current_status: 'ACTIVE', origin_system: 'screener', ...over,
})

function render(rows, directives = null) {
  globalThis.__watchpoolFixture = (url) => {
    const u = String(url)
    if (u.includes('/api/v2/watchpool')) return { data: { rows, count: rows.length }, error: null, loading: false, refetch() {} }
    if (u.includes('/api/v2/watch-directives') && directives) return { data: directives, error: null, loading: false, refetch() {} }
    return { data: null, error: null, loading: false, refetch() {} }
  }
  return renderToStaticMarkup(React.createElement(MemoryRouter, null,
    React.createElement(WatchpoolHub, { onDrill() {}, embedded: true })))
}

/** The visible text of the middle cell, never the attributes (the raw id deliberately lives in the title). */
function strategyCell(html) {
  const m = /<span[^>]*data-pool-strategy[^>]*>([\s\S]*?)<\/span>/.exec(html)
  if (!m) return null
  return m[1].replace(/<[^>]*>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim()
}

let pass = 0, fail = 0
const check = (name, fn) => {
  try { fn(); pass++; console.log(`  [PASS] ${name}`) } catch (e) { fail++; console.log(`  [FAIL] ${name}: ${e.message}`) }
}

const html = render([ROW()])
const cell = strategyCell(html)

check('the pool row renders at all (the fixture reaches the list, not the empty state)', () => {
  assert.match(html, /data-pool-row/)
  assert.doesNotMatch(html, /Watchpool empty|Watchpool unavailable/)
})
check('the middle cell reads the strategy in operator words', () => {
  assert.equal(cell, 'Core Growth Compounder', `cell read ${JSON.stringify(cell)}`)
})
check('the engine key never appears as visible row text', () => {
  const withoutTitles = html.replace(/\stitle="[^"]*"/g, '')
  assert.doesNotMatch(withoutTitles, /core_growth_compounder/)
})
check('the raw id is still recoverable, in the cell title', () => {
  assert.match(html, /title="strategy core_growth_compounder"/)
})

check('an already-human strategy label is not mangled', () => {
  const h = render([ROW({ strategy_id: 'Momentum + Pullback' })])
  assert.equal(strategyCell(h), 'Momentum + Pullback')
})
check('a missing strategy says so instead of printing nothing or a key', () => {
  const h = render([ROW({ strategy_id: null })])
  assert.equal(strategyCell(h), 'Unnamed strategy')
})
check('acronyms survive the human form (pullback_macd → Pullback MACD)', () => {
  const h = render([ROW({ strategy_id: 'pullback_macd' })])
  assert.equal(strategyCell(h), 'Pullback MACD')
})

// FQ-080's other half: the desk filter and loop health also read in operator words on the rendered page.
check('desk filters are operator words, not engine keys', () => {
  assert.match(html, />All desks</)
  assert.match(html, />CIO desk</)
  assert.doesNotMatch(html.replace(/\stitle="[^"]*"/g, ''), />\s*cio\s*</)
})

// FQ-080 P3 (cc-deepseek-8 at head f84a04507): one field, one reading. The expanded directive hits used to print
// `h.surfaced_by` raw while the queue chip above it rendered deskLabel(h.surfaced_by) — the same value in two
// forms on one page. This asserts the RENDERED chip inside the expanded hits.
check('the expanded directive hit uses the same desk words as the queue chip', () => {
  const directives = {
    directives: [{ id: 7, kind: 'ticker', label: 'Synthetic directive', spec: {}, created_at: '2026-11-05T00:00:00Z',
      ttl_days: 5, expires_in_days: 4, trade_ai_enabled: true, hermes_enabled: false }],
    recent_hits: [{ symbol: 'ABCD', directive_id: 7, surfaced_by: 'cio', promotion_status: 'STAGED_FOR_REVIEW' }],
    directive_count: 1,
  }
  const h = render([ROW()], directives)
  const chips = [...h.matchAll(/<span[^>]*>([\s\S]*?)<\/span>/g)].map(m => m[1].replace(/<[^>]*>/g, '').trim())
  assert.ok(chips.includes('CIO desk'), `expanded hit chip did not read the desk word; chips=${JSON.stringify(chips.filter(Boolean).slice(0, 12))}`)
  assert.ok(!h.replace(/\stitle="[^"]*"/g, '').includes('>cio<'), 'a raw cio chip is still rendered somewhere on the page')
})

console.log(`watchpoolPlain.view: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

/**
 * PR #2622 review P2622-R1 (cx-openai-4, whole-head BLOCK at 242358737):
 *
 * At 390 px the compact Wire row was `grid-template-columns: 28px 1fr auto auto`; the category and
 * freshness badges took the last two auto columns, leaving the headline ~28.7 px (50.7 px at 412), so
 * every title rendered as "S…". The fix gives the headline the row and moves the two badges into one
 * meta group on a second line at phone widths.
 *
 * This test renders the real compact ArticleCard and asserts the structure the phone CSS depends on,
 * and that the phone rule exists. It fails on the pre-fix tree (no classes, no rule). The reviewer's
 * browser measurement remains the width proof (276 px at 390, 298 px at 412).
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
    .replace(/^import\s+['"][^'"]+\.css['"]\s*$/gm, '')
    .replace(/import \{ useApi \} from ['"][^'"]+['"]/,
      'const useApi = (..._args: any[]): any => (globalThis as any).__researchFixture')
  let js = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (existsSync(target) && require('node:fs').statSync(target).isDirectory()) target = ['index.ts', 'index.tsx', 'index.js'].map(s => resolve(target, s)).find(existsSync)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map(s => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

globalThis.__researchFixture = { data: null, error: null, loading: false }
const { ArticleCard, SecondaryFiltersShell } = await import(compile(join(app, 'src/pages/ResearchIntelligenceHub.tsx')))

const item = {
  id: 'fixture-1', symbol: 'SCHD', title: 'A long research headline that must stay readable on a phone',
  lede: 'The standfirst also needs room to be read.', starred: false, primary_category: 'macro_sector',
  categories: ['macro_sector'], freshness_tier: 'fresh', freshness_label: 'Fresh',
  created_at: new Date().toISOString(), executive_summary: [], key_takeaways: [],
}
const html = renderToStaticMarkup(React.createElement(ArticleCard, {
  item, catMeta: { macro_sector: { label: 'Macro & sectors' } }, view: 'compact', onOpen() {}, onFeedback() {}, onStage: async () => {}, onThemeClick() {},
}))

const results = []
function check(name, fn) {
  try { fn(); results.push({ name, passed: true }) }
  catch (e) { results.push({ name, passed: false, assertion: e.message.split('\n')[0] }) }
}

check('the compact row carries the phone layout class', () => assert.match(html, /class="ri-wire-row"/))
check('the headline and standfirst are individually addressable', () => {
  assert.match(html, /class="ri-wire-headline"/)
  assert.match(html, /class="ri-wire-lede"/)
})
check('category and freshness share ONE meta group, after the title', () => {
  assert.match(html, /class="ri-wire-meta"/)
  assert.ok(html.indexOf('ri-wire-title') < html.indexOf('ri-wire-meta'), 'meta follows the title block')
  // both badges live inside that one group, not in their own grid columns
  const meta = html.slice(html.indexOf('ri-wire-meta'))
  assert.match(meta, /Macro &amp; sectors/)
  assert.match(meta, /Fresh/)
  assert.equal((html.match(/ri-wire-meta/g) || []).length, 1, 'exactly one meta group per row')
})
check('the full headline is rendered (not truncated server-side)', () => {
  assert.match(html, /A long research headline that must stay readable on a phone/)
})
check('the phone rule gives the headline the row and wraps it', () => {
  const css = readFileSync(join(app, 'src/pages/W9Mobile.css'), 'utf8')
  assert.match(css, /@media \(max-width: 820px\)[\s\S]*?\.w9-page \.ri-wire-row\s*\{[^}]*grid-template-columns:\s*28px minmax\(0, 1fr\)/)
  assert.match(css, /\.ri-wire-headline[\s\S]{0,200}?white-space:\s*normal/)
})
// review P2622-R2: a two-line clamp only clips with hidden overflow. `overflow: visible` lets the
// third and later lines paint over the badges line and the next row. The browser regression is
// e2e/fq058-wire-clamp.spec.ts; this pins the rule text so a future edit cannot silently un-clip it.
check('the phone clamp clips its overflow, so two lines cannot paint over the row', () => {
  const css = readFileSync(join(app, 'src/pages/W9Mobile.css'), 'utf8')
  const rule = css.slice(css.indexOf('.w9-page .ri-wire-headline'))
  const body = rule.slice(0, rule.indexOf('}'))
  assert.match(body, /overflow:\s*hidden\s*!important/, body)
  assert.match(body, /-webkit-line-clamp:\s*2/, body)
  assert.doesNotMatch(body, /overflow:\s*visible/)
})
// P2622 scope boundary (lead, 2026-11-04): this PR is the phone wire row's layout and the clamp paint.
// The advisory surfaces' MISSING-* state taxonomy ("MISSING MARKET" beside a known price) is a different
// component (lib/advisoryReason.ts via reentryDecisionScorecard), owned by #2637. Prove the boundary
// instead of asserting it: this page carries none of that vocabulary, and the row's own reason is its
// category label and freshness label, both rendered.
check('the page carries only its own reason vocabulary, not the advisory MISSING-* taxonomy', () => {
  const page = readFileSync(join(app, 'src/pages/ResearchIntelligenceHub.tsx'), 'utf8')
  const lib = readFileSync(join(app, 'src/lib/researchPhone.ts'), 'utf8')
  for (const src of [page, lib]) {
    assert.doesNotMatch(src, /advisoryReason|reentryDecisionScorecard/, 'the research page imports the advisory taxonomy')
    assert.doesNotMatch(src, /MISSING[ _-](MARKET|PLAN)/, 'the research page names an advisory MISSING-* state')
  }
  assert.doesNotMatch(html, /MISSING[ _-](MARKET|PLAN)/, 'the compact row rendered an advisory MISSING-* state')
  // and the reasons it does carry are present, in words: the category and the freshness label
  assert.match(html, /Macro &amp; sectors/, 'the row does not name its category')
  assert.match(html, /Fresh/, 'the row does not name its freshness')
})
// review P2622 P3: an unwrapped <details> on desktop gets a browser-inserted summary and can collapse
// every filter with one click. Desktop must be a plain container; only a phone folds behind a summary.
check('desktop secondary filters cannot collapse; a phone folds behind one summary', () => {
  const shell = (phone) => renderToStaticMarkup(React.createElement(SecondaryFiltersShell, {
    phone, open: false, summary: 'Filters',
  }, React.createElement('span', null, 'chips')))
  const desktop = shell(false)
  const phone = shell(true)
  assert.match(desktop, /<div data-testid="ri-secondary-filters"/)
  assert.doesNotMatch(desktop, /<details/, 'desktop must not be a collapsible details element')
  assert.match(phone, /<details/)
  assert.match(phone, /<summary/)
  assert.match(phone, /Filters/)
})

const out = { results, passed: results.filter(x => x.passed).length, failed: results.filter(x => !x.passed).length }
console.log(JSON.stringify(out, null, 2))
if (out.failed) process.exit(1)

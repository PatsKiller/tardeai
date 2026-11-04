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
const { ArticleCard } = await import(compile(join(app, 'src/pages/ResearchIntelligenceHub.tsx')))

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

const out = { results, passed: results.filter(x => x.passed).length, failed: results.filter(x => !x.passed).length }
console.log(JSON.stringify(out, null, 2))
if (out.failed) process.exit(1)

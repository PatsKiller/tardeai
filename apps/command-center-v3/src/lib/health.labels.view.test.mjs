// Rendering test for BOARD row 38 (/health): raw producer identifiers must read as people/lanes, not as keys.
//
// The audit (2026-11-04) found internal identifiers on /health: `health_agent` / `repair_agent` rendered in
// monospace as WHO, and an unmapped finding category printed raw. This test RENDERS the real page and asserts the
// operator's text, with the raw value recoverable in a title. It fails before the fix and after a regression.
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

globalThis.window = globalThis.window ?? {
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }),
  innerWidth: 1400, scrollTo() {}, location: { search: '' },
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
      if (list.includes('useApi')) stubs.push('const useApi = (...a: any[]): any => (globalThis as any).__apiFixture(String(a[0] ?? ""), a[2])')
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
    if (target && !existsSync(target)) target = undefined
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    if (existsSync(target) && require('node:fs').statSync(target).isDirectory()) {
      target = ['.ts', '.tsx', '.js'].map(s => join(target, 'index' + s)).find(existsSync)
      if (!target) throw new Error(`Missing fixture dependency index for ${spec}`)
    }
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const findings = [
  { category: 'pipeline_freshness', type: 'ticker_snapshots_stale', severity: 'warning', message: 'Ticker snapshots are stale.',
    why: 'Producer stopped.', recommended_action: 'Re-run the producer.', actionable: false, action_type: 'monitor',
    detected_by: 'health_agent', detected_at: '2026-11-04T10:00:00Z',
    remediation: { status: 'verified', by: 'repair_agent', at: '2026-11-04T10:30:00Z' } },
  { category: 'some_new_category', type: 'x', severity: 'info', message: 'A new category shipped.',
    why: '—', recommended_action: '—', actionable: false, action_type: 'monitor', detected_by: 'some_new_producer' },
]
globalThis.__apiFixture = (url) => {
  if (url.includes('/api/v2/health/dispatches') || url.includes('/api/v2/health/coders') || url.includes('/api/v2/health/history')) return { data: null, loading: false, error: null }
  if (url.includes('/api/v2/health')) return { data: { overall_score: 75, status: 'degraded', mode: 'advisory',
    captured_at: '2026-11-04T10:00:00Z', category_scores: { pipeline_freshness: 60 }, trends: [], findings }, loading: false, error: null }
  return { data: null, loading: false, error: null }
}

const { default: Page } = await import(compile(join(app, 'src/pages/HealthHub.tsx')))
const markup = renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/health?tab=overview'] }, React.createElement(Page)))
const text = markup.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/&quot;/g, '"')
  .replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/→/g, '→').replace(/\s+/g, ' ').trim()

const cases = []
const check = (name, ok, detail) => cases.push({ name, passed: !!ok, detail: ok ? '' : detail })

check('renders', text.length > 0, 'nothing rendered')
for (const raw of ['health_agent', 'repair_agent', 'some_new_producer', 'some_new_category']) {
  check(`no raw identifier ${raw} in the text`, !text.includes(raw), text.slice(0, 400))
}
for (const label of ['Health agent', 'Repair agent', 'Some new producer', 'Some new category']) {
  check(`plain label "${label}" is rendered`, text.includes(label), text.slice(0, 400))
}
check('the WHO row carries the raw pair in its title', /title="health_agent → repair_agent"[^>]*>Health agent → Repair agent/.test(markup), 'title missing on the WHO row')
check('the category keeps its raw key in a title', /title="some_new_category"[^>]*>Some new category/.test(markup), 'category title missing')

const out = { schema: 'HealthLabelsView@v1', cases, passed: cases.filter(c => c.passed).length, failed: cases.filter(c => !c.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) for (const c of cases.filter(x => !x.passed)) console.log(`FAIL ${c.name}: ${c.detail}`)
process.exitCode = out.failed ? 1 : 0

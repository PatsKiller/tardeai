// Rendering test for BOARD row 38 (/retirement): a metric with no value must say so, and a real 0 is not "missing".
//
// The audit (2026-11-04) found an unexplained em-dash on /retirement. It lives in the Metric tile, which rendered
// `value || '—'`: unknown, zero and empty all became one dash, and a 0% yield read as "no data". This test RENDERS the
// real page and asserts both directions — missing says "not reported", zero renders 0.
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
  innerWidth: 1400, scrollTo() {},
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
    if (require('node:fs').statSync(target).isDirectory()) {
      target = ['.ts', '.tsx', '.js'].map(s => join(target, 'index' + s)).find(existsSync)
      if (!target) throw new Error(`Missing fixture index for ${spec}`)
    }
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

let ceiling = null
globalThis.__apiFixture = (url) => {
  if (url.includes('/api/v2/retirement/planning-research')) return { data: { items: [] }, loading: false, error: null }
  if (url.includes('/api/v2/retirement')) {
    return { data: {
      current_age: 60, as_of: '2026-11-04T10:00:00Z',
      accounts: { total: 1000, roth: 400, traditional: 400, taxable: 200 },
      golden_window: { start_year: 2026, end_year: 2030, annual_conversion: 10000, bracket_ceiling: ceiling },
      dividend_income: { annual_total: 0, monthly_avg: 0 },
    }, loading: false, error: null }
  }
  return { data: null, loading: false, error: null }
}

const { default: Page } = await import(compile(join(app, 'src/pages/RetirementHub.tsx')))
const strip = (m) => m.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/&quot;/g, '"')
  .replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/\s+/g, ' ').trim()
const render = () => strip(renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/retirement'] }, React.createElement(Page))))

const cases = []
const check = (name, ok, detail) => cases.push({ name, passed: !!ok, detail: ok ? '' : detail })

ceiling = null
let t = render()
check('a missing value says "not reported"', /Bracket ceiling not reported/.test(t), t.slice(0, 300))
check('a missing value does not render a bare em-dash', !/Bracket ceiling —/.test(t), t.slice(0, 300))

ceiling = 0
t = render()
check('a real zero renders as 0', /Bracket ceiling 0/.test(t), t.slice(0, 300))
check('a real zero is not called missing', !/Bracket ceiling not reported/.test(t), t.slice(0, 300))

const out = { schema: 'RetirementMetricView@v1', cases, passed: cases.filter(c => c.passed).length, failed: cases.filter(c => !c.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) for (const c of cases.filter(x => !x.passed)) console.log(`FAIL ${c.name}: ${c.detail}`)
process.exitCode = out.failed ? 1 : 0

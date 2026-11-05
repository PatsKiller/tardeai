// Rendering test for PR 2630 F1/F2 (/intelligence): the new Decision-implications row must state SOURCE truth.
//
// Reviewer cx-openai-5 proved the caller seam, not the pure helper, was wrong: the page normalized an absent
// source confidence to 0.65, rescaled 62 to 62% and clamped -0.2 to 0, then labelled that "confidence"; and it
// clamped a future timestamp to zero, then called it "just now". This test renders the REAL page (server render;
// only the useApi transport is replaced with a synthetic /api/v2/command ABI) and asserts the actual row text,
// so a pure model fixture cannot hide the caller defect again.
//
// Fails before the fix: absent -> "65% confidence", 62 -> "62% confidence", -0.2 -> "0% confidence",
// future -> "just now". Passes after it, and the valid 0 / 1 / 0.62 and past / missing controls stay put.
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
// The server renderer emits one `useLayoutEffect does nothing on the server` warning per component — expected
// in SSR, and each stack line embeds a multi-megabyte `data:` module URL. Drop exactly that warning.
const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const { MemoryRouter } = require('react-router-dom')

// A server render has no window; the browser this page runs in does, so the harness supplies the minimal shape.
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

const Page = (await import(compile(join(app, 'src/components/CentralIntelligencePages.tsx')))).default

// The reviewer's fixed caller clock (2026-11-05T17:00:00Z), so "1 h old" and the future case are exact.
const FIXED_NOW = Date.parse('2026-11-05T17:00:00Z')
Date.now = () => FIXED_NOW
globalThis.fetch = () => { throw new Error('this rendering test refuses network calls') }

function renderWithTopNews(raw) {
  globalThis.__apiFixture = (url) => {
    if (url.includes('/api/v2/command')) return { data: { top_news: [raw] }, loading: false, error: null }
    return { data: null, loading: false, error: null }
  }
  return renderToStaticMarkup(React.createElement(MemoryRouter, null,
    React.createElement(Page, { mode: 'command', onDrill() {} })))
}

const uncertaintyTexts = (markup) =>
  [...markup.matchAll(/data-testid="intel-implication-uncertainty"[^>]*>([^<]*)</g)].map(x => x[1])
const conclusions = (markup) =>
  [...markup.matchAll(/data-testid="intel-implication-conclusion"[^>]*>([^<]*)</g)].map(x => x[1])

const cases = []
function check(surface, name, ok, detail, observed) {
  cases.push({ surface, name, passed: !!ok, detail: ok ? '' : detail, observed })
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${surface} / ${name} → ${JSON.stringify(observed)}${ok ? '' : ` :: ${detail}`}`)
}

const BASE = { symbol: 'SYN', title: 'Synthetic demand is improving. Margins held.', updated_at: '2026-11-05T16:00:00Z' }
const row = (extra = {}) => ({ ...BASE, ...extra })

// ---- F1: confidence is the source's recorded value, never a browser fallback or unit guess ---------------------
// The source confidence column is the exact fixture from the review; the row text is the required distinction.
const CONFIDENCE = [
  ['absent', undefined, 'confidence not recorded · 1 h old'],
  ['62 (out of the declared 0..1 domain)', 62, 'confidence not recorded · 1 h old'],
  ['-0.2 (out of the declared 0..1 domain)', -0.2, 'confidence not recorded · 1 h old'],
  ['0 (valid positive control)', 0, '0% confidence · 1 h old'],
  ['1 (valid positive control)', 1, '100% confidence · 1 h old'],
  ['0.62 (valid positive control)', 0.62, '62% confidence · 1 h old'],
]
for (const [name, value, expected] of CONFIDENCE) {
  const markup = renderWithTopNews(value === undefined ? row() : row({ confidence: value }))
  const got = uncertaintyTexts(markup)
  check('confidence', name, got.length === 1 && got[0] === expected, `got ${JSON.stringify(got)}; expected ${JSON.stringify([expected])}`, got.join(' | '))
  check('confidence', `${name}: rendered by the real page's row`, conclusions(markup).length === 1 && conclusions(markup)[0] === 'SYN: Synthetic demand is improving.', JSON.stringify(conclusions(markup)), conclusions(markup).join(' | '))
}

// ---- F2: a future timestamp is a clock mismatch, never "just now" ----------------------------------------------
const TIMES = [
  ['future hour (source clock ahead)', '2026-11-05T18:00:00Z', '62% confidence · source timestamp is in the future'],
  ['missing timestamp', undefined, '62% confidence · age not recorded'],
  ['valid past (positive control)', '2026-11-05T16:00:00Z', '62% confidence · 1 h old'],
]
for (const [name, when, expected] of TIMES) {
  const raw = row({ confidence: 0.62 })
  if (when === undefined) delete raw.updated_at
  else raw.updated_at = when
  const markup = renderWithTopNews(raw)
  const got = uncertaintyTexts(markup)
  check('time', name, got.length === 1 && got[0] === expected, `got ${JSON.stringify(got)}; expected ${JSON.stringify([expected])}`, got.join(' | '))
  check('time', `${name}: never says fresh`, !got.some(t => /just now|fresh/i.test(t)), JSON.stringify(got), got.join(' | '))
}

const out = {
  schema: 'IntelImplicationPageView@v1',
  fixed_now: new Date(FIXED_NOW).toISOString(),
  cases,
  passed: cases.filter(c => c.passed).length,
  failed: cases.filter(c => !c.passed).length,
}
console.log(JSON.stringify(out, null, 1))
if (out.failed) for (const c of cases.filter(x => !x.passed)) console.log(`FAIL ${c.surface}/${c.name}: ${c.detail}`)
process.exitCode = out.failed ? 1 : 0

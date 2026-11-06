// FQ-030 (rendering view test): the collapse controls are the only way out of the collapsed state, so they are
// touch targets and must clear the house 44px minimum — this page's whole finding is phone use.
//
// This test RENDERS the real page and asserts the style React actually emits. It replaces a source-regex version:
// that one read ConsumptionHub.tsx and looked for `minHeight: 44` near each `aria-expanded`, so replacing the real
// style with a comment of the same words kept it green (cc-deepseek-3 BLOCK on PR 2676, 2026-11-05). A guard that
// cannot be made red by removing the behaviour is not a guard. Runs in the CC-v3 build:
//   node src/lib/consumptionPresentation.view.test.mjs
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
// The server renderer emits one `useLayoutEffect does nothing on the server` warning per component — expected in SSR,
// and each stack line embeds a multi-megabyte `data:` module URL. Drop exactly that warning; everything else prints.
const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}
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
    if (existsSync(target) && statSync(target).isDirectory()) {
      target = ['.ts', '.tsx', '.js'].map(s => join(target, 'index' + s)).find(existsSync)
      if (!target) throw new Error(`Missing fixture dependency index for ${spec}`)
    }
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

// Synthetic payloads: enough rows that BOTH preview controls render (15 processes > 12 desk / 6 phone,
// 12 calls > 10 desk / 5 phone) and at least one call row carries the "Technical detail" disclosure.
const empty = { loading: false, error: null, refetch: () => {} }
const PROCESSES = Array.from({ length: 15 }, (_, i) => ({
  process_id: `synthetic_proc_${i}`, process_name: `Synthetic process ${i}`, mode: i % 2 ? 'manual' : 'automated',
  calls_30d: i, relative_units_30d: i * 1.5, last_used: '2026-11-04T10:00:00Z',
}))
const LOGS = Array.from({ length: 12 }, (_, i) => ({
  id: i, created_at: '2026-11-04T10:00:00Z', model_lane: i % 3 === 0 ? 'chatgpt' : 'grok',
  process_name: `Synthetic process ${i % 15}`, task_summary: `Synthetic task ${i}`, trigger_mode: 'manual',
  relative_units: 1.5, success: i % 4 !== 0,
}))
globalThis.__apiFixture = (url) => {
  if (url.includes('/api/v2/consumption/overview')) return { ...empty, data: { overview: null } }
  if (url.includes('/api/v2/consumption/processes')) return { ...empty, data: { processes: PROCESSES } }
  if (url.includes('/api/v2/consumption/lane-registry')) return { ...empty, data: { processes: {}, policy_labels: {} } }
  if (url.includes('/api/v2/consumption/logs')) return globalThis.__logsFixture ?? { ...empty, data: { logs: LOGS } }
  return { ...empty, data: null }
}

const { default: Page } = await import(compile(join(app, 'src/pages/ConsumptionHub.tsx')))
const MIN_44 = /min-height:\s*44px/
const cases = []
const check = (name, ok, detail) => cases.push({ name, passed: !!ok, detail: ok ? '' : detail })

function renderAs(phone) {
  // `usePhone()` reads matchMedia during render, so the viewport is flipped per render, not per module load.
  globalThis.window.matchMedia = () => ({
    matches: phone, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
  })
  return renderToStaticMarkup(
    React.createElement(MemoryRouter, { initialEntries: ['/consumption'] }, React.createElement(Page)),
  )
}

for (const [mode, phone] of [['desk', false], ['phone', true]]) {
  const markup = renderAs(phone)
  // React emits the controls with the attributes it was given; the style is what the browser will apply. The page's
  // own two preview controls are identified by their rendered label; child components carry their own disclosures.
  const buttons = [...markup.matchAll(/<button\b[^>]*\baria-expanded="(?:true|false)"[^>]*>[\s\S]*?<\/button>/g)].map(m => m[0])
  const preview = buttons.filter(b => /Show all — \d+ more (process|call)/.test(b))
  const summaries = [...markup.matchAll(/<summary\b[^>]*>/g)].map(m => m[0])
  const visibleCalls = phone ? 5 : 10  // PHONE_LOG_PREVIEW / DESK_LOG_PREVIEW
  const label = (name) => `[${mode}] ${name}`

  check(label('the page renders'), markup.length > 0, 'nothing rendered')
  check(label('both preview controls render'), preview.length === 2, `got ${preview.length} of ${buttons.length} disclosure buttons`)
  check(label('every preview control is a 44px touch target'), preview.every(b => MIN_44.test(b)),
    preview.filter(b => !MIN_44.test(b)).join(' | '))
  check(label('every preview control is a real button'), preview.every(b => /type="button"/.test(b)),
    preview.filter(b => !/type="button"/.test(b)).join(' | '))
  check(label('both preview controls are labelled'), /Show all — \d+ more process/.test(markup) && /Show all — \d+ more call/.test(markup),
    markup.slice(0, 300))
  // cx-openai-3, executed at 2e3d9e2be: the page renders 10/5 call rows that EACH carry their own direct "Technical
  // detail" disclosure, plus three Source-clocks Diagnostics disclosures that belong to DeskPage. A global <summary>
  // count therefore overcounts (13/8) and, worse, an unrelated decoy summary could keep a global count right while a
  // row had lost its disclosure. Scope the assertion to the call rows themselves.
  const rows = [...markup.matchAll(/<div\b[^>]*data-testid="consumption-call-row"[^>]*>/g)]
  check(label('the page renders the expected number of call rows'), rows.length === visibleCalls,
    `got ${rows.length}, expected ${visibleCalls}`)
  const segments = markup.split('data-testid="consumption-call-row"').slice(1)
  const perRow = segments.map(seg => {
    const own = [...seg.matchAll(/<summary\b[^>]*>[\s\S]{0,200}?Technical detail/g)].map(m => m[0])
    return own
  })
  check(label('every rendered call row carries its OWN "Technical detail" disclosure'),
    perRow.length === rows.length && perRow.every(own => own.length === 1),
    `rows ${perRow.length}; disclosures per row ${JSON.stringify(perRow.map(o => o.length))}`)
  const ownSummaries = perRow.flat()
  check(label('the detail disclosure is a 44px touch target'), ownSummaries.length > 0 && ownSummaries.every(s => MIN_44.test(s)),
    ownSummaries.filter(s => !MIN_44.test(s)).slice(0, 2).join(' | '))
}

// ── cx-openai-3's CX3-F1: the census must not invent a clean window from an unread source ─────────────
// Rendered through the real page with only the log read changed. The three states the finding named, plus the two
// positive controls that prove the probe is not simply suppressing every result.
const censusOf = (fx) => {
  globalThis.__logsFixture = fx
  const m = renderAs(false)
  globalThis.__logsFixture = undefined
  return m.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
}
const missing = censusOf({ ...empty, data: {} })
check('missing logs do not read as a clean window',
  /Activity is unavailable/.test(missing) && !/No failed calls/.test(missing), missing.slice(0, 220))
const refused = censusOf({ ...empty, data: { ok: false, error: 'Synthetic source refused' } })
check('a refused read says unavailable and names the refusal',
  /Activity is unavailable/.test(refused) && /Synthetic source refused/.test(refused) && !/No failed calls/.test(refused),
  refused.slice(0, 220))
const retained = censusOf({ ...empty, data: { logs: LOGS }, stale: true })
check('retained rows are labelled retained, not current',
  /retained from an earlier read/.test(retained) && /not the current window/.test(retained), retained.slice(0, 260))
const observedEmpty = censusOf({ ...empty, data: { logs: [] } })
check('an OBSERVED empty window still says so (positive control)',
  /No failed calls in the last 0/.test(observedEmpty), observedEmpty.slice(0, 220))
const measured = censusOf({ ...empty, data: { logs: LOGS } })
check('a measured window still counts its failures (positive control)',
  /failed calls?\b/.test(measured) && /in the last 12/.test(measured), measured.slice(0, 260))

const out = { schema: 'ConsumptionView@v1', cases, passed: cases.filter(c => c.passed).length, failed: cases.filter(c => !c.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) for (const c of cases.filter(x => !x.passed)) console.log(`FAIL ${c.name}: ${c.detail}`)
process.exitCode = out.failed ? 1 : 0

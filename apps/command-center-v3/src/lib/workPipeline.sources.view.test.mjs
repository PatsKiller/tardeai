// Row 78 rendering test: the Work pipeline's source strip and its queued ownership must say what the data says.
//
// The operator's complaint (2026-11-04): a frozen "Last successful run", a census that died, and "231 QUEUED with no
// owners". This renders the real panel and asserts: each coordination source shows its own as_of; a failed source says
// which file and when it last succeeded; the queued count is split by who owns it. Fails without the payload wiring.
import { readFileSync, existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
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

// Compiled modules are written to real files, not data: URLs. A data: URL embeds every module it imports, so a
// page-level component's graph is re-encoded once per level: one React "useLayoutEffect does nothing on the server"
// warning then carried a ~1 MB single-line stack into the CI log and the surface-agreement job (which runs the whole
// `npm run build` chain under a 20-minute cap) was cancelled twice at 20m. File modules keep every stack line short.
const memo = new Map()
const moduleDir = mkdtempSync(join(tmpdir(), 'workpipeline-sources-view-'))
process.on('exit', () => { try { rmSync(moduleDir, { recursive: true, force: true }) } catch {} })
let moduleSeq = 0
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
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    if (require('node:fs').statSync(target).isDirectory()) {
      target = ['.ts', '.tsx', '.js'].map(s => join(target, 'index' + s)).find(existsSync)
      if (!target) throw new Error(`Missing fixture index for ${spec}`)
    }
    return `from ${JSON.stringify(compile(target))}`
  })
  const file = join(moduleDir, `module-${moduleSeq++}.mjs`)
  writeFileSync(file, js)
  const url = pathToFileURL(file).href
  memo.set(path, url)
  return url
}

const item = {
  id: 'task-1', kind: 'task', stage: 'queued', rag: 'grey', label: 'Queued',
  cells: [{ stage: 'queued', rag: 'grey', label: 'Queued' }],
  next: { owner: 'agent', text: 'start it' },
  what: { title: 'A queued task' }, who: { kind: 'none', label: 'nobody yet' },
  when: {}, where: { file_count: 0, files: [] }, how: {},
}
const payload = {
  schema: 'WorkPipeline@v1', as_of: '2026-11-04T14:30:00Z',
  summary: { counts: { queued: 231 }, red: 0, amber: 0, needs_me: 0, waiting_for_batch: 0, finished: 0, total: 231,
    queued_by_owner: { operator: 38, agent: 87, nobody: 106 } },
  items: [item],
  sources: {
    census: { refreshed_at: '2026-11-04T14:29:00Z', warning: null, refreshing: false },
    census_age_s: 60, open_prs: 12,
    readers: {
      board: { label: 'Board', ok: true, as_of: '2026-11-04T14:30:00Z' },
      audit_queue: { label: 'Audit fix queue', ok: false, as_of: null, error: 'AUDIT_FIX_QUEUE.json not found',
        last_success_at: '2026-11-04T12:00:00Z' },
    },
  },
}
globalThis.__apiFixture = (url) => (String(url).includes('/coordination/pipeline')
  ? { data: payload, loading: false, error: null, refetch() {} }
  : { data: null, loading: false, error: null })

const { default: Panel } = await import(compile(join(app, 'src/pages/WorkPipelinePanel.tsx')))
// The server renderer warns once per useLayoutEffect in any component it walks; that warning is a property of
// rendering on the server, not of this panel, and its stack is the only reason this test used to log megabytes.
const realError = console.error
console.error = (...args) => { if (String(args[0]).includes('useLayoutEffect does nothing on the server')) return; realError(...args) }
let markup
try {
  markup = renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: ['/coordination?tab=pipeline'] },
    React.createElement(Panel)))
} finally { console.error = realError }
const text = markup.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/&quot;/g, '"')
  .replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/\s+/g, ' ').trim()

const cases = []
const check = (name, ok, detail) => cases.push({ name, passed: !!ok, detail: ok ? '' : detail })

check('the queued count is split by owner', /38 operator-owned/.test(text) && /87 agent-owned/.test(text) && /106 nobody has taken it/.test(text), text.slice(0, 300))
check('a good source shows its own as_of', /Board\s+as of/.test(text), text.slice(0, 300))
check('a failed source names the file', /Audit fix queue\s+unavailable — AUDIT_FIX_QUEUE\.json not found/.test(text), text.slice(0, 300))
check('a failed source says when it last succeeded', /last succeeded/.test(text), text.slice(0, 300))
check('a failed source never renders as a fresh clock', !/Audit fix queue\s+as of/.test(text), text.slice(0, 300))

const out = { schema: 'WorkPipelineSourcesView@v1', cases, passed: cases.filter(c => c.passed).length, failed: cases.filter(c => !c.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) for (const c of cases.filter(x => !x.passed)) console.log(`FAIL ${c.name}: ${c.detail}`)
process.exitCode = out.failed ? 1 : 0

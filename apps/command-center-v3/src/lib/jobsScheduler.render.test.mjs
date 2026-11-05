// node --experimental-strip-types src/lib/jobsScheduler.render.test.mjs
// FQ-048 (cx-openai-3 F1/F2): the exact scheduler must be reachable without hover — a <details> disclosure
// that a phone tap and a keyboard can open — and this test must RENDER the real component, not grep it.
// It fails if the scheduler cell is removed (no plain words, no disclosure), and it fails on the old
// title-only head (no <details> carrying the exact value).
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { MemoryRouter } = require('react-router-dom')

globalThis.window = {
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
}

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8')
  source = source.replace(/^import\s+['"][^'"]+\.css['"]\s*$/gm, '')
  source = source.replace(/import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (path: string): any => (globalThis as any).__jobsFixture(path)')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.split('\n').map(line => {
    if (!/^\s*(import|export)\b/.test(line)) return line
    return line.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
      if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
      let target = resolve(dirname(path), spec)
      const isFile = (p) => existsSync(p) && statSync(p).isFile()
      if (!isFile(target)) target = ['.ts', '.tsx', '.js', '/index.ts', '/index.tsx'].map(s => target + s).find(isFile)
      if (!target) throw new Error(`Missing fixture dependency ${spec}`)
      return `from ${JSON.stringify(compile(target))}`
    })
  }).join('\n')
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

const DATA = {
  rows: [], summary: { total: 1, due_today: 1, succeeded: 1, failed: 0, missed: 0, paused: 0, retired: 0 },
  total: 1, has_more: false, as_of: '2026-11-04T15:00:00Z', coverage_gaps: [],
  monitor: { status: 'RUNNING', cause: null, notification: null },
}
const ROW = {
  lane_id: 'lane-1', job: 'Indicator cache refresh', scheduler: 'systemd', state: 'ACTIVE', result: 'succeeded',
  last_run_at: '2026-11-04T14:00:00Z', last_success_at: '2026-11-04T14:00:00Z',
  next_due_at: '2026-11-04T15:00:00Z', due_today: true, missed_fires: 0, market_hours_only: false,
  cause: 'ran on schedule',
}
globalThis.__jobsFixture = (path) => {
  DATA.rows = [ROW]
  if (String(path).includes('/api/v2/jobs-health') && String(path).includes('job=lane-1')) {
    return { data: DATA, loading: false, error: null, refetch: () => {} }
  }
  if (String(path).includes('/api/v2/jobs-health')) {
    return { data: DATA, loading: false, error: null, refetch: () => {} }
  }
  return { data: null, loading: false, error: null, refetch: () => {} }
}

const { default: JobsHealth } = await import(compile(join(app, 'src/components/JobsHealth.tsx')))
const html = renderToStaticMarkup(
  React.createElement(MemoryRouter, null, React.createElement(JobsHealth, {})),
)

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

// 1. The plain label renders.
check(/Background service on this machine/.test(html), 'the plain scheduler words are not rendered')
// 2. A real disclosure carries the exact value — not a title attribute.
const details = html.match(/<details[^>]*data-testid="jobs-scheduler-technical"[\s\S]*?<\/details>/)
check(!!details, 'no <details> disclosure for the exact scheduler (a hover title is not a phone control)')
check(!!details && /Scheduler: systemd/.test(details[0]), 'the disclosure does not contain the exact scheduler value')
check(!!details && /<summary/.test(details[0]), 'the disclosure has no focusable <summary> to open it with a keyboard or tap')
// 3. The old title-only carrier must not be the sole path: the exact value appears inside the disclosure.
check(!/title="Scheduler: systemd"/.test(html) || !!details, 'the scheduler detail is still only a hover title')

if (failed) { console.error(`jobsScheduler.render: ${failed} failure(s)`); process.exit(1) }
console.log('jobsScheduler.render: ok')

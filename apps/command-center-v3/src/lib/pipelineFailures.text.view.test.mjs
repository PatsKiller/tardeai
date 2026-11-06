// FQ-065 — /system "Recent pipeline failures" reads as task + consequence; identifiers and parser text are in details.
//
// Red-first: each control fails against the pre-fix panel (which printed the script id, the word "zombie", the
// table/status vocabulary and the raw parser error on the reading line) and passes after. The reading text is the
// markup with every <details> block and every attribute removed — the rest is what an operator sees.
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
  let source = readFileSync(path, 'utf8').replace(
    /import \{ useApi \} from ['"][^'"]+['"]/,
    'const useApi = (..._args: any[]): any => (globalThis as any).__pipelineFixture',
  )
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.replace(/from ["']([^"']+)["']/g, (whole, spec) => {
    if (!spec.startsWith('.')) return `from ${JSON.stringify(pathToFileURL(require.resolve(spec)).href)}`
    let target = resolve(dirname(path), spec)
    if (!existsSync(target)) target = ['.ts', '.tsx', '.js'].map((s) => target + s).find(existsSync)
    if (!target) throw new Error(`Missing fixture dependency ${spec}`)
    return `from ${JSON.stringify(compile(target))}`
  })
  const url = `data:text/javascript;base64,${Buffer.from(js).toString('base64')}`
  memo.set(path, url)
  return url
}

function readingText(markup) {
  return markup
    .replace(/<details[\s\S]*?<\/details>/g, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

// The live shapes, 2026-11-04 (release 105df180e), including the raw parser text and the zombie rows.
const live = {
  status: 'OK',
  window_hours: 24,
  pipelines: [
    { pipeline: 'process_watchlist_agent_jobs', failed: 6, last_failed_at: '2026-11-04T06:15:00Z', last_error: 'terminated by SIGTERM (killed by a supervisor before the run could close)', zombie_cleared: null },
    { pipeline: 'rag_indexer', failed: 2, last_failed_at: '2026-11-04T02:14:00Z', last_error: null, zombie_cleared: 2 },
    { pipeline: 'social_ingest', failed: 1, last_failed_at: '2026-11-03T10:30:00Z', last_error: 'Expecting value: line 1 column 1 (char 0)', zombie_cleared: null },
    { pipeline: 'some_new_task', failed: 1, last_failed_at: '2026-11-03T09:00:00Z', last_error: null, zombie_cleared: null },
  ],
}

const { PipelineFailuresPanel } = await import(compile(join(app, 'src/components/system/HiddenFailurePanels.tsx')))

function render(payload, opts = {}) {
  globalThis.__pipelineFixture = { data: payload, error: opts.error ?? null, loading: opts.loading ?? false }
  return renderToStaticMarkup(React.createElement(PipelineFailuresPanel))
}

const cases = []
function check(name, fn) { cases.push({ name, fn }) }

check('tasks are named, not their script ids', () => {
  const t = readingText(render(live))
  assert.match(t, /Watchlist agent jobs/)
  assert.match(t, /Research indexer/)
  assert.match(t, /Social ingest/)
  assert.doesNotMatch(t, /process_watchlist_agent_jobs|rag_indexer|social_ingest/)
})

check('the consequence is stated in words', () => {
  const t = readingText(render(live))
  assert.match(t, /supervisor stopped the run/)
  assert.match(t, /never finished and were closed as failed/)
  assert.match(t, /empty or not valid JSON/)
})

check('no parser text on the reading line', () => {
  const t = readingText(render(live))
  assert.doesNotMatch(t, /Expecting value/)
  assert.doesNotMatch(t, /zombie/i)
})

check('no table or status vocabulary on the reading line', () => {
  const t = readingText(render(live))
  assert.doesNotMatch(t, /pipeline_runs|failed\/error\/timeout|crashed/i)
})

check('the identifiers and the raw error stay on the page, in the disclosure', () => {
  const raw = render(live)
  assert.match(raw, /<details/)
  for (const keep of ['process_watchlist_agent_jobs', 'Expecting value: line 1 column 1 (char 0)', 'zombie_cleared: 2', 'pipeline_runs']) {
    assert.ok(raw.includes(keep), `deleted instead of moved: ${keep}`)
  }
})

check('an unknown task id is humanised, never printed raw', () => {
  const t = readingText(render(live))
  assert.match(t, /Some new task/)
  assert.doesNotMatch(t, /some_new_task/)
})

check('a row with no recorded cause says so', () => {
  const t = readingText(render({ ...live, pipelines: [{ pipeline: 'x_task', failed: 1, last_failed_at: null, last_error: null, zombie_cleared: null }] }))
  assert.match(t, /No cause was recorded/)
  assert.match(t, /time not recorded/)
})

check('unavailable is never rendered as a clean run', () => {
  const t = readingText(render({ status: 'ERROR' }, { error: null }))
  assert.match(t, /UNAVAILABLE/)
  assert.doesNotMatch(t, /No pipeline failures recorded/)
})

const results = []
for (const c of cases) {
  try { c.fn(); results.push({ name: c.name, passed: true }) }
  catch (e) { results.push({ name: c.name, passed: false, error: e.message.split('\n')[0] }) }
}
const out = { results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)

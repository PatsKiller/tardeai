// FQ-039 — the /hermes research overview reads in plain English.
//
// Red-first convention in this repo: each control below fails against the pre-fix components and
// passes after. The check is structural, not decorative: strip every <details> disclosure and every
// attribute value from the rendered markup, and nothing internal may remain in what is left — that
// remainder is what an operator reads. The identifiers themselves stay available inside the
// disclosures and tooltips, so nothing is removed from the page.
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
    'const useApi = (..._args: any[]): any => (globalThis as any).__hermesFixture',
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

/** What an operator reads: disclosures closed, attributes (tooltips) not visible. */
function readingText(markup) {
  return markup
    .replace(/<details[\s\S]*?<\/details>/g, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

const pq = {
  ok: true,
  total: 30980,
  open_count: 26396,
  findings: [{ id: 1, finding_type: 'stale_data', severity: 'warning', status: 'resolved', description: 'x' }],
  open_findings: [
    { id: 39179, finding_type: 'unsupported_thesis', severity: 'info', status: 'open', description: 'industry Gold — composite 60.6 (review)' },
    { id: 39118, finding_type: 'unsupported_thesis', severity: 'info', status: 'open', description: 'trend industry — composite 61.1 (review)' },
  ],
}
const health = {
  staging_counts: { hermes_research_intelligence: 20470, hermes_validation_findings: 30980 },
  kill_switch_active: false,
  gateway_status: 'disabled',
  rag_pipeline: { promoted: 894, embedded: 894, coverage_pct: 100 },
  embedding_queue: { pending: 0, failed: 0 },
}

const cases = []
function check(name, data, fn) {
  cases.push({ name, data, fn })
}

let Spot
try {
  Spot = (await import(compile(join(app, 'src/components/HermesQualitySpotCheck.tsx')))).default
} catch (e) {
  console.error('compile failed:', e.message)
  process.exit(1)
}

function render(data) {
  globalThis.__hermesFixture = { data, error: null, loading: false }
  return renderToStaticMarkup(React.createElement(Spot, { onDrill() {} }))
}

check('finding types read in plain English', { ...pq, ...health }, () => {
  const text = readingText(render({ ...pq, ...health }))
  assert.match(text, /Thesis not yet supported by evidence/)
  assert.doesNotMatch(text, /unsupported_thesis/, 'raw finding key is in the reading text')
})

check('severities read in plain English', { ...pq, ...health }, () => {
  const text = readingText(render({ ...pq, ...health }))
  assert.match(text, /Note/, 'info should read as Note')
  assert.doesNotMatch(text, /\binfo\b/, 'raw severity is in the reading text')
})

check('endpoints are behind a disclosure', { ...pq, ...health }, () => {
  const raw = render({ ...pq, ...health })
  const text = readingText(raw)
  assert.doesNotMatch(text, /\/api\//, 'an endpoint is in the reading text')
  assert.match(raw, /<details/, 'no disclosure block exists, so the endpoints were deleted, not moved')
  assert.match(raw, /\/api\/v2\/hermes\/pipeline-quality/, 'the endpoint was deleted from the page')
})

check('an unknown finding type is never shown raw', { open_findings: [{ id: 2, finding_type: 'some_new_producer_key', severity: 'warning', status: 'open' }], findings: [], total: 1, open_count: 1, ...health }, () => {
  const text = readingText(render({ open_findings: [{ id: 2, finding_type: 'some_new_producer_key', severity: 'warning', status: 'open' }], findings: [], total: 1, open_count: 1, ...health }))
  assert.match(text, /Some new producer key/)
  assert.doesNotMatch(text, /some_new_producer_key/)
})

check('the counts still read as counts', { ...pq, ...health }, () => {
  const text = readingText(render({ ...pq, ...health }))
  assert.match(text, /20,470|20470/, 'research row count disappeared')
  assert.match(text, /30,980|30980/, 'findings count disappeared')
})

// ── FQ-039 R1 (codex P2607-R1): a known zero is a count, not a missing value ─────────────────────────────────

check('a known open_count of zero is rendered as nothing open', { ...pq, open_count: 0, open_findings: [], ...health }, () => {
  const t = readingText(render({ ...pq, open_count: 0, open_findings: [], ...health }))
  assert.match(t, /nothing open/)
  assert.doesNotMatch(t, /still need attention/)
})

check('resolved history is labelled as history, not as open work', {}, () => {
  const resolvedOnly = { ...pq, open_count: 0, open_findings: [],
    findings: [{ id: 9, finding_type: 'unsupported_thesis', severity: 'info', status: 'resolved',
                 description: 'industry Gold — composite 60.6 (review)' }], ...health }
  const raw = render(resolvedOnly)
  assert.match(raw, /data-testid="quality-history-caption"/)
  const t = readingText(raw)
  assert.match(t, /showing the most recent resolved ones/)
  assert.match(t, /Thesis not yet supported by evidence/)
})

check('an unknown open count says so instead of borrowing the history length', { ...pq, open_count: undefined, open_findings: undefined, ...health }, () => {
  const t = readingText(render({ ...pq, open_count: undefined, open_findings: undefined, ...health }))
  assert.match(t, /open count not reported/)
  assert.doesNotMatch(t, /still need attention/)
})

// ── FQ-039 R3 (codex P2607-R3): "no open findings" is a claim about the queue, not about an empty slice ────────

const resolvedOnly = { id: 9, finding_type: 'unsupported_thesis', severity: 'info', status: 'resolved',
  description: 'industry Gold — composite 60.6 (review)' }

check('a positive count with an empty open list is a gap, never a global no-open', { ...pq, open_count: 7, open_findings: [], findings: [resolvedOnly], ...health }, () => {
  const raw = render({ ...pq, open_count: 7, open_findings: [], findings: [resolvedOnly], ...health })
  const t = readingText(raw)
  assert.match(t, /7 still need attention/, 'the authoritative positive count disappeared')
  assert.doesNotMatch(t, /No open findings/, 'an empty open slice was reported as a global absence')
  assert.doesNotMatch(t, /showing the most recent resolved ones/)
  assert.match(raw, /data-testid="quality-history-gap"/, 'the gap between the count and the slice is not named')
  assert.match(t, /came back empty/)
})

check('an unreported count never claims that nothing is open', { ...pq, open_count: undefined, open_findings: undefined, findings: [resolvedOnly], ...health }, () => {
  const raw = render({ ...pq, open_count: undefined, open_findings: undefined, findings: [resolvedOnly], ...health })
  const t = readingText(raw)
  assert.match(t, /open count not reported/)
  assert.doesNotMatch(t, /No open findings/, 'an unknown count was rendered as a global absence')
  assert.doesNotMatch(t, /showing the most recent resolved ones/)
  assert.match(raw, /data-testid="quality-history-unknown"/)
})

check('a matched zero still reads as nothing open, with history captioned', { ...pq, open_count: 0, open_findings: [], findings: [resolvedOnly], ...health }, () => {
  const raw = render({ ...pq, open_count: 0, open_findings: [], findings: [resolvedOnly], ...health })
  const t = readingText(raw)
  assert.match(t, /nothing open/)
  assert.match(raw, /data-testid="quality-history-caption"/)
  assert.match(t, /showing the most recent resolved ones/)
  assert.doesNotMatch(raw, /data-testid="quality-history-gap"/)
  assert.doesNotMatch(raw, /data-testid="quality-history-unknown"/)
})

// P2607-R3 sibling (codex at 698d1cba5): a missing count with an EXPLICIT empty returned slice is still unknown —
// the slice is what came back, not how much is open, so it must never be read as a zero.
check('a missing count with an explicit empty open slice is unknown, not zero', { ...pq, open_count: undefined, open_findings: [], findings: [resolvedOnly], ...health }, () => {
  const raw = render({ ...pq, open_count: undefined, open_findings: [], findings: [resolvedOnly], ...health })
  const t = readingText(raw)
  assert.doesNotMatch(t, /nothing open/, 'an empty slice was counted as a known zero')
  assert.doesNotMatch(t, /No open findings/, 'an empty slice was reported as a global absence')
  assert.match(t, /open count not reported/)
  assert.match(raw, /data-testid="quality-history-unknown"/)
  assert.doesNotMatch(raw, /data-testid="quality-history-caption"/)
})

// ── FQ-039 R2 (codex P2607-R2): an inherited property name is an unknown key, not a crash ─────────────────────

for (const evil of ['__proto__', 'constructor', 'toString']) {
  check(`an unknown type named ${evil} renders as words, not a crash`, { ...pq, open_count: 1, open_findings: [
    { id: 7, finding_type: evil, severity: 'info', status: 'open', description: 'producer sent an inherited name' }], ...health }, () => {
    const raw = render({ ...pq, open_count: 1, open_findings: [
      { id: 7, finding_type: evil, severity: 'info', status: 'open', description: 'producer sent an inherited name' }], ...health })
    const t = readingText(raw)
    assert.match(t, /Proto|Constructor|ToString|Object prototype/i, `no humanised label for ${evil}: ${t.slice(0, 200)}`)
  })
}

// The staging table names live in HermesHub's overview, which pulls reactflow and the router; that
// page is covered by a source guard plus the label unit test rather than an SSR render.
const hub = readFileSync(join(app, 'src/pages/HermesHub.tsx'), 'utf8')
check('staging counts are labelled, not printed as table names', {}, () => {
  assert.doesNotMatch(hub, /k\.replace\('hermes_', ''\)/, 'the table name is still printed raw')
  assert.match(hub, /stagingTableLabel\(k\)/)
  assert.match(hub, /title=\{k\}/, 'the raw table name is not kept anywhere on the row')
})
check('script names are behind a disclosure', {}, () => {
  assert.match(hub, /What runs each of these/)
  assert.match(hub, /hermes_backlog_drain\.py/, 'the script name was deleted instead of moved into the disclosure')
})

const results = []
for (const c of cases) {
  try {
    c.fn()
    results.push({ name: c.name, passed: true })
  } catch (e) {
    results.push({ name: c.name, passed: false, error: e.message.split('\n')[0] })
  }
}
const out = { results, passed: results.filter((r) => r.passed).length, failed: results.filter((r) => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)

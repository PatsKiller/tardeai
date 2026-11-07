// node src/lib/n8nCatalog.render.test.mjs
// Ops › Jobs & n8n › n8n catalog (LQ-20261107-150). RENDERS the real components and asserts: every chip and top stat
// carries tooltip text (data-tip + title), never a bare "dry", "not audited" for lanes with no verdict, lane taps open
// the existing ?lane= sheet, a missing count reads "—", and no write button. Synthetic fixtures only.
import { readFileSync, existsSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

globalThis.window = { matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, location: { pathname: '/', search: '', href: 'http://synthetic.invalid/' } }

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  let source = readFileSync(path, 'utf8')
  source = source.replace(/^import\s+['"][^'"]+\.css['"]\s*$/gm, '')
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



const { MemoryRouter } = require('react-router-dom')
// SSR warns once per component that uses a layout effect; expected on the server and noisy in CI logs.
const __origConsoleError = console.error
console.error = (...args) => { if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return; __origConsoleError(...args) }
const { N8nCatalogView, LaneRow } = await import(compile(join(app, 'src/components/N8nCatalogViews.tsx')))

let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }
const h = (el, url = '/ops/jobs-n8n?tab=catalog') => renderToStaticMarkup(React.createElement(MemoryRouter, { initialEntries: [url] }, el))
const buttons = html => html.match(/<button[^>]*>/g) || []
const attr = (tag, name) => (tag.match(new RegExp(`${name}="([^"]*)"`)) || [])[1]

const lane = (id, extra) => ({ lane_id: id, title: `Synthetic ${id}`, does: 'does a synthetic thing', category_key: 'research', mode: 'live',
  in_relay: true, schedule: ['0 7 * * 1-5'], ...extra })
const lanes = {
  'syn-pass': lane('syn-pass', { verdict: 'PASS', verdict_class: 'pass' }),
  'syn-fail': lane('syn-fail', { mode: 'both', verdict: 'FAIL_DATA', verdict_class: 'fail', defect: 'synthetic stale values', work_item: 'LQ-20261107-999' }),
  'syn-dry': lane('syn-dry', { mode: 'dry', in_relay: false, verdict: null, verdict_class: 'not_audited', does: null }),
  'syn-unlisted': lane('syn-unlisted', { in_relay: false, verdict: 'UNVERIFIABLE', verdict_class: 'not_provable', defect: 'no live run yet' }),
}
const data = {
  schema: 'N8nCatalog@v1', computed_at: '2026-01-07T15:00:00Z',
  stats: { modes: { live: 2, both: 1, dry: 1, none: 5 }, audit: { pass: 1, fail: 1, not_provable: 1, audited: 3 } },
  categories: [
    { key: 'research', label: 'Research & intel', blurb: 'Synthetic news.', modes: { live: 2, both: 1, dry: 1, none: 0 }, lanes: Object.keys(lanes) },
    { key: 'broker', label: 'Broker', blurb: 'Synthetic broker.', modes: { live: 0, both: 0, dry: 0, none: 5 }, lanes: [] },
  ],
  lanes, relay: { source: 'test', lanes: 3, paused: [] }, audit: { state: 'ok', written_at: '2026-01-07T14:00:00Z', by: 'synthetic', rows: 3 }, notes: [],
}
const html = h(React.createElement(N8nCatalogView, { data, loading: false, error: null }))

// 1. Every chip and stat has tooltip text, on data-tip and on title (the desktop fallback).
const tips = buttons(html).filter(b => b.includes('data-tip='))
check(tips.length === 7 + 2 * 4 + 4 * 2, `7 stats + 4 mode counts per category (2) + 2 chips per lane (4) carry a tip (got ${tips.length})`)
check(tips.every(b => (attr(b, 'data-tip') || '').trim().length > 10 && attr(b, 'title') === attr(b, 'data-tip')), 'every tip is non-empty and mirrored on title')
check(buttons(html).every(b => b.includes('data-tip=') || b.includes('aria-expanded')), 'every button is a tip chip or the Show/Hide toggle')
check((html.match(/data-testid="n8n-catalog-stat"/g) || []).length === 7, 'seven top stats')

// 2. Words: Dry run spelled out; no verdict says "Not audited"; verdict tip carries defect + work item.
check(!/>\s*dry\s*</i.test(html) && html.includes('Dry run on n8n'), 'never a bare "dry"')
check(/data-lane="syn-dry"[\s\S]*?Not audited/.test(html), 'a lane with no verdict reads Not audited')
check(html.includes('Defect: synthetic stale values') && html.includes('Work item: LQ-20261107-999'), 'verdict tip carries the defect and work item')
check(!/data-lane="syn-pass"[\s\S]*?n8n-catalog-defect/.test(html.split('data-lane="syn-fail"')[0]), 'a PASS lane shows no defect line')
check(html.includes('synthetic stale values') && html.includes('No description yet'), 'failing defect shown; missing description stated')
check(/data-lane="syn-unlisted"[\s\S]*?not in the relay live list/.test(html) && !/data-lane="syn-dry"[^]*?not in the relay live list[^]*?data-lane="syn-unlisted"/.test(html), 'only the unlisted live lane is flagged off the relay list')

// 3. Lane tap opens the existing full-screen sheet; nothing writes.
check(html.includes('href="/ops/jobs-n8n?tab=n8n&amp;lane=syn-fail"'), 'lane link opens ?lane= sheet')
check(!/>(Run|Retry|Pause|Resume|Rerun)</.test(html), 'no write button')
check(html.includes('Nothing in this category is on n8n') && html.includes('All 5 jobs run on cron or systemd.'), 'empty category says so')

// 4. Missing data: every stat reads "—", never 0; a note renders.
const empty = h(React.createElement(N8nCatalogView, { data: { notes: ['No audit file yet: every lane is not audited.'] }, loading: false, error: null }))
check((empty.match(/<strong[^>]*>—<\/strong>/g) || []).length === 7, 'missing counts read —')
check(empty.includes('every lane is not audited') && empty.includes('No categories are reported.'), 'note and empty state')

// 5. A lone row renders both chips with tips.
const row = h(React.createElement(LaneRow, { lane: lanes['syn-dry'] }))
check(buttons(row).length === 2 && buttons(row).every(b => (attr(b, 'data-tip') || '').length > 10), 'lane row: two chips, both with tips')

// 6. LQ-20261107-180: the approved page in subtabs. Pure HTML builders, rendered per subtab.
const A = await import(compile(join(app, 'src/lib/n8nCatalogApproved.ts')))
const wire = {
  computed_at: '2026-11-07T17:00:00+00:00', relay: { lanes: 3 },
  audit: { written_at: '2026-11-07T16:15:00+00:00', by: 'synthetic-auditor', rows: 4 },
  stats: { modes: { live: 2, both: 0, dry: 1, none: 5 }, verdicts: { PASS: 1, FAIL_DATA: 1, FAIL_RUN: 1, UNVERIFIABLE: 1 },
    audit: { pass: 1, fail: 2, not_provable: 1, audited: 4 } },
  categories: [{ key: 'research', label: 'Synthetic research', blurb: 'b', modes: { live: 2, both: 0, dry: 1, none: 5 },
    lanes: ['syn-pass', 'syn-fail', 'syn-dry'], jobs: 10, inactive: 2,
    status_mix: { failed: 1, missed: 0, late: 1, running: 0, ok: 4, ok_unverified: 2, not_measured: 0, inactive: 2 } }],
  lanes: {
    'syn-pass': lane('syn-pass', { verdict: 'PASS', audited_at: '2026-11-07T15:00:00+00:00' }),
    'syn-fail': lane('syn-fail', { verdict: 'FAIL_DATA', defect: 'synthetic <stale> values', work_item: 'LQ-9', audited_at: '2026-11-07T15:00:00+00:00' }),
    'syn-dry': lane('syn-dry', { mode: 'dry', in_relay: false }),
    'syn-run': lane('syn-run', { mode: 'none', verdict: 'FAIL_RUN', audited_at: '2026-11-07T16:00:00+00:00' }),
    'syn-unv': lane('syn-unv', { verdict: 'UNVERIFIABLE' }),
  },
  work_items: { 'LQ-9': { id: 'LQ-20261107-9', owner: 'syn-owner', status: 'in_progress' } },
}
const tipsOf = html => [...html.matchAll(/data-tip="([^"]*)"/g)].map(m => m[1])
const btns = html => (html.match(/<button[^>]*>/g) || [])
check(A.resolveSub('lanes') === 'lanes' && A.resolveSub('bogus') === 'overview' && A.resolveSub(null) === 'overview', 'sub resolves, unknown -> overview')
for (const sub of ['overview', 'lanes', 'audit']) {
  const page = A.pageHtml(wire, sub)
  check((page.match(/role="tab"/g) || []).length === 3, `${sub}: three subtabs`)
  check(new RegExp(`data-sub="${sub}" aria-selected="true"`).test(page) && (page.match(/aria-selected="true"/g) || []).length === 1, `${sub}: exactly its own pill selected`)
  check(tipsOf(page).every(t => t.trim().length > 10), `${sub}: every ⓘ has tip text`)
  check(!/>(Run|Retry|Pause|Resume|Re-run|Rerun|Approve)\b/.test(page), `${sub}: no write button`)
  check(!/<script|<stale>/.test(page), `${sub}: escaped`)
  check(!/(^|[^-\w])dry(?! run)[^-\w"]/i.test(page.replace(/<[^>]+>/g, ' ').replace(/Dry run|dry run/g, '')), `${sub}: never a bare "dry"`)
}
const ov = A.overviewHtml(wire)
check((ov.match(/class="stat"/g) || []).length === 6, 'overview: six stat tiles')
check(ov.includes('1 / 4') && ov.includes('Each of the 4 n8n-only lanes') && ov.includes('Audited Sat, Nov 7, 11:15 AM ET.'), 'overview: live counts and ET audit time')
check(ov.includes('jobs as of Sat, Nov 7, 12:00 PM ET'), 'overview: as-of ET stamp')
const vbtn = btns(ov).filter(b => b.includes('data-sub="audit"'))
check(vbtn.length === 8 && vbtn.every(b => /data-filter="[A-Z_]+"/.test(b)), 'overview: 8 verdict counts, each opens the filtered audit tab')
check(/FAIL DATA <b>1<\/b>/.test(ov) && /FAIL CONSUMER <b>0<\/b>/.test(ov), 'overview: per-verdict counts, a missing verdict reads 0')
const ln = A.lanesHtml(wire)
check(ln.includes('8 active + 2 paused/retired = 10 jobs'), 'lanes: active + paused/retired = total')
check(ln.includes('1 failed ⓘ') && ln.includes('2 ok unproven ⓘ') && ln.includes('2 paused/retired ⓘ') && !ln.includes('0 missed'), 'lanes: job health chips, zeros hidden')
check(ln.includes('href="/ops/jobs-n8n?tab=n8n&amp;lane=syn-fail"') && ln.includes('data-lane-link="syn-fail"'), 'lanes: lane tap -> ?lane= sheet')
check(ln.includes('data-search') && /data-hay="[^"]*synthetic &lt;stale&gt; values/.test(ln), 'lanes: search box and searchable text')
check(ln.includes('not in relay live list') === false, 'lanes: the dry-run lane is not flagged off the relay list')
check(ln.includes('(in_progress, syn-owner)'), 'lanes: verdict tip carries fix status and owner')
const au = A.auditHtml(wire)
const order = [...au.matchAll(/<li data-lane="([^"]+)"/g)].map(m => m[1])
check(JSON.stringify(order) === JSON.stringify(['syn-fail', 'syn-run', 'syn-unv', 'syn-pass']), `audit: FAIL first then not provable then PASS (${order})`)
check(au.includes('fix LQ-20261107-9 · in_progress · syn-owner') && au.includes('status unknown') === false, 'audit: fix id, status and owner from the ledger')
check(au.includes('Audit written Sat, Nov 7, 11:15 AM ET by synthetic-auditor'), 'audit: written-at ET stamp')
const auF = A.auditHtml(wire, 'FAIL_RUN')
check([...auF.matchAll(/<li data-lane="([^"]+)"/g)].map(m => m[1]).join() === 'syn-run' && auF.includes('data-filter="FAIL_RUN" aria-pressed="true"'), 'audit: verdict filter')
const unk = A.auditHtml({ ...wire, work_items: {} })
check(unk.includes('fix LQ-9 · status unknown'), 'audit: a fix id the ledger lacks says status unknown')
const none = A.pageHtml({ notes: ['synthetic note'] }, 'overview')
check(none.includes('synthetic note') && none.includes('<b class="live">— / —</b>') && none.includes('Not audited yet.'), 'missing data reads — and the note shows')

if (failed) { console.error(`n8nCatalog.render: ${failed} failed`); process.exit(1) }
console.log('n8nCatalog.render: all checks passed')

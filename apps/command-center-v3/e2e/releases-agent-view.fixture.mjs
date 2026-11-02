// Releases & schedules → Deploy in flight: the REAL component + REAL bundled CSS, synthetic API, no server,
// no credentials, no broker, no HTTP 7777. Mirrors the repo's existing *.fixture.mjs pattern.
//   node e2e/releases-agent-view.fixture.mjs <output-directory> [backend-output.json]
//
// With the optional second argument, an extra case renders the wire produced by the REAL backend projection
// (scripts/lib/deploy_in_flight.py at the head under review) against a synthetic coordination store, instead
// of a hand-written shape. Sanitized/synthetic values only; zero external and zero mutating traffic.
//
// Proves at 320 / 390 / 412 / 1280: agent cards and per-PR review/CI/blocker facts are visible text (no hover),
// there is no horizontal page overflow, BLOCK verdicts are never green, an older-head review is not current,
// UNKNOWN mergeability never reads as auto-rebase, and an old backend (no work / no coordination) is UNKNOWN.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'
import { chromium } from '@playwright/test'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const out = process.argv[2]
assert(out, 'explicit fixture evidence directory required')
const backendPayload = process.argv[3]
  ? JSON.parse(fs.readFileSync(process.argv[3], 'utf8'))
  : null
fs.mkdirSync(out, { recursive: true })

const clock = '2026-11-02T18:00:00Z'
const H1 = '1111111111111111111111111111111111111111'
const H2 = '2222222222222222222222222222222222222222'
const H3 = '3333333333333333333333333333333333333333'
const H4 = '4444444444444444444444444444444444444444'
const H5 = '5555555555555555555555555555555555555555'
const HOLD = '9999999999999999999999999999999999999999'

const row = (n, over) => ({
  number: n, title: `Synthetic PR ${n} — fixture only`, url: `https://example.invalid/${n}`,
  head_sha: H1, head_sha_short: H1.slice(0, 9), branch: `wt/fixture-${n}`, has_operator_merge: false,
  mergeable: 'MERGEABLE', merge_state: 'CLEAN', is_draft: false, why_held: null, next: 'auto-merge',
  work: {
    owner: 'cc2', current_task: `task for ${n}`, publication_state: 'published', local_head: H1, published_head: H1,
    review: { state: 'MERGE', head_sha: H1, as_of: clock, source: 'ledger' },
    ci: { state: 'GREEN', head_sha: H1, as_of: clock, source: 'receipt' },
    blockers: [], next_action: 'merge via the queue', as_of: clock, source: 'claims',
  },
  ...over,
})

// #2501 — one MERGE and one BLOCK at the SAME head: must render blocked, never green.
const pr2501 = row(2501, { work: { ...row(2501, {}).work, review: {
  head_sha: H1, as_of: clock, source: 'ledger',
  verdicts: [{ verdict: 'MERGE', reviewer: 'cc5', head_sha: H1 }, { verdict: 'BLOCK', reviewer: 'cc3', head_sha: H1 }],
}, ci: { state: 'RED', head_sha: H1, as_of: clock, source: 'receipt' },
  blockers: [{ kind: 'review', text: 'review BLOCK: symlink escape', owner: 'cc2' }] } })

// #2502 — conflict + local-only work.
const pr2502 = row(2502, { head_sha: H2, mergeable: 'CONFLICTING', merge_state: 'DIRTY',
  work: { ...row(2502, {}).work, head_sha: H2, publication_state: 'local_only', local_head: H2, published_head: null,
    review: { state: 'NONE', head_sha: H2 }, ci: { state: 'PENDING', head_sha: H2 } } })

// #2503 — draft with skipped CI: skipped is not red, and not ready.
const pr2503 = row(2503, { head_sha: H3, is_draft: true,
  work: { ...row(2503, {}).work, head_sha: H3, review: { state: 'NONE', head_sha: H3 }, ci: { state: 'SKIPPED', head_sha: H3 } } })

// #2504 — mergeability UNKNOWN with a legacy auto-rebase hint: must NOT read as auto-rebase.
const pr2504 = row(2504, { head_sha: H4, mergeable: 'UNKNOWN', merge_state: 'UNKNOWN', next: 'auto-rebase',
  work: { ...row(2504, {}).work, head_sha: H4, next_action: null, review: { state: 'NONE', head_sha: H4 }, ci: { state: 'GREEN', head_sha: H4 } } })

// #2505 — review bound to an OLD head: stale, not current.
const pr2505 = row(2505, { head_sha: H5, work: { ...row(2505, {}).work, head_sha: H5,
  review: { state: 'MERGE', head_sha: HOLD, as_of: clock, source: 'ledger' }, ci: { state: 'GREEN', head_sha: H5 } } })

const full = {
  schema: 'DeployInFlight@v1', authority: 'READ_ONLY_ADVISORY', generated_at: clock, repo: 'fixture/repo',
  status: 'OK', freshness: 'OK', source: 'synthetic fixture', count: 5,
  coordination: { status: 'OK', as_of: clock, source: 'claims+board', agents: [
    { session: 'cc2', agent: 'claude', task: 'backend ledger aggregation', state: 'working', branch: 'wt/be', pr: 2501, as_of: clock, source: 'claims' },
    { session: 'cc4', task: 'releases frontend', state: 'blocked', blocker: 'backend BLOCK on review state', next_action: 'wait for cc2', as_of: clock, source: 'claims' },
    { session: 'cc7', task: 'idle between tasks', state: 'idle', as_of: clock, source: 'board' },
  ] },
  prs: [pr2501, pr2502, pr2503, pr2504, pr2505],
}

// Old backend: neither additive key exists.
const old = {
  schema: 'DeployInFlight@v1', generated_at: clock, status: 'OK', freshness: 'OK', source: 'synthetic fixture',
  count: 1, prs: [Object.fromEntries(Object.entries(pr2501).filter(([k]) => k !== 'work'))],
}

const bundled = await build({
  stdin: {
    contents: `import React from 'react'; import {createRoot} from 'react-dom/client';
      import {MemoryRouter} from 'react-router-dom'; import DeployInFlightBoard from './src/components/DeployInFlightBoard';
      import './src/index.css'; import './src/pages/OpsEvidencePages.css';
      createRoot(document.getElementById('root')).render(
        <MemoryRouter><div className="ops-evidence-page" data-testid="synthetic-frame"
          style={{ background: 'var(--bg0)', color: 'var(--text0)', minHeight: '100vh', padding: 8 }}>
          <div style={{ fontSize: 11, opacity: 0.7 }}>SYNTHETIC RELEASES FIXTURE — no live data, no broker, no network</div>
          <DeployInFlightBoard /></div></MemoryRouter>);`,
    resolveDir: app, loader: 'tsx', sourcefile: 'releases-fixture.tsx',
  },
  bundle: true, write: false, outfile: 'fixture.js', jsx: 'automatic', platform: 'browser',
  define: { 'process.env.NODE_ENV': '"production"' },
})
const js = bundled.outputFiles.find(f => f.path.endsWith('.js')).text
const css = bundled.outputFiles.find(f => f.path.endsWith('.css')).text
const html = `<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>${css}</style></head>
  <body><main id="root"></main><script>${js.replace(/<\/script/gi, '<\\/script')}</script></body></html>`

const browser = await chromium.launch({ args: ['--no-sandbox'] })
const results = []
try {
  const cases = [
    { name: 'full', payload: full, widths: [320, 390, 412, 1280] },
    { name: 'old-backend', payload: old, widths: [320, 1280] },
    ...(backendPayload ? [{ name: 'backend', payload: backendPayload, widths: [320, 390, 1440] }] : []),
  ]
  for (const c of cases) {
    for (const width of c.widths) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, serviceWorkers: 'block' })
      const page = await context.newPage()
      await page.clock.setFixedTime(new Date(clock))
      const traffic = { api: [], external: [], mutations: [], unexpected: [], errors: [] }
      page.on('pageerror', e => traffic.errors.push(e.message))
      await page.route('**/*', async route => {
        const req = route.request(); const url = new URL(req.url())
        if (url.origin !== 'http://releases-fixture.test') { traffic.external.push(req.url()); return route.abort() }
        if (req.method() !== 'GET') { traffic.mutations.push(`${req.method()} ${url.pathname}`); return route.abort() }
        if (url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: html })
        if (url.pathname === '/api/v2/ops/in-flight') {
          traffic.api.push(url.pathname)
          return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: c.payload }) })
        }
        traffic.unexpected.push(url.pathname)
        return route.abort()
      })
      await page.goto('http://releases-fixture.test/')
      await page.waitForSelector('[data-testid="deploy-in-flight"]')
      await page.waitForFunction(() => (document.body.textContent || '').includes('In flight'))
      await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))))
      const measure = await page.evaluate(() => {
        const text = document.body.textContent || ''
        const table = document.querySelector('[data-testid="deploy-in-flight-rows"] table')
        return {
          width: innerWidth,
          pageScrollWidth: document.documentElement.scrollWidth,
          bodyScrollWidth: document.body.scrollWidth,
          agentCards: document.querySelectorAll('[data-testid^="agent-"]').length,
          agentStates: [...document.querySelectorAll('[data-testid^="agent-"]')].map(el => el.textContent || ''),
          prRows: table ? table.querySelectorAll('tbody tr').length : 0,
          labeledCells: table ? table.querySelectorAll('td[data-label]').length : 0,
          unlabeledCells: table ? table.querySelectorAll('td:not([data-label])').length : 0,
          text,
        }
      })
      assert.ok(measure.pageScrollWidth <= measure.width + 1,
        `${c.name}@${width}: horizontal overflow ${measure.pageScrollWidth} > ${measure.width}`)
      assert.deepEqual(traffic.external, [], `${c.name}@${width}: external request attempted`)
      assert.deepEqual(traffic.mutations, [], `${c.name}@${width}: a mutation was attempted`)
      assert.deepEqual(traffic.unexpected, [], `${c.name}@${width}: unexpected path`)
      assert.deepEqual(traffic.errors, [], `${c.name}@${width}: page error`)
      const t = measure.text
      const has = (s, why) => assert.ok(t.includes(s), `${c.name}@${width}: missing "${s}" (${why})`)
      has('Agents and current work', 'agent overview panel')
      has('In flight · open PRs to main', 'board title')
      if (c.name === 'full') {
        assert.equal(measure.agentCards, 3, `${c.name}@${width}: agent cards`)
        assert.ok(measure.prRows >= 5, `${c.name}@${width}: PR rows`)
        has('#2501', 'first PR')
        has('REVIEW · blocked', 'a BLOCK verdict renders blocked')
        has('CI · red', 'CI red is shown')
        has('LOCAL · unpublished work', 'local-only work is labelled')
        has('DRAFT', 'draft is labelled')
        has('CI · skipped', 'draft CI skip is not red')
        has('mergeability not stated', 'UNKNOWN mergeability is stated')
        has('head_changed', 'review on another head is not current')
        has('review BLOCK: symlink escape', 'the blocker text is visible')
        has('wait for cc2', 'agent next action is visible')
        assert.ok(!/REVIEW · merge requested[^\n]*CI · red/.test(t), 'a blocked/red PR never reads as merge+green')
      } else if (c.name === 'backend') {
        // The wire produced by the REAL backend projection at the head under review (9a0ae89e).
        assert.equal(measure.agentCards, 17, `${c.name}@${width}: all 17 BOARD agents rendered`)
        assert.equal(measure.agentStates.filter(s => s.includes('ASSIGNED')).length, 17,
          `${c.name}@${width}: every BOARD agent is ASSIGNED (got ${JSON.stringify(measure.agentStates.map(s => s.slice(0, 60)))})`)
        assert.ok(measure.agentStates.every(s => !s.includes('UNKNOWN')),
          `${c.name}@${width}: no BOARD agent falls back to UNKNOWN`)
        assert.ok(measure.agentStates.every(s => !s.includes('WORKING ')),
          `${c.name}@${width}: an assignment is never relabelled WORKING`)
        assert.equal(measure.agentStates.filter(s => s.includes('execution: working')).length, 1,
          `${c.name}@${width}: only the fresh 30-minute heartbeat proves execution`)
        has('#2501', 'first PR')
        has('REVIEW · blocked', 'BLOCK dominates a MERGE verdict at the same head')
        has('CI · red', 'the CI observation from the ledger')
        has('stale_review_for_other_head', 'a verdict recorded for another head is not current')
        has('stale_ci_for_other_head', 'CI recorded for another head is not current')
        has('land the test fix', 'the BOARD Open PRs next join')
        has('from board_open_prs', 'the next step states its own source')
        has('source time not stated', 'a row with no source clock is undated, not stamped with capture time')
        has('mergeability not stated (not auto-rebase)', 'UNKNOWN mergeability is never auto-rebase')
      } else {
        has('UNAVAILABLE · agents/claims not in this response', 'old backend coordination is UNKNOWN')
        has('work facts UNKNOWN', 'old backend work is UNKNOWN')
      }
      const file = path.join(out, `${c.name}-${width}.png`)
      await page.screenshot({ path: file, fullPage: true })
      results.push({ fixture: true, case: c.name, width, clock, measure: { ...measure, text: undefined }, screenshot: file, traffic })
      await context.close()
    }
  }
} finally {
  await browser.close()
}
fs.writeFileSync(path.join(out, 'receipt.json'), JSON.stringify({ generated_for: 'releases-agent-view', results }, null, 2))
for (const r of results) console.log(`  [PASS] ${r.case}@${r.width} no overflow · ${r.traffic.api.length} API route(s) · ${path.basename(r.screenshot)}`)
console.log(`releases-agent-view fixture: ${results.length}/${results.length} viewports clean`)

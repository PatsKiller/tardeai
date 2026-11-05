// Hermetic actual-page integration: only fetch is fake; no server or live API.
//
// PR #2669 — codex-cloud P2 at 975a11f25. When `/api/v2/cio/asks/:threadId` first answers a caller refusal,
// ThreadView latches a TERMINAL failure in its own useApi hook. `Check access again` used to re-arm only the
// list and grouping requests. After access was restored, the recovery guidance disappeared while the selected
// thread still read "Thread unavailable" — a screen asserting a stale state after the condition had changed
// (D51). This test mounts the REAL page with the REAL hooks, refuses once, restores access, presses the real
// retry, and requires the selected thread's request to be re-armed so the thread renders.
//
// Run: node src/pages/MyQuestions.accessRetry.view.test.mjs [repo-root] [result.json]
import assert from 'node:assert/strict'
import { writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(process.argv[2] ?? join(dirname(fileURLToPath(import.meta.url)), '../../../..'))
const app = join(root, 'apps/command-center-v3')
const require = createRequire(join(app, 'package.json'))
const { build } = require('esbuild')
const { chromium, expect } = require('@playwright/test')

const bundle = await build({
  stdin: {
    contents: `
      import React, { act } from 'react'
      import { createRoot } from 'react-dom/client'
      import { MemoryRouter, Routes, Route } from 'react-router-dom'
      import Page from './src/pages/MyQuestions'
      window.IS_REACT_ACT_ENVIRONMENT = true
      const root = createRoot(document.getElementById('root'))
      const pageElement = React.createElement(Page)
      window.mountPage = () => act(async () => root.render(
        React.createElement(MemoryRouter, { initialEntries: ['/cio/questions/TH-1'] },
          React.createElement(Routes, null,
            React.createElement(Route, { path: '/cio/questions/:threadId', element: pageElement })))))
      window.settle = async () => {
        for (let i = 0; i < 10; i++) await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
      }
      window.clickCheckAccess = async () => {
        const button = [...document.querySelectorAll('button')].find(el => (el.textContent || '').trim() === 'Check access again')
        if (!button) throw new Error('Check access again button is not rendered')
        await act(async () => { button.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
        await window.settle()
      }
      window.unmountPage = () => act(async () => root.unmount())
    `,
    resolveDir: app,
    loader: 'tsx',
  },
  bundle: true,
  write: false,
  jsx: 'automatic',
  platform: 'browser',
  loader: { '.css': 'empty' },
  define: { 'process.env.NODE_ENV': '"test"' },
})

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ serviceWorkers: 'block' })
const pageErrors = []
const externalRequests = []
page.on('pageerror', error => pageErrors.push(error.message))
// Any accidental network request is refused and also fails the test.
await page.route('**/*', route => { externalRequests.push(route.request().url()); return route.abort() })
const evidence = { source_root: root, actual_page: true, live_requests: false }
try {
  await page.setContent('<div id="root"></div>')
  await page.evaluate(() => {
    const now = new Date().toISOString()
    window.mode = 'refused'
    window.calls = { list: 0, grouped: 0, thread: 0 }
    window.thread = {
      thread_id: 'TH-1', title: 'Is the AI capex cycle intact?', created_at: now, updated_at: now,
      status: 'quick', channels: ['cc'], reanswers: 0, entities: [],
      turns: [{
        ask_id: 'A1', question: 'Is the AI capex cycle intact?', channel: 'cc', asked_at: now, turn_kind: 'ask',
        answers: [{ answer_id: 'V1', version: 1, status: 'quick', depth: 'quick',
          summary: 'Demand remains firm across the largest buyers.', produced_at: now }],
      }],
    }
    window.summary = {
      thread_id: 'TH-1', title: 'Is the AI capex cycle intact?', updated_at: now, status: 'quick',
      channels: ['cc'], turns: 1, reanswers: 0, entities: [], last_answer_excerpt: 'Demand remains firm',
    }
    const json = (body, status = 200) => new Response(JSON.stringify(body), {
      status, headers: { 'Content-Type': 'application/json' },
    })
    window.fetch = async input => {
      const url = new URL(typeof input === 'string' ? input : input.url, 'http://command-center.local')
      if (url.pathname === '/api/v2/cio/asks' && url.searchParams.has('group_by')) window.calls.grouped += 1
      else if (url.pathname === '/api/v2/cio/asks') window.calls.list += 1
      else if (url.pathname.startsWith('/api/v2/cio/asks/')) window.calls.thread += 1
      if (window.mode === 'refused') {
        return json({ ok: false, error: 'AGENT_CALLER_REFUSED', detail: 'caller identity was not presented' }, 403)
      }
      if (url.pathname === '/api/v2/cio/asks' && url.searchParams.has('group_by')) {
        return json({ ok: true, data: { grouped: {
          group_by: 'security', q: '', channel: '', groups: [],
          group_bys: [{ id: 'security', available: true, reason: null }],
        } } })
      }
      if (url.pathname === '/api/v2/cio/asks') return json({ ok: true, data: { threads: [window.summary] } })
      if (url.pathname === '/api/v2/cio/asks/TH-1') return json({ ok: true, data: { thread: window.thread } })
      return new Response('unexpected request ' + url.pathname, { status: 404 })
    }
  })
  await page.addScriptTag({ content: bundle.outputFiles[0].text })

  await page.evaluate(() => window.mountPage())
  await page.evaluate(() => window.settle())

  // The refusal latches: guidance is offered AND the selected thread reports itself unavailable.
  await expect(page.getByTestId('mq-access-recovery')).toBeVisible()
  await expect(page.getByText(/Thread unavailable/)).toBeVisible()
  const callsAtRefusal = await page.evaluate(() => ({ ...window.calls }))
  assert.equal(callsAtRefusal.thread, 1, 'the refused thread must be requested once at mount')

  // Access is restored, then the operator presses the page's own retry.
  await page.evaluate(() => { window.mode = 'restored' })
  await page.evaluate(() => window.clickCheckAccess())

  const text = await page.locator('body').innerText()
  const callsAfterRetry = await page.evaluate(() => ({ ...window.calls }))
  assert.equal(callsAfterRetry.thread, callsAtRefusal.thread + 1,
    'Check access again must re-arm the selected thread request, not only the list and grouping')
  assert.doesNotMatch(text, /Thread unavailable/,
    'the thread pane must not keep asserting "unavailable" after access has been restored')
  assert.equal(await page.getByTestId('ask-thread').count(), 1, 'the recovered thread must render')
  assert.match(text, /Is the AI capex cycle intact\?/, 'the thread title must be visible after recovery')
  assert.equal(await page.getByTestId('mq-access-recovery').count(), 0,
    'the recovery guidance is withdrawn once the list request succeeds, so the thread must be truthful')

  await page.evaluate(() => window.unmountPage())
  assert.deepEqual(pageErrors, [], 'the real page must not throw in the browser')
  assert.deepEqual(externalRequests, [], 'all fetches must stay in the fake boundary')
  evidence.result = 'PASS'
  evidence.calls = { refusal: callsAtRefusal, after_retry: callsAfterRetry }
} catch (error) {
  evidence.result = 'FAIL'
  evidence.error = { name: error.name, message: error.message }
  evidence.text = await page.locator('body').innerText().catch(() => '')
  evidence.calls = await page.evaluate(() => ({ ...window.calls })).catch(() => null)
  process.exitCode = 1
} finally {
  await page.close()
  await browser.close()
}
if (process.argv[3]) writeFileSync(process.argv[3], JSON.stringify(evidence, null, 2) + '\n')
console.log(JSON.stringify(evidence, null, 2))

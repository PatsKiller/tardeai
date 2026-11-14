// Ask the CIO / My questions — the refused-read panel render (campaign Home item 6).
//
// The panel is drawn instead of the list when useApi's answer was 401/403. It must name the server's code when the body
// carried one and the HTTP status when it did not — never invent a code — quote the server's sentence, say that polling
// stopped, show the held body as a stated non-display with an absolute time, and offer one operator recovery.
// Synthetic fixtures only.
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, dirname, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const __origConsoleError = console.error
console.error = (...args) => {
  if (String(args[0] ?? '').includes('useLayoutEffect does nothing on the server')) return
  __origConsoleError(...args)
}

const app = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(join(app, 'package.json'))
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

const memo = new Map()
function compile(path) {
  if (memo.has(path)) return memo.get(path)
  const source = readFileSync(path, 'utf8')
  let js = ts.transpileModule(source, {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  js = js.replace(/import\s+['"][^'"]+\.css['"];?/g, '')
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

const { askDenialView } = await import(compile(join(app, 'src', 'lib', 'askCioDenied.ts')))
const { default: Panel } = await import(compile(join(app, 'src', 'components', 'AskCioDenied.tsx')))

const NOW = Date.parse('2031-03-07T15:00:00Z')
const HELD = '2031-03-07T14:56:00Z'
const render = (view, heldAt = HELD, nowMs = NOW) => renderToStaticMarkup(
  React.createElement(Panel, { view, heldAt, nowMs, onRetry: () => {} }))
const text = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()

let n = 0
function test(name, fn) { fn(); n += 1; console.log(`ok - ${name}`) }

// 1. A 403 with the server's code and sentence: the code is named, the sentence quoted, the held body disclosed.
test('403 names the server code + sentence, and the held read is not shown as current', () => {
  const t = text(render(askDenialView({ authState: 'FORBIDDEN', errorCode: 'AGENT_CALLER_REFUSED', errorDetail: 'Ask the CIO answers only the operator’s tailnet identity' })))
  assert.match(t, /Refused — this surface answers only the operator/)
  assert.match(t, /AGENT_CALLER_REFUSED/)
  assert.match(t, /tailnet identity/)
  assert.match(t, /The questions last read at Mar 7 09:56 ET · 4m ago are not shown: they may have changed since\./)
  assert.match(t, /Polling stopped\. It asks once more when you return to this tab\./)
  assert.match(t, /Try again/)
})

// 2. A 403 whose body carried no code is labelled by the status, and no code is invented.
test('code-less 403 is labelled HTTP 403, never a guessed code', () => {
  const t = text(render(askDenialView({ authState: 'FORBIDDEN' })))
  assert.match(t, /HTTP 403/)
  assert.doesNotMatch(t, /AGENT_CALLER_REFUSED|CSRF_REFUSED/)
  assert.match(t, /the server refused this read/)
})

// 3. A 401 is its own refusal with its own recovery.
test('401 is a sign-in refusal, not a forbidden one', () => {
  const t = text(render(askDenialView({ authState: 'UNAUTHORIZED' })))
  assert.match(t, /Sign-in required/)
  assert.match(t, /HTTP 401/)
  assert.match(t, /Sign in, then press Try again or return to this tab\./)
  assert.doesNotMatch(t, /HTTP 403|AGENT_CALLER_REFUSED/)
})

// 4. No held body: the panel says so instead of implying an empty queue.
test('a session that never read the list says it has not read it', () => {
  const t = text(render(askDenialView({ authState: 'FORBIDDEN', errorCode: 'AGENT_CALLER_REFUSED' }), null))
  assert.match(t, /This page has not read any questions in this session\./)
  assert.doesNotMatch(t, /are not shown/)
})

// 5. The held age is computed at render: the same held instant ages with the render clock.
test('the held age moves with the render clock (no stored age)', () => {
  const view = askDenialView({ authState: 'FORBIDDEN', errorCode: 'AGENT_CALLER_REFUSED' })
  assert.match(text(render(view, HELD, NOW + 30 * 60_000)), /Mar 7 09:56 ET · 34m ago/)
})

// 6. A read that was not refused draws nothing at all.
test('not denied -> no panel', () => {
  for (const view of [askDenialView({ authState: 'OK' }), askDenialView(null)]) {
    assert.equal(renderToStaticMarkup(React.createElement(Panel, { view, heldAt: null, nowMs: NOW, onRetry: () => {} })), '')
  }
})

// 7. The retry is an operator button inside the alert, and the panel carries the typed identity as data.
test('the panel is an alert carrying one retry button and the typed identity', () => {
  const html = render(askDenialView({ authState: 'FORBIDDEN', errorCode: 'AGENT_CALLER_REFUSED' }))
  assert.match(html, /role="alert"/)
  assert.match(html, /data-testid="ask-denied"/)
  assert.match(html, /data-code="AGENT_CALLER_REFUSED"/)
  assert.equal((html.match(/<button/g) ?? []).length, 1)
  assert.match(html, /data-testid="ask-denied-retry"/)
})

console.log(`AskCioDenied: ${n} passed`)

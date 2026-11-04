// FQ-074 — a research review prompt and an actionable position decision must not read the same.
//
// Live at release 105df180e, `/watch?tab=intelligence&view=top_ideas` at 390 px showed a card whose decision chip read
// "▶ Review entry" (green) while the card's own posture said "Watching for confirmation — no executable ticket" and its
// Trade AI state said "WAIT". Two answers to one question, and the louder one implied an order.
//
// Red-first: the first two controls fail against the parent component (the hint was printed verbatim in green) and pass
// after. The other two are controls: a real action keeps its green badge, and a blocked decision is untouched.
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
  const source = readFileSync(path, 'utf8')
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

const mod = await import(compile(join(app, 'src/components/watch/WatchDecisionParts.tsx')))
const Badges = mod.WatchDecisionBadges
const text = (m) => m.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim()

const decision = (over = {}) => ({
  category: 'high_conviction_opportunity', priority: 'high', status: 'active', actionable: true,
  action_hint: 'Review entry', ttl_remaining_s: 259200, ...over,
})

const cases = []
function check(name, fn) { cases.push({ name, fn }) }

check('a review hint does not read as an order', () => {
  const t = text(renderToStaticMarkup(React.createElement(Badges, { d: decision() })))
  assert.match(t, /Review prompt: entry — not an order/)
  assert.doesNotMatch(t, /▶ Review entry/)
})

check('the review chip says what it is in its title', () => {
  const html = renderToStaticMarkup(React.createElement(Badges, { d: decision() }))
  assert.match(html, /nothing is executable from here/)
})

check('a real action keeps its actionable badge', () => {
  const t = text(renderToStaticMarkup(React.createElement(Badges, { d: decision({ action_hint: 'Trim' }) })))
  assert.match(t, /▶ Trim/)
})

check('actionable with no hint is unchanged', () => {
  const t = text(renderToStaticMarkup(React.createElement(Badges, { d: decision({ action_hint: null }) })))
  assert.match(t, /▶ Actionable/)
})

check('a blocked decision is still blocked, in red', () => {
  const t = text(renderToStaticMarkup(React.createElement(Badges, { d: decision({ actionable: false, actionable_blocked_by: 'DETERMINISTIC_FAIL' }) })))
  assert.match(t, /Not actionable — Trade AI DETERMINISTIC FAIL/)
  assert.doesNotMatch(t, /Review prompt/)
})

const results = []
for (const c of cases) {
  try { c.fn(); results.push({ name: c.name, passed: true }) }
  catch (e) { results.push({ name: c.name, passed: false, error: e.message.split('\n')[0] }) }
}
const out = { results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length }
console.log(JSON.stringify(out, null, 1))
if (out.failed) process.exit(1)

// Pure state coverage plus real DeskPage output: a declaration alone cannot prove a rendered label.
import assert from 'node:assert/strict'
import { writerStateWords } from './deskWriterState.ts'
import { renderWriter, primaryOf, diagnosticsOf, text } from './deskSourceClocks.boundary.test.mjs'

let passed = 0, failed = 0
function check(name, fn) {
  try { fn(); passed++; console.log(`[PASS] ${name}`) }
  catch (error) { failed++; console.log(`[FAIL] ${name}: ${error.message}`) }
}
const states = [
  ['ACTIVE', 'Enabled'],
  ['PAUSED', 'Paused — not refreshing this source'],
  ['RETIRED', 'Retired — not refreshing this source'],
  ['NONE', 'No writer is scheduled for this source'],
]
for (const [state, expected] of states) {
  check(`${state} mapping`, () => assert.equal(writerStateWords(state), expected))
  check(`${state} is actually rendered`, () => assert.equal(primaryOf(renderWriter(state)), expected))
}
check('ACTIVE without any successful execution does not claim refreshing', () => {
  const html = renderWriter('ACTIVE')
  assert.equal(primaryOf(html), 'Enabled')
  assert.doesNotMatch(primaryOf(html), /refreshing|running/i)
  assert.match(text(diagnosticsOf(html)), /No successful run is recorded in the available execution evidence\./)
})
check('historical success does not make registry state live execution evidence', () => {
  const html = renderWriter('ACTIVE', { lastSuccess: '2026-11-05T19:00:00Z' })
  assert.equal(primaryOf(html), 'Enabled')
  assert.match(text(diagnosticsOf(html)), /Last successful run:/)
})
check('all readable states keep distinct primary labels', () => assert.equal(new Set(states.map(([state]) => primaryOf(renderWriter(state)))).size, 4))
check('unread while loading actually renders Checking', () => assert.equal(primaryOf(renderWriter(null, { loading: true })), 'Checking'))
check('unread after loading actually renders unavailable', () => assert.equal(primaryOf(renderWriter(null)), 'State unavailable'))
check('unknown state is not guessed into another meaning', () => assert.equal(primaryOf(renderWriter('SYNTHETIC_UNKNOWN')), 'State unavailable'))
console.log(JSON.stringify({ suite: 'deskWriterState', passed, failed }))
if (failed) process.exitCode = 1

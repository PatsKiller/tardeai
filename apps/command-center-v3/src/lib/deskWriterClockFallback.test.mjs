// Operator 2026-11-06 ("This seems not wired"): an ops page with no update time of its own showed "Update time
// unavailable" while the writer's last successful run sat hidden in Diagnostics. The headline now shows that run,
// labelled as the writer's run, never as the source's update time. Synthetic fixtures only.
import assert from 'node:assert/strict'
import { newestWriterRun } from './deskWriterState.ts'
import { renderWriter, markup, text } from './deskSourceClocks.boundary.test.mjs'

let passed = 0, failed = 0
function check(name, fn) {
  try { fn(); passed++; console.log(`[PASS] ${name}`) }
  catch (error) { failed++; console.log(`[FAIL] ${name}: ${error.message}`) }
}
const headline = html => text(markup(html).match(/<div\b[^>]*data-testid="desk-source-age"[^>]*>([\s\S]*?)<\/div>/)?.[1] ?? '')
const GAP = 'This page does not record when this source last updated; the writer’s last successful run is shown instead.'

check('newestWriterRun picks the latest valid instant', () => assert.equal(newestWriterRun([
  { last_success_at: '2026-11-05T19:00:00Z' }, undefined, { last_success_at: null }, { last_success_at: '2026-11-05' },
  { last_success_at: '2026-11-05T20:30:00Z' }]), '2026-11-05T20:30:00Z'))
check('newestWriterRun with nothing usable is null', () => assert.equal(newestWriterRun([undefined, { last_success_at: null }]), null))
check('no page time + writer ran: headline is the writer run, no gap', () => {
  const html = renderWriter('ACTIVE', { asOf: null, fallback: true, gap: GAP, lastSuccess: '2026-11-05T20:57:00Z', reason: null })
  assert.equal(headline(html), 'Writer last ran 3m ago')
  assert.doesNotMatch(text(html), /Update time unavailable/)
  assert.doesNotMatch(text(html), /does not record when this source last updated/)
  assert.match(text(html), /Last successful run at/)
})
check('no page time + writer never ran: stays unavailable with the gap', () => {
  const html = renderWriter('ACTIVE', { asOf: null, fallback: true, gap: GAP, lastSuccess: null })
  assert.equal(headline(html), 'Update time unavailable')
  assert.match(text(html), /does not record when this source last updated/)
})
check('writer run older than a day is flagged', () => {
  const html = renderWriter('ACTIVE', { asOf: null, fallback: true, gap: GAP, lastSuccess: '2026-11-03T20:00:00Z', reason: null })
  assert.equal(headline(html), 'Writer last ran 2d ago')
  assert.match(text(html), /has not succeeded in over a day/)
})
check('page time present: headline stays "Updated", fallback unused', () => {
  const html = renderWriter('ACTIVE', { fallback: true, lastSuccess: '2026-11-05T20:00:00Z', reason: null })
  assert.equal(headline(html), 'Updated 2m ago')
})
check('fallback off (non-ops desks): unchanged behaviour', () => {
  const html = renderWriter('ACTIVE', { asOf: null, lastSuccess: '2026-11-05T20:57:00Z', reason: null })
  assert.equal(headline(html), 'Update time unavailable')
})
console.log(JSON.stringify({ suite: 'deskWriterClockFallback', passed, failed }))
if (failed) process.exit(1)

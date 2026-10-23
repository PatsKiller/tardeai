// node --experimental-strip-types src/lib/pageVisibility.test.ts — visibility-paused polling (2026-10-22)
import { isPageVisible, subscribePageVisibility, REMEDIATION_POLL_MS } from './pageVisibility.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

function fakeDoc(state: string) {
  const listeners = new Set<() => void>()
  return {
    visibilityState: state,
    addEventListener: (_t: 'visibilitychange', cb: () => void) => { listeners.add(cb) },
    removeEventListener: (_t: 'visibilitychange', cb: () => void) => { listeners.delete(cb) },
    set(next: string) { this.visibilityState = next; listeners.forEach(l => l()) },
    count: () => listeners.size,
  }
}

check('remediation poll is 5 minutes', REMEDIATION_POLL_MS === 300_000)
check('visible document is visible', isPageVisible({ visibilityState: 'visible' }) === true)
check('hidden document is not visible', isPageVisible({ visibilityState: 'hidden' }) === false)
check('no document counts as visible', isPageVisible(undefined) === true)

{
  const doc = fakeDoc('visible')
  const seen: boolean[] = []
  const off = subscribePageVisibility(doc, v => seen.push(v))
  doc.set('hidden')
  doc.set('hidden') // no duplicate notification
  doc.set('visible')
  check('hidden then visible notified once each', JSON.stringify(seen) === '[false,true]')
  off()
  check('unsubscribe removes the listener', doc.count() === 0)
  doc.set('hidden')
  check('no notification after unsubscribe', seen.length === 2)
}

console.log(`\npageVisibility: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)

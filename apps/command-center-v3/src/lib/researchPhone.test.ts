import { PHONE_WIRE_LIMIT, defaultResearchView, secondaryFiltersOpen, wireRows } from './researchPhone.ts'

const assert = {
  equal(actual: unknown, expected: unknown, message?: string) {
    if (!Object.is(actual, expected)) throw new Error(message ? `${message}: expected ${String(expected)}, received ${String(actual)}` : `Expected ${String(expected)}, received ${String(actual)}`)
  },
}

// FQ-058: the phone opens the prioritized wire, not 100k px of article cards.
assert.equal(defaultResearchView(true), 'compact')
assert.equal(defaultResearchView(false), 'list')

// A phone shows a short list first; Show all releases the rest. Desktop is never capped.
const items = Array.from({ length: 40 }, (_, i) => i)
assert.equal(wireRows(items, true, false).length, PHONE_WIRE_LIMIT)
assert.equal(wireRows(items, true, false)[0], 0, 'the prioritized first row is kept')
assert.equal(wireRows(items, true, true).length, 40)
assert.equal(wireRows(items, false, false).length, 40)
assert.equal(wireRows(items.slice(0, 5), true, false).length, 5, 'fewer rows than the cap are all shown')

// Secondary filters fold on a phone and stay visible on a desktop.
assert.equal(secondaryFiltersOpen(true), false)
assert.equal(secondaryFiltersOpen(false), true)

console.log('research phone contract: passed')

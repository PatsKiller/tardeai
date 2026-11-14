import { scoreView, scoreTitle } from './rotationScores.ts'

const assert = {
  equal(actual: unknown, expected: unknown, what = '') {
    if (!Object.is(actual, expected)) throw new Error(`${what}Expected ${String(expected)}, received ${String(actual)}`)
  },
  ok(value: unknown, what = '') {
    if (!value) throw new Error(`${what}expected a truthy value, received ${String(value)}`)
  },
}

const byKey = (v: ReturnType<typeof scoreView>, k: string) => {
  const p = v.parts.find(x => x.key === k)
  if (!p) throw new Error(`no part ${k}`)
  return p
}

// ── The regression (RR-004): a genuine 0 was rendered as nothing (`{c.trim_score ? … : null}`). ──
// A zero is a real engine result, so it must be a visible part with its own state.
const zero = scoreView({ trim_score: 0, add_score: 0, confidence: 0.5, degradation: { thesis_status: 'triggered' } })
assert.equal(byKey(zero, 'trim').state, 'zero', 'trim 0 is a zero, not unavailable: ')
assert.equal(byKey(zero, 'trim').value, 0)
assert.equal(byKey(zero, 'trim').text, 'Trim score 0', 'trim 0 is rendered with its value: ')
assert.equal(byKey(zero, 'add').state, 'zero')
assert.equal(byKey(zero, 'add').text, 'Add score 0')
assert.equal(zero.stopDriven, true, 'trim 0 + degradation is stop-driven: ')

// A missing score is unavailable WITH a reason — distinguishable from a zero.
const missing = scoreView({ add_score: 42, confidence: 0.7 })
assert.equal(byKey(missing, 'trim').state, 'unavailable')
assert.equal(byKey(missing, 'trim').value, null)
assert.ok(/not returned as a number/.test(byKey(missing, 'trim').reason ?? ''), 'unavailable names why: ')
assert.equal(byKey(missing, 'trim').text, 'Trim score unavailable')
assert.ok(/unavailable/.test(scoreTitle(byKey(missing, 'trim'))), 'title explains unavailability: ')
assert.equal(missing.stopDriven, false, 'stop-driven needs a zero, not an unknown: ')

// Typed contract: a numeric string is not silently coerced into a score.
for (const raw of ['12', null, undefined, true, NaN, Infinity, {}]) {
  assert.equal(byKey(scoreView({ trim_score: raw }), 'trim').state, 'unavailable', `trim_score=${String(raw)} must be unavailable: `)
}
// Out-of-scale values are refused rather than displayed on a scale they cannot be on.
for (const raw of [-1, 101, 1e9]) {
  assert.equal(byKey(scoreView({ trim_score: raw }), 'trim').state, 'unavailable', `trim_score=${raw} is out of scale: `)
  assert.ok(/outside the engine's 0–100 scale/.test(byKey(scoreView({ trim_score: raw }), 'trim').reason ?? ''))
}
for (const raw of [-0.1, 1.2]) {
  assert.equal(byKey(scoreView({ confidence: raw }), 'confidence').state, 'unavailable', `confidence=${raw} is out of scale: `)
}

// Values pass through exactly; labels say "score"; scales are stated.
const real = scoreView({ trim_score: 12.34, add_score: 87.5, confidence: 0.623 })
assert.equal(byKey(real, 'trim').value, 12.34)
assert.equal(byKey(real, 'trim').text, 'Trim score 12.34')
assert.equal(byKey(real, 'trim').state, 'value')
assert.equal(byKey(real, 'add').text, 'Add score 87.5')
assert.equal(byKey(real, 'confidence').text, 'Confidence 0.623')
assert.equal(byKey(real, 'confidence').scale, '0–1 engine confidence')
assert.equal(byKey(real, 'trim').scale, '0–100 engine score')
assert.equal(real.stopDriven, false)
assert.ok(/not a share quantity/.test(scoreTitle(byKey(real, 'add'))), 'title denies a sizing meaning: ')

// An engine-supplied null reason is surfaced verbatim.
assert.equal(byKey(scoreView({ trim_score: null, score_unavailable_reason: 'engine_skipped_fund' }), 'trim').reason, 'engine_skipped_fund')

// Order is stable and exactly three parts (the layout renders them in order).
assert.equal(scoreView({}).parts.map(p => p.key).join(','), 'trim,add,confidence')

console.log('rotation score labels contract: passed')

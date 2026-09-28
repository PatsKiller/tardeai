// PR1 (2026-09-27): semantic token helpers are pure and theme-following (plain node, runs in npm build).
import assert from 'node:assert'
import { TONES, toneVars, toneFromVerdict, chipStyle, TOKENS, RADIUS, SHADOW, TYPE, CHART_HEX } from './designTokens.ts'

assert.deepEqual([...TONES], ['success', 'warning', 'danger', 'info', 'ai', 'neutral'])
for (const t of TONES) {
  const v = toneVars(t)
  assert.equal(v.color, `var(--${t}-color)`); assert.equal(v.bg, `var(--${t}-bg)`); assert.equal(v.border, `var(--${t}-border)`)
}
console.log('✓ every tone resolves to its three css vars')

assert.equal(toneFromVerdict('READY'), 'success'); assert.equal(toneFromVerdict('WAIT'), 'warning')
assert.equal(toneFromVerdict('MONITOR_ONLY'), 'warning'); assert.equal(toneFromVerdict('BLOCKED'), 'danger')
assert.equal(toneFromVerdict('hermes'), 'ai'); assert.equal(toneFromVerdict(undefined), 'neutral')
console.log('✓ legacy verdict vocabulary maps onto tones')

const chip = chipStyle('danger', 'soft', 'sm')
assert.equal(chip.color, 'var(--danger-color)'); assert.equal(chip.borderRadius, RADIUS.pill); assert.equal(chip.fontSize, TYPE.xs)
assert.ok(!JSON.stringify(chip).includes('#'), 'chip recipe carries no hex')
assert.ok(!JSON.stringify(TOKENS).includes('#') && !JSON.stringify(SHADOW).includes('#'), 'token maps are var() only')
console.log('✓ chip recipe and token maps are literal-free')

assert.equal(CHART_HEX.dark.series.length, 6); assert.equal(CHART_HEX.light.series.length, 6)
assert.ok(CHART_HEX.dark.series.every(h => /^#[0-9a-f]{6}$/i.test(h)) && CHART_HEX.light.series.every(h => /^#[0-9a-f]{6}$/i.test(h)))
console.log('✓ chart hex is the only literal palette, both themes')

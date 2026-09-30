/**
 * Hermetic nav alias tests for CIO Desk 5-tab IA.
 * Run via: node --experimental-strip-types src/lib/cioHubTabs.test.ts
 */
import assert from 'node:assert/strict'
import {
  CIO_HUB_DEFAULT_TAB,
  CIO_HUB_TABS,
  resolveCioHubTab,
  resolveEvidenceSubtab,
} from './cioHubTabs.ts'

assert.equal(CIO_HUB_DEFAULT_TAB, 'overview')
assert.deepEqual([...CIO_HUB_TABS], [
  'overview',
  'decisions',
  'research',
  'capital-policy',
  'evidence-comms',
])

assert.equal(resolveCioHubTab(null), 'overview')
assert.equal(resolveCioHubTab(''), 'overview')
assert.equal(resolveCioHubTab('overview'), 'overview')
assert.equal(resolveCioHubTab('cio-brain'), 'overview')
assert.equal(resolveCioHubTab('cio-now'), 'decisions')
assert.equal(resolveCioHubTab('opportunities'), 'decisions')
assert.equal(resolveCioHubTab('universe-theses'), 'research')
assert.equal(resolveCioHubTab('investment-books'), 'research')
assert.equal(resolveCioHubTab('capital-plan'), 'capital-policy')
assert.equal(resolveCioHubTab('posture'), 'capital-policy')
assert.equal(resolveCioHubTab('operator-policy'), 'capital-policy')
assert.equal(resolveCioHubTab('report'), 'evidence-comms')
assert.equal(resolveCioHubTab('telegram-receipts'), 'evidence-comms')
assert.equal(resolveCioHubTab('unknown-tab'), 'overview')

assert.equal(resolveEvidenceSubtab('telegram-receipts'), 'telegram-receipts')
assert.equal(resolveEvidenceSubtab('cio-brain'), 'full-brain')
assert.equal(resolveEvidenceSubtab('evidence'), 'audit')
assert.equal(resolveEvidenceSubtab('overview'), null)

console.log('cioHubTabs.test.ts: ok')

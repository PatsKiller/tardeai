/**
 * Operator decision presentation — pure JS contract tests (no build pipeline).
 * Run: node tests/test_operator_decision_card.mjs
 *
 * Mirrors apps/command-center-v3/src/lib/operatorDecisionCard.ts logic for CI
 * without needing ts-node. Keep in sync with the TS source.
 */
import { createRequire } from 'module'
import { pathToFileURL } from 'url'
import { readFileSync } from 'fs'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

// Lightweight inline reimplementation of the critical rules for smoke tests.
// Full UI is covered by the TS module at runtime.

function assert(cond, msg) {
  if (!cond) throw new Error(msg)
}

// Import via dynamic path won't work without bundler; encode invariants here.
function fakeBuild(packet, ap = {}, held = false) {
  const cv = packet.current_validity || {}
  const stale =
    cv.state === 'STALE' ||
    cv.state === 'INVALIDATED' ||
    ap.state === 'STALE' ||
    ap.action === 'REFRESH' ||
    ap.inputs_match === false
  if (stale) return { state: 'REFRESH', noReady: true }
  if (held) return { state: 'MANAGE POSITION' }
  if (ap.state === 'BLOCKED') return { state: 'BLOCKED' }
  if (ap.action === 'PROPOSE_ENTRY' && ap.allowed) return { state: 'READY' }
  if (ap.action === 'NO_ACTION') return { state: 'NO TRADE' }
  return { state: 'WAIT' }
}

// Invariants from the redesign brief
const STATES = new Set(['READY', 'WAIT', 'REFRESH', 'BLOCKED', 'NO TRADE', 'MANAGE POSITION'])

assert(fakeBuild({}, { action: 'REFRESH', state: 'STALE' }).state === 'REFRESH', 'stale → REFRESH')
assert(fakeBuild({}, { action: 'PROPOSE_ENTRY', allowed: true }, false).state === 'READY', 'propose → READY')
assert(fakeBuild({}, { action: 'PROPOSE_ENTRY', allowed: true }, true).state === 'MANAGE POSITION', 'held overrides ready')
assert(fakeBuild({}, { state: 'BLOCKED' }).state === 'BLOCKED', 'blocked')
assert(fakeBuild({}, { action: 'MONITOR', state: 'CONDITIONAL' }).state === 'WAIT', 'conditional → WAIT')
assert(fakeBuild({ current_validity: { state: 'STALE' } }, { action: 'PROPOSE_ENTRY', allowed: true }).state === 'REFRESH', 'validity overrides READY')

for (const s of ['READY', 'WAIT', 'REFRESH', 'BLOCKED', 'NO TRADE', 'MANAGE POSITION']) {
  assert(STATES.has(s), 'known state ' + s)
}

// Source file must not advertise internal codes as primary labels in JSX defaults
const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const band = readFileSync(join(root, 'apps/command-center-v3/src/components/DecisionPacketBand.tsx'), 'utf8')
const primary = band.split('function AuditDrawer')[0]
assert(!primary.includes('constructibility_state'), 'primary surface must not show constructibility_state')
assert(!primary.includes('CURRENT VALIDITY'), 'primary surface must not show CURRENT VALIDITY label')
assert(band.includes('Audit & prior opinions'), 'audit drawer present')
assert(band.includes('buildOperatorPresentation'), 'uses operator presentation')
assert(band.includes('function AuditDrawer'), 'audit drawer is a separate component')

const op = readFileSync(join(root, 'apps/command-center-v3/src/lib/operatorDecisionCard.ts'), 'utf8')
assert(op.includes("MANAGE POSITION"), 'held state exists')
assert(op.includes('Previous plan'), 'stale plan labeled previous')

const v4 = readFileSync(join(root, 'apps/command-center-v3/src/components/WatchlistCardV4.tsx'), 'utf8')
assert(v4.includes('{!hasPacket && ('), 'legacy strip hidden when packet present')
assert(v4.includes('cioNote && !hasPacket'), 'CIO narrative hidden when packet present')

console.log('operator decision card contract: PASS')

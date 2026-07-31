/**
 * Deterministic Node checks for holdingsRowModel stop-truth + cash boundary.
 * Run: node --experimental-strip-types tests/test_holdings_row_model_stop_truth.mjs
 * (falls back to reading source markers when strip-types is unavailable)
 */
import { readFileSync, existsSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const SRC = join(ROOT, 'apps/command-center-v3/src/lib/holdingsRowModel.ts')
const TABLE = join(ROOT, 'apps/command-center-v3/src/components/HoldingsTableView.tsx')
const PROTECT = join(ROOT, 'apps/command-center-v3/src/components/HoldingProtectionActions.tsx')

function assert(cond, msg) {
  if (!cond) {
    console.error('FAIL:', msg)
    process.exitCode = 1
  } else {
    console.log('ok:', msg)
  }
}

const rowSrc = readFileSync(SRC, 'utf8')
const tableSrc = readFileSync(TABLE, 'utf8')
const protectSrc = readFileSync(PROTECT, 'utf8')

assert(rowSrc.includes("protectionState: 'PROTECTED' | 'NO_STOP' | 'UNVERIFIABLE' | 'CASH'"), 'protectionState union includes CASH')
assert(rowSrc.includes('Do not place duplicate stop'), 'UNVERIFIABLE copy blocks duplicate placement')
assert(rowSrc.includes('needsVerification'), 'needsVerification field present')
assert(rowSrc.includes('isCashHolding'), 'isCashHolding helper present')
assert(rowSrc.includes("stopKind: 'CASH'"), 'cash rows use CASH stop kind')
assert(rowSrc.includes("protectionState: 'CASH'"), 'cash rows use CASH protection state')
assert(rowSrc.includes("primaryAction: { label: 'N/A', tone: 'muted' }"), 'cash primary action is N/A muted')
assert(rowSrc.includes('const needsVerification = protectionState === \'UNVERIFIABLE\''), 'UNVERIFIABLE sets needsVerification')
assert(rowSrc.includes('!needsVerification && (primary.tone === \'amber\' || primary.tone === \'red\')'), 'UNVERIFIABLE excluded from needsAction')
assert(tableSrc.includes('need stop placement'), 'footer separates placement count')
assert(tableSrc.includes('verification required'), 'footer separates verification count')
assert(tableSrc.includes('holdings-placement-count'), 'placement count testid')
assert(tableSrc.includes('holdings-verification-count'), 'verification count testid')
assert(protectSrc.includes('VERIFY STOPS — BROKER VERIFICATION REQUIRED'), 'degraded banner present')
assert(protectSrc.includes('Do not place duplicate stop'), 'degraded banner forbids duplicate')
assert(protectSrc.includes('CASH — no protective stop'), 'cash drawer short-circuits')
assert(protectSrc.includes('&& !brokerReadDegraded'), 'showProtect gated on broker read ok')

if (process.exitCode) {
  console.error('\nSome holdings row-model stop-truth checks failed')
  process.exit(1)
}
console.log('\nAll holdings row-model stop-truth static checks passed')

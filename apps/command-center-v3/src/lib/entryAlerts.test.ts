// node src/lib/entryAlerts.test.ts — the visible options chip state for entry alerts (no node:assert)
import { optionsAltChip } from './entryAlerts.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) { const g = JSON.stringify(got), w = JSON.stringify(want); if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) } }

// the incident shape, as the repaired index now serves it
const axti = { status: 'STALE_PRE_FIX', reason: 'no gate_version on the stored verdicts (computed before the 2026-09-28 earnings-gate fix)', qualified_count: 0, considered: 4, claimed: { status: 'OPTIONS_ALT_OK', qualified: ['debit_call_vertical'] } }
eq('AXTI stale is a warning with zero, never green', [optionsAltChip(axti).tone, optionsAltChip(axti).label], ['warning', 'options: stale, pre-fix packet — re-evaluate · file claimed 1 qualified, not trusted'])
eq('unverified is a warning', optionsAltChip({ status: 'PACKET_UNVERIFIED', reason: 'x' }).tone, 'warning')
eq('OK with zero is neutral', optionsAltChip({ status: 'OPTIONS_ALT_OK', qualified_count: 0, considered: 4 }).tone, 'neutral')
eq('OK with one is the only green', optionsAltChip({ status: 'OPTIONS_ALT_OK', qualified_count: 1, strategy: 'debit_call_vertical', gate_version: '2026-09-28', evaluated_at: 't' }), { tone: 'success', label: 'options: 1 qualified (debit call vertical)', title: 'gate 2026-09-28 · evaluated t' })
eq('none qualified reason', optionsAltChip({ status: 'OPTIONS_ALT_NONE', reason: 'NONE_QUALIFIED', considered: 3 }).label, 'options: none qualified · 3 considered')
eq('legacy claim alone is never green', optionsAltChip({ status: 'OPTIONS_ALT_OK', qualified_count: 0, claimed: { qualified: ['long_call'] } }).tone, 'neutral')
eq('null', optionsAltChip(null).tone, 'neutral')

if (failed) throw new Error(`entryAlerts: ${failed} failed`)
console.log('[entryAlerts] ok')

// node src/lib/optionChainTruth.test.ts — chain truth helpers (no node:assert: CI tsc has no @types/node)
import { ageLabel, chainStatusMessage, executableNet, legsFromProposal, quoteAgeSeconds, quoteLabel, spreadPct } from './optionChainTruth.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) { const g = JSON.stringify(got), w = JSON.stringify(want); if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) } }

eq('two-sided → Mid, never executable', quoteLabel({ bid: 5.9, ask: 9.5 }), { value: 7.7, label: 'Mid', executable: false })
eq('bid 0 → Last, not Mid', quoteLabel({ bid: 0, ask: 11.3, last: 0.5 }), { value: 0.5, label: 'Last', executable: false })
eq('bid 0, last 0 → Ask only', quoteLabel({ bid: 0, ask: 11.3, last: 0 }), { value: 11.3, label: 'Ask only', executable: false })
eq('crossed → not Mid', quoteLabel({ bid: 9.5, ask: 5.9, last: 7 }).label, 'Last')
eq('nothing → —', quoteLabel({}), { value: null, label: '—', executable: false })
eq('server two_sided false wins', quoteLabel({ bid: 5.9, ask: 9.5, two_sided: false, last: 7.45 }).label, 'Last')

eq('spread% computed', spreadPct({ bid: 5.9, ask: 9.5 }), 46.8)
eq('spread% server value wins', spreadPct({ bid: 5.9, ask: 9.5, spread_pct: 46.75 }), 46.75)
eq('spread% one-sided null', spreadPct({ bid: 0, ask: 11.3 }), null)

const now = Date.parse('2026-09-28T15:53:00Z')
eq('age seconds', quoteAgeSeconds('2026-09-28T15:52:18Z', now), 42)
eq('age garbage null', quoteAgeSeconds('nope', now), null)
eq('age labels', [ageLabel(42), ageLabel(600), ageLabel(7200), ageLabel(null)], ['42s ago', '10m ago', '2h ago', 'no quote time'])

eq('ok → null', chainStatusMessage('ok', true), null)
eq('http failure first', chainStatusMessage('ok', false, null, 502)?.title, 'Command Center API error (HTTP 502)')
eq('reauth is danger', chainStatusMessage('needs_reauth', true, 'HTTP 401')?.tone, 'danger')
eq('empty is warning', chainStatusMessage('empty', true)?.tone, 'warning')
eq('unknown status falls to error', chainStatusMessage('weird', true)?.title, 'Chain fetch failed')

const rows = [
  { exp: '2026-11-20', strike: 520, side: 'put' as const, bid: 31.75, ask: 34.05 },
  { exp: '2026-11-20', strike: 500, side: 'put' as const, bid: 24.2, ask: 25.4 },
  { exp: '2026-11-20', strike: 225, side: 'put' as const, bid: 0, ask: 11.3 },
]
const spread = executableNet([{ role: 'short', side: 'put', strike: 520 }, { role: 'long', side: 'put', strike: 500 }], rows, 1)
eq('credit spread: sell short at bid, buy long at ask', [spread.perContract, spread.kind, spread.net, spread.reason], [6.35, 'credit', 635, null])
const missing = executableNet([{ role: 'short', side: 'put', strike: 520 }, { role: 'long', side: 'put', strike: 480 }], rows)
eq('missing leg refuses and names it', [missing.net, missing.reason], [null, 'long put $480 is not in the chain window'])
const noBid = executableNet([{ role: 'short', side: 'put', strike: 225 }], rows)
eq('no bid refuses', [noBid.net, noBid.reason], [null, 'short put $225 has no bid'])
const longCall = executableNet([{ role: 'long', side: 'call', strike: 46 }], [{ exp: 'x', strike: 46, side: 'call', bid: 0.25, ask: 2.25 }], 1)
eq('long call debit at ask', [longCall.perContract, longCall.kind, longCall.net], [-2.25, 'debit', -225])

eq('legs: credit spread', legsFromProposal({ strategy: 'credit_spread', option_type: 'put', short_strike: 520, long_strike: 500 }), [{ role: 'short', side: 'put', strike: 520 }, { role: 'long', side: 'put', strike: 500 }])
eq('legs: csp short', legsFromProposal({ strategy: 'cash_secured_put', strike: 12 }), [{ role: 'short', side: 'put', strike: 12 }])
eq('legs: protective put long', legsFromProposal({ strategy: 'protective_put', strike: 225 }), [{ role: 'long', side: 'put', strike: 225 }])
eq('legs: covered call short call', legsFromProposal({ strategy: 'covered_call', strike: 157.5 }), [{ role: 'short', side: 'call', strike: 157.5 }])
eq('legs: none without strike', legsFromProposal({ strategy: 'long_call' }), [])

if (failed) throw new Error(`optionChainTruth: ${failed} failed`)
console.log('[optionChainTruth] ok')

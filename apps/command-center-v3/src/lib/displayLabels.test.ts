// P3 2026-10-23: display labels (strategy ids, header TRADING / price / VIX faces, rotation chips).
// Runs in the CC-v3 build:  node --experimental-strip-types src/lib/displayLabels.test.ts
import { humanizeIdentifier, looksLikeIdentifier, shortPriceSource, shortPriceStamp, slotClock, tradingTileValue, vixProvenance } from './displayLabels.ts'
import { rotationAvailability, rotationReasonChips } from './rotationPublication.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean, got?: unknown) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}${got !== undefined ? ` — got ${JSON.stringify(got)}` : ''}`) }
}
const eq = (name: string, got: unknown, want: unknown) => check(name, JSON.stringify(got) === JSON.stringify(want), got)

// Strategy leaderboard (captured /v3/strategy 2026-10-22).
eq('fib_retracement_bounce', humanizeIdentifier('fib_retracement_bounce'), 'Fib Retracement Bounce')
eq('acronym kept upper-case', humanizeIdentifier('pullback_macd_reversal'), 'Pullback MACD Reversal')
eq('REIT acronym', humanizeIdentifier('reit_income'), 'REIT Income')
eq('assessment maintain_current', humanizeIdentifier('maintain_current'), 'Maintain Current')
eq('assessment review_risk_reward', humanizeIdentifier('review_risk_reward'), 'Review Risk Reward')
eq('minor word stays lower-case mid-label', humanizeIdentifier('break_of_structure'), 'Break of Structure')
eq('kebab case', humanizeIdentifier('swing-breakout'), 'Swing Breakout')
eq('single word capitalised', humanizeIdentifier('screener'), 'Screener')
eq('already human text unchanged', humanizeIdentifier('Maintain current allocation'), 'Maintain current allocation')
eq('mixed case unchanged', humanizeIdentifier('Momentum_Scalp'), 'Momentum_Scalp')
eq('null / empty → empty string', [humanizeIdentifier(null), humanizeIdentifier('')], ['', ''])
check('looksLikeIdentifier', looksLikeIdentifier('a_b') && !looksLikeIdentifier('a b') && !looksLikeIdentifier('abc'))

// Header TRADING tile: "trades" dropped; the P&L survives.
eq('TRADING value', tradingTileValue(47.9, 238, '$25,505'), '47.9% win · 238 · $25,505 P&L')
check('TRADING value no longer repeats "trades"', !/trades/.test(tradingTileValue(47.9, 238, '$25,505')))
eq('TRADING without count', tradingTileValue(50, 0, '$1'), '50% win · $1 P&L')
eq('TRADING without P&L', tradingTileValue(50, 3, null), '50% win · 3')
eq('TRADING face without a journal win rate', tradingTileValue(null, 3, '$1'), '—')

// Header price stamp and VIX provenance (captured /api/v2/overview + trade-ai/summary 2026-10-22).
eq('price source short', shortPriceSource('finviz_afterhours'), 'after-hours')
eq('unknown price source readable', shortPriceSource('some_feed'), 'some feed')
eq('price stamp face', shortPriceStamp('16:45 ET', 'finviz_afterhours', 12, 12, false), 'Prices 16:45 ET · after-hours · 12/12')
check('price stamp face fits the 210 px stamp column (≤ 40 chars)', shortPriceStamp('16:45 ET', 'finviz_afterhours', 12, 12, false).length <= 40)
eq('price stamp degraded', shortPriceStamp('16:45 ET', 'finviz', 11, 12, true), 'Prices 16:45 ET · Finviz · 11/12 DEGRADED')
eq('price stamp without coverage', shortPriceStamp(null, 'schwab'), 'Prices · Schwab')
eq('slot clock', [slotClock('1730'), slotClock('0700'), slotClock('premarket'), slotClock(null)], ['17:30', '07:00', 'premarket', null])
eq('VIX from a scanner run', vixProvenance('trade_ai_run_summary', '1730', '22:21 ET'), 'scanner · 17:30 run')
eq('VIX from a feed', vixProvenance('cboe', null, '15:59 ET'), 'CBOE · 15:59 ET')
eq('VIX source unknown', vixProvenance(null, null, null), 'source —')

// Rotation withheld notice chips (captured rotation/summary publication, 2026-10-23).
const withheld = rotationAvailability({ ok: true, publication: { schema: 'RotationPublication@v1', status: 'UNAVAILABLE',
  reasons: ['account_stale', 'position_evidence_stale', 'unsupported_stop_claim'] } })
eq('reason chips', rotationReasonChips(withheld), ['account data stale', 'position evidence stale', 'stop claim unsupported'])
eq('duplicate meanings collapse', rotationReasonChips({ ...withheld, reasons: ['account_stale', 'account_evidence_stale'] }), ['account data stale'])
eq('unknown code shown as words', rotationReasonChips({ ...withheld, reasons: ['brand_new_code'] }), ['brand new code'])

console.log(`displayLabels: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)

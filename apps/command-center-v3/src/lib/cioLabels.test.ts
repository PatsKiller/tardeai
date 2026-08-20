// Pure tests for cioLabels.ts
//   node apps/command-center-v3/src/lib/cioLabels.test.ts
import { cioLabel, formatAsOfET, CIO_FIELD_LABELS } from './cioLabels.ts'

declare const process: { exit(code?: number): never }

let pass = 0, fail = 0
function check(name: string, cond: boolean) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) }
  else { fail++; console.log(`  [FAIL] ${name}`) }
}

console.log('cioLabels')

check('perf_QTD mapped', cioLabel('perf_QTD') === 'QTD performance')
check('perf_true_TWR mapped', cioLabel('perf_true_TWR') === 'True TWR')
check('style_value_blend_growth mapped', cioLabel('style_value_blend_growth') === 'Style: value/blend/growth')
check('cash_band_min_pct mapped', cioLabel('cash_band_min_pct') === 'Cash band min %')
check('unknown snake fallback', cioLabel('some_new_field') === 'Some New Field')
check('empty → em dash', cioLabel('') === '—')
check('null → em dash', cioLabel(null) === '—')
check('catalog has core keys', Boolean(CIO_FIELD_LABELS.perf_QTD && CIO_FIELD_LABELS.cash_band_min_pct))

{
  const s = formatAsOfET('2026-08-20T11:59:11Z')
  check('as-of contains ET', /EDT|EST/.test(s))
  check('as-of contains UTC suffix', s.includes('UTC'))
  check('as-of null → em dash', formatAsOfET(null) === '—')
}

console.log(`cioLabels: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

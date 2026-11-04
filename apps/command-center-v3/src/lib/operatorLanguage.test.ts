// FQ-035 / FQ-050 / FQ-055 / FQ-057: operator-facing words for internal identifiers.
// Runs in the CC-v3 build:  node --experimental-strip-types src/lib/operatorLanguage.test.ts
import { absenceWords, componentLabel, sentenceIdentifiers } from './operatorLanguage.ts'
declare const process: { exit(code?: number): void }
let pass = 0, fail = 0
function check(name: string, cond: boolean, got?: unknown) {
  if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}${got !== undefined ? ` — got ${JSON.stringify(got)}` : ''}`) }
}
const eq = (name: string, got: unknown, want: unknown) => check(name, JSON.stringify(got) === JSON.stringify(want), got)

// The exact string the audit found on /health desktop (health.data.json, FQ-035).
eq('health component label', componentLabel('data_quality:data_source_stale'), 'Data quality · Data source stale')
eq('second audited component', componentLabel('data_quality:news_symbol_mismatch'), 'Data quality · News symbol mismatch')
eq('single known key', componentLabel('risk_protection'), 'Risk protection')
eq('unknown key still humanised', componentLabel('brand_new_signal'), 'Brand New Signal')
eq('plain text untouched', componentLabel('Coverage by Source'), 'Coverage by Source')
eq('empty component', componentLabel(null), '')

// Sentences: identifiers become words; ordinary text is returned byte for byte.
eq('why line', sentenceIdentifiers('data_quality signal needs review.'), 'Data quality signal needs review.')
eq('identifier inside prose', sentenceIdentifiers('Schwab journal ingest has no log — trade_closed may never have been populated from Schwab.'),
  'Schwab journal ingest has no log — Trade Closed may never have been populated from Schwab.')
eq('no identifiers means no change', sentenceIdentifiers('Operator review and monitor.'), 'Operator review and monitor.')
eq('trailing punctuation kept', sentenceIdentifiers('check pullback_macd_reversal,'), 'check Pullback MACD Reversal,')
eq('hyphenated English is not an identifier', sentenceIdentifiers('A well-known after-hours read.'), 'A well-known after-hours read.')
eq('kebab ids are labels, not prose', sentenceIdentifiers('source swing-breakout failed'), 'source swing-breakout failed')

// A dash must say which absence it is.
eq('not measured', absenceWords('measured', 'Credit'), 'Credit not measured')
eq('unavailable', absenceWords('unavailable'), 'unavailable')
eq('not applicable', absenceWords('not-applicable', 'Next run'), 'Next run not applicable')

console.log(`operatorLanguage: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)

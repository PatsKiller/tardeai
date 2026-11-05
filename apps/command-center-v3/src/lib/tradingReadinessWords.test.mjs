// node --experimental-strip-types src/lib/tradingReadinessWords.test.mjs
// FQ-072 (/trading E): the opportunity readiness strip printed the raw producer status
// (RUN_UNDERFILLED, …) in its primary flow. The words come from the existing operator dictionary
// (lib/homeLabels.plain); an untranslated status still renders raw, which is the documented
// additive-rendering rule, so this test pins both the translations and the page wiring.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { plain } from './homeLabels.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

check(plain('RUN_UNDERFILLED') === 'scan ran thin (few symbols)', 'RUN_UNDERFILLED has no operator translation')
check(plain('MANUAL_REVIEW') === 'manual review', 'MANUAL_REVIEW has no operator translation')
check(plain('NOT_A_REAL_STATUS') === null, 'an untranslated status must return null so it renders raw rather than being relabelled')

const page = readFileSync(join(HERE, '../pages/TradingHub.tsx'), 'utf8')
check(/import \{[^}]*plain[^}]*\} from '\.\.\/lib\/homeLabels'/.test(page), 'TradingHub does not import the operator dictionary')
check(/healthStatusWords = plain\(/.test(page), 'TradingHub does not derive operator words for the run status')
const rendered = (page.match(/\{healthStatusWords\}/g) || []).length
check(rendered >= 3, `only ${rendered} render site(s) use the operator words; the raw status is still shown in the primary flow`)
check(/title=\{healthCodes\.length \? `\$\{healthCodes\.join\(', '\)\} · \$\{healthStatusLabel\}` : healthStatusLabel\}/.test(page),
  'the raw status code is no longer reachable from the chip title')

if (failed) { console.error(`tradingReadinessWords: ${failed} failure(s)`); process.exit(1) }
console.log('tradingReadinessWords: ok')

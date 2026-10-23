import { clipAtWord } from './clipText.ts'
declare const process: { exit(code?: number): never }
let pass = 0, fail = 0
function check(name: string, cond: boolean) { if (cond) { pass++; console.log(`  [PASS] ${name}`) } else { fail++; console.log(`  [FAIL] ${name}`) } }
const s = 'Relisted — No Stop-Out. Market reconnection event (relist #1). Price discovery continuing; not a strategy failure. Price $35.21 above original stop $33.12 today'
const c = clipAtWord(s, 150)
check('never cuts inside a number', !/\$\d*…$/.test(c) && !/\$\d+\.\d*…$/.test(c))
check('ends with ellipsis when clipped', c.endsWith('…') && c.length <= 151)
check('short text untouched', clipAtWord('short text', 150) === 'short text')
check('null-safe', clipAtWord(null) === '' && clipAtWord(undefined) === '')
check('whitespace collapsed', clipAtWord('a   b') === 'a b')
console.log(`clipText: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)

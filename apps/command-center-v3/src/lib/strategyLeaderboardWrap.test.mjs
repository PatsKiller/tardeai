// node src/lib/strategyLeaderboardWrap.test.mjs
// FQ-064 (/strategy D): leaderboard result cells wrapped inside the number on a phone (e.g. a P&L or
// "1,234 · 1.83R" split across lines). The numeric cells must not wrap, and the table must scroll
// horizontally rather than squeeze its columns.
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

const src = readFileSync(join(HERE, '../pages/StrategyHub.tsx'), 'utf8')
check(/const th = \{[^}]*whiteSpace: 'nowrap'/.test(src), 'leaderboard header cells can still wrap')
check(/const td = \{[^}]*whiteSpace: 'nowrap'/.test(src), 'leaderboard result cells can still wrap inside a number')
check(/overflowX: 'auto'/.test(src), 'the leaderboard table no longer scrolls horizontally, so nowrap would clip columns')

if (failed) { console.error(`strategyLeaderboardWrap: ${failed} failure(s)`); process.exit(1) }
console.log('strategyLeaderboardWrap: ok')

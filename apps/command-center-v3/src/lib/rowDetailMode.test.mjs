// node --experimental-strip-types src/lib/rowDetailMode.test.mjs
// FQ-043: a phone must open the full ticket as a full-screen sheet, not expand it inline in a long list.
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { rowDetailMode, nextDetailState, SHEET_MAX_WIDTH } from './rowDetailMode.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

check(rowDetailMode(390) === 'sheet', 'a 390 px phone expands inline instead of opening a full-screen detail')
check(rowDetailMode(412) === 'sheet', 'a 412 px phone expands inline')
check(rowDetailMode(SHEET_MAX_WIDTH) === 'sheet', 'the boundary width does not use the sheet')
check(rowDetailMode(SHEET_MAX_WIDTH + 1) === 'inline', 'a desktop width was forced into a sheet')
check(rowDetailMode(null) === 'inline', 'an unknown width was guessed as a phone')

const desk = readFileSync(join(HERE, '../pages/ManualTosDesk.tsx'), 'utf8')
check(/currentRowDetailMode\(\)/.test(desk), 'the desk does not choose sheet vs inline from the viewport')
check(/manual-desk-detail-sheet/.test(desk), 'the desk has no full-screen detail sheet')
check(/role="dialog"/.test(desk), 'the detail sheet is not a dialog')
check(/onSetField=\{setField\}/.test(desk), 'the sheet does not render the real row (field editing lost)')
check(/keep the inline path|openRows/.test(desk), 'the inline path was removed instead of kept for wide screens')

// codex B2 (2026-11-04): pressing the phone detail control on the OPEN sheet must CLOSE it.
const closed = nextDetailState('sheet', 'WATCHLIST-1', 'WATCHLIST-1', {})
check(closed.sheetKey === null, 'phone Hide details left the sheet open (it re-set the same key)')
const opened = nextDetailState('sheet', null, 'WATCHLIST-2', {})
check(opened.sheetKey === 'WATCHLIST-2', 'phone Show details did not open the row')
const inline = nextDetailState('inline', null, 'WATCHLIST-1', { 'WATCHLIST-1': true })
check(inline.openFlags['WATCHLIST-1'] === false, 'the inline control did not collapse the open row')

// codex P1 at f5586fdd1 (PR 2599): the exit used to run BEFORE these toggle assertions, so a
// nextDetailState regression printed FAIL and still exited 0 — scripts/run-tests.mjs reads the exit
// status, so that regression would have passed the build. There is now exactly one summary/exit at
// the end, after every check, so any failure here fails the run.
if (failed) { console.error(`rowDetailMode: ${failed} failure(s)`); process.exit(1) }
console.log('rowDetailMode: ok')

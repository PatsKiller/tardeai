// node --experimental-strip-types src/lib/conflictRulesDecisionGap.test.ts
// FQ-007 (/conflicts/rules F). Measured live 2026-11-04: proposals [], total 0, unmatched 16 — nothing
// awaited the operator, 16 cases awaited an AI proposal, and the page said both "nothing needs a decision"
// and "awaiting your approval". These helpers are what the page renders; the last check pins that the page
// actually uses them.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { decisionGapText, proposalsHeading, proposalsIntro } from './conflictRulesModel.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
let failed = 0
const check = (ok, msg) => { if (!ok) { failed++; console.error('FAIL ' + msg) } }

// 1. The live shape: 0 awaiting the operator, 16 awaiting an AI proposal.
const gap = decisionGapText(0, 16)
check(/16 cases/.test(gap), 'the summary does not account for the 16 cases')
check(/await an AI rule proposal/.test(gap), 'the summary does not say what those cases are waiting for')
check(/Nothing is waiting for your approval/.test(gap), 'the summary does not say clearly that the operator has nothing to approve')
check(!/Nothing on this page needs a decision/.test(gap), 'the summary still claims nothing needs a decision while 16 cases are listed')

check(!/awaiting your approval/i.test(proposalsHeading(0, 16)), 'the heading claims operator approval when no proposal exists')
check(/awaiting an AI proposal/i.test(proposalsHeading(0, 16)), 'the heading does not name what the cases await')
check(/awaiting your approval/i.test(proposalsHeading(1, 16)), 'the heading no longer names operator approval when a proposal exists')
check(/nothing for you to approve/i.test(proposalsIntro(0)), 'the intro claims an AI drafted a rule when none exists')
check(/until you approve/i.test(proposalsIntro(1)), 'the intro no longer describes a real proposal')

// 2. Truly empty page keeps the old, correct sentence.
check(decisionGapText(0, 0) === 'Nothing on this page needs a decision right now.',
  'the empty page no longer says nothing needs a decision')

// 3. The page must actually render these helpers, or this test proves nothing about the page.
const page = readFileSync(join(HERE, '../pages/ConflictRules.tsx'), 'utf8')
check(/decisionGap=\{decisionGapText\(/.test(page), 'ConflictRules.tsx does not use decisionGapText')
check(/\{proposalsHeading\(/.test(page), 'ConflictRules.tsx does not use proposalsHeading')
check(/\{proposalsIntro\(/.test(page), 'ConflictRules.tsx does not use proposalsIntro')
check(!/awaiting your approval<\/h2>/.test(page), 'ConflictRules.tsx still hardcodes the "awaiting your approval" heading')

if (failed) { console.error(`conflictRulesDecisionGap: ${failed} failure(s)`); process.exit(1) }
console.log('conflictRulesDecisionGap: ok')

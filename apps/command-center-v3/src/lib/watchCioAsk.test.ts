// node --experimental-strip-types src/lib/watchCioAsk.test.ts
declare const process: { exit(code?: number): never }
import { STANCE_GAP, WATCH_ASK_QUESTION_CHARS, finishAsk, stanceFromAskPayload, watchAskQuestion } from './watchCioAsk.ts'

let failed = 0
function eq(name: string, got: unknown, want: unknown) {
  const g = JSON.stringify(got), w = JSON.stringify(want)
  if (g !== w) { failed++; console.error(`FAIL ${name}: got ${g} want ${w}`) }
}
function ok(name: string, cond: boolean) {
  if (!cond) { failed++; console.error(`FAIL ${name}`) }
}

const row = {
  symbol: 'SYM001',
  stance: 'WATCH',
  conviction: 61,
  why: 'Synthetic setup',
  summary: 'Synthetic summary',
  price: 12.5,
  price_as_of: '2026-10-23T19:45:00Z',
  conflicts: [{ kind: 'k', summary: 'Card fact A vs B', a: { value: 1, source: null, at: null }, b: { value: 2, source: null, at: null } }],
  next_action: { kind: 'resolve_conflict', label: 'Resolve conflict', reason: 'what would change the stance' },
}

const question = watchAskQuestion(row)
ok('question names the review', question.startsWith('Review SYM001 for my watchlist: stance, conviction, what would change it'))
ok('question carries the card facts', question.includes('Card stance: WATCH') && question.includes('Card conviction: 61') && question.includes('Price: 12.5'))
ok('question stays inside the ask limit', question.length <= WATCH_ASK_QUESTION_CHARS)

const wide = watchAskQuestion({ ...row, why: 'x'.repeat(4000) })
eq('a long card fact is clipped', wide.length, WATCH_ASK_QUESTION_CHARS)
ok('the clipped question still starts with the review', wide.startsWith('Review SYM001 for my watchlist:'))

const leaked = watchAskQuestion({ ...row, account_number: '12345678', quantity: 40 } as typeof row)
ok('an account number is not copied into the question', !leaked.includes('12345678'))
ok('a quantity is not copied into the question', !/quantity/i.test(leaked))

eq('prose is not a stance', stanceFromAskPayload({ answer_text: 'Stance: ADD', thread_id: 't1' }), { stance: null, stanceGap: STANCE_GAP })
eq('a structured stance string is kept', stanceFromAskPayload({ stance: ' ADD ', answer_text: 'ignore' }), { stance: 'ADD', stanceGap: null })

const failedAsk = finishAsk({ askOk: false, askMessage: 'Ask the CIO is turned off (config/cio_ask.json).', queueMessage: 'CIO review queued.' })
eq('an ask failure leads', failedAsk.phase === 'failed' && failedAsk.message.startsWith('Ask the CIO'), true)
eq('a queue success does not replace the ask failure', failedAsk.message.includes('CIO review queued.'), false)
eq('the queue result stays a separate note', failedAsk.queueNote, 'CIO review queued.')

const answered = finishAsk({ askOk: true, askMessage: 'Answered', threadId: 'thread-sym', stance: null, queueMessage: 'Could not queue: HTTP 500' })
eq('a thread with no stance is answered', answered.phase, 'answered')
eq('the stance gap is explicit', answered.stanceGap, STANCE_GAP)
eq('a queue failure does not replace the answer', answered.message, 'Answered')
eq('the queue failure stays a note', answered.queueNote, 'Could not queue: HTTP 500')
eq('the thread id is kept', answered.threadId, 'thread-sym')

eq('no thread is a failure', finishAsk({ askOk: true, askMessage: 'The CIO did not return a thread.', threadId: null }).phase, 'failed')

if (failed) { console.error(`watchCioAsk: ${failed} failure(s)`); process.exit(1) }
console.log('watchCioAsk: all checks passed')

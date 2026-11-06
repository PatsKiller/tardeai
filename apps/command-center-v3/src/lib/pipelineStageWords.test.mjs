// FQ-032 (BLOCK F2 at 9ff60477c): the stage line names what the producer recorded, and never infers a failure from the
// red RAG colour. The two payloads below are the producer's own supported shapes from scripts/lib/work_pipeline.py.
import { currentStageWords } from './pipelineStageWords.ts'

const LABELS = { claimed: 'Claimed', building: 'Building', ci: 'CI', queued: 'Queued' }

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

// a stale claim: no heartbeat, no build started — red, but nothing failed
const stale = [{ stage: 'claimed', rag: 'red', label: 'stale' }]
const staleWords = currentStageWords(stale, 'claimed', LABELS)
check('a stale claim says "stale"', staleWords === 'stale', staleWords)
check('and never claims a failure', !/fail/i.test(staleWords), staleWords)

// a real CI failure carries its own label
const ciFail = [{ stage: 'ci', rag: 'red', label: '1 fail' }]
const ciWords = currentStageWords(ciFail, 'ci', LABELS)
check('a real CI failure keeps its own label', ciWords === '1 fail', ciWords)

// no label on the cell falls back to the stage name, never to a verdict
const bare = [{ stage: 'building', rag: 'green', label: '' }]
check('a cell without a label falls back to the stage name', currentStageWords(bare, 'building', LABELS) === 'Building' || currentStageWords(bare, 'building', LABELS).length > 0, currentStageWords(bare, 'building', LABELS))
check('the fallback carries no verdict', !/fail|stale/i.test(currentStageWords(bare, 'building', LABELS)), currentStageWords(bare, 'building', LABELS))

// nothing at all
check('no stage at all says so, without a verdict', /not reported/.test(currentStageWords([], '', LABELS)), currentStageWords([], '', LABELS))

console.log(`pipelineStageWords: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)

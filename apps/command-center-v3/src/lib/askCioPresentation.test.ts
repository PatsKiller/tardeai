import { answerForAsk, answerPresentation, answerSourceTime, askUpdate, keepNewestAnswer, keepNewestThread, matchingThread, newerHeaderAnswer, readableAnswerForAsk, readableVersion, statusForAsk, threadVersionKey } from './askCioPresentation.ts'
import type { AnswerVersion, Thread } from './askCioModel.ts'
function equal(actual: unknown, expected: unknown) { if (actual !== expected) throw new Error(`${String(actual)} != ${String(expected)}`) }
const quick: AnswerVersion = { version:1,status:'quick',depth:'quick',summary:'Exact saved answer.\n\nIts reasoning remains intact.',produced_at:'2032-04-12T14:30:00Z',sources:[{title:'Stored evidence',kind:'fixture',as_of:'2032-04-12T14:29:00Z'}] }
const deep: AnswerVersion = {...quick,version:2,status:'deep',depth:'deep',summary:'This research is partial.\n\nExact saved deep answer, with its reasons.',produced_at:'2032-04-12T14:31:00Z'}
const thread: Thread = {thread_id:'fixture-thread',title:'Fixture question',created_at:quick.produced_at,updated_at:quick.produced_at,status:'deep_pending',channels:['cc'],turns:[{ask_id:'fixture-ask',question:'Fixture question',channel:'cc',asked_at:quick.produced_at,turn_kind:'ask',answers:[quick]}],entities:[],reanswers:0}
const completed: Thread = {...thread,status:'deep',updated_at:deep.produced_at,turns:[{...thread.turns[0],answers:[quick,deep]}]}
const initial={thread_id:thread.thread_id,ask_id:'fixture-ask',thread}
equal(answerPresentation(deep).text,deep.summary)
equal(answerPresentation(quick).sources,quick.sources)
equal(matchingThread({ok:true,data:{thread}},thread.thread_id),thread)
equal(matchingThread({thread},'another-thread'),null)
equal(matchingThread({thread:{...thread,turns:[null]}},thread.thread_id),null)
equal(matchingThread({ok:false,data:{thread}},thread.thread_id),null)
equal(answerForAsk(completed,'fixture-ask'),deep)
equal(answerForAsk(completed,'another-ask'),null)
equal(newerHeaderAnswer(initial,thread),null)
equal(newerHeaderAnswer(initial,completed),deep)
equal(newerHeaderAnswer(initial,{...completed,thread_id:'another-thread'}),null)
equal(newerHeaderAnswer({...initial,ask_id:'another-ask'},completed),null)
equal(newerHeaderAnswer({...initial,thread:completed},thread),null)
equal(statusForAsk(thread,'fixture-ask'),'deep_pending')
equal(statusForAsk(completed,'fixture-ask'),'deep')
const differentPending: Thread={...completed,status:'deep_pending',turns:[...completed.turns,{...thread.turns[0],ask_id:'another-ask',answers:[quick]}]}
equal(statusForAsk(differentPending,'fixture-ask'),'deep')
equal(statusForAsk(differentPending,'another-ask'),'deep_pending')
equal(threadVersionKey(thread)===threadVersionKey(completed),false)
equal(threadVersionKey(thread),threadVersionKey({...thread}))
equal(askUpdate({detail:{threadId:'fixture-thread',source:'header'}} as unknown as Event)?.threadId,'fixture-thread')
equal(askUpdate({detail:{threadId:'fixture-thread',source:'unrecognised'}} as unknown as Event),null)
equal(answerSourceTime('2032-04-12'),'2032-04-12 (date only)')
equal(answerSourceTime('2032-04-12 14:30:00'),'2032-04-12 14:30:00 (timezone unavailable)')
equal(answerSourceTime('2032-04-12T14:30:00Z'),'Apr 12, 10:30 AM ET')
equal(keepNewestAnswer(deep,quick),deep)
equal(keepNewestAnswer(quick,deep),deep)
equal(keepNewestAnswer(deep,null),deep)
equal(keepNewestThread(completed,thread),completed)
equal(keepNewestThread(thread,completed),completed)
equal(keepNewestThread(completed,{...completed,turns:[]}),completed)
equal(keepNewestThread(completed,{...completed,updated_at:quick.produced_at}),completed)
const queued: AnswerVersion={...quick,version:2,status:'deep_pending',summary:'Actual saved pending notice.'}
const pendingTurn={...thread.turns[0],answers:[quick,queued]}
equal(readableVersion(pendingTurn),quick)
equal(readableAnswerForAsk({...thread,turns:[pendingTurn]},'fixture-ask'),quick)
equal(newerHeaderAnswer(initial,{...thread,turns:[pendingTurn]}),null)
console.log('askCioPresentation: verbatim body, source references, matching identities, monotonic versions and update events passed')

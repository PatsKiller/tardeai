/** Presentation and refresh identity only. The backend owns canonical prose and all financial facts. */
import { currentVersion, unwrap, type AnswerVersion, type AskStatus, type Thread, type Turn } from './askCioModel.ts'

export const ASK_UPDATED_EVENT = 'cc-cio-ask-updated'
export type AskUpdate = { threadId: string; source: 'mutation' | 'header' | 'thread' }

export function publishAskUpdate(detail: AskUpdate): void {
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(ASK_UPDATED_EVENT, { detail }))
}
export function askUpdate(event: Event): AskUpdate | null {
  const d = (event as CustomEvent).detail
  return d && typeof d.threadId === 'string' && ['mutation','header','thread'].includes(d.source) ? d : null
}
export function matchingThread(raw: unknown, threadId: string): Thread | null {
  const t = unwrap<{ thread?: Thread }>(raw)?.thread
  return t?.thread_id === threadId && Array.isArray(t.entities) && Array.isArray(t.channels)
    && Array.isArray(t.turns) && t.turns.every(turn => turn && typeof turn.ask_id === 'string' && Array.isArray(turn.answers)
      && turn.answers.every(answer => answer && Number.isFinite(answer.version) && typeof answer.summary === 'string')) ? t : null
}
export function answerForAsk(thread: Thread | null | undefined, askId: string): AnswerVersion | null {
  const turn = thread?.turns.find(turn => turn.ask_id === askId)
  return turn ? currentVersion(turn) : null
}
/** A queued/running status record does not replace the actual saved answer's reasoning. */
export function readableVersion(turn: Turn): AnswerVersion | null {
  return currentVersion({ ...turn, answers: turn.answers.filter(answer => answer.status !== 'deep_pending') }) ?? currentVersion(turn)
}
export function readableAnswerForAsk(thread: Thread | null | undefined, askId: string): AnswerVersion | null {
  const turn = thread?.turns.find(turn => turn.ask_id === askId)
  return turn ? readableVersion(turn) : null
}
export function newerHeaderAnswer(initial: { ask_id: string; thread_id: string; thread: Thread | null }, live: Thread | null): AnswerVersion | null {
  if (live?.thread_id !== initial.thread_id) return null
  const answer = readableAnswerForAsk(live, initial.ask_id), baseline = answerForAsk(matchingThread({ thread: initial.thread }, initial.thread_id), initial.ask_id)
  return answer && answer.version > (baseline?.version ?? 0) ? answer : null
}
export function statusForAsk(thread: Thread | null | undefined, askId: string): AskStatus {
  if (thread?.status === 'deep_pending' && thread.turns[thread.turns.length - 1]?.ask_id === askId) return 'deep_pending'
  return answerForAsk(thread, askId)?.status ?? 'quick'
}
export function keepNewestAnswer(previous: AnswerVersion | null, next: AnswerVersion | null): AnswerVersion | null {
  return next && (!previous || next.version > previous.version) ? next : previous
}
/** An append-only thread snapshot cannot lose an observed turn/version or move its source clock backwards. */
export function keepNewestThread(previous: Thread | null, next: Thread | null): Thread | null {
  if (!next) return previous
  if (!previous || previous.thread_id !== next.thread_id) return next
  if (previous.turns.some(turn => {
    const candidate = next.turns.find(item => item.ask_id === turn.ask_id)
    return !candidate || (currentVersion(candidate)?.version ?? 0) < (currentVersion(turn)?.version ?? 0)
  })) return previous
  const before = Date.parse(previous.updated_at), after = Date.parse(next.updated_at)
  return Number.isFinite(before) && Number.isFinite(after) && after < before ? previous : next
}
export function threadVersionKey(thread: Thread): string {
  return JSON.stringify([thread.thread_id, thread.status, thread.updated_at,
    thread.turns.map(turn => [turn.ask_id, turn.answers.map(answer => [answer.answer_id, answer.version, answer.status, answer.produced_at])])])
}
/** Verbatim canonical text: never strip prose, round embedded numbers or infer a different answer in the browser. */
export function answerPresentation(answer: Pick<AnswerVersion, 'summary' | 'sources'>): { text: string; sources: NonNullable<AnswerVersion['sources']> } {
  return { text: answer.summary, sources: answer.sources ?? [] }
}
export function answerSourceTime(value: string): string {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${value} (date only)`
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)) return `${value} (timezone unavailable)`
  const time = Date.parse(value)
  return Number.isFinite(time) ? new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }).format(time) + ' ET' : 'time unavailable'
}

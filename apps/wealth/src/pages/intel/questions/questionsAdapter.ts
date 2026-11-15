import { accountMap, body, record, rows, safeText, safeUrl, state, text } from '../../home/homeAdapter.ts'
import type { Read, Row } from '../../home/homeAdapter.ts'
export const QUESTIONS_PATH = '/api/v2/cio/asks'
export function questionPath(id?: string): string | null {
 if (id === undefined) return QUESTIONS_PATH
 if (!/^thr_[0-9a-f]{16}$/.test(id)) return null
 return QUESTIONS_PATH + '/' + encodeURIComponent(id)
}
export interface Question { ref: string | null; title: string; excerpt: string; updated: string; status: string; symbols: string[] }
export function questionsModel(r: Row): Question[] {
 const labels = accountMap(r)
 return rows(r.threads).map(t => ({
  ref: /^thr_[0-9a-f]{16}$/.test(text(t.thread_id)) ? text(t.thread_id) : null,
  title: safeText(t.title, labels), excerpt: safeText(t.last_answer_excerpt, labels), updated: text(t.updated_at),
  status: safeText(t.status, labels), symbols: rows(t.entities).map(e => text(e.symbol)).filter(Boolean),
 }))
}
export function questionsState(read: Read, now: number) {
 // The list's as_of is _now() at request time, not ledger freshness or the answer date.
 return state(read, questionsModel, now, undefined, questions => questions.length === 0)
}
export interface Answer { summary: string; at: string; status: string; changed: string; sources: { title: string; kind: string; asOf: string; url: string | null }[] }
export interface QuestionDetail { title: string; updated: string; turns: { question: string; asked: string; answers: Answer[] }[] }
export function questionDetailModel(r: Row): QuestionDetail {
 const t = record(r.thread), labels = accountMap(r)
 return {
  title: safeText(t.title, labels), updated: text(t.updated_at),
  turns: rows(t.turns).map(turn => ({
   question: safeText(turn.question, labels), asked: text(turn.asked_at),
   answers: rows(turn.answers).map(a => ({
    summary: safeText(a.summary, labels), at: text(a.produced_at), status: safeText(a.status, labels),
    changed: safeText(a.what_changed, labels),
    sources: rows(a.sources).map(s => ({ title: safeText(s.title, labels), kind: safeText(s.kind, labels), asOf: text(s.as_of), url: safeUrl(s.url) })),
   })),
  })),
 }
}
export function questionDetailState(read: Read, now: number) {
 const result=state(read,questionDetailModel,now)
 if(read?.error) return {...result,status:'ERROR' as const,data:null,reason:read.error}
 if(result.status!=='OK') {
  const detail=safeText(body(read?.data).error || body(read?.data).reason)
  return {...result,reason:detail ? result.reason+' Source: '+detail : result.reason}
 }
 if (!Object.keys(record(body(read?.data).thread)).length)
  return { ...result, status: 'UNKNOWN' as const, data: null, reason: 'Stored thread unavailable; no answer is inferred.' }
 return result
}

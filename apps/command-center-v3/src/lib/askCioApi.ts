/**
 * Ask the CIO — POST helper. Same-origin JSON (cc_auth CSRF: Origin / Sec-Fetch-Site are sent by the browser;
 * Content-Type: application/json is required). Errors carry the server's typed code.
 */
import { ASK_PATHS, buildAskBody, newRequestId, unwrap } from './askCioModel.ts'
import type { Thread, ResearchRefreshResult } from './askCioModel.ts'
import { publishAskUpdate } from './askCioPresentation.ts'
import { regroupPath } from './askCioGroups.ts'

export class AskApiError extends Error {
  code: string
  status: number
  constructor(code: string, status: number, detail?: string) {
    super(detail ? `${code}: ${detail}` : code)
    this.code = code
    this.status = status
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  let j: unknown = null
  try { j = await r.json() } catch { /* empty body */ }
  const o = (j ?? {}) as { ok?: boolean; error?: string; detail?: string; reason?: string; blocker?: string | { reason?: string } }
  const reason = o.detail ?? o.reason ?? (typeof o.blocker === 'string' ? o.blocker : o.blocker?.reason)
  if (!r.ok || o.ok === false) throw new AskApiError(o.error || `HTTP_${r.status}`, r.status, reason)
  return (unwrap<T>(j) ?? ({} as T))
}

export interface AskResult { ask_id: string; thread_id: string; answer_text: string; thread: Thread | null }

export async function askCio(question: string, opts: { deep?: boolean; threadId?: string | null } = {}): Promise<AskResult> {
  const result = await post<AskResult>(ASK_PATHS.ask, buildAskBody(question, { ...opts, requestId: newRequestId() }))
  if (result.thread_id) publishAskUpdate({ threadId: result.thread_id, source: 'mutation' })
  return result
}

// One in-flight refresh per thread across groups, navigation and repeated clicks. The request id
// stays fixed for that request; an intentional later refresh gets a new id.
const deepRequests = new Map<string, Promise<ResearchRefreshResult>>()
export function requestDeep(threadId: string, askId?: string, requestId?: string): Promise<ResearchRefreshResult> {
  const active = deepRequests.get(threadId)
  if (active) return active
  const body = { request_id: requestId ?? newRequestId(), ...(askId ? { ask_id: askId } : {}) }
  const request = post<ResearchRefreshResult>(ASK_PATHS.deep(threadId), body).then(result => {
    publishAskUpdate({ threadId, source: 'mutation' })
    return result
  }).finally(() => { deepRequests.delete(threadId) })
  deepRequests.set(threadId, request)
  return request
}

export function untrackEntity(threadId: string, entityKey: string): Promise<{ ok: boolean }> {
  return post(ASK_PATHS.untrack(threadId), { entity_key: entityKey })
}

export const ASK_ERROR_TEXT: Record<string, string> = {
  AGENT_CALLER_REFUSED: 'Only the operator can ask the CIO from here.',
  CSRF_REFUSED: 'Request refused (not same-origin). Reload the page and try again.',
  QUESTION_EMPTY: 'Type a question.',
  QUESTION_TOO_LONG: 'That question is too long.',
  ASK_DISABLED: 'Ask the CIO is turned off (config/cio_ask.json).',
}

export function askErrorText(e: unknown): string {
  if (e instanceof AskApiError) return ASK_ERROR_TEXT[e.code] ?? e.message
  return e instanceof Error ? e.message : 'Something went wrong.'
}

/** Operator manual regroup: appends an ask.group_override event (never edits history). */
export async function regroupQuestion(threadId: string, body: { ask_id: string; group_by: string; group_key: string | null; group_label?: string }): Promise<unknown> {
  const result = await post<unknown>(regroupPath(threadId), body)
  publishAskUpdate({ threadId, source: 'mutation' })
  return result
}

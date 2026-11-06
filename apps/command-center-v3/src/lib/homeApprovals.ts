/** Home v008 "Needs you": one-tap operator approvals (design home/v008, operator-approved 2026-11-03).
 *
 *  Client for the HTTP edge in scripts/lib/home_approvals_api.py (route /api/v2/home/approvals) over the store and its
 *  CLOSED action list in scripts/lib/home_approvals.py (ACTION_TYPES). This module never decides anything: the server
 *  owns operator-session + same-origin CSRF, requester != approver, the bound-fact revalidation and the receipt.
 *
 *  Routes used (all under HOME_APPROVALS below):
 *    GET  <base>                     the open queue (card list)
 *    GET  <base>/summary             count + urgent_count (nav badge, tab title)
 *    GET  <base>/<id>?revalidate=1   one request + its binding + a live fact check (confirm sheet)
 *    POST <base>/<id>/approve        { binding, note? }
 *    POST <base>/<id>/decline        { binding, note? }
 *    POST <base>/<id>/question       { note }
 *
 *  CSRF: cc_auth.command_csrf_check accepts a same-origin browser POST (Origin / Sec-Fetch-Site set by the browser) with
 *  Content-Type: application/json. There is no token to carry; a fetch with credentials 'same-origin' and a JSON body is
 *  exactly what the server requires, the same as the existing Approve/Hold/Push controls. */
import { readableTime } from './readableTime.ts'

export const HOME_APPROVALS = '/api/v2/home/approvals'

/** Mirror of ACTION_TYPES in scripts/lib/home_approvals.py. homeApprovals.test.ts fails if the two drift.
 *  A request whose type is not in this list never gets a button on the card. */
export const CLOSED_ACTIONS = [
  'merge_pr', 'rerun_ci', 'grant', 'stop_job', 'install_schedule', 'restore_store', 'policy_approval', 'backup_n8n',
] as const
export type ClosedAction = typeof CLOSED_ACTIONS[number]

export const ACTION_TAG: Record<ClosedAction, string> = {
  merge_pr: 'MERGE', rerun_ci: 'RE-RUN', grant: 'GRANT', stop_job: 'STOP JOB', install_schedule: 'SCHEDULE',
  restore_store: 'RESTORE', policy_approval: 'POLICY', backup_n8n: 'BACKUP',
}

/** Same rule as the server's /summary urgent_count: expires within two hours. */
export const URGENT_SECONDS = 2 * 3600

export function isClosedAction(type: unknown): type is ClosedAction {
  return typeof type === 'string' && (CLOSED_ACTIONS as readonly string[]).includes(type)
}

export type Requester = { session?: string | null; claim?: string | null; actor?: string | null; vendor?: string | null }
export type ActionResult = { ok?: boolean; outcome?: string; plain?: string; attempted?: unknown; [k: string]: unknown }
export type NeedsYouItem = {
  id: string
  type: string
  title?: string | null
  why?: string | null
  rule?: string | null
  what_happens?: string | null
  risk?: string | null
  undo?: string | null
  facts?: Record<string, unknown> | null
  requester?: Requester | null
  created_at?: string | null
  expires_at?: string | null
  state?: string | null
  can_act?: boolean
  blocked_reason?: string | null
  reask_requested?: boolean
  question?: { at?: string; by?: string; note?: string } | null
  result?: ActionResult | null
  receipt?: string | null
  age_seconds?: number | null
  expires_in_seconds?: number | null
  binding?: string | null
  revalidated?: boolean
}
export type NeedsYouQueue = {
  schema?: string; as_of?: string; count: number; total: number; limit?: number; offset?: number; has_more?: boolean
  empty_text?: string; items: NeedsYouItem[]
}
export type NeedsYouSummary = { count: number; urgent_count: number; as_of?: string }

export function isUrgent(item: NeedsYouItem): boolean {
  const s = item.expires_in_seconds
  return typeof s === 'number' && Number.isFinite(s) && s <= URGENT_SECONDS
}

const ms = (iso: unknown) => { const t = typeof iso === 'string' ? Date.parse(iso) : NaN; return Number.isFinite(t) ? t : -Infinity }

/** Only real decisions: open (or just-expired) requests whose type is on the closed list. Urgent first, then newest. */
export function needsYouList(queue: NeedsYouQueue | null | undefined): { items: NeedsYouItem[]; hiddenUnknown: number } {
  const raw = Array.isArray(queue?.items) ? queue!.items : []
  const real = raw.filter(it => it && typeof it.id === 'string' && it.id && (it.state === 'open' || it.state === 'expired'))
  const items = real.filter(it => isClosedAction(it.type))
  items.sort((a, b) => (Number(isUrgent(b)) - Number(isUrgent(a))) || (ms(b.created_at) - ms(a.created_at)))
  return { items, hiddenUnknown: real.length - items.length }
}

/** Who asked, in plain words. The lead's session ids are not useful to the operator; the actor/vendor is. */
export function askedBy(r: Requester | null | undefined): string {
  const who = (r?.actor || r?.vendor || r?.session || '').trim()
  return who ? `asked by ${who}` : 'asker not recorded'
}

export function timeLabel(iso: unknown): string {
  return readableTime(iso) ?? 'time not recorded'
}

/** "bound to pr 2531 · head_sha 93dd68e": the exact facts the button is tied to. Long hex digests are shortened. */
export function boundFacts(facts: Record<string, unknown> | null | undefined): string {
  if (!facts || typeof facts !== 'object') return ''
  const parts = Object.entries(facts).filter(([, v]) => v !== null && v !== undefined && v !== '').map(([k, v]) => {
    const s = typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean' ? String(v) : JSON.stringify(v)
    return `${k.replace(/_/g, ' ')} ${/^[0-9a-f]{12,}$/i.test(s) ? s.slice(0, 7) : s.length > 60 ? s.slice(0, 57) + '…' : s}`
  })
  return parts.length ? `bound to ${parts.join(' · ')}` : ''
}

export const CHANGED_TEXT = 'This changed. The lead will re-ask.'
export const EXPIRED_TEXT = 'This request expired. The lead will re-ask; nothing was approved.'

/** Why the buttons are off for this item, or null when it can be decided. */
export function blockedText(item: NeedsYouItem): string | null {
  if (item.state === 'expired') return EXPIRED_TEXT
  if (item.blocked_reason) return item.blocked_reason
  if (item.can_act === false) return CHANGED_TEXT
  return null
}

export type Verb = 'approve' | 'decline' | 'question'

/** What a click came back with, already in the card's terms. Every field is the server's own words. */
export type Outcome = {
  kind: 'done' | 'pending' | 'declined' | 'failed' | 'refused' | 'question'
  text: string
  receipt: string | null
  code?: string
  /** For a refusal that moved the card (CHANGED) or ended it (EXPIRED / NOT_OPEN): the item state to show next. */
  blocked?: string | null
  expired?: boolean
}

const OUTCOME_FALLBACK: Record<string, string> = {
  executed: 'Done ✓', declined: 'Declined. The lead was told and will not ask again unless something changes.',
  uncertain: 'Approved. The result is not confirmed yet; check back shortly.',
}

/** Interpret one decision/question response exactly as home_approvals_api.py shapes it. */
export function outcomeFrom(verb: Verb, status: number, envelope: any): Outcome {
  const env = envelope && typeof envelope === 'object' ? envelope : {}
  const data = env.data && typeof env.data === 'object' ? env.data : {}
  const receipt = typeof data.receipt === 'string' && data.receipt ? data.receipt : null
  if (verb === 'question') {
    if (env.ok === true) {
      return { kind: 'question', receipt: null, text: data.delivered === false
        ? 'Your note is saved on the request, but it could not be put in the lead’s inbox. Ask again in Telegram if it is urgent.'
        : 'Note sent to the lead ✓' }
    }
  }
  if (env.ok === true && verb !== 'question') {
    const outcome = String(data.outcome || '')
    const plain = typeof data.result?.plain === 'string' && data.result.plain ? data.result.plain
      : typeof data.message === 'string' && data.message ? data.message : ''
    if (outcome === 'declined' || data.state === 'declined') return { kind: 'declined', receipt, text: OUTCOME_FALLBACK.declined }
    if (status === 202 || outcome === 'uncertain') return { kind: 'pending', receipt, text: plain || OUTCOME_FALLBACK.uncertain }
    return { kind: 'done', receipt, text: plain ? `Done ✓ ${plain}` : OUTCOME_FALLBACK.executed }
  }
  const code = typeof env.code === 'string' ? env.code : typeof env.error === 'string' ? env.error : 'UNAVAILABLE'
  const reason = typeof env.reason === 'string' && env.reason ? env.reason
    : status === 0 ? 'The Command Center could not be reached; nothing was decided.' : `The server refused (${status || 'no answer'}); nothing was decided.`
  if (code === 'ACTION_FAILED') return { kind: 'failed', code, receipt, text: reason }
  return {
    kind: 'refused', code, receipt: null, text: reason,
    blocked: code === 'CHANGED' ? (typeof env.blocked_reason === 'string' && env.blocked_reason ? env.blocked_reason : reason) : null,
    expired: code === 'EXPIRED' || env.state === 'expired',
  }
}

type FetchLike = (input: string, init?: RequestInit) => Promise<{ status: number; json(): Promise<any> }>

/** POST a decision or a question. Same-origin JSON: what cc_auth.command_csrf_check requires. Never throws. */
export async function postDecision(id: string, verb: Verb, body: { binding?: string; note?: string }, fetcher: FetchLike = fetch as unknown as FetchLike): Promise<Outcome> {
  if (!id || !/^[A-Za-z0-9._:-]+$/.test(id)) return outcomeFrom(verb, 400, { ok: false, code: 'BAD_REQUEST', reason: 'This request id is not valid; nothing was sent.' })
  let status = 0
  let envelope: any = null
  try {
    const response = await fetcher(`${HOME_APPROVALS}/${encodeURIComponent(id)}/${verb}`, {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    status = response.status
    envelope = await response.json().catch(() => null)
  } catch {
    status = 0
  }
  return outcomeFrom(verb, status, envelope)
}

/** GET one request with a live fact check, for the confirm sheet. Returns the item or a plain error. Never throws. */
export async function fetchForConfirm(id: string, fetcher: FetchLike = fetch as unknown as FetchLike): Promise<{ item: NeedsYouItem | null; error: string | null }> {
  try {
    const response = await fetcher(`${HOME_APPROVALS}/${encodeURIComponent(id)}?revalidate=1`, { credentials: 'same-origin' })
    const env = await response.json().catch(() => null)
    if (response.status === 200 && env?.ok === true && env.data && typeof env.data === 'object') return { item: env.data as NeedsYouItem, error: null }
    return { item: null, error: typeof env?.reason === 'string' && env.reason ? env.reason : 'This request could not be checked right now; nothing was decided.' }
  } catch {
    return { item: null, error: 'The Command Center could not be reached; nothing was decided.' }
  }
}

/** Tab title with the open count: "(2) Command Center v3". */
export function titledWithCount(base: string, count: number | null | undefined): string {
  const clean = base.replace(/^\(\d+\)\s+/, '')
  return typeof count === 'number' && count > 0 ? `(${count}) ${clean}` : clean
}

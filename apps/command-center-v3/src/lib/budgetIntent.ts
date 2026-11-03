// Operator budget-intent request shape (E's contract, `market_risk_budget_presentation`).
//
// This module builds the one body the decide route accepts and nothing else. It can never carry an actor, a measured
// amount, a limit or a breach flag: the server derives those from its own snapshot, and the route refuses any field
// outside the allowlist. Preview is always `dry_run: true`; a real write needs a separate confirm with the same
// request_id and the same canonical source binding.

export const BUDGET_PRESENTATION_SUBTYPE = 'market_risk_budget_presentation'
export const BUDGET_ACTION = 'intentional_until'
export const BUDGET_BASIS_PATH = '/api/v2/governance/budget-presentation'
export const BUDGET_DECIDE_PATH = '/api/v2/governance/budget-presentation/decide'

export type SourceBinding = { as_of: string; sha256: string }

export type IntentInput = {
  scopeId: string | null
  budget: string | null
  binding: SourceBinding | null
  /** An explicit UTC instant ending in ``Z``; the server refuses anything else. */
  untilUtc: string | null
  requestId: string
  comment?: string
  dryRun: boolean
}

export type IntentBody = {
  subtype: string
  action: string
  scope_id: string
  budget: string
  source_binding: SourceBinding
  intentional_until: string
  request_id: string
  comment?: string
  dry_run?: boolean
}

/** Local `<input type="datetime-local">` value → the UTC ``Z`` instant the route accepts. */
export function toUtcZ(localValue: string): string | null {
  const raw = String(localValue || '').trim()
  if (!raw) return null
  const at = Date.parse(raw)
  if (!Number.isFinite(at)) return null
  return new Date(at).toISOString().replace(/\.\d{3}Z$/, 'Z')
}

/** A UTC instant that is strictly in the future, or null (the server refuses a past expiry). */
export function futureUtcZ(localValue: string, now = Date.now()): string | null {
  const z = toUtcZ(localValue)
  if (!z) return null
  const at = Date.parse(z)
  return Number.isFinite(at) && at > now ? z : null
}

export function requestId(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto
  if (c && typeof c.randomUUID === 'function') return c.randomUUID()
  const bytes = new Uint8Array(16)
  c?.getRandomValues(bytes)
  return 'req-' + Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
}

/**
 * The exact decide-route body, or a thrown error naming what is missing. Only allowlisted fields are emitted.
 */
export function intentBody(input: IntentInput, now = Date.now()): IntentBody {
  const scope = String(input.scopeId || '').trim()
  const budget = String(input.budget || '').trim()
  if (!scope || !budget) throw new Error('This budget row does not name the canonical scope and budget the route needs.')
  const binding = input.binding
  if (!binding || !/^[0-9a-f]{64}$/i.test(String(binding.sha256 || '')) || !String(binding.as_of || '').endsWith('Z')) {
    throw new Error('The measurement basis is missing or not canonical; reload the row before recording intent.')
  }
  const until = futureUtcZ(String(input.untilUtc || ''), now)
  if (!until) throw new Error('Choose an expiry in the future.')
  if (!/^[A-Za-z0-9_-]{8,80}$/.test(input.requestId)) throw new Error('A request id is required.')
  const body: IntentBody = {
    subtype: BUDGET_PRESENTATION_SUBTYPE,
    action: BUDGET_ACTION,
    scope_id: scope,
    budget,
    source_binding: { as_of: String(binding.as_of), sha256: String(binding.sha256) },
    intentional_until: until,
    request_id: input.requestId,
  }
  const comment = String(input.comment || '').trim()
  if (comment) body.comment = comment.slice(0, 4000)
  if (input.dryRun) body.dry_run = true
  return body
}

export type PresentationReply = {
  ok: boolean
  status: number
  /** The server's own error code (never a prose guess), when the call failed. */
  code: string | null
  data: unknown
}

const HUMAN: Record<string, string> = {
  BUDGET_SOURCE_CHANGED: 'The measurement changed since this page loaded. Reload the basis and check the new numbers.',
  BUDGET_NOT_BREACHED: 'This budget is no longer breached, so there is nothing to record intent for.',
  INVALID_INTENTIONAL_UNTIL: 'That expiry is not a future UTC instant.',
  BUDGET_BINDING_REQUIRED: 'The measurement basis is missing or malformed.',
  REQUEST_ID_REQUIRED: 'The request id was rejected.',
  IDEMPOTENCY_CONFLICT: 'This request id was already used for a different intent.',
  CSRF_REFUSED: 'This request could not be verified. Reload the page and try again.',
  AGENT_CALLER_REFUSED: 'Only your authenticated operator session can record this.',
  STORE_APPROVAL_PENDING: 'Decision recording is awaiting the operator’s data-source sign-off.',
}

export function humanError(reply: PresentationReply): string {
  return (reply.code && HUMAN[reply.code]) || 'The decision could not be recorded. Nothing was written.'
}

/** GET the fresh basis, or POST the decide body. Never carries a request body on GET. */
export async function presentationCall(url: string, body?: IntentBody, signal?: AbortSignal): Promise<PresentationReply> {
  const response = await fetch(url, {
    method: body === undefined ? 'GET' : 'POST',
    credentials: 'same-origin',
    cache: 'no-store',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
  let envelope: any = null
  try { envelope = await response.json() } catch { envelope = null }
  return {
    ok: response.ok && envelope?.ok === true,
    status: response.status,
    code: typeof envelope?.error === 'string' ? envelope.error : null,
    data: envelope?.data ?? null,
  }
}

export function basisUrl(scopeId: string, budget: string): string {
  return `${BUDGET_BASIS_PATH}?scope_id=${encodeURIComponent(scopeId)}&budget=${encodeURIComponent(budget)}`
}

/** The current snapshot from a basis reply, or null when the source is unavailable (503 keeps history only). */
export function currentBasis(data: unknown): { binding: SourceBinding | null; breached: boolean | null; asOf: string | null } {
  const doc = (data && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const current = (doc.current && typeof doc.current === 'object' ? doc.current : null) as Record<string, unknown> | null
  const binding = (current?.source_binding && typeof current.source_binding === 'object' ? current.source_binding : null) as Record<string, unknown> | null
  return {
    binding: binding && typeof binding.as_of === 'string' && typeof binding.sha256 === 'string'
      ? { as_of: String(binding.as_of), sha256: String(binding.sha256) } : null,
    breached: current && typeof current.breached === 'boolean' ? current.breached : null,
    asOf: current && typeof current.snapshot_as_of === 'string' ? String(current.snapshot_as_of) : null,
  }
}

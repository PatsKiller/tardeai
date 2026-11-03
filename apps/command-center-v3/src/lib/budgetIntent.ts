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

export type PresentationOutcome = 'ok' | 'refused' | 'unknown'

export type PresentationReply = {
  ok: boolean
  status: number
  /** The server's own error code (never a prose guess), when the call was a clean refusal. */
  code: string | null
  data: unknown
  /**
   * ``refused`` = the server answered with its own error envelope (nothing may have been written, but a refusal can
   * also follow an earlier append). ``unknown`` = a transport failure or a body we could not parse: the outcome is not
   * known and must never be reported as "nothing was written".
   */
  outcome: PresentationOutcome
}

const HUMAN: Record<string, string> = {
  SOURCE_UNAVAILABLE: 'The canonical budget source is unavailable right now. Its earlier decisions are still listed; nothing can be recorded until it answers.',
  BUDGET_SOURCE_CHANGED: 'The measurement changed since this page loaded. Reload the basis and check the new numbers.',
  BUDGET_NOT_BREACHED: 'This budget is no longer breached, so there is nothing to record intent for.',
  INVALID_INTENTIONAL_UNTIL: 'That expiry is not a future UTC instant.',
  BUDGET_BINDING_REQUIRED: 'The measurement basis is missing or malformed.',
  REQUEST_ID_REQUIRED: 'The request id was rejected.',
  IDEMPOTENCY_CONFLICT: 'This request id was already used for a different intent.',
  CSRF_REFUSED: 'This request could not be verified. Reload the page and try again.',
  AGENT_CALLER_REFUSED: 'Only your authenticated operator session can record this.',
  STORE_APPROVAL_PENDING: 'Decision recording is awaiting the operator’s data-source sign-off.',
  BUDGET_IDENTITY_REQUIRED: 'This row does not name exactly one canonical scope and budget.',
  INVALID_PRESENTATION_FIELDS: 'The request carried a field this route does not accept. Nothing was sent.',
  INVALID_PRESENTATION_ACTION: 'The request was not the reviewed budget-presentation intent.',
  INVALID_DRY_RUN: 'The preview flag was malformed.',
  OBJECT_BODY_REQUIRED: 'The request body was malformed.',
  ADMIN_REQUIRED: 'Only the operator session can record this.',
  AUTHENTICATED_READER_REQUIRED: 'Sign in as the operator to read the basis.',
  NOT_FOUND: 'This budget-intent route is not available on the running backend yet.',
}

/** The call may have reached the server and still failed on the way back: never claim it did nothing. */
export function refusedText(code: string | null): string {
  const known = code ? HUMAN[code] : null
  // A refusal is not proof that nothing happened: E prepares the source and expiry before it looks for an earlier
  // identical request, so a 409/400 can be returned even when the decision already exists.
  return `${known ?? 'The server refused this request.'} A refusal is not proof the decision is absent — an identical request may already be recorded.`
}

export function networkOutcomeUnknown(error: unknown): string {
  const message = String((error as Error)?.message || error || '')
  if (/abort/i.test(message)) return message
  return 'The reply never arrived, so the outcome is unknown. Retry with the same request — an identical request replays instead of writing twice.'
}

export function humanError(reply: PresentationReply): string {
  // An unrecognised code is not proof of anything: the reply may follow an append we could not read.
  return (reply.code && HUMAN[reply.code]) || 'The decision could not be confirmed; check the history before retrying.'
}

/**
 * GET the fresh basis, or POST the decide body. Never carries a request body on GET.
 *
 * A transport failure or an unparseable body is ``unknown``, not ``refused``: the request may have reached the server
 * and been applied, so the caller must preserve the pending request id and reconcile through the history read.
 */
export async function presentationCall(url: string, body?: IntentBody, signal?: AbortSignal): Promise<PresentationReply> {
  let response: Response
  try {
    response = await fetch(url, {
      method: body === undefined ? 'GET' : 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if ((error as Error)?.name === 'AbortError') throw error
    return { ok: false, status: 0, code: null, data: null, outcome: 'unknown' }
  }
  let envelope: any = null
  try { envelope = await response.json() } catch { envelope = null }
  const clean = envelope && typeof envelope === 'object' && typeof envelope.ok === 'boolean'
  return {
    ok: response.ok && envelope?.ok === true,
    status: response.status,
    code: clean && typeof envelope.error === 'string' ? envelope.error : null,
    data: clean ? (envelope.data ?? null) : null,
    outcome: response.ok && envelope?.ok === true ? 'ok' : clean ? 'refused' : 'unknown',
  }
}

export type DecisionRecord = {
  requestId: string | null
  scopeId: string | null
  budget: string | null
  bindingSha: string | null
  bindingAsOf: string | null
  intentionalUntil: string | null
  receipt: string | null
  active: boolean
}

/**
 * Every decision event a basis reply carries, active or inactive. An empty list is a fact, not a lack of data.
 *
 * E projects each budget as an ITEM whose own ``history`` array holds the ledger events — the request id and the
 * composite binding live on those events, while the item carries the receipt and the active flag. A flattened list
 * that reads only the item's top level would find no request id and could never reconcile an uncertain write, so both
 * shapes are read here.
 */
export function historyRecords(data: unknown): DecisionRecord[] {
  const doc = (data && typeof data === 'object' ? data : {}) as Record<string, unknown>
  const ledger = (doc.budget_presentation_decisions && typeof doc.budget_presentation_decisions === 'object'
    ? doc.budget_presentation_decisions : {}) as Record<string, unknown>
  const items = Array.isArray(ledger.items) ? ledger.items : []
  const flat = Array.isArray(ledger.history) ? ledger.history : []
  const out: DecisionRecord[] = []
  const seen = new Set<string>()

  const push = (row: unknown, parent?: Record<string, unknown>) => {
    const r = (row && typeof row === 'object' ? row : {}) as Record<string, unknown>
    const p = parent ?? {}
    const binding = (r.source_binding && typeof r.source_binding === 'object' ? r.source_binding
      : p.source_binding && typeof p.source_binding === 'object' ? p.source_binding : {}) as Record<string, unknown>
    const id = typeof r.request_id === 'string' ? r.request_id : null
    const receipt = typeof r.hash_self === 'string' ? r.hash_self : typeof r.receipt === 'string' ? r.receipt
      : typeof p.receipt === 'string' ? p.receipt : null
    const scope = typeof r.scope_id === 'string' ? r.scope_id : typeof p.scope_id === 'string' ? p.scope_id : null
    const budget = typeof r.budget === 'string' ? r.budget : typeof p.budget === 'string' ? p.budget : null
    const until = typeof r.intentional_until === 'string' ? r.intentional_until : typeof p.intentional_until === 'string' ? p.intentional_until : null
    const key = `${id}|${receipt}|${scope}|${budget}|${until}`
    if (seen.has(key)) return
    seen.add(key)
    out.push({
      requestId: id,
      scopeId: scope,
      budget,
      bindingSha: typeof binding.sha256 === 'string' ? binding.sha256 : null,
      bindingAsOf: typeof binding.as_of === 'string' ? binding.as_of : null,
      intentionalUntil: until,
      receipt,
      active: typeof r.active === 'boolean' ? r.active : p.active === true,
    })
  }

  for (const item of items) {
    const row = (item && typeof item === 'object' ? item : {}) as Record<string, unknown>
    const events = Array.isArray(row.history) ? row.history : []
    // One decision must not be counted twice: when the item carries its ledger events, those are the records and the
    // item is only their context (receipt, active flag). An item with no events is itself the record.
    if (events.length) for (const event of events) push(event, row)
    else push(item)
  }
  for (const event of flat) push(event)

  // A record without any identity cannot be reconciled against; keep only rows that carry an id or a receipt.
  return out.filter(r => r.requestId || r.receipt)
}

/** Did the pending request already land? Identity is the request id AND the payload it was bound to. */
export function reconcile(records: DecisionRecord[], pending: IntentBody): DecisionRecord | null {
  for (const record of records) {
    if (record.requestId !== pending.request_id) continue
    if (record.scopeId !== pending.scope_id || record.budget !== pending.budget) continue
    if (record.bindingSha !== pending.source_binding.sha256) continue
    if (record.bindingAsOf !== pending.source_binding.as_of) continue
    if (record.intentionalUntil !== pending.intentional_until) continue
    return record
  }
  return null
}

export function basisUrl(scopeId: string, budget: string): string {
  return `${BUDGET_BASIS_PATH}?scope_id=${encodeURIComponent(scopeId)}&budget=${encodeURIComponent(budget)}`
}

/** The current snapshot from a basis reply; a source-unavailable (503) reply keeps its history but no basis. */
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

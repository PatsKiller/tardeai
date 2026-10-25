/** Approvals → Designs (design workflow, AGENTS.md §28.13 proposed). Pure model + request helpers; no React.
 *  Server: scripts/lib/design_decisions_api.py (/api/v2/design). Decisions are operator-only; agents are refused. */

export const DESIGN_API = '/api/v2/design'

export type DesignImage = { path: string; width: number | null; sha256: string }
export type DesignRemoval = { action: string; kind: string; label: string }
export type ProposedDesign = {
  id: string; page: string; page_title: string; version: string; title: string; state: string
  fingerprint: string; created: string | null; proposed_by: string | null; removals: DesignRemoval[]
  spec: string; images: DesignImage[]; mockup_files: number
}
export type DsnProposed = { id: string; title: string; path: string | null; approval: string | null; href: string }
export type DecidedDesign = {
  id: string; title: string; decision: string; outcome: string; at: string | null; actor: string | null
  recorded: string; comment?: string; ref?: string; pages?: string[]
}
export type DesignQueue = {
  proposed: ProposedDesign[]; dsn_proposed: DsnProposed[]; decided_recently: DecidedDesign[]
  counts: { proposed: number; dsn_proposed: number }; complete: boolean; gaps: { source: string; reason: string }[]
  as_of: string; can_decide: boolean; signature: string
}
export type DesignAsset = { image: string; mime: string; width: number | null; path: string }

const MESSAGES: Record<string, string> = {
  STORE_APPROVAL_PENDING: 'Decision recording is waiting for your sign-off of the decisions ledger (data-source approval).',
  DOCUMENT_CHANGED: 'This design changed since you opened it. Reload and look again before deciding.',
  ALREADY_DECIDED: 'This version is already decided.',
  VERSION_NOT_PROPOSED: 'This version is no longer waiting for a decision.',
  REASON_REQUIRED: 'Say why you are rejecting it, so the agent can propose a better version.',
  AGENT_CALLER_REFUSED: 'Only your authenticated operator session can record a decision.',
  CSRF_REFUSED: 'This request could not be verified. Reload the page and try again.',
  AUTHENTICATED_READER_REQUIRED: 'Sign in through the Command Center to see designs.',
  ASSET_CHANGED: 'This mockup file changed after it was proposed.',
  ASSET_UNAVAILABLE: 'This mockup is not on the host.',
}

export function designMessage(code: string | undefined): string {
  return (code && MESSAGES[code]) || 'The design service is unavailable. Please try again.'
}

export async function designRequest<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), signal })
  let envelope: { ok?: boolean; data?: T; error?: string } = {}
  try { envelope = await response.json() } catch { /* non-JSON is a failure below */ }
  if (!response.ok || envelope.ok !== true) throw new Error(designMessage(envelope.error))
  return envelope.data as T
}

export function assetUrl(page: string, version: string, path: string): string {
  return `${DESIGN_API}/asset?page=${encodeURIComponent(page)}&version=${encodeURIComponent(version)}&path=${encodeURIComponent(path)}`
}

/** The three widths the workflow requires, in order; a missing width is reported, never invented. */
export function thumbsFor(images: DesignImage[]): { width: number; image: DesignImage | null }[] {
  return [1440, 412, 390].map(width => ({ width, image: images.find(i => i.width === width) ?? null }))
}

const ET_DAY = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric' })
const ET_TIME = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })

/** "Oct 24" for a recorded date, "Oct 25 10:25 ET" for an instant; never a raw ISO string. */
export function decidedAt(value: string | null | undefined): string {
  if (!value) return 'Time not recorded'
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.exec(value)
  if (dateOnly) {
    const [y, m, d] = value.split('-').map(Number)
    return ET_DAY.format(new Date(Date.UTC(y, m - 1, d, 12)))
  }
  const t = Date.parse(value)
  if (!Number.isFinite(t)) return 'Time not recorded'
  return `${ET_DAY.format(t)} ${ET_TIME.format(t)} ET`
}

export function outcomeTone(outcome: string): 'success' | 'danger' | 'warning' {
  return outcome === 'Approved' ? 'success' : outcome === 'Rejected' ? 'danger' : 'warning'
}

export function canSubmit(decision: 'APPROVE' | 'REJECT', reason: string, busy: boolean): boolean {
  return !busy && (decision === 'APPROVE' || reason.trim().length > 0)
}

export type RecentLike = { item_id?: string; decision: string; at: string; kind?: string; document_sha?: string }

/** Board 19 "Decided recently": design decisions (with titles) merged with other Approvals decisions, newest first. */
export function mergeRecent(designs: DecidedDesign[], others: RecentLike[], labels: Record<string, string>, limit = 5): DecidedDesign[] {
  const seen = new Set(designs.map(d => d.id))
  const rest: DecidedDesign[] = others.filter(r => !r.item_id || !seen.has(r.item_id)).map(r => ({
    id: r.item_id ?? `${r.kind}:${r.at}`, title: `${labels[r.kind ?? ''] ?? 'Approval'} decision`, decision: r.decision,
    outcome: r.decision === 'APPROVE' ? 'Approved' : r.decision === 'REJECT' ? 'Rejected' : 'Changes requested',
    at: r.at, actor: null, recorded: 'ledger' }))
  return [...designs, ...rest].sort((a, b) => sortKey(b.at).localeCompare(sortKey(a.at))).slice(0, limit)
}

function sortKey(at: string | null): string {
  if (!at) return ''
  return /^\d{4}-\d{2}-\d{2}$/.test(at) ? `${at}T23:59:59` : new Date(at).toISOString()
}

export function newRequestId(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto
  if (c && typeof c.randomUUID === 'function') return 'design-' + c.randomUUID()
  const bytes = new Uint8Array(16)
  c?.getRandomValues(bytes)
  return 'design-' + Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
}

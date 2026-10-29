/**
 * Ask the CIO — UI model (Phases 8–11). Pure functions over the /api/v2/cio/ask(s) payloads.
 *
 * The answer text is produced server-side by the same converse path Telegram uses, so this model never rewrites it;
 * it only labels status, orders the thread, and validates what the operator types. Quantities are optional and never
 * prompted for. READ_ONLY_ADVISORY — nothing here sizes, orders, stops or weights.
 */
import type { Tone } from './designTokens'

export const ASK_PATHS = {
  ask: '/api/v2/cio/ask',
  list: '/api/v2/cio/asks',
  tracked: '/api/v2/cio/asks/tracked',
  thread: (id: string) => `/api/v2/cio/asks/${encodeURIComponent(id)}`,
  deep: (id: string) => `/api/v2/cio/asks/${encodeURIComponent(id)}/deep`,
  untrack: (id: string) => `/api/v2/cio/asks/${encodeURIComponent(id)}/untrack`,
} as const

export const MAX_QUESTION_CHARS = 2000

export type AskStatus = 'quick' | 'deep_pending' | 'deep' | 'reanswer' | 'capped' | 'failed'
export type Channel = 'cc' | 'telegram' | 'whatsapp' | 'event'

export interface SizingRow {
  symbol: string
  operator_amount: number
  operator_unit: 'shares' | 'usd'
  exposure_usd: number | null
  pct_of_portfolio: number | null
  combined_pct_of_portfolio?: number | null
  concentration_limit_pct?: number | null
  over_concentration_limit?: boolean | null
  reference_stop_price?: number | null
  reference_stop_basis?: string | null
  loss_at_reference_usd?: number | null
  gaps?: string[]
}

export interface AnswerSource { title: string; kind: string; as_of: string | null; url?: string | null }

export interface AnswerVersion {
  answer_id?: string
  version: number
  status: AskStatus
  depth: 'quick' | 'deep'
  summary: string
  produced_at: string
  sources?: AnswerSource[]
  sizing_context?: SizingRow[]
  what_changed?: string | null
  confidence?: { level: string; rationale?: string }
  mbi_guard?: { stripped: number }
  prospectus?: unknown[]
}

export interface Turn {
  ask_id: string
  question: string
  channel: Channel
  asked_at: string
  turn_kind: 'ask' | 'follow_up' | 'reanswer'
  answers: AnswerVersion[]
}

export interface TrackedEntity {
  key: string
  name?: string
  symbol?: string | null
  kind?: 'security' | 'private_entity' | 'unresolved'
  tracking?: { state: 'tracked' | 'untracked' | null; at?: string }
}

export interface Thread {
  thread_id: string
  title: string | null
  created_at: string
  updated_at: string
  status: AskStatus | null
  channels: Channel[]
  turns: Turn[]
  entities: TrackedEntity[]
  reanswers: number
  lifecycle?: unknown
}

export interface ThreadSummary {
  thread_id: string
  title: string | null
  updated_at: string
  status: AskStatus | null
  channels: Channel[]
  turns: number
  reanswers: number
  entities: { key: string; name?: string; symbol?: string | null; kind?: string; tracking?: string | null }[]
  last_answer_excerpt: string
  lifecycle?: unknown
}

export const STATUS_LABEL: Record<AskStatus, string> = {
  quick: 'Quick answer',
  deep_pending: 'Deep research pending',
  deep: 'Deep answer',
  reanswer: 'Updated on new information',
  capped: 'Deep research capped',
  failed: 'Failed',
}

export const STATUS_TONE: Record<AskStatus, Tone> = {
  quick: 'info',
  deep_pending: 'warning',
  deep: 'ai',
  reanswer: 'success',
  capped: 'warning',
  failed: 'danger',
}

export const CHANNEL_LABEL: Record<Channel, string> = { cc: 'Command Center', telegram: 'Telegram', whatsapp: 'WhatsApp', event: 'Material change' }

export function statusLabel(s: AskStatus | null | undefined): string {
  return s ? STATUS_LABEL[s] ?? s : 'Asked'
}

export function statusTone(s: AskStatus | null | undefined): Tone {
  return s ? STATUS_TONE[s] ?? 'neutral' : 'neutral'
}

export type AskValidation = { ok: true; question: string } | { ok: false; reason: string }

/** What the operator typed → a question to send. No quantity is required or prompted for. */
export function validateQuestion(raw: string): AskValidation {
  const q = (raw ?? '').replace(/\s+/g, ' ').trim()
  if (!q) return { ok: false, reason: 'Type a question.' }
  if (q.length > MAX_QUESTION_CHARS) return { ok: false, reason: `Keep it under ${MAX_QUESTION_CHARS} characters.` }
  return { ok: true, question: q }
}

export interface AskBody { question: string; depth: 'quick' | 'deep'; thread_id?: string; client_request_id: string }

export function buildAskBody(question: string, opts: { deep?: boolean; threadId?: string | null; requestId: string }): AskBody {
  const body: AskBody = { question, depth: opts.deep ? 'deep' : 'quick', client_request_id: opts.requestId }
  if (opts.threadId) body.thread_id = opts.threadId
  return body
}

/** ⌘K on macOS, Ctrl-K elsewhere. */
export function isAskShortcut(e: { key: string; metaKey?: boolean; ctrlKey?: boolean; altKey?: boolean; shiftKey?: boolean }): boolean {
  return (e.key === 'k' || e.key === 'K') && !!(e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey
}

export function latestAnswer(t: Pick<Thread, 'turns'>): AnswerVersion | null {
  let last: AnswerVersion | null = null
  for (const turn of t.turns ?? []) for (const a of turn.answers ?? []) last = a
  return last
}

/** The answer of a turn the operator should read first: the newest version. */
export function currentVersion(turn: Turn): AnswerVersion | null {
  const a = turn.answers ?? []
  return a.length ? [...a].sort((x, y) => y.version - x.version)[0] : null
}

export function isPending(s: AskStatus | null | undefined): boolean {
  return s === 'deep_pending'
}

export function trackedEntities(t: Pick<Thread, 'entities'>): TrackedEntity[] {
  return (t.entities ?? []).filter(e => e.tracking?.state === 'tracked')
}

export function entityLabel(e: { symbol?: string | null; name?: string; kind?: string }): string {
  if (e.symbol) return e.symbol
  return e.kind === 'private_entity' ? `${e.name ?? 'Unnamed'} (private)` : (e.name ?? 'Unresolved')
}

export interface TrackedRow { thread_id: string; key: string; name?: string; symbol?: string | null; kind?: string }

/** Header chips: one per tracked entity (newest thread wins), capped. Flags tracked names on every page. */
export function trackedChips(rows: TrackedRow[] | null | undefined, max = 6): { key: string; label: string; thread_id: string }[] {
  const seen = new Map<string, { key: string; label: string; thread_id: string }>()
  for (const r of rows ?? []) {
    if (!r?.key || seen.has(r.key)) continue
    seen.set(r.key, { key: r.key, label: entityLabel(r), thread_id: r.thread_id })
  }
  return [...seen.values()].slice(0, max)
}

export function sortSummaries(rows: ThreadSummary[]): ThreadSummary[] {
  return [...rows].sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? ''))
}

export function filterSummaries(rows: ThreadSummary[], q: string): ThreadSummary[] {
  const s = q.trim().toLowerCase()
  if (!s) return rows
  return rows.filter(r => (r.title ?? '').toLowerCase().includes(s)
    || r.entities.some(e => (e.symbol ?? '').toLowerCase() === s || (e.name ?? '').toLowerCase().includes(s)))
}

function usd(v: number | null | undefined): string {
  return v == null ? 'n/a' : `$${Math.round(v).toLocaleString('en-US')}`
}

/** One line per operator-named quantity. Never a recommended quantity. */
export function sizingLine(r: SizingRow): string {
  const amt = r.operator_unit === 'shares' ? `${r.operator_amount.toLocaleString('en-US')} ${r.symbol}` : `${usd(r.operator_amount)} of ${r.symbol}`
  const bits = [`≈ ${usd(r.exposure_usd)}`]
  if (r.pct_of_portfolio != null) bits.push(`${r.pct_of_portfolio.toFixed(1)}% of portfolio`)
  if (r.over_concentration_limit && r.concentration_limit_pct != null) bits.push(`over the ${r.concentration_limit_pct}% limit`)
  if (r.loss_at_reference_usd != null) bits.push(`loss at reference stop ≈ ${usd(r.loss_at_reference_usd)}`)
  return `${amt}: ${bits.join(' · ')}`
}

export function relativeAge(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return ''
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const m = Math.max(0, Math.round((now.getTime() - t) / 60000))
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  if (h < 48) return `${h}h ago`
  return `${Math.round(h / 24)}d ago`
}

export function newRequestId(): string {
  const r = Math.random().toString(16).slice(2, 10)
  return `${Date.now().toString(16)}${r}`.slice(0, 24)
}

export function unwrap<T>(res: unknown): T | null {
  if (!res || typeof res !== 'object') return null
  const o = res as { ok?: boolean; data?: unknown }
  if (o.ok === false) return null
  return ((o.data ?? res) as T) ?? null
}


export const RESEARCH_STATES = ['not_checked', 'checking', 'current', 'partial', 'blocked', 'failed', 'overdue', 'deferred'] as const
export type ResearchState = typeof RESEARCH_STATES[number] | 'not_measured'
export interface ResearchReceipt { state: string | null; reason: string | null }
export interface ResearchEvidence { label: string; state: string | null; reason: string | null; as_of: string | null }
export interface ResearchLifecycle {
  state: ResearchState; last_checked_at: string | null; last_answer_at: string | null
  next_check_at: string | null; next_eligible_at: string | null; last_check_outcome: string | null
  reason: string | null; monitoring_active: boolean | null
  memory_sync: ResearchReceipt; delivery: ResearchReceipt; sources: ResearchEvidence[]; providers: ResearchEvidence[]
}
const text = (value: unknown): string | null => typeof value === 'string' && value.trim() ? value.trim() : null
const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const clock = (value: unknown): string | null => { const s = text(value); return s && Number.isFinite(Date.parse(s)) ? s : null }
const receipt = (value: unknown): ResearchReceipt => { const r = record(value); return { state: text(r.state), reason: text(r.reason) } }
function evidence(value: unknown): ResearchEvidence[] {
  return (Array.isArray(value) ? value : []).map(item => {
    const r = record(item)
    return { label: text(item) ?? ([r.name ?? r.provider ?? r.title ?? r.source ?? r.id, r.model, r.role].map(text).filter(Boolean).join(' · ') || 'Evidence source not named'),
      state: text(r.state ?? r.status), reason: text(r.reason), as_of: clock(r.as_of ?? r.at) }
  })
}
/** Missing measurements never inherit the answer clock or become a fresh/zero receipt. */
export function researchLifecycle(raw: unknown): ResearchLifecycle {
  const r = record(raw), checked = clock(r.last_checked_at)
  let state: ResearchState = (RESEARCH_STATES as readonly unknown[]).includes(r.state) ? r.state as ResearchState : 'not_measured'
  if (state === 'current' && !checked) state = 'not_measured'
  return { state, last_checked_at: checked, last_answer_at: clock(r.last_answer_at), next_check_at: clock(r.next_check_at),
    next_eligible_at: clock(r.next_eligible_at), last_check_outcome: text(r.last_check_outcome),
    reason: text(r.blocker) ?? text(record(r.blocker).reason) ?? text(r.reason),
    monitoring_active: typeof r.monitoring_active === 'boolean' ? r.monitoring_active : null,
    memory_sync: receipt(r.memory_sync), delivery: receipt(r.delivery), sources: evidence(r.sources), providers: evidence(r.providers) }
}
export function researchStatus(lifecycle: ResearchLifecycle): string {
  if (lifecycle.last_checked_at && lifecycle.last_check_outcome === 'no_change' && lifecycle.state === 'current') return 'Checked — no material change'
  const labels: Record<ResearchState, string> = { not_measured: 'Research status: not measured', not_checked: 'Not checked yet',
    checking: 'Checking research…', current: 'Research current', partial: 'Research partial', blocked: 'Research blocked',
    failed: 'Research check failed', overdue: 'Research check overdue', deferred: 'Research check deferred' }
  return labels[lifecycle.state]
}
export interface ResearchRefreshResult { status?: string; request_id?: string; reason?: string | null; blocker?: unknown; lifecycle?: unknown }
export function researchRefreshText(result: ResearchRefreshResult): string {
  const lifecycle = researchLifecycle(result.lifecycle), status = result.status?.toLowerCase()
  const reason = text(result.blocker) ?? text(record(result.blocker).reason) ?? text(result.reason) ?? lifecycle.reason
  const label = status === 'blocked' || status === 'capped' ? 'Research blocked'
    : status === 'failed' ? 'Research refresh failed'
    : ['pending', 'queued', 'scheduled', 'running', 'checking', 'deep_pending'].includes(status ?? '') ? 'Research pending'
    : lifecycle.state !== 'not_measured' ? researchStatus(lifecycle)
    : ['deep', 'complete', 'completed', 'current', 'reanswer'].includes(status ?? '') ? 'Research refresh completed'
    : 'Refresh result not measured'
  return label + (reason ? ` — ${reason}` : '')
}

export const TOOLTIPS = {
  bar: 'Ask the CIO anything — same brain as the CIO Telegram bot. ⌘K / Ctrl-K focuses this box.',
  deep: 'Deep: a research pass through the governed model panel and available sources. It may take a few minutes; spend follows the configured question and daily caps. Missing evidence is stated in the answer. Unchecked = Quick: an answer from what the CIO already knows (no model spend).',
  ask: 'Ask: answers from the CIO record, holdings, Watch, catalysts and earlier questions on the same name. The question and answer are saved to CIO memory and recalled next time this name comes up, here or on Telegram.',
  mic: 'Dictate: tap, speak your question, tap again (or pause) to stop. Uses your device microphone through the browser; edit the text before you press Ask.',
  myQuestions: 'Every question you asked (here or on Telegram), its answer versions, sources and what it started tracking.',
  untrack: 'Stop tracking: removes what this question added (watchlist entry, catalyst watch). History stays.',
  sizing: 'Only for quantities you named. Exposure and risk — never a recommended size.',
} as const

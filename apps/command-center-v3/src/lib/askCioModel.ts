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

export const TOOLTIPS = {
  bar: 'Ask the CIO anything — same brain as the CIO Telegram bot. ⌘K / Ctrl-K focuses this box.',
  deep: 'Deep research: street targets, filings, news and a model panel → a 3/6/12-month prospectus. Spend-capped.',
  untrack: 'Stop tracking: removes what this question added (watchlist entry, catalyst watch). History stays.',
  sizing: 'Only for quantities you named. Exposure and risk — never a recommended size.',
} as const

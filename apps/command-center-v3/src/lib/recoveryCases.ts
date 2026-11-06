/** Recovery & re-entry (piece D) — the view model over GET /api/v2/recovery → `recovery_cases`.
 *
 *  Design: persistent-state/handoffs/recovery-reentry-mockup-20261103-codex (operator-APPROVED 2026-11-06).
 *  The projection is piece A's case row (read through its one accessor) plus `case_version` and the latest quote with its
 *  own observation time. This module only RENDERS that projection: it never computes policy, eligibility, size, stop,
 *  target, risk budget or a recovery state. A value the projection does not carry is "unavailable", never 0.
 *
 *  The four actions are exactly create_reentry_plan, watch, close_case, snooze. They are enabled only when the server
 *  says a validating endpoint exists (`actions.wired === true` with an endpoint) AND the displayed case version is the
 *  one the operator reviewed. Today the server reports `wired: false`, so every action renders disabled "not wired yet". */

export const RECOVERY_ACTIONS = ['create_reentry_plan', 'watch', 'close_case', 'snooze'] as const
export type RecoveryAction = typeof RECOVERY_ACTIONS[number]
export const ACTION_LABEL: Record<RecoveryAction, string> = {
  create_reentry_plan: 'Plan re-entry', watch: 'Watch', close_case: 'Close case', snooze: 'Snooze',
}
export const NOT_WIRED = 'not wired yet'

export const STATE_LABEL: Record<string, string> = {
  STOPPED_OUT: 'Stopped out', WATCHING: 'Watching', RECOVERING: 'Recovering', RE_ENTRY_READY: 'Re-entry ready',
  RE_ENTERED: 'Re-entered', CLOSED: 'Closed', SNOOZED: 'Snoozed',
}
export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'
export const STATE_TONE: Record<string, Tone> = {
  STOPPED_OUT: 'danger', WATCHING: 'neutral', RECOVERING: 'success', RE_ENTRY_READY: 'success',
  RE_ENTERED: 'info', CLOSED: 'neutral', SNOOZED: 'neutral',
}
/** Operator-held states: the case is no longer asking for a decision. */
const SETTLED = new Set(['CLOSED', 'RE_ENTERED', 'SNOOZED'])

export interface RecoveryQuote { price: number; observedAt: string | null; source: string }
export interface RecoveryEligibility { account: string; eligible: boolean | null; eligibleFrom: string | null; reason: string; answered: boolean }
export interface RecoveryCaseView {
  key: string
  version: string | null
  symbol: string
  account: string
  state: string
  stateLabel: string
  stateTone: Tone
  stateSince: string | null
  materialityTier: string | null
  realizedPnl: number | null
  exitPrice: number | null
  exitDate: string | null
  stopPrice: number | null
  quote: RecoveryQuote | null
  eligibility: RecoveryEligibility[]
  pendingOperatorDecision: boolean
  residualNote: string | null
  operatorDecision: string | null
  operatorNote: string | null
  planText: string | null
  gaps: string[]
  asOf: string | null
  source: string | null
  settled: boolean
}
export interface RecoveryProjection {
  state: 'ok' | 'unavailable' | 'missing'
  reason: string | null
  /** null = unknown. Never 0 when the read did not answer. */
  count: number | null
  generatedAt: string | null
  cases: RecoveryCaseView[]
  actionsWired: boolean
  actionsEndpoint: string | null
  actionsReason: string
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v : null)

function planText(plan: unknown): string | null {
  if (!plan || typeof plan !== 'object') return str(plan)
  const p = plan as Record<string, unknown>
  return str(p.proposal) ?? str(p.summary) ?? str(p.text) ?? null
}

export function caseView(raw: any): RecoveryCaseView | null {
  if (!raw || typeof raw !== 'object' || !str(raw.case_key) || !str(raw.symbol)) return null
  const exits: any[] = Array.isArray(raw.exits) ? raw.exits : []
  const last = exits.length ? exits[exits.length - 1] : null
  const state = str(raw.state) ?? 'UNKNOWN'
  const q = raw.quote && typeof raw.quote === 'object' ? raw.quote : null
  const quotePrice = num(q?.price)
  return {
    key: raw.case_key,
    version: str(raw.case_version),
    symbol: String(raw.symbol).toUpperCase(),
    account: str(raw.account) ?? 'Account unavailable',
    state,
    stateLabel: STATE_LABEL[state] ?? 'State unavailable',
    stateTone: STATE_TONE[state] ?? 'warning',
    stateSince: str(raw.state_since),
    materialityTier: str(raw.materiality_tier),
    realizedPnl: num(raw.realized_pnl),
    exitPrice: num(last?.price),
    exitDate: str(last?.date) ?? str(raw.exit_last_date),
    stopPrice: num(last?.stop_price),
    quote: quotePrice != null && quotePrice > 0 ? { price: quotePrice, observedAt: str(q?.observed_at), source: str(q?.source) ?? 'source unnamed' } : null,
    eligibility: (Array.isArray(raw.eligibility) ? raw.eligibility : []).filter((e: any) => e && typeof e === 'object').map((e: any) => ({
      account: str(e.account) ?? 'Account unavailable',
      eligible: typeof e.eligible === 'boolean' ? e.eligible : null,
      eligibleFrom: str(e.eligible_from),
      reason: str(e.reason) ?? '',
      answered: e.answered === true || e.pending_operator_decision === false,
    })),
    pendingOperatorDecision: raw.pending_operator_decision === true,
    residualNote: str(raw.residual_note),
    operatorDecision: str(raw.operator_decision) && raw.operator_decision !== 'none' ? raw.operator_decision : null,
    operatorNote: str(raw.operator_note),
    planText: planText(raw.plan),
    gaps: Array.isArray(raw.gaps) ? raw.gaps.filter((g: unknown) => typeof g === 'string' && g) : [],
    asOf: str(raw.as_of) ?? str(raw.updated_at),
    source: str(raw.source),
    settled: SETTLED.has(state),
  }
}

/** Unwrap the /api/v2/recovery response. Absent block = the server predates piece D → "missing", never "no cases". */
export function recoveryProjection(resp: any, error?: unknown): RecoveryProjection {
  const body = resp?.data && typeof resp.data === 'object' && !Array.isArray(resp.data) && resp.data.recovery_cases ? resp.data : resp
  const block = body?.recovery_cases
  const actions = block?.actions || {}
  const base = {
    generatedAt: str(block?.generated_at),
    actionsWired: actions.wired === true && !!str(actions.endpoint),
    actionsEndpoint: str(actions.endpoint),
    actionsReason: str(actions.reason) ?? 'No server endpoint validates recovery-case actions yet.',
  }
  if (!block || typeof block !== 'object') {
    return { ...base, state: error ? 'unavailable' : 'missing', count: null, cases: [],
      reason: error ? 'The recovery source did not answer.' : 'This server does not publish recovery cases yet.' }
  }
  if (block.state !== 'ok') {
    return { ...base, state: 'unavailable', count: null, cases: [], reason: str(block.reason) ?? 'The recovery case store did not answer.' }
  }
  const cases = (Array.isArray(block.cases) ? block.cases : []).map(caseView).filter((c: RecoveryCaseView | null): c is RecoveryCaseView => !!c)
  return { ...base, state: 'ok', reason: null, count: typeof block.count === 'number' ? block.count : cases.length, cases }
}

const TIER_RANK: Record<string, number> = { T1: 0, T2: 1, T3: 2 }
/** The case's RECORDED impact first (the store's tier), then the most recent exit. Sorting only — nothing is scored here. */
export function byImpact(a: RecoveryCaseView, b: RecoveryCaseView): number {
  const ta = TIER_RANK[a.materialityTier ?? ''] ?? 9, tb = TIER_RANK[b.materialityTier ?? ''] ?? 9
  if (ta !== tb) return ta - tb
  if (a.settled !== b.settled) return a.settled ? 1 : -1
  return String(b.exitDate ?? '').localeCompare(String(a.exitDate ?? ''))
}
/** Home shows the one open, high-impact (T1) case. Lower tiers stay on Risk → Recovery. */
export function homeCase(p: RecoveryProjection): RecoveryCaseView | null {
  return [...p.cases].filter(c => !c.settled && c.materialityTier === 'T1').sort(byImpact)[0] ?? null
}

export type ReviewGate = 'fresh' | 'changed'
/** A changed case requires a fresh review: when the version on screen differs from the version the operator last
 *  reviewed, no action may use the earlier version. A case with no version cannot be bound, so it is never "fresh". */
export function reviewGate(reviewedVersion: string | null | undefined, current: RecoveryCaseView): ReviewGate {
  if (!current.version) return 'changed'
  return reviewedVersion == null || reviewedVersion === current.version ? 'fresh' : 'changed'
}

export interface ActionState { action: RecoveryAction; label: string; enabled: boolean; why: string | null }
export function actionStates(p: RecoveryProjection, c: RecoveryCaseView, gate: ReviewGate, sourceUnavailable: boolean): ActionState[] {
  return RECOVERY_ACTIONS.map(action => {
    let why: string | null = null
    if (!p.actionsWired) why = NOT_WIRED
    else if (sourceUnavailable) why = 'Decisions pause until the case can be refreshed.'
    else if (gate === 'changed') why = 'This case changed. Review the latest case first.'
    else if (c.settled) why = `Case is ${c.stateLabel.toLowerCase()}.`
    return { action, label: ACTION_LABEL[action], enabled: why == null, why }
  })
}

export function eligibilityLine(e: RecoveryEligibility): { value: string; tone: Tone } {
  if (!e.answered) return { value: 'Eligibility pending', tone: 'warning' }
  if (e.eligible === true) return { value: 'Eligible now', tone: 'success' }
  if (e.eligible === false) return { value: e.eligibleFrom ? `Hold through ${e.eligibleFrom}` : 'Not eligible · date unavailable', tone: 'warning' }
  return { value: 'Eligibility unavailable', tone: 'warning' }
}

export const fmtPrice = (v: number | null): string => (v == null ? 'Unavailable' : `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`)
export const fmtUsd = (v: number | null): string => (v == null ? 'Unavailable' : `${v < 0 ? '−' : ''}$${Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 0 })}`)

/** Observation-time label for an ISO instant, in ET. An unparseable or missing time is "time unavailable". */
export function etTime(iso: string | null): string {
  if (!iso) return 'time unavailable'
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return `${iso} (date only)`
  const d = new Date(iso)
  if (Number.isNaN(d.getTime()) || !/T.*(?:Z|[+-]\d\d:?\d\d)$/.test(iso)) return 'time unavailable'
  return d.toLocaleString('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
}
/** "Quote $52.50 · observed Nov 6, 9:55 AM EST · source" — the quote is never shown without its observation time. */
export function quoteLabel(q: RecoveryQuote | null): { value: string; detail: string } {
  if (!q) return { value: 'Unavailable', detail: 'Quote source unavailable' }
  return { value: fmtPrice(q.price), detail: `Quote observed ${etTime(q.observedAt)} · ${q.source}` }
}

export interface StateCounts { needsReview: number; watching: number; snoozed: number; closed: number }
/** Counts by the store's own state. Returned only for an answered read; the caller shows "unavailable" otherwise. */
export function stateCounts(p: RecoveryProjection): StateCounts | null {
  if (p.state !== 'ok') return null
  const n = (pred: (c: RecoveryCaseView) => boolean) => p.cases.filter(pred).length
  return {
    needsReview: n(c => ['STOPPED_OUT', 'RECOVERING', 'RE_ENTRY_READY'].includes(c.state)),
    watching: n(c => c.state === 'WATCHING'),
    snoozed: n(c => c.state === 'SNOOZED'),
    closed: n(c => c.state === 'CLOSED' || c.state === 'RE_ENTERED'),
  }
}

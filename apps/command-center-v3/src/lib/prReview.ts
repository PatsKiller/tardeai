// Approvals → Merges: the independent PR review sheet (Design approvals-pr-review/v001; docs/ops/PR_REVIEW_MODAL_SPEC.md).
// Wire types for GET /api/v2/governance/approvals?kind=MERGE, …/approvals/pr:<N> and …/pr-reviews/summary
// (scripts/lib/pr_review_view.py), plus pure display helpers. No fetch here; no decision is made in the browser.

export type Tone = 'success' | 'warning' | 'danger' | 'neutral' | 'info'
export type Pill = { state: 'ready' | 'notes' | 'held' | 'hold' | 'stale' | 'credit' | 'cannot'; label: string; tone: Tone }
export type Severity = 'BLOCKER' | 'MAJOR' | 'MINOR' | 'NOTE'
export type Finding = { id: string; severity: Severity; title: string; file: string; line: number | null; detail: string; suggestion: string }
export type Hunk = { id: string; file: string; header: string; start_line: number; end_line: number; added: number; removed: number; lines: string[]; truncated: boolean; note: string | null }
export type ReviewFile = { path: string; additions: number; deletions: number; status: string; hunks: Hunk[] }
export type Area = { name: string; files: ReviewFile[]; additions: number; deletions: number }
export type SecondRead = { process_id: string; provider: string | null; run_id: string; id: string; cost_usd: number; verdict: string | null; summary: string | null; findings: Finding[]; error: string | null }
export type PrReview = {
  schema: 'PrReview@v1'; pr: number; title: string; url: string; base_sha: string; head_sha: string; diff_sha256: string
  files: { path: string; additions: number; deletions: number; status: string }[]
  author: { vendor: string; agent: string | null; session: string | null; model: string | null; ids: string[] }
  reviewer: { process_id: string; provider: string; model: string; run_id: string; id: string; started_at: string; finished_at: string; duration_s: number; cost_usd: number; calls: number }
  second_read: SecondRead | null
  independent: { ok: boolean; rule: string; compared: string[]; reviewer: string }
  summary: string; risk: { level: 'LOW' | 'MEDIUM' | 'HIGH'; why: string; floor?: string }
  classes: { held: string[]; held_paths?: Record<string, string[]>; shared_infra: boolean; labels: string[] }
  areas: Area[]
  evidence: { checks: Record<string, string>; tests_changed: number; tests_added: number; dry_run_quoted: boolean; real_layout_proof: boolean; adversarial_receipts: string[] }
  findings: Finding[]; dropped_findings: number; unexplained_hunks: number; hunk_count: number
  verdict: 'MERGE' | 'MERGE_WITH_NOTES' | 'HOLD' | 'CANNOT_REVIEW'; verdict_reason: string; created_at: string; document_sha: string
  status_post?: { posted: boolean; reason?: string } | null
}
export type QueueStatus = { state: 'SETTLING' | 'WAITING_FOR_CREDIT' | 'CANNOT_REVIEW'; reason: string; next_try_at: string | null; head_sha: string }
export type ReviewView = {
  pr: number; title: string; url: string | null; current_head: string; labels: string[]; checks: Record<string, string>; checks_green: boolean
  pill: Pill; stale: boolean; queue: QueueStatus | null; approve_all: { eligible: boolean; reason: string }; review: PrReview | null
}
export type Merge = { head_sha: string; held: boolean; reviewed: boolean; stale: boolean; state: Pill['state']; refusal: string | null }
export type MergeRow = { id: string; kind: 'MERGE'; title: string; pr: number; created_at: string | null; proposed_by: string | null; document_sha?: string
  pill: Pill; summary: string | null; head_sha: string; checks_green: boolean; checks?: Record<string, string>; classes: { held: string[]; shared_infra: boolean }; merge: Merge }
export type ThreadQuestion = { at: string; question: string; head_sha: string; answer: string | null; answered_at: string | null; cost_usd: number | null }
export type ThreadDecision = { at: string; decision: string; effect: string; head_sha: string | null; source_sha: string; actor: string; comment: string }
export type MergeItem = MergeRow & {
  document: { document_sha: string; source_sha: string; changes: { id: string; section: string; after: string }[]; review: ReviewView }
  thread: { questions: ThreadQuestion[]; decisions: ThreadDecision[] }; decisions_store_approved: boolean
}
export type MergesSummary = {
  store_approved: boolean; decisions_store_approved: boolean; label_applier_live: boolean; snapshot_as_of: string | null
  counts: { ready: number; held: number; rereviewing: number; waiting_credit: number; cannot: number; hold: number }
  digest: { last_sent_at: string | null; next_at: string | null }
  spend: { usd_today: number; cap_usd: number; reviews_today: number; max_reviews_per_day: number; questions_today: number }
  models: { normal: string; deep: string } | null
}

export const SEVERITY_LABEL: Record<Severity, string> = { BLOCKER: 'Blocker', MAJOR: 'Major', MINOR: 'Minor', NOTE: 'Note' }
export const SEVERITY_TONE: Record<Severity, Tone> = { BLOCKER: 'danger', MAJOR: 'warning', MINOR: 'info', NOTE: 'neutral' }
export const RISK_TONE: Record<string, Tone> = { LOW: 'success', MEDIUM: 'warning', HIGH: 'danger' }
export const HELD_CLASS_LABEL: Record<string, string> = {
  broker_order: 'broker and orders', secrets: 'secrets', agents_policy: 'policy text', hooks_guard: 'hooks and guard',
  merge_deploy_control: 'merge & deploy tooling', held_label: 'held label', files_unverified: 'files not verified',
}

export const short = (sha: string | null | undefined, n = 9) => (sha ?? '').slice(0, n)

/** Readable ET time, never raw ISO (§28.13 item 5). "Today 12:14 ET" for today, else "Oct 27, 12:14 ET". */
export function etTime(value: string | null | undefined, now: Date = new Date()): string {
  if (!value || !Number.isFinite(Date.parse(value))) return '—'
  const d = new Date(value)
  const fmt = (x: Date, o: Intl.DateTimeFormatOptions) => x.toLocaleString('en-US', { timeZone: 'America/New_York', ...o })
  const day = (x: Date) => fmt(x, { year: 'numeric', month: '2-digit', day: '2-digit' })
  const hm = fmt(d, { hour: 'numeric', minute: '2-digit' })
  return day(d) === day(now) ? `Today ${hm} ET` : `${fmt(d, { month: 'short', day: 'numeric' })}, ${hm} ET`
}

export function waited(value: string | null | undefined, now: number = Date.now()): string {
  if (!value || !Number.isFinite(Date.parse(value))) return 'waiting time unknown'
  const m = Math.max(0, Math.floor((now - Date.parse(value)) / 60000))
  return m < 60 ? `waiting ${m} min` : m < 1440 ? `waiting ${Math.floor(m / 60)} h` : `waiting ${Math.floor(m / 1440)} d`
}

export function classText(c: { held: string[]; shared_infra: boolean } | undefined): string {
  if (c?.held?.length) return 'held · ' + c.held.map(h => HELD_CLASS_LABEL[h] ?? h.replace(/_/g, ' ')).join(', ')
  return c?.shared_infra ? 'shared-infra' : 'normal'
}

export function checksText(checks: Record<string, string> | undefined, green: boolean): string {
  const v = Object.values(checks ?? {})
  if (!v.length) return green ? 'checks green' : 'checks unknown'
  const ok = v.filter(s => s === 'SUCCESS').length
  if (ok === v.length) return `checks ${ok}/${v.length} green`
  return v.some(s => /PENDING|IN_PROGRESS|QUEUED|MISSING/.test(s)) ? 'checks running' : `checks ${ok}/${v.length} green`
}

export function plusMinus(files: { additions: number; deletions: number }[]): string {
  const a = files.reduce((n, f) => n + (f.additions || 0), 0), d = files.reduce((n, f) => n + (f.deletions || 0), 0)
  return `+${a} −${d}`
}

export const riskLabel = (level: string) => `${level.charAt(0)}${level.slice(1).toLowerCase()} risk`
export const money = (usd: number | null | undefined) => (typeof usd === 'number' && Number.isFinite(usd) ? `$${usd.toFixed(2)}` : '—')

/** Why the operator's decision buttons are off, in the order the operator can act on it; null when Approve may be tapped. */
export function approveBlock(item: Pick<MergeItem, 'merge' | 'decisions_store_approved'>, opts: { reviewId: string; unread: number; applierLive: boolean }): string | null {
  if (!item.decisions_store_approved) return 'Decision store not yet approved'
  const r = item.merge.refusal
  if (r === 'REVIEW_STALE') return 'A new push is being re-reviewed'
  if (r === 'REVIEW_REQUIRED') return item.merge.state === 'credit' ? 'The review is waiting for credit' : 'The review has not finished'
  if (r === 'REVIEW_CANNOT_REVIEW') return 'This PR could not be reviewed'
  if (r === 'CHECKS_NOT_GREEN') return 'Required checks are not green on this head'
  if (!opts.reviewId) return 'Opening your reading session…'
  if (opts.unread > 0) return `Read ${opts.unread} more finding${opts.unread === 1 ? '' : 's'}`
  if (!item.merge.held && !opts.applierLive) return 'The label step ships in a separate held PR; use "Approve all" in Telegram meanwhile'
  return null
}

/** The decision line under the buttons (what Approve does). */
export function approveEffect(held: boolean, pr: number, head: string): string {
  return held
    ? `Approve review records that you read this review of head ${short(head)}. It adds no label: a held PR is merged only by you, on GitHub.`
    : `Approve adds operator-merge for this head only. Mergify merges PR #${pr} in the next ET window (never 09:30–16:15 on weekdays). Recorded with your tailnet identity in the decision ledger.`
}

/** A non-terminal earlier approval of another head is shown as cancelled (a new push cancels it). */
export function cancelledApprovals(decisions: ThreadDecision[], currentHead: string): ThreadDecision[] {
  return decisions.filter(d => d.decision === 'APPROVE' && (d.head_sha ?? d.source_sha) !== currentHead)
}

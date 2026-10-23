// Ops → Controls · Data approvals readiness (feat/ops-controls-data-approvals-20261022).
// Operator 2026-10-22: the tab listed 17 domains, all "proposed", with no other information — "This is not a
// dashboard." The server (scripts/lib/data_domain_readiness.py, served in GET /state data_approvals) now sends, per
// domain: store, single writer, readers, live checker findings, freshness, approval and a verdict. This module turns
// that into the summary strip, plain-language labels, filters and tooltips. Pure module: no React, no DOM, no fetch.
// Nothing here approves anything: a grant is the operator's decision, applied by a reviewed PR (AGENTS.md §17, §26.6).

export type Tone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'
export type Verdict = 'APPROVED' | 'READY_TO_APPROVE' | 'NOT_READY'

export type FileList = { count: number; files: string[]; truncated?: boolean }
export type DataFinding = {
  check: string; store?: string; copy?: string; ceiling?: number; now?: number; file?: string; why?: string
  where?: string; writer?: string; projection?: string; files?: FileList
}
export type Freshness = {
  state: 'MEASURED' | 'EMPTY' | 'MISSING' | 'NO_SIGNAL' | 'UNAVAILABLE' | string
  signal?: string; newest_at?: string; age_h?: number | null; stale_after_hours?: number | null
  stale?: boolean | null; detail?: string | null; rows_estimate?: number | null; declared_signal_mismatch?: boolean
}
export type Criterion = { id: string; label: string; source: string; ok: boolean; gaps: string[] }
export type ReaderBatch = { batch?: number; reader?: string; files?: string[]; surfaces?: string[]; facts?: string; approved_on?: string }
export type DataRow = {
  domain: string; title?: string; entity?: string; status?: string; class?: string
  store?: string | null; store_detail?: string | null
  writer?: string | null; writer_status?: string | null; writer_target?: string | null; writer_target_status?: string | null
  writer_note?: string | null
  projection?: string | null; projection_status?: string | null
  refresh_lane?: { runner?: string; lane?: string; note?: string } | null; cadence?: string | null
  freshness_sla?: string | null; stale_after_hours?: number | null
  readers_declared?: string[]; approved_reader_batches?: ReaderBatch[]
  reader_gate?: { tables?: string[]; unbatched?: string[] } | null
  derived_copies?: Array<{ store?: string | null; role?: string; how?: string }>
  supersedes?: string[]; extends_approved?: boolean
  base_domain_approval?: Record<string, string> | null
  decision?: string | null
  approval?: { approved_by?: string; approved_on?: string; reference?: string; scope?: string } | null
  operator_note?: { approval_given?: boolean; decision?: string; pending?: string } | null
  freshness?: Freshness | null
  verdict?: Verdict | null; missing?: string[]; criteria?: Criterion[]; approval_effects?: string[]
  live?: {
    writer_files: FileList; surface_reads: Record<string, FileList>; store_readers: FileList
    findings: DataFinding[]; warn_count: number
  } | null
}
export type DataApprovals = {
  state?: string; reason?: string | null; note?: string
  rows?: DataRow[]
  summary?: { approved: number; ready: number; not_ready: number; unchecked: number; findings: number; operator_approved_pending_pr: string[] }
  scan?: { state: 'DONE' | 'RUNNING' | 'FAILED' | string; as_of?: string | null; age_s?: number | null; duration_s?: number | null; refreshing?: boolean; error?: string | null; refresh_error?: string | null }
  criteria?: Array<{ id: string; label: string; source: string }>
  ttl_s?: number
}

// ── words ─────────────────────────────────────────────────────────────────────────────────────────────────────────
export const EXPLAINER =
  'Proposed = the data flows today, but the one-store / one-writer rule for it is not signed off yet. '
  + 'Approving a row makes the rule binding: the CI gate (check_data_source_authority) then fails the build on a second '
  + 'writer or a page reading a copy above the ceilings measured at approval, instead of only warning. '
  + 'Approval itself creates no table, moves no reader and changes no page; those are separate decisions.'

export const VERDICT_TIP: Record<Verdict, string> = {
  APPROVED: 'Granted by the operator: the row is in domains[] with its approval record and its ceilings bind in CI.',
  READY_TO_APPROVE: 'Promoted in memory with today\'s ceilings, the row passes every gate it would face once binding. '
    + 'Approval is still the operator\'s decision, applied by a reviewed PR.',
  NOT_READY: 'Promoted today, the row would fail a gate. Each missing item below is the gate\'s own finding; fix those first.',
}

export const SUMMARY_TIP = {
  approved: 'Rows the operator has granted (in domains[] with a dictionary block). Their ceilings fail CI when exceeded.',
  ready: 'Proposed rows that would pass every gate if approved now. Approving is an operator decision.',
  not_ready: 'Proposed rows that would fail a gate if approved now. Open a row to see exactly what is missing.',
  findings: 'Live checker results across all rows: today these are warnings for proposed rows (they never fail the build) and '
    + 'failures for approved rows.',
}

export const CHECK_TIP: Record<string, string> = {
  DICTIONARY_SECOND_WRITER: 'More files write this store than its ceiling. For a proposed row this is a warning; at approval the ceiling is set to today\'s count and may only fall.',
  NON_AUTHORITATIVE_READ: 'A page or API file reads a derived or retiring copy instead of the store through its projection.',
  UNAPPROVED_READER: 'A file reads a gated store without an operator-approved reader batch. This fails CI today.',
  READER_GRANT_INVALID: 'An approved reader batch entry is incomplete or names a file that no longer reads the store.',
  DICTIONARY_INVALID: 'The proposed row is malformed. This always fails CI.',
  WRITER_CLAIM_FALSE: 'The row names one writer, but other files also write the store.',
}

export function verdictView(r: Pick<DataRow, 'verdict' | 'operator_note'>): { label: string; tone: Tone; tip: string } {
  const pending = !!r.operator_note?.approval_given && r.verdict !== 'APPROVED'
  switch (r.verdict) {
    case 'APPROVED': return { label: 'Approved', tone: 'success', tip: VERDICT_TIP.APPROVED }
    case 'READY_TO_APPROVE':
      return pending
        ? { label: 'Approved by operator · PR pending', tone: 'info', tip: `${VERDICT_TIP.READY_TO_APPROVE} The operator has approved it (${r.operator_note?.decision || 'decision recorded'}); it binds once ${r.operator_note?.pending || 'its own PR'} merges.` }
        : { label: 'Ready to approve', tone: 'info', tip: VERDICT_TIP.READY_TO_APPROVE }
    case 'NOT_READY':
      return { label: pending ? 'Not ready · operator approved' : 'Not ready', tone: 'warning', tip: VERDICT_TIP.NOT_READY }
    default: return { label: 'Checking…', tone: 'neutral', tip: 'The live scan has not finished yet; registry facts are shown meanwhile.' }
  }
}

export function writerText(r: Pick<DataRow, 'writer' | 'writer_status' | 'writer_target' | 'writer_target_status' | 'live'>): string {
  const n = r.live?.writer_files?.count
  if (r.writer && r.writer_status !== 'UNCONSOLIDATED') {
    const extra = typeof n === 'number' && n > 1 ? ` — ${n} files write it today` : ''
    return `${r.writer} (single writer)${extra}`
  }
  const today = typeof n === 'number' ? `${n} writer file${n === 1 ? '' : 's'} today` : 'writers not yet counted'
  const target = r.writer_target ? `; target ${r.writer_target}${r.writer_target_status ? ` (${r.writer_target_status})` : ''}` : ''
  return `Not consolidated — ${today}${target}`
}

function ago(h: number): string {
  if (h < 1) return `${Math.round(h * 60)} min ago`
  if (h < 48) return `${h.toFixed(1)} h ago`
  return `${(h / 24).toFixed(1)} d ago`
}

export function freshnessView(f: Freshness | null | undefined): { text: string; tone: Tone; tip: string } {
  if (!f) return { text: 'Not measured yet', tone: 'neutral', tip: 'The live scan has not finished.' }
  const sla = typeof f.stale_after_hours === 'number' ? `stale after ${f.stale_after_hours} h` : 'no staleness limit declared'
  switch (f.state) {
    case 'MEASURED': {
      const age = typeof f.age_h === 'number' ? ago(f.age_h) : 'age unknown'
      return { text: `Updated ${age}${f.stale ? ' — stale' : ''}`, tone: f.stale ? 'warning' : 'success', tip: `${f.signal || 'signal'} = ${f.newest_at || '—'}; ${sla}.` }
    }
    case 'EMPTY': return { text: 'Store is empty', tone: 'warning', tip: `${f.signal || ''} returned no rows; ${sla}.` }
    case 'MISSING': return { text: 'Store does not exist', tone: 'warning', tip: f.detail || 'absent' }
    case 'NO_SIGNAL': return { text: f.declared_signal_mismatch ? 'Declared time column not found' : 'No freshness signal declared', tone: f.declared_signal_mismatch ? 'warning' : 'neutral', tip: `${f.detail || ''}${typeof f.rows_estimate === 'number' ? ` · ~${f.rows_estimate.toLocaleString('en-US')} rows` : ''}` }
    default: return { text: 'Freshness unavailable', tone: 'warning', tip: f.detail || 'the probe could not run' }
  }
}

export function findingText(f: DataFinding): string {
  switch (f.check) {
    case 'DICTIONARY_SECOND_WRITER': return `${f.now} writer files on ${f.store} (target ${f.ceiling})`
    case 'NON_AUTHORITATIVE_READ': return `${f.now} page/API file${f.now === 1 ? '' : 's'} read copy ${f.copy}`
    case 'UNAPPROVED_READER': return `${f.file} reads the gated store without an approved batch`
    case 'DICTIONARY_INVALID': return `malformed: ${f.why || f.where || ''}`
    default: return `${f.check}${f.file ? ` · ${f.file}` : ''}${f.why ? ` · ${f.why}` : ''}`
  }
}

// ── summary + filters ─────────────────────────────────────────────────────────────────────────────────────────────
export type DataSummary = { approved: number; ready: number; notReady: number; findings: number; unchecked: number; pendingPr: string[] }
/** Counted from the rows (the server's summary is the same arithmetic; rows are the truth when they disagree). */
export function summarize(rows: DataRow[] | null | undefined): DataSummary {
  const rs = rows || []
  return {
    approved: rs.filter(r => r.verdict === 'APPROVED').length,
    ready: rs.filter(r => r.verdict === 'READY_TO_APPROVE').length,
    notReady: rs.filter(r => r.verdict === 'NOT_READY').length,
    findings: rs.reduce((n, r) => n + (r.live?.findings?.length || 0), 0),
    unchecked: rs.filter(r => !r.verdict).length,
    pendingPr: rs.filter(r => r.operator_note?.approval_given && r.verdict !== 'APPROVED').map(r => r.domain),
  }
}

export type DataFilter = 'all' | 'ready' | 'not_ready' | 'approved' | 'findings'
export const DATA_FILTERS: Array<[DataFilter, string]> = [
  ['all', 'All'], ['ready', 'Ready to approve'], ['not_ready', 'Not ready'], ['approved', 'Approved'], ['findings', 'With findings'],
]
export function matchesDataFilter(r: DataRow, f: DataFilter): boolean {
  switch (f) {
    case 'ready': return r.verdict === 'READY_TO_APPROVE'
    case 'not_ready': return r.verdict === 'NOT_READY'
    case 'approved': return r.verdict === 'APPROVED'
    case 'findings': return (r.live?.findings?.length || 0) > 0
    default: return true
  }
}

/** Not ready first (they need work), then ready, then approved; unchecked last; registry order within a group. */
export function sortRows(rows: DataRow[] | null | undefined): DataRow[] {
  const rank = (v?: Verdict | null) => (v === 'NOT_READY' ? 0 : v === 'READY_TO_APPROVE' ? 1 : v === 'APPROVED' ? 2 : 3)
  return (rows || []).map((r, i) => ({ r, i })).sort((a, b) => rank(a.r.verdict) - rank(b.r.verdict) || a.i - b.i).map(x => x.r)
}

export function scanText(scan: DataApprovals['scan'] | null | undefined): { text: string; tone: Tone } {
  if (!scan) return { text: 'Live scan status unavailable', tone: 'warning' }
  if (scan.state === 'RUNNING') return { text: 'Live scan running — verdicts appear when it finishes', tone: 'neutral' }
  if (scan.state === 'FAILED') return { text: `Live scan FAILED: ${scan.error || 'no reason'} — no verdict is shown`, tone: 'danger' }
  const age = typeof scan.age_s === 'number' ? `${scan.age_s}s ago` : 'age unknown'
  const err = scan.refresh_error ? ` · last refresh failed: ${scan.refresh_error}` : ''
  return { text: `Live scan ${age} (took ${scan.duration_s ?? '—'}s)${scan.refreshing ? ' · refreshing' : ''}${err}`, tone: scan.refresh_error ? 'warning' : 'neutral' }
}

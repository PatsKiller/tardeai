// Deployment log — the operator's "what was deployed, when, what it fixed, what is the truth" view (LQ-20261107-1794).
// Pure projection of the `deployment_log` section of GET /api/v2/ops/releases-schedules
// (scripts/lib/releases_schedules_view.py), which serves a lead-owned DeploymentLog@v1 file.
//
// THE RULE: a truth chip is VERIFIED only when the record's own `truth.state` is exactly 'VERIFIED'. Nothing here
// upper-cases, trims or infers a state — a lowercase 'verified', a missing truth member or a state this build does
// not know renders as UNKNOWN, never green. The operator asked for "what is the truth", and a page that quietly
// promoted a not-re-measured fix to VERIFIED would be the false positive the whole log exists to prevent.
import type { Tone } from './designTokens'

export type DeployTruth = { state: string | null; text: string | null }
export type DeployItem = { lq: string | null; title: string | null; owner: string | null; truth: DeployTruth | null }
export type DeployRow = {
  activated_at: string | null; activated_et: string | null; kind: string | null; rollback: boolean
  release: string | null; sha: string | null; short_sha: string | null
  previous_release: string | null; previous_sha: string | null
  commit_count: number | null; commits: string[] | null; commits_shown: number | null
  items: DeployItem[] | null; is_current: boolean
}
export type DeploymentSummary = { deploys?: number | null; rollbacks?: number | null; lq_items?: number | null
  verified?: number | null; not_remeasured?: number | null }
export type DeploymentLog = {
  since: string | null; generated_at: string | null; current_release: string | null
  summary: DeploymentSummary | null; truth_rule: string | null
  deployments_total: number | null; shown: number | null; truncated: boolean | null; deployments: DeployRow[] | null
}

export type TruthChip = { label: string; tone: Tone; text: string | null; state: string | null }

/** One LQ item's truth as a chip. Only the record's exact 'VERIFIED' is green. */
export function truthChip(t: DeployTruth | null | undefined): TruthChip {
  const state = typeof t?.state === 'string' && t.state ? t.state : null
  const text = typeof t?.text === 'string' && t.text ? t.text : null
  if (state === 'VERIFIED') return { label: 'VERIFIED', tone: 'success', text, state }
  if (state === 'NOT_REMEASURED') return { label: 'NOT RE-MEASURED', tone: 'warning', text, state }
  if (state === 'NO_CHANGE') return { label: 'NO CHANGE', tone: 'neutral', text, state }
  if (state === 'UNTRACKED') return { label: 'UNTRACKED', tone: 'neutral', text, state }
  // Absent, empty or unrecognised: say so, with the record's own word, and never upgrade it.
  return { label: state ? `UNKNOWN (${state})` : 'NOT RECORDED', tone: 'neutral', text, state }
}

/** Everything one deployment fixed, one line per LQ item. */
export function fixedItems(row: DeployRow | null | undefined): DeployItem[] {
  return Array.isArray(row?.items) ? row!.items.filter(i => i && (i.lq || i.title)) : []
}

/** The commit subjects to show for a row that fixed no tracked LQ item. */
export function commitSubjects(row: DeployRow | null | undefined): string[] {
  return Array.isArray(row?.commits) ? row!.commits.filter(c => typeof c === 'string' && c) : []
}

export function commitLine(row: DeployRow | null | undefined): string {
  if (typeof row?.commit_count === 'number' && row.commit_count >= 0) {
    return `${row.commit_count.toLocaleString('en-US')} commit${row.commit_count === 1 ? '' : 's'}`
  }
  const n = commitSubjects(row).length
  return n ? `${n} commit${n === 1 ? '' : 's'}` : 'commit count not recorded'
}

/** The one-line "what it was" label. A rollback is named as one; nothing else is inferred from the SHA. */
export function kindLabel(row: DeployRow | null | undefined): { label: string; tone: Tone } {
  const kind = typeof row?.kind === 'string' && row.kind ? row.kind : 'kind not recorded'
  if (row?.rollback === true || /rollback/i.test(kind)) return { label: kind, tone: 'warning' }
  return { label: kind, tone: 'neutral' }
}

/** The deployment date in ET. The wire's own ET string when it has one, else the ISO stamp; never a blank row. */
export function whenET(row: DeployRow | null | undefined, etDateTime: (iso: string | null | undefined) => string): string {
  if (typeof row?.activated_et === 'string' && row.activated_et) return row.activated_et
  const rendered = etDateTime(row?.activated_at ?? null)
  return rendered === '—' ? 'date not recorded' : rendered
}

/** Summary chips: deploys · verified · not re-measured. A count the record does not carry is "unknown", never 0. */
export function summaryChips(v: DeploymentLog | null | undefined): Array<{ label: string; value: string; tone: Tone }> {
  const count = (n: number | null | undefined) =>
    typeof n === 'number' && Number.isFinite(n) && n >= 0 ? n.toLocaleString('en-US') : 'unknown'
  const s = v?.summary ?? null
  const chip = (label: string, n: number | null | undefined, tone: Tone) => ({
    label, value: count(n), tone: typeof n === 'number' && n >= 0 ? tone : ('warning' as Tone) })
  return [
    chip('deploys', s?.deploys, 'neutral'),
    chip('verified', s?.verified, 'success'),
    chip('not re-measured', s?.not_remeasured, 'warning'),
  ]
}

/** "showing the newest 200 of 139" — stated only when the response was actually cut. */
export function shownLine(v: DeploymentLog | null | undefined): string | null {
  if (!v || v.truncated !== true) return null
  const shown = typeof v.shown === 'number' ? v.shown : null
  const total = typeof v.deployments_total === 'number' ? v.deployments_total : null
  if (shown === null || total === null) return 'older deployments are not shown'
  return `showing the newest ${shown} of ${total} deployments`
}

/** The section heading: "Deployment log (since 2026-11-03)". */
export function logTitle(v: DeploymentLog | null | undefined): string {
  const since = typeof v?.since === 'string' && v.since ? v.since : null
  return since ? `Deployment log (since ${since})` : 'Deployment log'
}

/** One row's headline for the list: how many fixes it carries. */
export function fixedLine(row: DeployRow | null | undefined): string {
  const items = fixedItems(row)
  if (items.length) return `Fixed: ${items.length} item${items.length === 1 ? '' : 's'}`
  const subjects = commitSubjects(row)
  return subjects.length ? commitLine(row) : 'no commit subjects recorded'
}

// Releases & Schedules, operator view (operator 2026-11-03: "its ok not clear and actionable for a non developer").
// Pure projection over the two payloads the page already fetches — GET /api/v2/ops/releases-schedules and
// GET /api/v2/ops/in-flight. It invents no facts: every function either derives a sentence from a served value or
// says in words that the value is missing and why. No code, no SHA, no branch, no PR number reaches the default view.
import type { InFlightPr } from './deployInFlight.ts'
import { evidenceSentence } from './deployInFlight.ts'
import { operatorStage, type OperatorStage } from './workPipeline.ts'
import { prPipelineStage } from './deployInFlight.ts'
import type { SectionView } from './releasesSchedules.ts'

export type Tone = 'success' | 'warning' | 'danger' | 'neutral'

/** Strip machine identifiers out of a sentence a person has to read. Never returns an empty string. */
export function plainText(raw: unknown, fallback = 'an unnamed change'): string {
  const s = String(raw ?? '').trim()
  if (!s) return fallback
  const cleaned = s
    .replace(/(?:PR[-\s]?#?\d+|#\d+)/gi, 'the change')
    .replace(/\b[0-9a-f]{7,40}\b/gi, '')
    .replace(/\b(?:feat|fix|wt|release|hotfix)\/[A-Za-z0-9._/-]+/g, 'the work')
    .replace(/\s{2,}/g, ' ')
    .trim()
  return cleaned || fallback
}

/** The operator's words for a reason code the payload carries. Unknown codes are shown as a plain statement about
 *  the source, never as the raw identifier. */
const REASON_SENTENCE: Record<string, string> = {
  no_review_record: 'nobody has recorded a review for this version yet',
  no_ci_observation: 'the checks for this version have not been observed',
  stale_review_for_other_head: 'the review on record is for an older version of this change',
  stale_ci_for_other_head: 'the check result on record is for an older version of this change',
  target_head_missing: 'the version the check refers to is no longer the one proposed',
  coordination_unavailable: 'the record of reviews and checks could not be read',
  head_changed: 'the change moved on after it was checked',
}
export function plainReason(code: unknown, fallback = 'the source did not say why'): string {
  const key = String(code ?? '').trim()
  return REASON_SENTENCE[key] ?? (key ? `the source says: ${key.replace(/_/g, ' ')}` : fallback)
}

/** One sentence for a review/CI factor, or null when there is something worth saying about it. */
export function checkSentence(f: { state?: string | null; reason?: string | null; gap?: string | null } | null | undefined): string | null {
  if (!f) return null
  if (f.state === 'MERGE' || f.state === 'GREEN') return null
  if (f.state === 'CHANGES') return 'a reviewer asked for changes'
  if (f.state === 'RED') return 'the checks failed'
  if (f.state === 'PENDING') return 'the checks are still running'
  if (f.state === 'SKIPPED') return 'the checks were skipped'
  if (f.state === 'NONE') return 'it has not been reviewed yet'
  if (f.state === 'UNAVAILABLE') return 'CI not checked right now'
  const st = (f as { evidence_state?: unknown }).evidence_state
  return evidenceSentence(st) ?? plainReason(f.reason ?? f.gap)
}

export type StatusLine = { tone: Tone; headline: string; detail: string; clock: string }

const CLOCK_MISSING = 'as of unknown — the source did not record when it checked'

/** Block 1: what is live, in one line, with its own clock. Never green when a contributing section is unavailable. */
export function liveNow(sections: Record<string, SectionView<any>>, generatedAt: string | null | undefined, when: (v: string | null | undefined) => string): StatusLine {
  const serving = sections.serving
  const next = sections.next_release
  const errors = sections.release_errors
  const clock = serving?.asOf ? `Checked ${when(serving.asOf)}` : generatedAt ? `Checked ${when(generatedAt)}` : CLOCK_MISSING
  if (!serving || serving.state === 'UNAVAILABLE' || !serving.value) {
    return { tone: 'warning', headline: 'Cannot tell what is live right now', clock,
      detail: `${plainReason(serving?.reason, 'the release source could not be read')}. This is not an all-clear.` }
  }
  const sv = serving.value as { release_name?: string | null; since?: string | null }
  const name = sv.release_name && !/[0-9a-f]{7,}/i.test(sv.release_name) ? plainText(sv.release_name, 'the current release') : 'the current release'
  const since = sv.since ? ` since ${when(sv.since)}` : ''
  const problems: string[] = []
  if (errors?.state === 'OK' && Array.isArray(errors.value?.rows) && errors.value.rows.length) problems.push(`${errors.value.rows.length} release error(s) recorded`)
  if (next?.state === 'OK' && next.value?.is_serving !== true) problems.push('the newest change is not live yet')
  return {
    tone: problems.length ? 'warning' : 'success',
    headline: `Live now: ${name}`,
    detail: problems.length ? `${problems.join(' · ')}.` : `Nothing is waiting to go live.${since}`,
    clock,
  }
}

export type StageGroup = { stage: OperatorStage; label: string; rows: InFlightPr[] }

const GROUP_ORDER: OperatorStage[] = ['building', 'review', 'ready', 'merging', 'live']

/** Block 3: open changes grouped by what is actually happening to them. Unknown facts fall into the earliest group. */
export function goingLive(prs: InFlightPr[]): StageGroup[] {
  const by = new Map<OperatorStage, InFlightPr[]>()
  for (const pr of prs) {
    const op = operatorStage({ stage: prPipelineStage(pr) })
    if (!op) continue
    by.set(op, [...(by.get(op) ?? []), pr])
  }
  return GROUP_ORDER.filter(g => by.has(g)).map(stage => ({
    stage, rows: by.get(stage)!,
    label: { backlog: 'Not started', building: 'Being built', review: 'Waiting for review', ready: 'Ready',
      merging: 'Merging in the next window', live: 'Live' }[stage],
  }))
}

/** Block 2: only the changes where the OPERATOR is the one who must act. */
export function needsYou(prs: InFlightPr[]): InFlightPr[] {
  return prs.filter(p => {
    // The server decides who may act; fall back to the same rules only when an older payload omits them.
    const actions = p.operator_actions
    if (actions && Array.isArray(actions.eligible)) return actions.eligible.includes('approve')
    return !p.is_draft && p.mergeable !== 'CONFLICTING' && !p.has_operator_merge
      && p.work?.review?.state === 'MERGE' && p.work?.ci?.state === 'GREEN'
  })
}

/** Block 4: stuck, and whose step it is. The threshold is stated in the heading, never implied. */
export function stuck(prs: InFlightPr[]): Array<{ pr: InFlightPr; because: string; whose: string }> {
  const out: Array<{ pr: InFlightPr; because: string; whose: string }> = []
  for (const p of prs) {
    const because = p.mergeable === 'CONFLICTING' ? 'conflicts with newer code'
      : checkSentence(p.work?.review) ?? checkSentence(p.work?.ci) ?? (p.work?.blockers?.length ? 'a blocker is recorded' : null)
    if (!because) continue
    const whose = p.work?.next_action_source === 'claims' ? 'the agent that owns it' : 'the coordinator'
    out.push({ pr: p, because, whose })
  }
  return out
}

/** Block 8: the jobs sentence and its clock. A number never appears without one. */
export function jobsLine(ledger: SectionView<any> | undefined, when: (v: string | null | undefined) => string): { text: string; clock: string; tone: Tone } {
  const clock = ledger?.asOf ? `counted ${when(ledger.asOf)}` : CLOCK_MISSING
  const td = ledger?.state === 'OK' ? ledger.value : null
  if (!td) return { text: 'Scheduled job health cannot be read — this is not the same as zero runs.', clock, tone: 'warning' }
  const waits = td.dead_letters?.available ? `${Number(td.dead_letters.unreleased ?? 0).toLocaleString('en-US')} failed runs waiting to be cleared` : 'the number of failed runs waiting is not available'
  return { tone: Number(td.errors_total ?? 0) || Number(td.dead_letters?.unreleased ?? 0) ? 'warning' : 'success',
    text: `${Number(td.total ?? 0).toLocaleString('en-US')} runs today: ${Number(td.errors_total ?? 0)} errors, ${waits}.`, clock }
}

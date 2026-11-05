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

/** Props for the engineer panel, so "closed" cannot be contradicted by an inline style (codex R3, PR 2541).
 *
 *  The panel used to carry `hidden` AND an unconditional `display: 'grid'`. An inline display beats the hidden
 *  attribute's UA rule, so the panel was laid out while its toggle said CLOSED (`aria-expanded=false`, computed
 *  display=grid, 868 px of content at 1440 px and 1220 px at 390 px). One function now decides both, so there is no
 *  second place to disagree with the first.
 */
export function engineerPanelProps(open: boolean): { hidden: boolean; style: { display: 'grid' | 'none' } } {
  return { hidden: !open, style: { display: open ? 'grid' : 'none' } }
}

/** Strip machine identifiers out of a sentence a person has to read. Never returns an empty string. */
export function plainText(raw: unknown, fallback = 'an unnamed change'): string {
  const s = String(raw ?? '').trim()
  if (!s) return fallback
  const cleaned = s
    .replace(/(?:PR[-\s]?#?\d+|#\d+)/gi, 'the change')
    .replace(/\b[0-9a-f]{7,40}\b/gi, '')
    .replace(/\b(?:feat|fix|wt|release|hotfix)\/[A-Za-z0-9._/-]+/g, 'the work')
    // codex R6 (PR 2541): a file path and a database-style identifier are machine diagnostics. The operator asked for
    // plain English, so they are named as what they are instead of printed. Both patterns need a name-like shape so
    // ordinary prose ("per item", "on hold") is untouched.
    .replace(/(?:^|\s)(?:~|\/)[\w./-]*[\w/]/g, ' a file location')
    .replace(/\b[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}\b/g, ' an internal name')
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
  if (f.state === 'NONE') return /\s/.test(String(f.reason ?? '')) ? String(f.reason) : 'it has not been reviewed yet'
  if (f.state === 'UNAVAILABLE') return 'CI not checked right now'
  const st = (f as { evidence_state?: unknown }).evidence_state
  const why = String(f.reason ?? '').trim()
  // a served reason that is already a sentence is shown as written; a code is translated
  if (/\s/.test(why)) return why
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
  const sv = serving.value as { release_name?: string | null; since?: string | null; pins_agree?: boolean | null }
  const name = sv.release_name && !/[0-9a-f]{7,}/i.test(sv.release_name) ? plainText(sv.release_name, 'the current release') : 'the current release'
  const since = sv.since ? ` since ${when(sv.since)}` : ''
  // codex R2 (PR 2541): a RETAINED value is not a verified current one. A stale reading, a pin disagreement, and an
  // unreadable neighbouring source must each stop the summary from claiming "All good" — the page may say what it
  // knows, never more.
  const problems: string[] = []
  const unknowns: string[] = []
  if (serving.state === 'STALE') problems.push('this reading is older than 5 minutes, so what is running may have changed')
  if (sv.pins_agree === false) problems.push('what is actually running disagrees with the recorded current release')
  if (!errors || errors.state !== 'OK') unknowns.push('whether any release failed could not be read')
  else if (Array.isArray(errors.value?.rows) && errors.value.rows.length) problems.push(`${errors.value.rows.length} release error(s) recorded`)
  if (!next || next.state !== 'OK') unknowns.push('whether anything newer is waiting could not be read')
  else if (next.value?.is_serving !== true) problems.push('the newest change is not live yet')
  const detail = problems.length ? `${problems.join(' · ')}.`
    : unknowns.length ? `Nothing known is wrong. ${unknowns.join(' · ')}.`
      : `Nothing is waiting to go live.${since}`
  return {
    tone: problems.length || unknowns.length ? 'warning' : 'success',
    headline: `Live now: ${name}`,
    detail,
    clock,
  }
}

/** Merged-but-not-live, derived from the RELEASE data rather than from a list of open PRs (codex R5, PR 2541).
 *
 *  The page only receives OPEN pull requests, so a change that has MERGED but is not yet the version running cannot
 *  appear at all — the page could say "Nothing is going live today" while exactly that was true. The evidence for the
 *  real state is already in this payload and needs no PR feed: the serving release identity, and main HEAD with its
 *  commit count ahead of that release. `is_serving` is the producer's own comparison of those two, and the engine is
 *  not allowed to reinterpret it — it is only translated.
 *
 *  `waiting` is what the page keys its "nothing is going live" sentence on: when true, that sentence must not appear.
 */
export type MergedWaiting = { known: boolean; waiting: boolean; headline: string; detail: string; tone: Tone }

export function mergedWaiting(
  next: { is_serving?: boolean | null; commits_ahead?: number | null; subject?: string | null
    committed_at?: string | null; prs_since_serving?: number[] | null; prs_reason?: string | null } | null | undefined,
  serving: { release_name?: string | null; since?: string | null } | null | undefined,
  when: (v: string | null | undefined) => string,
): MergedWaiting {
  if (!next || typeof next.is_serving !== 'boolean') {
    return { known: false, waiting: false, tone: 'warning',
      headline: 'Whether merged work is still waiting cannot be read',
      detail: 'The page could not compare what is merged with what is running, so treat "nothing is going live" as unknown rather than as an all-clear.' }
  }
  // A release NAME is a build hash plus a suffix; showing it here would put a SHA in the operator block, and
  // stripping the hash leaves a fragment. The fact that identifies the running version without code is WHEN it started
  // serving — which is exactly the activation evidence R5 asks for.
  const running = serving?.since ? `the release that has been serving since ${when(serving.since)}`
    : 'the release that is serving now'
  if (next.is_serving) {
    return { known: true, waiting: false, tone: 'success',
      headline: 'Main is the version that is running',
      detail: `Nothing merged is waiting to be promoted. The version running is ${running}.` }
  }
  const ahead = next.commits_ahead
  const count = typeof ahead === 'number' && ahead > 0
    ? `${ahead} merged change${ahead === 1 ? '' : 's'} ${ahead === 1 ? 'is' : 'are'} not live yet`
    : 'A merge is not live yet'
  const merged = next.committed_at ? ` The newest of them was merged ${when(next.committed_at)}.` : ''
  const prs = Array.isArray(next.prs_since_serving) && next.prs_since_serving.length
    ? ` They came in through ${next.prs_since_serving.length} change${next.prs_since_serving.length === 1 ? '' : 's'}.` : ''
  return { known: true, waiting: true, tone: 'warning', headline: count,
    detail: `The version running is ${running}; code merged after that has not been promoted yet.${merged}${prs}` }
}

/** What the open-change source itself is doing, in one sentence, for lists that DO have rows (codex R4, PR 2541).
 *
 *  A stale or still-loading list that happens to be non-empty used to render exactly like a current one: only the
 *  empty case said anything about the source. Rows under a stale reading are historical, and the sentence has to be
 *  there before them, not only in their absence.
 */
export function flightFreshnessNote(input: { loading?: boolean; stale?: boolean; asOf?: string | null },
                                     when: (v: string | null | undefined) => string): string | null {
  if (input.loading) return 'The open-change list is still being read; what is shown is from the previous answer.'
  if (input.stale) {
    return `The open-change list is out of date${input.asOf ? ` (last read ${when(input.asOf)})` : ''}; the rows below may have moved since.`
  }
  return null
}

/** The coordination source's own state (codex R4, PR 2541). PARTIAL is not UNAVAILABLE and neither is "nobody working":
 *  a partly-answered list proves nothing about the agents it did not mention. */
export function coordinationNote(status: 'OK' | 'PARTIAL' | 'UNAVAILABLE'): string | null {
  if (status === 'OK') return null
  if (status === 'PARTIAL') return 'The agent list only partly answered, so an agent missing from it is not shown to be idle.'
  return 'Cannot tell who is working — the agent list did not answer. That is not the same as nobody working.'
}

/** One agent's state in words, and whether it is safe for the page to colour it as idle.
 *  `null` means the page does not know — which is not the same as idle, and must not be drawn as such. */
export function agentStateSentence(state: string | null | undefined): { text: string; idle: boolean | null } {
  const s = String(state ?? '').trim().toLowerCase()
  if (!s) return { text: 'its state was not recorded', idle: null }
  if (s === 'working' || s === 'building' || s === 'running') return { text: 'working now', idle: false }
  if (s === 'idle' || s === 'free') return { text: 'idle', idle: true }
  if (s === 'blocked') return { text: 'blocked on something', idle: true }
  if (s === 'waiting') return { text: 'waiting its turn', idle: true }
  if (s === 'stale') return { text: 'its last report is out of date', idle: null }
  return { text: `reported as ${s.replace(/_/g, ' ')}`, idle: null }
}

// ── THE GENERAL PROPERTY (codex third read, PR 2541) ───────────────────────────────────────────────────────────
//
// Three rounds of this page produced the same defect in different clothes: the page had LESS information than it
// needed to be decisive, and rendered decisiveness anyway. "Unknown source" → an empty list. "Agent list did not
// answer" → "No agent is working". "Comparison unavailable" → a verdict. Two special cases were fixed; the class did
// not go away, because each fix taught one panel a trick instead of changing the rule.
//
// The rule: a panel may assert "none" ONLY when its own source is CURRENT — answered, fresh, and not errored. In every
// other state it says what it does not know and why. One source's positive answer never certifies another source's
// emptiness, and a known fact about one question (merged work is waiting) never certifies an empty census of another
// (nothing is waiting to merge).

export type SourceState = 'current' | 'stale' | 'loading' | 'unavailable' | 'unknown'
export type SourceOpinion = { state: SourceState; canAssertEmpty: boolean; note: string }

const SOURCE_REASON: Record<Exclude<SourceState, 'current'>, string> = {
  stale: 'the list on record is out of date',
  loading: 'it is still being read',
  unavailable: 'it could not be read',
  unknown: 'no answer was recorded',
}

/** What the open-change (in-flight) source can support. `answered` is "a response object exists at all" — a page with
 *  no data, no error and no loading flag is UNKNOWN, not empty. */
export function flightSource(input: { answered?: boolean; loading?: boolean; stale?: boolean; error?: string | null },
                             when: (v: string | null | undefined) => string, asOf?: string | null): SourceOpinion {
  const clock = asOf ? ` (last read ${when(asOf)})` : ''
  if (input.error) return { state: 'unavailable', canAssertEmpty: false,
    note: `The open-change list could not be read${clock}, so an empty list here is not proof that nothing is open.` }
  if (input.loading && !input.answered) return { state: 'loading', canAssertEmpty: false,
    note: 'Still asking the open-change source — this is not an answer yet.' }
  if (input.stale && !input.answered) return { state: 'stale', canAssertEmpty: false,
    note: `The open-change list on record is out of date${clock}, so an empty list here is not proof that nothing is open.` }
  if (!input.answered) return { state: 'unknown', canAssertEmpty: false,
    note: 'Nothing has been read from the open-change source yet, so an empty list here is not proof that nothing is open.' }
  if (input.stale) return { state: 'stale', canAssertEmpty: false,
    note: `The open-change list is out of date${clock}; what is shown may have moved since.` }
  return { state: 'current', canAssertEmpty: true, note: '' }
}

/** What the agent-list (coordination) source can support. It inherits the whole response's staleness: a cached
 *  response whose coordination block still says OK is NOT a current answer (codex third read, counterexample 1). */
export function coordinationSource(input: { status: 'OK' | 'PARTIAL' | 'UNAVAILABLE' | null | undefined
  answered?: boolean; stale?: boolean }, when: (v: string | null | undefined) => string,
  asOf?: string | null): SourceOpinion {
  const clock = asOf ? ` (last report ${when(asOf)})` : ''
  if (!input.answered || input.status === 'UNAVAILABLE' || !input.status) {
    return { state: 'unavailable', canAssertEmpty: false,
      note: 'Cannot tell who is working — the agent list did not answer. That is not the same as nobody working.' }
  }
  if (input.stale) return { state: 'stale', canAssertEmpty: false,
    note: `The agent list is out of date${clock}, so an agent missing from it is not shown to be idle.` }
  if (input.status === 'PARTIAL') return { state: 'stale', canAssertEmpty: false,
    note: 'The agent list only partly answered, so an agent missing from it is not shown to be idle.' }
  return { state: 'current', canAssertEmpty: true, note: '' }
}

export type Panel = 'needs_you' | 'going_live' | 'stuck' | 'agents'

/** What an EMPTY panel says. `none` only on a current source; otherwise the panel states its own ignorance. */
export const PANEL_NONE: Record<Panel, string> = {
  needs_you: 'Nothing needs you.',
  going_live: 'Nothing is going live today.',
  stuck: 'Nothing is stuck right now.',
  agents: 'No agent is working right now.',
}

export function panelSentence(panel: Panel, source: SourceOpinion): string {
  if (source.canAssertEmpty) return PANEL_NONE[panel]
  const reason = SOURCE_REASON[(source.state === 'current' ? 'unknown' : source.state)]
  const subject = panel === 'agents' ? 'who is working' : panel === 'stuck' ? 'what is stuck'
    : panel === 'needs_you' ? 'whether anything needs you' : 'what is going live'
  return `Cannot tell ${subject} — ${reason}. That is not the same as ${panel === 'agents' ? 'nobody working'
    : panel === 'stuck' ? 'nothing being stuck' : panel === 'needs_you' ? 'nothing needing you' : 'nothing going live'}.`
}

/** The Going-live panel has TWO sources: the open-change census and the merged-vs-serving comparison. The "nothing is
 *  going live" claim needs BOTH to be decisive; if either is unknown the panel says so, and a known "merged work is
 *  waiting" does not license an empty-census claim (codex third read, counterexamples 3 and 5). */
export function goingLiveSentence(flight: SourceOpinion,
                                  comparison: { known: boolean; waiting: boolean }): string {
  if (!comparison.known) {
    return 'Cannot tell what is going live — whether merged work is still waiting to be promoted could not be read. '
      + 'That is not the same as nothing going live.'
  }
  if (comparison.waiting) {
    return flight.canAssertEmpty
      ? 'No open change is waiting to merge; the merged work above is what is waiting to go live.'
      : 'The merged work above is waiting to go live. This page cannot tell whether an open change is also waiting.'
  }
  return panelSentence('going_live', flight)
}

export type StageGroup = { stage: OperatorStage; label: string; rows: InFlightPr[] }

const GROUP_ORDER: OperatorStage[] = ['building', 'review', 'ready', 'merging', 'awaiting', 'live']

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
      merging: 'Merging in the next window', awaiting: 'Merged, waiting to go live', live: 'Live' }[stage],
  }))
}

/** Block 2: server-marked operator decisions plus legacy ready rows retained for read-only inspection.
 *  Missing action metadata never grants approval or upload authority. */
export function needsYou(prs: InFlightPr[]): InFlightPr[] {
  return prs.filter(p => {
    const actions = p.operator_actions
    if (actions) return actions.required === true || (actions.eligible ?? []).includes('approve')
    return !p.is_draft && p.mergeable !== 'CONFLICTING' && !p.has_operator_merge
      && p.work?.review?.state === 'MERGE' && p.work?.ci?.state === 'GREEN'
  })
}

/** The facts a Needs-you card is allowed to state, derived per action from the served row.
 *
 *  cc3 review F6 (2026-11-03): the card said "<agent> finished it and the checks passed" unconditionally, and the
 *  push-budget cards the server flags are exactly the rows where that is false — drafts, DIRTY and BLOCKED branches
 *  with no review and no CI. A card that asks the operator to authorize an upload must not also tell him the work is
 *  finished and green. */
export function needsYouFacts(p: InFlightPr, action: { kind: 'approve' | 'push' | 'inspect' }): { headline: string; warning: string | null } {
  // F7 (cc3, 2026-11-03): DIRTY means the branch conflicts with the base, NOT uncommitted work — and a conflicting
  // branch can still be uploaded; the conflict bites at merge time. Say exactly that.
  const warning = p.mergeable === 'CONFLICTING' || p.merge_state === 'DIRTY'
    ? action.kind === 'push'
      ? 'GitHub reports this branch conflicts with newer code in the base. The upload is still possible; the merge will need a rebase first.'
      : 'GitHub reports this branch conflicts with newer code in the base; the merge needs a rebase first.'
    : p.merge_state === 'BLOCKED'
      ? 'GitHub reports this change is blocked by something it is waiting on.'
      : p.is_draft ? 'It is still a draft, so it is not ready for anyone to merge.' : null
  if (action.kind === 'approve') {
    const proven = p.work?.review?.state === 'MERGE' && p.work?.ci?.state === 'GREEN'
    return { headline: proven ? 'A reviewer approved it and its checks passed.'
      : 'The server says this change is ready for your approval; its own record of the check is incomplete.',
    warning }
  }
  const publication = p.work?.publication_state
  const fact = publication === 'local_only' ? 'This branch holds work that has not been uploaded yet.'
    : publication === 'published' ? 'This change is recorded as uploaded.'
      : publication === 'merged' ? 'This change is recorded as merged.'
        : publication === 'live' ? 'This change is recorded as live.'
          : 'Whether this work has been uploaded is not recorded.'
  return { headline: `${fact} ${action.kind === 'push'
    ? 'The server offers upload authorization for this version.'
    : 'No approval or upload action was supplied for this version.'}`, warning }
}

/** The server-granted action, or a read-only inspection when no action was supplied. */
export function needsYouAction(p: InFlightPr): { kind: 'approve' | 'push' | 'inspect'; label: string; effect: string } {
  const eligible = p.operator_actions?.eligible ?? []
  if (eligible.includes('approve')) {
    return { kind: 'approve', label: 'Open the change and approve it →',
      effect: 'If you say yes, it is queued for the next merge window; the host still has to promote it before it is live.' }
  }
  if (eligible.includes('push')) {
    return { kind: 'push', label: 'Authorize the upload for this branch →',
      effect: 'If you say yes, one fast-forward upload is allowed, bound to this exact version. Force-push stays refused.' }
  }
  return { kind: 'inspect', label: 'View the recorded change →',
    effect: 'The source did not supply an approval or upload action; these details are read-only.' }
}

/** Block 4: stuck, and whose step it is. The threshold is stated in the heading, never implied. */
/** Block 4 shows only a RECORDED cause. "No record of a review" is not evidence that a change is stuck — the served
 *  contract defines NOT_RECORDED that way — so an unreviewed ten-minute-old PR never lands here (cc3 review F3). */
export function stuck(prs: InFlightPr[]): Array<{ pr: InFlightPr; because: string; whose: string }> {
  const out: Array<{ pr: InFlightPr; because: string; whose: string }> = []
  for (const p of prs) {
    const review = p.work?.review
    const ci = p.work?.ci
    const because = p.mergeable === 'CONFLICTING' ? 'conflicts with newer code'
      : review?.state === 'CHANGES' ? 'a reviewer asked for changes'
      : ci?.state === 'RED' ? 'the checks failed'
      : p.work?.blockers?.length ? 'a blocker is recorded'
      : null
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

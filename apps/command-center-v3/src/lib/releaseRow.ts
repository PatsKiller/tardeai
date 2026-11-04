// One release-history row, in the operator's words (FQ-069 + FQ-070).
//
// The history table was five nowrap columns wide — 819 px on a 390 px phone — and carried the served short SHA, the
// receipt id and "sha from <basis>" in the reading line. The fix is one row shape that reads at any width: what was
// released and when, whether it verified, which PRs, what is left to do; and a diagnostics half holding the hashes, the
// basis, the receipt and the raw reason. Nothing is dropped.
//
// The verdict is NOT re-derived here: `verifyVerdict` in releasesSchedules.ts owns that, because the label text must never
// be suffix-tested ("NOT VERIFIED" ends in "VERIFIED").
import { verifyLabel, type ReleaseRow } from './releasesSchedules.ts'
import type { Tone } from './designTokens'

export type ReleaseRowModel = {
  /** when it was recorded, as the page already formats it */
  when: string
  /** what was released, in words: the release name, or a plain admission that none was recorded */
  purpose: string
  /** the structured verdict AND its words; the tone comes from the verdict, never from the text */
  verdict: { kind: 'verified' | 'not_verified' | 'rollback' | 'not_recorded'; label: string; tone: Tone }
  /** which change this was: the PRs, or why they cannot be named */
  changes: string
  /** what stands in the way of calling this good, and what to do next — null when nothing does */
  blocker: string | null
  nextAction: string
  /** hashes, basis, receipt and the raw reason — shown only in the disclosure */
  diagnostics: Array<{ label: string; value: string }>
}

const clean = (v: unknown) => String(v ?? '').replace(/\s+/g, ' ').trim()

function prsText(prs: number[] | null | undefined, reason: string | null | undefined): string {
  if (!Array.isArray(prs)) return reason ? `changes not recorded (${clean(reason)})` : 'changes not recorded'
  if (!prs.length) return 'no change recorded against it'
  const shown = prs.slice(0, 6).map(n => `PR ${n}`).join(', ')
  return prs.length > 6 ? `${shown} and ${prs.length - 6} more` : shown
}

/** The structured verdict. `verifyLabel` owns the WORDS; this owns the KIND, from the same fields, so no call site ever
 *  learns to read a verdict out of the label text ("NOT VERIFIED" ends in "VERIFIED"). A test pins the two together:
 *  for every case the kind and the label's tone must agree. */
export function releaseVerdict(r: ReleaseRow): ReleaseRowModel['verdict']['kind'] {
  if (r.mode === 'rollback') return 'rollback'
  if (!r.verify) return 'not_recorded'
  const ok = r.verify.ok === true && !r.verify.rolled_back && !(r.verify.readback_errors ?? []).length
  return ok ? 'verified' : 'not_verified'
}

export function releaseRowModel(r: ReleaseRow, when: string): ReleaseRowModel {
  const kind = releaseVerdict(r)
  const label = verifyLabel(r)
  const name = clean(r.release_name)
  const purpose = r.mode === 'rollback'
    ? (name ? `Rollback — ${name}` : 'Rollback')
    : (name || 'Release recorded without a name')
  const reason = clean(r.verify_reason) || clean(r.error)

  // A blocker is a fact the record states; when the record states none, the row says what it is waiting for instead.
  const blocker = kind === 'not_verified'
    ? `The deploy did not verify${reason ? `: ${reason}` : ', and no reason was recorded'}.`
    : kind === 'rollback' ? 'This release was a rollback, not a promotion.'
      : kind === 'not_recorded' ? 'No verification is retained for this release, so it cannot be called verified.'
        : null
  const nextAction = kind === 'verified' ? 'Nothing to do.'
    : kind === 'not_verified' ? 'Check the deploy receipt for this release before relying on it.'
      : kind === 'rollback' ? 'Nothing to do — the previous version was restored deliberately.'
        : 'Nothing to do, but do not read this row as verified.'

  return {
    when,
    purpose,
    verdict: { kind, label: label.text, tone: label.tone },
    changes: prsText(r.prs, r.prs_reason),
    blocker,
    nextAction,
    diagnostics: [
      { label: 'Served SHA', value: clean(r.sha) || 'not recorded' },
      { label: 'Short SHA', value: clean(r.short_sha) || 'not recorded' },
      { label: 'SHA basis', value: clean(r.sha_basis) || 'not recorded' },
      { label: 'Receipt', value: clean(r.receipt) || 'not recorded' },
      { label: 'Mode', value: clean(r.mode) || 'not recorded' },
      { label: 'Verify reason', value: clean(r.verify_reason) || 'not recorded' },
      ...(clean(r.error) ? [{ label: 'Recorded error', value: clean(r.error) }] : []),
    ],
  }
}

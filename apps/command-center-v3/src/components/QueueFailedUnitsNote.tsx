/** The /ops Queue tab's failed-unit line (OPS-C1, operator OP-020, 2026-11-14).
 *
 *  The Queue card derived "service failed" from a per-timer `systemctl --user show` loop, so it listed
 *  `hermes-deep-research-local` and missed `tradeai-deploy-on-main` while the Platform card listed the tradeai
 *  units — two probes, two scopes, no observation time. The API now publishes one shared view as
 *  `sections.failed_units` (units, scope, source, as_of, answered). This renders it, and — the part that matters
 *  most — refuses to print "All systems nominal" when that view says it could not look: UNKNOWN is never an
 *  all-clear.
 *
 *  `section` is the API's `sections.failed_units`. It is absent on a release that does not publish it yet, and an
 *  absent section renders nothing rather than claiming anything (the Platform card still carries its own row).
 */
import { TOKENS, TYPE } from '../lib/designTokens'

type FailedUnitsView = {
  units?: Array<{ unit?: string }>
  count?: number
  outside_count?: number
  scope?: string
  source?: string
  as_of?: string | null
  answered?: boolean
  reason?: string | null
}

/** True when the section exists and the probe could not answer — the case that must never read as OK. */
export function failedUnitsUnproven(section: FailedUnitsView | null | undefined): boolean {
  return !!section && section.answered !== true
}

function shortTime(iso: string | null | undefined): string {
  if (!iso) return 'time unknown'
  const t = Date.parse(iso)
  return Number.isFinite(t) ? new Date(t).toISOString().replace('T', ' ').replace(/\.\d+Z$/, 'Z') : String(iso)
}

/** The line under the Needs Attention list: what this scope saw, from which source, read when. */
export function failedUnitsNote(section: FailedUnitsView | null | undefined): string | null {
  if (!section) return null
  if (failedUnitsUnproven(section)) {
    return `Failed-unit state unknown: ${section.reason ?? 'no answer from systemctl'}. Nothing here is known to be OK.`
  }
  const n = typeof section.count === 'number' ? section.count : 0
  const outside = section.outside_count ? `, ${section.outside_count} outside this scope` : ''
  return `${n} failed user unit${n === 1 ? '' : 's'} in scope (${section.scope ?? 'scope unstated'}${outside}) · as of ${shortTime(section.as_of)}`
}

/** The empty-list sentence. "All systems nominal" is only true when the failed-unit view answered. */
export function queueNominalText(section: FailedUnitsView | null | undefined): string {
  return failedUnitsUnproven(section)
    ? `Failed-unit state unknown: ${section?.reason ?? 'no answer from systemctl'}. Nothing here is known to be OK.`
    : 'All systems nominal'
}

export function QueueFailedUnitsNote({ section }: { section: FailedUnitsView | null | undefined }) {
  const text = failedUnitsNote(section)
  if (!text) return null
  return (
    <div
      data-testid="queue-failed-units"
      role="note"
      style={{ marginTop: 6, fontSize: TYPE.xs, lineHeight: 1.45, color: failedUnitsUnproven(section) ? TOKENS.warning : TOKENS.text[2] }}
    >
      {text}
    </div>
  )
}

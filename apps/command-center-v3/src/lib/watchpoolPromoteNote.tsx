/**
 * FQ-079 — why Promote is unavailable on a desk suggestion, as a component so it can be RENDERED in a test.
 *
 * The page had two different unavailable facts and explained only one: a suggestion that DOES carry a directive can still
 * have no professional-analyst view to compare against, and that is not the same as having nothing to promote. The first
 * pass at this row tested the source text, which passes whatever the rendered case does — cc-deepseek-3's review of
 * PR 2660 at a098e91b is right about that, and this extraction is the repair.
 *
 * LQ-20261107-250: "unavailable" itself was two facts. Measured on 2026-11-07, 930 of the 1,200 names with a Street view
 * had no internal direction, so the sentence below ("no professional-analyst view is attached") was false for most of the
 * rows that showed it. The read model now says which side is missing (`divergence_reason`), the page joins the live pills
 * map so a stale stored hit cannot keep the wrong sentence on screen, and each reason gets its own honest sentence.
 *
 * The producer emits LOWERCASE (`build_pro_analyst_read_model.py` assigns `divergence = "unavailable"`), so the check
 * normalises case rather than comparing a literal the producer never writes.
 */
import { BB, TYPE } from './watchTokens'

const noteStyle = { marginLeft: 'auto', fontSize: TYPE.xs, color: BB.text3, overflowWrap: 'anywhere' } as const

export type DivergenceReason =
  | 'no_professional_coverage'
  | 'no_street_direction'
  | 'no_internal_direction'
  | 'read_model_unreadable'

/** Which side of the comparison is missing, from the live pills map (`/api/v2/pro-analyst/pills?map=1`).
 *
 * The map carries `has` (professional coverage), `street` and `internal`, so the reason is derivable without a new
 * server field. A symbol with no pill at all yields null: the page then keeps the generic sentence rather than
 * inventing a cause. `unreadable` is the read-model read failure the API reports as a note instead of a map. */
export function divergenceReason(
  divergence?: string | null,
  pill?: { has?: boolean; street?: string | null; internal?: string | null } | null,
  readModelUnreadable?: boolean,
): DivergenceReason | null {
  if (String(divergence || '').toUpperCase() !== 'UNAVAILABLE') return null
  if (readModelUnreadable) return 'read_model_unreadable'
  if (!pill) return null
  if (!pill.has) return 'no_professional_coverage'
  if (!pill.street) return 'no_street_direction'
  if (!pill.internal) return 'no_internal_direction'
  return null
}

/** The desk row's live divergence: the pills map when the name is in it, else the stored hit value.
 *
 * `watch_directive_hits.divergence` is written once at insert and never refreshed, so a row can show a verdict the
 * read model no longer holds. The provenance drawer already reads the pills file live; this makes the row agree. */
export function liveDivergence(
  stored?: string | null,
  pill?: { divergence?: string | null } | null,
): string | null | undefined {
  return pill && pill.divergence != null ? pill.divergence : stored
}

const SENTENCES: Record<DivergenceReason, string> = {
  no_professional_coverage:
    'Street comparison unavailable — no professional-analyst view is attached to this suggestion yet, so there is ' +
    "nothing to compare the desk's read against; Promote still attaches it to your watchlist",
  no_street_direction:
    'Street comparison unavailable — coverage exists for this name but no Street direction is attached, so there is ' +
    "nothing to compare the desk's read against; Promote still attaches it to your watchlist",
  no_internal_direction:
    "Street comparison unavailable — the Street view exists, but the system's own directional read is missing for " +
    'this name (internal direction feed gap), so there is nothing to compare it against; Promote still attaches it ' +
    'to your watchlist',
  read_model_unreadable:
    'Street comparison unavailable — the professional-analyst read model could not be read just now, so this is a ' +
    'data error, not an absence of coverage; Promote still attaches it to your watchlist',
}

export function PromoteUnavailableNote({ directiveId, divergence, reason, pending }: {
  directiveId?: string | number | null
  divergence?: string | null
  reason?: DivergenceReason | null
  /** The live pills map is still loading: say nothing rather than assert a cause the map may contradict. */
  pending?: boolean
}) {
  if (!directiveId) {
    return <span data-testid="wp-promote-unavailable" style={noteStyle}>
      Cannot promote — no directive is attached to this suggestion, so there is nothing for Promote to act on
    </span>
  }
  if (String(divergence || '').toUpperCase() !== 'UNAVAILABLE') return null
  if (pending && !reason) return null
  return <span data-testid="wp-promote-unavailable" style={noteStyle} data-divergence-reason={reason || 'unclassified'}>
    {SENTENCES[reason || 'no_professional_coverage']}
  </span>
}

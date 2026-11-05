/**
 * FQ-079 — why Promote is unavailable on a desk suggestion, as a component so it can be RENDERED in a test.
 *
 * The page had two different unavailable facts and explained only one: a suggestion that DOES carry a directive can still
 * have no professional-analyst view to compare against, and that is not the same as having nothing to promote. The first
 * pass at this row tested the source text, which passes whatever the rendered case does — cc-deepseek-3's review of
 * PR 2660 at a098e91b is right about that, and this extraction is the repair.
 *
 * The producer emits LOWERCASE (`build_pro_analyst_read_model.py` assigns `divergence = "unavailable"`), so the check
 * normalises case rather than comparing a literal the producer never writes.
 */
import { BB, TYPE } from './watchTokens'

const noteStyle = { marginLeft: 'auto', fontSize: TYPE.xs, color: BB.text3 } as const

export function PromoteUnavailableNote({ directiveId, divergence }: {
  directiveId?: string | number | null
  divergence?: string | null
}) {
  if (!directiveId) {
    return <span data-testid="wp-promote-unavailable" style={noteStyle}>
      Cannot promote — no directive is attached to this suggestion, so there is nothing for Promote to act on
    </span>
  }
  if (String(divergence || '').toUpperCase() !== 'UNAVAILABLE') return null
  return <span data-testid="wp-promote-unavailable" style={noteStyle}>
    Street comparison unavailable — no professional-analyst view is attached to this suggestion yet, so there is
    nothing to compare the desk's read against; Promote still attaches it to your watchlist
  </span>
}

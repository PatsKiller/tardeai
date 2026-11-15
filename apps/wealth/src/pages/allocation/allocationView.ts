// Allocation — the pure model behind the nav page. No React, no fetch, no arithmetic of its own.
//
// The page answers one question the Holdings analytics panel never had to: "how much of the BOOK is this
// sleeve, and how much of the SELECTED VIEW is it?" (RELEASE-ACCEPTANCE-LEDGER row D: "selected 100% vs
// unlabelled book weight" — FAIL, owner -6 commit A / -5.) The answer is two calls to the SAME approved
// selector the Holdings page renders (`portfolio-analytics.mjs`, the reviewed v0.5 port, sha256 98b826d3…):
// one with every filter empty (the BOOK basis), one with the reader's filters (the SELECTED basis), joined on
// the selector's own bucket key.
//
// Every number this page prints is one the selector returned:
//   * `book.weight`     = value / the book's valued total       (selector: allocationValid ? value/total : null)
//   * `selected.weight` = value / the selection's valued total  (the same field, from the other view)
//   * the amounts are the selector's own bucket sums. This module adds no sum, no ratio and no estimate, so
//     there is no second definition of "weight" anywhere on the page.
//
// Two states the join must not turn into a number (never a fabricated 0):
//   * a sleeve whose rows are present but unpublished (`valued === 0`): the selector's weight there is 0
//     because its value is 0. Printing that would say "0.0%" for a sleeve nobody valued. It is withheld
//     (null ⇒ the page prints "Unknown"), matching the reviewed legend's `known ? pct : 'Unknown'`.
//   * a sleeve with no row in a NON-EMPTY selection: a measured absence, not an unknown. Its selected weight
//     is 0 only when the selector says the selection's allocation is valid; otherwise it stays unknown.
//     An empty selection has no denominator at all, so both sides are withheld.
//
// Labels are the page's job (`displaySectorKey` maps the selector's internal 'Cash & sweep' to the reader's
// 'Funds & Cash'), which is why this module imports no adapter and stays loadable by node's test runner
// without the JSX graph.

import { derivePortfolioView } from '../portfolio/analytics/portfolio-analytics.mjs'
import type {
  AnalyticsRowInput,
  AnalyticsSnapshot,
  PortfolioView,
  SectorBucket,
} from '../portfolio/analytics/portfolio-analytics.mjs'

export interface AllocationFilters {
  /** `'ALL'` or a served account key — the same scope the shell's top bar renders. */
  scope: string
  /** A selector bucket key, or '' for every sleeve. */
  sector: string
  query: string
}

/** One sleeve measured under one denominator. */
export interface SleeveBasis {
  /** The selector's own sum for this sleeve in that view. null = rows present, none valued (never $0). */
  amount: number | null
  /** The selector's weight over that view's valued total. null = withheld (see the header). */
  weight: number | null
  /** Rows in this sleeve in that view. */
  count: number
  /** Of those, the rows that publish a position value. */
  valued: number
}

export interface Sleeve {
  /** The selector's bucket key — the join key, and the key the sector filter accepts. */
  key: string
  /** The palette colour the selector assigned to this sleeve (from the book view, where it always exists). */
  color: string | null
  inBook: boolean
  inSelection: boolean
  book: SleeveBasis
  selected: SleeveBasis
}

export interface AllocationModel<R extends AnalyticsRowInput = AnalyticsRowInput> {
  /** Every row in the read, one currency, no filter. The denominator of every "weight of book". */
  bookView: PortfolioView<R>
  /** The rows the filters kept. The denominator of every "weight of selected view". */
  view: PortfolioView<R>
  /** The union of both views' sleeves, in the book view's own order (the selector sorts by value), then any
   *  selection-only sleeve in the selection's order. */
  sleeves: Sleeve[]
}

/** One concise line for the top of the page, and the full technical reason for the expanded detail. */
export interface ReadStatus {
  /** null when the read is current (fresh) and the caller has nothing to disclose. */
  warning: string | null
  /** The producer's full reason plus the session/read clock, for the disclosure. null when there is none. */
  detail: string | null
}

/**
 * The notice's lead clause: the part before its parenthetical (or its first sentence), and the rest.
 *
 * The page's `notice` (liveProps, last-known-good with age) can run to several hundred characters — measured
 * 355 on 2026-11-15. The top line takes the lead clause and the disclosure keeps the whole text verbatim, so
 * nothing is dropped and nothing is reworded. Deterministic: split at the first " (" or first ". " only.
 */
function leadClause(text: string): { lead: string; rest: string | null } {
  const paren = text.indexOf(' (')
  if (paren > 0) return { lead: text.slice(0, paren).trim(), rest: text.slice(paren).trim() }
  const sentence = text.indexOf('. ')
  if (sentence > 0) return { lead: text.slice(0, sentence + 1).trim(), rest: text.slice(sentence + 1).trim() }
  return { lead: text.trim(), rest: null }
}

/**
 * The read's status as ONE concise line plus its full reason.
 *
 * Operator route 2026-11-15T1745Z, item 1: keep one honest freshness/session warning at the top and put
 * the technical explanation behind a disclosure. Nothing is invented — a current read says nothing, an
 * absent field is reported as absent, and a long notice is shortened only at its own clause boundary with
 * the whole text kept in `detail`.
 *
 * `line` is the shell's ONE freshness sentence — `freshnessCopy(snapshot).line` in
 * `portfolio/analyticsAdapter` (RC3, live on base 0659545ba). While it is non-empty it IS the top line,
 * verbatim, and the producer's `notice` is never printed there a second time.
 *
 * The fallback is NOT dead on W1, which is why it stays: `holdingsProps` sets `notice = st.healthUnproven`
 * on a read the producer's freshness verdict calls current (`liveProps.ts` :110/:128, `components/
 * renderState.ts` :85 — a payload with no health flag and no producer clock is OK *and* unproven). In that
 * state `freshnessCopy` returns `''` and the health caveat is the only warning there is; dropping it would
 * print a calm strip over an unmeasured read, and the Holdings page beside it prints the same notice whole.
 * So when the adapter is silent the notice's own lead clause — a verbatim prefix, never a new sentence —
 * is the top line, and its full text stays in `detail`.
 */
export function readStatus(
  notice: string | null | undefined,
  snapshot: Pick<AnalyticsSnapshot, 'status' | 'reason' | 'session' | 'observedAt'>,
  line?: string | null,
): ReadStatus {
  const lineText = typeof line === 'string' && line.trim() !== '' ? line.trim() : null
  const noticeText = typeof notice === 'string' && notice.trim() !== '' ? notice.trim() : null
  const reason = typeof snapshot.reason === 'string' && snapshot.reason.trim() !== '' ? snapshot.reason.trim() : null
  // `snapshot.session` is the producer's own phrase and may already lead with the word — the live adapter
  // publishes 'Session unknown' when the phase is not KNOWN (analyticsAdapter, measured 2026-11-15). Prefixing
  // it again printed "Session Session unknown" behind the disclosure, so the word is added only when absent.
  const rawSession =
    typeof snapshot.session === 'string' && snapshot.session.trim() !== '' ? snapshot.session.trim() : 'Session unknown'
  const sessionText = /^Session\b/.test(rawSession) ? rawSession : `Session ${rawSession}`
  const clock = `${sessionText} · read ${snapshot.observedAt ?? 'time unknown'}.`

  const noticeClause = noticeText !== null ? leadClause(noticeText) : null
  // One source: the adapter's sentence when it has one, otherwise the notice's own lead clause.
  const warning = lineText ?? noticeClause?.lead ?? null

  const detailParts: string[] = []
  // The whole notice goes behind the disclosure only when the top line truncated it; a notice short enough
  // to be the whole top line is not printed twice.
  if (noticeClause !== null && noticeClause.rest !== null) detailParts.push(`Full notice: ${noticeText}`)
  if (reason !== null && !(noticeText ?? '').includes(reason) && !(lineText ?? '').includes(reason)) {
    detailParts.push(reason)
  }
  // The session/read clock belongs with anything the page is flagging — and behind the disclosure only.
  if (warning !== null || detailParts.length > 0) detailParts.push(clock)
  return { warning, detail: detailParts.length > 0 ? detailParts.join(' ') : null }
}

/**
 * One sleeve under one denominator.
 *
 * `undefined` means "no row of this sleeve in that view". For a non-empty view that is a measured absence and
 * its share is 0 — but only when the view has a valid allocation total; otherwise there is no denominator and
 * the weight is withheld. `valued === 0` with rows present is the unpublished case: the selector's 0 is a
 * placeholder for "no value published", so both amount and weight become null.
 */
function basis(b: SectorBucket | undefined, emptyView: boolean, allocationValid: boolean): SleeveBasis {
  if (b === undefined) {
    return emptyView
      ? { amount: null, weight: null, count: 0, valued: 0 }
      : { amount: 0, weight: allocationValid ? 0 : null, count: 0, valued: 0 }
  }
  const valued = b.known > 0
  return { amount: valued ? b.value : null, weight: valued ? b.weight : null, count: b.count, valued: b.known }
}

/**
 * The two views of the same rows, side by side.
 *
 * Throws (like the selector) when the rows do not satisfy the canonical row contract; the page states that
 * instead of charting an identity it cannot keep.
 */
export function buildAllocationModel<R extends AnalyticsRowInput>(
  rows: R[],
  snapshot: AnalyticsSnapshot,
  filters: AllocationFilters,
): AllocationModel<R> {
  // One currency is served on this read (the adapter declares it), and the selector does no FX. Passing null
  // lets the selector resolve the single served currency itself; it never mixes two.
  const currency = null
  const bookView = derivePortfolioView(rows, { account: '', sector: '', query: '', currency }, snapshot)
  const view = derivePortfolioView(
    rows,
    { account: filters.scope === 'ALL' ? '' : filters.scope, sector: filters.sector, query: filters.query, currency },
    snapshot,
  )
  return { bookView, view, sleeves: joinSleeves(bookView, view) }
}

/** Join two selector views on the bucket key. Pure; exported for the test that pins the two denominators. */
export function joinSleeves<R extends AnalyticsRowInput>(
  bookView: PortfolioView<R>,
  view: PortfolioView<R>,
): Sleeve[] {
  const selectedByKey = new Map<string, SectorBucket>()
  for (const s of view.sectors) selectedByKey.set(s.key, s)
  const emptyBook = bookView.rows.length === 0
  const emptySelection = view.rows.length === 0
  const out: Sleeve[] = []
  const seen = new Set<string>()
  for (const b of bookView.sectors) {
    seen.add(b.key)
    const s = selectedByKey.get(b.key)
    out.push({
      key: b.key,
      color: b.color,
      inBook: true,
      inSelection: s !== undefined,
      book: basis(b, emptyBook, bookView.allocationValid),
      selected: basis(s, emptySelection, view.allocationValid),
    })
  }
  for (const s of view.sectors) {
    if (seen.has(s.key)) continue
    out.push({
      key: s.key,
      color: s.color,
      inBook: false,
      inSelection: true,
      book: basis(undefined, emptyBook, bookView.allocationValid),
      selected: basis(s, emptySelection, view.allocationValid),
    })
  }
  return out
}

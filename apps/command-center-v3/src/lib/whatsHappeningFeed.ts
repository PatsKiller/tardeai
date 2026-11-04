// The card's feed adapter — the SHAPE F1 (PR 2592) settled on: a source opinion, never a bare list.
//
// cx-openai-2's F1 finding was that a response carrying every field can still be one the page must not reason over
// (unsupported schema, stale wire, dropped rows, clocks in the past). PR 2592 answers that with `inFlightCensus()` at the
// page boundary; this module takes THAT verdict rather than inventing a second one.
//
// When PR 2592 merges, the Home page passes `inFlightCensus(wire, transport)` here directly. Until then the adapter takes
// the same three facts — answered, reason, rows — so the two agree by construction and the call site is a one-line swap.
import type { WorkItem, WorkState } from './whatsHappening'

export type Census = { answered: boolean; reason: string | null }
export type FeedRow = {
  id: string; title: string
  /** the raw board/PR state — mapped below, never rendered */
  state: string | null | undefined
  owner?: string | null; eta?: string | null; updated_at?: string | null; source?: string | null
}

/** The state vocabulary the card shows, and the words a served row uses for each. Anything unlisted is in progress. */
const STATE_OF: Record<string, WorkState> = {
  // An unlisted or MISSING state is unknown, never "in progress": the source established no activity (F2).
  p0: 'p0', incident: 'p0', blocked_p0: 'p0',
  running: 'in_progress', working: 'in_progress', claimed: 'in_progress', building: 'in_progress',
  ci: 'verifying', verifying: 'verifying', checking: 'verifying',
  pr_open: 'in_review', review: 'in_review', in_review: 'in_review',
  needs_operator: 'waiting_on_you', waiting_on_you: 'waiting_on_you', awaiting_approval: 'waiting_on_you',
  merged: 'done', done: 'done', verified: 'done', released: 'done',
}

export function workStateOf(state: string | null | undefined): WorkState {
  const k = String(state ?? '').trim().toLowerCase()
  return STATE_OF[k] ?? 'unknown'      // null, idle, stale and anything unlisted are UNKNOWN, not activity
}

/** What the card renders. `unknown` is a first-class outcome: the caller shows the reason, never an empty card. */
export type CardFeed =
  | { kind: 'rows'; items: WorkItem[]; unknown: number }
  | { kind: 'unknown'; reason: string }

export function cardFeed(census: Census, rows: FeedRow[] | null | undefined): CardFeed {
  if (!census.answered) return { kind: 'unknown', reason: census.reason ?? 'the source did not answer' }
  // An answered census that carried NO row list is still not an empty list: a missing census member is unknown.
  if (!Array.isArray(rows)) return { kind: 'unknown', reason: 'the source answered without a list of work' }
  const items: WorkItem[] = rows.map(r => ({
    id: r.id, title: r.title, state: workStateOf(r.state), owner: r.owner ?? null,
    eta: r.eta ?? null, updated_at: r.updated_at ?? null, source: r.source ?? null,
  }))
  // A list where NOT ONE row carries a state is not a list of six zeroes: nothing was established, so the card says so
  // rather than rendering a confident strip (F1: a bare list must never look like a measurement).
  const unknown = items.filter(i => i.state === 'unknown').length
  if (items.length > 0 && unknown === items.length) {
    return { kind: 'unknown', reason: 'the source listed work but no row recorded a state' }
  }
  return { kind: 'rows', items, unknown }
}

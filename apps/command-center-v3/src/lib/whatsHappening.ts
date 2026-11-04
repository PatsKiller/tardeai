// "What's happening" — the Home card the operator approved at 14:43Z.
//
// The operator's one condition was stated by him: it must match the site's design colours. So the model below names a
// STATE, and the component maps that state to a TONE that already exists in designTokens — it never invents a hue.
//
//   in progress  -> info      (blue)
//   verifying    -> ai        (purple)
//   in review    -> warning   (amber)
//   waiting on you -> elevated (orange)
//   done         -> success   (green)
//   P0           -> danger    (red)
//
// Pure projection: no React, no network. The component renders it; the test renders the component.

export type WorkState = 'in_progress' | 'verifying' | 'in_review' | 'waiting_on_you' | 'done' | 'p0'

/** The operator's words for each state. Never a status code. */
export const STATE_LABEL: Record<WorkState, string> = {
  in_progress: 'In progress',
  verifying: 'Verifying',
  in_review: 'In review',
  waiting_on_you: 'Waiting on you',
  done: 'Done',
  p0: 'P0',
}

/** The designTokens tone each state uses — the mapping IS the operator's condition, in one place. */
export const STATE_TONE: Record<WorkState, 'info' | 'ai' | 'warning' | 'elevated' | 'success' | 'danger'> = {
  in_progress: 'info',
  verifying: 'ai',
  in_review: 'warning',
  waiting_on_you: 'elevated',
  done: 'success',
  p0: 'danger',
}

export type WorkItem = {
  id: string
  title: string
  state: WorkState
  owner?: string | null
  /** Optional; dropped entirely on a phone rather than squashed. */
  eta?: string | null
  updated_at?: string | null
  source?: string | null
}

/** The six cells of the counter strip, in the approved order. */
export const COUNTER_ORDER: WorkState[] = ['in_progress', 'verifying', 'in_review', 'waiting_on_you', 'done', 'p0']

export function counters(items: WorkItem[]): Array<{ state: WorkState; label: string; count: number }> {
  const c: Record<string, number> = {}
  for (const i of items) c[i.state] = (c[i.state] ?? 0) + 1
  return COUNTER_ORDER.map(state => ({ state, label: STATE_LABEL[state], count: c[state] ?? 0 }))
}

/** At most eight rows, P0 first, then "waiting on you", then the rest — the operator's own urgency order. */
const RANK: Record<WorkState, number> = { p0: 0, waiting_on_you: 1, in_review: 2, verifying: 3, in_progress: 4, done: 5 }

export function topRows(items: WorkItem[], max = 8): WorkItem[] {
  return [...items]
    .sort((a, b) => (RANK[a.state] - RANK[b.state])
      || String(b.updated_at ?? '').localeCompare(String(a.updated_at ?? ''))
      || a.title.localeCompare(b.title))
    .slice(0, max)
}

/** Columns that survive a phone. The other three are DROPPED, not shrunk (operator, 14:43Z). */
export const PHONE_COLUMNS = ['title', 'state', 'owner'] as const
export const WIDE_COLUMNS = ['title', 'state', 'owner', 'eta', 'updated_at', 'source'] as const
export type Column = (typeof WIDE_COLUMNS)[number]

export function columns(compact: boolean): readonly Column[] {
  return compact ? PHONE_COLUMNS : WIDE_COLUMNS
}

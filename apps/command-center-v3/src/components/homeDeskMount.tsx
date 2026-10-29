import { Children, isValidElement, type ReactNode } from 'react'
import W7Conflicts from './W7Conflicts'
import HomeBoard14 from './HomeBoard14'
import type { DeskSource } from './DeskPage'

function isPagePayload(data: unknown): data is Record<string, unknown> {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return false
  return 'do_now' in data || 'portfolio' in data
}

/** The CIO page object passed into the Home panel. HomeHub stays untouched while another claim holds it. */
export function cioPageDataFrom(node: ReactNode): Record<string, unknown> | null {
  for (const child of Children.toArray(node)) {
    if (!isValidElement(child)) continue
    const props = child.props as { data?: unknown; children?: ReactNode }
    if (isPagePayload(props.data)) return props.data
    const nested = cioPageDataFrom(props.children)
    if (nested) return nested
  }
  return null
}

function gapReason(gap: unknown): string | undefined {
  if (!gap) return undefined
  if (typeof gap === 'string') return gap
  if (typeof gap === 'object' && typeof (gap as { reason?: unknown }).reason === 'string') {
    return (gap as { reason: string }).reason
  }
  return undefined
}

/** Holdings weekend phrase and the Jobs receipt clock. Does not drop lane ids the caller supplied. */
export function withHomeClocks(sources: readonly DeskSource[], data: Record<string, unknown>): DeskSource[] {
  const portfolio = data.portfolio as { market_closed_phrase?: unknown; sync_missed?: unknown; sync_missed_reason?: unknown } | undefined
  const next = sources.map(source => {
    if (source.id !== 'holdings' || !portfolio || typeof portfolio !== 'object') return source
    const phrase = typeof portfolio.market_closed_phrase === 'string' && portfolio.market_closed_phrase
      ? portfolio.market_closed_phrase
      : source.note
    const gap = portfolio.sync_missed
      ? (typeof portfolio.sync_missed_reason === 'string' ? portfolio.sync_missed_reason : source.gap)
      : source.gap
    return { ...source, note: phrase, gap }
  })
  const jobs = data.jobs
  if (!jobs || typeof jobs !== 'object' || Array.isArray(jobs)) return next
  const record = jobs as { as_of?: unknown; phrase?: unknown; gap?: unknown }
  const phrase = typeof record.phrase === 'string' && record.phrase ? record.phrase : undefined
  const gap = gapReason(record.gap)
  const asOf = typeof record.as_of === 'string' ? record.as_of : null
  const existing = next.findIndex(source => source.id === 'jobs')
  if (existing >= 0) {
    const prior = next[existing]
    next[existing] = {
      ...prior,
      clockOnly: true,
      asOf: prior.asOf ?? asOf,
      note: phrase ?? prior.note,
      gap: gap ?? prior.gap,
    }
    return next
  }
  next.push({ id: 'jobs', label: 'Jobs', asOf, clockOnly: true, note: phrase, gap })
  return next
}

export function HomeBoardMount({ data }: { data: Record<string, unknown> }) {
  return <div data-testid="home-hub">
    <W7Conflicts section={(data as { conflicts?: unknown }).conflicts} title="CIO findings" />
    <HomeBoard14 data={data} />
  </div>
}

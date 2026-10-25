import { useState } from 'react'
import { RADIUS, TOKENS } from '../lib/designTokens'

export type ListPage = { offset: number; returned: number; total: number; next_offset: number | null; has_more: boolean }

/** Track actual byte-bounded boundaries; subtracting the requested limit can skip rows. */
export function useListOffset(key = '') {
  const [state, setState] = useState({ key, history: [0] })
  const history = state.key === key ? state.history : [0]
  return { offset: history[history.length - 1], reset: () => setState({ key, history: [0] }),
    previous: () => setState({ key, history: history.length > 1 ? history.slice(0, -1) : history }),
    next: (offset: number) => setState({ key, history: [...history, offset] }) }
}

export default function ListPager({ page, previous, next, busy, gap }: {
  page?: ListPage; previous: () => void; next: (offset: number) => void; busy?: boolean; gap?: { reason: string }
}) {
  if (!page) return null
  const style = { color: TOKENS.text[1], background: TOKENS.bg[2], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.sm, minHeight: 44, minWidth: 44, padding: '4px 10px', cursor: 'pointer' }
  return <div aria-label="List pages" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', padding: '8px 0', fontSize: 11 }}>
    <button type="button" style={style} disabled={busy || page.offset === 0} onClick={previous}>Previous</button>
    <span>{page.returned ? `${page.offset + 1}–${page.offset + page.returned}` : 'No rows'} of {page.total}</span>
    <button type="button" style={style} disabled={busy || !page.has_more || page.next_offset == null} onClick={() => page.next_offset != null && next(page.next_offset)}>Next</button>
    {gap && <span role="status" style={{ color: TOKENS.warning }}>Some data could not fit this page ({gap.reason.replace(/_/g, ' ')}).</span>}
  </div>
}

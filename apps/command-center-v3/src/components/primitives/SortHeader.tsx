/** SortHeader (PR2, 2026-09-27): a table header cell wired to useSort. */
import type { CSSProperties, ReactNode } from 'react'
import { TOKENS, TYPE } from '../../lib/designTokens'
import type { SortDir, SortState } from '../../lib/tableSort'
import type { MetricGuideKey } from '../../lib/metricGuide'
import { MetricGuide } from './Tooltip'

export function SortHeader({ sortKey, sort, onToggle, firstDir = 'desc', guideKey, align = 'left', children, style }: {
  sortKey: string
  sort: SortState
  onToggle: (key: string, firstDir?: SortDir) => void
  firstDir?: SortDir
  guideKey?: MetricGuideKey
  align?: 'left' | 'right'
  children: ReactNode
  style?: CSSProperties
}) {
  const active = sort?.key === sortKey
  const label = (
    <button type="button" onClick={() => onToggle(sortKey, firstDir)} aria-sort={active ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: 0, fontFamily: 'inherit',
        fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.05em', textTransform: 'uppercase',
        color: active ? TOKENS.text[0] : TOKENS.text[3], display: 'inline-flex', gap: 3, alignItems: 'center', ...style }}>
      {children}
      <span aria-hidden style={{ opacity: active ? 1 : 0.35 }}>{active ? (sort!.dir === 'asc' ? '▲' : '▼') : '↕'}</span>
    </button>
  )
  return (
    <th scope="col" style={{ textAlign: align, padding: '4px 6px', whiteSpace: 'nowrap' }}>
      {guideKey ? <MetricGuide guideKey={guideKey} phase="short">{label}</MetricGuide> : label}
    </th>
  )
}

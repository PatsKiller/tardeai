import { useState, useMemo } from 'react'

interface Column<T> {
  key: string
  label: string
  width?: number | string
  align?: 'left' | 'right' | 'center'
  render?: (row: T) => React.ReactNode
  sortable?: boolean
  sortKey?: (row: T) => number | string
}

interface DataGridProps<T> {
  columns: Column<T>[]
  data: T[]
  rowKey: (row: T) => string
  onRowClick?: (row: T) => void
  selectedKey?: string
  maxHeight?: number | string
}

export default function DataGrid<T>({ columns, data, rowKey, onRowClick, selectedKey, maxHeight = 500 }: DataGridProps<T>) {
  const [sortCol, setSortCol] = useState<string | null>(null)
  const [sortAsc, setSortAsc] = useState(true)

  const sorted = useMemo(() => {
    if (!sortCol) return data
    const col = columns.find(c => c.key === sortCol)
    if (!col) return data
    const fn = col.sortKey || ((r: T) => (r as Record<string, unknown>)[col.key] as number | string)
    return [...data].sort((a, b) => {
      const va = fn(a), vb = fn(b)
      if (typeof va === 'number' && typeof vb === 'number') return sortAsc ? va - vb : vb - va
      return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va))
    })
  }, [data, sortCol, sortAsc, columns])

  const handleSort = (key: string) => {
    if (sortCol === key) setSortAsc(!sortAsc)
    else { setSortCol(key); setSortAsc(false) }
  }

  return (
    <div style={{
      overflow: 'auto', maxHeight,
      border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-md)',
      boxShadow: 'var(--shadow-sm)',
    }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
        <thead>
          <tr>
            {columns.map(col => (
              <th
                key={col.key}
                onClick={col.sortable !== false ? () => handleSort(col.key) : undefined}
                style={{
                  position: 'sticky', top: 0, zIndex: 2,
                  padding: '5px 8px',
                  textAlign: col.align || 'left',
                  color: sortCol === col.key ? 'var(--accent)' : 'var(--text3)',
                  fontWeight: 600,
                  fontSize: 9,
                  textTransform: 'uppercase',
                  letterSpacing: '.4px',
                  borderBottom: '1px solid var(--border)',
                  background: 'var(--bg1)',
                  cursor: col.sortable !== false ? 'pointer' : 'default',
                  width: col.width,
                  whiteSpace: 'nowrap',
                  userSelect: 'none',
                  transition: 'color var(--transition)',
                }}
              >
                {col.label}
                {sortCol === col.key && <span style={{ marginLeft: 2, fontSize: 8 }}>{sortAsc ? '\u25b2' : '\u25bc'}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map(row => {
            const key = rowKey(row)
            const isSelected = key === selectedKey
            return (
              <tr
                key={key}
                onClick={() => onRowClick?.(row)}
                style={{
                  background: isSelected ? 'var(--accent-dim)' : 'transparent',
                  cursor: onRowClick ? 'pointer' : 'default',
                  transition: 'background var(--transition)',
                }}
                onMouseEnter={e => { if (!isSelected) (e.currentTarget.style.background = 'rgba(255,255,255,.02)') }}
                onMouseLeave={e => { if (!isSelected) (e.currentTarget.style.background = 'transparent') }}
              >
                {columns.map(col => (
                  <td key={col.key} style={{
                    padding: '4px 8px',
                    textAlign: col.align || 'left',
                    borderBottom: '1px solid var(--border-subtle)',
                    color: 'var(--text1)',
                  }}>
                    {col.render ? col.render(row) : String((row as Record<string, unknown>)[col.key] ?? '')}
                  </td>
                ))}
              </tr>
            )
          })}
          {sorted.length === 0 && (
            <tr><td colSpan={columns.length} style={{ padding: 20, textAlign: 'center', color: 'var(--text3)' }}>No data</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

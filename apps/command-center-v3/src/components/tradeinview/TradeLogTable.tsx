import { fmt$ } from '../../lib/format'

const COLS = [
  { k: 'symbol', l: 'Symbol' },
  { k: 'na', l: 'Account' },
  { k: 'entryDate', l: 'Entry' },
  { k: 'exitDate', l: 'Exit' },
  { k: 'shares', l: 'Sh' },
  { k: 'ep', l: 'Entry $' },
  { k: 'xp', l: 'Exit $' },
  { k: 'pnl', l: 'P&L' },
  { k: 'pnlPct', l: '%' },
  { k: 'strat', l: 'Strategy' },
  { k: 'eg', l: 'E' },
  { k: 'xg', l: 'X' },
  { k: 'status', l: 'Status' },
] as const

export default function TradeLogTable({ trades, onRow, sortCol, sortDir, onSort }: {
  trades: any[]
  onRow: (t: any) => void
  sortCol: string
  sortDir: 'asc' | 'desc'
  onSort: (col: string) => void
}) {
  return (
    <div style={{ overflowX: 'auto', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
        <thead>
          <tr style={{ background: 'var(--bg2)' }}>
            {COLS.map(c => (
              <th key={c.k} onClick={() => onSort(c.k)}
                style={{ padding: '6px 8px', textAlign: 'left', cursor: 'pointer', color: sortCol === c.k ? '#60a5fa' : 'var(--text3)', fontSize: 8, textTransform: 'uppercase' }}>
                {c.l}{sortCol === c.k ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => (
            <tr key={i} onClick={() => onRow(t)} style={{ borderTop: '1px solid var(--border)', cursor: 'pointer' }}>
              {COLS.map(c => {
                let v: any = t[c.k]
                if (c.k === 'pnl') v = fmt$(v, 2)
                if (c.k === 'pnlPct' && v != null) v = `${Number(v).toFixed(1)}%`
                if (c.k === 'ep' || c.k === 'xp') v = v != null ? `$${Number(v).toFixed(2)}` : '—'
                return (
                  <td key={c.k} style={{ padding: '5px 8px', color: c.k === 'pnl' ? (t.pnl >= 0 ? '#22c55e' : '#ef4444') : 'var(--text1)', fontFamily: c.k === 'symbol' ? 'monospace' : undefined, fontWeight: c.k === 'symbol' ? 700 : 400 }}>
                    {v ?? '—'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {trades.length === 0 && <div style={{ padding: 16, textAlign: 'center', color: 'var(--text3)' }}>No trades</div>}
    </div>
  )
}
import { useState, useMemo } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import DetailDrawer, { DrawerStat, DrawerSection } from '../components/DetailDrawer'
import DataGrid from '../components/DataGrid'
import { BarChartJS } from '../components/charts'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtPct, deltaColor } from '../lib/format'

interface Trade { symbol: string; account: string; open_date: string; close_date: string; trade_type: string; shares: number; buy_price: number; sell_price: number; pnl: number; pnl_pct: number; hold_days: number }
interface JournalData { stats: Record<string, number>; trade_count: number; real_trade_count: number; trades: Trade[] }

export default function Journal() {
  const { data: j } = useApi<JournalData>('/api/v2/journal')
  const [symFilter, setSymFilter] = useState('ALL')
  const [acctFilter, setAcctFilter] = useState('ALL')
  const [typeFilter, setTypeFilter] = useState('ALL')
  const [resultFilter, setResultFilter] = useState('ALL')
  const [calMonth, setCalMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null)

  const realTrades = useMemo(() => j?.trades.filter(t => t.pnl !== 0) ?? [], [j])

  const symbols = useMemo(() => ['ALL', ...Array.from(new Set(realTrades.map(t => t.symbol))).sort()], [realTrades])
  const accounts = useMemo(() => ['ALL', ...Array.from(new Set(realTrades.map(t => t.account))).sort()], [realTrades])
  const types = useMemo(() => ['ALL', ...Array.from(new Set(realTrades.map(t => t.trade_type).filter(Boolean))).sort()], [realTrades])

  const filtered = useMemo(() => {
    return realTrades.filter(t => {
      if (symFilter !== 'ALL' && t.symbol !== symFilter) return false
      if (acctFilter !== 'ALL' && t.account !== acctFilter) return false
      if (typeFilter !== 'ALL' && t.trade_type !== typeFilter) return false
      if (resultFilter === 'Win' && t.pnl <= 0) return false
      if (resultFilter === 'Loss' && t.pnl >= 0) return false
      return true
    })
  }, [realTrades, symFilter, acctFilter, typeFilter, resultFilter])

  if (!j) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading...</div>

  const s = j.stats

  // Monthly P&L
  const monthly: Record<string, number> = {}
  for (const t of realTrades) { const m = t.close_date?.slice(0, 7) || '?'; monthly[m] = (monthly[m] || 0) + t.pnl }
  const months = Object.entries(monthly).sort((a, b) => a[0].localeCompare(b[0]))

  // Trade calendar — daily P&L for selected month
  const calDays: Record<number, number> = {}
  for (const t of realTrades) {
    if (t.close_date?.slice(0, 7) === calMonth) {
      const day = parseInt(t.close_date.slice(8, 10))
      calDays[day] = (calDays[day] || 0) + t.pnl
    }
  }
  const calYear = parseInt(calMonth.slice(0, 4))
  const calMon = parseInt(calMonth.slice(5, 7)) - 1
  const firstDay = new Date(calYear, calMon, 1).getDay()
  const daysInMonth = new Date(calYear, calMon + 1, 0).getDate()
  const calMonths = Array.from(new Set(realTrades.map(t => t.close_date?.slice(0, 7)).filter(Boolean))).sort()

  const FilterRow = ({ label, options, value, onChange }: { label: string; options: string[]; value: string; onChange: (v: string) => void }) => (
    <div style={{ display: 'flex', gap: 3, alignItems: 'center', marginBottom: 4 }}>
      <span style={{ width: 50, fontSize: 9, color: 'var(--text3)' }}>{label}</span>
      <div style={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
        {options.slice(0, 12).map(o => (
          <button key={o} onClick={() => onChange(o)} style={{
            padding: '2px 7px', fontSize: 9, border: '1px solid var(--border)', borderRadius: 'var(--radius)',
            background: value === o ? 'var(--accent-dim)' : 'var(--bg-card)',
            color: value === o ? 'var(--accent)' : 'var(--text3)',
            cursor: 'pointer', fontFamily: 'var(--mono)',
          }}>{o === 'ALL' ? 'All' : o.replace('schwab_', '').slice(0, 8)}</button>
        ))}
      </div>
    </div>
  )

  const columns = [
    { key: 'close_date', label: 'Closed', width: 68, render: (r: Trade) => <span style={{ fontSize: 10, color: 'var(--text2)' }}>{r.close_date}</span> },
    { key: 'symbol', label: 'Symbol', width: 50, render: (r: Trade) => <span style={{ fontWeight: 700 }}>{r.symbol}</span> },
    { key: 'trade_type', label: 'Type', width: 42, render: (r: Trade) => <span style={{ fontSize: 9, color: 'var(--text3)' }}>{r.trade_type?.slice(0, 5)}</span> },
    { key: 'shares', label: 'Shares', width: 45, align: 'right' as const, render: (r: Trade) => r.shares.toFixed(1) },
    { key: 'buy_price', label: 'Buy', width: 50, align: 'right' as const, render: (r: Trade) => fmt$(r.buy_price, 2) },
    { key: 'sell_price', label: 'Sell', width: 50, align: 'right' as const, render: (r: Trade) => fmt$(r.sell_price, 2) },
    { key: 'pnl', label: 'P&L', width: 55, align: 'right' as const, sortKey: (r: Trade) => r.pnl, render: (r: Trade) => (
      <span style={{ fontWeight: 600, color: deltaColor(r.pnl) }}>{r.pnl >= 0 ? '+' : ''}{fmt$(r.pnl)}</span>
    )},
    { key: 'pnl_pct', label: '%', width: 45, align: 'right' as const, sortKey: (r: Trade) => r.pnl_pct, render: (r: Trade) => (
      <span style={{ color: deltaColor(r.pnl_pct) }}>{fmtPct(r.pnl_pct, 1)}</span>
    )},
    { key: 'hold_days', label: 'Days', width: 32, align: 'right' as const, render: (r: Trade) => <span style={{ color: 'var(--text3)' }}>{r.hold_days}</span> },
    { key: 'account', label: 'Acct', width: 55, render: (r: Trade) => <span style={{ fontSize: 9, color: 'var(--text3)' }}>{r.account?.replace('schwab_', '').slice(0, 8)}</span> },
  ]

  return (
    <>
      <PageHeader title="Trade Journal" subtitle={`${j.real_trade_count} closed trades | ${filtered.length} shown`} />

      {/* Stat cards */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <MetricTile label="Net P&L" value={`${s.total_pnl >= 0 ? '+' : ''}${fmt$(s.total_pnl)}`} deltaColor={deltaColor(s.total_pnl)} />
        <MetricTile label="Win Rate" value={`${s.win_rate}%`} deltaColor={s.win_rate >= 50 ? 'var(--green)' : 'var(--amber)'} />
        <MetricTile label="Profit Factor" value={(s.profit_factor || 0).toFixed(2)} />
        <MetricTile label="Avg Winner" value={`+${fmt$(s.avg_winner || 0)}`} deltaColor="var(--green)" />
        <MetricTile label="Avg Loser" value={fmt$(s.avg_loser || 0)} deltaColor="var(--red)" />
        <MetricTile label="Expectancy" value={fmt$(s.trade_expectancy || 0)} />
      </div>

      {/* BLOCK 9: Trade calendar + monthly chart side by side */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 12 }}>
        <Card title="Trade Calendar" subtitle={calMonth}>
          <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
            <button onClick={() => { const i = calMonths.indexOf(calMonth); if (i > 0) setCalMonth(calMonths[i - 1]) }} style={{ fontSize: 10, padding: '1px 6px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>{'\u25c0'}</button>
            <span style={{ fontSize: 10, color: 'var(--text1)', flex: 1, textAlign: 'center' }}>{calMonth}</span>
            <button onClick={() => { const i = calMonths.indexOf(calMonth); if (i < calMonths.length - 1) setCalMonth(calMonths[i + 1]) }} style={{ fontSize: 10, padding: '1px 6px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>{'\u25b6'}</button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 2, fontSize: 9 }}>
            {['Su','Mo','Tu','We','Th','Fr','Sa'].map(d => <div key={d} style={{ textAlign: 'center', color: 'var(--text3)', fontWeight: 600 }}>{d}</div>)}
            {Array.from({ length: firstDay }).map((_, i) => <div key={'e' + i} />)}
            {Array.from({ length: daysInMonth }).map((_, i) => {
              const day = i + 1
              const pnl = calDays[day]
              const hasTrade = pnl !== undefined
              return (
                <div key={day} style={{
                  textAlign: 'center', padding: '3px 0', borderRadius: 2, cursor: hasTrade ? 'pointer' : 'default',
                  background: hasTrade ? (pnl > 0 ? 'var(--green-dim)' : pnl < 0 ? 'var(--red-dim)' : 'var(--bg3)') : 'transparent',
                  color: hasTrade ? (pnl > 0 ? 'var(--green)' : pnl < 0 ? 'var(--red)' : 'var(--text3)') : 'var(--text3)',
                  fontWeight: hasTrade ? 700 : 400,
                }}>
                  <div>{day}</div>
                  {hasTrade && <div style={{ fontSize: 7 }}>{pnl >= 0 ? '+' : ''}{Math.abs(pnl) >= 1000 ? (pnl / 1000).toFixed(0) + 'k' : Math.round(pnl)}</div>}
                </div>
              )
            })}
          </div>
        </Card>

        {months.length > 1 && (
          <Card title="Monthly P&L">
            <div style={{ height: 120 }}>
              <BarChartJS labels={months.map(([m]) => m.slice(5))} data={months.map(([, v]) => v)} />
            </div>
          </Card>
        )}
      </div>

      {/* BLOCK 8: Filter pills */}
      <SectionHeader title="Filters" />
      <Card compact>
        <FilterRow label="Symbol" options={symbols} value={symFilter} onChange={setSymFilter} />
        <FilterRow label="Account" options={accounts} value={acctFilter} onChange={setAcctFilter} />
        <FilterRow label="Type" options={types} value={typeFilter} onChange={setTypeFilter} />
        <FilterRow label="Result" options={['ALL', 'Win', 'Loss']} value={resultFilter} onChange={setResultFilter} />
      </Card>

      <SectionHeader title="Closed Trades" count={filtered.length} />
      <DataGrid columns={columns} data={filtered} rowKey={r => r.symbol + r.close_date + r.pnl} maxHeight={350}
        onRowClick={r => setSelectedTrade(r)} />

      {/* Journal trade detail drawer */}
      <DetailDrawer open={!!selectedTrade} onClose={() => setSelectedTrade(null)}
        title={selectedTrade?.symbol || ''} subtitle={`${selectedTrade?.trade_type || ''} | Closed ${selectedTrade?.close_date || ''}`}>
        {selectedTrade && (
          <>
            <DrawerSection title="Trade Detail">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                <DrawerStat label="Type" value={selectedTrade.trade_type || '—'} />
                <DrawerStat label="Close Date" value={selectedTrade.close_date} />
                <DrawerStat label="Shares" value={selectedTrade.shares.toFixed(2)} />
                <DrawerStat label="Hold Days" value={String(selectedTrade.hold_days || '—')} />
                <DrawerStat label="Buy Price" value={fmt$(selectedTrade.buy_price, 2)} />
                <DrawerStat label="Sell Price" value={fmt$(selectedTrade.sell_price, 2)} />
                <DrawerStat label="P&L" value={`${selectedTrade.pnl >= 0 ? '+' : ''}${fmt$(selectedTrade.pnl)}`} color={deltaColor(selectedTrade.pnl)} />
                <DrawerStat label="P&L %" value={fmtPct(selectedTrade.pnl_pct, 1)} color={deltaColor(selectedTrade.pnl_pct)} />
                <DrawerStat label="Account" value={selectedTrade.account?.replace('schwab_', '') || '—'} />
                <DrawerStat label="Result" value={selectedTrade.pnl > 0 ? 'WIN' : selectedTrade.pnl < 0 ? 'LOSS' : 'FLAT'} color={deltaColor(selectedTrade.pnl)} />
              </div>
            </DrawerSection>
            <DrawerSection title="Links">
              <div style={{ display: 'flex', gap: 6 }}>
                <a href={`https://finviz.com/quote.ashx?t=${selectedTrade.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Finviz</a>
                <a href={`https://finance.yahoo.com/quote/${selectedTrade.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Yahoo</a>
              </div>
            </DrawerSection>
            <div style={{ marginTop: 14, padding: '6px 10px', background: 'var(--bg3)', borderRadius: 'var(--radius)', fontSize: 9, color: 'var(--text3)' }}>
              Read-only view. Setup/rating/notes editing deferred to future build.
            </div>
          </>
        )}
      </DetailDrawer>
    </>
  )
}

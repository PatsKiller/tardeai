import { useState, useMemo, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import DetailDrawer, { DrawerStat, DrawerSection } from '../components/DetailDrawer'
import DataGrid from '../components/DataGrid'
import { BarChartJS } from '../components/charts'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtPct, deltaColor } from '../lib/format'

interface Trade { trade_key: string; symbol: string; account: string; open_date: string; close_date: string; trade_type: string; shares: number; buy_price: number; sell_price: number; pnl: number; pnl_pct: number; hold_days: number }
interface JournalData { stats: Record<string, number>; trade_count: number; real_trade_count: number; trades: Trade[] }

interface ReviewData {
  setup_name: string; setup_family: string; timeframe: string; catalyst_type: string
  direction: string; entry_type: string; exit_type: string; market_regime: string
  followed_plan: boolean | null; well_executed: boolean | null
  execution_quality_score: number | null; sizing_quality_score: number | null
  risk_management_score: number | null; confidence_before: number | null; stress_level: number | null
  emotion_before: string; emotion_during: string
  mistake_tags: string[]; lesson_learned: string; review_notes: string
}

const EMPTY_REVIEW: ReviewData = {
  setup_name: '', setup_family: '', timeframe: '', catalyst_type: '',
  direction: '', entry_type: '', exit_type: '', market_regime: '',
  followed_plan: null, well_executed: null,
  execution_quality_score: null, sizing_quality_score: null,
  risk_management_score: null, confidence_before: null, stress_level: null,
  emotion_before: '', emotion_during: '',
  mistake_tags: [], lesson_learned: '', review_notes: '',
}

const SETUP_OPTIONS = ['Breakout', 'Pullback', 'Trend Follow', 'Mean Reversion', 'Momentum', 'Swing', 'Dividend Capture', 'Earnings Play', 'Gap Fill', 'Other']
const SETUP_FAMILY_OPTIONS = ['Momentum', 'Mean Reversion', 'Trend', 'Income', 'Value', 'Speculative', 'Defensive']
const TIMEFRAME_OPTIONS = ['Scalp', 'Intraday', 'Swing 1-5d', 'Swing 1-4w', 'Position 1-6m', 'Long Term']
const CATALYST_OPTIONS = ['Earnings', 'News', 'Sector Rotation', 'Technical', 'Macro', 'Dividend', 'None']
const DIRECTION_OPTIONS = ['Long', 'Short']
const ENTRY_OPTIONS = ['Limit', 'Market', 'Stop Entry', 'Scale In', 'Breakout Entry']
const EXIT_OPTIONS = ['Target Hit', 'Stop Hit', 'Trailing Stop', 'Time Exit', 'Discretionary', 'Scale Out']
const REGIME_OPTIONS = ['Bull', 'Neutral', 'Bear', 'Volatile', 'Range-Bound']
const EMOTION_OPTIONS = ['Calm', 'Confident', 'Focused', 'Hesitant', 'Anxious', 'FOMO', 'Revenge', 'Impatient', 'Distracted', 'Greedy']
const MISTAKE_OPTIONS = ['Oversized', 'No stop', 'Chased entry', 'Early exit', 'Late exit', 'FOMO entry', 'Revenge trade', 'Ignored plan', 'Poor timing', 'Wrong thesis']

export default function Journal() {
  const navigate = useNavigate()
  const { data: j } = useApi<JournalData>('/api/v2/journal')
  const [symFilter, setSymFilter] = useState('ALL')
  const [acctFilter, setAcctFilter] = useState('ALL')
  const [typeFilter, setTypeFilter] = useState('ALL')
  const [resultFilter, setResultFilter] = useState('ALL')
  const [dateFilter, setDateFilter] = useState('')
  const [chartPeriod, setChartPeriod] = useState<'1w' | '1m' | '3m' | 'all'>('all')
  const [calView, setCalView] = useState<'month' | 'quarter' | 'year' | 'all'>('month')
  const [calMonth, setCalMonth] = useState('')  // set to latest trade month once data loads
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null)
  const [drawerTab, setDrawerTab] = useState<'trade' | 'review' | 'psych'>('trade')
  const [review, setReview] = useState<ReviewData>(EMPTY_REVIEW)
  const [reviewLoading, setReviewLoading] = useState(false)
  const [saveStatus, setSaveStatus] = useState<string | null>(null)

  const realTrades = useMemo(() => j?.trades.filter(t => t.pnl !== 0) ?? [], [j])

  // Default calendar to the most recent month with trades
  useEffect(() => {
    if (!calMonth && realTrades.length > 0) {
      const months = realTrades.map(t => t.close_date?.slice(0, 7)).filter(Boolean).sort()
      setCalMonth(months[months.length - 1] || new Date().toISOString().slice(0, 7))
    }
  }, [realTrades, calMonth])

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
      if (dateFilter && t.close_date !== dateFilter) return false
      return true
    })
  }, [realTrades, symFilter, acctFilter, typeFilter, resultFilter])

  // Load review when trade is selected
  useEffect(() => {
    if (!selectedTrade) return
    setDrawerTab('trade')
    setReviewLoading(true)
    setSaveStatus(null)
    fetch(`/api/v2/journal/review?trade_key=${encodeURIComponent(selectedTrade.trade_key)}`)
      .then(r => r.json())
      .then(d => {
        const rv = d?.data?.review || {}
        setReview({
          setup_name: rv.setup_name || '', setup_family: rv.setup_family || '',
          timeframe: rv.timeframe || '', catalyst_type: rv.catalyst_type || '',
          direction: rv.direction || '', entry_type: rv.entry_type || '',
          exit_type: rv.exit_type || '', market_regime: rv.market_regime || '',
          followed_plan: rv.followed_plan ?? null, well_executed: rv.well_executed ?? null,
          execution_quality_score: rv.execution_quality_score ?? null,
          sizing_quality_score: rv.sizing_quality_score ?? null,
          risk_management_score: rv.risk_management_score ?? null,
          confidence_before: rv.confidence_before ?? null,
          stress_level: rv.stress_level ?? null,
          emotion_before: rv.emotion_before || '', emotion_during: rv.emotion_during || '',
          mistake_tags: rv.mistake_tags || [],
          lesson_learned: rv.lesson_learned || '', review_notes: rv.review_notes || '',
        })
        setReviewLoading(false)
      })
      .catch(() => { setReview(EMPTY_REVIEW); setReviewLoading(false) })
  }, [selectedTrade])

  const handleSave = useCallback(async () => {
    if (!selectedTrade) return
    setSaveStatus('Saving...')
    try {
      const resp = await fetch('/api/v2/journal/review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trade_key: selectedTrade.trade_key,
          symbol: selectedTrade.symbol,
          account: selectedTrade.account,
          closed_date: selectedTrade.close_date,
          ...review,
        }),
      })
      const d = await resp.json()
      setSaveStatus(d.ok ? 'Saved' : d.error || 'Failed')
      if (d.ok) setTimeout(() => setSaveStatus(null), 2000)
    } catch { setSaveStatus('Failed') }
  }, [selectedTrade, review])

  if (!j) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading...</div>

  const s = j.stats

  // Monthly P&L
  const monthly: Record<string, number> = {}
  for (const t of realTrades) { const m = t.close_date?.slice(0, 7) || '?'; monthly[m] = (monthly[m] || 0) + t.pnl }
  const months = Object.entries(monthly).sort((a, b) => a[0].localeCompare(b[0]))

  // Trade calendar — daily P&L + tickers for selected month
  const effectiveCalMonth = calMonth || new Date().toISOString().slice(0, 7)
  const calDays: Record<number, number> = {}
  const calTickers: Record<number, { sym: string; pnl: number }[]> = {}
  for (const t of realTrades) {
    if (t.close_date?.slice(0, 7) === effectiveCalMonth) {
      const day = parseInt(t.close_date.slice(8, 10))
      calDays[day] = (calDays[day] || 0) + t.pnl
      if (!calTickers[day]) calTickers[day] = []
      calTickers[day].push({ sym: t.symbol, pnl: t.pnl })
    }
  }
  const calYear = parseInt(effectiveCalMonth.slice(0, 4))
  const calMon = parseInt(effectiveCalMonth.slice(5, 7)) - 1
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
    { key: 'symbol', label: 'Symbol', width: 50, render: (r: Trade) => <span style={{ fontWeight: 700, color: 'var(--accent)', cursor: 'pointer' }} onClick={e => { e.stopPropagation(); navigate(`/research?symbol=${r.symbol}`) }}>{r.symbol}</span> },
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
    { key: 'account', label: 'Acct', width: 55, render: (r: Trade) => <span style={{ fontSize: 9, color: 'var(--text3)', cursor: 'pointer' }} onClick={e => { e.stopPropagation(); setAcctFilter(r.account) }}>{r.account?.replace('schwab_', '').slice(0, 8)}</span> },
  ]

  // Shared styles
  const selectStyle: React.CSSProperties = { padding: '4px 6px', fontSize: 10, background: 'var(--bg3)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', color: 'var(--text1)', fontFamily: 'var(--mono)', width: '100%' }
  const textareaStyle: React.CSSProperties = { ...selectStyle, resize: 'vertical', minHeight: 40 }
  const labelStyle: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' as const, letterSpacing: '0.5px', marginBottom: 2 }

  const BoolToggle = ({ label, value, onChange }: { label: string; value: boolean | null; onChange: (v: boolean) => void }) => (
    <div>
      <div style={labelStyle}>{label}</div>
      <div style={{ display: 'flex', gap: 3 }}>
        {[true, false].map(v => (
          <button key={String(v)} onClick={() => onChange(v)} style={{
            flex: 1, padding: '3px 0', fontSize: 9, fontWeight: 600,
            border: `1px solid ${value === v ? (v ? 'var(--green)' : 'var(--red)') : 'var(--border)'}`,
            borderRadius: 'var(--radius)', cursor: 'pointer', fontFamily: 'var(--mono)',
            background: value === v ? (v ? 'var(--green-dim)' : 'var(--red-dim)') : 'var(--bg3)',
            color: value === v ? (v ? 'var(--green)' : 'var(--red)') : 'var(--text3)',
          }}>{v ? 'Yes' : 'No'}</button>
        ))}
      </div>
    </div>
  )

  const ScoreSelect = ({ label, value, onChange }: { label: string; value: number | null; onChange: (v: number) => void }) => (
    <div>
      <div style={labelStyle}>{label}</div>
      <div style={{ display: 'flex', gap: 2 }}>
        {[1, 2, 3, 4, 5].map(n => (
          <button key={n} onClick={() => onChange(n)} style={{
            flex: 1, padding: '3px 0', fontSize: 10, fontWeight: 600,
            border: `1px solid ${value === n ? 'var(--accent)' : 'var(--border)'}`,
            borderRadius: 'var(--radius)', cursor: 'pointer', fontFamily: 'var(--mono)',
            background: value === n ? 'var(--accent-dim)' : 'var(--bg3)',
            color: value === n ? 'var(--accent)' : 'var(--text3)',
          }}>{n}</button>
        ))}
      </div>
    </div>
  )

  const TagSelect = ({ label, options, value, onChange }: { label: string; options: string[]; value: string[]; onChange: (v: string[]) => void }) => (
    <div>
      <div style={labelStyle}>{label}</div>
      <div style={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
        {options.map(tag => {
          const active = value.includes(tag)
          return (
            <button key={tag} onClick={() => onChange(active ? value.filter(t => t !== tag) : [...value, tag])} style={{
              padding: '2px 6px', fontSize: 8, fontWeight: active ? 600 : 400,
              border: `1px solid ${active ? 'var(--red)' : 'var(--border)'}`,
              borderRadius: 'var(--radius)', cursor: 'pointer', fontFamily: 'var(--mono)',
              background: active ? 'var(--red-dim)' : 'var(--bg3)',
              color: active ? 'var(--red)' : 'var(--text3)',
            }}>{tag}</button>
          )
        })}
      </div>
    </div>
  )

  // Tab button style
  const tabBtn = (tab: string, active: boolean): React.CSSProperties => ({
    flex: 1, padding: '5px 0', fontSize: 9, fontWeight: 600, textAlign: 'center',
    border: 'none', borderBottom: `2px solid ${active ? 'var(--accent)' : 'transparent'}`,
    background: 'transparent', color: active ? 'var(--accent)' : 'var(--text3)',
    cursor: 'pointer', fontFamily: 'var(--mono)',
  })

  return (
    <>
      <PageHeader title="Trade Journal" subtitle={`${j.real_trade_count} closed trades | ${filtered.length} shown (filters applied — clear to see all ${j.trade_count})`} />

      {/* Stat cards */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <MetricTile label="Net P&L" value={`${s.total_pnl >= 0 ? '+' : ''}${fmt$(s.total_pnl)}`} deltaColor={deltaColor(s.total_pnl)} />
        <MetricTile label="Win Rate" value={`${s.win_rate}%`} deltaColor={s.win_rate >= 50 ? 'var(--green)' : 'var(--amber)'} />
        <MetricTile label="Profit Factor" value={(s.profit_factor || 0).toFixed(2)} />
        <MetricTile label="Avg Winner" value={`+${fmt$(s.avg_winner || 0)}`} deltaColor="var(--green)" />
        <MetricTile label="Avg Loser" value={fmt$(s.avg_loser || 0)} deltaColor="var(--red)" />
        <MetricTile label="Expectancy" value={fmt$(s.trade_expectancy || 0)} delta="avg $/trade · target >$50" deltaColor={(s.trade_expectancy || 0) >= 50 ? 'var(--green)' : 'var(--amber)'} tooltip="Expected $ per trade on average. Positive = edge exists. Formula: (Win% × Avg Win) − (Loss% × Avg Loss). Under $50 may not cover commissions + slippage." />
      </div>

      {/* Trade Calendar — multi-view: month / quarter / year / all */}
      <Card title="Trade Calendar">
        <div style={{ display: 'flex', gap: 6, marginBottom: 10, alignItems: 'center' }}>
          <button onClick={() => { const i = calMonths.indexOf(effectiveCalMonth); if (i > 0) setCalMonth(calMonths[i - 1]) }} style={{ fontSize: 12, padding: '3px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>{'\u25c0'}</button>
          <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)', flex: 1, textAlign: 'center', fontFamily: 'var(--sans)' }}>{effectiveCalMonth}</span>
          <button onClick={() => { const i = calMonths.indexOf(effectiveCalMonth); if (i < calMonths.length - 1) setCalMonth(calMonths[i + 1]) }} style={{ fontSize: 12, padding: '3px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>{'\u25b6'}</button>
          <div style={{ display: 'flex', gap: 2, marginLeft: 8 }}>
            {(['month', 'quarter', 'year', 'all'] as const).map(v => (
              <button key={v} onClick={() => setCalView(v)} style={{
                padding: '3px 8px', fontSize: 9, fontWeight: 600,
                border: `1px solid ${calView === v ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 'var(--radius)', cursor: 'pointer', fontFamily: 'var(--mono)',
                background: calView === v ? 'var(--accent-dim)' : 'var(--bg3)',
                color: calView === v ? 'var(--accent)' : 'var(--text3)',
              }}>{v === 'month' ? 'Month' : v === 'quarter' ? 'Quarter' : v === 'year' ? 'Year' : 'All'}</button>
            ))}
          </div>
        </div>

        {(() => {
          // Build list of months to render based on view
          const getMonthsToShow = (): string[] => {
            if (calView === 'month') return [effectiveCalMonth]
            if (calView === 'quarter') {
              const m = parseInt(effectiveCalMonth.slice(5, 7))
              const y = effectiveCalMonth.slice(0, 4)
              const qStart = Math.floor((m - 1) / 3) * 3 + 1
              return [0, 1, 2].map(i => `${y}-${String(qStart + i).padStart(2, '0')}`)
            }
            if (calView === 'year') {
              const y = effectiveCalMonth.slice(0, 4)
              return Array.from({ length: 12 }, (_, i) => `${y}-${String(i + 1).padStart(2, '0')}`)
            }
            // 'all' — show every month that has trades
            return calMonths
          }
          const monthsToShow = getMonthsToShow()
          const isCompact = calView !== 'month'
          const gridCols = calView === 'month' ? 1 : calView === 'quarter' ? 3 : calView === 'year' ? 4 : 4

          // Build trade data per day across ALL months
          const allDayData: Record<string, { pnl: number; tickers: { sym: string; pnl: number }[] }> = {}
          for (const t of realTrades) {
            const d = t.close_date
            if (!d) continue
            if (!allDayData[d]) allDayData[d] = { pnl: 0, tickers: [] }
            allDayData[d].pnl += t.pnl
            allDayData[d].tickers.push({ sym: t.symbol, pnl: t.pnl })
          }

          return (
            <div style={{ display: 'grid', gridTemplateColumns: `repeat(${gridCols}, 1fr)`, gap: isCompact ? 8 : 0 }}>
              {monthsToShow.map(monthKey => {
                const yr = parseInt(monthKey.slice(0, 4))
                const mn = parseInt(monthKey.slice(5, 7)) - 1
                const fd = new Date(yr, mn, 1).getDay()
                const dim = new Date(yr, mn + 1, 0).getDate()
                const monthPnl = Object.entries(allDayData).filter(([d]) => d.startsWith(monthKey)).reduce((s, [, v]) => s + v.pnl, 0)
                const monthTrades = Object.entries(allDayData).filter(([d]) => d.startsWith(monthKey)).reduce((s, [, v]) => s + v.tickers.length, 0)

                return (
                  <div key={monthKey}>
                    {isCompact && (
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3, padding: '2px 4px' }}>
                        <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text0)', cursor: 'pointer' }} onClick={() => { setCalMonth(monthKey); setCalView('month') }}>{monthKey}</span>
                        {monthTrades > 0 && <span style={{ fontSize: 9, fontWeight: 700, color: monthPnl >= 0 ? 'var(--green)' : 'var(--red)' }}>{monthPnl >= 0 ? '+' : ''}{fmt$(monthPnl)} ({monthTrades})</span>}
                      </div>
                    )}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: isCompact ? 1 : 3 }}>
                      {!isCompact && ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(d => <div key={d} style={{ textAlign: 'center', color: 'var(--text3)', fontWeight: 700, fontSize: 10, padding: '4px 0' }}>{d}</div>)}
                      {isCompact && ['S','M','T','W','T','F','S'].map((d, di) => <div key={di} style={{ textAlign: 'center', color: 'var(--text3)', fontSize: 7, fontWeight: 600 }}>{d}</div>)}
                      {Array.from({ length: fd }).map((_, i) => <div key={'e' + i} />)}
                      {Array.from({ length: dim }).map((_, i) => {
                        const day = i + 1
                        const dateStr = `${monthKey}-${String(day).padStart(2, '0')}`
                        const dd = allDayData[dateStr]
                        const pnl = dd?.pnl
                        const tickers = dd?.tickers || []
                        const hasTrade = dd !== undefined
                        const isSelected = dateFilter === dateStr

                        if (isCompact) {
                          return (
                            <div key={day} onClick={() => { if (hasTrade) setDateFilter(isSelected ? '' : dateStr) }} style={{
                              textAlign: 'center', padding: '2px 0', borderRadius: 2, cursor: hasTrade ? 'pointer' : 'default', fontSize: 8,
                              background: isSelected ? 'var(--accent-dim)' : hasTrade ? (pnl! > 0 ? 'rgba(14,203,129,0.12)' : 'rgba(246,70,93,0.12)') : 'transparent',
                              color: isSelected ? 'var(--accent)' : hasTrade ? (pnl! > 0 ? 'var(--green)' : 'var(--red)') : 'var(--text3)',
                              fontWeight: hasTrade ? 700 : 400,
                            }}>{day}</div>
                          )
                        }

                        return (
                          <div key={day} onClick={() => { if (hasTrade) setDateFilter(isSelected ? '' : dateStr) }} style={{
                            padding: '6px 4px', borderRadius: 6, cursor: hasTrade ? 'pointer' : 'default', minHeight: 52,
                            background: isSelected ? 'var(--accent-dim)' : hasTrade ? (pnl! > 0 ? 'rgba(14,203,129,0.06)' : pnl! < 0 ? 'rgba(246,70,93,0.06)' : 'var(--bg3)') : 'transparent',
                            border: isSelected ? '2px solid var(--accent)' : hasTrade ? `1px solid ${pnl! > 0 ? 'rgba(14,203,129,0.15)' : 'rgba(246,70,93,0.15)'}` : '1px solid transparent',
                          }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 2 }}>
                              <span style={{ fontSize: 11, fontWeight: hasTrade ? 800 : 400, color: isSelected ? 'var(--accent)' : hasTrade ? 'var(--text0)' : 'var(--text3)' }}>{day}</span>
                              {hasTrade && <span style={{ fontSize: 10, fontWeight: 700, color: pnl! > 0 ? 'var(--green)' : pnl! < 0 ? 'var(--red)' : 'var(--text3)' }}>{pnl! >= 0 ? '+' : ''}{Math.abs(pnl!) >= 1000 ? `$${(pnl! / 1000).toFixed(1)}k` : `$${Math.round(pnl!)}`}</span>}
                            </div>
                            {tickers.length > 0 && (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                                {tickers.slice(0, 3).map((t, ti) => (
                                  <span key={ti} style={{ fontSize: 8, fontWeight: 600, color: t.pnl > 0 ? 'var(--green)' : t.pnl < 0 ? 'var(--red)' : 'var(--text3)' }}>{t.sym}</span>
                                ))}
                                {tickers.length > 3 && <span style={{ fontSize: 7, color: 'var(--text3)' }}>+{tickers.length - 3} more</span>}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          )
        })()}
      </Card>

      {/* ── Analytics Charts ── */}
      {(() => {
        const now = new Date()
        const periodCutoff = chartPeriod === '1w' ? new Date(now.getTime() - 7 * 86400000).toISOString().slice(0, 10)
          : chartPeriod === '1m' ? new Date(now.getTime() - 30 * 86400000).toISOString().slice(0, 10)
          : chartPeriod === '3m' ? new Date(now.getTime() - 90 * 86400000).toISOString().slice(0, 10)
          : '2000-01-01'
        const cTrades = realTrades.filter(t => (t.close_date || '') >= periodCutoff)

        // ── Day-of-week stats ──
        const dowNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        const dowPnl: number[] = Array(7).fill(0)
        const dowCount: number[] = Array(7).fill(0)
        const dowWins: number[] = Array(7).fill(0)
        for (const t of cTrades) {
          const d = new Date(t.close_date + 'T12:00:00').getDay()
          dowPnl[d] += t.pnl; dowCount[d]++
          if (t.pnl > 0) dowWins[d]++
        }
        const dowWinRate = dowCount.map((c, i) => c > 0 ? Math.round((dowWins[i] / c) * 100) : 0)

        // ── Weekly stats ──
        const weeklyMap: Record<string, { pnl: number; trades: number; wins: number }> = {}
        for (const t of cTrades) {
          const w = t.close_date?.slice(0, 7) || '?'
          if (!weeklyMap[w]) weeklyMap[w] = { pnl: 0, trades: 0, wins: 0 }
          weeklyMap[w].pnl += t.pnl; weeklyMap[w].trades++
          if (t.pnl > 0) weeklyMap[w].wins++
        }
        const weekKeys = Object.keys(weeklyMap).sort().slice(-12)

        // ── Trade type stats ──
        const typeMap: Record<string, { pnl: number; trades: number; wins: number; losses: number }> = {}
        for (const t of cTrades) {
          const tt = t.trade_type || 'UNKNOWN'
          if (!typeMap[tt]) typeMap[tt] = { pnl: 0, trades: 0, wins: 0, losses: 0 }
          typeMap[tt].pnl += t.pnl; typeMap[tt].trades++
          if (t.pnl > 0) typeMap[tt].wins++; else if (t.pnl < 0) typeMap[tt].losses++
        }
        const typeKeys = Object.keys(typeMap).sort()

        // ── Hour of day (from open_time if available, else estimate from trade_type) ──
        const hourCounts: number[] = Array(13).fill(0)  // 6AM-6PM
        const hourPnl: number[] = Array(13).fill(0)
        for (const t of cTrades) {
          // Estimate hour from trade type
          let hour = t.trade_type === 'DAY' ? 10 : t.trade_type === 'SWING' ? 9 : 11
          // If open_time exists, parse it
          const ot = (t as any).open_time || (t as any).close_time || ''
          if (ot && ot.includes(':')) {
            const h = parseInt(ot.split(':')[0])
            if (h >= 6 && h <= 18) hour = h
          }
          const idx = Math.max(0, Math.min(12, hour - 6))
          hourCounts[idx]++; hourPnl[idx] += t.pnl
        }
        const hourLabels = Array.from({ length: 13 }, (_, i) => `${i + 6}${i + 6 < 12 ? 'a' : 'p'}`)

        const periodBtn = (p: typeof chartPeriod, label: string) => (
          <button key={p} onClick={() => setChartPeriod(p)} style={{
            padding: '3px 10px', fontSize: 9, fontWeight: 600,
            border: `1px solid ${chartPeriod === p ? 'var(--accent)' : 'var(--border)'}`,
            borderRadius: 'var(--radius)',
            background: chartPeriod === p ? 'var(--accent-dim)' : 'var(--bg3)',
            color: chartPeriod === p ? 'var(--accent)' : 'var(--text3)',
            cursor: 'pointer', fontFamily: 'var(--mono)',
          }}>{label}</button>
        )

        return (
          <>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10, marginTop: 12 }}>
              <SectionHeader title="Trade Analytics" count={cTrades.length} />
              <div style={{ display: 'flex', gap: 3, marginLeft: 'auto' }}>
                {periodBtn('1w', '1W')}{periodBtn('1m', '1M')}{periodBtn('3m', '3M')}{periodBtn('all', 'All')}
              </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
              {/* Time of Day — trade count */}
              <Card title="Trades by Time of Day" subtitle={`${cTrades.length} trades`}>
                <div style={{ height: 140 }}>
                  <BarChartJS labels={hourLabels} data={hourCounts} colors={hourCounts.map(() => '#4a90f4')} height={120} />
                </div>
              </Card>

              {/* Time of Day — P&L */}
              <Card title="P&L by Time of Day" subtitle="estimated from trade type">
                <div style={{ height: 140 }}>
                  <BarChartJS labels={hourLabels} data={hourPnl} colors={hourPnl.map(v => v >= 0 ? '#0ecb81' : '#f6465d')} height={120} />
                </div>
              </Card>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
              {/* Day of Week — P&L + Win Rate */}
              <Card title="P&L by Day of Week">
                <div style={{ height: 140 }}>
                  <BarChartJS labels={dowNames} data={dowPnl} colors={dowPnl.map(v => v >= 0 ? '#0ecb81' : '#f6465d')} height={120} />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>
                  {dowNames.map((d, i) => <span key={d} style={{ color: dowWinRate[i] >= 60 ? 'var(--green)' : dowWinRate[i] >= 40 ? 'var(--text2)' : 'var(--red)' }}>{dowCount[i] > 0 ? `${dowWinRate[i]}%` : '—'}</span>)}
                </div>
                <div style={{ fontSize: 8, color: 'var(--text3)', textAlign: 'center', marginTop: 2 }}>Win rate by day</div>
              </Card>

              {/* Monthly P&L + Win Rate */}
              <Card title="Monthly P&L + Win Rate">
                <div style={{ height: 140 }}>
                  <BarChartJS labels={weekKeys.map(k => k.slice(5))} data={weekKeys.map(k => weeklyMap[k].pnl)} colors={weekKeys.map(k => weeklyMap[k].pnl >= 0 ? '#0ecb81' : '#f6465d')} height={120} />
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, color: 'var(--text3)', marginTop: 4 }}>
                  {weekKeys.map(k => {
                    const wr = weeklyMap[k].trades > 0 ? Math.round((weeklyMap[k].wins / weeklyMap[k].trades) * 100) : 0
                    return <span key={k} style={{ color: wr >= 60 ? 'var(--green)' : wr >= 40 ? 'var(--text2)' : 'var(--red)' }}>{wr}%</span>
                  })}
                </div>
                <div style={{ fontSize: 8, color: 'var(--text3)', textAlign: 'center', marginTop: 2 }}>Win rate by month</div>
              </Card>
            </div>

            {/* Wins & Losses by Trade Type */}
            <Card title="Wins & Losses by Trade Type">
              <div style={{ display: 'grid', gridTemplateColumns: `repeat(${typeKeys.length}, 1fr)`, gap: 8 }}>
                {typeKeys.map(tt => {
                  const d = typeMap[tt]
                  const wr = d.trades > 0 ? Math.round((d.wins / d.trades) * 100) : 0
                  return (
                    <div key={tt} style={{ textAlign: 'center', padding: '8px 4px', background: 'var(--bg3)', borderRadius: 6 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>{tt}</div>
                      <div style={{ fontSize: 18, fontWeight: 800, color: d.pnl >= 0 ? 'var(--green)' : 'var(--red)' }}>{d.pnl >= 0 ? '+' : ''}{fmt$(d.pnl)}</div>
                      <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 6, fontSize: 10 }}>
                        <span style={{ color: 'var(--green)' }}>{d.wins}W</span>
                        <span style={{ color: 'var(--red)' }}>{d.losses}L</span>
                      </div>
                      <div style={{ marginTop: 4, height: 6, background: 'var(--bg1)', borderRadius: 3, overflow: 'hidden' }}>
                        <div style={{ width: `${wr}%`, height: '100%', background: wr >= 50 ? 'var(--green)' : 'var(--red)' }} />
                      </div>
                      <div style={{ fontSize: 9, color: wr >= 50 ? 'var(--green)' : 'var(--red)', marginTop: 2 }}>{wr}% win · {d.trades} trades</div>
                    </div>
                  )
                })}
              </div>
            </Card>
          </>
        )
      })()}

      {/* Filter pills */}
      <SectionHeader title="Filters" />
      <Card compact>
        <FilterRow label="Symbol" options={symbols} value={symFilter} onChange={setSymFilter} />
        <FilterRow label="Account" options={accounts} value={acctFilter} onChange={setAcctFilter} />
        <FilterRow label="Type" options={types} value={typeFilter} onChange={setTypeFilter} />
        <FilterRow label="Result" options={['ALL', 'Win', 'Loss']} value={resultFilter} onChange={setResultFilter} />
        {dateFilter && (
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginTop: 4 }}>
            <span style={{ fontSize: 9, color: 'var(--accent)', fontWeight: 600 }}>Date: {dateFilter}</span>
            <button onClick={() => setDateFilter('')} style={{ fontSize: 8, padding: '1px 6px', border: '1px solid var(--border)', borderRadius: 3, background: 'var(--bg3)', color: 'var(--text2)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Clear</button>
          </div>
        )}
      </Card>

      <SectionHeader title="Closed Trades" count={filtered.length} />
      <DataGrid columns={columns} data={filtered} rowKey={r => r.trade_key} maxHeight={350}
        onRowClick={r => setSelectedTrade(r)} />

      {/* Journal trade detail drawer — 3 tabs */}
      <DetailDrawer open={!!selectedTrade} onClose={() => setSelectedTrade(null)}
        title={selectedTrade?.symbol || ''} subtitle={`${selectedTrade?.trade_type || ''} | Closed ${selectedTrade?.close_date || ''}`}>
        {selectedTrade && (
          <>
            {/* Tab bar */}
            <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', marginBottom: 10 }}>
              <button style={tabBtn('trade', drawerTab === 'trade')} onClick={() => setDrawerTab('trade')}>Trade</button>
              <button style={tabBtn('review', drawerTab === 'review')} onClick={() => setDrawerTab('review')}>Review</button>
              <button style={tabBtn('psych', drawerTab === 'psych')} onClick={() => setDrawerTab('psych')}>Psychology</button>
            </div>

            {/* Tab: Trade Facts (read-only) */}
            {drawerTab === 'trade' && (
              <>
                <DrawerSection title="Trade Detail">
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                    <DrawerStat label="Type" value={selectedTrade.trade_type || '\u2014'} />
                    <DrawerStat label="Close Date" value={selectedTrade.close_date} />
                    <DrawerStat label="Shares" value={selectedTrade.shares.toFixed(2)} />
                    <DrawerStat label="Hold Days" value={String(selectedTrade.hold_days || '\u2014')} />
                    <DrawerStat label="Buy Price" value={fmt$(selectedTrade.buy_price, 2)} />
                    <DrawerStat label="Sell Price" value={fmt$(selectedTrade.sell_price, 2)} />
                    <DrawerStat label="P&L" value={`${selectedTrade.pnl >= 0 ? '+' : ''}${fmt$(selectedTrade.pnl)}`} color={deltaColor(selectedTrade.pnl)} />
                    <DrawerStat label="P&L %" value={fmtPct(selectedTrade.pnl_pct, 1)} color={deltaColor(selectedTrade.pnl_pct)} />
                    <DrawerStat label="Account" value={selectedTrade.account?.replace('schwab_', '') || '\u2014'} />
                    <DrawerStat label="Result" value={selectedTrade.pnl > 0 ? 'WIN' : selectedTrade.pnl < 0 ? 'LOSS' : 'FLAT'} color={deltaColor(selectedTrade.pnl)} />
                  </div>
                </DrawerSection>
                <DrawerSection title="Links & Research">
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <button onClick={() => navigate(`/research?symbol=${selectedTrade.symbol}`)} style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer' }}>Research</button>
                    <button onClick={() => navigate(`/portfolio?symbol=${selectedTrade.symbol}`)} style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer' }}>Holdings</button>
                    <button onClick={() => navigate(`/technical?symbol=${selectedTrade.symbol}`)} style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer' }}>Technical</button>
                    <a href={`https://finviz.com/quote.ashx?t=${selectedTrade.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Finviz</a>
                    <a href={`https://finance.yahoo.com/quote/${selectedTrade.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Yahoo</a>
                  </div>
                </DrawerSection>
              </>
            )}

            {/* Tab: Review (editable) */}
            {drawerTab === 'review' && (
              <>
                {reviewLoading ? (
                  <div style={{ color: 'var(--text3)', fontSize: 10, padding: 12 }}>Loading review...</div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <DrawerSection title="Setup & Methodology">
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                        <div>
                          <div style={labelStyle}>Setup</div>
                          <select value={review.setup_name} onChange={e => setReview({ ...review, setup_name: e.target.value })} style={selectStyle}>
                            <option value="">--</option>
                            {SETUP_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                          </select>
                        </div>
                        <div>
                          <div style={labelStyle}>Family / Philosophy</div>
                          <select value={review.setup_family} onChange={e => setReview({ ...review, setup_family: e.target.value })} style={selectStyle}>
                            <option value="">--</option>
                            {SETUP_FAMILY_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                          </select>
                        </div>
                        <div>
                          <div style={labelStyle}>Timeframe</div>
                          <select value={review.timeframe} onChange={e => setReview({ ...review, timeframe: e.target.value })} style={selectStyle}>
                            <option value="">--</option>
                            {TIMEFRAME_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                          </select>
                        </div>
                        <div>
                          <div style={labelStyle}>Direction</div>
                          <select value={review.direction} onChange={e => setReview({ ...review, direction: e.target.value })} style={selectStyle}>
                            <option value="">--</option>
                            {DIRECTION_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                          </select>
                        </div>
                        <div>
                          <div style={labelStyle}>Entry Type</div>
                          <select value={review.entry_type} onChange={e => setReview({ ...review, entry_type: e.target.value })} style={selectStyle}>
                            <option value="">--</option>
                            {ENTRY_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                          </select>
                        </div>
                        <div>
                          <div style={labelStyle}>Exit Type</div>
                          <select value={review.exit_type} onChange={e => setReview({ ...review, exit_type: e.target.value })} style={selectStyle}>
                            <option value="">--</option>
                            {EXIT_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                          </select>
                        </div>
                        <div>
                          <div style={labelStyle}>Market Regime</div>
                          <select value={review.market_regime} onChange={e => setReview({ ...review, market_regime: e.target.value })} style={selectStyle}>
                            <option value="">--</option>
                            {REGIME_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                          </select>
                        </div>
                        <div>
                          <div style={labelStyle}>Catalyst</div>
                          <select value={review.catalyst_type} onChange={e => setReview({ ...review, catalyst_type: e.target.value })} style={selectStyle}>
                            <option value="">--</option>
                            {CATALYST_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                          </select>
                        </div>
                      </div>
                    </DrawerSection>

                    <DrawerSection title="Execution & Risk">
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                        <BoolToggle label="Followed Plan" value={review.followed_plan} onChange={v => setReview({ ...review, followed_plan: v })} />
                        <BoolToggle label="Well Executed" value={review.well_executed} onChange={v => setReview({ ...review, well_executed: v })} />
                        <ScoreSelect label="Execution (1-5)" value={review.execution_quality_score} onChange={v => setReview({ ...review, execution_quality_score: v })} />
                        <ScoreSelect label="Sizing (1-5)" value={review.sizing_quality_score} onChange={v => setReview({ ...review, sizing_quality_score: v })} />
                        <ScoreSelect label="Risk Mgmt (1-5)" value={review.risk_management_score} onChange={v => setReview({ ...review, risk_management_score: v })} />
                      </div>
                    </DrawerSection>

                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <button onClick={handleSave} style={{
                        padding: '5px 16px', fontSize: 10, fontWeight: 600,
                        border: '1px solid var(--green)', borderRadius: 'var(--radius)',
                        background: 'var(--green-dim)', color: 'var(--green)',
                        cursor: 'pointer', fontFamily: 'var(--mono)',
                      }}>Save Review</button>
                      {saveStatus && <span style={{ fontSize: 10, color: saveStatus === 'Saved' ? 'var(--green)' : 'var(--text2)' }}>{saveStatus}</span>}
                    </div>
                  </div>
                )}
              </>
            )}

            {/* Tab: Psychology (editable) */}
            {drawerTab === 'psych' && (
              <>
                {reviewLoading ? (
                  <div style={{ color: 'var(--text3)', fontSize: 10, padding: 12 }}>Loading review...</div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <DrawerSection title="Emotions & State">
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                        <div>
                          <div style={labelStyle}>Before Trade</div>
                          <select value={review.emotion_before} onChange={e => setReview({ ...review, emotion_before: e.target.value })} style={selectStyle}>
                            <option value="">--</option>
                            {EMOTION_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                          </select>
                        </div>
                        <div>
                          <div style={labelStyle}>During Trade</div>
                          <select value={review.emotion_during} onChange={e => setReview({ ...review, emotion_during: e.target.value })} style={selectStyle}>
                            <option value="">--</option>
                            {EMOTION_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                          </select>
                        </div>
                        <ScoreSelect label="Confidence Before (1-5)" value={review.confidence_before} onChange={v => setReview({ ...review, confidence_before: v })} />
                        <ScoreSelect label="Stress Level (1-5)" value={review.stress_level} onChange={v => setReview({ ...review, stress_level: v })} />
                      </div>
                    </DrawerSection>

                    <DrawerSection title="Mistakes">
                      <TagSelect label="Tags" options={MISTAKE_OPTIONS} value={review.mistake_tags} onChange={v => setReview({ ...review, mistake_tags: v })} />
                    </DrawerSection>

                    <DrawerSection title="Reflection">
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                        <div>
                          <div style={labelStyle}>Lesson Learned</div>
                          <textarea value={review.lesson_learned} onChange={e => setReview({ ...review, lesson_learned: e.target.value })} placeholder="What did this trade teach you?" rows={2} style={textareaStyle} />
                        </div>
                        <div>
                          <div style={labelStyle}>Review Notes</div>
                          <textarea value={review.review_notes} onChange={e => setReview({ ...review, review_notes: e.target.value })} placeholder="Additional notes..." rows={3} style={textareaStyle} />
                        </div>
                      </div>
                    </DrawerSection>

                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <button onClick={handleSave} style={{
                        padding: '5px 16px', fontSize: 10, fontWeight: 600,
                        border: '1px solid var(--green)', borderRadius: 'var(--radius)',
                        background: 'var(--green-dim)', color: 'var(--green)',
                        cursor: 'pointer', fontFamily: 'var(--mono)',
                      }}>Save Review</button>
                      {saveStatus && <span style={{ fontSize: 10, color: saveStatus === 'Saved' ? 'var(--green)' : 'var(--text2)' }}>{saveStatus}</span>}
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </DetailDrawer>
    </>
  )
}

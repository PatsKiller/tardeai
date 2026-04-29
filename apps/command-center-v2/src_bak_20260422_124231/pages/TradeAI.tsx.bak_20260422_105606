import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import DetailDrawer, { DrawerStat, DrawerSection } from '../components/DetailDrawer'
import DataGrid from '../components/DataGrid'
import { BarChartJS } from '../components/charts'
import { useApi } from '../hooks/useApi'
import { deltaColor } from '../lib/format'

interface Ticker {
  symbol: string; score: number; grade: string; decision: string
  rvol: number; price: number; change_pct: string; gap_pct: string
  float_m: string; catalyst: string
}

interface RunHistoryItem {
  date: string; label: string; go: number; wait: number; total: number
  top_ticker: string; top_score: number
}

interface TradeAIData {
  run_date: string; run_label: string; vix: number | null; breadth: string
  go_count: number; wait_count: number; avoid_count: number; ticker_count: number
  top_ticker: string; top_score: number; delta_events: number
  tickers: Ticker[]; sectors: Record<string, number>; run_history: RunHistoryItem[]
}

const decisionColor: Record<string, string> = { GO: 'var(--green)', WAIT: 'var(--amber)', AVOID: 'var(--red)', 'NO GO': 'var(--red)' }
const decisionBg: Record<string, string> = { GO: 'var(--green-dim)', WAIT: 'var(--amber-dim)', AVOID: 'var(--red-dim)', 'NO GO': 'var(--red-dim)' }

export default function TradeAI() {
  const { data: tai } = useApi<TradeAIData>('/api/v2/trade-ai')
  const [filter, setFilter] = useState<string>('ALL')
  const [selectedTicker, setSelectedTicker] = useState<Ticker | null>(null)

  if (!tai) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading Trade AI data...</div>

  const tickers = filter === 'ALL' ? tai.tickers : tai.tickers.filter(t => t.decision === filter)
  const regimeEmoji = tai.breadth?.includes('Bull') ? '\u{1f7e2}' : tai.breadth?.includes('Bear') ? '\u{1f534}' : '\u{1f7e1}'

  const columns = [
    { key: 'decision', label: 'Signal', width: 55, render: (r: Ticker) => (
      <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 3, background: decisionBg[r.decision] || 'var(--bg3)', color: decisionColor[r.decision] || 'var(--text3)' }}>
        {r.decision}
      </span>
    )},
    { key: 'symbol', label: 'Symbol', width: 60, render: (r: Ticker) => <span style={{ fontWeight: 700, color: 'var(--text0)' }}>{r.symbol}</span> },
    { key: 'score', label: 'Score', width: 50, align: 'right' as const, sortKey: (r: Ticker) => r.score, render: (r: Ticker) => (
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, justifyContent: 'flex-end' }}>
        <div style={{ width: 30, height: 5, background: 'var(--bg3)', borderRadius: 2, overflow: 'hidden' }}>
          <div style={{ width: `${Math.min(r.score, 50) * 2}%`, height: '100%', background: r.score >= 40 ? 'var(--green)' : r.score >= 30 ? 'var(--amber)' : 'var(--text3)', borderRadius: 2 }} />
        </div>
        <span style={{ fontWeight: 600, color: r.score >= 40 ? 'var(--green)' : r.score >= 30 ? 'var(--amber)' : 'var(--text2)' }}>{r.score}</span>
      </div>
    )},
    { key: 'grade', label: 'Grd', width: 30, render: (r: Ticker) => <span style={{ fontWeight: 600, color: r.grade === 'A' ? 'var(--green)' : 'var(--text2)' }}>{r.grade}</span> },
    { key: 'rvol', label: 'RVOL', width: 45, align: 'right' as const, sortKey: (r: Ticker) => r.rvol, render: (r: Ticker) => (
      <span style={{ color: r.rvol >= 5 ? 'var(--green)' : 'var(--text2)' }}>{r.rvol.toFixed(1)}x</span>
    )},
    { key: 'price', label: 'Price', width: 55, align: 'right' as const, render: (r: Ticker) => '$' + r.price.toFixed(2) },
    { key: 'change_pct', label: 'Chg%', width: 55, align: 'right' as const, render: (r: Ticker) => (
      <span style={{ color: r.change_pct.startsWith('-') ? 'var(--red)' : 'var(--green)', fontWeight: 600 }}>{r.change_pct}%</span>
    )},
    { key: 'gap_pct', label: 'Gap%', width: 55, align: 'right' as const, render: (r: Ticker) => (
      <span style={{ color: r.gap_pct.startsWith('-') ? 'var(--red)' : 'var(--green)' }}>{r.gap_pct}%</span>
    )},
    { key: 'float_m', label: 'Float', width: 45, align: 'right' as const, render: (r: Ticker) => <span style={{ color: 'var(--text2)' }}>{r.float_m}M</span> },
    { key: 'catalyst', label: 'Catalyst', render: (r: Ticker) => (
      <span style={{ fontSize: 10, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block', maxWidth: 280 }}>{r.catalyst}</span>
    )},
  ]

  return (
    <>
      <PageHeader title="Trade AI" subtitle={`Run ${tai.run_label} | ${tai.run_date} | ${tai.ticker_count} tickers scanned`} />

      {/* Regime + VIX banner */}
      <div style={{
        display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14,
      }}>
        <MetricTile label="VIX" value={tai.vix?.toFixed(1) ?? '—'} deltaColor={tai.vix != null ? (tai.vix > 25 ? 'var(--red)' : tai.vix > 18 ? 'var(--amber)' : 'var(--green)') : undefined} />
        <MetricTile label="Regime" value={`${regimeEmoji} ${tai.breadth}`} />
        <MetricTile label="GO" value={String(tai.go_count)} deltaColor="var(--green)" />
        <MetricTile label="WAIT" value={String(tai.wait_count)} deltaColor="var(--amber)" />
        <MetricTile label="NO GO" value={String(tai.avoid_count)} deltaColor={tai.avoid_count > 0 ? 'var(--red)' : 'var(--text3)'} />
        <MetricTile label="Top Ticker" value={tai.top_ticker || '—'} delta={`Score: ${tai.top_score}`} />
        <MetricTile label="Deltas" value={String(tai.delta_events)} />
      </div>

      {/* Decision filter */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 10 }}>
        {['ALL', 'GO', 'WAIT'].map(f => (
          <button key={f} onClick={() => setFilter(f)} style={{
            padding: '4px 14px', fontSize: 10, fontWeight: 600,
            border: `1px solid ${filter === f ? (decisionColor[f] || 'var(--accent)') : 'var(--border)'}`,
            borderRadius: 'var(--radius)',
            background: filter === f ? (decisionBg[f] || 'var(--accent-dim)') : 'var(--bg-card)',
            color: filter === f ? (decisionColor[f] || 'var(--accent)') : 'var(--text2)',
            cursor: 'pointer', fontFamily: 'var(--mono)',
          }}>
            {f} {f !== 'ALL' ? `(${tai.tickers.filter(t => t.decision === f).length})` : `(${tai.tickers.length})`}
          </button>
        ))}
      </div>

      {/* Main ticker table */}
      <DataGrid columns={columns} data={tickers} rowKey={r => r.symbol} maxHeight={350}
        onRowClick={r => setSelectedTicker(r.symbol === selectedTicker?.symbol ? null : r)} selectedKey={selectedTicker?.symbol} />

      {/* Setup detail drawer — matches v1 openSetupModal */}
      <DetailDrawer open={!!selectedTicker} onClose={() => setSelectedTicker(null)}
        title={selectedTicker?.symbol || ''} subtitle={`${selectedTicker?.decision} | Score ${selectedTicker?.score} | Grade ${selectedTicker?.grade}`}>
        {selectedTicker && (
          <>
            <DrawerSection title="Setup">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                <DrawerStat label="Decision" value={selectedTicker.decision} color={decisionColor[selectedTicker.decision]} />
                <DrawerStat label="Score" value={String(selectedTicker.score)} color={selectedTicker.score >= 40 ? 'var(--green)' : selectedTicker.score >= 30 ? 'var(--amber)' : 'var(--text2)'} />
                <DrawerStat label="Grade" value={selectedTicker.grade} color={selectedTicker.grade === 'A' ? 'var(--green)' : 'var(--text2)'} />
                <DrawerStat label="RVOL" value={selectedTicker.rvol.toFixed(1) + 'x'} color={selectedTicker.rvol >= 5 ? 'var(--green)' : 'var(--text2)'} />
                <DrawerStat label="Price" value={'$' + selectedTicker.price.toFixed(2)} />
                <DrawerStat label="Change" value={selectedTicker.change_pct + '%'} color={selectedTicker.change_pct.startsWith('-') ? 'var(--red)' : 'var(--green)'} />
                <DrawerStat label="Gap" value={selectedTicker.gap_pct + '%'} color={selectedTicker.gap_pct.startsWith('-') ? 'var(--red)' : 'var(--green)'} />
                <DrawerStat label="Float" value={selectedTicker.float_m + 'M'} />
              </div>
            </DrawerSection>

            <DrawerSection title="Catalyst">
              <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5 }}>
                {selectedTicker.catalyst || 'No catalyst data available'}
              </div>
            </DrawerSection>

            <DrawerSection title="Links">
              <div style={{ display: 'flex', gap: 6 }}>
                <a href={`https://finviz.com/quote.ashx?t=${selectedTicker.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Finviz</a>
                <a href={`https://finance.yahoo.com/quote/${selectedTicker.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Yahoo</a>
                <a href={`https://www.tradingview.com/symbols/${selectedTicker.symbol}/`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Chart</a>
              </div>
            </DrawerSection>
          </>
        )}
      </DetailDrawer>

      {/* Run context + What Changed */}
      {tai.run_date && (
        <div style={{ display: 'flex', gap: 10, marginTop: 10, marginBottom: 4, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: 10, color: 'var(--text2)', padding: '3px 10px', background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius)' }}>
            Run {tai.run_label} | {tai.run_date}
          </span>
          {tai.delta_events > 0 && (
            <span style={{ fontSize: 10, color: 'var(--accent)', padding: '3px 10px', background: 'var(--accent-dim)', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', fontWeight: 600 }}>
              {tai.delta_events} score/decision change{tai.delta_events !== 1 ? 's' : ''} since prior run
            </span>
          )}
          {tai.delta_events === 0 && (
            <span style={{ fontSize: 10, color: 'var(--text3)', padding: '3px 10px', background: 'var(--bg3)', borderRadius: 'var(--radius)' }}>
              No score drift detected
            </span>
          )}
        </div>
      )}

      {/* Bottom panels */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>

        {/* Run history sparkline */}
        <div>
          <SectionHeader title="Run History" count={tai.run_history.length} />
          <Card>
            {tai.run_history.length > 1 ? (
              <BarChartJS
                labels={tai.run_history.map(r => r.label).reverse()}
                data={tai.run_history.map(r => r.go).reverse()}
                colors={tai.run_history.map(r => r.go > 0 ? '#0ecb81' : '#4e5a6e').reverse()}
                height={80}
              />
            ) : (
              <div style={{ color: 'var(--text3)', fontSize: 11 }}>Single run only</div>
            )}
            <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
              {tai.run_history.map((r, i) => (
                <div key={i} style={{ fontSize: 9, color: 'var(--text3)' }}>
                  <span style={{ fontWeight: 600 }}>{r.label}</span> GO:{r.go} W:{r.wait}
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* Sector matrix */}
        <div>
          <SectionHeader title="Sector Distribution" count={Object.keys(tai.sectors).length} />
          <Card>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {Object.entries(tai.sectors).map(([sec, count]) => (
                <div key={sec} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ width: 100, fontSize: 10, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sec}</span>
                  <div style={{ flex: 1, height: 8, background: 'var(--bg3)', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ width: `${(count / Math.max(...Object.values(tai.sectors))) * 100}%`, height: '100%', background: 'var(--accent)', opacity: 0.6, borderRadius: 3 }} />
                  </div>
                  <span style={{ width: 20, fontSize: 10, color: 'var(--text1)', textAlign: 'right', fontWeight: 600 }}>{count}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>

      {/* TOS copy section */}
      <SectionHeader title="TOS Export" />
      <Card compact>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['GO', 'WAIT', 'ALL'] as const).map(type => {
            const syms = type === 'ALL' ? tai.tickers.map(t => t.symbol) : tai.tickers.filter(t => t.decision === type).map(t => t.symbol)
            return (
              <button key={type} onClick={() => navigator.clipboard.writeText(syms.join(','))} style={{
                padding: '4px 12px', fontSize: 10, border: '1px solid var(--border)',
                borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)',
                cursor: 'pointer', fontFamily: 'var(--mono)',
              }}>
                Copy {type} ({syms.length})
              </button>
            )
          })}
        </div>
      </Card>
    </>
  )
}

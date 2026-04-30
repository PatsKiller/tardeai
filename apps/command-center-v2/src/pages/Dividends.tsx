import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import MetricTile from '../components/MetricTile'
import DataGrid from '../components/DataGrid'
import { BarChartJS, DoughnutChart } from '../components/charts'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'

interface Payer { symbol: string; shares: number; price: number; market_value: number; yield_pct: number; frequency: string; annual_income: number; monthly_amort: number; qualified: boolean; safety: string }
interface MonthlySummaryItem { month: number; month_name: string; total: number; symbols: string[]; count: number }
interface DivData { has_data: boolean; payers: Payer[]; total_annual: number; qualified_annual: number; ordinary_annual: number; monthly_average: number; monthly_summary: MonthlySummaryItem[] | Record<string, number>; ex_div_alerts: { symbol: string; ex_date: string; amount: string }[] }

/* ── Income target constants ─────────────────────────────────────────── */
const TARGET   = 55_000
const MINIMUM  = 37_500
const STRETCH  = 67_500
const BAR_MAX  = STRETCH * 1.1  // give a little headroom on the bar

export default function Dividends() {
  const { data: d } = useApi<DivData>('/api/v2/dividends')
  if (!d) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading dividends…</div>
  if (!d.has_data) return <><PageHeader title="Dividends" subtitle="Income architecture" /><Card><div style={{ color: 'var(--text3)', padding: 20 }}>No dividend data yet. Run the daily pipeline to compute income from current holdings.</div></Card></>

  const payers = [...d.payers].sort((a, b) => b.annual_income - a.annual_income)
  // Normalize monthly_summary — API may return array of objects or Record<string, number>
  const monthEntries: [string, number][] = (() => {
    const ms = d.monthly_summary
    if (!ms) return []
    if (Array.isArray(ms)) {
      return ms.map((item: MonthlySummaryItem) => [item.month_name || `M${item.month}`, Number(item.total) || 0] as [string, number])
    }
    return Object.entries(ms).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => [k, Number(v) || 0] as [string, number])
  })()

  /* ── Doughnut data: top 8 payers + "Other" ─────────────────────────── */
  const top8 = payers.slice(0, 8)
  const otherIncome = payers.slice(8).reduce((s, p) => s + p.annual_income, 0)
  const doughnutLabels = top8.map(p => p.symbol).concat(otherIncome > 0 ? ['Other'] : [])
  const doughnutData   = top8.map(p => p.annual_income).concat(otherIncome > 0 ? [otherIncome] : [])

  /* ── Progress bar helpers ──────────────────────────────────────────── */
  const pct = (v: number) => Math.min((v / BAR_MAX) * 100, 100)
  const earned = d.total_annual

  const columns = [
    { key: 'symbol', label: 'Symbol', width: 55, render: (r: Payer) => <strong>{r.symbol}</strong> },
    { key: 'yield_pct', label: 'Yield', width: 45, align: 'right' as const, render: (r: Payer) => <span style={{ color: 'var(--green)' }}>{r.yield_pct.toFixed(2)}%</span> },
    { key: 'annual_income', label: 'Annual', width: 62, align: 'right' as const, render: (r: Payer) => <span style={{ color: '#f2d35a', fontWeight: 700 }}>{fmt$(r.annual_income)}</span> },
    { key: 'monthly_amort', label: 'Monthly', width: 55, align: 'right' as const, render: (r: Payer) => fmt$(r.monthly_amort) },
    { key: 'frequency', label: 'Freq', width: 55, render: (r: Payer) => <span style={{ color: 'var(--text2)', fontSize: 10 }}>{r.frequency}</span> },
    { key: 'qualified', label: 'Tax', width: 40, render: (r: Payer) => <span style={{ fontSize: 9, color: r.qualified ? 'var(--green)' : 'var(--amber)' }} title={r.qualified ? 'Qualified: taxed at 0% LTCG rate at 12% bracket' : 'Ordinary: taxed as income (JEPI, PFLT, BND etc)'}>{r.qualified ? 'Qual' : 'Ord'}</span> },
    { key: 'safety', label: 'Safety', width: 50, render: (r: Payer) => <span style={{ color: r.safety === 'strong' ? 'var(--green)' : 'var(--amber)' }} title={r.safety === 'watch' ? 'High yield may signal sustainability concern — monitor payout ratio and earnings' : 'Dividend appears well-covered by earnings'}>{r.safety}</span> },
    { key: 'links', label: 'Links', width: 90, sortable: false, render: (r: Payer) => <div style={{ display: 'flex', gap: 5 }}><a href={`https://finance.yahoo.com/quote/${r.symbol}`} target="_blank" rel="noreferrer">Yahoo</a><a href={`https://finviz.com/quote.ashx?t=${r.symbol}`} target="_blank" rel="noreferrer">Finviz</a></div> },
  ]

  return (
    <>
      <PageHeader title={`Dividend Income — ${fmt$(d.total_annual)}/yr`} subtitle={`${payers.length} payers · Qualified: ${fmt$(d.qualified_annual)} (0% LTCG at 12% bracket) · Ordinary: ${fmt$(d.ordinary_annual)} (taxed as income)`} />

      {/* ── Income Progress Hero Card ──────────────────────────────────── */}
      <Card title="Annual Income Progress">
        <div style={{ padding: '4px 0 8px' }}>
          {/* headline metrics row */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
            <div>
              <span style={{ fontSize: 28, fontWeight: 800, color: 'var(--green)' }}>{fmt$(earned)}</span>
              <span style={{ color: 'var(--text3)', fontSize: 12, marginLeft: 8 }}>/ yr projected</span>
            </div>
            <div style={{ textAlign: 'right', lineHeight: 1.6, fontSize: 11, color: 'var(--text2)' }}>
              <div>Minimum <strong style={{ color: 'var(--amber)' }}>{fmt$(MINIMUM)}</strong></div>
              <div>Target <strong style={{ color: 'var(--green)' }}>{fmt$(TARGET)}</strong></div>
              <div>Stretch <strong style={{ color: '#a78bfa' }}>{fmt$(STRETCH)}</strong></div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>Gap: {fmt$(TARGET - earned)} · Close by adding SCHD/JEPI in Roll IRA ($16K cash)</div>
            </div>
          </div>

          {/* progress bar */}
          <div style={{ position: 'relative', height: 28, background: 'var(--bg3)', borderRadius: 6, overflow: 'visible' }}>
            {/* filled portion */}
            <div style={{
              position: 'absolute', left: 0, top: 0, bottom: 0,
              width: `${pct(earned)}%`,
              background: 'linear-gradient(90deg, #0ecb81 0%, #4a90f4 100%)',
              borderRadius: 6,
              transition: 'width 0.6s ease',
            }} />

            {/* marker: minimum */}
            <div style={{ position: 'absolute', left: `${pct(MINIMUM)}%`, top: -2, bottom: -2, width: 2, background: 'var(--amber)', zIndex: 2 }}>
              <div style={{ position: 'absolute', top: -16, left: '50%', transform: 'translateX(-50%)', fontSize: 9, color: 'var(--amber)', whiteSpace: 'nowrap' }}>Min</div>
            </div>

            {/* marker: target */}
            <div style={{ position: 'absolute', left: `${pct(TARGET)}%`, top: -2, bottom: -2, width: 2, background: 'var(--green)', zIndex: 2 }}>
              <div style={{ position: 'absolute', top: -16, left: '50%', transform: 'translateX(-50%)', fontSize: 9, color: 'var(--green)', whiteSpace: 'nowrap' }}>Target</div>
            </div>

            {/* marker: stretch */}
            <div style={{ position: 'absolute', left: `${pct(STRETCH)}%`, top: -2, bottom: -2, width: 2, background: '#a78bfa', zIndex: 2 }}>
              <div style={{ position: 'absolute', top: -16, left: '50%', transform: 'translateX(-50%)', fontSize: 9, color: '#a78bfa', whiteSpace: 'nowrap' }}>Stretch</div>
            </div>

            {/* current value label on the bar */}
            <div style={{
              position: 'absolute',
              left: `${pct(earned)}%`,
              top: '50%', transform: 'translate(-50%, -50%)',
              fontSize: 11, fontWeight: 700, color: '#fff',
              textShadow: '0 1px 3px rgba(0,0,0,0.6)',
              whiteSpace: 'nowrap',
              zIndex: 3,
            }}>
              {fmt$(earned)}
            </div>
          </div>

          {/* percentage toward target */}
          <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text3)', textAlign: 'right' }}>
            {((earned / TARGET) * 100).toFixed(1)}% of target
            {earned < MINIMUM && <span style={{ color: 'var(--red)', marginLeft: 12 }}>{fmt$(MINIMUM - earned)} to minimum</span>}
            {earned >= MINIMUM && earned < TARGET && <span style={{ color: 'var(--amber)', marginLeft: 12 }}>{fmt$(TARGET - earned)} to target</span>}
            {earned >= TARGET && earned < STRETCH && <span style={{ color: '#a78bfa', marginLeft: 12 }}>{fmt$(STRETCH - earned)} to stretch</span>}
            {earned >= STRETCH && <span style={{ color: 'var(--green)', marginLeft: 12 }}>Stretch goal achieved!</span>}
          </div>
        </div>
      </Card>

      {/* ── Metric tiles ──────────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8, marginBottom: 12, marginTop: 12 }}>
        <MetricTile label="Annual Income" value={fmt$(d.total_annual)} deltaColor="var(--green)" />
        <MetricTile label="Monthly Avg" value={fmt$(d.monthly_average)} />
        <MetricTile label="Qualified" value={fmt$(d.qualified_annual)} />
        <MetricTile label="Payers" value={String(payers.length)} />
      </div>

      {/* ── Charts row: bar charts + doughnut ─────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 12 }}>
        <Card title="Annual Income by Position">
          <div style={{ height: 260 }}><BarChartJS labels={payers.slice(0, 10).map(p => p.symbol)} data={payers.slice(0, 10).map(p => p.annual_income)} colors={payers.slice(0, 10).map(() => '#f2d35a')} height={240} /></div>
        </Card>
        <Card title="Yield by Position">
          <div style={{ height: 260 }}><BarChartJS labels={payers.slice(0, 10).map(p => p.symbol)} data={payers.slice(0, 10).map(p => p.yield_pct)} colors={payers.slice(0, 10).map(() => '#68b6cf')} height={240} /></div>
        </Card>
        <Card title="Top Dividend Payers">
          <div style={{ display: 'flex', gap: 12, height: 260, alignItems: 'center' }}>
            <div style={{ flex: '0 0 150px', height: 150 }}>
              <DoughnutChart labels={doughnutLabels} data={doughnutData} height={150} />
            </div>
            <div style={{ flex: 1, overflow: 'auto', maxHeight: 250 }}>
              {doughnutLabels.map((label, i) => (
                <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 0', fontSize: 11 }}>
                  <div style={{
                    width: 8, height: 8, borderRadius: 2, flexShrink: 0,
                    background: ['#4a90f4', '#0ecb81', '#f6465d', '#f0b90b', '#a78bfa', '#38bdf8', '#fb923c', '#6ee7b7', '#f472b6', '#94a3b8'][i] || '#94a3b8',
                  }} />
                  <span style={{ color: 'var(--text1)', fontWeight: 600, minWidth: 36 }}>{label}</span>
                  <span style={{ color: 'var(--text3)', marginLeft: 'auto' }}>{fmt$(doughnutData[i])}</span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>

      {/* ── Data grid + sidebar cards ─────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.35fr 0.9fr', gap: 12 }}>
        <div>
          <DataGrid columns={columns} data={payers} rowKey={r => `${r.symbol}-${r.market_value}`} maxHeight={360} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Card title="Ex-div / pay-date monitor">
            {d.ex_div_alerts?.length ? d.ex_div_alerts.map((a, idx) => <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 11 }}><span style={{ fontWeight: 700 }}>{a.symbol}</span><span style={{ color: 'var(--text2)' }}>{a.ex_date}</span><span style={{ color: 'var(--green)' }}>{a.amount}</span></div>) : <div style={{ color: 'var(--text3)', fontSize: 11 }}>No upcoming ex-dividend dates in scope.</div>}
          </Card>
          <Card title="Monthly income pattern">
            <div style={{ display: 'grid', gap: 4 }}>
              {(() => { const maxVal = Math.max(...monthEntries.map(([, v]) => v), 1); return monthEntries.map(([month, amount]) => <div key={month} style={{ display: 'flex', alignItems: 'center', gap: 8 }}><span style={{ width: 40, color: 'var(--text3)', fontSize: 10 }}>{month}</span><div style={{ flex: 1, height: 8, background: 'var(--bg3)', borderRadius: 999, overflow: 'hidden' }}><div style={{ width: `${(amount / maxVal) * 100}%`, height: '100%', background: '#f2d35a' }} /></div><span style={{ width: 64, textAlign: 'right', color: 'var(--text0)' }}>{fmt$(amount)}</span></div>) })()}
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}

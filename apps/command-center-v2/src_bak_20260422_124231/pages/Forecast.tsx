import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import DataGrid from '../components/DataGrid'
import { BarChartJS } from '../components/charts'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtPct } from '../lib/format'

interface Projection { label: string; total_return_pct: number; years: Record<string, { projected_value: number; growth: number; cumulative_dividends: number; total_return_pct: number }> }
interface Payer { symbol: string; yield_pct: number; annual_income: number; frequency: string }
interface Account { account: string; current_value: number; pct_of_total: number }
interface ForecastData {
  portfolio_value: number; annual_dividend_income: number; portfolio_yield_pct: number; monthly_dividend_avg: number
  projections: Record<string, Projection>; accounts: Account[]; top_dividend_payers: Payer[]
  assumptions: { basis: string; market_scenarios: string; dividend_basis: string; limitations: string }
  retirement_age: number | null
}

const ACCT_LABEL: Record<string, string> = { fidelity_401k: 'Fidelity 401k', schwab_rollover_ira: 'Rollover IRA', schwab_roth: 'Roth IRA', schwab_taxable: 'Taxable' }

export default function Forecast() {
  const { data: f } = useApi<ForecastData>('/api/v2/forecast')
  if (!f) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading...</div>

  const scenarios = Object.entries(f.projections)
  const years = ['1Y', '2Y', '3Y', '5Y']

  return (
    <>
      <PageHeader title="Portfolio Forecast" subtitle={`Age ${f.retirement_age?.toFixed(1) || '—'} | Yield ${f.portfolio_yield_pct}%`} />

      {/* Current income */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <MetricTile label="Portfolio Value" value={fmt$(f.portfolio_value)} />
        <MetricTile label="Annual Dividends" value={fmt$(f.annual_dividend_income)} deltaColor="var(--green)" />
        <MetricTile label="Monthly Avg" value={fmt$(f.monthly_dividend_avg)} deltaColor="var(--green)" />
        <MetricTile label="Portfolio Yield" value={`${f.portfolio_yield_pct}%`} />
      </div>

      {/* Projection scenarios */}
      <SectionHeader title="Growth Projections" count={scenarios.length} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10, marginBottom: 14 }}>
        {scenarios.map(([key, sc]) => (
          <Card key={key} title={sc.label} subtitle={`${sc.total_return_pct}% total return/yr`}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {years.map(yr => {
                const p = sc.years[yr]
                if (!p) return null
                return (
                  <div key={yr} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 11 }}>
                    <span style={{ fontWeight: 600, color: 'var(--text2)', width: 24 }}>{yr}</span>
                    <span style={{ color: 'var(--green)', fontWeight: 600 }}>{fmt$(p.projected_value)}</span>
                    <span style={{ color: 'var(--text2)', fontSize: 10 }}>{fmtPct(p.total_return_pct, 1)}</span>
                  </div>
                )
              })}
            </div>
          </Card>
        ))}
      </div>

      {/* 5-year projection chart */}
      <SectionHeader title="5-Year Projection" />
      <Card compact>
        <div style={{ height: 140 }}>
          <BarChartJS
            labels={scenarios.map(([, sc]) => sc.label.split(' (')[0])}
            data={scenarios.map(([, sc]) => sc.years['5Y']?.projected_value || 0)}
            colors={['#4a90f4', '#0ecb81', '#f0b90b']}
          />
        </div>
      </Card>

      {/* Account breakdown */}
      <SectionHeader title="By Account" count={f.accounts.length} />
      <Card compact>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {f.accounts.map(a => (
            <div key={a.account} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border-subtle)' }}>
              <span style={{ width: 100, fontSize: 11, fontWeight: 600, color: 'var(--text1)' }}>{ACCT_LABEL[a.account] || a.account}</span>
              <div style={{ flex: 1, height: 8, background: 'var(--bg3)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${a.pct_of_total}%`, height: '100%', background: 'var(--accent)', opacity: 0.6, borderRadius: 3 }} />
              </div>
              <span style={{ width: 80, textAlign: 'right', fontSize: 11, color: 'var(--text0)', fontWeight: 600 }}>{fmt$(a.current_value)}</span>
              <span style={{ width: 35, textAlign: 'right', fontSize: 9, color: 'var(--text3)' }}>{a.pct_of_total}%</span>
            </div>
          ))}
        </div>
      </Card>

      {/* Top dividend payers */}
      <SectionHeader title="Top Dividend Payers" count={f.top_dividend_payers.length} />
      <DataGrid
        columns={[
          { key: 'symbol', label: 'Symbol', width: 55, render: (r: Payer) => <span style={{ fontWeight: 700 }}>{r.symbol}</span> },
          { key: 'yield_pct', label: 'Yield', width: 45, align: 'right' as const, sortKey: (r: Payer) => r.yield_pct, render: (r: Payer) => <span style={{ color: 'var(--green)' }}>{r.yield_pct.toFixed(2)}%</span> },
          { key: 'annual_income', label: 'Annual', width: 65, align: 'right' as const, sortKey: (r: Payer) => r.annual_income, render: (r: Payer) => fmt$(r.annual_income) },
          { key: 'frequency', label: 'Freq', width: 60, render: (r: Payer) => <span style={{ fontSize: 9, color: 'var(--text2)' }}>{r.frequency}</span> },
        ]}
        data={f.top_dividend_payers}
        rowKey={r => r.symbol}
        maxHeight={250}
      />

      {/* Assumptions */}
      <SectionHeader title="Assumptions & Limitations" />
      <Card compact>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 10, color: 'var(--text2)' }}>
          <div><strong style={{ color: 'var(--text1)' }}>Basis:</strong> {f.assumptions.basis}</div>
          <div><strong style={{ color: 'var(--text1)' }}>Market scenarios:</strong> {f.assumptions.market_scenarios}</div>
          <div><strong style={{ color: 'var(--text1)' }}>Dividend basis:</strong> {f.assumptions.dividend_basis}</div>
          <div style={{ color: 'var(--amber)' }}><strong>Limitations:</strong> {f.assumptions.limitations}</div>
        </div>
      </Card>
    </>
  )
}

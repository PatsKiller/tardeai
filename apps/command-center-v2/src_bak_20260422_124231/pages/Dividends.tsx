import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import DataGrid from '../components/DataGrid'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'

interface Payer { symbol: string; shares: number; price: number; market_value: number; yield_pct: number; frequency: string; annual_income: number; monthly_amort: number; qualified: boolean; safety: string }
interface DivData { has_data: boolean; payers: Payer[]; total_annual: number; qualified_annual: number; ordinary_annual: number; monthly_average: number; monthly_summary: Record<string, number>; ex_div_alerts: unknown[] }

export default function Dividends() {
  const { data: d } = useApi<DivData>('/api/v2/dividends')
  if (!d) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading...</div>
  if (!d.has_data) return <><PageHeader title="Dividends" /><Card><div style={{ color: 'var(--text3)', padding: 20 }}>No dividend data available</div></Card></>

  const columns = [
    { key: 'symbol', label: 'Symbol', width: 55, render: (r: Payer) => <span style={{ fontWeight: 700 }}>{r.symbol}</span> },
    { key: 'yield_pct', label: 'Yield', width: 45, align: 'right' as const, sortKey: (r: Payer) => r.yield_pct, render: (r: Payer) => <span style={{ color: 'var(--green)' }}>{r.yield_pct.toFixed(2)}%</span> },
    { key: 'annual_income', label: 'Annual', width: 65, align: 'right' as const, sortKey: (r: Payer) => r.annual_income, render: (r: Payer) => fmt$(r.annual_income) },
    { key: 'monthly_amort', label: 'Monthly', width: 55, align: 'right' as const, render: (r: Payer) => fmt$(r.monthly_amort) },
    { key: 'frequency', label: 'Freq', width: 55, render: (r: Payer) => <span style={{ fontSize: 9, color: 'var(--text2)' }}>{r.frequency}</span> },
    { key: 'market_value', label: 'Value', width: 65, align: 'right' as const, render: (r: Payer) => fmt$(r.market_value) },
    { key: 'shares', label: 'Shares', width: 50, align: 'right' as const, render: (r: Payer) => r.shares.toFixed(1) },
    { key: 'qualified', label: 'Qual', width: 35, render: (r: Payer) => <span style={{ color: r.qualified ? 'var(--green)' : 'var(--text3)', fontSize: 9 }}>{r.qualified ? 'Yes' : 'No'}</span> },
    { key: 'safety', label: 'Safety', width: 50, render: (r: Payer) => <span style={{ fontSize: 9, color: r.safety === 'strong' ? 'var(--green)' : 'var(--amber)' }}>{r.safety}</span> },
  ]

  const monthEntries = Object.entries(d.monthly_summary || {}).sort(([a], [b]) => a.localeCompare(b))

  return (
    <>
      <PageHeader title="Dividends" subtitle={`${d.payers.length} dividend payers`} />
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <MetricTile label="Annual Income" value={fmt$(d.total_annual)} deltaColor="var(--green)" />
        <MetricTile label="Monthly Avg" value={fmt$(d.monthly_average)} />
        <MetricTile label="Qualified" value={fmt$(d.qualified_annual)} deltaColor="var(--green)" />
        <MetricTile label="Ordinary" value={fmt$(d.ordinary_annual)} />
        <MetricTile label="Payers" value={String(d.payers.length)} />
      </div>

      <SectionHeader title="Dividend Payers" count={d.payers.length} />
      <DataGrid columns={columns} data={d.payers} rowKey={r => r.symbol} maxHeight={350} />

      {monthEntries.length > 0 && (
        <>
          <SectionHeader title="Monthly Calendar" />
          <Card compact>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 6 }}>
              {monthEntries.map(([month, amount]) => (
                <div key={month} style={{ padding: '6px 8px', background: 'var(--bg3)', borderRadius: 'var(--radius)', textAlign: 'center' }}>
                  <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase' }}>{month}</div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--green)' }}>{fmt$(amount as number)}</div>
                </div>
              ))}
            </div>
          </Card>
        </>
      )}

      {Array.isArray(d.ex_div_alerts) && d.ex_div_alerts.length > 0 && (
        <>
          <SectionHeader title="Upcoming Ex-Dividend" count={d.ex_div_alerts.length} />
          <Card compact>
            {(d.ex_div_alerts as Array<Record<string, string>>).map((a, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, padding: '3px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 11 }}>
                <span style={{ fontWeight: 600, width: 50 }}>{a.symbol}</span>
                <span style={{ color: 'var(--text2)' }}>{a.ex_date}</span>
                <span style={{ color: 'var(--green)' }}>{a.amount}</span>
              </div>
            ))}
          </Card>
        </>
      )}
    </>
  )
}

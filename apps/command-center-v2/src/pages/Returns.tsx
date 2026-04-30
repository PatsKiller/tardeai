import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import MetricTile from '../components/MetricTile'
import SectionHeader from '../components/SectionHeader'
import { BarChartJS, LineChart } from '../components/charts'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtPct, deltaColor } from '../lib/format'

interface PerfData {
  current_value: number
  periods: Record<string, { change_pct: number; change: number; start_value: number; start_date: string; source?: string; estimated?: boolean }>
  accounts: Record<string, { current_value: number; periods: Record<string, { change_pct: number; change: number }> }>
  warning?: string | null
}
interface HoldingsData { equity_curve: { date: string; value: number }[] }

const PERIODS = ['1D', '1W', '1M', '3M', '6M', 'YTD', '1Y']
const ACCT = { fidelity_401k: 'Fidelity 401k', schwab_rollover_ira: 'Rollover IRA', schwab_roth: 'Roth IRA', schwab_taxable: 'Taxable' } as Record<string, string>

export default function Returns() {
  const { data: perf } = useApi<PerfData>('/api/v2/portfolio/performance')
  const { data: holdings } = useApi<HoldingsData>('/api/v2/portfolio/holdings')
  const [acctFilter, setAcctFilter] = useState('portfolio')

  if (!perf) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading returns…</div>
  const periodData = perf.periods || {}
  const activePeriods = PERIODS.filter(k => periodData[k])
  const accountEntries = Object.entries(perf.accounts || {})
  const activeAcct = acctFilter === 'portfolio' ? null : perf.accounts?.[acctFilter]
  const cardsSource = activeAcct?.periods ?? periodData

  return (
    <>
      <PageHeader title="Performance & Returns" subtitle={`Portfolio ${fmt$(perf.current_value)}`} />
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
        <FilterChip active={acctFilter === 'portfolio'} onClick={() => setAcctFilter('portfolio')} label="Portfolio" />
        {accountEntries.map(([k]) => <FilterChip key={k} active={acctFilter === k} onClick={() => setAcctFilter(k)} label={ACCT[k] || k} />)}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, minmax(0, 1fr))', gap: 8, marginBottom: 12 }}>
        {activePeriods.map(period => {
          const data = cardsSource[period]
          if (!data) return <MetricTile key={period} label={period} value="—" delta="Insufficient snapshot history" tooltip={`${period} returns require ${period === '6M' ? '180' : '365'}+ days of daily pipeline runs to compute.`} />
          return <MetricTile key={period} label={period} value={fmtPct(data.change_pct ?? 0)} delta={`${fmt$(data.change ?? 0)} · from ${periodData[period]?.start_date || '—'}`} deltaColor={deltaColor(data.change_pct)} />
        })}
      </div>

      {perf.warning && <div style={{ marginBottom: 12, padding: '8px 12px', background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 10, fontSize: 10, color: 'var(--amber)' }}>{perf.warning}</div>}
      {accountEntries.some(([k, r]) => k.includes('roth') && r.periods?.['YTD']?.change_pct > 500) && (
        <div style={{ marginBottom: 12, padding: '8px 12px', background: 'var(--accent-dim)', border: '1px solid var(--accent)', borderRadius: 10, fontSize: 10, color: 'var(--accent)' }}>
          ℹ️ Roth IRA YTD return distorted by Roth conversion — reflects cost basis of converted shares, not actual market return.
        </div>
      )}

      <Card title="Period Returns" subtitle="portfolio vs prior periods">
        <div style={{ height: 260 }}>
          <BarChartJS labels={activePeriods} data={activePeriods.map(k => periodData[k]?.change_pct ?? 0)} height={240} />
        </div>
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: 12, marginTop: 12 }}>
        <Card title="Equity Curve" subtitle="latest 30 snapshot points">
          {holdings?.equity_curve?.length ? (
            <div style={{ height: 240 }}>
              <LineChart labels={holdings.equity_curve.map(x => x.date.slice(5))} data={holdings.equity_curve.map(x => x.value)} height={220} />
            </div>
          ) : <div style={{ color: 'var(--text3)', fontSize: 11 }}>No equity curve available</div>}
        </Card>
        <Card title="Account Context" subtitle="by account">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {accountEntries.map(([key, row]) => (
              <div key={key} style={{ padding: '6px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <span style={{ color: 'var(--text1)', fontWeight: 600 }}>{ACCT[key] || key}</span>
                  <span style={{ color: 'var(--text0)' }}>{fmt$(row.current_value)}</span>
                </div>
                <div style={{ display: 'flex', gap: 10, marginTop: 3, fontSize: 10 }}>
                  {['1D', '1W', '1M', 'YTD'].map(p => row.periods?.[p] ? <span key={p} style={{ color: deltaColor(row.periods[p].change_pct) }}>{p} {fmtPct(row.periods[p].change_pct)}</span> : null)}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <SectionHeader title="Reconstructed Return Notes" />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <Card>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {activePeriods.map(period => (
              <div key={period} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ width: 30, color: 'var(--text2)' }}>{period}</span>
                <div style={{ flex: 1, height: 8, background: 'var(--bg3)', borderRadius: 999, overflow: 'hidden' }}>
                  <div style={{ width: `${Math.min(Math.abs((periodData[period]?.change_pct ?? 0) * 25), 100)}%`, height: '100%', background: deltaColor(periodData[period]?.change_pct), borderRadius: 999 }} />
                </div>
                <span style={{ width: 60, textAlign: 'right', color: deltaColor(periodData[period]?.change_pct) }}>{fmtPct(periodData[period]?.change_pct ?? 0)}</span>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Attribution Context">
          <div style={{ color: 'var(--text2)', fontSize: 11, lineHeight: 1.6 }}>Compare return windows across accounts. Check Attribution for position-level drivers.</div>
          <div style={{ marginTop: 10, display: 'grid', gap: 5 }}>
            {accountEntries.map(([key, row]) => (
              <div key={key} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, borderBottom: '1px solid var(--border-subtle)', paddingBottom: 4 }}>
                <span style={{ color: 'var(--text3)' }}>{ACCT[key] || key}</span>
                <span style={{ color: deltaColor(row.periods?.['1D']?.change ?? 0) }}>{fmt$(row.current_value)} · {fmt$(row.periods?.['1D']?.change ?? 0)}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  )
}

function FilterChip({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return <button onClick={onClick} style={{ padding: '6px 10px', borderRadius: 999, border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`, background: active ? 'var(--accent-dim)' : 'var(--bg2)', color: active ? 'var(--accent-bright)' : 'var(--text2)', cursor: 'pointer', fontSize: 10 }}>{label}</button>
}

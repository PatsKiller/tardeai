import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import { fmt$ } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Holdings', 'Returns', 'Dividends', 'Tax'] as const
const COLORS = ['#60a5fa', '#22c55e', '#f59e0b', '#a855f7', '#ef4444', '#06b6d4', '#e879f9', '#fb923c']

const ACCT_COLORS = ['#60a5fa', '#22c55e', '#f59e0b', '#a855f7', '#ef4444', '#06b6d4', '#e879f9']

export default function PortfolioHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Holdings')
  const [acctFilter, setAcctFilter] = useState<string | null>(null)
  const { data: overview } = useApi<any>('/api/v2/overview', 60_000)
  const { data: holdings } = useApi<any>('/api/v2/portfolio/holdings', 60_000)
  const { data: divs } = useApi<any>('/api/v2/dividends', 120_000)
  const { data: taxLots } = useApi<any>('/api/v2/tax-lots', 120_000)
  const { data: perfData } = useApi<any>('/api/v2/portfolio/performance', 120_000)

  const sectors = overview?.sectors ?? []
  const allHoldings = holdings?.holdings ?? []
  const payers = divs?.payers ?? []

  // ── Account filter: chips derived from holdings, with per-account counts + value ──
  const acctMap: Record<string, { n: number; value: number }> = {}
  for (const h of allHoldings) {
    const a = h.account ?? 'unknown'
    acctMap[a] ??= { n: 0, value: 0 }
    acctMap[a].n++; acctMap[a].value += (h.market_value ?? 0)
  }
  const accounts = Object.entries(acctMap).sort((a, b) => b[1].value - a[1].value)
  const acctColor = (a: string) => ACCT_COLORS[Math.max(0, accounts.findIndex(([k]) => k === a)) % ACCT_COLORS.length]
  const holdingsList = acctFilter ? allHoldings.filter((h: any) => (h.account ?? 'unknown') === acctFilter) : allHoldings

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Portfolio</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{holdingsList.length} holdings · {fmt$(overview?.portfolio_value ?? 0, 0)}</div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
            }}>{t}</button>
          ))}
        </div>
      </div>

      {tab === 'Holdings' && accounts.length > 1 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12, alignItems: 'center' }}>
          <button onClick={() => setAcctFilter(null)} style={{
            padding: '3px 10px', fontSize: 10, borderRadius: 12, cursor: 'pointer',
            border: `1px solid ${acctFilter === null ? '#60a5fa' : 'var(--border)'}`,
            background: acctFilter === null ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
            color: acctFilter === null ? '#60a5fa' : 'var(--text3)', fontWeight: acctFilter === null ? 700 : 400,
          }}>All ({allHoldings.length})</button>
          {accounts.map(([a, info]) => (
            <button key={a} onClick={() => setAcctFilter(a === acctFilter ? null : a)} style={{
              padding: '3px 10px', fontSize: 10, borderRadius: 12, cursor: 'pointer',
              border: `1px solid ${acctFilter === a ? acctColor(a) : 'var(--border)'}`,
              background: acctFilter === a ? `${acctColor(a)}22` : 'var(--bg2)',
              color: acctFilter === a ? acctColor(a) : 'var(--text3)', fontWeight: acctFilter === a ? 700 : 400,
            }}>
              <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: acctColor(a), marginRight: 5 }} />
              {a} ({info.n})
            </button>
          ))}
        </div>
      )}

      {tab === 'Holdings' && (
        <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 16 }}>
          {/* Allocation donut */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Allocation</div>
            {sectors.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No sector data</div> : (
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={sectors} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} stroke="var(--bg0)" strokeWidth={2}>
                    {sectors.map((_: any, i: number) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} formatter={(v: number) => [fmt$(v, 0), 'Value']} />
                </PieChart>
              </ResponsiveContainer>
            )}
            {sectors.map((s: any, i: number) => (
              <div key={s.name} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '2px 0' }}>
                <span style={{ color: COLORS[i % COLORS.length] }}>{s.name}</span>
                <span style={{ color: 'var(--text2)' }}>{fmt$(s.value, 0)}</span>
              </div>
            ))}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/overview → sectors</div>
          </div>

          {/* Holdings table */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, maxHeight: 500, overflowY: 'auto' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Holdings ({holdingsList.length})</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr 1fr 1fr', fontSize: 9, color: 'var(--text3)', padding: '4px 6px', borderBottom: '1px solid var(--border)' }}>
              <span>Symbol</span><span>Value</span><span>Shares</span><span>Day Chg</span><span>% Port</span>
            </div>
            {holdingsList.map((h: any) => (
              <div key={`${h.symbol}-${h.account}`}
                onClick={() => onDrill({ title: h.symbol, subtitle: `${h.account} · ${h.name}`, endpoint: '/api/v2/portfolio/holdings', rows: [h] })}
                style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr 1fr 1fr 1fr', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
                <div>
                  <div style={{ fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{h.symbol}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)' }}>{h.account}</div>
                </div>
                <span style={{ color: 'var(--text0)' }}>{fmt$(h.market_value, 0)}</span>
                <span style={{ color: 'var(--text2)' }}>{h.shares}</span>
                <span style={{ color: (h.day_change_pct ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>
                  {h.day_change_pct != null ? `${h.day_change_pct >= 0 ? '+' : ''}${h.day_change_pct.toFixed(1)}%` : '—'}
                </span>
                <span style={{ color: 'var(--text2)' }}>{h.portfolio_pct != null ? `${h.portfolio_pct.toFixed(1)}%` : '—'}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'Dividends' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Dividend Income</div>
          {divs ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 16 }}>
                <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 10, textAlign: 'center' }}>
                  <div style={{ fontSize: 18, fontWeight: 700, color: '#22c55e' }}>{fmt$(divs.total_annual ?? 0, 0)}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>Annual</div>
                </div>
                <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 10, textAlign: 'center' }}>
                  <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)' }}>{fmt$(divs.monthly_average ?? 0, 0)}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>Monthly Avg</div>
                </div>
                <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 10, textAlign: 'center' }}>
                  <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)' }}>{payers.length}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>Payers</div>
                </div>
              </div>
              <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/dividends</div>
            </>
          ) : <div style={{ color: 'var(--text3)', fontSize: 11 }}>Loading dividend data...</div>}
        </div>
      )}

      {tab === 'Returns' && perfData && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Portfolio Performance</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)', marginBottom: 12 }}>{fmt$(perfData.current_value ?? 0, 0)}</div>
          {perfData.periods && Object.entries(perfData.periods).map(([period, data]: [string, any]) => (
            <div key={period} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 6px', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
              <span style={{ color: 'var(--text2)' }}>{period}</span>
              <span style={{ color: (data?.change_pct ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>
                {data?.change_pct != null ? `${data.change_pct >= 0 ? '+' : ''}${data.change_pct.toFixed(2)}%` : '—'}
              </span>
              <span style={{ color: 'var(--text2)' }}>{data?.change != null ? fmt$(data.change, 0) : '—'}</span>
            </div>
          ))}
          {perfData.warning && <div style={{ fontSize: 9, color: '#f59e0b', marginTop: 8 }}>{perfData.warning}</div>}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/portfolio/performance</div>
        </div>
      )}
      {tab === 'Returns' && !perfData && <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20 }}>Loading performance data...</div>}
      {tab === 'Tax' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Tax Lots ({taxLots?.count ?? 0})</div>
          {taxLots?.harvest_candidates?.length > 0 && (
            <div style={{ marginBottom: 12, padding: '6px 10px', background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.15)', borderRadius: 6, fontSize: 11, color: '#f59e0b' }}>
              {taxLots.harvest_candidates.length} harvest candidates
            </div>
          )}
          <div style={{ fontSize: 9, color: 'var(--text3)' }}>{taxLots?.data_note ?? 'Source: /api/v2/tax-lots'}</div>
        </div>
      )}
    </div>
  )
}

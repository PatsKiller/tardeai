import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Overview', 'Accounts', 'Timeline'] as const

export default function RetirementHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Overview')
  const { data: ret } = useApi<any>('/api/v2/retirement', 300_000)

  if (!ret) return <div style={{ padding: 24, color: 'var(--text3)' }}>Loading retirement data...</div>

  const accounts = ret.accounts ?? []
  const timeline = ret.timeline ?? []
  const golden = ret.golden_window ?? {}
  const divIncome = ret.dividend_income ?? {}

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Retirement</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Age {ret.current_age ?? '—'} · {accounts.length} accounts · as of {ret.as_of ?? '—'}</div>
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

      {tab === 'Overview' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {/* Golden Window */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#f59e0b', marginBottom: 10 }}>Golden Window (Roth Strategy)</div>
            {golden.start_year && (
              <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.6 }}>
                <div>Window: {golden.start_year} — {golden.end_year}</div>
                <div>Annual conversion target: {fmt$(golden.annual_conversion ?? 0, 0)}</div>
                <div>Tax bracket ceiling: {golden.bracket_ceiling ?? '—'}</div>
              </div>
            )}
            <div onClick={() => onDrill({ title: 'Golden Window', subtitle: 'Roth conversion strategy', endpoint: '/api/v2/retirement', rows: [golden] })}
              style={{ marginTop: 8, fontSize: 9, color: '#60a5fa', cursor: 'pointer' }}>drill for details</div>
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/retirement → golden_window</div>
          </div>

          {/* Dividend Income */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#22c55e', marginBottom: 10 }}>Dividend Income</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#22c55e' }}>{fmt$(divIncome.annual_total ?? 0, 0)}/yr</div>
            <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 4 }}>{fmt$(divIncome.monthly_avg ?? 0, 0)}/mo average</div>
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/retirement → dividend_income</div>
          </div>

          {/* Key dates */}
          {ret.key_dates && (
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, gridColumn: '1 / -1' }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Key Dates</div>
              {Object.entries(ret.key_dates).map(([k, v]: [string, any]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 6px', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
                  <span style={{ color: 'var(--text2)' }}>{k.replace(/_/g, ' ')}</span>
                  <span style={{ color: 'var(--text0)', fontFamily: 'monospace' }}>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'Accounts' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Accounts ({accounts.length})</div>
          {accounts.map((a: any, i: number) => (
            <div key={i} onClick={() => onDrill({ title: a.name ?? a.account, subtitle: a.type ?? '', endpoint: '/api/v2/retirement', rows: [a] })}
              style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 8px', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text0)' }}>{a.name ?? a.account}</div>
                <div style={{ fontSize: 9, color: 'var(--text3)' }}>{a.type ?? a.account_type ?? '—'}</div>
              </div>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text0)' }}>{fmt$(a.value ?? a.balance ?? 0, 0)}</div>
            </div>
          ))}
        </div>
      )}

      {tab === 'Timeline' && <div style={{ color: 'var(--text3)', fontSize: 12, padding: 20 }}>Retirement timeline — awaiting data integration</div>}
    </div>
  )
}

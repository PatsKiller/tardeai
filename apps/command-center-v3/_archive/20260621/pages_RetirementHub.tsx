import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { fmt$ } from '../lib/format'
import type { DrillContext } from '../components/DetailDrawer'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Overview', 'Accounts', 'Timeline', 'Planning Research'] as const

export default function RetirementHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Overview')
  const { data: ret } = useApi<any>('/api/v2/retirement', 300_000)
  const { data: planning } = useApi<any>('/api/v2/retirement/planning-research', 300_000)

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

      {tab === 'Timeline' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Retirement Timeline</div>
          {timeline.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No timeline data from /api/v2/retirement</div> :
          timeline.map((t: any, i: number) => (
            <div key={i} onClick={() => onDrill({ title: t.label ?? t.event ?? `Event ${i}`, subtitle: t.year ?? t.date ?? '', endpoint: '/api/v2/retirement', rows: [t] })}
              style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
              <span style={{ color: 'var(--text0)' }}>{t.label ?? t.event ?? t.description ?? JSON.stringify(t).slice(0, 60)}</span>
              <span style={{ color: 'var(--text2)', fontFamily: 'monospace' }}>{t.year ?? t.date ?? t.age ?? ''}</span>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/retirement → timeline</div>
        </div>
      )}

      {tab === 'Planning Research' && (
        <div>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 12, lineHeight: 1.5 }}>
            Hermes knowledge research on your retirement / estate / tax / Medicare topics (routed from the topics you add via Telegram into the research pipeline). {planning?.total ?? 0} researched items. Advisory — consult an elder-law attorney + tax advisor.
          </div>
          {!planning && <div style={{ color: 'var(--text3)', fontSize: 11 }}>Loading…</div>}
          {planning && (planning.themes ?? []).length === 0 && <div style={{ color: 'var(--text3)', fontSize: 11 }}>No planning research yet — topics are queued; Hermes researches them on its loop.</div>}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))', gap: 14 }}>
            {(planning?.themes ?? []).map((th: any) => (
              <div key={th.theme} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 13, fontWeight: 800, color: '#60a5fa', marginBottom: 8 }}>{th.theme} <span style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 500 }}>· {th.count}</span></div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {(th.items ?? []).map((it: any, i: number) => (
                    <div key={i} onClick={() => onDrill({ title: it.topic, subtitle: th.theme, endpoint: '/api/v2/retirement/planning-research', rows: [it] })}
                      style={{ padding: '7px 9px', borderRadius: 7, background: 'var(--bg2)', cursor: 'pointer', borderLeft: `3px solid ${it.status === 'promoted' || it.status === 'embedded' ? '#22c55e' : '#f59e0b'}` }}>
                      <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text0)', lineHeight: 1.3 }}>{it.topic}</div>
                      {it.summary && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 3, lineHeight: 1.4, display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{it.summary}</div>}
                      {(it.sources ?? []).length > 0 && (
                        <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                          {(it.sources ?? []).slice(0, 4).map((s: any, j: number) => (
                            <span key={j} title={s.title ?? ''} style={{ background: 'rgba(34,197,94,.10)', color: '#22c55e', borderRadius: 4, padding: '1px 5px' }}>{s.source}</span>
                          ))}
                        </div>
                      )}
                      <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 4, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        <span>{it.status ?? 'staged'}</span>{it.confidence != null && <span>· conf {it.confidence}</span>}{it.model && <span>· {it.model}</span>}{it.source_count > 0 && <span>· {it.source_count} vetted src</span>}{it.at && <span>· {String(it.at).slice(0, 10)}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 10 }}>Source: /api/v2/retirement/planning-research → topic_research (Hermes knowledge research). Advisory only.</div>
        </div>
      )}
    </div>
  )
}

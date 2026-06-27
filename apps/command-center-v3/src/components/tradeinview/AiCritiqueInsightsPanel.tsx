import { useState } from 'react'
import { useApi } from '../../hooks/useApi'

type SearchItem = {
  trade_key: string
  symbol: string
  closed_date?: string
  setup_family?: string
  summary?: string
  takeaways?: string[]
  stale?: boolean
  generated_at?: string
}

type SetupAgg = {
  setup_family: string
  trades: number
  stale: number
  top_improvements: { text: string; count: number }[]
}

export default function AiCritiqueInsightsPanel({
  days,
  initialQuery = '',
  onOpenTrade,
}: {
  days: number
  initialQuery?: string
  onOpenTrade?: (tradeKey: string) => void
}) {
  const [q, setQ] = useState(initialQuery)
  const [setupFilter, setSetupFilter] = useState('')
  const searchUrl = `/api/v2/journal/ai-critique/search?days=${days}&limit=40&q=${encodeURIComponent(q)}&setup_family=${encodeURIComponent(setupFilter)}`
  const { data: searchResp, loading: searchLoading } = useApi<any>(searchUrl, 120_000)
  const { data: insightsResp } = useApi<any>(`/api/v2/journal/ai-critique/insights?days=${Math.min(days, 90)}`, 120_000)
  const { data: setupsResp } = useApi<any>(`/api/v2/journal/ai-critique/setups?days=${days}&limit=12`, 120_000)

  const search = searchResp?.data ?? searchResp
  const insights = insightsResp?.data ?? insightsResp
  const setups = setupsResp?.data ?? setupsResp
  const items: SearchItem[] = search?.items ?? []
  const setupRows: SetupAgg[] = setups?.setups ?? []

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <div style={{ background: 'var(--bg1)', border: '1px solid rgba(167,139,250,.35)', borderRadius: 10, padding: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#c4b5fd', marginBottom: 8 }}>AI Critique Insights</div>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>
          Search persisted critiques across all trades — strengths, improvements, and takeaways from replay + tags + execution data.
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder='Search e.g. "chased entry", "premature exit", GOVX…'
            style={{ flex: '1 1 200px', fontSize: 11, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)' }}
          />
          <input
            value={setupFilter}
            onChange={e => setSetupFilter(e.target.value)}
            placeholder="Setup family filter"
            style={{ width: 160, fontSize: 11, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text1)' }}
          />
        </div>
        {searchLoading && <div style={{ fontSize: 10, color: 'var(--text3)' }}>Searching…</div>}
        {!searchLoading && items.length === 0 && (
          <div style={{ fontSize: 10, color: 'var(--text3)' }}>No critiques match — generate critiques from Trade Detail first.</div>
        )}
        <div style={{ maxHeight: 220, overflow: 'auto' }}>
          {items.map(it => (
            <div
              key={it.trade_key}
              onClick={() => onOpenTrade?.(it.trade_key)}
              style={{
                padding: '8px 0', borderBottom: '1px solid var(--border)', cursor: onOpenTrade ? 'pointer' : 'default',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)' }}>
                  {it.symbol} · {it.setup_family || 'untagged'}
                  {it.stale && <span style={{ marginLeft: 6, fontSize: 9, color: '#f59e0b' }}>stale</span>}
                </span>
                <span style={{ fontSize: 9, color: 'var(--text3)' }}>{it.closed_date}</span>
              </div>
              <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 3, lineHeight: 1.45 }}>
                {it.summary?.slice(0, 160)}{(it.summary?.length ?? 0) > 160 ? '…' : ''}
              </div>
              {it.takeaways?.[0] && (
                <div style={{ fontSize: 9, color: '#a78bfa', marginTop: 2 }}>→ {it.takeaways[0].slice(0, 100)}</div>
              )}
            </div>
          ))}
        </div>
      </div>

      {(insights?.coaching_bullets?.length > 0 || insights?.highlights?.length > 0) && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Coaching patterns ({insights?.critique_count ?? 0} critiques)</div>
          {(insights?.coaching_bullets ?? []).map((b: string, i: number) => (
            <div key={i} style={{ fontSize: 10, color: 'var(--text2)', padding: '3px 0' }}>• {b}</div>
          ))}
          {(insights?.highlights ?? []).slice(0, 3).map((h: any) => (
            <div key={h.trade_key} style={{ fontSize: 10, color: 'var(--text3)', marginTop: 6, fontStyle: 'italic' }}>
              {h.symbol}: {h.takeaway || h.summary?.slice(0, 80)}
            </div>
          ))}
        </div>
      )}

      {setupRows.length > 0 && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>By setup family</div>
          {setupRows.map(s => (
            <div key={s.setup_family} style={{ marginBottom: 10, paddingBottom: 8, borderBottom: '1px solid var(--border)' }}>
              <div style={{ fontSize: 11, fontWeight: 600 }}>{s.setup_family} · {s.trades} trades{s.stale ? ` · ${s.stale} stale` : ''}</div>
              {(s.top_improvements ?? []).slice(0, 3).map((imp, i) => (
                <div key={i} style={{ fontSize: 9, color: '#fca5a5', marginTop: 3 }}>
                  {imp.text.slice(0, 90)} ({imp.count}×)
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )

}
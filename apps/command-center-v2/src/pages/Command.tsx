import { useApi } from '../hooks/useApi'
import FreshnessBadge from '../components/FreshnessBadge'

interface Action { priority: string; action: string }
interface Mover { symbol: string; perf_week: number; price: number; market_value: number }
interface Proposal { id: number; symbol: string; strategy_id: string; status: string; created: string }
interface Recovery { symbol: string; analyst_verdict: string; analyst_confidence: number; exit_type: string }
interface NewsItem { symbol: string; title: string; source: string; sentiment: string; date: string }

interface CommandData {
  generated_at: string
  portfolio: { total_value: number; cash: number; cash_pct: number; positions: number; heat_pct: number; no_stop_count: number; triggered_count: number }
  actions: Action[]
  top_gainers: Mover[]
  top_losers: Mover[]
  dividends: { month: string; total: number; symbols: string[]; annual_income: number }
  pending_proposals: Proposal[]
  recovery_watch: Recovery[]
  top_news: NewsItem[]
  cio_pending: { symbol: string; action: string; priority: string }[]
  screener: { status: string; symbols_scanned: number }
  pipeline: { ok: boolean; note: string }
  freshness: { last_refresh: string; status: string }
  llm_intelligence?: Record<string, { content?: string; error?: string }>
  social_highlights?: { symbol: string; summary: string }[]
}

const fmt = (v: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v)
const pct = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`

const PRIORITY_COLORS: Record<string, string> = {
  urgent: '#f6465d',
  high: '#f0b90b',
  medium: '#4a90f4',
  low: '#0ecb81',
}

export default function Command() {
  const { data: cmd, loading, error, refetch } = useApi<CommandData>('/api/v2/command')

  if (loading) return <div style={{ padding: 20, color: 'var(--text3)' }}>Loading command briefing...</div>
  if (error || !cmd) return (
    <div style={{ padding: 20 }}>
      <div style={{ padding: '16px 20px', background: 'rgba(246,70,93,.08)', border: '1px solid rgba(246,70,93,.3)', borderRadius: 8, maxWidth: 500 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: '#f6465d', marginBottom: 8 }}>Failed to load command data</div>
        <div style={{ fontSize: 11, color: '#94A3B8', marginBottom: 12 }}>{error || 'The command API returned no data. The endpoint may be temporarily unavailable.'}</div>
        <button onClick={() => window.location.reload()} style={{ fontSize: 11, padding: '6px 16px', border: '1px solid #4a90f4', borderRadius: 6, background: 'rgba(74,144,244,.1)', color: '#4a90f4', cursor: 'pointer', fontFamily: 'monospace' }}>Retry</button>
      </div>
    </div>
  )

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 16, marginBottom: 16 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)', margin: 0 }}>Morning Command</h2>
        <FreshnessBadge lastRefresh={cmd.freshness?.last_refresh} label="Data" />
        <button onClick={refetch} style={{ padding: '3px 10px', fontSize: 10, border: '1px solid var(--border1, #2a2a3a)', borderRadius: 4, background: 'transparent', color: 'var(--accent, #4a90f4)', cursor: 'pointer', fontFamily: 'monospace' }}>Refresh</button>
      </div>

      {/* Portfolio snapshot */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10, marginBottom: 20 }}>
        {[
          { label: 'Portfolio', value: fmt(cmd.portfolio.total_value) },
          { label: 'Cash', value: `${fmt(cmd.portfolio?.cash ?? 0)} (${cmd.portfolio?.cash_pct ?? 0}%)` },
          { label: 'Positions', value: String(cmd.portfolio?.positions ?? 0) },
          { label: 'Heat', value: `${(cmd.portfolio?.heat_pct ?? 0).toFixed(1)}%`, alert: (cmd.portfolio?.heat_pct ?? 0) > 5 },
          { label: 'No Stop', value: String(cmd.portfolio?.no_stop_count ?? 0), alert: (cmd.portfolio?.no_stop_count ?? 0) > 5 },
          { label: 'Triggered', value: String(cmd.portfolio?.triggered_count ?? 0), alert: (cmd.portfolio?.triggered_count ?? 0) > 0 },
        ].map(m => (
          <div key={m.label} style={{ padding: '10px 12px', background: 'var(--bg1, #1e1e2e)', borderRadius: 6, border: m.alert ? '1px solid #f6465d' : '1px solid var(--border1, #2a2a3a)' }}>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 4 }}>{m.label}</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: m.alert ? '#f6465d' : 'var(--text0)' }}>{m.value}</div>
          </div>
        ))}
      </div>

      {/* Action items */}
      {(cmd.actions?.length ?? 0) > 0 && (
        <div style={{ marginBottom: 20, padding: '12px 16px', background: 'var(--bg1)', borderRadius: 6, border: '1px solid var(--border1)' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Action Items</div>
          {(cmd.actions || []).map((a, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', fontSize: 12 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: PRIORITY_COLORS[a.priority] || '#888', flexShrink: 0 }} />
              <span style={{ color: 'var(--text1)' }}>{a.action}</span>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
        {/* Top Gainers */}
        <div style={{ padding: '12px 16px', background: 'var(--bg1)', borderRadius: 6, border: '1px solid var(--border1)' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#0ecb81', marginBottom: 8 }}>Top Gainers (Week)</div>
          {(cmd.top_gainers?.length ?? 0) > 0 ? (cmd.top_gainers || []).map(m => (
            <div key={m.symbol} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', fontSize: 12 }}>
              <span style={{ color: 'var(--text0)', fontWeight: 500 }}>{m.symbol}</span>
              <span style={{ color: '#0ecb81' }}>{pct(m.perf_week)}</span>
            </div>
          )) : <div style={{ fontSize: 11, color: 'var(--text3)' }}>No data</div>}
        </div>

        {/* Top Losers */}
        <div style={{ padding: '12px 16px', background: 'var(--bg1)', borderRadius: 6, border: '1px solid var(--border1)' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#f6465d', marginBottom: 8 }}>Top Losers (Week)</div>
          {(cmd.top_losers?.length ?? 0) > 0 ? (cmd.top_losers || []).map(m => (
            <div key={m.symbol} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', fontSize: 12 }}>
              <span style={{ color: 'var(--text0)', fontWeight: 500 }}>{m.symbol}</span>
              <span style={{ color: '#f6465d' }}>{pct(m.perf_week)}</span>
            </div>
          )) : <div style={{ fontSize: 11, color: 'var(--text3)' }}>No data</div>}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
        {/* Dividends */}
        <div style={{ padding: '12px 16px', background: 'var(--bg1)', borderRadius: 6, border: '1px solid var(--border1)' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Dividends — {cmd.dividends?.month ?? '—'}</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#0ecb81', marginBottom: 4 }}>{fmt(cmd.dividends?.total ?? 0)}</div>
          <div style={{ fontSize: 11, color: 'var(--text2)' }}>{(cmd.dividends?.symbols || []).join(', ')}</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>Annual: {fmt(cmd.dividends?.annual_income ?? 0)}</div>
        </div>

        {/* Pipeline & Screener */}
        <div style={{ padding: '12px 16px', background: 'var(--bg1)', borderRadius: 6, border: '1px solid var(--border1)' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>System Status</div>
          <div style={{ fontSize: 12, color: cmd.pipeline?.ok ? '#0ecb81' : '#f6465d', marginBottom: 4 }}>
            {cmd.pipeline?.ok ? '● ' : '○ '}{cmd.pipeline?.note ?? 'Unknown'}
          </div>
          {cmd.screener?.status && (
            <div style={{ fontSize: 11, color: 'var(--text2)' }}>
              Screener: {cmd.screener.status} ({cmd.screener.symbols_scanned ?? 0} symbols)
            </div>
          )}
        </div>
      </div>

      {/* News */}
      {(cmd.top_news?.length ?? 0) > 0 && (
        <div style={{ marginBottom: 20, padding: '12px 16px', background: 'var(--bg1)', borderRadius: 6, border: '1px solid var(--border1)' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Latest News (24h)</div>
          {(cmd.top_news || []).map((n, i) => (
            <div key={i} style={{ padding: '4px 0', fontSize: 12, borderBottom: '1px solid var(--border1)' }}>
              <span style={{ fontWeight: 500, color: 'var(--accent)', marginRight: 8 }}>{n.symbol}</span>
              <span style={{ color: 'var(--text1)' }}>{n.title?.slice(0, 100)}</span>
              <span style={{ color: 'var(--text3)', marginLeft: 8, fontSize: 10 }}>{n.source}</span>
            </div>
          ))}
        </div>
      )}

      {/* Recovery + Proposals + CIO in grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
        {/* Proposals */}
        <div style={{ padding: '12px 16px', background: 'var(--bg1)', borderRadius: 6, border: '1px solid var(--border1)' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Proposals Pending ({(cmd.pending_proposals || []).length})</div>
          {(cmd.pending_proposals?.length ?? 0) > 0 ? (cmd.pending_proposals || []).slice(0, 5).map(p => (
            <div key={p.id} style={{ fontSize: 11, padding: '2px 0', color: 'var(--text2)' }}>
              {p.symbol} — {p.strategy_id}
            </div>
          )) : <div style={{ fontSize: 11, color: 'var(--text3)' }}>None pending</div>}
        </div>

        {/* Recovery */}
        <div style={{ padding: '12px 16px', background: 'var(--bg1)', borderRadius: 6, border: '1px solid var(--border1)' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Recovery Watch ({(cmd.recovery_watch || []).length})</div>
          {(cmd.recovery_watch || []).slice(0, 5).map(r => (
            <div key={r.symbol} style={{ fontSize: 11, padding: '2px 0', color: 'var(--text2)' }}>
              {r.symbol} — {r.analyst_verdict?.replace(/_/g, ' ')} ({((r.analyst_confidence || 0) * 100).toFixed(0)}%)
            </div>
          ))}
        </div>

        {/* CIO */}
        <div style={{ padding: '12px 16px', background: 'var(--bg1)', borderRadius: 6, border: '1px solid var(--border1)' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>CIO Pending ({(cmd.cio_pending || []).length})</div>
          {(cmd.cio_pending || []).slice(0, 5).map((c, i) => (
            <div key={i} style={{ fontSize: 11, padding: '2px 0', color: 'var(--text2)' }}>
              {c.symbol} — {c.action?.replace(/_/g, ' ')}
            </div>
          ))}
        </div>
      </div>

      {/* LLM Intelligence */}
      {cmd.llm_intelligence && Object.keys(cmd.llm_intelligence).length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>AI Intelligence Briefing</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {Object.entries(cmd.llm_intelligence).map(([key, val]) => (
              <div key={key} style={{ padding: '12px 16px', background: 'var(--bg1)', borderRadius: 6, border: '1px solid var(--border1)' }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--accent)', marginBottom: 6, textTransform: 'capitalize' }}>
                  {key.replace(/_/g, ' ')}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text1)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                  {val?.content || val?.error || 'Analysis not yet available.'}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

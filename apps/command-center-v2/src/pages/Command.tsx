import { useApi } from '../hooks/useApi'
import FreshnessBadge from '../components/FreshnessBadge'
import { useNavigate } from 'react-router-dom'

interface Action { priority: string; action: string }
interface Mover { symbol: string; perf_week: number; price: number; market_value: number }
interface Proposal { id: number; symbol: string; strategy_id: string; status: string; created: string }
interface Recovery { symbol: string; analyst_verdict: string; analyst_confidence: number; exit_type: string }
interface NewsItem { symbol: string; title: string; source: string; sentiment: string; date: string }
interface AgentHealth { agent: string; total: number; latest: string; age_days: number; max_days: number; status: string }
interface TriggeredStop { symbol: string; stop: number; price: number; pnl_pct: number; account: string }
interface PaperTrade { id: number; symbol: string; entry_price: number; shares: number; stop_loss: number; current_price: number; unrealized_pnl: number; r_multiple: number; lifecycle_state: string }

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
  cio_pending: { symbol: string; action: string; priority: string; rationale?: string }[]
  screener: { status: string; symbols_scanned: number }
  pipeline: { ok: boolean; note: string }
  freshness: { last_refresh: string; status: string; context?: string; is_weekend?: boolean; age_display?: string }
  llm_intelligence?: Record<string, { content?: string; error?: string; generated_at?: string }>
  social_highlights?: { symbol: string; summary: string }[]
  agent_health?: AgentHealth[]
  triggered_detail?: TriggeredStop[]
  open_paper_trades?: PaperTrade[]
}

const fmt = (v: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v)
const pct = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`

const P = { urgent: { bg: 'rgba(246,70,93,.12)', border: '#f6465d', text: '#f6465d', dot: '#f6465d' },
            high: { bg: 'rgba(240,185,11,.10)', border: '#f0b90b', text: '#f0b90b', dot: '#f0b90b' },
            medium: { bg: 'rgba(74,144,244,.08)', border: '#4a90f4', text: '#4a90f4', dot: '#4a90f4' },
            low: { bg: 'rgba(14,203,129,.08)', border: '#0ecb81', text: '#0ecb81', dot: '#0ecb81' } } as Record<string, any>

const Card = ({ children, style, alert }: { children: React.ReactNode; style?: React.CSSProperties; alert?: boolean }) => (
  <div style={{ padding: '14px 16px', background: 'var(--bg1, #1e1e2e)', borderRadius: 8,
    border: alert ? '1px solid #f6465d' : '1px solid var(--border1, #2a2a3a)', ...style }}>
    {children}
  </div>
)

const SectionTitle = ({ children, count, color }: { children: React.ReactNode; count?: number; color?: string }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
    <span style={{ fontSize: 13, fontWeight: 700, color: color || 'var(--text0)', letterSpacing: '-0.01em' }}>{children}</span>
    {count !== undefined && <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 8, background: 'rgba(255,255,255,.06)', color: 'var(--text3)' }}>{count}</span>}
  </div>
)

const AgentDot = ({ status }: { status: string }) => {
  const c = status === 'healthy' ? '#0ecb81' : status === 'stale' ? '#f0b90b' : '#f6465d'
  return <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: c, flexShrink: 0 }} />
}

export default function Command() {
  const { data: cmd, loading, error, refetch } = useApi<CommandData>('/api/v2/command', 300_000)
  const nav = useNavigate()

  if (loading) return <div style={{ padding: 32, color: 'var(--text3)', fontSize: 13 }}>Loading command briefing...</div>
  if (error || !cmd) return (
    <div style={{ padding: 32 }}>
      <Card alert><div style={{ fontSize: 13, fontWeight: 700, color: '#f6465d', marginBottom: 6 }}>Failed to load</div>
        <div style={{ fontSize: 11, color: '#94A3B8', marginBottom: 10 }}>{error || 'API unavailable'}</div>
        <button onClick={() => window.location.reload()} style={{ fontSize: 11, padding: '5px 14px', border: '1px solid #4a90f4', borderRadius: 6, background: 'rgba(74,144,244,.1)', color: '#4a90f4', cursor: 'pointer', fontFamily: 'monospace' }}>Retry</button>
      </Card>
    </div>
  )

  const staleAgents = (cmd.agent_health || []).filter(a => a.status !== 'healthy')
  const healthyAgents = (cmd.agent_health || []).filter(a => a.status === 'healthy')
  const hasUrgent = (cmd.actions || []).some(a => a.priority === 'urgent')

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* ═══ HEADER ═══ */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)', margin: 0 }}>Command Center</h2>
          <FreshnessBadge lastRefresh={cmd.freshness?.last_refresh} label="Data" context={cmd.freshness?.context} isWeekend={cmd.freshness?.is_weekend} />
        </div>
        <button onClick={refetch} style={{ padding: '4px 12px', fontSize: 10, border: '1px solid var(--border1)', borderRadius: 5, background: 'transparent', color: 'var(--accent, #4a90f4)', cursor: 'pointer', fontFamily: 'monospace' }}>Refresh</button>
      </div>

      {/* ═══ PRIORITY ACTIONS — only shows if there are actions ═══ */}
      {(cmd.actions?.length ?? 0) > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {(cmd.actions || []).map((a, i) => {
            const p = P[a.priority] || P.medium
            const link = a.priority === 'urgent' ? '/risk' : a.action.includes('proposal') ? '/paper-proposals' : a.action.includes('CIO') ? '/cio' : undefined
            return (
              <div key={i} onClick={() => link && nav(link)} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 14px',
                background: p.bg, border: `1px solid ${p.border}40`, borderRadius: 6, cursor: link ? 'pointer' : 'default' }}>
                <span style={{ width: 7, height: 7, borderRadius: '50%', background: p.dot, flexShrink: 0 }} />
                <span style={{ fontSize: 12, fontWeight: 600, color: p.text, flex: 1 }}>{a.action}</span>
                {link && <span style={{ fontSize: 10, color: p.text, opacity: 0.6 }}>Review →</span>}
              </div>
            )
          })}
        </div>
      )}

      {/* ═══ PORTFOLIO PULSE — 6 KPIs ═══ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 8 }}>
        {[
          { label: 'Portfolio', value: fmt(cmd.portfolio.total_value), sub: `${cmd.portfolio?.positions ?? 0} positions` },
          { label: 'Cash', value: fmt(cmd.portfolio?.cash ?? 0), sub: `${cmd.portfolio?.cash_pct ?? 0}% of portfolio` },
          { label: 'Heat', value: `${(cmd.portfolio?.heat_pct ?? 0).toFixed(1)}%`, alert: (cmd.portfolio?.heat_pct ?? 0) > 5, sub: (cmd.portfolio?.heat_pct ?? 0) > 5 ? 'Above 5% limit' : 'Within limits' },
          { label: 'No Stop', value: String(cmd.portfolio?.no_stop_count ?? 0), alert: (cmd.portfolio?.no_stop_count ?? 0) > 5, sub: 'Unprotected' },
          { label: 'Triggered', value: String(cmd.portfolio?.triggered_count ?? 0), alert: (cmd.portfolio?.triggered_count ?? 0) > 0, sub: (cmd.portfolio?.triggered_count ?? 0) > 0 ? 'Action needed' : 'All clear' },
          { label: 'Income', value: fmt(cmd.dividends?.annual_income ?? 0), sub: `${fmt(cmd.dividends?.total ?? 0)} this ${cmd.dividends?.month || 'month'}` },
        ].map(m => (
          <Card key={m.label} alert={m.alert}>
            <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text3)', marginBottom: 4 }}>{m.label}</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: m.alert ? '#f6465d' : 'var(--text0)' }}>{m.value}</div>
            {m.sub && <div style={{ fontSize: 10, color: m.alert ? '#f6465d80' : 'var(--text3)', marginTop: 2 }}>{m.sub}</div>}
          </Card>
        ))}
      </div>

      {/* ═══ TRIGGERED STOPS — if any ═══ */}
      {(cmd.triggered_detail?.length ?? 0) > 0 && (
        <Card alert>
          <SectionTitle color="#f6465d" count={cmd.triggered_detail!.length}>Stops Triggered — Action Required</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 8 }}>
            {(cmd.triggered_detail || []).map(t => (
              <div key={t.symbol} style={{ padding: '8px 12px', background: 'rgba(246,70,93,.06)', borderRadius: 6, border: '1px solid rgba(246,70,93,.15)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: '#f6465d' }}>{t.symbol}</span>
                  <span style={{ fontSize: 11, color: '#f6465d' }}>{pct(t.pnl_pct)}</span>
                </div>
                <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>
                  Stop ${t.stop?.toFixed(2)} · Now ${t.price?.toFixed(2)} · {t.account}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* ═══ TWO-COLUMN: Paper Trades + Movers ═══ */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {/* Open Paper Trades */}
        <Card>
          <SectionTitle count={(cmd.open_paper_trades || []).length}>Paper Trades</SectionTitle>
          {(cmd.open_paper_trades?.length ?? 0) > 0 ? (cmd.open_paper_trades || []).map(t => (
            <div key={t.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', borderBottom: '1px solid var(--border1)' }}>
              <div>
                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text0)', marginRight: 8 }}>{t.symbol}</span>
                <span style={{ fontSize: 10, color: 'var(--text3)' }}>{t.shares}sh @ ${t.entry_price?.toFixed(2)}</span>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: (t.unrealized_pnl ?? 0) >= 0 ? '#0ecb81' : '#f6465d' }}>
                  {fmt(t.unrealized_pnl ?? 0)}
                </div>
                {t.r_multiple != null && <div style={{ fontSize: 9, color: 'var(--text3)' }}>{t.r_multiple?.toFixed(1)}R</div>}
              </div>
            </div>
          )) : <div style={{ fontSize: 11, color: 'var(--text3)' }}>No open trades</div>}
        </Card>

        {/* Movers */}
        <Card>
          <SectionTitle>Weekly Movers</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, color: '#0ecb81', marginBottom: 6 }}>GAINERS</div>
              {(cmd.top_gainers?.length ?? 0) > 0 ? (cmd.top_gainers || []).map(m => (
                <div key={m.symbol} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', fontSize: 11 }}>
                  <span style={{ color: 'var(--text0)' }}>{m.symbol}</span>
                  <span style={{ color: '#0ecb81', fontWeight: 500 }}>{pct(m.perf_week)}</span>
                </div>
              )) : <div style={{ fontSize: 10, color: 'var(--text3)' }}>—</div>}
            </div>
            <div>
              <div style={{ fontSize: 10, fontWeight: 600, color: '#f6465d', marginBottom: 6 }}>LOSERS</div>
              {(cmd.top_losers?.length ?? 0) > 0 ? (cmd.top_losers || []).map(m => (
                <div key={m.symbol} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', fontSize: 11 }}>
                  <span style={{ color: 'var(--text0)' }}>{m.symbol}</span>
                  <span style={{ color: '#f6465d', fontWeight: 500 }}>{pct(m.perf_week)}</span>
                </div>
              )) : <div style={{ fontSize: 10, color: 'var(--text3)' }}>—</div>}
            </div>
          </div>
        </Card>
      </div>

      {/* ═══ THREE-COLUMN: Proposals + CIO + Recovery ═══ */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
        <Card>
          <SectionTitle count={(cmd.pending_proposals || []).length}>Proposals</SectionTitle>
          {(cmd.pending_proposals?.length ?? 0) > 0 ? (cmd.pending_proposals || []).slice(0, 6).map(p => (
            <div key={p.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '3px 0', fontSize: 11 }}>
              <div>
                <span style={{ fontWeight: 600, color: 'var(--text0)', marginRight: 6 }}>{p.symbol}</span>
                <span style={{ color: 'var(--text3)', fontSize: 10 }}>{p.strategy_id?.replace(/_/g, ' ')}</span>
              </div>
              <span style={{ fontSize: 9, color: 'var(--text3)' }}>{p.created}</span>
            </div>
          )) : <div style={{ fontSize: 11, color: 'var(--text3)' }}>None pending</div>}
          {(cmd.pending_proposals?.length ?? 0) > 0 && (
            <div onClick={() => nav('/paper-proposals')} style={{ fontSize: 10, color: 'var(--accent)', marginTop: 8, cursor: 'pointer' }}>View all →</div>
          )}
        </Card>

        <Card>
          <SectionTitle count={(cmd.cio_pending || []).length}>CIO Decisions</SectionTitle>
          {(cmd.cio_pending?.length ?? 0) > 0 ? (cmd.cio_pending || []).slice(0, 6).map((c, i) => (
            <div key={i} style={{ padding: '3px 0', fontSize: 11 }}>
              <span style={{ fontWeight: 600, color: c.priority === 'critical' ? '#f6465d' : 'var(--text0)', marginRight: 6 }}>{c.symbol}</span>
              <span style={{ color: 'var(--text2)' }}>{c.action?.replace(/_/g, ' ')}</span>
            </div>
          )) : <div style={{ fontSize: 11, color: 'var(--text3)' }}>No pending decisions</div>}
        </Card>

        <Card>
          <SectionTitle count={(cmd.recovery_watch || []).length}>Recovery Watch</SectionTitle>
          {(cmd.recovery_watch || []).slice(0, 6).map(r => (
            <div key={r.symbol} style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', fontSize: 11 }}>
              <span style={{ fontWeight: 600, color: 'var(--text0)' }}>{r.symbol}</span>
              <span style={{ fontSize: 10, color: r.analyst_verdict === 'reentry_candidate' ? '#0ecb81' : 'var(--text3)' }}>
                {r.analyst_verdict?.replace(/_/g, ' ')} {((r.analyst_confidence || 0) * 100).toFixed(0)}%
              </span>
            </div>
          ))}
          {(cmd.recovery_watch || []).length === 0 && <div style={{ fontSize: 11, color: 'var(--text3)' }}>No recovery items</div>}
        </Card>
      </div>

      {/* ═══ NEWS ═══ */}
      {(cmd.top_news?.length ?? 0) > 0 && (
        <Card>
          <SectionTitle count={(cmd.top_news || []).length}>Portfolio News</SectionTitle>
          {(cmd.top_news || []).slice(0, 8).map((n, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'baseline', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border1)', fontSize: 11 }}>
              <span style={{ fontWeight: 600, color: 'var(--accent)', minWidth: 45 }}>{n.symbol}</span>
              <span style={{ color: 'var(--text1)', flex: 1 }}>{n.title?.slice(0, 90)}</span>
              <span style={{ fontSize: 9, color: n.sentiment === 'positive' ? '#0ecb81' : n.sentiment === 'negative' ? '#f6465d' : 'var(--text3)', flexShrink: 0 }}>
                {n.sentiment === 'positive' ? '▲' : n.sentiment === 'negative' ? '▼' : '—'} {n.source}
              </span>
            </div>
          ))}
        </Card>
      )}

      {/* ═══ AI INTELLIGENCE BRIEFING ═══ */}
      {cmd.llm_intelligence && Object.keys(cmd.llm_intelligence).length > 0 && (
        <Card>
          <SectionTitle>AI Intelligence Briefing</SectionTitle>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {Object.entries(cmd.llm_intelligence).map(([key, val]) => (
              <div key={key} style={{ padding: '10px 14px', background: 'rgba(74,144,244,.04)', borderRadius: 6, border: '1px solid rgba(74,144,244,.1)' }}>
                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--accent)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  {key.replace(/_/g, ' ')}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text1)', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
                  {val?.content || val?.error || 'Analysis not yet available.'}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* ═══ SYSTEM HEALTH — Agents + Pipeline ═══ */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
        <Card alert={staleAgents.length > 0}>
          <SectionTitle count={(cmd.agent_health || []).length}>Agent Health</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 6 }}>
            {(cmd.agent_health || []).map(a => (
              <div key={a.agent} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 8px', borderRadius: 5,
                background: a.status !== 'healthy' ? 'rgba(246,70,93,.06)' : 'transparent' }}>
                <AgentDot status={a.status} />
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: a.status !== 'healthy' ? '#f6465d' : 'var(--text0)' }}>{a.agent}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>
                    {a.age_days < 0.04 ? 'just now' : a.age_days < 1 ? `${(a.age_days * 24).toFixed(0)}h ago` : `${a.age_days.toFixed(0)}d ago`}
                    {' · '}{a.total} runs
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <SectionTitle>System</SectionTitle>
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span style={{ color: cmd.pipeline?.ok ? '#0ecb81' : '#f6465d', fontSize: 14 }}>{cmd.pipeline?.ok ? '●' : '○'}</span>
              <span style={{ color: 'var(--text1)' }}>{cmd.pipeline?.note}</span>
            </div>
          </div>
          {cmd.screener?.status && (
            <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 4 }}>
              Screener: {cmd.screener.status} · {cmd.screener.symbols_scanned ?? 0} symbols
            </div>
          )}
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 6 }}>
            {healthyAgents.length}/{(cmd.agent_health || []).length} agents healthy
            {staleAgents.length > 0 && <span style={{ color: '#f6465d' }}> · {staleAgents.length} stale</span>}
          </div>
        </Card>
      </div>

    </div>
  )
}

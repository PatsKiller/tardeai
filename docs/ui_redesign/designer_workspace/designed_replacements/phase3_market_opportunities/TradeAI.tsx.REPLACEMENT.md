# TradeAI.tsx Replacement

Status:      HISTORICAL
as_of:       2026-05-25T14:16:20-04:00
Measured at: efcc51365 / not measured

**Target repo path:** `apps/command-center-v2/src/pages/TradeAI.tsx`

**Original SHA256:** `100acd120f2bba7fa9dba07bb675e2c9e66e199a92f922b79d07c470e626e907`

## Full Replacement

```tsx
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import ScalpLiveFeed from '../components/ScalpLiveFeed'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import DetailDrawer, { DrawerStat, DrawerSection } from '../components/DetailDrawer'
import DataGrid from '../components/DataGrid'
import { BarChartJS } from '../components/charts'
import { ConfluenceBadge } from '../components/ConfluenceBadge'
import { useApi } from '../hooks/useApi'
import { deltaColor, fmt$ } from '../lib/format'
import { StatusBadge } from '../components/StatusBadge'
import { SeverityBadge } from '../components/SeverityBadge'
import { ActionButton } from '../components/ActionButton'
import { StateCard } from '../components/StateCard'

interface Ticker {
  symbol: string; score: number; grade: string; decision: string
  rvol: number; price: number; change_pct: string; gap_pct: string
  float_m: string; catalyst: string; source?: string; source_detail?: string
  disqualified?: boolean; disqualification_reason?: string
  catalyst_verified?: boolean | null; industry?: string
  critic_verdict?: string | null; critic_confidence?: number | null
  original_decision?: string | null; decision_changed?: boolean
  critic_reasoning?: string | null; critic_flags?: string[]
  sector?: string | null; country?: string | null; sector_etf?: string | null
  ticker_perf_1m?: number | null; sector_perf_1m?: number | null; vs_sector_pct?: number | null
  social_sentiment?: string | null; social_score?: number | null
  social_reddit?: number | null; social_stocktwits?: number | null; social_bullish_pct?: number | null
  intelligence_readiness?: number | null
  incubator_llm_grade?: string | null; incubator_llm_verdict?: string | null
  holdings_llm_health?: string | null; holdings_llm_action?: string | null
  proposal_llm_stage?: string | null; proposal_llm_confidence?: number | null
  proposal_llm_decision?: string | null; proposal_risk_grade?: string | null
  proposal_catalyst_grade?: string | null
}

interface RunHistoryItem {
  date: string; label: string; go: number; wait: number; total: number
  top_ticker: string; top_score: number
}

interface TradeAIData {
  ok?: boolean; run_date: string; run_label: string; vix: number | null; breadth: string
  go_count: number; wait_count: number; avoid_count: number; ticker_count: number
  top_ticker: string; top_score: number; delta_events: number
  latest_run_label?: string; latest_run_timestamp?: string; latest_run_symbols_scanned?: number
  latest_run_go_count?: number; latest_run_wait_count?: number; latest_run_no_go_count?: number
  current_run_scanned?: number; current_run_go?: number; current_run_wait?: number; current_run_nogo?: number
  universe_count?: number; universe_go?: number; universe_wait?: number; universe_nogo?: number
  run_health_status?: string; today_strategy_signal_count?: number
  tickers: Ticker[]; sectors: Record<string, number>; run_history: RunHistoryItem[]
}

const decisionColor: Record<string, string> = { GO: 'var(--green)', WAIT: 'var(--amber)', AVOID: 'var(--red)', 'NO GO': 'var(--red)' }
const decisionBg: Record<string, string> = { GO: 'var(--green-dim)', WAIT: 'var(--amber-dim)', AVOID: 'var(--red-dim)', 'NO GO': 'var(--red-dim)' }

/** Map decision strings to StatusBadge status values */
function decisionToStatus(decision: string): string {
  switch (decision) {
    case 'GO': return 'ready'
    case 'WAIT': return 'waiting'
    case 'AVOID': return 'blocked'
    case 'NO GO': return 'blocked'
    default: return 'unknown'
  }
}

/** Map run health to StateCard status */
function runHealthToStatus(health?: string): string {
  if (!health) return 'unknown'
  if (health === 'RUN_HEALTHY') return 'fresh'
  if (health === 'RUN_UNDERFILLED') return 'blocked'
  return 'warning'
}

export default function TradeAI() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { data: tai } = useApi<TradeAIData>('/api/v2/trade-ai')
  const [filter, setFilter] = useState<string>('ALL')
  const [selectedTicker, setSelectedTicker] = useState<Ticker | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const [irisStatus, setIrisStatus] = useState<any>(null)
  const [confluenceData, setConfluenceData] = useState<Record<string, any>>({})

  useEffect(() => {
    fetch('/api/v2/iris/integrity').then(r => r.json())
      .then(d => { if (d.ok) setIrisStatus(d.data) }).catch(() => {})
  }, [])

  // Load confluence for GO/WAIT tickers (non-fatal)
  useEffect(() => {
    const goWait = (tai?.tickers || []).filter(t => t.decision === 'GO' || t.decision === 'WAIT').map(t => t.symbol).slice(0, 20)
    if (goWait.length === 0) return
    fetch('/api/v2/indicators/batch', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols: goWait, profile: 'scalp' })
    })
      .then(r => r.json())
      .then(d => { if (d.ok && d.results) setConfluenceData(d.results) })
      .catch(() => {})
  }, [tai])

  useEffect(() => {
    const symbol = params.get('symbol')?.toUpperCase()
    if (!symbol || !tai?.tickers?.length) return
    const found = tai.tickers.find(t => t.symbol === symbol)
    if (found) setSelectedTicker(found)
  }, [params, tai])

  if (!tai) return (
    <div style={{ color: 'var(--text3)', padding: 40, textAlign: 'center' }}>
      <div style={{ fontSize: 14, marginBottom: 8 }}>Loading Market Opportunities...</div>
      <div style={{ fontSize: 11, color: 'var(--text3)' }}>Fetching Trade AI data from /api/v2/trade-ai</div>
    </div>
  )

  // Grade legend for tooltip
  const gradeLegend: Record<string, string> = { A: 'High confidence (score >=45, all criteria met)', B: 'Moderate (score 35-44, some criteria marginal)', C: 'Low confidence (score <35)' }

  const tickers = filter === 'ALL' ? (tai.tickers || []) : (tai.tickers || []).filter(t => t.decision === filter)
  const regimeEmoji = tai.breadth?.includes('Bull') ? '\u{1f7e2}' : tai.breadth?.includes('Bear') ? '\u{1f534}' : '\u{1f7e1}'

  const columns = [
    { key: 'decision', label: 'Signal', width: 70, render: (r: Ticker) => (
      <span style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
        <StatusBadge status={decisionToStatus(r.decision)} label={r.decision} />
        {r.decision_changed && r.original_decision && (
          <span style={{ fontSize: 8, color: '#64748B', textDecoration: 'line-through' }}>{r.original_decision}</span>
        )}
      </span>
    )},
    { key: 'source', label: 'Source', width: 70, render: (r: Ticker) => {
      const src = r.source || 'screener'
      const detail = r.source_detail || ''
      const cfg: Record<string, { icon: string; color: string; label: string }> = {
        social: { icon: '\uD83D\uDCAC', color: '#d97706', label: detail ? `Social ${detail}` : 'Social' },
        portfolio: { icon: '\uD83D\uDCBC', color: '#6366f1', label: 'Portfolio' },
        personal_watchlist: { icon: '\uD83D\uDC64', color: '#6366f1', label: 'Personal' },
        ai_discovered: { icon: '\uD83E\uDD16', color: '#059669', label: 'AI' },
        ai_watchlist: { icon: '\uD83D\uDD0D', color: '#059669', label: 'AI Watch' },
        screener: { icon: '\uD83D\uDCCA', color: '#0891b2', label: 'Finviz' },
      }
      const c = cfg[src] || cfg.screener
      return <span style={{ fontSize: 8, fontWeight: 600, padding: '1px 5px', borderRadius: 3, border: `1px solid ${c.color}40`, color: c.color, whiteSpace: 'nowrap' }}>{c.icon} {c.label}</span>
    }},
    { key: 'symbol', label: 'Symbol', width: 60, render: (r: Ticker) => <span style={{ fontWeight: 700, color: 'var(--text0)' }}>{r.symbol}</span> },
    { key: 'score', label: 'Score', width: 50, align: 'right' as const, sortKey: (r: Ticker) => r.score, render: (r: Ticker) => (
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, justifyContent: 'flex-end' }}>
        <div style={{ width: 30, height: 5, background: 'var(--bg3)', borderRadius: 2, overflow: 'hidden' }}>
          <div style={{ width: `${Math.min(r.score, 50) * 2}%`, height: '100%', background: r.score >= 40 ? 'var(--green)' : r.score >= 30 ? 'var(--amber)' : 'var(--text3)', borderRadius: 2 }} />
        </div>
        <span style={{ fontWeight: 600, color: r.score >= 40 ? 'var(--green)' : r.score >= 30 ? 'var(--amber)' : 'var(--text2)' }}>{r.score}</span>
      </div>
    )},
    { key: 'intelligence_readiness', label: 'Intel', width: 35, align: 'right' as const, sortKey: (r: Ticker) => r.intelligence_readiness || 0, render: (r: Ticker) => {
      const ir = r.intelligence_readiness;
      if (ir == null) return <span style={{ color: 'var(--text3)' }}>--</span>;
      const color = ir >= 75 ? '#10B981' : ir >= 50 ? '#F59E0B' : ir >= 25 ? '#F97316' : '#EF4444';
      return <span style={{ fontFamily: 'monospace', fontSize: 11, color }}>{ir}</span>;
    }},
    { key: 'ai_review', label: 'AI Review', width: 80, render: (r: Ticker) => {
      const pills: React.ReactElement[] = []
      if (r.incubator_llm_grade) {
        const gc = r.incubator_llm_grade === 'A' || r.incubator_llm_grade === 'B' ? '#22C55E' : r.incubator_llm_grade === 'C' ? '#F59E0B' : '#EF4444'
        pills.push(<span key="inc" style={{ fontSize: 7, fontWeight: 700, padding: '1px 4px', borderRadius: 3, background: `${gc}18`, color: gc, border: `1px solid ${gc}40` }}>{r.incubator_llm_grade} {r.incubator_llm_verdict === 'PROMOTE' ? '\u2191' : ''}</span>)
      }
      if (r.holdings_llm_health) {
        const hc = r.holdings_llm_health === 'STRONG' ? '#22C55E' : r.holdings_llm_health === 'STABLE' ? '#3B82F6' : r.holdings_llm_health === 'WATCH' ? '#F59E0B' : '#EF4444'
        pills.push(<span key="hld" style={{ fontSize: 7, fontWeight: 700, padding: '1px 4px', borderRadius: 3, background: `${hc}18`, color: hc, border: `1px solid ${hc}40` }}>{r.holdings_llm_health}{r.holdings_llm_action && r.holdings_llm_action !== 'HOLD' ? ` \u2192${r.holdings_llm_action}` : ''}</span>)
      }
      if (r.proposal_risk_grade) {
        const rc = r.proposal_risk_grade === 'A' || r.proposal_risk_grade === 'B' ? '#22C55E' : r.proposal_risk_grade === 'C' ? '#F59E0B' : '#EF4444'
        pills.push(<span key="risk" style={{ fontSize: 7, fontWeight: 700, padding: '1px 4px', borderRadius: 3, background: `${rc}18`, color: rc, border: `1px solid ${rc}40` }}>R:{r.proposal_risk_grade}</span>)
      }
      if (r.proposal_catalyst_grade) {
        const cc = r.proposal_catalyst_grade === 'A' || r.proposal_catalyst_grade === 'B' ? '#22C55E' : r.proposal_catalyst_grade === 'C' ? '#F59E0B' : '#EF4444'
        pills.push(<span key="cat" style={{ fontSize: 7, fontWeight: 700, padding: '1px 4px', borderRadius: 3, background: `${cc}18`, color: cc, border: `1px solid ${cc}40` }}>C:{r.proposal_catalyst_grade}</span>)
      }
      return pills.length > 0 ? <div style={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>{pills}</div> : <span style={{ color: 'var(--text3)', fontSize: 7 }}>--</span>
    }},
    { key: 'grade', label: 'Grd', width: 30, render: (r: Ticker) => <span style={{ fontWeight: 600, color: r.grade === 'A' ? 'var(--green)' : 'var(--text2)' }}>{r.grade}</span> },
    { key: 'rvol', label: 'RVOL', width: 45, align: 'right' as const, sortKey: (r: Ticker) => r.rvol, render: (r: Ticker) => (
      <span style={{ color: r.rvol >= 5 ? 'var(--green)' : 'var(--text2)' }}>{r.rvol.toFixed(1)}x</span>
    )},
    { key: 'price', label: 'Price', width: 55, align: 'right' as const, render: (r: Ticker) => '$' + r.price.toFixed(2) },
    { key: 'change_pct', label: 'Chg%', width: 55, align: 'right' as const, render: (r: Ticker) => (
      <span style={{ color: r.change_pct.startsWith('-') ? 'var(--red)' : 'var(--green)', fontWeight: 600 }}>{r.change_pct}%</span>
    )},
    { key: 'gap_pct', label: 'Gap%', width: 55, align: 'right' as const, render: (r: Ticker) => (
      <span style={{ color: r.gap_pct.startsWith('-') ? 'var(--red)' : 'var(--green)' }}>{r.gap_pct}%</span>
    )},
    { key: 'float_m', label: 'Float', width: 45, align: 'right' as const, render: (r: Ticker) => <span style={{ color: 'var(--text2)' }}>{r.float_m}M</span> },
    { key: 'sector', label: 'Sector', width: 80, render: (r: Ticker) => {
      const country = r.country || ''
      const flag = (!country || country === '\uD83C\uDDFA\uD83C\uDDF8' || country === 'United States') ? '' : country
      return (
        <span style={{ fontSize: 9, color: 'var(--text2)', display: 'flex', flexDirection: 'column', gap: 1 }}>
          <span style={{ fontWeight: 600, color: 'var(--text1)' }}>{flag}{flag ? ' ' : ''}{r.sector || '--'}</span>
          {r.vs_sector_pct != null && (
            <span style={{ fontSize: 8, color: r.vs_sector_pct >= 0 ? '#4ADE80' : '#F87171' }}>
              vs {r.sector_etf || 'sector'}: {r.vs_sector_pct >= 0 ? '+' : ''}{r.vs_sector_pct}%
            </span>
          )}
        </span>
      )
    }},
    { key: 'social', label: 'Social', width: 75, render: (r: Ticker) => {
      const label = r.social_sentiment || ''
      const color = label.includes('Very Bullish') ? '#4ADE80' : label.includes('Bullish') ? '#86EFAC' : label.includes('Bearish') ? '#F87171' : '#64748B'
      const bull = r.social_bullish_pct != null ? `${Math.round(r.social_bullish_pct)}%` : ''
      return label ? (
        <span style={{ fontSize: 9, display: 'flex', flexDirection: 'column', gap: 1 }}>
          <span style={{ fontWeight: 600, color }}>{label}</span>
          {(r.social_reddit || r.social_stocktwits) ? (
            <span style={{ fontSize: 8, color: '#64748B' }}>
              R:{r.social_reddit || 0} ST:{r.social_stocktwits || 0}{bull ? ` (${bull} bull)` : ''}
            </span>
          ) : null}
        </span>
      ) : <span style={{ fontSize: 9, color: '#475569' }}>--</span>
    }},
    { key: 'confluence', label: 'Confluence', width: 90, render: (r: Ticker) => {
      const cd = confluenceData[r.symbol]
      if (!cd?.confluence_tier) return <span style={{ fontSize: 9, color: '#475569' }}>--</span>
      return <ConfluenceBadge tier={cd.confluence_tier} bullishCount={cd.signals_bullish || 0} badges={cd.strategy_badges || []} compact />
    }},
    { key: 'catalyst', label: 'Catalyst', render: (r: Ticker) => (
      <span style={{ fontSize: 10, color: r.disqualified ? '#FCA5A5' : r.catalyst_verified === false ? '#F59E0B' : 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: 4, maxWidth: 280 }}>
        {r.disqualified && <span style={{ fontSize: 8, background: '#7F1D1D', color: '#FCA5A5', padding: '1px 4px', borderRadius: 2, fontWeight: 700, flexShrink: 0 }}>DQ</span>}
        {!r.disqualified && r.catalyst_verified === false && <span style={{ fontSize: 8, background: '#78350F', color: '#FCD34D', padding: '1px 4px', borderRadius: 2, fontWeight: 700, flexShrink: 0 }}>?</span>}
        {!r.disqualified && r.catalyst_verified === true && <span style={{ fontSize: 8, background: '#052E16', color: '#86EFAC', padding: '1px 4px', borderRadius: 2, fontWeight: 700, flexShrink: 0 }}>V</span>}
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.catalyst}</span>
      </span>
    )},
  ]

  return (
    <>
      <PageHeader title="Market Opportunities" subtitle={`Trade AI signals, regime context, opportunity ranking, and next actions | Run ${tai.run_label} | ${tai.run_date} | ${tai.current_run_scanned ?? tai.ticker_count} scanned${tai.universe_count ? ` | ${tai.universe_count} universe` : ''}`} />

      {/* Summary StateCards row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8, marginBottom: 12 }}>
        <StateCard title="GO Signals" value={tai.go_count} status="ready" description="Current run" compact />
        <StateCard title="WAIT Signals" value={tai.wait_count} status="waiting" description="Current run" compact />
        <StateCard title="NO GO" value={tai.avoid_count} status={tai.avoid_count > 0 ? 'blocked' : 'unknown'} description="Current run" compact />
        <StateCard title="VIX" value={tai.vix?.toFixed(1) ?? '--'} status={tai.vix != null ? (tai.vix > 25 ? 'blocked' : tai.vix > 18 ? 'warning' : 'fresh') : 'unknown'} compact />
        <StateCard title="Regime" value={tai.breadth || '--'} status={tai.breadth?.includes('Bull') ? 'ready' : tai.breadth?.includes('Bear') ? 'blocked' : 'waiting'} compact />
        <StateCard title="Last Run" value={tai.run_label} description={tai.run_date} status={runHealthToStatus(tai.run_health_status)} compact />
        <StateCard title="Top Ticker" value={tai.top_ticker || '--'} description={`Score: ${tai.top_score}`} status="ready" compact />
        <StateCard title="Deltas" value={tai.delta_events} description="vs prior run" status={tai.delta_events > 0 ? 'running' : 'unknown'} compact />
      </div>

      {/* Run health banner */}
      {tai.run_health_status && (
        <div style={{
          padding: '6px 14px', marginBottom: 8, borderRadius: 6, fontSize: 11, fontWeight: 600,
          background: tai.run_health_status === 'RUN_HEALTHY' ? 'rgba(34,197,94,0.08)' :
                      tai.run_health_status === 'RUN_UNDERFILLED' ? 'rgba(239,68,68,0.1)' : 'rgba(245,158,11,0.08)',
          border: `1px solid ${tai.run_health_status === 'RUN_HEALTHY' ? 'rgba(34,197,94,0.25)' :
                   tai.run_health_status === 'RUN_UNDERFILLED' ? 'rgba(239,68,68,0.25)' : 'rgba(245,158,11,0.25)'}`,
          color: tai.run_health_status === 'RUN_HEALTHY' ? '#4ADE80' :
                 tai.run_health_status === 'RUN_UNDERFILLED' ? '#F87171' : '#FBBF24',
        }}>
          <StatusBadge
            status={tai.run_health_status === 'RUN_HEALTHY' ? 'fresh' : tai.run_health_status === 'RUN_UNDERFILLED' ? 'blocked' : 'warning'}
            label={tai.run_health_status}
            size="md"
            style={{ marginRight: 8 }}
          />
          Run {tai.latest_run_label || tai.run_label} &middot; {tai.run_date} &middot; {tai.latest_run_symbols_scanned ?? tai.ticker_count} symbols
          {tai.run_health_status === 'RUN_UNDERFILLED' && (
            <span style={{ fontWeight: 400, opacity: 0.8 }}> -- Screener returned fewer symbols than target universe. Check Finviz filters or cookie freshness.</span>
          )}
          {tai.today_strategy_signal_count != null && ` | ${tai.today_strategy_signal_count} signals today`}
        </div>
      )}
      <div style={{ padding: '8px 14px', marginBottom: 12, background: 'rgba(74,144,244,0.08)', border: '1px solid rgba(74,144,244,0.2)', borderRadius: 8, fontSize: 11, color: '#4a90f4' }}>
        Scalp trades only -- execute in <strong>Taxable account</strong> (Fidelity cash account) or paper-trade. Do NOT use IRA accounts. Position size: risk $150/trade, target $300+. Grade: A = score &ge;45 (all criteria met), B = 35-44 (marginal), C = &lt;35. Deltas = tickers whose score changed vs previous run.
      </div>

      {/* Regime + VIX banner (kept for detail metrics beyond StateCards) */}
      <div style={{
        display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14,
      }}>
        <MetricTile label="VIX" value={tai.vix?.toFixed(1) ?? '--'} deltaColor={tai.vix != null ? (tai.vix > 25 ? 'var(--red)' : tai.vix > 18 ? 'var(--amber)' : 'var(--green)') : undefined} />
        <MetricTile label="Regime" value={`${regimeEmoji} ${tai.breadth}`} />
        <MetricTile label="Run GO" value={String(tai.go_count)} deltaColor="var(--green)" delta="current run" />
        <MetricTile label="Run WAIT" value={String(tai.wait_count)} deltaColor="var(--amber)" delta="current run" />
        <MetricTile label="Run NO GO" value={String(tai.avoid_count)} deltaColor={tai.avoid_count > 0 ? 'var(--red)' : 'var(--text3)'} delta="current run" />
        <MetricTile label="Universe" value={String(tai.universe_count ?? (tai.tickers || []).length)} delta="tracked symbols" />
        <MetricTile label="Top Ticker" value={tai.top_ticker || '--'} delta={`Score: ${tai.top_score}`} />
        <MetricTile label="Deltas" value={String(tai.delta_events)} delta="score/decision changes vs prior run" />
        <MetricTile label="Iris" value={irisStatus?.overall === 'ok' ? 'CLEAN' : `${(irisStatus?.checks || []).filter((c: any) => c.status === 'warn').length} WARN`}
          deltaColor={irisStatus?.overall === 'ok' ? 'var(--green)' : 'var(--amber)'}
          delta={irisStatus?.overall === 'ok' ? 'source integrity OK' : 'click to review'} />
      </div>

      {/* Live scalp feed */}
      <div style={{ marginBottom: 14 }}>
        <ScalpLiveFeed />
      </div>

      {/* Decision filter - using ActionButton primitives */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
        {['ALL', 'GO', 'WAIT'].map(f => (
          <ActionButton
            key={f}
            variant={filter === f ? 'primary' : 'secondary'}
            onClick={() => setFilter(f)}
            style={{
              fontFamily: 'var(--mono)',
              ...(filter === f && f === 'GO' ? { background: 'var(--green-dim)', color: 'var(--green)', borderColor: 'var(--green)' } : {}),
              ...(filter === f && f === 'WAIT' ? { background: 'var(--amber-dim)', color: 'var(--amber)', borderColor: 'var(--amber)' } : {}),
            }}
          >
            {f === 'ALL' ? 'Universe' : f} ({f !== 'ALL' ? (tai.tickers || []).filter(t => t.decision === f).length : (tai.tickers || []).length})
          </ActionButton>
        ))}
      </div>

      {/* TOS export */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
        {(['GO', 'WAIT', 'ALL'] as const).map(type => {
          const syms = type === 'ALL' ? (tai.tickers || []).map(t => t.symbol) : (tai.tickers || []).filter(t => t.decision === type).map(t => t.symbol)
          const text = syms.join(',')
          return (
            <div key={type} style={{ flex: 1, padding: '6px 10px', background: 'var(--bg3)', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
                <span style={{ fontSize: 8, color: type === 'GO' ? 'var(--green)' : type === 'WAIT' ? 'var(--amber)' : 'var(--text2)', fontWeight: 700 }}>{type === 'ALL' ? 'Universe' : type} ({syms.length})</span>
                {syms.length > 0 && (
                  <ActionButton
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta); setCopied(type); setTimeout(() => setCopied(null), 1500)
                    }}
                    style={{ fontSize: 8, padding: '1px 6px', ...(copied === type ? { background: 'var(--green-dim)', color: 'var(--green)' } : {}) }}
                  >
                    {copied === type ? 'Copied' : 'Copy'}
                  </ActionButton>
                )}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text0)', fontFamily: 'var(--mono)', wordBreak: 'break-all', userSelect: 'all', cursor: 'text', minHeight: 16 }}>
                {text || '--'}
              </div>
            </div>
          )
        })}
      </div>

      {/* Empty state if no tickers */}
      {tickers.length === 0 && (
        <div style={{ textAlign: 'center', padding: '40px 20px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', marginBottom: 12 }}>
          <div style={{ fontSize: 14, color: 'var(--text2)', marginBottom: 6 }}>No {filter === 'ALL' ? '' : filter + ' '}signals found</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>
            {filter !== 'ALL' ? 'Try switching to Universe view to see all signals.' : 'No tickers in the current run. Check screener health.'}
          </div>
        </div>
      )}

      {/* Main ticker table */}
      {tickers.length > 0 && (
        <DataGrid columns={columns} data={tickers} rowKey={r => r.symbol} maxHeight={350}
          onRowClick={r => { setSelectedTicker(r.symbol === selectedTicker?.symbol ? null : r); setParams(prev => { const p = new URLSearchParams(prev); p.set('symbol', r.symbol); return p }, { replace: true }) }} selectedKey={selectedTicker?.symbol} />
      )}

      {/* Setup detail drawer */}
      <DetailDrawer open={!!selectedTicker} onClose={() => setSelectedTicker(null)}
        title={selectedTicker?.symbol || ''} subtitle={`${selectedTicker?.decision} | Score ${selectedTicker?.score} | Grade ${selectedTicker?.grade}`}>
        {selectedTicker && (
          <>
            <DrawerSection title="Setup">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                <DrawerStat label="Decision" value={selectedTicker.decision} color={decisionColor[selectedTicker.decision]} />
                <DrawerStat label="Score" value={String(selectedTicker.score)} color={selectedTicker.score >= 40 ? 'var(--green)' : selectedTicker.score >= 30 ? 'var(--amber)' : 'var(--text2)'} />
                <DrawerStat label="Grade" value={`${selectedTicker.grade} -- ${gradeLegend[selectedTicker.grade] || 'Unknown'}`} color={selectedTicker.grade === 'A' ? 'var(--green)' : 'var(--text2)'} />
                <DrawerStat label="RVOL" value={selectedTicker.rvol.toFixed(1) + 'x'} color={selectedTicker.rvol >= 5 ? 'var(--green)' : 'var(--text2)'} />
                <DrawerStat label="Price" value={'$' + selectedTicker.price.toFixed(2)} />
                <DrawerStat label="Change" value={selectedTicker.change_pct + '%'} color={selectedTicker.change_pct.startsWith('-') ? 'var(--red)' : 'var(--green)'} />
                <DrawerStat label="Gap" value={selectedTicker.gap_pct + '%'} color={selectedTicker.gap_pct.startsWith('-') ? 'var(--red)' : 'var(--green)'} />
                <DrawerStat label="Float" value={selectedTicker.float_m + 'M'} />
              </div>
            </DrawerSection>

            <DrawerSection title="Position Sizing">
              <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.6 }}>
                <div>Risk per trade: <strong style={{ color: 'var(--text0)' }}>$150</strong> | Target: <strong style={{ color: 'var(--green)' }}>$300+</strong> (2:1 R:R minimum)</div>
                {selectedTicker.price > 0 && (
                  <div style={{ marginTop: 4 }}>
                    Suggested shares: <strong style={{ color: 'var(--accent)' }}>{Math.floor(150 / (selectedTicker.price * 0.05))}</strong> (assuming 5% stop)
                    | Max position: <strong>{fmt$(Math.floor(150 / (selectedTicker.price * 0.05)) * selectedTicker.price)}</strong>
                  </div>
                )}
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>Execute in Taxable account only. Do not hold overnight unless A-grade with volume confirmation.</div>
              </div>
            </DrawerSection>

            {/* Disqualification warning */}
            {selectedTicker.disqualified && (
              <div style={{ background: '#450A0A', border: '1px solid #DC2626', borderRadius: 6, padding: '10px 14px', margin: '8px 0', color: '#FCA5A5' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <SeverityBadge severity="critical" label="AUTO-DISQUALIFIED" size="md" />
                </div>
                <div style={{ fontSize: 12 }}>{selectedTicker.disqualification_reason}</div>
              </div>
            )}

            <DrawerSection title="Catalyst">
              <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5 }}>
                {selectedTicker.catalyst || 'No catalyst data available'}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
                {selectedTicker.catalyst_verified === false && (
                  <StatusBadge status="blocked" label="CATALYST UNVERIFIED" title="Headline may not relate to this ticker" />
                )}
                {selectedTicker.catalyst_verified === true && (
                  <StatusBadge status="complete" label="Catalyst verified" />
                )}
              </div>
            </DrawerSection>

            {/* Industry */}
            <DrawerSection title="Industry">
              {selectedTicker.industry && selectedTicker.industry !== 'Unclassified' ? (
                <span style={{ fontSize: 11, color: 'var(--text1)' }}>{selectedTicker.industry}</span>
              ) : (
                <StatusBadge status="warning" label="Industry unclassified" />
              )}
            </DrawerSection>

            {/* Agent Critique */}
            {selectedTicker.critic_verdict && (
              <DrawerSection title="Agent Critique">
                <div style={{
                  padding: '10px 14px', borderRadius: 6, marginBottom: 8,
                  background: selectedTicker.critic_verdict === 'BLOCK' ? '#450A0A' :
                              selectedTicker.critic_verdict === 'DOWNGRADE' ? '#431407' : '#052E16',
                  border: `1px solid ${
                    selectedTicker.critic_verdict === 'BLOCK' ? '#DC2626' :
                    selectedTicker.critic_verdict === 'DOWNGRADE' ? '#EA580C' : '#16A34A'}`
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <SeverityBadge
                      severity={selectedTicker.critic_verdict === 'BLOCK' ? 'critical' : selectedTicker.critic_verdict === 'DOWNGRADE' ? 'high' : 'low'}
                      label={selectedTicker.critic_verdict === 'BLOCK' ? 'BLOCKED' : selectedTicker.critic_verdict === 'DOWNGRADE' ? 'DOWNGRADED' : 'CONFIRMED'}
                      size="md"
                    />
                    {selectedTicker.critic_confidence != null && (
                      <span style={{ fontWeight: 400, fontSize: 11, opacity: 0.8, color: 'var(--text2)' }}>
                        {Math.round(selectedTicker.critic_confidence * 100)}% confidence
                      </span>
                    )}
                  </div>
                  {selectedTicker.critic_reasoning && (
                    <div style={{ fontSize: 12, color: '#CBD5E1', lineHeight: 1.4, marginTop: 4 }}>
                      {selectedTicker.critic_reasoning}
                    </div>
                  )}
                </div>
                {selectedTicker.decision_changed && selectedTicker.original_decision && (
                  <div style={{ fontSize: 11, color: '#94A3B8', marginTop: 4 }}>
                    Original decision: <span style={{ textDecoration: 'line-through' }}>{selectedTicker.original_decision}</span> &rarr; {selectedTicker.decision}
                  </div>
                )}
              </DrawerSection>
            )}

            {/* Context: sector, country, performance */}
            <DrawerSection title="Context">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                <div style={{ background: '#0B1120', borderRadius: 6, padding: '8px 10px' }}>
                  <div style={{ fontSize: 9, color: '#64748B', marginBottom: 2 }}>SECTOR</div>
                  <div style={{ fontSize: 12, color: 'var(--text0)', fontWeight: 600 }}>{selectedTicker.sector || selectedTicker.industry || 'Unknown'}</div>
                  {selectedTicker.sector_etf && <div style={{ fontSize: 10, color: '#64748B' }}>{selectedTicker.sector_etf}</div>}
                </div>
                <div style={{ background: '#0B1120', borderRadius: 6, padding: '8px 10px' }}>
                  <div style={{ fontSize: 9, color: '#64748B', marginBottom: 2 }}>COUNTRY</div>
                  <div style={{ fontSize: 12, color: 'var(--text0)', fontWeight: 600 }}>{selectedTicker.country || 'US'}</div>
                </div>
                <div style={{ background: '#0B1120', borderRadius: 6, padding: '8px 10px' }}>
                  <div style={{ fontSize: 9, color: '#64748B', marginBottom: 2 }}>1M PERF</div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: selectedTicker.ticker_perf_1m != null ? (selectedTicker.ticker_perf_1m >= 0 ? '#4ADE80' : '#F87171') : '#64748B' }}>
                    {selectedTicker.ticker_perf_1m != null ? `${selectedTicker.ticker_perf_1m >= 0 ? '+' : ''}${selectedTicker.ticker_perf_1m}%` : '--'}
                  </div>
                </div>
                <div style={{ background: '#0B1120', borderRadius: 6, padding: '8px 10px' }}>
                  <div style={{ fontSize: 9, color: '#64748B', marginBottom: 2 }}>VS {selectedTicker.sector_etf || 'SECTOR'}</div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: selectedTicker.vs_sector_pct != null ? (selectedTicker.vs_sector_pct >= 0 ? '#4ADE80' : '#F87171') : '#64748B' }}>
                    {selectedTicker.vs_sector_pct != null ? `${selectedTicker.vs_sector_pct >= 0 ? '+' : ''}${selectedTicker.vs_sector_pct}%` : '--'}
                  </div>
                  {selectedTicker.sector_perf_1m != null && <div style={{ fontSize: 10, color: '#64748B' }}>{selectedTicker.sector_etf}: {selectedTicker.sector_perf_1m >= 0 ? '+' : ''}{selectedTicker.sector_perf_1m}%</div>}
                </div>
              </div>
              {selectedTicker.country && selectedTicker.country !== 'United States' && selectedTicker.country !== '\uD83C\uDDFA\uD83C\uDDF8' && selectedTicker.country !== '' && (
                <div style={{ marginTop: 6, padding: '5px 8px', borderRadius: 4, background: '#1C1300', border: '1px solid #78350F', fontSize: 11, color: '#FCD34D' }}>
                  <SeverityBadge severity="medium" label="Foreign Issuer" style={{ marginRight: 6 }} />
                  ({selectedTicker.country}) -- additional regulatory and liquidity risks
                </div>
              )}
            </DrawerSection>

            {/* AI Review section */}
            {(selectedTicker.incubator_llm_grade || selectedTicker.holdings_llm_health || selectedTicker.proposal_llm_stage) && (
              <DrawerSection title="AI Review (Local LLM)">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                  {selectedTicker.incubator_llm_grade && (
                    <div style={{ background: '#0B1120', borderRadius: 6, padding: '8px 10px' }}>
                      <div style={{ fontSize: 9, color: '#64748B', marginBottom: 2 }}>INCUBATOR SCREEN</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: selectedTicker.incubator_llm_grade === 'A' || selectedTicker.incubator_llm_grade === 'B' ? '#22C55E' : selectedTicker.incubator_llm_grade === 'C' ? '#F59E0B' : '#EF4444' }}>
                        {selectedTicker.incubator_llm_grade} -- {selectedTicker.incubator_llm_verdict}
                      </div>
                    </div>
                  )}
                  {selectedTicker.holdings_llm_health && (
                    <div style={{ background: '#0B1120', borderRadius: 6, padding: '8px 10px' }}>
                      <div style={{ fontSize: 9, color: '#64748B', marginBottom: 2 }}>HOLDINGS HEALTH</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: selectedTicker.holdings_llm_health === 'STRONG' ? '#22C55E' : selectedTicker.holdings_llm_health === 'STABLE' ? '#3B82F6' : selectedTicker.holdings_llm_health === 'WATCH' ? '#F59E0B' : '#EF4444' }}>
                        {selectedTicker.holdings_llm_health}{selectedTicker.holdings_llm_action && selectedTicker.holdings_llm_action !== 'HOLD' ? ` \u2192 ${selectedTicker.holdings_llm_action}` : ''}
                      </div>
                    </div>
                  )}
                  {selectedTicker.proposal_risk_grade && (
                    <div style={{ background: '#0B1120', borderRadius: 6, padding: '8px 10px' }}>
                      <div style={{ fontSize: 9, color: '#64748B', marginBottom: 2 }}>RISK GRADE</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: selectedTicker.proposal_risk_grade === 'A' || selectedTicker.proposal_risk_grade === 'B' ? '#22C55E' : selectedTicker.proposal_risk_grade === 'C' ? '#F59E0B' : '#EF4444' }}>
                        {selectedTicker.proposal_risk_grade}
                      </div>
                    </div>
                  )}
                  {selectedTicker.proposal_catalyst_grade && (
                    <div style={{ background: '#0B1120', borderRadius: 6, padding: '8px 10px' }}>
                      <div style={{ fontSize: 9, color: '#64748B', marginBottom: 2 }}>CATALYST GRADE</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: selectedTicker.proposal_catalyst_grade === 'A' || selectedTicker.proposal_catalyst_grade === 'B' ? '#22C55E' : selectedTicker.proposal_catalyst_grade === 'C' ? '#F59E0B' : '#EF4444' }}>
                        {selectedTicker.proposal_catalyst_grade}
                      </div>
                    </div>
                  )}
                  {selectedTicker.proposal_llm_decision && (
                    <div style={{ background: '#0B1120', borderRadius: 6, padding: '8px 10px' }}>
                      <div style={{ fontSize: 9, color: '#64748B', marginBottom: 2 }}>LLM DECISION</div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: selectedTicker.proposal_llm_decision === 'APPROVE_READY' ? '#22C55E' : selectedTicker.proposal_llm_decision === 'CAUTIOUS_TEST' ? '#F59E0B' : '#EF4444' }}>
                        {selectedTicker.proposal_llm_decision} ({selectedTicker.proposal_llm_confidence}%)
                      </div>
                    </div>
                  )}
                </div>
              </DrawerSection>
            )}

            <DrawerSection title="Links & Drillthrough">
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <ActionButton variant="secondary" onClick={() => navigate(`/research?symbol=${selectedTicker.symbol}`)}>Open Research</ActionButton>
                <ActionButton variant="secondary" onClick={() => navigate(`/watchlist?symbol=${selectedTicker.symbol}`)}>Open Watchlist</ActionButton>
                <a href={`https://finviz.com/quote.ashx?t=${selectedTicker.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Finviz</a>
                <a href={`https://finance.yahoo.com/quote/${selectedTicker.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Yahoo</a>
                <a href={`https://www.tradingview.com/symbols/${selectedTicker.symbol}/`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Chart</a>
              </div>
            </DrawerSection>
          </>
        )}
      </DetailDrawer>

      {/* Run context + What Changed */}
      {tai.run_date && (
        <div style={{ display: 'flex', gap: 10, marginTop: 10, marginBottom: 4, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: 10, color: 'var(--text2)', padding: '3px 10px', background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius)' }}>
            Run {tai.run_label} | {tai.run_date}
          </span>
          {tai.delta_events > 0 && (
            <StatusBadge status="running" label={`${tai.delta_events} score/decision change${tai.delta_events !== 1 ? 's' : ''} since prior run`} size="md" />
          )}
          {tai.delta_events === 0 && (
            <StatusBadge status="unknown" label="No score drift detected" size="md" />
          )}
        </div>
      )}

      {/* Bottom panels */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>

        {/* Run history sparkline */}
        <div>
          <SectionHeader title="Run History" count={tai.run_history.length} />
          <Card>
            {tai.run_history.length > 1 ? (
              <BarChartJS
                labels={tai.run_history.map(r => r.label).reverse()}
                data={tai.run_history.map(r => r.go).reverse()}
                colors={tai.run_history.map(r => r.go > 0 ? '#0ecb81' : '#4e5a6e').reverse()}
                height={80}
              />
            ) : (
              <div style={{ color: 'var(--text3)', fontSize: 11 }}>Single run only</div>
            )}
            <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
              {tai.run_history.map((r, i) => (
                <div key={i} style={{ fontSize: 9, color: 'var(--text3)' }}>
                  <span style={{ fontWeight: 600 }}>{r.label}</span> GO:{r.go} W:{r.wait}
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* Sector matrix */}
        <div>
          <SectionHeader title="Sector Distribution" count={Object.keys(tai.sectors).length} />
          <Card>
            {Object.keys(tai.sectors).length === 0 ? (
              <div style={{ color: 'var(--text3)', fontSize: 11, textAlign: 'center', padding: 12 }}>No sector data available</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {Object.entries(tai.sectors).map(([sec, count]) => (
                  <div key={sec} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ width: 100, fontSize: 10, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sec}</span>
                    <div style={{ flex: 1, height: 8, background: 'var(--bg3)', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{ width: `${(count / Math.max(...Object.values(tai.sectors))) * 100}%`, height: '100%', background: 'var(--accent)', opacity: 0.6, borderRadius: 3 }} />
                    </div>
                    <span style={{ width: 20, fontSize: 10, color: 'var(--text1)', textAlign: 'right', fontWeight: 600 }}>{count}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>

    </>
  )
}
```

## Acceptance Checklist

- [ ] Title changed from "Trade AI" to "Market Opportunities"
- [ ] Subtitle includes "Trade AI signals, regime context, opportunity ranking, and next actions"
- [ ] StateCard used for top summary metrics (GO, WAIT, NO GO, VIX, Regime, Last Run, Top Ticker, Deltas) with `title=` prop (NOT `label=`)
- [ ] StatusBadge used for GO/WAIT/NO_GO decisions per ticker in table column via `status=` prop
- [ ] StatusBadge used for run health banner, catalyst verified/unverified, delta drift indicator
- [ ] SeverityBadge used for disqualification warning, critic verdict, foreign issuer warning
- [ ] ActionButton uses children pattern (`<ActionButton>Text</ActionButton>`) -- NO `label=` prop anywhere
- [ ] ActionButton used for decision filter buttons (ALL/GO/WAIT)
- [ ] ActionButton used for TOS copy buttons
- [ ] ActionButton used for drawer drillthrough buttons (Open Research, Open Watchlist)
- [ ] All existing TypeScript interfaces preserved identically (Ticker, RunHistoryItem, TradeAIData)
- [ ] `useApi('/api/v2/trade-ai')` call preserved unchanged
- [ ] All existing fetch() calls preserved (iris/integrity, indicators/batch)
- [ ] All existing useEffect hooks preserved
- [ ] All existing state variables preserved
- [ ] DataGrid columns and rendering logic preserved
- [ ] DetailDrawer with all DrawerSections preserved
- [ ] ConfluenceBadge rendering preserved
- [ ] BarChartJS run history chart preserved
- [ ] Sector distribution chart preserved
- [ ] ScalpLiveFeed component preserved
- [ ] Empty states added for: loading, no tickers, no sector data
- [ ] No trading execution buttons present
- [ ] No `<AgentChip agent=` anywhere (correct: `name=`)
- [ ] No `<ActionButton label=` anywhere (correct: children)
- [ ] No `<StateCard label=` anywhere (correct: `title=`)
- [ ] All imports added for StatusBadge, SeverityBadge, ActionButton, StateCard
- [ ] Position sizing info preserved in drawer
- [ ] Grade legend preserved
- [ ] TOS export copy-to-clipboard preserved

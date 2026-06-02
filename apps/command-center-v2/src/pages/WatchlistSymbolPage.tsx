import { useParams, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import InlineDualOpinionPanel from '../components/InlineDualOpinionPanel'

const REC_COLOR: Record<string, string> = {
  BUY: '#0ecb81', ADD: '#0ecb81', HOLD: '#4a90f4', NEUTRAL: '#8891a0',
  TRIM: '#f6465d', SELL: '#f6465d', AVOID: '#f6465d',
  RESEARCH_MORE: '#f0b90b', IGNORE: '#525c6a',
}

const TRADE_TYPE_STYLE: Record<string, { bg: string; color: string }> = {
  INCOME: { bg: 'rgba(13,148,136,.12)', color: '#0D9488' },
  LONG: { bg: 'rgba(22,163,74,.12)', color: '#16A34A' },
  SWING: { bg: 'rgba(217,119,6,.12)', color: '#D97706' },
  SHORT: { bg: 'rgba(220,38,38,.12)', color: '#DC2626' },
  WATCH: { bg: 'rgba(100,116,139,.1)', color: '#64748B' },
}

const lbl: React.CSSProperties = { fontSize: 10, color: '#64748B', fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: '.04em', fontWeight: 700, marginBottom: 6 }
const card: React.CSSProperties = { background: '#0F172A', border: '1px solid #1E293B', borderRadius: 8, padding: 16, marginBottom: 14 }

export default function WatchlistSymbolPage() {
  const { symbol } = useParams<{ symbol: string }>()
  const navigate = useNavigate()
  const [ctx, setCtx] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!symbol) return
    setLoading(true)
    fetch(`/api/v2/watchlist/context/${symbol}`)
      .then(r => r.json())
      .then(d => { if (!d.ok) throw new Error(d.error); setCtx(d.data) })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [symbol])

  if (loading) return <div style={{ padding: 24, color: '#94A3B8' }}>Loading {symbol}...</div>
  if (error) return <div style={{ padding: 24, color: '#DC2626' }}>Error: {error}</div>
  if (!ctx) return null

  const synthesis = ctx.synthesis
  const sc = ctx.strategy_card || {}
  const isLLMError = (synthesis?.synthesis_narrative || '').includes('LLM error') ||
    (synthesis?.synthesis_narrative || '').includes('All providers failed')
  const ttStyle = TRADE_TYPE_STYLE[ctx.trade_type] || TRADE_TYPE_STYLE.WATCH

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px' }}>

      {/* Hermes Second Opinion */}
      <InlineDualOpinionPanel symbol={symbol} compact={false} />

      {/* HEADER */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
        <h1 style={{ fontSize: 28, fontWeight: 700, color: '#E2EAF4', fontFamily: 'monospace', margin: 0 }}>{symbol}</h1>
        {synthesis?.recommendation && !isLLMError && (
          <span style={{ fontSize: 13, fontWeight: 700, padding: '3px 10px', borderRadius: 4, background: `color-mix(in srgb, ${REC_COLOR[synthesis.recommendation] || '#64748B'} 15%, transparent)`, color: REC_COLOR[synthesis.recommendation] || '#64748B' }}>
            {synthesis.recommendation}
          </span>
        )}
        {ctx.trade_type !== 'WATCH' && (
          <span style={{ fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 3, background: ttStyle.bg, color: ttStyle.color }}>{ctx.trade_type}</span>
        )}
        {ctx.in_portfolio && (
          <span style={{ background: 'rgba(220,38,38,0.15)', color: '#DC2626', border: '1px solid rgba(220,38,38,0.3)', fontSize: 11, fontFamily: 'monospace', padding: '3px 8px', borderRadius: 4 }}>
            HELD {ctx.portfolio_weight?.toFixed(1)}%
          </span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <a href={`https://finviz.com/quote.ashx?t=${symbol}`} target="_blank" rel="noreferrer" style={{ color: '#2E86D4', fontSize: 12, textDecoration: 'none', border: '1px solid #2E86D4', padding: '4px 10px', borderRadius: 4 }}>Finviz</a>
          <a href={`https://finance.yahoo.com/quote/${symbol}`} target="_blank" rel="noreferrer" style={{ color: '#64748B', fontSize: 12, textDecoration: 'none', border: '1px solid #334155', padding: '4px 10px', borderRadius: 4 }}>Yahoo</a>
          <button onClick={() => navigate('/watchlist')} style={{ background: 'transparent', color: '#64748B', border: '1px solid #334155', padding: '4px 10px', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}>Back</button>
        </div>
      </div>

      {/* SUMMARY VERDICT */}
      {ctx.summary_verdict && (
        <div style={card}>
          <p style={{ color: '#94A3B8', fontStyle: 'italic', fontSize: 14, margin: '0 0 12px', lineHeight: 1.6 }}>{ctx.summary_verdict}</p>
          <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
            {[
              ['CONFIDENCE', synthesis?.confidence ? `${Math.round(synthesis.confidence * 100)}%` : '—'],
              ['AGENT AGREE', ctx.agent_agree || '—'],
              ['IN PORTFOLIO', ctx.in_portfolio ? 'YES' : 'NO'],
              ['PORTFOLIO VALUE', ctx.portfolio_value ? `$${ctx.portfolio_value.toLocaleString()}` : '—'],
            ].map(([k, v]) => (
              <div key={k as string}>
                <div style={lbl}>{k as string}</div>
                <div style={{ fontSize: 18, fontFamily: 'monospace', color: '#E2EAF4', fontWeight: 700 }}>{v as string}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* LLM ERROR */}
      {isLLMError && (
        <div style={{ ...card, background: 'rgba(220,38,38,0.06)', borderColor: 'rgba(220,38,38,0.3)' }}>
          <div style={{ color: '#DC2626', fontFamily: 'monospace', fontSize: 12, marginBottom: 6 }}>ANALYSIS INCOMPLETE</div>
          <p style={{ color: '#94A3B8', fontSize: 13, margin: '0 0 10px' }}>LLM providers were unavailable when this analysis ran. The recommendation is not valid.</p>
          <button onClick={() => { fetch(`/api/v2/watchlist/${symbol}/requeue`, { method: 'POST' }).then(() => alert('Re-queued')) }} style={{ background: '#1E3A5F', color: 'white', border: 'none', padding: '8px 16px', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}>Re-queue Analysis</button>
        </div>
      )}

      {/* TWO-COLUMN: Strategy + Sector */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
        {/* Strategy Card */}
        <div style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <span style={{ ...lbl, margin: 0 }}>TRADE PLAN</span>
            {sc.account_fit && (
              <span style={{ color: '#0D9488', fontSize: 10, fontFamily: 'monospace', marginLeft: 'auto', border: '1px solid #0D9488', padding: '2px 6px', borderRadius: 3 }}>{sc.account_fit}</span>
            )}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 10, marginBottom: 12 }}>
            {[
              { label: 'ENTRY', value: sc.ideal_entry, color: '#16A34A' },
              { label: 'TARGET', value: sc.target_price, color: '#2E86D4' },
              { label: 'STOP', value: sc.stop_loss, color: '#DC2626' },
              { label: 'R:R', value: sc.risk_reward, color: '#E2EAF4' },
            ].map(({ label, value, color }) => (
              <div key={label}>
                <div style={{ fontSize: 9, color: '#64748B', fontFamily: 'monospace' }}>{label}</div>
                <div style={{ fontSize: 18, fontFamily: 'monospace', fontWeight: 700, color: value ? color : '#374151' }}>
                  {value ? (label === 'R:R' ? `${Number(value).toFixed(1)}:1` : `$${Number(value).toFixed(2)}`) : '—'}
                </div>
              </div>
            ))}
          </div>
          {(sc.support || sc.resistance) && (
            <div style={{ display: 'flex', gap: 24, fontSize: 12, color: '#64748B', paddingTop: 8, borderTop: '1px solid #1E293B' }}>
              {sc.support && <span>Support: <span style={{ color: '#E2EAF4' }}>${Number(sc.support).toFixed(2)}</span></span>}
              {sc.resistance && <span>Resistance: <span style={{ color: '#E2EAF4' }}>${Number(sc.resistance).toFixed(2)}</span></span>}
            </div>
          )}
          {!sc.ideal_entry && !sc.stop_loss && (
            <div style={{ color: '#6B7280', fontSize: 12, fontStyle: 'italic', marginTop: 8 }}>Entry/stop pending — Escalate to Alex for a trade plan</div>
          )}
        </div>

        {/* Sector Comparison */}
        <div style={card}>
          <div style={lbl}>SECTOR CONTEXT</div>
          {ctx.sector_comparison ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div><div style={{ fontSize: 9, color: '#64748B' }}>SECTOR</div><div style={{ fontSize: 14, color: '#E2EAF4' }}>{ctx.sector_comparison.sector || '—'}</div></div>
              <div><div style={{ fontSize: 9, color: '#64748B' }}>ETF</div><div style={{ fontSize: 14, color: '#E2EAF4' }}>{ctx.sector_comparison.sector_etf || '—'}</div></div>
              <div><div style={{ fontSize: 9, color: '#64748B' }}>TICKER 1M</div><div style={{ fontSize: 14, color: '#E2EAF4', fontFamily: 'monospace' }}>{ctx.sector_comparison.ticker_perf_1m || '—'}</div></div>
              <div><div style={{ fontSize: 9, color: '#64748B' }}>SECTOR 1M</div><div style={{ fontSize: 14, color: '#E2EAF4', fontFamily: 'monospace' }}>{ctx.sector_comparison.sector_perf_1m || '—'}</div></div>
            </div>
          ) : <div style={{ color: '#64748B', fontSize: 12 }}>No sector data available</div>}
          {ctx.conflict?.is_conflict && (
            <div style={{ marginTop: 12, padding: 10, background: 'rgba(246,70,93,.06)', border: '1px solid rgba(246,70,93,.2)', borderRadius: 6 }}>
              <div style={{ fontSize: 10, color: '#f6465d', fontWeight: 700, marginBottom: 4 }}>AGENT CONFLICT</div>
              <div style={{ fontSize: 12, color: '#CBD5E1' }}>{ctx.conflict.explanation}</div>
            </div>
          )}
        </div>
      </div>

      {/* AGENT NARRATIVES — full, no truncation */}
      {ctx.agent_results?.length > 0 && (
        <div style={card}>
          <div style={lbl}>AGENT NARRATIVES ({ctx.agent_results.length})</div>
          {ctx.agent_results.map((agent: any, i: number) => (
            <div key={i} style={{ padding: '14px 0', borderBottom: i < ctx.agent_results.length - 1 ? '1px solid #1E293B' : 'none' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                <span style={{ fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 4, background: `color-mix(in srgb, ${REC_COLOR[agent.recommendation] || '#64748B'} 15%, transparent)`, color: REC_COLOR[agent.recommendation] || '#64748B' }}>
                  {(agent.agent_name || '').replace('_agent', '').replace('_research', '').replace('_allocation', '').toUpperCase()}
                </span>
                <span style={{ fontWeight: 700, fontSize: 14, color: REC_COLOR[agent.recommendation] || '#94A3B8' }}>{agent.recommendation}</span>
                <span style={{ color: '#64748B', fontSize: 12 }}>{agent.confidence_score ? `${Math.round(agent.confidence_score * 100)}%` : ''}</span>
                <span style={{ color: '#6B7280', fontSize: 11, marginLeft: 'auto' }}>{agent.created_at?.substring(0, 10)}</span>
              </div>
              <p style={{ color: '#CBD5E1', fontSize: 14, lineHeight: 1.7, margin: 0, whiteSpace: 'pre-wrap' }}>
                {agent.full_narrative || agent.summary || 'No narrative'}
              </p>
              {agent.reason_codes?.length > 0 && (
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 8 }}>
                  {agent.reason_codes.map((tag: string, ti: number) => (
                    <span key={ti} style={{ fontSize: 9, padding: '2px 8px', borderRadius: 99, background: 'rgba(74,144,244,.08)', color: '#4a90f4' }}>{tag}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* SYNTHESIS (full — if not LLM error) */}
      {synthesis && !isLLMError && (
        <div style={card}>
          <div style={lbl}>FINAL SYNTHESIS</div>
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 10 }}>
            <span style={{ fontSize: 22, fontWeight: 800, color: REC_COLOR[synthesis.recommendation] || '#E2EAF4' }}>{synthesis.recommendation}</span>
            <span style={{ color: '#64748B', fontSize: 12 }}>Confidence: {synthesis.confidence ? `${Math.round(synthesis.confidence * 100)}%` : '?'}</span>
            {synthesis.next_review_date && <span style={{ color: '#64748B', fontSize: 12 }}>Review: {synthesis.next_review_date}</span>}
          </div>
          <p style={{ color: '#CBD5E1', fontSize: 14, lineHeight: 1.7, margin: 0 }}>
            {synthesis.synthesis_narrative || synthesis.action || 'No narrative'}
          </p>
          {synthesis.conflicts && (
            <div style={{ marginTop: 10, fontSize: 12, color: '#D97706' }}>Conflicts: {JSON.stringify(synthesis.conflicts)}</div>
          )}
        </div>
      )}

      {/* NEWS */}
      {(ctx.news?.length > 0 || ctx.sector_news?.length > 0) && (
        <div style={card}>
          <div style={lbl}>RECENT INTELLIGENCE ({(ctx.news?.length || 0) + (ctx.sector_news?.length || 0)})</div>
          {[...(ctx.news || []), ...(ctx.sector_news || [])].map((item: any, i: number) => (
            <div key={i} style={{ padding: '8px 0', borderBottom: '1px solid #1E293B', display: 'flex', alignItems: 'flex-start', gap: 10 }}>
              {item.sentiment && (
                <span style={{ fontSize: 10, color: item.sentiment === 'positive' ? '#16A34A' : item.sentiment === 'negative' ? '#DC2626' : '#64748B', fontFamily: 'monospace', minWidth: 30 }}>
                  {item.sentiment === 'positive' ? '+' : item.sentiment === 'negative' ? '-' : '~'}
                </span>
              )}
              <span style={{ color: '#CBD5E1', fontSize: 13, flex: 1 }}>{item.title}</span>
              <span style={{ color: '#6B7280', fontSize: 11, whiteSpace: 'nowrap' }}>{item.source}</span>
            </div>
          ))}
        </div>
      )}

      {/* INTEL WHITEBOARD */}
      {ctx.intel?.length > 0 && (
        <div style={card}>
          <div style={lbl}>INTELLIGENCE WHITEBOARD ({ctx.intel.length})</div>
          {ctx.intel.map((item: any, i: number) => (
            <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid #1E293B', display: 'flex', gap: 8, fontSize: 12 }}>
              <span style={{ color: '#64748B', minWidth: 60 }}>{item.source_type}</span>
              <span style={{ color: '#CBD5E1', flex: 1 }}>{item.title}</span>
              <span style={{ color: '#64748B' }}>Q:{item.quality_score}</span>
            </div>
          ))}
        </div>
      )}

      {/* ACTION BAR */}
      <div style={{ display: 'flex', gap: 10, paddingTop: 14, borderTop: '1px solid #1E293B' }}>
        <button onClick={() => { fetch(`/api/v2/watchlist/submit`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbols: [symbol], agent: 'full_chain', request_type: 'research', note: 'full_page_review' }) }).then(() => alert(`${symbol} submitted to full chain`)) }}
          style={{ flex: 2, background: 'linear-gradient(135deg,#7C3AED,#1E6FBF)', color: 'white', padding: 12, borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>
          Escalate to Alex (Full Chain)
        </button>
        {ctx.conflict?.is_conflict && (
          <button onClick={() => { fetch('/api/v2/debates/trigger', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol, trigger: 'manual' }) }).then(() => alert('Debate queued')) }}
            style={{ flex: 1, background: '#1E293B', color: 'white', padding: 12, borderRadius: 6, border: '1px solid #334155', cursor: 'pointer', fontSize: 13 }}>
            Force Debate
          </button>
        )}
        <button onClick={() => navigate('/watchlist')} style={{ flex: 1, background: 'transparent', color: '#64748B', padding: 12, borderRadius: 6, border: '1px solid #334155', cursor: 'pointer', fontSize: 13 }}>
          Back to Watchlist
        </button>
      </div>
    </div>
  )
}

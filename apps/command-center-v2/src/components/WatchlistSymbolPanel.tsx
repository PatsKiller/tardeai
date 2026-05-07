import { useState, useEffect } from 'react'

interface StrategyCardData {
  trade_type: string; strategy_label: string; account_fit: string
  ideal_entry: number | null; stop_loss: number | null; target_price: number | null
  risk_reward: number | null; support: number | null; resistance: number | null
  why_added: string; days_watched: number
}

interface ContextData {
  symbol: string
  agent_results: any[]
  synthesis: any | null
  strategy: any | null
  strategy_card?: StrategyCardData | null
  news: any[]
  holdings: any[]
  intel: any[]
  outcomes: any[]
  macro: any
  conflict: { is_conflict: boolean; type: string; explanation: string; buyers?: any[]; sellers?: any[]; data_gaps?: any[] }
  trade_type?: string
  sector_comparison?: { sector: string; sector_etf: string; ticker_perf_1m: string; sector_perf_1m: string } | null
  sector_news?: any[]
  summary_verdict?: string
  agent_agree?: string
  in_portfolio?: boolean
  portfolio_weight?: number
  portfolio_value?: number
}

const REC_COLOR: Record<string, string> = {
  BUY: '#0ecb81', ADD: '#0ecb81', HOLD: '#4a90f4', NEUTRAL: '#8891a0',
  TRIM: '#f6465d', SELL: '#f6465d', AVOID: '#f6465d',
  RESEARCH_MORE: '#f0b90b', IGNORE: '#525c6a',
}
const lbl: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em', fontWeight: 700 }
const fmt$ = (v: number) => v != null ? `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : '—'

function dedupeNarrative(text: string | null | undefined): string {
  if (!text || text.length < 50) return text || ''
  const sentences = text.split(/(?<=[.!?])\s+/)
  const seen = new Set<string>()
  return sentences.filter(s => {
    const key = s.trim().substring(0, 60)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }).join(' ')
}

const TRADE_TYPE_COLOR: Record<string, { bg: string; color: string }> = {
  INCOME: { bg: 'rgba(13,148,136,.12)', color: '#0D9488' },
  SWING: { bg: 'rgba(217,119,6,.12)', color: '#D97706' },
  LONG: { bg: 'rgba(22,163,74,.12)', color: '#16A34A' },
  SHORT: { bg: 'rgba(220,38,38,.12)', color: '#DC2626' },
  WATCH: { bg: 'var(--bg3)', color: 'var(--text3)' },
}

export default function WatchlistSymbolPanel({ symbol, onClose }: { symbol: string | null; onClose: () => void }) {
  const [data, setData] = useState<ContextData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [confluence, setConfluence] = useState<any>(null)

  useEffect(() => {
    if (!symbol) { setData(null); setConfluence(null); return }
    setLoading(true); setError('')
    fetch(`/api/v2/watchlist/context/${symbol}`)
      .then(r => r.json())
      .then(d => { d.ok ? setData(d.data) : setError(d.error || 'Failed'); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
    // Fetch confluence data (non-fatal)
    fetch(`/api/v2/indicators/confluence?symbol=${symbol}&profile=swing`)
      .then(r => r.json())
      .then(d => { if (d.ok) setConfluence(d.data) })
      .catch(() => {})
  }, [symbol])

  useEffect(() => {
    if (!symbol) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [symbol, onClose])

  if (!symbol) return null

  const Skeleton = () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: 20 }}>
      {[80, 120, 200, 150, 100].map((h, i) => (
        <div key={i} style={{ height: h, background: 'var(--bg2)', borderRadius: 8, animation: 'pulse 1.5s infinite' }} />
      ))}
    </div>
  )

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.55)', zIndex: 1200, display: 'flex', justifyContent: 'flex-end' }} onClick={onClose}>
      <div style={{ width: '65vw', maxWidth: 900, minWidth: 500, height: '100vh', background: 'var(--bg0)', borderLeft: '2px solid var(--border)', display: 'flex', flexDirection: 'column', transition: 'transform 200ms ease' }} onClick={e => e.stopPropagation()}>

        {/* Sticky header */}
        <div style={{ padding: '14px 20px', borderBottom: '2px solid var(--border)', flexShrink: 0, background: 'var(--bg1)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 24, fontWeight: 800, color: 'var(--accent)' }}>{symbol}</span>
              {data?.strategy?.strategy_type && <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 99, background: 'rgba(74,144,244,.1)', color: 'var(--accent)', fontWeight: 600 }}>{data.strategy.strategy_type.replace(/_/g, ' ')}</span>}
              {data?.synthesis && <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 99, fontWeight: 700, background: `color-mix(in srgb, ${REC_COLOR[data.synthesis.recommendation] || 'var(--text3)'} 15%, transparent)`, color: REC_COLOR[data.synthesis.recommendation] || 'var(--text3)' }}>{data.synthesis.recommendation}</span>}
              {data?.trade_type && (() => { const tc = TRADE_TYPE_COLOR[data.trade_type] || TRADE_TYPE_COLOR.WATCH; return <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 99, fontWeight: 700, background: tc.bg, color: tc.color }}>{data.trade_type}</span> })()}
              {data?.in_portfolio && <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 99, fontWeight: 700, background: 'rgba(220,38,38,.12)', color: '#DC2626', border: '1px solid rgba(220,38,38,.3)' }}>{'\u26a0\ufe0f'} HELD {data.portfolio_weight ? `${Number(data.portfolio_weight).toFixed(1)}%` : ''}</span>}
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <a href={`/v2/watchlist/${symbol}`} style={{ fontSize: 9, padding: '3px 10px', border: '1px solid var(--green)', borderRadius: 4, color: 'var(--green)', textDecoration: 'none' }} title="Open full page">⤢</a>
              <a href={`https://finviz.com/quote.ashx?t=${symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 9, padding: '3px 10px', border: '1px solid var(--accent)', borderRadius: 4, color: 'var(--accent)', textDecoration: 'none' }}>Finviz</a>
              <a href={`https://finance.yahoo.com/quote/${symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 9, padding: '3px 10px', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text2)', textDecoration: 'none' }}>Yahoo</a>
              <button onClick={onClose} style={{ fontSize: 18, color: 'var(--text3)', background: 'none', border: 'none', cursor: 'pointer', padding: '0 4px' }}>x</button>
            </div>
          </div>
          {data?.strategy && (
            <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 10, color: 'var(--text2)' }}>
              <span>Price: <strong style={{ color: 'var(--text0)' }}>{data.strategy.latest_price ? fmt$(data.strategy.latest_price) : '—'}</strong></span>
              <span>Support: {data.strategy.support ? fmt$(data.strategy.support) : '—'}</span>
              <span>Resistance: {data.strategy.resistance ? fmt$(data.strategy.resistance) : '—'}</span>
              <span>Stop: <strong style={{ color: 'var(--amber)' }}>{data.strategy.stop_loss ? fmt$(data.strategy.stop_loss) : '—'}</strong></span>
              <span>Target: <strong style={{ color: 'var(--green)' }}>{data.strategy.target_price ? fmt$(data.strategy.target_price) : '—'}</strong></span>
              {data.strategy.risk_reward && <span>R:R: <strong>{Number(data.strategy.risk_reward).toFixed(1)}</strong></span>}
            </div>
          )}
          {data?.holdings && data.holdings.length > 0 && (
            <div style={{ display: 'flex', gap: 12, marginTop: 4, fontSize: 10, color: 'var(--text2)' }}>
              <span>Held: <strong>{data.holdings.reduce((s: number, h: any) => s + (h.shares || 0), 0).toFixed(1)} shares</strong></span>
              <span>in {data.holdings.map((h: any) => (h.account || '').replace('schwab_', '').replace('fidelity_', '')).join(', ')}</span>
            </div>
          )}
        </div>

        {/* Scrollable content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
          {loading && <Skeleton />}
          {error && (
            <div style={{ padding: 16, background: 'var(--red-dim)', border: '1px solid var(--red)', borderRadius: 8, color: 'var(--red)', fontSize: 11 }}>
              {error}
              <button onClick={() => { setLoading(true); setError(''); fetch(`/api/v2/watchlist/context/${symbol}`).then(r => r.json()).then(d => { d.ok ? setData(d.data) : setError(d.error); setLoading(false) }).catch(e => { setError(String(e)); setLoading(false) }) }} style={{ marginLeft: 12, fontSize: 9, padding: '2px 8px', border: '1px solid var(--red)', borderRadius: 3, background: 'transparent', color: 'var(--red)', cursor: 'pointer' }}>Retry</button>
            </div>
          )}

          {data && !loading && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

              {/* Summary verdict card — quick scan */}
              <div style={{ padding: 16, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>
                <div style={{ fontSize: 13, color: 'var(--text1)', fontStyle: 'italic', marginBottom: 12, lineHeight: 1.5 }}>
                  {data.summary_verdict || 'No summary available yet.'}
                </div>
                <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
                  {[
                    ['CONFIDENCE', data.synthesis?.confidence ? `${Math.round(data.synthesis.confidence * 100)}%` : '—', data.synthesis?.confidence && data.synthesis.confidence > 0.7 ? 'var(--green)' : data.synthesis?.confidence && data.synthesis.confidence > 0.4 ? 'var(--amber)' : 'var(--text2)'],
                    ['AGENT AGREE', data.agent_agree || '—', 'var(--text0)'],
                    ['DAYS ON LIST', data.strategy?.days_watched != null ? `${data.strategy.days_watched}d` : (data.agent_results.length > 0 ? '—' : '0d'), 'var(--text0)'],
                    ['IN PORTFOLIO', data.in_portfolio ? `YES ${data.portfolio_value ? fmt$(data.portfolio_value) : ''}` : 'NO', data.in_portfolio ? 'var(--green)' : 'var(--text3)'],
                    ['VS SECTOR', data.sector_comparison?.ticker_perf_1m || '—', (data.sector_comparison?.ticker_perf_1m || '').startsWith('-') ? 'var(--red)' : 'var(--green)'],
                  ].map(([label, value, color]) => (
                    <div key={String(label)}>
                      <div style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 600, letterSpacing: '.04em' }}>{String(label)}</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color: String(color), fontFamily: 'var(--mono)' }}>{String(value)}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Technical Confluence */}
              {confluence?.ok && (
                <div style={{ padding: 14, background: 'rgba(74,144,244,.04)', border: '1px solid rgba(74,144,244,.12)', borderRadius: 10 }}>
                  <div style={{ fontSize: 9, color: 'var(--accent)', textTransform: 'uppercase', fontWeight: 700, letterSpacing: '.04em', marginBottom: 10 }}>Technical Confluence</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
                    <span style={{
                      fontSize: 13, fontWeight: 800, padding: '3px 10px', borderRadius: 4,
                      background: confluence.confluence_tier === 'STRONG' ? '#064E3B' : confluence.confluence_tier === 'MODERATE' ? '#451A03' : '#1E293B',
                      color: confluence.confluence_tier === 'STRONG' ? '#6EE7B7' : confluence.confluence_tier === 'MODERATE' ? '#FCD34D' : '#94A3B8',
                      border: `1px solid ${confluence.confluence_tier === 'STRONG' ? '#10B981' : confluence.confluence_tier === 'MODERATE' ? '#F59E0B' : '#475569'}`,
                    }}>
                      {confluence.confluence_tier}
                    </span>
                    <span style={{ fontSize: 11, color: 'var(--text1)' }}>
                      {confluence.signals_bullish} bullish / {confluence.signals_bearish} bearish / {confluence.signals_neutral} neutral
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 10 }}>
                    {(confluence.strategy_badges || []).map((b: string) => (
                      <span key={b} style={{ fontSize: 10, fontWeight: 600, padding: '2px 6px', borderRadius: 3, background: '#064E3B', color: '#6EE7B7', border: '1px solid #10B98133' }}>{b}</span>
                    ))}
                    {(confluence.bearish_badges || []).map((b: string) => (
                      <span key={b} style={{ fontSize: 10, fontWeight: 600, padding: '2px 6px', borderRadius: 3, background: '#7F1D1D33', color: '#FCA5A5', border: '1px solid #EF444433' }}>{b}</span>
                    ))}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, fontSize: 10 }}>
                    <div>
                      <div style={{ ...lbl }}>Entry Quality</div>
                      <div style={{ fontWeight: 700, color: confluence.entry_quality === 'good' ? '#0ecb81' : confluence.entry_quality === 'ok' ? '#f0b90b' : '#f6465d' }}>
                        {confluence.entry_quality === 'good' ? 'Good zone' : confluence.entry_quality === 'ok' ? 'Acceptable' : 'Overbought'}
                      </div>
                    </div>
                    <div>
                      <div style={{ ...lbl }}>ADX Regime</div>
                      <div style={{ fontWeight: 700, color: 'var(--text1)' }}>
                        {confluence.adx_regime === 'trending' ? 'Trending' : confluence.adx_regime === 'ranging' ? 'Ranging' : 'Moderate'}
                      </div>
                    </div>
                    <div>
                      <div style={{ ...lbl }}>Stop</div>
                      <div style={{ fontWeight: 700, color: 'var(--amber)' }}>{confluence.stop_price ? `$${confluence.stop_price}` : '--'}</div>
                    </div>
                    <div>
                      <div style={{ ...lbl }}>Target</div>
                      <div style={{ fontWeight: 700, color: 'var(--green)' }}>{confluence.target_price ? `$${confluence.target_price}` : '--'}</div>
                    </div>
                  </div>
                  {confluence.key_levels?.fibonacci && (
                    <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid rgba(255,255,255,.05)', display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 9, color: 'var(--text2)' }}>
                      {Object.entries(confluence.key_levels.fibonacci as Record<string, number>).slice(0, 5).map(([k, v]) => (
                        <span key={k}>Fib {(parseFloat(k.replace('ret_', '')) * 100).toFixed(1)}%: <strong style={{ color: 'var(--text1)' }}>${Number(v).toFixed(2)}</strong></span>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Conflict resolver — show first if conflict detected */}
              {data.conflict && (data.conflict.is_conflict || data.conflict.type === 'data_gap') && (
                <div style={{ padding: 14, background: data.conflict.is_conflict ? 'rgba(240,185,11,.06)' : 'rgba(74,144,244,.04)', border: `1px solid ${data.conflict.is_conflict ? 'var(--amber)' : 'rgba(74,144,244,.15)'}`, borderRadius: 10 }}>
                  <div style={{ fontSize: 12, fontWeight: 800, color: data.conflict.is_conflict ? 'var(--amber)' : 'var(--accent)', marginBottom: 8 }}>
                    {data.conflict.is_conflict ? 'AGENT CONFLICT DETECTED' : 'DATA GAP (not a conflict)'}
                  </div>
                  {data.agent_results.map((a, i) => (
                    <div key={i} style={{ fontSize: 11, color: 'var(--text1)', padding: '3px 0' }}>
                      <strong style={{ color: REC_COLOR[a.recommendation] || 'var(--text2)' }}>{a.agent_name?.replace('_agent', '')}: {a.recommendation}</strong>
                      <span style={{ color: 'var(--text3)', marginLeft: 6 }}>({a.confidence_score ? `${Math.round(a.confidence_score * 100)}%` : '?'})</span>
                      <span style={{ color: 'var(--text2)', marginLeft: 6 }}>— {a.summary?.slice(0, 80)}</span>
                    </div>
                  ))}
                  <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text0)', fontWeight: 600, lineHeight: 1.6 }}>
                    WHY: {data.conflict.explanation}
                  </div>
                </div>
              )}

              {/* Synthesis verdict */}
              {data.synthesis && (() => {
                const isLLMError = (data.synthesis.synthesis_narrative || '').includes('LLM error') ||
                  (data.synthesis.synthesis_narrative || '').includes('All providers failed')
                if (isLLMError) {
                  return (
                    <div style={{ padding: 14, background: 'rgba(220,38,38,.06)', border: '1px solid rgba(220,38,38,.25)', borderRadius: 10 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                        <span style={{ ...lbl, color: '#DC2626' }}>Analysis Incomplete</span>
                        <span style={{ fontSize: 14, fontWeight: 700, color: '#DC2626', fontFamily: 'monospace' }}>PENDING</span>
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.6, marginBottom: 10 }}>
                        LLM providers were unavailable when this symbol was analyzed. The displayed recommendation is not valid.
                      </div>
                      <button onClick={() => { fetch(`/api/v2/watchlist/${data.symbol}/requeue`, { method: 'POST' }).then(r => r.json()).then(d => { if (d.ok) alert(`Re-queued ${data.symbol} for fresh analysis`) }) }}
                        style={{ background: '#1E3A5F', color: 'white', border: 'none', padding: '6px 14px', borderRadius: 4, cursor: 'pointer', fontSize: 11, fontWeight: 600 }}>
                        Re-queue Analysis
                      </button>
                    </div>
                  )
                }
                return (
                  <div style={{ padding: 14, background: 'rgba(14,203,129,.04)', border: '1px solid rgba(14,203,129,.12)', borderRadius: 10 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                      <span style={{ ...lbl }}>Final Synthesis</span>
                      <span style={{ fontSize: 20, fontWeight: 800, color: REC_COLOR[data.synthesis.recommendation] || 'var(--text1)' }}>{data.synthesis.recommendation}</span>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.6, marginBottom: 6 }}>
                      {data.synthesis.synthesis_narrative || data.synthesis.action || 'No narrative'}
                    </div>
                    <div style={{ display: 'flex', gap: 8, fontSize: 9, color: 'var(--text3)' }}>
                      <span>Confidence: {data.synthesis.confidence ? `${Math.round(data.synthesis.confidence * 100)}%` : '?'}</span>
                      {data.synthesis.next_review_date && <span>Next review: {data.synthesis.next_review_date}</span>}
                      {data.synthesis.decision_quality_status && <span>QA: {data.synthesis.decision_quality_status}</span>}
                    </div>
                    {data.synthesis.conflicts && <div style={{ fontSize: 9, color: 'var(--amber)', marginTop: 4 }}>Conflicts: {String(data.synthesis.conflicts)}</div>}
                  </div>
                )
              })()}

              {/* Strategy card — entry/stop/target */}
              {data.strategy_card && (
                <div style={{ padding: 14, background: '#0F172A', border: '1px solid #1E293B', borderRadius: 10 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                    {data.strategy_card.trade_type && data.strategy_card.trade_type !== 'WATCH' && (
                      <span style={{
                        fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 3,
                        background: data.strategy_card.trade_type === 'INCOME' ? 'rgba(13,148,136,.12)' :
                                    data.strategy_card.trade_type === 'LONG' ? 'rgba(22,163,74,.12)' :
                                    data.strategy_card.trade_type === 'SWING' ? 'rgba(217,119,6,.12)' : 'var(--bg3)',
                        color: data.strategy_card.trade_type === 'INCOME' ? '#0D9488' :
                               data.strategy_card.trade_type === 'LONG' ? '#16A34A' :
                               data.strategy_card.trade_type === 'SWING' ? '#D97706' : 'var(--text3)',
                      }}>{data.strategy_card.trade_type}</span>
                    )}
                    <span style={{ color: '#94A3B8', fontSize: 11, fontFamily: 'monospace' }}>
                      {data.strategy_card.strategy_label}
                    </span>
                    {data.strategy_card.account_fit && (
                      <span style={{ color: '#0D9488', fontSize: 10, fontFamily: 'monospace', marginLeft: 'auto', border: '1px solid #0D9488', padding: '1px 6px', borderRadius: 3 }}>
                        {data.strategy_card.account_fit}
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 8, marginBottom: 8 }}>
                    {[
                      { label: 'ENTRY', value: data.strategy_card.ideal_entry, color: '#16A34A' },
                      { label: 'TARGET', value: data.strategy_card.target_price, color: '#2E86D4' },
                      { label: 'STOP', value: data.strategy_card.stop_loss, color: '#DC2626' },
                      { label: 'R:R', value: data.strategy_card.risk_reward, color: '#E2EAF4' },
                    ].map(({ label, value, color }) => (
                      <div key={label}>
                        <div style={{ fontSize: 9, color: '#64748B', fontFamily: 'monospace' }}>{label}</div>
                        <div style={{ fontSize: 15, fontFamily: 'monospace', fontWeight: 700, color: value ? color : '#374151' }}>
                          {value ? (label === 'R:R' ? `${Number(value).toFixed(1)}:1` : `$${Number(value).toFixed(2)}`) : '—'}
                        </div>
                      </div>
                    ))}
                  </div>
                  {(data.strategy_card.support || data.strategy_card.resistance) && (
                    <div style={{ display: 'flex', gap: 16, fontSize: 11, color: '#64748B' }}>
                      {data.strategy_card.support && <span>Support: <span style={{ color: '#E2EAF4' }}>${Number(data.strategy_card.support).toFixed(2)}</span></span>}
                      {data.strategy_card.resistance && <span>Resistance: <span style={{ color: '#E2EAF4' }}>${Number(data.strategy_card.resistance).toFixed(2)}</span></span>}
                    </div>
                  )}
                  {data.strategy_card.why_added && (
                    <div style={{ fontSize: 11, color: '#94A3B8', fontStyle: 'italic', marginTop: 8, paddingTop: 8, borderTop: '1px solid #1E293B' }}>
                      Added: {data.strategy_card.why_added}
                    </div>
                  )}
                  {!data.strategy_card.ideal_entry && !data.strategy_card.stop_loss && (
                    <div style={{ color: '#6B7280', fontSize: 11, fontStyle: 'italic', marginTop: 6 }}>
                      Entry/stop levels pending — Escalate to Alex for a full trade plan
                    </div>
                  )}
                </div>
              )}

              {/* Agent narratives — full text */}
              <div style={{ padding: 14, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>
                <div style={{ ...lbl, marginBottom: 10 }}>Agent Narratives ({data.agent_results.length})</div>
                {data.agent_results.length > 0 ? data.agent_results.map((a, i) => (
                  <div key={i} style={{ padding: '10px 0', borderBottom: i < data.agent_results.length - 1 ? '1px solid var(--border)' : 'none' }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                      <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 3, background: `color-mix(in srgb, ${REC_COLOR[a.recommendation] || 'var(--text3)'} 15%, transparent)`, color: REC_COLOR[a.recommendation] || 'var(--text3)' }}>{a.agent_name?.replace('_agent', '').toUpperCase()}</span>
                      <span style={{ fontWeight: 700, color: REC_COLOR[a.recommendation] || 'var(--text2)' }}>{a.recommendation}</span>
                      <span style={{ color: 'var(--text3)', fontSize: 10 }}>{a.confidence_score ? `${Math.round(a.confidence_score * 100)}%` : ''}</span>
                      <span style={{ color: 'var(--text3)', fontSize: 9, marginLeft: 'auto' }}>{a.created_at?.slice(0, 16)}</span>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
                      {dedupeNarrative(a.full_narrative || a.summary) || 'No narrative'}
                    </div>
                    {a.reason_codes && a.reason_codes.length > 0 && (
                      <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', marginTop: 6 }}>
                        {(Array.isArray(a.reason_codes) ? a.reason_codes : []).map((tag: string, ti: number) => (
                          <span key={ti} style={{ fontSize: 8, padding: '1px 6px', borderRadius: 99, background: 'rgba(74,144,244,.08)', color: 'var(--accent)' }}>{tag}</span>
                        ))}
                      </div>
                    )}
                  </div>
                )) : <div style={{ color: 'var(--text3)', fontSize: 10 }}>No recent agent analyses</div>}
              </div>

              {/* Strategy card */}
              {data.strategy ? (
                <div style={{ padding: 14, background: 'var(--bg2)', borderRadius: 10 }}>
                  <div style={{ ...lbl, marginBottom: 8 }}>Strategy Card</div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 8 }}>
                    {[['Price', data.strategy.latest_price], ['Support', data.strategy.support], ['Resistance', data.strategy.resistance], ['Stop', data.strategy.stop_loss], ['Target', data.strategy.target_price], ['R:R', data.strategy.risk_reward], ['Account', data.strategy.account_fit], ['Horizon', data.strategy.time_horizon]].map(([l, v]) => (
                      <div key={String(l)}><div style={lbl}>{String(l)}</div><div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>{typeof v === 'number' ? (l === 'R:R' ? Number(v).toFixed(1) : fmt$(v)) : (v || '—')}</div></div>
                    ))}
                  </div>
                  {data.strategy.thesis && <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.5, borderTop: '1px solid var(--border)', paddingTop: 6 }}>{data.strategy.thesis}</div>}
                </div>
              ) : <div style={{ padding: 12, background: 'var(--bg2)', borderRadius: 8, color: 'var(--text3)', fontSize: 10 }}>No strategy card generated yet</div>}

              {/* Sector comparison */}
              {data.sector_comparison?.sector && (
                <div style={{ padding: 14, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>
                  <div style={{ ...lbl, marginBottom: 10 }}>Sector Context · {data.sector_comparison.sector} {data.sector_comparison.sector_etf ? `(${data.sector_comparison.sector_etf})` : ''}</div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                    {[
                      ['Ticker 1M', data.sector_comparison.ticker_perf_1m || '—'],
                      [`Sector ETF 1M`, data.sector_comparison.sector_perf_1m || '—'],
                      ['VS Sector', (() => {
                        const tp = parseFloat(data.sector_comparison?.ticker_perf_1m || '0')
                        const sp = parseFloat(data.sector_comparison?.sector_perf_1m || '0')
                        return isNaN(tp) || isNaN(sp) ? '—' : `${(tp - sp).toFixed(1)}%`
                      })()],
                    ].map(([label, val]) => (
                      <div key={String(label)}>
                        <div style={{ fontSize: 10, color: 'var(--text3)' }}>{String(label)}</div>
                        <div style={{ fontSize: 18, fontWeight: 700, color: String(val).startsWith('-') ? 'var(--red)' : val === '—' ? 'var(--text3)' : 'var(--green)' }}>{String(val)}</div>
                      </div>
                    ))}
                  </div>
                  {/* Sector news */}
                  {(data.sector_news || []).length > 0 && (
                    <div style={{ marginTop: 10, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
                      <div style={{ ...lbl, marginBottom: 6 }}>Sector News</div>
                      {(data.sector_news || []).slice(0, 3).map((n: any, i: number) => (
                        <div key={i} style={{ fontSize: 10, padding: '4px 0', borderBottom: '1px solid var(--border)', display: 'flex', gap: 6, alignItems: 'center' }}>
                          <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'rgba(13,148,136,.12)', color: '#0D9488', fontWeight: 600 }}>SECTOR</span>
                          <span style={{ color: 'var(--text1)', flex: 1 }}>{n.title?.slice(0, 70)}</span>
                          <span style={{ color: 'var(--text3)', fontSize: 9, whiteSpace: 'nowrap' }}>{n.source}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* News */}
              <div style={{ padding: 14, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>
                <div style={{ ...lbl, marginBottom: 8 }}>Recent News ({data.news.length})</div>
                {data.news.length > 0 ? data.news.map((n, i) => (
                  <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <span style={{ color: 'var(--text3)', fontSize: 9 }}>[{n.source}]</span>
                      <span style={{ color: 'var(--text0)', flex: 1 }}>{n.title}</span>
                      {n.relevance_score && <span style={{ color: 'var(--accent)', fontSize: 9 }}>{n.relevance_score}%</span>}
                      {n.sentiment && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: n.sentiment === 'positive' ? 'var(--green-dim)' : n.sentiment === 'negative' ? 'var(--red-dim)' : 'var(--bg3)', color: n.sentiment === 'positive' ? 'var(--green)' : n.sentiment === 'negative' ? 'var(--red)' : 'var(--text3)' }}>{n.sentiment}</span>}
                    </div>
                    {n.summary && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 3, lineHeight: 1.5 }}>{n.summary.slice(0, 150)}</div>}
                  </div>
                )) : <div style={{ color: 'var(--text3)', fontSize: 10 }}>No recent news — symbol may need Brave Search credit</div>}
              </div>

              {/* Intel whiteboard */}
              {data.intel.length > 0 && (
                <div style={{ padding: 14, background: 'var(--bg2)', borderRadius: 10 }}>
                  <div style={{ ...lbl, marginBottom: 8 }}>Intelligence Whiteboard ({data.intel.length})</div>
                  {data.intel.map((item, i) => (
                    <div key={i} style={{ padding: '5px 0', borderBottom: '1px solid var(--border)', fontSize: 10 }}>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'var(--accent-dim)', color: 'var(--accent)' }}>{item.source_type}</span>
                        <span style={{ color: 'var(--text1)' }}>{item.title}</span>
                        <span style={{ color: 'var(--text3)', marginLeft: 'auto' }}>Q:{item.quality_score}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Position if held */}
              {data.holdings.length > 0 && (
                <div style={{ padding: 14, background: 'rgba(14,203,129,.04)', border: '1px solid rgba(14,203,129,.12)', borderRadius: 10 }}>
                  <div style={{ ...lbl, marginBottom: 8 }}>Position ({data.holdings.length} account{data.holdings.length > 1 ? 's' : ''})</div>
                  {data.holdings.map((h: any, i: number) => (
                    <div key={i} style={{ fontSize: 11, padding: '4px 0', display: 'flex', gap: 12 }}>
                      <span style={{ fontWeight: 600 }}>{(h.account || '').replace('schwab_', '').replace('fidelity_', '')}</span>
                      <span>{h.shares?.toFixed(1)} shares</span>
                      <span>{fmt$(h.market_value)}</span>
                      <span style={{ color: (h.gain_loss || 0) >= 0 ? 'var(--green)' : 'var(--red)' }}>{(h.gain_loss || 0) >= 0 ? '+' : ''}{fmt$(h.gain_loss || 0)}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Past outcomes */}
              {data.outcomes.length > 0 && (
                <div style={{ padding: 14, background: 'var(--bg2)', borderRadius: 10 }}>
                  <div style={{ ...lbl, marginBottom: 8 }}>Past Outcomes</div>
                  {data.outcomes.map((o, i) => (
                    <div key={i} style={{ fontSize: 10, color: 'var(--text2)', padding: '3px 0' }}>
                      {o.recommendation} at {fmt$(o.price_at_decision)} → 7d: {o.price_7d ? fmt$(o.price_7d) : '—'}
                      <span style={{ color: (o.outcome_score || 0) > 0 ? 'var(--green)' : 'var(--red)', marginLeft: 6, fontWeight: 600 }}>
                        {(o.outcome_score || 0) > 0 ? 'CORRECT' : 'WRONG'}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Action bar */}
              <div style={{ display: 'flex', gap: 8, padding: '16px 0 0', borderTop: '1px solid var(--border)', marginTop: 4 }}>
                <button onClick={() => {
                  fetch(`/api/v2/watchlist/${data.symbol}/escalate-alex`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: 'user_interest', note: 'Flagged from watchlist panel' }) })
                    .then(r => r.json()).then(d => { if (d.ok) { alert(`\u2b50 ${data.symbol} escalated to Alex \u2014 check Telegram`) } else { alert('Error: ' + d.error) } })
                }} style={{ flex: 2, background: 'linear-gradient(135deg,#7C3AED,#1E6FBF)', color: 'white', padding: '10px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>
                  {'\u2b50'} Escalate to Alex
                </button>
                {data.conflict?.is_conflict && (
                  <button onClick={() => {
                    fetch('/api/v2/debates/trigger', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol: data.symbol, trigger: 'manual' }) })
                      .then(r => r.json()).then(d => { alert(d.ok ? `\uD83D\uDDE3 Debate queued for ${data.symbol}` : d.error) })
                  }} style={{ flex: 1, background: 'var(--bg3)', color: 'var(--text1)', padding: '10px', borderRadius: 6, border: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, fontWeight: 600 }}>
                    {'\uD83D\uDDE3'} Debate
                  </button>
                )}
                <button onClick={onClose} style={{ flex: 1, background: 'var(--bg3)', color: 'var(--text2)', padding: '10px', borderRadius: 6, border: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
                  Close
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

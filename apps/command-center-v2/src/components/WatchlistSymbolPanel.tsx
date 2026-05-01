import { useState, useEffect } from 'react'

interface ContextData {
  symbol: string
  agent_results: any[]
  synthesis: any | null
  strategy: any | null
  news: any[]
  holdings: any[]
  intel: any[]
  outcomes: any[]
  macro: string
  conflict: { is_conflict: boolean; type: string; explanation: string; buyers?: any[]; sellers?: any[]; data_gaps?: any[] }
}

const REC_COLOR: Record<string, string> = {
  BUY: '#0ecb81', ADD: '#0ecb81', HOLD: '#4a90f4', NEUTRAL: '#8891a0',
  TRIM: '#f6465d', SELL: '#f6465d', AVOID: '#f6465d',
  RESEARCH_MORE: '#f0b90b', IGNORE: '#525c6a',
}
const lbl: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em', fontWeight: 700 }
const fmt$ = (v: number) => v != null ? `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : '—'

export default function WatchlistSymbolPanel({ symbol, onClose }: { symbol: string | null; onClose: () => void }) {
  const [data, setData] = useState<ContextData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!symbol) { setData(null); return }
    setLoading(true); setError('')
    fetch(`/api/v2/watchlist/context/${symbol}`)
      .then(r => r.json())
      .then(d => { d.ok ? setData(d.data) : setError(d.error || 'Failed'); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
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
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
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
              {data.synthesis && (
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
                      {a.full_narrative || a.summary || 'No narrative'}
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
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

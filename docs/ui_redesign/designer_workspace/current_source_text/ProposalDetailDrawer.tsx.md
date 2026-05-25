# Source Export: ProposalDetailDrawer.tsx

- **Original path:** apps/command-center-v2/src/components/ProposalDetailDrawer.tsx
- **Git branch:** main
- **Git commit:** d3fefdb9bd7af34f2ec2a6b0a31d89f24dbc8421
- **Export timestamp:** 2026-05-25T11:37:46-04:00
- **SHA256:** 60f09eaf7ba86c26668feace1428adb20bb2035ce487eb3e290eee1d406a0ec1
- **File size:** 13149 bytes
- **Exists:** YES

```tsx
import { useState, useEffect } from 'react'

interface ProposalDetail {
  proposal: Record<string, any>
  position: Record<string, any>
  holdings: any[]
  agent_results: any[]
  synthesis: any | null
  news: any[]
  stop_data: Record<string, any>
  outcomes: any[]
  portfolio_value: number
}

const REC_COLOR: Record<string, string> = {
  BUY: 'var(--green)', ADD: 'var(--green)', HOLD: 'var(--amber)',
  TRIM: 'var(--red)', SELL: 'var(--red)', AVOID: 'var(--red)',
  NEUTRAL: 'var(--text2)', RESEARCH_MORE: 'var(--accent)',
}
const lbl: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.04em' }

export default function ProposalDetailDrawer({ proposalId, onClose }: { proposalId: number | null; onClose: () => void }) {
  const [data, setData] = useState<ProposalDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!proposalId) { setData(null); return }
    setLoading(true); setError('')
    fetch(`/api/v2/proposal-detail/${proposalId}`)
      .then(r => r.json())
      .then(d => {
        if (d.ok) setData(d.data)
        else setError(d.error || 'Failed to load')
        setLoading(false)
      })
      .catch(e => { setError(String(e)); setLoading(false) })
  }, [proposalId])

  if (!proposalId) return null

  const computeAiRec = () => {
    if (!data) return null
    const agents = data.agent_results || []
    const trimSell = agents.filter(a => ['TRIM', 'SELL', 'AVOID'].includes(a.recommendation?.toUpperCase()))
    const holdBuy = agents.filter(a => ['HOLD', 'BUY', 'ADD'].includes(a.recommendation?.toUpperCase()))
    const stopBreached = data.stop_data?.triggered || (data.stop_data?.distance_pct != null && data.stop_data.distance_pct <= 0)
    const hasIncome = (data.position?.annual_income || 0) > 0
    const synth = data.synthesis

    const reasons: string[] = []
    let rec = 'HOLD'

    if (synth?.recommendation) {
      rec = synth.recommendation
      reasons.push(`Synthesis: ${synth.recommendation}`)
    } else if (trimSell.length >= 2) {
      rec = 'TRIM'
      reasons.push(`${trimSell.length}/${agents.length} agents say TRIM/SELL`)
    } else if (holdBuy.length >= 2) {
      rec = 'HOLD'
      reasons.push(`${holdBuy.length}/${agents.length} agents say HOLD/BUY`)
    }
    if (stopBreached) reasons.push('Stop breached - bias toward exit')
    if (hasIncome) reasons.push(`Income position: $${data.position.annual_income}/yr`)
    const ssdi = data.proposal?.ssdi_impact
    if (ssdi && ssdi !== 'none') reasons.push(`SSDI impact: ${ssdi} - consult Alex`)

    const conf = synth?.confidence ? Math.round(synth.confidence * 100) : agents.length > 0 ? Math.round(agents.reduce((s: number, a: any) => s + (a.confidence_score || 0), 0) / agents.length * 100) : 0
    return { rec, reasons, conf }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1100, display: 'flex', justifyContent: 'flex-end' }} onClick={onClose}>
      <div style={{ width: 560, height: '100vh', background: 'var(--bg0)', borderLeft: '2px solid var(--border)', padding: '16px 20px', overflowY: 'auto' }} onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div>
            {data && (
              <>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4 }}>
                  {data.proposal.urgency === 'urgent' && <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 8px', borderRadius: 3, background: 'var(--red-dim)', color: 'var(--red)' }}>URGENT</span>}
                  <span style={{ fontSize: 9, fontWeight: 600, padding: '2px 8px', borderRadius: 3, background: 'var(--bg3)', color: 'var(--text2)' }}>{data.proposal.action}</span>
                  <span style={{ fontSize: 9, color: 'var(--text3)' }}>ID: {proposalId}</span>
                </div>
                <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--accent)' }}>{data.proposal.symbol}</div>
              </>
            )}
          </div>
          <button onClick={onClose} style={{ fontSize: 20, color: 'var(--text3)', background: 'none', border: 'none', cursor: 'pointer' }}>x</button>
        </div>

        {loading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[1,2,3,4].map(i => <div key={i} style={{ height: 60, background: 'var(--bg2)', borderRadius: 8, animation: 'pulse 1.5s infinite' }} />)}
          </div>
        )}

        {error && <div style={{ padding: 12, background: 'var(--red-dim)', border: '1px solid var(--red)', borderRadius: 8, color: 'var(--red)', fontSize: 11 }}>{error}</div>}

        {data && !loading && (
          <>
            {/* Position + Stop */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 12 }}>
              <div style={{ padding: 12, background: 'var(--bg2)', borderRadius: 8 }}>
                <div style={{ ...lbl, marginBottom: 6 }}>Position Summary</div>
                {data.position && Object.keys(data.position).length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11 }}>
                    <div>Shares: <strong>{data.position.total_shares}</strong> in [{data.position.accounts?.join(', ')}]</div>
                    <div>Cost: <strong>${data.position.cost_per_share?.toFixed(2)}/sh</strong> (${data.position.total_cost_basis?.toLocaleString()})</div>
                    <div>Value: <strong>${data.position.total_market_value?.toLocaleString()}</strong></div>
                    <div style={{ color: (data.position.unrealized_pnl || 0) >= 0 ? 'var(--green)' : 'var(--red)' }}>
                      P&L: {data.position.unrealized_pnl >= 0 ? '+' : ''}${data.position.unrealized_pnl?.toLocaleString()} ({data.position.unrealized_pct}%)
                    </div>
                    <div>Portfolio: <strong>{data.position.pct_of_portfolio}%</strong></div>
                    {data.position.annual_income > 0 && <div style={{ color: 'var(--green)' }}>Income: ${data.position.annual_income}/yr ({data.position.income_pct_of_target}% of $55K)</div>}
                  </div>
                ) : (
                  <div style={{ color: 'var(--text3)', fontSize: 10 }}>Not currently held - watchlist proposal only</div>
                )}
              </div>

              <div style={{ padding: 12, background: 'var(--bg2)', borderRadius: 8 }}>
                <div style={{ ...lbl, marginBottom: 6 }}>Stop / Price</div>
                {data.stop_data && Object.keys(data.stop_data).length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11 }}>
                    <div>Current: <strong>${data.stop_data.current_price?.toFixed(2)}</strong></div>
                    <div style={{ color: data.stop_data.triggered ? 'var(--red)' : 'var(--text1)' }}>
                      Stop: <strong>${data.stop_data.stop_price?.toFixed(2)}</strong>
                      {data.stop_data.triggered && <span style={{ marginLeft: 6, fontWeight: 700, color: 'var(--red)' }}>BREACHED</span>}
                    </div>
                    <div>Distance: {data.stop_data.distance_pct?.toFixed(1)}%</div>
                  </div>
                ) : (
                  <div style={{ color: 'var(--text3)', fontSize: 10 }}>No stop data</div>
                )}
                <div style={{ marginTop: 8, borderTop: '1px solid var(--border)', paddingTop: 6 }}>
                  <div style={{ ...lbl, marginBottom: 3 }}>SSDI / IRMAA</div>
                  <div style={{ fontSize: 10, color: data.proposal.ssdi_impact && data.proposal.ssdi_impact !== 'none' ? 'var(--amber)' : 'var(--text3)' }}>
                    SSDI: {data.proposal.ssdi_impact || 'none'} | IRMAA: {data.proposal.irmaa_risk ? 'Yes' : 'No'}
                  </div>
                </div>
              </div>
            </div>

            {/* Agent Verdicts */}
            <div style={{ padding: 12, background: 'var(--bg2)', borderRadius: 8, marginBottom: 12 }}>
              <div style={{ ...lbl, marginBottom: 6 }}>Agent Verdicts</div>
              {data.agent_results.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {data.agent_results.slice(0, 6).map((a, i) => (
                    <div key={i} style={{ display: 'flex', gap: 8, fontSize: 11, alignItems: 'center' }}>
                      <span style={{ width: 60, fontWeight: 700, color: REC_COLOR[a.agent_name] || 'var(--text2)' }}>{a.agent_name?.replace('_agent', '')}</span>
                      <span style={{ fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 3, background: `color-mix(in srgb, ${REC_COLOR[a.recommendation] || 'var(--text3)'} 15%, transparent)`, color: REC_COLOR[a.recommendation] || 'var(--text3)' }}>{a.recommendation}</span>
                      <span style={{ color: 'var(--text2)', fontSize: 10 }}>{a.confidence_score ? `${Math.round(a.confidence_score * 100)}%` : ''}</span>
                      <span style={{ color: 'var(--text3)', fontSize: 10, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.summary?.slice(0, 80)}</span>
                    </div>
                  ))}
                  {(() => {
                    const recs = data.agent_results.map(a => a.recommendation)
                    const unique = [...new Set(recs)]
                    return unique.length > 1 ? (
                      <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 4, fontWeight: 600 }}>
                        CONFLICT: {unique.join(' vs ')}
                      </div>
                    ) : null
                  })()}
                </div>
              ) : (
                <div style={{ color: 'var(--text3)', fontSize: 10 }}>No recent agent analyses</div>
              )}
            </div>

            {/* News */}
            <div style={{ padding: 12, background: 'var(--bg2)', borderRadius: 8, marginBottom: 12 }}>
              <div style={{ ...lbl, marginBottom: 6 }}>Recent News (7d)</div>
              {data.news.length > 0 ? data.news.map((n, i) => (
                <div key={i} style={{ fontSize: 10, padding: '3px 0', borderBottom: '1px solid var(--border)', color: 'var(--text1)' }}>
                  <span style={{ color: 'var(--text3)', marginRight: 6 }}>[{n.source}]</span>
                  {n.title?.slice(0, 80)}
                  <span style={{ color: 'var(--accent)', marginLeft: 6 }}>{n.relevance_score}%</span>
                </div>
              )) : <div style={{ color: 'var(--text3)', fontSize: 10 }}>No recent news</div>}
            </div>

            {/* Past Outcomes */}
            {data.outcomes.length > 0 && (
              <div style={{ padding: 12, background: 'var(--bg2)', borderRadius: 8, marginBottom: 12 }}>
                <div style={{ ...lbl, marginBottom: 6 }}>Past Outcomes</div>
                {data.outcomes.map((o, i) => (
                  <div key={i} style={{ fontSize: 10, color: 'var(--text2)', padding: '3px 0' }}>
                    {o.recommendation} at ${o.price_at_decision} → 7d: {o.price_7d ? `$${o.price_7d}` : '—'}
                    <span style={{ color: (o.outcome_score || 0) > 0 ? 'var(--green)' : 'var(--red)', marginLeft: 6 }}>
                      {(o.outcome_score || 0) > 0 ? 'CORRECT' : 'WRONG'}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* AI Recommendation */}
            {(() => {
              const ai = computeAiRec()
              if (!ai) return null
              return (
                <div style={{ padding: 12, background: 'rgba(74,144,244,0.06)', border: '1px solid rgba(74,144,244,0.15)', borderRadius: 8, marginBottom: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <span style={{ ...lbl }}>AI Recommendation</span>
                    <span style={{ fontSize: 16, fontWeight: 800, color: REC_COLOR[ai.rec] || 'var(--text1)' }}>{ai.rec}</span>
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.6 }}>
                    {ai.reasons.map((r, i) => <div key={i}>- {r}</div>)}
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>Confidence: {ai.conf}%</div>
                </div>
              )
            })()}

            {/* Proposal reason */}
            <div style={{ padding: 10, background: 'var(--bg3)', borderRadius: 6, marginBottom: 12, fontSize: 10, color: 'var(--text2)', lineHeight: 1.5 }}>
              <div style={{ ...lbl, marginBottom: 3 }}>Proposal Reason</div>
              {data.proposal.reason || 'No reason provided'}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
```

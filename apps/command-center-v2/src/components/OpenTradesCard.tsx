import { useApi } from '../hooks/useApi'

interface OpenTrade {
  id: number; symbol: string; strategy_id: string
  entry_price: number; current_price: number; shares: number
  stop_loss: number; target_1: number
  pnl: number; pnl_pct: number; r_multiple: number | null; rr_ratio: number | null
  dist_to_stop_pct: number | null; dist_to_stop_usd: number | null
  dist_to_target_pct: number | null; dist_to_target_usd: number | null
  risk_flags: string[]; trail_recommendation: string; trail_advice: string
  opened_at: string; catalyst: string | null
}

interface OpenTradesData { trades: OpenTrade[]; count: number; total_unrealized_pnl: number; last_updated_at?: string }

const pf = (v: number | null) => v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`
const uf = (v: number | null) => v == null ? '—' : `${v >= 0 ? '+' : '-'}$${Math.abs(v).toFixed(2)}`

export default function OpenTradesCard() {
  const { data } = useApi<OpenTradesData>('/api/v2/open-trades', 60_000)

  if (!data || data.count === 0) return (
    <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 10, padding: '14px 18px', fontSize: 13, color: 'rgba(255,255,255,0.4)', marginBottom: 16 }}>
      No open paper trades right now.
    </div>
  )

  return (
    <div>
      {data.last_updated_at && (
        <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', fontFamily: 'monospace', marginBottom: 8, textAlign: 'right' }}>
          Prices updated {new Date(data.last_updated_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
        </div>
      )}
      {data.trades.map(t => {
        const isUp = (t.pnl ?? 0) >= 0
        const range = (t.target_1 ?? 0) - (t.stop_loss ?? 0)
        const pos = range > 0 ? Math.max(0, Math.min(100, ((t.current_price - t.stop_loss) / range) * 100)) : 50
        const entryPos = range > 0 ? Math.max(0, Math.min(100, ((t.entry_price - t.stop_loss) / range) * 100)) : 50

        return (
          <div key={t.id} style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 12, padding: '16px 20px', marginBottom: 16, borderLeft: `3px solid ${isUp ? '#22c55e' : '#ef4444'}` }}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
              <div>
                <span style={{ fontSize: 20, fontWeight: 600, color: 'rgba(255,255,255,0.9)' }}>{t.symbol}</span>
                <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)', marginLeft: 8 }}>
                  {(t.strategy_id ?? '').replace(/_/g, ' ')} · {t.shares} shares
                </span>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 18, fontWeight: 600, color: isUp ? '#4ade80' : '#f87171' }}>{uf(t.pnl)}</div>
                <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)' }}>
                  {pf(t.pnl_pct)} · {t.r_multiple != null ? `${t.r_multiple >= 0 ? '+' : ''}${t.r_multiple.toFixed(2)}R` : ''}
                </div>
              </div>
            </div>

            {/* Price ladder */}
            <div style={{ marginBottom: 14 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'rgba(255,255,255,0.4)', marginBottom: 4 }}>
                <span>Stop ${(t.stop_loss ?? 0).toFixed(2)}</span>
                <span style={{ color: 'rgba(255,255,255,0.7)', fontWeight: 500 }}>Now ${(t.current_price ?? 0).toFixed(3)}</span>
                <span>Target ${(t.target_1 ?? 0).toFixed(2)}</span>
              </div>
              <div style={{ height: 10, borderRadius: 5, background: 'rgba(255,255,255,0.08)', position: 'relative', overflow: 'hidden' }}>
                <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(to right,rgba(239,68,68,0.3) 0%,rgba(245,158,11,0.3) 40%,rgba(34,197,94,0.3) 100%)' }} />
                <div style={{ position: 'absolute', top: 0, bottom: 0, width: 3, background: isUp ? '#22c55e' : '#ef4444', left: `calc(${pos}% - 1.5px)`, borderRadius: 2 }} />
                <div style={{ position: 'absolute', top: 2, bottom: 2, width: 2, background: 'rgba(255,255,255,0.4)', left: `calc(${entryPos}% - 1px)` }} />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'rgba(255,255,255,0.3)', marginTop: 3 }}>
                <span>loss zone</span>
                <span>entry ${(t.entry_price ?? 0).toFixed(2)}</span>
                <span>profit zone</span>
              </div>
            </div>

            {/* Key numbers */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, marginBottom: 14 }}>
              {[
                { label: 'Entry', value: `$${(t.entry_price ?? 0).toFixed(2)}`, color: 'rgba(255,255,255,0.7)' },
                { label: 'Current', value: `$${(t.current_price ?? 0).toFixed(3)}`, color: isUp ? '#4ade80' : '#f87171' },
                { label: 'Stop dist', value: pf(t.dist_to_stop_pct), color: '#f87171' },
                { label: 'Target dist', value: pf(t.dist_to_target_pct), color: '#4ade80' },
              ].map(k => (
                <div key={k.label} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: 8, padding: '8px 10px', textAlign: 'center' }}>
                  <div style={{ fontSize: 15, fontWeight: 500, color: k.color }}>{k.value}</div>
                  <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', marginTop: 2 }}>{k.label}</div>
                </div>
              ))}
            </div>

            {/* Risk flags */}
            {(t.risk_flags?.length ?? 0) > 0 && (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
                {t.risk_flags.map(f => (
                  <span key={f} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 4, fontWeight: 500, background: 'rgba(239,68,68,0.15)', color: '#fca5a5' }}>
                    {f.replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
            )}

            {/* Trail advice */}
            <div style={{ background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.2)', borderRadius: 8, padding: '10px 12px', fontSize: 12, color: 'rgba(255,255,255,0.7)', lineHeight: 1.5 }}>
              <span style={{ color: '#fbbf24', fontWeight: 500 }}>
                {t.trail_recommendation === 'keep_fixed' ? 'Trail: Keep fixed stop' : 'Trail: Consider trailing stop'}
              </span>
              {' — '}{t.trail_advice}
            </div>
          </div>
        )
      })}
    </div>
  )
}

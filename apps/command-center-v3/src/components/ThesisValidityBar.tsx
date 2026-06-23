import { zoneColor, type ThesisValidity } from '../lib/brokerThesis'

const MUTED = '#94a3b8'
const TEXT0 = '#f8fafc'

type Props = {
  tv?: ThesisValidity | null
  compact?: boolean
  showSourceNote?: boolean
}

export default function ThesisValidityBar({ tv, compact, showSourceNote }: Props) {
  if (!tv?.ok) {
    return (
      <div style={{ fontSize: 10, color: MUTED, fontStyle: 'italic', padding: compact ? '4px 0' : '8px 10px',
        background: 'rgba(15,23,42,.4)', borderRadius: 8, border: '1px dashed rgba(148,163,184,.25)' }}>
        Thesis band unavailable — refresh prices
      </div>
    )
  }

  const low = Number(tv.valid_low ?? tv.stop ?? 0)
  const high = Number(tv.valid_high ?? tv.entry ?? 0)
  const stop = Number(tv.stop ?? low)
  const target = Number(tv.target ?? high)
  const live = tv.current_price != null ? Number(tv.current_price) : null
  const entry = Number(tv.entry ?? (low + high) / 2)
  const span = Math.max(high - low, 0.01)
  const chartMin = Math.min(stop, low) * 0.998
  const chartMax = Math.max(target, high) * 1.002
  const chartSpan = Math.max(chartMax - chartMin, 0.01)
  const pct = (v: number) => `${Math.min(100, Math.max(0, ((v - chartMin) / chartSpan) * 100))}%`
  const color = zoneColor(tv.zone_status, tv.zone_color)

  return (
    <div style={{
      padding: compact ? '8px 10px' : '10px 12px',
      borderRadius: 10,
      background: `${color}0d`,
      border: `1px solid ${color}44`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <div style={{ fontSize: 10, fontWeight: 800, color, textTransform: 'uppercase', letterSpacing: '.04em' }}>
          Thesis validity · {String(tv.zone_status || 'unknown').replace(/_/g, ' ')}
        </div>
        {live != null && (
          <div style={{ fontSize: 10, fontFamily: 'monospace', color: TEXT0 }}>
            Live <b style={{ color }}>${live.toFixed(2)}</b>
            {tv.drift_pct != null && (
              <span style={{ color: Math.abs(tv.drift_pct) > 3 ? '#f59e0b' : MUTED, marginLeft: 6 }}>
                {tv.drift_pct >= 0 ? '+' : ''}{tv.drift_pct}%
              </span>
            )}
            {tv.current_rr != null && (
              <span style={{ color: MUTED, marginLeft: 6 }}>R:R {tv.current_rr}:1</span>
            )}
          </div>
        )}
      </div>

      <div style={{ position: 'relative', height: compact ? 22 : 28, marginBottom: 6 }}>
        {/* track */}
        <div style={{ position: 'absolute', left: 0, right: 0, top: '50%', transform: 'translateY(-50%)', height: 6, borderRadius: 3, background: 'rgba(15,23,42,.7)' }} />
        {/* valid band */}
        <div style={{
          position: 'absolute', top: '50%', transform: 'translateY(-50%)', height: 10, borderRadius: 4,
          left: pct(low), width: `calc(${pct(high)} - ${pct(low)})`,
          background: `linear-gradient(90deg, ${color}55, ${color}99)`,
          border: `1px solid ${color}`,
          boxShadow: `0 0 12px ${color}33`,
        }} />
        {/* stop marker */}
        <div title={`Stop $${stop.toFixed(2)}`} style={{
          position: 'absolute', top: 2, bottom: 2, width: 2, left: pct(stop), background: '#ef4444', borderRadius: 1,
        }} />
        {/* target marker */}
        <div title={`Target $${target.toFixed(2)}`} style={{
          position: 'absolute', top: 2, bottom: 2, width: 2, left: pct(target), background: '#22c55e', borderRadius: 1,
        }} />
        {/* entry marker */}
        <div title={`Entry $${entry.toFixed(2)}`} style={{
          position: 'absolute', top: 0, bottom: 0, width: 3, left: pct(entry), background: '#60a5fa', borderRadius: 2,
        }} />
        {/* live price */}
        {live != null && (
          <div title={`Current $${live.toFixed(2)}`} style={{
            position: 'absolute', top: '50%', transform: 'translate(-50%, -50%)',
            left: pct(live), width: 12, height: 12, borderRadius: '50%',
            background: color, border: '2px solid #f8fafc', boxShadow: `0 0 8px ${color}`,
          }} />
        )}
      </div>

      <div style={{ fontSize: 9.5, color: TEXT0, fontWeight: 600, marginBottom: 4 }}>
        {tv.label || `Valid $${low.toFixed(2)} – $${high.toFixed(2)}`}
      </div>
      {showSourceNote && (
        <div style={{ fontSize: 8.5, color: MUTED, marginBottom: 4 }}>
          Price math from entry/stop/target + live quote — not Grok/ChatGPT cloud review.
        </div>
      )}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 9, color: MUTED }}>
        <span>↓ room {tv.room_down_pct != null ? `${tv.room_down_pct.toFixed(1)}%` : '—'}</span>
        <span>↑ room {tv.room_up_pct != null ? `${tv.room_up_pct.toFixed(1)}%` : '—'}</span>
        <span>band ${(span).toFixed(2)} wide</span>
      </div>
      {(tv.reasons?.length ?? 0) > 0 && (
        <div style={{ marginTop: 6, fontSize: 9 }}>
          {tv.reasons!.map((r, i) => (
            <div key={i} style={{ color: tv.zone_color === 'red' ? '#ef4444' : '#f59e0b' }}>• {r}</div>
          ))}
        </div>
      )}
    </div>
  )
}
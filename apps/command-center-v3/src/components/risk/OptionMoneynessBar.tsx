const GREEN = '#22c55e'
const AMBER = '#f59e0b'
const RED = '#ef4444'
const BLUE = '#60a5fa'
const MUTED = 'var(--text3)'

type Props = {
  moneyness?: string
  spot?: number
  strike?: number
  popOtm?: number | null
  popItm?: number | null
  optionType?: string
  compact?: boolean
}

export default function OptionMoneynessBar({
  moneyness, spot, strike, popOtm, popItm, optionType = 'call', compact,
}: Props) {
  if (!spot || !strike) return null

  const isCall = !optionType.includes('put')
  const itm = moneyness === 'ITM' || (isCall ? spot > strike : spot < strike)
  const otm = moneyness === 'OTM' || (isCall ? spot < strike : spot > strike)
  const zoneColor = itm ? RED : otm ? GREEN : AMBER
  const zoneLabel = moneyness || (itm ? 'ITM' : otm ? 'OTM' : 'ATM')

  const lo = Math.min(spot, strike) * 0.92
  const hi = Math.max(spot, strike) * 1.08
  const span = Math.max(hi - lo, 0.01)
  const pct = (v: number) => `${Math.min(100, Math.max(0, ((v - lo) / span) * 100))}%`
  const pop = otm ? (popOtm ?? popItm) : (popItm ?? popOtm)

  return (
    <div style={{
      marginTop: compact ? 8 : 10,
      padding: compact ? '7px 9px' : '8px 10px',
      borderRadius: 8,
      background: `${zoneColor}0a`,
      border: `1px solid ${zoneColor}33`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 9, fontWeight: 800, color: zoneColor, textTransform: 'uppercase', letterSpacing: '.04em' }}>
          {zoneLabel} · {isCall ? 'call' : 'put'}
        </span>
        {pop != null && (
          <span style={{ fontSize: 9, color: MUTED }}>
            POP {otm ? 'OTM' : 'ITM'} <b style={{ color: zoneColor }}>{Math.round(pop)}%</b>
          </span>
        )}
      </div>
      <div style={{ position: 'relative', height: compact ? 14 : 18 }}>
        <div style={{
          position: 'absolute', left: 0, right: 0, top: '50%', transform: 'translateY(-50%)',
          height: 5, borderRadius: 3, background: 'rgba(15,23,42,.65)',
        }} />
        <div style={{
          position: 'absolute', top: '50%', transform: 'translateY(-50%)', height: 8, borderRadius: 4,
          left: pct(Math.min(spot, strike)), width: `calc(${pct(Math.max(spot, strike))} - ${pct(Math.min(spot, strike))})`,
          background: `linear-gradient(90deg, ${GREEN}44, ${AMBER}55, ${RED}44)`,
        }} />
        <div title={`Strike $${strike.toFixed(2)}`} style={{
          position: 'absolute', top: 2, bottom: 2, width: 2, left: pct(strike),
          background: '#a855f7', borderRadius: 1,
        }} />
        <div title={`Spot $${spot.toFixed(2)}`} style={{
          position: 'absolute', top: '50%', transform: 'translate(-50%, -50%)',
          left: pct(spot), width: 10, height: 10, borderRadius: '50%',
          background: BLUE, border: '2px solid #f8fafc', boxShadow: `0 0 6px ${BLUE}`,
        }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, color: MUTED, marginTop: 4 }}>
        <span>K ${strike.toFixed(2)}</span>
        <span>Spot ${spot.toFixed(2)}</span>
      </div>
    </div>
  )
}
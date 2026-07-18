import { BB, T, DASH, numStyle } from '../../lib/watchTokens'

// Defense v6 WS-LAD — the ladder as a visual stepper, not chip soup. ONE component
// for card faces and the Rotation Plan. 14px bold tranche labels, ~28px tall,
// readable at arm's length: done=green fill · armed=amber · fired=red ·
// disarmed=slate strike. Fired segments carry timestamp + cause on the track.

function seg(status: string): { color: string; fill: string; strike?: boolean } {
  switch (status) {
    case 'executed': return { color: BB.green, fill: BB.greenDim ?? 'transparent' }
    case 'fired': return { color: BB.red, fill: 'transparent' }
    case 'armed': return { color: BB.amber, fill: 'transparent' }
    case 'disarmed': return { color: BB.text3, fill: 'transparent', strike: true }
    default: return { color: BB.text3, fill: 'transparent' }
  }
}

function fmtDate(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.toLocaleString('en-US', { month: 'short' })} ${d.getDate()}`
}

export default function LadderTrack({ ladder, price }: { ladder: any; price?: number | null }) {
  if (!ladder) return null
  const t1Done = ladder.t1_status === 'executed'
  const steps: Array<{ label: string; sub?: string; status: string }> = [{
    label: `T1 ${t1Done ? '✓ ' : ''}${ladder.t1_fraction}%${t1Done ? ' sold' : ' advised'}`,
    status: t1Done ? 'executed' : 'advised',
  }]
  for (const t of ladder.tranches || []) {
    const armedTriggers = (t.triggers || [])
    let sub: string | undefined
    if (t.status === 'armed') {
      const priceTrig = armedTriggers.find((x: any) => x.type === 'price_below')
      const nearest = priceTrig
        ? `close < $${priceTrig.level}` + (price && priceTrig.level
          ? ` (${(((priceTrig.level - price) / price) * 100).toFixed(1)}% away)` : '')
        : armedTriggers[0]?.label
      sub = `${armedTriggers.length} triggers · nearest: ${nearest || '—'}`
    } else if (t.status === 'fired') {
      sub = `FIRED ${fmtDate(t.fired_at)} · ${(t.fired_by || '').slice(0, 44)}`
    } else if (t.status === 'disarmed') {
      sub = `DISARMED · ${(t.disarmed_reason || '').slice(0, 44)}`
    } else if (t.status === 'executed') {
      sub = `✓ sold ${fmtDate(t.executed_at)}`
    }
    steps.push({
      label: `${t.tranche} ${t.status === 'armed' ? '▲ ARMED' : t.status === 'fired' ? '⚠ FIRED' : t.status === 'executed' ? `✓ +${t.add_fraction_pct}%` : t.status.toUpperCase()}`,
      sub, status: t.status,
    })
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, flexWrap: 'wrap', minHeight: 28, margin: '4px 0' }}>
      {steps.map((s, i) => {
        const sg = seg(s.status)
        return (
          <span key={i} style={{ display: 'flex', alignItems: 'center' }}>
            {i > 0 && <span style={{ width: 26, height: 2, background: BB.borderHair, display: 'inline-block' }} />}
            <span title={s.sub} style={{
              display: 'inline-flex', flexDirection: 'column', border: `1.5px solid ${sg.color}`,
              background: sg.fill, borderRadius: 3, padding: '3px 10px',
              textDecoration: sg.strike ? 'line-through' : 'none',
            }}>
              <span style={{ fontSize: DASH.section, fontWeight: 800, color: sg.color, lineHeight: 1.15, whiteSpace: 'nowrap' }}>{s.label}</span>
              {s.sub && <span style={{ ...numStyle, fontSize: DASH.data, color: s.status === 'fired' ? sg.color : BB.text3, lineHeight: 1.25, whiteSpace: 'nowrap' }}>{s.sub}</span>}
            </span>
          </span>
        )
      })}
    </div>
  )
}

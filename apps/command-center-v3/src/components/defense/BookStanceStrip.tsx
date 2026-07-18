import { useState } from 'react'
import { BB, T, DASH, numStyle } from '../../lib/watchTokens'

// Defense v4 L3 — every ≥$10K position carries an explicit stance, INCLUDING HOLD.
// Silence about the core was the failure; assessed-and-holding is the fix.

const STANCE_COLOR: Record<string, string> = {
  HOLD: BB.green, ADD: T.link, TRIM: BB.red, 'TRIM-WATCH': BB.amber, ROTATE: BB.amber, HEDGED: BB.text2,
}

export default function BookStanceStrip({ stances, notDecomposed, ladders }: { stances: any[]; notDecomposed?: any; ladders?: any[] }) {
  const [open, setOpen] = useState<string | null>(null)
  if (!stances?.length) return null
  // v5 EL3 — ladder progress inline on the stance chip
  const ladderFor = (sym: string, acct: string) => {
    const lad = (ladders || []).find(l => l.symbol === sym && l.account === acct && l.status === 'open')
    if (!lad) return null
    const armed = (lad.tranches || []).filter((t: any) => t.status === 'armed').length
    const fired = (lad.tranches || []).filter((t: any) => t.status === 'fired').length
    return `T1 ${lad.t1_fraction}% ${lad.t1_status === 'executed' ? '✓' : 'advised'}`
      + (fired ? ` · ${fired} FIRED` : armed ? ` · T2 armed` : '')
  }
  const counts: Record<string, number> = {}
  stances.forEach(s => { counts[s.stance] = (counts[s.stance] || 0) + 1 })
  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '10px 12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: DASH.panel, fontWeight: 800, color: BB.text1 }}>
          Your book <span style={{ fontSize: DASH.data, color: BB.text3, fontWeight: 600 }}>· every position ≥$10K has a stance</span>
        </span>
        <span style={{ fontSize: DASH.data, color: BB.text3 }}>
          {Object.entries(counts).map(([k, n]) => (
            <span key={k} style={{ marginLeft: 10 }}><b style={{ color: STANCE_COLOR[k] || BB.text2 }}>{n}</b> {k}</span>
          ))}
          {notDecomposed?.dollars ? <span style={{ marginLeft: 10 }}>· ${Math.round(notDecomposed.dollars / 1000)}K not decomposed</span> : null}
        </span>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {stances.map(s => {
          const key = `${s.symbol}-${s.account}`
          const c = STANCE_COLOR[s.stance] || BB.text2
          const isOpen = open === key
          return (
            <div key={key} onClick={() => setOpen(isOpen ? null : key)} style={{
              border: `1px solid ${BB.border}`, borderLeft: `3px solid ${c}`, borderRadius: 2,
              padding: '4px 9px', cursor: 'pointer', minWidth: isOpen ? '100%' : undefined,
            }}>
              <span style={{ fontSize: DASH.data, fontWeight: 800, color: BB.text1 }}>{s.symbol}</span>
              <span style={{ ...numStyle, fontSize: DASH.data, color: BB.text2, marginLeft: 6 }}>${Math.round(s.value / 1000)}K</span>
              <span style={{ fontSize: DASH.chip, fontWeight: 800, color: c, marginLeft: 8, textTransform: 'uppercase' }}>{s.stance}</span>
              <span style={{ fontSize: DASH.chip, color: BB.text3, marginLeft: 6 }}>{s.account_label}</span>
              {ladderFor(s.symbol, s.account) && (
                <span style={{ fontSize: DASH.chip, fontWeight: 700, color: BB.amber, marginLeft: 6 }}>{ladderFor(s.symbol, s.account)}</span>
              )}
              {isOpen && (
                <div style={{ fontSize: DASH.data, color: BB.text2, marginTop: 4 }}>{s.reason}</div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

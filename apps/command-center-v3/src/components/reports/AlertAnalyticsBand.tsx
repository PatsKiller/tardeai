import { useState } from 'react'
import { useApi } from '../../hooks/useApi'
import { BB, T, TYPE, numStyle } from '../../lib/watchTokens'
import { Chip } from '../TerminalChip'

// Reports Desk v1 (WS-D): alert & message analytics over the archive corpora.
// Deterministic rollups from /api/v2/reports/analytics; clicking a type drills the
// archive list (onDrillType). Parity line states raw-store vs portal-indexed honestly.

export default function AlertAnalyticsBand({ onDrillType }: { onDrillType?: (q: string) => void }) {
  const [days, setDays] = useState(30)
  const { data } = useApi<any>(`/api/v2/reports/analytics?days=${days}`, 300_000)
  const [open, setOpen] = useState(true)
  const [showPolicy, setShowPolicy] = useState(false)
  if (!data?.ok) return null
  const byDay: any[] = data.by_day ?? []
  const max = Math.max(1, ...byDay.map(d => (d.alerts || 0) + (d.telegram || 0) + (d.notifications || 0)))
  const sev: any[] = data.by_severity ?? []
  const types: any[] = data.top_types ?? []
  const noisy: any[] = data.noisiest_sources ?? []
  const par = data.parity ?? {}
  const sevTone: Record<string, 'red' | 'amber' | 'slate' | 'green'> = { critical: 'red', urgent: 'red', warning: 'amber', info: 'slate' }

  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderLeft: `3px solid ${BB.amber}`, borderRadius: 2, padding: '10px 12px' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.06em', color: BB.text3 }}>ALERT & MESSAGE ANALYTICS · {days}d <span style={{ fontWeight: 700, color: BB.amber }}>· raw events</span></span>
        {[7, 30, 90].map(d => (
          <button key={d} onClick={() => setDays(d)}
                  style={{ fontSize: TYPE.xs, fontWeight: days === d ? 800 : 600, padding: '1px 8px', borderRadius: 2, cursor: 'pointer',
                           border: `1px solid ${days === d ? BB.amber : BB.border}`, background: days === d ? BB.amberDim : 'transparent',
                           color: days === d ? BB.amber : BB.text3 }}>{d}d</button>
        ))}
        {sev.map(s => <Chip key={s.severity} kind="state" tone={sevTone[s.severity] || 'slate'}>{`${s.severity} ${s.n.toLocaleString()}`}</Chip>)}
        <button onClick={() => setOpen(o => !o)} style={{ marginLeft: 'auto', fontSize: TYPE.xs, color: BB.text3, background: 'transparent', border: 'none', cursor: 'pointer' }}>{open ? '▾ collapse' : '▸ expand'}</button>
      </div>

      {open && (
        <>
          {/* daily volume bars */}
          <div style={{ display: 'flex', gap: 2, alignItems: 'flex-end', height: 46, marginTop: 8 }}>
            {byDay.map((d, i) => {
              const tot = (d.alerts || 0) + (d.telegram || 0) + (d.notifications || 0)
              return <div key={i} title={`${d.day}: ${d.alerts} alerts · ${d.telegram} telegram · ${d.notifications} notifications`}
                          style={{ flex: 1, minWidth: 3, height: Math.max(2, (tot / max) * 44), background: tot > 0 ? `${T.link}88` : BB.border, borderRadius: 1 }} />
            })}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 8 }}>
            <div>
              <div style={{ fontSize: TYPE.xs, fontWeight: 800, color: BB.text3, letterSpacing: '.05em', marginBottom: 4 }}>TOP ALERT TYPES — click to drill the archive</div>
              {types.slice(0, 8).map((t, i) => (
                <div key={i} onClick={() => onDrillType?.(t.alert_type)}
                     style={{ display: 'flex', gap: 8, fontSize: TYPE.xs, padding: '2px 0', borderBottom: `1px solid ${BB.borderHair}`, cursor: onDrillType ? 'pointer' : 'default', alignItems: 'baseline' }}>
                  <span style={{ color: T.link, minWidth: 170, textDecoration: 'underline dotted' }}>{t.alert_type}</span>
                  <span style={{ ...numStyle, color: BB.text1, minWidth: 60, textAlign: 'right' }}>{t.n.toLocaleString()}</span>
                  <span style={{ ...numStyle, color: BB.text3 }}>acked {t.acked}</span>
                </div>
              ))}
            </div>
            <div>
              <div style={{ fontSize: TYPE.xs, fontWeight: 800, color: BB.text3, letterSpacing: '.05em', marginBottom: 4 }}>NOISIEST PRODUCERS</div>
              {noisy.slice(0, 8).map((s, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, fontSize: TYPE.xs, padding: '2px 0', borderBottom: `1px solid ${BB.borderHair}`, alignItems: 'baseline' }}>
                  <span style={{ color: BB.text2, minWidth: 200 }}>{s.source}</span>
                  <span style={{ ...numStyle, color: BB.text1 }}>{s.n.toLocaleString()}</span>
                </div>
              ))}
              <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 6 }} title={par.note}>
                parity: raw {Object.entries(par.raw_stores || {}).map(([k, v]: any) => `${k} ${v?.toLocaleString?.() ?? v}`).join(' · ')} → portal-indexed {par.portal_indexed_total?.toLocaleString?.()}
                <span onClick={() => setShowPolicy(v => !v)} style={{ cursor: 'pointer', color: T.link }}> ⓘ indexing policy</span>
              </div>
              {showPolicy && data.index_policy && (
                <div style={{ marginTop: 6, padding: '7px 9px', background: BB.bg, border: `1px solid ${BB.borderHair}`, borderRadius: 2 }}>
                  <div style={{ fontSize: TYPE.xs, fontWeight: 800, color: BB.text3, letterSpacing: '.05em', marginBottom: 3 }}>INDEXING POLICY (config/report_index_policy.json)</div>
                  <div style={{ fontSize: TYPE.xs, color: BB.text3, marginBottom: 4 }}>default: {data.index_policy.default}</div>
                  {Object.entries(data.index_policy.classes || {}).map(([k, v]: any) => (
                    <div key={k} style={{ fontSize: TYPE.xs, padding: '1px 0', display: 'flex', gap: 8 }}>
                      <span style={{ ...numStyle, color: BB.text2, minWidth: 150, flexShrink: 0 }}>{k}</span>
                      <span style={{ color: BB.text3 }}>{v}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

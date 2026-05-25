import { useNavigate } from 'react-router-dom'
import { fmt$ } from '../../lib/format'
import type { RiskData, RiskPos, EscItem } from './types'
import s from './MorningBrief.module.css'

interface Props { rk: RiskData | null }

export default function RiskExposurePanel({ rk }: Props) {
  const nav = useNavigate()
  if (!rk) return null

  const trig = rk.positions.filter(p => p.triggered)
  const danger = rk.escalation?.danger || []
  const warning = rk.escalation?.warning || []
  const unprot = rk.escalation?.unprotected || []
  const protPct = rk.pct_protected
  const unprotPct = 100 - protPct
  const topRisk = [...trig.map(t => ({ sym: t.symbol, val: t.max_loss })), ...danger.map(d => ({ sym: d.symbol, val: d.max_loss ?? 0 }))].sort((a, b) => b.val - a.val)
  const maxRisk = topRisk.length > 0 ? topRisk[0].val : 1

  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6, padding: '10px 12px' }}>
      <div className={s.secHead}>
        <span className={`${s.secTitle} ${s.sans}`}>Risk & Exposure</span>
        <button className={`${s.secLink} ${s.sans}`} onClick={() => nav('/risk')}>Full Risk View</button>
      </div>

      {/* Protection stacked bar */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, fontWeight: 700, marginBottom: 3 }} className={s.sans}>
          <span style={{ color: 'var(--green)' }}>Protected {protPct.toFixed(0)}%</span>
          <span style={{ color: 'var(--amber)' }}>Unprotected {unprotPct.toFixed(0)}%</span>
        </div>
        <div className={s.riskBar}>
          <div className={s.riskBarSeg} style={{ width: `${protPct}%`, background: 'var(--green)', opacity: 0.7 }} />
          <div className={s.riskBarSeg} style={{ width: `${unprotPct}%`, background: 'var(--amber)', opacity: 0.5 }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, marginTop: 3 }} className={s.sans}>
          <span style={{ color: 'var(--text3)' }}>Heat: <strong style={{ color: rk.portfolio_heat_pct > 5 ? 'var(--red)' : 'var(--amber)' }}>{rk.portfolio_heat_pct.toFixed(1)}%</strong></span>
          <span style={{ color: 'var(--text3)' }}>Total risk: <strong style={{ color: 'var(--red)' }}>{fmt$(rk.total_risk_dollars)}</strong></span>
          <span style={{ color: 'var(--text3)' }}>{rk.position_count} positions</span>
        </div>
      </div>

      {/* Top risk by exposure — horizontal bars */}
      {topRisk.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div className={s.sans} style={{ fontSize: 8, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 4 }}>Top Exposure by $</div>
          {topRisk.slice(0, 5).map(r => (
            <div key={r.sym} className={s.riskRow} onClick={() => nav(`/risk?symbol=${r.sym}`)}>
              <span className={s.sans} style={{ fontWeight: 700, color: 'var(--text0)', width: 40 }}>{r.sym}</span>
              <div style={{ flex: 1, height: 6, background: 'var(--bg3)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${(r.val / maxRisk) * 100}%`, height: '100%', background: 'var(--red)', opacity: 0.6, borderRadius: 3 }} />
              </div>
              <span className={s.sans} style={{ fontWeight: 700, color: 'var(--red)', fontSize: 10, width: 60, textAlign: 'right' }}>{fmt$(r.val)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Tiered lists */}
      {trig.length > 0 && <TierList label="Triggered" count={trig.length} color="var(--red)" items={trig.map(t => ({ sym: t.symbol, detail: `${fmt$(t.current_price, 2)} / stop ${t.stop_price ? fmt$(t.stop_price, 2) : '—'}`, val: fmt$(t.max_loss) }))} onSymClick={sym => nav(`/risk?symbol=${sym}`)} />}
      {danger.length > 0 && <TierList label="Danger Zone" count={danger.length} color="var(--amber)" items={danger.map(d => ({ sym: d.symbol, detail: `${d.distance_pct?.toFixed(1) ?? '—'}% from stop`, val: fmt$(d.max_loss ?? 0) }))} onSymClick={sym => nav(`/risk?symbol=${sym}`)} />}
      {warning.length > 0 && <TierList label="Warning" count={warning.length} color="var(--text3)" items={warning.slice(0, 3).map(w => ({ sym: w.symbol, detail: `${w.distance_pct?.toFixed(1) ?? '—'}% from stop`, val: fmt$(w.max_loss ?? 0) }))} onSymClick={sym => nav(`/risk?symbol=${sym}`)} />}

      {unprot.length > 0 && (
        <div style={{ marginTop: 6 }}>
          <div className={s.sans} style={{ fontSize: 8, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 2 }}>Unprotected ({unprot.length})</div>
          <div className={s.sans} style={{ fontSize: 10, color: 'var(--text2)' }}>{unprot.slice(0, 8).map(u => u.symbol).join(', ')}{unprot.length > 8 ? ` +${unprot.length - 8}` : ''}</div>
          <div className={s.sans} style={{ fontSize: 9, color: 'var(--text3)', marginTop: 1 }}>Total: {fmt$(rk.total_unprotected_mv)}</div>
        </div>
      )}

      {trig.length === 0 && danger.length === 0 && warning.length === 0 && unprot.length === 0 && (
        <div className={s.sans} style={{ fontSize: 10, color: 'var(--green)', padding: '6px 0' }}>All positions within safe parameters.</div>
      )}
    </div>
  )
}

function TierList({ label, count, color, items, onSymClick }: { label: string; count: number; color: string; items: { sym: string; detail: string; val: string }[]; onSymClick: (sym: string) => void }) {
  return (
    <div style={{ marginBottom: 6 }}>
      <div className={s.sans} style={{ fontSize: 8, fontWeight: 700, color, textTransform: 'uppercase', marginBottom: 2 }}>{label} ({count})</div>
      {items.map(i => (
        <div key={i.sym} className={s.riskRow} onClick={() => onSymClick(i.sym)}>
          <span className={s.sans} style={{ fontWeight: 700, color: 'var(--text0)', width: 40 }}>{i.sym}</span>
          <span className={s.sans} style={{ color: 'var(--text2)', flex: 1 }}>{i.detail}</span>
          <span className={s.sans} style={{ fontWeight: 700, color, whiteSpace: 'nowrap' }}>{i.val}</span>
        </div>
      ))}
    </div>
  )
}

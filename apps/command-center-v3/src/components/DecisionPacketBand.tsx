import { useState, type CSSProperties } from 'react'
import { BB } from '../lib/watchlistTerminalTokens'

/*
 * DecisionPacketBand — the PRIMARY decision surface (Stage: primary-card replacement).
 *
 * Three-axis family display (2026-07-21 semantic integration):
 *   constructibility · decision · action
 * so EVENT_BLOCKED never renders as "Swing ELIGIBLE · READY".
 *
 * DATA AT BUILD (packet.data_quality) is separate from CURRENT VALIDITY
 * (packet vs current input hash).
 */

const STATE_COLOR: Record<string, string> = {
  ELIGIBLE: BB.green, CONDITIONAL: BB.amber, REJECTED: BB.red,
  NOT_APPLICABLE: BB.text3, DATA_UNAVAILABLE: BB.text3,
  READY: BB.green, BLOCKED: BB.red, STALE: BB.amber,
  CONSTRUCTIBLE: BB.green, UNCONSTRUCTIBLE: BB.red,
  CURRENT: BB.green, INVALIDATED: BB.red,
}
const THESIS_COLOR: Record<string, string> = {
  STRONG_CONVICTION: BB.green, CONSTRUCTIVE: BB.green,
  SPECULATIVE_CONSTRUCTIVE: BB.amber, NEUTRAL: BB.text3,
  DETERIORATING: BB.red, FUNDAMENTALLY_UNATTRACTIVE: BB.red,
  INSUFFICIENT_EVIDENCE: BB.text3,
}
const FAMILY_LABEL: Record<string, string> = {
  LONG_TERM: 'Long-term', SWING: 'Swing', BEARISH: 'Bearish',
  OPTIONS: 'Options', NO_TRADE: 'No-trade',
}
const FAMILY_ORDER = ['LONG_TERM', 'SWING', 'BEARISH', 'OPTIONS', 'NO_TRADE'] as const

function ageStr(iso?: string): string {
  if (!iso) return ''
  const ms = Date.now() - new Date(iso).getTime()
  if (!isFinite(ms) || ms < 0) return ''
  const m = Math.floor(ms / 60000)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

const n = (v: any, d = 2) => (v == null || isNaN(Number(v)) ? null : Number(v).toFixed(d))

function mechanics(fam: string, f: any): string {
  const s = (f?.structures || [])[0]
  if (!s) return ''
  if (fam === 'LONG_TERM') {
    const z = s.starter_entry?.price_or_zone || []
    const parts = []
    if (z.length === 2) parts.push(`starter ${n(z[0])}–${n(z[1])}`)
    if (s.stop_or_invalidation?.price) parts.push(`stop ${n(s.stop_or_invalidation.price)}`)
    if ((s.targets || [])[0]?.price) parts.push(`target ${n(s.targets[0].price)}`)
    if (s.reward_to_risk) parts.push(`R:R ${n(s.reward_to_risk, 1)}`)
    if (s.maximum_position_pct) parts.push(`max ${n(s.maximum_position_pct, 0)}%`)
    return parts.join(' · ')
  }
  if (fam === 'SWING') {
    const z = s.entry_zone || []
    const parts = []
    if (z.length === 2 && z[0]) parts.push(`zone ${n(z[0])}–${n(z[1])}`)
    if (s.limit_price) parts.push(`limit ${n(s.limit_price)}`)
    if (s.stop_price) parts.push(`stop ${n(s.stop_price)}`)
    if ((s.targets || [])[0]) parts.push(`tgt ${n(s.targets[0])}`)
    if (s.risk_reward) parts.push(`R:R ${n(s.risk_reward, 1)}`)
    if (s.urgency) parts.push(String(s.urgency))
    return parts.join(' · ')
  }
  if (fam === 'BEARISH' && (s.state === 'ELIGIBLE' || s.decision_state === 'ELIGIBLE')) {
    const parts = []
    if ((s.entry_zone || [])[0]) parts.push(`entry ${n(s.entry_zone[0])}–${n(s.entry_zone[1])}`)
    if (s.buy_stop) parts.push(`buy-stop ${n(s.buy_stop)}`)
    return parts.join(' · ')
  }
  return ''
}

function optionLine(s: any): string {
  const parts = [s.structure, s.state]
  if (s.strike) parts.push(`$${n(s.strike)}`)
  else if (s.occ_symbol) parts.push(String(s.occ_symbol))
  if (s.net_debit_mid) parts.push(`debit ${n(s.net_debit_mid)}`)
  if (s.maximum_loss != null) parts.push(`maxloss $${n(s.maximum_loss, 0)}`)
  if (s.breakeven) parts.push(`be ${n(s.breakeven)}`)
  const reason = (s.rejection_reasons || [])[0]
  if (reason) parts.push('— ' + String(reason).slice(0, 60))
  return parts.filter(Boolean).join(' ')
}

/** Family display: constructibility · decision · action (never one overloaded word). */
function familyStateLabel(f: any): { text: string; color: string } {
  const dec = String(f?.decision_state || f?.state || 'DATA_UNAVAILABLE')
  const act = String(f?.action_state || '')
  const constr = String(f?.constructibility_state || '')
  if (f?.family === 'NO_TRADE' || dec === 'NOT_APPLICABLE' && f?.available) {
    const pref = f?.preferred ? 'PREFERRED' : f?.dominant ? 'DOMINANT' : 'AVAILABLE'
    return { text: pref, color: f?.preferred || f?.dominant ? BB.amber : BB.text3 }
  }
  // Show decision · action when both present and differ; suppress READY under BLOCKED.
  if (act && act !== dec) {
    return {
      text: `${dec} · ${act}`,
      color: STATE_COLOR[act] || STATE_COLOR[dec] || BB.text3,
    }
  }
  if (constr && constr !== 'CONSTRUCTIBLE' && dec === 'ELIGIBLE') {
    return { text: `${constr} · ${dec}`, color: STATE_COLOR[dec] || BB.text3 }
  }
  return { text: dec, color: STATE_COLOR[dec] || BB.text3 }
}

export default function DecisionPacketBand({ packet, generatedAt }: { packet: any; generatedAt?: string }) {
  const [open, setOpen] = useState(true)
  if (!packet || typeof packet !== 'object') return null

  const lt = packet.horizons?.long_term || {}
  const thesis = String(lt.thesis_state || 'INSUFFICIENT_EVIDENCE')
  const ev = packet.event_state?.earnings || {}
  const dq = packet.data_quality || {}
  const mr = packet.model_review || {}
  const fams = packet.plan_families || {}
  const legacy = packet.legacy_summary || {}
  const accent = THESIS_COLOR[thesis] || BB.text3
  const cv = packet.current_validity || null
  const cvState = String(cv?.state || '').toUpperCase()
  const inputsStale = cvState === 'STALE' || cvState === 'INVALIDATED'

  const age = ageStr(generatedAt || packet.evaluated_at)
  const buildStale = dq.state && ['STALE', 'CONFLICTED', 'INSUFFICIENT', 'PROVIDER_DOWN'].includes(String(dq.state))

  const chip = (label: string, value: string, color: string) => (
    <span style={{ fontSize: 10, color: BB.text3, whiteSpace: 'nowrap' }}>
      {label} <b style={{ color }}>{value}</b>
    </span>
  )

  return (
    <div onClick={e => e.stopPropagation()}
      style={{ borderLeft: `3px solid ${accent}`, background: BB.bgShift,
               borderBottom: `1px solid ${BB.border}`, padding: '5px 10px' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.08em', color: accent,
                       textTransform: 'uppercase', flexShrink: 0 }}>DECISION</span>
        <span style={{ flex: 1, minWidth: 160, fontSize: 11, fontWeight: 800, color: BB.text0 }}>
          {packet.headline}
        </span>
        {/* One labelled legacy chip only — hide dual unqualified "prior" strips. */}
        {legacy.recommendation && (
          <span title={`LEGACY AT PACKET GENERATION · ${legacy.generated_at || 'unknown time'} — not the decision source of truth`}
            style={{ fontSize: 10, fontWeight: 700, color: BB.text3, textTransform: 'uppercase', flexShrink: 0 }}>
            LEGACY @ BUILD {String(legacy.recommendation)}
          </span>
        )}
        <button onClick={() => setOpen(v => !v)}
          style={{ fontSize: 10, fontWeight: 700, color: BB.text3, background: 'transparent',
                   border: `1px solid ${BB.border}`, borderRadius: 2, padding: '0 5px', cursor: 'pointer', flexShrink: 0 }}>
          {open ? 'less ▴' : 'more ▾'}
        </button>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 3, alignItems: 'baseline' }}>
        {chip('THESIS', thesis.replace(/_/g, ' '), accent)}
        {chip('TIMING', String(packet.horizons?.tactical?.timing || '—').replace(/_/g, ' '),
          packet.horizons?.tactical?.timing === 'READY' ? BB.green
            : packet.horizons?.tactical?.timing === 'EVENT_BLOCKED' ? BB.red : BB.amber)}
        {chip('EVENT', `${ev.state || 'UNKNOWN'}${ev.date ? ' ' + ev.date : ''}`,
          ev.state === 'SCHEDULED' ? BB.amber : ev.state === 'NONE_CONFIRMED' ? BB.green : BB.text3)}
        {/* DATA AT BUILD — not current validity */}
        {chip('DATA @ BUILD', String(dq.state || '—'), buildStale ? BB.amber : BB.green)}
        {/* CURRENT VALIDITY from input-hash comparison */}
        {cv && chip('CURRENT VALIDITY', cvState || '—',
          inputsStale ? BB.amber : (cvState === 'CURRENT' ? BB.green : BB.text3))}
        {chip('MODELS', `${mr.mode || 'UNAVAILABLE'} ${(mr.lanes_completed || []).length}/${(mr.lanes_requested || []).length}`,
          mr.mode === 'BLIND' ? BB.green : BB.amber)}
        {age && <span style={{ fontSize: 10, color: BB.text3 }}>· {age}</span>}
      </div>
      {inputsStale && (
        <div style={{ marginTop: 3, fontSize: 10, fontWeight: 700, color: BB.amber }}>
          CURRENT VALIDITY {cvState}
          {(cv?.invalidation_reasons || []).length > 0
            ? ` — ${(cv.invalidation_reasons as string[]).slice(0, 3).join(' · ')}`
            : ' — refresh before acting'}
        </div>
      )}

      {open && (
        <div style={{ marginTop: 5, display: 'flex', flexDirection: 'column', gap: 3 }}>
          {mr.agreement_by_dimension && (
            <div style={{ fontSize: 10, color: BB.text3 }}>
              AGREEMENT {Object.entries(mr.agreement_by_dimension).map(([d, v]: any) =>
                `${d.replace('long_term_thesis', 'thesis').replace('tactical_timing', 'timing')} ${v}`).join(' · ')}
              {mr.mode !== 'BLIND' && mr.mode !== 'BLIND_PARTIAL' && (
                <b style={{ color: BB.amber }}> · not an independent consensus</b>
              )}
            </div>
          )}
          {(() => {
            const tac = packet.horizons?.tactical || {}
            if (!tac.trigger && !tac.invalidation) return null
            return (
              <div style={{ fontSize: 10, color: BB.text3 }}>
                {tac.trigger && <span>TRIGGER <b style={{ color: BB.text2 }}>{tac.trigger}</b></span>}
                {tac.invalidation && <span> · INVALIDATE <b style={{ color: BB.text2 }}>{tac.invalidation}</b></span>}
              </div>
            )
          })()}
          {FAMILY_ORDER.map(fam => {
            const f = fams[fam.toLowerCase()] || {}
            const label = familyStateLabel(f)
            const mech = mechanics(fam, f)
            const reason = (f.rejection_reasons || f.blocks || [])[0]
            const opts = fam === 'OPTIONS' ? (f.structures || []) : []
            const constr = f.constructibility_state
            return (
              <div key={fam} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <span style={{ minWidth: 66, color: BB.text2, fontWeight: 700, fontSize: 10 }}>{FAMILY_LABEL[fam]}</span>
                  <span style={{ minWidth: 120, fontWeight: 800, fontSize: 10, color: label.color }}>{label.text}</span>
                  {constr && constr !== 'CONSTRUCTIBLE' && (
                    <span style={{ fontSize: 10, color: BB.text3 }} title="constructibility_state">{constr.replace(/_/g, ' ')}</span>
                  )}
                  {mech
                    ? <span style={{ color: BB.text1, fontSize: 10, fontWeight: 600 }}>{mech}</span>
                    : reason && <span style={{ color: BB.text3, fontSize: 10 }}>{String(reason).slice(0, 82)}</span>}
                  {fam === 'NO_TRADE' && f.reason && (
                    <span style={{ color: BB.text3, fontSize: 10 }}>{String(f.reason).slice(0, 90)}</span>
                  )}
                </div>
                {opts.length > 0 && opts.map((s: any, i: number) => (
                  <div key={i} style={{ paddingLeft: 72, color: BB.text3, fontSize: 10 }}>
                    <span style={{ color: STATE_COLOR[s.state] || BB.text3, fontWeight: 700 }}>{optionLine(s)}</span>
                  </div>
                ))}
              </div>
            )
          })}
          {packet.ownership && (
            <div style={{ fontSize: 10, color: BB.text3 }}>
              OWNERSHIP {packet.ownership.held
                ? `HELD ${Number(packet.ownership.shares || 0).toLocaleString()} sh`
                : 'NOT HELD'}
              {packet.ownership.uncommitted_shares != null
                ? ` · uncommitted ${Number(packet.ownership.uncommitted_shares).toLocaleString()}`
                : ''}
              {packet.ownership.as_of ? ` · ${packet.ownership.as_of}` : ''}
            </div>
          )}
          <div style={{ fontSize: 10, color: BB.text3, fontStyle: 'italic', borderTop: `1px solid ${BB.border}`, paddingTop: 3 }}>
            Multidimensional decision · constructibility ≠ decision ≠ action · advisory only
          </div>
        </div>
      )}
    </div>
  )
}

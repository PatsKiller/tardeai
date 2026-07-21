import { useState, type CSSProperties } from 'react'
import { BB } from '../lib/watchlistTerminalTokens'

/*
 * DecisionPacketBand — the PRIMARY decision surface (Stage: primary-card replacement).
 *
 * When a symbol has a live multidimensional decision packet, this band leads the
 * card: the composed headline, the six dimensions, per-dimension blind-model
 * agreement, and all five plan families — with the legacy one-word CIO label
 * (IGNORE/AVOID) demoted to a small "prior" chip, NOT removed.
 *
 * It renders nothing when no packet exists, so cards for un-analysed symbols keep
 * their legacy verdict band unchanged (no regression). The packet is delivered
 * inline on the watchlist item (it.decision_packet) — no per-card fetch.
 *
 * This replaces the PRIMACY of the one-word verdict, not the card. Nothing here
 * queues, approves, or submits anything; it is an advisory display.
 *
 * Design: BB tokens only (no raw hex), no sub-10px fonts (the card design guard
 * rejects both).
 */

const STATE_COLOR: Record<string, string> = {
  ELIGIBLE: BB.green, CONDITIONAL: BB.amber, REJECTED: BB.red,
  NOT_APPLICABLE: BB.text3, DATA_UNAVAILABLE: BB.text3,
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

export default function DecisionPacketBand({ packet, generatedAt }: { packet: any; generatedAt?: string }) {
  const [open, setOpen] = useState(false)
  if (!packet || typeof packet !== 'object') return null

  const lt = packet.horizons?.long_term || {}
  const thesis = String(lt.thesis_state || 'INSUFFICIENT_EVIDENCE')
  const ev = packet.event_state?.earnings || {}
  const dq = packet.data_quality || {}
  const mr = packet.model_review || {}
  const fams = packet.plan_families || {}
  const legacy = packet.legacy_summary || {}
  const accent = THESIS_COLOR[thesis] || BB.text3

  const age = ageStr(generatedAt || packet.evaluated_at)
  const stale = dq.state && ['STALE', 'CONFLICTED', 'INSUFFICIENT', 'PROVIDER_DOWN'].includes(String(dq.state))

  const chip = (label: string, value: string, color: string) => (
    <span style={{ fontSize: 10, color: BB.text3, whiteSpace: 'nowrap' }}>
      {label} <b style={{ color }}>{value}</b>
    </span>
  )

  return (
    <div onClick={e => e.stopPropagation()}
      style={{ borderLeft: `3px solid ${accent}`, background: BB.bgShift,
               borderBottom: `1px solid ${BB.border}`, padding: '5px 10px' }}>
      {/* lead row: headline + demoted legacy chip + expander */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.08em', color: accent,
                       textTransform: 'uppercase', flexShrink: 0 }}>DECISION</span>
        <span style={{ flex: 1, minWidth: 160, fontSize: 11, fontWeight: 800, color: BB.text0 }}>
          {packet.headline}
        </span>
        {legacy.recommendation && (
          <span title="Prior one-word CIO label — not the decision source of truth"
            style={{ fontSize: 10, fontWeight: 700, color: BB.text3, textTransform: 'uppercase', flexShrink: 0 }}>
            prior CIO {String(legacy.recommendation)}
          </span>
        )}
        <button onClick={() => setOpen(v => !v)}
          style={{ fontSize: 10, fontWeight: 700, color: BB.text3, background: 'transparent',
                   border: `1px solid ${BB.border}`, borderRadius: 2, padding: '0 5px', cursor: 'pointer', flexShrink: 0 }}>
          {open ? 'less ▴' : 'more ▾'}
        </button>
      </div>

      {/* dimension chips — always visible */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 3, alignItems: 'baseline' }}>
        {chip('THESIS', thesis.replace(/_/g, ' '), accent)}
        {chip('TIMING', String(packet.horizons?.tactical?.timing || '—').replace(/_/g, ' '),
          packet.horizons?.tactical?.timing === 'READY' ? BB.green : BB.amber)}
        {chip('EVENT', `${ev.state || 'UNKNOWN'}${ev.date ? ' ' + ev.date : ''}`,
          ev.state === 'SCHEDULED' ? BB.amber : ev.state === 'NONE_CONFIRMED' ? BB.green : BB.text3)}
        {chip('DATA', String(dq.state || '—'), stale ? BB.amber : BB.green)}
        {chip('MODELS', `${mr.mode || 'UNAVAILABLE'} ${(mr.lanes_completed || []).length}/${(mr.lanes_requested || []).length}`,
          mr.mode === 'BLIND' ? BB.green : BB.amber)}
        {age && <span style={{ fontSize: 10, color: BB.text3 }}>· {age}</span>}
      </div>

      {open && (
        <div style={{ marginTop: 5, display: 'flex', flexDirection: 'column', gap: 3 }}>
          {/* per-dimension blind agreement — replaces the anchored AGREE/SPLIT badge */}
          {mr.agreement_by_dimension && (
            <div style={{ fontSize: 10, color: BB.text3 }}>
              AGREEMENT {Object.entries(mr.agreement_by_dimension).map(([d, v]: any) =>
                `${d.replace('long_term_thesis', 'thesis').replace('tactical_timing', 'timing')} ${v}`).join(' · ')}
              {mr.mode !== 'BLIND' && mr.mode !== 'BLIND_PARTIAL' && (
                <b style={{ color: BB.amber }}> · not an independent consensus</b>
              )}
            </div>
          )}
          {/* every family, always present, colour-coded by rollup state */}
          {FAMILY_ORDER.map(fam => {
            const f = fams[fam.toLowerCase()] || {}
            const state = f.state || 'DATA_UNAVAILABLE'
            const reason = (f.rejection_reasons || [])[0]
            return (
              <div key={fam} style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                <span style={{ minWidth: 66, color: BB.text2, fontWeight: 700, fontSize: 10 }}>{FAMILY_LABEL[fam]}</span>
                <span style={{ minWidth: 96, fontWeight: 800, fontSize: 10, color: STATE_COLOR[state] || BB.text3 }}>{state}</span>
                {reason && <span style={{ color: BB.text3, fontSize: 10 }}>{String(reason).slice(0, 82)}</span>}
              </div>
            )
          })}
          <div style={{ fontSize: 10, color: BB.text3, fontStyle: 'italic', borderTop: `1px solid ${BB.border}`, paddingTop: 3 }}>
            Multidimensional shadow decision · advisory only · legacy CIO label demoted, not the source of truth
          </div>
        </div>
      )}
    </div>
  )
}

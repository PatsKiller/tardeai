import { useState } from 'react'
import { BB, numStyle, terminalButton } from '../lib/watchlistTerminalTokens'
import {
  buildOperatorPresentation,
  operatorStateColor,
  type OperatorPresentation,
  type OperatorState,
} from '../lib/operatorDecisionCard'

/*
 * DecisionPacketBand — Watch Decision Desk V6 presentation.
 *
 * The packet remains the audit record. This component is the operator surface:
 * action first, five strategies second, technical setup third, mechanics and
 * freshness always visible, audit/detail explicitly separated.
 *
 * Advisory only. No orders. No approvals. No 2FA.
 */

type Props = {
  packet: any
  generatedAt?: string
  actionPolicy?: any
  held?: boolean
  onRefresh?: (e: React.MouseEvent) => void
  onRefreshStrategy?: (e: React.MouseEvent) => void
  refreshing?: boolean
  onPrimary?: (pres: OperatorPresentation, e: React.MouseEvent) => void
  onAlert?: (pres: OperatorPresentation, e: React.MouseEvent) => void
}

const FAMILY_ORDER = [
  ['long_term', 'Long term'],
  ['swing', 'Swing'],
  ['bearish', 'Bearish'],
  ['options', 'Options'],
  ['no_trade', 'No trade'],
] as const

function stateBg(state: OperatorState): string {
  if (state === 'READY') return 'rgba(34,197,94,.10)'
  if (state === 'BLOCKED' || state === 'NO TRADE') return 'rgba(239,68,68,.09)'
  if (state === 'MANAGE POSITION') return 'rgba(96,165,250,.09)'
  return 'rgba(245,158,11,.09)'
}

function asDate(v?: string | null): Date | null {
  if (!v) return null
  const d = new Date(v)
  return Number.isFinite(d.getTime()) ? d : null
}

function clock(v?: string | null): string {
  const d = asDate(v)
  if (!d) return '—'
  return d.toLocaleString([], {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    timeZoneName: 'short',
  })
}

function age(v?: string | null): string {
  const d = asDate(v)
  if (!d) return '—'
  const mins = Math.max(0, Math.round((Date.now() - d.getTime()) / 60_000))
  if (mins < 1) return 'now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 48) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function familyWord(k: string, f: any): string {
  if (k === 'no_trade') return f?.preferred || f?.dominant ? 'PREFERRED' : f?.available ? 'AVAILABLE' : '—'
  const act = String(f?.action_state || '').toUpperCase()
  const dec = String(f?.decision_state || f?.state || '').toUpperCase()
  if (act === 'READY') return 'READY'
  if (act.startsWith('WAIT') || dec.startsWith('WAIT') || dec === 'CONDITIONAL') return 'WAIT'
  if (dec.includes('REJECT') || act.includes('REJECT')) return 'REJECTED'
  if (k === 'options' && (dec.includes('STALE') || act.includes('STALE'))) return 'CHAIN STALE'
  if (dec.includes('UNAVAILABLE') || act.includes('UNAVAILABLE') || dec.includes('DATA_UNAVAILABLE')) return 'UNAVAILABLE'
  if (dec.includes('ELIGIBLE') || dec.includes('VALID') || dec.includes('CONSTRUCT')) return 'AVAILABLE'
  return '—'
}

function statusColor(word: string): string {
  if (word === 'READY') return BB.green
  if (word === 'WAIT' || word === 'CHAIN STALE' || word === 'PREFERRED') return BB.amber
  if (word === 'REJECTED') return BB.red
  return BB.text3
}

function familyReason(k: string, f: any): string {
  if (k === 'no_trade') return String(f?.reason || (f?.preferred ? 'No constructive plan is currently preferred' : 'Available as the risk-off alternative'))
  const reason = (f?.rejection_reasons || f?.blocks || [])[0]
  if (reason) return String(reason)
  const structure = (f?.structures || [])[0]
  if (structure?.structure) return String(structure.structure).replace(/_/g, ' ').toLowerCase()
  const word = familyWord(k, f)
  if (word === 'READY') return 'Mechanics resolved and current'
  if (word === 'WAIT') return 'Conditions are not yet confirmed'
  if (word === 'UNAVAILABLE') return k === 'options' ? 'Exact option chain or eligible structure unavailable' : 'Required evidence unavailable'
  if (word === 'REJECTED') return 'Eligibility or risk constraints failed'
  return 'No active construction'
}

function technicalColor(p: any): string {
  const fresh = String(p?.freshness || 'UNAVAILABLE').toUpperCase()
  const lifecycle = String(p?.lifecycle || '').toUpperCase()
  const direction = String(p?.direction || 'NEUTRAL').toUpperCase()
  if (fresh !== 'CURRENT') return BB.text3
  if (lifecycle === 'CONFIRMED' && direction === 'BULLISH') return BB.green
  if (lifecycle === 'CONFIRMED' && direction === 'BEARISH') return BB.red
  if (lifecycle === 'FORMING' || lifecycle === 'AWAITING_CONFIRMATION' || direction === 'MIXED') return BB.amber
  return BB.text2
}

function technicalBg(p: any): string {
  const c = technicalColor(p)
  if (c === BB.green) return 'rgba(34,197,94,.08)'
  if (c === BB.red) return 'rgba(239,68,68,.08)'
  if (c === BB.amber) return 'rgba(245,158,11,.08)'
  return 'rgba(148,163,184,.05)'
}

export default function DecisionPacketBand({
  packet, generatedAt, actionPolicy, held, onRefresh, onRefreshStrategy,
  refreshing, onPrimary, onAlert,
}: Props) {
  const [details, setDetails] = useState(false)
  const [whyOpen, setWhyOpen] = useState(false)
  const [prevOpen, setPrevOpen] = useState(false)

  const pres = buildOperatorPresentation({ packet, actionPolicy, held })
  if (!pres) return null

  const accent = operatorStateColor(pres.state)
  const tech = packet?.technical_state || {}
  const builtAt = generatedAt || packet?.evaluated_at || packet?.generated_at
  const inputsAt = packet?.freshness?.last_input_refresh_at || packet?.current_input_snapshot?.computed_at
  const validUntil = packet?.freshness?.valid_until || actionPolicy?.valid_until
  const nextDue = packet?.freshness?.next_refresh_due_at || actionPolicy?.next_refresh_due_at
  const invalidatedAt = packet?.freshness?.invalidated_at || packet?.current_validity?.invalidated_at
  const analysisMode = String(packet?.model_review?.mode || packet?.analysis_tier || 'LOCAL_QUANT').replace(/_/g, ' ')
  const pills: any[] = tech?.pills || []

  return (
    <section
      aria-label="Decision strategy desk"
      onClick={e => e.stopPropagation()}
      style={{
        borderLeft: `4px solid ${accent}`,
        background: stateBg(pres.state),
        borderBottom: `1px solid ${BB.border}`,
      }}
    >
      {/* ACTION + FRESHNESS HEADER */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'minmax(0, 1.7fr) minmax(280px, .8fr)',
        gap: 12, padding: '12px 14px 10px', borderBottom: `1px solid ${BB.border}`,
      }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9, flexWrap: 'wrap' }}>
            <span style={{
              fontSize: 13, fontWeight: 950, letterSpacing: '.10em', color: accent,
              textTransform: 'uppercase',
            }}>{pres.state}</span>
            <span style={{ fontSize: 17, fontWeight: 850, color: BB.text0 }}>{pres.headline}</span>
          </div>
          <div style={{ marginTop: 5, fontSize: 11.5, lineHeight: 1.45, color: BB.text2, fontWeight: 650 }}>
            {pres.thesisLine}
          </div>
          {pres.whyLines.length > 0 && (
            <div style={{ marginTop: 7, display: 'flex', gap: 7, flexWrap: 'wrap' }}>
              {pres.whyLines.slice(0, 2).map((line, i) => (
                <span key={i} style={{
                  fontSize: 10.5, color: BB.text1, background: 'rgba(15,23,42,.34)',
                  border: `1px solid ${BB.border}`, borderRadius: 4, padding: '3px 7px',
                }}>{line}</span>
              ))}
            </div>
          )}
        </div>

        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '5px 10px', alignContent: 'start',
          background: 'rgba(2,6,23,.28)', border: `1px solid ${BB.border}`,
          borderRadius: 5, padding: '8px 10px',
        }}>
          <Meta label="Strategy built" value={`${clock(builtAt)} · ${age(builtAt)}`} />
          <Meta label="Analysis" value={analysisMode} />
          <Meta label="Inputs refreshed" value={clock(inputsAt)} />
          <Meta label="Technical snapshot" value={tech?.computed_at ? `${clock(tech.computed_at)} · ${tech.overall_freshness || '—'}` : 'Unavailable'} />
          <Meta label={pres.stale ? 'Invalidated' : 'Valid until'} value={pres.stale ? clock(invalidatedAt) : clock(validUntil)} tone={pres.stale ? BB.amber : undefined} />
          <Meta label="Next scheduled review" value={clock(nextDue)} />
        </div>
      </div>

      {/* FIVE STRATEGIES — visible, comparable, preferred obvious */}
      <div style={{ padding: '10px 14px', borderBottom: `1px solid ${BB.border}` }}>
        <SectionTitle title="Strategies evaluated" note="Every family is visible; only the selected family drives mechanics and the primary action." />
        <StrategyGrid pres={pres} onOpen={() => setDetails(true)} />
      </div>

      {/* TECHNICAL SETUP — real pills with hierarchy */}
      <div style={{ padding: '10px 14px', borderBottom: `1px solid ${BB.border}` }}>
        <SectionTitle
          title="Technical setup"
          note={tech?.source_hash ? `${tech.overall_direction || 'UNRESOLVED'} · source ${tech.source_hash}` : 'Canonical technical snapshot unavailable'}
        />
        <TechnicalGrid tech={tech} onOpen={() => setDetails(true)} />
      </div>

      {/* MECHANICS + WHAT CHANGES THE DECISION */}
      <div style={{
        display: 'grid', gridTemplateColumns: pres.mechanics ? 'minmax(0, 1.25fr) minmax(260px, .75fr)' : '1fr',
        gap: 12, padding: '10px 14px', borderBottom: `1px solid ${BB.border}`,
      }}>
        {pres.mechanics && (
          <div style={{ opacity: pres.stale || pres.mechanics.previous ? .58 : 1 }}>
            <SectionTitle title={pres.stale ? 'Previous mechanics — not current' : 'Current mechanics'} />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(76px, 1fr))', gap: 7 }}>
              {([
                ['Entry', pres.mechanics.entry], ['Limit', pres.mechanics.limit],
                ['Stop', pres.mechanics.stop], ['Target', pres.mechanics.target],
                ['R:R', pres.mechanics.rr],
              ] as const).map(([label, value]) => (
                <div key={label} style={{
                  background: 'rgba(2,6,23,.28)', border: `1px solid ${BB.border}`,
                  borderRadius: 4, padding: '6px 8px', minHeight: 42,
                }}>
                  <div style={{ fontSize: 10, fontWeight: 850, color: BB.text3, textTransform: 'uppercase', letterSpacing: '.07em' }}>{label}</div>
                  <div style={{ ...numStyle, marginTop: 2, fontSize: 14, fontWeight: 850, color: BB.text0 }}>{value || '—'}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div>
          <SectionTitle title="What changes the decision" />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {(packet?.horizons?.tactical?.trigger || packet?.horizons?.swing?.trigger) && (
              <Condition label="Trigger" text={packet?.horizons?.tactical?.trigger || packet?.horizons?.swing?.trigger} color={BB.green} />
            )}
            {(packet?.horizons?.tactical?.invalidation || packet?.horizons?.swing?.invalidation) && (
              <Condition label="Invalidation" text={packet?.horizons?.tactical?.invalidation || packet?.horizons?.swing?.invalidation} color={BB.red} />
            )}
            {!packet?.horizons?.tactical?.trigger && !packet?.horizons?.swing?.trigger && (
              <Condition label="Next" text={pres.primaryFamily?.why || pres.whyLines[0] || 'Review the full evidence'} color={BB.amber} />
            )}
          </div>
        </div>
      </div>

      {/* ACTION BAR */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap', padding: '9px 14px' }}>
        <button
          onClick={e => {
            e.stopPropagation()
            if (pres.state === 'REFRESH') {
              if (onRefreshStrategy) onRefreshStrategy(e)
              else if (onRefresh) onRefresh(e)
            } else if (pres.state === 'WAIT' && onAlert) onAlert(pres, e)
            else if (onPrimary) onPrimary(pres, e)
          }}
          disabled={refreshing && pres.state === 'REFRESH'}
          style={{
            ...terminalButton(pres.state === 'READY' || pres.state === 'REFRESH' ? 'primary' : 'secondary'),
            fontSize: 11, padding: '5px 10px',
            ...(refreshing && pres.state === 'REFRESH' ? { opacity: .6, cursor: 'wait' } : {}),
          }}
        >
          {refreshing && pres.state === 'REFRESH' ? 'Refreshing strategy…' : pres.primaryCta}
        </button>

        {!pres.stale && onRefreshStrategy && (
          <button onClick={e => { e.stopPropagation(); onRefreshStrategy(e) }} disabled={refreshing}
            style={{ ...terminalButton('ghost'), fontSize: 10.5 }}>
            {refreshing ? 'Refreshing…' : 'Refresh Strategy'}
          </button>
        )}
        {onRefresh && (
          <button onClick={e => { e.stopPropagation(); onRefresh(e) }} style={{ ...terminalButton('ghost'), fontSize: 10.5 }}>
            Refresh Inputs
          </button>
        )}
        {pres.stale && pres.mechanics?.previous && (
          <button onClick={e => { e.stopPropagation(); setPrevOpen(v => !v) }} style={{ ...terminalButton('ghost'), fontSize: 10.5 }}>
            {prevOpen ? 'Hide Previous Strategy' : 'View Previous Strategy'}
          </button>
        )}
        {pres.whyNot.length > 0 && (
          <button onClick={e => { e.stopPropagation(); setWhyOpen(v => !v) }} style={{ ...terminalButton('ghost'), fontSize: 10.5 }}>
            {whyOpen ? 'Hide alternatives' : 'Why not alternatives?'}
          </button>
        )}
        <button onClick={e => { e.stopPropagation(); setDetails(v => !v) }} style={{ ...terminalButton('ghost'), fontSize: 10.5 }}>
          {details ? 'Hide audit' : 'Details & audit'}
        </button>
        <span style={{ marginLeft: 'auto', fontSize: 10, color: BB.text3 }}>Advisory only · proposal review remains separate</span>
      </div>

      {prevOpen && pres.mechanics?.previous && (
        <div style={{ margin: '0 14px 9px', padding: '7px 9px', fontSize: 10.5, color: BB.text3, border: `1px solid ${BB.border}`, borderRadius: 4 }}>
          Previous strategy: {pres.mechanics.summary}
        </div>
      )}

      {whyOpen && (
        <div style={{ margin: '0 14px 9px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 6 }}>
          {pres.whyNot.map(w => (
            <div key={w.title} style={{ padding: '6px 8px', border: `1px solid ${BB.border}`, borderRadius: 4, background: 'rgba(2,6,23,.22)' }}>
              <div style={{ fontSize: 10, fontWeight: 850, color: BB.text2 }}>{w.title}</div>
              <div style={{ marginTop: 2, fontSize: 10, color: BB.text3 }}>{w.reason}</div>
            </div>
          ))}
        </div>
      )}

      {details && <AuditDrawer pres={pres} tech={tech} />}
    </section>
  )
}

function SectionTitle({ title, note }: { title: string; note?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
      <span style={{ fontSize: 10, fontWeight: 900, color: BB.text2, textTransform: 'uppercase', letterSpacing: '.08em' }}>{title}</span>
      {note && <span style={{ fontSize: 10, color: BB.text3 }}>{note}</span>}
    </div>
  )
}

function Meta({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 10, fontWeight: 850, color: BB.text3, textTransform: 'uppercase', letterSpacing: '.06em' }}>{label}</div>
      <div style={{ marginTop: 1, fontSize: 10, color: tone || BB.text1, fontWeight: 650, overflow: 'hidden', textOverflow: 'ellipsis' }} title={value}>{value}</div>
    </div>
  )
}

function Condition({ label, text, color }: { label: string; text: string; color: string }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '72px 1fr', gap: 7, alignItems: 'start' }}>
      <span style={{ fontSize: 10, fontWeight: 900, color, textTransform: 'uppercase', letterSpacing: '.06em' }}>{label}</span>
      <span style={{ fontSize: 10.5, color: BB.text1, lineHeight: 1.35 }}>{text}</span>
    </div>
  )
}

function StrategyGrid({ pres, onOpen }: { pres: OperatorPresentation; onOpen: () => void }) {
  const fams = pres.audit?.families || {}
  const prefKey = pres.primaryFamily?.key === 'refresh' ? null : String(pres.primaryFamily?.key || '')
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(120px, 1fr))', gap: 6 }}>
      {FAMILY_ORDER.map(([key, label]) => {
        const fam = fams[key] || {}
        const word = familyWord(key, fam)
        const color = statusColor(word)
        const preferred = !!prefKey && (prefKey === key || prefKey.startsWith(key.split('_')[0]))
        return (
          <button key={key} onClick={e => { e.stopPropagation(); onOpen() }}
            title={`${label}: ${word}. ${familyReason(key, fam)}`}
            style={{
              textAlign: 'left', cursor: 'pointer', minHeight: 58,
              background: preferred ? `${color}12` : 'rgba(2,6,23,.22)',
              border: `1px solid ${preferred ? color : BB.border}`,
              borderRadius: 5, padding: '7px 8px',
              boxShadow: preferred ? `inset 3px 0 0 ${color}` : undefined,
            }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ fontSize: 10.5, fontWeight: 900, color: preferred ? BB.text0 : BB.text2 }}>{label}</span>
              {preferred && <span style={{ fontSize: 10, fontWeight: 900, color, border: `1px solid ${color}66`, borderRadius: 3, padding: '0 4px' }}>PRIMARY</span>}
            </div>
            <div style={{ marginTop: 4, fontSize: 10, fontWeight: 900, color }}>{word}</div>
            <div style={{ marginTop: 2, fontSize: 10, lineHeight: 1.25, color: BB.text3 }}>{familyReason(key, fam).slice(0, 72)}</div>
          </button>
        )
      })}
    </div>
  )
}

function TechnicalGrid({ tech, onOpen }: { tech: any; onOpen: () => void }) {
  const pills: any[] = tech?.pills || []
  if (!pills.length) {
    return (
      <div style={{ padding: '8px 10px', border: `1px dashed ${BB.border}`, borderRadius: 5, color: BB.text3, fontSize: 10.5 }}>
        Technical snapshot unavailable. Refresh Strategy to rebuild the canonical multi-timeframe analysis.
      </div>
    )
  }
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(115px, 1fr))', gap: 6 }}>
      {pills.slice(0, 6).map((p, i) => {
        const color = technicalColor(p)
        const lifecycle = String(p.lifecycle || '').replace(/_/g, ' ')
        const fresh = String(p.freshness || 'UNAVAILABLE')
        return (
          <button key={`${p.kind || 'tech'}-${i}`} onClick={e => { e.stopPropagation(); onOpen() }}
            title={`${p.tooltip || ''} · ${lifecycle} · ${fresh}`}
            style={{
              textAlign: 'left', cursor: 'pointer', minHeight: 60,
              background: technicalBg(p), border: `1px solid ${color}55`,
              borderRadius: 5, padding: '7px 8px',
            }}>
            <div style={{ fontSize: 10, color: BB.text3, fontWeight: 850, textTransform: 'uppercase', letterSpacing: '.07em' }}>
              {String(p.kind || 'technical').replace(/_/g, ' ')}
            </div>
            <div style={{ marginTop: 3, fontSize: 10.5, color, fontWeight: 900, lineHeight: 1.2 }}>{p.label}</div>
            <div style={{ marginTop: 3, fontSize: 10, color: BB.text2, fontWeight: 700 }}>{p.value || lifecycle || '—'}</div>
            <div style={{ marginTop: 2, fontSize: 10, color: fresh === 'CURRENT' ? BB.text3 : BB.amber }}>{fresh}{lifecycle ? ` · ${lifecycle}` : ''}</div>
          </button>
        )
      })}
    </div>
  )
}

function AuditDrawer({ pres, tech }: { pres: OperatorPresentation; tech: any }) {
  const a = pres.audit
  const fams = a.families || {}
  const order = ['long_term', 'swing', 'bearish', 'options', 'no_trade'] as const
  return (
    <div style={{
      margin: '0 14px 12px', padding: 10, border: `1px solid ${BB.border}`,
      borderRadius: 5, background: 'rgba(2,6,23,.30)', display: 'flex', flexDirection: 'column', gap: 7,
    }}>
      <div style={{ fontSize: 10, fontWeight: 900, color: BB.amber, letterSpacing: '.07em', textTransform: 'uppercase' }}>
        Details & audit — not the primary decision
      </div>
      <div style={{ fontSize: 10, color: BB.text3 }}>
        Packet {a.packet?.packet_version || '—'} · policy {a.actionPolicy?.policy_version || '—'}
        {a.inputHashes.packet ? ` · packet ${a.inputHashes.packet}` : ''}
        {a.inputHashes.current ? ` · current ${a.inputHashes.current}` : ''}
        {tech?.source_hash ? ` · technical ${tech.source_hash}` : ''}
      </div>
      {a.currentValidity && (
        <div style={{ fontSize: 10, color: BB.text2 }}>
          Current validity: <b>{String(a.currentValidity.state || '—')}</b>
          {(a.currentValidity.invalidation_reasons || []).length > 0 && <span> — {(a.currentValidity.invalidation_reasons as string[]).join('; ')}</span>}
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(130px, 1fr))', gap: 6 }}>
        {order.map(key => {
          const f = fams[key] || {}
          const kids = f.structures || []
          return (
            <div key={key} style={{ padding: '6px 7px', border: `1px solid ${BB.border}`, borderRadius: 4, fontSize: 10, color: BB.text3 }}>
              <div style={{ fontWeight: 900, color: BB.text1, textTransform: 'uppercase' }}>{key.replace('_', ' ')}</div>
              <div>construct={f.constructibility_state || '—'}</div>
              <div>decision={f.decision_state || f.state || '—'}</div>
              <div>action={f.action_state || '—'}</div>
              {kids.slice(0, 4).map((s: any, i: number) => (
                <div key={i} style={{ marginTop: 3 }}>{s.structure || '?'} · {s.state}{s.occ_symbol ? ` · ${s.occ_symbol}` : ''}</div>
              ))}
            </div>
          )
        })}
      </div>
      {tech?.timeframes && (
        <div style={{ fontSize: 10, color: BB.text3 }}>
          Technical timeframes: {Object.entries(tech.timeframes).map(([tf, r]: any) => `${tf} ${r?.meta?.freshness_state || '—'} @ ${r?.meta?.last_closed_bar || '—'}`).join(' · ')}
        </div>
      )}
      {a.modelReview && (
        <div style={{ fontSize: 10, color: BB.text3 }}>
          Models: {a.modelReview.mode || '—'}{a.modelReview.agreement_by_dimension ? ` · agreement ${JSON.stringify(a.modelReview.agreement_by_dimension)}` : ''}
        </div>
      )}
      {a.ownership && (
        <div style={{ fontSize: 10, color: BB.text3 }}>
          Ownership: {a.ownership.held ? `HELD ${a.ownership.shares}` : 'NOT HELD'}{a.ownership.source ? ` · ${a.ownership.source}` : ''}{a.ownership.as_of ? ` · ${a.ownership.as_of}` : ''}
        </div>
      )}
      {a.legacy?.recommendation && (
        <div style={{ fontSize: 10, color: BB.text3 }}>Legacy @ build: {String(a.legacy.recommendation)}{a.legacy.generated_at ? ` · ${a.legacy.generated_at}` : ''}</div>
      )}
      {a.actionPolicy && (
        <div style={{ fontSize: 10, color: BB.text3 }}>
          Action policy: {a.actionPolicy.action} · state={a.actionPolicy.state} · allowed={String(!!a.actionPolicy.allowed)}{a.actionPolicy.reason ? ` · ${a.actionPolicy.reason}` : ''}
        </div>
      )}
    </div>
  )
}

import { useState } from 'react'
import { BB, numStyle, terminalButton } from '../lib/watchlistTerminalTokens'
import {
  buildOperatorPresentation,
  operatorStateColor,
  type OperatorPresentation,
  type OperatorState,
} from '../lib/operatorDecisionCard'

/*
 * DecisionPacketBand — OPERATOR primary surface (not a packet viewer).
 *
 * Answers only: what now? why? at what price? what invalidates? what next?
 * Full packet / family / model audit lives behind Details.
 *
 * No orders. No 2FA. Advisory only.
 */

type Props = {
  packet: any
  generatedAt?: string
  actionPolicy?: any
  held?: boolean
  onRefresh?: (e: React.MouseEvent) => void
  /** V5: canonical packet rebuild (watch_decision_refresh orchestrator). When
   *  absent, the REFRESH primary falls back to onRefresh (legacy inputs-only). */
  onRefreshStrategy?: (e: React.MouseEvent) => void
  /** V5: a strategy-refresh run is in flight for this symbol. */
  refreshing?: boolean
  onPrimary?: (pres: OperatorPresentation, e: React.MouseEvent) => void
  onAlert?: (pres: OperatorPresentation, e: React.MouseEvent) => void
}

function stateBg(state: OperatorState): string {
  if (state === 'READY') return 'rgba(34,197,94,.12)'
  if (state === 'BLOCKED' || state === 'NO TRADE') return 'rgba(239,68,68,.10)'
  return 'rgba(255,176,0,.12)'
}

export default function DecisionPacketBand({
  packet, actionPolicy, held, onRefresh, onRefreshStrategy, refreshing, onPrimary, onAlert,
}: Props) {
  const [details, setDetails] = useState(false)
  const [whyOpen, setWhyOpen] = useState(false)
  const [prevOpen, setPrevOpen] = useState(false)

  const pres = buildOperatorPresentation({ packet, actionPolicy, held })
  if (!pres) return null

  const accent = operatorStateColor(pres.state)
  const mechDim = pres.stale || !!pres.mechanics?.previous

  return (
    <div
      onClick={e => e.stopPropagation()}
      style={{
        borderLeft: `3px solid ${accent}`,
        background: stateBg(pres.state),
        borderBottom: `1px solid ${BB.border}`,
        padding: '8px 10px',
      }}
    >
      {/* LINE 1 — ACTION */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span style={{
          fontSize: 12, fontWeight: 900, letterSpacing: '.06em', color: accent,
          textTransform: 'uppercase', flexShrink: 0,
        }}>
          {pres.state}
        </span>
        <span style={{ fontSize: 13, fontWeight: 800, color: BB.text0, flex: 1, minWidth: 140 }}>
          {pres.headline}
        </span>
      </div>

      {/* LINE 2 — THESIS */}
      <div style={{ marginTop: 4, fontSize: 11, color: BB.text2, fontWeight: 600 }}>
        {pres.thesisLine}
      </div>

      {/* chips — max 3 */}
      {pres.chips.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 5 }}>
          {pres.chips.map(c => (
            <span key={c} style={{
              fontSize: 10, fontWeight: 800, letterSpacing: '.04em',
              color: c.includes('REFRESH') || c.includes('REJECT') ? BB.amber : BB.text3,
              border: `1px solid ${BB.border}`, borderRadius: 2, padding: '1px 6px',
            }}>{c}</span>
          ))}
        </div>
      )}

      {/* LINE 3 — MECHANICS */}
      {pres.mechanics && (
        <div style={{
          marginTop: 8,
          opacity: mechDim ? 0.55 : 1,
          filter: mechDim ? 'grayscale(0.25)' : undefined,
        }}>
          {mechDim && (
            <div style={{ fontSize: 10, fontWeight: 800, color: BB.amber, marginBottom: 3, textTransform: 'uppercase', letterSpacing: '.05em' }}>
              Previous plan — not current
            </div>
          )}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(88px, 1fr))',
            gap: 6,
          }}>
            {([
              ['ENTRY', pres.mechanics.entry],
              ['LIMIT', pres.mechanics.limit],
              ['STOP', pres.mechanics.stop],
              ['TARGET', pres.mechanics.target],
              ['R:R', pres.mechanics.rr],
            ] as const).filter(([, v]) => v).map(([lbl, val]) => (
              <div key={lbl}>
                <div style={{ fontSize: 10, fontWeight: 700, color: BB.text3, letterSpacing: '.06em' }}>{lbl}</div>
                <div style={{ ...numStyle, fontSize: 13, fontWeight: 800, color: BB.text0 }}>{val}</div>
              </div>
            ))}
          </div>
          {!pres.mechanics.entry && !pres.mechanics.limit && (
            <div style={{ ...numStyle, fontSize: 11, fontWeight: 700, color: BB.text1, marginTop: 2 }}>
              {pres.mechanics.summary}
            </div>
          )}
        </div>
      )}

      {/* Why */}
      {pres.whyLines.length > 0 && (
        <div style={{ marginTop: 7 }}>
          <div style={{ fontSize: 10, fontWeight: 800, color: BB.text3, textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 2 }}>
            {pres.state === 'REFRESH' ? 'Why refresh' : pres.state === 'WAIT' ? 'Why wait' : pres.state === 'READY' ? 'Why this' : 'Why'}
          </div>
          {pres.whyLines.map((line, i) => (
            <div key={i} style={{ fontSize: 11, color: BB.text1, lineHeight: 1.35 }}>{line}</div>
          ))}
        </div>
      )}

      {/* Selected plan + alternative (compact) */}
      {!pres.stale && pres.primaryFamily && (
        <div style={{ marginTop: 6, fontSize: 11, color: BB.text2 }}>
          <span style={{ fontWeight: 800, color: BB.text0 }}>PRIMARY </span>
          {pres.primaryFamily.title} — {pres.primaryFamily.statusLabel}
        </div>
      )}
      {!pres.stale && pres.alternative && (
        <div style={{ marginTop: 2, fontSize: 11, color: BB.text3 }}>
          <span style={{ fontWeight: 700 }}>ALTERNATIVE </span>
          {pres.alternative.title} — {pres.alternative.statusLabel}
        </div>
      )}

      {/* Why not alternatives */}
      {pres.whyNot.length > 0 && (
        <div style={{ marginTop: 4 }}>
          <button
            onClick={() => setWhyOpen(v => !v)}
            style={{ ...terminalButton('ghost'), fontSize: 10, padding: '2px 0' }}
          >
            Why not the alternatives? {whyOpen ? '▴' : '▾'}
          </button>
          {whyOpen && (
            <div style={{ marginTop: 3, display: 'flex', flexDirection: 'column', gap: 2 }}>
              {pres.whyNot.map(w => (
                <div key={w.title} style={{ fontSize: 10, color: BB.text3 }}>
                  <b style={{ color: BB.text2 }}>{w.title}</b> {w.reason}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* V5 STRATEGY RAIL — all five families always visible (click → details) */}
      <StrategyRail pres={pres} onOpen={() => setDetails(true)} />

      {/* 17.14 TECHNICAL SETUP RAIL — max 6 server-ranked pills; freshness and
          direction are separate axes (a stale bullish pill renders gray). */}
      <TechSetupRail tech={packet?.technical_state} onOpen={() => setDetails(true)} />

      {/* CTAs — V5 split: Refresh Strategy = packet rebuild orchestrator;
          Refresh Inputs = the old enrichment-only endpoint, honestly labelled. */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
        <button
          onClick={e => {
            e.stopPropagation()
            if (pres.state === 'REFRESH') {
              if (onRefreshStrategy) onRefreshStrategy(e)
              else if (onRefresh) onRefresh(e)
            }
            else if (pres.state === 'WAIT' && onAlert) onAlert(pres, e)
            else if (onPrimary) onPrimary(pres, e)
          }}
          disabled={refreshing && pres.state === 'REFRESH'}
          style={{
            ...terminalButton(pres.state === 'READY' || pres.state === 'REFRESH' ? 'primary' : 'secondary'),
            ...(refreshing && pres.state === 'REFRESH' ? { opacity: 0.6, cursor: 'wait' } : {}),
          }}
        >
          {refreshing && pres.state === 'REFRESH' ? 'Refreshing…' : pres.primaryCta}
        </button>
        {pres.stale && (
          <button onClick={e => { e.stopPropagation(); setPrevOpen(v => !v) }} style={terminalButton('ghost')}>
            {prevOpen ? 'Hide previous plan' : 'View Previous Plan'}
          </button>
        )}
        {!pres.stale && onRefreshStrategy && (
          <button
            onClick={e => { e.stopPropagation(); onRefreshStrategy(e) }}
            disabled={refreshing}
            style={{ ...terminalButton('ghost'), ...(refreshing ? { opacity: 0.6, cursor: 'wait' } : {}) }}
          >
            {refreshing ? 'Refreshing…' : 'Refresh Strategy'}
          </button>
        )}
        {onRefresh && (
          <button onClick={e => { e.stopPropagation(); onRefresh(e) }} style={terminalButton('ghost')}>
            Refresh Inputs
          </button>
        )}
        <button
          onClick={e => { e.stopPropagation(); setDetails(v => !v) }}
          style={terminalButton('ghost')}
        >
          {details ? 'Hide details' : 'Details'}
        </button>
      </div>

      {prevOpen && pres.mechanics?.previous && (
        <div style={{ marginTop: 6, fontSize: 11, color: BB.text3 }}>
          Previous plan: {pres.mechanics.summary}
        </div>
      )}

      {/* Audit drawer — internal codes, all families, hashes, legacy */}
      {details && <AuditDrawer pres={pres} />}
    </div>
  )
}

/** V5 Section 6C — compact always-visible five-family rail. The preferred family
 *  is visually primary; rejection prose stays in the drawer (click to open). */
function StrategyRail({ pres, onOpen }: { pres: OperatorPresentation; onOpen: () => void }) {
  const fams = pres.audit?.families || {}
  const order = [
    ['long_term', 'LT'], ['swing', 'SWING'], ['bearish', 'BEAR'],
    ['options', 'OPT'], ['no_trade', 'NO-TRADE'],
  ] as const
  const prefKey = pres.primaryFamily?.key === 'refresh' ? null : pres.primaryFamily?.key
  // Operator words ONLY — internal packet codes (constructibility etc.) stay in
  // the Audit drawer; unmapped states render as a neutral dash, never raw codes.
  const famWord = (k: string, f: any): string => {
    if (k === 'no_trade') return f.preferred || f.dominant ? 'PREFERRED' : f.available ? 'AVAILABLE' : '—'
    const act = String(f.action_state || '').toUpperCase()
    const dec = String(f.decision_state || f.state || '').toUpperCase()
    if (act === 'READY') return 'READY'
    if (act.startsWith('WAIT') || dec.startsWith('WAIT')) return 'WAIT'
    if (dec.includes('REJECT') || act.includes('REJECT')) return 'REJECTED'
    if (k === 'options' && (dec.includes('STALE') || act.includes('STALE'))) return 'CHAIN STALE'
    if (dec.includes('UNAVAILABLE') || act.includes('UNAVAILABLE')) return 'UNAVAILABLE'
    if (dec.includes('ELIGIBLE') || dec.includes('VALID') || dec.includes('CONSTRUCT')) return 'AVAILABLE'
    return '—'
  }
  const toneColor = (w: string): string =>
    w === 'READY' ? BB.green
      : w === 'WAIT' || w === 'CHAIN STALE' ? BB.amber
        : w === 'REJECTED' ? BB.red
          : BB.text3
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 7 }}>
      {order.map(([k, label]) => {
        const f = (fams as any)[k] || {}
        const w = famWord(k, f)
        const primary = prefKey && String(prefKey).startsWith(k.split('_')[0])
        return (
          <button
            key={k}
            onClick={e => { e.stopPropagation(); onOpen() }}
            title={`${label}: ${w} — click for mechanics, conditions, rejection reasons`}
            style={{
              fontSize: 10, fontWeight: 800, letterSpacing: '.04em', cursor: 'pointer',
              color: toneColor(w), background: 'transparent',
              border: `1px solid ${primary ? toneColor(w) : BB.border}`,
              borderRadius: 2, padding: '1px 5px',
              boxShadow: primary ? `inset 0 0 0 1px ${toneColor(w)}` : undefined,
            }}
          >
            {label} {w}
          </button>
        )
      })}
    </div>
  )
}

/** 17.14 pill colors: green only for CONFIRMED bullish AND CURRENT; red for
 *  confirmed bearish current; amber for forming/conditional/mixed/due-soon;
 *  gray for neutral, unavailable, or stale evidence. */
function TechSetupRail({ tech, onOpen }: { tech: any; onOpen: () => void }) {
  const pills: any[] = tech?.pills || []
  if (!pills.length) return null
  const color = (p: any): string => {
    const stale = p.freshness !== 'CURRENT'
    const confirmed = p.lifecycle === 'CONFIRMED'
    if (stale) return BB.text3
    if (confirmed && p.direction === 'BULLISH') return BB.green
    if (confirmed && p.direction === 'BEARISH') return BB.red
    if (p.lifecycle === 'FORMING' || p.lifecycle === 'AWAITING_CONFIRMATION'
        || p.direction === 'MIXED') return BB.amber
    return BB.text3
  }
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 5 }}>
      <span style={{ fontSize: 10, fontWeight: 800, color: BB.text3, letterSpacing: '.05em', alignSelf: 'center' }}>
        TECH
      </span>
      {pills.slice(0, 6).map((p, i) => (
        <button
          key={i}
          onClick={e => { e.stopPropagation(); onOpen() }}
          title={`${p.tooltip || ''} · ${p.lifecycle} · ${p.freshness}`}
          style={{
            fontSize: 10, fontWeight: 800, letterSpacing: '.03em', cursor: 'pointer',
            color: color(p), background: 'transparent',
            border: `1px solid ${BB.border}`, borderRadius: 2, padding: '1px 5px',
          }}
        >
          {p.label}{p.value ? ` · ${p.value}` : ''}
          {p.freshness !== 'CURRENT' ? ` · ${String(p.freshness)}` : ''}
        </button>
      ))}
    </div>
  )
}

function AuditDrawer({ pres }: { pres: OperatorPresentation }) {
  const a = pres.audit
  const fams = a.families || {}
  const order = ['long_term', 'swing', 'bearish', 'options', 'no_trade'] as const
  const labels: Record<string, string> = {
    long_term: 'LONG_TERM', swing: 'SWING', bearish: 'BEARISH',
    options: 'OPTIONS', no_trade: 'NO_TRADE',
  }
  return (
    <div style={{
      marginTop: 8, paddingTop: 8, borderTop: `1px solid ${BB.border}`,
      display: 'flex', flexDirection: 'column', gap: 6,
    }}>
      <div style={{ fontSize: 10, fontWeight: 800, color: BB.amber, letterSpacing: '.06em', textTransform: 'uppercase' }}>
        Audit & prior opinions — not the operator decision
      </div>

      <div style={{ fontSize: 10, color: BB.text3 }}>
        Packet {a.packet?.packet_version || '—'} · policy {a.actionPolicy?.policy_version || '—'}
        {a.inputHashes.packet ? ` · packet hash ${a.inputHashes.packet}` : ''}
        {a.inputHashes.current ? ` · current hash ${a.inputHashes.current}` : ''}
      </div>

      {a.currentValidity && (
        <div style={{ fontSize: 10, color: BB.text2 }}>
          Current validity: <b>{String(a.currentValidity.state || '—')}</b>
          {(a.currentValidity.invalidation_reasons || []).length > 0 && (
            <span> — {(a.currentValidity.invalidation_reasons as string[]).join('; ')}</span>
          )}
        </div>
      )}

      {order.map(k => {
        const f = fams[k] || {}
        const kids = f.structures || []
        return (
          <div key={k} style={{ fontSize: 10, color: BB.text3, borderTop: `1px solid ${BB.border}`, paddingTop: 4 }}>
            <div>
              <b style={{ color: BB.text1 }}>{labels[k]}</b>
              {' '}constr={f.constructibility_state || '—'}
              {' · '}dec={f.decision_state || f.state || '—'}
              {' · '}act={f.action_state || '—'}
            </div>
            {kids.slice(0, 6).map((s: any, i: number) => (
              <div key={i} style={{ paddingLeft: 8 }}>
                {s.structure || '?'} · {s.state}
                {s.occ_symbol ? ` · ${s.occ_symbol}` : ''}
                {(s.rejection_reasons || [])[0] ? ` — ${String(s.rejection_reasons[0]).slice(0, 70)}` : ''}
              </div>
            ))}
            {k === 'no_trade' && (
              <div style={{ paddingLeft: 8 }}>
                available={String(!!f.available)} preferred={String(!!f.preferred)} dominant={String(!!f.dominant)}
                {f.reason ? ` · ${f.reason}` : ''}
              </div>
            )}
          </div>
        )
      })}

      {a.modelReview && (
        <div style={{ fontSize: 10, color: BB.text3 }}>
          Models: mode={a.modelReview.mode || '—'}
          {a.modelReview.agreement_by_dimension && (
            <span> · agreement {JSON.stringify(a.modelReview.agreement_by_dimension)}</span>
          )}
        </div>
      )}

      {a.ownership && (
        <div style={{ fontSize: 10, color: BB.text3 }}>
          Ownership: {a.ownership.held ? `HELD ${a.ownership.shares}` : 'NOT HELD'}
          {a.ownership.source ? ` · ${a.ownership.source}` : ''}
          {a.ownership.as_of ? ` · ${a.ownership.as_of}` : ''}
        </div>
      )}

      {a.legacy?.recommendation && (
        <div style={{ fontSize: 10, color: BB.text3 }}>
          Legacy @ build: {String(a.legacy.recommendation)}
          {a.legacy.generated_at ? ` · ${a.legacy.generated_at}` : ''}
        </div>
      )}

      {a.actionPolicy && (
        <div style={{ fontSize: 10, color: BB.text3 }}>
          Action policy: {a.actionPolicy.action} · state={a.actionPolicy.state} · allowed={String(!!a.actionPolicy.allowed)}
          {a.actionPolicy.reason ? ` · ${a.actionPolicy.reason}` : ''}
        </div>
      )}
    </div>
  )
}

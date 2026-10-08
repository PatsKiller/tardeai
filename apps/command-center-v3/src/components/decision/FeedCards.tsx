/** Communications feed as decision cards (operator 2026-10-08): "🚨 DT · STOP HEALTH · Priority 98 · Review Stops ·
 *  4d remaining" — colour-coded by family, no extra metadata unless expanded (click → the detail drawer). */
import { RADIUS, numStyle } from '../../lib/designTokens'
import { SymbolLink } from '../opportunity/OpportunityContext'
import { PANEL_ORDER, PANEL_PRESET, labelOf, ttlLabel } from '../comms/CommsHubParts'
import { BigNumberCard, FAMILY_ICON, familyFor, familyStyle, type Family } from './DecisionParts'

/** "🚨 STOP HEALTH — 3 alert(s) (1 urgent)" → "STOP HEALTH": the alert TYPE, without emoji, ticker or counts. */
export function alertType(headline?: string | null, symbols: string[] = []): string {
  let h = String(headline || '').replace(/^[^A-Za-z$]+/, '')
  for (const s of symbols) h = h.replace(new RegExp(`\\$?\\b${s}\\b`, 'g'), '')
  h = h.split(/\s[—–-]\s|·|:/)[0] || h
  return h.replace(/\s+/g, ' ').trim().slice(0, 48).toUpperCase() || '—'
}

const usd = (v: any) => (v == null || !Number.isFinite(Number(v)) ? '—' : `$${Number(v).toFixed(2)}`)

/** Live quote next to the ticker: "$14.04 ▲2.1%" (data-broker quote read at request time). */
export function PriceTag({ m }: { m?: any }) {
  if (!m || m.price == null) return null
  const ch = m.day_change_pct
  const up = Number(ch) >= 0
  return (
    <span title={m.as_of ? `${m.source || 'quote'} · ${new Date(m.as_of).toLocaleTimeString()}` : m.source}
      style={{ ...numStyle, fontSize: 14, fontWeight: 800, color: 'var(--text0)' }}>
      {usd(m.price)}
      {ch != null && <span style={{ fontSize: 12, marginLeft: 4, color: up ? 'var(--success-color)' : 'var(--danger-color)' }}>{up ? '▲' : '▼'}{Math.abs(Number(ch)).toFixed(1)}%</span>}
    </span>
  )
}

/** "Entry $13.90–$14.50 · Target $22.00 · R:R 6.5" from the CIO opportunity levels, when the CIO has them. */
export function LevelsLine({ l }: { l?: any }) {
  if (!l) return null
  const parts: string[] = []
  if (l.entry_zone && l.entry_zone[0] != null) parts.push(`Entry ${usd(l.entry_zone[0])}–${usd(l.entry_zone[1])}`)
  else if (l.entry_ref != null) parts.push(`Entry ${usd(l.entry_ref)}`)
  if (l.target != null) parts.push(`Target ${usd(l.target)}`)
  if (l.rr != null) parts.push(`R:R ${Number(l.rr).toFixed(1)}`)
  if (!parts.length) return null
  return <div style={{ ...numStyle, fontSize: 12, color: 'var(--text2)', marginTop: 2 }}>{parts.join(' · ')}</div>
}

export function FeedCard({ e, selected, picked, onPick, onOpen }: {
  e: any; selected: boolean; picked: boolean; onPick: () => void; onOpen: () => void
}) {
  const fam: Family = familyFor(e.priority, e.category)
  const s = familyStyle(fam)
  const syms: string[] = e.symbols || []
  // opportunity cards only: on a risk/stop card the urgency (priority) is the decision number
  const conv: number | null = fam === 'opportunity' && e.levels?.conviction != null && Number.isFinite(Number(e.levels.conviction)) ? Number(e.levels.conviction) : null
  const soon = e.ttl_remaining_s != null && e.ttl_remaining_s > 0 && e.ttl_remaining_s < 12 * 3600
  return (
    <div data-feed-card={e.event_id} data-family={fam} onClick={onOpen}
      style={{ display: 'grid', gridTemplateColumns: '20px minmax(0,1fr) auto', gap: 10, alignItems: 'center', cursor: 'pointer',
        background: selected ? s.bg : 'var(--bg1)', border: `1px solid ${selected ? s.border : 'var(--border)'}`,
        borderLeft: `5px solid ${s.border}`, borderRadius: RADIUS.md, padding: '8px 12px' }}>
      <input type="checkbox" checked={picked} onClick={(ev) => ev.stopPropagation()} onChange={onPick} aria-label="select" />
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 16 }}>{FAMILY_ICON[fam]}</span>
          {syms.length > 0
            ? <span style={{ fontSize: 17, fontWeight: 900, color: 'var(--text0)' }}><SymbolLink symbol={syms[0]} />{syms.length > 1 ? <span style={{ fontSize: 11, color: 'var(--text3)' }}> +{syms.length - 1}</span> : null}</span>
            : e.direction === 'INBOUND' ? <span style={{ fontSize: 12, fontWeight: 900, color: s.color }}>FROM YOU</span> : null}
          {syms.length > 0 && <PriceTag m={e.market} />}
          <span style={{ fontSize: 13, fontWeight: 800, color: s.color, letterSpacing: '.03em' }}>{alertType(e.headline || e.short_summary, syms)}</span>
        </div>
        {e.action_hint && e.actionable
          ? <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginTop: 2 }}>▶ {e.action_hint}</div>
          : <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2 }}>{labelOf(e.category)} · informational</div>}
        <LevelsLine l={e.levels} />
      </div>
      <div style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
        {/* One number per ticker everywhere (operator 2026-10-08: "why confidence doesn't match"): the CIO conviction
            that Home and the opportunity view show. Message priority (an urgency score per message, so two messages
            on one ticker differed) is shown, labelled, on risk cards and when the CIO has no conviction for the name. */}
        {conv != null ? (
          <>
            <div style={{ ...numStyle, fontSize: 22, fontWeight: 900, color: 'var(--text0)', lineHeight: 1 }} title={`CIO conviction ${Math.round(conv)}/100${e.priority_score != null ? ` · message priority ${Math.round(e.priority_score)}` : ''}`}>{Math.round(conv)}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)' }}>conviction{e.levels?.rank ? ` #${e.levels.rank}` : ''}</div>
          </>
        ) : (
          <>
            <div style={{ ...numStyle, fontSize: 22, fontWeight: 900, color: 'var(--text3)', lineHeight: 1 }} title="message priority (urgency of this message)">{e.priority_score != null ? Math.round(e.priority_score) : '—'}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)' }}>priority</div>
          </>
        )}
        <div style={{ fontSize: 11, color: soon ? 'var(--warning-color)' : 'var(--text3)' }}>{ttlLabel(e.ttl_remaining_s, e.legal_hold).replace('left', 'remaining')}</div>
      </div>
    </div>
  )
}

const PANEL_LOOK: Record<string, { icon: string; label: string; family: Family }> = {
  attention: { icon: '🚨', label: 'Attention', family: 'critical' },
  reward: { icon: '🟢', label: 'Highest reward', family: 'opportunity' },
  reentry: { icon: '↩️', label: 'Re-entry', family: 'opportunity' },
  risk: { icon: '🔴', label: 'Highest risk', family: 'high' },
  expiring: { icon: '⏳', label: 'Expiring soon', family: 'medium' },
  recent: { icon: '⚡', label: 'Recently actionable', family: 'medium' },
}

/** The board as numbers first: live / actionable / informational, then one big-number card per question. */
export function BoardCards({ board, onPick }: { board: any; onPick: (preset: Record<string, string>) => void }) {
  if (!board?.panels) return null
  return (
    <div data-testid="comms-board-cards" style={{ marginBottom: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, marginBottom: 10 }}>
        <BigNumberCard label="Live" value={board.live ?? 0} family="neutral" />
        <BigNumberCard label="Actionable" value={board.actionable ?? 0} family="critical" onClick={() => onPick(PANEL_PRESET.attention)} />
        <BigNumberCard label="Informational" value={board.ignorable ?? 0} family="neutral" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}>
        {PANEL_ORDER.filter((k) => board.panels[k]).map((k) => {
          const p = board.panels[k]
          const look = PANEL_LOOK[k] || { icon: '•', label: p.label, family: 'neutral' as Family }
          return <BigNumberCard key={k} testId={`board-${k}`} icon={look.icon} label={look.label} value={p.count ?? 0}
            family={look.family} onClick={() => onPick(PANEL_PRESET[k])}
            sub={(p.items || []).slice(0, 3).map((e: any) => {
              const sym = (e.symbols || [])[0]
              if (!sym) return null
              return e.market?.price != null ? `${sym} ${usd(e.market.price)}` : sym
            }).filter(Boolean).join(' · ') || undefined} />
        })}
      </div>
    </div>
  )
}

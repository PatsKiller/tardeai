/** Communications feed as decision cards (operator 2026-10-08): "🚨 DT · STOP HEALTH · Priority 98 · Review Stops ·
 *  4d remaining" — colour-coded by family; the card carries the decision facts (entry / stop / target / R:R, Street
 *  consensus, catalyst) so the drawer is for the full message (operator 2026-10-19). */
import { RADIUS, numStyle } from '../../lib/designTokens'
import { SymbolLink } from '../opportunity/OpportunityContext'
import { PANEL_ORDER, PANEL_PRESET, labelOf, ttlLabel } from '../comms/CommsHubParts'
import { BigNumberCard, FAMILY_ICON, familyFor, familyStyle, type Family } from './DecisionParts'

/** "🚨 STOP HEALTH — 3 alert(s) (1 urgent)" → "STOP HEALTH": the alert TYPE, without emoji, ticker or counts. */
export function alertType(headline?: string | null, symbols: string[] = []): string {
  let h = String(headline || '').replace(/^[^A-Za-z$]+/, '')
  for (const s of symbols) {
    const literal = s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    h = h.replace(new RegExp(`\\$?\\b${literal}\\b`, 'g'), '')
  }
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

/** "Catalyst: News: Navan Advances … (2026-10-16) · +2 more" → the first catalyst line, tags stripped. */
export function catalystOf(body?: string | null): string | null {
  if (!body) return null
  const text = body.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  const m = text.match(/Catalyst:\s*(?:News:\s*)?([^\n]+)/i)
  return m ? m[1].trim().slice(0, 160) : null
}

// ── Street view ─────────────────────────────────────────────────────────────
export function AnalystLine({ a, size = 12 }: { a?: any; size?: number }) {
  if (!a) return null
  const parts: string[] = []
  parts.push(a.rating ? `${a.rating}` : 'No consensus rating')
  if (a.analyst_count) parts.push(`${a.analyst_count} analysts`)
  if (a.target_mean != null) parts.push(`mean target ${usd(a.target_mean)}${a.upside_pct != null ? ` (${a.upside_pct >= 0 ? '+' : ''}${a.upside_pct}%)` : ''}`)
  const color = /buy/i.test(a.rating || '') ? 'var(--success-color)' : /sell|underperform/i.test(a.rating || '') ? 'var(--danger-color)' : 'var(--text2)'
  return (
    <div data-testid="analyst-line" style={{ fontSize: size, color: 'var(--text2)', marginTop: 2 }}
      title={`Street consensus (${a.source || 'analyst targets'}) as of ${a.as_of ? new Date(a.as_of).toLocaleDateString() : '—'}${a.target_low != null ? ` · range ${usd(a.target_low)}–${usd(a.target_high)}` : ''}`}>
      <span style={{ color: 'var(--text3)' }}>Analysts </span>
      <b style={{ color }}>{parts[0]}</b>{parts.length > 1 ? ` · ${parts.slice(1).join(' · ')}` : ''}
      {a.stale && <span style={{ color: 'var(--warning-color)' }}> · {Math.round(a.age_days)}d old</span>}
    </div>
  )
}

/** "Entry $13.90–$14.50 · Target $22.00 · R:R 6.5" from the CIO opportunity levels, when the CIO has them. */
export function LevelsLine({ l }: { l?: any }) {
  if (!l) return null
  const parts: string[] = []
  if (l.entry_zone && l.entry_zone[0] != null) parts.push(`Entry ${usd(l.entry_zone[0])}–${usd(l.entry_zone[1])}`)
  else if (l.entry_ref != null) parts.push(`Entry ${usd(l.entry_ref)}`)
  if (l.invalidation_level != null) parts.push(`Stop ${usd(l.invalidation_level)}`)
  if (l.target != null) parts.push(`Target ${usd(l.target)}`)
  if (l.rr != null) parts.push(`R:R ${Number(l.rr).toFixed(1)}`)
  if (!parts.length) return null
  return <div style={{ ...numStyle, fontSize: 12, color: 'var(--text2)', marginTop: 2 }}>{parts.join(' · ')}</div>
}

/** Investment entry messages need an identified instrument before they can invite a decision.
 * General operational messages and inbound notes may legitimately have no ticker. */
export function messageIdentity(e: any): { symbols: string[]; incomplete: boolean } {
  const usableSymbol = (value: unknown): value is string => typeof value === 'string' && /[\p{L}\p{N}]/u.test(value)
  const parsed = Array.isArray(e?.symbols) ? e.symbols.filter(usableSymbol).map((s: string) => s.trim()) : []
  // symbols[] is parsed from message prose, independently of the producer's explicit instrument identity. A body
  // without a ticker can therefore have symbols=[] AND a known entity_refs.symbol. Use that canonical field when
  // no parsed symbols are usable; never extract a ticker from subject_key/prose or change the event's actionability.
  const refs = e?.entity_refs
  const explicit = refs && typeof refs === 'object' && !Array.isArray(refs)
    && Object.prototype.hasOwnProperty.call(refs, 'symbol') && usableSymbol(refs.symbol) ? refs.symbol.trim() : null
  const symbols: string[] = parsed.length ? parsed : explicit ? [explicit] : []
  const entry = ['reward', 'high_conviction_opportunity', 're_entry', 'watchlist_candidate'].includes(e?.category)
    || /\b(?:review entry|high conviction entry)\b/i.test(`${e?.action_hint || ''} ${e?.headline || e?.short_summary || ''}`)
  return { symbols, incomplete: e?.direction !== 'INBOUND' && entry && symbols.length === 0 }
}

export function FeedCard({ e, selected, picked, onPick, onOpen, selectable = true }: {
  e: any; selected: boolean; picked: boolean; onPick: () => void; onOpen: () => void; selectable?: boolean
}) {
  const { symbols: syms, incomplete } = messageIdentity(e)
  const fam: Family = incomplete ? 'neutral' : familyFor(e.priority, e.category)
  const s = familyStyle(fam)
  // opportunity cards only: on a risk/stop card the urgency (priority) is the decision number
  const conv: number | null = !incomplete && fam === 'opportunity' && e.levels?.conviction != null && Number.isFinite(Number(e.levels.conviction)) ? Number(e.levels.conviction) : null
  const soon = e.ttl_remaining_s != null && e.ttl_remaining_s > 0 && e.ttl_remaining_s < 12 * 3600
  const catalyst = catalystOf(e.sanitized_body)
  const acked = e.lifecycle_status === 'acknowledged' || !!e.acknowledged_at
  return (
    <div data-feed-card={e.event_id} data-family={fam} data-selectable={selectable} onClick={onOpen}
      style={{ display: 'grid', gridTemplateColumns: selectable ? '20px minmax(0,1fr) auto' : 'minmax(0,1fr) auto', gap: 10, alignItems: 'center', cursor: 'pointer',
        background: selected ? s.bg : 'var(--bg1)', borderTop: `1px solid ${selected ? s.border : 'var(--border)'}`,
        borderRight: `1px solid ${selected ? s.border : 'var(--border)'}`, borderBottom: `1px solid ${selected ? s.border : 'var(--border)'}`, borderLeft: `5px solid ${s.border}`, borderRadius: RADIUS.md, padding: '8px 12px', opacity: acked && !selected ? 0.75 : 1 }}>
      {selectable && <input type="checkbox" checked={picked} onClick={(ev) => ev.stopPropagation()} onChange={onPick} aria-label="Select this message" />}
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 16 }}>{FAMILY_ICON[fam]}</span>
          {syms.length > 0
            ? <span style={{ fontSize: 17, fontWeight: 900, color: 'var(--text0)' }}><SymbolLink symbol={syms[0]} />{syms.length > 1 ? <span style={{ fontSize: 11, color: 'var(--text3)' }}> +{syms.length - 1}</span> : null}</span>
            : e.direction === 'INBOUND' ? <span style={{ fontSize: 12, fontWeight: 900, color: s.color }}>FROM YOU</span> : null}
          {syms.length > 0 && <PriceTag m={e.market} />}
          <span style={{ fontSize: 13, fontWeight: 800, color: s.color, letterSpacing: '.03em' }}>{incomplete ? 'Incomplete message' : alertType(e.headline || e.short_summary, syms)}</span>
        </div>
        {incomplete ? <div role="note" style={{ color: 'var(--warning-color)', fontSize: 13, marginTop: 2 }}>The subject is missing. Entry review is unavailable; read the original message for context.</div> : e.action_hint && e.actionable
          ? <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginTop: 2 }}>▶ {e.action_hint}</div>
          : <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2 }}>{labelOf(e.category)} · informational</div>}
        {!incomplete && <details className="comms-card-facts" onClick={event => event.stopPropagation()} style={{ marginTop: 4 }}>
          <summary style={{ fontSize: 12, color: 'var(--text3)', cursor: 'pointer', minHeight: 44 }}>Supporting detail</summary>
          <LevelsLine l={e.levels} />
          <AnalystLine a={e.analyst} />
        {catalyst && <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={catalyst}><span style={{ color: 'var(--text3)' }}>Catalyst </span>{catalyst}</div>}
        </details>}
        <button type="button" onClick={event => { event.stopPropagation(); onOpen() }} style={{ minHeight: 44, color: 'var(--info-color)', background: 'transparent', border: 0, padding: 0, cursor: 'pointer' }}>Read message</button>
      </div>
      <div style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
        {/* One number per ticker everywhere (operator 2026-10-08: "why confidence doesn't match"): the CIO conviction
            that Home and the opportunity view show. Message priority (an urgency score per message, so two messages
            on one ticker differed) is shown, labelled, on risk cards and when the CIO has no conviction for the name. */}
        {incomplete ? <span style={{ fontSize: 11, color: 'var(--text3)' }}>Subject needed</span> : conv != null ? (
          <>
            <div style={{ ...numStyle, fontSize: 22, fontWeight: 900, color: e.levels?.low_conviction ? 'var(--text3)' : 'var(--text0)', lineHeight: 1 }} title={`CIO conviction ${Math.round(conv)}/100${e.priority_score != null ? ` · message priority ${Math.round(e.priority_score)}` : ''}`}>{Math.round(conv)}</div>
            <div style={{ fontSize: 10, color: e.levels?.low_conviction ? 'var(--warning-color)' : 'var(--text3)' }}
              title={e.levels?.low_conviction ? `below the CIO conviction floor ${e.levels.conviction_floor} — ranked last` : undefined}>
              {e.levels?.low_conviction ? 'low conviction' : 'conviction'}{e.levels?.rank ? ` #${e.levels.rank}` : ''}
            </div>
          </>
        ) : (
          <>
            <div style={{ ...numStyle, fontSize: 22, fontWeight: 900, color: 'var(--text3)', lineHeight: 1 }} title="message priority (urgency of this message)">{e.priority_score != null ? Math.round(e.priority_score) : '—'}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)' }}>priority</div>
          </>
        )}
        <div style={{ fontSize: 11, color: soon ? 'var(--warning-color)' : 'var(--text3)' }}>{ttlLabel(e.ttl_remaining_s, e.legal_hold).replace('left', 'remaining')}</div>
        {acked && <div style={{ fontSize: 10, color: 'var(--success-color)' }} title={e.acknowledged_by ? `acknowledged by ${e.acknowledged_by}` : undefined}>✓ seen</div>}
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

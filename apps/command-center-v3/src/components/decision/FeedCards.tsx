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

export function FeedCard({ e, selected, picked, onPick, onOpen }: {
  e: any; selected: boolean; picked: boolean; onPick: () => void; onOpen: () => void
}) {
  const fam: Family = familyFor(e.priority, e.category)
  const s = familyStyle(fam)
  const syms: string[] = e.symbols || []
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
          <span style={{ fontSize: 13, fontWeight: 800, color: s.color, letterSpacing: '.03em' }}>{alertType(e.headline || e.short_summary, syms)}</span>
        </div>
        {e.action_hint && e.actionable
          ? <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginTop: 2 }}>▶ {e.action_hint}</div>
          : <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2 }}>{labelOf(e.category)} · informational</div>}
      </div>
      <div style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
        <div style={{ ...numStyle, fontSize: 22, fontWeight: 900, color: 'var(--text0)', lineHeight: 1 }} title="priority score">{e.priority_score != null ? Math.round(e.priority_score) : '—'}</div>
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
            sub={(p.items || []).slice(0, 3).map((e: any) => (e.symbols || [])[0]).filter(Boolean).join(' · ') || undefined} />
        })}
      </div>
    </div>
  )
}

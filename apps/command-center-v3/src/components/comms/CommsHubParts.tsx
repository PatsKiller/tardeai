/** Communications hub — decision-support parts (operator 2026-10-07).
 *  Board: the six questions (attention, reward, re-entry, risk, expiring soon, recently actionable).
 *  Filter modal: category, risk, reward, re-entry status, confidence, time range, source, symbol, priority.
 *  Badges: priority, category, re-entry status, actionable, TTL remaining, status. Data: /api/v2/communications/*. */
import { useEffect, useState } from 'react'

const MUTED = 'var(--text3)'
const TEXT = 'var(--text0)'
const TEXT2 = 'var(--text2)'
const BORDER = 'var(--border)'
const MONO = "'JetBrains Mono', ui-monospace, Consolas, monospace"

export const PRIORITY_COLOR: Record<string, string> = {
  critical: '#ef4444', high: '#f59e0b', medium: '#60a5fa', low: '#94a3b8',
}
export const REENTRY_COLOR: Record<string, string> = {
  confirmed: '#22c55e', opportunity: '#4ade80', potential: '#facc15', expired: '#94a3b8', invalidated: '#ef4444',
}
export const CATEGORY_COLOR: Record<string, string> = {
  re_entry: '#22c55e', risk: '#f97316', reward: '#4ade80', high_conviction_opportunity: '#10b981',
  watchlist_candidate: '#a78bfa', threat: '#ef4444', market_event: '#38bdf8', news: '#94a3b8',
  security_alert: '#f43f5e', system_alert: '#64748b', operational_issue: '#eab308', operator_conversation: '#c084fc',
}

export function labelOf(id?: string | null) {
  if (!id) return '—'
  return id.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function ttlLabel(seconds?: number | null, legalHold?: boolean) {
  if (legalHold) return 'kept'
  if (seconds == null) return '—'
  if (seconds <= 0) return 'expired'
  const h = seconds / 3600
  if (h < 1) return `${Math.max(1, Math.round(seconds / 60))}m left`
  if (h < 48) return `${Math.round(h)}h left`
  return `${Math.round(h / 24)}d left`
}

export function Badge({ text, color, title }: { text: string; color: string; title?: string }) {
  return (
    <span title={title} style={{ display: 'inline-block', fontSize: 9, fontWeight: 800, padding: '1px 6px', borderRadius: 3,
      color, border: `1px solid ${color}`, background: 'transparent', whiteSpace: 'nowrap', letterSpacing: '.02em' }}>
      {text}
    </span>
  )
}

export function ScoreBar({ v, color, title }: { v?: number | null; color: string; title: string }) {
  const pct = v == null ? 0 : Math.round(v * 100)
  return (
    <span title={`${title}: ${v == null ? 'n/a' : pct}`} style={{ display: 'inline-block', width: 26, height: 5, background: 'var(--bg2, #1f2937)', borderRadius: 2, marginRight: 2, verticalAlign: 'middle' }}>
      <span style={{ display: 'block', width: `${pct}%`, height: 5, background: color, borderRadius: 2 }} />
    </span>
  )
}

export function ItemBadges({ e }: { e: any }) {
  return (
    <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
      {e.priority && <Badge text={e.priority.toUpperCase()} color={PRIORITY_COLOR[e.priority] || MUTED} title={`priority score ${e.priority_score ?? '—'}`} />}
      {e.category && <Badge text={labelOf(e.category)} color={CATEGORY_COLOR[e.category] || MUTED} />}
      {e.reentry_status && <Badge text={`Re-entry: ${e.reentry_status}`} color={REENTRY_COLOR[e.reentry_status] || MUTED} />}
      {e.actionable && <Badge text={e.action_hint ? `▶ ${e.action_hint}` : '▶ Actionable'} color="#22c55e" />}
    </span>
  )
}

// ── Decision board ──────────────────────────────────────────────────────────

const PANEL_PRESET: Record<string, Record<string, string>> = {
  attention: { actionable: '1', priority: 'critical,high', sort: 'priority_score' },
  reward: { actionable: '1', category: 'reward,high_conviction_opportunity,re_entry', sort: 'reward_score' },
  reentry: { category: 're_entry', reentry_status: 'confirmed,opportunity,potential', sort: 'priority_score' },
  risk: { category: 'threat,risk', sort: 'risk_score' },
  expiring: { actionable: '1', expiring_within_h: '12', sort: 'expires_at', order: 'asc' },
  recent: { actionable: '1', sort: 'actionable_since' },
}
const PANEL_ORDER = ['attention', 'reward', 'reentry', 'risk', 'expiring', 'recent']

export function DecisionBoard({ board, onPick, onOpen }: { board: any; onPick: (preset: Record<string, string>) => void; onOpen: (id: string) => void }) {
  if (!board?.panels) return null
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 10, color: MUTED, marginBottom: 6 }}>
        <b style={{ color: TEXT }}>{board.live ?? 0}</b> live items · <b style={{ color: '#22c55e' }}>{board.actionable ?? 0}</b> actionable ·{' '}
        <b style={{ color: TEXT2 }}>{board.ignorable ?? 0}</b> can be ignored (informational)
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 8 }}>
        {PANEL_ORDER.filter((k) => board.panels[k]).map((k) => {
          const p = board.panels[k]
          return (
            <div key={k} className="cc-panel" style={{ border: `1px solid ${BORDER}`, borderRadius: 6, padding: 8, background: 'var(--bg1)' }}>
              <button type="button" onClick={() => onPick(PANEL_PRESET[k])} title="Filter the feed to this view"
                style={{ all: 'unset', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', width: '100%', marginBottom: 6 }}>
                <span style={{ fontSize: 10, fontWeight: 800, color: TEXT, textTransform: 'uppercase', letterSpacing: '.05em' }}>{p.label}</span>
                <span style={{ fontSize: 11, fontWeight: 800, color: p.count ? TEXT : MUTED }}>{p.count}</span>
              </button>
              {(p.items || []).length === 0 && <div style={{ fontSize: 10, color: MUTED }}>Nothing here.</div>}
              {(p.items || []).map((e: any) => (
                <div key={e.event_id} onClick={() => onOpen(e.event_id)} style={{ cursor: 'pointer', padding: '3px 0', borderTop: `1px solid ${BORDER}` }}>
                  <div style={{ fontSize: 10, color: TEXT, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={e.headline}>
                    {(e.symbols || []).length > 0 && <b style={{ fontFamily: MONO, marginRight: 4 }}>{e.symbols.slice(0, 2).join(' ')}</b>}
                    {e.headline || e.short_summary}
                  </div>
                  <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginTop: 2, flexWrap: 'wrap' }}>
                    <ItemBadges e={e} />
                    <span style={{ fontSize: 9, color: MUTED }}>{ttlLabel(e.ttl_remaining_s, e.legal_hold)}</span>
                  </div>
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Filter modal ────────────────────────────────────────────────────────────

export type HubFilters = Record<string, string>

const LEVELS = [['', 'any'], ['0.3', '≥ 0.3'], ['0.5', '≥ 0.5'], ['0.7', '≥ 0.7'], ['0.9', '≥ 0.9']]
const RANGES = [['', 'all time'], ['1', 'last 1h'], ['6', 'last 6h'], ['24', 'last 24h'], ['72', 'last 3d'], ['168', 'last 7d']]

function toggleCsv(csv: string | undefined, v: string) {
  const s = new Set((csv || '').split(',').filter(Boolean))
  if (s.has(v)) s.delete(v)
  else s.add(v)
  return Array.from(s).join(',')
}

function Chips({ options, value, onChange, colors }: { options: { id: string; label: string; count?: number }[]; value?: string; onChange: (v: string) => void; colors?: Record<string, string> }) {
  const sel = new Set((value || '').split(',').filter(Boolean))
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
      {options.map((o) => {
        const on = sel.has(o.id)
        const c = colors?.[o.id] || '#60a5fa'
        return (
          <button key={o.id} type="button" onClick={() => onChange(toggleCsv(value, o.id))}
            style={{ fontSize: 10, padding: '2px 7px', borderRadius: 3, cursor: 'pointer', border: `1px solid ${on ? c : BORDER}`, background: on ? `${c}22` : 'transparent', color: on ? TEXT : TEXT2 }}>
            {o.label}{o.count != null ? ` · ${o.count}` : ''}
          </button>
        )
      })}
    </div>
  )
}

export function CommsFilterModal({ open, initial, meta, onApply, onClose }: { open: boolean; initial: HubFilters; meta: any; onApply: (f: HubFilters) => void; onClose: () => void }) {
  const [f, setF] = useState<HubFilters>(initial)
  useEffect(() => { if (open) setF(initial) }, [open, initial])
  if (!open) return null
  const set = (k: string, v: string) => setF((p) => { const n = { ...p }; if (v) n[k] = v; else delete n[k]; return n })
  const cats = (meta?.categories || []).map((c: any) => ({ id: c.id, label: c.label, count: meta?.facets?.category?.[c.id] }))
  const prios = ['critical', 'high', 'medium', 'low'].map((p) => ({ id: p, label: labelOf(p), count: meta?.facets?.priority?.[p] }))
  const reent = ['confirmed', 'opportunity', 'potential', 'expired', 'invalidated'].map((p) => ({ id: p, label: labelOf(p), count: meta?.facets?.reentry_status?.[p] }))
  const row = (label: string, el: any) => (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 10, color: MUTED, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 4 }}>{label}</div>
      {el}
    </div>
  )
  const sel = (k: string, opts: string[][]) => (
    <select value={f[k] || ''} onChange={(e) => set(k, e.target.value)} style={{ fontSize: 10, padding: '3px 6px', background: 'var(--bg1)', border: `1px solid ${BORDER}`, color: TEXT }}>
      {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )
  const inp = (k: string, ph: string) => (
    <input value={f[k] || ''} onChange={(e) => set(k, e.target.value)} placeholder={ph}
      style={{ fontSize: 10, padding: '3px 8px', background: 'var(--bg1)', border: `1px solid ${BORDER}`, color: TEXT, minWidth: 160 }} />
  )
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: 'var(--bg1)', border: `1px solid ${BORDER}`, borderRadius: 10, padding: 18, width: 620, maxWidth: '94vw', maxHeight: '88vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
          <b style={{ color: TEXT }}>Communication intelligence filters</b>
          <button type="button" onClick={() => setF({})} style={{ fontSize: 10, border: `1px solid ${BORDER}`, background: 'transparent', color: MUTED, cursor: 'pointer', padding: '2px 8px' }}>Clear all</button>
        </div>
        {row('Category', <Chips options={cats} value={f.category} onChange={(v) => set('category', v)} colors={CATEGORY_COLOR} />)}
        {row('Priority', <Chips options={prios} value={f.priority} onChange={(v) => set('priority', v)} colors={PRIORITY_COLOR} />)}
        {row('Re-entry status', <Chips options={reent} value={f.reentry_status} onChange={(v) => set('reentry_status', v)} colors={REENTRY_COLOR} />)}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          {row('Risk level', sel('min_risk', LEVELS))}
          {row('Reward potential', sel('min_reward', LEVELS))}
          {row('Confidence level', sel('min_confidence', LEVELS))}
          {row('Time sensitivity', sel('min_time', LEVELS))}
          {row('Time range', sel('within_h', RANGES))}
          {row('Expiring within', sel('expiring_within_h', [['', 'any'], ['6', '6h'], ['12', '12h'], ['24', '24h'], ['48', '48h']]))}
          {row('Symbol or asset', inp('symbol', 'e.g. SPCX, TDG'))}
          {row('Source (producer)', inp('producer', 'e.g. telegram_alert.send_telegram'))}
          {row('Text search', inp('q', 'words in the message'))}
          {row('Show', (
            <div style={{ display: 'flex', gap: 10, fontSize: 10, color: TEXT2 }}>
              <label><input type="checkbox" checked={f.actionable === '1'} onChange={(e) => set('actionable', e.target.checked ? '1' : '')} /> actionable only</label>
              <label><input type="checkbox" checked={f.include_expired === '1'} onChange={(e) => set('include_expired', e.target.checked ? '1' : '')} /> include expired</label>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 6 }}>
          <button type="button" onClick={onClose} style={{ fontSize: 11, padding: '4px 12px', border: `1px solid ${BORDER}`, background: 'transparent', color: TEXT2, cursor: 'pointer' }}>Cancel</button>
          <button type="button" onClick={() => { onApply(f); onClose() }} style={{ fontSize: 11, padding: '4px 12px', border: '1px solid #22c55e', background: '#22c55e22', color: TEXT, cursor: 'pointer', fontWeight: 700 }}>Apply filters</button>
        </div>
      </div>
    </div>
  )
}

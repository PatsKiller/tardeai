import { useState } from 'react'
import { GLOSSARY, strategyGuide } from '../lib/optionsNovice'
import { NOVICE } from '../lib/optionsTooltips'

const panel = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 } as const
const BLUE = '#60a5fa'
const GREEN = '#22c55e'
const TEXT2 = 'var(--text2)'
const MUTED = 'var(--text3)'

const STRATEGIES = ['covered_call', 'cash_secured_put', 'long_call', 'credit_spread'] as const

export function Options101Banner({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  return (
    <div title={NOVICE.banner} style={{ ...panel, marginBottom: 14, borderLeft: '4px solid #a855f7', cursor: 'help' }}>
      <button
        type="button"
        onClick={onToggle}
        style={{ display: 'flex', width: '100%', justifyContent: 'space-between', alignItems: 'center', background: 'none', border: 'none', cursor: 'help', padding: 0, color: 'var(--text0)' }}
      >
        <span style={{ fontSize: 12, fontWeight: 800 }}>📘 Options 101 — plain-English guide ⓘ</span>
        <span style={{ fontSize: 10, color: MUTED }}>{collapsed ? 'Show' : 'Hide'}</span>
      </button>
      {!collapsed && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 11, color: TEXT2, lineHeight: 1.55, marginBottom: 12 }}>
            This desk only surfaces <b>pre-filtered</b> ideas (quality score, POP, IV). Cards show what you would do, what you collect or pay, and what can go wrong.
            Always <b>View Chain</b> for live quotes before trading. Live orders need <b>2FA</b> — nothing auto-submits.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10, marginBottom: 14 }}>
            {STRATEGIES.map(s => {
              const g = strategyGuide(s)
              return (
                <div key={s} style={{ background: 'var(--bg2)', borderRadius: 8, padding: 10, border: '1px solid var(--border)' }}>
                  <div style={{ fontSize: 11, fontWeight: 800, color: BLUE }}>{g.emoji} {g.name}</div>
                  <div style={{ fontSize: 10, color: TEXT2, marginTop: 5, lineHeight: 1.45 }}>{g.oneLiner}</div>
                  <div style={{ fontSize: 9.5, color: GREEN, marginTop: 6 }}>✓ {g.win}</div>
                  <div style={{ fontSize: 9.5, color: '#f59e0b', marginTop: 3 }}>⚠ {g.lose}</div>
                </div>
              )
            })}
          </div>
          <details>
            <summary style={{ fontSize: 10, fontWeight: 800, color: MUTED, cursor: 'pointer' }}>Glossary ({GLOSSARY.length} terms)</summary>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 8, marginTop: 10 }}>
              {GLOSSARY.map(g => (
                <div key={g.term} style={{ fontSize: 10, color: TEXT2, lineHeight: 1.4 }}>
                  <b style={{ color: 'var(--text1)' }}>{g.term}</b> — {g.def}
                </div>
              ))}
            </div>
          </details>
        </div>
      )}
    </div>
  )
}

export function PreflightConfirmModal({
  proposal,
  onConfirm,
  onCancel,
}: {
  proposal: { symbol: string; strategy: string; strike: number; expiration?: string; dte?: number; contracts?: number; premium_total?: number; data_source?: string }
  onConfirm: () => void
  onCancel: () => void
}) {
  const g = strategyGuide(proposal.strategy)
  const lines = [
    `${g.name} on ${proposal.symbol}`,
    `${proposal.contracts ?? 1} contract(s) · $${proposal.strike} strike · ${proposal.dte ?? '—'} days`,
    `Est. ${proposal.premium_total != null ? `$${proposal.premium_total.toLocaleString()}` : '—'} ${proposal.data_source === 'bs_estimate' ? '(verify on chain!)' : ''}`,
    `✓ ${g.win}`,
    `⚠ ${g.lose}`,
  ]

  return (
    <div onClick={onCancel} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.72)', zIndex: 90, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg1)', border: '1px solid #60a5fa', borderRadius: 12, padding: 18, width: 'min(440px, 94vw)' }}>
        <div style={{ fontSize: 14, fontWeight: 900, color: BLUE }}>Confirm before preflight</div>
        <div style={{ fontSize: 10, color: MUTED, marginTop: 4 }}>Read this checklist — then we request 2FA (you still approve before anything hits the broker).</div>
        <ul style={{ margin: '12px 0 0', paddingLeft: 18, fontSize: 11, color: TEXT2, lineHeight: 1.55 }}>
          {lines.map((l, i) => <li key={i} style={{ marginBottom: 4 }}>{l}</li>)}
        </ul>
        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          <button type="button" onClick={onCancel} style={{ fontSize: 11, padding: '7px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: MUTED, cursor: 'pointer' }}>Cancel</button>
          <button type="button" onClick={onConfirm} style={{ fontSize: 11, fontWeight: 800, padding: '7px 16px', borderRadius: 6, border: 'none', background: GREEN, color: '#0f172a', cursor: 'pointer' }}>I understand — request 2FA</button>
        </div>
      </div>
    </div>
  )
}

export function NoviceToggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <label title={NOVICE.toggle} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: MUTED, cursor: 'help' }}>
      <input type="checkbox" checked={on} onChange={e => onChange(e.target.checked)} />
      <span>Beginner hints ⓘ</span>
    </label>
  )
}

export function StrikeDistanceBar({ spot, strike, side }: { spot: number; strike: number; side: 'otm' | 'itm' | 'atm' }) {
  const pct = ((strike - spot) / spot) * 100
  const color = side === 'otm' ? GREEN : side === 'itm' ? '#ef4444' : '#f59e0b'
  const width = Math.min(100, Math.max(8, Math.abs(pct) * 8))
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: MUTED, marginBottom: 4 }}>
        <span>Spot ${spot.toFixed(2)}</span>
        <span style={{ color }}>Strike ${strike.toFixed(strike < 50 ? 2 : 0)}</span>
      </div>
      <div style={{ height: 6, background: 'var(--bg2)', borderRadius: 4, position: 'relative', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 2, background: MUTED, transform: 'translateX(-50%)', opacity: 0.5 }} />
        <div style={{
          position: 'absolute',
          top: 0, bottom: 0,
          width: `${width}%`,
          background: color,
          borderRadius: 4,
          left: side === 'itm' ? `${50 - width / 2}%` : side === 'otm' ? '50%' : '48%',
          opacity: 0.85,
        }} />
      </div>
    </div>
  )
}

export function RiskFlagChips({ flags }: { flags: { label: string; tip: string; severity: string }[] }) {
  if (!flags.length) return null
  const c = (s: string) => s === 'danger' ? '#ef4444' : s === 'warn' ? '#f59e0b' : MUTED
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 8 }}>
      {flags.map(f => (
        <span key={f.label} title={f.tip} style={{ fontSize: 8.5, fontWeight: 800, padding: '2px 7px', borderRadius: 4, color: c(f.severity), background: `${c(f.severity)}18`, border: `1px solid ${c(f.severity)}44`, cursor: 'help' }}>
          {f.severity === 'danger' ? '⚠ ' : ''}{f.label}
        </span>
      ))}
    </div>
  )
}

export function WhatIfBox({ strategy, symbol }: { strategy: string; symbol: string }) {
  const [open, setOpen] = useState(false)
  const g = strategyGuide(strategy)
  if (!open) {
    return (
      <button type="button" title={NOVICE.whatIf} onClick={e => { e.stopPropagation(); setOpen(true) }} style={{ fontSize: 9, color: '#a855f7', background: 'none', border: 'none', cursor: 'help', padding: 0, marginTop: 6 }}>
        ▸ What if the stock moves? ⓘ
      </button>
    )
  }
  return (
    <div onClick={e => e.stopPropagation()} style={{ marginTop: 8, padding: 9, borderRadius: 8, background: 'rgba(168,85,247,.08)', border: '1px solid rgba(168,85,247,.25)', fontSize: 10, color: TEXT2, lineHeight: 1.5 }}>
      <div style={{ fontWeight: 800, color: '#d8b4fe', marginBottom: 4 }}>{symbol} — if / then</div>
      <div><b style={{ color: GREEN }}>Works:</b> {g.win}</div>
      <div style={{ marginTop: 4 }}><b style={{ color: '#f59e0b' }}>Hurts:</b> {g.lose}</div>
      <div style={{ marginTop: 4 }}><b style={{ color: MUTED }}>Watch:</b> {g.watch}</div>
      <button type="button" onClick={() => setOpen(false)} style={{ fontSize: 9, color: MUTED, background: 'none', border: 'none', cursor: 'pointer', marginTop: 6, padding: 0 }}>▾ Hide</button>
    </div>
  )
}
import { useState } from 'react'
import { strategyGuide } from '../lib/optionsNovice'
import {
  buildOptionEducation,
  buildStockMoveScenarios,
  explainAdviceLabel,
  NOVICE_GLOSSARY,
  OPEN_OPTIONS_INTRO,
  type EducationCard,
} from '../lib/optionsEducation'
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
            <summary style={{ fontSize: 10, fontWeight: 800, color: MUTED, cursor: 'pointer' }}>Glossary ({NOVICE_GLOSSARY.length} terms)</summary>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 8, marginTop: 10 }}>
              {NOVICE_GLOSSARY.map(g => (
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

export function BeginnerSummaryRow({ card }: { card: EducationCard }) {
  const edu = buildOptionEducation(card)
  return (
    <div
      title="Plain-English one-line summary for new operators"
      style={{
        marginTop: 8,
        padding: '7px 9px',
        borderRadius: 8,
        background: 'rgba(96,165,250,.08)',
        border: '1px solid rgba(96,165,250,.22)',
        fontSize: 10,
        color: TEXT2,
        lineHeight: 1.5,
        cursor: 'help',
      }}
    >
      <b style={{ color: '#93c5fd' }}>Beginner view:</b> {edu.beginnerSummary.replace(/^Beginner view:\s*/i, '')}
    </div>
  )
}

function EduSection({ title, body }: { title: string; body: React.ReactNode }) {
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontSize: 10, fontWeight: 800, color: '#93c5fd', marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 10, color: TEXT2, lineHeight: 1.55, whiteSpace: 'pre-wrap' }}>{body}</div>
    </div>
  )
}

export function ExplainTradePanel({ card }: { card: EducationCard }) {
  const [open, setOpen] = useState(false)
  const edu = buildOptionEducation(card)
  if (!open) {
    return (
      <button
        type="button"
        title="Plain-English education — advisory review only, not trade instructions"
        onClick={e => { e.stopPropagation(); setOpen(true) }}
        style={{ fontSize: 9, color: '#60a5fa', background: 'none', border: 'none', cursor: 'help', padding: 0, marginTop: 8, fontWeight: 700 }}
      >
        ▸ Explain this trade ⓘ
      </button>
    )
  }
  return (
    <div
      onClick={e => e.stopPropagation()}
      style={{
        marginTop: 8,
        padding: 11,
        borderRadius: 8,
        background: 'rgba(96,165,250,.06)',
        border: '1px solid rgba(96,165,250,.2)',
        fontSize: 10,
        color: TEXT2,
        lineHeight: 1.55,
      }}
    >
      <div style={{ fontWeight: 900, color: '#bfdbfe', fontSize: 11, marginBottom: 6 }}>{edu.title}</div>
      <EduSection title="1. What type of trade is this?" body={edu.sections.tradeType} />
      <EduSection title="2. What am I buying or selling?" body={edu.sections.buyingSelling} />
      <EduSection title="3. Why would someone use this?" body={edu.sections.whyUse} />
      <EduSection title="4. How can it make money?" body={edu.sections.howMakeMoney} />
      <EduSection title="5. How can it lose money?" body={edu.sections.howLoseMoney} />
      <EduSection title="6. What should I monitor?" body={edu.sections.whatToMonitor} />
      <div style={{ marginTop: 10 }}>
        <div style={{ fontSize: 10, fontWeight: 800, color: '#93c5fd', marginBottom: 4 }}>7. What do these numbers mean?</div>
        <div style={{ fontSize: 10, color: TEXT2, lineHeight: 1.55 }}>{edu.sections.numbersMean}</div>
        <ul style={{ margin: '6px 0 0', paddingLeft: 16, fontSize: 9.5, color: MUTED }}>
          {edu.warningSigns.map(w => <li key={w}>{w}</li>)}
        </ul>
      </div>
      <EduSection title="8. Paper / live status" body={edu.sections.paperLive} />
      <details style={{ marginTop: 10 }}>
        <summary style={{ fontSize: 9.5, fontWeight: 800, color: MUTED, cursor: 'pointer' }}>What to monitor after entry (checklist)</summary>
        <ul style={{ margin: '6px 0 0', paddingLeft: 16, fontSize: 9.5, color: TEXT2 }}>
          {edu.monitorChecklist.map(item => <li key={item}>{item}</li>)}
        </ul>
      </details>
      <details style={{ marginTop: 8 }}>
        <summary style={{ fontSize: 9.5, fontWeight: 800, color: MUTED, cursor: 'pointer' }}>Glossary on this card</summary>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 6, marginTop: 8 }}>
          {edu.noviceGlossary.slice(0, 10).map(g => (
            <div key={g.term} style={{ fontSize: 9.5, color: TEXT2 }}>
              <b style={{ color: 'var(--text1)' }}>{g.term}</b> — {g.def}
            </div>
          ))}
        </div>
      </details>
      <button type="button" onClick={() => setOpen(false)} style={{ fontSize: 9, color: MUTED, background: 'none', border: 'none', cursor: 'pointer', marginTop: 8, padding: 0 }}>▾ Hide explanation</button>
    </div>
  )
}

export function OpenOptionsIntroBanner() {
  const [open, setOpen] = useState(true)
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} style={{ fontSize: 10, color: MUTED, background: 'none', border: 'none', cursor: 'pointer', marginBottom: 10, padding: 0 }}>
        ▸ Show open-options monitoring guide
      </button>
    )
  }
  return (
    <div style={{ ...panel, marginBottom: 12, borderLeft: '4px solid #a855f7', cursor: 'help' }} title={OPEN_OPTIONS_INTRO}>
      <div style={{ fontSize: 11, fontWeight: 800, color: '#d8b4fe', marginBottom: 6 }}>Open options — what am I looking at? ⓘ</div>
      <div style={{ fontSize: 10.5, color: TEXT2, lineHeight: 1.55 }}>{OPEN_OPTIONS_INTRO}</div>
      <button type="button" onClick={() => setOpen(false)} style={{ fontSize: 9, color: MUTED, background: 'none', border: 'none', cursor: 'pointer', marginTop: 6, padding: 0 }}>Hide</button>
    </div>
  )
}

export function OpenPositionEducation({ position }: { position: EducationCard & { advice_label?: string } }) {
  const edu = buildOptionEducation(position)
  const sym = position.symbol || position.underlying || '—'
  return (
    <div style={{ marginTop: 8, padding: 9, borderRadius: 8, background: 'rgba(168,85,247,.06)', border: '1px solid rgba(168,85,247,.2)', fontSize: 10, color: TEXT2, lineHeight: 1.5 }}>
      <div style={{ fontWeight: 800, color: '#d8b4fe', marginBottom: 4 }}>Paper position review — {sym}</div>
      <div><b>Entry:</b> {position.entry_fill_price != null ? `$${position.entry_fill_price.toFixed(2)}` : '—'} · <b>Mark:</b> {position.mark != null ? `$${position.mark.toFixed(2)}` : '—'} · <b>P/L:</b> {position.unrealized_pnl != null ? `$${position.unrealized_pnl.toFixed(0)}` : '—'}</div>
      {position.advice_label && (
        <div style={{ marginTop: 4 }}>
          <b>Monitor advice:</b> {position.advice_label} — {explainAdviceLabel(position.advice_label)}
        </div>
      )}
      <ul style={{ margin: '6px 0 0', paddingLeft: 16, fontSize: 9.5 }}>
        {edu.monitorChecklist.slice(0, 6).map(item => <li key={item}>{item}</li>)}
      </ul>
    </div>
  )
}

export function WhatIfBox({ strategy, symbol, card }: { strategy: string; symbol: string; card?: EducationCard }) {
  const [open, setOpen] = useState(false)
  const g = strategyGuide(strategy)
  const scenarios = buildStockMoveScenarios(strategy, symbol)
  if (!open) {
    return (
      <button type="button" title={NOVICE.whatIf} onClick={e => { e.stopPropagation(); setOpen(true) }} style={{ fontSize: 9, color: '#a855f7', background: 'none', border: 'none', cursor: 'help', padding: 0, marginTop: 6 }}>
        ▸ What if the stock moves? ⓘ
      </button>
    )
  }
  return (
    <div onClick={e => e.stopPropagation()} style={{ marginTop: 8, padding: 9, borderRadius: 8, background: 'rgba(168,85,247,.08)', border: '1px solid rgba(168,85,247,.25)', fontSize: 10, color: TEXT2, lineHeight: 1.5 }}>
      <div style={{ fontWeight: 800, color: '#d8b4fe', marginBottom: 4 }}>{symbol} — if the stock moves</div>
      {scenarios.map(block => (
        <div key={block.heading} style={{ marginTop: 6 }}>
          <b style={{ color: block.heading.includes('rises') ? GREEN : block.heading.includes('falls') ? '#f59e0b' : MUTED }}>{block.heading}</b>
          <ul style={{ margin: '3px 0 0', paddingLeft: 16 }}>
            {block.bullets.map(b => <li key={b}>{b}</li>)}
          </ul>
        </div>
      ))}
      <div style={{ marginTop: 8, fontSize: 9.5, color: MUTED }}>
        <b>Quick summary:</b> ✓ {g.win} · ⚠ {g.lose}
      </div>
      <button type="button" onClick={() => setOpen(false)} style={{ fontSize: 9, color: MUTED, background: 'none', border: 'none', cursor: 'pointer', marginTop: 6, padding: 0 }}>▾ Hide</button>
    </div>
  )
}
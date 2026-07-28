import { useEffect, useMemo, useRef, useState } from 'react'

/**
 * SETUPS & STRATEGY RULES — read-only, registry-driven strategy modal for the scalp taxonomy.
 * Educational only: contains NO buy/submit/approve/2FA/broker/live-action control. Everything it shows
 * comes from the backend setup registry (/api/v3/active-trader/scalp/setups). A lane is not a setup.
 */

export type Setup = {
  setup_id: string; display_label: string; family: string; version: string; enabled: boolean
  operating_state: string; supported_sessions: string[]; active_window_et: string
  required_data_tier: string; best_conditions: string; entry_rule: string; invalidation_rule: string
  stop_rule: string; target_rule: string; exit_if_wrong: string; required_inputs?: string[]
  optional_confirmations?: string[]; source_attribution?: string[]; rule_provenance?: string
  source_rule_notes?: string; engine_adaptations?: string
}

const FILTERS = ['ALL', 'PREMARKET', 'REGULAR', 'AVAILABLE NOW', 'DATA UNAVAILABLE'] as const
type Filter = typeof FILTERS[number]

// v1 availability heuristic from the current data plane: T0 present, T1 dormant, T2 scaffold-only.
function available(tier: string): boolean { return tier === 'T0' }

function chip(text: string, tone: 'green' | 'red' | 'amber' | 'muted' = 'muted') {
  const c = tone === 'green' ? 'var(--green)' : tone === 'red' ? 'var(--red)' : tone === 'amber' ? 'var(--amber)' : 'var(--text3)'
  return (
    <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.04em', color: c,
      border: `1px solid ${c}`, borderRadius: 3, padding: '1px 6px', whiteSpace: 'nowrap' }}>{text}</span>
  )
}

function Field({ label, value }: { label: string; value?: string }) {
  if (!value) return null
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.06em', color: 'var(--text3)' }}>{label}</div>
      <div style={{ fontSize: 11.5, color: 'var(--text1)', lineHeight: 1.4 }}>{value}</div>
    </div>
  )
}

export default function ScalpStrategyModal({ open, onClose, setups, registryHash, preselectId }: {
  open: boolean; onClose: () => void; setups: Setup[]; registryHash?: string; preselectId?: string | null
}) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const openerRef = useRef<Element | null>(null)
  const [filter, setFilter] = useState<Filter>('ALL')
  const [selectedId, setSelectedId] = useState<string | null>(preselectId ?? null)
  const [compare, setCompare] = useState(false)

  useEffect(() => { if (open) { setSelectedId(preselectId ?? null); setCompare(false) } }, [open, preselectId])

  // focus management: remember opener, focus dialog, trap focus, restore on close
  useEffect(() => {
    if (!open) return
    openerRef.current = document.activeElement
    const el = dialogRef.current
    el?.focus()
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.stopPropagation(); onClose(); return }
      if (e.key === 'Tab' && el) {
        const f = el.querySelectorAll<HTMLElement>('button, [href], input, [tabindex]:not([tabindex="-1"])')
        if (!f.length) return
        const first = f[0], last = f[f.length - 1]
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      ;(openerRef.current as HTMLElement | null)?.focus?.()
    }
  }, [open, onClose])

  const filtered = useMemo(() => setups.filter(s => {
    if (filter === 'ALL') return true
    if (filter === 'PREMARKET') return s.supported_sessions?.includes('PREMARKET')
    if (filter === 'REGULAR') return s.supported_sessions?.includes('REGULAR')
    if (filter === 'AVAILABLE NOW') return available(s.required_data_tier)
    if (filter === 'DATA UNAVAILABLE') return !available(s.required_data_tier)
    return true
  }), [setups, filter])

  const selected = useMemo(() => setups.find(s => s.setup_id === selectedId) || null, [setups, selectedId])
  const comparable = useMemo(() => setups.filter(s => s.setup_id !== 'SCALP_IGNITION_BREAKOUT_V1' || true), [setups])

  if (!open) return null

  return (
    <div role="presentation" onClick={onClose}
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)', zIndex: 1000,
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="scalp-strategy-title"
        tabIndex={-1} onClick={e => e.stopPropagation()}
        style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8,
          width: 'min(920px, 100%)', maxHeight: '90vh', display: 'flex', flexDirection: 'column',
          outline: 'none', overflow: 'hidden' }}>
        {/* sticky header */}
        <div style={{ position: 'sticky', top: 0, background: 'var(--bg1)', borderBottom: '1px solid var(--border)',
          padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span id="scalp-strategy-title" style={{ fontSize: 13, fontWeight: 900, color: 'var(--text0)', letterSpacing: '.04em' }}>
              SETUPS &amp; STRATEGY RULES
            </span>
            <span style={{ fontSize: 10, color: 'var(--text3)' }}>
              Read-only · SHADOW / MANUAL PAPER ONLY · deterministic named setups (a lane is not a setup)
            </span>
          </div>
          <button onClick={() => setCompare(c => !c)} style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 800,
            padding: '3px 9px', background: 'transparent', color: 'var(--text2)', border: '1px solid var(--border)',
            borderRadius: 4, cursor: 'pointer' }}>{compare ? 'List view' : 'Compare setups'}</button>
          <button aria-label="Close" onClick={onClose} style={{ fontSize: 14, fontWeight: 800, lineHeight: 1,
            padding: '3px 9px', background: 'transparent', color: 'var(--text2)', border: '1px solid var(--border)',
            borderRadius: 4, cursor: 'pointer' }}>✕</button>
        </div>

        {/* filters */}
        <div style={{ display: 'flex', gap: 6, padding: '8px 16px', flexWrap: 'wrap', borderBottom: '1px solid var(--border)' }}>
          {FILTERS.map(f => (
            <button key={f} onClick={() => setFilter(f)} aria-pressed={filter === f}
              style={{ fontSize: 10, fontWeight: 800, letterSpacing: '.04em', padding: '2px 8px', borderRadius: 3,
                cursor: 'pointer', background: filter === f ? 'var(--text2)' : 'transparent',
                color: filter === f ? 'var(--bg0)' : 'var(--text3)', border: '1px solid var(--border)' }}>{f}</button>
          ))}
        </div>

        {/* scrollable body */}
        <div style={{ overflowY: 'auto', overflowX: 'hidden', padding: 16, flex: 1 }}>
          {compare ? (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 640, fontSize: 10.5 }}>
                <thead>
                  <tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
                    {['Setup', 'Session', 'Window ET', 'Tier', 'Entry rule', 'Invalidation'].map(h => (
                      <th key={h} style={{ borderBottom: '1px solid var(--border)', padding: '4px 8px', fontWeight: 800 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {comparable.map(s => (
                    <tr key={s.setup_id} style={{ verticalAlign: 'top' }}>
                      <td style={{ padding: '5px 8px', fontWeight: 800, color: 'var(--text0)' }}>{s.display_label}</td>
                      <td style={{ padding: '5px 8px', color: 'var(--text2)' }}>{(s.supported_sessions || []).join(', ')}</td>
                      <td style={{ padding: '5px 8px', color: 'var(--text2)' }}>{s.active_window_et}</td>
                      <td style={{ padding: '5px 8px' }}>{chip(s.required_data_tier, available(s.required_data_tier) ? 'green' : 'amber')}</td>
                      <td style={{ padding: '5px 8px', color: 'var(--text1)' }}>{s.entry_rule}</td>
                      <td style={{ padding: '5px 8px', color: 'var(--text1)' }}>{s.invalidation_rule}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(180px, 240px) 1fr', gap: 14 }}>
              {/* setup list */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
                {filtered.map(s => (
                  <button key={s.setup_id} onClick={() => setSelectedId(s.setup_id)}
                    aria-pressed={selectedId === s.setup_id}
                    style={{ textAlign: 'left', padding: '7px 9px', borderRadius: 5, cursor: 'pointer',
                      background: selectedId === s.setup_id ? 'var(--bg2)' : 'transparent',
                      border: `1px solid ${selectedId === s.setup_id ? 'var(--text3)' : 'var(--border)'}` }}>
                    <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text0)' }}>{s.display_label}</div>
                    <div style={{ display: 'flex', gap: 5, marginTop: 3, flexWrap: 'wrap' }}>
                      {chip(s.supported_sessions?.[0] === 'PREMARKET' ? 'PREMARKET' : 'REGULAR')}
                      {chip(s.required_data_tier, available(s.required_data_tier) ? 'green' : 'amber')}
                    </div>
                  </button>
                ))}
                {!filtered.length && <div style={{ fontSize: 10, color: 'var(--text3)' }}>No setups in this filter.</div>}
              </div>

              {/* detail */}
              <div style={{ minWidth: 0 }}>
                {!selected ? (
                  <div style={{ fontSize: 11, color: 'var(--text3)' }}>Select a setup to view its exact rules.</div>
                ) : (
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
                      <span style={{ fontSize: 14, fontWeight: 900, color: 'var(--text0)' }}>{selected.display_label}</span>
                      {chip(`v${selected.version}`)}
                      {chip(selected.operating_state, 'amber')}
                      {chip('MANUAL PAPER ONLY', 'red')}
                      {chip(available(selected.required_data_tier) ? 'AVAILABLE NOW' : 'DATA UNAVAILABLE',
                        available(selected.required_data_tier) ? 'green' : 'amber')}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>
                      {selected.setup_id} · {selected.family} · {(selected.supported_sessions || []).join(', ')} · {selected.active_window_et} ET · tier {selected.required_data_tier}
                    </div>
                    <Field label="BEST CONDITIONS" value={selected.best_conditions} />
                    <Field label="ENTRY RULE" value={selected.entry_rule} />
                    <Field label="INVALIDATION" value={selected.invalidation_rule} />
                    <Field label="STOP" value={selected.stop_rule} />
                    <Field label="TARGET" value={selected.target_rule} />
                    <Field label="EXIT IF WRONG" value={selected.exit_if_wrong} />
                    <Field label="REQUIRED INPUTS" value={(selected.required_inputs || []).join(', ')} />
                    <Field label="CONFIRMATION OVERLAYS" value={(selected.optional_confirmations || []).join(', ')} />
                    <Field label="RULE PROVENANCE" value={selected.rule_provenance} />
                    <Field label="SOURCE" value={(selected.source_attribution || []).join(' · ')} />
                    <Field label="SOURCE NOTES" value={selected.source_rule_notes} />
                    <Field label="TRADE AI ADAPTATION" value={selected.engine_adaptations} />
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <div style={{ borderTop: '1px solid var(--border)', padding: '6px 16px', fontSize: 10, color: 'var(--text3)' }}>
          Educational / read-only. No order, submit, approval, 2FA, or broker control. Registry {registryHash || '—'}.
          Universal execution-quality gate (liquidity/spread/slippage) can veto any setup.
        </div>
      </div>
    </div>
  )
}

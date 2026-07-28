import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import ScalpStrategyModal, { type Setup } from './ScalpStrategyModal'

/**
 * Scalp setup taxonomy panel for the Trading hub Scalp tab. Read-only, SHADOW / MANUAL PAPER ONLY.
 * Renders the SETUPS & STRATEGY RULES button (opens the registry-driven modal) and recent setup-tagged
 * events with prominent setup chips + MULTI-SETUP. Clicking a setup chip opens the modal preselected.
 * Contains NO order/submit/approve/2FA/broker control.
 */

function setupChip(label: string, onClick?: () => void, tone: 'green' | 'amber' | 'muted' = 'green') {
  const c = tone === 'green' ? 'var(--green)' : tone === 'amber' ? 'var(--amber)' : 'var(--text3)'
  return (
    <button key={label} onClick={onClick} title="Open strategy rules for this setup"
      style={{ fontSize: 10, fontWeight: 900, letterSpacing: '.04em', color: c, border: `1px solid ${c}`,
        borderRadius: 3, padding: '1px 7px', background: 'transparent', cursor: onClick ? 'pointer' : 'default',
        whiteSpace: 'nowrap' }}>{label}</button>
  )
}

export default function ScalpSetupsPanel() {
  const { data: reg } = useApi<any>('/api/v3/active-trader/scalp/setups', 300_000, { enabled: true })
  const { data: evData } = useApi<any>('/api/v3/active-trader/scalp/setup-events?limit=40', 60_000, { enabled: true })
  const [open, setOpen] = useState(false)
  const [preselect, setPreselect] = useState<string | null>(null)

  const setups: Setup[] = reg?.setup_registry?.setups ?? []
  const registryHash: string | undefined = reg?.setup_registry?.registry_hash
  const byLabel = useMemo(() => {
    const m: Record<string, string> = {}
    setups.forEach(s => { m[s.display_label] = s.setup_id })
    return m
  }, [setups])
  const events: any[] = evData?.events ?? []

  function openFor(label: string) {
    setPreselect(byLabel[label] ?? null); setOpen(true)
  }

  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 12, marginBottom: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)' }}>Scalp Setups — Named Taxonomy</div>
        <span style={{ fontSize: 10, fontWeight: 800, color: 'var(--amber)', border: '1px solid var(--amber)', borderRadius: 3, padding: '1px 6px' }}>SHADOW · MANUAL PAPER ONLY</span>
        <button onClick={() => { setPreselect(null); setOpen(true) }}
          style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 800, letterSpacing: '.04em', padding: '4px 10px',
            background: 'transparent', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: 5, cursor: 'pointer' }}>
          SETUPS &amp; STRATEGY RULES
        </button>
      </div>
      <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>
        Every FIRED signal is tagged with its deterministic named setup. A lane (IGN_60 / IGN_ACCEL / TRIGGER) is not a setup.
        These are advisory — no order is placed.
      </div>

      {!events.length ? (
        <div style={{ fontSize: 10.5, color: 'var(--text3)' }}>
          No setup-tagged events yet {evData?.source === 'unavailable' ? '(store not initialized — SHADOW)' : '(SHADOW)'}.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 560, fontSize: 10.5 }}>
            <thead>
              <tr style={{ color: 'var(--text3)', textAlign: 'left' }}>
                {['Symbol', 'Setup(s)', 'Session', 'Lane', 'State', 'Fired'].map(h => (
                  <th key={h} style={{ borderBottom: '1px solid var(--border)', padding: '4px 8px', fontWeight: 800 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {events.map((e, i) => {
                const labels: string[] = e.matched_setup_labels || (e.primary_setup_label ? [e.primary_setup_label] : [])
                const multi = labels.length > 1
                return (
                  <tr key={i} style={{ verticalAlign: 'top' }}>
                    <td style={{ padding: '5px 8px', fontWeight: 800, color: 'var(--text0)' }}>{e.symbol}</td>
                    <td style={{ padding: '5px 8px' }}>
                      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
                        {e.primary_setup_label && setupChip(e.primary_setup_label, () => openFor(e.primary_setup_label))}
                        {multi && setupChip('MULTI-SETUP', () => setOpen(true), 'amber')}
                        {labels.filter(l => l !== e.primary_setup_label).map(l => setupChip(l, () => openFor(l), 'muted'))}
                      </div>
                    </td>
                    <td style={{ padding: '5px 8px', color: 'var(--text2)' }}>{e.market_session || '—'}</td>
                    <td style={{ padding: '5px 8px', color: 'var(--text3)' }}>{e.lane}</td>
                    <td style={{ padding: '5px 8px', color: e.setup_state === 'FIRED' ? 'var(--green)' : 'var(--text2)', fontWeight: 700 }}>{e.setup_state || '—'}</td>
                    <td style={{ padding: '5px 8px', color: 'var(--text3)' }}>{(e.fired_at || '').slice(11, 19) || '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <ScalpStrategyModal open={open} onClose={() => setOpen(false)} setups={setups}
        registryHash={registryHash} preselectId={preselect} />
    </div>
  )
}

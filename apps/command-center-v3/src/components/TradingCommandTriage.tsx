/**
 * WP-T3 — sticky Trading NOW command triage strip.
 * Chips deep-link into the right tab; never auto-executes.
 */
import type { CSSProperties } from 'react'
import type { TriageChip, TriageTone } from '../lib/tradingCommandTriage'
import type { TradingTab } from '../lib/tradingDeepLink'

type Props = {
  chips: TriageChip[]
  onNavigate: (tab: TradingTab, params?: Record<string, string>) => void
  loading?: boolean
}

function toneColor(tone: TriageTone): string {
  // CSS variables only (design-token guard) — semantic via opacity, not raw hex
  if (tone === 'critical' || tone === 'warn' || tone === 'action') return 'var(--text0)'
  if (tone === 'ok') return 'var(--text2)'
  return 'var(--text1)'
}

function toneBorder(tone: TriageTone): string {
  if (tone === 'critical') return '1px solid var(--border)'
  if (tone === 'action') return '1px solid var(--text1)'
  return '1px solid var(--border)'
}

export default function TradingCommandTriage({ chips, onNavigate, loading }: Props) {
  const wrap: CSSProperties = {
    display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center',
    marginBottom: 12, padding: '8px 12px',
    background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8,
    position: 'sticky', top: 0, zIndex: 15,
  }
  const chipBtn = (tone: TriageTone, active = false): CSSProperties => ({
    fontSize: 10, fontWeight: 800, padding: '5px 10px', borderRadius: 5, cursor: 'pointer',
    border: toneBorder(tone),
    background: active ? 'var(--bg2)' : 'var(--bg2)',
    color: toneColor(tone),
    textAlign: 'left' as const,
  })

  if (loading && !chips.length) {
    return (
      <div data-testid="trading-command-triage" style={wrap}>
        <span style={{ fontSize: 10, fontWeight: 800, color: 'var(--text2)' }}>NOW</span>
        <span style={{ fontSize: 10, color: 'var(--text3)' }}>Loading triage…</span>
      </div>
    )
  }

  if (!chips.length) return null

  return (
    <div data-testid="trading-command-triage" style={wrap}>
      <span style={{ fontSize: 10, fontWeight: 800, color: 'var(--text2)', letterSpacing: 0.3 }} title="Command triage — advisory navigation only">
        NOW
      </span>
      {chips.map(chip => (
        <button
          key={chip.id}
          type="button"
          data-testid={`triage-chip-${chip.id}`}
          title={`${chip.detail}${chip.samples?.length ? `\n${chip.samples.join(', ')}` : ''}\n→ ${chip.tab}`}
          onClick={() => {
            const params = { ...(chip.params || {}) }
            // Focus first sample symbol when landing Open Trades
            if (chip.tab === 'Open Trades' && chip.samples?.[0] && !params.symbol) {
              params.symbol = chip.samples[0]
            }
            onNavigate(chip.tab, params)
          }}
          style={chipBtn(chip.tone)}
        >
          <span style={{ color: 'var(--text3)', marginRight: 6 }}>{chip.label}</span>
          {chip.count > 0 && <b>{chip.count}</b>}
          {chip.samples && chip.samples.length > 0 && (
            <span style={{ marginLeft: 6, color: 'var(--text3)', fontWeight: 600 }}>
              {chip.samples.slice(0, 3).join(' · ')}
            </span>
          )}
        </button>
      ))}
      <span style={{ fontSize: 10, color: 'var(--text3)', marginLeft: 'auto' }}>
        click → tab · no auto-submit
      </span>
    </div>
  )
}

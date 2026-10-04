import { useState } from 'react'
import { useApi } from '../../hooks/useApi'
import { RADIUS } from '../../lib/designTokens'

type GateRow = {
  gate: string
  horizon_sessions: number
  blocks: number
  measured: number
  pending: number
  stale_identical: number
  median_return_pct: number | null
  mean_return_pct: number | null
  cost_good_moves_blocked: number
  benefit_losers_avoided: number
}
type Horizon = { status?: string; return_pct?: number | null; relative_pct?: number | null; reason?: string }
type Row = { block_id: string; gate: string; symbol: string; day: string; rechecks?: number; horizons?: Record<string, Horizon> }
type Payload = { ok?: boolean; status?: string; summary?: GateRow[]; rows?: Row[]; row_count?: number; source_as_of?: string | null; error?: string }

const HORIZONS = [1, 5, 20]
const SLOW_POLL_MS = 300_000

function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`
}

function tone(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'var(--text3)'
  return v > 0 ? 'var(--green)' : v < 0 ? 'var(--red)' : 'var(--text2)'
}

/** What blocked ideas did afterwards, by gate (GET /api/v3/cio/counterfactuals).
 * Observation only: a gate that blocks mostly losers is earning its keep. */
export default function CioCounterfactualPanel() {
  const [horizon, setHorizon] = useState(5)
  const { data, loading, error } = useApi<Payload>('/api/v3/cio/counterfactuals?limit=40', SLOW_POLL_MS)
  const gates = (data?.summary || []).filter((g) => g.horizon_sessions === horizon && g.blocks > 0)
  const cell = { padding: '6px 8px', borderBottom: '1px solid var(--border-subtle)', fontSize: 11, textAlign: 'right' as const }

  return (
    <section data-testid="cio-counterfactuals" style={{ display: 'grid', gap: 12 }}>
      <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 14, background: 'var(--bg2)' }}>
        <div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 800, letterSpacing: '.6px' }}>BLOCKED IDEAS · WHAT HAPPENED NEXT</div>
        <div style={{ marginTop: 5, color: 'var(--text1)', fontSize: 12, lineHeight: 1.5 }}>
          Each idea a gate blocked, counted once per symbol and day, with its price change 1, 5 and 20 sessions later.
          "Good moves blocked" is the gate's cost; "losers avoided" is its benefit. Observation only.
        </div>
        <div style={{ marginTop: 8, color: 'var(--text3)', fontSize: 11 }}>
          Source as of {data?.source_as_of ? data.source_as_of.replace('T', ' ').slice(0, 16) : 'UNKNOWN'} · {data?.row_count ?? 0} blocked ideas
        </div>
      </div>

      {loading && !data && <div style={{ color: 'var(--text2)' }}>Loading blocked ideas…</div>}
      {error && <div style={{ color: 'var(--amber)' }}>Blocked-idea ledger unavailable: {String(error)}</div>}
      {data?.status === 'NO_LEDGER_YET' && <div style={{ color: 'var(--text2)' }}>The ledger has not run yet. Its first daily run fills this view.</div>}

      {gates.length > 0 && (
        <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 12, background: 'var(--bg1)' }}>
          <div role="tablist" aria-label="Horizon" style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
            {HORIZONS.map((h) => (
              <button key={h} type="button" role="tab" aria-selected={horizon === h} onClick={() => setHorizon(h)}
                style={{ minHeight: 32, padding: '4px 10px', borderRadius: RADIUS.sm, border: '1px solid var(--border)', background: horizon === h ? 'var(--bg3)' : 'transparent', color: 'var(--text1)', fontSize: 11, cursor: 'pointer' }}>
                {h} session{h === 1 ? '' : 's'}
              </button>
            ))}
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', width: '100%', fontVariantNumeric: 'tabular-nums' }}>
              <thead>
                <tr>
                  {['Gate', 'Blocked', 'Measured', 'Median', 'Good moves blocked', 'Losers avoided', 'Pending'].map((h, i) => (
                    <th key={h} style={{ ...cell, textAlign: i === 0 ? 'left' : 'right', color: 'var(--text3)', fontWeight: 700 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {gates.map((g) => (
                  <tr key={g.gate} data-testid="cio-counterfactual-gate">
                    <td style={{ ...cell, textAlign: 'left', color: 'var(--text1)' }}>{g.gate.replace(':', ' · ')}</td>
                    <td style={cell}>{g.blocks}</td>
                    <td style={cell}>{g.measured}</td>
                    <td style={{ ...cell, color: tone(g.median_return_pct) }}>{pct(g.median_return_pct)}</td>
                    <td style={{ ...cell, color: g.cost_good_moves_blocked ? 'var(--amber)' : 'var(--text2)' }}>{g.cost_good_moves_blocked}</td>
                    <td style={{ ...cell, color: g.benefit_losers_avoided ? 'var(--green)' : 'var(--text2)' }}>{g.benefit_losers_avoided}</td>
                    <td style={{ ...cell, color: 'var(--text3)' }}>{g.pending + g.stale_identical}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {(data?.rows || []).length > 0 && (
        <div style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 12, background: 'var(--bg1)', display: 'grid', gap: 4 }}>
          <div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 800, letterSpacing: '.6px' }}>LATEST BLOCKED IDEAS</div>
          {(data?.rows || []).slice(0, 20).map((r) => {
            const h = r.horizons?.[String(horizon)]
            return (
              <div key={r.block_id} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', fontSize: 11, borderTop: '1px solid var(--border-subtle)', paddingTop: 4 }}>
                <span style={{ fontWeight: 800, color: 'var(--text1)', minWidth: 52 }}>{r.symbol}</span>
                <span style={{ color: 'var(--text2)' }}>{r.gate.replace(':', ' · ')}</span>
                <span style={{ color: 'var(--text3)' }}>{r.day}{r.rechecks && r.rechecks > 1 ? ` · ${r.rechecks} checks` : ''}</span>
                <span style={{ marginLeft: 'auto', color: h?.status === 'MEASURED' ? tone(h.return_pct) : 'var(--text3)' }}>
                  {h?.status === 'MEASURED' ? pct(h.return_pct) : h?.status === 'STALE_IDENTICAL' ? 'stale price' : 'pending'}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

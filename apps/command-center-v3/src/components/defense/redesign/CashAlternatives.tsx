/** Cash Alternatives card — Defense Desk v10.
 *
 * Renders the top-3 cash deployment alternatives in a compact card with an
 * expandable full ranking table. Advisory only; nothing routes.
 */
import { useEffect, useState, type ReactNode } from 'react'
import { S, panel, ph, mono, chip, th, thL, td, tdL } from '../../../lib/defenseRedesign'
import { Val, Unk } from './Val'

interface Candidate {
  symbol: string
  name: string
  category: string
  total_score: number
  scores: { yield: number; preservation: number; liquidity: number; tax: number }
  thesis?: string
  thesis_lane?: string
  price?: { price?: number; change_pct?: number } | null
  yield_data?: { div_yield?: number } | null
}

interface CashData {
  candidates: Candidate[]
  top3: Candidate[]
  risk_free_rate?: number
  note?: string
  generated_at?: string | null
  error?: string
}

const CAT_CHIP: Record<string, string> = {
  low_vol: 'LOW VOL', dividend: 'DIVIDEND', bond: 'BOND',
  money_market: 'MM', balanced: 'BALANCED', covered_call: 'CC INC',
}

const catTone = (cat: string): 'g' | 'n' | 'b' | 'a' | 'r' => {
  if (cat === 'money_market') return 'g'
  if (cat === 'bond') return 'b'
  if (cat === 'low_vol') return 'n'
  return 'n'
}

function ageShort(iso?: string | null): string {
  if (!iso) return 'never'
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (m < 60) return `${m}m`
  if (m < 48 * 60) return `${Math.round(m / 60)}h`
  return `${Math.round(m / 1440)}d`
}

export default function CashAlternatives({ data, onRefresh }: { data: CashData | null; onRefresh?: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const candidates = data?.candidates || []
  const top3 = data?.top3 || candidates.slice(0, 3)
  const rf = data?.risk_free_rate

  return (
    <section style={{ ...panel, marginTop: 14 }}>
      <div style={{ ...ph, background: S.sunk }}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: S.t0 }}>Cash Alternatives</h2>
        <span style={{ color: S.t2, fontSize: 12 }}>
          {rf ? `vs ~${rf}% risk-free · ` : ''}advisory only — nothing routes
        </span>
        {data?.generated_at ? (
          <span style={{ ...chip('n'), marginLeft: 'auto' }} title={`snapshot at ${data.generated_at}`}>
            {ageShort(data.generated_at)}
          </span>
        ) : null}
      </div>

      {top3.length === 0 ? (
        <div style={{ padding: '13px 16px', color: S.t3, fontSize: 12 }}>
          Cash alternatives have not been screened yet. Run <code>scripts/defense_cash_alternatives.py</code> to populate the vehicle universe.
        </div>
      ) : (
        <>
          {/* Top-3 compact summary */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 1, background: S.line }}>
            {top3.map((c, i) => (
              <div key={c.symbol} style={{ background: S.bg1, padding: '13px 16px' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 7, marginBottom: 5 }}>
                  <span style={chip(catTone(c.category))}>{CAT_CHIP[c.category] || c.category}</span>
                  <strong style={{ fontSize: 15, color: S.t0 }}>{c.symbol}</strong>
                  <span style={{ ...mono, color: S.t3, fontSize: 11 }}>#{i + 1}</span>
                </div>
                <div style={{ color: S.t2, fontSize: 11, marginBottom: 4 }}>{c.name}</div>
                <div style={{ ...mono, fontSize: 26, color: S.t0, marginBottom: 2 }}>
                  <Val value={c.total_score} suffix="" fmt={v => v.toFixed(0)} reason="score not computed" />
                </div>
                <div style={{ height: 5, borderRadius: 3, background: S.sunk, overflow: 'hidden', marginBottom: 7 }}>
                  <span style={{ display: 'block', height: '100%', width: `${Math.min(100, c.total_score)}%`, background: c.total_score >= 75 ? S.green : c.total_score >= 60 ? S.amber : S.red }} />
                </div>
                <div style={{ display: 'flex', gap: 8, fontSize: 10, color: S.t3, marginBottom: 6 }}>
                  <span title="Yield adequacy">Y {c.scores?.yield ?? '—'}</span>
                  <span title="Capital preservation">P {c.scores?.preservation ?? '—'}</span>
                  <span title="Liquidity">L {c.scores?.liquidity ?? '—'}</span>
                  <span title="Tax efficiency">T {c.scores?.tax ?? '—'}</span>
                </div>
                <div style={{ fontSize: 11, color: S.t2, lineHeight: 1.5 }}>
                  {c.thesis || <Unk reason="no thesis generated" />}
                </div>
                {c.price?.price ? (
                  <div style={{ fontSize: 10, color: S.t3, marginTop: 4 }}>
                    <Val value={c.price.price} reason="no price" />
                    {c.price.change_pct != null ? (
                      <span style={{ color: c.price.change_pct >= 0 ? S.green : S.red }}>
                        {' '}{c.price.change_pct >= 0 ? '+' : ''}{c.price.change_pct}%
                      </span>
                    ) : null}
                    {c.yield_data?.div_yield != null ? (
                      <span style={{ marginLeft: 6 }}>{c.yield_data.div_yield}% yield</span>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ))}
          </div>

          {/* Expandable full ranking */}
          <div style={{ borderTop: `1px solid ${S.line}` }}>
            <button
              onClick={() => setExpanded(e => !e)}
              style={{
                width: '100%', textAlign: 'left', padding: '9px 16px', fontSize: 12,
                color: S.t2, background: 'transparent', border: 'none', cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 6,
              }}
            >
              <span>{expanded ? '▾' : '▸'}</span>
              {expanded ? 'Collapse' : 'Expand'} full ranking ({candidates.length} vehicles)
            </button>
            {expanded && (
              <div style={{ overflowX: 'auto', padding: '0 0 10px' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead><tr>
                    <th style={thL}>Symbol</th><th style={th}>Category</th><th style={th}>Score</th>
                    <th style={th}>Yield</th><th style={th}>Preserv</th><th style={th}>Liq</th>
                    <th style={th}>Tax</th><th style={{ ...thL, paddingLeft: 18 }}>Thesis</th>
                  </tr></thead>
                  <tbody style={mono}>
                    {candidates.map((c, i) => (
                      <tr key={c.symbol}>
                        <td style={{ ...tdL, color: S.t0 }}>
                          {c.symbol}
                          <span style={{ color: S.t3, fontSize: 10, marginLeft: 6 }}>{c.name}</span>
                        </td>
                        <td style={td}>
                          <span style={chip(catTone(c.category))}>{CAT_CHIP[c.category] || c.category}</span>
                        </td>
                        <td style={{ ...td, color: S.t0 }}>{c.total_score}</td>
                        <td style={{ ...td, color: c.scores?.yield >= 60 ? S.green : S.t2 }}>{c.scores?.yield ?? '—'}</td>
                        <td style={{ ...td, color: c.scores?.preservation >= 80 ? S.green : S.t2 }}>{c.scores?.preservation ?? '—'}</td>
                        <td style={{ ...td, color: S.t2 }}>{c.scores?.liquidity ?? '—'}</td>
                        <td style={{ ...td, color: S.t2 }}>{c.scores?.tax ?? '—'}</td>
                        <td style={{ ...tdL, color: S.t2, maxWidth: 300, fontSize: 11 }}>
                          {(c.thesis || '').slice(0, 120)}{(c.thesis || '').length > 120 ? '…' : ''}
                          {c.thesis_lane ? <span style={{ ...chip('n'), marginLeft: 6, fontSize: 10 }}>{c.thesis_lane}</span> : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {data?.note ? (
            <div style={{ padding: '8px 16px', borderTop: `1px solid ${S.line}`, fontSize: 11, color: S.t3 }}>
              {data.note}
            </div>
          ) : null}
        </>
      )}
    </section>
  )
}
